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
const meta=await bridge.inspectMetadata(xsk(doc));
assert.equal(meta.document.title,'ทำได้เพียง');
assert.equal(meta.document.artist,'25 Hours');
assert.equal(meta.midi,undefined,'Import must not unpack MIDI media');
const decoded=await bridge.openPackage(xsk(doc));
assert.equal(decoded.code,'00001');
assert.equal(decoded.document.schemaVersion,1);
assert.equal(decoded.document.title,'ทำได้เพียง');
assert.equal(decoded.document.artist,'25 Hours');
assert.equal(decoded.document.sourceFormat,'XSK');
assert.deepEqual(Buffer.from(await decoded.midi.arrayBuffer()),midi);
assert.equal(core.songIdentity(decoded.document,'00001').artist,'25 Hours');
assert.equal(decoded.lyrics.name,'00001.json');
await assert.rejects(()=>bridge.openPackage(new File([Buffer.from('XSK1'+'A'.repeat(64))],
  'old.xsk')),/XSK1/);
const badDigest=xsk({...doc,audio:{...doc.audio,sha256:'0'.repeat(64)}});
assert.equal((await bridge.inspectMetadata(badDigest)).document.title,'ทำได้เพียง',
  'Only JSON is inspected at import; MIDI integrity checked on playback');
await assert.rejects(()=>bridge.openPackage(badDigest),/SHA-256/);
await assert.rejects(()=>bridge.openPackage(xsk({...doc,title:'00001',artist:'X-Stage Karaoke'})),
  /ชื่อเพลงหรือศิลปิน/);
console.log('PASS: portable XSK2 (no key), ZIP deflate, SHA-256, real identity and XSK1 migration');


 // Build an authentic XSTGPLS1 fixture with SHA-256 hashes and binary metadata.
 vm.runInNewContext(fs.readFileSync(new URL('../xmid-browser.js',import.meta.url),'utf8'),ctx);
 const xmid=ctx.XStageXmid;
 const u32=n=>{const b=Buffer.alloc(4);b.writeUInt32LE(n);return b;};
 const f64=n=>{const b=Buffer.alloc(8);b.writeDoubleLE(n);return b;};
 const str=s=>{const b=Buffer.from(s,'utf8');return Buffer.concat([u32(b.length),b]);};
 function fixture({title='ทดสอบภาษาไทย',artist='ศิลปินทดสอบ',lines=[],badHash=false}={}){
   const parts=['song-1','00001','lyrics-1',title,artist,'verified'].map(str);
   parts.push(u32(lines.length));
   for(const line of lines)parts.push(f64(line.startTime),f64(line.endTime),str(line.text),str('verified'),u32(0));
   const meta=Buffer.concat(parts),header=Buffer.alloc(92);
   header.write('XSTGPLS1');header.writeUInt32LE(1,8);
   header.writeBigUInt64LE(BigInt(meta.length),12);header.writeBigUInt64LE(BigInt(midi.length),20);
   createHash('sha256').update(midi).digest().copy(header,28);
   createHash('sha256').update(meta).digest().copy(header,60);
   if(badHash)header[28]^=255;
   return new Blob([header,meta,midi]);
 }
 const empty=await xmid.openPackage(fixture({title:'00001',artist:'unknown'}));
 assert.equal(empty.lyricsAvailable,false);
 assert.equal(empty.document.lines.length,0);
 assert.equal(empty.document.title,'ไม่ระบุชื่อเพลง');
 assert.equal(empty.document.artist,'ไม่ระบุศิลปิน');
 assert.deepEqual(Array.from(empty.document.metadataIssues),['missing-title','missing-artist','missing-timed-lyrics']);
 assert.deepEqual(Buffer.from(await empty.midi.arrayBuffer()),midi);
 const thai=await xmid.openPackage(fixture({lines:[{startTime:1,endTime:3,text:'ภาษาไทย'}]}));
 assert.equal(thai.document.title,'ทดสอบภาษาไทย');
 assert.equal(thai.document.lines[0].text,'ภาษาไทย');
 assert.equal(thai.lyricsAvailable,true);
 assert.equal(thai.document.metadataIssues.length,0);
 const suspect=await xmid.inspectMetadata(fixture({artist:'ทดสอบ\uFFFD'}));
 assert.ok(suspect.document.metadataIssues.includes('suspect-text-encoding'));
 const broken=fixture({badHash:true});
 await assert.rejects(()=>xmid.openPackage(broken),/SHA-256/);
 await assert.rejects(()=>xmid.openPackage(fixture({lines:[{startTime:3,endTime:1,text:'ผิดเวลา'}]})),/เวลา/);
 await assert.rejects(()=>xmid.openPackage(fixture({lines:[{startTime:1,endTime:3,text:' '}]})),/^Error: XMID: metadata/);
 console.log('PASS: XMID verified MIDI-only, missing metadata, Thai text, invalid timing and corrupt media digest');
