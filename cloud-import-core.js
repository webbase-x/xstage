/* X-Stage Online private folder importer: format validation and incremental MD5.
 * No tokens, media, or file handles are stored by this module.
 * Shared by browser import and Node regression tests.
 */
(function(scope){
'use strict';
const AUDIO=new Set(['mp3','m4a','wav','aac','flac','ogg','oga']);
const BROWSER_VIDEO=new Set(['mp4','webm']);
const FONTS=new Set(['sf2','sf3']);
const MIDI=new Set(['mid','midi','kar']);
const VIDEO=new Set(['mp4','avi','mpg','mpeg','dat','vob','wmv','mkv','mov','webm','flv']);
const OTHER_AUDIO=new Set(['wma','aiff','aif','opus']);
const ROLES=new Set(['song','songs','lyric','lyrics','cursor','cursors']);
const S=[7,12,17,22,7,12,17,22,7,12,17,22,7,12,17,22,
  5,9,14,20,5,9,14,20,5,9,14,20,5,9,14,20,
  4,11,16,23,4,11,16,23,4,11,16,23,4,11,16,23,
  6,10,15,21,6,10,15,21,6,10,15,21,6,10,15,21];
const K=Array.from({length:64},(_,i)=>Math.floor(Math.abs(Math.sin(i+1))*4294967296)>>>0);
class MD5 {
  constructor(){this.state=[0x67452301,0xefcdab89,0x98badcfe,0x10325476];this.tail=new Uint8Array(64);this.used=0;this.length=0;}
  block(bytes,pos){
    const w=new Uint32Array(16);
    for(let j=0;j<16;j++){const i=pos+j*4;w[j]=(bytes[i]|(bytes[i+1]<<8)|(bytes[i+2]<<16)|(bytes[i+3]<<24))>>>0;}
    let [a,b,c,d]=this.state;
    for(let i=0;i<64;i++){
      let f,g;
      if(i<16){f=(b&c)|(~b&d);g=i;}
      else if(i<32){f=(d&b)|(~d&c);g=(5*i+1)%16;}
      else if(i<48){f=b^c^d;g=(3*i+5)%16;}
      else{f=c^(b|~d);g=(7*i)%16;}
      const t=(a+f+K[i]+w[g])|0;
      a=d;d=c;c=b;b=(b+((t<<S[i])|(t>>>(32-S[i]))))|0;
    }
    this.state[0]=(this.state[0]+a)|0;
    this.state[1]=(this.state[1]+b)|0;
    this.state[2]=(this.state[2]+c)|0;
    this.state[3]=(this.state[3]+d)|0;
  }
  append(chunk){
    const bytes=chunk instanceof Uint8Array?chunk:new Uint8Array(chunk);
    this.length+=bytes.length;
    let offset=0;
    if(this.used){
      const n=Math.min(64-this.used,bytes.length);
      this.tail.set(bytes.subarray(0,n),this.used);this.used+=n;offset+=n;
      if(this.used===64){this.block(this.tail,0);this.used=0;}
    }
    for(;offset+64<=bytes.length;offset+=64)this.block(bytes,offset);
    if(offset<bytes.length){this.tail.set(bytes.subarray(offset),0);this.used=bytes.length-offset;}
    return this;
  }
  end(){
    const total=this.length;
    const n=(56-((total+1)%64)+64)%64;
    const pad=new Uint8Array(1+n+8);pad[0]=128;
    const low=(total*8)>>>0,high=Math.floor(total/536870912)>>>0;
    for(let i=0;i<4;i++){pad[1+n+i]=(low>>>(8*i))&255;pad[5+n+i]=(high>>>(8*i))&255;}
    this.append(pad);
    if(this.used!==0)throw Error('MD5 padding failure');
    let out='';
    for(const word of this.state)for(let i=0;i<4;i++)out+=((word>>>(8*i))&255).toString(16).padStart(2,'0');
    return out;
  }
}
async function hashBlob(blob,check){
  const h=new MD5();
  for(let at=0;at<blob.size;at+=4*1024*1024){
    if(check)check();
    h.append(await blob.slice(at,Math.min(at+4*1024*1024,blob.size)).arrayBuffer());
  }
  return h.end();
}
function ext(name){const dot=String(name||'').lastIndexOf('.');return dot<0?'':name.slice(dot+1).toLowerCase();}
function groupKey(path){
  const pieces=String(path||'').replace(/\\/g,'/').split('/').filter(Boolean);
  const base=(pieces.pop()||'').replace(/\.[^.]+$/,'');
  return [...pieces.filter(p=>!ROLES.has(p.toLowerCase())),base].join('/').normalize('NFC').toLocaleLowerCase('en-US');
}
function scan(files){
  const groups=new Map(),fonts=[],blocked=[],seen=new Set();
  for(const item of files){
    const file=item.file||item,relative=String(item.relative||file.webkitRelativePath||file.name||'');
    if(!file||!file.name||!Number.isSafeInteger(file.size)||file.size<0)continue;
    const sig=relative.toLocaleLowerCase('en-US')+'|'+file.size+'|'+(file.lastModified||0);
    if(seen.has(sig))continue;seen.add(sig);
    const extension=ext(file.name);
    if(FONTS.has(extension)){fonts.push({file,relative,kind:extension.toUpperCase()});continue;}
    if(!AUDIO.has(extension)&&!MIDI.has(extension)&&!VIDEO.has(extension)&&!OTHER_AUDIO.has(extension)&&
       !['lrc','lyr','cur','json'].includes(extension))continue;
    const key=groupKey(relative);
    if(!groups.has(key))groups.set(key,[]);
    groups.get(key).push({file,relative,kind:extension});
  }
  const songs=[],midis=[];
  for(const [key,items] of groups){
    const sound=items.filter(x=>AUDIO.has(x.kind)),lrc=items.filter(x=>x.kind==='lrc');
    const video=items.filter(x=>BROWSER_VIDEO.has(x.kind));
    const json=items.filter(x=>x.kind==='json'),midi=items.filter(x=>MIDI.has(x.kind));
    const lyr=items.filter(x=>x.kind==='lyr'),cur=items.filter(x=>x.kind==='cur');
    const extra=items.filter(x=>(VIDEO.has(x.kind)&&!BROWSER_VIDEO.has(x.kind))||OTHER_AUDIO.has(x.kind));
    if((sound.length===1||(!sound.length&&video.length===1))&&video.length<=1&&midi.length===0&&extra.length===0&&lyr.length===0&&cur.length===0&&
       lrc.length<=1&&json.length<=1&&(lrc.length===1||json.length===1)){
      const primary=sound[0]||video[0];
      if(primary.file.size<1024||(video.length&&video[0].file.size<1024)||
          (lrc.length&&lrc[0].file.size<8)||(json.length&&json[0].file.size<8)){
        blocked.push({key,reason:'ไฟล์เสียงหรือเนื้อร้องมีขนาดไม่สมบูรณ์'});continue;
      }
      songs.push({key,code:primary.file.name.replace(/\.[^.]+$/,'').slice(0,140),
        audio:primary,video:video[0]||null,lrc:lrc[0]||null,json:json[0]||null,
        kind:primary.kind.toUpperCase()});
    }else if(midi.length===1&&sound.length===0&&extra.length===0&&
        lrc.length<=1&&json.length<=1&&lyr.length<=1&&cur.length<=1){
      const isNcn=/\/(?:ncn)\//i.test('/'+midi[0].relative.replace(/\\/g,'/'))||
        lyr.length>0||cur.length>0;
      if((isNcn&&(!lyr.length||!cur.length))||(lyr.length!==cur.length)){
        blocked.push({key,reason:'ชุด NCN ต้องมี MID + LYR + CUR รหัสเดียวกันครบทั้งสามไฟล์'});continue;
      }
      if(midi[0].file.size<22||(lyr.length&&lyr[0].file.size<8)||
          (cur.length&&cur[0].file.size<2)){
        blocked.push({key,reason:'ชุด MIDI/NCN มีขนาดไฟล์ไม่สมบูรณ์'});continue;
      }
      midis.push({key,code:midi[0].file.name.replace(/\.[^.]+$/,'').slice(0,140),
        midi:midi[0],lyr:lyr[0]||null,cur:cur[0]||null,lrc:lrc[0]||null,
        json:json[0]||null,kind:lyr.length?'NCN':midi[0].kind.toUpperCase()});
    }else if(sound.length||video.length||midi.length||extra.length){
      const reason=extra.length?'สื่อชนิดนี้ต้องแปลงเป็นไฟล์เสียง/วิดีโอที่เบราว์เซอร์รองรับก่อน':
        midi.length?'ไฟล์ MIDI ซ้ำ หรือชุดเพลงไม่สมบูรณ์':
        'ต้องมีไฟล์ MP3/M4A และ Lyrics JSON หรือ LRC ชื่อเดียวกันอย่างละหนึ่งชุด';
      blocked.push({key,reason});
    }else if(lrc.length||json.length||lyr.length||cur.length){
      blocked.push({key,reason:'มีเฉพาะเนื้อร้อง แต่ไม่มีไฟล์เสียงหรือ MIDI คู่กัน'});
    }
  }
  return {songs,midis,fonts,blocked,files:seen.size};
}
async function validAudio(file){
  if(file.size<1024)return false;
  const b=new Uint8Array(await file.slice(0,32).arrayBuffer()),type=ext(file.name);
  const signature=(at,s)=>String.fromCharCode(...b.slice(at,at+s.length))===s;
  if(type==='mp3')return signature(0,'ID3')||b[0]===255&&(b[1]&224)===224;
  if(type==='m4a'||type==='mp4')return signature(4,'ftyp');
  if(type==='wav')return signature(0,'RIFF')&&signature(8,'WAVE');
  if(type==='flac')return signature(0,'fLaC');
  if(type==='ogg'||type==='oga')return signature(0,'OggS');
  if(type==='aac')return (b[0]===0xff&&(b[1]&0xf6)===0xf0)||
    (b[0]===0x41&&b[1]===0x44&&b[2]===0x49&&b[3]===0x46);
  if(type==='webm')return b[0]===26&&b[1]===69&&b[2]===223&&b[3]===163;
  return false;
}
async function validFont(file){
  const extension=ext(file.name);
  if(!FONTS.has(extension)||file.size<256||file.size>2*1024*1024*1024)return false;
  const h=new Uint8Array(await file.slice(0,12).arrayBuffer());
  if(h.length!==12||String.fromCharCode(...h.slice(0,4))!=='RIFF'||
      String.fromCharCode(...h.slice(8,12))!=='sfbk')return false;
  const riffSize=(h[4]|(h[5]<<8)|(h[6]<<16)|(h[7]<<24))>>>0;
  const end=8+riffSize;
  if(riffSize<12||end>file.size)return false;
  // Validate RIFF boundaries and all three mandatory SF2/SF3 LIST sections.
  // Read only 12 bytes per top-level chunk, never load a large sample bank
  // into memory merely to check whether it is structurally complete.
  let at=12,count=0;
  const found=new Set();
  while(at<end){
    if(at+8>end||++count>4096)return false;
    const head=new Uint8Array(await file.slice(at,Math.min(at+12,end)).arrayBuffer());
    if(head.length<8)return false;
    const kind=String.fromCharCode(...head.slice(0,4));
    const length=(head[4]|(head[5]<<8)|(head[6]<<16)|(head[7]<<24))>>>0;
    if(at+8+length>end)return false;
    if(kind==='LIST'){
      if(length<4||head.length<12)return false;
      found.add(String.fromCharCode(...head.slice(8,12)));
    }
    at+=8+length+(length&1);
  }
  return at===end&&['INFO','sdta','pdta'].every(part=>found.has(part));
}
function lrcToJson(raw,code){
  const lines=[],value=String(raw||'').replace(/\r\n?/g,'\n');
  let offset=0,title='',artist='';
  const stamp=/\[(\d{1,3}):([0-5]\d)(?:[.:](\d{1,3}))?\]/g;
  const cue=/<(\d{1,3}):([0-5]\d)(?:[.:](\d{1,3}))?>/g;
  function when(m){return Math.round((Number(m[1])*60+Number(m[2])+(Number((m[3]||'0').padEnd(3,'0').slice(0,3))/1000))*1000)/1000;}
  for(const row of value.split('\n')){
    const meta=row.match(/^\[(offset|ti|ar):([^\]]*)\]/i);
    if(meta){
      const v=meta[2].trim();
      if(meta[1].toLowerCase()==='offset')offset=Number(v)||0;
      if(meta[1].toLowerCase()==='ti')title=v.slice(0,180);
      if(meta[1].toLowerCase()==='ar')artist=v.slice(0,180);
      continue;
    }
    const tags=[...row.matchAll(stamp)];
    if(!tags.length)continue;
    const body=row.replace(stamp,'');
    const text=body.replace(cue,'').trim();
    // Preserve empty timed cues: they end the preceding lyric before a solo.
    const wordTags=[...body.matchAll(cue)];
    for(const tag of tags){
      const startTime=when(tag);
      if(!Number.isFinite(startTime)||startTime<0||startTime>=86400)continue;
      const entry={startTime,text};
      if(!text){entry._clear=true;lines.push(entry);continue;}
      if(wordTags.length){
        const segments=[];
        const head=body.slice(0,wordTags[0].index);
        if(head)segments.push({start:startTime,text:head});
        for(let i=0;i<wordTags.length;i++){
          const curr=wordTags[i],next=wordTags[i+1];
          const fragment=body.slice(curr.index+curr[0].length,next?next.index:body.length);
          if(fragment)segments.push({start:when(curr)+startTime-when(tags[0]),text:fragment});
        }
        entry._words=segments;
      }
      lines.push(entry);
    }
  }
  lines.sort((a,b)=>a.startTime-b.startTime);
  for(let i=0;i<lines.length;i++){
    const line=lines[i];
    const next=lines[i+1]?.startTime??(line.startTime+4);
    line.endTime=Math.round(Math.max(line.startTime+.05,next)*1000)/1000;
    if(line._words){
      const words=line._words;
      line.syllables=words.map((w,j)=>({text:w.text,start:Math.round(w.start*1000)/1000,
        duration:Math.round(Math.max(0,(words[j+1]?.start??line.endTime)-w.start)*1000)/1000}));
      delete line._words;
    }
  }
  const visibleLines=lines.filter(line=>!line._clear);
  if(!visibleLines.length)throw Error('LRC ไม่มีบรรทัดข้อความพร้อมเวลาใช้งานจริง');
  return {schemaVersion:1,songCode:code,audioOffsetMs:offset,lines:visibleLines,rawLrc:value,title,artist};
}
function validLyricsJson(raw,code){
  let document;
  try{document=typeof raw==='string'?JSON.parse(raw):raw;}
  catch{throw Error('Lyrics JSON ไม่ใช่ JSON ที่สมบูรณ์');}
  if(!document||document.schemaVersion!==1||!Array.isArray(document.lines)||
      !document.lines.length)throw Error('Lyrics JSON ต้องใช้ schemaVersion 1 และมีเนื้อร้อง');
  let previous=-1;
  for(const line of document.lines){
    const start=line?.startTime;
    if(typeof start!=='number'||!Number.isFinite(start)||start<0||start>=86400||
       start<previous||typeof line.text!=='string'||!line.text.trim())
      throw Error('Lyrics JSON มีบรรทัด/เวลาไม่ถูกต้อง');
    if(line.endTime!==undefined &&
      (typeof line.endTime!=='number'||!Number.isFinite(line.endTime)||line.endTime<start))
      throw Error('Lyrics JSON มี endTime ไม่ถูกต้อง');
    previous=start;
  }
  if(document.audioOffsetMs!==undefined &&
     (!Number.isFinite(Number(document.audioOffsetMs))||
      Math.abs(Number(document.audioOffsetMs))>600000))
    throw Error('Lyrics JSON มี offset ผิดขอบเขต');
  const actualCode=String(document.songCode||code||'').trim();
  if(!actualCode||actualCode.length>140||/[\/\\\u0000-\u001f]/.test(actualCode))
    throw Error('Lyrics JSON มีรหัสเพลงไม่ปลอดภัย');
  return document;
}
function bucket(code){const c=String(code||'').charAt(0).toUpperCase();return /[0-9A-Z]/.test(c)?c:'_';}
scope.XStageImportCore={MD5,hashBlob,ext,groupKey,scan,validAudio,validFont,lrcToJson,validLyricsJson,bucket};
})(typeof window!=='undefined'?window:globalThis);
