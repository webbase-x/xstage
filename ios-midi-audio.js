/* X-Stage Karaoke Online — iPhone Safari music session and media bridge.
 * Best effort only: iOS may suspend Web Audio when Safari is backgrounded.
 * No native installs, background loops, or bypassing a user's pause intent.
 */
(function(scope){
'use strict';
const nav=scope.navigator;
const ios=!!nav&&(/iPad|iPhone|iPod/.test(nav.userAgent||'')||
  (/Macintosh/.test(nav.userAgent||'')&&Number(nav.maxTouchPoints)>1));
let relay=null;
function activate(){
  if(!ios)return false;
  try{
    if(nav?.audioSession&&nav.audioSession.type!=='playback')
      nav.audioSession.type='playback';
  }catch{/* Unsupported AudioSession API on older iOS. */}
  return true;
}
function available(ctx){
  return ios&&typeof ctx?.createMediaStreamDestination==='function'&&
    !!scope.document?.createElement&&!!scope.document?.body;
}
function createRelay(ctx){
  if(!available(ctx))return null;
  if(relay?.ctx===ctx&&!relay.closed)return relay;
  const destination=ctx.createMediaStreamDestination();
  const audio=scope.document.createElement('audio');
  audio.setAttribute('playsinline','');
  audio.setAttribute('aria-hidden','true');
  audio.playsInline=true;audio.autoplay=false;audio.controls=false;
  audio.preload='none';audio.volume=1;audio.style.display='none';
  audio.srcObject=destination.stream;
  scope.document.body.appendChild(audio);
  relay={ctx,destination,audio,sources:new Set(),closed:false,failed:false,
    failureNotice:new Set(),keepAliveForQueue:false};
  return relay;
}
function fallBack(record,error){
  if(record.closed||record.failed)return;
  record.failed=true;
  for(const source of record.sources){
    try{source.disconnect(record.destination);}catch{}
    source.connect(record.ctx.destination);
  }
  try{
    record.audio.pause();record.audio.srcObject=null;record.audio.remove();
  }catch{}
  for(const notify of record.failureNotice)
    notify('iPhone ไม่อนุญาตทางเสียงสื่อ · ใช้ Web Audio สำรอง');
  if(error)scope.console?.warn?.('iPhone MIDI output:',error?.message||error);
}
function start(record){
  if(!record||record.closed)return Promise.resolve(false);
  if(record.failed)return Promise.resolve(true); // Audio is on direct fallback.
  activate();
  try{
    return Promise.resolve(record.audio.play()).then(()=>true,error=>{
      fallBack(record,error);return true;
    });
  }catch(error){fallBack(record,error);return Promise.resolve(true);}
}
// Call during the original user tap, BEFORE asynchronous SoundFont downloads.
// Reuse the same HTMLAudioElement when the worklet finally starts.
function prime(ctx){
  if(!available(ctx))return Promise.resolve(false);
  return start(createRelay(ctx));
}
// Preserve the already-playing iPhone media stream during an automatic
// MIDI-to-MIDI queue handoff. Pausing it between songs can cause Safari to
// require a fresh user gesture, which is unavailable on natural song end.
function keepPlayingBetweenSongs(enabled){
  if(!relay||relay.closed||relay.failed)return false;
  relay.keepAliveForQueue=!!enabled;
  if(!enabled&&!relay.sources.size)relay.audio.pause();
  return true;
}
function attach(ctx,source,{onStatus=()=>{}}={}){
  const record=createRelay(ctx);
  if(!record){
    source.connect(ctx.destination);
    return {mode:'direct',start:()=>Promise.resolve(true),pause(){},resume(){},
      dispose(){try{source.disconnect(ctx.destination);}catch{}}};
  }
  record.failureNotice.add(onStatus);
  if(record.failed)source.connect(ctx.destination);
  else source.connect(record.destination);
  record.sources.add(source);
  record.keepAliveForQueue=false;
  return {
    mode:record.failed?'direct':'ios-media',
    start:()=>start(record),
    pause(){
      // SoundFont changes can briefly attach two synths; do not mute the new
      // song when the previous synth releases its output connection.
      if(!record.failed&&!record.keepAliveForQueue&&record.sources.size<=1)
        record.audio.pause();
    },
    async resume(){
      if(record.failed)return true; // Audio is already on the single direct fallback.
      if(record.closed||scope.document?.hidden===true)return false;
      activate();
      // A locked iPhone can suspend the HTMLMediaElement even when the MIDI
      // transport still reports 'playing'. Try the existing relay again, do
      // not create a second output or permanently reroute after a wake denial.
      try{
        await record.audio.play();
        return !record.audio.paused;
      }catch{return false;} // Safari may require another user interaction.
    },
    dispose(){
      if(!record.sources.delete(source))return;
      try{source.disconnect(record.failed?ctx.destination:record.destination);}catch{}
      record.failureNotice.delete(onStatus);
      if(!record.sources.size&&!record.failed&&!record.keepAliveForQueue)
        record.audio.pause();
    }
  };
}
function release(){
  if(!relay||relay.closed)return;
  const record=relay;
  record.closed=true;
  for(const source of record.sources){
    try{source.disconnect(record.failed?record.ctx.destination:record.destination);}catch{}
  }
  record.sources.clear();
  try{record.audio.pause();record.audio.srcObject=null;record.audio.remove();}catch{}
  try{record.destination.disconnect();}catch{}
  relay=null;
}
scope.XStageIOSMidiAudio={isIOS:ios,activate,prime,attach,release,keepPlayingBetweenSongs};
})(typeof window!=='undefined'?window:globalThis);
