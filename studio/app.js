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
    create: ['MIDI to .XSK', 'เลือกต้นทาง ปลายทาง จำนวนหลักรหัสและสร้างโดยตรวจเพลงซ้ำ'],
    'ai-lyrics': ['Lyrics AI', 'นำเข้าเสียง/วิดีโอ · อ่านคำร้องจากไฟล์หรือสร้างด้วย AI · แก้เวลา · พรีวิว'],
    'json-pro': ['MIDI to Lyrics JSON', 'Pro · ส่งออก MIDI/เพลงพร้อม Lyrics JSON และ Catalog'],
    'lyric-head-tail': ['แก้ไข Lyrics JSON', '2 บรรทัดแรกและท้าย · จัดกลุ่ม · แทนที่ · ย้อนคืน'],
    upload: ['นำเข้า X-Stage Karaoke Online', 'ส่งเพลงขึ้น Google Drive ส่วนตัว · ตรวจรายการซ้ำก่อนเผยแพร่'],
    'pc-export': ['นำเข้า X-Stage Karaoke PC', 'นำเข้า AUDIO + LYRICS พร้อมสร้าง/อัปเดต songs.sqlite3 ตาม Karaoke PC'],
    download: ['ดาวน์โหลด', 'กู้คืน Song / DB / ZIP ผ่านบัญชี Google ของคุณ'],
    settings: ['ตั้งค่า', 'ทุกการตั้งค่าใช้ร่วมกันทั้งแอป PC และหน้าเว็บ']
  };
  const selected = new Set();
  let activeTab = 'create';
  let page = 0, pageSize = 100, total = 0, search = '', searchTimer = 0;
  let songs = [], prefs = {}, googleConnected = false, googleConfigured = false;
  let lastJobId = '', lastJobState = 'idle', refreshTimer = 0;
  // A finished build offers uploading once per job, never automatically.
  const promptedBuildUploadJobs = new Set();
  let proEnabled = false;
  let busy = false, cancellationPending = false, editingId = null, notificationTimer = null;
  let activeJobs = [], parallelCapacity = {parallelLimit:1,active:0,freeSlots:1};
  const parallelGroup = action => {
    if (['scan','build','xsk-stream','json-pro-export','created-xsk',
         'pc-export','download','lyric-groups-scan','lyric-groups-replace',
         'lyric-groups-undo'].includes(action)) return 'library';
    if (['ai-lyrics','ai-align','ai-separate-vocals','ai-export','preview'].includes(action)) return 'audio-ai';
    if (['upload','upload-folder','upload-soundfont','login','logout',
         'check-update','download-update'].includes(action)) return 'network';
    if (action === 'install-update') return 'installer';
    return 'exclusive';
  };
  function canLaunch(action) {
    const active=activeJobs.filter(job=>job.state==='running');
    if(!active.length) return true;
    const group=parallelGroup(action);
    if(group==='exclusive'||group==='installer'||active.some(job=>
       ['exclusive','installer'].includes(parallelGroup(job.kind))))return false;
    if(active.some(job=>parallelGroup(job.kind)===group))return false;
    return active.length < (parallelCapacity.parallelLimit||1);
  }
  function renderParallelJobs() {
    const root=$('parallel-job-list');
    root.replaceChildren();
    const active=activeJobs.filter(job=>job.state==='running');
    const slots=parallelCapacity.parallelLimit||1;
    const ram=parallelCapacity.memoryAvailableBytes;
    const lowRam=Number.isFinite(ram)&&ram<1024**3;
    const cpuPercent=parallelCapacity.cpuBusyPercent;
    $('parallel-job-summary').textContent='ทำงานพร้อมกัน '+active.length+'/'+slots+
      ' งาน · CPU '+(parallelCapacity.cpuCores||'—')+' คอร์'+
      (Number.isFinite(cpuPercent)?' · ใช้งาน '+cpuPercent+'%':'')+
      (Number.isFinite(ram)?' · RAM เหลือ '+(ram/1024**3).toFixed(1)+' GB':'')+
      (lowRam?' · ⚠ RAM ต่ำกว่า 1 GB: ยังไม่รับงานใหม่':'')+
      (Number.isFinite(cpuPercent)&&cpuPercent>=92?' · ⚠ CPU สูง':'');
    const completedLatest=[];
    const seenKinds=new Set(active.map(job=>job.kind));
    for(const job of activeJobs){
      if(job.state==='running'||seenKinds.has(job.kind))continue;
      seenKinds.add(job.kind);
      completedLatest.push(job);
      if(completedLatest.length>=3)break;
    }
    const recent=[...active,...completedLatest];
    for(const job of recent){
      const item=document.createElement('div');
      item.className='parallel-job'+(job.state==='running'?'':' parallel-job-finished');
      const detail=document.createElement('div');
      const title=document.createElement('strong');
      title.textContent=job.kind+' · '+(job.stage||(job.state==='running'?'กำลังทำงาน':'เสร็จสิ้น'));
      const subtitle=document.createElement('small');
      subtitle.textContent=job.detail||('รหัสงาน '+job.id);
      detail.append(title,subtitle);
      item.append(detail);
      if(job.state==='success' && job.outputFolder){
        const open=document.createElement('button');
        open.type='button';open.className='button ghost';
        open.textContent='เปิดโฟลเดอร์ปลายทาง';
        open.addEventListener('click',async()=>{
          open.disabled=true;
          try{
            await post('/api/jobs/open-output',{id:job.id});
            message('เปิดโฟลเดอร์ปลายทางของงานที่เสร็จแล้ว',false);
          }catch(error){message(error.message);}
          finally{open.disabled=false;}
        });
        item.append(open);
      }
      if(job.state==='running'){
        const stop=document.createElement('button');
        stop.type='button';stop.className='button ghost';
        stop.textContent=job.stage?.includes('กำลังยกเลิก')?'กำลังหยุด…':'หยุดเฉพาะงาน';
        stop.disabled=stop.textContent==='กำลังหยุด…';
        stop.addEventListener('click',async()=>{
          stop.disabled=true;
          try{await post('/api/jobs/cancel',{id:job.id});await poll();}
          catch(error){stop.disabled=false;message(error.message);}
        });
        item.append(stop);
      }
      root.append(item);
    }
  }

  let createStep = 1;
  const createStepLabels = [
    'เลือกต้นฉบับและสแกนไฟล์',
    'ค้นหาและเลือกเพลง',
    'เลือก SoundFont และทดลองฟัง',
    'ตรวจสอบและสร้างเพลง'
  ];
  const previewAudio = $('preview-audio');
  let previewSongId = null, previewSearchTimer = 0, previewSearchSeq = 0;
  let previewSongRows = [], livePreviewPending = false;
  let previewLyrics = null, previewLyricsSeq = 0, currentLyricIndex = -2;
  let liveStreamId = '', liveControlTimer = 0, liveControlPending = false, liveControlDirty = false;
  let previewSourceSeq = 0, previewPlaySerial = 0, previewPendingChange = false;
  let previewSourceSongId = null, karaokeAnimationFrame = 0;
  let previewClockLast = -1, previewClockStalledAt = 0, previewLyricCoverageWarned = false;
  let aiSongId = null, aiSongs = [], aiOffset = 0, aiTotal = 0;
  let aiSearchTimer = 0, aiSearchSeq = 0, aiDraftSeq = 0;
  let aiStreamId = '', aiPlaySerial = 0, aiDraftReady = false, aiEngineReady = false;
  let aiTimed = [], aiActiveIndex = -2, aiKaraokeFrame = 0;
  let aiSeparationAvailable=false,aiSeparatedPath=null;
  let phraseReady=false,phrasePosition='first',phraseOffset=0,phraseRows=[];
  let phraseSeq=0,phraseSearchTimer=0,phraseBackup=null;
  const MAX_SELECTED_LYRIC_GROUPS=1000;
  const phraseSelected=new Map();
  let phraseSelectionTimer=0;
  let phrasePlan=null,phraseSelectionSeq=0;
  // Keep the owner's pasted words independent from Whisper's guessed text.
  const aiPastedLyrics = new Map();
  let pendingAiAlignment = null;
  let aiDetailsDirty = false;

  // Keep a visible, non-fake heartbeat while any slow API operation is
  // awaiting the Engine. Exclude the regular status polling requests.
  const pendingRequests = new Map();
  let requestSerial=0;
  function updateRequestActivity() {
    const panel=$('request-activity');
    if(!panel)return;
    const now=Date.now();
    const visible=[...pendingRequests.values()].filter(x=>now-x.started>=700);
    panel.hidden=visible.length===0;
    if(!visible.length)return;
    const oldest=visible.reduce((a,b)=>a.started<b.started?a:b);
    const elapsed=Math.floor((now-oldest.started)/1000);
    const seconds=fmtTime(elapsed);
    const warning=elapsed>=60?' · ไม่มีคำตอบกลับเกิน 1 นาที โปรดตรวจสถานะเครื่อง':
      elapsed>=20?' · ยังรอ PC Engine ตอบกลับ':'';
    $('request-activity-text').textContent=
      'กำลังติดต่อ PC Engine '+visible.length+' รายการ · '+oldest.name+
      ' · ผ่านไป '+seconds+warning+' (ไม่ใช่เปอร์เซ็นต์ความคืบหน้า)';
  }
  const requestHeartbeat=setInterval(updateRequestActivity,750);
  function requestLabel(path,method) {
    if(path.includes('/inspect'))return 'ตรวจสอบไฟล์และข้อมูลต้นทาง';
    if(path.includes('/folder-picker'))return 'เปิดหน้าต่างเลือกโฟลเดอร์';
    if(path.includes('/jobs'))return method==='POST'?'ส่งคำสั่งงาน':'อ่านสถานะงาน';
    if(path.includes('/config'))return 'บันทึกการตั้งค่า';
    if(path.includes('/song'))return 'อ่านข้อมูลเพลง';
    return 'อ่านหรือบันทึกข้อมูล';
  }
  async function api(path, opts = {}) {
    if (!engineBase || !token) throw new Error('กรุณาเชื่อมต่อ Local Engine บน PC จากเมนู “เปิด Web Control”');
    const track=!(path === '/api/status' || path.startsWith('/api/status?') ||
      path === '/api/environment' || path.startsWith('/api/environment?'));
    const serial=++requestSerial;
    if(track)pendingRequests.set(serial,{started:Date.now(),name:requestLabel(path,opts.method||'GET')});
    try {
      const response = await fetch(engineAddress(path), {
        cache: 'no-store', credentials: onlinePage ? 'omit' : 'same-origin',
        mode: onlinePage ? 'cors' : 'same-origin',
        ...opts,
        headers: {'X-XStage-Token': token, ...(opts.body ? {'Content-Type': 'application/json'} : {}), ...(opts.headers || {})}
      });
      const text = await response.text();
      let payload;
      try { payload = text ? JSON.parse(text) : {}; }
      catch { payload = {error: 'รูปแบบข้อมูลจาก Local Engine ไม่ถูกต้อง'}; }
      if (!response.ok) throw new Error(payload.error || 'Local Engine ไม่ตอบรับคำสั่ง');
      return payload;
    } finally {
      pendingRequests.delete(serial);
      updateRequestActivity();
    }
  }
  const post = (path, data) => api(path, {method: 'POST', body: JSON.stringify(data)});
  // Every long inspection gets an honest elapsed-time heartbeat. No invented
  // percentages or made-up inspected-file counts; final data comes from PC Engine.
  const inspectionTimers = new Map();
  function beginInspection(targetId, description) {
    const element=$(targetId);
    if(inspectionTimers.has(targetId)) return null;
    const started=Date.now();
    const token={started, timer:null};
    inspectionTimers.set(targetId, token);
    element.classList.add('working-pulse');
    function tick(){
      const elapsed=Math.floor((Date.now()-started)/1000);
      const dots='.'.repeat((elapsed%3)+1);
      const waiting=elapsed>=45
        ? ' · Engine ยังไม่ตอบกลับ โปรดตรวจ RAM/CPU หรือรายการงานที่กำลังทำ'
        : elapsed>=15 ? ' · ยังรอผลจาก PC Engine' : '';
      element.textContent=description+dots+'  '+fmtTime(elapsed)+' ผ่านไป'+waiting+
        '\\nกำลังรอผลตรวจจริง · ยังไม่ทราบจำนวนไฟล์ทั้งหมด';
    }
    tick();
    token.timer=setInterval(tick,1000);
    return () => {
      if(inspectionTimers.get(targetId)!==token)return;
      clearInterval(token.timer);
      inspectionTimers.delete(targetId);
      element.classList.remove('working-pulse');
    };
  }

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
    box.hidden = !text; box.dataset.error = isError ? 'true' : 'false';
    clearTimeout(notificationTimer);
    if (text) notificationTimer = setTimeout(() => {box.hidden = true;}, isError ? 9500 : 5000);
  }
  function confirmStudio(description, title='ยืนยันรายการ',
                         {acceptLabel='ยืนยัน', cancelLabel='ยกเลิก'} = {}) {
    // Never replace the content/listeners of an unresolved confirmation.
    // Two near-simultaneous UI actions must not overwrite one another.
    const dialog = $('studio-confirm-dialog');
    if (dialog.open) {
      message('มีหน้าต่างยืนยันรายการอื่นเปิดอยู่ · กรุณาทำรายการนั้นให้เสร็จก่อน');
      return Promise.resolve(false);
    }
    return new Promise(resolve => {
      $('studio-confirm-title').textContent = title;
      $('studio-confirm-message').textContent = String(description);
      const ok = $('studio-confirm-ok');
      const cancel = $('studio-confirm-cancel');
      const oldOk = ok.textContent, oldCancel = cancel.textContent;
      ok.textContent = acceptLabel;
      cancel.textContent = cancelLabel;
      let resolved = false;
      const complete = answer => {
        if (resolved) return;
        resolved = true;
        ok.removeEventListener('click', accept);
        cancel.removeEventListener('click', reject);
        dialog.removeEventListener('close', closed);
        if (dialog.open) dialog.close();
        ok.textContent = oldOk;
        cancel.textContent = oldCancel;
        resolve(answer);
      };
      const accept = () => complete(true);
      const reject = () => complete(false);
      const closed = () => complete(false);
      ok.addEventListener('click', accept);
      cancel.addEventListener('click', reject);
      dialog.addEventListener('close', closed);
      dialog.showModal(); // In-app borderless UI; never a native OS confirm title bar.
      ok.focus(); // Enter confirms the explicit build action, not Cancel.
    });
  }
  function updateCreateWizard() {
    for (const panel of document.querySelectorAll('[data-create-step]')) {
      const visible = Number(panel.dataset.createStep) === createStep;
      panel.hidden = !visible;
    }
    for (const button of document.querySelectorAll('[data-create-target]')) {
      const step = Number(button.dataset.createTarget);
      const isActive = step === createStep;
      button.classList.toggle('active', isActive);
      button.classList.toggle('completed', step < createStep);
      if (isActive) button.setAttribute('aria-current', 'step');
      else button.removeAttribute('aria-current');
      button.disabled = busy || (step > 1 && total < 1) || (step === 4 && selected.size === 0);
    }
    $('create-step-progress').textContent = 'ขั้นตอนที่ ' + createStep + ' จาก 4';
    $('create-step-description').textContent = 'ขั้นตอน ' + createStep + '/4 · ' + createStepLabels[createStep - 1];
    $('create-step-previous').disabled = busy || createStep === 1;
    const next = $('create-step-next');
    next.hidden = createStep === 4;
    next.disabled = busy || (createStep === 1 && total < 1) || (createStep === 3 && selected.size === 0);
    if (createStep < 4) {
      next.textContent = 'ขั้นตอนถัดไป: ' + ['เลือกเพลง', 'ตั้งค่าเสียง / ทดลองฟัง', 'สร้างเพลง'][createStep - 1] + ' ›';
    }
    $('preview-button').disabled = busy || livePreviewPending || (!previewSongId && selected.size !== 1);
    $('preview-button').textContent = $('preview-file-type').value.startsWith('inspect:')
      ? '⌕ ตรวจไฟล์ประกอบ' : '▶ เล่นเพลงทันที';
    aiUpdateButtons();
    const previewHint = $('create-preview-hint');
    if (!previewAudio.src && !livePreviewPending) {
      previewHint.textContent = previewSongId || selected.size === 1
        ? 'พร้อมทดลองฟังแบบสตรีมสด · กดเล่นหรือเลือกเพลงจากผลค้นหาได้ทันที'
        : 'ค้นหาและเลือกเพลงที่จะทดลองฟังภายในหน้านี้ได้เลย';
    }
    $('review-song-count').textContent = fmtNum(selected.size) + ' เพลง';
    $('review-workspace').textContent = $('create-workspace').value.trim() || prefs.workspace || 'ยังไม่ได้เลือก';
    const fontValue = $('create-soundfont').value || prefs.soundfont || '';
    $('review-soundfont').textContent = fontValue ? fontValue.split(/[\\/]/).pop() : 'ไม่ได้เลือก (ไฟล์เสียงทั่วไป)';
    const mode = $('create-mode');
    $('review-mode').textContent = mode.options[mode.selectedIndex]?.textContent || mode.value || 'คงเสียงต้นฉบับ';
  }
  function goCreateStep(target) {
    const step = Number(target);
    if (!Number.isInteger(step) || step < 1 || step > 4 || busy) return;
    if (step > 1 && total < 1) {
      message('ขั้นตอนที่ 1: เลือกโฟลเดอร์ต้นฉบับ กดตรวจสอบไฟล์เพลง และรอให้สแกนพบเพลงก่อน');
      return;
    }
    if (step === 4 && selected.size === 0) {
      message('ก่อนสร้างเพลง กรุณาเลือกเพลงอย่างน้อย 1 เพลงในขั้นตอนที่ 2');
      return;
    }
    if (createStep === 3 && step !== 3) stopLivePreview();
    createStep = step;
    if (createStep === 3) {
      if (!previewSongId && selected.size === 1) previewSongId = [...selected][0];
      void searchPreviewSongs();
      if (previewSongId) {
        void loadPreviewIdentity(previewSongId);
        void loadPreviewSources(previewSongId);
        void loadPreviewLyrics(previewSongId);
      }
    }
    updateCreateWizard();
    document.querySelector('.create-assistant')?.scrollIntoView({behavior: 'smooth', block: 'start'});
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
    if (activeTab !== 'create') stopLivePreview();
    stopImportPreviews(name==='upload'?'online':name==='pc-export'?'pc':'');
    if (activeTab !== 'ai-lyrics') {
      aiStopPlayback();
    }
    if (name === 'ai-lyrics') void aiRefreshSongList();
    if (name === 'settings') void refreshHistory();
    if (name === 'lyric-head-tail') {
      void refreshPhraseBackup();
      if(phraseReady)void refreshPhraseGroups();
    }
    if (name === 'settings') void refreshEnvironment();
  }
  // Local-only text grouping; the backend never modifies audio or uploads.
  // Operator queue for multiple text groups, across pages and all 4 slots.
  // Search changes clear selection because they change the matching songs.
  function phraseUpdateButtons(){
    const allow=phraseReady&&!busy;
    $('lyric-group-scan').disabled=busy;
    $('lyric-group-folder').disabled=busy;
    $('lyric-group-reset').disabled=busy||!prefs.lyric_source;
    $('lyric-group-search').disabled=!allow;
    $('lyric-group-repeats').disabled=!allow;
    $('lyric-group-replacement-mode').disabled=busy;
    $('lyric-group-replacement').disabled=!allow||phraseSelected.size===0;
    $('lyric-group-apply').disabled=!allow||phraseSelected.size===0||
      !$('lyric-group-replacement').value.trim();
    $('lyric-group-undo').disabled=busy||!phraseBackup;
    $('lyric-group-select-page').disabled=!allow||phraseRows.length===0;
    $('lyric-group-select-matching').disabled=!allow||phraseRows.length===0||phraseSelected.size>=MAX_SELECTED_LYRIC_GROUPS;
    $('lyric-group-clear').disabled=busy||phraseSelected.size===0;
    $('lyric-group-selected-count').textContent=
      'เลือก '+fmtNum(phraseSelected.size)+' / '+fmtNum(MAX_SELECTED_LYRIC_GROUPS)+' กลุ่ม';
    const total=Number($('lyric-group-page-count').dataset.total||0);
    $('lyric-group-prev').disabled=!allow||phraseOffset===0;
    $('lyric-group-next').disabled=!allow||phraseOffset+40>=total;
    for(const btn of document.querySelectorAll('[data-lyric-position]')){
      const active=btn.dataset.lyricPosition===phrasePosition;
      btn.disabled=busy;
      btn.classList.toggle('primary',active);
      btn.classList.toggle('ghost',!active);
      btn.setAttribute('aria-pressed',String(active));
    }
    for(const input of $('lyric-group-results').querySelectorAll('[data-lyric-group]'))
      input.disabled=busy;
  }
  function phraseClearSelection(){
    phraseSelected.clear();
    phrasePlan=null;
    ++phraseSelectionSeq;
    clearTimeout(phraseSelectionTimer);
    $('lyric-group-selection').textContent='ยังไม่ได้เลือกกลุ่มข้อความ';
    $('lyric-group-examples').replaceChildren();
    // Keep the replacement text so the operator can reuse the same intro
    // or outro in the next batch without typing it again.
    $('lyric-group-preview-status').textContent=
      'เลือกรายการที่ยังไม่แก้เพื่อทำชุดถัดไป · ตรวจจำนวนเพลงก่อนยืนยัน';
    for(const input of $('lyric-group-results').querySelectorAll('[data-lyric-group]'))
      input.checked=false;
    phraseUpdateButtons();
  }
  function phraseInvalidate(){
    ++phraseSeq;
    phraseReady=false;phraseRows=[];phraseOffset=0;phraseBackup=null;
    phraseClearSelection();
    $('lyric-group-results').textContent=
      'เปลี่ยนโฟลเดอร์ต้นทางแล้ว · กดวิเคราะห์เพื่ออ่านคลังที่เลือก';
    $('lyric-group-page-count').dataset.total='0';
    $('lyric-group-page-count').textContent='ยังไม่ได้วิเคราะห์คลังนี้';
    $('lyric-group-stats').textContent='กรุณาวิเคราะห์คลังต้นทางที่เลือก';
  }
  async function refreshPhraseBackup(){
    try{
      const value=await api('/api/lyric-groups-backup');
      phraseBackup=value.latest||null;
    }catch{phraseBackup=null;}
    phraseUpdateButtons();
  }
  async function refreshPhraseGroups(){
    if(!phraseReady)return;
    const seq=++phraseSeq;
    const phraseSearch=$('lyric-group-search').value.trim();
    if(phrasePosition==='all'&&!phraseSearch){
      phraseRows=[];
      $('lyric-group-results').textContent='โหมดทุกบรรทัด: กรุณาพิมพ์วลีค้นหาเพื่อระบุบรรทัดที่จะแก้';
      $('lyric-group-page-count').dataset.total='0';
      $('lyric-group-page-count').textContent='ระบุวลีค้นหาก่อน';
      phraseUpdateButtons();
      return;
    }
    $('lyric-group-results').textContent='กำลังค้นหาวลีตามลำดับคำในบรรทัด…';
    const params=new URLSearchParams({
      position:phrasePosition,offset:String(phraseOffset),limit:'40',
      repeats:$('lyric-group-repeats').checked?'1':'0',
      search:$('lyric-group-search').value.trim()
    });
    try{
      const data=await api('/api/lyric-groups?'+params.toString());
      if(seq!==phraseSeq)return;
      if(data.total&&phraseOffset>=data.total){
        phraseOffset=Math.floor((data.total-1)/40)*40;
        return refreshPhraseGroups();
      }
      phraseRows=data.rows||[];
      const panel=$('lyric-group-results');panel.replaceChildren();
      for(const group of phraseRows){
        const label=document.createElement('label');
        label.className='lyric-group-row';
        label.classList.toggle('active',phraseSelected.has(group.id));
        const input=document.createElement('input');
        input.type='checkbox';
        input.dataset.lyricGroup=group.id;
        input.checked=phraseSelected.has(group.id);
        input.setAttribute('aria-label','เลือกกลุ่มข้อความ '+group.text);
        const txt=document.createElement('span');txt.className='lyric-group-row-text';
        txt.textContent=group.text;
        const number=document.createElement('span');number.className='lyric-group-row-count';
        const unit=phrasePosition==='all'?' บรรทัด':' เพลง';
        number.textContent=fmtNum(group.count)+unit+
          (group.libraryCount!==group.count?' / ทั้งกลุ่ม '+fmtNum(group.libraryCount):'');
        label.append(input,txt,number);panel.append(label);
      }
      if(!phraseRows.length){
        const empty=document.createElement('div');empty.className='preview-empty';
        empty.textContent='ไม่พบข้อความตามเงื่อนไขนี้ · ลองตำแหน่งอื่นหรือยกเลิกตัวกรองข้อความซ้ำ';
        panel.append(empty);
      }
      $('lyric-group-page-count').dataset.total=String(data.total||0);
      $('lyric-group-page-count').textContent=data.total?
        fmtNum(phraseOffset+1)+'–'+fmtNum(Math.min(data.total,phraseOffset+phraseRows.length))+
        ' จาก '+fmtNum(data.total)+' กลุ่ม':'ไม่มีกลุ่มข้อความ';
      $('lyric-group-stats').textContent='เพลงที่ตรวจได้ '+fmtNum(data.songs)+
        ' · รายการในคลัง '+fmtNum(data.inspected)+
        ' · ไม่มีคำร้องครบ 4 บรรทัด '+fmtNum(data.withoutLyrics)+
        ' · ข้ามไฟล์ไม่รองรับ '+fmtNum(data.skippedInvalid);
      phraseUpdateButtons();
    }catch(error){
      if(seq!==phraseSeq)return;
      phraseReady=false;
      $('lyric-group-results').textContent='อ่านข้อมูลไม่สำเร็จ: '+error.message;
      message(error.message);
      phraseUpdateButtons();
    }
  }
  async function phraseRefreshSelection(){
    const seq=++phraseSelectionSeq;
    if(!phraseSelected.size){
      phrasePlan=null;
      $('lyric-group-selection').textContent='ยังไม่ได้เลือกกลุ่มข้อความ';
      $('lyric-group-examples').replaceChildren();
      phraseUpdateButtons();
      return;
    }
    $('lyric-group-selection').textContent='กำลังตรวจจำนวนเพลงที่เลือก…';
    try{
      const result=await post('/api/lyric-groups-plan',{
        groups:[...phraseSelected.keys()],
        search:$('lyric-group-search').value.trim(),
        replacement:$('lyric-group-replacement').value.trim()||null
      });
      if(seq!==phraseSelectionSeq)return;
      phrasePlan=result;
      $('lyric-group-selection').textContent=
        'เลือก '+fmtNum(phraseSelected.size)+' กลุ่ม · จะแก้ '+
        fmtNum(result.changedLines)+' บรรทัดใน '+fmtNum(result.changedSongs)+' เพลง'+
        (result.alreadyCorrect?' · ข้ามที่มีข้อความนี้แล้ว '+fmtNum(result.alreadyCorrect)+' บรรทัด':'');
      const panel=$('lyric-group-examples');panel.replaceChildren();
      const data=result.selected||[];
      for(const group of data.slice(0,20)){
        const summary=document.createElement('div');summary.className='lyric-group-example';
        const examples=(group.examples||[]).map(x=>x.code+' '+x.title).join(' · ');
        summary.textContent=group.label+' · '+group.text+' · '+
          fmtNum(group.count)+' เพลง'+(examples?' · ตัวอย่าง '+examples:'');
        panel.append(summary);
      }
      if(phraseSelected.size>data.length){
        const more=document.createElement('div');more.className='lyric-group-example';
        more.textContent='และอีก '+fmtNum(phraseSelected.size-data.length)+' กลุ่มที่เลือก';
        panel.append(more);
      }
      $('lyric-group-preview-status').textContent=
        'ค้นหาวลีเรียงตามลำดับภายในบรรทัดที่จะเปลี่ยน · แทนที่ทั้งบรรทัดที่เลือก · '+
        'สำรองก่อนแก้ · หลังยืนยันรายการที่ยังไม่แก้ยังแสดงอยู่';
    }catch(error){
      if(seq!==phraseSelectionSeq)return;
      phrasePlan=null;
      $('lyric-group-selection').textContent='ตรวจกลุ่มที่เลือกไม่สำเร็จ: '+error.message;
      message(error.message);
    }
    phraseUpdateButtons();
  }
  function schedulePhraseSelectionPreview(){
    clearTimeout(phraseSelectionTimer);
    // Invalidate a slow earlier response immediately; plan once after
    // a burst of checkbox clicks to keep large catalogs responsive.
    ++phraseSelectionSeq;
    phraseSelectionTimer=setTimeout(()=>{void phraseRefreshSelection();},350);
  }
  function phraseToggleGroup(id,selected){
    const row=phraseRows.find(x=>x.id===id);
    if(!row||busy)return;
    if(selected){
      if(!phraseSelected.has(row.id)&&phraseSelected.size>=MAX_SELECTED_LYRIC_GROUPS){
        const checkbox=[...$('lyric-group-results').querySelectorAll('input[data-lyric-group]')].find(x=>x.dataset.lyricGroup===id);
        if(checkbox)checkbox.checked=false;
        return message('เลือกได้สูงสุด '+fmtNum(MAX_SELECTED_LYRIC_GROUPS)+' กลุ่มต่องาน · กดแทนที่เพื่อบันทึกชุดนี้ แล้วเลือกกลุ่มที่เหลือต่อ');
      }
      phraseSelected.set(row.id,row);
    }else phraseSelected.delete(id);
    for(const label of $('lyric-group-results').querySelectorAll('.lyric-group-row')){
      const input=label.querySelector('[data-lyric-group]');
      if(input)label.classList.toggle('active',phraseSelected.has(input.dataset.lyricGroup));
    }
    phraseUpdateButtons();
    schedulePhraseSelectionPreview();
  }
  async function phraseApply(){
    if(busy||!phraseReady||phraseSelected.size===0)return;
    const ids=[...phraseSelected.keys()];
    const replacement=$('lyric-group-replacement').value.trim();
    const search=$('lyric-group-search').value.trim();
    if(!replacement||replacement.length>400||/[\r\n]/.test(replacement))
      return message('กรุณาใส่ข้อความใหม่หนึ่งบรรทัด ความยาวไม่เกิน 400 ตัวอักษร');
    let planned;
    try{
      planned=await post('/api/lyric-groups-plan',{
        groups:ids,search,replacement
      });
    }catch(error){return message('ตรวจจำนวนเพลงไม่สำเร็จ: '+error.message);}
    if(!planned.changedLines)return message('ข้อความที่เลือกเหมือนข้อความใหม่ทั้งหมด ไม่มีรายการต้องเปลี่ยน');
    if(busy||!phraseReady||ids.some(id=>!phraseSelected.has(id))||
       replacement!==$('lyric-group-replacement').value.trim()||
       search!==$('lyric-group-search').value.trim())return;
    const approved=await confirmStudio(
      'เลือก '+fmtNum(planned.chosenGroups)+' กลุ่ม\n'+
      'จำนวนเพลง: '+fmtNum(planned.changedSongs)+' เพลง\n'+
      'จำนวนบรรทัดที่เปลี่ยน: '+fmtNum(planned.changedLines)+' บรรทัด\n'+
      (search?'วลีในบรรทัดที่เลือก: '+search+'\nแทนที่ทั้งบรรทัดที่มีวลีนี้ตรงลำดับ\n':'')+
      '\nข้อความใหม่ร่วมกัน:\n'+replacement+'\n\n'+
      'Smart Batch: รักษาเวลาเดิมของส่วนไม่เปลี่ยน · ประมาณเฉพาะช่วงแก้ · สำรองก่อนบันทึก'+
      '\nข้ามเพลงผิดปกติพร้อมรายงาน · ไม่แก้ MID/LYR/CUR · อัปโหลด Drive ต้องสั่งเอง',
      'ยืนยันแทนที่ข้อความหลายกลุ่ม',
      {acceptLabel:'สำรองและแทนที่',cancelLabel:'ยกเลิก'});
    if(!approved||busy||ids.some(id=>!phraseSelected.has(id))||
       replacement!==$('lyric-group-replacement').value.trim()||
       search!==$('lyric-group-search').value.trim())return;
    const started=await run('lyric-groups-replace',{
      groups:ids,search,replacement,expectedCount:planned.changedLines
    });
    if(started)$('lyric-group-preview-status').textContent=
      'กำลังสำรองและแทนที่ข้อความ · รายการอื่นยังรอแก้ต่อได้หลังเสร็จ';
  }
  async function phraseUndo(){
    const backup=phraseBackup;if(!backup||busy)return;
    const approved=await confirmStudio(
      'ย้อนคืนการแก้ไข '+fmtNum(backup.songs)+' เพลง\n\nจาก: '+
      backup.newText+'\nกลับเป็น: '+backup.oldText+
      '\n\nระบบจะคืนค่าต่อเมื่อทุกไฟล์ยังตรงกับการแก้ไขครั้งก่อน เพื่อป้องกันทับข้อมูลใหม่',
      'ยืนยันย้อนคืนข้อความทั้งชุด',
      {acceptLabel:'ตรวจและย้อนคืน',cancelLabel:'ยกเลิก'});
    if(approved&&!busy)await run('lyric-groups-undo',{backupId:backup.id});
  }
  function syncXskControls() {
    const choice=$('create-output-kind');
    if (!proEnabled && choice.value!=='xsk') choice.value='xsk';
    for (const option of choice.options) option.disabled=!proEnabled&&option.value!=='xsk';
    const legacy=proEnabled&&choice.value!=='xsk';
    $('pro-legacy-format').hidden=!proEnabled;
    $('create-export-format').disabled=!legacy||busy;
    $('create-export-format').value=legacy?choice.value:'xstage';
    $('build-audio-button').hidden=!legacy;
    $('build-button').textContent=legacy?'▶ สร้างไฟล์เพลง':'▶ สร้างเพลง XSK';
    $('xsk-output-hint').textContent=legacy
      ? 'โหมด Pro · ส่งออกแบบเดิมตามโครงสร้าง XStageSong'
      : 'จัดเก็บ XSK ใน XStageSong/MIDI/XSK/ ตามอักขระแรกของรหัสเพลง';
    $('xsk-edit-options').hidden=$('xsk-edit-choice').value!=='yes';
    $('pro-license-status').textContent=proEnabled
      ? 'เปิดใช้ X-Stage Song Studio PC Pro แล้ว'
      : 'รุ่นทั่วไป · โปรดเปิดใช้ Pro ในเมนูตั้งค่า';
    // License activation is the only reason to show the license form.
    // Never show the PRO brand on a failed/unverified local license.
    $('pro-license-settings').hidden=proEnabled;
    $('brand-pro-status').hidden=!proEnabled;
    if($('xsk-pro-badge'))$('xsk-pro-badge').textContent=proEnabled?'PRO ACTIVATED':'LOCKED · PRO';
    if($('created-xsk-build'))$('created-xsk-build').disabled=!proEnabled||busy;
    $('json-pro-start').disabled=!proEnabled||busy;
    $('xsk-stream-build').disabled=busy;
    const directXsk=choice.value==='xsk';
    $('tab-create').classList.toggle('xsk-auto-mode',directXsk);
    if(directXsk && createStep!==1){
      createStep=1;
      updateCreateWizard();
    }
  }
  async function refreshProLicense() {
    try {
      const license=await api('/api/license/status');
      proEnabled=!!license.pro;
      syncXskControls();
      if($('created-xsk-build'))$('created-xsk-build').disabled=!proEnabled||busy||createdJsonSelected.size===0;
    } catch(e) {
      proEnabled=false;syncXskControls();
    }
  }
  function setFields() {
    $('create-source').value = prefs.source || '';
    $('create-workspace').value = prefs.workspace || '';
    $('xsk-destination').value = prefs.xsk_folder || prefs.workspace || '';
    $('xsk-build-folder').value = prefs.xsk_folder || '';
    $('xsk-stream-code-style').value = prefs.code_style || 'numeric';
    $('xsk-stream-code-length').value = prefs.code_length || '5';
    $('json-pro-source').value = prefs.json_source || '';
    $('json-pro-destination').value = prefs.json_destination || '';
    $('json-pro-code-style').value = prefs.code_style || 'numeric';
    $('json-pro-code-length').value = prefs.code_length || '5';
    $('lyric-group-folder').value = prefs.lyric_source || '';
    $('lyric-group-source-status').textContent = prefs.lyric_source
      ? 'ต้นทางที่เลือก: '+prefs.lyric_source+' · ใช้ Lyrics JSON เท่านั้น'
      : 'ใช้คลังหลักของโฟลเดอร์งาน: '+(prefs.workspace||'')+' · XStageSong';
    $('download-destination').value = prefs.download || '';
    $('upload-folder').value = prefs.upload_folder || '';
    $('pc-export-folder').value = prefs.pc_export_folder || '';
    $('upload-soundfont-path').value = prefs.soundfont || '';
    $('ai-export-folder').textContent = prefs.download || 'ยังไม่ได้เลือกโฟลเดอร์';
    $('settings-oauth').value = prefs.oauth || '';
    $('create-preset').value = prefs.midi_preset || 'balanced';
    $('create-mode').value = prefs.mode || 'original';
    // Dedicated MIDI to .XSK menu defaults to XSK even with a Pro license.
    $('create-output-kind').value = 'xsk';
    syncXskControls();
    $('catalog-view').value = prefs.catalog_view === 'all' ? 'all' : 'changes';
    $('create-code-style').value = prefs.code_style || 'numeric';
    $('create-code-length').value = prefs.code_length || '5';
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
    const previousGoogle = googleConnected;
    const previousConfigured = googleConfigured;
    googleConnected = !!google?.connected;
    const configured = !!google?.configured;
    googleConfigured = configured;
    const badge = $('google-badge');
    badge.classList.toggle('offline', !googleConnected);
    const label = googleConnected ? `เชื่อม Google · ${google.email}`
      : configured ? 'Google พร้อมให้ลงชื่อเข้าใช้' : 'ยังไม่ได้ตั้งค่า Google OAuth';
    badge.innerHTML = '<span class="small-dot"></span>' + escapeHTML(label);
    $('upload-google-state').textContent = googleConnected ? google.email + ' · พร้อมอัปโหลด'
      : configured ? 'พร้อมเชื่อมต่อ · กด Google Login เพื่อเลือกบัญชีของคุณ'
      : 'ผู้พัฒนาแอปยังไม่ได้ตั้งค่า Desktop OAuth Client';
    $('google-login-header').textContent = googleConnected ? 'Google ✓' : 'Google Login';
    const status = $('google-config-state');
    if (status) {
      status.dataset.ready = configured ? 'true' : 'false';
      status.textContent = configured
        ? '✓ OAuth Client ตั้งค่าแล้ว (' + (google.config_source === 'bundled' ? 'รวมในแอป' : 'บันทึกถาวรบนเครื่อง') +
          ') · ผู้ใช้เพียงเลือกบัญชี Google ครั้งแรก'
        : 'ยังไม่มี Desktop OAuth Client ในแอป · ผู้ดูแลต้องเพิ่ม Client ID ในแพ็กเกจ หรือเลือก JSON ครั้งเดียวในตัวเลือกขั้นสูง';
    }
    const loginState = $('google-login-state');
    if (loginState) {
      loginState.dataset.ready = googleConnected ? 'true' : 'false';
      loginState.textContent = googleConnected
        ? '✓ เชื่อมต่อ Google Drive ใน Song Studio PC แล้ว · ' + (google?.email || 'บัญชี Google')
        : !configured ? 'ยังไม่ได้เชื่อมต่อ: รุ่น Core Preview ต้องนำเข้า Google Desktop OAuth Client JSON ในตัวเลือกขั้นสูงก่อน ไม่สามารถใช้การล็อกอินของ X-Stage Karaoke Online แทนได้' + (google?.error ? ' · ' + google.error : '')
        : 'OAuth Client พร้อมแล้ว แต่ Song Studio PC ยังไม่ได้รับ Google refresh token' + (google?.error ? ' · ' + google.error : ' · กด Google Login และอนุญาตสิทธิ์ในหน้าต่างเบราว์เซอร์');
    }
    const advanced = $('oauth-advanced');
    if (advanced && !advanced.dataset.initialized) {
      advanced.open = !configured;
      advanced.dataset.initialized = 'true';
    }
    $('upload-folder-button').disabled = busy || !googleConnected;
    $('upload-soundfont-button').disabled = busy || !googleConnected;
    $('upload-soundfont-picker').disabled = busy;
    for (const id of ['settings-logout']) $(id).disabled = busy || !googleConnected;
    for (const el of document.querySelectorAll('.download-action')) el.disabled = busy || !googleConnected;
    // The environment panel previously remained stale after an OAuth import
    // or successful login even while the header badge was live.
    if (activeTab === 'settings' &&
        (previousGoogle !== googleConnected || previousConfigured !== configured)) {
      void refreshEnvironment();
    }
  }
  async function loadState({initialize = false} = {}) {
    const data = await api('/api/status');
    busy = data.job?.state === 'running';
    activeJobs=data.jobs||[];
    parallelCapacity=data.resources||parallelCapacity;
    renderParallelJobs();
    prefs = data.preferences || prefs;
    $('engine-state').textContent = 'พร้อมใช้งานบน PC · เชื่อมต่อแล้ว';
    $('version-info').textContent = `Song Studio v${data.version} · Build ${data.build}`;
    $('update-version').textContent = data.update?.status === 'available'
       ? `มีรุ่นใหม่ v${data.update.version}` : `v${data.version} / ${data.build}`;
    if (initialize) {
      presetOptions(data.presets); soundfontOptions(data.soundfonts); setFields();
      // A previously finished job must not reopen the consent dialog on launch.
      // If a build is in progress, polling still detects its completion.
      lastJobId = data.job?.id || '';
      lastJobState = data.job?.state || 'idle';
    }
    setGoogle(data.google);
    renderJob(data.job || {});
    updateButtons();
  }
  function updateButtons() {
    $('selected-count').textContent = `เลือกแล้ว ${fmtNum(selected.size)} เพลง`;
    $('upload-inspect').disabled = busy;
    $('pc-export-inspect').disabled = busy;
    $('json-pro-inspect').disabled=busy;
    $('json-pro-start').disabled=busy||!proEnabled;
    $('pc-export-start').disabled = busy;
    $('upload-soundfont-button').disabled = busy || !googleConnected;
    $('upload-soundfont-picker').disabled = busy;
    $('upload-folder-button').disabled = busy || !googleConnected;
    const buttons = ['scan-button','reconcile-button','scan-full-button','preview-button','edit-button','build-button',
      'build-audio-button','select-all','select-page','clear-selection','upload-login','settings-login',
      'settings-logout','google-login-header','update-button','verify-code-registry'];
    for (const name of buttons) $(name).disabled = busy;
    $('update-download').disabled = busy;
    $('build-button').disabled = busy || selected.size === 0;
    $('build-audio-button').disabled = busy || selected.size === 0 || !proEnabled;
    syncXskControls();
    $('preview-button').disabled = busy || livePreviewPending || (!previewSongId && selected.size !== 1);
    $('edit-button').disabled = busy || selected.size !== 1;

    $('settings-logout').disabled = busy || !googleConnected;
    for (const el of document.querySelectorAll('.download-action')) el.disabled = busy || !googleConnected;
    for (const el of document.querySelectorAll('[data-pick],.field,.song-table input[type=checkbox]')) el.disabled = busy;
    $('cancel-job').hidden = !busy;
    $('cancel-job').disabled = cancellationPending;
    updateCreateWizard();
    phraseUpdateButtons();
    aiUpdateButtons();
    // Keep independent workflows accessible while an unrelated group runs.
    const libraryOK=canLaunch('xsk-stream');
    const audioOK=canLaunch('ai-lyrics');
    const netOK=canLaunch('upload-folder');
    $('xsk-stream-build').disabled=!libraryOK;
    $('json-pro-start').disabled=!libraryOK||!proEnabled;
    $('json-pro-inspect').disabled=!libraryOK;
    $('ai-lyrics-start').disabled=!audioOK||!Number.isInteger(aiSongId)||!aiEngineReady;
    $('ai-lyrics-separate').disabled=!audioOK||!Number.isInteger(aiSongId)||!aiSeparationAvailable;
    $('ai-lyrics-align').disabled=!audioOK||!Number.isInteger(aiSongId)||
       !(aiEngineReady||aiDraftReady)||!$('ai-lyrics-paste').value.trim();
    $('upload-folder-button').disabled=!netOK||!googleConnected;
    $('upload-soundfont-button').disabled=!netOK||!googleConnected;
    $('update-button').disabled=!canLaunch('check-update');
    $('update-download').disabled=!canLaunch('install-update');
    for(const id of ['create-source','xsk-build-folder','xsk-stream-code-style','xsk-stream-code-length',
                     'json-pro-source','json-pro-destination','json-pro-format']) {
       $(id).disabled=!libraryOK;
    }
    for(const id of ['upload-folder','upload-soundfont-path']) $(id).disabled=!netOK;
    for(const button of document.querySelectorAll('[data-pick]')) {
       const kind=button.dataset.pick;
       if(['source','xsk_folder','json_source','json_destination'].includes(kind))
         button.disabled=!libraryOK;
       else if(['upload_folder','soundfont'].includes(kind))
         button.disabled=!netOK;
    }
  }
  async function verifyCodeRegistry() {
    const button = $('verify-code-registry');
    const indicator = $('code-registry-state');
    if (busy || button.disabled) return;
    button.disabled = true;
    const priorLabel = button.textContent;
    button.textContent = 'กำลังเทียบรหัสทั้งสองคลัง…';
    indicator.textContent = 'กำลังอ่าน Catalog ในเครื่องและ XStageSong บน Google Drive · ยังไม่เปลี่ยนรหัสหรือไฟล์ใด ๆ';
    try {
      await saveInputs(['create-workspace']);
      const report = await api('/api/code-registry');
      let messageText = report.message || '';
      if (report.sampleRemaps?.length) {
        const examples = report.sampleRemaps.slice(0,3)
          .map(x => x.oldCode + ' → ' + x.newCode).join(' · ');
        messageText += ' · ตัวอย่าง ' + examples;
      }
      indicator.textContent = messageText;
      indicator.dataset.verified = report.onlineVerified ? 'true' : 'false';
      message(messageText, !report.onlineVerified);
    } catch (error) {
      indicator.textContent = 'ตรวจทะเบียนรหัสไม่สำเร็จ: ' + error.message +
        ' · ระบบยังไม่ได้เปลี่ยนเพลงเดิมหรือรหัสใด';
      indicator.dataset.verified = 'false';
      message(indicator.textContent);
    } finally {
      button.textContent = priorLabel;
      button.disabled = busy;
    }
  }
  async function refreshSongs() {
    const view=$('catalog-view').value;
    const data = await api('/api/songs?limit=' + pageSize + '&offset=' + (page * pageSize) + '&search=' + encodeURIComponent(search) + '&view=' + encodeURIComponent(view) + '&midi_only=' + ($('create-output-kind').value==='xsk'?'1':'0'));
    songs = data.rows || []; total = data.total || 0;
    const rows = $('song-rows'); rows.replaceChildren();
    if (!songs.length) rows.innerHTML = '<tr><td colspan="5" class="empty-row">' +
      (view==='changes' ? 'ไม่พบเพลงเพิ่มใหม่หรือเปลี่ยนแปลง · เลือก “เพลงทั้งหมดในคลัง” เพื่อดูของเดิม' :
        'ไม่พบเพลงในรายการ · เลือกโฟลเดอร์และกดตรวจสอบไฟล์เพลง') + '</td></tr>';
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
    const previousSource = prefs.source;
    const previousLyricSource = prefs.lyric_source || '';
    const response = await post('/api/config', patch);
    prefs = response.preferences || prefs;
    if ((patch.workspace && previousWorkspace !== prefs.workspace) ||
        (patch.source && previousSource !== prefs.source)) {
      selected.clear(); page = 0; await refreshSongs();
    }
    if ('soundfont' in patch || 'workspace' in patch) soundfontOptions(response.soundfonts || []);
    if ((('lyric_source' in patch) && previousLyricSource !== (prefs.lyric_source || '')) ||
        (('workspace' in patch) && previousWorkspace !== prefs.workspace && !prefs.lyric_source)) {
      phraseInvalidate();
      void refreshPhraseBackup();
    }
    setFields();
    if (response.google) setGoogle(response.google);
    if ('oauth' in patch) await refreshEnvironment();
    return response;
  }
  const fields = {'create-source': 'source', 'create-workspace': 'workspace',
                  'create-soundfont': 'soundfont', 'create-preset': 'midi_preset',
                  'create-mode': 'mode', 'create-export-format': 'export_format',
                  'create-code-style': 'code_style', 'create-code-length': 'code_length',
                  'download-destination': 'download',
                  'upload-folder': 'upload_folder',
                  'pc-export-folder': 'pc_export_folder',
                  'xsk-build-folder': 'xsk_folder',
                  'xsk-stream-code-style': 'code_style',
                  'xsk-stream-code-length': 'code_length',
                  'json-pro-source': 'json_source',
                  'json-pro-destination': 'json_destination',
                   'json-pro-code-style': 'code_style',
                   'json-pro-code-length': 'code_length',
                  'lyric-group-folder': 'lyric_source',
                  'upload-soundfont-path': 'soundfont',
                  'settings-oauth': 'oauth'};
  async function saveInputs(keys = Object.keys(fields)) {
    const payload = {};
    for (const id of keys) payload[fields[id]] = $(id).value.trim();
    await config(payload);
  }
  async function pick(kind, trigger=null) {
    const button = trigger || [...document.querySelectorAll('[data-pick]')].find(el => el.dataset.pick === kind);
    if (button?.disabled) return;
    const oldLabel = button?.textContent || '';
    if (button) {
      button.disabled = true;
      button.textContent = 'กำลังเปิดหน้าต่าง Windows…';
    }
    message('กำลังเปิดหน้าต่างเลือก' + (kind === 'soundfont' || kind === 'oauth' ? 'ไฟล์' : 'โฟลเดอร์') +
      ' ของ Windows · หากไม่เห็นให้ดูที่แถบงาน', false);
    try {
      const response = await post('/api/folder-picker', {kind});
      if (!response.path) {
        message('ยกเลิกการเลือก · เก็บตำแหน่งเดิมไว้', false);
        return;
      }
      const field = ({source:'create-source',workspace:'create-workspace',soundfont:'create-soundfont',
          download:'download-destination',upload_folder:'upload-folder',
          pc_export_folder:'pc-export-folder',
          lyric_source:'lyric-group-folder',xsk_folder:button?.closest('#tab-create')?'xsk-build-folder':'xsk-destination',
          json_source:'json-pro-source',json_destination:'json-pro-destination',oauth:'settings-oauth'})[kind];
      const element = $(field);
      if (kind === 'soundfont' && ![...element.options].some(opt => opt.value === response.path)) {
        element.add(new Option(response.path.split(/[\\/]/).pop(), response.path));
      }
      element.value = response.path;
      try { await config({[kind]: response.path}); }
      catch(error) { element.value = prefs[kind] || ''; throw error; }
      message('เลือกและบันทึกตำแหน่งใหม่เรียบร้อยแล้ว', false);
      if (kind === 'upload_folder') void inspectUploadFolder();
    } finally {
      if (button) {
        button.textContent = oldLabel;
        button.disabled = busy;
      }
    }
  }
  function stopLivePreview() {
    previewPlaySerial++;
    if (karaokeAnimationFrame) cancelAnimationFrame(karaokeAnimationFrame);
    karaokeAnimationFrame = 0;
    previewClockLast = -1;
    previewClockStalledAt = 0;
    previewLyricCoverageWarned = false;
    clearTimeout(liveControlTimer);
    const stopping = liveStreamId;
    liveStreamId = '';
    liveControlDirty = false;
    previewAudio.pause();
    previewAudio.removeAttribute('src');
    previewAudio.load(); // Aborts HTTP stream; closes FFmpeg/FluidSynth without writing files.
    if (stopping) void post('/api/live-stop', {stream_id:stopping}).catch(()=>{});
    $('preview-label').textContent = 'หยุดทดลองฟังแล้ว';
  }
  function queueLiveControl(immediate = false) {
    if (!liveStreamId) return;
    liveControlDirty = true;
    clearTimeout(liveControlTimer);
    liveControlTimer = setTimeout(async () => {
      if (liveControlPending || !liveStreamId || !liveControlDirty) return;
      liveControlDirty = false;
      liveControlPending = true;
      const stream = liveStreamId;
      try {
        const payload = {
          stream_id:stream,
          music_volume:Number($('preview-music-volume').value)/100,
          synth_volume:Number($('preview-sf-volume').value)/100,
          soundfont:$('create-soundfont').value || prefs.soundfont,
          preset:$('create-preset').value
        };
        await post('/api/live-control', payload);
        if (stream === liveStreamId) {
          $('create-preview-hint').textContent = 'ปรับเสียงสดแล้ว · เสียงดนตรีต้นฉบับแยกจาก SoundFont';
        }
      } catch (error) {
        if (stream === liveStreamId) message('ปรับเสียงสดไม่สำเร็จ: ' + error.message);
      } finally {
        liveControlPending = false;
        if (liveControlDirty && liveStreamId) queueLiveControl(true);
      }
    }, immediate ? 0 : 70);
  }
  // MIDI-style progressive color wipe. For NCN/KAR and enhanced LRC,
  // use genuine cue boundaries; plain LRC is line-level interpolation only.
  function karaokeWipeRatio(time,start,end){
    if(!Number.isFinite(time)||!Number.isFinite(start))return 0;
    const finish=Number.isFinite(end)&&end>start?end:start+0.05;
    return Math.max(0,Math.min(1,(time-start)/(finish-start)));
  }
  function karaokeCueWindows(units,lineStart,lineEnd){
    // A MIDI/NCN cursor can assign several characters to the same tick.
    // The old renderer painted those letters in one frame and appeared to
    // freeze, then jump. Spread tied cues across the following beat.
    if(!Array.isArray(units)||!units.length)return null;
    const times=units.map(u=>Number(u.startTime));
    if(times.some((t,i)=>!Number.isFinite(t)||t<0||
        (i&&t<times[i-1]-.001)))return null;
    if(times.length===1||times.every(t=>Math.abs(t-times[0])<=.001))
      return null; // No meaningful character timing: use whole-line sweep.
    const unique=[];
    for(let i=0;i<times.length;i++)
      if(i===0||times[i]>times[i-1]+.001)unique.push(times[i]);
    const gaps=unique.slice(1).map((t,i)=>t-unique[i])
      .filter(d=>d>.001).sort((a,b)=>a-b);
    const cadence=gaps.length?gaps[Math.floor(gaps.length/2)]:.45;
    const windows=[];
    for(let i=0;i<times.length;){
      let j=i+1;
      while(j<times.length&&Math.abs(times[j]-times[i])<=.001)j++;
      const from=times[i],next=j<times.length?times[j]:NaN;
      let finish;
      if(j-i>1){
        finish=Number.isFinite(next)?next:
          Math.min(lineEnd,from+Math.max(.12,Math.min(1.2,cadence)));
        if(finish-from<.04*(j-i))return null;
      }else{
        finish=Number.isFinite(next)?next:
          Math.min(lineEnd,from+Math.max(.15,Math.min(1.25,cadence*1.25)));
      }
      if(!Number.isFinite(finish)||finish<=from)return null;
      for(let k=i;k<j;k++){
        const a=from+(finish-from)*(k-i)/(j-i);
        const b=from+(finish-from)*(k-i+1)/(j-i);
        windows.push({start:a,end:b});
      }
      i=j;
    }
    return windows;
  }
  function karaokeWipeSpan(text,start,end){
    const el=document.createElement('span');
    el.className='karaoke-wipe-text';
    el.textContent=text;
    el.dataset.startTime=String(start);
    el.dataset.endTime=String(end);
    el.style.setProperty('--karaoke-wipe','0%');
    return el;
  }
  function karaokeUpdateSpans(line,time){
    for(const span of line.querySelectorAll('.karaoke-wipe-text')){
      const progress=karaokeWipeRatio(time,
        Number(span.dataset.startTime),Number(span.dataset.endTime));
      span.style.setProperty('--karaoke-wipe',(progress*100).toFixed(2)+'%');
    }
  }
  function updateLyricTime(timeSeconds=0) {
    const data = previewLyrics;
    if (!data?.lines?.length) return;
    const time = Number.isFinite(timeSeconds) && timeSeconds >= 0 ? timeSeconds : 0;
    const entries = data.lines;
    let lo = 0, hi = entries.length - 1, index = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >>> 1;
      if (Number(entries[mid].startTime) <= time) { index = mid; lo = mid + 1; }
      else hi = mid - 1;
    }
    const panel = $('preview-lyrics-lines');
    if (currentLyricIndex !== index) {
      currentLyricIndex = index;
      panel.replaceChildren();
      const from = Math.max(0, Math.min(entries.length - 5, index - 2));
      const to = Math.min(entries.length, Math.max(5, from + 5));
      for (let i = from; i < to; i++) {
        const entry = entries[i];
        const line = document.createElement('div');
        line.className = 'preview-lyric-line';
        line.dataset.lineIndex = String(i);
        const start = Number(entry.startTime)||0;
        const end = Number(entry.endTime) > start ? Number(entry.endTime) :
          (Number(entries[i+1]?.startTime) > start ? Number(entries[i+1].startTime) : start+4);
        const units = Array.isArray(entry.characters)?entry.characters:[];
        // Discard invalid/incomplete MIDI cues and preserve the displayed
        // full line: never guess absent words or split Thai combining marks.
        const validCues = data.status==='found' && units.length>0 &&
          units.map(u=>String(u.text||'')).join('')===String(entry.text||'') &&
          units.every(u=>Number.isFinite(Number(u.startTime))&&
            Number(u.startTime)>=start&&Number(u.startTime)<=end);
        const windows=validCues?karaokeCueWindows(units,start,end):null;
        if(windows){
          for(let j=0;j<units.length;j++){
            const unit=units[j],window=windows[j];
            line.append(karaokeWipeSpan(String(unit.text||''),
              window.start,window.end));
          }
          line.dataset.cueType='midi';
        }else{
          // No reliable separate cue intervals: never flash all characters
          // simultaneously. Estimate a continuous whole-line sweep instead.
          line.append(karaokeWipeSpan(String(entry.text||''),start,end));
          line.dataset.cueType='line-estimate';
        }
        if (i > index) line.classList.add('upcoming');
        panel.append(line);
      }
    }
    for (const line of panel.querySelectorAll('[data-line-index]')) {
      const i = Number(line.dataset.lineIndex);
      // Preserve the fully swept color between an early lyric end and
      // the next verse, as on MIDI karaoke players; do not snap back.
      const active=i===index;
      line.classList.toggle('active',active);
      line.classList.toggle('upcoming',i>index);
      karaokeUpdateSpans(line,time);
    }
  }
  function previewLyricClockHealth() {
    // Live streaming MP3 has no stable duration/seek table in every browser.
    // Never guess a second clock: follow the media's actual decoded playhead.
    const now = performance.now();
    const time = Number(previewAudio.currentTime);
    if (!Number.isFinite(time) || time < 0) return;
    if (Math.abs(time - previewClockLast) > .025) {
      previewClockLast = time;
      previewClockStalledAt = now;
    } else if (!previewAudio.paused && !previewAudio.seeking &&
               previewAudio.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA &&
               previewClockStalledAt && now - previewClockStalledAt > 3500) {
      $('preview-lyrics-status').textContent =
        'เวลาการเล่นเสียงไม่เดินต่อ · ตรวจการโหลดสตรีม/การพักเสียง แล้วกดเล่นใหม่';
      previewClockStalledAt = now; // Do not update this warning every animation frame.
    }
    const lines = previewLyrics?.lines;
    if (!lines?.length || previewLyricCoverageWarned || previewAudio.paused) return;
    const last = lines[lines.length - 1];
    const end = Math.max(Number(last.endTime) || 0, Number(last.startTime) || 0);
    if (time > end + 6 && !previewAudio.ended) {
      previewLyricCoverageWarned = true;
      $('preview-lyrics-status').textContent =
        'เสียงยังเล่น แต่เวลาเนื้อร้องสิ้นสุดที่ ' +
        Math.floor(end / 60) + ':' + String(Math.floor(end % 60)).padStart(2, '0') +
        ' · ตรวจไฟล์ LRC/LYR/CUR ที่นำเข้า (ไม่มีการแต่งเวลาเพิ่ม)';
    }
  }
  function animateKaraoke() {
    karaokeAnimationFrame = 0;
    if (previewAudio.paused || previewAudio.ended) return;
    updateLyricTime(previewAudio.currentTime);
    previewLyricClockHealth();
    karaokeAnimationFrame = requestAnimationFrame(animateKaraoke);
  }
  function startKaraokeAnimation() {
    updateLyricTime(previewAudio.currentTime);
    if (!karaokeAnimationFrame) karaokeAnimationFrame = requestAnimationFrame(animateKaraoke);
  }
  function showPreviewIdentity(song) {
    if (!song) return;
    const title = String(song.title || song.code || 'ไม่ระบุชื่อเพลง').trim();
    const artist = String(song.artist || '').trim();
    $('preview-selected-title').textContent = title;
    $('preview-selected-artist').textContent = 'นักร้อง / ศิลปิน: ' + (artist || 'ไม่มีข้อมูลผู้ร้องในต้นฉบับ');
    $('preview-label').textContent = 'เพลงที่เลือก: ' + title +
      ' · ' + (artist || 'ไม่ระบุนักร้อง');
  }
  async function loadPreviewIdentity(songId, fallback = null) {
    if (fallback) showPreviewIdentity(fallback);
    if (!songId) return;
    try {
      const song = await api('/api/song/' + encodeURIComponent(songId));
      if (songId === previewSongId) showPreviewIdentity(song);
    } catch (error) {
      if (songId === previewSongId && !fallback)
        $('preview-label').textContent = 'อ่านชื่อเพลงและนักร้องไม่สำเร็จ: ' + error.message;
    }
  }
  async function loadPreviewSources(songId) {
    const seq = ++previewSourceSeq;
    const picker = $('preview-file-type');
    picker.disabled = true;
    picker.replaceChildren(new Option('กำลังตรวจประเภทไฟล์…', ''));
    $('preview-file-evidence').textContent = 'กำลังตรวจ Song, Lyrics, Cursor หรือ LRC ตามประเภทเพลง…';
    $('preview-file-inspection').hidden = true;
    if (!songId) return;
    try {
      const report = await api('/api/preview-sources?id=' + encodeURIComponent(songId));
      if (seq !== previewSourceSeq || songId !== previewSongId) return null;
      previewSourceSongId = songId;
      picker.replaceChildren();
      for (const choice of report.options || []) {
        const option = new Option(choice.label, choice.value);
        picker.add(option);
      }
      if (!picker.options.length) picker.add(new Option('ไม่พบไฟล์ที่ทดสอบได้', ''));
      picker.disabled = !report.options?.length;
      picker.value = report.options?.some(c => c.value === 'auto') ? 'auto' :
        (report.options?.[0]?.value || '');
      const evidence = $('preview-file-evidence');
      evidence.replaceChildren();
      for (const item of report.components || []) {
        const element = document.createElement('span');
        element.className = 'preview-component ' + (item.found ? 'found' : 'missing');
        element.textContent = (item.found ? '✓ ' : '✕ ') + item.type +
          (item.found ? ' · ' + item.name : ' · ไม่พบไฟล์');
        evidence.append(element);
      }
      const proof = document.createElement('p');
      proof.className = 'preview-proof-message';
      proof.textContent = (report.timedLyricsReady ? '✓ เนื้อร้องและเวลาผ่านการอ่านจริง' :
        '⚠ ยังยืนยันเนื้อร้องที่ตรงเวลาไม่ได้') + ' · ' + (report.proofMessage || '');
      evidence.append(proof);
      updateButtons();
      return report;
    } catch (error) {
      if (seq !== previewSourceSeq) return null;
      picker.replaceChildren(new Option('ตรวจไฟล์ไม่สำเร็จ', ''));
      $('preview-file-evidence').textContent = 'ตรวจองค์ประกอบไม่สำเร็จ: ' + error.message;
      updateButtons();
      return null;
    }
  }
  async function inspectPreviewFile(songId, kind) {
    stopLivePreview();
    const panel = $('preview-file-inspection');
    panel.hidden = false;
    panel.replaceChildren();
    panel.textContent = 'กำลังอ่านไฟล์ประกอบ…';
    try {
      const result = await api('/api/preview-inspect?id=' + encodeURIComponent(songId) +
        '&kind=' + encodeURIComponent(kind));
      if (songId !== previewSongId || $('preview-file-type').value !== kind) return;
      panel.replaceChildren();
      const summary = document.createElement('strong');
      summary.textContent = '✓ ' + result.file + ' · ' + result.message;
      panel.append(summary);
      if (result.text) {
        const content = document.createElement('pre');
        content.textContent = result.text;
        panel.append(content);
      }
      $('preview-label').textContent = 'ตรวจไฟล์ ' + result.file + ' แล้ว · ไม่มีการสร้างเพลง';
    } catch (error) {
      if (songId === previewSongId) {
        panel.textContent = '✕ ตรวจไฟล์ไม่ผ่าน: ' + error.message;
        $('preview-label').textContent = 'ตรวจไฟล์ประกอบไม่สำเร็จ';
      }
    }
  }
  async function loadPreviewLyrics(songId) {
    const seq = ++previewLyricsSeq;
    previewLyrics = null;
    currentLyricIndex = -2;
    previewLyricCoverageWarned = false;
    const panel = $('preview-lyrics-lines');
    panel.replaceChildren();
    const empty = document.createElement('div');
    empty.className = 'preview-lyrics-empty';
    empty.textContent = 'กำลังตรวจเนื้อร้องจากไฟล์ต้นฉบับ…';
    panel.append(empty);
    $('preview-lyrics-source').textContent = 'กำลังตรวจสอบ';
    $('preview-lyrics-source').dataset.state = 'loading';
    $('preview-lyrics-status').textContent = 'ตรวจสอบ LRC / KAR / NCN (Song + Lyrics + Cursor)';
    $('preview-lyrics-ai-tools').hidden = true;
    if (!songId) {
      empty.textContent = '♫ เลือกเพลงเพื่อดูเนื้อร้อง';
      $('preview-lyrics-source').textContent = 'ยังไม่ได้เลือกเพลง';
      $('preview-lyrics-status').textContent = 'เลือกเพลงแล้วระบบจะแสดงที่มาและเนื้อร้องตรงกับเวลา';
      return;
    }
    try {
      const result = await api('/api/preview-lyrics?id=' + encodeURIComponent(songId));
      if (seq !== previewLyricsSeq || songId !== previewSongId) return;
      previewLyrics = result;
      showPreviewIdentity(result);
      $('preview-lyrics-source').textContent = result.source || 'ไม่พบแหล่งข้อมูล';
      $('preview-lyrics-source').dataset.state = result.status || 'missing';
      $('preview-lyrics-status').textContent = result.message ||
        (result.status === 'found' ? 'พบเนื้อร้องจากไฟล์จริง' : 'ยังไม่พบเนื้อร้อง');
      panel.replaceChildren();
      if (Array.isArray(result.lines) && result.lines.length) {
        updateLyricTime(previewAudio.currentTime || 0);
      } else {
        const noLyrics = document.createElement('div');
        noLyrics.className = 'preview-lyrics-empty';
        noLyrics.textContent = result.status === 'missing'
          ? 'ไม่พบเนื้อร้องพร้อมเวลาของเพลงนี้ · ไม่สร้างข้อความหรือเวลาปลอม'
          : 'ไม่พบข้อความเนื้อร้องที่ตรวจได้';
        panel.append(noLyrics);
      }
      const aiControls = $('preview-lyrics-ai-tools');
      aiControls.hidden = result.status === 'found' || !result.aiEligible && result.status !== 'ai-draft';
      $('preview-ai-transcribe').disabled = !result.aiAvailable || busy;
      $('preview-ai-transcribe').textContent = result.aiAvailable
        ? '✦ ใช้ AI ถอดเสียงร้อง (ร่างสำหรับตรวจ)'
        : 'AI ถอดเสียงร้องยังไม่พร้อมในแพ็กเกจนี้';
      $('preview-ai-review').hidden = result.status !== 'ai-draft' || !result.draftLrc;
    } catch (error) {
      if (seq !== previewLyricsSeq) return;
      panel.replaceChildren();
      const alert = document.createElement('div');
      alert.className = 'preview-lyrics-empty';
      alert.textContent = 'ตรวจเนื้อร้องไม่สำเร็จ: ' + error.message;
      panel.append(alert);
      $('preview-lyrics-source').textContent = 'ตรวจสอบผิดพลาด';
      $('preview-lyrics-source').dataset.state = 'missing';
      $('preview-lyrics-status').textContent = error.message;
    }
  }
  async function transcribePreviewWithAi() {
    if (!previewSongId || !previewLyrics?.aiAvailable)
      return message('เพลงนี้ไม่มีไฟล์เสียงร้อง หรือแพ็กเกจยังไม่มีโมเดล AI ถอดเสียง');
    if (busy) return message('กรุณาให้งานที่กำลังทำอยู่เสร็จก่อน');
    const approved = await confirmStudio(
      'AI ใช้เสียงร้องในไฟล์จริงถอดเป็นข้อความแบบออฟไลน์ ผลอาจผิดหรือแต่งคำเกินจริง โดยเฉพาะเพลงดนตรีล้วน\n' +
      'ผลจะเป็นฉบับร่างในพื้นที่ส่วนตัวของ Windows เท่านั้น ไม่เพิ่ม Lyrics ในคลังอัตโนมัติ\n' +
      'ต้องตรวจคำและเวลาแล้วกดบันทึกก่อนใช้งาน ยืนยันหรือไม่?',
      'AI ถอดเนื้อร้องเป็นฉบับร่าง');
    if (!approved) return;
    stopLivePreview();
    const started = await run('ai-lyrics', {id:previewSongId, language:$('preview-ai-language').value});
    if (started) {
      $('preview-lyrics-status').textContent = 'AI กำลังถอดเสียง · ดูสถานะในแผงงาน · ไม่แก้ไขไฟล์เพลงต้นฉบับ';
      $('preview-ai-transcribe').disabled = true;
    }
  }
  async function reviewAiLyrics() {
    if (!previewSongId || previewLyrics?.status !== 'ai-draft' || !previewLyrics.draftLrc)
      return message('ไม่มีร่าง AI ที่ตรวจแก้ได้');
    try {
      const row = await api('/api/song/' + previewSongId);
      editingId = previewSongId;
      $('edit-code').textContent = (row.code || '') + ' · ' + (row.kind || '') + ' · ร่าง AI';
      $('edit-title').value = row.title || '';
      $('edit-artist').value = row.artist || '';
      $('edit-lyrics').value = previewLyrics.draftLrc;
      $('edit-dialog').showModal();
    } catch (error) { message(error.message); }
  }
  async function searchPreviewSongs() {
    if (!token || !engineBase) return;
    const seq = ++previewSearchSeq;
    const q = $('preview-song-search').value.trim();
    const list = $('preview-search-results');
    list.replaceChildren();
    const loading = document.createElement('div');
    loading.className = 'preview-empty';
    loading.textContent = 'กำลังค้นเพลง…';
    list.append(loading);
    try {
      const result = await api('/api/songs?offset=0&limit=30&preview_identity=1&search=' + encodeURIComponent(q));
      if (seq !== previewSearchSeq) return;
      previewSongRows = result.rows || [];
      list.replaceChildren();
      if (!previewSongRows.length) {
        const empty = document.createElement('div');
        empty.className = 'preview-empty';
        empty.textContent = 'ไม่พบชื่อเพลงที่ค้นหา ลองพิมพ์คำอื่นหรือสแกนต้นฉบับใหม่';
        list.append(empty);
        return;
      }
      for (const song of previewSongRows) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'preview-search-option';
        button.dataset.previewId = String(song.id);
        button.setAttribute('role', 'option');
        button.setAttribute('aria-selected', String(song.id === previewSongId));
        const info = document.createElement('span');
        info.className = 'preview-song-title';
        const title = document.createElement('strong');
        title.textContent = song.title || 'ไม่ระบุชื่อเพลง';
        const code = document.createElement('small');
        code.textContent = 'รหัส: ' + (song.code || '—');
        info.append(title, code);
        const performer = document.createElement('span');
        performer.className = 'preview-song-artist';
        performer.textContent = song.artist?.trim() || 'ไม่ระบุนักร้อง';
        if (!song.artist?.trim()) performer.classList.add('artist-unknown');
        const type = document.createElement('small');
        type.className = 'chip';
        type.textContent = song.kind || 'AUDIO';
        button.setAttribute('aria-label', [song.title || 'ไม่ระบุชื่อเพลง',
          song.artist?.trim() ? 'นักร้อง ' + song.artist.trim() : 'ไม่ระบุนักร้อง',
          'รหัส ' + (song.code || '—')].join(' · '));
        button.append(info, performer, type);
        list.append(button);
      }
    } catch(error) {
      if (seq !== previewSearchSeq) return;
      list.replaceChildren();
      const err = document.createElement('div');
      err.className = 'preview-empty';
      err.textContent = 'ค้นเพลงไม่สำเร็จ: ' + error.message;
      list.append(err);
    }
  }
  async function startLivePreview() {
    const songId = previewSongId || (selected.size === 1 ? [...selected][0] : null);
    if (!songId) return message('กรุณาค้นหาและเลือกเพลงจากรายการในขั้นตอนทดลองฟังก่อน');
    if (previewSourceSongId !== songId) await loadPreviewSources(songId);
    const choice = $('preview-file-type').value || 'auto';
    if (choice.startsWith('inspect:')) return inspectPreviewFile(songId, choice);
    if (livePreviewPending) { previewPendingChange = true; return; }
    livePreviewPending = true;
    $('preview-button').disabled = true;
    $('preview-label').textContent = 'กำลังเปิดเสียงสตรีมสด…';
    try {
      stopLivePreview();
      const serial = previewPlaySerial;
      $('preview-file-inspection').hidden = true;
      await saveInputs(['create-soundfont']);
      if (serial !== previewPlaySerial || songId !== previewSongId) return;
      const response = await post('/api/live-preview', {
        id:songId,
        source_choice:choice,
        music_volume:Number($('preview-music-volume').value) / 100,
        synth_volume:Number($('preview-sf-volume').value) / 100
      });
      if (serial !== previewPlaySerial || songId !== previewSongId ||
          $('preview-file-type').value !== choice) {
        if (response.stream_id) void post('/api/live-stop', {stream_id:response.stream_id}).catch(()=>{});
        return;
      }
      showPreviewIdentity(response);
      $('create-preview-hint').textContent = response.message ||
        (response.mixed ? 'เล่นเสียงดนตรีและ SoundFont พร้อมกัน' : 'เล่นแบบสด');
      $('preview-label').textContent = 'กำลังเล่น ' + (response.title || response.code || 'เพลงที่เลือก') +
        ' · ' + (response.artist?.trim() || 'ไม่ระบุนักร้อง');
      liveStreamId = response.stream_id || '';
      if (response.original_is_midi) $('create-preview-hint').textContent =
        'ดนตรีต้นฉบับ MIDI ใช้ SoundFont มาตรฐาน · เลื่อนเสียง SoundFont ที่เลือกเป็น 0% ก็ยังได้ยินเพลงเดิม';
      else if (!response.has_midi) $('create-preview-hint').textContent =
        'ไฟล์นี้เป็นเสียงดนตรีต้นฉบับล้วน ไม่มี MIDI คู่กัน จึงไม่มี SoundFont ให้ผสม';
      previewAudio.src = engineAddress('/api/live-stream?ticket=' + encodeURIComponent(response.ticket));
      const result = previewAudio.play();
      if (result) await result.catch(() => {
        message('เครื่องเล่นพร้อมแล้ว · กด ▶ ในแถบเครื่องเล่นเพื่อเริ่มเสียง', false);
      });
    } catch(error) {
      $('preview-label').textContent = 'ไม่สามารถทดลองฟังได้';
      message(error.message);
    } finally {
      livePreviewPending = false;
      updateButtons();
      if (previewPendingChange) {
        previewPendingChange = false;
        void startLivePreview();
      }
    }
  }

  // Independent AI Lyrics workspace: files are registered by the user in this menu.
  const aiAudio = $('ai-lyrics-audio');
  function aiParseLrc() {
    const rows = [], errors = [];
    let last = -1;
    for (const [index,raw] of $('ai-lyrics-editor').value.split(/\r?\n/).entries()) {
      const line = raw.trim();
      if (!line || /^\[[a-z][a-z0-9_-]{1,30}:[^\]]*\]$/i.test(line)) continue;
      const match = /^\[(\d{1,3}):(\d{2})(?:\.(\d{1,3}))?\](.+)$/.exec(line);
      if (!match || Number(match[2]) >= 60 || !match[4].trim()) {
        errors.push('บรรทัด ' + (index+1) + ' ไม่ใช่รูปแบบ LRC ที่ถูกต้อง');
        continue;
      }
      const seconds = Number(match[1])*60+Number(match[2])+
        Number((match[3]||'0').padEnd(3,'0'))/1000;
      if (seconds < last) errors.push('เวลาคำร้องบรรทัด '+(index+1)+' ไม่เรียงตามลำดับ');
      last = seconds;
      rows.push({startTime: seconds, text:match[4].trim()});
    }
    return {valid:rows.length>0 && errors.length===0, lines:rows, errors};
  }
  function aiUpdateButtons() {
    const hasSong = Number.isInteger(aiSongId);
    const valid = aiParseLrc().valid;
    $('ai-lyrics-start').disabled = busy || !hasSong || !aiEngineReady;
    $('ai-lyrics-read-source').disabled = busy || !hasSong;
    $('ai-lyrics-separate').disabled = busy || !hasSong || !aiSeparationAvailable;
    $('ai-lyrics-use-vocals').disabled = busy || !hasSong || !aiSeparatedPath;
    $('ai-lyrics-play').disabled = busy || !hasSong;
    $('ai-lyrics-editor').disabled = !hasSong;
    $('ai-lyrics-insert-time').disabled = !hasSong || !aiAudio.src;
    $('ai-lyrics-download').disabled = !hasSong || !valid;
    $('ai-lyrics-save').disabled = busy || !hasSong || !valid;
    for (const id of ['ai-lyrics-title','ai-lyrics-artist'])
      $(id).disabled = !hasSong;
    $('ai-lyrics-save-details').disabled = busy || !hasSong ||
      !$('ai-lyrics-title').value.trim();
    $('ai-export-button').disabled = busy || !hasSong ||
      (!$('ai-export-lyrics').checked && !$('ai-export-instrumental').checked && !$('ai-export-source').checked);
    $('ai-lyrics-paste').disabled = !hasSong;
    $('ai-lyrics-align').disabled = busy || !hasSong ||
      !(aiEngineReady || aiDraftReady) || !$('ai-lyrics-paste').value.trim();
    for(const control of $('ai-lyrics-results').querySelectorAll('[data-ai-remove]'))
      control.disabled=busy;
  }
  async function aiRefreshSongList() {
    if (!token || !engineBase) return;
    const seq = ++aiSearchSeq, panel = $('ai-lyrics-results');
    panel.textContent = 'กำลังอ่านไฟล์เสียงที่นำเข้า…';
    try {
      const data = await api('/api/vocal-songs?search='+
        encodeURIComponent($('ai-lyrics-search').value.trim())+
        '&offset='+aiOffset+'&limit=30');
      if (seq !== aiSearchSeq) return;
      aiSongs = data.rows || [];
      aiTotal = Number(data.total || 0);
      if(aiTotal && aiOffset>=aiTotal){
        aiOffset=Math.floor((aiTotal-1)/30)*30;
        return aiRefreshSongList();
      }
      panel.replaceChildren();
      for(const item of aiSongs) {
        const button = document.createElement('button');
        button.type='button'; button.className='ai-lyrics-song';
        button.dataset.aiId=String(item.id);
        button.classList.toggle('active',item.id===aiSongId);
        const info=document.createElement('span');
        const title=document.createElement('strong');
        title.textContent=item.title||item.code||'ไม่มีชื่อเพลง';
        const subtitle=document.createElement('small');
        subtitle.textContent=(item.artist||'ไม่ระบุศิลปิน')+' · '+item.code;
        info.append(title,subtitle);
        const chip=document.createElement('span');
        chip.className='chip';chip.textContent=item.kind||'AUDIO';
        const row=document.createElement('div');
        row.className='ai-lyrics-song-row';
        const remove=document.createElement('button');
        remove.type='button';remove.className='ai-lyrics-song-remove';
        remove.dataset.aiRemove=String(item.id);
        remove.textContent='นำออก';
        remove.title='นำเพลงนี้ออกจากรายการ AI (ไม่ลบไฟล์ต้นฉบับหรือร่างเนื้อร้อง)';
        remove.setAttribute('aria-label','นำ '+(item.title||item.code||'เพลงที่เลือก')+' ออกจากรายการ');
        remove.disabled=busy;
        button.append(info,chip);row.append(button,remove);panel.append(row);
      }
      if(!aiSongs.length) {
        const empty=document.createElement('div');
        empty.className='preview-empty';
        empty.textContent='ยังไม่มีเพลงในเมนูนี้ · กด “นำเข้าเพลงใหม่” เพื่อเลือกไฟล์จากเครื่อง';
        panel.append(empty);
      }
      $('ai-lyrics-count').textContent = aiTotal ?
        fmtNum(aiOffset+1)+'–'+fmtNum(Math.min(aiOffset+aiSongs.length,aiTotal))+
        ' จาก '+fmtNum(aiTotal)+' ไฟล์' : 'ยังไม่มีเพลงที่นำเข้า';
      $('ai-lyrics-prev').disabled=aiOffset===0;
      $('ai-lyrics-next').disabled=aiOffset+30>=aiTotal;
      aiUpdateButtons();
    } catch(error) {if(seq===aiSearchSeq)panel.textContent='อ่านรายการไม่สำเร็จ: '+error.message;}
  }
  async function aiSeparateVocals(){
    if(!Number.isInteger(aiSongId)||!canLaunch('ai-separate-vocals')||!aiSeparationAvailable)
      return message('กรุณาเลือกไฟล์เสียงร้องและตรวจว่า HTDemucs พร้อม');
    const id=aiSongId;
    const approved=await confirmStudio(
      'แยกเสียงร้องและดนตรีแบบออฟไลน์ด้วย HTDemucs แล้วบันทึก M4A แยก 2 ไฟล์ใน XStageSong/audio\n'+
      'เสียงเพลงต้นฉบับไม่เปลี่ยนและไม่อัปโหลด Google Drive\n'+
      'การแยกเสียงร้องอาจมีเสียงดนตรีหลงเหลือ ต้องทดลองฟังตรวจสอบ',
      'ยืนยันแยกเสียงร้องและดนตรีเป็น M4A',
      {acceptLabel:'เริ่มแยกเสียงร้อง',cancelLabel:'ยกเลิก'});
    if(!approved||!canLaunch('ai-separate-vocals')||aiSongId!==id)return;
    aiStopPlayback();
    $('ai-lyrics-vocals-status').textContent=
      'กำลังแยกเสียงร้องและดนตรีด้วย HTDemucs · ตรวจความคืบหน้าที่แผงงาน';
    await run('ai-separate-vocals',{id});
  }
  async function aiImportAudio() {
    if(busy)return message('มีงานกำลังดำเนินการ กรุณาให้เสร็จก่อนนำเข้า');
    $('ai-lyrics-status').textContent='กำลังเปิดหน้าต่างเลือกไฟล์เสียงจากเครื่อง…';
    try {
      const imported=await post('/api/vocal-import',{});
      if(imported.cancelled) {
        $('ai-lyrics-status').textContent='ยกเลิกการเลือกไฟล์แล้ว';
        return;
      }
      $('ai-lyrics-search').value='';aiOffset=0;
      await aiRefreshSongList();
      if(imported.song)await aiChooseSong(imported.song);
      message(imported.message||'นำเข้าไฟล์เสียงแล้ว',false);
    }catch(error) {
      $('ai-lyrics-status').textContent='นำเข้าไม่สำเร็จ: '+error.message;
      message(error.message);
    }
  }
  async function aiRemoveImportedSong(song) {
    if(busy) return message('มีงานกำลังดำเนินการ · กรุณารอให้เสร็จก่อนนำเพลงออก');
    if(!song || !Number.isInteger(song.id) || song.id>=0)return;
    const label=song.title||song.code||'เพลงที่เลือก';
    const approved=await confirmStudio(
      'นำเพลง “'+label+'” ออกจากรายการสร้างเนื้อร้อง AI ใช่หรือไม่?\n\n'+
      'การนำออกจะลบเฉพาะรายการที่นำเข้า ไม่ลบไฟล์เพลงต้นฉบับ ไม่ลบร่าง AI หรือ LRC ที่บันทึกไว้ในเครื่อง\n'+
      'สามารถนำเข้าไฟล์เดิมได้อีกครั้งภายหลัง',
      'ยืนยันนำเพลงออกจากรายการ AI',
      {acceptLabel:'นำออกจากรายการ',cancelLabel:'ยกเลิก'}
    );
    if(!approved)return;
    if(busy)return message('มีงานเริ่มประมวลผลแล้ว · กรุณาลองนำออกอีกครั้งหลังงานเสร็จ');
    try{
      const result=await post('/api/vocal-remove',{id:song.id});
      // Invalidate any delayed draft fetch from the removed selection.
      if(aiSongId===song.id){
        ++aiDraftSeq;
        aiStopPlayback();
        aiSongId=null;aiDraftReady=false;aiEngineReady=false;
        aiPastedLyrics.delete(song.id);
        if(pendingAiAlignment?.id===song.id)pendingAiAlignment=null;
        $('ai-lyrics-selected').textContent='ยังไม่ได้เลือกเพลง';
        $('ai-lyrics-title').value='';
        $('ai-lyrics-artist').value='';
        $('ai-lyrics-source-status').textContent='นำเพลงออกจากรายการแล้ว';
        aiDetailsDirty=false;
        $('ai-lyrics-editor').value='';
        $('ai-lyrics-paste').value='';
        $('ai-lyrics-align-review').textContent='นำเพลงออกจากรายการแล้ว';
        $('ai-lyrics-status').textContent='นำเพลงออกจากรายการแล้ว · เลือกหรือนำเข้าเพลงอื่นได้';
        aiValidateEditor();
      }
      await aiRefreshSongList();
      message(result.message||'นำเพลงออกจากรายการแล้ว · ไฟล์เพลงต้นฉบับยังอยู่',false);
    }catch(error){
      message('นำเพลงออกจากรายการไม่สำเร็จ: '+error.message);
    }
  }
  function aiStopKaraokeAnimation(){
    if(aiKaraokeFrame)cancelAnimationFrame(aiKaraokeFrame);
    aiKaraokeFrame=0;
  }
  function aiStopPlayback() {
    ++aiPlaySerial;
    aiStopKaraokeAnimation();
    const stream=aiStreamId;aiStreamId='';
    aiAudio.pause();aiAudio.removeAttribute('src');aiAudio.load();
    if(stream)void post('/api/live-stop',{stream_id:stream}).catch(()=>{});
    aiActiveIndex=-2;
    aiClockLast=-1;aiClockStalledAt=0;aiCoverageWarned=false;
  }
  let aiClockLast=-1,aiClockStalledAt=0,aiCoverageWarned=false;
  function aiRenderTime() {
    const panel=$('ai-lyrics-karaoke');
    if(!aiTimed.length)return;
    const t=Number(aiAudio.currentTime);
    if(!Number.isFinite(t)||t<0)return;
    // Follow the decoded audio clock. Never advance lyrics using wall time.
    // If the media stream stalls, surface the real problem instead of showing
    // a frozen lyric line without an explanation.
    const now=performance.now();
    if(Math.abs(t-aiClockLast)>.025){
      aiClockLast=t;aiClockStalledAt=now;
    }else if(!aiAudio.paused&&!aiAudio.seeking&&!aiAudio.ended&&
             aiAudio.readyState>=HTMLMediaElement.HAVE_CURRENT_DATA&&
             aiClockStalledAt&&now-aiClockStalledAt>3500){
      $('ai-lyrics-status').textContent=
        'เสียงทดลองฟังหยุดเดินที่ '+Math.floor(t/60)+':'+
        String(Math.floor(t%60)).padStart(2,'0')+
        ' · เป็นปัญหาสตรีมเสียง ไม่ใช่เวลา LRC · กดหยุดแล้วเล่นใหม่';
      aiClockStalledAt=now;
    }
    const finalTime=Number(aiTimed[aiTimed.length-1].startTime);
    if(!aiCoverageWarned&&!aiAudio.paused&&!aiAudio.ended&&
       Number.isFinite(finalTime)&&t>finalTime+6){
      aiCoverageWarned=true;
      $('ai-lyrics-status').textContent=
        'เสียงยังเล่น แต่เนื้อร้อง LRC สิ้นสุดที่ '+Math.floor(finalTime/60)+':'+
        String(Math.floor(finalTime%60)).padStart(2,'0')+
        ' · ตรวจว่าคำร้องหลังเวลานี้หายไปหรือยังไม่ได้จัดเวลา';
    }
    let lo=0,hi=aiTimed.length-1,current=-1;
    while(lo<=hi){
      const mid=(lo+hi)>>>1;
      if(aiTimed[mid].startTime<=t){current=mid;lo=mid+1;}
      else hi=mid-1;
    }
    if(aiActiveIndex!==current){
      aiActiveIndex=current;panel.replaceChildren();
      const from=Math.max(0,current<0?0:current-1);
      const until=Math.min(aiTimed.length,Math.max(from+2,current+3));
      for(let i=from;i<until;i++) {
        const entry=aiTimed[i];
        const start=Number(entry.startTime)||0;
        const next=Number(aiTimed[i+1]?.startTime);
        const end=Number.isFinite(next)&&next>start?next:start+4;
        const line=document.createElement('div');
        line.className='ai-karaoke-line';
        line.dataset.lineIndex=String(i);
        line.append(karaokeWipeSpan(entry.text,start,end));
        panel.append(line);
      }
    }
    for(const line of panel.querySelectorAll('[data-line-index]')){
      const i=Number(line.dataset.lineIndex);
      line.classList.toggle('active',i===current);
      karaokeUpdateSpans(line,t);
    }
  }
  function aiAnimateKaraoke(){
    aiKaraokeFrame=0;
    if(aiAudio.paused||aiAudio.ended)return;
    aiRenderTime();
    aiKaraokeFrame=requestAnimationFrame(aiAnimateKaraoke);
  }
  function aiStartKaraokeAnimation(){
    if(!aiKaraokeFrame)aiKaraokeFrame=requestAnimationFrame(aiAnimateKaraoke);
  }
  function aiValidateEditor() {
    const check=aiParseLrc();
    aiTimed=check.lines;aiActiveIndex=-2;aiCoverageWarned=false;
    if(check.lines.length)aiRenderTime();
    else $('ai-lyrics-karaoke').textContent='ยังไม่มีเนื้อร้องที่มีเวลาให้ทดลอง';
    $('ai-lyrics-validation').textContent=check.valid ?
      '✓ ตรวจรูปแบบ LRC แล้ว '+fmtNum(check.lines.length)+' บรรทัด · ควรฟังตรวจคำและเวลาอีกครั้ง':
      check.errors.length ? '✕ '+check.errors.slice(0,3).join(' · '):
      'ยังไม่มีเนื้อร้องที่มีเวลา';
    aiUpdateButtons();
  }
  async function aiChooseSong(row, {preferVocals=false}={}) {
    const previous=aiSongId===row.id&&$('ai-lyrics-use-vocals').checked;
    aiStopPlayback();
    aiSongId=row.id;
    aiSeparationAvailable=false;aiSeparatedPath=null;
    $('ai-lyrics-use-vocals').checked=false;
    $('ai-lyrics-vocals-status').textContent='กำลังตรวจไฟล์เสียงร้องที่แยกไว้…';
    const seq=++aiDraftSeq;
    aiDraftReady=false;aiEngineReady=false;aiDetailsDirty=false;
    $('ai-lyrics-title').value=row.title||row.code||'';
    $('ai-lyrics-artist').value=String(row.artist||'').trim()||'X-Stage Song Studio';
    $('ai-lyrics-source-status').textContent='กำลังอ่านชื่อเพลง ผู้ร้อง และเนื้อร้องจากไฟล์ต้นฉบับ…';
    $('ai-lyrics-selected').textContent=(row.title||row.code)+
      ' · '+(String(row.artist||'').trim()||'X-Stage Song Studio')+' · '+(row.kind||'');
    $('ai-lyrics-editor').value='';
    $('ai-lyrics-paste').value=aiPastedLyrics.get(row.id)||'';
    $('ai-lyrics-align-review').textContent='วางเนื้อเพลงถูกต้องแล้วกด AI จัดเวลา · ผลเป็นเวลาโดยประมาณ ต้องฟังตรวจ';
    $('ai-lyrics-status').textContent='กำลังตรวจโมเดล AI และร่างเนื้อร้องที่เคยสร้าง…';
    for(const button of $('ai-lyrics-results').querySelectorAll('[data-ai-id]'))
      button.classList.toggle('active',Number(button.dataset.aiId)===row.id);
    aiValidateEditor();
    try{
      const data=await api('/api/ai-lyrics-draft?id='+encodeURIComponent(row.id));
      if(seq!==aiDraftSeq||row.id!==aiSongId)return;
      aiEngineReady=Boolean(data.available);
      aiDraftReady=Boolean(data.hasDraft);
      aiSeparationAvailable=Boolean(data.separationAvailable);
      aiSeparatedPath=typeof data.separatedVocals==='string'&&data.separatedVocals?
        data.separatedVocals:null;
      $('ai-lyrics-use-vocals').checked=Boolean(aiSeparatedPath&&(preferVocals||previous));
      $('ai-lyrics-vocals-status').textContent=aiSeparatedPath?
        '✓ พบไฟล์เสียงร้องแยก M4A · '+aiSeparatedPath+
        ' · เลือกช่องเพื่อใช้ถอดคำร้องกับ Whisper AI':
        aiSeparationAvailable?
        'ยังไม่มีเสียงแยก · กดสร้าง M4A เสียงร้องและดนตรีโดยไม่แก้ต้นฉบับ':
        'HTDemucs ไม่พร้อม · ตรวจแพ็กเกจ PC Ready และโมเดล AI';
      if(!aiDetailsDirty){
        $('ai-lyrics-title').value=data.title||row.title||row.code||'';
        $('ai-lyrics-artist').value=String(data.artist||'').trim()||'X-Stage Song Studio';
      }
      const originalTimed=String(data.sourceLrc||'');
      const originalPlain=String(data.hasSavedPlainLyrics?
        data.savedPlainLyrics:(data.sourcePlainLyrics||''));
      $('ai-lyrics-editor').value=String(data.approvedLrc||originalTimed||data.draft?.rawLrc||'');
      if(!aiPastedLyrics.has(row.id))$('ai-lyrics-paste').value=originalPlain;
      const info=[];
      info.push(data.metadataSource||'ไม่พบชื่อผู้ร้องในแท็ก · แก้ไขเองได้');
      info.push(data.approvedLrc?'ใช้ LRC ที่บันทึกไว้แล้ว':
        originalTimed?(data.lyricsSource||'พบคำร้องพร้อมเวลา'):
        originalPlain?(data.lyricsSource||'พบคำร้องที่ไม่มีเวลา'):
        data.hasDraft?'พบร่าง AI':'ไม่พบเนื้อร้องในต้นฉบับ · พิมพ์หรือใช้ AI ได้');
      $('ai-lyrics-source-status').textContent=info.join(' · ');
      $('ai-lyrics-engine-state').textContent=aiEngineReady ?
        'Whisper AI พร้อมใช้งาน' : 'Whisper AI ไม่พร้อม';
      $('ai-lyrics-status').textContent=!aiEngineReady ?
        'AI ยังถอดคำร้องไม่ได้: '+(data.aiProblem||'กรุณาติดตั้ง PC Ready รุ่นเต็มให้ครบ'):
        data.approvedLrc ?
        '✓ พบเนื้อร้อง LRC ที่เคยบันทึกแล้ว · แก้ไขและทดลองฟังได้':
        originalTimed ? '✓ อ่านเนื้อร้อง LRC ต้นฉบับพร้อมเวลาแล้ว · แก้ไขได้ทันที':
        originalPlain ? '✓ อ่านเนื้อร้องต้นฉบับไม่มีเวลาแล้ว · แก้ไขและบันทึกได้':
        data.hasDraft ? 'พบร่างคำร้อง AI · โปรดฟังตรวจคำและเวลา':
        'ไม่พบเนื้อร้องต้นฉบับ · สามารถพิมพ์เองหรือให้ AI ถอดเสียง';
      aiValidateEditor();
    }catch(error){
      if(seq===aiDraftSeq)$('ai-lyrics-status').textContent='อ่านข้อมูลเพลงไม่สำเร็จ: '+error.message;
    }
  }
  async function aiSaveSourceDetails(){
    if(!Number.isInteger(aiSongId)||busy)return;
    const id=aiSongId;
    const title=$('ai-lyrics-title').value.trim();
    const artist=$('ai-lyrics-artist').value.trim()||'X-Stage Song Studio';
    const plainLyrics=$('ai-lyrics-paste').value;
    if(!title)return message('กรุณาระบุชื่อเพลงก่อนบันทึก');
    try{
      const result=await post('/api/ai-lyrics-details',{id,title,artist,plainLyrics});
      if(id!==aiSongId)return;
      aiDetailsDirty=false;
      aiPastedLyrics.delete(id);
      const row=aiSongs.find(item=>item.id===id);
      if(row){row.title=title;row.artist=artist;}
      $('ai-lyrics-selected').textContent=title+' · '+(artist||'ไม่ระบุศิลปิน');
      $('ai-lyrics-source-status').textContent='✓ บันทึกการแก้ไขลงฐานข้อมูลส่วนตัวแล้ว · ไฟล์ต้นฉบับไม่เปลี่ยน';
      await aiRefreshSongList();
      message(result.message||'บันทึกข้อมูลเพลงแล้ว',false);
    }catch(error){message('บันทึกข้อมูลเพลงไม่สำเร็จ: '+error.message);}
  }
  async function aiExportSelected() {
    if (!Number.isInteger(aiSongId) || busy) return;
    const id=aiSongId;
    const lyrics=$('ai-export-lyrics').checked;
    const instrumental=$('ai-export-instrumental').checked;
    const source=$('ai-export-source').checked;
    const source_format=$('ai-export-format').value;
    if (!lyrics && !instrumental && !source)
      return message('กรุณาเลือกเนื้อร้อง เพลงตัดเสียงร้อง หรือไฟล์ต้นฉบับอย่างน้อยหนึ่งรายการ');
    // Persist destination exactly as the existing Download settings do.
    try { await saveInputs(['download-destination']); }
    catch(error) { return message('บันทึกโฟลเดอร์ส่งออกไม่ได้: '+error.message); }
    const label=[lyrics?'LRC เนื้อร้องที่ตรวจแล้ว':null,
                 instrumental?'M4A เพลงตัดเสียงร้อง':null,
                 source?'เพลงต้นฉบับ ('+(source_format==='original'?'คัดลอก':source_format)+')':null].filter(Boolean).join(' + ');
    const yes=await confirmStudio(
      'ส่งออก '+label+' ไปที่\\n'+(prefs.download||'ยังไม่ได้ตั้งค่า')+
      '\\n\\nถ้า M4A ยังไม่มี ระบบจะแยกเสียงก่อน · ไม่แก้เพลงต้นฉบับและไม่เขียนทับไฟล์เดิม',
      'ยืนยันส่งออกไฟล์ที่เลือก',
      {acceptLabel:'เริ่มส่งออก',cancelLabel:'ยกเลิก'});
    if (!yes || busy || aiSongId!==id) return;
    $('ai-export-status').textContent='กำลังส่งออก '+label+' · ติดตามสถานะที่แผงงาน';
    await run('ai-export',{id,lyrics,instrumental,source,source_format});
  }

  async function aiStartTranscription() {
    if(!Number.isInteger(aiSongId)||!aiEngineReady||!canLaunch('ai-lyrics'))
      return message('กรุณานำเข้าเพลงเสียงร้องและตรวจว่า Whisper AI พร้อมใช้งาน');
    const consent=await confirmStudio(
      'AI จะถอดเสียงจากไฟล์เพลงที่เลือก พร้อมประเมินเวลาแต่ละบรรทัดแบบออฟไลน์\n'+
      'คำร้องและเวลาอาจผิด ต้องทดลองฟังและตรวจแก้ก่อนบันทึก ยืนยันให้เริ่มหรือไม่?',
      'เริ่มสร้างเนื้อร้อง AI');
    if(!consent)return;
    aiStopPlayback();
    $('ai-lyrics-status').textContent='เริ่มถอดเสียงร้อง AI · ตรวจสถานะได้ที่แผงงานด้านล่าง';
    void run('ai-lyrics',{id:aiSongId,language:$('ai-lyrics-language').value,
      useSeparatedVocals:$('ai-lyrics-use-vocals').checked});
  }
  async function aiAlignPastedLyrics() {
    if(!Number.isInteger(aiSongId)||!canLaunch('ai-align') || !(aiEngineReady||aiDraftReady))
      return message('กรุณาเลือกเพลงเสียงร้องและตรวจว่า AI พร้อม หรือมีร่าง Whisper เดิม');
    const lyrics=$('ai-lyrics-paste').value;
    if(!lyrics.trim())return message('กรุณาวางเนื้อเพลงที่ถูกต้องทีละบรรทัดก่อน');
    if(/^\s*\[\d{1,3}:\d{2}/m.test(lyrics))
      return message('พบเวลา LRC อยู่แล้ว · ช่องวางเนื้อเพลงรับข้อความที่ยังไม่มีเวลา');
    const approved=await confirmStudio(
      'โปรแกรมจะใช้คำร้องที่คุณวางไว้ตามเดิม แล้วเทียบกับผลถอดเสียง Whisper ที่มีเวลา\n'+
      'หากยังไม่มีร่าง Whisper จะถอดเสียงร้องจากไฟล์เพลงก่อน โดยไม่แก้คำที่คุณวาง\n\n'+
      'เวลาเป็นค่าประมาณ ไม่ใช่การจัดคำต่อคำอย่างแม่นยำ ต้องทดลองฟังและแก้ก่อนบันทึก',
      'ยืนยัน AI จัดเวลาให้เนื้อเพลงที่วาง',
      {acceptLabel:'เริ่มจัดเวลา',cancelLabel:'ยกเลิก'}
    );
    if(!approved)return;
    if(busy)return message('มีงานอื่นกำลังดำเนินการ');
    aiStopPlayback();
    const id=aiSongId;
    pendingAiAlignment={id,lyrics};
    $('ai-lyrics-align-review').textContent='กำลังเทียบเนื้อเพลงที่วางกับเสียงร้อง · จะไม่แก้คำร้องต้นฉบับ';
    $('ai-lyrics-status').textContent='AI กำลังจัดเวลาเนื้อเพลงที่วาง…';
    const started=await run('ai-align',{
      id,lyrics,language:$('ai-lyrics-language').value,
      useSeparatedVocals:$('ai-lyrics-use-vocals').checked
    });
    if(!started)pendingAiAlignment=null;
  }
  async function aiPlayAudio() {
    if(!Number.isInteger(aiSongId))return message('กรุณาเลือกเพลงที่นำเข้าก่อน');
    if(busy)return message('งาน AI ยังดำเนินการอยู่');
    aiStopPlayback();
    const serial=aiPlaySerial,chosen=aiSongId;
    $('ai-lyrics-status').textContent='กำลังเปิดเสียงต้นฉบับสำหรับทดลองเนื้อร้อง…';
    try{
      const res=await post('/api/live-preview',{
        id:chosen,source_choice:$('ai-lyrics-use-vocals').checked?'ai-vocals':'audio:'+chosen,
        music_volume:1,synth_volume:0
      });
      if(serial!==aiPlaySerial||chosen!==aiSongId){
        if(res.stream_id)void post('/api/live-stop',{stream_id:res.stream_id}).catch(()=>{});
        return;
      }
      aiStreamId=res.stream_id||'';
      aiAudio.src=engineAddress('/api/live-stream?ticket='+encodeURIComponent(res.ticket));
      const play=aiAudio.play();
      if(play)await play.catch(()=>message('กด ▶ บนเครื่องเล่นเพื่อฟัง',false));
      $('ai-lyrics-status').textContent='ทดลองฟัง '+
        ($('ai-lyrics-use-vocals').checked?'เสียงร้องที่แยกไว้':'เพลงต้นฉบับ')+
        ' · ตรวจคำและเวลาในจอคาราโอเกะ';
    }catch(error){
      $('ai-lyrics-status').textContent='ทดลองฟังไม่สำเร็จ: '+error.message;
      message(error.message);
    }
  }
  function aiInsertTimestamp() {
    const t=aiAudio.currentTime||0;
    const minute=Math.floor(t/60), seconds=(t%60).toFixed(2).padStart(5,'0');
    const stamp='['+String(minute).padStart(2,'0')+':'+seconds+']';
    const editor=$('ai-lyrics-editor');
    editor.setRangeText(stamp,editor.selectionStart,editor.selectionEnd,'end');
    editor.focus();aiValidateEditor();
  }
  function aiDownloadLrc() {
    const result=aiParseLrc();
    if(!result.valid)return message('ตรวจรูปแบบเนื้อร้องก่อนดาวน์โหลด LRC');
    const blob=new Blob([$('ai-lyrics-editor').value],{type:'text/plain;charset=utf-8'});
    const url=URL.createObjectURL(blob);
    const link=document.createElement('a');link.href=url;
    link.download='XStage-AI-'+String(aiSongId)+'.lrc';
    document.body.append(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),5000);
  }
  async function aiApproveLrc() {
    if(!aiParseLrc().valid)
      return message('ต้องมีเนื้อร้อง LRC ที่มีเวลาถูกต้องก่อนบันทึก');
    if(!await confirmStudio(
      'ตรวจคำร้องและเวลาเทียบกับเสียงจริงแล้วใช่หรือไม่?\n'+
      'ยืนยันบันทึกลงข้อมูลเพลงส่วนตัว (ไม่แก้ไฟล์เสียงต้นฉบับ)',
      'ยืนยันเนื้อร้องที่ตรวจแก้แล้ว'))return;
    try{
      const result=await post('/api/ai-lyrics-approve',{
        id:aiSongId,lrc:$('ai-lyrics-editor').value
      });
      $('ai-lyrics-status').textContent='✓ '+result.message;
      message('บันทึก LRC ที่ตรวจแล้ว '+fmtNum(result.lines)+' บรรทัด',false);
    }catch(error){message(error.message);}
  }
  function buildFeedback(state, title, detail) {
    const card = $('create-build-feedback');
    if (!card) return;
    card.dataset.state = state;
    $('create-build-feedback-icon').textContent = state === 'error' ? '!' :
      state === 'success' ? '✓' : state === 'running' || state === 'starting' ? '◉' : '♫';
    $('create-build-feedback-title').textContent = title;
    $('create-build-feedback-detail').textContent = detail;
  }
  function showBuildLog() {
    const logs = $('job-log');
    logs.hidden = false;
    $('toggle-log').setAttribute('aria-expanded', 'true');
    $('job-panel').scrollIntoView({behavior:'smooth',block:'center'});
  }
  // A fresh accepted job replaces only its own page's previous run state.
  // Other active jobs, catalog data and completed output files are untouched.
  const jobStatusFields = {
    'xsk-stream':['xsk-stream-status'],
    'json-pro-export':['json-pro-report'],
    'pc-export':['pc-export-status'],
    'upload-folder':['upload-folder-report'],
    'upload-soundfont':['upload-soundfont-status'],
    'upload':['upload-status'],
    'created-xsk':['created-xsk-status'],
    'ai-lyrics':['ai-lyrics-status'],
    'ai-align':['ai-lyrics-status','ai-lyrics-align-review'],
    'ai-separate-vocals':['ai-lyrics-status','ai-lyrics-vocals-status'],
    'ai-export':['ai-export-status'],
    'check-update':['update-result'],
    'download-update':['update-result'],
    'install-update':['update-result'],
  };
  function resetStatusForNewJob(action, id) {
    for(const field of jobStatusFields[action]||[]) {
      const element=$(field);
      if(element)element.textContent='กำลังเริ่มงานใหม่ · '+action+' · เลขงาน '+id;
    }
    // Remove only historic completed records of this same action. Live
    // unrelated workers stay on screen and keep their own progress.
    activeJobs=activeJobs.filter(job=>job.kind!==action || job.state==='running');
    if(action==='build') {
      buildFeedback('starting','เริ่มสร้างเพลงรอบใหม่','เลขงาน '+id+' · เริ่มนับใหม่');
    }
    $('job-title').textContent='● เริ่มงานใหม่: '+action;
    $('job-detail').textContent='เลขงาน '+id+' · รอความคืบหน้าจาก PC Engine';
    $('job-fraction').textContent='เริ่มงานใหม่ · 0 รายการ';
    $('job-skip-count').textContent='ข้ามซ้ำ 0 · ERR 0 · M4A 0 · Lyrics 0';
    $('job-eta').textContent='เวลาคงเหลือ —';
    $('job-timing').textContent='00:00';
    $('job-log').replaceChildren();
    const fill=$('progress-fill');
    fill.style.width='33%';
    fill.classList.add('indeterminate');
    $('job-led').className='job-led running';
  }
  async function run(action, options = {}) {
    if (!canLaunch(action)) {
      message('งานชนิดนี้กำลังทำอยู่ หรือ CPU/RAM ไม่พร้อมรับงานเพิ่ม · ตรวจรายการงานด้านล่าง');
      return false;
    }
    if (action === 'build') {
      buildFeedback('starting', 'กำลังส่งคำสั่งสร้างเพลงไปยัง PC Engine…',
        'กำลังตรวจสิทธิ์เขียนไฟล์และรายการเพลงที่เลือก');
    }
    try {
      const response = await post('/api/jobs', {action, ...options});
      if (!response?.id) throw new Error('Local Engine ไม่คืนเลขงาน โปรดตรวจสอบการเชื่อมต่อแล้วลองอีกครั้ง');
      lastJobId = response.id; lastJobState = 'running';
      resetStatusForNewJob(action,response.id);
      busy = true;
      activeJobs=[{id:response.id,kind:action,state:'running',stage:'กำลังเริ่มต้น',
                   completed:0,total:response.total||0,created:0,skipped:0,errors:0,logs:[]},...activeJobs];
      updateButtons();
      if (action === 'build') {
        buildFeedback('running', 'PC Engine รับคำสั่งสร้างเพลงแล้ว',
          'เลขงาน ' + response.id + ' · ' + fmtNum(response.total ?? options.ids?.length ?? 0) +
          ' เพลง · ' + (options.audio_only ? 'สร้าง M4A อย่างเดียว' :
             options.export_format==='xsk' ? 'สร้าง XSK เข้ารหัส' :
             options.export_format==='xstage' ? 'ส่งออกแบบเดิม' :
             'สร้าง M4A + Lyrics JSON') +
          ' · กำลังติดตามสถานะ');
        message('รับคำสั่งสร้างเพลงแล้ว · ตรวจสถานะได้ในขั้นตอนที่ 4', false);
      }
      await loadState();
      if (action !== 'build') $('job-panel').scrollIntoView({behavior:'smooth',block:'nearest'});
      return true;
    } catch (error) {
      if (action === 'build') buildFeedback('error', 'ไม่สามารถเริ่มสร้างเพลงได้', error.message);
      message('PC Engine ไม่รับงาน: '+error.message);
      return false;
    }
  }
  const selectedIDs = () => [...selected];
  async function startStreamingXsk() {
    if(!canLaunch('xsk-stream'))return message('งานแปลงเพลงกำลังทำอยู่ หรือเครื่องไม่พร้อมรับงานเพิ่ม');
    try{
      await saveInputs(['create-source','xsk-build-folder',
                        'xsk-stream-code-style','xsk-stream-code-length']);
      const source=(prefs.source||'').trim();
      const destination=(prefs.xsk_folder||prefs.workspace||'').trim();
      const count=Number($('xsk-stream-code-length').value);
      if(!source||!destination)throw new Error('กรุณาเลือกต้นทางและปลายทาง');
      if(!Number.isInteger(count)||count<1||count>12)
        throw new Error('จำนวนหลักรหัสเพลงต้องอยู่ระหว่าง 1–12');
      // One-click folder-to-folder batch conversion; input validation stays in place.
      // Engine retains duplicate, input integrity and no-overwrite safety checks.
      $('xsk-stream-status').textContent='กำลังส่งงานสแกนและสร้าง .XSK แบบต่อเนื่อง…';
      const started=await run('xsk-stream',{
        source,xsk_folder:destination,
        code_style:$('xsk-stream-code-style').value,
        code_length:String(count)
      });
      if(started)$('xsk-stream-status').textContent=
        'PC Engine รับงานแล้ว · จัดคิวครั้งละ 32 เพลง · ตรวจความคืบหน้าที่แผงงานด้านล่าง';
    }catch(error){
      $('xsk-stream-status').textContent='เริ่มงานไม่สำเร็จ: '+error.message;
      message(error.message);
    }
  }

  async function startBuild(audioOnly) {
    if (busy) return message('มีงานกำลังดำเนินการอยู่ กรุณารอให้จบก่อน');
    if (!selected.size) {
      buildFeedback('error', 'ยังไม่ได้เลือกเพลงเพื่อสร้าง', 'กรุณากลับไปขั้นตอนที่ 2 แล้วเลือกรายการอย่างน้อยหนึ่งเพลง');
      return message('กรุณาเลือกเพลงก่อนสร้าง');
    }
    try {
      buildFeedback('starting', 'กำลังตรวจสอบไฟล์ต้นฉบับและพื้นที่ว่าง…',
        'ยังไม่เริ่มสร้างไฟล์ · ตรวจสอบรายการที่เลือกอยู่');
      const chosenOutput=$('create-output-kind').value;
      await saveInputs(['create-source','create-soundfont','create-preset',
         'create-mode','create-code-style','create-code-length','xsk-build-folder']);
      await config({export_format:chosenOutput});
      const ids = selectedIDs();
      const estimate = await post('/api/estimate', {ids});
      if (!estimate.songs) throw new Error('ไม่พบเพลงที่เลือกในฐานข้อมูล กรุณาสแกนโฟลเดอร์ใหม่และเลือกเพลงอีกครั้ง');
      if (!estimate.enoughDisk) throw new Error('พื้นที่ว่างไม่เพียงพอ กรุณาเปลี่ยนโฟลเดอร์บันทึกหรือเพิ่มพื้นที่ว่าง');
      const formats = Object.entries(estimate.formats || {}).sort((a,b)=>b[1]-a[1])
        .map(([extension,count]) => (extension || 'ไม่มีนามสกุล').toUpperCase() + ' ' + fmtNum(count)).join(' · ');
      if ($('create-output-kind').value==='xsk' && ![...selectedIDs()].some(id=>true)) throw new Error('ยังไม่ได้เลือกเพลง');
      if (estimate.unsupported >= estimate.songs) throw new Error(
        'เพลงที่เลือกทั้งหมดเป็น NCN ซึ่ง PC Engine รุ่นนี้ยังแปลงไม่ได้ · กรุณาเลือกเพลงรูปแบบที่รองรับ');
      const warning = (formats ? '\nประเภทไฟล์: ' + formats : '') +
        (estimate.warning ? '\n\n⚠ รายการขนาดใหญ่ โปรแกรมจะสร้างทีละเพลง ไม่คัดลอกต้นฉบับทั้งหมด' : '') +
        (estimate.spaceWarning ? '\n⚠ พื้นที่ว่างอาจไม่พอสำหรับสร้างทุกเพลง หากเต็มจะหยุดรายการที่เหลือและเก็บเพลงที่สำเร็จไว้' : '') +
        (estimate.unsupported ? '\n⚠ มี ' + fmtNum(estimate.unsupported) + ' ไฟล์ NCN ซึ่งยังไม่รองรับ และจะแจ้ง ERR รายเพลง' : '');
      const exportFormat=audioOnly?'m4a':$('create-output-kind').value;
      const summary = 'จำนวน ' + fmtNum(estimate.songs) + ' เพลง (' + fmtSize(estimate.bytes) + ')\n' +
        'วิธีสร้าง: ' + (audioOnly ? 'M4A อย่างเดียว' :
          exportFormat==='xsk' ? 'สร้าง XSK ที่เข้ารหัส' :
          exportFormat==='xstage' ? 'ส่งออกเพลงแบบเดิม' :
          'แปลง M4A + Lyrics JSON') +
        '\nไฟล์ที่สร้างแล้วจะถูกตรวจซ้ำและข้ามโดยไม่สร้างใหม่' + warning;
      buildFeedback('starting', 'ตรวจสอบพร้อม · รอผู้ใช้ยืนยันสร้างเพลง',
        'เลือก ' + fmtNum(ids.length) + ' เพลง · ยังไม่ได้เริ่ม Engine · กด “ยืนยัน” เพื่อสร้างไฟล์');
      const approved = await confirmStudio(summary, 'ยืนยันเริ่มสร้างเพลง');
      if (!approved) {
        buildFeedback('idle', 'ยกเลิกก่อนเริ่มสร้างเพลง', 'คำสั่งไม่ได้ส่งไปยัง PC Engine · กดสร้างและยืนยันอีกครั้งได้');
        return;
      }
      buildFeedback('starting', 'ยืนยันแล้ว · กำลังส่งงานให้ PC Engine…',
        'กำลังส่งรายการ ' + fmtNum(ids.length) + ' เพลง · รอเลขงานจาก Engine');
      await run('build', {ids, audio_only:audioOnly,
         export_format:exportFormat, edit_head_tail:$('xsk-edit-choice').value,
         head_find:$('xsk-head-find').value,head_replace:$('xsk-head-replace').value,
         tail_find:$('xsk-tail-find').value,tail_replace:$('xsk-tail-replace').value});
    } catch (error) {
      buildFeedback('error', 'เริ่มสร้างเพลงไม่ได้', error.message);
      message(error.message);
    }
  }
  async function chooseUploadSoundfont() {
    if (busy) return;
    try {
      const result=await post('/api/folder-picker',{kind:'soundfont'});
      if (!result.path) return;
      await config({soundfont:result.path});
      $('upload-soundfont-path').value=result.path;
      $('upload-soundfont-status').textContent='เลือก SoundFont แล้ว · ตรวจความพร้อมก่อนอัปโหลด';
    } catch (error) { message('เลือก SoundFont ไม่สำเร็จ: '+error.message); }
  }
  async function startSoundfontUpload() {
    if (busy || !googleConnected)
      return message('กรุณาล็อกอิน Google Drive ก่อนอัปโหลด SoundFont');
    try {
      await saveInputs(['upload-soundfont-path']);
      const createNew=$('upload-allow-new').checked;
      const agreed=await confirmStudio(
        'อัปโหลด SoundFont ที่เลือกไปยัง XStageSong/AUDIO สำหรับ SoundFont SF2/SF3'+
        '\\nตรวจไฟล์และ MD5 ก่อนส่ง ไม่ทับ SoundFont เดิม'+
        (createNew?'\\nถ้ามองไม่เห็น XStageSong ระบบจะสร้างใหม่ โปรดตรวจบัญชีและสิทธิ์ Google ก่อน':'')+
        '\\n\\nหมายเหตุ: เว็บหลักยังไม่มี MIDI SoundFont Engine พร้อมเล่น',
        'ยืนยันอัปโหลด SoundFont',
        {acceptLabel:'เริ่มอัปโหลด',cancelLabel:'ยกเลิก'});
      if (!agreed) return;
      $('upload-soundfont-status').textContent='กำลังอัปโหลด SoundFont · ตรวจความคืบหน้าในแผงงาน';
      await run('upload-soundfont',{create_new_library:createNew});
    } catch(error){$('upload-soundfont-status').textContent=error.message;message(error.message);}
  }
  // Both import menus have isolated, read-only preview players.
  const importPreviews = new Map();
  for (const kind of ['online', 'pc']) {
    const state = {kind, offset:0, total:0, rows:[], session:'', lines:[], serial:0, loaded:false};
    importPreviews.set(kind, state);
    const audio = $(kind+'-preview-audio');
    const selected = $(kind+'-preview-select');
    const setStatus = value => {$(kind+'-preview-status').textContent=value;};
    function stop() {
      state.serial++;
      audio.pause();
      audio.removeAttribute('src');
      audio.load();
      if (state.session) {
        const previous=state.session;state.session='';
        void post('/api/live-stop',{stream_id:previous}).catch(()=>{});
      }
      $(kind+'-preview-stop').disabled=true;
    }
    state.stop=stop;
    function drawLyrics(time=0) {
      const node=$(kind+'-preview-lyrics');
      for(const line of node.querySelectorAll('[data-preview-time]')) {
        const from=Number(line.dataset.previewTime),end=Number(line.dataset.previewEnd);
        const active=time>=from&&time<end;
        line.classList.toggle('active',active);
        line.style.fontWeight=active?'700':'400';
        line.style.opacity=active?'1':'.75';
        if(active && node.dataset.active!==line.dataset.previewTime){
          node.dataset.active=line.dataset.previewTime;
          line.scrollIntoView({block:'nearest'});
        }
      }
    }
    function showLyrics(lines) {
      state.lines=lines;
      const node=$(kind+'-preview-lyrics');node.replaceChildren();node.dataset.active='';
      if(!lines.length){
        const p=document.createElement('p');p.className='hint';
        p.textContent='ไม่มีเนื้อร้องพร้อมเวลาที่แสดงได้';node.append(p);return;
      }
      for(const line of lines){
        const p=document.createElement('div');
        p.textContent=line.text;
        p.dataset.previewTime=String(line.startTime);
        p.dataset.previewEnd=String(line.endTime);
        p.style.padding='4px 6px';
        node.append(p);
      }
      drawLyrics(audio.currentTime);
    }
    async function load(reset=false) {
      stop();
      const ticket=++state.serial;
      if(reset)state.offset=0;
      const qs=new URLSearchParams({kind,search:$(kind+'-preview-search').value.trim(),
                    offset:String(state.offset),limit:'50'});
      try {
        const data=await api('/api/import-preview/list?'+qs);
        if(ticket!==state.serial)return;
        state.total=data.total||0;state.rows=data.rows||[];
        state.loaded=!data.needsScan;
        selected.replaceChildren();
        selected.add(new Option('เลือกเพลงเพื่อทดลองฟัง',''));
        for(const item of state.rows){
          selected.add(new Option((item.code||'')+' · '+(item.title||'')+' ['+item.kind+']',String(item.id)));
        }
        const first=state.total?state.offset+1:0;
        $(kind+'-preview-page').textContent=first+'–'+(state.offset+state.rows.length)+' / '+state.total;
        $(kind+'-preview-prev').disabled=state.offset===0;
        $(kind+'-preview-next').disabled=state.offset+50>=state.total;
        $(kind+'-preview-play').disabled=true;
        showLyrics([]);
        setStatus(data.needsScan?'เลือกโฟลเดอร์แล้วกดโหลดรายการเพลงสำหรับพรีวิว':
          'พบ '+state.total+' เพลงที่มีไฟล์เสียง · เลือกเพลงเพื่อฟังได้');
      }catch(error){setStatus('อ่านรายการเพลงไม่สำเร็จ: '+error.message);}
    }
    async function scan() {
      stop();setStatus('กำลังตรวจต้นทางและจัดรายการเพลงสำหรับพรีวิว…');
      $(kind+'-preview-scan').disabled=true;
      const current=++state.serial;
      try{
        await saveInputs([kind==='online'?'upload-folder':'create-workspace']);
        const result=await post('/api/import-preview/scan',{kind});
        if(current!==state.serial)return;
        state.offset=0;state.loaded=true;
        setStatus('ตรวจพบ '+result.total+' เพลงพร้อมพรีวิว');
        await load(true);
      }catch(error){setStatus('สแกนไม่สำเร็จ: '+error.message);}
      finally{$(kind+'-preview-scan').disabled=false;}
    }
    async function choose() {
      stop();
      const id=Number(selected.value);
      const row=state.rows.find(x=>x.id===id);
      $(kind+'-preview-play').disabled=!selected.value||!row;
      showLyrics([]);
      if(!row)return;
      setStatus(row.title+' · '+row.kind+' · '+row.status);
      const ticket=++state.serial;
      try{
        const details=await post('/api/import-preview/lyrics',{kind,id});
        if(ticket!==state.serial)return;
        showLyrics(details.lines||[]);
        setStatus(row.title+' · '+row.kind+' · '+details.status);
      }catch(error){if(ticket===state.serial)setStatus('อ่านเนื้อร้องไม่ได้: '+error.message);}
    }
    async function play() {
      const row=state.rows.find(x=>String(x.id)===selected.value);
      if(!row)return;
      stop();
      const ticket=++state.serial;
      setStatus('กำลังเปิดเสียงทดลองเล่น '+row.title+'…');
      try{
        const result=await post('/api/import-preview/play',{kind,id:row.id});
        if(ticket!==state.serial)return;
        state.session=result.session;
        audio.src=engineAddress('/api/live-stream?ticket='+encodeURIComponent(result.ticket));
        $(kind+'-preview-stop').disabled=false;
        await audio.play();
        setStatus('กำลังทดลองเล่น '+row.title+' · '+result.format+' (ไม่อัปโหลดไฟล์)');
      }catch(error){
        if(ticket===state.serial)setStatus('ทดลองเล่นไม่สำเร็จ: '+error.message);
      }
    }
    $(kind+'-preview-scan').addEventListener('click',()=>{void scan();});
    $(kind+'-preview-search').addEventListener('change',()=>{void load(true);});
    $(kind+'-preview-prev').addEventListener('click',()=>{state.offset=Math.max(0,state.offset-50);void load();});
    $(kind+'-preview-next').addEventListener('click',()=>{state.offset+=50;void load();});
    selected.addEventListener('change',()=>{void choose();});
    $(kind+'-preview-play').addEventListener('click',()=>{void play();});
    $(kind+'-preview-stop').addEventListener('click',stop);
    audio.addEventListener('timeupdate',()=>drawLyrics(audio.currentTime));
    audio.addEventListener('ended',()=>{ $(kind+'-preview-stop').disabled=true; });
    audio.addEventListener('error',()=>{if(audio.currentSrc)setStatus('ตัวเล่นเสียงไม่รองรับไฟล์หรือสตรีมหยุดก่อนจบ');});
    state.load=load;
  }
  function stopImportPreviews(except='') {
    for(const [kind, state] of importPreviews)if(kind!==except)state.stop();
  }

  async function inspectUploadFolder() {
    const finishInspection=beginInspection('upload-folder-report','กำลังตรวจความครบถ้วนของไฟล์ในโฟลเดอร์ย่อยทั้งหมด');
    if(!finishInspection)return null;
    try {
      await saveInputs(['upload-folder']);
      const result=await api('/api/upload-folder/inspect');
      const breakdown=Object.entries(result.kinds||{})
        .filter(([,count])=>count>0)
        .map(([kind,count])=>kind+' '+fmtNum(count)).join(' · ');
      const examples=(result.examples||[]).slice(0,5)
        .map(x=>x.name+': '+x.reason);
      $('upload-folder-report').textContent=
        (result.source === 'XStageSong catalog'
          ? 'โหมดคลัง XStageSong · ตรวจไฟล์ตาม Catalog ที่เผยแพร่แล้ว · '
          : 'ตรวจโฟลเดอร์หลักและโฟลเดอร์ย่อยทั้งหมด · ')+
        'ตรวจ '+fmtNum(result.fileCount)+' ไฟล์ ใน '+fmtNum(result.folderCount||0)+' โฟลเดอร์ · ชุดสมบูรณ์ '+
        fmtNum(result.ready)+' · ไม่ครบ '+fmtNum(result.incomplete)+
        ' · ไม่รองรับ '+fmtNum(result.unsupported)+
        (breakdown?'\\n'+breakdown:'')+
        (examples.length?'\\nข้าม: '+examples.join(' | '):'');
      return result;
    } catch (error) {
      $('upload-folder-report').textContent='ตรวจโฟลเดอร์ไม่สำเร็จ: '+error.message;
      message(error.message);
      return null;
    } finally {
      finishInspection();
    }
  }
  async function inspectPCExport(){
    const finishInspection=beginInspection('pc-export-report','กำลังตรวจคลังเพลงและฐานข้อมูล Karaoke PC');
    if(!finishInspection)return null;
    try {
      await saveInputs(['pc-export-folder']);
      const result=await api('/api/pc-export/inspect');
      $('pc-export-report').textContent='คลังเพลง '+fmtNum(result.songs)+
        ' เพลง · พบ '+fmtNum(result.files)+' ไฟล์ · ต้องคัดลอกใหม่ '+
        fmtNum(result.newFiles)+' ไฟล์ ('+fmtSize(result.bytesToCopy)+
        ') · เดิมในปลายทาง '+fmtNum(result.existingSongs)+' เพลง'+
        '\\nตำแหน่งปลายทาง: '+result.destination+
        '\\nSQLite: '+(result.databaseAction==='update'?'อัปเดตฐานเดิม':'สร้างฐานใหม่')+
        ' · '+result.database+
        '\\nDB พกพาสำหรับเผยแพร่ Web/APK: '+result.portableDatabase+
        '\\nWeb/APK ต้องอัปโหลดด้วยบัญชี Google Drive เพื่อสร้าง File ID จริง'+
        (result.databaseInstalled?' · เชื่อมฐาน Karaoke PC ที่ติดตั้งแล้ว':
        ' · โหมดส่งออก: ยังไม่พบโปรแกรม Karaoke PC ณ ตำแหน่งนี้');
      return result;
    } catch(error) {
      $('pc-export-report').textContent='ตรวจคลัง Karaoke PC ไม่สำเร็จ: '+error.message;
      message(error.message);
      return null;
    } finally {
      finishInspection();
    }
  }
  async function startPCExport(){
    if(busy)return;
    const report=await inspectPCExport();
    if(!report || !report.songs)return message('ยังไม่มีเพลงที่สร้างสำเร็จใน XStageSong');
    const approved=await confirmStudio(
      'คัดลอกเพลง '+fmtNum(report.songs)+' รายการ จาก Song Studio ไปยัง\\n'+
      report.destination+'\\nจำนวนไฟล์ '+fmtNum(report.files)+
      ' · ต้องคัดลอกใหม่ '+fmtNum(report.newFiles)+
      ' ('+fmtSize(report.bytesToCopy)+')\\n'+
      'ส่งออก AUDIO, LYRICS, SQLite songs.sqlite3 สำหรับ PC และ DB/songs-portable.json\\n'+
      'การใช้ผ่าน Web/APK ต้องนำเข้า Google Drive หลังส่งออก ไม่ใช้ SQLite โดยตรง\\n'+
      'ตำแหน่ง DB: '+report.database+'\\n'+
      (report.databaseInstalled?'เชื่อมฐานของ Karaoke PC ที่ติดตั้งแล้ว\\n':
       'ยังไม่พบ Karaoke PC ที่ติดตั้ง · สร้างฐาน SQLite สำหรับส่งออกเท่านั้น\\n')+
      'สำรองฐานเดิมก่อนอัปเดต · รักษาเพลงเดิม รายการโปรด และข้อมูลที่ผู้ใช้แก้ไข',
      'ยืนยันนำเข้า X-Stage Karaoke PC',
      {acceptLabel:'เริ่มคัดลอก',cancelLabel:'ยกเลิก'});
    if(!approved)return;
    $('pc-export-status').textContent='กำลังเริ่มคัดลอกและตรวจ SHA-256 · ดูสถานะที่แผงงาน';
    await run('pc-export');
  }
  async function startFolderUpload() {
    if (!canLaunch('upload-folder') || !googleConnected)
      return message('กรุณาเชื่อม Google Drive หรือรอทรัพยากรเครื่องพร้อมก่อนอัปโหลด');
    const report=await inspectUploadFolder();
    if (!report || !report.ready)
      return message('ไม่มีชุดเพลงที่ตรวจแล้วว่าสมบูรณ์ · ยังไม่อัปโหลด');
    const createNew=$('upload-allow-new').checked;
    // Retain one short confirmation because a missing/inaccessible Drive library
    // may otherwise create a duplicate when automatic library creation is enabled.
    const details='พร้อมอัปโหลด '+fmtNum(report.ready)+' เพลง'+
      (report.incomplete||report.unsupported
        ? '\\nข้ามไฟล์ไม่พร้อม '+fmtNum(report.incomplete+report.unsupported)+' รายการ':'')+
      (createNew?'\\nหากไม่พบคลังเดิม จะสร้าง XStageSong ใหม่ใน Google Drive':'');
    if (!await confirmStudio(details,'ยืนยันอัปโหลด',
      {acceptLabel:'อัปโหลด',cancelLabel:'ยกเลิก'})) return;
    $('upload-folder-report').textContent='กำลังอัปโหลด '+fmtNum(report.ready)+' เพลง…';
    await run('upload-folder',{create_new_library:createNew});
  }

  async function offerUploadAfterBuild(job) {
    if (job.kind !== 'build' || job.state !== 'success') return;
    if (Number(job.result?.created||0) <= 0) return;
    message('สร้างเพลงเสร็จแล้ว · หากต้องการส่งไฟล์ไป XStageSong ให้เปิดเมนูอัปโหลด เลือกโฟลเดอร์ แล้วกดอัปโหลด',false);
  }
  async function startDownload(kind) {
    if (!googleConnected) return message('ต้อง Google Login ก่อนดาวน์โหลด');
    try {
      await saveInputs(['download-destination']);
      const labels = {songs:'โฟลเดอร์เพลง',db:'ฐานข้อมูล DB',zip:'ZIP สำรองทั้งชุด'};
      if (!await confirmStudio(`ดาวน์โหลด ${labels[kind]} ไปที่\n${prefs.download}\n\nไฟล์เดิมที่มีเนื้อหาต่างกันจะไม่ถูกเขียนทับ ยืนยันหรือไม่?`, 'ยืนยันดาวน์โหลด')) return;
      await run('download',{kind});
    } catch (error) { message(error.message); }
  }
  function renderJob(job) {
    const state = job.state || 'idle';
    const isRunning = state === 'running';
    // Do not silently leave the user on the original app window: the OAuth
    // browser opens in front, while this panel remains available as fallback.
    const oauthWaiting = job.kind === 'login' && isRunning;
    $('google-login-help').hidden = !oauthWaiting;
    $('google-login-focus').disabled = !oauthWaiting;
    const led = $('job-led');led.className = 'job-led ' + (/^(idle|running|error|success|cancelled)$/.test(state) ? state : 'idle');
    const stage = job.stage || 'พร้อมใช้งาน';
    const jobLabel = job.kind === 'scan' && state === 'success'
      ? 'สแกนโฟลเดอร์เสร็จแล้ว (ยังไม่ได้สร้างเพลง)'
      : stage;
    $('job-title').textContent = (isRunning ? '● ' : '') + jobLabel + (state === 'error' ? ' · ผิดพลาด' : '');
    $('job-detail').textContent = job.detail || 'ไม่มีงานที่กำลังประมวลผล';
    if (job.kind === 'build' && job.id) {
      const report = 'งาน ' + job.id + ' · ' +
        fmtNum(job.completed || 0) + '/' + fmtNum(job.total || 0) + ' เพลง · M4A ' +
        fmtNum(job.m4aCount || 0) + ' · Lyrics ' + fmtNum(job.lyricsCount || 0) +
        ' · ข้ามซ้ำ ' + fmtNum(job.skipped || 0) + ' · ERR ' + fmtNum(job.errors || 0);
      if (state === 'running') {
        buildFeedback('running', job.stage || 'กำลังสร้างเพลง…', report + ' · ' + (job.detail || 'PC Engine กำลังทำงาน'));
      } else if (state === 'success') {
        const errors = Number(job.errors || job.result?.errors || 0);
        const created = Number(job.created || job.result?.created || 0);
        const skipped = Number(job.skipped || job.result?.skipped || 0);
        const invalidEmpty = created === 0 && skipped === 0;
        buildFeedback(errors || invalidEmpty ? 'error' : 'success',
          errors ? 'สร้างเพลงบางรายการไม่สำเร็จ · ตรวจสอบ Log' :
          created ? 'สร้างเพลงเสร็จแล้ว' :
          skipped ? 'ไม่มีเพลงใหม่ · ตรวจพบเพลงเดิมที่ยืนยันแล้ว' : 'ไม่พบผลการสร้างเพลงที่ตรวจสอบได้',
          (job.result?.message || report) +
          (invalidEmpty ? '\nEngine แจ้งเสร็จสิ้น แต่ไม่มีไฟล์ใหม่หรือรายการข้ามที่ตรวจยืนยันได้ · กรุณาตรวจสอบ Log และไฟล์ต้นฉบับ' : '') +
          (errors ? '\n' + (job.result?.issues || []).slice(0,3).join('\n') : ''));
      } else if (state === 'error' || state === 'cancelled') {
        const reasons = (job.logs || []).filter(item => /ERR|ผิดพลาด|Error|ไม่พบ|ซ้ำ|พื้นที่/.test(item));
        buildFeedback('error', state === 'cancelled' ? 'หยุดงานแล้ว' : 'สร้างเพลงไม่สำเร็จ',
          [job.detail, ...reasons.slice(-3)].filter(Boolean).join('\n') || report);
        $('job-log').hidden = false;
        $('toggle-log').setAttribute('aria-expanded','true');
      }
    }
    $('job-timing').textContent = fmtTime(job.elapsed || 0);
    if(job.kind==='xsk-stream'){
      const discovered=Number(job.discovered||0),scanned=Number(job.scannedFiles||0);
      const processed=Number(job.completed||0);
      const details='ตรวจไฟล์ '+fmtNum(scanned)+' · พบ MIDI '+fmtNum(discovered)+
        ' · ประมวลผล '+fmtNum(processed)+' · สร้าง '+fmtNum(job.created||0)+
        ' · ข้ามซ้ำ '+fmtNum(job.skipped||0)+' · ไม่พร้อม '+fmtNum(job.notReady||0)+
        ' · ERR '+fmtNum(job.errors||0);
      $('xsk-stream-status').textContent=details+
        (job.scanDone?'\\nสแกนจบแล้ว · กำลังทำรายการที่อยู่ในคิวให้ครบ':
           '\\nกำลังสแกนต่อพร้อมสร้างเพลง · รอคิว '+fmtNum(job.queuedBatches||0)+' ชุด')+
        (state==='error'?'\\n'+(job.detail||'เกิดข้อผิดพลาด · ตรวจ Log'):'')+
        (state==='success'?'\\n'+(job.result?.message||'เสร็จสิ้น'):'');
      $('job-detail').textContent=details;
    }
    $('job-skip-count').textContent = job.kind === 'scan'
      ? (state === 'success'
          ? 'สแกนพบ ' + fmtNum(Number(job.result?.songs ?? job.result?.count ?? job.completed ?? 0)) + ' เพลง · ยังไม่ได้สร้าง M4A/Lyrics'
          : 'ตรวจไฟล์ ' + fmtNum(job.completed || 0) + ' · ยังไม่ได้สร้างเพลง')
      : 'ข้ามซ้ำ ' + fmtNum(Number(job.skipped || 0)) +
        ' · ERR ' + fmtNum(Number(job.errors || 0)) +
        ' · M4A ' + fmtNum(Number(job.m4aCount || 0)) +
        ' · Lyrics ' + fmtNum(Number(job.lyricsCount || 0));
    const fraction = (job.kind==='xsk-stream' && isRunning && !job.scanDone) ? null :
      Number(job.total)>0 ? Number(job.completed) / Number(job.total) :
      Number(job.bytesTotal)>0 ? Number(job.bytesDone)/Number(job.bytesTotal) : null;
    const fill = $('progress-fill');
    fill.classList.toggle('indeterminate', isRunning && fraction === null);
    fill.style.width = fraction !== null ? Math.max(0,Math.min(100,100*fraction)).toFixed(1)+'%' : (isRunning?'33%':'0%');
    $('job-fraction').textContent =
      (job.kind==='xsk-stream' && isRunning && !job.scanDone)
        ? 'พบ MIDI '+fmtNum(job.discovered||0)+' เพลง · ทำแล้ว '+fmtNum(job.completed||0)+' · ยังไม่ทราบจำนวนรวม'
        : Number(job.total)>0 ? `${fmtNum(job.completed)} / ${fmtNum(job.total)} รายการ · ${Math.round(fraction*100)}%` :
      Number(job.bytesTotal)>0?`${fmtSize(job.bytesDone)} / ${fmtSize(job.bytesTotal)} · ${Math.round(fraction*100)}%`:
      isRunning && job.kind === 'scan'
        ? 'ตรวจรายการแล้ว ' + fmtNum(job.completed || 0) + ' ไฟล์ · กำลังตรวจการเปลี่ยนแปลง'
        : isRunning ? 'กำลังดำเนินการ · ยังไม่ทราบเปอร์เซ็นต์' : state === 'success' ? 'เสร็จสิ้น' : 'รอเริ่มงาน';
    $('job-eta').textContent = isRunning
      ? `เวลาคงเหลือประมาณ ${job.eta !== null ? fmtTime(job.eta) : '—'} · ${job.idleFor > 7 ? `ยังทำงานอยู่ ${job.idleFor} วินาที` : 'สถานะสด'}`
      : state === 'success' ? (job.kind === 'scan' ? 'สแกนสำเร็จ · ยังไม่ได้สร้างเพลง' : 'งานสำเร็จ') : state === 'error' ? 'ตรวจ Log ข้อผิดพลาด' : 'พร้อม';
    const list = $('job-log'); list.replaceChildren();
    for (const item of job.logs || []) {const li=document.createElement('li');li.textContent=item;list.append(li);}
  }
  async function poll() {
    try {
      const response = await api('/api/status');
      const job = response.job || {};
      const beforeBusy = busy;
      busy = job.state === 'running';
      activeJobs=response.jobs||[];
      parallelCapacity=response.resources||parallelCapacity;
      renderParallelJobs();
      if (!busy) cancellationPending = false;
      setGoogle(response.google);
      renderJob(job);updateButtons();
      if (job.kind === 'created-xsk') {
        const report='XSK '+fmtNum(job.completed||0)+'/'+fmtNum(job.total||0)+
          ' · สร้าง '+fmtNum(job.created||0)+' · ข้าม MIDI ซ้ำ '+fmtNum(job.skipped||0)+
          ' · ผิดพลาด '+fmtNum(job.errors||0);
        $('created-xsk-status').textContent=report+'\\n'+(job.detail||job.stage||'')+
          (job.state==='success'?'\\n'+(job.result?.message||'เสร็จสิ้น'):'');
        if(!busy && job.state==='success' && lastJobState==='running')void refreshCreatedJson();
      }
      if (job.kind === 'pc-export' && job.state === 'running')
        $('pc-export-status').textContent = job.stage || 'กำลังคัดลอกไฟล์เข้า XStageSong';
      if (job.kind === 'ai-export' && job.state === 'running')
        $('ai-export-status').textContent = job.stage || job.detail || 'กำลังส่งออกไฟล์ที่เลือก';
      if (['ai-lyrics','ai-align','ai-separate-vocals'].includes(job.kind) && job.state === 'running' && aiSongId !== null)
        $('ai-lyrics-status').textContent = job.stage || job.detail || 'AI กำลังจัดเวลา';
      if (job.id && (job.id !== lastJobId || (lastJobState !== job.state && !busy))) {
        lastJobId = job.id;
        if (!busy) {
          if (job.state === 'success') {
            if (job.kind === 'preview' && job.result?.ticket) {
              const t = encodeURIComponent(job.result.ticket);
              previewAudio.pause(); previewAudio.src = engineAddress('/api/preview?ticket=' + t);
              $('preview-label').textContent = 'ตัวอย่างเสียงพร้อม · กด ▶ เพื่อฟัง';
              previewAudio.play().catch(()=>{});
            } else if (job.kind === 'pc-export') {
              $('pc-export-status').textContent='✓ '+(job.result?.message||'คัดลอกคลังเพลงสำเร็จ');
              message(job.result?.message||'นำเข้า Karaoke PC สำเร็จ',false);
            } else if (job.kind === 'ai-export') {
              $('ai-export-status').textContent=job.result?.message ||
                '✓ ส่งออกไฟล์ที่เลือกเรียบร้อยแล้ว';
              message(job.result?.message || 'ส่งออกไฟล์ที่เลือกสำเร็จ',false);
            } else if (job.kind === 'ai-separate-vocals') {
              const row=aiSongs.find(item=>item.id===job.result?.songId);
              if(row&&aiSongId===row.id)await aiChooseSong(row,{preferVocals:true});
              $('ai-lyrics-vocals-status').textContent=job.result?.message||
                'แยกเสียงร้องและดนตรีเป็น M4A สองไฟล์สำเร็จ';
              message(job.result?.message||'แยกเสียงร้องสำเร็จ',false);
            } else if (job.kind === 'ai-lyrics') {
              if (job.result?.songId === previewSongId)
                await loadPreviewLyrics(previewSongId);
              if (job.result?.songId === aiSongId) {
                const aiCurrent = aiSongs.find(x=>x.id===aiSongId);
                if (aiCurrent) await aiChooseSong(aiCurrent);
              }
              message(job.result?.message || 'AI ถอดคำร้องเป็นฉบับร่างแล้ว · กรุณาตรวจแก้', false);
            } else if (job.kind === 'ai-align') {
              const result=job.result||{};
              const pending=pendingAiAlignment;
              if (pending && pending.id===aiSongId && result.songId===aiSongId &&
                  $('ai-lyrics-paste').value===pending.lyrics && result.rawLrc) {
                // Replacing the editor is safe only if the user's pasted
                // source has not been modified while Whisper was running.
                $('ai-lyrics-editor').value=result.rawLrc;
                aiDraftReady=true;
                aiValidateEditor();
                $('ai-lyrics-align-review').textContent=
                  result.message+'\n'+(result.issues||[]).join('\n')+
                  '\nเวลาเป็นการประมาณจากเสียงร้องจริง · ต้องฟังตรวจทุกบรรทัดก่อนกดบันทึก';
                $('ai-lyrics-status').textContent='✓ ได้ร่างเวลา LRC แล้ว · โปรดฟังตรวจและแก้เวลา';
                message('จัดเวลาเบื้องต้นแล้ว · '+fmtNum(result.uncertain)+' บรรทัดควรตรวจเป็นพิเศษ',false);
              } else {
                message('จัดเวลาสำเร็จแต่เพลงหรือเนื้อเพลงที่เลือกเปลี่ยนไป · โปรแกรมไม่เขียนทับข้อความของคุณ');
              }
              pendingAiAlignment=null;
            } else if (job.kind === 'lyric-groups-scan') {
              phraseReady=true;
              phraseOffset=0;phraseClearSelection();
              await refreshPhraseGroups();
              await refreshPhraseBackup();
              message(job.result?.message||'จัดกลุ่มข้อความเสร็จแล้ว',false);
            } else if (job.kind === 'lyric-groups-replace') {
              // Keep the current position, lyric search and page: the backend
              // already patched the live groups without a full rescan.
              phraseReady=true;
              phraseClearSelection();
              await refreshPhraseGroups();
              await refreshPhraseBackup();
              const summary=job.result||{};
              $('lyric-group-preview-status').textContent=
                'Smart Batch เสร็จ · แก้ '+fmtNum(summary.changedSongs)+' เพลง / '+
                fmtNum(summary.changedLines)+' บรรทัด · เวลาโดยประมาณ '+
                fmtNum(summary.estimatedLines)+' บรรทัด · ข้ามผิดปกติ '+
                fmtNum(summary.skippedInvalid)+' เพลง'+
                (summary.skippedReport?' · รายงานบน PC: '+summary.skippedReport:'')+
                ' · ย้อนคืนได้ด้วย Undo · รายการที่ยังไม่แก้คงอยู่';
              message(job.result?.message||'แทนที่ข้อความสำเร็จ',false);
            } else if (job.kind === 'lyric-groups-undo') {
              phraseReady=false;phraseRows=[];phraseOffset=0;
              ++phraseSeq;phraseClearSelection();
              $('lyric-group-results').textContent=
                'ย้อนคืนข้อมูลแล้ว · กดวิเคราะห์อีกครั้งเพื่อจัดกลุ่มตามข้อมูลเดิม';
              $('lyric-group-page-count').textContent='ต้องวิเคราะห์ใหม่';
              $('lyric-group-page-count').dataset.total='0';
              await refreshPhraseBackup();
              message(job.result?.message||'ย้อนคืนสำเร็จ',false);
            } else if (job.kind === 'check-update') {
              const info=job.result||{};
              $('update-result').textContent=info.message||'ไม่สามารถยืนยันเวอร์ชันได้';
              $('update-download').hidden=!info.update;
              $('update-version').textContent=info.update
                ? 'มีรุ่นใหม่ v'+info.version+' Build '+info.build
                : 'รุ่นล่าสุดที่เผยแพร่';
              message(info.message||'ตรวจเวอร์ชันเสร็จแล้ว',false);
            } else if (job.kind === 'download-update') {
              const info=job.result||{};
              $('update-result').textContent=info.message||'ดาวน์โหลด ZIP แล้ว';
              message(info.message||'ดาวน์โหลดและตรวจไฟล์อัปเดตแล้ว',false);
            } else if (job.kind === 'install-update') {
              const info=job.result||{};
              $('update-result').textContent=info.launched
                ? 'ติดตั้งเรียบร้อย · กำลังเปิด X-Stage Song Studio PC รุ่นใหม่'
                : (info.message||'ไม่มีรุ่นใหม่ให้ติดตั้ง');
              message($('update-result').textContent,false);
            } else message(job.result?.message || 'ดำเนินการสำเร็จ · '+job.kind, false);
          } else if (job.state === 'error') {
            if(job.kind==='pc-export'){
              $('pc-export-status').textContent='คัดลอกไม่สำเร็จ: '+(job.detail||'ตรวจบันทึกข้อผิดพลาด');
            }
            if(job.kind==='ai-export'){
              $('ai-export-status').textContent='ส่งออกไม่สำเร็จ: '+
                (job.detail||'ตรวจรายละเอียดในแผงงาน');
            }
            if(job.kind==='ai-separate-vocals'){
              $('ai-lyrics-vocals-status').textContent=
                'แยกเสียงร้องไม่สำเร็จ · ไฟล์เสียงต้นฉบับยังอยู่ · ตรวจ Log';
            }
            if(job.kind?.startsWith('lyric-groups-')) {
              $('lyric-group-preview-status').textContent=
                'ไม่สำเร็จ · ตรวจ Log · หากเริ่มแก้ไขแล้วสามารถตรวจชุดสำรองเพื่อย้อนคืนได้';
              await refreshPhraseBackup();
            }
            if(job.kind==='ai-align'){
              $('ai-lyrics-align-review').textContent=
                'จัดเวลาไม่สำเร็จ · คำร้องที่วางยังอยู่ · '+(job.detail||'ตรวจ Log เพื่อดูสาเหตุ');
              pendingAiAlignment=null;
            }
            message(job.detail || 'งานไม่สำเร็จ');
          } else if (job.state==='cancelled') {
            if (job.kind==='ai-align') {
              pendingAiAlignment=null;
              $('ai-lyrics-align-review').textContent='ยกเลิกจัดเวลาแล้ว · คำร้องที่วางยังอยู่';
            }
            message('ยกเลิกงานเรียบร้อย · พร้อมทำรายการอื่น',false);
          }
          if (['scan','build','upload','download'].includes(job.kind)) await refreshSongs();
          if (job.kind === 'build' && ['success','error'].includes(job.state) &&
              !promptedBuildUploadJobs.has(job.id)) {
            // Mark before awaiting the dialog: polling runs every 900 ms.
            promptedBuildUploadJobs.add(job.id);
            void offerUploadAfterBuild(job).catch(error =>
              message('ไม่สามารถเปิดขั้นตอนอัปโหลดหลังสร้างเพลง: ' + error.message));
          }
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
  async function refreshHistory() {
    const panel = $('history-list');
    if (!panel) return;
    try {
      const result = await api('/api/history');
      panel.replaceChildren();
      if (!result.events?.length) {
        panel.textContent = 'ยังไม่มีประวัติ · ระบบจะบันทึกเมื่อแก้ข้อมูลเพลงหรือเปลี่ยนการตั้งค่า';
        return;
      }
      for (const event of result.events) {
        const row = document.createElement('div');
        row.className = 'history-row';
        const detail = document.createElement('div');
        const title = document.createElement('strong');
        title.textContent = event.summary + ' · ' + event.target;
        const date = document.createElement('small');
        date.textContent = event.createdAt ?
          new Date(event.createdAt).toLocaleString('th-TH') : '';
        detail.append(title, date);
        const action = document.createElement('button');
        action.className = 'button ghost';
        action.type = 'button';
        action.textContent = '↶ คืนค่าก่อนแก้';
        action.dataset.restoreHistory = event.id;
        row.append(detail, action);
        panel.append(row);
      }
    } catch (error) {
      panel.textContent = 'อ่านประวัติไม่ได้: ' + error.message;
    }
  }
  async function restoreHistory(id) {
    if (busy) return message('มีงานกำลังทำงานอยู่ ไม่สามารถคืนค่าได้');
    const yes = await confirmStudio(
      'คืนค่าข้อมูลก่อนการแก้ไขที่เลือกใช่หรือไม่? ระบบจะบันทึกการคืนค่านี้ลงประวัติอีกครั้ง และไม่แตะไฟล์เพลงต้นฉบับ',
      'ยืนยันคืนค่าประวัติ', {acceptLabel:'คืนค่าก่อนแก้',cancelLabel:'ยกเลิก'});
    if (!yes) return;
    try {
      const result = await post('/api/history/restore',{id});
      if (result.preferences) {
        prefs = result.preferences;
        setFields();
      }
      selected.clear();
      await refreshSongs();
      await refreshHistory();
      message(result.message || 'คืนค่าจากประวัติสำเร็จ', false);
    } catch (error) { message('คืนค่าประวัติไม่สำเร็จ: ' + error.message); }
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
      if (editingId === previewSongId) void loadPreviewLyrics(previewSongId);
      message('บันทึกข้อมูลเพลงและเนื้อร้องแล้ว',false);
    }catch(error){message(error.message);}
  }
  // Created-file JSON management is deliberately limited to catalog-backed lyrics.
  // Never interpolate untrusted filenames or lyrics into HTML.
  let createdJsonItems = [], createdJsonSelected = new Set(), createdJsonOffset = 0;
  let createdJsonTotal = 0, createdJsonLastBackup = null, createdJsonBusy = false;
  const createdJsonLimit = 50;
  function createdJsonBusyState(value) {
    createdJsonBusy = value;
    for (const id of ['created-json-refresh','created-json-preview','created-json-apply',
                      'created-json-select','created-json-select-all','created-json-clear','created-json-clear-page','created-json-prev','created-json-next']) {
      $(id).disabled = value;
    }
    $('created-json-prev').disabled = value || createdJsonOffset <= 0;
    $('created-json-next').disabled = value || createdJsonOffset + createdJsonLimit >= createdJsonTotal;
    $('created-json-undo').disabled = value || !createdJsonLastBackup;
    $('created-xsk-build').disabled = value || busy || !proEnabled || createdJsonSelected.size===0;
  }
  function createdJsonRender() {
    const tbody = $('created-json-rows');
    tbody.replaceChildren();
    if (!createdJsonItems.length) {
      const tr=document.createElement('tr'),td=document.createElement('td');
      td.colSpan=4;td.className='empty-row';td.textContent='ไม่พบไฟล์ Lyrics JSON ในคลังที่สร้างแล้ว';
      tr.append(td);tbody.append(tr);
    }
    for (const item of createdJsonItems) {
      const tr=document.createElement('tr');
      const selectCell=document.createElement('td');
      const cb=document.createElement('input');
      cb.type='checkbox';cb.checked=createdJsonSelected.has(item.path);
      cb.disabled=createdJsonBusy;cb.setAttribute('aria-label','เลือก '+item.path);
      cb.addEventListener('change',()=>{
        if(cb.checked)createdJsonSelected.add(item.path);
        else createdJsonSelected.delete(item.path);
        $('created-json-summary').textContent='เลือกแล้ว '+createdJsonSelected.size+' ไฟล์ · จากทั้งหมด '+createdJsonTotal+' ไฟล์';
        $('created-xsk-build').disabled=createdJsonBusy||busy||!proEnabled||createdJsonSelected.size===0;
      });
      selectCell.append(cb);
      const title=document.createElement('td');
      const strong=document.createElement('strong');strong.textContent=(item.code||'—')+' · '+(item.title||'ไม่มีชื่อ');
      const artist=document.createElement('div');artist.className='hint';artist.textContent=item.artist||'';
      title.append(strong,artist);
      const path=document.createElement('td');path.textContent=item.path;
      const status=document.createElement('td');status.textContent=item.status;
      tr.append(selectCell,title,path,status);tbody.append(tr);
    }
    const first=createdJsonTotal?createdJsonOffset+1:0;
    $('created-json-page').textContent=first+'–'+(createdJsonOffset+createdJsonItems.length)+' / '+createdJsonTotal;
    $('created-json-prev').disabled=createdJsonBusy||createdJsonOffset<=0;
    $('created-json-next').disabled=createdJsonBusy||createdJsonOffset+createdJsonLimit>=createdJsonTotal;
    $('created-json-summary').textContent='เลือกแล้ว '+createdJsonSelected.size+' ไฟล์ · พบในผลค้นหา '+createdJsonTotal+' ไฟล์ · คงรายการที่เลือกเมื่อเปลี่ยนหน้า';
    $('created-xsk-build').disabled=createdJsonBusy||busy||!proEnabled||createdJsonSelected.size===0;
  }
  async function refreshCreatedJson() {
    if (createdJsonBusy) return;
    createdJsonBusyState(true);
    try {
      const query=new URLSearchParams({search:$('created-json-search').value.trim(),
          offset:String(createdJsonOffset),limit:String(createdJsonLimit)});
      const result=await api('/api/created-json?'+query.toString());
      createdJsonTotal=result.total||0;createdJsonItems=result.rows||[];
      createdJsonRender();
    }catch(e){$('created-json-result').textContent='โหลดไฟล์ไม่สำเร็จ: '+e.message;}
    finally{createdJsonBusyState(false);}
  }
  async function createdJsonAction(dryRun) {
    if (createdJsonBusy||busy) return message('มีงานกำลังทำงานอยู่ กรุณารอให้เสร็จก่อน');
    const paths=[...createdJsonSelected];
    if (!paths.length) return message('กรุณาเลือกไฟล์ JSON ก่อน');
    if(paths.length>100)return message('เลือกได้ไม่เกิน 100 ไฟล์ต่อครั้ง');
    if(!dryRun){
      const yes=await confirmStudio('จัดรูปแบบ '+paths.length+' ไฟล์? ระบบสำรอง JSON ก่อนแก้ และไม่เปลี่ยนเนื้อร้องหรือเวลา','จัดรูปแบบ JSON');
      if(!yes)return;
    }
    createdJsonBusyState(true);
    try{
      const result=await post('/api/created-json/format',{paths,dryRun});
      const lines=result.results.map(x=>x.path+' : '+x.status+(x.reason?' · '+x.reason:''));
      $('created-json-result').textContent=(dryRun?'ผลตรวจสอบ (ยังไม่แก้ไฟล์)':'ผลจัดรูปแบบ')+
        ' · รายการที่จัดได้ '+result.formatted+' · ข้าม '+result.skipped+'\n'+lines.join('\n');
      if(!dryRun){
        const done=result.results.filter(x=>x.status==='formatted'&&x.backup&&x.sha256);
        createdJsonLastBackup=done.length===1?{path:done[0].path,backup:done[0].backup,sha256:done[0].sha256}:null;
        if(done.length>1)$('created-json-result').textContent+='\nสำรองแต่ละไฟล์ไว้ข้างไฟล์ต้นทาง · การย้อนคืนอัตโนมัติจากหน้านี้รองรับครั้งละหนึ่งไฟล์';
      }
    }catch(e){$('created-json-result').textContent='ไม่สำเร็จ: '+e.message;}
    finally{createdJsonBusyState(false);}
    if(!dryRun)void refreshCreatedJson();
  }
  async function undoCreatedJson() {
    if(!createdJsonLastBackup||createdJsonBusy||busy)return;
    if(!await confirmStudio('ย้อนคืน JSON จากสำรอง '+createdJsonLastBackup.backup+' ใช่หรือไม่?','ย้อนคืน JSON'))return;
    createdJsonBusyState(true);
    try {
      const result=await post('/api/created-json/restore',createdJsonLastBackup);
      createdJsonLastBackup=null;
      $('created-json-result').textContent=result.message||'ย้อนคืนสำเร็จ';
    }catch(e){$('created-json-result').textContent='ย้อนคืนไม่สำเร็จ: '+e.message;}
    finally{createdJsonBusyState(false);}
    void refreshCreatedJson();
  }
  async function buildCreatedXsk() {
    if (busy || createdJsonBusy) return message('มีงานอื่นกำลังทำงานอยู่');
    if (!proEnabled) {
      tab('settings');
      return message('กรุณาเปิดใช้ X-Stage Song Studio PC Pro ด้วย License Key ในเมนูตั้งค่า');
    }
    const paths=[...createdJsonSelected];
    if (!paths.length) return message('กรุณาเลือกเพลงอย่างน้อยหนึ่งรายการ');
    const folder=$('xsk-destination').value.trim();
    if (!folder)return message('กรุณาเลือกโฟลเดอร์ปลายทาง XSK');
    if (!await confirmStudio(
      'สร้าง XSK จาก '+paths.length+' รายการ?\\nตรวจ MIDI ซ้ำด้วย SHA-256 และไม่เขียนทับ XSK หรือ Lyrics JSON เดิม',
      'ยืนยันสร้าง .XSK Pro'))return;
    try {
      await config({xsk_folder:folder});
      $('created-xsk-status').textContent='กำลังส่งงาน XSK '+paths.length+' เพลงไปยัง PC Engine…';
      const started=await run('created-xsk',{paths});
      if(!started)$('created-xsk-status').textContent='เริ่มงาน XSK ไม่สำเร็จ · ตรวจข้อความแจ้งเตือน';
    }catch(error){$('created-xsk-status').textContent='เกิดข้อผิดพลาด: '+error.message;message(error.message);}
  }
  $('created-xsk-build').addEventListener('click',()=>{void buildCreatedXsk();});
  $('xsk-destination').addEventListener('change',()=>{
    const folder=$('xsk-destination').value.trim();
    if(folder)void config({xsk_folder:folder}).catch(error=>message(error.message));
  });
  $('created-json-refresh').addEventListener('click',()=>{void refreshCreatedJson();});
  $('created-json-search').addEventListener('change',()=>{createdJsonOffset=0;void refreshCreatedJson();});
  $('created-json-prev').addEventListener('click',()=>{createdJsonOffset=Math.max(0,createdJsonOffset-createdJsonLimit);void refreshCreatedJson();});
  $('created-json-next').addEventListener('click',()=>{createdJsonOffset+=createdJsonLimit;void refreshCreatedJson();});
  $('created-json-select').addEventListener('click',()=>{
    for(const item of createdJsonItems)createdJsonSelected.add(item.path);
    createdJsonRender();
  });
  $('created-json-clear-page').addEventListener('click',()=>{
    for(const item of createdJsonItems)createdJsonSelected.delete(item.path);
    createdJsonRender();
  });
  $('created-json-select-all').addEventListener('click',async()=>{
    if(createdJsonBusy || busy)return;
    createdJsonBusyState(true);
    try{
      const search=$('created-json-search').value.trim();
      const result=await api('/api/created-json/paths?'+new URLSearchParams({search}).toString());
      for(const path of (result.paths||[]))createdJsonSelected.add(path);
      createdJsonRender();
      $('created-xsk-status').textContent='เลือกเพลงจากผลค้นหาทั้งหมดแล้ว '+(result.paths||[]).length+' รายการ';
    }catch(error){message('เลือกทั้งหมดไม่สำเร็จ: '+error.message);}
    finally{createdJsonBusyState(false);createdJsonRender();}
  });
  $('created-json-clear').addEventListener('click',()=>{createdJsonSelected.clear();createdJsonRender();});
  $('created-json-preview').addEventListener('click',()=>{void createdJsonAction(true);});
  $('created-json-apply').addEventListener('click',()=>{void createdJsonAction(false);});
  $('created-json-undo').addEventListener('click',()=>{void undoCreatedJson();});

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
      await searchPreviewSongs();
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
  for (const el of document.querySelectorAll('[data-create-target]')) {
    el.addEventListener('click', () => goCreateStep(el.dataset.createTarget));
  }
  $('create-step-previous').addEventListener('click', () => goCreateStep(createStep - 1));
  $('create-step-next').addEventListener('click', () => goCreateStep(createStep + 1));
  $('song-rows').addEventListener('click', rowSelection);
  $('select-page').addEventListener('click',()=>{for (const song of songs) selected.add(song.id);void refreshSongs();});
  $('clear-selection').addEventListener('click',()=>{selected.clear();void refreshSongs();});
  $('select-all').addEventListener('click',async()=>{
    try {
      const result = await api('/api/songs/ids?search='+encodeURIComponent(search)+
        '&view='+encodeURIComponent($('catalog-view').value)+
        '&midi_only='+($('create-output-kind').value==='xsk'?'1':'0'));
      if (result.ids.length > 1000 && !await confirmStudio(`พบ ${fmtNum(result.ids.length)} เพลงที่ตรงเงื่อนไข ต้องการเลือกทั้งหมดจริงหรือไม่?`, 'เลือกรายการทั้งหมด')) return;
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
  for (const el of document.querySelectorAll('[data-pick]')) el.addEventListener('click',()=>pick(el.dataset.pick,el).catch(e=>message(e.message)));
  $('verify-code-registry').addEventListener('click',()=>{void verifyCodeRegistry();});
  $('catalog-view').addEventListener('change',async()=>{
    page=0;
    try {await config({catalog_view:$('catalog-view').value});}
    catch(e){message('จำตัวกรองรายการไม่ได้: '+e.message);}
    await refreshSongs();
  });
  $('scan-button').addEventListener('click',async()=>{
    try{await saveInputs(['create-source']);await run('scan',{full:false});}catch(e){message(e.message);}
  });
  $('reconcile-button').addEventListener('click',async()=>{
    try{await saveInputs(['create-source']);await run('scan',{full:false});}catch(e){message(e.message);}
  });
  $('scan-full-button').addEventListener('click',async()=>{
    try{await saveInputs(['create-source']);await run('scan',{full:true});}catch(e){message(e.message);}
  });
  $('create-build-show-log').addEventListener('click',showBuildLog);
  $('xsk-stream-build').addEventListener('click',()=>{void startStreamingXsk();});
  $('build-button').addEventListener('click',()=>{void startBuild(false);});
  $('build-audio-button').addEventListener('click',()=>{void startBuild(true);});
  $('preview-button').addEventListener('click',()=>{void startLivePreview();});
  $('lyric-group-scan').addEventListener('click',async()=>{
    if(busy)return;
    try {
      await saveInputs(['lyric-group-folder']);
      if(!busy)await run('lyric-groups-scan');
    }catch(error){message('เลือกโฟลเดอร์ต้นทางไม่สำเร็จ: '+error.message);}
  });
  $('lyric-group-reset').addEventListener('click',async()=>{
    if(busy)return;
    try{
      await config({lyric_source:''});
      message('กลับไปใช้คลัง XStageSong ของโฟลเดอร์งานหลักแล้ว',false);
    }catch(error){message(error.message);}
  });
  $('lyric-group-undo').addEventListener('click',()=>{void phraseUndo();});
  for(const btn of document.querySelectorAll('[data-lyric-position]')){
    btn.addEventListener('click',()=>{
      if(busy)return;
      const nextPosition=btn.dataset.lyricPosition;
      if(nextPosition==="all" || phrasePosition==="all"){
        // All-line groups are generated for the active exact phrase.
        // Never retain stale checked groups after changing this mode.
        phraseClearSelection();
      }
      phrasePosition=nextPosition;
      if(phrasePosition==="all")$('lyric-group-repeats').checked=false;
      phraseOffset=0;
      if(phraseReady)void refreshPhraseGroups();
    });
  }
  $('lyric-group-search').addEventListener('input',()=>{
    // Invalidate selections and previous search results IMMEDIATELY.
    // Delaying this reset until the debounce fired could silently clear
    // checkboxes the user had just selected from a stale result page.
    clearTimeout(phraseSearchTimer);
    ++phraseSeq;
    phraseOffset=0;
    phraseRows=[];
    phraseClearSelection();
    $('lyric-group-results').textContent='กำลังค้นหาวลีตามลำดับคำในบรรทัด…';
    $('lyric-group-page-count').dataset.total='0';
    $('lyric-group-page-count').textContent='กำลังค้นหา';
    phraseUpdateButtons();
    phraseSearchTimer=setTimeout(()=>{void refreshPhraseGroups();},220);
  });
  $('lyric-group-repeats').addEventListener('change',()=>{
    phraseOffset=0;phraseClearSelection();
    void refreshPhraseGroups();
  });
  $('lyric-group-results').addEventListener('change',event=>{
    const check=event.target.closest('input[data-lyric-group]');
    if(check)phraseToggleGroup(check.dataset.lyricGroup,check.checked);
  });
  $('lyric-group-select-page').addEventListener('click',()=>{
    if(busy||!phraseReady)return;
    const slots=Math.max(0,MAX_SELECTED_LYRIC_GROUPS-phraseSelected.size);
    let added=0;
    for(const row of phraseRows){
      if(phraseSelected.has(row.id))continue;
      if(added>=slots)break;
      phraseSelected.set(row.id,row);added++;
    }
    for(const check of $('lyric-group-results').querySelectorAll('input[data-lyric-group]'))
      check.checked=phraseSelected.has(check.dataset.lyricGroup);
    if(phraseRows.some(row=>!phraseSelected.has(row.id)))
      message('เลือกครบ '+fmtNum(MAX_SELECTED_LYRIC_GROUPS)+' กลุ่มแล้ว · บันทึกชุดที่เลือกก่อนแล้วจึงเลือกที่เหลือ');
    phraseUpdateButtons();schedulePhraseSelectionPreview();
  });
  $('lyric-group-select-matching').addEventListener('click',async()=>{
    if(busy||!phraseReady||phraseSelected.size>=MAX_SELECTED_LYRIC_GROUPS)return;
    const button=$('lyric-group-select-matching');
    const position=phrasePosition;
    const search=$('lyric-group-search').value.trim();
    const repeats=$('lyric-group-repeats').checked;
    const sequence=phraseSeq;
    button.disabled=true;
    try{
      const params=new URLSearchParams({
        position,search,repeats:repeats?'1':'0'
      });
      const result=await api('/api/lyric-groups/ids?'+params);
      if(busy||!phraseReady||position!==phrasePosition||sequence!==phraseSeq
         ||search!==$('lyric-group-search').value.trim()
         ||repeats!==$('lyric-group-repeats').checked)return;
      let added=0;
      for(const id of result.ids||[]){
        if(phraseSelected.size>=MAX_SELECTED_LYRIC_GROUPS)break;
        if(!phraseSelected.has(id)){
          phraseSelected.set(id,{id});
          added++;
        }
      }
      for(const check of $('lyric-group-results').querySelectorAll('input[data-lyric-group]'))
        check.checked=phraseSelected.has(check.dataset.lyricGroup);
      if(result.total>result.ids.length||phraseSelected.size>=MAX_SELECTED_LYRIC_GROUPS)
        message('เพิ่ม '+fmtNum(added)+' กลุ่ม · รองรับสูงสุด 1,000 กลุ่มต่อหนึ่งงาน เมื่อเสร็จแล้วเลือกชุดต่อไป',false);
      phraseUpdateButtons();
      schedulePhraseSelectionPreview();
    }catch(error){message('เลือกรายการตามตัวกรองไม่สำเร็จ: '+error.message);}
    finally{phraseUpdateButtons();}
  });
  $('lyric-group-clear').addEventListener('click',phraseClearSelection);
  $('lyric-group-prev').addEventListener('click',()=>{
    phraseOffset=Math.max(0,phraseOffset-40);
    void refreshPhraseGroups();
  });
  $('lyric-group-next').addEventListener('click',()=>{
    phraseOffset+=40;
    void refreshPhraseGroups();
  });
  $('lyric-group-replacement-mode').addEventListener('change',()=>{
    const value=$('lyric-group-replacement-mode').value;
    if(value!=='custom')$('lyric-group-replacement').value=value;
    else if(!$('lyric-group-replacement').disabled){
      $('lyric-group-replacement').focus();
      $('lyric-group-replacement').select();
    }
    phraseUpdateButtons();
    clearTimeout(phraseSearchTimer);
    phraseSearchTimer=setTimeout(()=>{void phraseRefreshSelection();},220);
  });
  $('lyric-group-replacement').addEventListener('input',()=>{
    const chosen=$('lyric-group-replacement-mode').value;
    if(chosen!=='custom'&&$('lyric-group-replacement').value!==chosen)
      $('lyric-group-replacement-mode').value='custom';
    phraseUpdateButtons();
    clearTimeout(phraseSearchTimer);
    phraseSearchTimer=setTimeout(()=>{void phraseRefreshSelection();},220);
  });
  $('lyric-group-apply').addEventListener('click',()=>{void phraseApply();});
  $('ai-lyrics-import').addEventListener('click',()=>{void aiImportAudio();});
  for(const id of ['ai-lyrics-title','ai-lyrics-artist'])
    $(id).addEventListener('input',()=>{aiDetailsDirty=true;aiUpdateButtons();});
  $('ai-lyrics-save-details').addEventListener('click',()=>{void aiSaveSourceDetails();});
  $('ai-lyrics-separate').addEventListener('click',()=>{void aiSeparateVocals();});
  $('ai-lyrics-use-vocals').addEventListener('change',()=>{
    aiStopPlayback();
    $('ai-lyrics-status').textContent=$('ai-lyrics-use-vocals').checked?
      'ใช้ M4A เสียงร้องแยกสำหรับ Whisper และการทดลองฟัง':
      'ใช้ไฟล์เพลงต้นฉบับสำหรับ Whisper และการทดลองฟัง';
    aiUpdateButtons();
  });
  $('ai-lyrics-refresh').addEventListener('click',()=>{void aiRefreshSongList();});
  $('ai-lyrics-search').addEventListener('input',()=>{
    clearTimeout(aiSearchTimer);
    aiSearchTimer=setTimeout(()=>{aiOffset=0;void aiRefreshSongList();},180);
  });
  $('ai-lyrics-results').addEventListener('click',event=>{
    const remove=event.target.closest('[data-ai-remove]');
    if(remove){
      const song=aiSongs.find(item=>item.id===Number(remove.dataset.aiRemove));
      if(song)void aiRemoveImportedSong(song);
      return;
    }
    const option=event.target.closest('[data-ai-id]');
    if(!option)return;
    const row=aiSongs.find(x=>x.id===Number(option.dataset.aiId));
    if(row)void aiChooseSong(row);
  });
  $('ai-lyrics-prev').addEventListener('click',()=>{
    aiOffset=Math.max(0,aiOffset-30);void aiRefreshSongList();
  });
  $('ai-lyrics-next').addEventListener('click',()=>{
    if(aiOffset+30<aiTotal){aiOffset+=30;void aiRefreshSongList();}
  });
  $('ai-lyrics-read-source').addEventListener('click',async()=>{
    if(!Number.isInteger(aiSongId) || busy)return;
    const chosen=aiSongId;
    if(aiDetailsDirty || $('ai-lyrics-editor').value.trim() || $('ai-lyrics-paste').value.trim()){
      const yes=await confirmStudio(
        'อ่านแท็กและเนื้อร้องจากต้นฉบับอีกครั้ง? ข้อความที่กำลังแก้ในช่องอาจถูกแทนที่ แต่ไม่แก้ไฟล์ต้นฉบับหรือข้อมูลที่บันทึกแล้ว',
        'อ่านข้อมูลต้นฉบับ');
      if(!yes)return;
    }
    $('ai-lyrics-source-status').textContent='กำลังตรวจชื่อเพลง ศิลปิน และคำร้องจากแท็ก/ไฟล์คู่เพลง…';
    try{
      const file=await api('/api/ai-lyrics-source?id='+encodeURIComponent(chosen));
      if(chosen!==aiSongId)return;
      const title=String(file.title||'').trim();
      const artist=String(file.artist||'').trim();
      if(title)$('ai-lyrics-title').value=title;
      if(artist)$('ai-lyrics-artist').value=artist;
      if(file.timedLrc){
        $('ai-lyrics-editor').value=String(file.timedLrc);
      }
      if(file.plainLyrics){
        $('ai-lyrics-paste').value=String(file.plainLyrics);
        aiPastedLyrics.set(chosen,String(file.plainLyrics));
      }
      aiDetailsDirty=true;
      aiValidateEditor();
      aiUpdateButtons();
      $('ai-lyrics-source-status').textContent=(file.metadataSource||'ไม่พบแท็กชื่อเพลง')+
        ' · '+(file.lyricsSource||'ไม่พบเนื้อร้องในไฟล์')+' · ตรวจแก้แล้วกดบันทึกก่อนส่งออก';
      message('อ่านข้อมูลจากไฟล์ต้นฉบับแล้ว · หากต้องการใช้ผลลัพธ์ ให้ตรวจและบันทึก',false);
    }catch(error){
      $('ai-lyrics-source-status').textContent='อ่านข้อมูลจากไฟล์ไม่สำเร็จ: '+error.message;
      message(error.message);
    }
  });
  $('ai-lyrics-start').addEventListener('click',()=>{void aiStartTranscription();});
  $('ai-lyrics-align').addEventListener('click',()=>{void aiAlignPastedLyrics();});
  $('ai-lyrics-paste').addEventListener('input',()=>{
    if(Number.isInteger(aiSongId))aiPastedLyrics.set(aiSongId,$('ai-lyrics-paste').value);
    aiUpdateButtons();
  });
  $('ai-lyrics-play').addEventListener('click',()=>{void aiPlayAudio();});
  $('ai-lyrics-stop').addEventListener('click',aiStopPlayback);
  $('ai-lyrics-editor').addEventListener('input',aiValidateEditor);
  $('ai-lyrics-audio').addEventListener('timeupdate',aiRenderTime);
  $('ai-lyrics-audio').addEventListener('play',aiStartKaraokeAnimation);
  $('ai-lyrics-audio').addEventListener('playing',aiStartKaraokeAnimation);
  $('ai-lyrics-audio').addEventListener('waiting',()=>{
    $('ai-lyrics-status').textContent='กำลังรอข้อมูลเสียงเพิ่มเติมจาก Local Engine · ตรวจการเชื่อมต่อสตรีม';
  });
  $('ai-lyrics-audio').addEventListener('error',()=>{
    const code=aiAudio.error?.code||'unknown';
    $('ai-lyrics-status').textContent='สตรีมทดลองฟังมีข้อผิดพลาด ('+code+
      ') · กดหยุดแล้วเริ่มทดลองฟังอีกครั้ง';
    aiStopKaraokeAnimation();
  });
  document.addEventListener('visibilitychange',()=>{
    if(!document.hidden&&!aiAudio.paused)aiStartKaraokeAnimation();
  });
  $('ai-lyrics-audio').addEventListener('pause',aiStopKaraokeAnimation);
  $('ai-lyrics-audio').addEventListener('ended',()=>{
    aiStopKaraokeAnimation();aiRenderTime();
  });
  $('ai-lyrics-audio').addEventListener('seeked',()=>{aiActiveIndex=-2;aiRenderTime();});
  $('ai-lyrics-insert-time').addEventListener('click',aiInsertTimestamp);
  $('ai-lyrics-download').addEventListener('click',aiDownloadLrc);
  $('ai-export-button').addEventListener('click',()=>{void aiExportSelected();});
  for(const id of ['ai-export-lyrics','ai-export-instrumental','ai-export-source','ai-export-format'])
    $(id).addEventListener('change',aiUpdateButtons);
  $('ai-export-choose-folder').addEventListener('click',()=>{
    void pick('download').then(()=>{
      $('ai-export-folder').textContent=prefs.download||'ยังไม่ได้เลือกโฟลเดอร์';
    }).catch(error=>message(error.message));
  });
  $('ai-lyrics-save').addEventListener('click',()=>{void aiApproveLrc();});
  $('preview-stop-button').addEventListener('click',stopLivePreview);
  $('preview-file-type').addEventListener('change', () => {
    stopLivePreview();
    updateButtons();
    if (livePreviewPending) { previewPendingChange = true; return; }
    void startLivePreview();
  });
  $('preview-ai-transcribe').addEventListener('click',()=>{void transcribePreviewWithAi();});
  $('preview-ai-review').addEventListener('click',()=>{void reviewAiLyrics();});
  previewAudio.addEventListener('timeupdate',()=>{
    updateLyricTime(previewAudio.currentTime);
    previewLyricClockHealth();
  });
  previewAudio.addEventListener('play', startKaraokeAnimation);
  previewAudio.addEventListener('playing', startKaraokeAnimation);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && !previewAudio.paused) startKaraokeAnimation();
  });
  previewAudio.addEventListener('pause', () => {
    if (karaokeAnimationFrame) cancelAnimationFrame(karaokeAnimationFrame);
    karaokeAnimationFrame = 0;
  });
  previewAudio.addEventListener('ended', () => {
    if (karaokeAnimationFrame) cancelAnimationFrame(karaokeAnimationFrame);
    karaokeAnimationFrame = 0;
  });
  previewAudio.addEventListener('seeked',()=>{
    currentLyricIndex=-2;
    previewClockLast=-1;
    previewLyricCoverageWarned=false;
    updateLyricTime(previewAudio.currentTime);
    if (!previewAudio.paused) startKaraokeAnimation();
  });
  $('preview-song-search').addEventListener('input', () => {
    clearTimeout(previewSearchTimer);
    previewSearchTimer = setTimeout(() => {void searchPreviewSongs();}, 180);
  });
  $('preview-search-results').addEventListener('click', event => {
    const option = event.target.closest('[data-preview-id]');
    if (!option) return;
    const chosen = Number(option.dataset.previewId);
    const song = previewSongRows.find(item => item.id === chosen);
    if (!song) return;
    stopLivePreview();
    previewSongId = chosen;
    showPreviewIdentity(song);
    void loadPreviewIdentity(chosen, song);
    for (const button of $('preview-search-results').querySelectorAll('[data-preview-id]')) {
      button.setAttribute('aria-selected', String(Number(button.dataset.previewId) === chosen));
      button.classList.toggle('active', Number(button.dataset.previewId) === chosen);
    }
    updateButtons();
    void loadPreviewLyrics(chosen);
    void loadPreviewSources(chosen).then(report => {
      if (report && previewSongId === chosen) void startLivePreview();
    });
  });
  for (const [slider,label] of [['preview-music-volume','preview-music-volume-label'],
                                 ['preview-sf-volume','preview-sf-volume-label']]) {
    $(slider).addEventListener('input', () => {
      $(label).textContent = $(slider).value + '%';
      queueLiveControl();
    });
  }
  // SoundFont and MIDI preset adjustments apply to the existing stream,
  // without creating another file or losing the current play position.
  $('create-soundfont').addEventListener('change',()=>queueLiveControl(true));
  $('create-preset').addEventListener('change',()=>queueLiveControl(true));
  $('create-mode').addEventListener('change', () => {
    if (liveStreamId) $('create-preview-hint').textContent =
      'AI แยกเสียงใช้กับการสร้างเพลงในขั้นตอนที่ 4 เท่านั้น · เสียงทดลองฟังยังเป็นดนตรีต้นฉบับ';
  });
  previewAudio.addEventListener('error', () => {
    if (previewAudio.getAttribute('src')) message('สตรีมเสียงขัดข้อง · ตรวจไฟล์ต้นฉบับและ SoundFont แล้วกดเล่นใหม่');
  });
  $('edit-button').addEventListener('click',()=>{void openEdit();});
  $('history-refresh').addEventListener('click',()=>{void refreshHistory();});
  $('history-list').addEventListener('click',event=>{
    const button=event.target.closest('[data-restore-history]');
    if (button) void restoreHistory(button.dataset.restoreHistory);
  });
  $('edit-dialog').addEventListener('close',event=>{if($('edit-dialog').returnValue==='save')void saveEdit();});
  for (const button of [$('upload-login'),$('settings-login'),$('google-login-header')]) button.addEventListener('click',async()=>{
    try {
      // A manually pasted JSON path must be imported before starting OAuth;
      // clicking Login immediately after editing used to skip that step.
      const proposed = $('settings-oauth').value.trim();
      if (proposed && proposed !== (prefs.oauth || '')) {
        await config({oauth:proposed});
      }
      const latest = await api('/api/status');
      setGoogle(latest.google);
      if (!latest.google?.configured) {
        $('oauth-advanced').open = true;
        tab('settings');
        message('Song Studio PC ยังไม่มี Google Desktop OAuth Client JSON · กรุณาเปิดตัวเลือกขั้นสูง เลือกไฟล์ JSON ชนิด Desktop App แล้วกด Google Login อีกครั้ง' + (latest.google?.error ? ' · ' + latest.google.error : ''));
        return;
      }
      if (latest.google?.connected) {
        message('Song Studio PC เชื่อม Google Drive อยู่แล้ว: ' + (latest.google.email || 'บัญชี Google'), false);
        await refreshEnvironment();
        return;
      }
      await run('login');
    } catch(e) {
      message('เริ่ม Google Login ไม่สำเร็จ: ' + e.message);
      await refreshEnvironment();
    }
  });
  $('google-login-focus').addEventListener('click',async()=>{
    const button = $('google-login-focus');
    button.disabled = true;
    try {
      const opened = await post('/api/google-login-focus',{});
      message(opened.message || 'แสดงหน้า Google Login แล้ว · โปรดเลือกบัญชีและกดอนุญาต',false);
    } catch(e) {
      message('เปิดหน้า Google Login ไม่สำเร็จ: ' + e.message);
    } finally {
      button.disabled = false;
    }
  });
  $('settings-logout').addEventListener('click',async()=>{if(await confirmStudio('ออกจากบัญชี Google ใน Song Studio ใช่หรือไม่?', 'ยืนยันออกจากบัญชี'))void run('logout');});
  $('upload-folder').addEventListener('change',()=>{void inspectUploadFolder();});

  async function inspectJsonPro() {
    const label=$('json-pro-report');
    const finishInspection=beginInspection('json-pro-report','กำลังตรวจรายการเพลงและ Lyrics JSON ในโฟลเดอร์ย่อยทั้งหมด');
    if(!finishInspection)return null;
    try{
      await saveInputs(['json-pro-source','json-pro-destination']);
      const report=await api('/api/json-pro/inspect');
      label.textContent='ตรวจ '+fmtNum(report.fileCount)+' ไฟล์ · พร้อมแปลง '+fmtNum(report.ready)+
        ' · เนื้อร้องไม่ครบ '+fmtNum(report.incomplete)+' · ไม่รองรับ '+fmtNum(report.unsupported)+
        '\\nต้นทาง: '+report.folder+'\\nปลายทาง: '+(prefs.json_destination||'ยังไม่ได้เลือก')+
        (report.examples?.length?'\\nข้าม: '+report.examples.slice(0,5).map(x=>x.name+' '+x.reason).join(' | '):'');
      return report;
    }catch(error){
      label.textContent='ตรวจไม่สำเร็จ: '+error.message;
      message(error.message);
      return null;
    } finally {
      finishInspection();
    }
  }
  async function startJsonPro() {
    if(!canLaunch('json-pro-export') || !proEnabled)return message('เมนู Lyrics JSON ต้องเปิดใช้ Pro และมีทรัพยากรเครื่องเพียงพอ');
    const report=await inspectJsonPro();
    if(!report||!report.ready)return message('ไม่มีชุดเพลงที่ตรวจผ่านพร้อม Lyrics JSON');
    const format=$('json-pro-format').value;
    const code_style=$('json-pro-code-style').value;
    const code_length=Number($('json-pro-code-length').value);
    if(!Number.isInteger(code_length)||code_length<1||code_length>12)
      return message('จำนวนหลักรหัสเพลงต้องอยู่ระหว่าง 1–12');
    await saveInputs(['json-pro-code-style','json-pro-code-length']);
    // The single "ตกลง" action initiates inspected batch export directly.
    // The engine still rejects invalid sources, duplicates and overwrites.
    $('json-pro-report').textContent='กำลังส่งคำสั่งส่งออก '+fmtNum(report.ready)+' เพลงไปยัง PC Engine…';
    const started=await run('json-pro-export',{format,code_style,code_length:String(code_length)});
    if(!started){
      $('json-pro-report').textContent=
        'ยังไม่ได้เริ่มส่งออก '+fmtNum(report.ready)+' เพลง · PC Engine ไม่รับงาน'+
        '\\nตรวจ RAM/CPU และข้อความแจ้งเตือนด้านบน · ยังไม่มีไฟล์ใหม่จากคำสั่งนี้';
      return;
    }
    $('json-pro-report').textContent=
      'PC Engine รับงานส่งออก '+fmtNum(report.ready)+' เพลงแล้ว · ตรวจความคืบหน้าจริงด้านล่าง';
  }
  $('json-pro-inspect').addEventListener('click',()=>{void inspectJsonPro();});
  $('json-pro-start').addEventListener('click',()=>{void startJsonPro();});
  // Inspect on "ตกลง" only, not while users are still choosing folders.
  $('upload-inspect').addEventListener('click',()=>{void inspectUploadFolder();});
  $('pc-export-inspect').addEventListener('click',()=>{void inspectPCExport();});
  $('pc-export-start').addEventListener('click',()=>{void startPCExport();});
  $('upload-soundfont-picker').addEventListener('click',()=>{void chooseUploadSoundfont();});
  $('upload-soundfont-button').addEventListener('click',()=>{void startSoundfontUpload();});
  $('upload-folder-button').addEventListener('click',()=>{void startFolderUpload();});
  for(const button of document.querySelectorAll('.download-action')) button.addEventListener('click',()=>{void startDownload(button.dataset.kind);});
  $('refresh-environment').addEventListener('click',()=>{void refreshEnvironment();});
  $('open-web').addEventListener('click',async()=>{
    try {await post('/api/open-browser',{});message('เปิด Web Control ด้วย Local Engine ชุดเดียวกันแล้ว',false);}
    catch(e){message(e.message);}
  });
  $('update-button').addEventListener('click',()=>{
    $('update-result').textContent='กำลังตรวจข้อมูลรุ่น PC Ready ที่เผยแพร่…';
    $('update-download').hidden=true;
    void run('check-update');
  });
  $('update-download').addEventListener('click',()=>{
    $('update-result').textContent='กำลังดาวน์โหลด ตรวจ SHA-256 และติดตั้งรุ่นใหม่…';
    void run('install-update');
  });
  $('cancel-job').addEventListener('click',async()=>{
    if(cancellationPending)return;
    cancellationPending=true;
    $('cancel-job').disabled=true;
    try{
      const result=await post('/api/jobs/cancel',{});
      if(result.stopping){
        message('กำลังหยุดงานเดิมและคืนทรัพยากร · เมื่อหยุดเสร็จสามารถทำรายการอื่นได้',false);
      }else{
        cancellationPending=false;
      }
    }catch(e){
      cancellationPending=false;
      $('cancel-job').disabled=false;
      message(e.message);
    }
  });
  $('toggle-log').addEventListener('click',()=>{
    const log = $('job-log');log.hidden=!log.hidden;
    $('toggle-log').setAttribute('aria-expanded',String(!log.hidden));
    $('toggle-log').textContent=log.hidden?'รายละเอียด ▾':'ซ่อนรายละเอียด ▴';
  });
  $('create-output-kind').addEventListener('change',()=>{
    syncXskControls();
    selected.clear();
    page=0;
    void config({export_format:$('create-output-kind').value})
      .then(()=>refreshSongs()).catch(e=>message(e.message));
  });
  $('xsk-edit-choice').addEventListener('change',syncXskControls);
  $('pro-license-activate').addEventListener('click',async()=>{
    const entered=$('pro-license-key').value.trim();
    if(!entered)return message('กรุณากรอก License Key Pro');
    try{
      await post('/api/license/activate',{key:entered});
      $('pro-license-key').value='';
      await refreshProLicense();
      message('เปิดใช้ X-Stage Song Studio PC Pro สำเร็จ',false);
    }catch(error){message('เปิดใช้ Pro ไม่สำเร็จ: '+error.message);}
  });
  updateCreateWizard();
  void initialize().then(()=>refreshProLicense());
})();