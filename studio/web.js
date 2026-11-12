/* X-Stage Song Studio Web Beta 0.3.0
 * All input audio, lyrics and rendered output stay inside the browser.
 * Only FFmpeg library/wasm code is downloaded from jsDelivr when requested.
 * This page never uploads song files to a network endpoint. */
'use strict';
(function () {
  const $ = (id) => document.getElementById(id);
  const AUDIO = new Set(['mp3', 'm4a', 'wav', 'aac', 'ogg', 'oga', 'flac']);
  const MIDI = new Set(['mid', 'midi', 'kar', 'ncn']);
  const SIDE = new Set(['lrc', 'lyr', 'cur', 'sf2', 'sf3']);
  const ALL = new Set([...AUDIO, ...MIDI, ...SIDE]);
  const entries = new Map();
  const selected = new Set();
  const encoder = new TextEncoder();
  const state = { active: null, previewURL: '', dest: null, ffmpeg: null, busy: false,
                  cancelled: false, currentIndex: 0, total: 0, currentFraction: 0,
                  archive: null, archiveName: '' };
  const ffmpegUrls = [
    'https://cdn.jsdelivr.net/npm/@ffmpeg/ffmpeg@0.12.15/dist/esm/index.js',
    'https://cdn.jsdelivr.net/npm/@ffmpeg/ffmpeg@0.12.15/dist/esm/worker.js',
    'https://cdn.jsdelivr.net/npm/@ffmpeg/core@0.12.10/dist/esm/ffmpeg-core.js',
    'https://cdn.jsdelivr.net/npm/@ffmpeg/core@0.12.10/dist/esm/ffmpeg-core.wasm'
  ];
  const extOf = (name) => String(name).split('.').pop().toLowerCase();
  const baseOf = (name) => String(name).replace(/\.[^.]+$/, '');
  const readableBytes = (n) => (n < 1024 * 1024 ?
    (n / 1024).toFixed(0) + ' KB' : (n / 1048576).toFixed(1) + ' MB');
  function notice(text, kind) {
    const box = $('notice');
    box.textContent = text;
    box.className = 'notice' + (kind ? ' ' + kind : '');
  }
  function log(text, isError) {
    const p = document.createElement('p');
    p.className = isError ? 'fail' : 'success';
    p.textContent = (isError ? '✕ ' : '✓ ') + text;
    $('results').appendChild(p);
  }
  function setProgress(text, percent) {
    const p = Math.min(100, Math.max(0, Number(percent) || 0));
    $('progress-label').textContent = text;
    $('progress-percent').textContent = Math.round(p) + '%';
    $('progress-bar').style.width = p + '%';
  }
  function setBusy(flag) {
    state.busy = flag;
    $('download-result').disabled = flag || !state.archive;
    for (const id of ['choose-files', 'choose-folder', 'clear-all', 'select-all', 'deselect-all',
                      'pick-destination', 'load-engine', 'build', 'save-lyrics', 'insert-time']) {
      $(id).disabled = flag;
    }
    $('build').disabled = flag || ![...selected].some((id) => entries.get(id)?.audio);
    $('cancel').hidden = !flag;
    if (!flag) {
      $('save-lyrics').disabled = !state.active;
      $('insert-time').disabled = !entries.get(state.active)?.audio;
    }
  }
  function safeName(name) {
    return String(name || 'untitled').replace(/[\\/:*?"<>|\x00-\x1f]/g, '_')
      .replace(/\s+/g, ' ').replace(/[. ]+$/, '').slice(0, 160) || 'untitled';
  }
  function updateOverview() {
    const songs = [...entries.values()].filter((e) => e.audio || e.midi);
    const bytes = [...entries.values()].reduce((n, e) => n + [...e.parts.values()]
      .reduce((sum, part) => sum + part.size, 0), 0);
    $('file-count').textContent = songs.length.toLocaleString('th-TH') + ' เพลง';
    $('source-size').textContent = readableBytes(bytes);
    $('selected-counter').textContent = 'เลือก ' + selected.size.toLocaleString('th-TH');
    $('build').disabled = state.busy || ![...selected].some((id) => entries.get(id)?.audio);
  }
  function songTitle(e) {
    return e.name || 'ไม่ทราบชื่อ';
  }
  function makeRow(e) {
    const tr = document.createElement('tr');
    const tdSelect = document.createElement('td');
    const check = document.createElement('input');
    check.type = 'checkbox';
    check.checked = selected.has(e.id);
    check.disabled = !e.audio || state.busy;
    check.setAttribute('aria-label', 'เลือก ' + songTitle(e));
    check.addEventListener('click', (event) => event.stopPropagation());
    check.addEventListener('change', () => {
      if (check.checked) selected.add(e.id); else selected.delete(e.id);
      updateOverview();
    });
    tdSelect.appendChild(check);
    const tdTitle = document.createElement('td');
    const strong = document.createElement('strong');
    strong.textContent = songTitle(e);
    tdTitle.appendChild(strong);
    const hint = document.createElement('small');
    hint.textContent = e.path ? e.path : 'ไฟล์ที่เลือก';
    tdTitle.appendChild(hint);
    const tdType = document.createElement('td');
    const badge = document.createElement('span');
    badge.className = 'file-state' + (e.audio ? '' : ' unsupported');
    badge.textContent = e.audio ? extOf(e.audio.name).toUpperCase() : 'MIDI · รอ Engine';
    tdType.appendChild(badge);
    const tdLyric = document.createElement('td');
    tdLyric.textContent = e.lyricsText || e.lrc ? 'มี LRC' : '—';
    const tdSize = document.createElement('td');
    tdSize.textContent = readableBytes(e.audio?.size || e.midi?.size || 0);
    tr.append(tdSelect, tdTitle, tdType, tdLyric, tdSize);
    tr.style.cursor = 'pointer';
    tr.addEventListener('click', () => { void activate(e.id); });
    return tr;
  }
  function renderTable() {
    const filter = $('search').value.trim().toLocaleLowerCase();
    const songs = [...entries.values()].filter((e) => (e.audio || e.midi) &&
      (e.name + ' ' + e.path + ' ' + [...e.parts.keys()].join(' ')).toLocaleLowerCase().includes(filter));
    const tbody = $('song-list');
    tbody.replaceChildren();
    for (const item of songs.slice(0, 500)) tbody.appendChild(makeRow(item));
    if (!songs.length) {
      const tr = document.createElement('tr'), td = document.createElement('td');
      td.colSpan = 5;
      td.className = 'empty';
      td.textContent = entries.size ? 'ไม่พบเพลงที่ค้นหา' : 'ยังไม่มีเพลง กรุณาเลือกไฟล์หรือโฟลเดอร์';
      tr.appendChild(td); tbody.appendChild(tr);
    }
    $('catalog-note').textContent = 'แสดง ' + Math.min(songs.length, 500) + ' จาก ' + songs.length +
      ' เพลง · ไฟล์ MIDI/KAR/NCN ต้องใช้ SoundFont Engine ซึ่งยังไม่พร้อมในรุ่นเว็บนี้';
    updateOverview();
  }
  function addFiles(files, prefix) {
    let accepted = 0;
    for (const item of files) {
      const file = item.file || item;
      const ext = extOf(file.name);
      if (!ALL.has(ext) || !file.size) continue;
      const path = item.path !== undefined ? item.path :
        (file.webkitRelativePath ? file.webkitRelativePath.split('/').slice(0, -1).join('/') : (prefix || ''));
      const stem = baseOf(file.name);
      const id = (path + '/' + stem).toLocaleLowerCase();
      if (!entries.has(id)) entries.set(id, {
        id, name: stem, path, audio: null, midi: null, lrc: null,
        lyricsText: null, parts: new Map()
      });
      const song = entries.get(id);
      song.parts.set(ext, file);
      if (AUDIO.has(ext)) song.audio = file;
      if (MIDI.has(ext)) song.midi = file;
      if (ext === 'lrc') { song.lrc = file; song.lyricsText = null; }
      if (AUDIO.has(ext)) selected.add(id);
      accepted++;
    }
    renderTable();
    notice(accepted
      ? 'เพิ่ม ' + accepted + ' ไฟล์จากเครื่องแล้ว · ไฟล์ต้นฉบับยังอยู่ที่เดิม' :
        'ไม่พบไฟล์ที่รองรับในรายการที่เลือก', accepted ? 'good' : 'error');
  }
  async function walkFolder(handle, path, output, depth) {
    if (depth > 12) throw new Error('โฟลเดอร์ซ้อนลึกเกิน 12 ระดับ');
    for await (const child of handle.values()) {
      if (state.cancelled) return;
      if (child.kind === 'directory') {
        await walkFolder(child, path ? path + '/' + child.name : child.name, output, depth + 1);
      } else if (ALL.has(extOf(child.name))) {
        output.push({ file: await child.getFile(), path });
        if (output.length >= 5000) throw new Error('เกิน 5,000 ไฟล์ กรุณาเลือกโฟลเดอร์ย่อย');
      }
    }
  }
  async function chooseFolder() {
    if (typeof window.showDirectoryPicker !== 'function') {
      $('folder-input').click(); return;
    }
    try {
      state.cancelled = false;
      const handle = await window.showDirectoryPicker({ mode: 'read' });
      notice('กำลังอ่านรายการไฟล์จากโฟลเดอร์ ' + handle.name);
      const files = [];
      await walkFolder(handle, handle.name, files, 0);
      addFiles(files);
    } catch (error) {
      if (error.name !== 'AbortError') notice('ไม่สามารถอ่านโฟลเดอร์: ' + error.message, 'error');
    }
  }
  function parseLrc(text) {
    const list = [];
    for (const line of String(text || '').split(/\r?\n/)) {
      const stamp = /\[(\d{1,3}):(\d\d)(?:[.:](\d{1,3}))?\]/.exec(line);
      if (!stamp) continue;
      const seconds = Number(stamp[1]) * 60 + Number(stamp[2]) +
        Number((stamp[3] || '0').padEnd(3, '0').slice(0, 3)) / 1000;
      const lyrics = line.slice(stamp.index + stamp[0].length).trim();
      if (lyrics) list.push({ seconds, text: lyrics });
    }
    return list.sort((a, b) => a.seconds - b.seconds);
  }
  async function lyricsFor(song) {
    if (song.lyricsText !== null) return song.lyricsText;
    song.lyricsText = song.lrc ? await song.lrc.text() : '';
    return song.lyricsText;
  }
  async function activate(id) {
    if (state.busy) return;
    const song = entries.get(id);
    if (!song) return;
    state.active = id;
    $('active-title').textContent = songTitle(song);
    $('active-kind').textContent = song.audio ? 'เสียงต้นฉบับ ' + extOf(song.audio.name).toUpperCase() :
      'MIDI/KAR/NCN · ยังไม่มีตัวสังเคราะห์ SoundFont ในเว็บ';
    if (state.previewURL) URL.revokeObjectURL(state.previewURL);
    $('player').pause();
    state.previewURL = song.audio ? URL.createObjectURL(song.audio) : '';
    $('player').src = state.previewURL || '';
    $('insert-time').disabled = !song.audio;
    $('lyrics-text').disabled = false;
    $('save-lyrics').disabled = false;
    $('download-lyrics').disabled = false;
    const text = await lyricsFor(song);
    if (state.active === id) {
      $('lyrics-text').value = text;
      $('active-lyric').textContent = 'เนื้อร้องจะแสดงตามเวลาใน LRC';
    }
  }
  function stamp(time) {
    const t = Math.max(0, time || 0), mm = Math.floor(t / 60), ss = Math.floor(t % 60);
    return '[' + String(mm).padStart(2, '0') + ':' + String(ss).padStart(2, '0') + '.' +
      String(Math.floor((t % 1) * 100)).padStart(2, '0') + ']';
  }
  function syncActiveLyric() {
    const lines = parseLrc($('lyrics-text').value);
    const time = $('player').currentTime;
    const active = lines.filter((line) => line.seconds <= time + 0.04).pop();
    $('active-lyric').textContent = active?.text || '♪';
  }
  async function blobFromURL(url, type) {
    const response = await fetch(url, {cache: 'force-cache'});
    if (!response.ok) throw new Error('ดาวน์โหลดไลบรารีไม่สำเร็จ (' + response.status + ')');
    const blob = await response.blob();
    return URL.createObjectURL(new Blob([blob], {type}));
  }
  async function ensureEngine() {
    if (state.ffmpeg) return state.ffmpeg;
    $('engine-caption').textContent = 'กำลังดาวน์โหลด WebAssembly / เตรียม Engine (เฉพาะครั้งแรกหรือเมื่อแคชหมด)';
    setProgress('กำลังโหลดโค้ด FFmpeg.wasm จาก CDN', 4);
    const tempURLs = [];
    let instance;
    try {
      const module = await import(ffmpegUrls[0]);
      instance = new module.FFmpeg();
      instance.on('progress', ({progress}) => {
        if (!state.busy || state.cancelled) return;
        state.currentFraction = Math.min(.99, Math.max(0, Number(progress) || 0));
        const pct = 100 * ((state.currentIndex + state.currentFraction) / Math.max(1, state.total));
        setProgress('กำลังเข้ารหัส M4A · เพลง ' + (state.currentIndex + 1) + '/' + state.total, pct);
      });
      const workerURL = URL.createObjectURL(new Blob(['import "' + ffmpegUrls[1] + '";'], {type: 'text/javascript'}));
      const coreURL = await blobFromURL(ffmpegUrls[2], 'text/javascript');
      const wasmURL = await blobFromURL(ffmpegUrls[3], 'application/wasm');
      tempURLs.push(workerURL, coreURL, wasmURL);
      await instance.load({classWorkerURL: workerURL, coreURL, wasmURL});
      state.ffmpeg = instance;
      $('engine-caption').textContent = 'พร้อมประมวลผลในเบราว์เซอร์ · ไม่อัปโหลดไฟล์เพลง';
      $('load-engine').textContent = '✓ Engine พร้อมใช้งาน';
      notice('Web Engine พร้อมแล้ว · ไฟล์เพลงถูกประมวลผลบนอุปกรณ์ของคุณ', 'good');
      return instance;
    } catch (error) {
      $('engine-caption').textContent = 'โหลด Engine ไม่สำเร็จ · ตรวจสอบอินเทอร์เน็ตและเบราว์เซอร์';
      try { instance?.terminate(); } catch (_) { /* ignore */ }
      throw new Error('เปิด FFmpeg Web Engine ไม่สำเร็จ: ' + error.message);
    } finally {
      /* Keep temporary blob URLs until the worker has fully initialized.
         The worker/core may still reference these URLs during bootstrap. */
      if (state.ffmpeg) tempURLs.forEach((url) => { /* retained for the session */ });
      else tempURLs.forEach((url) => URL.revokeObjectURL(url));
    }
  }
  async function renderAudio(song, number) {
    const ext = extOf(song.audio.name);
    if (ext === 'm4a') return song.audio;
    const engine = await ensureEngine();
    if (state.cancelled) throw new Error('ยกเลิกโดยผู้ใช้');
    const input = 'song-input-' + number + '.' + ext;
    const output = 'song-result-' + number + '.m4a';
    await engine.writeFile(input, new Uint8Array(await song.audio.arrayBuffer()));
    try {
      const rc = await engine.exec(['-hide_banner', '-loglevel', 'error', '-y',
        '-i', input, '-vn', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', output]);
      if (state.cancelled) throw new Error('ยกเลิกโดยผู้ใช้');
      if (rc !== 0) throw new Error('FFmpeg ไม่สามารถแปลงไฟล์ชนิดนี้ได้ (code ' + rc + ')');
      const data = await engine.readFile(output);
      if (!data?.length) throw new Error('ไฟล์เสียงผลลัพธ์ว่างเปล่า');
      return new Blob([data], {type: 'audio/mp4'});
    } finally {
      try { await engine.deleteFile(input); } catch (_) { /* ignore */ }
      try { await engine.deleteFile(output); } catch (_) { /* ignore */ }
    }
  }
  function download(blob, filename) {
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    link.href = url; link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 60000);
  }
  function dosTimeDate() {
    const d = new Date();
    return {time: (d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1),
            date: ((Math.max(1980, d.getFullYear()) - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate()};
  }
  function crc32(data) {
    let crc = -1;
    for (const byte of data) {
      crc ^= byte;
      for (let n = 0; n < 8; n++) crc = crc >>> 1 ^ (crc & 1 ? 0xEDB88320 : 0);
    }
    return (crc ^ -1) >>> 0;
  }
  async function makeZIP(assets) {
    const pieces = [], index = [];
    let offset = 0;
    const stamp = dosTimeDate();
    for (const asset of assets) {
      const filename = encoder.encode(asset.name);
      const contents = new Uint8Array(await asset.blob.arrayBuffer());
      const crc = crc32(contents), size = contents.length;
      const local = new Uint8Array(30 + filename.length), head = new DataView(local.buffer);
      head.setUint32(0, 0x04034b50, true); head.setUint16(4, 20, true);
      head.setUint16(6, 0x0800, true); head.setUint16(8, 0, true);
      head.setUint16(10, stamp.time, true); head.setUint16(12, stamp.date, true);
      head.setUint32(14, crc, true); head.setUint32(18, size, true);
      head.setUint32(22, size, true); head.setUint16(26, filename.length, true);
      local.set(filename, 30);
      pieces.push(local, asset.blob);
      const central = new Uint8Array(46 + filename.length), v = new DataView(central.buffer);
      v.setUint32(0, 0x02014b50, true); v.setUint16(4, 20, true); v.setUint16(6, 20, true);
      v.setUint16(8, 0x0800, true); v.setUint16(10, 0, true);
      v.setUint16(12, stamp.time, true); v.setUint16(14, stamp.date, true);
      v.setUint32(16, crc, true); v.setUint32(20, size, true); v.setUint32(24, size, true);
      v.setUint16(28, filename.length, true); v.setUint32(42, offset, true);
      central.set(filename, 46);
      index.push(central);
      offset += local.length + size;
      if (offset > 0xffffffff) throw new Error('ZIP มีขนาดเกิน 4GB กรุณาแบ่งงานเป็นชุดย่อย');
    }
    const count = index.length, centralSize = index.reduce((n, b) => n + b.length, 0);
    if (count > 65535 || offset + centralSize > 0xffffffff)
      throw new Error('ชุด ZIP มีขนาดเกินขีดจำกัด กรุณาแบ่งงานเป็นชุดย่อย');
    const eocd = new Uint8Array(22), tail = new DataView(eocd.buffer);
    tail.setUint32(0, 0x06054b50, true); tail.setUint16(8, count, true);
    tail.setUint16(10, count, true); tail.setUint32(12, centralSize, true);
    tail.setUint32(16, offset, true);
    return new Blob([...pieces, ...index, eocd], {type: 'application/zip'});
  }
  async function saveUniqueToDirectory(directory, name, blob) {
    const dot = name.lastIndexOf('.'), stem = dot < 0 ? name : name.slice(0, dot);
    const ext = dot < 0 ? '' : name.slice(dot);
    for (let n = 0; n < 1000; n++) {
      const candidate = n ? stem + ' (' + n + ')' + ext : name;
      let exists = false;
      try { await directory.getFileHandle(candidate, {create: false}); exists = true; }
      catch (error) { if (error.name !== 'NotFoundError') throw error; }
      if (exists) continue;
      const handle = await directory.getFileHandle(candidate, {create: true});
      const writer = await handle.createWritable();
      try { await writer.write(blob); await writer.close(); }
      catch (error) { try { await writer.abort(); } catch (_) { /* ignore */ } throw error; }
      return candidate;
    }
    throw new Error('มีไฟล์ชื่อซ้ำเกินจำนวนที่รองรับ: ' + name);
  }
  async function chooseDestination() {
    if (typeof window.showDirectoryPicker !== 'function') {
      notice('เบราว์เซอร์นี้ไม่รองรับการเลือกโฟลเดอร์ผลลัพธ์ · ใช้ ZIP ดาวน์โหลดได้', 'error');
      return;
    }
    try {
      state.dest = await window.showDirectoryPicker({mode: 'readwrite'});
      $('destination-label').textContent = 'บันทึกไปยัง: ' + state.dest.name + ' · ไม่เขียนทับไฟล์เดิม';
      notice('เลือกโฟลเดอร์ผลลัพธ์แล้ว · การบันทึกจะไม่เขียนทับไฟล์เดิม', 'good');
    } catch (error) {
      if (error.name !== 'AbortError') notice('เลือกโฟลเดอร์ไม่ได้: ' + error.message, 'error');
    }
  }
  async function createSongAssets(song, number) {
    const assets = [];
    const name = safeName(song.name);
    const audioBlob = await renderAudio(song, number);
    if (state.cancelled) throw new Error('ยกเลิกโดยผู้ใช้');
    assets.push({name: name + '.m4a', blob: audioBlob});
    const lyrics = await lyricsFor(song);
    if (lyrics.trim()) assets.push({
      name: name + '.lrc', blob: new Blob([lyrics.replace(/\r?\n/g, '\r\n')], {type: 'text/plain;charset=utf-8'})
    });
    return assets;
  }
  async function reserveSongAssetNames(songName, assets, usedNames, exists) {
    // Reserve one common filename stem for ALL parts of a single song.
    // A missing LRC on the first copy must not cause the second copy's LRC
    // to be paired with the wrong M4A in a ZIP or restored folder.
    const originalStem = safeName(songName);
    const key = originalStem.toLocaleLowerCase();
    const extensions = assets.map(asset => asset.name.slice(asset.name.lastIndexOf('.')));
    let suffix = usedNames.get(key) || 0;
    let filenames;
    for (;;) {
      if (suffix > 9999) throw new Error('ชื่อเพลงซ้ำมากเกินไป: ' + originalStem);
      const stem = originalStem + (suffix ? ' (' + suffix + ')' : '');
      filenames = extensions.map(ext => stem + ext);
      if (!(await Promise.all(filenames.map(exists))).some(Boolean)) break;
      suffix++;
    }
    usedNames.set(key, suffix + 1);
    assets.forEach((asset, index) => { asset.name = filenames[index]; });
    return assets;
  }
  async function build() {
    if (state.busy) return;
    const work = [...selected].map((id) => entries.get(id)).filter((e) => e?.audio);
    if (!work.length) return notice('กรุณาเลือกไฟล์เสียงอย่างน้อยหนึ่งเพลง', 'error');
    const totalSize = work.reduce((n, e) => n + e.audio.size, 0);
    if (!state.dest && totalSize > 500 * 1048576) {
      notice('ไฟล์รวมเกิน 500MB · เพื่อหลีกเลี่ยงหน่วยความจำไม่พอ กรุณาเลือกโฟลเดอร์ปลายทางหรือแบ่งงาน', 'error');
      return;
    }
    state.cancelled = false;
    state.archive = null;
    state.archiveName = '';
    $('download-result').hidden = true;
    state.currentIndex = 0; state.total = work.length;
    setBusy(true);
    $('results').replaceChildren();
    let success = 0, errors = 0, audioCount = 0, lyricCount = 0;
    const zipAssets = [];
    // Reserve a shared basename per song so .m4a and .lrc always stay paired.
    const usedNames = new Map();
    const fileExists = async (name) => {
      if (!state.dest) return false;
      try { await state.dest.getFileHandle(name, {create:false}); return true; }
      catch (error) {
        if (error?.name === 'NotFoundError') return false;
        throw error;
      }
    };
    try {
      for (let i = 0; i < work.length; i++) {
        if (state.cancelled) break;
        state.currentIndex = i; state.currentFraction = 0;
        const song = work[i];
        setProgress('กำลังสร้าง ' + (i + 1) + '/' + work.length + ' · ' + song.name,
          i * 100 / work.length);
        try {
          const assets = await createSongAssets(song, i);
          await reserveSongAssetNames(song.name, assets, usedNames, fileExists);
          for (const asset of assets) {
            if (state.dest) {
              const saved = await saveUniqueToDirectory(state.dest, asset.name, asset.blob);
              if (saved !== asset.name)
                throw new Error('มีไฟล์ชื่อเดียวกันถูกสร้างเพิ่มระหว่างบันทึก: ' + asset.name);
            } else zipAssets.push(asset);
          }
          success++;
          audioCount++;
          if (assets.some(asset => asset.name.toLowerCase().endsWith('.lrc'))) lyricCount++;
          else log('สร้าง M4A สำหรับ ' + song.name + ' แต่ยังไม่มี LRC พร้อมเวลาจริง · ต้องเพิ่มเนื้อร้องก่อนส่งออก LRC', true);
          log('สร้าง ' + song.name + ' เรียบร้อย (' + assets.map((a) => a.name).join(', ') + ')');
        } catch (error) {
          if (state.cancelled) break;
          errors++;
          log(song.name + ': ' + error.message, true);
        }
        setProgress('ดำเนินการแล้ว ' + (i + 1) + '/' + work.length + ' เพลง',
          (i + 1) * 100 / work.length);
      }
      if (!state.cancelled && zipAssets.length) {
        setProgress('กำลังจัดเตรียม ZIP สำหรับดาวน์โหลด', 98);
        const blob = await makeZIP(zipAssets);
        if (!blob.size) throw new Error('ZIP ผลลัพธ์ว่างเปล่า');
        state.archive = blob;
        state.archiveName = 'X-Stage-Song-Studio-' + new Date().toISOString().slice(0, 10) + '.zip';
        $('download-result').hidden = false;
        $('download-result').disabled = false;
        log('สร้าง ZIP แล้ว ' + zipAssets.length + ' ไฟล์ (' + readableBytes(blob.size) +
            ') · กด “ดาวน์โหลด ZIP ผลลัพธ์” เพื่อบันทึกลงเครื่อง');
      }
      if (state.cancelled) {
        notice('ยกเลิกงานแล้ว · ไฟล์ที่สร้างเสร็จก่อนหน้ายังคงอยู่', 'error');
        setProgress('ยกเลิกงาน', 0);
      } else {
        notice(success
          ? 'สร้าง M4A ' + audioCount + ' ไฟล์ · LRC ' + lyricCount + ' ไฟล์' +
            (audioCount > lyricCount ? ' · บางเพลงยังไม่มีเนื้อร้องที่มีเวลา (ไม่สร้างเนื้อร้องปลอม)' : '') +
            ' · ข้อผิดพลาด ' + errors +
            (state.archive ? ' · กด “ดาวน์โหลด ZIP ผลลัพธ์” เพื่อรับไฟล์' : ' · บันทึกลงโฟลเดอร์ที่เลือกแล้ว')
          : 'สร้างเพลงไม่สำเร็จ · ตรวจรายละเอียดข้อผิดพลาดด้านล่าง',
          errors || !success || audioCount !== lyricCount ? 'error' : 'good');
        setProgress('เสร็จสิ้น ' + success + '/' + work.length + ' เพลง', 100);
      }
    } catch (error) {
      notice('ไม่สามารถส่งออกได้: ' + error.message, 'error');
      log(error.message, true);
    } finally {
      setBusy(false);
    }
  }
  function cancel() {
    state.cancelled = true;
    try { state.ffmpeg?.terminate(); } catch (_) { /* ignore */ }
    state.ffmpeg = null;
    $('engine-caption').textContent = 'Engine ถูกหยุด สามารถโหลดใหม่ได้';
    $('load-engine').textContent = '↓ ดาวน์โหลด Web Engine';
    notice('ได้รับคำสั่งหยุด · กำลังยุติงานปัจจุบัน', 'error');
  }
  $('choose-files').addEventListener('click', () => $('file-input').click());
  $('choose-folder').addEventListener('click', () => {void chooseFolder();});
  $('file-input').addEventListener('change', (e) => {addFiles([...e.target.files]);e.target.value='';});
  $('folder-input').addEventListener('change', (e) => {addFiles([...e.target.files]);e.target.value='';});
  $('clear-all').addEventListener('click', () => {
    if (state.previewURL) URL.revokeObjectURL(state.previewURL);
    state.previewURL = '';
    $('player').pause(); $('player').removeAttribute('src'); $('player').load();
    entries.clear(); selected.clear(); state.active = null;
    state.archive = null; state.archiveName = '';
    $('download-result').hidden = true;
    $('active-title').textContent = 'ยังไม่ได้เลือกเพลง'; $('active-kind').textContent = '—';
    $('lyrics-text').value = ''; $('lyrics-text').disabled = true;
    $('save-lyrics').disabled = true; $('download-lyrics').disabled = true;
    $('insert-time').disabled = true;
    renderTable(); notice('ล้างรายการชั่วคราวแล้ว · ไฟล์ต้นฉบับในเครื่องไม่ถูกลบ');
  });
  $('search').addEventListener('input', renderTable);
  $('select-all').addEventListener('click', () => {
    for (const e of entries.values()) if (e.audio) selected.add(e.id);
    renderTable();
  });
  $('deselect-all').addEventListener('click', () => {selected.clear();renderTable();});
  $('player').addEventListener('timeupdate', syncActiveLyric);
  $('insert-time').addEventListener('click', () => {
    if (!state.active) return;
    const el = $('lyrics-text');
    const tag = stamp($('player').currentTime);
    const index = el.selectionStart, prefix = el.value.slice(0, index), suffix = el.value.slice(index);
    el.value = prefix + tag + suffix;
    el.focus(); el.setSelectionRange(index + tag.length, index + tag.length);
    entries.get(state.active).lyricsText = el.value;
  });
  $('lyrics-text').addEventListener('input', () => {
    if (state.active) entries.get(state.active).lyricsText = $('lyrics-text').value;
  });
  $('save-lyrics').addEventListener('click', () => {
    if (!state.active) return;
    entries.get(state.active).lyricsText = $('lyrics-text').value;
    renderTable(); notice('บันทึกเนื้อร้องไว้ในหน้านี้แล้ว · กดสร้างเพลงหรือดาวน์โหลด LRC เพื่อเก็บในเครื่อง', 'good');
  });
  $('download-lyrics').addEventListener('click', () => {
    const song = entries.get(state.active);
    if (!song) return;
    download(new Blob([$('lyrics-text').value], {type:'text/plain;charset=utf-8'}), safeName(song.name) + '.lrc');
  });
  $('load-engine').addEventListener('click', async () => {
    if (state.busy) return;
    $('load-engine').disabled = true;
    try { await ensureEngine(); }
    catch (error) {notice(error.message, 'error');log(error.message, true);}
    finally {$('load-engine').disabled = false;}
  });
  $('pick-destination').addEventListener('click', () => {void chooseDestination();});
  $('build').addEventListener('click', () => {void build();});
  $('download-result').addEventListener('click', () => {
    if (!state.archive || !state.archiveName) {
      notice('ยังไม่มี ZIP ที่สร้างสำเร็จ กรุณาสร้างเพลงก่อน', 'error');
      return;
    }
    download(state.archive, state.archiveName);
    notice('ส่งคำสั่งดาวน์โหลด ZIP แล้ว · ตรวจสอบการดาวน์โหลดของเบราว์เซอร์', 'good');
  });
  $('cancel').addEventListener('click', cancel);
  const drop = $('drop-zone');
  ['dragenter', 'dragover'].forEach((eventName) => drop.addEventListener(eventName, (event) => {
    event.preventDefault(); drop.classList.add('dragging');
  }));
  ['dragleave', 'drop'].forEach((eventName) => drop.addEventListener(eventName, (event) => {
    event.preventDefault(); drop.classList.remove('dragging');
  }));
  drop.addEventListener('drop', (event) => addFiles([...event.dataTransfer.files]));
  drop.addEventListener('click', (event) => {
    if (event.target.closest('button')) return;
    $('file-input').click();
  });
  drop.addEventListener('keydown', (event) => {
    if (event.target !== drop) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault(); $('file-input').click();
    }
  });
  renderTable();
  if (typeof window.showDirectoryPicker !== 'function') {
    $('pick-destination').disabled = true;
    $('pick-destination').title = 'เบราว์เซอร์นี้ใช้การดาวน์โหลด ZIP แทน';
  }
})();
