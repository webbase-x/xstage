// Isolated MIDI laboratory. No OAuth/Drive access; no mutation of the M4A player.
const VERSION='4.4.8';
const LIB_URL='https://esm.sh/spessasynth_lib@'+VERSION+'?bundle';
const WORKLET_URL='https://cdn.jsdelivr.net/npm/spessasynth_lib@'+VERSION+'/dist/spessasynth_processor.min.js';
const STORE='xstage-midi-soundfont-v1', LIMIT=64*1024*1024;
const $=id=>document.getElementById(id);
const status=msg=>{$('status').textContent=msg;};
const DEFAULTS={mode:'auto',quality:'balanced',cache:true};
let audioContext=null,synth=null,sequencer=null,fontSignature='',loading=false;
let cachedFont=null,uiTimer=null;
function prefs(){try{return {...DEFAULTS,...JSON.parse(localStorage.getItem('xstage-midi-lab-settings')||'{}')};}catch{return {...DEFAULTS};}}
function savePrefs(){try{localStorage.setItem('xstage-midi-lab-settings',JSON.stringify({mode:$('mode').value,quality:$('quality').value,cache:$('cache').checked}));}catch{}}
function hasMidiHeader(buffer){const b=new Uint8Array(buffer,0,Math.min(buffer.byteLength,4));return b.length===4&&b[0]===77&&b[1]===84&&b[2]===104&&b[3]===100;}
function soundFontHeader(buffer){const b=new Uint8Array(buffer,0,Math.min(buffer.byteLength,12));return b.length===12&&String.fromCharCode(...b.subarray(0,4))==='RIFF'&&String.fromCharCode(...b.subarray(8,12))==='sfbk';}
function cacheDB(){return new Promise((resolve,reject)=>{if(!indexedDB){reject(Error('IndexedDB unavailable'));return;}const req=indexedDB.open(STORE,1);req.onupgradeneeded=()=>req.result.createObjectStore('fonts');req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);});}
async function cacheGet(){let db;try{db=await cacheDB();return await new Promise((resolve,reject)=>{const tx=db.transaction('fonts','readonly');const req=tx.objectStore('fonts').get('last');req.onsuccess=()=>resolve(req.result||null);req.onerror=()=>reject(req.error);});}finally{db?.close();}}
async function cachePut(record){let db;try{db=await cacheDB();await new Promise((resolve,reject)=>{const tx=db.transaction('fonts','readwrite');tx.objectStore('fonts').put(record,'last');tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});}finally{db?.close();}}
async function cacheClear(){let db;try{db=await cacheDB();await new Promise((resolve,reject)=>{const tx=db.transaction('fonts','readwrite');tx.objectStore('fonts').clear();tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});}finally{db?.close();}}
function stopCurrent(){if(sequencer){try{sequencer.pause();sequencer.currentTime=0;}catch{}}updateUI();}
async function makeEngine(fontBuffer,identity){
  if(!window.AudioContext||!AudioWorkletNode)throw Error('เบราว์เซอร์นี้ไม่มี Web Audio AudioWorklet');
  if(!audioContext){audioContext=new AudioContext({latencyHint:'playback',sampleRate:$('quality').value==='light'?32000:48000});}
  // Security: only pinned package versions, not user-supplied JS URLs.
  const {WorkletSynthesizer,Sequencer}=await import(LIB_URL);
  if(!synth){
    await audioContext.audioWorklet.addModule(WORKLET_URL);
    synth=new WorkletSynthesizer(audioContext);
    synth.connect(audioContext.destination);
    await synth.isReady;
  }
  if(fontSignature!==identity){
    if(fontSignature){throw Error('เปลี่ยน SoundFont ต้องรีโหลดหน้าทดสอบก่อน (ป้องกันเสียงซ้อน)');}
    await synth.soundBankManager.addSoundBank(fontBuffer,'main');
    fontSignature=identity;
  }
  if(!sequencer)sequencer=new Sequencer(synth);
  return sequencer;
}
async function chosenFont(){
  const file=$('font').files?.[0];
  if(file){
    if(!/\.(sf2|sf3)$/i.test(file.name))throw Error('ต้องเป็นไฟล์ SF2 หรือ SF3');
    if(file.size<16||file.size>512*1024*1024)throw Error('SoundFont ต้องมีขนาด 16 B ถึง 512 MiB');
    const binary=await file.arrayBuffer();
    if(!soundFontHeader(binary))throw Error('ไฟล์ SoundFont ไม่ถูกต้อง (RIFF sfbk)');
    if($('cache').checked&&file.size<=LIMIT){
      try{await cachePut({name:file.name,bytes:binary,modified:file.lastModified});}catch(e){status('แคชไม่สำเร็จ ใช้ไฟล์ในหน่วยความจำแทน: '+e.message);}
    }
    return {binary,identity:file.name+':'+file.size+':'+file.lastModified};
  }
  if($('cache').checked){
    const entry=cachedFont||await cacheGet().catch(()=>null);
    if(entry&&entry.bytes&&soundFontHeader(entry.bytes))return {binary:entry.bytes,identity:entry.name+':'+entry.bytes.byteLength+':'+entry.modified};
  }
  throw Error('เลือก SoundFont .sf2/.sf3 ก่อน หรือเปิดแคชที่เคยบันทึกไว้');
}
function formatTime(s){if(!Number.isFinite(s)||s<0)s=0;return String(Math.floor(s/60)).padStart(2,'0')+':'+String(Math.floor(s%60)).padStart(2,'0');}
function updateUI(){
  $('pause').disabled=!sequencer;$('stop').disabled=!sequencer;
  const duration=sequencer?.duration||0,current=sequencer?.currentTime||0;
  $('seek').disabled=!(duration>0);
  if(!$('seek').matches(':active'))$('seek').value=duration>0?Math.min(1000,Math.round(current/duration*1000)):0;
  $('position').textContent=formatTime(current)+' / '+formatTime(duration);
  $('pause').textContent=sequencer&&!sequencer.paused?'Ⅱ พัก':'▶ ต่อ';
  if(sequencer?.isFinished){status('เล่น MIDI จบแล้ว');}
}
async function start(){
  if(loading)return;
  loading=true;$('play').disabled=true;
  try{
    savePrefs();
    if($('mode').value==='audio')throw Error('เลือกโหมด M4A · ให้กลับไปเล่นบนเวทีหลัก');
    const midi=$('midi').files?.[0];
    if(!midi||!/\.(mid|midi|kar)$/i.test(midi.name))throw Error('เลือกไฟล์ MIDI หรือ KAR ก่อน');
    if(midi.size>16*1024*1024)throw Error('ไฟล์ MIDI มีขนาดเกิน 16 MiB');
    const binary=await midi.arrayBuffer();
    if(!hasMidiHeader(binary))throw Error('ไฟล์นี้ไม่ใช่ Standard MIDI File (MThd)');
    status('กำลังอ่าน SoundFont และเตรียม AudioWorklet…');
    const font=await chosenFont();
    const seq=await makeEngine(font.binary,font.identity);
    await audioContext.resume();
    seq.pause();
    seq.loadNewSongList([{binary}]);
    seq.play();
    seq.playbackRate=Number($('speed').value)/100;
    status('กำลังเล่น MIDI · '+midi.name);
    clearInterval(uiTimer);uiTimer=setInterval(updateUI,250);
    updateUI();
  }catch(err){status('ไม่สามารถเริ่ม MIDI: '+(err?.message||err));}
  finally{loading=false;$('play').disabled=false;}
}
async function init(){
  const p=prefs();$('mode').value=['auto','midi','audio'].includes(p.mode)?p.mode:'auto';
  $('quality').value=['light','balanced','high'].includes(p.quality)?p.quality:'balanced';$('cache').checked=!!p.cache;
  for(const id of ['mode','quality','cache'])$(id).addEventListener('change',savePrefs);
  $('play').addEventListener('click',start);
  $('pause').addEventListener('click',async()=>{if(!sequencer)return;try{if(sequencer.paused){await audioContext.resume();sequencer.play();status('เล่น MIDI ต่อ');}else{sequencer.pause();status('พัก MIDI');}updateUI();}catch(e){status(e.message);}});
  $('stop').addEventListener('click',()=>{stopCurrent();status('หยุด MIDI แล้ว');});
  $('seek').addEventListener('input',()=>{if(sequencer?.duration>0)sequencer.currentTime=sequencer.duration*Number($('seek').value)/1000;updateUI();});
  $('speed').addEventListener('input',()=>{$('speed-value').textContent=$('speed').value+'%';if(sequencer)sequencer.playbackRate=Number($('speed').value)/100;});
  $('clear').addEventListener('click',async()=>{try{await cacheClear();cachedFont=null;status('ล้างแคช SoundFont แล้ว (ไม่ลบไฟล์ต้นฉบับ)');}catch(e){status('ล้างแคชไม่สำเร็จ: '+e.message);}});
  if(p.cache){cachedFont=await cacheGet().catch(()=>null);if(cachedFont)status('พบ SoundFont ในแคช: '+cachedFont.name+' · เลือก MIDI แล้วกดเล่น');}
}
init();
window.addEventListener('pagehide',()=>{clearInterval(uiTimer);try{sequencer?.pause();}catch{}try{audioContext?.close();}catch{}});
