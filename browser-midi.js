/* X-Stage browser MIDI renderer. No external executable, CDN or third-party script required.
 * Renders SMF/KAR to a seekable WAV with Web Audio. SF2 PCM and SF3 Ogg sample banks
 * may come from the owner's private Drive, or the explicitly credited small GPL GM default.
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
        }else if(type===0x59&&len===2){
          // Standard MIDI key signature: signed sharps/flats (-7..7),
          // followed by 0=major or 1=minor.
          const sf=(b[cursor]<<24)>>24,minor=b[cursor+1];
          if(sf>=-7&&sf<=7&&(minor===0||minor===1))
            events.push({tick,kind:'keySignature',sf,minor,track});
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
  const channels=Array.from({length:16},()=>({program:0,bank:0,volume:100,expression:127,pan:64,notes:new Map(),sustain:false,held:[]}));
  const notes=[],lyricEvents=[];
  let keySignature='';
  const keyNames={
    majorSharp:['C','G','D','A','E','B','F♯','C♯'],
    majorFlat:['C','F','B♭','E♭','A♭','D♭','G♭','C♭'],
    minorSharp:['Am','Em','Bm','F♯m','C♯m','G♯m','D♯m','A♯m'],
    minorFlat:['Am','Dm','Gm','Cm','Fm','B♭m','E♭m','A♭m']
  };
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
    if(e.kind==='keySignature'){
      if(!keySignature)keySignature=keyNames[
        e.minor?(e.sf<0?'minorFlat':'minorSharp'):(e.sf<0?'majorFlat':'majorSharp')
      ][Math.abs(e.sf)];
      continue;
    }
    if(e.kind==='text'){if(e.meta===5||e.meta===1)lyricEvents.push({time:clock,text:e.value,meta:e.meta,track:e.track});continue;}
    const c=channels[e.ch],id=e.a;
    if(e.k===0xc0)c.program=id;
    if(e.k===0xb0){
      if(id===0)c.bank=e.v;
      if(id===7)c.volume=e.v;
      if(id===11)c.expression=e.v;
      if(id===10)c.pan=e.v;
      if(id===64){const down=e.v>=64;if(c.sustain&&!down){for(const n of c.held)endNote(n,clock);c.held=[];}c.sustain=down;}
      if(id===120||id===123){for(const q of c.notes.values())for(const n of q)endNote(n,clock);c.notes.clear();for(const n of c.held)endNote(n,clock);c.held=[];}
    }
    if(e.k===0x90&&e.v>0){
      const note={start:clock,end:clock+.25,key:id,velocity:e.v,channel:e.ch,
        program:c.program,bank:e.ch===9?128:c.bank,
        // Keep raw CC7 / CC11 and pan for the native-grade synth. Multiplying
        // them into velocity before a SoundFont's own controller response
        // weakens the attack and can double-attenuate the arrangement.
        channelVolume:c.volume,channelExpression:c.expression,pan:c.pan,
        level:c.volume*c.expression/(127*127)};
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
  return {notes,duration,lyricEvents,division,tempoMap,keySignature};
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

// A large SoundFont is parsed by the dedicated AudioWorklet after playback
// starts. Avoid parsing its entire preset/sample tree on the iPhone UI thread
// while the user is waiting at the Play button.
function validateFontContainer(bytes){
  const b=bytes instanceof Uint8Array?bytes:new Uint8Array(bytes);
  if(b.byteLength<256||b.byteLength>MAX_FONT||
     str(b,0,4)!=='RIFF'||str(b,8,4)!=='sfbk')
    fail('ไฟล์ SoundFont ไม่ใช่ SF2/SF3 ที่สมบูรณ์');
  const reported=u32(new DataView(b.buffer,b.byteOffset,b.byteLength),4)+8;
  if(reported!==b.byteLength&&reported+1!==b.byteLength)
    fail('SoundFont RIFF ขนาดไม่ตรง');
  return true;
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
  return {b,d,chunks,samples,find,cache:new Map(),cacheBytes:0};
}
// A chord can request the same SF2 sample from many simultaneous notes.
// Decode each sample once, then share the pending Promise across those notes.
const pendingSampleBuffers=new WeakMap();
async function sampleBuffer(font,index,context){
  if(font.cache.has(index))return font.cache.get(index);
  let pending=pendingSampleBuffers.get(font);
  if(!pending){pending=new Map();pendingSampleBuffers.set(font,pending);}
  if(pending.has(index))return pending.get(index);
  const task=decodeSampleBuffer(font,index,context);
  pending.set(index,task);
  try{return await task;}
  finally{if(pending.get(index)===task)pending.delete(index);}
}
async function decodeSampleBuffer(font,index,context){
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
  // Keep decoded sample buffers across songs, but enforce a memory budget.
  // An AudioBuffer is ~4 bytes per sample per channel; this is an estimate.
  const low=Number(scope.navigator?.deviceMemory||4)<=2;
  const limit=(low?12:48)*1048576;
  const weight=buffer.length*buffer.numberOfChannels*4;
  while(font.cache.size&&(font.cache.size>=80||font.cacheBytes+weight>limit)){
    const oldest=font.cache.keys().next().value,removed=font.cache.get(oldest);
    font.cacheBytes-=removed.length*removed.numberOfChannels*4;
    font.cache.delete(oldest);
  }
  if(weight<=limit){font.cache.set(index,buffer);font.cacheBytes+=weight;}
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
async function render(source,{fontBytes=null,signal=null,onStatus=null,
  transpose=0,channelMutes=null,channelVolumes=null}={}){
  const check=()=>{if(signal?.aborted)fail('ยกเลิกการเตรียม MIDI แล้ว');};
  check();const song=parseMidi(source),ctx=new OfflineAudioContext(2,Math.ceil((song.duration+.5)*RATE),RATE);
  const shift=Math.max(-12,Math.min(12,Math.trunc(Number(transpose)||0)));
  const muted=Array.isArray(channelMutes)?channelMutes:[];
  const levels=Array.isArray(channelVolumes)?channelVolumes:[];
  const font=fontBytes?(fontCache?.bytes===fontBytes&&fontCache.parsed
    ?fontCache.parsed:parseFont(fontBytes)):null;
  let num=0,scheduled=0;
  const master=ctx.createGain();master.gain.value=font?.75:.24;master.connect(ctx.destination);
  for(const note of song.notes){
    if(num++%200===0){check();onStatus?.('เตรียม MIDI '+Math.floor(num*100/song.notes.length)+'%');
      await new Promise(resolve=>setTimeout(resolve,0));}
    if(muted[note.channel])continue;
    const pitchKey=note.channel===9?note.key:Math.max(0,Math.min(127,note.key+shift));
    const userLevel=Number(levels[note.channel]);
    const channelLevel=Number.isFinite(userLevel)?Math.max(0,Math.min(1,userLevel)):1;
    if(!channelLevel)continue;
    const start=Math.max(0,note.start),end=Math.max(start+.06,note.end);
    let regions=font?font.find(note.bank,note.program,pitchKey,note.velocity):[];
    if(font&&!regions.length)continue;
    if(!font)regions=[null];
    for(const g of regions){
      scheduled++;
      const gain=ctx.createGain(),velocity=Math.pow(note.velocity/127,1.5),level=Math.max(0,Math.min(1,note.level));
      const attenuation=g?(g.get(48)||0):0;
      const amp=Math.max(.00001,velocity*level*channelLevel*Math.pow(10,-attenuation/200)*(.5/Math.max(1,regions.length)));
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
        src.playbackRate.value=Math.pow(2,(pitchKey-pitch+coarse+(fine+s.correct)/100)/12);
        const mode=g.get(54)||0;
        if((mode&1)&&s.loopStart>=s.start&&s.loopEnd<=s.end&&
            s.loopEnd>s.loopStart+8&&!(s.type&0x10)){
          src.loop=true;src.loopStart=(s.loopStart-s.start)/s.rate;src.loopEnd=(s.loopEnd-s.start)/s.rate;
        }
        src.connect(gain);src.start(start);src.stop(Math.min(song.duration+.4,end+release+.03));
      }else{
        const src=ctx.createOscillator();
        src.type=note.channel===9?'square':note.program>=80?'sawtooth':note.program>=40?'triangle':'sine';
        src.frequency.value=440*Math.pow(2,(pitchKey-69)/12);
        src.connect(gain);src.start(start);src.stop(Math.min(song.duration+.4,end+release+.03));
      }
    }
  }
  if(font&&!scheduled)fail('SoundFont นี้ไม่มี preset ที่ใช้กับ MIDI · กรุณาเลือกซาวด์ฟอนต์อื่น');
  onStatus?.('กำลังสังเคราะห์เสียง MIDI…');
  const result=await ctx.startRendering();check();
  onStatus?.('กำลังเตรียมเสียงสำหรับเล่น…');
  const rendered={audio:toWav(result),lyrics:midiLyrics(song,''),duration:song.duration};
  // The parsed SoundFont and bounded samples remain cached; emit their
  // updated footprint after rendering, never on every sample lookup.
  if(fontCache?.parsed===font)fontStatusChanged();
  return rendered;
}
// Small GPL-2.0 General MIDI bank from the pretty-midi project.
// Used only when the listener has not chosen a private SoundFont.
// Original: https://github.com/craffel/pretty-midi/blob/main/pretty_midi/TimGM6mb.sf2
// Source/license: https://github.com/craffel/pretty-midi and TimGM6mb GPL-2.0.
const BUILTIN_GM_ID='builtin:TimGM6mb';
const BUILTIN_GM_URL='https://raw.githubusercontent.com/craffel/pretty-midi/main/pretty_midi/TimGM6mb.sf2';
const BUILTIN_GM_MAX_BYTES=8*1048576;
// Large PC-sized SF2 banks must never delay the first audible web MIDI note.
const FAST_START_FONT_MAX_BYTES=48*1048576;
let quickGmPromise=null,quickGmBytes=null;
let context=null,selected=BUILTIN_GM_ID,fontCache=null,fontRefreshSequence=0,fontRefreshPromise=null;
let fontLoadPromise=null, fontWarning='',builtinRetryAfter=0;
function fontStatus(){
  return {loaded:!!fontCache,selectedId:selected,
    fileBytes:fontCache?.bytes.byteLength||0,
    sampleBytes:fontCache?.parsed?.cacheBytes||0,
    warning:fontWarning,label:fontCache?.label||'',source:'selected SoundFont in session memory'};
}
function fontStatusChanged(){
  scope.dispatchEvent?.(new CustomEvent('xstage:font-memory',{detail:fontStatus()}));
}
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
  if(!sameLibrary){selected=BUILTIN_GM_ID;fontCache=null;fontLoadPromise=null;fontStatusChanged();}
  select.replaceChildren(new Option('กำลังตรวจสอบ SoundFont…',''));
  const pending=(async()=>{
    const sub=auth?.sub||'',rootId=auth?.rootId||'';
    const choices=[
      new Option('เสียงเครื่องดนตรี GM · TimGM6mb (6 MB)',BUILTIN_GM_ID)
    ];
    if(!auth?.token||!rootId){
      if(sequence===fontRefreshSequence){selected=BUILTIN_GM_ID;fontCache=null;select.replaceChildren(...choices);select.value=selected;}
      return;
    }
    try{
      const categories=await listFolder(rootId,auth.token);
      const soundFolders=categories.filter(x=>
        x.name==='SOUNDFONT'&&x.mimeType==='application/vnd.google-apps.folder');
      if(soundFolders.length>1)fail('พบ SOUNDFONT ซ้ำใน XStageKaraoke');
      if(soundFolders.length){
        const formatDirs=(await listFolder(soundFolders[0].id,auth.token)).filter(x=>
          x.mimeType==='application/vnd.google-apps.folder'&&
          ['SF2','SF3'].includes(x.name.toUpperCase()));
        for(const format of ['SF2','SF3'])
          if(formatDirs.filter(dir=>dir.name.toUpperCase()===format).length>1)
            fail('พบ '+format+' ซ้ำใน SOUNDFONT');
        for(const dir of formatDirs)
          for(const f of (await listFolder(dir.id,auth.token)).filter(x=>
            /\.sf[23]$/i.test(x.name)&&x.mimeType!=='application/vnd.google-apps.folder')){
            const option=new Option(f.name+' ('+Math.round(Number(f.size||0)/1048576)+' MB)',f.id);
            option.dataset.size=String(Number(f.size)||0);
            choices.push(option);
          }
      }
      if(sequence!==fontRefreshSequence)return;
      const storageKey='xstage-font-pref:'+sub+':'+rootId;
      let saved='';
      try{saved=localStorage.getItem(storageKey)||'';}catch{}
      select.replaceChildren(...choices);
      const hinted=Number(scope.navigator?.deviceMemory||4);
      const maxMB=(hinted<=2?64:hinted<=4?128:256)*1048576;
      const eligible=choices.slice(1).filter(option=>
        Number(option.dataset.size)>0&&Number(option.dataset.size)<=Math.min(MAX_FONT,maxMB));
      // A selected GM bank sounds like actual instruments; the old
      // no-SoundFont fallback used raw oscillators (8-bit game sound).
      // Prefer the user's saved bank, then a complete-looking GM/GS bank.
      const savedChoice=eligible.find(option=>option.value===saved);
      const savedTooLarge=!!savedChoice&&
        Number(savedChoice.dataset.size)>FAST_START_FONT_MAX_BYTES;
      // Include common complete-GM bank names such as CT56MGM_V45.
      // A larger GM SoundFont can sound fuller than the 6 MB starter bank,
      // but never auto-select a collection that appears single-instrument.
      const gmCandidates=eligible.filter(option=>Number(option.dataset.size)<=48*1048576&&
        /general.?midi|generaluser|fluidr3|timgm|mgm|(?:^|[^a-z])gm(?:[^a-z]|$)|(?:^|[^a-z])gs(?:[^a-z]|$)/i.test(option.text));
      // Never auto-download a saved 243 MB bank on page open.
      // Preserve the user's saved choice for explicit use in the menu.
      const autoChoice=savedTooLarge?null:savedChoice||
        gmCandidates.slice().sort((a,b)=>
          Number(b.dataset.size)-Number(a.dataset.size))[0];
      // Use the bundled-source GM reference rather than guessing that an
      // unrelated instrument-only SF2 can play a complete karaoke arrangement.
      select.value=autoChoice?.value||BUILTIN_GM_ID;
      selected=select.value;
      fontWarning=savedTooLarge
        ?'SoundFont เดิม '+Math.round(Number(savedChoice.dataset.size)/1048576)+
          ' MB ใหญ่เกินไปสำหรับเริ่มเพลงทันที · ใช้ GM 6 MB ก่อน'
        :'';
      fontStatusChanged();
      // Save automatic choice so subsequent sessions retain the same bank.
      if(autoChoice){try{localStorage.setItem(storageKey,selected);}catch{}}
      select.onchange=()=>{
        selected=select.value;fontCache=null;fontLoadPromise=null;fontWarning='';fontStatusChanged();
        try{localStorage.setItem(storageKey,selected);}catch{}
        // Selected SoundFont is retained for this app session and reused.
        // Never cache private font bytes across Google accounts or on disk.
        if(selected&&context?.token)void selectedFont(context.token).catch(error=>{
          console.warn('SoundFont preload:',error.message);
          scope.dispatchEvent?.(new CustomEvent('xstage:font-memory-error',
            {detail:{message:error.message}}));
        });
        // Any pre-rendered XSK2 in the queue used the prior SoundFont.
        // Invalidate that temporary audio before the next song starts.
        scope.dispatchEvent?.(new CustomEvent('xstage:soundfont-change',
          {detail:{soundFontId:selected}}));
      };
    }catch(error){
      if(sequence!==fontRefreshSequence)return;
      select.replaceChildren(...choices);
      const option=new Option('SoundFont: '+String(error.message).slice(0,80),'');
      option.disabled=true;select.append(option);
      selected=BUILTIN_GM_ID;fontCache=null;select.value=selected;fontStatusChanged();
    }
  })();
  fontRefreshPromise=pending;
  try{await pending;}
  finally{if(fontRefreshPromise===pending)fontRefreshPromise=null;}
  // Start preload only after the scan Promise is cleared: selectedFont
  // itself awaits that Promise, so preloading inside the scan deadlocks.
  if(selected&&context?.token&&sequence===fontRefreshSequence&&
     !prefersCompactGm())
    void selectedFont(context.token).catch(error=>{
      console.warn('SoundFont automatic preload:',error.message);
      scope.dispatchEvent?.(new CustomEvent('xstage:font-memory-error',
        {detail:{message:error.message}}));
    });
}
// Only cold oversized banks fall back. If a large bank has already loaded,
// keep using it without downgrading the chosen instrument sounds.
function prefersCompactGm(){
  if(selected===BUILTIN_GM_ID)return false;
  const size=Number($('xstage-soundfont-select')?.selectedOptions?.[0]?.dataset?.size||0);
  return size>FAST_START_FONT_MAX_BYTES&&
    !(fontCache?.id===selected&&fontCache?.sub===context?.sub);
}
async function fastGmFont(token,signal){
  if(selected===BUILTIN_GM_ID)return selectedFont(token,signal);
  if(signal?.aborted)throw new DOMException('ยกเลิก','AbortError');
  if(!context||token!==context.token)fail('บัญชี Google เปลี่ยน');
  if(!quickGmPromise){
    quickGmPromise=(async()=>{
      // Public GM only. Never include a Drive OAuth token in this request.
      const response=await fetch(BUILTIN_GM_URL,{cache:'force-cache'});
      if(!response.ok)fail('GM 6 MB โหลดไม่ได้ HTTP '+response.status);
      if(Number(response.headers.get('Content-Length')||0)>BUILTIN_GM_MAX_BYTES)
        fail('GM 6 MB ขนาดไม่ถูกต้อง');
      const bytes=new Uint8Array(await response.arrayBuffer());
      if(bytes.byteLength<100000||bytes.byteLength>BUILTIN_GM_MAX_BYTES)
        fail('GM 6 MB ไม่ครบ');
      validateFontContainer(bytes);
      quickGmBytes=bytes;
      return bytes;
    })().catch(error=>{quickGmPromise=null;throw error;});
  }
  const bytes=await quickGmPromise;
  if(signal?.aborted)throw new DOMException('ยกเลิก','AbortError');
  if(context?.token!==token)fail('บัญชี Google เปลี่ยน');
  fontWarning='SoundFont ที่เลือกยังโหลดไม่ครบ · เพลงนี้ใช้ GM 6 MB เพื่อเล่นได้ก่อน';
  fontStatusChanged();
  return bytes;
}
async function selectedFont(token,signal){
  if(fontRefreshPromise)await fontRefreshPromise;
  if(signal?.aborted)throw new DOMException('ยกเลิกการโหลด SoundFont','AbortError');
  if(!selected)selected=BUILTIN_GM_ID;
  if(!context||token!==context.token)fail('บัญชี Google เปลี่ยน · โปรดเลือก SoundFont อีกครั้ง');
  if(selected===BUILTIN_GM_ID){
    const id=BUILTIN_GM_ID,sub=context.sub;
    if(Date.now()<builtinRetryAfter)return null;
    if(fontCache?.id===id&&fontCache.sub===sub)return fontCache.bytes;
    if(fontLoadPromise?.id===id&&fontLoadPromise.sub===sub)
      return fontLoadPromise.promise;
    const task=(async()=>{
      try{
        const response=await fetch(BUILTIN_GM_URL,{cache:'force-cache',signal});
        if(!response.ok)fail('โหลดชุดเสียง GM เริ่มต้นไม่สำเร็จ HTTP '+response.status);
        const length=Number(response.headers.get('Content-Length')||0);
        if(length>BUILTIN_GM_MAX_BYTES)fail('ชุดเสียง GM เริ่มต้นใหญ่เกินขอบเขต');
        const bytes=new Uint8Array(await response.arrayBuffer());
        if(bytes.length<100000||bytes.length>BUILTIN_GM_MAX_BYTES)
          fail('ขนาดไฟล์เสียง GM ไม่ถูกต้อง');
        validateFontContainer(bytes);
        if(selected!==id||context?.token!==token||context?.sub!==sub)
          throw new DOMException('เปลี่ยนบัญชีหรือชุดเสียง','AbortError');
        fontCache={id,sub,bytes,parsed:null,label:'TimGM6mb · General MIDI'};
        // Keep the public 6 MB bank available even if the listener later
        // selects a 243 MB bank. This avoids downloading fallback twice.
        quickGmBytes=bytes;
        quickGmPromise=Promise.resolve(bytes);
        builtinRetryAfter=0;
        fontWarning='';fontStatusChanged();
        return bytes;
      }catch(error){
        if(error?.name==='AbortError')throw error;
        builtinRetryAfter=Date.now()+60000;
        fontWarning='โหลด GM SoundFont เริ่มต้นไม่สำเร็จ · เสียงอาจคล้ายเกม โปรดเลือก SoundFont จาก Google Drive: '+error.message;
        fontStatusChanged();
        return null;
      }
    })();
    fontLoadPromise={id,sub,promise:task};
    try{return await task;}
    finally{if(fontLoadPromise?.promise===task)fontLoadPromise=null;}
  }
  // The Drive file list already contains exact sizes. Reject an oversized
  // SF2/SF3 *before* downloading it or allocating large decoded samples.
  // Falling back to the built-in MIDI synthesizer keeps playback functional.
  const option=$('xstage-soundfont-select')?.selectedOptions?.[0];
  const listedSize=Number(option?.dataset?.size||0);
  const hinted=Number(scope.navigator?.deviceMemory||4);
  const sizeLimit=Math.min(MAX_FONT,(hinted<=2?64:hinted<=4?128:256)*1048576);
  if(listedSize>sizeLimit){
    fontWarning='SoundFont '+Math.round(listedSize/1048576)+' MB ใหญ่เกินงบ RAM · ใช้เสียง MIDI พื้นฐานเพื่อเริ่มเล่นโดยไม่ต้องดาวน์โหลดไฟล์ใหญ่';
    fontStatusChanged();
    return null;
  }
  const id=selected,sub=context.sub;
  if(fontCache?.id===id&&fontCache?.sub===sub)return fontCache.bytes;
  if(fontLoadPromise?.id===id&&fontLoadPromise.sub===sub)
    return fontLoadPromise.promise;
  const task=(async()=>{
    const early=scope.XStageMemory?.nativeRam?.();
    if(early?.lowMemory){
      fontWarning='Android RAM ต่ำ · ใช้เสียง MIDI พื้นฐานชั่วคราว';
      fontStatusChanged();
      return null;
    }
    const res=await fetch('https://www.googleapis.com/drive/v3/files/'+encodeURIComponent(id)+'?alt=media',
      {headers:{Authorization:'Bearer '+token},cache:'no-store',signal});
    if(!res.ok)fail('โหลด SoundFont จาก Drive ไม่สำเร็จ HTTP '+res.status);
    const len=Number(res.headers.get('Content-Length')||0);
    const hinted=Number(scope.navigator?.deviceMemory||4);
    const deviceLimit=(hinted<=2?64:hinted<=4?128:256)*1048576;
    const native=scope.XStageMemory?.nativeRam?.();
    if(native?.lowMemory||native&&len&&
       len>Math.max(16*1048576,native.available*.22)||
       len>MAX_FONT||len>deviceLimit){
      fontWarning='SoundFont ใหญ่เกินงบ RAM · เล่นด้วยเสียง MIDI พื้นฐานชั่วคราว';
      fontStatusChanged();
      await res.body?.cancel?.();
      return null;
    }
    const bytes=new Uint8Array(await res.arrayBuffer());
    if(bytes.byteLength>MAX_FONT||bytes.byteLength>deviceLimit||
       native&&bytes.byteLength>Math.max(16*1048576,native.available*.22)){
      fontWarning='SoundFont ใช้ RAM มากเกินไป · เล่นด้วยเสียงพื้นฐานชั่วคราว';
      fontStatusChanged();
      return null;
    }
    if(signal?.aborted)throw new DOMException('ยกเลิกการโหลด SoundFont','AbortError');
    if(selected!==id||context?.token!==token||context?.sub!==sub)
      fail('รายการ SoundFont เปลี่ยนระหว่างโหลด · กรุณาเลือกใหม่');
    // Parse once, then reuse decoded structure and bounded sample buffers.
    validateFontContainer(bytes);
    const label=$('xstage-soundfont-select')?.selectedOptions?.[0]?.text||'SoundFont';
    fontCache={id,sub,bytes,parsed:null,label};
    fontWarning='';
    fontStatusChanged();
    return bytes;
  })();
  fontLoadPromise={id,sub,promise:task};
  try{return await task;}
  finally{if(fontLoadPromise?.promise===task)fontLoadPromise=null;}
}
// Fast native-clock MIDI playback: no whole-song OfflineAudioContext/WAV render.
// Used only with the built-in synthesizer; selected SoundFonts retain full rendering.
let sharedLiveContext=null;
function unlockAudio(){
  const Ctor=scope.AudioContext||scope.webkitAudioContext;
  if(!Ctor)return false;
  scope.XStageIOSMidiAudio?.activate();
  if(!sharedLiveContext||sharedLiveContext.state==='closed')sharedLiveContext=new Ctor();
  void sharedLiveContext.resume().catch(()=>{});
  return true;
}
// Decode the earliest song samples BEFORE starting the MIDI transport.
// A cold Web Audio sampler used to miss notes while SF2 samples were
// first converted, but replaying the song reused warm sample buffers.
async function warmRealtimeSamples(source,fontBytes,{signal=null,onStatus=()=>{}}={}){
  if(!fontBytes?.byteLength)fail('ยังไม่พบ SoundFont เครื่องดนตรี');
  const Ctor=scope.AudioContext||scope.webkitAudioContext;
  if(!Ctor)fail('เบราว์เซอร์ไม่รองรับ Web Audio');
  const ctx=sharedLiveContext&&sharedLiveContext.state!=='closed'?
    sharedLiveContext:new Ctor();
  sharedLiveContext=ctx;
  const font=fontCache?.bytes===fontBytes
    ?(fontCache.parsed||(fontCache.parsed=parseFont(fontBytes)))
    :parseFont(fontBytes);
  const song=parseMidi(source);
  const first=song.notes.reduce((min,n)=>Math.min(min,n.start),Infinity);
  const horizon=(Number.isFinite(first)?first:0)+12;
  const samples=new Set();
  for(const n of song.notes){
    if(n.start>horizon)continue;
    for(const g of font.find(n.bank,n.program,n.key,n.velocity)){
      samples.add(g.get(53));
      if(samples.size>=72)break;
    }
    if(samples.size>=72)break;
  }
  if(!samples.size)fail('SoundFont ไม่มีเครื่องดนตรีสำหรับเพลงนี้ · โปรดเลือก GM/GS SoundFont ที่ครบถ้วน');
  let ready=0;
  for(const index of samples){
    if(signal?.aborted)throw new DOMException('ยกเลิก','AbortError');
    await sampleBuffer(font,index,ctx);
    if(++ready%12===0){
      onStatus('เตรียมเสียงเครื่องดนตรี '+ready+'/'+samples.size+'…');
      await new Promise(resolve=>setTimeout(resolve,0));
    }
  }
  if(fontCache?.parsed===font)fontStatusChanged();
  return {samples:ready};
}
function playRealtime(player,source,{signal,onStatus,fontBytes=null,getTranspose=()=>0,getProgram=()=>null}={}){
  const Ctor=scope.AudioContext||scope.webkitAudioContext;
  if(!Ctor)fail('เบราว์เซอร์ไม่รองรับ Web Audio MIDI Synthesizer');
  const song=parseMidi(source),ctx=sharedLiveContext&&sharedLiveContext.state!=='closed'?
    sharedLiveContext:new Ctor();
  sharedLiveContext=ctx;
  const font=fontBytes?(fontCache?.bytes===fontBytes
    ?(fontCache.parsed||(fontCache.parsed=parseFont(fontBytes)))
    :parseFont(fontBytes)):null;
  // The PC BASSMIDI backend starts fonts at -6 dB and limits polyphony.
  // Web Audio summing has no built-in clipping guard; keep headroom and use
  // a single final dynamics limiter, never boost every note independently.
  const master=ctx.createGain();
  const limiter=typeof ctx.createDynamicsCompressor==='function'
    ?ctx.createDynamicsCompressor():null;
  if(limiter){
    limiter.threshold.value=-18;
    limiter.knee.value=12;
    limiter.ratio.value=12;
    limiter.attack.value=.003;
    limiter.release.value=.16;
    master.connect(limiter);
  }
  const output=limiter||master;
  const iosOutput=scope.XStageIOSMidiAudio?.attach(ctx,output,{
    onStatus:message=>onStatus?.(message)
  })||null;
  if(!iosOutput)output.connect(ctx.destination);
  const MASTER_GAIN=.18;
  const MAX_VOICES=96;
  master.gain.value=MASTER_GAIN;
  const notes=song.notes.slice().sort((a,b)=>a.start-b.start);
  let cursor=0,disposed=false,timer=null,voices=[],revision=0;
  const regionCache=new Map();
  let missingPresetWarning=false;
  const fadeOutVoice=voice=>{
    try{
      const at=ctx.currentTime;
      voice.gain.gain.cancelScheduledValues?.(at);
      voice.gain.gain.setTargetAtTime?.(.00001,at,.006);
      voice.src.stop(at+.035);
    }catch{try{voice.src.stop();}catch{}}
  };
  const stopVoices=()=>{
    for(const voice of voices)fadeOutVoice(voice);
    voices=[];
  };
  const reset=()=>{
    revision++;stopVoices();
    const at=Number(player.currentTime)||0;
    let lo=0,hi=notes.length;
    while(lo<hi){const mid=(lo+hi)>>1;if(notes[mid].start<at-.04)lo=mid+1;else hi=mid;}
    cursor=lo;
  };
  const register=(src,gain)=>{
    const voice={src,gain};voices.push(voice);
    src.onended=()=>{
      try{src.disconnect();gain.disconnect();}catch{}
      const at=voices.indexOf(voice);if(at>=0)voices.splice(at,1);
    };
  };
  const scheduleNote=async(n,now,rate,generation)=>{
    const start=ctx.currentTime+Math.max(.015,(n.start-now)/rate);
    const duration=Math.max(.055,(n.end-n.start)/rate);
    const shift=Math.max(-12,Math.min(12,Math.trunc(Number(getTranspose())||0)));
    const pitch=n.channel===9?n.key:Math.max(0,Math.min(127,n.key+shift));
    const override=getProgram(),program=n.channel===9?n.program:
      Number.isInteger(override)&&override>=0&&override<=127?override:n.program;
    const regionKey=n.bank+':'+program+':'+pitch+':'+n.velocity;
    let regions=[null];
    if(font){
      if(!regionCache.has(regionKey))regionCache.set(regionKey,
        font.find(n.bank,program,pitch,n.velocity).slice(0,4));
      regions=regionCache.get(regionKey);
    }
    if(!regions.length){
      // A missing SF2 instrument must not morph into an oscillator.
      if(!missingPresetWarning){missingPresetWarning=true;
        onStatus?.('SoundFont ไม่มีเสียงเครื่องดนตรีบางช่อง · กรุณาใช้ชุดเสียง GM/GS ที่ครบถ้วน');}
      return;
    }
    for(const region of regions){
      let buffer=null;
      if(region){
        try{buffer=await sampleBuffer(font,region.get(53),ctx);}
        catch(error){onStatus?.('SoundFont มีตัวอย่างเสียงที่ถอดรหัสไม่ได้: '+error.message);continue;}
      }
      if(disposed||signal?.aborted||generation!==revision||
         player.paused||ctx.currentTime>start+duration)return;
      const gain=ctx.createGain();
      // MIDI CC7/CC11 and SF2 attenuation are multiplicative; the number
      // of layers must never multiply the total level above a single voice.
      const attenuation=region?Math.max(0,Number(region.get(48))||0):0;
      const amp=Math.max(.00001,Math.pow(n.velocity/127,1.65)*
        Math.max(0,Math.min(1,Number(n.level)||0))*
        Math.pow(10,-attenuation/200)*.20/regions.length);
      const onset=Math.max(start,ctx.currentTime+.003);
      const attack=Math.min(.014,duration*.25);
      const release=Math.min(.09,Math.max(.025,duration*.25));
      const held=Math.max(onset+attack,onset+duration-release);
      gain.gain.setValueAtTime(.00001,onset);
      gain.gain.linearRampToValueAtTime(amp,onset+attack);
      gain.gain.setValueAtTime(amp,held);
      gain.gain.exponentialRampToValueAtTime(.00001,onset+duration);
      gain.connect(master);
      let src;
      if(buffer){
        const sample=font.samples[region.get(53)];
        src=ctx.createBufferSource();src.buffer=buffer;
        const base=region.has(58)?region.get(58):sample.pitch;
        const coarse=region.has(51)?(region.get(51)<<16>>16):0;
        const fine=region.has(52)?(region.get(52)<<16>>16):0;
        src.playbackRate.value=Math.pow(2,(pitch-base+coarse+(fine+sample.correct)/100)/12);
        if((region.get(54)||0)&1&&sample.loopEnd>sample.loopStart+8){
          src.loop=true;src.loopStart=(sample.loopStart-sample.start)/sample.rate;
          src.loopEnd=(sample.loopEnd-sample.start)/sample.rate;
        }
      }else{
        src=ctx.createOscillator();
        src.type=n.channel===9?'square':program>=80?'sawtooth':program>=40?'triangle':'sine';
        src.frequency.value=440*Math.pow(2,(pitch-69)/12);
      }
      // Preserve rhythm over unlimited polyphony: retire oldest voices
      // before allocating another active oscillator/sample source.
      while(voices.length>=MAX_VOICES)fadeOutVoice(voices.shift());
      src.connect(gain);register(src,gain);
      src.start(onset);src.stop(onset+duration+.015);
    }
  };
  const schedule=()=>{
    if(disposed||signal?.aborted||player.paused||player.ended)return;
    const now=Number(player.currentTime)||0,rate=Math.max(.25,Number(player.playbackRate)||1);
    master.gain.value=MASTER_GAIN*(player.muted?0:Math.max(0,Math.min(1,Number(player.volume)||0)));
    const horizon=now+rate*(font?.9:.42),current=revision;
    for(;cursor<notes.length&&notes[cursor].start<horizon;cursor++){
      const n=notes[cursor];if(n.start<now-.08)continue;
      void scheduleNote(n,now,rate,current);
    }
  };
  const play=()=>{
    if(disposed)return;
    scope.XStageIOSMidiAudio?.activate();
    void iosOutput?.start().catch(()=>{});
    ctx.resume().catch(()=>onStatus?.('กด ▶ อีกครั้งเพื่ออนุญาตเสียง MIDI'));
    reset();schedule();if(timer===null)timer=setInterval(schedule,80);
  };
  const pause=()=>{if(timer!==null){clearInterval(timer);timer=null;}reset();iosOutput?.pause();};
  const seek=()=>{pause();if(!player.paused)play();};
  const listeners=[['play',play],['pause',pause],['ended',pause],
    ['seeking',seek],['ratechange',seek],['xstage-midi-transpose',seek]];
  for(const [event,fn] of listeners)player.addEventListener(event,fn);
  const dispose=()=>{
    if(disposed)return;disposed=true;pause();
    for(const [event,fn] of listeners)player.removeEventListener(event,fn);
    try{iosOutput?.dispose();master.disconnect();limiter?.disconnect();}catch{}
  };
  signal?.addEventListener('abort',dispose,{once:true});
  if(!player.paused)play();
  onStatus?.(font?'SoundFont พร้อมสังเคราะห์ MIDI แบบเรียลไทม์':'MIDI พร้อมเล่นโดยไม่แปลงเป็น WAV');
  return {
    dispose,duration:song.duration,
    async resumeAudio(){
      if(disposed||player.paused)return false;
      scope.XStageIOSMidiAudio?.activate?.();
      let ready=ctx.state==='running';
      if(!ready){try{await ctx.resume();ready=ctx.state==='running';}catch{ready=false;}}
      const relayReady=await iosOutput?.resume?.();
      return ready&&relayReady!==false;
    }
  };
}
scope.XStageBrowserMidi={parseMidi,midiLyrics,ncnLyrics,parseFont,render,refreshFonts,selectedFont,fontStatus,playRealtime,warmRealtimeSamples,unlockAudio,
  prefersCompactGm,fastGmFont,isFastGmBytes:bytes=>!!bytes&&bytes===quickGmBytes,
  liveAudioContext:()=>sharedLiveContext?.state!=='closed'?sharedLiveContext:null,
  supportsRealtime:()=>!!(scope.AudioContext||scope.webkitAudioContext),
  reset(){fontRefreshSequence++;fontRefreshPromise=null;fontLoadPromise=null;fontWarning='';context=null;selected=BUILTIN_GM_ID;fontCache=null;fontStatusChanged();const node=$('xstage-soundfont-select');if(node)node.replaceChildren(new Option('เสียงเครื่องดนตรี GM · TimGM6mb (6 MB)',BUILTIN_GM_ID));}};
scope.addEventListener?.('xstage:auth-cleared',()=>scope.XStageBrowserMidi.reset());
})(typeof window!=='undefined'?window:globalThis);
