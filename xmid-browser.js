/* Song Studio Pro XSTGPLS1 XMID reader for X-Stage Karaoke Online.
 * The original package stays in Drive. MIDI is verified before playback.
 */
(function(scope){
'use strict';
const fail=s=>{throw Error('XMID: '+s);};
const HEADER=92,MAX_META=32*1024*1024,MAX_MIDI=64*1024*1024;
const decoder=new TextDecoder('utf-8',{fatal:true});
const toHex=a=>Array.from(new Uint8Array(a),x=>x.toString(16).padStart(2,'0')).join('');
async function verify(bytes,expected){
  if(!scope.crypto?.subtle)fail('เบราว์เซอร์ไม่รองรับ SHA-256');
  const digest=await scope.crypto.subtle.digest('SHA-256',bytes);
  if(toHex(digest)!==toHex(expected))fail('SHA-256 ไม่ตรงกับไฟล์ต้นฉบับ');
}
function metadata(bytes){
  const view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
  let offset=0;
  const need=n=>{if(n<0||offset+n>bytes.length)fail('metadata ไม่ครบ');};
  const u32=()=>{need(4);const n=view.getUint32(offset,true);offset+=4;return n;};
  const f64=()=>{need(8);const n=view.getFloat64(offset,true);offset+=8;return n;};
  const str=()=>{const size=u32();if(size>1048576)fail('ข้อความยาวเกินกำหนด');need(size);
    const value=decoder.decode(bytes.subarray(offset,offset+size));offset+=size;return value;};
  const [songId,code,lyricsVersionId,title,artist,timingStatus]=Array.from({length:6},str);
  const count=u32();if(count>100000)fail('จำนวนบรรทัดเกินขอบเขต');
  const lines=[];
  for(let i=0;i<count;i++){
    const startTime=f64(),endTime=f64(),text=str(),status=str(),n=u32();
    if(!Number.isFinite(startTime)||!Number.isFinite(endTime)||startTime<0||
       endTime<=startTime||n>100000)fail('เวลาบรรทัดหรือจำนวนจุดปาดไม่ถูกต้อง');
    const syllables=[];let previous=-1;
    for(let j=0;j<n;j++){
      const start=f64(),duration=f64(),glyph=str();
      if(!Number.isFinite(start)||!Number.isFinite(duration)||duration<0||
         start<startTime-.001||start>endTime+.001||start<previous)
        fail('เวลาปาดสีย้อนกลับหรือออกนอกบรรทัด');
      previous=start;syllables.push({startTime:start,start,duration,text:glyph});
    }
    lines.push({startTime,endTime,text,timingStatus:status,syllables});
  }
  if(offset!==bytes.length)fail('metadata มีข้อมูลส่วนเกิน');
  const document={schemaVersion:1,songCode:code,title,artist,sourceFormat:'XMID',
    songId,lyricsVersionId,timingStatus,lines};
  scope.XStageImportCore?.validLyricsJson(document,code);
  if(!/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(code))fail('รหัสเพลงไม่ปลอดภัย');
  const identity=scope.XStageImportCore?.songIdentity(document,code);
  if(!identity)fail('ไม่พบระบบตรวจสอบชื่อเพลง');
  // Some intact XMID packages contain playable MIDI but do not contain
  // a real artist or timed lyrics. Preserve the original package bytes and
  // mark missing metadata explicitly instead of treating MIDI as corrupt.
  const placeholderLyrics=lines.length===1&&
    /^x-stage karaoke$/i.test(String(lines[0].text||'').trim());
  document.title=identity.title;document.artist=identity.artist;
  document.metadataComplete=Boolean(identity.identityComplete);
  if(placeholderLyrics){
    document.lines=[];
    document.lyricsMode='unavailable';
  }
  return {code,document,identityComplete:Boolean(identity.identityComplete),
    lyricsAvailable:!placeholderLyrics};
}
async function openPackage(file,{metadataOnly=false}={}){
  if(!(file instanceof Blob))fail('ไม่พบไฟล์');
  if(file.size<HEADER||file.size>HEADER+MAX_META+MAX_MIDI)fail('ขนาดไฟล์เกินขอบเขต');
  const header=new Uint8Array(await file.slice(0,HEADER).arrayBuffer());
  const magic=decoder.decode(header.subarray(0,8));
  if(magic!=='XSTGPLS1')fail('ไม่ใช่ XMID จาก Song Studio Pro');
  const view=new DataView(header.buffer);
  if(view.getUint32(8,true)!==1)fail('เวอร์ชันไฟล์ไม่รองรับ');
  const metaSize=Number(view.getBigUint64(12,true)),mediaSize=Number(view.getBigUint64(20,true));
  if(!Number.isSafeInteger(metaSize)||!Number.isSafeInteger(mediaSize)||
     metaSize<1||metaSize>MAX_META||mediaSize<1||mediaSize>MAX_MIDI||
     HEADER+metaSize+mediaSize!==file.size)fail('ส่วนหัวระบุขนาดผิดปกติ');
  const meta=new Uint8Array(await file.slice(HEADER,HEADER+metaSize).arrayBuffer());
  await verify(meta,header.subarray(60,92));
  const result=metadata(meta);
  if(metadataOnly)return result;
  const midi=new Uint8Array(await file.slice(HEADER+metaSize).arrayBuffer());
  await verify(midi,header.subarray(28,60));
  if(decoder.decode(midi.subarray(0,4))!=='MThd' &&
     decoder.decode(midi.subarray(0,4))!=='NCN1')fail('สื่อใน XMID ไม่ใช่ MIDI');
  return {...result,midi:new Blob([midi],{type:'audio/midi'})};
}
scope.XStageXmid={inspectMetadata:file=>openPackage(file,{metadataOnly:true}),openPackage};
})(typeof window!=='undefined'?window:globalThis);
