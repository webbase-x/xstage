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
  // The professional engine must be completely fetched before its worklet
  // is registered. Earlier asynchronous prewarming overlaps the Drive load.
  await preload({onStatus});
  if(signal?.aborted)throw new DOMException('ยกเลิก','AbortError');
  const [{WorkletSynthesizer,Sequencer},parsed]=await Promise.all([
    load(),Promise.resolve(scope.XStageBrowserMidi.parseMidi(source))
  ]);
  if(typeof WorkletSynthesizer!=='function')throw Error('ไฟล์ SpessaSynth ไม่สมบูรณ์');
  const Ctor=scope.AudioContext||scope.webkitAudioContext;
  const unlocked=scope.XStageBrowserMidi?.liveAudioContext?.();
  const ownsContext=!unlocked;
  const ctx=unlocked||new Ctor({latencyHint:'playback'});
  let synth=null,sequencer=null,master=null,tone=null,limiter=null,mediaOutput=null,disposed=false;
  const dispose=()=>{
    if(disposed)return;disposed=true;
    try{sequencer?.pause();}catch{}
    try{synth?.stopAll(true);}catch{}
    try{synth?.destroy();}catch{}
    try{mediaOutput?.dispose();}catch{}
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
    mediaOutput=scope.XStageIOSMidiAudio?.attach(ctx,limiter,{onStatus})||null;
    if(!mediaOutput)limiter.connect(ctx.destination);
    const bank=fontBytes.buffer.slice(fontBytes.byteOffset,
      fontBytes.byteOffset+fontBytes.byteLength);
    await synth.soundBankManager.addSoundBank(bank,'X-Stage GM');
    await synth.isReady;
    if(signal?.aborted)throw new DOMException('ยกเลิก','AbortError');
    // SpessaSynth's native sequencer runs MIDI events in the synthesis
    // thread: hidden-tab setInterval throttling cannot starve note delivery.
    if(typeof Sequencer==='function'&&source?.byteLength){
      try{
        const bytes=source instanceof Uint8Array?source:new Uint8Array(source);
        if(String.fromCharCode(...bytes.subarray(0,4))==='MThd'){
          sequencer=new Sequencer(synth);
          const binary=bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength);
          // SpessaSynth loadNewSongList() is asynchronous. It sets
          // isLoading=true and later signals songChange *after* the worklet
          // parses MIDI and preloads its instruments. Starting playback
          // before songChange can lose the first GM patches or notes.
          if(typeof sequencer.eventHandler?.addEvent!=='function')
            throw Error('SpessaSynth ยังไม่รองรับสัญญาณพร้อมของ Sequencer');
          await new Promise((resolve,reject)=>{
            const id='xstage-midi-initial-song-ready';
            let settled=false,timeout=null;
            const cleanup=()=>{
              clearTimeout(timeout);
              sequencer?.eventHandler?.removeEvent?.('songChange',id);
              signal?.removeEventListener?.('abort',abort);
            };
            const done=error=>{
              if(settled)return;
              settled=true;cleanup();
              if(error)reject(error);else resolve();
            };
            const abort=()=>done(new DOMException('ยกเลิก','AbortError'));
            sequencer.eventHandler?.addEvent?.('songChange',id,()=>{
              done();
            });
            signal?.addEventListener?.('abort',abort,{once:true});
            timeout=setTimeout(()=>done(Error('เครื่องเสียง MIDI ยังโหลดเพลงแรกไม่เสร็จ')),15000);
            if(signal?.aborted){abort();return;}
            try{
              sequencer.loadNewSongList([{binary,fileName:'X-Stage.mid'}]);
            }catch(error){done(error);}
          });
          if(signal?.aborted)throw new DOMException('ยกเลิก','AbortError');
          sequencer.loopCount=0;
        }
      }catch(error){
        if(error?.name==='AbortError')throw error;
        console.warn('AudioWorklet MIDI sequencer unavailable:',error);
        try{sequencer?.pause();}catch{}
        sequencer=null;
      }
    }
    onStatus(sequencer
      ?'SpessaSynth Sequencer · เล่น MIDI ต่อได้ขณะสลับแท็บ'
      :'SpessaSynth · ใช้โหมด MIDI สำรอง');
  }catch(error){dispose();throw error;}
  return {
    attach(player,{getTranspose=()=>0,getProgram=()=>null,onEnded=()=>{}}={}){
      // The PC keyboard previews notes on an independent voice. In the Web
      // synth, reserve an unused MIDI channel so touching piano keys cannot
      // change an instrument or suppress notes of the playing song.
      const usedChannels=new Set(parsed.notes.map(note=>note.channel));
      const previewChannel=Array.from({length:16},(_,i)=>15-i)
        .find(ch=>ch!==9&&!usedChannels.has(ch));
      const previewHeld=new Set();
      let previewProgram=null;
      const previewNote=(pitch,on,programOverride=null)=>{
        if(disposed||previewChannel===undefined||
           !Number.isInteger(pitch)||pitch<0||pitch>127||
           typeof synth.noteOn!=='function'||typeof synth.noteOff!=='function')
          return false;
        try{
          if(on){
            const program=programOverride===''||programOverride===null
              ?0:clamp(Number(programOverride)||0,0,127);
            if(previewProgram!==program){
              for(const key of previewHeld)synth.noteOff(previewChannel,key);
              previewHeld.clear();
              synth.controllerChange(previewChannel,0,0);
              synth.controllerChange(previewChannel,7,100);
              synth.controllerChange(previewChannel,11,127);
              synth.controllerChange(previewChannel,10,64);
              synth.programChange(previewChannel,program);
              previewProgram=program;
            }
            void ctx.resume().catch(()=>{});
            if(!previewHeld.has(pitch)){
              synth.noteOn(previewChannel,pitch,100);previewHeld.add(pitch);
            }
          }else if(previewHeld.delete(pitch))synth.noteOff(previewChannel,pitch);
          return true;
        }catch(error){console.warn('MIDI keyboard preview:',error);return false;}
      };
      const releasePreview=()=>{
        for(const key of previewHeld){
          try{synth.noteOff(previewChannel,key);}catch{}
        }
        previewHeld.clear();
      };
      // Prefer audio-thread sequencing. No UI-thread note scheduler runs in
      // this mode. A clock event loop in the app is for lyrics only.
      if(sequencer){
        let stopped=false,started=false,completionPending=false,completionDelivered=false;
        let shiftApplied=null,programApplied=null;
        const finishListenerId='xstage-midi-natural-finish';
        // Soft, bounded percussion played through the SAME GM/GS SoundFont
        // (not an oscillator) during genuine silent MIDI edges or handoffs.
        // This keeps the outgoing synth alive only until the new track begins,
        // preventing repeated SF2 downloads or an endless waiting loop.
        const tempoMap=parsed.tempoMap||[];
        const firstNote=Math.min(...parsed.notes.map(note=>note.start));
        const finalNote=Math.max(...parsed.notes.map(note=>note.end));
        const beatAt=time=>{
          let tempo=500000;
          for(const point of tempoMap){
            if(point.seconds>time)break;
            if(point.tempo>=10000&&point.tempo<=10000000)tempo=point.tempo;
          }
          return clamp(tempo/1000000,.28,1.15);
        };
        const introBeat=beatAt(0),bridgeBeat=beatAt(parsed.duration);
        const noteOffTimers=new Set();
        let gapTimer=null,lastGapBeat=-1,bridgeTimer=null,bridgeDeadline=null;
        const drum=(note,velocity)=>{
          if(disposed||typeof synth.noteOn!=='function')return;
          try{
            synth.noteOn(9,note,velocity);
            const timer=setTimeout(()=>{
              noteOffTimers.delete(timer);
              if(!disposed)try{synth.noteOff(9,note);}catch{}
            },95);
            noteOffTimers.add(timer);
          }catch(error){console.warn('SF2 transition rhythm:',error);}
        };
        const beat=(index,quiet=false)=>{
          if(player.muted)return;
          // Minimal rhythm that does not invent pitched notes or overwrite
          // song channels. The GM bank itself supplies the acoustic samples.
          drum(42,quiet?30:42);
          if(index%4===0)drum(36,quiet?29:38);
          else if(index%4===2)drum(38,quiet?25:34);
        };
        const stopGapFill=()=>{
          if(gapTimer!==null){clearInterval(gapTimer);gapTimer=null;}
          lastGapBeat=-1;
        };
        const gapTick=()=>{
          if(stopped||disposed||player.paused)return;
          const t=Number(sequencer.currentTime)||0;
          // Never layer the beat under the actual MIDI arrangement.
          const leading=firstNote>1.35&&t<firstNote-.12;
          const trailing=parsed.duration-finalNote>0.85&&
            t>finalNote+.08&&t<parsed.duration-.08;
          if(!leading&&!trailing){lastGapBeat=-1;return;}
          const seconds=leading?introBeat:bridgeBeat;
          const beatIndex=Math.floor(t/seconds);
          if(beatIndex===lastGapBeat)return;
          lastGapBeat=beatIndex;
          beat(beatIndex,true);
        };
        const stopBridgeTimer=()=>{
          if(bridgeTimer!==null){clearInterval(bridgeTimer);bridgeTimer=null;}
          if(bridgeDeadline!==null){clearTimeout(bridgeDeadline);bridgeDeadline=null;}
        };
        const clearDrums=()=>{
          stopGapFill();stopBridgeTimer();
          for(const timer of noteOffTimers)clearTimeout(timer);
          noteOffTimers.clear();
          if(!disposed)for(const n of [36,38,42]){
            try{synth.noteOff(9,n);}catch{}
          }
        };
        const naturalEnd=()=>{
          if(stopped||!started||player.paused||completionPending||completionDelivered)return;
          completionPending=true;completionDelivered=true;
          // Avoid destroying an AudioWorklet inside its own event dispatch.
          void Promise.resolve().then(()=>{
            completionPending=false;
            if(stopped||!started||player.paused)return;
            if(player.loop){
              completionDelivered=false;
              sequencer.currentTime=0;
              player.currentTime=0;
              sequencer.play();
              return;
            }
            onEnded();
          });
        };
        try{sequencer.eventHandler?.addEvent?.('songEnded',finishListenerId,naturalEnd);}
        catch(error){console.warn('MIDI end-of-song callback unavailable:',error);}

        const updateVolume=()=>{
          master.gain.value=(player.muted?0:clamp(Number(player.volume)||0,0,1))*.92;
        };
        const applyKey=()=>{
          const shift=clamp(Math.trunc(Number(getTranspose())||0),-12,12);
          if(shift===shiftApplied)return;
          for(let ch=0;ch<16;ch++){
            if(ch===9||ch===previewChannel)continue; // Percussion and separate preview.
            try{synth.midiChannels?.[ch]?.setSystemParameter?.('keyShift',shift);}
            catch(error){onStatus('การปรับคีย์ไม่รองรับในเครื่องเสียงนี้');}
          }
          shiftApplied=shift;
        };
        const applyProgram=()=>{
          const program=getProgram();
          if(program===programApplied)return;
          for(let ch=0;ch<16;ch++){
            if(ch===9||ch===previewChannel)continue;
            const channel=synth.midiChannels?.[ch];
            try{
              if(program===null||program===undefined||program===''){
                channel?.setSystemParameter?.('presetLock',false);
              }else{
                channel?.setSystemParameter?.('presetLock',false);
                synth.programChange(ch,clamp(Number(program),0,127));
                channel?.setSystemParameter?.('presetLock',true);
              }
            }catch(error){onStatus('เปลี่ยนเครื่องดนตรีไม่สำเร็จ');}
          }
          programApplied=program;
        };
        const play=()=>{
          if(stopped||started)return;
          started=true;completionDelivered=false;
          updateVolume();applyKey();applyProgram();
          sequencer.playbackRate=clamp(Number(player.playbackRate)||1,.25,2);
          sequencer.currentTime=clamp(Number(player.currentTime)||0,0,parsed.duration);
          scope.XStageIOSMidiAudio?.activate();
          void ctx.resume().catch(()=>onStatus('ต้องอนุญาตเล่นเสียงเบื้องหลัง'));
          void mediaOutput?.start().catch(()=>{});
          sequencer.play();
          if(gapTimer===null)gapTimer=setInterval(gapTick,90);
          gapTick();
        };
        const pause=()=>{
          started=false;stopGapFill();sequencer.pause();mediaOutput?.pause();
        };
        const seek=()=>{
          if(stopped)return;
          sequencer.currentTime=clamp(Number(player.currentTime)||0,0,parsed.duration);
        };
        const rate=()=>{sequencer.playbackRate=clamp(Number(player.playbackRate)||1,.25,2);};
        const change=()=>{applyKey();applyProgram();};
        const visibility=()=>{
          if(stopped||scope.document?.hidden||player.paused)return;
          scope.XStageIOSMidiAudio?.activate();
          if(ctx.state==='suspended'||ctx.state==='interrupted'){
            // Resume only after the tab is visible and the user did not pause.
            void ctx.resume().catch(()=>onStatus(
              'iPhone พักเสียงขณะสลับแท็บ · แตะ ▶ เพื่อเล่นต่อ'));
          }
          mediaOutput?.resume();
          // Reconcile the lyric/player clock with the actual audio thread
          // when a backgrounded tab is shown again.
          const actual=Number(sequencer.currentTime);
          if(Number.isFinite(actual)&&actual>=0&&
             Math.abs(actual-Number(player.currentTime))>.45){
            player.currentTime=Math.min(actual,parsed.duration);
          }
          updateVolume();
        };
        const listeners=[['play',play],['pause',pause],['ended',pause],
          ['seeking',seek],['ratechange',rate],['xstage-midi-transpose',change]];
        for(const [name,fn] of listeners)player.addEventListener(name,fn);
        scope.document?.addEventListener?.('visibilitychange',visibility);
        scope.addEventListener?.('focus',visibility);
        scope.addEventListener?.('pageshow',visibility);
        if(!player.paused)play();
        let fullyReleased=false;
        const detachPlayback=()=>{
          try{sequencer.eventHandler?.removeEvent?.('songEnded',finishListenerId);}catch{}
          for(const [name,fn] of listeners)player.removeEventListener(name,fn);
          scope.document?.removeEventListener?.('visibilitychange',visibility);
          scope.removeEventListener?.('focus',visibility);
          scope.removeEventListener?.('pageshow',visibility);
        };
        const releaseEngine=()=>{
          if(fullyReleased)return;
          fullyReleased=true;stopped=true;
          clearDrums();stopGapFill();releasePreview();
          try{sequencer.pause();}catch{}
          detachPlayback();dispose();
        };
        const beginTransitionFill=()=>{
          if(disposed||stopped||fullyReleased)return null;
          stopped=true;started=false;
          stopGapFill();
          detachPlayback();
          releasePreview();
          try{sequencer.pause();}catch{}
          try{
            scope.XStageIOSMidiAudio?.activate?.();
            void ctx.resume().catch(()=>{});
            void mediaOutput?.resume?.();
          }catch{}
          let last=-1;
          const start=Date.now();
          const tick=()=>{
            if(fullyReleased||disposed)return;
            const elapsed=(Date.now()-start)/1000;
            const index=Math.floor(elapsed/bridgeBeat);
            if(index!==last){
              last=index;
              beat(index);
            }
          };
          // A failed/no-network next song must never leave SoundFont
          // playback or an AudioContext running indefinitely.
          bridgeTimer=setInterval(tick,75);
          bridgeDeadline=setTimeout(releaseEngine,16000);
          tick();
          return {stop:releaseEngine};
        };
        return {
          engine:'SpessaSynth',scheduler:'audio-worklet',duration:parsed.duration,
          beginTransitionFill,
          currentTime:()=>Number(sequencer.currentTime),
          finished:()=>!!sequencer.isFinished,previewNote,
          dispose(){releaseEngine();}
        };
      }
      // Compatibility mode for browsers/SMFs that cannot initialize Sequencer.
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
        playing=true;
        scope.XStageIOSMidiAudio?.activate();
        void mediaOutput?.start().catch(()=>{});
        void ctx.resume().catch(()=>onStatus('กด ▶ อีกครั้งเพื่ออนุญาตเสียง'));
        reset();step();timer=setInterval(step,15);
      };
      const pause=()=>{
        if(timer!==null){clearInterval(timer);timer=null;}
        playing=false;reset();mediaOutput?.pause();
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
          releasePreview();dispose();
        },
        duration:parsed.duration,engine:'SpessaSynth',previewNote
      };
    },
    dispose
  };
}
scope.XStageProMidi={available,preload,prepare};
})(typeof window!=='undefined'?window:globalThis);
