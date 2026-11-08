const cfg=window.XSTAGE_CONFIG||{};let token='',manifest=null,snapshotRootId='',objectUrl='';
const $=id=>document.getElementById(id);
const esc=value=>String(value).replace(/\\/g,"\\\\").replace(/'/g,"\\'");
function status(value){$('status').textContent=value}
function tokenClient(){if(!cfg.googleClientId||cfg.googleClientId.startsWith('YOUR_'))throw Error('ยังไม่ได้ตั้งค่า Google OAuth Web Client ID');return google.accounts.oauth2.initTokenClient({client_id:cfg.googleClientId,scope:'openid email https://www.googleapis.com/auth/drive.file',callback:async result=>{if(result.error){status('เข้าสู่ระบบไม่สำเร็จ');return}resetPrivate();token=result.access_token;try{await openDrive()}catch(error){status(error.message)}}})}
async function drive(query,orderBy='modifiedTime desc'){const params={q:query,fields:'files(id,name,mimeType,parents,modifiedTime)',pageSize:'1000'};if(orderBy)params.orderBy=orderBy;const response=await fetch('https://www.googleapis.com/drive/v3/files?'+new URLSearchParams(params),{headers:{Authorization:'Bearer '+token}});if(!response.ok)throw Error('อ่าน Google Drive ไม่สำเร็จ');return(await response.json()).files||[]}
async function fileMeta(id){const response=await fetch('https://www.googleapis.com/drive/v3/files/'+encodeURIComponent(id)+'?fields=id,name,mimeType,parents,modifiedTime',{headers:{Authorization:'Bearer '+token}});if(!response.ok)throw Error('อ่านโครงสร้างคลังเพลงไม่สำเร็จ');return response.json()}
async function underRoot(fileId,rootId){let current=fileId,seen=new Set();for(let depth=0;depth<12&&current&&!seen.has(current);depth++){seen.add(current);if(current===rootId)return true;const meta=await fileMeta(current);current=(meta.parents||[])[0]}return false}
async function privateJson(id){
 const r=await fetch('https://www.googleapis.com/drive/v3/files/'+encodeURIComponent(id)+'?alt=media',{headers:{Authorization:'Bearer '+token},cache:'no-store'});
 if(!r.ok)throw Error('ไม่สามารถอ่านไฟล์ส่วนตัวบน Drive (HTTP '+r.status+')');
 return r.json();
}
async function openDrive(){
 status('กำลังตรวจคลัง XStageWeb ของบัญชี Google นี้…');
 const roots=(await drive("name='XStageWeb' and 'root' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",'name')).filter(r=>r.mimeType==='application/vnd.google-apps.folder');
 if(roots.length!==1)throw Error(roots.length?'พบ XStageWeb ซ้ำ':'ไม่พบ XStageWeb กรุณาซิงก์จาก X-Stage Windows ก่อน');
 const pointers=await drive("'"+roots[0].id+"' in parents and name='current.json' and trashed=false",'name');
 if(pointers.length!==1)throw Error('ยังไม่มี current.json ที่เผยแพร่สำเร็จ');
 const pointer=await privateJson(pointers[0].id);
 if(pointer.schemaVersion!==1||!pointer.catalogFileId)throw Error('รูปแบบ current.json ไม่รองรับ');
 const data=await privateJson(pointer.catalogFileId);
 if(data.schemaVersion!==1||!Array.isArray(data.songs))throw Error('รูปแบบฐานเพลงไม่รองรับ');
 manifest={songs:data.songs.filter(s=>s&&s.audio?.fileId&&s.lyrics?.fileId)};
 const r=await fetch('https://openidconnect.googleapis.com/v1/userinfo',{headers:{Authorization:'Bearer '+token},cache:'no-store'});
 if(!r.ok)throw Error('ตรวจบัญชี Google ไม่สำเร็จ');
 const me=await r.json();if(!me.email_verified)throw Error('บัญชี Google ไม่ได้รับการยืนยัน');
 $('account').textContent=me.email||'';
 $('library').hidden=false;
 status('พร้อมเล่น '+manifest.songs.length.toLocaleString()+' เพลงใน Drive ของบัญชีนี้');
 render();
}
function webPlayable(song){return !!(song&&song.audio?.fileId&&song.lyrics?.fileId)}
const queue = [];
const history = [];
let currentSong = null;
let currentLyrics = null;
let playRequest = 0;
const player = $('player');
const playStatus = message => { $('play-status').textContent = message; };

function action(label, handler, className = '') {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = label;
  button.className = className;
  button.onclick = handler;
  return button;
}

function songInfo(song) {
  const info = document.createElement('div');
  info.className = 'info';
  const title = document.createElement('strong');
  title.textContent = song.title || 'ไม่ระบุชื่อเพลง';
  const artist = document.createElement('small');
  artist.textContent = [song.code, song.artist].filter(Boolean).join(' · ');
  info.append(title, artist);
  return info;
}

function render() {
  const query = $('search').value.trim().toLocaleLowerCase();
  const matches = (manifest?.songs || []).filter(song =>
    [song.title, song.artist, song.code].join(' ').toLocaleLowerCase().includes(query));
  $('songs').replaceChildren(...matches.slice(0, 500).map(song => {
    const row = document.createElement('div');
    row.className = 'row';
    const controls = document.createElement('div');
    controls.className = 'row-actions';
    if (webPlayable(song)) {
      controls.append(action('เล่น', () => play(song), 'play'),
        action('+ คิว', () => { queue.push(song); renderQueue(); }));
    } else {
      const hint = document.createElement('small');
      hint.textContent = 'เล่นบน Windows';
      controls.append(hint);
    }
    row.append(songInfo(song), controls);
    return row;
  }));
  if (!matches.length) $('songs').textContent = 'ไม่พบเพลง';
}

function renderQueue() {
  $('queue-count').textContent = queue.length ? '(' + queue.length + ')' : '';
  $('next').disabled = !queue.length;
  $('previous').disabled = !history.length;
  $('stop').disabled = !currentSong;
  $('queue').replaceChildren(...queue.map((song, index) => {
    const row = document.createElement('li');
    row.className = 'row';
    row.append(songInfo(song), action('เล่น', () => {
      queue.splice(index, 1);
      renderQueue();
      play(song);
    }), action('นำออก', () => { queue.splice(index, 1); renderQueue(); }));
    return row;
  }));
  if (!queue.length) {
    const empty = document.createElement('li');
    empty.textContent = 'ยังไม่มีเพลงในคิว';
    $('queue').append(empty);
  }
}

function playNext() {
  const song = queue.shift();
  renderQueue();
  if (song) play(song);
}
async function folderChild(parentId,name,mimeType){const files=await drive("name='"+esc(name)+"' and '"+parentId+"' in parents and trashed=false",'name');return files.find(file=>!mimeType||file.mimeType===mimeType)||null}
async function resolveSongFile(song) {
 if(!webPlayable(song))return null;
 return {id:song.audio.fileId};
}
async function play(song, remember = true) {
  const request = ++playRequest;
  playStatus('กำลังโหลดเพลง…');
  try {
    const file = await resolveSongFile(song);
    if (!file) throw Error('ไม่พบไฟล์เพลงใน Google Drive');
    if (request !== playRequest) return;
    const response = await fetch('https://www.googleapis.com/drive/v3/files/' +
      encodeURIComponent(file.id) + '?alt=media', {headers: {Authorization: 'Bearer ' + token}});
    if (!response.ok) throw Error('ดาวน์โหลดไฟล์เพลงไม่สำเร็จ');
    const data = await response.blob();
    const lr=await fetch('https://www.googleapis.com/drive/v3/files/'+encodeURIComponent(song.lyrics.fileId)+'?alt=media',{headers:{Authorization:'Bearer '+token},cache:'no-store'});
    if(!lr.ok)throw Error('ไม่สามารถดาวน์โหลดเนื้อร้องส่วนตัวจาก Drive');
    const lyricJson=await lr.json();
    if(lyricJson.schemaVersion!==1||!Array.isArray(lyricJson.lines))throw Error('Lyrics JSON ไม่รองรับ');
    if (request !== playRequest) return;
    player.pause();
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = URL.createObjectURL(data);
    if (remember && currentSong) history.push(currentSong);
    currentSong = song;
    currentLyrics = lyricJson;
    $('now-playing').textContent = song.title || 'ไม่ระบุชื่อเพลง';
    player.src = objectUrl;
    player.playbackRate = Number($('speed').value);
    renderQueue();
    try {
      await player.play();
      if (request === playRequest) playStatus('');
    } catch {
      if (request === playRequest) playStatus('กดปุ่มเล่นในเครื่องเล่นเพื่อเริ่มเพลง');
    }
  } catch (error) {
    if (request === playRequest) playStatus(error.message);
  }
}

function resetPrivate(){
 ++playRequest;player.pause();player.removeAttribute('src');player.load();
 if(objectUrl)URL.revokeObjectURL(objectUrl);objectUrl='';
 queue.length=0;history.length=0;currentSong=null;currentLyrics=null;
 manifest=null;token='';$('library').hidden=true;$('account').textContent='';
 renderQueue();
}
const lyricCanvas=$('lyrics');
const lyricPen=lyricCanvas?.getContext('2d');
function paintLyric(text,y,color,ratio=0){
 if(!lyricPen)return;
 const c=lyricPen;const width=lyricCanvas.width;
 c.font='bold 48px "Noto Sans Thai","Leelawadee UI",sans-serif';c.textBaseline='middle';c.textAlign='center';
 c.lineWidth=6;c.strokeStyle='#07131f';c.strokeText(text,width/2,y);
 c.fillStyle=color;c.fillText(text,width/2,y);
 if(ratio>0){const w=c.measureText(text).width;c.save();c.beginPath();c.rect(width/2-w/2,y-42,w*Math.min(1,ratio),84);c.clip();c.fillStyle='#f6d54b';c.fillText(text,width/2,y);c.restore();}
}
function drawLyrics(){
 if(lyricPen){
 const w=lyricCanvas.width,h=lyricCanvas.height;
 lyricPen.fillStyle='#07131f';lyricPen.fillRect(0,0,w,h);
 const lines=currentLyrics?.lines||[];
 if(!lines.length)paintLyric('X-Stage Karaoke Online',h/2,'#bcd2e2');
 else{
   const now=player.currentTime+(Number(currentLyrics.audioOffsetMs)||0)/1000;
   let i=-1;for(let j=0;j<lines.length;j++){if(Number(lines[j].startTime)<=now)i=j;else break;}
   if(i>=0){const line=lines[i],units=Array.isArray(line.syllables)?line.syllables:[];let whole=0,lit=0;
    for(const unit of units){const n=String(unit.text||'').length,d=Number(unit.duration)||0,st=Number(unit.start)||0;
     whole+=n;lit+=n*(now>=st?(d?Math.min(1,(now-st)/d):1):0);}
    paintLyric(line.text||'',h*.35,'#f0f6fb',whole?lit/whole:1);}
   if(lines[i+1])paintLyric(lines[i+1].text||'',h*.72,'#a8bccc');
 }
 }
 requestAnimationFrame(drawLyrics);
}
requestAnimationFrame(drawLyrics);
$('logout').onclick=()=>{const old=token;resetPrivate();status('ออกจากระบบ Google แล้ว');if(old)google.accounts.oauth2.revoke(old,()=>{});};
$('next').onclick = playNext;
$('previous').onclick = () => {
  const song = history.pop();
  renderQueue();
  if (song) play(song, false);
};
$('stop').onclick = () => {
  ++playRequest;
  player.pause();
  if (player.readyState) player.currentTime = 0;
  playStatus('หยุดเล่นแล้ว');
};
$('speed').onchange = () => { player.playbackRate = Number($('speed').value); };
$('repeat').onchange = () => { player.loop = $('repeat').checked; };
player.addEventListener('ended', playNext);
player.addEventListener('error', () => playStatus('เบราว์เซอร์เล่นไฟล์นี้ไม่ได้'));
renderQueue();
$('login').onclick=()=>{try{tokenClient().requestAccessToken({prompt:'consent'})}catch(error){status(error.message)}};$('search').oninput=render;window.addEventListener('beforeunload',()=>{if(objectUrl)URL.revokeObjectURL(objectUrl)});

