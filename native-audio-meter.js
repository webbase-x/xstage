/* X-Stage Android APK — direct speaker playback plus visual-only meter.
 * Do NOT connect HTMLMediaElement through createMediaElementSource(): that
 * redirects all sound into Web Audio and risks EQ, silence and added latency.
 * captureStream() leaves the original player as the only audible source.
 * The captured stream is connected exclusively to a 0-gain output, so no
 * second audible audio path is created. No microphone permission is used.
 */
'use strict';
(()=>{
  const player=document.getElementById('player');
  const stage=document.getElementById('stage');
  const canvas=document.getElementById('stage-viz-left');
  const rightCanvas=document.getElementById('stage-viz-right');
  const bridge=window.XStageAndroid;
  let native=!!(bridge&&typeof bridge.getAppVersion==='function');
  if(!native)try{native=['android-tv','android-tablet'].includes(new URLSearchParams(location.search).get('source'));}catch{}
  if(!native||!player||!stage||!canvas)return;
  document.body.classList.add('xstage-native-audio-direct');

  const surface=canvas.getContext('2d');
  const rightSurface=rightCanvas?.getContext('2d');
  if(!surface)return;
  // Android's silent capture feeds both EQ-style side meters, exactly like
  // the Web stage. The second canvas does not create a second audio source.
  const views=[{canvas,ctx:surface,mirror:false}];
  if(rightSurface)views.push({canvas:rightCanvas,ctx:rightSurface,mirror:true});
  const label=document.createElement('div');
  label.className='xstage-native-meter-label';
  label.setAttribute('role','status');
  label.setAttribute('aria-live','polite');
  stage.querySelector('.stage-hero')?.append(label);
  const LEVELS=28,SMOOTH=Array(LEVELS).fill(0);
  let stream=null,context=null,source=null,analyser=null,silent=null;
  let frame=0,lastFrame=0,retryTimer=0,tries=0,epoch=0;
  let status='';
  function statusText(next){
    if(status===next)return;
    status=next;stage.dataset.nativeMeter=next;
    const texts={
      idle:'เสียงตรง · มิเตอร์รอเพลง',
      waiting:'เสียงตรง · กำลังเตรียมมิเตอร์',
      active:'AUDIO DIRECT · LEVEL MONITOR',
      paused:'เสียงตรง · พักเพลง',
      unsupported:'เสียงตรง · อุปกรณ์นี้ไม่รองรับมิเตอร์สด',
      unavailable:'เสียงตรง · ไม่สามารถอ่านระดับเสียงได้',
      blocked:'เสียงตรง · แตะหรือกด OK เพื่อเริ่มมิเตอร์'
    };
    label.textContent=texts[next]||texts.idle;
  }
  function dispose(){
    epoch++;
    if(retryTimer){clearTimeout(retryTimer);retryTimer=0;}
    if(frame){cancelAnimationFrame(frame);frame=0;}
    try{source?.disconnect();}catch{}
    try{analyser?.disconnect();}catch{}
    try{silent?.disconnect();}catch{}
    for(const track of stream?.getTracks?.()||[])try{track.stop();}catch{}
    try{context?.close?.().catch(()=>{});}catch{}
    stream=null;context=null;source=null;analyser=null;silent=null;
    tries=0;lastFrame=0;SMOOTH.fill(0);
    stage.style.setProperty('--xstage-viz-energy','0');
    stage.style.setProperty('--xstage-viz-bass','0');
    for(const view of views){
      const size=view.canvas.getBoundingClientRect();
      view.ctx.clearRect(0,0,Math.max(view.canvas.width,size.width),Math.max(view.canvas.height,size.height));
    }
  }
  function retry(){
    if(retryTimer||!player.src||player.paused||player.ended)return;
    if(tries>=8){statusText('unavailable');return;}
    tries++;
    const current=epoch;
    retryTimer=setTimeout(()=>{
      retryTimer=0;
      if(current===epoch)start();
    },Math.min(1500,tries*280));
  }
  function sizeCanvas(target){
    const rect=target.getBoundingClientRect();
    const scale=Math.min(window.devicePixelRatio||1,2);
    const w=Math.max(1,Math.round(rect.width*scale)),h=Math.max(1,Math.round(rect.height*scale));
    if(target.width!==w||target.height!==h){target.width=w;target.height=h;}
    return [w,h];
  }
  function render(timestamp){
    if(!analyser||!context){frame=0;return;}
    frame=requestAnimationFrame(render);
    if(timestamp-lastFrame<40)return; // 25fps keeps Android TV GPUs responsive.
    lastFrame=timestamp;
    const data=new Uint8Array(analyser.frequencyBinCount);
    const playing=!player.paused&&!player.ended&&!player.muted&&player.volume>0;
    if(playing&&context.state==='running')analyser.getByteFrequencyData(data);
    const nyquist=(context.sampleRate||48000)/2;
    const upper=Math.min(15500,nyquist*.92),lower=40;
    let energy=0,bass=0;
    for(let i=0;i<LEVELS;i++){
      const f0=lower*Math.pow(upper/lower,i/LEVELS),f1=lower*Math.pow(upper/lower,(i+1)/LEVELS);
      const from=Math.max(0,Math.floor(f0/nyquist*data.length));
      const to=Math.min(data.length,Math.max(from+1,Math.ceil(f1/nyquist*data.length)));
      let peak=0,energySquared=0,count=0;
      for(let n=from;n<to;n++){
        const value=(data[n]||0)/255;peak=Math.max(peak,value);
        energySquared+=value*value;count++;
      }
      const value=Math.min(1,(Math.sqrt(energySquared/Math.max(1,count))*.83+peak*.31)*Math.sqrt(player.volume));
      const old=SMOOTH[i];
      SMOOTH[i]=value>old?old*.2+value*.8:old*.77+value*.23;
      const level=SMOOTH[i];energy+=level;if(i<7)bass+=level;
    }
    // Same live spectrum in Web and TV: bars on both sides of the stationary
    // banner. Mirror their order so the spectrum balances visually.
    for(const view of views){
      const [w,h]=sizeCanvas(view.canvas),ctx=view.ctx;
      const gap=Math.max(1.2,w*.009),barWidth=Math.max(1.5,(w-(LEVELS-1)*gap)/LEVELS);
      ctx.clearRect(0,0,w,h);
      for(let i=0;i<LEVELS;i++){
        const level=SMOOTH[view.mirror?LEVELS-1-i:i];
        const barHeight=Math.max(2,level*h*.92);
        const x=i*(barWidth+gap),y=h-barHeight;
        const gradient=ctx.createLinearGradient(0,y,0,h);
        gradient.addColorStop(0,'#c8ffff');
        gradient.addColorStop(.48,'#42d8ff');
        gradient.addColorStop(1,'#825dff');
        ctx.globalAlpha=.28+.72*level;
        ctx.fillStyle=gradient;
        ctx.fillRect(x,y,barWidth,barHeight);
      }
      ctx.globalAlpha=1;
    }
    stage.style.setProperty('--xstage-viz-energy',(energy/LEVELS).toFixed(3));
    stage.style.setProperty('--xstage-viz-bass',(bass/7).toFixed(3));
    if(context.state!=='running'&&playing)statusText('blocked');
    else if(playing)statusText('active');
    else statusText('paused');
  }
  function start(){
    if(analyser){
      if(context?.state==='suspended')try{void context.resume().catch(()=>{});}catch{}
      return;
    }
    if(!player.src||player.paused||player.ended)return;
    if(typeof player.captureStream!=='function'){
      statusText('unsupported');return;
    }
    const C=window.AudioContext||window.webkitAudioContext;
    if(!C){statusText('unsupported');return;}
    statusText('waiting');
    let captured=null,ctx=null,src=null,fft=null,mute=null;
    try{
      captured=player.captureStream();
      if(!captured?.getAudioTracks?.().length){
        for(const track of captured?.getTracks?.()||[])try{track.stop();}catch{}
        retry();return;
      }
      ctx=new C();
      src=ctx.createMediaStreamSource(captured);
      fft=ctx.createAnalyser();fft.fftSize=2048;fft.smoothingTimeConstant=.7;
      mute=ctx.createGain();mute.gain.value=0;
      // Visual analysis is the ONLY Web Audio path for Android APK.
      src.connect(fft);
      fft.connect(mute);
      mute.connect(ctx.destination);
      stream=captured;context=ctx;source=src;analyser=fft;silent=mute;
      if(retryTimer){clearTimeout(retryTimer);retryTimer=0;}
      try{void ctx.resume().catch(()=>{});}catch{}
      if(!frame)frame=requestAnimationFrame(render);
    }catch(error){
      try{src?.disconnect();}catch{}
      try{fft?.disconnect();}catch{}
      try{mute?.disconnect();}catch{}
      try{ctx?.close?.().catch(()=>{});}catch{}
      for(const track of captured?.getTracks?.()||[])try{track.stop();}catch{}
      retry();
    }
  }
  player.addEventListener('loadstart',()=>{dispose();statusText('waiting');});
  for(const name of ['play','playing','loadeddata','canplay']){
    player.addEventListener(name,start);
  }
  player.addEventListener('pause',()=>statusText('paused'));
  player.addEventListener('ended',()=>{dispose();statusText('idle');});
  for(const name of ['pointerdown','keydown']){
    document.addEventListener(name,()=>{
      if(!player.paused&&context?.state==='suspended')try{void context.resume().catch(()=>{});}catch{}
    },{passive:true});
  }
  window.addEventListener('pagehide',dispose);
  window.XStageNativeMeterStatus=()=>({
    audioOutput:'direct',
    active:!!analyser&&context?.state==='running',
    captureSupported:typeof player.captureStream==='function',
    silentGain:silent?.gain.value===0,
    status
  });
  statusText('idle');
})();
