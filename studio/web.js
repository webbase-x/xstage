/* X-Stage Song Studio Web MIDI/NCN edition.
 * Sources stay on the user's device. Shared, bundled MIDI/NCN and SF2/SF3
 * parsing uses XStageBrowserMidi; FFmpeg is only for M4A conversion.
 * Never upload music or silently modify source MID/LYR/CUR bytes. */
'use strict';
(function () {
  const $ = (id) => document.getElementById(id);
  const AUDIO = new Set(['mp3', 'm4a', 'wav', 'aac', 'ogg', 'oga', 'flac']);
  const AUDIO_PRIORITY = ['m4a', 'wav', 'flac', 'mp3', 'aac', 'ogg', 'oga'];
  const MIDI = new Set(['mid', 'midi', 'kar', 'ncn']);
  const SIDE = new Set(['lrc', 'lyr', 'cur', 'sf2', 'sf3']);
  const ALL = new Set([...AUDIO, ...MIDI, ...SIDE]);
  const entries = new Map();
  const selected = new Set();
  const fonts = new Map();
  const midiCore = window.XStageStudioMidiCore;
  const midiRuntime = window.XStageBrowserMidi;
  if (!midiCore || !midiRuntime) throw Error('Song Studio Web: MIDI/NCN modules are missing');
  const encoder = new TextEncoder();
  const state = { active: null, previewURL: '', dest: null, ffmpeg: null, busy: false,
                  cancelled: false, currentIndex: 0, total: 0, currentFraction: 0,
                  archive: null, archiveName: '', activation: 0,
                  midiController: null, midiRenderSequence: 0, renderingMidi: false,
                  fontCache: null, fontID: '', scanActive: false,
                  channelMutes: Array(16).fill(false),
                  channelVolumes: Array(16).fill(1) };
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
    for (const item of document.querySelectorAll('[data-audio-select]'))
      item.disabled = flag;
    $('download-result').disabled = flag || !state.archive;
    for (const id of ['choose-files', 'choose-folder', 'clear-all', 'select-all', 'deselect-all',
                      'pick-destination', 'load-engine', 'build', 'save-lyrics', 'insert-time',
                      'choose-soundfont', 'soundfont-select', 'export-format', 'midi-transpose']) {
      $(id).disabled = flag;
    }
    $('build').disabled = flag || ![...selected].some((id) => canExport(entries.get(id)));
    $('cancel').hidden = !flag;
    if (!flag) {
      $('save-lyrics').disabled = !state.active;
      $('insert-time').disabled = !state.active || !state.previewURL;
    }
  }
  function safeName(name) {
    return String(name || 'untitled').replace(/[\\/:*?"<>|\x00-\x1f]/g, '_')
      .replace(/\s+/g, ' ').replace(/[. ]+$/, '').slice(0, 160) || 'untitled';
  }
  function invalidateArchive() {
    state.archive = null; state.archiveName = '';
    $('download-result').hidden = true;
    $('download-result').disabled = true;
  }
  function usesMidi(song) {
    return !!song?.midi && (!song.audio || song.useMidi === true);
  }
  function canExport(song) {
    if (!song || song.conflicts?.size) return false;
    if (usesMidi(song)) return midiCore.companionState(song).complete;
    return !!song.audio;
  }
  function isMIDI(song) { return !!song?.midi; }
  function refreshFontChoices() {
    const select=$('soundfont-select');
    const previous=select.value;
    select.replaceChildren(new Option('เสียง MIDI พื้นฐาน (สำรอง)',''));
    for (const [id,file] of fonts)select.add(new Option(
      file.name+' · '+readableBytes(file.size),id));
    select.value=fonts.has(previous)?previous:'';
    state.fontID=select.value;
    updateFontStatus();
  }
  function updateFontStatus() {
    const file=fonts.get($('soundfont-select').value);
    $('soundfont-status').textContent=file
      ? file.name+' · '+readableBytes(file.size)+' · อ่านจากเครื่องเท่านั้น'
      : 'เสียง MIDI พื้นฐาน (ไม่มี SF2/SF3) · คุณภาพเสียงต่างจาก Song Studio PC';
  }
  function selectStateChanged() {
    invalidateArchive();
    updateOverview();
  }
  function updateOverview() {
    const songs = [...entries.values()].filter((e) => e.audio || e.midi);
    const bytes = [...entries.values()].reduce((n, e) => n + [...e.parts.values()]
      .reduce((sum, part) => sum + part.size, 0), 0) +
      [...fonts.values()].reduce((n,font)=>n+font.size,0);
    $('file-count').textContent = songs.length.toLocaleString('th-TH') + ' เพลง';
    $('source-size').textContent = readableBytes(bytes);
    $('selected-counter').textContent = 'เลือก ' + selected.size.toLocaleString('th-TH');
    $('build').disabled = state.busy || ![...selected].some((id) => canExport(entries.get(id)));
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
    check.disabled = !canExport(e) || state.busy;
    check.setAttribute('aria-label', 'เลือก ' + songTitle(e));
    check.addEventListener('click', (event) => event.stopPropagation());
    check.addEventListener('change', () => {
      if (check.checked) selected.add(e.id); else selected.delete(e.id);
      selectStateChanged();
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
    const partState=midiCore.companionState(e);
    badge.className = 'file-state' + ((!canExport(e) || e.conflicts?.size) ? ' unsupported' : '');
    badge.textContent = e.conflicts?.size ? 'ชื่อซ้ำ · ตรวจไฟล์' :
      usesMidi(e) ? (partState.complete?partState.kind:partState.kind+' · ไม่ครบ') :
      (e.audio ? extOf(e.audio.name).toUpperCase() : partState.kind+' · ไม่ครบ');
    tdType.appendChild(badge);
    if (e.audioFiles?.size > 1) {
      const picker = document.createElement('select');
      picker.dataset.audioSelect = e.id;
      picker.disabled = state.busy;
      picker.setAttribute('aria-label', 'เลือกไฟล์เสียงที่จะใช้สร้างและทดลองฟัง: ' + songTitle(e));
      for (const [extension, audioFile] of e.audioFiles) {
        const option = document.createElement('option');
        option.value = extension;
        option.textContent = extension.toUpperCase() + ' · ' + readableBytes(audioFile.size);
        option.selected = e.audio === audioFile;
        picker.appendChild(option);
      }
      picker.addEventListener('click', event => event.stopPropagation());
      picker.addEventListener('change', event => {
        event.stopPropagation();
        e.audio = e.audioFiles.get(picker.value);
        badge.textContent = picker.value.toUpperCase();
        selectStateChanged();
        if (state.active === e.id) void activate(e.id);
      });
      tdType.appendChild(picker);
    }
    if (e.audio && e.midi) {
      const sourcePicker=document.createElement('select');
      sourcePicker.dataset.sourceSelect=e.id;
      sourcePicker.setAttribute('aria-label','เลือกไฟล์เสียงหรือ MIDI: '+songTitle(e));
      sourcePicker.add(new Option('ใช้ไฟล์เสียง','audio'));
      sourcePicker.add(new Option('ใช้ MIDI/NCN','midi'));
      sourcePicker.value=e.useMidi?'midi':'audio';
      sourcePicker.disabled=state.busy;
      sourcePicker.addEventListener('click',event=>event.stopPropagation());
      sourcePicker.addEventListener('change',event=>{
        event.stopPropagation();
        e.useMidi=sourcePicker.value==='midi';
        badge.textContent=e.useMidi?partState.kind:extOf(e.audio.name).toUpperCase();
        badge.className='file-state'+(!canExport(e)?' unsupported':'');
        if(!canExport(e))selected.delete(e.id);
        selectStateChanged();
        if(state.active===e.id)void activate(e.id);
      });
      tdType.appendChild(sourcePicker);
    }
    const tdLyric = document.createElement('td');
    tdLyric.textContent = e.conflicts?.size?'ชื่อชน':e.lyricsText||e.lrc?'มี LRC':
      e.lyr&&e.cur?'มี NCN CUR':e.midi?'MIDI/KAR':'—';
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
    const incomplete=songs.filter(song=>!canExport(song)).length;
    $('catalog-note').textContent = 'แสดง '+Math.min(songs.length,500)+' จาก '+songs.length+
      ' เพลง · พร้อมสร้าง '+(songs.length-incomplete)+' · ต้องตรวจสอบ '+incomplete+
      ' · รองรับ MIDI/KAR/NCN + SF2/SF3 · แสดงสูงสุด 500 แถวเพื่อให้เลื่อนเร็ว';
    updateOverview();
  }
  async function addFiles(files, prefix) {
    let accepted = 0, collisions = 0, importedFonts = 0;
    const touched=new Set();
    state.cancelled=false;
    invalidateArchive();
    for (const item of files) {
      if(state.cancelled)break;
      const file = item.file || item;
      const ext = extOf(file.name);
      if (!ALL.has(ext) || !file.size) continue;
      if(ext==='sf2'||ext==='sf3'){
        if(file.size>midiCore.MAX_FONT){collisions++;continue;}
        const fontId=[file.name,file.size,file.lastModified||0].join('|');
        if(!fonts.has(fontId)){fonts.set(fontId,file);importedFonts++;}
        accepted++;
        continue;
      }
      const path = item.path !== undefined ? item.path :
        (file.webkitRelativePath ? file.webkitRelativePath.split('/').slice(0,-1).join('/') : (prefix || ''));
      const stem = baseOf(file.name);
      const id = midiCore.groupIdentity(path,file.name);
      if (!entries.has(id)) entries.set(id, {
        id, name: stem, path, audio: null, midi: null, lrc: null, lyr:null, cur:null,
        lyricsText: null, editedLyrics:false, midiInfo:null, conflicts:new Set(),
        parts: new Map(), audioFiles: new Map(), midiFiles:new Map(),useMidi:false
      });
      const song = entries.get(id);
      const previous=song.parts.get(ext);
      if(previous && previous!==file && (previous.size!==file.size ||
          previous.lastModified!==file.lastModified || previous.name!==file.name)){
        song.conflicts.add(ext);selected.delete(id);collisions++;continue;
      }
      song.parts.set(ext, file);
      touched.add(id);
      if (AUDIO.has(ext)) {
        const prior = song.audio;
        song.audioFiles.set(ext,file);
        if (!prior || AUDIO_PRIORITY.indexOf(ext) < AUDIO_PRIORITY.indexOf(extOf(prior.name)))
          song.audio=file;
        else if(extOf(prior.name)===ext) song.audio=file;
      }
      if(MIDI.has(ext)){
        song.midiFiles.set(ext,file);
        if(!song.midi||ext==='mid')song.midi=file;
        song.midiInfo=null;
      }
      if(ext==='lyr'){song.lyr=file;song.midiInfo=null;}
      if(ext==='cur'){song.cur=file;song.midiInfo=null;}
      if(ext==='lrc'){song.lrc=file;song.lyricsText=null;song.editedLyrics=false;}
      accepted++;
      if(accepted%500===0){
        notice('นำเข้ารายการแล้ว '+accepted.toLocaleString('th-TH')+' ไฟล์ · กำลังจัดกลุ่มเพลง/NCN…');
        await new Promise(resolve=>setTimeout(resolve,0));
      }
    }
    for(const id of touched){
      const song=entries.get(id);
      if(canExport(song))selected.add(id);
      else selected.delete(id);
    }
    refreshFontChoices();
    renderTable();
    notice(accepted
      ? 'เพิ่ม '+accepted.toLocaleString('th-TH')+' ไฟล์ · SoundFont '+importedFonts+
        ' · รายการต้องตรวจชื่อซ้ำ/ขนาด '+collisions+' · ต้นฉบับยังอยู่ที่เดิม'
      : 'ไม่พบไฟล์ที่รองรับในรายการที่เลือก',accepted?'good':'error');
  }
  async function walkFolder(handle, path, output, depth) {
    if (depth > 12) throw new Error('โฟลเดอร์ซ้อนลึกเกิน 12 ระดับ');
    for await (const child of handle.values()) {
      if (state.cancelled) return;
      if (child.kind === 'directory') {
        await walkFolder(child, path ? path + '/' + child.name : child.name, output, depth + 1);
      } else if (ALL.has(extOf(child.name))) {
        output.push({ file: await child.getFile(), path });
        if (output.length >= 120000) throw new Error('เกิน 120,000 ไฟล์ กรุณาเลือกโฟลเดอร์ย่อย');
        if (output.length % 500 === 0) {
          notice('กำลังสแกนต้นฉบับ '+output.length.toLocaleString('th-TH')+' ไฟล์ · ตรวจชุด NCN/SoundFont…');
          await new Promise(resolve=>setTimeout(resolve,0));
        }
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
      if(state.cancelled){notice('ยกเลิกการสแกน · ยังไม่ได้เปลี่ยนรายการเพลง','error');return;}
      await addFiles(files);
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
    if(state.busy)return;
    const song=entries.get(id);if(!song)return;
    const activation=++state.activation;
    stopMidiPreview(false);
    state.active=id;
    $('active-title').textContent=songTitle(song);
    const midi=usesMidi(song),quality=midiCore.companionState(song);
    $('active-kind').textContent=midi?quality.message:'เสียงต้นฉบับ '+extOf(song.audio.name).toUpperCase();
    if(state.previewURL)URL.revokeObjectURL(state.previewURL);
    $('player').pause();
    state.previewURL=!midi&&song.audio?URL.createObjectURL(song.audio):'';
    $('player').src=state.previewURL||'';
    $('midi-workspace').hidden=!midi;
    $('insert-time').disabled=!state.previewURL;
    $('lyrics-text').disabled=false;
    $('save-lyrics').disabled=false;
    $('download-lyrics').disabled=false;
    $('active-lyric').textContent='กำลังตรวจสอบเนื้อร้องและเวลา…';
    if(midi){
      $('midi-status').textContent='กำลังอ่านโน้ต MIDI และตรวจเวลาเนื้อร้องจริง…';
      $('preview-midi').disabled=true;
      if(!quality.complete){
        $('midi-status').textContent=quality.message;
        $('resource-status').textContent='ชุดเพลงไม่ครบ · ไม่อนุญาตให้สร้างข้อมูลเวลาแทน';
        $('resource-status').dataset.state='warning';
        $('lyrics-text').value='';
        $('active-lyric').textContent=quality.message;
        return;
      }
      try{
        const info=await midiCore.inspectSong(song,midiRuntime);
        if(state.activation!==activation)return;
        song.midiInfo=info;
        if(!song.editedLyrics&&!song.lrc)song.lyricsText=info.lrc;
        const lyricText=await lyricsFor(song);
        if(state.activation!==activation)return;
        $('lyrics-text').value=lyricText;
        $('active-lyric').textContent=info.lrc
          ? 'อ่านเนื้อร้องจาก '+info.kind+' จริงแล้ว · กดสังเคราะห์เพื่อทดลองฟัง'
          : '♪ ดนตรีบรรเลง · ไม่สร้างข้อความร้องหรือเวลาเทียม';
        $('midi-status').textContent=info.warning||
          (info.safeLyrics?'พบเวลา '+info.kind+' จริง · แก้ LRC ได้โดยไม่เปลี่ยนไฟล์ต้นฉบับ':
            'MIDI ไม่มีคำร้องที่มีเวลาจริง · ส่งออกได้เฉพาะต้นฉบับ');
        $('preview-midi').disabled=!info.parsed?.notes?.length;
        updateMidiResource(info);
      }catch(error){
        if(state.activation!==activation)return;
        song.midiInfo=null;
        $('midi-status').textContent='ตรวจ MIDI/NCN ไม่ผ่าน: '+error.message;
        $('resource-status').textContent='ไม่ผ่านการตรวจโครงสร้าง · หยุดก่อนสังเคราะห์/ส่งออก';
        $('resource-status').dataset.state='warning';
        $('active-lyric').textContent='ไม่สามารถตรวจเวลาได้ · '+error.message;
        $('lyrics-text').value='';
        $('preview-midi').disabled=true;
      }
    }else{
      const text=await lyricsFor(song);
      if(state.activation!==activation)return;
      $('lyrics-text').value=text;
      $('active-lyric').textContent='เนื้อร้องจะแสดงตามเวลาใน LRC';
    }
  }
  function stamp(time) {
    const t = Math.max(0, time || 0), mm = Math.floor(t / 60), ss = Math.floor(t % 60);
    return '[' + String(mm).padStart(2, '0') + ':' + String(ss).padStart(2, '0') + '.' +
      String(Math.floor((t % 1) * 100)).padStart(2, '0') + ']';
  }
  function syncActiveLyric() {
    const song=entries.get(state.active);
    const time=$('player').currentTime;
    if(usesMidi(song)&&song?.midiInfo?.document?.lines?.length&&!song.editedLyrics&&!song.lrc){
      const lines=song.midiInfo.document.lines;
      const active=lines.filter(line=>line.startTime<=time+.04).pop();
      if(!active){$('active-lyric').textContent='♪';return;}
      const syllables=active.syllables||[];
      if(!syllables.length){$('active-lyric').textContent=active.text||'♪';return;}
      const root=$('active-lyric');
      if(root.dataset.lyricLine!==String(lines.indexOf(active))||root.dataset.songId!==song.id){
        root.replaceChildren();
        root.dataset.lyricLine=String(lines.indexOf(active));
        root.dataset.songId=song.id;
        for(const cue of syllables){
          const span=document.createElement('span');
          span.className='karaoke-cue';span.textContent=cue.text;
          root.appendChild(span);
        }
      }
      [...root.children].forEach((span,i)=>{
        const cue=syllables[i];if(!cue)return;
        const pct=Math.max(0,Math.min(100,100*(time-cue.start)/Math.max(.03,cue.duration)));
        span.style.setProperty('--fill',pct.toFixed(1)+'%');
      });
      return;
    }
    $('active-lyric').dataset.lyricLine='';
    $('active-lyric').dataset.songId='';
    const lines=parseLrc($('lyrics-text').value);
    const active=lines.filter(line=>line.seconds<=time+.04).pop();
    $('active-lyric').textContent=active?.text||'♪';
  }
  function stopMidiPreview(announce=true){
    if(state.midiController){state.midiController.abort();state.midiController=null;}
    state.midiRenderSequence++;
    state.renderingMidi=false;
    $('player').pause();
    $('stop-midi').disabled=true;
    if(announce)$('midi-status').textContent='หยุด MIDI แล้ว · ไฟล์ต้นฉบับไม่เปลี่ยน';
  }
  function updateMidiResource(info){
    const font=fonts.get($('soundfont-select').value);
    const capacity=midiCore.assessResources(info.parsed.duration,font?.size||0,
      navigator.deviceMemory||null);
    const mib=n=>Math.round((n||0)/1048576);
    $('resource-status').textContent=(capacity.ok?'พร้อมประมวลผล':'ข้อจำกัดเครื่อง')+
      ' · MIDI '+info.parsed.duration.toFixed(1)+' วินาที · RAM ประเมิน '+
      mib(capacity.peakBytes)+' / '+mib(capacity.budgetBytes)+' MB · '+capacity.reason;
    $('resource-status').dataset.state=capacity.ok?'ready':'warning';
    $('preview-midi').disabled=!capacity.ok;
    return capacity;
  }
  function midiMixerOptions(){
    return {transpose:Number($('midi-transpose').value)||0,
      channelMutes:[...state.channelMutes],channelVolumes:[...state.channelVolumes]};
  }
  async function fontBytes(){
    const id=$('soundfont-select').value;
    if(!id)return null;
    if(state.fontCache?.id===id)return state.fontCache.bytes;
    const font=fonts.get(id);
    if(!font||font.size>midiCore.MAX_FONT)
      throw Error('SoundFont ไม่พบหรือใหญ่เกินขอบเขตความจำ 256 MB');
    $('soundfont-status').textContent='กำลังตรวจโครงสร้าง SoundFont '+font.name+'…';
    const bytes=new Uint8Array(await font.arrayBuffer());
    midiRuntime.parseFont(bytes);
    if($('soundfont-select').value!==id)throw Error('เปลี่ยน SoundFont ระหว่างโหลด · กรุณาเริ่มใหม่');
    state.fontCache={id,bytes};
    updateFontStatus();
    return bytes;
  }
  async function renderMidiWave(song,{signal=null,onStatus=null}={}){
    const info=song.midiInfo||await midiCore.inspectSong(song,midiRuntime);
    song.midiInfo=info;
    const capacity=updateMidiResource(info);
    if(!capacity.ok)throw Error(capacity.reason);
    const bytes=new Uint8Array(await song.midi.arrayBuffer());
    const sf=await fontBytes();
    if(signal?.aborted)throw Error('ยกเลิก MIDI แล้ว');
    return midiRuntime.render(bytes,{fontBytes:sf,signal,onStatus,...midiMixerOptions()});
  }
  async function previewMidi(){
    const song=entries.get(state.active);
    if(!song||!usesMidi(song)||state.busy||state.renderingMidi)return;
    if(!song.midiInfo)return notice('ยังตรวจ MIDI/NCN ไม่สำเร็จ','error');
    const sequence=++state.midiRenderSequence;
    const controller=new AbortController();
    state.midiController=controller;state.renderingMidi=true;
    $('preview-midi').disabled=true;$('stop-midi').disabled=false;
    $('midi-status').textContent='กำลังเตรียม SoundFont/โน้ต MIDI…';
    try{
      const output=await renderMidiWave(song,{signal:controller.signal,
        onStatus:message=>{$('midi-status').textContent=message;}});
      if(sequence!==state.midiRenderSequence||state.active!==song.id||controller.signal.aborted)return;
      if(state.previewURL)URL.revokeObjectURL(state.previewURL);
      state.previewURL=URL.createObjectURL(output.audio);
      $('player').src=state.previewURL;
      $('insert-time').disabled=false;
      $('midi-status').textContent='สังเคราะห์เสียงแล้ว · เล่น/เลื่อนเวลาเพื่อดูเนื้อร้องตาม MIDI/CUR';
      await $('player').play();
    }catch(error){
      if(sequence===state.midiRenderSequence&&!controller.signal.aborted)
        notice('ทดลองฟัง MIDI ไม่สำเร็จ: '+error.message,'error');
    }finally{
      if(sequence===state.midiRenderSequence){
        state.renderingMidi=false;state.midiController=null;
        $('preview-midi').disabled=false;$('stop-midi').disabled=true;
      }
    }
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
    if (song.midi && usesMidi(song)) {
      const info=song.midiInfo||await midiCore.inspectSong(song,midiRuntime);
      song.midiInfo=info;
      if(!info.safe)throw Error(info.warning||'NCN มีเวลาไม่ปลอดภัย · ข้ามไฟล์นี้');
      const inputKind=extOf(song.midi.name);
      if($('export-format').value==='m4a'){
        const audio=await renderMidiWave(song,{onStatus:message=>setProgress(
          message,100*state.currentIndex/Math.max(1,state.total))});
        if(state.cancelled)throw Error('ยกเลิกโดยผู้ใช้');
        // Only a separate output file is converted; original MIDI stays intact.
        const waveFile=new File([audio.audio],name+'.wav',{type:'audio/wav'});
        const m4a=await renderAudio({audio:waveFile},number);
        assets.push({name:name+'.m4a',blob:m4a});
      }else{
        assets.push({name:name+'.'+inputKind,blob:song.midi});
        if(info.kind==='NCN'){
          assets.push({name:name+'.lyr',blob:song.lyr},{name:name+'.cur',blob:song.cur});
        }
      }
      const lyrics=await lyricsFor(song);
      let doc=null;
      if(lyrics.trim()){
        doc=(song.editedLyrics||song.lrc)
          ? midiCore.lrcToDocument(lyrics,song.name,'LRC')
          : info.safeLyrics?info.document:null;
      }
      if(doc?.lines?.length){
        assets.push({name:name+'.json',blob:new Blob([JSON.stringify(doc)],
          {type:'application/json'})});
        assets.push({name:name+'.lrc',blob:new Blob([
          lyrics.replace(/\r?\n/g,'\r\n')],{type:'text/plain;charset=utf-8'})});
      }else if(lyrics.trim()){
        throw Error('เนื้อร้องไม่มีเวลา LRC/CUR ที่ยืนยันได้ · ไม่สร้าง JSON เทียม');
      }
      return assets;
    }
    const audioBlob = await renderAudio(song, number);
    if (state.cancelled) throw new Error('ยกเลิกโดยผู้ใช้');
    assets.push({name: name + '.m4a', blob: audioBlob});
    const lyrics = await lyricsFor(song);
    if (lyrics.trim() && parseLrc(lyrics).length) assets.push({
      name: name + '.lrc', blob: new Blob([lyrics.replace(/\r?\n/g, '\r\n')], {type: 'text/plain;charset=utf-8'})
    });
    else if (lyrics.trim())
      log(song.name + ': ข้าม LRC เพราะไม่มีบรรทัดเนื้อร้องพร้อมเวลาที่ถูกต้อง', true);
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
    const work=[...selected].map(id=>entries.get(id)).filter(canExport);
    if(!work.length)return notice('กรุณาเลือกเพลงที่มีชุดไฟล์ครบอย่างน้อยหนึ่งเพลง','error');
    const totalSize=work.reduce((n,e)=>n+(usesMidi(e)?e.midi.size+
      (e.lyr?.size||0)+(e.cur?.size||0):e.audio.size),0);
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
    let success = 0, errors = 0, audioCount = 0, midiCount = 0, lyricCount = 0;
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
          if(usesMidi(song))midiCount++;else audioCount++;
          if(assets.some(asset=>asset.name.toLowerCase().endsWith('.lrc')))lyricCount++;
          else log('ส่งออก '+song.name+' โดยไม่มีคำร้องพร้อมเวลาจริง · ไม่สร้าง LRC/JSON เทียม',true);
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
          ? 'สร้างเพลงเสียง '+audioCount+' · MIDI/NCN '+midiCount+' · มี LRC '+lyricCount+
            ' · ข้ามรายการผิดปกติ '+errors+
            (state.archive?' · กด “ดาวน์โหลด ZIP ผลลัพธ์”':' · บันทึกลงโฟลเดอร์ที่เลือกแล้ว')
          : 'สร้างเพลงไม่สำเร็จ · ตรวจรายละเอียดข้อผิดพลาดด้านล่าง',
          errors||!success?'error':'good');
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
    if(state.midiController)state.midiController.abort();
    try { state.ffmpeg?.terminate(); } catch (_) { /* ignore */ }
    state.ffmpeg = null;
    $('engine-caption').textContent = 'Engine ถูกหยุด สามารถโหลดใหม่ได้';
    $('load-engine').textContent = '↓ ดาวน์โหลด Web Engine';
    notice('ได้รับคำสั่งหยุด · กำลังยุติงานปัจจุบัน', 'error');
  }
  function setupMidiMixer(){
    const panel=$('midi-channels');
    panel.replaceChildren();
    for(let channel=0;channel<16;channel++){
      const row=document.createElement('div');row.className='midi-channel';
      const title=document.createElement('strong');
      title.textContent='ช่อง '+(channel+1)+(channel===9?' กลอง':'');
      const muted=document.createElement('label');
      const toggle=document.createElement('input');
      toggle.type='checkbox';toggle.checked=false;toggle.dataset.channelMute=String(channel);
      const muteText=document.createElement('span');muteText.textContent='ปิด';
      muted.append(toggle,muteText);
      const volume=document.createElement('input');
      volume.type='range';volume.min='0';volume.max='100';volume.step='5';volume.value='100';
      volume.dataset.channelVolume=String(channel);
      volume.setAttribute('aria-label','ระดับเสียงช่อง '+(channel+1));
      const indicator=document.createElement('output');indicator.textContent='100%';
      toggle.addEventListener('change',()=>{
        state.channelMutes[channel]=toggle.checked;invalidateArchive();
        $('midi-status').textContent='มิกเซอร์เปลี่ยนแล้ว · กดสังเคราะห์ใหม่เพื่อฟัง';
      });
      volume.addEventListener('input',()=>{
        state.channelVolumes[channel]=Number(volume.value)/100;
        indicator.textContent=volume.value+'%';invalidateArchive();
        $('midi-status').textContent='มิกเซอร์เปลี่ยนแล้ว · กดสังเคราะห์ใหม่เพื่อฟัง';
      });
      row.append(title,muted,volume,indicator);panel.appendChild(row);
    }
  }
  setupMidiMixer();
  $('choose-soundfont').addEventListener('click',()=>$('soundfont-input').click());
  $('soundfont-input').addEventListener('change',event=>{
    void addFiles([...event.target.files]).catch(error=>notice(error.message,'error'));
    event.target.value='';
  });
  $('soundfont-select').addEventListener('change',()=>{
    state.fontID=$('soundfont-select').value;state.fontCache=null;
    invalidateArchive();updateFontStatus();
    const active=entries.get(state.active);
    if(active?.midiInfo&&usesMidi(active))updateMidiResource(active.midiInfo);
    $('midi-status').textContent='SoundFont เปลี่ยนแล้ว · กดสังเคราะห์ใหม่เพื่อฟัง';
  });
  $('midi-transpose').addEventListener('change',()=>{
    const input=$('midi-transpose');
    input.value=String(Math.max(-12,Math.min(12,Math.round(Number(input.value)||0))));
    invalidateArchive();
    $('midi-status').textContent='คีย์เปลี่ยนแล้ว · กดสังเคราะห์ใหม่เพื่อฟัง';
  });
  $('reset-midi-mixer').addEventListener('click',()=>{
    state.channelMutes.fill(false);state.channelVolumes.fill(1);
    $('midi-transpose').value='0';
    for(const input of document.querySelectorAll('[data-channel-mute]'))input.checked=false;
    for(const input of document.querySelectorAll('[data-channel-volume]')){
      input.value='100';input.closest('.midi-channel').querySelector('output').textContent='100%';
    }
    invalidateArchive();$('midi-status').textContent='คืนค่ามิกเซอร์ 16 ช่องแล้ว';
  });
  $('preview-midi').addEventListener('click',()=>{void previewMidi();});
  $('stop-midi').addEventListener('click',()=>stopMidiPreview());
  $('export-format').addEventListener('change',()=>{
    invalidateArchive();
    notice($('export-format').value==='xstage'
      ? 'ส่งออก MIDI/KAR เดิมทุกไบต์ + Lyrics JSON โดยไม่แปลงเสียง'
      : 'MIDI จะสังเคราะห์ผ่าน SoundFont แล้วแปลงเป็น M4A · ต้องมี RAM และ FFmpeg เพียงพอ');
  });
  const stepLinks=[...document.querySelectorAll('.navigation a[href^="#"]')];
  for(const link of stepLinks){
    link.addEventListener('click',()=>{
      for(const item of stepLinks){item.classList.toggle('active',item===link);
        if(item===link)item.setAttribute('aria-current','step');
        else item.removeAttribute('aria-current');}
    });
  }
  $('choose-files').addEventListener('click', () => $('file-input').click());
  $('choose-folder').addEventListener('click', () => {void chooseFolder();});
  $('file-input').addEventListener('change',e=>{
    void addFiles([...e.target.files]).catch(error=>notice('นำเข้าไม่สำเร็จ: '+error.message,'error'));
    e.target.value='';
  });
  $('folder-input').addEventListener('change',e=>{
    void addFiles([...e.target.files]).catch(error=>notice('นำเข้าไม่สำเร็จ: '+error.message,'error'));
    e.target.value='';
  });
  $('clear-all').addEventListener('click', () => {
    stopMidiPreview(false);
    if (state.previewURL) URL.revokeObjectURL(state.previewURL);
    state.previewURL = '';
    $('player').pause(); $('player').removeAttribute('src'); $('player').load();
    entries.clear(); selected.clear(); state.active = null;
    state.fontCache=null;fonts.clear();refreshFontChoices();
    $('midi-workspace').hidden=true;
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
    for(const e of entries.values())if(canExport(e))selected.add(e.id);
    invalidateArchive();renderTable();
  });
  $('deselect-all').addEventListener('click',()=>{selected.clear();invalidateArchive();renderTable();});
  $('player').addEventListener('timeupdate', syncActiveLyric);
  $('insert-time').addEventListener('click', () => {
    if (!state.active) return;
    const el = $('lyrics-text');
    const tag = stamp($('player').currentTime);
    const index = el.selectionStart, prefix = el.value.slice(0, index), suffix = el.value.slice(index);
    el.value = prefix + tag + suffix;
    el.focus(); el.setSelectionRange(index + tag.length, index + tag.length);
    entries.get(state.active).lyricsText = el.value;
    entries.get(state.active).editedLyrics=true;invalidateArchive();
  });
  $('lyrics-text').addEventListener('input',()=>{
    if(state.active){
      const song=entries.get(state.active);
      song.lyricsText=$('lyrics-text').value;song.editedLyrics=true;
      invalidateArchive();
    }
  });
  $('save-lyrics').addEventListener('click', () => {
    if (!state.active) return;
    entries.get(state.active).lyricsText = $('lyrics-text').value;
    invalidateArchive();
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
  drop.addEventListener('drop',event=>{
    void addFiles([...event.dataTransfer.files]).catch(error=>notice('นำเข้าไม่สำเร็จ: '+error.message,'error'));
  });
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
  refreshFontChoices();
  renderTable();
  if (typeof window.showDirectoryPicker !== 'function') {
    $('pick-destination').disabled = true;
    $('pick-destination').title = 'เบราว์เซอร์นี้ใช้การดาวน์โหลด ZIP แทน';
  }
})();
