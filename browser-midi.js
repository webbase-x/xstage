/* X-Stage browser MIDI renderer. No external executable, CDN or third-party script required.
 * Renders SMF/KAR to a seekable WAV with Web Audio. SF2 PCM and SF3 Ogg sample banks
 * are read from the owner's private Drive only after explicit SoundFont selection.
 * This is a bounded compatibility renderer, not a bit-exact FluidSynth replacement. */
(function(scope){
'use strict';
const MAX_MIDI=12*1024*1024, MAX_FONT=256*1024*1024, MAX_SECONDS=900, RATE=32000;
const $=id=>document.getElementById(id);
const u16=(d,p)=>d.getUint16(p,true),i16=(d,p)=>d.getInt16(p,true),u32=(d,p)=>d.getUint32(p,true);
const str=(a,p,n)=>String.fromCharCode(...a.subarray(p,p+n));
function fail(message){throw Error(message);}
function text(bytes){
  const b=bytes instanceof Uint8Array?bytes:new Uint8Array(bytes);
  for(const enc of ['utf-8','windows-874']){
    try{const s=new TextDecoder(enc,{fatal:enc==='utf-8'}).decode(b);
      if(s&&!s.includes('\ufffd'))return s;}catch{}
  }
  return new TextDecoder().decode(b);
}
function parseMidi(source){
  const b=source instanceof Uint8Array?source:new Uint8Array(source);
  if(b.byteLength<22||b.byteLength>MAX_MIDI||str(b,0,4)!=='MThd')fail('ไม่ใช่ไฟล์ MIDI มาตรฐานหรือไฟล์ใหญ่เกิน 12 MB');
  const d=new DataView(b.buffer,b.byteOffset,b.byteLength);
  const be16=p=>d.getUint16(p,false),be32=p=>d.getUint32(p,false);
  const header=be32(4),format=be16(8),ntracks=be16(10),division=be16(12);
  if(header<6||header>256||format>1||!ntracks||ntracks>256||(division&0x8000)||!division)
    fail('MIDI format/division นี้ไม่รองรับ');
  let cursor=8+header; const events=[];
  for(let track=0;track<ntracks;track++){
    if(cursor+8>b.length||str(b,cursor,4)!=='MTrk')fail('MIDI track ไม่สมบูรณ์');
    const size=be32(cursor+4);cursor+=8;
    const end=cursor+size;if(end>b.length)fail('MIDI track มีความยาวผิด');
    let tick=0,run=0,count=0;
    const varlen=()=>{let n=0;for(let i=0;i<4;i++){if(cursor>=end)fail('MIDI delta/length ไม่ครบ');const c=b[cursor++];n=(n<<7)|(c&127);if(!(c&128))return n;}fail('MIDI variable-length ผิดรูปแบบ');};
    while(cursor<end){
      if(++count>250000)fail('จำนวน MIDI events มากเกินขีดจำกัด');
      tick+=varlen();if(tick>200000000)fail('MIDI tick เกินขอบเขต');
      let s=b[cursor];if(s&128){cursor++;if(s<0xf0)run=s;}else{if(!run)fail('MIDI running status ผิด');s=run;}
      if(s===0xff){
        if(cursor>=end)fail('MIDI meta event ไม่ครบ');
        const type=b[cursor++],len=varlen();if(cursor+len>end)fail('MIDI meta ยาวเกิน track');
        if(type===0x51&&len===3){
          const tempo=(b[cursor]<<16)|(b[cursor+1]<<8)|b[cursor+2];
          if(tempo>=10000&&tempo<=10000000)events.push({tick,kind:'tempo',value:tempo,track});
        }else if((type===0x05||type===0x01||type===0x03)&&len&&len<4096){
          events.push({tick,kind:'text',value:text(b.subarray(cursor,cursor+len)),meta:type,track});
        }
        cursor+=len;
        if(type===0x2f){cursor=end;break;}
      }else if(s===0xf0||s===0xf7){
        const len=varlen();if(cursor+len>end)fail('MIDI SysEx ไม่ครบ');cursor+=len;run=0;
      }else if(s>=0x80&&s<=0xef){
        const k=s&0xf0,ch=s&15,n=k===0xc0||k===0xd0?1:2;
        if(cursor+n>end)fail('MIDI channel event ไม่ครบ');
        const a=b[cursor++],v=n===2?b[cursor++]:0;
        if(a>127||v>127)fail('MIDI channel data ผิด');
        events.push({tick,kind:'channel',k,ch,a,v,track});
      }else fail('MIDI system event ไม่รองรับ');
    }
    cursor=end;
  }
  events.sort((a,b)=>a.tick-b.tick||Number(b.kind==='tempo')-Number(a.kind==='tempo'));
  let prev=0,tempo=500000,clock=0;
  // NCN CUR stores 24 positions per quarter note, not seconds. Retain
  // the exact MIDI tempo timeline for converting its positions later.
  const tempoMap=[{tick:0,seconds:0,tempo}];
  const channels=Array.from({length:16},()=>({program:0,bank:0,volume:100,expression:127,notes:new Map(),sustain:false,held:[]}));
  const notes=[],lyricEvents=[];
  const endNote=(note,at)=>{if(!note)return;note.end=Math.max(note.start+.06,at);notes.push(note);};
  for(const e of events){
    clock+=(e.tick-prev)*tempo/(division*1000000);prev=e.tick;
    if(!Number.isFinite(clock)||clock>MAX_SECONDS+60)fail('MIDI ยาวเกินขอบเขตเรนเดอร์');
    if(e.kind==='tempo'){
      tempo=e.value;
      const latest=tempoMap[tempoMap.length-1];
      const point={tick:e.tick,seconds:clock,tempo};
      if(latest.tick===e.tick)tempoMap[tempoMap.length-1]=point;
      else tempoMap.push(point);
      continue;
    }
    if(e.kind==='text'){if(e.meta===5||e.meta===1)lyricEvents.push({time:clock,text:e.value,meta:e.meta,track:e.track});continue;}
    const c=channels[e.ch],id=e.a;
    if(e.k===0xc0)c.program=id;
    if(e.k===0xb0){
      if(id===0)c.bank=e.v;
      if(id===7)c.volume=e.v;
      if(id===11)c.expression=e.v;
      if(id===64){const down=e.v>=64;if(c.sustain&&!down){for(const n of c.held)endNote(n,clock);c.held=[];}c.sustain=down;}
      if(id===120||id===123){for(const q of c.notes.values())for(const n of q)endNote(n,clock);c.notes.clear();for(const n of c.held)endNote(n,clock);c.held=[];}
    }
    if(e.k===0x90&&e.v>0){
      const note={start:clock,end:clock+.25,key:id,velocity:e.v,channel:e.ch,
        program:c.program,bank:e.ch===9?128:c.bank,level:c.volume*c.expression/(127*127)};
      if(!c.notes.has(id))c.notes.set(id,[]);c.notes.get(id).push(note);
    }
    if(e.k===0x80||(e.k===0x90&&e.v===0)){
      const stack=c.notes.get(id);const note=stack?.shift();if(stack&&!stack.length)c.notes.delete(id);
      if(note){if(c.sustain)c.held.push(note);else endNote(note,clock);}
    }
  }
  for(const c of channels){
    for(const q of c.notes.values())for(const note of q)endNote(note,clock+.15);
    for(const note of c.held)endNote(note,clock+.15);
  }
  if(!notes.length)fail('MIDI ไม่มีโน้ตที่เล่นได้');
  const duration=Math.max(clock,...notes.map(x=>x.end))+1;
  if(duration>MAX_SECONDS)fail('MIDI ยาวเกิน 15 นาทีสำหรับตัวเรนเดอร์บนเว็บ');
  return {notes,duration,lyricEvents,division,tempoMap};
}
function midiLyrics(parsed,code){
  let title='',artist='';const pieces=[];
  for(const e of parsed.lyricEvents){
    let v=e.text.replace(/\0/g,'').trim();
    if(!v)continue;
    if(v.startsWith('@T')){if(!title)title=v.slice(2);else if(!artist)artist=v.slice(2);continue;}
    if(v.startsWith('@'))continue;
    if(e.meta!==5&&!/[\\/]/.test(v))continue;
    if(v.startsWith('\\')||v.startsWith('/'))v=v.slice(1);
    v=v.replace(/[\\/]/g,'').trim();
    if(v)pieces.push({time:e.time,text:v});
  }
  const lines=[];
  let group=[];
  function flush(){
    if(!group.length)return;
    const start=group[0].time,end=Math.max(start+.25,group[group.length-1].time+1);
    lines.push({startTime:start,endTime:end,text:group.map(x=>x.text).join(''),
      syllables:group.map((x,i)=>({text:x.text,start:x.time,
        duration:Math.max(.04,(group[i+1]?.time||end)-x.time)}))});
    group=[];
  }
  for(const x of pieces){
    if(group.length&&(x.time-group[group.length-1].time>3.8||group.length>120))flush();
    group.push(x);
  }
  flush();
  if(!lines.length)lines.push({startTime:0,endTime:Math.min(parsed.duration,10),text:'♪ ดนตรีบรรเลง ♪'});
  return {schemaVersion:1,songCode:code,title,artist,lines};
}
function ncnTickSeconds(position,midi){
  // CUR is NCN24: 24 cursor positions per quarter, independent of MIDI PPQ.
  // Each MIDI tempo change owns the time interval until the next change.
  const tick=position*midi.division/24,entries=midi.tempoMap;
  let low=0,high=entries.length-1;
  while(low<high){
    const mid=Math.ceil((low+high)/2);
    if(entries[mid].tick<=tick)low=mid;
    else high=mid-1;
  }
  const point=entries[low];
  return point.seconds+(tick-point.tick)*point.tempo/(midi.division*1000000);
}
function ncnLyrics(lyrBytes,curBytes,code,midi){
  // LYR/CUR uses *source CP874 bytes*, not JS characters. NCN consumes one
  // invisible CUR entry before every nonblank lyric line, then one per byte.
  if(!midi||!Number.isFinite(midi.division)||midi.division<=0||
      !Array.isArray(midi.tempoMap)||!midi.tempoMap.length||
      !Number.isFinite(midi.duration))fail('NCN ต้องใช้ผลอ่าน MIDI และ Tempo จริงในการแปลงเวลา');
  const source=lyrBytes instanceof Uint8Array?lyrBytes:new Uint8Array(lyrBytes);
  if(source.length>1024*1024)fail('LYR NCN ใหญ่เกิน 1 MB');
  const eof=source.indexOf(0x1a),last=eof<0?source.length:eof;
  const rows=[];
  let from=0;
  for(let p=0;p<last;p++){
    if(source[p]===13||source[p]===10){
      rows.push(source.subarray(from,p));
      if(source[p]===13&&p+1<last&&source[p+1]===10)p++;
      from=p+1;
    }
  }
  rows.push(source.subarray(from,last));
  if(rows.length<5)fail('LYR NCN ต้องมีส่วนหัวสี่บรรทัด');
  const decoder=new TextDecoder('windows-874');
  const decode=bytes=>{
    const content=decoder.decode(bytes);
    if(content.includes('\ufffd'))fail('LYR NCN มีไบต์ข้อความที่รหัส CP874 ไม่รองรับ');
    return content;
  };
  const cur=curBytes instanceof Uint8Array?curBytes:new Uint8Array(curBytes);
  if(cur.length<2||cur.length>2*1024*1024)fail('CUR NCN ขนาดไม่ถูกต้อง');
  let valid=cur.length;
  // Historic NCN exporters may terminate a uint16-le CUR with one FF byte.
  if(valid%2){
    if(cur[valid-1]!==255)fail('CUR NCN มีไบต์ท้ายไม่ครบหนึ่งค่าเวลา');
    valid--;
  }
  const positions=new DataView(cur.buffer,cur.byteOffset,valid);
  const count=valid/2;
  if(!count)fail('CUR NCN ไม่มีตำแหน่งเวลา');
  const body=rows.slice(4);
  while(body.length&&!body[body.length-1].some(x=>x!==0&&x!==32&&x!==9))
    body.pop();
  let index=0,previous=0,partial=false,removedFooter=0;
  const warnings=[],lines=[];
  const vendorFooter=/^(?:nick[\s_-]*karaoke(?:\s+professional)?|นิค[\s_-]*คาราโอเกะ|by[\s_-]*นิค[\s_-]*คาราโอเกะ)$/i;
  const isNonempty=bytes=>bytes.some(x=>x!==0&&x!==32&&x!==9);
  const needed=bytes=>bytes.length+1;
  // Exclude only *untimed* vendor credits at the end. A timed vendor line
  // is kept as real stage text, as on the existing X-Stage PC parser.
  while(body.length&&count<body.filter(isNonempty).reduce((n,row)=>n+needed(row),0)){
    const trailing=body[body.length-1],caption=decode(trailing).trim();
    if(!vendorFooter.test(caption))break;
    body.pop();removedFooter++;
    while(body.length&&!isNonempty(body[body.length-1]))body.pop();
  }
  const mark=/\p{M}/u;
  let stop=false;
  for(const row of body){
    if(!isNonempty(row))continue;
    if(index>=count){partial=true;warnings.push('CUR มีเวลาไม่พอสำหรับเนื้อร้องทั้งหมด');break;}
    // Windows-874 is single-byte; decode the whole line only once and keep
    // each raw byte's exact glyph offset for CUR alignment (important for
    // large NCN folders on older TV WebViews).
    const rowText=decode(row);
    if(rowText.length!==row.length)fail('LYR NCN ไม่ใช่ CP874 ไบต์ต่ออักษร');
    index++; // one NCN newline/line-marker cue, not a printable character
    const syllables=[];
    let displayed='';
    for(let byteIndex=0;byteIndex<row.length;byteIndex++){
      if(index>=count){partial=true;stop=true;break;}
      const position=positions.getUint16(index*2,true);index++;
      if(position===65535){
        partial=true;
        // 65535 is untimed, not an absolute 2730-second lyric position.
        warnings.push('CUR มีค่า 65535 ในตำแหน่งอักษร · ข้ามเฉพาะอักษรที่ไม่มีเวลา');
        continue;
      }
      const effective=Math.max(previous,position);
      if(effective!==position)warnings.push('CUR มีเวลาย้อนกลับ · คงลำดับเวลาตามตัวเล่น PC');
      previous=effective;
      const at=ncnTickSeconds(effective,midi);
      if(!Number.isFinite(at)||at>midi.duration+10){
        partial=true;stop=true;
        warnings.push('CUR มีเวลาเกินช่วง MIDI · ไม่สร้างเวลาแทน');
        break;
      }
      const letter=rowText[byteIndex];
      displayed+=letter;
      if(mark.test(letter)&&syllables.length)syllables[syllables.length-1].text+=letter;
      else syllables.push({text:letter,start:at,duration:.08});
    }
    if(syllables.length&&displayed.trim()){
      for(let k=0;k<syllables.length;k++){
        const next=syllables[k+1]?.start;
        syllables[k].duration=Math.max(.03,(next??syllables[k].start+.4)-syllables[k].start);
      }
      const startTime=syllables[0].start;
      const endTime=Math.max(startTime+.1,
        syllables[syllables.length-1].start+.5);
      lines.push({startTime,endTime,text:displayed,syllables});
    }
    if(stop)break;
  }
  if(!lines.length)fail('LYR/CUR NCN ไม่มีเนื้อร้องที่จับคู่เวลาจริงได้');
  if(partial)warnings.push('เนื้อร้องบางส่วนไม่มีเวลา CUR จริง · ใช้เฉพาะส่วนที่ตรวจสอบได้');
  const metadata={
    timingComplete:!partial, cursorValues:count,
    unusedCursorValues:Math.max(0,count-index),
    removedUntimedFooterLines:removedFooter,
    timingWarnings:[...new Set(warnings)]
  };
  return {schemaVersion:1,songCode:code,sourceFormat:'NCN',
    title:decode(rows[0]).trim(),artist:decode(rows[1]).trim(),
    lines,metadata};
}

function parseFont(data){
  const b=data instanceof Uint8Array?data:new Uint8Array(data);
  if(b.byteLength<256||b.byteLength>MAX_FONT||str(b,0,4)!=='RIFF'||str(b,8,4)!=='sfbk')
    fail('SoundFont ไม่ใช่ SF2/SF3 ที่สมบูรณ์ หรือเกิน 256 MB');
  const d=new DataView(b.buffer,b.byteOffset,b.byteLength),chunks=new Map();
  const end=Math.min(b.length,8+u32(d,4));
  if(end!==b.length&&end+1!==b.length)fail('RIFF SoundFont ขนาดไม่ตรง');
  for(let at=12;at+12<=end;){
    const type=str(b,at,4),len=u32(d,at+4);
    if(at+8+len>end)fail('SoundFont RIFF chunk เสีย');
    if(type==='LIST'){
      const base=str(b,at+8,4);
      if(base==='sdta'||base==='pdta'||base==='INFO'){
        for(let p=at+12;p+8<=at+8+len;){
          const id=str(b,p,4),size=u32(d,p+4);
          if(p+8+size>at+8+len)fail('SoundFont subchunk เสีย');
          chunks.set(id,{at:p+8,len:size});
          p+=8+size+(size&1);
        }
      }
    }
    at+=8+len+(len&1);
  }
  for(const name of ['smpl','phdr','pbag','pgen','inst','ibag','igen','shdr'])
    if(!chunks.has(name))fail('SoundFont ขาดโครงสร้าง '+name);
  const records=(name,size,fn)=>{
    const c=chunks.get(name),n=Math.floor(c.len/size),out=[];
    if(n>400000)fail('SoundFont metadata มีขนาดผิด');
    for(let i=0;i<n;i++)out.push(fn(c.at+i*size));
    return out;
  };
  const presets=records('phdr',38,p=>({program:u16(d,p+20),bank:u16(d,p+22),bag:u16(d,p+24)}));
  const pbag=records('pbag',4,p=>u16(d,p)),pgen=records('pgen',4,p=>[u16(d,p),u16(d,p+2)]);
  const inst=records('inst',22,p=>u16(d,p+20));
  const ibag=records('ibag',4,p=>u16(d,p)),igen=records('igen',4,p=>[u16(d,p),u16(d,p+2)]);
  const samples=records('shdr',46,p=>({start:u32(d,p+20),end:u32(d,p+24),loopStart:u32(d,p+28),loopEnd:u32(d,p+32),
    rate:u32(d,p+36),pitch:b[p+40],correct:d.getInt8(p+41),type:u16(d,p+44)}));
  const zone=(bags,gens,i)=>{const start=bags[i],end=bags[i+1]??gens.length;
    const g=new Map();for(let j=start;j<end&&j<gens.length;j++)g.set(gens[j][0],gens[j][1]);return g;};
  const within=(g,key,vel)=>{const k=g.get(43),v=g.get(44);
    return (k===undefined||(key>=(k&255)&&key<=(k>>8)))&&
      (v===undefined||(vel>=(v&255)&&vel<=(v>>8)));};
  const combine=(a,b)=>new Map([...a,...b]);
  function find(bank,program,key,velocity){
    const p=presets.findIndex(x=>x.bank===bank&&x.program===program);
    const selected=p>=0?p:presets.findIndex(x=>x.bank===0&&x.program===program);
    if(selected<0||selected>=presets.length-1)return [];
    const result=[],first=presets[selected].bag,last=presets[selected+1].bag;
    let pg=new Map();
    for(let i=first;i<last;i++){
      const a=zone(pbag,pgen,i);
      if(!a.has(41)){pg=combine(pg,a);continue;}
      const g=combine(pg,a);if(!within(g,key,velocity))continue;
      const number=g.get(41);if(number>=inst.length-1)continue;
      let ig=new Map();
      for(let z=inst[number];z<inst[number+1];z++){
        const b=zone(ibag,igen,z);
        if(!b.has(53)){ig=combine(ig,b);continue;}
        const c=combine(g,combine(ig,b));
        if(within(c,key,velocity)&&c.get(53)<samples.length-1)result.push(c);
        if(result.length>=4)return result;
      }
    }
    return result;
  }
  return {b,d,chunks,samples,find,cache:new Map()};
}
async function sampleBuffer(font,index,context){
  if(font.cache.has(index))return font.cache.get(index);
  const sample=font.samples[index],chunk=font.chunks.get('smpl');
  if(!sample||!sample.rate||sample.rate>192000)fail('SoundFont sample header ผิด');
  let buffer;
  if(sample.type&0x10){
    const start=chunk.at+sample.start,end=chunk.at+sample.end;
    if(start<chunk.at||end>chunk.at+chunk.len||end-start<32||end-start>24*1024*1024)
      fail('SF3 compressed sample อยู่นอกขอบเขต');
    try{buffer=await context.decodeAudioData(font.b.slice(start,end).buffer);}
    catch{fail('เบราว์เซอร์นี้ถอดรหัสเสียง SF3 ไม่ได้ · กรุณาเลือก SF2 หรือเสียงพื้นฐาน');}
  }else{
    const n=sample.end-sample.start,at=chunk.at+sample.start*2;
    if(n<1||n>sample.rate*90||at<chunk.at||at+n*2>chunk.at+chunk.len)
      fail('SF2 PCM sample อยู่นอกขอบเขต');
    buffer=context.createBuffer(1,n,sample.rate);
    const out=buffer.getChannelData(0);
    for(let i=0;i<n;i++)out[i]=font.d.getInt16(at+i*2,true)/32768;
  }
  if(font.cache.size>=80)font.cache.delete(font.cache.keys().next().value);
  font.cache.set(index,buffer);
  return buffer;
}
function toWav(audio){
  const n=audio.length,channels=Math.min(2,audio.numberOfChannels),bytes=n*channels*2,buf=new ArrayBuffer(44+bytes),d=new DataView(buf);
  const ascii=(p,s)=>{for(let i=0;i<s.length;i++)d.setUint8(p+i,s.charCodeAt(i));};
  ascii(0,'RIFF');d.setUint32(4,36+bytes,true);ascii(8,'WAVE');ascii(12,'fmt ');
  d.setUint32(16,16,true);d.setUint16(20,1,true);d.setUint16(22,channels,true);
  d.setUint32(24,audio.sampleRate,true);d.setUint32(28,audio.sampleRate*channels*2,true);
  d.setUint16(32,channels*2,true);d.setUint16(34,16,true);ascii(36,'data');d.setUint32(40,bytes,true);
  const data=Array.from({length:channels},(_,i)=>audio.getChannelData(i));
  let pos=44;
  for(let i=0;i<n;i++)for(let c=0;c<channels;c++){
    const x=Math.max(-1,Math.min(1,data[c][i]));
    d.setInt16(pos,x<0?x*32768:x*32767,true);pos+=2;
  }
  return new Blob([buf],{type:'audio/wav'});
}
async function render(source,{fontBytes=null,signal=null,onStatus=null}={}){
  const check=()=>{if(signal?.aborted)fail('ยกเลิกการเตรียม MIDI แล้ว');};
  check();const song=parseMidi(source),ctx=new OfflineAudioContext(2,Math.ceil((song.duration+.5)*RATE),RATE);
  const font=fontBytes?parseFont(fontBytes):null;
  let num=0,scheduled=0;
  const master=ctx.createGain();master.gain.value=font?.75:.24;master.connect(ctx.destination);
  for(const note of song.notes){
    if(num++%200===0){check();onStatus?.('เตรียม MIDI '+Math.floor(num*100/song.notes.length)+'%');
      await new Promise(resolve=>setTimeout(resolve,0));}
    const start=Math.max(0,note.start),end=Math.max(start+.06,note.end);
    let regions=font?font.find(note.bank,note.program,note.key,note.velocity):[];
    if(font&&!regions.length)continue;
    if(!font)regions=[null];
    for(const g of regions){
      scheduled++;
      const gain=ctx.createGain(),velocity=Math.pow(note.velocity/127,1.5),level=Math.max(0,Math.min(1,note.level));
      const attenuation=g?(g.get(48)||0):0;
      const amp=Math.max(.00001,velocity*level*Math.pow(10,-attenuation/200)*(.5/Math.max(1,regions.length)));
      // SF2 omitted envelope generators use -12000 timecents, not zero seconds
      // (zero timecents means a full one-second envelope).
      const signed=v=>v>32767?v-65536:v;
      const volSeconds=(operator,fallback)=>Math.pow(2,signed(g?.get(operator)??fallback)/1200);
      const release=g?Math.max(.04,Math.min(4,volSeconds(38,-12000))):.12;
      const attack=g?Math.max(.005,Math.min(.5,volSeconds(34,-12000))):.015;
      gain.gain.setValueAtTime(.00001,start);
      gain.gain.linearRampToValueAtTime(amp,start+Math.min(attack,Math.max(.01,(end-start)/2)));
      gain.gain.setValueAtTime(amp,end);
      gain.gain.exponentialRampToValueAtTime(.00001,Math.min(song.duration+.3,end+release));
      gain.connect(master);
      if(g){
        const si=g.get(53),s=font.samples[si],buffer=await sampleBuffer(font,si,ctx);
        const src=ctx.createBufferSource();src.buffer=buffer;
        const pitch=g.has(58)?g.get(58):s.pitch;
        const coarse=g.has(51)?(g.get(51)<<16>>16):0;
        const fine=g.has(52)?(g.get(52)<<16>>16):0;
        src.playbackRate.value=Math.pow(2,(note.key-pitch+coarse+(fine+s.correct)/100)/12);
        const mode=g.get(54)||0;
        if((mode&1)&&s.loopStart>=s.start&&s.loopEnd<=s.end&&
            s.loopEnd>s.loopStart+8&&!(s.type&0x10)){
          src.loop=true;src.loopStart=(s.loopStart-s.start)/s.rate;src.loopEnd=(s.loopEnd-s.start)/s.rate;
        }
        src.connect(gain);src.start(start);src.stop(Math.min(song.duration+.4,end+release+.03));
      }else{
        const src=ctx.createOscillator();
        src.type=note.channel===9?'square':note.program>=80?'sawtooth':note.program>=40?'triangle':'sine';
        src.frequency.value=440*Math.pow(2,(note.key-69)/12);
        src.connect(gain);src.start(start);src.stop(Math.min(song.duration+.4,end+release+.03));
      }
    }
  }
  if(font&&!scheduled)fail('SoundFont นี้ไม่มี preset ที่ใช้กับ MIDI · กรุณาเลือกซาวด์ฟอนต์อื่น');
  onStatus?.('กำลังสังเคราะห์เสียง MIDI…');
  const result=await ctx.startRendering();check();
  onStatus?.('กำลังเตรียมเสียงสำหรับเล่น…');
  return {audio:toWav(result),lyrics:midiLyrics(song,''),duration:song.duration};
}
let context=null,selected='',fontCache=null,fontRefreshSequence=0,fontRefreshPromise=null;
async function listFolder(parent,token){
  const list=[];let page='';
  do{
    const q=new URLSearchParams({q:"'"+parent+"' in parents and trashed=false",
      fields:'nextPageToken,files(id,name,mimeType,size)',pageSize:'1000'});
    if(page)q.set('pageToken',page);
    const response=await fetch('https://www.googleapis.com/drive/v3/files?'+q,
      {headers:{Authorization:'Bearer '+token},cache:'no-store'});
    if(!response.ok)fail('อ่านรายการ SoundFont บน Drive ไม่สำเร็จ HTTP '+response.status);
    const json=await response.json();list.push(...(json.files||[]));page=json.nextPageToken||'';
  }while(page&&list.length<10000);
  return list;
}
async function refreshFonts(auth){
  const sequence=++fontRefreshSequence;
  const select=$('xstage-soundfont-select');if(!select)return;
  const sameLibrary=context?.sub===auth?.sub&&context?.rootId===auth?.rootId;
  context=auth;
  if(!sameLibrary){selected='';fontCache=null;}
  select.replaceChildren(new Option('กำลังตรวจสอบ SoundFont…',''));
  const pending=(async()=>{
    const sub=auth?.sub||'',rootId=auth?.rootId||'';
    const choices=[new Option('เสียง MIDI พื้นฐานในเว็บ (ไม่ใช้ SoundFont)','')];
    if(!auth?.token||!rootId){
      if(sequence===fontRefreshSequence){selected='';fontCache=null;select.replaceChildren(...choices);}
      return;
    }
    try{
      const categories=await listFolder(rootId,auth.token);
      const audio=categories.find(x=>x.name==='AUDIO'&&x.mimeType==='application/vnd.google-apps.folder');
      if(audio){
        const files=await listFolder(audio.id,auth.token);
        for(const f of files.filter(x=>/\.sf[23]$/i.test(x.name)&&
          x.mimeType!=='application/vnd.google-apps.folder'))
          choices.push(new Option(f.name+' ('+Math.round(Number(f.size||0)/1048576)+' MB)',f.id));
      }else{
        // Old library still readable; new uploads always use flat AUDIO.
        const old=categories.find(x=>x.name==='SOUNDFONT'&&x.mimeType==='application/vnd.google-apps.folder');
        if(old){
          for(const dir of (await listFolder(old.id,auth.token)).filter(x=>
            x.mimeType==='application/vnd.google-apps.folder'&&['SF2','SF3'].includes(x.name.toUpperCase())))
            for(const f of (await listFolder(dir.id,auth.token)).filter(x=>/\.sf[23]$/i.test(x.name)&&x.mimeType!=='application/vnd.google-apps.folder'))
              choices.push(new Option(f.name+' ('+Math.round(Number(f.size||0)/1048576)+' MB)',f.id));
        }
      }
      if(sequence!==fontRefreshSequence)return;
      const storageKey='xstage-font-pref:'+sub+':'+rootId;
      let saved='';
      try{saved=localStorage.getItem(storageKey)||'';}catch{}
      select.replaceChildren(...choices);
      select.value=choices.some(x=>x.value===saved)?saved:'';
      selected=select.value;
      select.onchange=()=>{
        selected=select.value;fontCache=null;
        try{localStorage.setItem(storageKey,selected);}catch{}
      };
    }catch(error){
      if(sequence!==fontRefreshSequence)return;
      select.replaceChildren(...choices);
      const option=new Option('SoundFont: '+String(error.message).slice(0,80),'');
      option.disabled=true;select.append(option);
      selected='';fontCache=null;
    }
  })();
  fontRefreshPromise=pending;
  try{await pending;}
  finally{if(fontRefreshPromise===pending)fontRefreshPromise=null;}
}
async function selectedFont(token,signal){
  if(fontRefreshPromise)await fontRefreshPromise;
  if(signal?.aborted)throw new DOMException('ยกเลิกการโหลด SoundFont','AbortError');
  if(!selected)return null;
  if(!context||token!==context.token)fail('บัญชี Google เปลี่ยน · โปรดเลือก SoundFont อีกครั้ง');
  const id=selected,sub=context.sub;
  if(fontCache?.id===id&&fontCache?.sub===sub)return fontCache.bytes;
  const res=await fetch('https://www.googleapis.com/drive/v3/files/'+encodeURIComponent(id)+'?alt=media',
    {headers:{Authorization:'Bearer '+token},cache:'no-store',signal});
  if(!res.ok)fail('โหลด SoundFont จาก Drive ไม่สำเร็จ HTTP '+res.status);
  const len=Number(res.headers.get('Content-Length')||0);
  if(len>MAX_FONT)fail('SoundFont ใหญ่กว่า 256 MB ไม่เหมาะกับหน่วยความจำเบราว์เซอร์');
  const bytes=new Uint8Array(await res.arrayBuffer());
  if(bytes.byteLength>MAX_FONT)fail('SoundFont ใหญ่เกินขอบเขตหน่วยความจำ');
  if(signal?.aborted)throw new DOMException('ยกเลิกการโหลด SoundFont','AbortError');
  if(selected!==id||context?.token!==token||context?.sub!==sub)fail('รายการ SoundFont เปลี่ยนระหว่างโหลด · กรุณาเลือกใหม่');
  parseFont(bytes);fontCache={id,sub,bytes};return bytes;
}
scope.XStageBrowserMidi={parseMidi,midiLyrics,ncnLyrics,parseFont,render,refreshFonts,selectedFont,
  reset(){fontRefreshSequence++;fontRefreshPromise=null;context=null;selected='';fontCache=null;const node=$('xstage-soundfont-select');if(node)node.replaceChildren(new Option('เสียง MIDI พื้นฐานในเว็บ',''));}};
scope.addEventListener?.('xstage:auth-cleared',()=>scope.XStageBrowserMidi.reset());
})(typeof window!=='undefined'?window:globalThis);
