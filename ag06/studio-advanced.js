// X-Stage independent editor helpers. Local-only; no third-party licensed assets.
export const limit=(v,a,b)=>Math.max(a,Math.min(b,Number.isFinite(+v)?+v:a));
export function waveformPeaks(buffer,bins=240){
 const n=Math.max(1,Math.min(2048,Math.floor(bins))), samples=buffer.getChannelData(0),out=[];
 for(let i=0;i<n;i++){const a=Math.floor(i*samples.length/n),b=Math.max(a+1,Math.floor((i+1)*samples.length/n));let peak=0;
  for(let j=a;j<b;j++)peak=Math.max(peak,Math.abs(samples[j]));out.push(peak);}
 return out;
}
export function drawWaveform(canvas,track,scale=50){
 const dpr=Math.min(2,window.devicePixelRatio||1),width=Math.max(260,Math.min(4000,Math.round((track.end-track.start)*scale)));
 canvas.width=Math.round(width*dpr);canvas.height=Math.round(80*dpr);canvas.style.width=width+"px";canvas.style.height="80px";
 const c=canvas.getContext("2d");if(!c)return;
 c.scale(dpr,dpr);c.clearRect(0,0,width,80);
 const peaks=waveformPeaks(track.buffer,Math.max(1,Math.floor(width/2))),bar=width/peaks.length;
 c.fillStyle="#5de2c1";peaks.forEach((v,i)=>{const height=Math.max(1,Math.round(v*72));c.fillRect(i*bar,(80-height)/2,Math.max(1,bar*.8),height);});
 c.strokeStyle="#d6ecff";c.beginPath();c.moveTo(0,40);c.lineTo(width,40);c.stroke();
}
export function encodeProject(session,notes=[]){
 const tracks=session.tracks.map(t=>({name:t.name,volume:t.volume,mute:!!t.mute,solo:!!t.solo,role:t.role||"music",start:t.start,end:t.end,offset:t.offset,
  audio:{sampleRate:t.buffer.sampleRate,channels:Array.from({length:Math.min(2,t.buffer.numberOfChannels)},(_,c)=>Array.from(t.buffer.getChannelData(c)))}}));
 return JSON.stringify({format:"xstage-audio-project",version:1,settings:{ducking:!!session.ducking,normalize:!!session.normalize,noiseGate:!!session.noiseGate,spectralReduction:!!session.spectralReduction},tracks,notes});
}
export function decodeProject(json){
 const project=JSON.parse(json);
 if(project?.format!=="xstage-audio-project"||project.version!==1||!Array.isArray(project.tracks)||project.tracks.length>12)throw new Error("ไฟล์โปรเจกต์ไม่ถูกต้อง");
 if(JSON.stringify(project).length>100*1024*1024)throw new Error("ไฟล์โปรเจกต์ใหญ่เกินไป");
 for(const t of project.tracks){
  if(!t.audio||!Number.isFinite(t.audio.sampleRate)||t.audio.sampleRate<8000||t.audio.sampleRate>192000||!Array.isArray(t.audio.channels)||t.audio.channels.length<1||t.audio.channels.length>2)throw new Error("ข้อมูลเสียงไม่ถูกต้อง");
  const len=t.audio.channels[0].length;
  if(!len||len>t.audio.sampleRate*600||t.audio.channels.some(c=>!Array.isArray(c)||c.length!==len))throw new Error("ความยาวเสียงไม่ถูกต้อง");
 }
 return project;
}
export const midiFrequency=note=>440*Math.pow(2,(note-69)/12);
export function noteSequence(notes,bpm=120){
 const beat=60/limit(bpm,40,240);
 return notes.map(n=>({pitch:Math.round(limit(n.pitch,36,96)),start:limit(n.beat,0,128)*beat,duration:limit(n.length,.125,16)*beat,velocity:limit(n.velocity,0,1)}));
}
export async function renderSynth(notes,bpm=120,instrument="triangle"){
 const sequence=noteSequence(notes,bpm);if(!sequence.length)throw new Error("เพิ่มโน้ตก่อนสร้างเสียง");
 const duration=Math.max(...sequence.map(n=>n.start+n.duration))+.25;
 if(duration>180)throw new Error("ความยาวเกิน 3 นาที");
 const rate=44100,ctx=new OfflineAudioContext(2,Math.ceil(duration*rate),rate);
 for(const n of sequence){
  const osc=ctx.createOscillator(),gain=ctx.createGain();osc.type=["triangle","sine","square","sawtooth"].includes(instrument)?instrument:"triangle";osc.frequency.value=midiFrequency(n.pitch);
  const start=n.start,stop=start+n.duration;
  gain.gain.setValueAtTime(.0001,start);gain.gain.exponentialRampToValueAtTime(Math.max(.0002,n.velocity*.16),start+.012);
  gain.gain.setTargetAtTime(.0001,Math.max(start+.02,stop-.04),.025);
  osc.connect(gain);gain.connect(ctx.destination);osc.start(start);osc.stop(stop+.14);
 }
 return ctx.startRendering();
}

// Standard MIDI File Type 0, ticks per quarter=480; no proprietary instruments.
function vlq(value){
 let n=Math.max(0,Math.floor(value)),bytes=[n&127];n>>=7;
 while(n){bytes.unshift((n&127)|128);n>>=7;}
 return bytes;
}
export function encodeMidi(notes,bpm=120){
 const tempo=Math.round(60000000/limit(bpm,40,240)),events=[];
 for(const n of notes.slice(0,512)){
  const start=Math.round(limit(n.beat,0,128)*480),end=start+Math.round(limit(n.length,.125,16)*480),pitch=Math.round(limit(n.pitch,36,96));
  events.push({tick:start,bytes:[0x90,pitch,Math.max(1,Math.round(limit(n.velocity,.01,1)*127))],order:1});
  events.push({tick:end,bytes:[0x80,pitch,0],order:0});
 }
 events.sort((a,b)=>a.tick-b.tick||a.order-b.order);
 const data=[0,0xff,0x51,3,(tempo>>16)&255,(tempo>>8)&255,tempo&255];
 let prev=0;for(const e of events){data.push(...vlq(e.tick-prev),...e.bytes);prev=e.tick;}
 data.push(0,0xff,0x2f,0);
 const length=data.length,header=[77,84,104,100,0,0,0,6,0,0,0,1,1,224];
 return new Uint8Array([...header,77,84,114,107,(length>>>24)&255,(length>>>16)&255,(length>>>8)&255,length&255,...data]);
}
export function decodeMidi(array){
 const data=array instanceof Uint8Array?array:new Uint8Array(array);
 if(data.length>1024*1024||data.length<22||String.fromCharCode(...data.slice(0,4))!=="MThd")throw new Error("ไฟล์ MIDI ไม่ถูกต้องหรือใหญ่เกิน 1 MB");
 const view=new DataView(data.buffer,data.byteOffset,data.byteLength);
 const headerSize=view.getUint32(4),format=view.getUint16(8),trackCount=view.getUint16(10),division=view.getUint16(12);
 if(headerSize<6||headerSize>100||format>1||trackCount>32||(division&0x8000)||!division)throw new Error("รูปแบบ MIDI ไม่รองรับ");
 let pos=8+headerSize,tempo=500000,notes=[],active=new Map(),events=[];
 for(let track=0;track<trackCount;track++){
  if(pos+8>data.length||String.fromCharCode(...data.slice(pos,pos+4))!=="MTrk")throw new Error("ส่วนข้อมูล MIDI เสีย");
  const size=view.getUint32(pos+4);pos+=8;const end=pos+size;if(end>data.length)throw new Error("ขนาดแทร็ก MIDI ไม่ถูกต้อง");
  let tick=0,status=0;
  const next=()=>{if(pos>=end)throw new Error("ข้อมูล MIDI ไม่ครบ");return data[pos++];};
  const readVlq=()=>{let n=0;for(let i=0;i<4;i++){const b=next();n=(n<<7)|(b&127);if(!(b&128))return n;}throw new Error("MIDI delta ยาวเกินไป");};
  while(pos<end){
   tick+=readVlq();let b=next();
   if(b===0xff){const type=next(),len=readVlq();if(pos+len>end)throw new Error("MIDI meta เสีย");
    if(type===0x51&&len===3&&!events.length)tempo=(data[pos]<<16)|(data[pos+1]<<8)|data[pos+2];
    pos+=len;continue;}
   if(b===0xf0||b===0xf7){const len=readVlq();if(pos+len>end)throw new Error("MIDI SysEx เสีย");pos+=len;continue;}
   if(b&0x80)status=b;else pos--;
   const type=status&0xf0,channel=status&15;
   if(type<0x80||type>0xe0)throw new Error("MIDI status ไม่ถูกต้อง");
   const pitch=next(),velocity=(type===0xc0||type===0xd0)?0:next();
   if(type===0x90&&velocity>0){active.set(channel+":"+pitch,{tick,velocity});}
   else if(type===0x80||(type===0x90&&velocity===0)){
    const key=channel+":"+pitch,begin=active.get(key);active.delete(key);
    if(begin&&tick>begin.tick&&notes.length<512)notes.push({pitch,beat:begin.tick/division,length:(tick-begin.tick)/division,velocity:begin.velocity/127});
   }
  }
  pos=end;
 }
 return {notes:notes.filter(n=>n.pitch>=36&&n.pitch<=96&&n.beat<=128).slice(0,512),bpm:Math.round(60000000/tempo)};
}
