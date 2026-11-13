/* X-Stage runtime policy: no private song files or OAuth tokens are persisted here.
 * Shared by browser and Android WebView. Every probe is feature-based. */
(function(global){
'use strict';
const PREF='xstage-runtime-v2';
const MAX_PREVIEW=16*1024*1024;
const DEFAULTS=Object.freeze({mode:'auto',quality:'balanced',soundFontCache:true});
function setting(){
  try{
    const v=JSON.parse(global.localStorage.getItem(PREF)||'{}');
    return {
      mode:['auto','midi','audio'].includes(v.mode)?v.mode:DEFAULTS.mode,
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
  const supportsMidi=device.wasm&&device.worklet&&!!global.XStageMidiEngine?.ready;
  const hasM4a=!!(files.m4a?.fileId||song?.audio?.fileId);
  const hasMp3=!!files.mp3?.fileId;
  const hasMidi=!!files.midi?.fileId;
  const hasVideo=!!files.video?.fileId;
  if(prefs.mode==='midi'&&hasMidi&&supportsMidi)return 'midi';
  if(prefs.mode!=='midi'){
    if(hasM4a&&device.m4a)return 'm4a';
    if(hasMp3&&device.mp3)return 'mp3';
  }
  if(hasMidi&&supportsMidi)return 'midi';
  if(hasM4a&&device.m4a)return 'm4a';
  if(hasMp3&&device.mp3)return 'mp3';
  if(hasVideo&&!!global.XStageVideoEngine?.ready)return 'video';
  return null;
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
const api=Object.freeze({setting,deviceInfo,chooseFormat,preloadEnvironment,
  MAX_PREVIEW,DEFAULTS});
global.XStageRuntime=api;
})(window);
