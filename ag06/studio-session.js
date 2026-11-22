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
  constructor(){this.tracks=[];this.ctx=null;this.players=[];}
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
      volume:1,mute:false,solo:false,start:0,end:decoded.duration,offset:0};
    this.tracks.push(track);return track;
  }
  remove(id){this.tracks=this.tracks.filter(t=>t.id!==id);}
  active(){const hasSolo=this.tracks.some(t=>t.solo);return this.tracks.filter(t=>!t.mute&&(!hasSolo||t.solo));}
  duration(){return Math.max(0,...this.tracks.map(t=>t.offset+t.end-t.start));}
  async createGraph(ctx,dest){
    const nodes=[];
    for(const track of this.active()){
      const source=ctx.createBufferSource(),gain=ctx.createGain();
      source.buffer=track.buffer;gain.gain.value=clamp(track.volume,0,2);
      source.connect(gain);gain.connect(dest);
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
    this.players=await this.createGraph(this.ctx,this.ctx.destination);
    return this.ctx;
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
    return encodeWav(buffer);
  }
}
