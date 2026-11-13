/* X-Stage runtime policy: no private song files or OAuth tokens are persisted here.
 * Shared by browser and Android WebView. Every probe is feature-based. */
(function(global){
'use strict';
const PREF='xstage-runtime-v2';
const MAX_PREVIEW=16*1024*1024;
const DEFAULTS=Object.freeze({mode:'auto',format:'auto',quality:'balanced',soundFontCache:true});
function setting(){
  try{
    const v=JSON.parse(global.localStorage.getItem(PREF)||'{}');
    return {
      mode:['auto','midi','audio'].includes(v.mode)?v.mode:DEFAULTS.mode,
      format:['auto','m4a','mp3','midi','video'].includes(v.format)?v.format:DEFAULTS.format,
      quality:['low','balanced','high'].includes(v.quality)?v.quality:DEFAULTS.quality,
      soundFontCache:v.soundFontCache!==false
    };
  }catch{return {...DEFAULTS};}
}
function deviceInfo(){
  const n=global.navigator||{},media=global.document?.createElement?.('audio'),
        video=global.document?.createElement?.('video');
  const canPlay=(element,m)=>{try{return ['maybe','probably'].includes(element?.canPlayType?.(m));}catch{return false;}};
  const cores=Number(n.hardwareConcurrency)||0,mem=Number(n.deviceMemory)||0;
  const android=/android/i.test(n.userAgent||'');
  const wasm=typeof WebAssembly==='object';
  const worklet=!!global.AudioWorkletNode&&!!global.AudioContext;
  const saver=!!n.connection?.saveData;
  const native=global.XStageDeviceProfile||{};
  const lowNative=!!native.lowRam||(Number(native.memoryClassMb)>0&&Number(native.memoryClassMb)<=128);
  const conservative=saver||lowNative||(mem>0&&mem<=2)||(cores>0&&cores<=2);
  const lower=conservative||android;
  return {wasm,worklet,android,cores,memoryGb:mem,nativeMemoryMb:Number(native.memoryClassMb)||0,conservative,saveData:saver,
    m4a:canPlay(media,'audio/mp4; codecs="mp4a.40.2"'),mp3:canPlay(media,'audio/mpeg'),
    video:{avi:canPlay(video,'video/x-msvideo'),mpg:canPlay(video,'video/mpeg'),
      vcd:canPlay(video,'video/mpeg'),wmv:canPlay(video,'video/x-ms-wmv')},
    maxPreloadBytes:conservative?2*1024*1024:lower?5*1024*1024:MAX_PREVIEW,
    preloadRemainingSeconds:conservative?8:lower?12:20,
    preloadIdleDelayMs:conservative?1200:lower?700:400};
}
function chooseFormat(song,device=deviceInfo(),prefs=setting()){
  const files=song?.media||{};
  const hasId=x=>typeof x?.fileId==='string'&&x.fileId.length>0;
  // Engine readiness is explicit: WASM/AudioWorklet support alone is insufficient.
  const midiReady=device.wasm&&device.worklet&&!!global.XStageMidiEngine?.ready;
  const original=song?.audio?.path||'';
  const legacyM4a=hasId(song?.audio)&&(/\.m4a(?:$|[?#])/i.test(original)||!original);
  const legacyMp3=hasId(song?.audio)&&/\.mp3(?:$|[?#])/i.test(original);
  const available={
    m4a:device.m4a&&(hasId(files.m4a)||legacyM4a),
    mp3:device.mp3&&(hasId(files.mp3)||legacyMp3),
    midi:midiReady&&hasId(files.midi),
    video:!!global.XStageVideoEngine?.ready&&hasId(files.video)
  };
  const requested=prefs.format||'auto';
  if(requested!=='auto')return available[requested]?requested:null;
  if(prefs.mode==='midi'&&available.midi)return 'midi';
  if(available.m4a)return 'm4a';
  if(available.mp3)return 'mp3';
  if(available.midi)return 'midi';
  return available.video?'video':null;
}
function selectedMedia(song,format=chooseFormat(song)){
  const source=song?.media?.[format];
  if(source?.fileId)return source;
  const path=song?.audio?.path||'';
  if((format==='m4a'&&(!path||/\.m4a(?:$|[?#])/i.test(path)))||
     (format==='mp3'&&/\.mp3(?:$|[?#])/i.test(path)))return song.audio;
  return null;
}
function saveFormat(format){
  if(!['auto','m4a','mp3','midi','video'].includes(format))throw Error('Unsupported playback selection');
  let raw={};
  try{raw=JSON.parse(global.localStorage.getItem(PREF)||'{}')||{};}catch{}
  global.localStorage.setItem(PREF,JSON.stringify({...raw,format}));
}

let readyPromise=null;
function preloadEnvironment(){
  if(readyPromise)return readyPromise;
  readyPromise=(async()=>{
    const info=deviceInfo();
    // Static shell is cacheable; never fetch/private-cache song or lyrics.
    // Service worker owns offline code cache, and can be absent in WebView.
    if(global.navigator?.serviceWorker?.getRegistration){
      try{
        const reg=await global.navigator.serviceWorker.getRegistration();
        if(reg?.active)await reg.update().catch(()=>{});
      }catch{}
    }
    return {device:info,prefs:setting(),preferred:info.conservative?'audio':'auto'};
  })();
  return readyPromise;
}
const api=Object.freeze({setting,saveFormat,deviceInfo,chooseFormat,selectedMedia,preloadEnvironment,
  MAX_PREVIEW,DEFAULTS});
global.XStageRuntime=api;
})(window);
