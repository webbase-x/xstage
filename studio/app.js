/* A single, identical control interface for X-Stage Song Studio PC and Web.
 * All filesystem/audio/Drive operations execute on the authenticated local
 * Python engine. The browser never exposes a Drive refresh token or music. */
'use strict';
(() => {
  const $ = id => document.getElementById(id);
  // The same UI is hosted on GitHub Pages and bundled with the Windows app.
  // A public page can only control the engine running ON THIS PC after the PC
  // launcher opens an authenticated pairing URL. No song or OAuth token is
  // stored on GitHub Pages; session capability stays in JS memory only.
  const onlinePage = location.hostname === 'webbase-x.github.io'
    && location.pathname.startsWith('/xstage/studio/');
  const fragment = new URLSearchParams(location.hash.replace(/^#/, ''));
  const tokenFromUrl = fragment.get('auth') || '';
  const engineCandidate = fragment.get('engine') || '';
  const engineBase = onlinePage ? (function(){
    try {
      const candidate = new URL(engineCandidate);
      if (candidate.protocol !== 'http:' || candidate.hostname !== '127.0.0.1'
          || !candidate.port || candidate.username || candidate.password
          || candidate.pathname !== '/' || candidate.search || candidate.hash) return '';
      return candidate.origin;
    }catch{return '';}
  })() : location.origin;
  const token = tokenFromUrl || (!onlinePage ? sessionStorage.getItem('xstage-songstudio-session') || '' : '');
  if (tokenFromUrl) {
    if (!onlinePage) sessionStorage.setItem('xstage-songstudio-session', tokenFromUrl);
    history.replaceState(null, '', location.pathname + location.search);
  }
  function engineAddress(path) { return (engineBase || location.origin) + path; }
  function connectionGate(text='') {
    const gate = $('online-connection-gate');
    if (!gate) return;
    gate.hidden = false;
    $('online-connection-help').textContent = text || (onlinePage
      ? 'เปิด X-Stage Song Studio บน PC และกด “เปิด Web Control” เพื่อเชื่อมต่ออย่างปลอดภัย'
      : 'กรุณาเปิด Song Studio ผ่านโปรแกรม Windows');
    $('engine-state').textContent = 'ยังไม่เชื่อมต่อ Engine';
  }

  const tabNames = {
    create: ['สร้างเพลงใหม่', 'เตรียมต้นฉบับให้ครบในเครื่องก่อนเริ่มสร้าง M4A'],
    upload: ['อัปโหลด', 'ตรวจไฟล์ซ้ำบน Google Drive · ส่งเฉพาะเพลงที่เปลี่ยน'],
    download: ['ดาวน์โหลด', 'กู้คืน Song / DB / ZIP ผ่านบัญชี Google ของคุณ'],
    settings: ['ตั้งค่า', 'ทุกการตั้งค่าใช้ร่วมกันทั้งแอป PC และหน้าเว็บ']
  };
  const selected = new Set();
  let activeTab = 'create';
  let page = 0, pageSize = 100, total = 0, search = '', searchTimer = 0;
  let songs = [], prefs = {}, googleConnected = false;
  let lastJobId = '', lastJobState = 'idle', refreshTimer = 0;
  let busy = false, editingId = null, notificationTimer = null;
  const previewAudio = $('preview-audio');

  async function api(path, opts = {}) {
    if (!engineBase || !token) throw new Error('กรุณาเชื่อมต่อ Local Engine บน PC จากเมนู “เปิด Web Control”');
    const response = await fetch(engineAddress(path), {
      cache: 'no-store', credentials: onlinePage ? 'omit' : 'same-origin',
      mode: onlinePage ? 'cors' : 'same-origin',
      ...opts,
      headers: {'X-XStage-Token': token, ...(opts.body ? {'Content-Type': 'application/json'} : {}), ...(opts.headers || {})}
    });
    const text = await response.text();
    let payload;
    try { payload = text ? JSON.parse(text) : {}; } catch { payload = {error: 'รูปแบบข้อมูลจาก Local Engine ไม่ถูกต้อง'}; }
    if (!response.ok) throw new Error(payload.error || 'Local Engine ไม่ตอบรับคำสั่ง');
    return payload;
  }
  const post = (path, data) => api(path, {method: 'POST', body: JSON.stringify(data)});
  const fmtNum = n => Number(n || 0).toLocaleString('th-TH');
  const fmtSize = n => {
    let size = Number(n) || 0;
    for (const unit of ['B', 'KB', 'MB', 'GB', 'TB']) {
      if (size < 1024 || unit === 'TB') return size.toFixed(unit === 'B' ? 0 : 1) + ' ' + unit;
      size /= 1024;
    }
  };
  const fmtTime = seconds => {
    if (!Number.isFinite(seconds) || seconds < 0) return '—';
    const n = Math.floor(seconds); return String(Math.floor(n / 60)).padStart(2, '0') + ':' + String(n % 60).padStart(2, '0');
  };
  function escapeHTML(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
  }
  function message(text, isError = true) {
    const box = $('global-message'); box.textContent = String(text || '');
    box.hidden = !text; box.style.borderColor = isError ? '#c45b70' : '#329c8d';
    clearTimeout(notificationTimer);
    if (text) notificationTimer = setTimeout(() => {box.hidden = true;}, isError ? 9500 : 5000);
  }
  function tab(name) {
    if (!tabNames[name]) return;
    activeTab = name;
    for (const button of document.querySelectorAll('.nav-button')) {
      const current = button.dataset.tab === name;
      button.classList.toggle('active', current);
      if (current) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
    }
    for (const element of document.querySelectorAll('.tab')) {
      element.classList.toggle('active', element.id === 'tab-' + name);
    }
    $('page-title').textContent = tabNames[name][0];
    $('page-subtitle').textContent = tabNames[name][1];
    document.title = `${tabNames[name][0]} · X-Stage Song Studio`;
    if (name === 'settings') void refreshEnvironment();
  }
  function setFields() {
    $('create-source').value = prefs.source || '';
    $('create-workspace').value = prefs.workspace || '';
    $('download-destination').value = prefs.download || '';
    $('settings-oauth').value = prefs.oauth || '';
    $('create-preset').value = prefs.midi_preset || 'balanced';
    $('create-mode').value = prefs.mode || 'original';
  }
  function soundfontOptions(items) {
    const chooser = $('create-soundfont'); const current = prefs.soundfont || '';
    chooser.replaceChildren(new Option('ยังไม่ได้เลือก SoundFont', ''));
    for (const path of items || []) chooser.add(new Option(path.split(/[\\/]/).slice(-1)[0], path));
    if (current && ![...chooser.options].some(o => o.value === current)) chooser.add(new Option(current, current));
    chooser.value = current;
  }
  function presetOptions(items) {
    const control = $('create-preset'); control.replaceChildren();
    for (const p of items || []) control.add(new Option(p.label, p.value));
    control.value = prefs.midi_preset || 'balanced';
  }
  function setGoogle(google) {
    googleConnected = !!google?.connected;
    const badge = $('google-badge');
    badge.classList.toggle('offline', !googleConnected);
    const label = googleConnected ? `เชื่อม Google · ${google.email}` : 'ยังไม่เชื่อม Google';
    badge.innerHTML = '<span class="small-dot"></span>' + escapeHTML(label);
    $('upload-google-state').textContent = googleConnected ? google.email + ' · พร้อมอัปโหลด' : 'กรุณาเชื่อม Google ก่อนอัปโหลด';
    $('google-login-header').textContent = googleConnected ? 'Google ✓' : 'Google Login';
    for (const id of ['upload-button', 'settings-logout']) $(id).disabled = busy || !googleConnected;
    for (const el of document.querySelectorAll('.download-action')) el.disabled = busy || !googleConnected;
  }
  async function loadState({initialize = false} = {}) {
    const data = await api('/api/status');
    busy = data.job?.state === 'running';
    prefs = data.preferences || prefs;
    $('engine-state').textContent = 'พร้อมใช้งานบน PC · เชื่อมต่อแล้ว';
    $('version-info').textContent = `Song Studio v${data.version} · Build ${data.build}`;
    $('update-version').textContent = data.update?.status === 'available'
       ? `มีรุ่นใหม่ v${data.update.version}` : `v${data.version} / ${data.build}`;
    if (initialize) {
      presetOptions(data.presets); soundfontOptions(data.soundfonts); setFields();
    }
    setGoogle(data.google);
    renderJob(data.job || {});
    updateButtons();
  }
  function updateButtons() {
    $('selected-count').textContent = `เลือกแล้ว ${fmtNum(selected.size)} เพลง`;
    $('upload-selected-count').textContent = `${fmtNum(selected.size)} เพลง`;
    const buttons = ['scan-button','reconcile-button','preview-button','edit-button','build-button',
      'build-audio-button','select-all','select-page','clear-selection','upload-login','settings-login',
      'settings-logout','google-login-header','update-button'];
    for (const name of buttons) $(name).disabled = busy;
    $('build-button').disabled = busy || selected.size === 0;
    $('build-audio-button').disabled = busy || selected.size === 0;
    $('preview-button').disabled = busy || selected.size !== 1;
    $('edit-button').disabled = busy || selected.size !== 1;
    $('upload-button').disabled = busy || !googleConnected || !selected.size;
    $('settings-logout').disabled = busy || !googleConnected;
    for (const el of document.querySelectorAll('.download-action')) el.disabled = busy || !googleConnected;
    for (const el of document.querySelectorAll('[data-pick],.field,.song-table input[type=checkbox]')) el.disabled = busy;
    $('cancel-job').hidden = !busy;
  }
  async function refreshSongs() {
    const data = await api('/api/songs?limit=' + pageSize + '&offset=' + (page * pageSize) + '&search=' + encodeURIComponent(search));
    songs = data.rows || []; total = data.total || 0;
    const rows = $('song-rows'); rows.replaceChildren();
    if (!songs.length) rows.innerHTML = '<tr><td colspan="5" class="empty-row">ไม่พบเพลงในรายการ · เลือกโฟลเดอร์และกดตรวจสอบไฟล์เพลง</td></tr>';
    for (const song of songs) {
      const tr = document.createElement('tr');
      tr.className = selected.has(song.id) ? 'selected' : '';
      tr.dataset.id = song.id;
      const status = String(song.status || 'new');
      const title = escapeHTML(song.title || 'ไม่ระบุชื่อ');
      const artist = song.artist ? ' · ' + escapeHTML(song.artist) : '';
      tr.innerHTML = `<td><input type="checkbox" class="song-check" aria-label="เลือก ${title}" ${selected.has(song.id) ? 'checked' : ''}></td>` +
       `<td><span class="song-name">${title}</span>${artist}<span class="song-code">${escapeHTML(song.code || '')}</span></td>` +
       `<td>${escapeHTML(song.kind || '')}</td><td>${fmtSize(song.size)}</td><td><span class="status-pill ${/^[a-z-]+$/.test(status)?status:''}">${escapeHTML(status)}</span></td>`;
      rows.append(tr);
    }
    $('catalog-total').textContent = fmtNum(total) + ' เพลง';
    $('table-page-label').textContent = `${total ? fmtNum(page * pageSize + 1) : 0}–${fmtNum(Math.min(total, (page + 1) * pageSize))} จาก ${fmtNum(total)} เพลง`;
    $('page-prev').disabled = page === 0;
    $('page-next').disabled = (page + 1) * pageSize >= total;
    updateButtons();
  }
  function rowSelection(event) {
    const row = event.target.closest('tr[data-id]');
    if (!row) return;
    const id = Number(row.dataset.id);
    if (!id) return;
    if (event.target.matches('input[type=checkbox]')) {
      if (event.target.checked) selected.add(id); else selected.delete(id);
    } else {
      if (selected.has(id)) selected.delete(id); else selected.add(id);
      const checkbox = row.querySelector('input.song-check'); if (checkbox) checkbox.checked = selected.has(id);
    }
    row.classList.toggle('selected', selected.has(id));
    updateButtons();
  }
  async function config(patch) {
    const previousWorkspace = prefs.workspace;
    const response = await post('/api/config', patch);
    prefs = response.preferences || prefs;
    if (patch.workspace && previousWorkspace !== prefs.workspace) { selected.clear(); page = 0; await refreshSongs(); }
    if ('soundfont' in patch || 'workspace' in patch) soundfontOptions(response.soundfonts || []);
    setFields();
    return response;
  }
  const fields = {'create-source': 'source', 'create-workspace': 'workspace',
                  'create-soundfont': 'soundfont', 'create-preset': 'midi_preset',
                  'create-mode': 'mode', 'download-destination': 'download',
                  'settings-oauth': 'oauth'};
  async function saveInputs(keys = Object.keys(fields)) {
    const payload = {};
    for (const id of keys) payload[fields[id]] = $(id).value.trim();
    await config(payload);
  }
  async function pick(kind) {
    const response = await post('/api/folder-picker', {kind});
    if (!response.path) return;
    const field = ({source:'create-source',workspace:'create-workspace',soundfont:'create-soundfont',
        download:'download-destination',oauth:'settings-oauth'})[kind];
    const element = $(field);
    if (kind === 'soundfont') element.add(new Option(response.path.split(/[\\/]/).pop(), response.path));
    element.value = response.path;
    await config({[kind]: response.path});
    message('เลือกและจำตำแหน่งใหม่แล้ว', false);
  }
  async function run(action, options = {}) {
    if (busy) return message('มีงานกำลังทำอยู่ · กรุณารอหรือกดยกเลิกก่อน');
    try {
      const response = await post('/api/jobs', {action, ...options});
      lastJobId = response.id; lastJobState = 'running';
      busy = true; updateButtons();
      await loadState();
      $('job-panel').scrollIntoView({behavior:'smooth',block:'nearest'});
    } catch (error) { message(error.message); }
  }
  const selectedIDs = () => [...selected];
  async function startBuild(audioOnly) {
    if (!selected.size) return message('กรุณาเลือกเพลงก่อนสร้าง');
    try {
      await saveInputs(['create-source','create-soundfont','create-preset','create-mode']);
      const estimate = await post('/api/estimate', {ids:selectedIDs()});
      if (!estimate.enoughDisk) return message('พื้นที่ว่างในเครื่องไม่เพียงพอสำหรับเก็บไฟล์ที่เลือกก่อนสร้าง');
      if (estimate.warning && !confirm(`รายการใหญ่ ${fmtNum(estimate.songs)} เพลง (${fmtSize(estimate.bytes)})\nอาจใช้เวลาเตรียมและสร้างนาน ต้องการทำต่อหรือไม่?`)) return;
      if (!confirm(`ยืนยันสร้างจาก ${fmtNum(estimate.songs)} เพลง (${fmtSize(estimate.bytes)})?\nระบบจะคัดลอกต้นฉบับที่เลือกและตรวจความสมบูรณ์ในเครื่องก่อนเริ่มแปลงทุกเพลง`)) return;
      await run('build', {ids:selectedIDs(), audio_only:audioOnly});
    } catch (error) { message(error.message); }
  }
  async function startUpload() {
    if (!googleConnected) return message('ต้อง Google Login ก่อนอัปโหลด');
    if (!selected.size) return message('กลับไปเลือกเพลงที่จะอัปโหลดในหน้า “สร้างเพลงใหม่”');
    if (confirm(`อัปโหลดเฉพาะ ${fmtNum(selected.size)} เพลงที่เลือก โดยตรวจไฟล์ซ้ำบน Drive ก่อนส่ง ใช่หรือไม่?`)) {
      await run('upload',{ids:selectedIDs()});
    }
  }
  async function startDownload(kind) {
    if (!googleConnected) return message('ต้อง Google Login ก่อนดาวน์โหลด');
    try {
      await saveInputs(['download-destination']);
      const labels = {songs:'โฟลเดอร์เพลง',db:'ฐานข้อมูล DB',zip:'ZIP สำรองทั้งชุด'};
      if (!confirm(`ดาวน์โหลด ${labels[kind]} ไปที่\n${prefs.download}\n\nไฟล์เดิมที่มีเนื้อหาต่างกันจะไม่ถูกเขียนทับ ยืนยันหรือไม่?`)) return;
      await run('download',{kind});
    } catch (error) { message(error.message); }
  }
  function renderJob(job) {
    const state = job.state || 'idle';
    const isRunning = state === 'running';
    const led = $('job-led');led.className = 'job-led ' + (/^(idle|running|error|success|cancelled)$/.test(state) ? state : 'idle');
    const stage = job.stage || 'พร้อมใช้งาน';
    $('job-title').textContent = (isRunning ? '● ' : '') + stage + (state === 'error' ? ' · ผิดพลาด' : '');
    $('job-detail').textContent = job.detail || 'ไม่มีงานที่กำลังประมวลผล';
    $('job-timing').textContent = fmtTime(job.elapsed || 0);
    const fraction = Number(job.total)>0 ? Number(job.completed) / Number(job.total) :
      Number(job.bytesTotal)>0 ? Number(job.bytesDone)/Number(job.bytesTotal) : null;
    const fill = $('progress-fill');
    fill.classList.toggle('indeterminate', isRunning && fraction === null);
    fill.style.width = fraction !== null ? Math.max(0,Math.min(100,100*fraction)).toFixed(1)+'%' : (isRunning?'33%':'0%');
    $('job-fraction').textContent = Number(job.total)>0 ? `${fmtNum(job.completed)} / ${fmtNum(job.total)} รายการ · ${Math.round(fraction*100)}%`:
      Number(job.bytesTotal)>0?`${fmtSize(job.bytesDone)} / ${fmtSize(job.bytesTotal)} · ${Math.round(fraction*100)}%`:
      isRunning ? 'กำลังดำเนินการ · ยังไม่ทราบเปอร์เซ็นต์' : state === 'success' ? 'เสร็จสิ้น' : 'รอเริ่มงาน';
    $('job-eta').textContent = isRunning
      ? `เวลาคงเหลือประมาณ ${job.eta !== null ? fmtTime(job.eta) : '—'} · ${job.idleFor > 7 ? `ยังทำงานอยู่ ${job.idleFor} วินาที` : 'สถานะสด'}`
      : state === 'success' ? 'งานสำเร็จ' : state === 'error' ? 'ตรวจ Log ข้อผิดพลาด' : 'พร้อม';
    const list = $('job-log'); list.replaceChildren();
    for (const item of job.logs || []) {const li=document.createElement('li');li.textContent=item;list.append(li);}
  }
  async function poll() {
    try {
      const response = await api('/api/status');
      const job = response.job || {};
      const beforeBusy = busy;
      busy = job.state === 'running';
      setGoogle(response.google);
      renderJob(job);updateButtons();
      if (job.id && (job.id !== lastJobId || (lastJobState !== job.state && !busy))) {
        lastJobId = job.id;
        if (!busy) {
          if (job.state === 'success') {
            if (job.kind === 'preview' && job.result?.ticket) {
              const t = encodeURIComponent(job.result.ticket);
              previewAudio.pause(); previewAudio.src = engineAddress('/api/preview?ticket=' + encodeURIComponent(t));
              $('preview-label').textContent = 'ตัวอย่างเสียงพร้อม · กด ▶ เพื่อฟัง';
              previewAudio.play().catch(()=>{});
            } else if (job.kind === 'check-update') {
              message(job.result?.message || (job.result?.update ? 'พบเวอร์ชันใหม่: ' + job.result.version : 'ยังไม่มี Installer รุ่นใหม่'), false);
            } else message(job.result?.message || 'ดำเนินการสำเร็จ · '+job.kind, false);
          } else if (job.state === 'error') message(job.detail || 'งานไม่สำเร็จ');
          if (['scan','build','upload','download'].includes(job.kind)) await refreshSongs();
        }
      }
      lastJobState = job.state;
      if (beforeBusy && !busy) {
        const stateData = response.preferences || {};
        prefs = stateData; soundfontOptions(response.soundfonts || []);
      }
    } catch (error) {
      $('engine-state').textContent = 'การเชื่อมต่อ Local Engine หลุด · กำลังลองใหม่';
      $('job-title').textContent = 'กำลังเชื่อมต่อ Local Engine อีกครั้ง';
    }
  }
  async function refreshEnvironment() {
    try {
      const status = await api('/api/environment');
      const root = $('environment-list');root.replaceChildren();
      for (const [name, ready] of Object.entries(status)) {
        const line = document.createElement('div');line.className = 'env-item';
        line.innerHTML = `<span>${escapeHTML(name)}</span><strong class="${ready ? '' : 'missing'}">${ready ? 'พร้อมใช้งาน' : 'ไม่พร้อม'}</strong>`;
        root.append(line);
      }
    } catch(error) {message(error.message);}
  }
  async function openEdit() {
    if (selected.size !== 1) return;
    const id = [...selected][0];
    try {
      const row = await api('/api/song/' + id);
      editingId = id;
      $('edit-code').textContent = row.code + ' · ' + (row.kind || '');
      $('edit-title').value = row.title || '';
      $('edit-artist').value = row.artist || '';
      $('edit-lyrics').value = row.lyrics_edit || '';
      $('edit-dialog').showModal();
    } catch(error) {message(error.message);}
  }
  async function saveEdit() {
    if (!editingId) return;
    try {
      await post('/api/song/' + editingId, {
        title:$('edit-title').value, artist:$('edit-artist').value,
        lyrics:$('edit-lyrics').value
      });
      await refreshSongs();
      message('บันทึกข้อมูลเพลงและเนื้อร้องแล้ว',false);
    }catch(error){message(error.message);}
  }
  async function initialize() {
    if (!token || !engineBase) {
      connectionGate();
      return;
    }
    if (onlinePage && !window.__xstageConnectedByUser) {
      // Modern browsers require a user gesture for loopback-network access.
      connectionGate('เชื่อมต่อ Engine บน PC เครื่องนี้ · เบราว์เซอร์อาจถามสิทธิ์เข้าถึงอุปกรณ์ในเครื่อง ให้กดอนุญาต');
      return;
    }
    try {
      await loadState({initialize:true}); await refreshSongs();
      await refreshEnvironment();
      refreshTimer = window.setInterval(poll, 900);
      // Connected workspace and authenticated web view use the exact same UI.
      $('engine-state').textContent = 'เชื่อมต่อสำเร็จ · พร้อมประมวลผล';
      $('online-connection-gate').hidden = true;
      if (onlinePage) $('open-web').hidden = true;
    } catch(error) {
      connectionGate('เชื่อมต่อไม่สำเร็จ: '+error.message+' · ตรวจว่า PC ยังเปิด Song Studio อยู่ และอนุญาตการเข้าถึง Local Network ในเบราว์เซอร์');
    }
  }
  $('online-connect-now')?.addEventListener('click',()=>{
    window.__xstageConnectedByUser = true;
    void initialize();
  });
  if (onlinePage) $('open-web').hidden = true;
  for (const el of document.querySelectorAll('.nav-button')) el.addEventListener('click',()=>tab(el.dataset.tab));
  $('song-rows').addEventListener('click', rowSelection);
  $('select-page').addEventListener('click',()=>{for (const song of songs) selected.add(song.id);void refreshSongs();});
  $('clear-selection').addEventListener('click',()=>{selected.clear();void refreshSongs();});
  $('select-all').addEventListener('click',async()=>{
    try {
      const result = await api('/api/songs/ids?search='+encodeURIComponent(search));
      if (result.ids.length > 1000 && !confirm(`พบ ${fmtNum(result.ids.length)} เพลงที่ตรงเงื่อนไข ต้องการเลือกทั้งหมดจริงหรือไม่?`)) return;
      for (const id of result.ids) selected.add(id);
      await refreshSongs();
    }catch(error){message(error.message);}
  });
  $('song-search').addEventListener('input',()=>{
    clearTimeout(searchTimer);
    searchTimer = setTimeout(()=>{search=$('song-search').value.trim();page=0;void refreshSongs();},220);
  });
  $('page-prev').addEventListener('click',()=>{if(page>0){page--;void refreshSongs();}});
  $('page-next').addEventListener('click',()=>{if((page+1)*pageSize<total){page++;void refreshSongs();}});
  for(const [id] of Object.entries(fields)) $(id).addEventListener('change',async()=>{
    try {await saveInputs([id]);} catch(error){message(error.message);}
  });
  for (const el of document.querySelectorAll('[data-pick]')) el.addEventListener('click',()=>pick(el.dataset.pick).catch(e=>message(e.message)));
  $('scan-button').addEventListener('click',async()=>{
    try{await saveInputs(['create-source']);await run('scan');}catch(e){message(e.message);}
  });
  $('reconcile-button').addEventListener('click',async()=>{
    try{await saveInputs(['create-source']);await run('scan');}catch(e){message(e.message);}
  });
  $('build-button').addEventListener('click',()=>{void startBuild(false);});
  $('build-audio-button').addEventListener('click',()=>{void startBuild(true);});
  $('preview-button').addEventListener('click',async()=>{
    try{await saveInputs(['create-soundfont','create-preset']);previewAudio.pause();await run('preview',{ids:selectedIDs()});}
    catch(error){message(error.message);}
  });
  $('edit-button').addEventListener('click',()=>{void openEdit();});
  $('edit-dialog').addEventListener('close',event=>{if($('edit-dialog').returnValue==='save')void saveEdit();});
  for (const button of [$('upload-login'),$('settings-login'),$('google-login-header')]) button.addEventListener('click',async()=>{
    try{await saveInputs(['settings-oauth']);await run('login');}catch(e){message(e.message);}
  });
  $('settings-logout').addEventListener('click',()=>{if(confirm('ออกจากบัญชี Google ใน Song Studio ใช่หรือไม่?'))void run('logout');});
  $('upload-button').addEventListener('click',()=>{void startUpload();});
  $('go-create').addEventListener('click',()=>tab('create'));
  for(const button of document.querySelectorAll('.download-action')) button.addEventListener('click',()=>{void startDownload(button.dataset.kind);});
  $('refresh-environment').addEventListener('click',()=>{void refreshEnvironment();});
  $('open-web').addEventListener('click',async()=>{
    try {await post('/api/open-browser',{});message('เปิด Web Control ด้วย Local Engine ชุดเดียวกันแล้ว',false);}
    catch(e){message(e.message);}
  });
  $('update-button').addEventListener('click',()=>{void run('check-update');});
  $('cancel-job').addEventListener('click',async()=>{
    try{await post('/api/jobs/cancel',{});message('รับคำสั่งยกเลิกแล้ว · กำลังหยุดอย่างปลอดภัย',false);}catch(e){message(e.message);}
  });
  $('toggle-log').addEventListener('click',()=>{
    const log = $('job-log');log.hidden=!log.hidden;
    $('toggle-log').setAttribute('aria-expanded',String(!log.hidden));
    $('toggle-log').textContent=log.hidden?'รายละเอียด ▾':'ซ่อนรายละเอียด ▴';
  });
  void initialize();
})();