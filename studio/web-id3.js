/* Offline ID3v2 metadata + UNSYNCHRONIZED lyrics reader for Song Studio Web.
 * Never uploads audio, synthesizes times, or alters original MP3 bytes.
 * Reads only the bounded tag prefix; USLT is NOT a karaoke timing source. */
(function(scope){
'use strict';
const MAX_TAG=2*1024*1024,MAX_LYRICS=256*1024;
const safe=(bytes,at,n)=>at>=0&&at+n<=bytes.length;
const latin=b=>new TextDecoder('iso-8859-1').decode(b);
function syncSafe(bytes,at){
  if(!safe(bytes,at,4))throw Error('ID3 ขนาดข้อมูลไม่ครบ');
  const x=bytes.subarray(at,at+4);
  if(x.some(v=>v>127))throw Error('ID3 synchsafe size ผิดรูปแบบ');
  return (x[0]*2097152+x[1]*16384+x[2]*128+x[3]);
}
function wideSize(bytes,at){
  if(!safe(bytes,at,4))throw Error('ID3 frame size ไม่ครบ');
  return (bytes[at]*16777216+bytes[at+1]*65536+bytes[at+2]*256+bytes[at+3]);
}
function decode(payload,encoding){
  if(!payload.length)return '';
  if(encoding===0)return latin(payload);
  if(encoding===3)return new TextDecoder('utf-8',{fatal:true}).decode(payload);
  if(encoding===1){
    if(payload.length<2)throw Error('ID3 UTF-16 BOM ไม่สมบูรณ์');
    if(payload[0]===0xfe&&payload[1]===0xff)
      return new TextDecoder('utf-16be',{fatal:true}).decode(payload.subarray(2));
    if(payload[0]===0xff&&payload[1]===0xfe)
      return new TextDecoder('utf-16le',{fatal:true}).decode(payload.subarray(2));
    return new TextDecoder('utf-16le',{fatal:true}).decode(payload);
  }
  if(encoding===2)return new TextDecoder('utf-16be',{fatal:true}).decode(payload);
  throw Error('ID3 text encoding ไม่รองรับ');
}
function textFrame(body){
  if(!body.length)return '';
  return decode(body.subarray(1),body[0]).split('\0')[0].trim();
}
function lyricsFrame(body){
  if(body.length<5)return '';
  const encoding=body[0],wide=encoding===1||encoding===2,step=wide?2:1;
  let p=4; // encoding byte followed by exactly three language bytes
  while(p+step<=body.length){
    if(body[p]===0&&(!wide||body[p+1]===0)){p+=step;break;}
    p+=step;
  }
  if(p>=body.length)return '';
  const raw=decode(body.subarray(p),encoding);
  return raw.replace(/\0+$/,'').replace(/\r\n?/g,'\n').trim().slice(0,MAX_LYRICS);
}
function parse(raw){
  const b=raw instanceof Uint8Array?raw:new Uint8Array(raw);
  const out={title:'',artist:'',lyrics:'',tagVersion:0,hasTiming:false};
  if(!safe(b,0,10)||latin(b.subarray(0,3))!=='ID3')return out;
  const v=b[3],flags=b[5];
  if(v!==3&&v!==4)throw Error('ID3v2.'+v+' ไม่รองรับ');
  if(flags&0x80)throw Error('ID3 unsynchronisation ไม่รองรับการอ่านเนื้อร้องอย่างปลอดภัย');
  const size=syncSafe(b,6);
  if(size>MAX_TAG)throw Error('ID3 tag ใหญ่เกิน 2 MB');
  if(!safe(b,10,size))throw Error('ID3 tag อ่านได้ไม่ครบ');
  out.tagVersion=v;
  let at=10;
  if(flags&0x40){
    const ext=v===4?syncSafe(b,at):wideSize(b,at);
    const skip=v===4?ext:ext+4;
    if(skip<4||at+skip>size+10)throw Error('ID3 extended header ผิดรูปแบบ');
    at+=skip;
  }
  for(;at+10<=size+10;){
    const id=latin(b.subarray(at,at+4));
    if(/^\x00{4}$/.test(id))break;
    if(!/^[A-Z0-9]{4}$/.test(id))break;
    const length=v===4?syncSafe(b,at+4):wideSize(b,at+4);
    const frameFlags=b[at+9],begin=at+10,end=begin+length;
    if(end>size+10)throw Error('ID3 frame '+id+' มีขนาดเกิน tag');
    // Grouping/compression/encryption/un-sync/data length change frame layout.
    // Skip instead of interpreting arbitrary bytes as trustworthy lyrics.
    const protectedFrame=v===4?(frameFlags&0x4f):(frameFlags&0xe0);
    if(!protectedFrame&&length>0){
      const body=b.subarray(begin,end);
      try{
        if(id==='TIT2'&&!out.title)out.title=textFrame(body).slice(0,200);
        else if(id==='TPE1'&&!out.artist)out.artist=textFrame(body).slice(0,200);
        else if(id==='USLT'&&!out.lyrics)out.lyrics=lyricsFrame(body);
      }catch{ /* skip malformed optional metadata, do not corrupt audio */ }
    }
    at=end;
  }
  return out;
}
async function read(file){
  if(!file||typeof file.slice!=='function'||file.size<10)return {title:'',artist:'',lyrics:'',tagVersion:0,hasTiming:false};
  const h=new Uint8Array(await file.slice(0,10).arrayBuffer());
  if(latin(h.subarray(0,3))!=='ID3')return {title:'',artist:'',lyrics:'',tagVersion:0,hasTiming:false};
  const size=syncSafe(h,6);
  if(size>MAX_TAG)throw Error('ID3 tag ใหญ่เกิน 2 MB · ข้ามการอ่านเนื้อร้อง');
  const bytes=new Uint8Array(await file.slice(0,10+size).arrayBuffer());
  return parse(bytes);
}
scope.XStageStudioId3={read,parse,MAX_TAG};
})(typeof window!=='undefined'?window:globalThis);
