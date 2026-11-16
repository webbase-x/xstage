/* XSK1 authorized browser/Android-WebView import bridge.
 * No network requests, key persistence, plaintext temp files or public tokens.
 * A password-wrapped access file is supplied by the owner from Song Studio PC.
 */
(function(scope){
'use strict';
const MAGIC='XSK-ACCESS1', AAD=new TextEncoder().encode(MAGIC);
const MAX_PACKAGE=152*1024*1024, MAX_MIDI=128*1024*1024, MAX_JSON=8*1024*1024;
const fail=message=>{throw Error('XSK: '+message);};
const u8=(data)=>data instanceof Uint8Array?data:new Uint8Array(data);
const ascii=(bytes)=>String.fromCharCode(...bytes);
function base64(value){
  if(typeof value!=='string'||value.length>300)return fail('ข้อมูลกุญแจผิดรูปแบบ');
  const binary=atob(value);
  return Uint8Array.from(binary,c=>c.charCodeAt(0));
}
async function unlockAccess(accessFile,password){
  if(!scope.crypto?.subtle||typeof password!=='string'||password.length<12)
    fail('ต้องใช้ WebCrypto และรหัสผ่านสิทธิ์ XSK อย่างน้อย 12 ตัวอักษร');
  if(!accessFile||accessFile.size>4096)fail('ไฟล์สิทธิ์ XSK มีขนาดผิดปกติ');
  let doc;
  try{doc=JSON.parse(await accessFile.text());}
  catch{fail('อ่านไฟล์สิทธิ์ไม่ได้');}
  if(doc?.format!==MAGIC||doc?.kdf!=='PBKDF2-SHA256'||doc?.iterations!==310000)
    fail('ไฟล์สิทธิ์ XSK ไม่ใช่รูปแบบที่ Song Studio รองรับ');
  const salt=base64(doc.salt),iv=base64(doc.nonce),wrapped=base64(doc.wrappedKey);
  if(salt.length!==16||iv.length!==12||wrapped.length!==48)
    fail('ไฟล์สิทธิ์ XSK ไม่สมบูรณ์');
  const seed=await scope.crypto.subtle.importKey('raw',new TextEncoder().encode(password),
    'PBKDF2',false,['deriveKey']);
  const wrapper=await scope.crypto.subtle.deriveKey(
    {name:'PBKDF2',hash:'SHA-256',salt,iterations:310000},
    seed,{name:'AES-GCM',length:256},false,['decrypt']);
  let plaintext;
  try{plaintext=await scope.crypto.subtle.decrypt(
    {name:'AES-GCM',iv,additionalData:AAD},wrapper,wrapped);}
  catch{fail('รหัสผ่านหรือไฟล์สิทธิ์ XSK ไม่ถูกต้อง');}
  if(plaintext.byteLength!==32)fail('ความยาวกุญแจ XSK ผิดปกติ');
  return scope.crypto.subtle.importKey('raw',plaintext,{name:'AES-GCM'},false,['decrypt']);
}
async function inflate(bytes,method,expected){
  if(expected<0||expected>MAX_MIDI)fail('ไฟล์ภายในมีขนาดเกินกำหนด');
  if(method===0){
    if(bytes.length!==expected)fail('ZIP STORED มีขนาดไม่ตรง');
    return bytes;
  }
  if(method!==8||typeof scope.DecompressionStream!=='function')
    fail('เบราว์เซอร์ไม่รองรับ ZIP DEFLATE ของ XSK (ต้องใช้เบราว์เซอร์รุ่นใหม่)');
  let reader;
  try{
    reader=new Blob([bytes]).stream().pipeThrough(
      new scope.DecompressionStream('deflate-raw')).getReader();
    const chunks=[];let total=0;
    for(;;){
      const {value,done}=await reader.read();
      if(done)break;
      total+=value.length;
      if(total>expected){await reader.cancel();fail('ZIP ขยายเกินขนาดที่ประกาศ');}
      chunks.push(value);
    }
    if(total!==expected)fail('ZIP ขยายได้ขนาดไม่ตรง');
    const output=new Uint8Array(total);let position=0;
    for(const chunk of chunks){output.set(chunk,position);position+=chunk.length;}
    return output;
  }catch(error){fail('แตกไฟล์ XSK ไม่สำเร็จ: '+error.message);}
}
function zipEntries(raw){
  const bytes=u8(raw), dv=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
  const r16=i=>dv.getUint16(i,true),r32=i=>dv.getUint32(i,true);
  let eocd=-1;
  for(let p=bytes.length-22;p>=Math.max(0,bytes.length-65557);p--){
    if(r32(p)===0x06054b50&&p+22+r16(p+20)===bytes.length){eocd=p;break;}
  }
  if(eocd<0||r16(eocd+4)||r16(eocd+6)||r16(eocd+8)!==2||
      r16(eocd+10)!==2)fail('ZIP ภายในไม่ครบ MIDI/JSON หรือมีหลายดิสก์');
  const length=r32(eocd+12),start=r32(eocd+16);
  if(start+length>eocd)fail('ZIP central directory เกินขอบเขต');
  let pos=start;const found=[];
  for(let i=0;i<2;i++){
    if(pos+46>eocd||r32(pos)!==0x02014b50)fail('ZIP directory ไม่ถูกต้อง');
    const flags=r16(pos+8),method=r16(pos+10),comp=r32(pos+20),
      size=r32(pos+24),nameLen=r16(pos+28),extra=r16(pos+30),
      comment=r16(pos+32),offset=r32(pos+42);
    if((flags&1)||![0,8].includes(method)||nameLen<1||nameLen>150||
       size>MAX_MIDI||comp>MAX_MIDI||pos+46+nameLen+extra+comment>eocd)
      fail('ZIP entries มีขนาด/วิธีบีบอัดไม่ปลอดภัย');
    const name=ascii(bytes.subarray(pos+46,pos+46+nameLen));
    if(!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,149}$/.test(name)||name.startsWith('.'))
      fail('ชื่อไฟล์ภายใน XSK ไม่ปลอดภัย');
    if(offset+30>start||r32(offset)!==0x04034b50)fail('ZIP local header ไม่ถูกต้อง');
    const localNameLen=r16(offset+26),localExtra=r16(offset+28),
      dataAt=offset+30+localNameLen+localExtra;
    if(dataAt+comp>start||localNameLen!==nameLen||
      ascii(bytes.subarray(offset+30,offset+30+localNameLen))!==name)
      fail('ZIP local และ central ไม่ตรงกัน');
    found.push({name,method,size,compressed:bytes.subarray(dataAt,dataAt+comp)});
    pos+=46+nameLen+extra+comment;
  }
  if(pos!==start+length||new Set(found.map(x=>x.name)).size!==2)
    fail('ZIP directory ไม่ตรงหรือมีชื่อซ้ำ');
  return found;
}
async function openPackage(file,key){
  if(!file||!Number.isFinite(file.size)||file.size<33||file.size>MAX_PACKAGE)
    fail('ขนาดไฟล์ไม่ปลอดภัย');
  const bytes=u8(await file.arrayBuffer());
  if(ascii(bytes.subarray(0,4))!=='XSK1')fail('ไฟล์ไม่ใช่ XSK1');
  let plain;
  try{plain=await scope.crypto.subtle.decrypt(
    {name:'AES-GCM',iv:bytes.subarray(4,16),
     additionalData:bytes.subarray(0,4)},key,bytes.subarray(16));}
  catch{fail('ไม่มีสิทธิ์ถอดรหัส XSK หรือแพ็กเกจเสียหาย');}
  const entries=zipEntries(plain);
  const docEntry=entries.filter(x=>x.name.endsWith('.json'))[0];
  if(!docEntry||docEntry.size>MAX_JSON)fail('ไม่พบ Lyrics JSON ภายใน XSK');
  let doc;
  try{doc=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(
    await inflate(docEntry.compressed,docEntry.method,docEntry.size)));}
  catch(error){fail('ข้อมูล Lyrics JSON ภายใน XSK ผิดปกติ: '+error.message);}
  const audio=doc?.audio||{}, midiEntry=entries.find(x=>x.name===audio.file);
  if(doc?.format!=='XSK'||doc?.formatVersion!==1||doc?.schemaVersion!==2||
      !midiEntry||!/^.+\.(mid|midi|kar)$/i.test(midiEntry.name)||
      !/^[a-f0-9]{64}$/i.test(String(audio.sha256||''))||
      !Array.isArray(doc.lines)||!doc.lines.length)
    fail('XSK ไม่มี MIDI และ Lyrics JSON ที่มีโครงสร้างถูกต้อง');
  const media=await inflate(midiEntry.compressed,midiEntry.method,midiEntry.size);
  const hash=new Uint8Array(await scope.crypto.subtle.digest('SHA-256',media));
  const digest=Array.from(hash,x=>x.toString(16).padStart(2,'0')).join('');
  if(digest!==audio.sha256.toLowerCase()||media.length!==audio.size)
    fail('SHA-256 ของ MIDI ภายใน XSK ไม่ตรง');
  // Compatible with the existing catalog/player schemaVersion 1.
  const normalized={...doc,schemaVersion:1,sourceFormat:'XSK'};
  const core=scope.XStageImportCore;
  if(!core?.validLyricsJson)fail('ไม่พบระบบตรวจสอบ Lyrics JSON ของ X-Stage');
  core.validLyricsJson(normalized,doc.songCode);
  const code=String(doc.songCode||'').trim();
  if(!/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(code))
    fail('รหัสเพลงภายใน XSK ไม่ปลอดภัย');
  return {code,document:normalized,
    midi:new File([media],midiEntry.name,{type:'audio/midi'}),
    lyrics:new File([JSON.stringify(normalized)],code+'.json',{type:'application/json'})};
}
scope.XStageXsk={unlockAccess,openPackage};
})(typeof window!=='undefined'?window:globalThis);
