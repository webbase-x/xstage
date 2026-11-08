
/* X-Stage web feature parity — keeps Google Drive and playback state in app.js */
'use strict';
(function(){
const $pc=id=>document.getElementById(id);
const dock=$pc('pc-search'),toggle=$pc('pc-hide-search'),dialog=$pc('pc-dialog'),body=$pc('pc-dialog-body');
const favorites=new Set();
let abA=null,abB=null,lyricScale=1,lyricColor='#ecf7ff';
const audio=ui.player;
function expand(open){dock.classList.toggle('pc-expanded',!!open);toggle.textContent=open?'▴':'▾';}
function focusSearch(){if(!state.token)return;expand(true);ui.search.focus();ui.search.select();}
$pc('pc-find').onclick=focusSearch;
toggle.onclick=()=>expand(!dock.classList.contains('pc-expanded'));
ui.search.addEventListener('focus',()=>{if(state.token)expand(true)});
ui.search.addEventListener('input',()=>{if(state.token)expand(true)});
ui.search.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();expand(false);ui.search.blur();}if(e.key==='Enter')queueMicrotask(()=>expand(false));},true);
ui.songs.addEventListener('dblclick',()=>queueMicrotask(()=>expand(false)));
document.addEventListener('keydown',e=>{
 if(e.key==='F3'&&state.token){e.preventDefault();focusSearch();return;}
 if(e.key==='Escape'&&dock.classList.contains('pc-expanded')){e.preventDefault();expand(false);return;}
 if(e.key==='F7'){e.preventDefault();if(state.queue.length)playNext();else{stopSong();audio.pause();audio.removeAttribute('src');audio.load();state.current=null;state.lyrics=null;ui.nowPlaying.textContent='ยังไม่ได้เลือกเพลง';ui.nowArtist.textContent='X-Stage Karaoke Online';ui.stageCode.textContent='—';ui.stage.classList.remove('playing');ui.stageIdle.hidden=false;updateTransport();}}
 if(!state.token||e.ctrlKey||e.altKey||e.metaKey||e.key.length!==1||!/[\p{L}\p{N}]/u.test(e.key))return;
 if(['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName))return;
 e.preventDefault();expand(true);ui.search.focus();ui.search.value+=e.key;ui.search.dispatchEvent(new Event('input'));
},true);
const baseRender=renderSongs;
renderSongs=function(){
 if(!state.token){baseRender();return;}
 const saved=state.songs,filtered=$pc('pc-favorites-only').checked;
 if(filtered)state.songs=saved.filter(s=>favorites.has(songIdentity(s)));
 try{baseRender();}finally{state.songs=saved;}
 [...ui.songs.querySelectorAll('.song-item')].forEach((row,i)=>{
  const song=state.shown[i];if(!song)return;
  const star=document.createElement('button');star.type='button';star.className='pc-star';star.style.cssText='border:0;background:transparent;color:#ffd46a;font-size:20px;padding:3px 7px';star.textContent=favorites.has(songIdentity(song))?'★':'☆';star.title='เพลงโปรด (เฉพาะในแท็บนี้)';
  star.onclick=e=>{e.stopPropagation();const id=songIdentity(song);if(favorites.has(id))favorites.delete(id);else favorites.add(id);renderSongs();};
  row.insertBefore(star,row.lastElementChild);
  row.addEventListener('contextmenu',e=>{e.preventDefault();showSong(song);});
 });
};
$pc('pc-favorites-only').onchange=()=>{state.selectedIndex=0;renderSongs();};
const loginObserver=new MutationObserver(()=>{
 if(state.token&&!dock.dataset.logged){dock.dataset.logged='yes';expand(true);}
 if(!state.token&&dock.dataset.logged){delete dock.dataset.logged;favorites.clear();expand(false);}
});
loginObserver.observe(ui.logout,{attributes:true,attributeFilter:['hidden']});
function openDialog(title){$pc('pc-dialog-title').textContent=title;body.replaceChildren();if(!dialog.open)dialog.showModal();return body;}
$pc('pc-dialog-close').onclick=()=>dialog.close();
function button(label,handler){const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=handler;return b;}
function para(text){const p=document.createElement('p');p.textContent=text;return p;}
function showSong(song){const d=openDialog('รายละเอียดเพลง');d.append(para([song.code,song.title,song.artist,song.type,'ระยะเวลา '+(song.duration||0)+' วินาที'].filter(Boolean).join(' · ')),button('เล่นทันที',()=>{dialog.close();playSong(song);expand(false);}),button('แทรกเป็นเพลงถัดไป',()=>{state.queue.unshift(song);renderQueue();dialog.close();}));}
$pc('pc-history').onclick=()=>{const d=openDialog('ประวัติการเล่น (เซสชันนี้)');const songs=[...state.history];if(state.current)songs.push(state.current);if(!songs.length)d.append(para('ยังไม่มีประวัติการเล่น'));for(const s of songs.slice().reverse().slice(0,100)){const row=document.createElement('div');row.className='pc-history-row';const title=document.createElement('span');title.textContent=(s.code||'')+' · '+(s.title||'');row.append(title,button('เล่น',()=>{dialog.close();playSong(s);}));d.append(row);}};
$pc('pc-random').onclick=()=>{if(!state.token)return;const songs=state.songs.filter(playable);if(!songs.length)return;const song=songs[Math.floor(Math.random()*songs.length)];state.queue.push(song);renderQueue();setPlayStatus('สุ่มเพิ่มเพลงเข้าคิว: '+song.title);};
function updateAB(){ $pc('pc-loop-a').classList.toggle('pc-active',abA!==null);$pc('pc-loop-b').classList.toggle('pc-active',abB!==null); }
$pc('pc-loop-a').onclick=()=>{if(!state.current)return;abA=audio.currentTime;abB=null;updateAB();setPlayStatus('ตั้งจุด A '+timeLabel(abA));};
$pc('pc-loop-b').onclick=()=>{if(abA===null||audio.currentTime<=abA+.15){setPlayStatus('ตั้งจุด A ก่อน และให้ B อยู่หลัง A');return;}abB=audio.currentTime;audio.loop=false;ui.repeat.checked=false;updateAB();setPlayStatus('กำลังวน A–B');};
$pc('pc-loop-clear').onclick=()=>{abA=null;abB=null;updateAB();setPlayStatus('ยกเลิกการวน A–B');};
audio.addEventListener('timeupdate',()=>{if(abA!==null&&abB!==null&&audio.currentTime>=abB)audio.currentTime=abA;});
audio.addEventListener('loadedmetadata',()=>{abA=null;abB=null;updateAB();});
const originalDrawLine=drawLine;
drawLine=function(text,y,maxWidth,fontSize,fill,progress){return originalDrawLine(text,y,maxWidth,fontSize*lyricScale,fill==='#ecf7ff'?lyricColor:fill,progress);};
let bg=true;
$pc('pc-lyrics-settings').onclick=()=>{
 const d=openDialog('เนื้อร้อง / พื้นหลัง');
 const scale=document.createElement('input');scale.type='range';scale.min='.7';scale.max='1.5';scale.step='.05';scale.value=String(lyricScale);scale.oninput=()=>lyricScale=+scale.value;
 const sl=document.createElement('label');sl.textContent='ขนาดตัวอักษร';sl.append(scale);d.append(sl);
 const col=document.createElement('input');col.type='color';col.value=lyricColor;col.oninput=()=>lyricColor=col.value;
 const cl=document.createElement('label');cl.textContent='สีเนื้อร้อง';cl.append(col);d.append(cl);
 const offset=document.createElement('input');offset.type='range';offset.min='-3000';offset.max='3000';offset.step='50';offset.value='0';
 offset.oninput=()=>{if(state.lyrics){state.lyrics.audioOffsetMs=(Number(state.lyrics.audioOffsetMs)||0)+(+offset.value-(+offset.dataset.before||0));offset.dataset.before=offset.value;}};
 const ol=document.createElement('label');ol.textContent='ชดเชยเวลาเนื้อร้อง (ms)';ol.append(offset);d.append(ol);
 d.append(button(bg?'ปิดพื้นหลังเวที':'ใช้พื้นหลัง X-STAGE',()=>{bg=!bg;ui.stage.classList.toggle('pc-bg-off',!bg);dialog.close();}));
 d.append(para('การตั้งค่านี้ไม่แก้ไขเพลงหรือฐานข้อมูลใน Google Drive'));
};
let eqContext=null,eqNodes=[];
$pc('pc-eq').onclick=()=>{
 const d=openDialog('EQ เสียง M4A บนเว็บ');
 try{
  if(!eqContext){const C=window.AudioContext||window.webkitAudioContext;if(!C)throw Error('Web Audio API ไม่รองรับ');eqContext=new C();const src=eqContext.createMediaElementSource(audio);eqNodes=[{freq:100,type:'lowshelf'},{freq:1000,type:'peaking'},{freq:8000,type:'highshelf'}].map(o=>{const n=eqContext.createBiquadFilter();n.type=o.type;n.frequency.value=o.freq;return n;});src.connect(eqNodes[0]);eqNodes[0].connect(eqNodes[1]);eqNodes[1].connect(eqNodes[2]);eqNodes[2].connect(eqContext.destination);}
  eqContext.resume().catch(()=>{});
  ['Bass 100 Hz','Mid 1 kHz','Treble 8 kHz'].forEach((name,i)=>{const r=document.createElement('input');r.type='range';r.min=-12;r.max=12;r.value=String(eqNodes[i].gain.value);r.oninput=()=>eqNodes[i].gain.value=Number(r.value);const l=document.createElement('label');l.textContent=name;l.append(r);d.append(l);});
  d.append(button('คืนค่า EQ',()=>{eqNodes.forEach(n=>n.gain.value=0);dialog.close();}));
 }catch(e){d.append(para(e.message));}
 d.append(para('EQ นี้ไม่ใช่มิกเซอร์แยกเครื่องดนตรี MIDI ของรุ่น PC'));
};
function downloadQueue(){
 const data={schemaVersion:1,source:'XStageWebQueue',songs:state.queue.map(songIdentity)};
 const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
 const a=document.createElement('a');a.href=url;a.download='xstage-web-queue.json';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
}
$pc('pc-export').onclick=downloadQueue;
$pc('pc-import').onclick=()=>$pc('pc-queue-file').click();
$pc('pc-queue-file').onchange=async e=>{
 const f=e.target.files[0];if(!f||!state.token)return;
 try{if(f.size>1e6)throw Error('ไฟล์ใหญ่เกินไป');const d=JSON.parse(await f.text());if(d.source!=='XStageWebQueue'||!Array.isArray(d.songs)||d.songs.length>10000)throw Error('รูปแบบไม่ถูกต้อง');
 const map=new Map(state.songs.filter(playable).map(s=>[songIdentity(s),s]));let count=0;for(const id of d.songs){const s=map.get(String(id));if(s){state.queue.push(s);count++;}}renderQueue();setPlayStatus('นำเข้าคิว '+count+' เพลง');}catch(e){setPlayStatus('นำเข้าคิวไม่สำเร็จ: '+e.message);}e.target.value='';
};
let screen=null;
$pc('pc-stage-pop').onclick=()=>{
 if(screen&&!screen.closed){screen.focus();return;}screen=window.open('./stage.html','xstage-second-stage','width=1100,height=640');
 if(!screen)setPlayStatus('กรุณาอนุญาตให้เปิดหน้าต่างจอร้องแยก');
};
setInterval(()=>{if(!screen||screen.closed)return;try{screen.postMessage({type:'xstage-stage',title:state.current?.title||'',artist:state.current?.artist||'',lines:state.lyrics?.lines||[],offset:Number(state.lyrics?.audioOffsetMs)||0,time:audio.currentTime},location.origin);}catch{}},200);
$pc('pc-other-tools').onclick=()=>{const d=openDialog('ความสามารถ X-Stage Web');d.append(para('เว็บ: ค้นหาแบบเรียลไทม์, คิวเพลง, ประวัติ, เพลงโปรดในเซสชัน, สุ่มเพลง, A–B, EQ, ตั้งค่าเนื้อร้องและพื้นหลัง, จอร้องแยก, ส่งออก/นำเข้าคิว'));
 d.append(para('เฉพาะ Windows: MIDI Mixer / SoundFont แยกชิ้นดนตรี, GM Keyboard, ปิด Guide Melody, ASIO, ปรับคีย์ดนตรีอิสระจาก M4A และจัดการฐานเพลงในเครื่อง'));
};
ui.logout.addEventListener('click',()=>{favorites.clear();expand(false);abA=null;abB=null;updateAB();if(screen&&!screen.closed)screen.close();screen=null;});
expand(false);
})();
