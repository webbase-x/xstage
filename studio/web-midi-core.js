/* Song Studio Web song/lyrics pair contract.
 * One MIDI/KAR and one VERIFIED timed LRC/JSON. The historic NCN .LYR/.CUR
 * trio is not a new import format; source files are never modified. */
(function(scope){
'use strict';
const ROLES=new Set(['song','songs','lyric','lyrics','cursor','cursors']);
const MAX_MIDI=12*1024*1024,MAX_FONT=256*1024*1024;
const encode=s=>String(s??'').normalize('NFC').toLocaleLowerCase('th');
function groupIdentity(path,name){
  const folder=String(path||'').replace(/\\/g,'/').split('/').filter(Boolean);
  const stem=String(name||'').replace(/\.[^.]+$/,'');
  return [...folder.filter(p=>!ROLES.has(p.toLowerCase())),stem]
    .map(encode).join('/');
}
function companionState(song){
  if(!song?.midi)return {kind:'AUDIO',complete:true,message:''};
  if(/\.ncn$/i.test(song.midi.name)||song.lyr||song.cur)
    return {kind:'LEGACY',complete:false,
      message:'ยกเลิก NCN แบบ 3 ไฟล์แล้ว · แปลงเป็น MIDI/KAR + LRC หรือ Lyrics JSON ที่มีเวลาก่อน'};
  const kind=/\.kar$/i.test(song.midi.name)?'KAR':'MIDI';
  if(song.lrc&&song.json)return {kind,complete:false,
    message:'มี LRC และ JSON ซ้ำ · โปรดเลือกเนื้อร้องเพียงหนึ่งไฟล์ต่อเพลง'};
  if(!song.lrc&&!song.json)return {kind,complete:false,
    message:'ยังไม่มีเนื้อร้องพร้อมเวลา · ต้องมีไฟล์เพลงและ LRC/JSON คู่กัน'};
  return {kind,complete:true,message:kind+' + Lyrics '+(song.json?'JSON':'LRC')+' · ครบ 2 ไฟล์'};
}
function validTimedLine(line){
  return line && Number.isFinite(line.startTime) && line.startTime>=0 &&
    typeof line.text==='string' && line.text.trim() &&
    line.text!=='♪ ดนตรีบรรเลง ♪';
}
function formatLrcTime(seconds){
  const t=Math.max(0,Math.round(Number(seconds)*100)||0);
  return '['+String(Math.floor(t/6000)).padStart(2,'0')+':'+
    String(Math.floor(t/100)%60).padStart(2,'0')+'.'+String(t%100).padStart(2,'0')+']';
}
function documentToLrc(doc){
  const lines=Array.isArray(doc?.lines)?doc.lines:[];
  return lines.filter(validTimedLine).map(line=>formatLrcTime(line.startTime)+line.text).join('\n');
}
function lrcToDocument(raw,code,sourceFormat='LRC'){
  const lines=[];
  for(const rawLine of String(raw||'').split(/\r?\n/)){
    const match=/^\s*\[(\d{1,3}):(\d\d)(?:[.:](\d{1,3}))?\]\s*(.*?)\s*$/.exec(rawLine);
    if(!match||!match[4])continue;
    const seconds=Number(match[1])*60+Number(match[2])+
      Number((match[3]||'0').padEnd(3,'0').slice(0,3))/1000;
    if(!Number.isFinite(seconds)||Number(match[2])>=60)throw Error('LRC มีเวลาไม่ถูกต้อง');
    lines.push({startTime:seconds,text:match[4]});
  }
  if(!lines.length)throw Error('LRC ไม่มีเนื้อร้องพร้อมเวลาจริง · ไม่สร้างเวลาแทน');
  if(lines.some((line,i)=>i&&line.startTime<lines[i-1].startTime))
    throw Error('LRC มีเวลาย้อนกลับ · ตรวจแก้ก่อนส่งออก');
  return {schemaVersion:1,songCode:String(code||''),sourceFormat,
    lines:lines.map((line,i)=>({
      startTime:line.startTime,
      endTime:Math.max(line.startTime+.1,lines[i+1]?.startTime||line.startTime+2),
      text:line.text
    }))};
}
function jsonToDocument(raw,code){
  const doc=typeof raw==='string'?JSON.parse(raw):raw;
  if(!doc||doc.schemaVersion!==1||!Array.isArray(doc.lines)||
      !doc.lines.length||doc.lyricsMode==='embedded-video')
    throw Error('Lyrics JSON ไม่มีบรรทัดที่มีเวลาในโครงสร้าง X-Stage');
  if(doc.requiresReview===true||doc.metadata?.timingComplete===false)
    throw Error('Lyrics JSON ยังไม่ผ่านการตรวจเวลาจริง · ให้ตรวจแก้ก่อนนำเข้า');
  if(doc.songCode&&String(doc.songCode).toLocaleLowerCase()!==String(code).toLocaleLowerCase())
    throw Error('Lyrics JSON มีรหัสเพลงไม่ตรงกับไฟล์ MIDI');
  let last=-1,visible=0;
  for(const line of doc.lines){
    if(!line||!Number.isFinite(line.startTime)||line.startTime<0||
      line.startTime>86400||typeof line.text!=='string')
      throw Error('Lyrics JSON มีเวลา/ข้อความไม่ถูกต้อง');
    if(line.startTime<last)throw Error('Lyrics JSON มีเวลาเนื้อร้องย้อนกลับ');
    last=line.startTime;
    if(line.text.trim())visible++;
    if(line.endTime!=null&&(!Number.isFinite(line.endTime)||
      line.endTime<line.startTime||line.endTime>86400))
      throw Error('Lyrics JSON มีเวลาสิ้นสุดไม่ถูกต้อง');
  }
  if(!visible)throw Error('Lyrics JSON ไม่มีข้อความร้องที่มีเวลา');
  return doc;
}
async function inspectSong(song,midiRuntime){
  const state=companionState(song);
  if(!song?.midi||!state.complete)throw Error(state.message||'ไม่มีไฟล์ MIDI');
  if(song.midi.size<22||song.midi.size>MAX_MIDI)
    throw Error('MIDI ไม่สมบูรณ์หรือมีขนาดเกิน 12 MB');
  const bytes=new Uint8Array(await song.midi.arrayBuffer());
  const parsed=midiRuntime.parseMidi(bytes);
  let doc;
  if(song.json){
    if(song.json.size>8*1024*1024)throw Error('Lyrics JSON ใหญ่เกิน 8 MB');
    doc=jsonToDocument(await song.json.text(),song.name);
  }else{
    if(song.lrc.size>2*1024*1024)throw Error('LRC ใหญ่เกิน 2 MB');
    doc=lrcToDocument(await song.lrc.text(),song.name);
  }
  const lrc=documentToLrc(doc);
  if(!lrc.trim())throw Error('ไม่มีบรรทัดคำร้องพร้อมเวลาจริง');
  return {kind:state.kind,parsed,document:doc,lrc,safe:true,safeLyrics:true,warning:''};
}
function assessResources(duration,fontBytes=0,deviceMemory=null){
  const sec=Number(duration),font=Number(fontBytes)||0;
  if(!Number.isFinite(sec)||sec<=0||sec>900)return {ok:false,reason:'MIDI ยาวเกิน 15 นาทีสำหรับเบราว์เซอร์'};
  if(font>MAX_FONT)return {ok:false,reason:'SoundFont ใหญ่กว่า 256 MB · ใช้บน PC แทน'};
  // Approximate offline float buffer + WAV PCM + scheduling/decoder overhead.
  const mib=1024*1024;
  const peak=Math.ceil((sec+.5)*32000*2*12+font*2+48*mib);
  const memory=Number(deviceMemory);
  const budget=Number.isFinite(memory)&&memory>0
    ? (memory<=2?192:memory<=4?384:memory<=8?640:1024)*mib
    : 320*mib;
  return {ok:peak<=budget,peakBytes:peak,budgetBytes:budget,
    reason:peak<=budget?'พร้อมเรนเดอร์ในขอบเขตทรัพยากรที่ประเมิน':'คาดว่า RAM ไม่พอสำหรับ SoundFont/เพลงนี้ · ใช้ Song Studio PC'};
}
scope.XStageStudioMidiCore={groupIdentity,companionState,formatLrcTime,
  documentToLrc,lrcToDocument,jsonToDocument,inspectSong,assessResources,MAX_MIDI,MAX_FONT};
})(typeof window!=='undefined'?window:globalThis);
