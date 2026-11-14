/* Shared offline Song Studio Web MIDI/NCN bridge.
 * Reuse the bundled XStageBrowserMidi parser: NEVER invent NCN CUR timestamps.
 * Source MID, LYR and CUR are read-only and are never uploaded by this module. */
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
  if(/\.ncn$/i.test(song.midi.name))
    return {kind:'NCN',complete:false,message:'NCN ต้องเป็นชุด MID + LYR + CUR ไม่ใช่ไฟล์ .ncn เดี่ยว'};
  if(song.lyr||song.cur){
    if(!song.lyr||!song.cur)
      return {kind:'NCN',complete:false,message:'ชุด NCN ยังไม่ครบ: ต้องมี MID + LYR + CUR รหัสเดียวกัน'};
    return {kind:'NCN',complete:true,message:'NCN · MID + LYR + CUR ครบ'};
  }
  return {kind:/\.kar$/i.test(song.midi.name)?'KAR':'MIDI',
    complete:true,message:'MIDI/KAR · ตรวจข้อมูลเพลงจากต้นฉบับ'};
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
function hasDangerousCursorWarnings(doc){
  const warnings=doc?.metadata?.timingWarnings||[];
  return !doc?.metadata?.timingComplete ||
    warnings.some(w=>/ย้อนกลับ|65535|ไม่มีเวลา|เวลาไม่พอ|เกินช่วง/i.test(String(w)));
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
async function inspectSong(song,midiRuntime){
  const state=companionState(song);
  if(!song?.midi||!state.complete)throw Error(state.message||'ไม่มีไฟล์ MIDI');
  if(song.midi.size<22||song.midi.size>MAX_MIDI)
    throw Error('MIDI ไม่สมบูรณ์หรือมีขนาดเกิน 12 MB');
  const bytes=new Uint8Array(await song.midi.arrayBuffer());
  const parsed=midiRuntime.parseMidi(bytes);
  let doc;
  if(state.kind==='NCN'){
    if(song.lyr.size>1024*1024||song.cur.size>2*1024*1024)
      throw Error('LYR/CUR NCN ใหญ่เกินขอบเขตปลอดภัย');
    doc=midiRuntime.ncnLyrics(new Uint8Array(await song.lyr.arrayBuffer()),
      new Uint8Array(await song.cur.arrayBuffer()),song.name,parsed);
  }else doc=midiRuntime.midiLyrics(parsed,song.name);
  const lrc=documentToLrc(doc);
  const warnings=doc?.metadata?.timingWarnings||[];
  const safe=state.kind!=='NCN'||!hasDangerousCursorWarnings(doc);
  return {kind:state.kind,parsed,document:doc,lrc,
    safe,safeLyrics:!!lrc&&safe,
    warning:!safe?'NCN มี CUR ย้อนกลับ/ไม่สมบูรณ์ · ข้ามการส่งออกที่มีเวลาเพื่อป้องกันเนื้อร้องผิด':
      warnings.join(' · ')};
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
  documentToLrc,lrcToDocument,inspectSong,assessResources,MAX_MIDI,MAX_FONT};
})(typeof window!=='undefined'?window:globalThis);
