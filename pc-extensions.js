
/* X-Stage web feature parity — keeps Google Drive and playback state in app.js */
'use strict';
(function(){
const $pc=id=>document.getElementById(id);
const dock=$pc('pc-search'),toggle=$pc('pc-hide-search'),dialog=$pc('pc-dialog'),body=$pc('pc-dialog-body');
const favorites=new Set();
let abA=null,abB=null,lyricScale=1,lyricColor='#ecf7ff';
const audio=ui.player;
function expand(open){dock.classList.toggle('pc-expanded',!!open);toggle.textContent=open?'▴':'▾';ui.search.setAttribute('aria-expanded',String(!!open));}
function focusSearch(){if(!state.token)return;expand(Boolean(ui.search.value.trim()));ui.search.focus();ui.search.select();}
$pc('pc-find').onclick=focusSearch;
toggle.onclick=()=>expand(!dock.classList.contains('pc-expanded'));
ui.search.addEventListener('focus',()=>{if(state.token)expand(Boolean(ui.search.value.trim()))});
ui.search.addEventListener('input',()=>{if(state.token){expand(Boolean(ui.search.value.trim()));if(state.shown.length)selectSong(0,false);}});
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
 if(state.token&&!dock.dataset.logged){dock.dataset.logged='yes';expand(Boolean(ui.search.value.trim()));}
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
drawLine=function(text,y,maxWidth,fontSize,fill,progress,centerX){return originalDrawLine(text,y,maxWidth,fontSize*lyricScale,fill==='#ecf7ff'?lyricColor:fill,progress,centerX);};
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

/* Optional PC-style utilities: queue performer, LRC editor, stage effects and microphone recording. */
(function(){
const el=id=>document.getElementById(id),d=el('pc-dialog'),title=el('pc-dialog-title'),body=el('pc-dialog-body');
function b(label,fn){const n=document.createElement('button');n.type='button';n.textContent=label;n.onclick=fn;return n;}
function paragraph(text){const n=document.createElement('p');n.textContent=text;return n;}
function show(titleText){title.textContent=titleText;body.replaceChildren();if(!d.open)d.showModal();}
function saveFile(name,text,type='text/plain;charset=utf-8'){const url=URL.createObjectURL(new Blob([text],{type}));const link=document.createElement('a');link.href=url;link.download=name;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);}
const qRender=renderQueue;
renderQueue=function(){qRender();[...ui.queue.querySelectorAll('.queue-item')].forEach((row,i)=>{
 const song=state.queue[i],controls=row.querySelector('.queue-controls');if(!song||!controls)return;
 const edit=b('✎',()=>queueEditor(i));edit.title='แก้ชื่อผู้ร้อง / ความเร็วเพลงนี้';controls.prepend(edit);
 const small=row.querySelector('.queue-info small');if(small&&song.queueSinger)small.textContent+=(small.textContent?' · ':'')+'ผู้ร้อง '+song.queueSinger;
 if(small&&song.queueSpeed&&song.queueSpeed!==1)small.textContent+=' · '+song.queueSpeed+'×';
});};
const originalPlay=playSong;
playSong=function(song,opts){if(song?.queueSpeed&&[.75,.9,1,1.1,1.25,1.5].includes(Number(song.queueSpeed)))ui.speed.value=String(song.queueSpeed);return originalPlay(song,opts);};
function queueEditor(index){const song=state.queue[index];if(!song)return;show('แก้ไขเพลงในคิว');
 const singer=document.createElement('input');singer.type='text';singer.maxLength=80;singer.value=song.queueSinger||'';singer.placeholder='ชื่อผู้ร้อง';singer.style.cssText='color:white;background:#092d42;border:1px solid #3685a2;padding:8px;border-radius:7px';
 const speed=document.createElement('select');for(const v of [.75,.9,1,1.1,1.25,1.5]){const o=document.createElement('option');o.value=String(v);o.textContent=v.toFixed(2)+'×';speed.append(o);}speed.value=String(song.queueSpeed||1);
 const l=document.createElement('label');l.textContent='ผู้ร้อง';l.append(singer);const l2=document.createElement('label');l2.textContent='ความเร็ว';l2.append(speed);body.append(l,l2);
 body.append(b('บันทึก',()=>{if(state.queue[index]===song){state.queue[index]={...song,queueSinger:singer.value.trim(),queueSpeed:Number(speed.value)};renderQueue();}d.close();}));
}
el('pc-export').onclick=()=>saveFile('xstage-web-queue.json',JSON.stringify({schemaVersion:1,source:'XStageWebQueue',songs:state.queue.map(song=>({id:songIdentity(song),singer:song.queueSinger||'',speed:Number(song.queueSpeed)||1}))},null,2),'application/json');
el('pc-queue-file').onchange=async e=>{const f=e.target.files[0];if(!f||!state.token)return;try{if(f.size>1000000)throw Error('ไฟล์ใหญ่เกินไป');const data=JSON.parse(await f.text());if(data.source!=='XStageWebQueue'||!Array.isArray(data.songs)||data.songs.length>10000)throw Error('รูปแบบคิวไม่รองรับ');
 const index=new Map(state.songs.filter(playable).map(song=>[songIdentity(song),song]));let count=0;for(const item of data.songs){const id=typeof item==='string'?item:String(item?.id||'');const song=index.get(id);if(song){state.queue.push({...song,queueSinger:typeof item?.singer==='string'?item.singer.slice(0,80):'',queueSpeed:[.75,.9,1,1.1,1.25,1.5].includes(Number(item?.speed))?Number(item.speed):1});count++;}}renderQueue();setPlayStatus('นำเข้าคิว '+count+' รายการ');}catch(e){setPlayStatus(e.message);}e.target.value='';};
function stamp(seconds){const n=Math.max(0,Number(seconds)||0);return '['+String(Math.floor(n/60)).padStart(2,'0')+':'+(n%60).toFixed(2).padStart(5,'0')+']';}
function lrcText(){return (state.lyrics?.lines||[]).map(line=>stamp(line.startTime)+String(line.text||'')).join('\n');}
function parseLRC(text){
 const entries=[];for(const line of text.split(/\r?\n/)){const marks=[...line.matchAll(/\[(\d{1,3}):(\d{2}(?:\.\d{1,3})?)\]/g)];const value=line.replace(/\[\d{1,3}:\d{2}(?:\.\d{1,3})?\]/g,'').trim();if(!value)continue;for(const m of marks)entries.push({start:Number(m[1])*60+Number(m[2]),text:value});}
 entries.sort((a,b)=>a.start-b.start);if(!entries.length)throw Error('ไม่พบเวลา LRC ที่ถูกต้อง');
 return {schemaVersion:1,audioOffsetMs:0,lines:entries.map((entry,i)=>{const end=Math.max(entry.start+.1,entries[i+1]?.start??entry.start+6);return {lineIndex:i,startTime:entry.start,endTime:end,text:entry.text,syllables:[{text:entry.text,start:entry.start,duration:end-entry.start}]};})};
}
function lyricEditor(){show('แก้ไข / นำเข้า LRC');if(!state.current){body.append(paragraph('กรุณาเลือกเพลงก่อน'));return;}body.append(paragraph('แก้ไขเฉพาะการเล่นครั้งนี้ ไม่เปลี่ยน JSON บน Drive; การนำเข้า LRC จะใช้เวลาระดับบรรทัด'));
 const area=document.createElement('textarea');area.value=lrcText();area.rows=9;area.style.cssText='background:#051b2c;color:#fff;border:1px solid #366f85;border-radius:8px;padding:10px;width:100%;font:13px/1.6 monospace';body.append(area);
 const uploader=document.createElement('input');uploader.type='file';uploader.accept='.lrc,text/plain';uploader.onchange=async()=>{const file=uploader.files[0];if(!file)return;if(file.size>250000){setPlayStatus('LRC ใหญ่เกินไป');return;}const bytes=await file.arrayBuffer();const decoded=new TextDecoder('utf-8').decode(bytes);area.value=decoded.includes('�')?new TextDecoder('windows-874').decode(bytes):decoded;};body.append(uploader);
 body.append(b('ใช้เนื้อร้องฉบับนี้',()=>{try{state.lyrics=parseLRC(area.value);d.close();setPlayStatus('อัปเดตเนื้อร้อง LRC ในแท็บแล้ว');}catch(e){body.append(paragraph(e.message));}}),b('ดาวน์โหลด LRC',()=>saveFile((state.current.code||'song')+'.lrc',area.value)));
}
let rec=null;async function micRecording(){if(rec){const r=rec;rec=null;r.stop();setPlayStatus('หยุดบันทึกไมโครโฟนแล้ว');return;}try{if(!navigator.mediaDevices?.getUserMedia||typeof MediaRecorder==='undefined')throw Error('เบราว์เซอร์ไม่รองรับบันทึกไมโครโฟน');
 const stream=await navigator.mediaDevices.getUserMedia({audio:true});const recorder=new MediaRecorder(stream),parts=[];recorder.ondataavailable=e=>{if(e.data.size)parts.push(e.data);};
 recorder.onstop=()=>{stream.getTracks().forEach(t=>t.stop());if(parts.length){const url=URL.createObjectURL(new Blob(parts,{type:recorder.mimeType}));const link=document.createElement('a');link.href=url;link.download='xstage-mic.'+(recorder.mimeType.includes('ogg')?'ogg':'webm');link.click();setTimeout(()=>URL.revokeObjectURL(url),30000);}};
 recorder.start();rec=recorder;setPlayStatus('กำลังบันทึกไมโครโฟน…');}catch(e){setPlayStatus(e.message);}
}
const effects=new Map();function stageEffects(){show('เสียงเอฟเฟกต์หน้าเวที (จากเครื่องนี้)');body.append(paragraph('เลือก WAV/MP3 ได้สูงสุด 10 ไฟล์เพื่อเล่นเฉพาะแท็บ ไม่อัปโหลดไป Drive'));
 const input=document.createElement('input');input.type='file';input.accept='.mp3,.wav,audio/*';input.multiple=true;
 const list=document.createElement('div');input.onchange=()=>{for(const url of effects.values())URL.revokeObjectURL(url);effects.clear();for(const [i,f] of [...input.files].slice(0,10).entries())effects.set(i,URL.createObjectURL(f));renderFx();};
 function renderFx(){list.replaceChildren();for(const [i,url] of effects)list.append(b('เอฟเฟกต์ '+(i+1),()=>new Audio(url).play().catch(()=>{})));}body.append(input,list);renderFx();}
const previousTools=el('pc-other-tools').onclick;
el('pc-other-tools').onclick=()=>{previousTools?.();body.append(b('แก้ไข / นำเข้าเนื้อร้อง LRC',lyricEditor),b(rec?'หยุดบันทึกไมโครโฟน':'บันทึกไมโครโฟน',micRecording),b('เสียงเอฟเฟกต์หน้าเวที',stageEffects),b('สุ่มเพิ่มเพลง 5 รายการ',()=>{const pool=state.songs.filter(playable).slice().sort(()=>Math.random()-.5);for(const song of pool.slice(0,5))state.queue.push(song);renderQueue();d.close();}));};
ui.logout.addEventListener('click',()=>{if(rec){const r=rec;rec=null;r.stop();}for(const url of effects.values())URL.revokeObjectURL(url);effects.clear();});
})();
