/* X-Stage Web MIDI SF2/SF3 engine, private-song transient only.
 * SoundFont may persist locally by explicit user setting; never cache songs. */
(function(global){
'use strict';
const LIB='https://esm.sh/spessasynth_lib@4.4.8?bundle';
const WORKLET='https://cdn.jsdelivr.net/npm/spessasynth_lib@4.4.8/dist/spessasynth_processor.min.js';
const DB='xstage-sf-v2',LIMIT=64*1024*1024;
let ctx=null,gain=null,synth=null,seq=null,fontKey='',ready=false,active=false,clock=null,finished=false,repeat=false;
let onReady=()=>{},lastError='';
const el=()=>global.document?.getElementById('player');
const signal=kind=>{try{el()?.dispatchEvent(new Event(kind));}catch{}};
function setStatus(message){const label=global.document?.getElementById('soundfont-status');if(label)label.textContent=message;}
function database(){return new Promise((resolve,reject)=>{
  if(typeof indexedDB==='undefined')return reject(Error('IndexedDB unavailable'));
  const req=indexedDB.open(DB,1);
  req.onupgradeneeded=()=>req.result.createObjectStore('soundfonts');
  req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);
});}
async function saveFont(bytes){
  if(bytes.byteLength>LIMIT||global.XStageRuntime?.setting?.().soundFontCache===false)return;
  let db;
  try{db=await database();await new Promise((resolve,reject)=>{
    const tx=db.transaction('soundfonts','readwrite');
    tx.objectStore('soundfonts').put(bytes,'active');tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);
  });}finally{db?.close();}
}
async function loadFont(){
  let db;try{db=await database();return await new Promise((resolve,reject)=>{
    const req=db.transaction('soundfonts','readonly').objectStore('soundfonts').get('active');
    req.onsuccess=()=>resolve(req.result||null);req.onerror=()=>reject(req.error);
  });}finally{db?.close();}
}
async function clearFont(){
  let db;try{db=await database();await new Promise((resolve,reject)=>{
    const tx=db.transaction('soundfonts','readwrite');tx.objectStore('soundfonts').clear();
    tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);
  });}finally{db?.close();}
}
function isSoundFont(bytes){
  if(!(bytes instanceof ArrayBuffer)||bytes.byteLength<12||bytes.byteLength>512*1024*1024)return false;
  const b=new Uint8Array(bytes,0,12);
  return String.fromCharCode(...b.slice(0,4))==='RIFF'&&String.fromCharCode(...b.slice(8,12))==='sfbk';
}
async function initialize(bytes){
  if(!isSoundFont(bytes))throw Error('SoundFont SF2/SF3 ไม่ถูกต้อง');
  if(!global.AudioContext||!global.AudioWorkletNode)throw Error('อุปกรณ์ไม่รองรับ AudioWorklet');
  if(ready){
    // Never overwrite an active sound bank while it is in use.
    throw Error('ต้องโหลดหน้าใหม่ก่อนเปลี่ยน SoundFont');
  }
  setStatus('กำลังเตรียม MIDI Engine และ SoundFont…');
  try{
    const {WorkletSynthesizer,Sequencer}=await import(LIB);
    ctx=new AudioContext({latencyHint:'playback'});
    await ctx.audioWorklet.addModule(WORKLET);
    synth=new WorkletSynthesizer(ctx);
    gain=ctx.createGain();
    gain.gain.value=.8;gain.connect(ctx.destination);
    synth.connect(gain);
    await synth.isReady;
    await synth.soundBankManager.addSoundBank(bytes,'main');
    seq=new Sequencer(synth);
    fontKey=String(bytes.byteLength);
    ready=true;lastError='';
    setStatus('MIDI SoundFont พร้อมใช้งาน');
    onReady();
  }catch(error){
    lastError=error?.message||String(error);
    setStatus('MIDI ไม่พร้อม: '+lastError);
    try{await ctx?.close();}catch{}
    ctx=null;synth=null;gain=null;seq=null;
    throw error;
  }
}
function stop(){
  if(clock){clearInterval(clock);clock=null;}
  if(seq){try{seq.pause();seq.currentTime=0;}catch{}}
  const wasActive=active;active=false;finished=false;
  if(wasActive)signal('pause');
}
function tick(){
  if(!active||!seq)return;
  signal('timeupdate');
  if(seq.isFinished&&!finished){
    finished=true;
    if(!repeat){stop();signal('ended');}
    else {seq.currentTime=0;seq.play();}
  }
}
async function start(buffer,{autoplay=true,resumeAt=0}={}){
  if(!ready||!seq)throw Error('กรุณาเลือก SoundFont ก่อนเล่น MIDI');
  const data=buffer instanceof ArrayBuffer?buffer:await buffer.arrayBuffer();
  const header=new Uint8Array(data,0,Math.min(data.byteLength,4));
  if(data.byteLength>32*1024*1024||String.fromCharCode(...header)!=='MThd')
    throw Error('ไม่ใช่ไฟล์ MIDI มาตรฐานหรือใหญ่เกิน 32 MiB');
  stop();seq.loadNewSongList([{binary:data}]);
  active=true;finished=false;
  if(resumeAt>0)seq.currentTime=resumeAt;
  clock=setInterval(tick,200);
  if(autoplay){await ctx.resume();seq.play();signal('play');}
  else signal('pause');
}
async function play(){if(!active||!seq)return;await ctx.resume();seq.play();signal('play');}
function pause(){if(active&&seq){seq.pause();signal('pause');}}
const api={
  get ready(){return ready;},get active(){return active;},
  get paused(){return !active||!seq||seq.paused;},
  get ended(){return !!seq?.isFinished;},
  get currentTime(){return active?Number(seq?.currentTime)||0:0;},
  set currentTime(v){if(active&&seq)seq.currentTime=Math.max(0,Number(v)||0);},
  get duration(){return active?Number(seq?.duration)||0:0;},
  get playbackRate(){return Number(seq?.playbackRate)||1;},
  set playbackRate(v){if(seq)seq.playbackRate=Math.max(.5,Math.min(2,Number(v)||1));},
  get volume(){return gain?.gain.value||0;},
  set volume(v){if(gain)gain.gain.value=Math.max(0,Math.min(1,Number(v)||0));},
  get loop(){return repeat;},set loop(v){repeat=!!v;},
  get error(){return lastError;},initialize,start,stop,play,pause,
  get onReady(){return onReady;},set onReady(v){onReady=typeof v==='function'?v:()=>{};},
  async fromFile(file){if(!file||!/\.(sf2|sf3)$/i.test(file.name))throw Error('เลือก SF2/SF3');
    const bytes=await file.arrayBuffer();await initialize(bytes);try{await saveFont(bytes);}catch{}},
  async restore(){if(ready||global.XStageRuntime?.setting?.().soundFontCache===false)return;
    const bytes=await loadFont().catch(()=>null);if(bytes)await initialize(bytes);},
  async clearCachedFont(){await clearFont();setStatus('ล้างแคช SoundFont แล้ว')}
};
global.XStageMidiEngine=api;
global.document?.addEventListener('DOMContentLoaded',()=>{
  const picker=global.document.getElementById('xstage-soundfont');
  picker?.addEventListener('change',async()=>{try{await api.fromFile(picker.files[0]);}
    catch(e){setStatus(e?.message||String(e));}});
  global.document.getElementById('xstage-soundfont-clear')?.addEventListener('click',
    ()=>api.clearCachedFont().catch(e=>setStatus(e?.message||String(e))));
  // Static engine assets are fetched only when a cached/user SoundFont exists.
  void api.restore().catch(e=>setStatus('SoundFont ไม่พร้อม: '+e.message));
});
})(window);