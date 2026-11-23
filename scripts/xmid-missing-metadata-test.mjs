import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {createHash,webcrypto} from 'node:crypto';

const read=path=>fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const context={Blob,crypto:webcrypto,TextDecoder,TextEncoder,Uint8Array,DataView};
context.window=context;
vm.runInNewContext(read('cloud-import-core.js'),context);
vm.runInNewContext(read('xmid-browser.js'),context);

const u32=n=>{const b=Buffer.alloc(4);b.writeUInt32LE(n);return b;};
const f64=n=>{const b=Buffer.alloc(8);b.writeDoubleLE(n);return b;};
const str=s=>{const b=Buffer.from(s,'utf8');return Buffer.concat([u32(b.length),b]);};
const midi=Buffer.from([
  0x4d,0x54,0x68,0x64,0,0,0,6,0,0,0,1,0,96,
  0x4d,0x54,0x72,0x6b,0,0,0,4,0,0xff,0x2f,0
]);
function packageFile(artist,lyrics='X-Stage Karaoke'){
  const metadata=Buffer.concat([
    ...['test-song-360','360','test-version','00363',artist,'estimated'].map(str),
    u32(1),f64(0),f64(4),str(lyrics),str('estimated'),u32(0)
  ]);
  const header=Buffer.alloc(92);
  header.write('XSTGPLS1',0,'ascii');
  header.writeUInt32LE(1,8);
  header.writeBigUInt64LE(BigInt(metadata.length),12);
  header.writeBigUInt64LE(BigInt(midi.length),20);
  createHash('sha256').update(midi).digest().copy(header,28);
  createHash('sha256').update(metadata).digest().copy(header,60);
  return new Blob([header,metadata,midi],{type:'application/octet-stream'});
}

const pending=await context.XStageXmid.openPackage(packageFile(''));
assert.equal(pending.code,'360');
assert.equal(pending.midi.size,midi.length);
assert.equal(pending.identityComplete,false);
assert.equal(pending.document.metadataComplete,false);
assert.equal(pending.document.title,'00363');
assert.equal(pending.document.artist,'ไม่ระบุศิลปิน');
assert.equal(pending.lyricsAvailable,false);
assert.equal(pending.document.lyricsMode,'unavailable');
assert.equal(pending.document.lines.length,0,
  'Do not treat placeholder branding as verified song lyrics');

const complete=await context.XStageXmid.openPackage(packageFile('Original Artist','Lyrics line'));
assert.equal(complete.identityComplete,true);
assert.equal(complete.document.artist,'Original Artist');
assert.equal(complete.lyricsAvailable,true);
assert.equal(complete.document.lines.length,1);
assert.equal(complete.document.lyricsMode,undefined);

const broken=new Uint8Array(await packageFile('').arrayBuffer());
broken[100]^=0x01;
await assert.rejects(context.XStageXmid.openPackage(new Blob([broken])),
  /SHA-256/, 'Corrupt metadata must still be rejected');
console.log('PASS: Valid playable XMID imports with explicitly incomplete metadata; corrupt files stay blocked');
