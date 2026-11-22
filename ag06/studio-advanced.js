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
 return JSON.stringify({format:"xstage-audio-project",version:1,settings:{ducking:!!session.ducking,normalize:!!session.normalize},tracks,notes});
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
export async function renderSynth(notes,bpm=120){
 const sequence=noteSequence(notes,bpm);if(!sequence.length)throw new Error("เพิ่มโน้ตก่อนสร้างเสียง");
 const duration=Math.max(...sequence.map(n=>n.start+n.duration))+.25;
 if(duration>180)throw new Error("ความยาวเกิน 3 นาที");
 const rate=44100,ctx=new OfflineAudioContext(2,Math.ceil(duration*rate),rate);
 for(const n of sequence){
  const osc=ctx.createOscillator(),gain=ctx.createGain();osc.type="triangle";osc.frequency.value=midiFrequency(n.pitch);
  const start=n.start,stop=start+n.duration;
  gain.gain.setValueAtTime(.0001,start);gain.gain.exponentialRampToValueAtTime(Math.max(.0002,n.velocity*.16),start+.012);
  gain.gain.setTargetAtTime(.0001,Math.max(start+.02,stop-.04),.025);
  osc.connect(gain);gain.connect(ctx.destination);osc.start(start);osc.stop(stop+.14);
 }
 return ctx.startRendering();
}
