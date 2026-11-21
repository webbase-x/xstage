/* X-Stage Karaoke Online: opt-in iOS media-audio output for MIDI synths.
 * Browser security still controls background playback; no wake-lock tricks,
 * native installs, muted looping files, or bypass of user playback intent.
 */
(function(scope){
'use strict';
const nav=scope.navigator;
const ios=!!nav&&(/iPad|iPhone|iPod/.test(nav.userAgent||'')||
  (/Macintosh/.test(nav.userAgent||'')&&Number(nav.maxTouchPoints)>1));
function activate(){
  if(!ios)return false;
  try{
    if(nav?.audioSession&&nav.audioSession.type!=='playback')
      nav.audioSession.type='playback';
  }catch{/* Older iOS does not expose the Audio Session API. */}
  return true;
}
function attach(ctx,source,{onStatus=()=>{}}={}){
  // A media element can sometimes retain iOS's playback audio category when
  // its Safari tab loses focus. No WebKit version guarantees background audio.
  const supported=ios&&typeof ctx.createMediaStreamDestination==='function'&&
    !!scope.document?.createElement&&!!scope.document?.body;
  if(!supported){
    source.connect(ctx.destination);
    return {mode:'direct',start:()=>Promise.resolve(true),pause(){},dispose(){
      try{source.disconnect(ctx.destination);}catch{}
    }};
  }
  const destination=ctx.createMediaStreamDestination();
  const audio=scope.document.createElement('audio');
  audio.setAttribute('playsinline','');
  audio.setAttribute('aria-hidden','true');
  audio.playsInline=true;audio.autoplay=false;audio.controls=false;
  audio.preload='none';audio.volume=1;
  audio.style.display='none';
  audio.srcObject=destination.stream;
  scope.document.body.appendChild(audio);
  source.connect(destination);
  let disposed=false,fallback=false;
  const revert=error=>{
    if(disposed||fallback)return;
    fallback=true;
    try{source.disconnect(destination);}catch{}
    source.connect(ctx.destination);
    try{audio.pause();audio.srcObject=null;audio.remove();}catch{}
    onStatus('iPhone ใช้ทางเสียง Web Audio สำรอง · อาจหยุดเมื่อสลับแท็บ');
    if(error)console.warn('iOS MIDI media output unavailable:',error?.message||error);
  };
  const start=()=>{
    if(disposed)return Promise.resolve(false);
    activate();
    if(fallback)return Promise.resolve(true);
    try{
      return Promise.resolve(audio.play()).then(()=>true,error=>{
        revert(error);return true;
      });
    }catch(error){revert(error);return Promise.resolve(true);}
  };
  const resume=()=>{
    if(disposed||fallback||audio.paused===false)return;
    // Called only when the user initiates play or returns while a track was
    // already playing. The browser may still require a new user gesture.
    void start();
  };
  return {
    mode:'ios-media',
    start,pause(){if(!disposed&&!fallback)audio.pause();},
    resume,
    dispose(){
      if(disposed)return;disposed=true;
      try{audio.pause();audio.srcObject=null;audio.remove();}catch{}
      try{source.disconnect(destination);}catch{}
      if(fallback)try{source.disconnect(ctx.destination);}catch{}
      try{destination.disconnect();}catch{}
    }
  };
}
scope.XStageIOSMidiAudio={isIOS:ios,activate,attach};
})(typeof window!=='undefined'?window:globalThis);
