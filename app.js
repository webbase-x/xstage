/* X-Stage Karaoke Online – single-page private Drive player.
 * Only a short-lived Google access token is kept in sessionStorage until tab close/expiry;
 * songs and catalog data are never persisted by this client. */
'use strict';
const cfg = window.XSTAGE_CONFIG || {};
const $ = id => document.getElementById(id);
const ui = {
  status: $('status'), login: $('login'), gateLogin: $('gate-login'), logout: $('logout'), gate: $('gate'),
  account: $('account'), libraryState: $('library-state'), songTotal: $('song-total'), resultCount: $('result-count'),
  search: $('search'), songs: $('songs'), queue: $('queue'), queueCount: $('queue-count'), clearQueue: $('clear-queue'),
  player: $('player'), stage: $('stage'), stageIdle: $('stage-idle'), stageCode: $('stage-code'),
  nowPlaying: $('now-playing'), nowArtist: $('now-artist'), playStatus: $('play-status'),
  playPause: $('play-pause'), stop: $('stop'), previous: $('previous'), next: $('next'),
  seek: $('seek'), elapsed: $('elapsed'), duration: $('duration'), speed: $('speed'), volume: $('volume'),
  repeat: $('repeat'), fullscreen: $('fullscreen'), lyrics: $('lyrics')
};
const state = {
  token: '', accountSub: '', manifest: null, songs: [], shown: [], selectedIndex: 0,
  queue: [], history: [], current: null, lyrics: null, objectUrl: '',
  requestId: 0, controller: null, authId: 0, loading: false,
  medley: false, medleyCache: null, medleyPrefetch: null,
  medleyUpcoming: null, medleyPoolSource: null, medleyPool: [], medleyRecent: [],
  userStopped: false, visualScale: 1,
  catalogPointerId:'',catalogGeneration:'',catalogPolling:false,catalogCache:new Map()
};
const REMEMBERED_LOGIN_KEY = 'xstage-remembered-google-login';
const ACTIVE_AUTH_KEY = 'xstage-tab-google-token-v1';
const AUTH_EXPIRY_MARGIN_MS = 90_000;
function clearTabAuth(){try{sessionStorage.removeItem(ACTIVE_AUTH_KEY);}catch{/* Blocked by browser settings. */}}
function saveTabAuth(token,expiresAt,sub){
  if(!token||!sub||!(expiresAt>Date.now()+AUTH_EXPIRY_MARGIN_MS))return;
  try{sessionStorage.setItem(ACTIVE_AUTH_KEY,JSON.stringify({token,expiresAt,sub}));}catch{/* Private browsing may block storage. */}
}
function readTabAuth(){
  try{
    const current=JSON.parse(sessionStorage.getItem(ACTIVE_AUTH_KEY)||'null');
    if(current&&typeof current.token==='string'&&current.token.length>25&&
      typeof current.sub==='string'&&current.sub.length>0&&
      Number.isFinite(current.expiresAt)&&current.expiresAt>Date.now()+AUTH_EXPIRY_MARGIN_MS)return current;
  }catch{}
  clearTabAuth();return null;
}
function hasRememberedLogin(){try{return localStorage.getItem(REMEMBERED_LOGIN_KEY)==='1';}catch{return false;}}
function rememberLogin(enabled){try{if(enabled)localStorage.setItem(REMEMBERED_LOGIN_KEY,'1');else localStorage.removeItem(REMEMBERED_LOGIN_KEY);}catch{/* Optional preference only. */}}
const player = ui.player;
player.volume = 0.8;

function setStatus(message, kind = '') {
  ui.status.textContent = message;
  ui.status.className = 'status-line' + (kind ? ' ' + kind : '');
}
function setPlayStatus(message) { ui.playStatus.textContent = message; }
function num(n) { return Number(n).toLocaleString('th-TH'); }
function timeLabel(t) {
  if (!Number.isFinite(t) || t < 0) return '00:00';
  const seconds = Math.floor(t); const h = Math.floor(seconds / 3600);
  const m = String(Math.floor(seconds / 60) % 60).padStart(2, '0');
  const s = String(seconds % 60).padStart(2, '0');
  return h ? `${h}:${m}:${s}` : `${m}:${s}`;
}
function getFileId(data) {
  return typeof data?.fileId === 'string' && data.fileId.length > 0 ? data.fileId : '';
}
function playable(song) { return !!(getFileId(song?.audio) && getFileId(song?.lyrics)); }
function requestHeaders(token) { return { Authorization: `Bearer ${token}` }; }
function driveError(status, subject) {
  if (status === 401) return new Error('สิทธิ์ Google หมดอายุ กรุณาเข้าสู่ระบบอีกครั้ง');
  if (status === 403) return new Error('บัญชีนี้ไม่มีสิทธิ์เข้าถึง ' + subject + ' (ตรวจสิทธิ์ drive.file และบัญชีที่ซิงก์)');
  if (status === 404) return new Error('ไม่พบ ' + subject + ' ใน Google Drive ของบัญชีนี้');
  return new Error(`อ่าน ${subject} ไม่สำเร็จ (HTTP ${status})`);
}
async function driveList(q, token) {
  const params = new URLSearchParams({q,fields:'nextPageToken,files(id,name,mimeType,parents)',pageSize:'1000'});
  const result = await fetch(`https://www.googleapis.com/drive/v3/files?${params}`, {headers: requestHeaders(token),cache:'no-store'});
  if (!result.ok) throw driveError(result.status, 'รายการไฟล์');
  const json = await result.json();
  return Array.isArray(json.files) ? json.files : [];
}
async function privateFile(id, token, opts = {}) {
  const r = await fetch(`https://www.googleapis.com/drive/v3/files/${encodeURIComponent(id)}?alt=media`, {
    headers: requestHeaders(token), cache:'no-store',signal:opts.signal
  });
  if (!r.ok) throw driveError(r.status, 'ไฟล์เพลงส่วนตัว');
  return r;
}
async function privateJson(id, token, opts) {
  const response = await privateFile(id, token, opts);
  try { return await response.json(); }
  catch { throw Error('ไฟล์ JSON บน Drive ไม่ถูกต้อง'); }
}

// The Windows sync publisher switches current.json after each verified batch.
// Older snapshots contain songs[]; newer pointers may include immutable deltas.
// Catalog media URLs remain private and are never exposed outside this account.
async function readPublishedCatalog(pointer,token){
  if(pointer?.schemaVersion!==1 || typeof pointer.catalogFileId!=='string' || !pointer.catalogFileId)
    throw Error('รูปแบบ current.json ไม่รองรับ');
  const deltaIds=pointer.deltaFileIds||[];
  if(!Array.isArray(deltaIds)||deltaIds.length>32||new Set(deltaIds).size!==deltaIds.length)
    throw Error('รายการอัปเดตฐานเพลงบน Drive ไม่ถูกต้อง');
  async function fetchImmutable(id){
    if(typeof id!=='string'||!id)throw Error('ฐานเพลงไม่มี Drive File ID');
    if(state.catalogCache.has(id))return state.catalogCache.get(id);
    const data=await privateJson(id,token);
    state.catalogCache.set(id,data);
    if(state.catalogCache.size>40){
      const oldest=state.catalogCache.keys().next().value;
      state.catalogCache.delete(oldest);
    }
    return data;
  }
  const base=await fetchImmutable(pointer.catalogFileId);
  if(base?.schemaVersion!==1||!Array.isArray(base.songs))
    throw Error('ฐานเพลงหลักบน Drive ไม่รองรับ');
  if(!deltaIds.length){
    if(Number.isSafeInteger(pointer.songCount)&&base.songs.length!==pointer.songCount)
      throw Error('ฐานเพลงชุดนี้มีจำนวนเพลงไม่ตรงกับข้อมูลเผยแพร่');
    return base;
  }
  const songs=new Map();
  for(const song of base.songs){
    if(song && typeof song.webSongId==='string')songs.set(song.webSongId,song);
  }
  for(const id of deltaIds){
    const delta=await fetchImmutable(id);
    if(delta?.schemaVersion!==1 || !Array.isArray(delta.upserts)||!Array.isArray(delta.removes))
      throw Error('ข้อมูลอัปเดตเพลงบางชุดไม่ถูกต้อง');
    for(const key of delta.removes){
      if(typeof key!=='string')throw Error('ข้อมูลลบเพลงไม่ถูกต้อง');
      songs.delete(key);
    }
    for(const song of delta.upserts){
      if(!song || typeof song.webSongId!=='string')throw Error('รายการเพลงที่อัปเดตไม่ถูกต้อง');
      songs.set(song.webSongId,song);
    }
  }
  if(Number.isSafeInteger(pointer.songCount) && songs.size!==pointer.songCount)
    throw Error('จำนวนเพลงที่เผยแพร่บางชุดไม่ตรงกัน กรุณาตรวจการซิงค์');
  return {schemaVersion:1,generation:pointer.generation,songs:[...songs.values()]};
}
async function pollPublishedCatalog(){
  if(!state.token||!state.catalogPointerId||state.catalogPolling)return;
  const authId=state.authId,token=state.token;
  state.catalogPolling=true;
  try{
    const pointer=await privateJson(state.catalogPointerId,token);
    if(authId!==state.authId||state.token!==token||!pointer?.generation||
       pointer.generation===state.catalogGeneration)return;
    const catalog=await readPublishedCatalog(pointer,token);
    if(authId!==state.authId||state.token!==token)return;
    const countBefore=state.songs.length;
    state.manifest=catalog;
    state.songs=catalog.songs.filter(playable);
    state.catalogGeneration=pointer.generation;
    state.medleyPoolSource=null;
    ui.songTotal.textContent=`${num(state.songs.length)} เพลง`;
    renderSongs();renderQueue();
    setStatus(`ฐานเพลงอัปเดตระหว่างซิงค์: ${num(countBefore)} → ${num(state.songs.length)} เพลง`,'success');
  }catch(error){
    // Keep the last known good catalog playable if a batch is unreachable.
    if(state.token===token&&authId===state.authId){
      console.warn('X-Stage catalog refresh:',error?.message||error);
    }
  }finally{state.catalogPolling=false;}
}
setInterval(pollPublishedCatalog,45000);

async function openDrive(token, authId, tokenExpiresAt=0, expectedSub='') {
  if(state.token && state.token!==token)state.catalogCache.clear();
  setStatus('กำลังค้นหาคลัง XStageWeb ใน Google Drive ของคุณ…');
  const roots = (await driveList("name='XStageWeb' and 'root' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",token));
  if (authId !== state.authId) return;
  if (roots.length !== 1) throw Error(roots.length ? 'พบโฟลเดอร์ XStageWeb ซ้ำ กรุณาตรวจใน Drive' : 'ไม่พบโฟลเดอร์ XStageWeb กรุณาซิงก์เพลงจาก X-Stage บน Windows ก่อน');
  const pointers = await driveList(`'${roots[0].id}' in parents and name='current.json' and trashed=false`,token);
  if (pointers.length !== 1) throw Error('ไม่พบ current.json ที่เผยแพร่สำเร็จในคลัง XStageWeb');
  const pointer = await privateJson(pointers[0].id, token);
  const catalog = await readPublishedCatalog(pointer,token);
  const accountResult = await fetch('https://openidconnect.googleapis.com/v1/userinfo', {headers:requestHeaders(token),cache:'no-store'});
  if (!accountResult.ok) throw driveError(accountResult.status,'ข้อมูลบัญชี Google');
  const account = await accountResult.json();
  if (!account.email_verified || !account.sub) throw Error('ไม่สามารถยืนยันบัญชี Google ได้');
  if (expectedSub && account.sub!==expectedSub) throw Error('บัญชี Google ไม่ตรงกับเซสชันเดิม กรุณาเข้าสู่ระบบอีกครั้ง');
  if (authId !== state.authId) return;
  state.token = token;
  state.accountSub = account.sub;
  rememberLogin(true);
  saveTabAuth(token,tokenExpiresAt,account.sub);
  state.manifest = catalog;
  state.catalogPointerId=pointers[0].id;
  state.catalogGeneration=String(pointer.generation||'');
  state.songs = catalog.songs.filter(playable);
  state.selectedIndex = 0;
  ui.account.textContent = account.email || 'Google';
  ui.account.hidden = false;
  ui.logout.hidden = false;
  ui.login.hidden = true;
  ui.gate.hidden = true;
  ui.search.disabled = false;
  ui.libraryState.textContent = 'เข้าถึงเฉพาะคลังส่วนตัวของบัญชีที่ลงชื่อเข้าใช้';
  ui.songTotal.textContent = `${num(state.songs.length)} เพลง`;
  setStatus(`เชื่อมต่อแล้ว · ${num(state.songs.length)} เพลงในคลังส่วนตัว`, 'success');
  renderSongs(); renderQueue();
  ui.search.focus();
}
function login({automatic=false} = {}) {
  if (typeof google === 'undefined' || !google.accounts?.oauth2?.initTokenClient) {
    setStatus('ไม่สามารถโหลด Google Sign-In ได้ กรุณาตรวจอินเทอร์เน็ตและรีเฟรชหน้า', 'error'); return;
  }
  if (!cfg.googleClientId || !String(cfg.googleClientId).endsWith('.apps.googleusercontent.com')) {
    setStatus('ยังไม่ได้กำหนด Google OAuth Web Client ID สำหรับเว็บไซต์นี้', 'error'); return;
  }
  ui.login.disabled = ui.gateLogin.disabled = true;
  setStatus(automatic?'กำลังเชื่อมต่อบัญชี Google ที่เคยใช้…':'กำลังเปิดการอนุญาต Google…');
  const authId = ++state.authId;
  try {
    const client = google.accounts.oauth2.initTokenClient({
      client_id:cfg.googleClientId,
      scope:'openid email https://www.googleapis.com/auth/drive.file',
      callback: async result => {
        if (authId !== state.authId) return;
        ui.login.disabled = ui.gateLogin.disabled = false;
        if (!result?.access_token) { setStatus('กรุณากดเข้าสู่ระบบ Google เพื่อเชื่อมต่ออีกครั้ง', 'error'); return; }
        resetPrivate({revoke:false, keepAuth:true});
        const expiresIn=Number(result.expires_in);
        const expiresAt=Date.now()+Math.max(0,Math.min(3600,Number.isFinite(expiresIn)?expiresIn:3600))*1000;
        try { await openDrive(result.access_token,authId,expiresAt); }
        catch (e) { if (authId === state.authId) {clearTabAuth();resetPrivate({keepAuth:true});setStatus(e.message, 'error');} }
      },
      error_callback: error => {
        if (authId !== state.authId) return;
        ui.login.disabled = ui.gateLogin.disabled = false;
        setStatus(error?.type === 'popup_closed' ? 'ปิดหน้าต่าง Google ก่อนเข้าสู่ระบบ' : 'เข้าสู่ระบบ Google ไม่สำเร็จ', 'error');
      }
    });
    // Do not force Google's consent screen on every login. Google decides when re-consent is required.
    client.requestAccessToken({prompt:''});
  } catch (e) { ui.login.disabled = ui.gateLogin.disabled = false; setStatus(e.message, 'error'); }
}
function resetPrivate({revoke = false, keepAuth = false} = {}) {
  if(revoke){rememberLogin(false);clearTabAuth();}
  if (!keepAuth) state.authId++;
  const oldToken = state.token;
  state.requestId++;
  state.controller?.abort(); state.controller = null; state.loading = false;
  player.pause(); player.removeAttribute('src'); player.load();
  if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
  state.objectUrl = ''; state.token = ''; state.accountSub = ''; state.manifest = null;
  state.songs = [];state.shown = [];state.queue = [];state.history = [];
  state.catalogPointerId='';state.catalogGeneration='';state.catalogCache.clear();
  state.medleyCache=null;state.medleyPrefetch=null;state.medleyUpcoming=null;
  state.medleyPoolSource=null;state.medleyPool=[];state.medleyRecent=[];state.userStopped=false;
  state.current = null;state.lyrics = null;state.selectedIndex = 0;
  ui.account.textContent = '';ui.account.hidden = true;ui.logout.hidden = true;ui.login.hidden = false;
  ui.gate.hidden = false;ui.search.disabled = true;ui.search.value = '';
  ui.songTotal.textContent = '0 เพลง';ui.resultCount.textContent = 'กรุณาเข้าสู่ระบบ';
  ui.libraryState.textContent = 'คลังส่วนตัว · ไม่มีการเผยแพร่เพลงสาธารณะ';
  ui.nowPlaying.textContent = 'ยังไม่ได้เลือกเพลง';ui.nowArtist.textContent='X-Stage Karaoke Online';ui.stageCode.textContent='—';
  ui.stage.classList.remove('playing');ui.stageIdle.hidden = false;
  setPlayStatus(''); updateTransport();renderSongs();renderQueue();
  if (revoke && oldToken && typeof google !== 'undefined') {
    try { google.accounts.oauth2.revoke(oldToken,()=>{}); } catch { /* session is already cleared */ }
  }
}

function songIdentity(song) { return String(song?.webSongId || `${song?.code}:${song?.title}:${song?.artist}`); }
function element(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}
function control(label,handler,title = label) {
  const b = element('button','',label); b.type='button';b.title=title;b.setAttribute('aria-label',title);
  b.addEventListener('click',handler);return b;
}
function renderMatchedText(node, value, term) {
  const raw=String(value ?? '');
  const hit=term ? raw.toLocaleLowerCase('th').indexOf(term) : -1;
  if(hit<0){node.textContent=raw;return;}
  node.append(document.createTextNode(raw.slice(0,hit)));
  const match=document.createElement('mark');
  match.className='song-match';
  match.textContent=raw.slice(hit,hit+term.length);
  node.append(match,document.createTextNode(raw.slice(hit+term.length)));
}
function renderSongs() {
  ui.songs.replaceChildren();
  if (!state.token) {
    ui.search.removeAttribute('aria-activedescendant');
    ui.songs.append(element('div','empty-state','เพลงจาก Google Drive ของคุณจะแสดงที่นี่'));
    return;
  }
  const term = ui.search.value.trim().toLocaleLowerCase('th');
  if(!term){
    // Empty search is not a request to list the complete private catalog.
    state.shown=[];state.selectedIndex=0;
    ui.resultCount.textContent='พิมพ์เพื่อค้นหาเพลง';
    ui.search.removeAttribute('aria-activedescendant');
    return;
  }
  const matches = state.songs.filter(song =>
    [song.code,song.title,song.artist].some(v => String(v || '').toLocaleLowerCase('th').includes(term)));
  state.shown = matches.slice(0,120);
  state.selectedIndex = Math.max(0,Math.min(state.selectedIndex,state.shown.length - 1));
  ui.resultCount.textContent = `พบ ${num(matches.length)} เพลง${matches.length>120?' · แสดง 120 รายการแรก':''}`;
  if (!state.shown.length) {
    ui.search.removeAttribute('aria-activedescendant');
    ui.songs.append(element('div','empty-state',term?'ไม่พบเพลงที่ค้นหา':'ยังไม่มีเพลงที่พร้อมเล่น'));return;
  }
  const fragment = document.createDocumentFragment();
  state.shown.forEach((song,i) => {
    const row=element('div','song-item'+(i===state.selectedIndex?' selected':''));
    row.role='option';row.id='song-option-'+i;row.setAttribute('aria-selected',String(i===state.selectedIndex));
    row.tabIndex = -1;row.title='คลิกเลือก · ดับเบิลคลิกเล่นทันที';
    const details=element('div','song-details');
    const code=element('div','song-code'),title=element('strong'),artist=element('small');
    renderMatchedText(code,song.code||'—',term);
    renderMatchedText(title,song.title||'ไม่ระบุชื่อเพลง',term);
    renderMatchedText(artist,song.artist||'ไม่ระบุศิลปิน',term);
    details.append(code,title,artist);
    const add=element('button','song-add','+');add.type='button';add.title='เพิ่มเพลงเข้าคิว';add.setAttribute('aria-label','เพิ่มเพลง '+(song.title||'')+' เข้าคิว');
    add.addEventListener('click',e=>{e.stopPropagation();selectSong(i,false);addToQueue(song);});
    row.append(details,add);
    row.addEventListener('click',()=>selectSong(i,false));
    row.addEventListener('dblclick',()=>playSong(song));
    fragment.append(row);
  });
  ui.songs.append(fragment);
  if(state.shown.length)ui.search.setAttribute('aria-activedescendant','song-option-'+state.selectedIndex);
  else ui.search.removeAttribute('aria-activedescendant');
}
function selectSong(i,scroll=true) {
  if (i<0||i>=state.shown.length) return;
  state.selectedIndex = i;
  for (const [j,row] of [...ui.songs.querySelectorAll('.song-item')].entries()) {
    row.classList.toggle('selected',i===j);row.setAttribute('aria-selected',String(i===j));
    if(i===j){ui.search.setAttribute('aria-activedescendant',row.id);if(scroll)row.scrollIntoView({block:'nearest'});}
  }
}
// X-Stage medley means shuffled, continuous music from the private M4A
// catalog. Requested songs in the queue always take priority over random songs.
// The next file is prepared in memory, but songs are never cached permanently.
const MEDLEY_RECENT_LIMIT=10;
function medleyPool(){
  if(state.medleyPoolSource!==state.songs){
    state.medleyPoolSource=state.songs;
    state.medleyPool=state.songs.filter(playable);
  }
  return state.medleyPool;
}
function randomMedleySong(){
  const pool=medleyPool();
  if(!pool.length)return null;
  const recent=new Set([state.current,...(state.medleyRecent||[])]);
  let candidate=pool[Math.floor(Math.random()*pool.length)];
  // Avoid repeating the active or recently played song when the library allows.
  if(pool.length>recent.size){
    for(let i=0;i<35&&recent.has(candidate);i++)
      candidate=pool[Math.floor(Math.random()*pool.length)];
    if(recent.has(candidate))candidate=pool.find(song=>!recent.has(song))||candidate;
  }else if(pool.length>1&&candidate===state.current){
    for(let i=0;i<20&&candidate===state.current;i++)
      candidate=pool[Math.floor(Math.random()*pool.length)];
  }
  return candidate;
}
function nextMedleyCandidate(){
  if(state.queue.length)return state.queue[0];
  if(!state.medley)return null;
  if(!state.medleyUpcoming||state.medleyUpcoming===state.current)
    state.medleyUpcoming=randomMedleySong();
  return state.medleyUpcoming;
}
function setMedleyMode(enabled){
  state.medley=!!enabled;
  if(state.medley&&ui.repeat.checked){
    ui.repeat.checked=false;
    ui.repeat.dispatchEvent(new Event('change',{bubbles:true}));
  }
  if(!state.medley){
    state.medleyCache=null;state.medleyPrefetch=null;state.medleyUpcoming=null;
    player.volume=Number(ui.volume.value)/100;
  }
  setPlayStatus(state.medley
    ?'เปิดเมดเลย์สุ่มเพลงต่อเนื่อง · เพลงที่ขอในคิวจะเล่นก่อน'
    :'ปิดเมดเลย์สุ่มเพลง');
  window.dispatchEvent(new CustomEvent('xstage:medleychange',
    {detail:{enabled:state.medley}}));
  // Start medley only when the player is genuinely idle; do not cut a paused song.
  if(state.medley&&state.token&&!state.loading&&
    (!state.current||!player.src||player.ended||state.userStopped)){
    state.userStopped=false;
    playNext();
  }
  return state.medley;
}
function setStageVisualScale(value){
  state.visualScale=Math.max(.7,Math.min(1.35,Math.round(Number(value)*100)/100));
  ui.stage.style.setProperty('--xstage-visual-scale',String(state.visualScale));
  return state.visualScale;
}
function prefetchMedleyNext(){
  if(!state.medley||!state.token||state.loading)return;
  const song=nextMedleyCandidate(),token=state.token;
  if(!song||state.medleyCache?.song===song||state.medleyPrefetch?.song===song)return;
  const task={song,token};state.medleyPrefetch=task;
  Promise.all([privateFile(song.audio.fileId,token),privateJson(song.lyrics.fileId,token)])
    .then(async ([response,lyrics])=>{
      const blob=await response.blob();
      if(state.medleyPrefetch!==task||!state.medley||state.token!==token||
          nextMedleyCandidate()!==song)return;
      if(!blob.size||lyrics?.schemaVersion!==1||!Array.isArray(lyrics.lines))return;
      state.medleyCache={song,blob,lyrics};
    })
    .catch(()=>{/* Playback falls back to loading the next song normally. */})
    .finally(()=>{if(state.medleyPrefetch===task)state.medleyPrefetch=null;});
}
function medleyTick(){
  if(!state.medley||state.loading||player.paused)return;
  const duration=player.duration;
  if(!Number.isFinite(duration)||duration<=0)return;
  // Keep the entire track; start the next random/queued song on the ended event.
  if(duration-player.currentTime<=25)prefetchMedleyNext();
}
function addToQueue(song) {
  if (!playable(song)) return;
  state.queue.push(song);renderQueue();setPlayStatus(`เพิ่มเข้าคิว: ${song.title||song.code}`);
}
function renderQueue() {
  ui.queue.replaceChildren();ui.queueCount.textContent=String(state.queue.length);
  ui.clearQueue.disabled=!state.queue.length;
  ui.next.disabled=!state.queue.length;
  ui.previous.disabled=!state.history.length;
  if (!state.queue.length) {ui.queue.append(element('li','empty-state','ยังไม่มีเพลงในคิว'));return;}
  state.queue.forEach((song,i)=>{
    const item=element('li','queue-item');
    const info=element('div','queue-info');info.append(element('strong','',song.title||'ไม่ระบุชื่อเพลง'),element('small','',song.artist||song.code||''));
    const buttons=element('div','queue-controls');
    const up=control('↑',()=>moveQueue(i,-1),'เลื่อนขึ้น');up.disabled=i===0;
    const down=control('↓',()=>moveQueue(i,1),'เลื่อนลง');down.disabled=i===state.queue.length-1;
    const remove=control('×',()=>{state.queue.splice(i,1);renderQueue();},'นำออกจากคิว');
    buttons.append(up,down,remove);
    const n=element('span','queue-number',String(i+1));
    item.append(n,info,buttons);item.title='คลิกสองครั้งเพื่อเล่นเพลงนี้ทันที';
    item.addEventListener('dblclick',e=>{if(e.target.closest('button'))return;state.queue.splice(i,1);renderQueue();playSong(song);});
    ui.queue.append(item);
  });
}
function moveQueue(index,step){const target=index+step;if(target<0||target>=state.queue.length)return;[state.queue[index],state.queue[target]]=[state.queue[target],state.queue[index]];renderQueue();}
function playNext(){
  const queued=state.queue.shift();
  const song=queued||(state.medley?nextMedleyCandidate():null);
  if(!queued)state.medleyUpcoming=null;
  state.userStopped=false;
  if(state.medleyCache&&state.medleyCache.song!==song)state.medleyCache=null;
  renderQueue();
  if(song){
    if(state.medley){
      state.medleyRecent.push(song);
      if(state.medleyRecent.length>MEDLEY_RECENT_LIMIT)state.medleyRecent.shift();
    }
    playSong(song);
  }else{
    setPlayStatus('จบเพลงแล้ว · ไม่มีเพลงรอในคิว');
    updateTransport();
  }
}
function stopSong(){state.userStopped=true;state.requestId++;state.controller?.abort();state.loading=false;player.pause();if(player.seekable?.length||player.readyState)player.currentTime=0;setPlayStatus('หยุดเล่นแล้ว');updateTransport();}
function togglePlayback(){if(state.loading)return;if(!player.src){if(state.queue.length)playNext();else if(state.shown.length)playSong(state.shown[state.selectedIndex]);return;}if(player.paused){player.play().catch(()=>setPlayStatus('เบราว์เซอร์ไม่อนุญาตให้เริ่มเสียง กรุณากดเล่นอีกครั้ง'));}else player.pause();}

async function playSong(song,{remember=true}={}) {
  state.userStopped=false;
  if (!state.token) {setStatus('กรุณาเข้าสู่ระบบ Google ก่อนเล่นเพลง','error');return;}
  if (!playable(song)) {setPlayStatus('เพลงนี้ยังไม่มี M4A/JSON ที่พร้อมเล่น');return;}
  const request=++state.requestId;
  state.controller?.abort();const controller=new AbortController();state.controller=controller;
  const token=state.token;
  state.loading=true;updateTransport();setPlayStatus('กำลังโหลดเพลงและเนื้อร้องจาก Drive ส่วนตัว…');
  try {
    const prepared=state.medleyCache?.song===song&&state.token===token ? state.medleyCache : null;
    if(prepared)state.medleyCache=null;
    const [audio,lyrics]=prepared
      ? [prepared.blob,prepared.lyrics]
      : await Promise.all([
          privateFile(song.audio.fileId,token,{signal:controller.signal}).then(r=>r.blob()),
          privateJson(song.lyrics.fileId,token,{signal:controller.signal})
        ]);
    if (lyrics?.schemaVersion !== 1 || !Array.isArray(lyrics.lines)) throw Error('ไฟล์ Lyrics JSON ไม่รองรับ');
    if (request!==state.requestId||token!==state.token)return;
    if (!audio.size)throw Error('ไฟล์เสียงว่างเปล่า');
    const url=URL.createObjectURL(audio);
    if (remember && state.current)state.history.push(state.current);
    player.pause();if(state.objectUrl)URL.revokeObjectURL(state.objectUrl);
    state.objectUrl=url;state.current=song;state.lyrics=lyrics;
    ui.nowPlaying.textContent=song.title||'ไม่ระบุชื่อเพลง';ui.nowArtist.textContent=song.artist||'ไม่ระบุศิลปิน';
    ui.stageCode.textContent=song.code||'—';ui.stage.classList.add('playing');ui.stageIdle.hidden=true;
    player.src=url;player.playbackRate=Number(ui.speed.value);player.loop=ui.repeat.checked;
    player.volume=Number(ui.volume.value)/100;
    state.loading=false;renderQueue();updateTransport();
    try{await player.play();if(request===state.requestId)setPlayStatus('กำลังเล่น · '+(song.title||song.code));}
    catch{if(request===state.requestId)setPlayStatus('เพลงพร้อมแล้ว · กด ▶ เพื่อเริ่มเล่น');}
  }catch(e){if(request!==state.requestId || e.name==='AbortError')return;setPlayStatus(e.message||'ไม่สามารถเล่นเพลงได้');state.loading=false;updateTransport();}
  finally{if(request===state.requestId){state.loading=false;state.controller=null;updateTransport();}}
}
function updateTransport(){
  ui.playPause.disabled=state.loading||(!state.current&&!state.queue.length&&!state.shown.length);
  ui.playPause.textContent=player.src&&!player.paused?'Ⅱ':'▶';
  ui.stop.disabled=!state.current&&!state.loading;
  ui.previous.disabled=!state.history.length;
  ui.next.disabled=!state.queue.length;
  const duration=Number.isFinite(player.duration)?player.duration:Number(state.current?.duration||0);
  ui.elapsed.textContent=timeLabel(player.currentTime);
  ui.duration.textContent=timeLabel(duration);
  ui.seek.disabled=!(duration>0&&state.current);
  if (!ui.seek.matches(':active'))ui.seek.value=duration>0?String(Math.round((player.currentTime/duration)*1000)):'0';
}
function onSearchKey(e){
  if(e.key==='ArrowDown'){e.preventDefault();if(state.shown.length)selectSong(Math.min(state.selectedIndex+1,state.shown.length-1));}
  else if(e.key==='ArrowUp'){e.preventDefault();if(state.shown.length)selectSong(Math.max(0,state.selectedIndex-1));}
  else if(e.key==='Enter'){e.preventDefault();const song=state.shown[state.selectedIndex];if(!song)return;
    if(state.current||state.loading)addToQueue(song);else playSong(song);
  }
}

// Draw timed karaoke lyrics on the same stage as the Windows player's background.
const pen=ui.lyrics.getContext('2d');
const graphemeCount = s => {
  if (typeof Intl.Segmenter === 'function') return [...new Intl.Segmenter('th',{granularity:'grapheme'}).segment(s)].length;
  return Array.from(s).length;
};
function resizeCanvas(){
  const r=ui.lyrics.getBoundingClientRect();
  if(!r.width||!r.height)return {w:0,h:0};
  const dpr=Math.min(window.devicePixelRatio||1,2),w=Math.round(r.width*dpr),h=Math.round(r.height*dpr);
  if(ui.lyrics.width!==w||ui.lyrics.height!==h){ui.lyrics.width=w;ui.lyrics.height=h;}
  return {w,h};
}
function drawLine(text,y,maxWidth,fontSize,fill,progress=null,centerX=ui.lyrics.width/2){
  if(!text)return;
  const w=ui.lyrics.width;
  let sz=fontSize;
  do {pen.font=`900 ${Math.round(sz)}px "Leelawadee UI","Noto Sans Thai",Tahoma,sans-serif`;if(pen.measureText(text).width<=maxWidth)break;sz*=.92;}while(sz>14);
  pen.textAlign='center';pen.textBaseline='middle';
  pen.lineWidth=Math.max(3,sz*.13);pen.strokeStyle='#010613';pen.lineJoin='round';pen.shadowColor='#000';pen.shadowBlur=6;
  // Canvas maxWidth keeps the entire text inside the reserved region even
  // when its Thai glyphs cannot shrink further (e.g. QR beside lyrics).
  const displayedWidth=Math.min(pen.measureText(text).width,maxWidth);
  pen.strokeText(text,centerX,y,maxWidth);pen.shadowBlur=0;pen.fillStyle=fill;pen.fillText(text,centerX,y,maxWidth);
  if(progress!==null){pen.save();pen.beginPath();pen.rect(centerX-displayedWidth/2-1,y-sz*.8,Math.max(0,Math.min(1,progress))*displayedWidth+1,sz*1.65);pen.clip();pen.fillStyle='#ffd76a';pen.fillText(text,centerX,y,maxWidth);pen.restore();}
}
function lineProgress(line,when){
  const units=Array.isArray(line.syllables)?line.syllables:[];
  if(!units.length){const start=Number(line.startTime)||0,end=Number(line.endTime)||start+1;return Math.min(1,Math.max(0,(when-start)/Math.max(.01,end-start)));}
  let total=0,lit=0;
  for(const u of units){const width=graphemeCount(String(u.text||'')),start=Number(u.start)||0,duration=Number(u.duration)||0;
    total+=width;lit+=width*Math.max(0,Math.min(1,duration>0?(when-start)/duration:(when>=start?1:0)));}
  return total?lit/total:0;
}
function drawLyrics(){
  try {
    const {w,h}=resizeCanvas();
    if(w&&h){pen.clearRect(0,0,w,h);
      if(state.lyrics?.lines?.length && state.current){
        const when=Math.max(0,player.currentTime+(Number(state.lyrics.audioOffsetMs)||0)/1000);
        const lines=state.lyrics.lines;
        let idx=-1;
        for(let i=0;i<lines.length;i++){if(Number(lines[i].startTime)<=when)idx=i;else break;}
        const fontSize=Math.min(61,w*.055,h*.115);
        // Keep both lyric lines above the integrated transport/virtual keyboard.
        const density=Math.min(window.devicePixelRatio||1,2);
        const transportHeight=ui.stage.querySelector('.transport-panel')?.getBoundingClientRect().height||0;
        const keyboard=ui.stage.querySelector('#virtual-keyboard');
        const keyboardHeight=keyboard&&!keyboard.hidden?keyboard.getBoundingClientRect().height+7:0;
        const usableBottom=h-(transportHeight+keyboardHeight+12)*density;
        let nextY=Math.max(h*.33,Math.min(h*.83,usableBottom-fontSize*.8));
        let currentY=Math.max(h*.19,Math.min(h*.66,nextY-fontSize*1.45));
        let lyricCenter=w/2,lyricWidth=w*.93,lyricFont=fontSize*state.visualScale;
        const qrPanel=ui.stage.querySelector('#remote-pair-panel');
        if(qrPanel&&!qrPanel.hidden){
          const canvasBox=ui.lyrics.getBoundingClientRect();
          const qrBox=qrPanel.getBoundingClientRect();
          const scale=w/Math.max(1,canvasBox.width);
          const qrTop=(qrBox.top-canvasBox.top)*scale;
          const qrBottom=(qrBox.bottom-canvasBox.top)*scale;
          if(qrTop<nextY+fontSize*.8 && qrBottom>currentY-fontSize*.8){
            // Prefer drawing below QR; on short landscape screens reserve the space to its left.
            const afterCurrent=qrBottom+fontSize*.95;
            const afterNext=afterCurrent+fontSize*1.5;
            if(afterNext+fontSize*.7<usableBottom){
              currentY=afterCurrent;nextY=afterNext;
            }else{
              const openWidth=Math.max(0,(qrBox.left-canvasBox.left)*scale-14*scale);
              if(openWidth>w*.28){
                lyricCenter=openWidth/2;
                lyricWidth=openWidth*.94;
                lyricFont=Math.min(fontSize,Math.max(12,openWidth*.075));
              }
            }
          }
        }
        if(idx<0){drawLine(String(lines[0].text||''),Math.min(h*.72,currentY),lyricWidth,lyricFont,'#bfe2ef',null,lyricCenter);}
        else{
          const current=lines[idx];drawLine(String(current.text||''),currentY,lyricWidth,lyricFont,'#ecf7ff',lineProgress(current,when),lyricCenter);
          const next=lines[idx+1];if(next)drawLine(String(next.text||''),nextY,lyricWidth,lyricFont*.77,'#b7d2e0',null,lyricCenter);
        }
      }
    }
  }catch(e){/* Preserve audio playback even if a malformed lyric line cannot draw. */}
  requestAnimationFrame(drawLyrics);
}

// The stage clock runs independently in index.html.
ui.login.addEventListener('click',()=>login());ui.gateLogin.addEventListener('click',()=>login());
ui.logout.addEventListener('click',()=>{resetPrivate({revoke:true});setStatus('ออกจากระบบแล้ว · ข้อมูลเพลงส่วนตัวถูกล้างจากหน้าเว็บ');});
ui.search.addEventListener('input',()=>{state.selectedIndex=0;renderSongs();});
ui.search.addEventListener('keydown',onSearchKey);
ui.clearQueue.addEventListener('click',()=>{state.queue.length=0;renderQueue();setPlayStatus('ล้างคิวแล้ว');});
ui.playPause.addEventListener('click',togglePlayback);
ui.stop.addEventListener('click',stopSong);
ui.previous.addEventListener('click',()=>{const old=state.history.pop();renderQueue();if(old)playSong(old,{remember:false});});
ui.next.addEventListener('click',playNext);
ui.speed.addEventListener('change',()=>{player.playbackRate=Number(ui.speed.value);});
ui.volume.addEventListener('input',()=>{player.volume=Number(ui.volume.value)/100;});
ui.repeat.addEventListener('change',()=>{player.loop=ui.repeat.checked;});
ui.seek.addEventListener('input',()=>{const d=Number.isFinite(player.duration)?player.duration:Number(state.current?.duration)||0;if(d>0)player.currentTime=d*Number(ui.seek.value)/1000;updateTransport();});
ui.fullscreen.addEventListener('click',async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await ui.stage.requestFullscreen();}catch{setPlayStatus('อุปกรณ์นี้ไม่รองรับการแสดงเต็มหน้าจอ');}});
player.addEventListener('timeupdate',updateTransport);player.addEventListener('timeupdate',medleyTick);player.addEventListener('loadedmetadata',updateTransport);
player.addEventListener('durationchange',updateTransport);player.addEventListener('play',updateTransport);
player.addEventListener('pause',updateTransport);player.addEventListener('ended',()=>{if(!player.loop)playNext();});
player.addEventListener('error',()=>{if(state.current)setPlayStatus('ไม่สามารถถอดรหัสไฟล์เสียงนี้ในเบราว์เซอร์ได้');});
document.addEventListener('keydown',e=>{
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='f'&&state.token){e.preventDefault();ui.search.focus();ui.search.select();return;}
  if(['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName))return;
  if(e.key==='F5'){e.preventDefault();togglePlayback();}
  if(e.key==='F6'){e.preventDefault();playNext();}
  if(e.key==='F8'){e.preventDefault();stopSong();}
  if(e.key==='Escape'&&document.fullscreenElement){document.exitFullscreen();}
});
window.addEventListener('beforeunload',()=>{state.controller?.abort();if(state.objectUrl)URL.revokeObjectURL(state.objectUrl);});
renderSongs();renderQueue();updateTransport();requestAnimationFrame(drawLyrics);
// Restore only an unexpired token in the current browser tab. Token-model reauthorization
// requires a user gesture after expiry; never open an unprompted OAuth popup on reload.
(function restoreTabSession(){
  const saved=readTabAuth();
  if(!saved){
    if(hasRememberedLogin())setStatus('เคยเข้าสู่ระบบแล้ว · กรุณากดเชื่อมต่อ Google เมื่อเซสชันหมดอายุ');
    return;
  }
  ui.gate.hidden=true;
  ui.login.disabled=ui.gateLogin.disabled=true;
  setStatus('กำลังตรวจสอบเซสชัน Google เดิม…');
  const id=++state.authId;
  openDrive(saved.token,id,saved.expiresAt,saved.sub).catch(error=>{
    if(id!==state.authId)return;
    clearTabAuth();
    resetPrivate({keepAuth:true});
    setStatus('เซสชันหมดอายุหรือเข้าถึงคลังไม่ได้: '+error.message,'error');
  }).finally(()=>{
    if(id===state.authId)ui.login.disabled=ui.gateLogin.disabled=false;
  });
})();
