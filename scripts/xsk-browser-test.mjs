/* Portable XSK2 imported by Web and Android WebView: no key/password. */
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {createHash,webcrypto} from 'node:crypto';
import {deflateRawSync} from 'node:zlib';
import {File} from 'node:buffer';

const ctx={Blob,File,TextEncoder,TextDecoder,Uint8Array,DataView,
  DecompressionStream,crypto:webcrypto,console};
ctx.window=ctx;
vm.runInNewContext(fs.readFileSync(new URL('../cloud-import-core.js',import.meta.url),'utf8'),ctx);
vm.runInNewContext(fs.readFileSync(new URL('../xsk-browser.js',import.meta.url),'utf8'),ctx);
const bridge=ctx.XStageXsk,core=ctx.XStageImportCore;
const enc=new TextEncoder();

function zip(files){
  const local=[],central=[];let offset=0;
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
const midi=Buffer.from('4d546864000000060000000101e04d54726b0000000d00903c508170803c0000ff2f00','hex');
const doc={schemaVersion:2,format:'XSK',formatVersion:2,songCode:'00001',
  title:'ทำได้เพียง',artist:'25 Hours',createdBy:'X-Stage Song Studio',
  audio:{file:'00001.mid',type:'MID',size:midi.length,
    sha256:createHash('sha256').update(midi).digest('hex')},
  lines:[{startTime:1.2,text:'เริ่มร้อง'},{startTime:2.3,text:'ต่อไป'}]};
const xsk=(document)=>new File([Buffer.from('XSK2'),
  zip([['00001.mid',midi],['00001.json',enc.encode(JSON.stringify(document))]])],
  '00001.xsk');
const decoded=await bridge.openPackage(xsk(doc));
assert.equal(decoded.code,'00001');
assert.equal(decoded.document.schemaVersion,1);
assert.equal(decoded.document.title,'ทำได้เพียง');
assert.equal(decoded.document.artist,'25 Hours');
assert.equal(decoded.document.sourceFormat,'XSK');
assert.deepEqual(Buffer.from(await decoded.midi.arrayBuffer()),midi);
assert.equal(core.songIdentity(decoded.document,'00001').artist,'25 Hours');
assert.equal(decoded.lyrics.name,'00001.json');
assert.throws(()=>bridge.openPackage(new File([Buffer.from('XSK1'+'A'.repeat(64))],
  'old.xsk')),/XSK1/);
await assert.rejects(()=>bridge.openPackage(xsk({...doc,audio:{...doc.audio,sha256:'0'.repeat(64)}})),
  /SHA-256/);
await assert.rejects(()=>bridge.openPackage(xsk({...doc,title:'00001',artist:'X-Stage Karaoke'})),
  /ชื่อเพลงหรือศิลปิน/);
console.log('PASS: portable XSK2 (no key), ZIP deflate, SHA-256, real identity and XSK1 migration');
