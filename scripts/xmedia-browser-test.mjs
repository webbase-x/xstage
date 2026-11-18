import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import vm from 'node:vm';

const context={
  crypto:crypto.webcrypto,TextDecoder,Uint8Array,Uint32Array,DataView,Blob,DOMException,
  BigInt,Number,Array,String,Error,Map,Set,Math
};
context.globalThis=context;
vm.createContext(context);
vm.runInContext(fs.readFileSync(new URL('../xmedia-browser.js',import.meta.url),'utf8'),context,{filename:'xmedia-browser.js'});
const api=context.XStageXMedia;
assert.ok(api,'XStageXMedia export missing');

function text(value){
  const raw=Buffer.from(value,'utf8'),head=Buffer.alloc(4);head.writeUInt32LE(raw.length);
  return Buffer.concat([head,raw]);
}
function f64(a,b){const out=Buffer.alloc(16);out.writeDoubleLE(a,0);out.writeDoubleLE(b,8);return out;}
function fixture(name='00000042.xmp3'){
  const cueCount=Buffer.alloc(4);cueCount.writeUInt32LE(2);
  const line=Buffer.concat([f64(1,3),text('สวัสดี'),text('complete'),cueCount,
    f64(1,.5),text('ส'),f64(1.5,.75),text('วัสดี')]);
  const lineCount=Buffer.alloc(4);lineCount.writeUInt32LE(1);
  const meta=Buffer.concat(['song-42','42','version-1','เพลงทดสอบ','ศิลปินทดสอบ','complete'].map(text)
    .concat([lineCount,line]));
  const media=Buffer.concat([Buffer.from('ID3'),Buffer.alloc(4096,7)]);
  const head=Buffer.alloc(92);head.write('XSTGPLS1',0,'ascii');head.writeUInt32LE(1,8);
  head.writeBigUInt64LE(BigInt(meta.length),12);head.writeBigUInt64LE(BigInt(media.length),20);
  crypto.createHash('sha256').update(media).digest().copy(head,28);
  crypto.createHash('sha256').update(meta).digest().copy(head,60);
  const blob=new Blob([head,meta,media]);Object.defineProperty(blob,'name',{value:name});
  return {blob,meta,media};
}
const {blob}=fixture();
const opened=await api.openPackage(blob);
assert.equal(opened.code,'42');
assert.equal(opened.title,'เพลงทดสอบ');
assert.equal(opened.artist,'ศิลปินทดสอบ');
assert.equal(opened.mediaKind,'audio');
assert.equal(opened.mediaExtension,'mp3');
assert.equal(opened.document.lines[0].syllables.length,2);
assert.equal(opened.document.lines[0].syllables[1].start,1.5);
assert.equal(Buffer.from(await opened.media.arrayBuffer()).subarray(0,3).toString(),'ID3');
const nameless=new Blob([await blob.arrayBuffer()]);
const driveOpened=await api.openPackage(nameless,{name:'AUDIO/XMP3/0/00000042.xmp3'});
assert.equal(driveOpened.mediaKind,'audio','Drive Blob without File.name must use catalog path');

const xmid=fixture('00000042.xmid').blob;
assert.equal((await api.inspectMetadata(xmid)).mediaKind,'midi');

const damaged=Buffer.from(await blob.arrayBuffer());damaged[damaged.length-1]^=1;
const bad=new Blob([damaged]);Object.defineProperty(bad,'name',{value:'00000042.xmp3'});
await assert.rejects(()=>api.openPackage(bad),/media SHA-256/);

const damagedMeta=Buffer.from(await blob.arrayBuffer());damagedMeta[95]^=1;
const badMeta=new Blob([damagedMeta]);Object.defineProperty(badMeta,'name',{value:'00000042.xmp3'});
await assert.rejects(()=>api.inspectMetadata(badMeta),/metadata SHA-256/);

assert.equal(api.supports('a.xmp4'),true);
assert.equal(api.supports('a.mp4'),false);
console.log('X-Media browser reader checks passed');
