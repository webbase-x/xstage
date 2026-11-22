/* X-Stage concert lights: visual only, driven by existing audio meters
 * or timestamped MIDI notes. Never opens another audio output or microphone. */
'use strict';
(()=>{
  const stage=document.getElementById('stage');
  const media=document.getElementById('player');
  if(!stage||!media)return;
  const deck=document.createElement('div');
  deck.className='xstage-stage-lights';
  deck.setAttribute('aria-hidden','true');
  const beams=Array.from({length:4},(_,index)=>{
    const element=document.createElement('span');
    element.className='xstage-light-beam xstage-light-beam-'+(index+1);
    deck.append(element);
    return element;
  });
  const floor=document.createElement('span');
  floor.className='xstage-light-floor';
  deck.append(floor);
  // In DOM order, lights sit over the background but behind the stage logo
  // and all selectable text, including the search dropdown.
  const hero=stage.querySelector('.stage-hero');
  if(hero)hero.before(deck);
  else stage.append(deck);
  const clamp=value=>Math.max(0,Math.min(1,Number(value)||0));
  const RATE=20;
  let midiBands=null,activeSource='audio',frame=0,lastFrame=0,playing=false;
  const reducedMotion=window.matchMedia?.('(prefers-reduced-motion: reduce)');
  const colorBands=[0,1,2,1];
  const sideMeters=['stage-viz-left','stage-viz-right'].map(id=>document.getElementById(id));
  // MIDI uses the live sequencer rather than the HTML5 audio element; its
  // actual note-on data must drive the existing left/right banner canvases.
  // The HTML5 analyser remains the sole writer for ordinary audio playback.
  function paintMidiSideMeters(bands,active){
    sideMeters.forEach((canvas,side)=>{
      if(!canvas||typeof canvas.getContext!=='function')return;
      const box=canvas.getBoundingClientRect?.();
      const width=Number(box?.width)||0,height=Number(box?.height)||0;
      if(width<2||height<2)return;
      const dpr=Math.min(2,Number(window.devicePixelRatio)||1);
      const w=Math.max(2,Math.round(width*dpr)),h=Math.max(2,Math.round(height*dpr));
      if(canvas.width!==w)canvas.width=w;
      if(canvas.height!==h)canvas.height=h;
      const ctx=canvas.getContext('2d');
      if(!ctx)return;
      ctx.clearRect(0,0,w,h);
      const count=Math.max(7,Math.min(22,Math.floor(w/Math.max(3,dpr*2.5))));
      const gap=Math.max(1,Math.round(w/count*.16));
      const barWidth=Math.max(1,(w-gap*(count-1))/count);
      for(let i=0;i<count;i++){
        const index=side?count-1-i:i;
        const band=bands[index/count<.33?0:index/count<.7?1:2]||0;
        const variation=.62+.38*Math.abs(Math.sin((index+1)*.79));
        const level=active?clamp(band*variation):0;
        const barHeight=Math.max(2,level*h*.92);
        const x=i*(barWidth+gap),y=h-barHeight;
        const gradient=ctx.createLinearGradient?.(0,y,0,h);
        if(gradient){
          gradient.addColorStop(0,'#b4fff4');
          gradient.addColorStop(.55,'#37cbff');
          gradient.addColorStop(1,'#7561ff');
        }
        ctx.fillStyle=gradient||'#49caff';
        ctx.globalAlpha=active ? (.34+.66*level) : .18;
        ctx.fillRect(x,y,barWidth,barHeight);
      }
      ctx.globalAlpha=1;
    });
  }
  function setMidiNotes(notes,duration){
    if(!Array.isArray(notes)||!notes.length){
      clearMidiNotes();return;
    }
    const bins=Math.max(2,Math.min(18005,Math.ceil((Number(duration)||0)*RATE)+2));
    const bands=Array.from({length:3},()=>new Float32Array(bins));
    for(const note of notes){
      const t=Number(note?.start),end=Number(note?.end),velocity=Number(note?.velocity);
      if(!Number.isFinite(t)||t<0||t*RATE>=bins||!Number.isFinite(velocity))continue;
      const group=note.channel===9||Number(note.key)<53?0:Number(note.key)>=76?2:1;
      const strength=clamp(velocity/127)*clamp(Number(note.channelVolume??100)/127)*
        clamp(Number(note.channelExpression??127)/127);
      // Lighting reacts to actual MIDI note-on timestamps. A drum hit is
      // short; sustained notes fade slowly, without inventing extra beats.
      const hold=note.channel===9?.28:Math.min(.85,Math.max(.18,(end||t+.18)-t));
      const first=Math.floor(t*RATE);
      const last=Math.min(bins-1,Math.ceil((t+hold)*RATE));
      for(let i=first;i<=last;i++){
        const seconds=(i/RATE)-t;
        bands[group][i]+=strength*Math.exp(-Math.max(0,seconds)/(note.channel===9?.12:.33));
      }
    }
    midiBands=bands;activeSource='midi';
    paintMidiSideMeters([0,0,0],false);
  }
  function clearMidiNotes(){
    midiBands=null;activeSource='audio';
    // Remove any stale MIDI bars before the real audio analyser takes over.
    paintMidiSideMeters([0,0,0],false);
  }
  function readMidiBands(position){
    if(!midiBands)return [0,0,0];
    const index=Math.max(0,Math.min(midiBands[0].length-1,Math.floor((Number(position)||0)*RATE)));
    return [clamp(midiBands[0][index]*.66),clamp(midiBands[1][index]*.52),clamp(midiBands[2][index]*.63)];
  }
  function readLiveSpectrum(){
    // Both the Web post-EQ analyser and Android silent-capture analyser
    // expose actual bass/mid/high energy. No new audio path or microphone.
    const sample=window.XStageStageLiveSpectrum?.();
    if(!sample||!Array.isArray(sample.bands)||
       Date.now()-(Number(sample.updatedAt)||0)>350)return null;
    return sample.active?sample.bands.slice(0,3).map(clamp):[0,0,0];
  }
  function readAudioBands(){
    const live=readLiveSpectrum();
    if(live)return live;
    // Compatibility for older cached audio meters until they are refreshed.
    const styles=getComputedStyle(stage);
    const energy=clamp(parseFloat(styles.getPropertyValue('--xstage-viz-energy')));
    const bass=clamp(parseFloat(styles.getPropertyValue('--xstage-viz-bass')));
    return [bass,energy,clamp(energy*1.12-bass*.15)];
  }
  function dark(){
    deck.classList.remove('is-active');
    for(const beam of beams)beam.style.opacity='0';
    floor.style.opacity='0';
  }
  function render(timestamp){
    frame=requestAnimationFrame(render);
    if(timestamp-lastFrame<45)return;
    lastFrame=timestamp;
    const video=document.getElementById('karaoke-video');
    if(!playing||media.paused||media.ended||media.muted||media.volume===0||
       !stage.classList.contains('playing')||video?.hidden===false){dark();return;}
    const live=readLiveSpectrum();
    // MIDI can reach the browser output through a separate synthesizer.
    // Prefer its measurable spectrum; otherwise use the actual scheduled
    // note-on events. Never invent a beat or route a second audio output.
    const midiFallback=activeSource==='midi'&&(!live||!live.some(value=>value>.012));
    const bands=midiFallback
      ?readMidiBands(media.currentTime)
      :(live||readAudioBands());
    const master=clamp(bands.reduce((a,b)=>a+b,0)/3);
    if(activeSource==='midi'&&midiFallback)paintMidiSideMeters(bands,master>.005);
    if(master<=.005){dark();return;}
    deck.classList.add('is-active');
    for(let i=0;i<beams.length;i++){
      const channel=bands[colorBands[i]];
      // Every beam reacts to measured audible energy or MIDI note events.
      beams[i].style.opacity=(.08+.92*clamp(channel*.8+master*.32)).toFixed(3);
    }
    floor.style.opacity=(.08+.8*master).toFixed(3);
    deck.style.setProperty('--xstage-light-power',master.toFixed(3));
    if(reducedMotion?.matches)deck.classList.add('still');
    else deck.classList.remove('still');
  }
  function onPlay(){
    playing=true;
    if(!frame)frame=requestAnimationFrame(render);
  }
  function onStop(){
    playing=false;
    if(frame){cancelAnimationFrame(frame);frame=0;}
    if(activeSource==='midi')paintMidiSideMeters([0,0,0],false);
    dark();
  }
  for(const event of ['play','playing'])media.addEventListener(event,onPlay);
  for(const event of ['pause','ended','emptied'])media.addEventListener(event,onStop);
  document.addEventListener('visibilitychange',()=>{
    if(document.hidden)onStop();
    else if(stage.classList.contains('playing')&&typeof player!=='undefined'&&!player.paused)onPlay();
  });
  window.addEventListener('pagehide',onStop);
  window.XStageStageLighting={
    setMidiNotes,clearMidiNotes,
    status:()=>({active:playing,source:activeSource,hasMidiNotes:!!midiBands,
      beamCount:beams.length,energy:Number(deck.style.getPropertyValue('--xstage-light-power'))||0})
  };
  // Keep a faint resting LED outline even before the first track. During
  // playback these bars show measured Web Audio or real MIDI note energy.
  paintMidiSideMeters([0,0,0],false);
  dark();
})();