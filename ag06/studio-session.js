// Independent local multitrack audio workspace. No proprietary Yamaha/Steinberg code.
const MAX_TRACKS=12, MAX_FILE_BYTES=80*1024*1024, MAX_RENDER_SECONDS=600;
export const clamp=(v,min,max)=>Math.max(min,Math.min(max,Number.isFinite(+v)?+v:min));
export const safeName=(name)=>String(name||"Track").replace(/[<>:"/\\|?*\x00-\x1f]/g,"").slice(0,70)||"Track";
export function encodeWav(buffer){
  const channels=Math.min(2,buffer.numberOfChannels),frames=buffer.length,rate=buffer.sampleRate;
  const wav=new ArrayBuffer(44+frames*channels*2),view=new DataView(wav);
  const write=(i,s)=>{for(let j=0;j<s.length;j++)view.setUint8(i+j,s.charCodeAt(j));};
  write(0,"RIFF");view.setUint32(4,36+frames*channels*2,true);write(8,"WAVE");write(12,"fmt ");
  view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,channels,true);
  view.setUint32(24,rate,true);view.setUint32(28,rate*channels*2,true);
  view.setUint16(32,channels*2,true);view.setUint16(34,16,true);write(36,"data");
  view.setUint32(40,frames*channels*2,true);
  const data=Array.from({length:channels},(_,c)=>buffer.getChannelData(c));
  let p=44;
  for(let i=0;i<frames;i++)for(let c=0;c<channels;c++){
    const sample=clamp(data[c][i],-1,1);
    view.setInt16(p,sample<0?Math.round(sample*32768):Math.round(sample*32767),true);p+=2;
  }
  return new Blob([wav],{type:"audio/wav"});
}
export class StudioSession {
  constructor(){this.tracks=[];this.ctx=null;this.players=[];this.ducking=false;this.normalize=false;this.noiseGate=false;this.spectralReduction=false;}
  async addFile(file,name=file.name){
    if(this.tracks.length>=MAX_TRACKS)throw new Error("รองรับสูงสุด "+MAX_TRACKS+" แทร็ก");
    if(!file.size||file.size>MAX_FILE_BYTES)throw new Error("ไฟล์ต้องมีขนาด 1–80 MB");
    const Ctx=window.AudioContext||window.webkitAudioContext;
    if(!Ctx)throw new Error("อุปกรณ์นี้ไม่รองรับ AudioContext");
    const context=new Ctx();
    let decoded;
    try{decoded=await context.decodeAudioData(await file.arrayBuffer());}
    finally{await context.close();}
    if(!decoded.length||decoded.duration>MAX_RENDER_SECONDS)throw new Error("ไฟล์เสียงต้องมีความยาวไม่เกิน 10 นาที");
    const track={id:crypto.randomUUID?.()||String(Date.now()+Math.random()),name:safeName(name),buffer:decoded,
      volume:1,mute:false,solo:false,role:"music",start:0,end:decoded.duration,offset:0};
    this.tracks.push(track);return track;
  }
  remove(id){this.tracks=this.tracks.filter(t=>t.id!==id);}
  active(){const hasSolo=this.tracks.some(t=>t.solo);return this.tracks.filter(t=>!t.mute&&(!hasSolo||t.solo));}
  duration(){return Math.max(0,...this.tracks.map(t=>t.offset+t.end-t.start));}
  // Speech-controlled ducking operates only on local decoded audio.
  voiceLevelAt(second){
    let level=0;
    for(const t of this.active().filter(t=>t.role==="voice"&&t.buffer?.getChannelData)){
      const local=second-t.offset+t.start;
      if(second<t.offset||local>=t.end||local<t.start)continue;
      const pcm=t.buffer.getChannelData(0),rate=t.buffer.sampleRate;
      const first=Math.floor(local*rate),last=Math.min(pcm.length,first+Math.floor(rate*.03));
      let sum=0,count=0;
      for(let i=first;i<last;i+=4){sum+=pcm[i]*pcm[i];count++;}
      level=Math.max(level,Math.sqrt(sum/Math.max(1,count)));
    }
    return level;
  }
  async createGraph(ctx,dest){
    const nodes=[];
    for(const track of this.active()){
      const source=ctx.createBufferSource(),gain=ctx.createGain();
      source.buffer=track.buffer;
      if(this.spectralReduction&&track.role==="voice"){
        if(track.buffer.duration>60)throw new Error("Spectral Reduction ใช้กับเสียงพูดไม่เกิน 60 วินาทีต่อแทร็ก");
        const original=track.buffer,processed=ctx.createBuffer(original.numberOfChannels,original.length,original.sampleRate);
        for(let channel=0;channel<original.numberOfChannels;channel++){
          const cleaned=reduceSpectralNoise(original.getChannelData(channel),original.sampleRate);
          processed.getChannelData(channel).set(cleaned);
        }
        source.buffer=processed;
      }
      gain.gain.value=clamp(track.volume,0,2);
      if(this.ducking&&track.role==="music"&&this.active().some(t=>t.role==="voice")){
        const start=track.offset,end=Math.min(this.duration(),track.offset+track.end-track.start);
        let smoothed=1;
        gain.gain.setValueAtTime(gain.gain.value,ctx.currentTime+start);
        for(let at=start;at<end;at+=.05){
          const target=this.voiceLevelAt(at)>.018?.28:1;
          smoothed+=(target-smoothed)*(target<smoothed?.5:.10);
          gain.gain.linearRampToValueAtTime(clamp(track.volume,0,2)*smoothed,ctx.currentTime+at+.05);
        }
      }
      if(this.noiseGate&&track.role==="voice"){
        const filter=ctx.createBiquadFilter();filter.type="highpass";filter.frequency.value=90;source.connect(filter);filter.connect(gain);
        const pcm=track.buffer.getChannelData(0),rate=track.buffer.sampleRate;
        for(let at=track.start;at<track.end;at+=.03){
          let sum=0,count=0;const first=Math.floor(at*rate),last=Math.min(pcm.length,first+Math.ceil(rate*.03));
          for(let i=first;i<last;i+=4){sum+=pcm[i]*pcm[i];count++;}
          const rms=Math.sqrt(sum/Math.max(1,count)),floor=rms<.012?.05:1;
          gain.gain.setTargetAtTime(clamp(track.volume,0,2)*floor,ctx.currentTime+track.offset+at-track.start,.008);
        }
      }else source.connect(gain);
      gain.connect(dest);
      const duration=track.end-track.start;
      if(duration>0){source.start(ctx.currentTime+track.offset,track.start,duration);nodes.push(source);}
    }
    return nodes;
  }
  async play(){
    this.stop();
    if(!this.tracks.length)throw new Error("เพิ่มแทร็กก่อนเล่น");
    const Ctx=window.AudioContext||window.webkitAudioContext;
    this.ctx=new Ctx();await this.ctx.resume();
    try{this.players=await this.createGraph(this.ctx,this.ctx.destination);return this.ctx;}
    catch(error){this.stop();throw error;}
  }
  stop(){
    for(const source of this.players){try{source.stop();}catch{}}
    this.players=[];
    const ctx=this.ctx;this.ctx=null;
    if(ctx)void ctx.close();
  }
  async bounce(){
    if(!this.tracks.length)throw new Error("ยังไม่มีแทร็ก");
    const seconds=this.duration();
    if(seconds<=0||seconds>MAX_RENDER_SECONDS)throw new Error("ความยาวมิกซ์ต้องไม่เกิน 10 นาที");
    const sampleRate=44100,ctx=new OfflineAudioContext(2,Math.ceil(seconds*sampleRate),sampleRate);
    await this.createGraph(ctx,ctx.destination);
    const buffer=await ctx.startRendering();
    if(this.normalize){
      let peak=0;
      for(let c=0;c<buffer.numberOfChannels;c++){
        const channel=buffer.getChannelData(c);
        for(let i=0;i<channel.length;i++)peak=Math.max(peak,Math.abs(channel[i]));
      }
      if(peak>.00001){
        const multiplier=Math.min(8,.95/peak);
        for(let c=0;c<buffer.numberOfChannels;c++){
          const channel=buffer.getChannelData(c);
          for(let i=0;i<channel.length;i++)channel[i]*=multiplier;
        }
      }
    }
    return encodeWav(buffer);
  }
}
