'use strict';
// X-Stage Web v0.9.44: each Google account reads only its private XStageWeb.
const config = window.XSTAGE_CONFIG || {};
const el = id => document.getElementById(id);
let token = '', identity = '', songs = [], queue = [], history = [], current = null;
let audioUrl = '', generation = 0, lyricsData = null, fetchController = null;
const player = el('player');
const canvas = el('lyrics');
const ctx = canvas ? canvas.getContext('2d') : null;
const rootName = 'XStageWeb';
function message(msg) { el('status').textContent = msg; }
function reset() {
  ++generation;
  if (fetchController) fetchController.abort();
  fetchController = null;
  player.pause(); player.removeAttribute('src'); player.load();
  if (audioUrl) URL.revokeObjectURL(audioUrl);
  audioUrl = ''; lyricsData = null; songs = [];queue=[];history=[];current=null;
  token = '';identity = '';
  el('library').hidden=true;el('account').textContent='';el('songs').replaceChildren();
  renderQueue();draw();
}
function auth() {
  if (!config.googleClientId || !config.googleClientId.endsWith('.apps.googleusercontent.com')) {
    message('ยังไม่ได้ตั้งค่า Google OAuth Web Client ID');return;
  }
  const client=google.accounts.oauth2.initTokenClient({
    client_id:config.googleClientId,
    scope:'openid email https://www.googleapis.com/auth/drive.file',
    callback:async result=>{
      if(result.error || !result.access_token) {message('Google Login ไม่สำเร็จ');return;}
      reset();token=result.access_token;const myGeneration=generation;
      try {
        const profile=await fetch('https://openidconnect.googleapis.com/v1/userinfo',{
          headers:{Authorization:'Bearer '+token},cache:'no-store'}).then(checkResponse);
        if(!profile.email_verified) throw Error('Google ไม่ยืนยันบัญชีนี้');
        identity=profile.sub || '';el('account').textContent=profile.email || 'Google Account';
        await loadLibrary(myGeneration);
      } catch(error) {if(generation===myGeneration){reset();message(error.message);}}
    }
  });
  client.requestAccessToken({prompt:'consent select_account'});
}
async function checkResponse(response) {
  if(!response.ok) {
    if(response.status===401) throw Error('สิทธิ์ Google หมดอายุ กรุณาเข้าสู่ระบบใหม่');
    if(response.status===403) throw Error('บัญชีนี้ไม่มีสิทธิ์เข้าถึงคลังที่ร้องขอ');
    throw Error('Google Drive ตอบ HTTP '+response.status);
  }
  return response.json();
}
async function apiList(parent, name) {
  const q="'"+String(parent).replace(/'/g,"\\'")+"' in parents and trashed=false" +
    (name ? " and name='"+String(name).replace(/'/g,"\\'")+"'" : '');
  let page='',out=[];
  do {
    const p=new URLSearchParams({q,fields:'nextPageToken,files(id,name,mimeType,md5Checksum,size)',pageSize:'1000'});
    if(page)p.set('pageToken',page);
    const resp=await fetch('https://www.googleapis.com/drive/v3/files?'+p,{headers:{Authorization:'Bearer '+token},cache:'no-store'});
    const value=await checkResponse(resp);
    out.push(...(value.files||[]));page=value.nextPageToken||'';
  }while(page);
  return out;
}
function unique(results, name) {
  if(results.length>1)throw Error('พบ '+name+' ซ้ำใน Drive กรุณาจัดการจากเครื่อง Windows');
  return results[0]||null;
}
async function media(id, signal) {
  if(!/^[A-Za-z0-9_-]{6,}$/.test(String(id)))throw Error('File ID ผิดรูปแบบ');
  const response=await fetch('https://www.googleapis.com/drive/v3/files/'+encodeURIComponent(id)+'?alt=media',{
    headers:{Authorization:'Bearer '+token},cache:'no-store',signal});
  if(!response.ok)throw Error('ดาวน์โหลดไฟล์จาก Drive ไม่สำเร็จ: HTTP '+response.status);
  return response;
}
async function loadLibrary(startGeneration) {
  message('กำลังอ่านคลังส่วนตัวจาก Google Drive…');
  const root=unique((await apiList('root',rootName)).filter(x=>x.mimeType==='application/vnd.google-apps.folder'),rootName);
  if(!root)throw Error('ยังไม่มี XStageWeb ใน Google Drive กรุณาซิงก์จาก X-Stage Windows ก่อน');
  const pointer=unique(await apiList(root.id,'current.json'),'current.json');
  if(!pointer)throw Error('ยังไม่มีฐานเพลงที่เผยแพร่สำเร็จ กรุณาซิงก์จาก Windows ก่อน');
  const pointerData=await (await media(pointer.id)).json();
  if(pointerData.schemaVersion!==1)throw Error('รูปแบบ current.json ไม่รองรับ');
  const database=await (await media(pointerData.catalogFileId)).json();
  if(database.schemaVersion!==1 || !Array.isArray(database.songs))throw Error('ฐานเพลงไม่รองรับ');
  if(startGeneration!==generation || !token)return;
  songs=database.songs.filter(song=>song&&song.audio?.fileId&&song.lyrics?.fileId);
  el('library').hidden=false;
  message('พร้อมเล่น '+songs.length.toLocaleString()+' เพลงใน Google Drive ของบัญชีนี้');
  renderSongs();renderQueue();
}
function songInfo(song) {
  const info=document.createElement('div');info.className='info';
  const title=document.createElement('strong');title.textContent=song.title||song.code||'ไม่ระบุ';
  const artist=document.createElement('small');artist.textContent=[song.code,song.artist].filter(Boolean).join(' · ');
  info.append(title,artist);return info;
}
function control(label,callback) {const b=document.createElement('button');b.textContent=label;b.type='button';b.onclick=callback;return b;}
function renderSongs() {
  const term=el('search').value.trim().toLocaleLowerCase();
  const found=songs.filter(s=>[s.code,s.title,s.artist].join(' ').toLocaleLowerCase().includes(term));
  el('songs').replaceChildren(...found.slice(0,300).map(song=>{
    const row=document.createElement('div');row.className='row';
    row.append(songInfo(song),control('เล่น',()=>play(song)),control('+ คิว',()=>{queue.push(song);renderQueue();}));
    return row;
  }));
  if(!found.length)el('songs').textContent='ไม่พบเพลง';
  el('result-count').textContent=found.length.toLocaleString()+' เพลง';
}
function renderQueue() {
  el('queue-count').textContent=queue.length.toLocaleString();
  el('queue').replaceChildren(...queue.map((song,index)=>{
    const row=document.createElement('li');row.className='row';
    row.append(songInfo(song),control('เล่น',()=>{queue.splice(index,1);renderQueue();play(song);}),
      control('นำออก',()=>{queue.splice(index,1);renderQueue();}));return row;
  }));
}
async function play(song, remember=true) {
  const request=++generation;
  if(fetchController)fetchController.abort();
  fetchController=new AbortController();
  const signal=fetchController.signal;
  player.pause();message('กำลังดาวน์โหลดเสียงและเนื้อร้อง…');
  try {
    const [audioResponse,lyricResponse]=await Promise.all([
      media(song.audio.fileId,signal),media(song.lyrics.fileId,signal)]);
    const [blob,lyrics]=await Promise.all([audioResponse.blob(),lyricResponse.json()]);
    if(request!==generation)return;
    if(lyrics.schemaVersion!==1 || !Array.isArray(lyrics.lines))throw Error('ข้อมูลเนื้อร้องไม่รองรับ');
    if(audioUrl)URL.revokeObjectURL(audioUrl);
    audioUrl=URL.createObjectURL(blob);
    if(current&&remember)history.push(current);
    current=song;lyricsData=lyrics;
    el('now-playing').textContent=[song.title,song.artist].filter(Boolean).join(' — ');
    player.src=audioUrl;
    player.playbackRate=Number(el('speed').value);
    renderQueue();message('กำลังเล่น '+(song.title||song.code));
    try{await player.play();}catch{message('โหลดเพลงแล้ว กดเล่นที่ตัวควบคุมเสียงเพื่อเริ่ม');}
  }catch(error){if(request===generation&&!signal.aborted)message(error.message);}
}
function paint(text,y,color,highlight=0) {
  const width=canvas.width;
  ctx.font='bold 48px "Noto Sans Thai", "Leelawadee UI", sans-serif';
  ctx.textAlign='center';ctx.textBaseline='middle';
  ctx.strokeStyle='#001421';ctx.lineWidth=6;ctx.strokeText(text,width/2,y);
  ctx.fillStyle=color;ctx.fillText(text,width/2,y);
  if(highlight>0){
    const measured=ctx.measureText(text).width;
    ctx.save();ctx.beginPath();ctx.rect(width/2-measured/2,y-42,measured*Math.min(1,highlight),84);ctx.clip();
    ctx.fillStyle='#f6d74b';ctx.fillText(text,width/2,y);ctx.restore();
  }
}
function draw(){
  if(!ctx)return;
  const width=canvas.width,height=canvas.height;
  ctx.clearRect(0,0,width,height);
  ctx.fillStyle='#07131f';ctx.fillRect(0,0,width,height);
  if(!lyricsData?.lines?.length){paint('X-Stage Karaoke Online',height/2,'#cedbe7');return;}
  const now=player.currentTime+(Number(lyricsData.audioOffsetMs)||0)/1000;
  const lines=lyricsData.lines;
  let index=-1;
  for(let i=0;i<lines.length;i++){if(Number(lines[i].startTime)<=now)index=i;else break;}
  const line=index>=0?lines[index]:null;
  const next=lines[index+1]||null;
  if(line){
    const chunks=Array.isArray(line.syllables)?line.syllables:[];
    let totalChars=0,highlightChars=0;
    for(const s of chunks){
      const size=String(s.text||'').length;totalChars+=size;
      const d=Math.max(0,Number(s.duration)||0);
      const ratio=now>=Number(s.start)?(d?Math.min(1,(now-Number(s.start))/d):1):0;
      highlightChars+=size*Math.max(0,ratio);
    }
    const ratio=totalChars?highlightChars/totalChars:(now>=Number(line.startTime)?1:0);
    paint(line.text||'',height*.36,'#f0f6fd',ratio);
  }
  if(next)paint(next.text||'',height*.71,'#b9cada');
}
function tick(){draw();requestAnimationFrame(tick);}requestAnimationFrame(tick);
el('login').addEventListener('click',()=>{try{auth()}catch(e){message(e.message);}});
el('logout').addEventListener('click',()=>{const old=token;reset();message('ออกจากระบบแล้ว');if(old)google.accounts.oauth2.revoke(old,()=>{});});
el('search').addEventListener('input',renderSongs);
el('next').addEventListener('click',()=>{const song=queue.shift();renderQueue();if(song)play(song);});
el('previous').addEventListener('click',()=>{const song=history.pop();if(song)play(song,false);});
el('stop').addEventListener('click',()=>{player.pause();if(player.readyState)player.currentTime=0;draw();});
el('speed').addEventListener('change',()=>{player.playbackRate=Number(el('speed').value);});
el('repeat').addEventListener('change',()=>{player.loop=el('repeat').checked;});
player.addEventListener('ended',()=>{if(!player.loop){const next=queue.shift();renderQueue();if(next)play(next);}});
window.addEventListener('beforeunload',reset);
renderQueue();draw();
