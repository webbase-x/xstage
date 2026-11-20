/* X-Stage Karaoke Online — optional professional GM SoundFont engine.
 * SpessaSynth 4.2.15 (Apache-2.0) is bundled locally by GitHub Actions.
 * Falls back to the existing renderer when assets or worklets are unavailable.
 * No Google Drive tokens or song files are sent to a third-party server.
 */
(function(scope){
'use strict';
const MODULE='vendor/spessasynth/engine.mjs';
const WORKLET='vendor/spessasynth/spessasynth_processor.min.js';
let modulePromise=null;
const clamp=(n,min,max)=>Math.max(min,Math.min(max,n));
function available(){
  return !!(scope.AudioContext||scope.webkitAudioContext)&&
    !!(scope.AudioWorkletNode||scope.AudioContext?.prototype?.audioWorklet);
}
async function load(){
  if(!modulePromise)modulePromise=import('./'+MODULE).catch(error=>{
    modulePromise=null;throw error;
  });
  return modulePromise;
}
async function prepare(source,fontBytes,{signal=null,onStatus=()=>{}}={}){
  if(!available())throw Error('เบราว์เซอร์ไม่รองรับ AudioWorklet');
  if(!fontBytes?.byteLength)throw Error('ต้องเลือก SoundFont ก่อนใช้งานตัวเล่นคุณภาพสูง');
  if(signal?.aborted)throw new DOMException('ยกเลิก','AbortError');
  onStatus('กำลังเตรียม SpessaSynth AudioWorklet…');
  const [{WorkletSynthesizer},parsed]=await Promise.all([
    load(),Promise.resolve(scope.XStageBrowserMidi.parseMidi(source))
  ]);
  if(typeof WorkletSynthesizer!=='function')throw Error('ไฟล์ SpessaSynth ไม่สมบูรณ์');
  const Ctor=scope.AudioContext||scope.webkitAudioContext;
  const ctx=new Ctor({latencyHint:'playback'});
  let synth=null,master=null,limiter=null,disposed=false;
  const dispose=()=>{
    if(disposed)return;disposed=true;
    try{synth?.stopAll(true);}catch{}
    try{synth?.destroy();}catch{}
    try{master?.disconnect();limiter?.disconnect();}catch{}
    void ctx.close().catch(()=>{});
  };
  try{
    await ctx.audioWorklet.addModule(WORKLET);
    if(signal?.aborted)throw new DOMException('ยกเลิก','AbortError');
    synth=new WorkletSynthesizer(ctx);
    master=ctx.createGain();
    master.gain.value=.52;
    limiter=ctx.createDynamicsCompressor();
    limiter.threshold.value=-12;limiter.knee.value=8;
    limiter.ratio.value=9;limiter.attack.value=.003;limiter.release.value=.14;
    synth.connect(master);
    master.connect(limiter);limiter.connect(ctx.destination);
    const bank=fontBytes.buffer.slice(fontBytes.byteOffset,
      fontBytes.byteOffset+fontBytes.byteLength);
    await synth.soundBankManager.addSoundBank(bank,'X-Stage GM');
    await synth.isReady;
    if(signal?.aborted)throw new DOMException('ยกเลิก','AbortError');
    onStatus('SpessaSynth + SoundFont พร้อมเล่น');
  }catch(error){dispose();throw error;}
  return {
    attach(player,{getTranspose=()=>0,getProgram=()=>null,onStatus:notice=>(onStatus(notice))}={}){
      const events=parsed.notes.flatMap(note=>[
        {time:note.start,on:true,note},{time:note.end,on:false,note}
      ]).sort((a,b)=>a.time-b.time||Number(a.on)-Number(b.on));
      let cursor=0,timer=null,generation=0,playing=false;
      const applied=new Array(16).fill(null);
      const reset=()=>{
        generation++;
        synth.stopAll(true);
        const now=Number(player.currentTime)||0;
        let left=0,right=events.length;
        while(left<right){
          const mid=(left+right)>>1;
          if(events[mid].time<now-.015)left=mid+1;else right=mid;
        }
        cursor=left;applied.fill(null);
      };
      const step=()=>{
        if(disposed||signal?.aborted||player.paused||player.ended)return;
        const now=Number(player.currentTime)||0;
        const speed=clamp(Number(player.playbackRate)||1,.25,2);
        master.gain.value=(player.muted?0:clamp(Number(player.volume)||0,0,1))*.52;
        const horizon=now+.025*speed;
        while(cursor<events.length&&events[cursor].time<=horizon){
          const event=events[cursor++],note=event.note,ch=note.channel;
          const shift=ch===9?0:clamp(Math.trunc(Number(getTranspose())||0),-12,12);
          const pitch=clamp(note.key+shift,0,127);
          if(event.on){
            const override=getProgram();
            const program=ch!==9&&Number.isInteger(override)&&override>=0&&override<=127
              ?override:note.program;
            const state=ch+':'+note.bank+':'+program;
            if(applied[ch]!==state){
              synth.controllerChange(ch,0,clamp(note.bank,0,127));
              synth.programChange(ch,program);applied[ch]=state;
            }
            const velocity=clamp(Math.round(note.velocity*clamp(note.level,.1,1)),1,127);
            synth.noteOn(ch,pitch,velocity);
          }else synth.noteOff(ch,pitch);
        }
      };
      const play=()=>{
        if(playing||disposed)return;
        playing=true;void ctx.resume().catch(()=>onStatus('กด ▶ อีกครั้งเพื่ออนุญาตเสียง'));
        reset();step();timer=setInterval(step,15);
      };
      const pause=()=>{
        if(timer!==null){clearInterval(timer);timer=null;}
        playing=false;reset();
      };
      const seek=()=>{pause();if(!player.paused)play();};
      const listeners=[['play',play],['pause',pause],['ended',pause],
        ['seeking',seek],['ratechange',seek],['xstage-midi-transpose',seek]];
      for(const [name,fn] of listeners)player.addEventListener(name,fn);
      if(!player.paused)play();
      return {
        dispose(){
          if(disposed)return;
          pause();
          for(const [name,fn] of listeners)player.removeEventListener(name,fn);
          dispose();
        },
        duration:parsed.duration,engine:'SpessaSynth'
      };
    },
    dispose
  };
}
scope.XStageProMidi={available,prepare};
})(typeof window!=='undefined'?window:globalThis);
