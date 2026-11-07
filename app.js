const cfg=window.XSTAGE_CONFIG||{};let token='',manifest=null,snapshotRootId='',objectUrl='';
const $=id=>document.getElementById(id);
const esc=value=>String(value).replace(/\\/g,"\\\\").replace(/'/g,"\\'");
function status(value){$('status').textContent=value}
function tokenClient(){if(!cfg.googleClientId||cfg.googleClientId.startsWith('YOUR_'))throw Error('ยังไม่ได้ตั้งค่า Google OAuth Web Client ID');return google.accounts.oauth2.initTokenClient({client_id:cfg.googleClientId,scope:'https://www.googleapis.com/auth/drive.readonly',callback:async result=>{if(result.error){status('เข้าสู่ระบบไม่สำเร็จ');return}token=result.access_token;try{await openDrive()}catch(error){status(error.message)}}})}
async function drive(query,orderBy='modifiedTime desc'){const params={q:query,fields:'files(id,name,mimeType,parents,modifiedTime)',pageSize:'1000'};if(orderBy)params.orderBy=orderBy;const response=await fetch('https://www.googleapis.com/drive/v3/files?'+new URLSearchParams(params),{headers:{Authorization:'Bearer '+token}});if(!response.ok)throw Error('อ่าน Google Drive ไม่สำเร็จ');return(await response.json()).files||[]}
async function fileMeta(id){const response=await fetch('https://www.googleapis.com/drive/v3/files/'+encodeURIComponent(id)+'?fields=id,name,mimeType,parents,modifiedTime',{headers:{Authorization:'Bearer '+token}});if(!response.ok)throw Error('อ่านโครงสร้างคลังเพลงไม่สำเร็จ');return response.json()}
async function underRoot(fileId,rootId){let current=fileId,seen=new Set();for(let depth=0;depth<12&&current&&!seen.has(current);depth++){seen.add(current);if(current===rootId)return true;const meta=await fileMeta(current);current=(meta.parents||[])[0]}return false}
async function openDrive(){status('กำลังค้นหาคลัง XStageKaraoke…');const roots=await drive("name='XStageKaraoke' and mimeType='application/vnd.google-apps.folder' and trashed=false",'name');if(!roots.length)throw Error('ไม่พบโฟลเดอร์ XStageKaraoke ใน Google Drive');const rootIds=new Set(roots.map(root=>root.id));const manifests=await drive("name='web-manifest.json' and trashed=false",'modifiedTime desc');let selected=null;for(const candidate of manifests){for(const rootId of rootIds){if(await underRoot(candidate.id,rootId)){selected=candidate;break}}if(selected)break}if(!selected)throw Error('ไม่พบ web-manifest.json ในคลัง XStageKaraoke กรุณากดซิงก์จาก PC ก่อน');snapshotRootId=(selected.parents||[])[0]||'';const response=await fetch('https://www.googleapis.com/drive/v3/files/'+encodeURIComponent(selected.id)+'?alt=media',{headers:{Authorization:'Bearer '+token}});if(!response.ok)throw Error('อ่าน web-manifest.json ไม่สำเร็จ');manifest=await response.json();$('account').textContent=manifest.user_id||'';$('library').hidden=false;status('พร้อมเล่น '+(manifest.songs||[]).length.toLocaleString()+' เพลง');render()}
function webPlayable(song){return /\.(mp3|wav|ogg|m4a|aac|flac)$/i.test(String(song.path||song.format||''))}
const queue = [];
const history = [];
let currentSong = null;
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
async function resolveSongFile(song){const hasRelative=typeof song.rel_path==='string'&&song.rel_path.trim()!=='';const relative=String(hasRelative?song.rel_path:song.path||'').replaceAll('\\','/');const marker=hasRelative?-1:relative.toLowerCase().indexOf('/songs/');const normalized=marker>=0?relative.slice(marker+7):relative;const parts=normalized.split('/').filter(Boolean);if(!parts.length)return null;let parent=await folderChild(snapshotRootId,'Songs','application/vnd.google-apps.folder');if(!parent)return null;for(let index=0;index<parts.length;index++){const child=await folderChild(parent.id,parts[index],index===parts.length-1?'':'application/vnd.google-apps.folder');if(!child)return null;parent=child}return parent}
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
    if (request !== playRequest) return;
    player.pause();
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = URL.createObjectURL(data);
    if (remember && currentSong) history.push(currentSong);
    currentSong = song;
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

