/* X-Stage Karaoke Online – single-page private Drive player.
 * No song content, credentials, or tokens are persisted by this client. */
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
  requestId: 0, controller: null, authId: 0, loading: false
};
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

async function openDrive(token, authId) {
  setStatus('กำลังค้นหาคลัง XStageWeb ใน Google Drive ของคุณ…');
  const roots = (await driveList("name='XStageWeb' and 'root' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",token));
  if (authId !== state.authId) return;
  if (roots.length !== 1) throw Error(roots.length ? 'พบโฟลเดอร์ XStageWeb ซ้ำ กรุณาตรวจใน Drive' : 'ไม่พบโฟลเดอร์ XStageWeb กรุณาซิงก์เพลงจาก X-Stage บน Windows ก่อน');
  const pointers = await driveList(`'${roots[0].id}' in parents and name='current.json' and trashed=false`,token);
  if (pointers.length !== 1) throw Error('ไม่พบ current.json ที่เผยแพร่สำเร็จในคลัง XStageWeb');
  const pointer = await privateJson(pointers[0].id, token);
  if (pointer?.schemaVersion !== 1 || !getFileId({fileId:pointer.catalogFileId})) throw Error('รูปแบบ current.json ไม่รองรับ');
  const catalog = await privateJson(pointer.catalogFileId, token);
  if (catalog?.schemaVersion !== 1 || !Array.isArray(catalog.songs)) throw Error('รูปแบบฐานข้อมูลเพลงไม่รองรับ');
  const accountResult = await fetch('https://openidconnect.googleapis.com/v1/userinfo', {headers:requestHeaders(token),cache:'no-store'});
  if (!accountResult.ok) throw driveError(accountResult.status,'ข้อมูลบัญชี Google');
  const account = await accountResult.json();
  if (!account.email_verified || !account.sub) throw Error('ไม่สามารถยืนยันบัญชี Google ได้');
  if (authId !== state.authId) return;
  state.token = token;
  state.accountSub = account.sub;
  state.manifest = catalog;
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
function login() {
  if (typeof google === 'undefined' || !google.accounts?.oauth2?.initTokenClient) {
    setStatus('ไม่สามารถโหลด Google Sign-In ได้ กรุณาตรวจอินเทอร์เน็ตและรีเฟรชหน้า', 'error'); return;
  }
  if (!cfg.googleClientId || !String(cfg.googleClientId).endsWith('.apps.googleusercontent.com')) {
    setStatus('ยังไม่ได้กำหนด Google OAuth Web Client ID สำหรับเว็บไซต์นี้', 'error'); return;
  }
  ui.login.disabled = ui.gateLogin.disabled = true;
  setStatus('กำลังเปิดการอนุญาต Google…');
  const authId = ++state.authId;
  try {
    const client = google.accounts.oauth2.initTokenClient({
      client_id:cfg.googleClientId,
      scope:'openid email https://www.googleapis.com/auth/drive.file',
      callback: async result => {
        if (authId !== state.authId) return;
        ui.login.disabled = ui.gateLogin.disabled = false;
        if (!result?.access_token) { setStatus('ไม่ได้รับสิทธิ์จาก Google กรุณาลองเข้าสู่ระบบใหม่', 'error'); return; }
        resetPrivate({revoke:false, keepAuth:true});
        try { await openDrive(result.access_token,authId); }
        catch (e) { if (authId === state.authId) setStatus(e.message, 'error'); }
      },
      error_callback: error => {
        if (authId !== state.authId) return;
        ui.login.disabled = ui.gateLogin.disabled = false;
        setStatus(error?.type === 'popup_closed' ? 'ปิดหน้าต่าง Google ก่อนเข้าสู่ระบบ' : 'เข้าสู่ระบบ Google ไม่สำเร็จ', 'error');
      }
    });
    client.requestAccessToken({prompt:'consent'});
  } catch (e) { ui.login.disabled = ui.gateLogin.disabled = false; setStatus(e.message, 'error'); }
}
function resetPrivate({revoke = false, keepAuth = false} = {}) {
  if (!keepAuth) state.authId++;
  const oldToken = state.token;
  state.requestId++;
  state.controller?.abort(); state.controller = null; state.loading = false;
  player.pause(); player.removeAttribute('src'); player.load();
  if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
  state.objectUrl = ''; state.token = ''; state.accountSub = ''; state.manifest = null;
  state.songs = [];state.shown = [];state.queue = [];state.history = [];
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
function renderSongs() {
  ui.songs.replaceChildren();
  if (!state.token) {
    ui.songs.append(element('div','empty-state','เพลงจาก Google Drive ของคุณจะแสดงที่นี่'));
    return;
  }
  const term = ui.search.value.trim().toLocaleLowerCase('th');
  const matches = state.songs.filter(song =>
    [song.code,song.title,song.artist].some(v => String(v || '').toLocaleLowerCase('th').includes(term)));
  state.shown = matches.slice(0,120);
  state.selectedIndex = Math.max(0,Math.min(state.selectedIndex,state.shown.length - 1));
  ui.resultCount.textContent = `พบ ${num(matches.length)} เพลง${matches.length>120?' · แสดง 120 รายการแรก':''}`;
  if (!state.shown.length) {
    ui.songs.append(element('div','empty-state',term?'ไม่พบเพลงที่ค้นหา':'ยังไม่มีเพลงที่พร้อมเล่น'));return;
  }
  const fragment = document.createDocumentFragment();
  state.shown.forEach((song,i) => {
    const row=element('div','song-item'+(i===state.selectedIndex?' selected':''));
    row.role='option';row.setAttribute('aria-selected',String(i===state.selectedIndex));
    row.tabIndex = -1;row.title='คลิกเลือก · ดับเบิลคลิกเล่นทันที';
    const details=element('div','song-details');
    details.append(element('div','song-code',String(song.code||'—')),
      element('strong','',song.title||'ไม่ระบุชื่อเพลง'),element('small','',song.artist||'ไม่ระบุศิลปิน'));
    const add=element('button','song-add','+');add.type='button';add.title='เพิ่มเพลงเข้าคิว';add.setAttribute('aria-label','เพิ่มเพลง '+(song.title||'')+' เข้าคิว');
    add.addEventListener('click',e=>{e.stopPropagation();selectSong(i,false);addToQueue(song);});
    row.append(details,add);
    row.addEventListener('click',()=>selectSong(i,false));
    row.addEventListener('dblclick',()=>playSong(song));
    fragment.append(row);
  });
  ui.songs.append(fragment);
}
function selectSong(i,scroll=true) {
  if (i<0||i>=state.shown.length) return;
  state.selectedIndex = i;
  for (const [j,row] of [...ui.songs.querySelectorAll('.song-item')].entries()) {
    row.classList.toggle('selected',i===j);row.setAttribute('aria-selected',String(i===j));
    if (scroll && i===j) row.scrollIntoView({block:'nearest'});
  }
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
function playNext(){const song=state.queue.shift();renderQueue();if(song)playSong(song);else{setPlayStatus('จบเพลงแล้ว · ไม่มีเพลงรอในคิว');updateTransport();}}
function stopSong(){state.requestId++;state.controller?.abort();state.loading=false;player.pause();if(player.seekable?.length||player.readyState)player.currentTime=0;setPlayStatus('หยุดเล่นแล้ว');updateTransport();}
function togglePlayback(){if(state.loading)return;if(!player.src){if(state.queue.length)playNext();else if(state.shown.length)playSong(state.shown[state.selectedIndex]);return;}if(player.paused){player.play().catch(()=>setPlayStatus('เบราว์เซอร์ไม่อนุญาตให้เริ่มเสียง กรุณากดเล่นอีกครั้ง'));}else player.pause();}

async function playSong(song,{remember=true}={}) {
  if (!state.token) {setStatus('กรุณาเข้าสู่ระบบ Google ก่อนเล่นเพลง','error');return;}
  if (!playable(song)) {setPlayStatus('เพลงนี้ยังไม่มี M4A/JSON ที่พร้อมเล่น');return;}
  const request=++state.requestId;
  state.controller?.abort();const controller=new AbortController();state.controller=controller;
  const token=state.token;
  state.loading=true;updateTransport();setPlayStatus('กำลังโหลดเพลงและเนื้อร้องจาก Drive ส่วนตัว…');
  try {
    const [audioResponse,lyrics]=await Promise.all([
      privateFile(song.audio.fileId,token,{signal:controller.signal}),
      privateJson(song.lyrics.fileId,token,{signal:controller.signal})
    ]);
    if (lyrics?.schemaVersion !== 1 || !Array.isArray(lyrics.lines)) throw Error('ไฟล์ Lyrics JSON ไม่รองรับ');
    const audio=await audioResponse.blob();
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
  if(e.key==='ArrowDown'){e.preventDefault();selectSong(Math.min(state.selectedIndex+1,state.shown.length-1));}
  else if(e.key==='ArrowUp'){e.preventDefault();selectSong(Math.max(0,state.selectedIndex-1));}
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
function drawLine(text,y,maxWidth,fontSize,fill,progress=null){
  if(!text)return;
  const w=ui.lyrics.width;
  let sz=fontSize;
  do {pen.font=`900 ${Math.round(sz)}px "Leelawadee UI","Noto Sans Thai",Tahoma,sans-serif`;if(pen.measureText(text).width<=maxWidth)break;sz*=.92;}while(sz>14);
  pen.textAlign='center';pen.textBaseline='middle';
  pen.lineWidth=Math.max(3,sz*.13);pen.strokeStyle='#010613';pen.lineJoin='round';pen.shadowColor='#000';pen.shadowBlur=6;
  pen.strokeText(text,w/2,y);pen.shadowBlur=0;pen.fillStyle=fill;pen.fillText(text,w/2,y);
  if(progress!==null){const width=pen.measureText(text).width;pen.save();pen.beginPath();pen.rect(w/2-width/2-1,y-sz*.8,Math.max(0,Math.min(1,progress))*width+1,sz*1.65);pen.clip();pen.fillStyle='#ffd76a';pen.fillText(text,w/2,y);pen.restore();}
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
        if(idx<0){drawLine(String(lines[0].text||''),h*.72,w*.93,fontSize,'#bfe2ef');}
        else{
          const current=lines[idx];drawLine(String(current.text||''),h*.66,w*.93,fontSize,'#ecf7ff',lineProgress(current,when));
          const next=lines[idx+1];if(next)drawLine(String(next.text||''),h*.83,w*.93,fontSize*.77,'#b7d2e0');
        }
      }
    }
  }catch(e){/* Preserve audio playback even if a malformed lyric line cannot draw. */}
  requestAnimationFrame(drawLyrics);
}

// Wall clock is local device time. Bar/beat are only shown when valid tempo metadata exists.
const stageClock=$('stage-clock'),stageBar=$('stage-bar'),stageBeat=$('stage-beat');
function musicalPosition(song,lyrics,seconds){
  const bpm=Number(lyrics?.bpm ?? song?.bpm ?? song?.tempo);
  const beatsPerBar=Number(lyrics?.beatsPerBar ?? song?.beatsPerBar ?? 4);
  if(!Number.isFinite(bpm)||bpm<=0||bpm>400||!Number.isInteger(beatsPerBar)||beatsPerBar<1||beatsPerBar>16)return null;
  const origin=Number(lyrics?.beatOffsetSeconds ?? song?.beatOffsetSeconds ?? 0);
  const beatIndex=Math.max(0,Math.floor((Math.max(0,seconds)-origin)*bpm/60));
  return {bar:Math.floor(beatIndex/beatsPerBar)+1,beat:beatIndex%beatsPerBar+1};
}
function updateStageMetrics(){
  if(stageClock)stageClock.textContent=new Date().toLocaleTimeString('th-TH',{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
  const m=state.current&&state.lyrics?musicalPosition(state.current,state.lyrics,player.currentTime):null;
  if(stageBar)stageBar.textContent='ห้อง '+(m?m.bar:'—');
  if(stageBeat)stageBeat.textContent='จังหวะ '+(m?m.beat:'—');
}
updateStageMetrics();setInterval(updateStageMetrics,250);
ui.login.addEventListener('click',login);ui.gateLogin.addEventListener('click',login);
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
player.addEventListener('timeupdate',updateTransport);player.addEventListener('loadedmetadata',updateTransport);
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