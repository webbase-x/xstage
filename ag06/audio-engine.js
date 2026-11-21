import {sanitizeParams} from "./presets.js";

const Context = ()=>window.AudioContext || window.webkitAudioContext;
const asDb = (samples)=>{
  let sum=0;
  for(const v of samples)sum+=v*v;
  const rms=Math.sqrt(sum/Math.max(1,samples.length));
  return rms<0.00001?-100:Math.max(-100,20*Math.log10(rms));
};
const buildImpulse=(ctx,seconds=1.5)=>{
  const count=Math.floor(ctx.sampleRate*seconds);
  const buffer=ctx.createBuffer(2,count,ctx.sampleRate);
  for(let channel=0;channel<2;channel++){
    const data=buffer.getChannelData(channel);
    for(let i=0;i<count;i++){
      const decay=Math.pow(1-i/count,3);
      data[i]=(Math.random()*2-1)*decay*0.33;
    }
  }
  return buffer;
};
const driveCurve=(percent)=>{
  const curve=new Float32Array(1024);
  const intensity=percent/100;
  const k=1+intensity*35;
  const scale=Math.tanh(k);
  for(let i=0;i<curve.length;i++){
    const x=2*i/(curve.length-1)-1;
    curve[i]=percent===0?x:Math.tanh(k*x)/scale;
  }
  return curve;
};
const bestMime=()=>{
  if(!window.MediaRecorder)return null;
  for(const mime of ["audio/webm;codecs=opus","audio/ogg;codecs=opus","audio/mp4","audio/webm"]){
    if(MediaRecorder.isTypeSupported(mime))return mime;
  }
  return "";
};

export class AG06AudioEngine {
  constructor(){
    this.ctx=null;
    this.stream=null;
    this.params=sanitizeParams();
    this.onMeter=()=>{};
    this.onDisconnected=()=>{};
    this.monitor=false;
    this.recorder=null;
    this.recorderDone=null;
    this.animation=0;
    this.recordingStartedAt=0;
  }
  get connected(){return Boolean(this.stream&&this.ctx);}
  get sampleRate(){return this.ctx?.sampleRate||0;}
  static canRecord(){return bestMime()!==null;}
  async connect(deviceId=""){
    await this.disconnect();
    if(!navigator.mediaDevices?.getUserMedia)throw new Error("อุปกรณ์หรือเบราว์เซอร์นี้ไม่รองรับการรับเสียงจากไมโครโฟน");
    const audio={echoCancellation:false,noiseSuppression:false,autoGainControl:false,channelCount:{ideal:2}};
    if(deviceId)audio.deviceId={exact:deviceId};
    const stream=await navigator.mediaDevices.getUserMedia({audio,video:false});
    const AudioContextClass=Context();
    if(!AudioContextClass){stream.getTracks().forEach(track=>track.stop());throw new Error("ไม่มี Web Audio API บนอุปกรณ์นี้");}
    try{
      const ctx=new AudioContextClass({latencyHint:"interactive"});
      this.ctx=ctx;
      this.stream=stream;
      this.source=ctx.createMediaStreamSource(stream);
      this.hpf=ctx.createBiquadFilter();this.hpf.type="highpass";this.hpf.Q.value=.707;
      this.low=ctx.createBiquadFilter();this.low.type="lowshelf";this.low.frequency.value=170;
      this.mid=ctx.createBiquadFilter();this.mid.type="peaking";this.mid.frequency.value=1400;this.mid.Q.value=.9;
      this.high=ctx.createBiquadFilter();this.high.type="highshelf";this.high.frequency.value=4500;
      this.comp=ctx.createDynamicsCompressor();this.comp.knee.value=12;this.comp.ratio.value=3.5;
      this.comp.attack.value=.005;this.comp.release.value=.2;
      this.shaper=ctx.createWaveShaper();this.shaper.oversample="2x";
      this.dry=ctx.createGain();this.dry.gain.value=1;
      this.convolver=ctx.createConvolver();this.convolver.buffer=buildImpulse(ctx);
      this.wet=ctx.createGain();this.mix=ctx.createGain();
      this.master=ctx.createGain();
      this.monitorOutput=ctx.createGain();this.monitorOutput.gain.value=0;
      this.recordDestination=ctx.createMediaStreamDestination();
      this.splitter=ctx.createChannelSplitter(2);
      this.meterL=ctx.createAnalyser();this.meterR=ctx.createAnalyser();
      this.meterL.fftSize=2048;this.meterR.fftSize=2048;
      this.source.connect(this.splitter);
      this.splitter.connect(this.meterL,0);
      // If the source is mono the right-channel meter may show silence.
      this.splitter.connect(this.meterR,1);
      this.source.connect(this.hpf);
      this.hpf.connect(this.low);this.low.connect(this.mid);this.mid.connect(this.high);
      this.high.connect(this.comp);this.comp.connect(this.shaper);
      this.shaper.connect(this.dry);this.dry.connect(this.mix);
      this.shaper.connect(this.convolver);this.convolver.connect(this.wet);this.wet.connect(this.mix);
      this.mix.connect(this.master);
      this.master.connect(this.recordDestination);
      this.master.connect(this.monitorOutput);this.monitorOutput.connect(ctx.destination);
      this.applyParams(this.params);this.setMonitor(false);
      stream.getAudioTracks().forEach(track=>{track.onended=()=>{
        if(this.stream===stream){void this.disconnect().then(()=>this.onDisconnected("อุปกรณ์เสียงหยุดส่งสัญญาณ"));}
      };});
      if(ctx.state==="suspended")await ctx.resume();
      this.startMeters();
      return {sampleRate:ctx.sampleRate,label:stream.getAudioTracks()[0]?.label||"USB / Microphone"};
    }catch(error){await this.disconnect();throw error;}
  }
  applyParams(input){
    this.params=sanitizeParams(input);
    if(!this.ctx)return;
    const t=this.ctx.currentTime, p=this.params;
    const set=(param,value)=>param.setTargetAtTime(value,t,.025);
    set(this.hpf.frequency,p.hpf);
    set(this.low.gain,p.low);set(this.mid.gain,p.mid);set(this.high.gain,p.high);
    set(this.comp.threshold,p.comp);
    this.shaper.curve=driveCurve(p.drive);
    set(this.wet.gain,p.reverb/100);
    set(this.dry.gain,1);
    set(this.master.gain,Math.pow(10,p.gain/20));
  }
  setMonitor(enabled){
    this.monitor=Boolean(enabled);
    if(this.ctx&&this.monitorOutput)this.monitorOutput.gain.setTargetAtTime(this.monitor?1:0,this.ctx.currentTime,.02);
  }
  startMeters(){
    const left=new Float32Array(this.meterL.fftSize),right=new Float32Array(this.meterR.fftSize);
    const read=()=>{
      if(!this.connected)return;
      this.meterL.getFloatTimeDomainData(left);this.meterR.getFloatTimeDomainData(right);
      this.onMeter(asDb(left),asDb(right));
      this.animation=requestAnimationFrame(read);
    };
    this.animation=requestAnimationFrame(read);
  }
  startRecording(){
    if(!this.connected)throw new Error("กรุณาเริ่มรับเสียงก่อนบันทึก");
    if(this.recorder)throw new Error("กำลังบันทึกอยู่");
    const mime=bestMime();
    if(mime===null)throw new Error("ระบบนี้ยังไม่รองรับ MediaRecorder");
    const recorder=new MediaRecorder(this.recordDestination.stream,mime?{mimeType:mime}:undefined);
    const chunks=[];
    this.recorderDone=new Promise((resolve,reject)=>{
      recorder.ondataavailable=e=>{if(e.data&&e.data.size)chunks.push(e.data);};
      recorder.onerror=e=>reject(e.error||new Error("เกิดปัญหาระหว่างบันทึกเสียง"));
      recorder.onstop=()=>{
        const type=recorder.mimeType||mime||"application/octet-stream";
        const extension=type.includes("mp4")?"m4a":type.includes("ogg")?"ogg":"webm";
        const blob=new Blob(chunks,{type});
        resolve({blob,extension,type});
      };
    });
    this.recorder=recorder;
    recorder.start(1000);
    this.recordingStartedAt=Date.now();
  }
  async stopRecording(){
    if(!this.recorder)return null;
    const recorder=this.recorder;
    this.recorder=null;
    if(recorder.state!=="inactive")recorder.stop();
    return this.recorderDone;
  }
  async disconnect(){
    cancelAnimationFrame(this.animation);
    this.animation=0;
    if(this.recorder){try{await this.stopRecording();}catch{}}
    const stream=this.stream;this.stream=null;
    if(stream)stream.getTracks().forEach(track=>{track.onended=null;track.stop();});
    if(this.ctx){const ctx=this.ctx;this.ctx=null;try{await ctx.close();}catch{}}
    this.onMeter(-100,-100);
  }
}
