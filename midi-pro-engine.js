/* X-Stage Karaoke Online — optional professional GM SoundFont engine.
 * SpessaSynth 4.4.8 (Apache-2.0) is bundled locally by GitHub Actions.
 * Falls back to the existing renderer when assets or worklets are unavailable.
 * No Google Drive tokens or song files are sent to a third-party server.
 */
(function(scope){
'use strict';
const MODULE='vendor/spessasynth/engine.mjs';
const WORKLET='vendor/spessasynth/spessasynth_processor.min.js';
let modulePromise=null,preloadPromise=null;
const MAX_WORKLET_BYTES=8*1024*1024;
const registeredWorklets=new WeakMap();
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

// Warm the locally hosted, public synthesizer assets before MIDI playback.
// Browser HTTP cache handles persistence; never cache Google Drive media or
// authorization headers. This does not install native DLLs on the user's PC.
async function preload({onStatus=()=>{}}={}){
  if(!available())throw Error('AudioWorklet ไม่พร้อมใช้งานบนเบราว์เซอร์นี้');
  if(preloadPromise)return preloadPromise;
  preloadPromise=(async()=>{
    onStatus('กำลังเตรียมเครื่องเสียง MIDI คุณภาพสูง (ดาวน์โหลดครั้งแรกและใช้แคชเบราว์เซอร์)…');
    const [engine,response]=await Promise.all([
      load(),
      fetch(WORKLET,{cache:'force-cache',credentials:'same-origin'})
    ]);
    if(typeof engine.WorkletSynthesizer!=='function')
      throw Error('ชุดไฟล์เครื่องเสียง SpessaSynth ไม่ครบ');
    if(!response.ok)throw Error('ดาวน์โหลด AudioWorklet ไม่สำเร็จ (HTTP '+response.status+')');
    const hintedSize=Number(response.headers.get('Content-Length')||0);
    if(hintedSize>MAX_WORKLET_BYTES)throw Error('เครื่องเสียง MIDI มีขนาดผิดปกติ');
    const data=await response.arrayBuffer();
    if(!data.byteLength||data.byteLength>MAX_WORKLET_BYTES)
      throw Error('ข้อมูล AudioWorklet ไม่ครบหรือขนาดผิดปกติ');
    onStatus('เครื่องเสียง MIDI คุณภาพสูงพร้อมใช้');
    return true;
  })().catch(error=>{preloadPromise=null;throw error;});
  return preloadPromise;
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
  const unlocked=scope.XStageBrowserMidi?.liveAudioContext?.();
  const ownsContext=!unlocked;
  const ctx=unlocked||new Ctor({latencyHint:'playback'});
  let synth=null,master=null,tone=null,limiter=null,disposed=false;
  const dispose=()=>{
    if(disposed)return;disposed=true;
    try{synth?.stopAll(true);}catch{}
    try{synth?.destroy();}catch{}
    try{master?.disconnect();tone?.disconnect();limiter?.disconnect();}catch{}
    if(ownsContext)void ctx.close().catch(()=>{});
  };
  try{
    let loaded=registeredWorklets.get(ctx);
    if(!loaded){
      loaded=ctx.audioWorklet.addModule(WORKLET);
      registeredWorklets.set(ctx,loaded);
    }
    try{await loaded;}
    catch(error){registeredWorklets.delete(ctx);throw error;}
    if(signal?.aborted)throw new DOMException('ยกเลิก','AbortError');
    synth=new WorkletSynthesizer(ctx);
    // The older .52 master followed by -12 dB / 9:1 compression lost
    // several dB of level and flattened kick/snare attacks. Keep sensible
    // headroom but avoid squeezing every transient.
    const OUTPUT_GAIN=.92;
    master=ctx.createGain();
    master.gain.value=OUTPUT_GAIN;
    if(typeof ctx.createBiquadFilter==='function'){
      tone=ctx.createBiquadFilter();
      tone.type='lowshelf';tone.frequency.value=145;tone.gain.value=1.5;
    }
    limiter=ctx.createDynamicsCompressor();
    limiter.threshold.value=-6;limiter.knee.value=5;
    limiter.ratio.value=5;limiter.attack.value=.004;limiter.release.value=.13;
    synth.connect(master);
    if(tone){master.connect(tone);tone.connect(limiter);}
    else master.connect(limiter);
    limiter.connect(ctx.destination);
    const bank=fontBytes.buffer.slice(fontBytes.byteOffset,
      fontBytes.byteOffset+fontBytes.byteLength);
    await synth.soundBankManager.addSoundBank(bank,'X-Stage GM');
    await synth.isReady;
    if(signal?.aborted)throw new DOMException('ยกเลิก','AbortError');
    onStatus('SpessaSynth · เสียง GM เต็มรูปแบบ พร้อมเล่น');
  }catch(error){dispose();throw error;}
  return {
    attach(player,{getTranspose=()=>0,getProgram=()=>null}={}){
      const events=parsed.notes.flatMap(note=>[
        {time:note.start,on:true,note},{time:note.end,on:false,note}
      ]).sort((a,b)=>a.time-b.time||Number(a.on)-Number(b.on));
      let cursor=0,timer=null,generation=0,playing=false;
      const applied=new Array(16).fill(null);
      const controls=Array.from({length:16},()=>({volume:-1,expression:-1,pan:-1}));
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
        for(const state of controls){state.volume=-1;state.expression=-1;state.pan=-1;}
      };
      const step=()=>{
        if(disposed||signal?.aborted||player.paused||player.ended)return;
        const now=Number(player.currentTime)||0;
        const speed=clamp(Number(player.playbackRate)||1,.25,2);
        master.gain.value=(player.muted?0:clamp(Number(player.volume)||0,0,1))*.92;
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
              // Match the PC's restrained reverb/chorus; channel 10 must
              // remain percussion, not be reassigned to a melodic bank.
              synth.controllerChange(ch,91,40);
              synth.controllerChange(ch,93,12);
              if(ch!==9){
                synth.controllerChange(ch,0,clamp(note.bank,0,127));
                synth.programChange(ch,program);
              }
              applied[ch]=state;
            }
            // BASSMIDI on PC consumes the MIDI velocity and CC7/CC11 as
            // separate messages. Reconstruct them rather than folding CCs
            // into velocity, which thins the sound and changes timbre.
            const volume=clamp(Math.round(note.channelVolume??100),0,127);
            const expression=clamp(Math.round(note.channelExpression??127),0,127);
            const pan=clamp(Math.round(note.pan??64),0,127);
            const stateCC=controls[ch];
            if(stateCC.volume!==volume){
              synth.controllerChange(ch,7,volume);stateCC.volume=volume;
            }
            if(stateCC.expression!==expression){
              synth.controllerChange(ch,11,expression);stateCC.expression=expression;
            }
            if(stateCC.pan!==pan){
              synth.controllerChange(ch,10,pan);stateCC.pan=pan;
            }
            synth.noteOn(ch,pitch,clamp(Math.round(note.velocity),1,127));
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
scope.XStageProMidi={available,preload,prepare};
})(typeof window!=='undefined'?window:globalThis);
