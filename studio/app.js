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
    'ai-lyrics': ['สร้างเนื้อร้อง AI', 'นำเข้าเพลงใหม่ ถอดเสียงร้อง จัดเวลา และทดลองฟัง LRC'],
    'lyric-head-tail': ['จัดการข้อความหัว–ท้ายเพลง', 'ตรวจข้อความซ้ำ 4 ตำแหน่ง · แทนที่ทั้งกลุ่มและย้อนคืนได้'],
    upload: ['อัปโหลด', 'ตรวจไฟล์ซ้ำบน Google Drive · ส่งเฉพาะเพลงที่เปลี่ยน'],
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
  let busy = false, editingId = null, notificationTimer = null;
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
  let aiMicRecorder=null,aiMicStream=null,aiMicChunks=[];
  let aiMicBlob=null,aiMicUrl='',aiMicTimer=0,aiMicStarted=0;
  let aiMicSaving=false,aiMicPending=false;
  let phraseReady=false,phrasePosition='first',phraseOffset=0,phraseRows=[];
  let phraseSeq=0,phraseSearchTimer=0,phraseBackup=null;
  const phraseSelected=new Map();
  let phrasePlan=null,phraseSelectionSeq=0;
  // Keep the owner's pasted words independent from Whisper's guessed text.
  const aiPastedLyrics = new Map();
  let pendingAiAlignment = null;

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
    box.hidden = !text; box.dataset.error = isError ? 'true' : 'false';
    clearTimeout(notificationTimer);
    if (text) notificationTimer = setTimeout(() => {box.hidden = true;}, isError ? 9500 : 5000);
  }
  function confirmStudio(description, title='ยืนยันรายการ',
                         {acceptLabel='ยืนยัน', cancelLabel='ยกเลิก'} = {}) {
    return new Promise(resolve => {
      const dialog = $('studio-confirm-dialog');
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
    if (activeTab !== 'ai-lyrics') {
      aiStopPlayback();
      if(aiMicRecorder?.state==='recording')aiStopMic();
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
    $('lyric-group-search').disabled=!allow;
    $('lyric-group-repeats').disabled=!allow;
    $('lyric-group-replacement').disabled=!allow||phraseSelected.size===0;
    $('lyric-group-apply').disabled=!allow||phraseSelected.size===0||
      !$('lyric-group-replacement').value.trim();
    $('lyric-group-undo').disabled=busy||!phraseBackup;
    $('lyric-group-select-page').disabled=!allow||phraseRows.length===0;
    $('lyric-group-clear').disabled=busy||phraseSelected.size===0;
    $('lyric-group-selected-count').textContent=
      'เลือก '+fmtNum(phraseSelected.size)+' กลุ่ม';
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
    $('lyric-group-results').textContent='กำลังจัดอันดับข้อความที่ใช้ซ้ำ…';
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
        number.textContent=fmtNum(group.count)+' เพลง'+
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
      if(data.length>20){
        const more=document.createElement('div');more.className='lyric-group-example';
        more.textContent='และอีก '+fmtNum(data.length-20)+' กลุ่มที่เลือก';
        panel.append(more);
      }
      $('lyric-group-preview-status').textContent=
        'ค้นหาในเนื้อร้องทั้งเพลง · แก้เฉพาะเพลงที่ตรงคำค้นและกลุ่มที่ติ๊กเลือก · '+
        'สำรองก่อนแก้ · หลังยืนยันรายการที่ยังไม่แก้ยังแสดงอยู่';
    }catch(error){
      if(seq!==phraseSelectionSeq)return;
      phrasePlan=null;
      $('lyric-group-selection').textContent='ตรวจกลุ่มที่เลือกไม่สำเร็จ: '+error.message;
      message(error.message);
    }
    phraseUpdateButtons();
  }
  function phraseToggleGroup(id,selected){
    const row=phraseRows.find(x=>x.id===id);
    if(!row||busy)return;
    if(selected)phraseSelected.set(row.id,row);
    else phraseSelected.delete(id);
    for(const label of $('lyric-group-results').querySelectorAll('.lyric-group-row')){
      const input=label.querySelector('[data-lyric-group]');
      if(input)label.classList.toggle('active',phraseSelected.has(input.dataset.lyricGroup));
    }
    phraseUpdateButtons();
    void phraseRefreshSelection();
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
      (search?'ค้นหาในทุกบรรทัด: '+search+'\nแก้เฉพาะเพลงที่ตรงคำค้นหานี้\n':'')+
      '\nข้อความใหม่ร่วมกัน:\n'+replacement+'\n\n'+
      'สำรอง JSON/LRC ก่อนแก้ทุกเพลง · ไฟล์เสียงและเวลาเดิมไม่เปลี่ยน'+
      '\nรายการอื่นยังคงอยู่เพื่อแก้ต่อ · อัปโหลด Google Drive ต้องสั่งเอง',
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
    for (const id of ['upload-button', 'settings-logout']) $(id).disabled = busy || !googleConnected;
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
    $('upload-selected-count').textContent = 'ซิงค์คลังเพลงทั้งหมด';
    const buttons = ['scan-button','reconcile-button','scan-full-button','preview-button','edit-button','build-button',
      'build-audio-button','select-all','select-page','clear-selection','upload-login','settings-login',
      'settings-logout','google-login-header','update-button','verify-code-registry'];
    for (const name of buttons) $(name).disabled = busy;
    $('build-button').disabled = busy || selected.size === 0;
    $('build-audio-button').disabled = busy || selected.size === 0;
    $('preview-button').disabled = busy || livePreviewPending || (!previewSongId && selected.size !== 1);
    $('edit-button').disabled = busy || selected.size !== 1;
    $('upload-button').disabled = busy || !googleConnected;
    $('settings-logout').disabled = busy || !googleConnected;
    for (const el of document.querySelectorAll('.download-action')) el.disabled = busy || !googleConnected;
    for (const el of document.querySelectorAll('[data-pick],.field,.song-table input[type=checkbox]')) el.disabled = busy;
    $('cancel-job').hidden = !busy;
    updateCreateWizard();
    phraseUpdateButtons();
    aiUpdateButtons();
  }
  async function verifyCodeRegistry() {
    const button = $('verify-code-registry');
    const indicator = $('code-registry-state');
    if (busy || button.disabled) return;
    button.disabled = true;
    const priorLabel = button.textContent;
    button.textContent = 'กำลังเทียบรหัสทั้งสองคลัง…';
    indicator.textContent = 'กำลังอ่าน Catalog ในเครื่องและ XStageWeb บน Google Drive · ยังไม่เปลี่ยนรหัสหรือไฟล์ใด ๆ';
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
    const previousSource = prefs.source;
    const response = await post('/api/config', patch);
    prefs = response.preferences || prefs;
    if ((patch.workspace && previousWorkspace !== prefs.workspace) ||
        (patch.source && previousSource !== prefs.source)) {
      selected.clear(); page = 0; await refreshSongs();
    }
    if ('soundfont' in patch || 'workspace' in patch) soundfontOptions(response.soundfonts || []);
    setFields();
    if (response.google) setGoogle(response.google);
    if ('oauth' in patch) await refreshEnvironment();
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
    const button = [...document.querySelectorAll('[data-pick]')].find(el => el.dataset.pick === kind);
    if (busy || button?.disabled) return;
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
          download:'download-destination',oauth:'settings-oauth'})[kind];
      const element = $(field);
      if (kind === 'soundfont' && ![...element.options].some(opt => opt.value === response.path)) {
        element.add(new Option(response.path.split(/[\\/]/).pop(), response.path));
      }
      element.value = response.path;
      await config({[kind]: response.path});
      message('เลือกและบันทึกตำแหน่งใหม่เรียบร้อยแล้ว', false);
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
      if (!line || /^\[(ti|ar|al|by|offset):/i.test(line)) continue;
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
    $('ai-lyrics-separate').disabled = busy || !hasSong || !aiSeparationAvailable;
    $('ai-lyrics-use-vocals').disabled = busy || !hasSong || !aiSeparatedPath;
    const micRecording=aiMicRecorder?.state==='recording';
    $('ai-mic-start').disabled=busy||aiMicSaving||aiMicPending||micRecording||
      !navigator.mediaDevices?.getUserMedia||typeof MediaRecorder==='undefined';
    $('ai-mic-stop').disabled=!micRecording;
    $('ai-mic-save').disabled=busy||aiMicSaving||aiMicPending||micRecording||!aiMicBlob;
    $('ai-mic-discard').disabled=aiMicSaving||aiMicPending||micRecording||!aiMicBlob;
    $('ai-lyrics-play').disabled = busy || !hasSong;
    $('ai-lyrics-editor').disabled = !hasSong;
    $('ai-lyrics-insert-time').disabled = !hasSong || !aiAudio.src;
    $('ai-lyrics-download').disabled = !hasSong || !valid;
    $('ai-lyrics-save').disabled = busy || !hasSong || !valid || !aiDraftReady;
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
    if(!Number.isInteger(aiSongId)||busy||!aiSeparationAvailable)
      return message('กรุณาเลือกไฟล์เสียงร้องและตรวจว่า HTDemucs พร้อม');
    const id=aiSongId;
    const approved=await confirmStudio(
      'แยกเสียงร้องและดนตรีแบบออฟไลน์ด้วย HTDemucs แล้วบันทึก M4A แยก 2 ไฟล์ใน StageWeb/audio\n'+
      'เสียงเพลงต้นฉบับไม่เปลี่ยนและไม่อัปโหลด Google Drive\n'+
      'การแยกเสียงร้องอาจมีเสียงดนตรีหลงเหลือ ต้องทดลองฟังตรวจสอบ',
      'ยืนยันแยกเสียงร้องและดนตรีเป็น M4A',
      {acceptLabel:'เริ่มแยกเสียงร้อง',cancelLabel:'ยกเลิก'});
    if(!approved||busy||aiSongId!==id)return;
    aiStopPlayback();
    $('ai-lyrics-vocals-status').textContent=
      'กำลังแยกเสียงร้องและดนตรีด้วย HTDemucs · ตรวจความคืบหน้าที่แผงงาน';
    await run('ai-separate-vocals',{id});
  }
  function aiUpdateMicTimer(){
    if(!aiMicStarted)return;
    const seconds=Math.min(1200,Math.floor((Date.now()-aiMicStarted)/1000));
    $('ai-mic-timer').textContent=String(Math.floor(seconds/60)).padStart(2,'0')+
      ':'+String(seconds%60).padStart(2,'0');
    if(seconds>=1200&&aiMicRecorder?.state==='recording')aiStopMic();
  }
  function aiMicReleaseStream(){
    if(aiMicStream)for(const track of aiMicStream.getTracks())track.stop();
    aiMicStream=null;
    if(aiMicTimer){clearInterval(aiMicTimer);aiMicTimer=0;}
  }
  function aiMicDiscard(){
    if(aiMicRecorder?.state==='recording')return;
    aiMicReleaseStream();aiMicBlob=null;aiMicChunks=[];
    if(aiMicUrl)URL.revokeObjectURL(aiMicUrl);
    aiMicUrl='';
    $('ai-mic-preview').pause();
    $('ai-mic-preview').removeAttribute('src');
    $('ai-mic-preview').hidden=true;
    $('ai-mic-timer').textContent='00:00';
    $('ai-mic-status').textContent='ลบเสียงที่ยังไม่บันทึกจากหน่วยความจำแล้ว · พร้อมอัดใหม่';
    aiUpdateButtons();
  }
  async function aiStartMic(){
    if(busy||aiMicSaving||aiMicPending||aiMicRecorder?.state==='recording')return;
    if(!navigator.mediaDevices?.getUserMedia||typeof MediaRecorder==='undefined')
      return message('เบราว์เซอร์นี้ไม่รองรับการบันทึกไมโครโฟน · ใช้ Edge หรือ Chrome เวอร์ชันล่าสุด');
    aiMicDiscard();
    try{
      const stream=await navigator.mediaDevices.getUserMedia({
        audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
      aiMicStream=stream;
      const mime=[
        'audio/webm;codecs=opus','audio/mp4','audio/ogg;codecs=opus'
      ].find(type=>MediaRecorder.isTypeSupported(type));
      if(!mime)throw new Error('เบราว์เซอร์ไม่รองรับ WebM/MP4/OGG สำหรับไมโครโฟน');
      aiMicRecorder=new MediaRecorder(stream,{mimeType:mime,audioBitsPerSecond:128000});
      aiMicChunks=[];
      aiMicRecorder.ondataavailable=event=>{
        if(event.data?.size)aiMicChunks.push(event.data);
        if(aiMicChunks.reduce((s,item)=>s+item.size,0)>64*1024*1024)
          aiStopMic();
      };
      aiMicRecorder.onerror=()=>{
        $('ai-mic-status').textContent='ไมโครโฟนขัดข้อง · ตรวจสิทธิ์อุปกรณ์และลองใหม่';
        aiMicReleaseStream();aiUpdateButtons();
      };
      aiMicRecorder.onstop=()=>{
        aiMicReleaseStream();
        const blob=new Blob(aiMicChunks,{type:mime});
        aiMicRecorder=null;
        aiMicChunks=[];
        if(blob.size<1000||blob.size>64*1024*1024){
          $('ai-mic-status').textContent='เสียงสั้นเกินไปหรือเกิน 64 MB · กรุณาบันทึกใหม่';
          aiMicBlob=null;
        }else{
          aiMicBlob=blob;
          aiMicUrl=URL.createObjectURL(blob);
          const player=$('ai-mic-preview');
          player.src=aiMicUrl;player.hidden=false;
          $('ai-mic-status').textContent=
            'อัดเสร็จ · '+fmtSize(blob.size)+' · ทดลองฟังก่อนกดบันทึกเป็น M4A';
        }
        aiUpdateButtons();
      };
      aiMicRecorder.start(1000);
      aiMicStarted=Date.now();
      aiMicTimer=setInterval(aiUpdateMicTimer,500);
      $('ai-mic-status').textContent=
        '● กำลังบันทึกจากไมโครโฟนในเบราว์เซอร์ · กดหยุดก่อนทดลองฟัง · ไม่ส่งข้อมูลขึ้น Drive';
      aiUpdateButtons();
    }catch(error){
      aiMicRecorder=null;aiMicReleaseStream();
      $('ai-mic-status').textContent='เปิดไมโครโฟนไม่ได้: '+error.message;
      aiUpdateButtons();
    }
  }
  function aiStopMic(){
    if(aiMicRecorder?.state==='recording'){
      try{aiMicRecorder.stop();}
      catch(error){$('ai-mic-status').textContent='หยุดอัดเสียงไม่สำเร็จ: '+error.message;}
    }
    aiMicReleaseStream();
    aiUpdateButtons();
  }
  async function aiSaveMic(){
    if(!aiMicBlob||busy||aiMicSaving||aiMicPending)return;
    const blob=aiMicBlob;
    const approved=await confirmStudio(
      'นำเสียงร้องที่อัดผ่านไมโครโฟนมาแปลงเป็น AAC/M4A ภายในคอมพิวเตอร์\n'+
      'จัดเก็บใน StageWeb/audio และเพิ่มเข้าเมนูสร้างเนื้อร้อง AI\n'+
      'ไม่มีการอัปโหลด Google Drive และยังไม่เผยแพร่ในคลังเพลงออนไลน์',
      'ยืนยันบันทึกเสียงร้องใหม่',
      {acceptLabel:'บันทึกเสียง M4A',cancelLabel:'ยกเลิก'});
    if(!approved||busy||blob!==aiMicBlob)return;
    aiMicSaving=true;aiUpdateButtons();
    $('ai-mic-status').textContent='กำลังส่งเสียงที่อัดให้ Local Engine บนเครื่องเดียวกัน…';
    try{
      const response=await fetch(engineAddress('/api/ai-recording-upload'),{
        method:'POST',body:blob,cache:'no-store',
        credentials:onlinePage?'omit':'same-origin',mode:onlinePage?'cors':'same-origin',
        headers:{'X-XStage-Token':token,'Content-Type':blob.type||'audio/webm'}
      });
      const data=await response.json();
      if(!response.ok)throw new Error(data.error||'Engine ไม่รับไฟล์เสียงที่อัด');
      aiMicPending=true;aiMicSaving=false;
      $('ai-mic-status').textContent='รับเสียงบันทึกแล้ว · กำลังแปลงเป็น M4A…';
      const started=await run('ai-recording-save',{recordingId:data.recordingId});
      if(!started)throw new Error('เริ่มแปลง M4A ไม่สำเร็จ · โปรดลองบันทึกใหม่');
    }catch(error){
      aiMicSaving=false;aiMicPending=false;
      $('ai-mic-status').textContent='บันทึกไม่สำเร็จ: '+error.message+
        ' · ยังเก็บเสียงที่อัดไว้ในหน้านี้เพื่อให้ลองใหม่';
      message(error.message);
    }
    aiUpdateButtons();
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
  }
  function aiRenderTime() {
    const panel=$('ai-lyrics-karaoke');
    if(!aiTimed.length)return;
    const t=Number(aiAudio.currentTime)||0;
    let current=-1;
    for(let i=0;i<aiTimed.length;i++){
      if(aiTimed[i].startTime>t)break;
      current=i;
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
    aiTimed=check.lines;aiActiveIndex=-2;
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
    aiDraftReady=false;aiEngineReady=false;
    $('ai-lyrics-selected').textContent=(row.title||row.code)+
      ' · '+(row.artist||'ไม่ระบุศิลปิน')+' · '+(row.kind||'');
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
      $('ai-lyrics-editor').value=String(data.approvedLrc||data.draft?.rawLrc||'');
      $('ai-lyrics-engine-state').textContent=aiEngineReady ?
        'Whisper AI พร้อมใช้งาน' : 'Whisper AI ไม่พร้อม';
      $('ai-lyrics-status').textContent=!aiEngineReady ?
        'AI ยังถอดคำร้องไม่ได้: '+(data.aiProblem||'กรุณาติดตั้ง PC Ready รุ่นเต็มให้ครบ'):
        data.approvedLrc ?
        '✓ พบเนื้อร้องที่เคยตรวจบันทึกแล้ว · สามารถทดลองฟังอีกครั้ง':
        data.hasDraft ? 'พบร่างคำร้อง AI · โปรดฟังตรวจคำและเวลา':
        'ยังไม่มีร่าง AI · ถ้าเพลงมีเสียงร้องให้กดถอดคำร้อง';
      aiValidateEditor();
    }catch(error){
      if(seq===aiDraftSeq)$('ai-lyrics-status').textContent='อ่านร่างไม่สำเร็จ: '+error.message;
    }
  }
  async function aiStartTranscription() {
    if(!Number.isInteger(aiSongId)||!aiEngineReady||busy)
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
    if(!Number.isInteger(aiSongId)||busy || !(aiEngineReady||aiDraftReady))
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
    if(!aiParseLrc().valid||!aiDraftReady)
      return message('ต้องมีร่าง AI และรูปแบบ LRC ที่ถูกต้องก่อนบันทึก');
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
  async function run(action, options = {}) {
    if (busy) {
      message('มีงานกำลังทำอยู่ · กรุณารอหรือกดยกเลิกก่อน');
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
      busy = true;
      updateButtons();
      if (action === 'build') {
        buildFeedback('running', 'PC Engine รับคำสั่งสร้างเพลงแล้ว',
          'เลขงาน ' + response.id + ' · ' + fmtNum(response.total ?? options.ids?.length ?? 0) +
          ' เพลง · ' + (options.audio_only ? 'สร้าง M4A อย่างเดียว' : 'สร้าง M4A และ Lyrics') +
          ' · กำลังติดตามสถานะ');
        message('รับคำสั่งสร้างเพลงแล้ว · ตรวจสถานะได้ในขั้นตอนที่ 4', false);
      }
      await loadState();
      if (action !== 'build') $('job-panel').scrollIntoView({behavior:'smooth',block:'nearest'});
      return true;
    } catch (error) {
      if (action === 'build') buildFeedback('error', 'ไม่สามารถเริ่มสร้างเพลงได้', error.message);
      message(error.message);
      return false;
    }
  }
  const selectedIDs = () => [...selected];
  async function startBuild(audioOnly) {
    if (busy) return message('มีงานกำลังดำเนินการอยู่ กรุณารอให้จบก่อน');
    if (!selected.size) {
      buildFeedback('error', 'ยังไม่ได้เลือกเพลงเพื่อสร้าง', 'กรุณากลับไปขั้นตอนที่ 2 แล้วเลือกรายการอย่างน้อยหนึ่งเพลง');
      return message('กรุณาเลือกเพลงก่อนสร้าง');
    }
    try {
      buildFeedback('starting', 'กำลังตรวจสอบไฟล์ต้นฉบับและพื้นที่ว่าง…',
        'ยังไม่เริ่มสร้างไฟล์ · ตรวจสอบรายการที่เลือกอยู่');
      await saveInputs(['create-source','create-soundfont','create-preset','create-mode']);
      const ids = selectedIDs();
      const estimate = await post('/api/estimate', {ids});
      if (!estimate.songs) throw new Error('ไม่พบเพลงที่เลือกในฐานข้อมูล กรุณาสแกนโฟลเดอร์ใหม่และเลือกเพลงอีกครั้ง');
      if (!estimate.enoughDisk) throw new Error('พื้นที่ว่างไม่เพียงพอ กรุณาเปลี่ยนโฟลเดอร์บันทึกหรือเพิ่มพื้นที่ว่าง');
      const formats = Object.entries(estimate.formats || {}).sort((a,b)=>b[1]-a[1])
        .map(([extension,count]) => (extension || 'ไม่มีนามสกุล').toUpperCase() + ' ' + fmtNum(count)).join(' · ');
      if (estimate.unsupported >= estimate.songs) throw new Error(
        'เพลงที่เลือกทั้งหมดเป็น NCN ซึ่ง PC Engine รุ่นนี้ยังแปลงไม่ได้ · กรุณาเลือกเพลงรูปแบบที่รองรับ');
      const warning = (formats ? '\nประเภทไฟล์: ' + formats : '') +
        (estimate.warning ? '\n\n⚠ รายการขนาดใหญ่ โปรแกรมจะสร้างทีละเพลง ไม่คัดลอกต้นฉบับทั้งหมด' : '') +
        (estimate.spaceWarning ? '\n⚠ พื้นที่ว่างอาจไม่พอสำหรับสร้างทุกเพลง หากเต็มจะหยุดรายการที่เหลือและเก็บเพลงที่สำเร็จไว้' : '') +
        (estimate.unsupported ? '\n⚠ มี ' + fmtNum(estimate.unsupported) + ' ไฟล์ NCN ซึ่งยังไม่รองรับ และจะแจ้ง ERR รายเพลง' : '');
      const summary = 'จำนวน ' + fmtNum(estimate.songs) + ' เพลง (' + fmtSize(estimate.bytes) + ')\n' +
        'วิธีสร้าง: ' + (audioOnly ? 'M4A อย่างเดียว' : 'M4A พร้อม Lyrics') +
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
      await run('build', {ids, audio_only:audioOnly});
    } catch (error) {
      buildFeedback('error', 'เริ่มสร้างเพลงไม่ได้', error.message);
      message(error.message);
    }
  }
  async function startUpload({confirmedAfterBuild = false} = {}) {
    // Post-build consent never inherits a manually checked "new library"
    // option: uploads must merge into an existing, accessible Drive catalog.
    if (!googleConnected) return message('กรุณา Google Login ก่อนซิงค์คลังเพลง');
    const createNew = !confirmedAfterBuild && $('upload-create-library').checked === true;
    const details = 'ส่ง M4A + Lyrics JSON ที่พร้อมใช้งานจากคลังในเครื่องไปยัง X-Stage Song Karaoke Online ผ่าน Google Drive ส่วนตัว\n'+
      'ตรวจเพลงซ้ำด้วยรหัสเพลงและ MD5 ของไฟล์จริง · ไม่ลบเพลงเดิม\n'+
      'เพิ่มเฉพาะเพลงใหม่หรือข้อมูลที่แก้ไข และเผยแพร่ current.json หลังตรวจไฟล์ครบแล้ว';
    const warning = createNew
      ? '\n\n⚠ เลือกสร้างคลังใหม่: ยืนยันว่า Google Drive นี้ไม่มีคลัง XStageWeb เดิมที่ต้องใช้ต่อ'
      : '\n\nหากมองไม่เห็นคลังเดิมเพราะสิทธิ์ Google ไม่ครบ ระบบจะหยุดโดยไม่สร้างคลังซ้ำ';
    if (confirmedAfterBuild || await confirmStudio(details + warning, 'ยืนยันเผยแพร่เพลงไปยัง X-Stage Song Karaoke Online')) {
      await run('upload',{create_new_library:createNew});
    }
  }

  async function offerUploadAfterBuild(job) {
    if (job.kind !== 'build' || !['success','error'].includes(job.state)) return;
    const created = Number(job.result?.created || job.created || 0);
    const skipped = Number(job.result?.skipped || job.skipped || 0);
    const errors = Number(job.result?.errors || job.errors || 0);
    // No verified media to publish: leave the build failure in the log.
    if (created + skipped <= 0) return;
    const report = 'สร้างใหม่ ' + fmtNum(created) + ' เพลง · เพลงเดิมที่ตรวจยืนยันแล้ว ' +
      fmtNum(skipped) + ' · ผิดพลาด ' + fmtNum(errors);
    const partial = errors
      ? '\n⚠ บางเพลงสร้างไม่สำเร็จ จะอัปโหลดเฉพาะเพลงในคลังที่ตรวจสอบว่าพร้อมเท่านั้น'
      : '';
    const approved = await confirmStudio(
      report + partial +
      '\n\nต้องการอัปโหลดเพลงที่พร้อมไปยัง X-Stage Song Karaoke Online ตอนนี้หรือไม่?' +
      '\n\nใช้ Google Drive ส่วนตัว · ตรวจเพลงซ้ำก่อนอัปโหลด · ไม่ลบเพลงเดิม' +
      '\nไม่สร้างคลังเพลงใหม่โดยอัตโนมัติ · เลือกยกเลิกเพื่ออัปโหลดภายหลังได้',
      'สร้างเพลงเสร็จแล้ว · อัปโหลดเข้า X-Stage Song Karaoke Online?',
      {acceptLabel:'อัปโหลดตอนนี้', cancelLabel:'ไว้ภายหลัง'}
    );
    if (!approved) {
      message('เก็บเพลงในเครื่องแล้ว · อัปโหลดเข้า X-Stage Song Karaoke Online ภายหลังได้จากเมนูอัปโหลด', false);
      return;
    }
    tab('upload');
    $('upload-create-library').checked = false;
    try {
      // OAuth may have expired while the build was running. Check the local
      // engine's current connection before sending a single song.
      const latest = await api('/api/status');
      setGoogle(latest.google);
      if (!latest.google?.connected) {
        message('เลือกอัปโหลดแล้ว แต่ยังไม่ได้เชื่อม Google Drive · กรุณากด เชื่อม Google แล้วกด เพิ่มเพลงเข้า XStageWeb อีกครั้ง (ยังไม่ได้อัปโหลด)', false);
        $('upload-login').focus();
        return;
      }
      await startUpload({confirmedAfterBuild:true});
    } catch (error) {
      message('ยังไม่ได้เริ่มอัปโหลด: ' + error.message);
    }
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
    $('job-skip-count').textContent = job.kind === 'scan'
      ? (state === 'success'
          ? 'สแกนพบ ' + fmtNum(Number(job.result?.songs ?? job.result?.count ?? job.completed ?? 0)) + ' เพลง · ยังไม่ได้สร้าง M4A/Lyrics'
          : 'ตรวจไฟล์ ' + fmtNum(job.completed || 0) + ' · ยังไม่ได้สร้างเพลง')
      : 'ข้ามซ้ำ ' + fmtNum(Number(job.skipped || 0)) +
        ' · ERR ' + fmtNum(Number(job.errors || 0)) +
        ' · M4A ' + fmtNum(Number(job.m4aCount || 0)) +
        ' · Lyrics ' + fmtNum(Number(job.lyricsCount || 0));
    const fraction = Number(job.total)>0 ? Number(job.completed) / Number(job.total) :
      Number(job.bytesTotal)>0 ? Number(job.bytesDone)/Number(job.bytesTotal) : null;
    const fill = $('progress-fill');
    fill.classList.toggle('indeterminate', isRunning && fraction === null);
    fill.style.width = fraction !== null ? Math.max(0,Math.min(100,100*fraction)).toFixed(1)+'%' : (isRunning?'33%':'0%');
    $('job-fraction').textContent = Number(job.total)>0 ? `${fmtNum(job.completed)} / ${fmtNum(job.total)} รายการ · ${Math.round(fraction*100)}%`:
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
      setGoogle(response.google);
      renderJob(job);updateButtons();
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
            } else if (job.kind === 'ai-recording-save') {
              aiMicPending=false;
              aiMicDiscard();
              $('ai-mic-status').textContent='✓ บันทึก M4A สำเร็จ · เลือกเสียงใหม่ในหน้า AI แล้ว';
              await aiRefreshSongList();
              if(job.result?.song)await aiChooseSong(job.result.song);
              message(job.result?.message||'บันทึกเสียงใหม่สำเร็จ',false);
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
              $('lyric-group-preview-status').textContent=
                'แก้ไขแล้ว · รายการที่ยังไม่แก้คงอยู่ด้านบน เลือกชุดถัดไปได้ทันที';
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
              message(job.result?.message || (job.result?.update ? 'พบเวอร์ชันใหม่: ' + job.result.version : 'ยังไม่มี Installer รุ่นใหม่'), false);
            } else message(job.result?.message || 'ดำเนินการสำเร็จ · '+job.kind, false);
          } else if (job.state === 'error') {
            if(job.kind==='ai-recording-save'){
              aiMicPending=false;
              $('ai-mic-status').textContent=
                'แปลงเสียงไม่สำเร็จ · เสียงที่อัดยังอยู่ในหน้าจอ · ตรวจ Log แล้วลองอีกครั้ง';
              aiUpdateButtons();
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
          } else if (job.state==='cancelled' && job.kind==='ai-recording-save'){
            aiMicPending=false;
            $('ai-mic-status').textContent=
              'ยกเลิกการแปลงเสียง · ไฟล์ที่อัดยังอยู่ในหน้าจอเพื่อทดลองใหม่';
            aiUpdateButtons();
          } else if (job.state==='cancelled' && job.kind==='ai-align') {
            pendingAiAlignment=null;
            $('ai-lyrics-align-review').textContent='ยกเลิกจัดเวลาแล้ว · คำร้องที่วางยังอยู่';
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
      const result = await api('/api/songs/ids?search='+encodeURIComponent(search));
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
  for (const el of document.querySelectorAll('[data-pick]')) el.addEventListener('click',()=>pick(el.dataset.pick).catch(e=>message(e.message)));
  $('verify-code-registry').addEventListener('click',()=>{void verifyCodeRegistry();});
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
  $('build-button').addEventListener('click',()=>{void startBuild(false);});
  $('build-audio-button').addEventListener('click',()=>{void startBuild(true);});
  $('preview-button').addEventListener('click',()=>{void startLivePreview();});
  $('lyric-group-scan').addEventListener('click',()=>{
    if(!busy)void run('lyric-groups-scan');
  });
  $('lyric-group-undo').addEventListener('click',()=>{void phraseUndo();});
  for(const btn of document.querySelectorAll('[data-lyric-position]')){
    btn.addEventListener('click',()=>{
      if(busy)return;
      phrasePosition=btn.dataset.lyricPosition;
      phraseOffset=0;
      // Keep checked groups from the other line positions.
      if(phraseReady)void refreshPhraseGroups();
    });
  }
  $('lyric-group-search').addEventListener('input',()=>{
    clearTimeout(phraseSearchTimer);
    phraseSearchTimer=setTimeout(()=>{
      phraseOffset=0;phraseClearSelection();
      void refreshPhraseGroups();
    },220);
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
    for(const row of phraseRows)phraseSelected.set(row.id,row);
    for(const check of $('lyric-group-results').querySelectorAll('input[data-lyric-group]'))
      check.checked=true;
    phraseUpdateButtons();void phraseRefreshSelection();
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
  $('lyric-group-replacement').addEventListener('input',()=>{
    phraseUpdateButtons();
    clearTimeout(phraseSearchTimer);
    phraseSearchTimer=setTimeout(()=>{void phraseRefreshSelection();},220);
  });
  $('lyric-group-apply').addEventListener('click',()=>{void phraseApply();});
  $('ai-lyrics-import').addEventListener('click',()=>{void aiImportAudio();});
  $('ai-lyrics-separate').addEventListener('click',()=>{void aiSeparateVocals();});
  $('ai-lyrics-use-vocals').addEventListener('change',()=>{
    aiStopPlayback();
    $('ai-lyrics-status').textContent=$('ai-lyrics-use-vocals').checked?
      'ใช้ M4A เสียงร้องแยกสำหรับ Whisper และการทดลองฟัง':
      'ใช้ไฟล์เพลงต้นฉบับสำหรับ Whisper และการทดลองฟัง';
    aiUpdateButtons();
  });
  $('ai-mic-start').addEventListener('click',()=>{void aiStartMic();});
  $('ai-mic-stop').addEventListener('click',aiStopMic);
  $('ai-mic-save').addEventListener('click',()=>{void aiSaveMic();});
  $('ai-mic-discard').addEventListener('click',aiMicDiscard);
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
  $('ai-lyrics-audio').addEventListener('pause',aiStopKaraokeAnimation);
  $('ai-lyrics-audio').addEventListener('ended',()=>{
    aiStopKaraokeAnimation();aiRenderTime();
  });
  $('ai-lyrics-audio').addEventListener('seeked',()=>{aiActiveIndex=-2;aiRenderTime();});
  $('ai-lyrics-insert-time').addEventListener('click',aiInsertTimestamp);
  $('ai-lyrics-download').addEventListener('click',aiDownloadLrc);
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
  updateCreateWizard();
  void initialize();
})();