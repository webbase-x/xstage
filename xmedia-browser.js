/* X-Stage X-Media v1 reader for Web/Android WebView.
 * Reads Song Studio Plus embedded media without changing legacy XSK/JSON paths.
 */
(function(scope){
'use strict';
const MAGIC='XSTGPLS1',VERSION=1,HEADER_BYTES=92,MAX_METADATA=32*1024*1024,MAX_TEXT=1024*1024;
const FORMATS={
  xmid:{kind:'midi',extension:'mid',mime:'audio/midi'},
  xmp3:{kind:'audio',extension:'mp3',mime:'audio/mpeg'},xm4a:{kind:'audio',extension:'m4a',mime:'audio/mp4'},
  xwav:{kind:'audio',extension:'wav',mime:'audio/wav'},xaac:{kind:'audio',extension:'aac',mime:'audio/aac'},
  xflac:{kind:'audio',extension:'flac',mime:'audio/flac'},xogg:{kind:'audio',extension:'ogg',mime:'audio/ogg'},
  xoga:{kind:'audio',extension:'oga',mime:'audio/ogg'},xwma:{kind:'audio',extension:'wma',mime:'audio/x-ms-wma'},
  xmp4:{kind:'video',extension:'mp4',mime:'video/mp4'},xwebm:{kind:'video',extension:'webm',mime:'video/webm'},
  xmkv:{kind:'video',extension:'mkv',mime:'video/x-matroska'},xavi:{kind:'video',extension:'avi',mime:'video/x-msvideo'},
  xmpg:{kind:'video',extension:'mpg',mime:'video/mpeg'},xmpeg:{kind:'video',extension:'mpeg',mime:'video/mpeg'},
  xdat:{kind:'video',extension:'dat',mime:'video/mpeg'},xvob:{kind:'video',extension:'vob',mime:'video/mpeg'},
  xmov:{kind:'video',extension:'mov',mime:'video/quicktime'},xwmv:{kind:'video',extension:'wmv',mime:'video/x-ms-wmv'},
  xflv:{kind:'video',extension:'flv',mime:'video/x-flv'}
};
function ext(name){const at=String(name||'').lastIndexOf('.');return at<0?'':String(name).slice(at+1).toLowerCase();}
function formatOf(name){return FORMATS[ext(name)]||null;}
function supports(name){return !!formatOf(name);}
function hex(bytes){return Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');}
function equalBytes(a,b){if(a.length!==b.length)return false;let diff=0;for(let i=0;i<a.length;i++)diff|=a[i]^b[i];return diff===0;}
function u64(view,at){const value=view.getBigUint64(at,true);if(value>BigInt(Number.MAX_SAFE_INTEGER))throw Error('X-Media มีขนาดเกินช่วงที่เบราว์เซอร์รองรับ');return Number(value);}
function utf8(bytes){try{return new TextDecoder('utf-8',{fatal:true}).decode(bytes);}catch{throw Error('X-Media metadata ไม่ใช่ UTF-8 ที่สมบูรณ์');}}
function decodeMetadata(bytes){
  const view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);let at=0;
  const need=n=>{if(!Number.isSafeInteger(n)||n<0||at+n>bytes.length)throw Error('X-Media metadata ถูกตัดหรือขนาดไม่ถูกต้อง');};
  const u32=()=>{need(4);const v=view.getUint32(at,true);at+=4;return v;};
  const f64=()=>{need(8);const v=view.getFloat64(at,true);at+=8;if(!Number.isFinite(v))throw Error('X-Media metadata มีเวลาที่ไม่ใช่ตัวเลข');return v;};
  const text=()=>{const n=u32();if(n>MAX_TEXT)throw Error('X-Media metadata มีข้อความยาวเกินขอบเขต');need(n);const v=utf8(bytes.subarray(at,at+n));at+=n;return v;};
  const [songId,code,lyricsVersionId,title,artist,timingStatus]=[text(),text(),text(),text(),text(),text()];
  const count=u32();if(count>100000)throw Error('X-Media มีบรรทัดเนื้อร้องมากเกินขอบเขต');
  const lines=[];let previous=-1;
  for(let i=0;i<count;i++){
    const startTime=f64(),endTime=f64(),value=text(),lineTiming=text();
    if(startTime<0||endTime<startTime||startTime<previous)throw Error('X-Media มีเวลาเนื้อร้องไม่ถูกต้องหรือย้อนหลัง');
    previous=startTime;
    const cueCount=u32();if(cueCount>200000)throw Error('X-Media มีจุดปาดสีมากเกินขอบเขต');
    const syllables=[];let cuePrevious=-1;
    for(let j=0;j<cueCount;j++){
      const start=f64(),duration=f64(),glyph=text();
      if(start<0||duration<0||start<cuePrevious)throw Error('X-Media มีเวลาปาดสีไม่ถูกต้องหรือย้อนหลัง');
      cuePrevious=start;syllables.push({start,duration,text:glyph});
    }
    lines.push({startTime,endTime,text:value,timingStatus:lineTiming,syllables});
  }
  if(at!==bytes.length)throw Error('X-Media metadata มีข้อมูลส่วนเกินที่ไม่รู้จัก');
  return {schemaVersion:1,songId,songCode:code,lyricsVersionId,title,artist,timingStatus,audioOffsetMs:0,lines};
}
async function sha256(bytes){const raw=bytes instanceof Uint8Array?bytes:new Uint8Array(bytes);return new Uint8Array(await scope.crypto.subtle.digest('SHA-256',raw));}
const SHA_K=new Uint32Array([0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2]);
const rr=(x,n)=>(x>>>n)|(x<<(32-n));
class SHA256{
  constructor(){this.h=new Uint32Array([0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]);this.tail=new Uint8Array(64);this.used=0;this.bytes=0;}
  block(b,o){const w=new Uint32Array(64);for(let i=0;i<16;i++){const p=o+i*4;w[i]=((b[p]<<24)|(b[p+1]<<16)|(b[p+2]<<8)|b[p+3])>>>0;}for(let i=16;i<64;i++){const x=w[i-15],y=w[i-2],s0=rr(x,7)^rr(x,18)^(x>>>3),s1=rr(y,17)^rr(y,19)^(y>>>10);w[i]=(w[i-16]+s0+w[i-7]+s1)>>>0;}let [a,c,d,e,f,g,h,k]=this.h;for(let i=0;i<64;i++){const s1=rr(f,6)^rr(f,11)^rr(f,25),ch=(f&g)^(~f&h),t1=(k+s1+ch+SHA_K[i]+w[i])>>>0,s0=rr(a,2)^rr(a,13)^rr(a,22),maj=(a&c)^(a&d)^(c&d),t2=(s0+maj)>>>0;k=h;h=g;g=f;f=(e+t1)>>>0;e=d;d=c;c=a;a=(t1+t2)>>>0;}const v=[a,c,d,e,f,g,h,k];for(let i=0;i<8;i++)this.h[i]=(this.h[i]+v[i])>>>0;}
  append(chunk){const b=chunk instanceof Uint8Array?chunk:new Uint8Array(chunk);this.bytes+=b.length;let o=0;if(this.used){const n=Math.min(64-this.used,b.length);this.tail.set(b.subarray(0,n),this.used);this.used+=n;o+=n;if(this.used===64){this.block(this.tail,0);this.used=0;}}for(;o+64<=b.length;o+=64)this.block(b,o);if(o<b.length){this.tail.set(b.subarray(o),0);this.used=b.length-o;}return this;}
  end(){const before=this.bytes;const rem=(56-((before+1)%64)+64)%64,pad=new Uint8Array(1+rem+8);pad[0]=128;const bits=BigInt(before)*8n;for(let i=0;i<8;i++)pad[pad.length-1-i]=Number((bits>>BigInt(i*8))&255n);this.append(pad);if(this.used)throw Error('SHA-256 padding failure');const out=new Uint8Array(32);for(let i=0;i<8;i++){out[i*4]=(this.h[i]>>>24)&255;out[i*4+1]=(this.h[i]>>>16)&255;out[i*4+2]=(this.h[i]>>>8)&255;out[i*4+3]=this.h[i]&255;}return out;}
}
async function sha256Blob(blob,signal){const h=new SHA256();for(let at=0;at<blob.size;at+=4*1024*1024){if(signal?.aborted)throw new DOMException('ยกเลิก','AbortError');h.append(new Uint8Array(await blob.slice(at,Math.min(blob.size,at+4*1024*1024)).arrayBuffer()));}return h.end();}
async function inspectMetadata(blob,name=blob?.name||''){
  const format=formatOf(name);if(!format)throw Error('ยังไม่รองรับนามสกุล X-Media นี้');
  if(!blob||!Number.isSafeInteger(blob.size)||blob.size<HEADER_BYTES)throw Error('X-Media มีขนาดไม่สมบูรณ์');
  const head=new Uint8Array(await blob.slice(0,HEADER_BYTES).arrayBuffer()),view=new DataView(head.buffer,head.byteOffset,head.byteLength);
  if(utf8(head.subarray(0,8))!==MAGIC)throw Error('X-Media magic ไม่ถูกต้อง');
  const version=view.getUint32(8,true);if(version!==VERSION)throw Error('X-Media version '+version+' ยังไม่รองรับ');
  const metadataBytes=u64(view,12),mediaBytes=u64(view,20);if(metadataBytes<4||metadataBytes>MAX_METADATA)throw Error('X-Media metadata มีขนาดผิดปกติ');
  const mediaOffset=HEADER_BYTES+metadataBytes;if(mediaOffset+mediaBytes!==blob.size)throw Error('X-Media ขนาดไฟล์ไม่ตรงกับ header');
  const mediaSha=head.slice(28,60),metadataSha=head.slice(60,92);
  const metadata=new Uint8Array(await blob.slice(HEADER_BYTES,mediaOffset).arrayBuffer());
  const actualMetadataSha=await sha256(metadata);if(!equalBytes(metadataSha,actualMetadataSha))throw Error('X-Media metadata SHA-256 ไม่ตรงกัน');
  const document=decodeMetadata(metadata);
  return {document,code:document.songCode,title:document.title,artist:document.artist,mediaOffset,mediaBytes,
    mediaSha256:hex(mediaSha),metadataSha256:hex(metadataSha),mediaKind:format.kind,mediaExtension:format.extension,mimeType:format.mime,format:ext(name).toUpperCase()};
}
async function openPackage(blob,{verifyMedia=true,signal,name=blob?.name||''}={}){
  const info=await inspectMetadata(blob,name),media=blob.slice(info.mediaOffset,info.mediaOffset+info.mediaBytes,info.mimeType);
  if(verifyMedia){const actual=await sha256Blob(media,signal);if(hex(actual)!==info.mediaSha256)throw Error('X-Media media SHA-256 ไม่ตรงกัน');}
  return {...info,media};
}
scope.XStageXMedia={MAGIC,VERSION,HEADER_BYTES,FORMATS,supports,formatOf,inspectMetadata,openPackage,decodeMetadata,sha256Blob};
})(typeof window!=='undefined'?window:globalThis);
