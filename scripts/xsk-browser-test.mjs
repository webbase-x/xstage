/* Browser XSK1 authenticated interoperability with Song Studio portable access. */
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {createHash,randomBytes,webcrypto,pbkdf2Sync} from 'node:crypto';
import {deflateRawSync} from 'node:zlib';
import {File} from 'node:buffer';

const ctx={Blob,File,TextEncoder,TextDecoder,Uint8Array,DataView,DecompressionStream,
  atob,crypto:webcrypto,console};
ctx.window=ctx;
vm.runInNewContext(fs.readFileSync(new URL('../cloud-import-core.js',import.meta.url),'utf8'),ctx);
vm.runInNewContext(fs.readFileSync(new URL('../xsk-browser.js',import.meta.url),'utf8'),ctx);
const bridge=ctx.XStageXsk,core=ctx.XStageImportCore;
const enc=new TextEncoder();
const key=randomBytes(32),password='long encrypted access password';
const salt=randomBytes(16),nonce=randomBytes(12);
const wrapping=pbkdf2Sync(password,salt,310000,32,'sha256');
const wrapKey=await webcrypto.subtle.importKey('raw',wrapping,'AES-GCM',false,['encrypt']);
const accessCipher=Buffer.from(await webcrypto.subtle.encrypt({
  name:'AES-GCM',iv:nonce,additionalData:enc.encode('XSK-ACCESS1')},wrapKey,key));
const access={format:'XSK-ACCESS1',kdf:'PBKDF2-SHA256',iterations:310000,
  salt:salt.toString('base64'),nonce:nonce.toString('base64'),
  wrappedKey:accessCipher.toString('base64'),publisher:'X-Stage Song Studio'};
const accessFile=new File([JSON.stringify(access)],'XStageSong-access.xskkey');
const unlocked=await bridge.unlockAccess(accessFile,password);
await assert.rejects(()=>bridge.unlockAccess(accessFile,'wrong password 123'),/รหัสผ่าน/);

function zip(files){
  const local=[],central=[];
  let offset=0;
  for(const [name,raw] of files){
    const nameBytes=Buffer.from(name),source=Buffer.from(raw);
    const packed=deflateRawSync(source);
    const header=Buffer.alloc(30);
    header.writeUInt32LE(0x04034b50,0);
    header.writeUInt16LE(20,4);
    header.writeUInt16LE(8,8);
    header.writeUInt32LE(packed.length,18);
    header.writeUInt32LE(source.length,22);
    header.writeUInt16LE(nameBytes.length,26);
    local.push(header,nameBytes,packed);
    const directory=Buffer.alloc(46);
    directory.writeUInt32LE(0x02014b50,0);
    directory.writeUInt16LE(20,4);
    directory.writeUInt16LE(20,6);
    directory.writeUInt16LE(8,10);
    directory.writeUInt32LE(packed.length,20);
    directory.writeUInt32LE(source.length,24);
    directory.writeUInt16LE(nameBytes.length,28);
    directory.writeUInt32LE(offset,42);
    central.push(directory,nameBytes);
    offset+=header.length+nameBytes.length+packed.length;
  }
  const centralData=Buffer.concat(central);
  const ending=Buffer.alloc(22);
  ending.writeUInt32LE(0x06054b50,0);
  ending.writeUInt16LE(files.length,8);
  ending.writeUInt16LE(files.length,10);
  ending.writeUInt32LE(centralData.length,12);
  ending.writeUInt32LE(offset,16);
  return Buffer.concat([...local,centralData,ending]);
}
const midi=Buffer.from('MThd000000060000000101e0MTrk0000000400ff2f00','hex');
const doc={schemaVersion:2,format:'XSK',formatVersion:1,songCode:'00001',
  title:'ทำได้เพียง',artist:'25 Hours',createdBy:'X-Stage Song Studio',
  audio:{file:'00001.mid',type:'MID',size:midi.length,
    sha256:createHash('sha256').update(midi).digest('hex')},
  lines:[{startTime:1.2,text:'เริ่มร้อง'},{startTime:2.3,text:'ต่อไป'}]};
const plaintext=zip([['00001.mid',midi],['00001.json',enc.encode(JSON.stringify(doc))]]);
const iv=randomBytes(12);
const xskKey=await webcrypto.subtle.importKey('raw',key,'AES-GCM',false,['encrypt']);
const ciphertext=Buffer.from(await webcrypto.subtle.encrypt({
  name:'AES-GCM',iv,additionalData:enc.encode('XSK1')},xskKey,plaintext));
const xskBytes=Buffer.concat([Buffer.from('XSK1'),iv,ciphertext]);
const file=new File([xskBytes],'00001.xsk');
const decoded=await bridge.openPackage(file,unlocked);
assert.equal(decoded.code,'00001');
assert.equal(decoded.document.schemaVersion,1);
assert.equal(decoded.document.title,'ทำได้เพียง');
assert.equal(decoded.document.artist,'25 Hours');
assert.equal(decoded.document.sourceFormat,'XSK');
assert.deepEqual(Buffer.from(await decoded.midi.arrayBuffer()),midi);
assert.equal(core.songIdentity(decoded.document,'00001').artist,'25 Hours');
const tampered=Buffer.from(xskBytes);tampered[tampered.length-1]^=1;
await assert.rejects(()=>bridge.openPackage(new File([tampered],'bad.xsk'),unlocked),
  /ไม่มีสิทธิ์|เสียหาย/);
console.log('XSK portable access, browser AES-GCM, DEFLATE ZIP, SHA-256 and metadata PASS');
