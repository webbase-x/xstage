import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const read=p=>fs.readFileSync(new URL('../'+p,import.meta.url),'utf8');
const upload=read('cloud-import.js'),app=read('app.js');
const startUpload=upload.indexOf('const MiB=1024*1024,CHUNK=');
const endUpload=upload.indexOf('\nfunction fail(',startUpload);
assert.ok(startUpload>=0&&endUpload>startUpload,'Adaptive Drive upload code must exist');
const chooseChunk=vm.runInNewContext(upload.slice(startUpload,endUpload)+'\nnextUploadChunk;');
const M=1024*1024;
assert.equal(chooseChunk(8*M,0,48*M),8*M);
assert.equal(chooseChunk(8*M,7*M,48*M),16*M);
assert.equal(chooseChunk(16*M,20*M,48*M),32*M);
assert.equal(chooseChunk(8*M,30*M,12*M),8*M);
for(const chunk of [chooseChunk(8*M,7*M,48*M),chooseChunk(8*M,20*M,100*M)])
  assert.equal(chunk%(256*1024),0,'Drive resumable chunk must be 256 KiB-aligned');
assert.ok(upload.includes('onBytes(start,file.size,Number.isFinite(measured)?measured:0)'),
  'Upload must report measured committed bytes per second');
assert.ok(upload.includes('const uploadPair=async(first,second)=>')&&
  upload.includes('Promise.allSettled([first(),second()])'),
  'Independent song and timed lyrics uploads must await both commits before publishing');
const pairStart=upload.indexOf('const uploadPair=async(');
const pairEnd=upload.indexOf('\n      const publish=async',pairStart);
assert.ok(pairEnd>pairStart,'Parallel upload helper must be independently testable');
const uploadPair=vm.runInNewContext(upload.slice(pairStart,pairEnd)+'\nuploadPair;');
let finished=0;
const [song,lyrics]=await uploadPair(async()=>{finished++;return 'song-id';},
  async()=>{finished++;return 'lyrics-id';});
assert.equal(finished,2);
assert.equal(song,'song-id');assert.equal(lyrics,'lyrics-id');
let failureSettled=false;
await assert.rejects(uploadPair(async()=>{throw Error('Drive 403');},
  async()=>{failureSettled=true;return 'completed-lyric';}),/Drive 403/);
assert.equal(failureSettled,true,'Do not publish a failed pair or abandon pending verification');

const from=app.indexOf('const FAST_DOWNLOAD_MIB=1024*1024;');
const to=app.indexOf('\nasync function privateJson(',from);
assert.ok(from>=0&&to>from,'Fast Drive blob downloader must exist');
// Use smaller threshold in behavioral tests, preserving the exact range logic.
const source=app.slice(from,to).replace('const FAST_DOWNLOAD_MIB=1024*1024;',
  'const FAST_DOWNLOAD_MIB=1024;');
let data=Uint8Array.from({length:700000},(_,i)=>i%251);
let requests=[],fallbacks=0,mode='ranges';
const ctx={
  Blob,Uint8Array,AbortController,DOMException,Number,Math,Promise,
  navigator:{deviceMemory:4,userAgent:'Android',connection:{saveData:false}},
  requestHeaders:token=>({Authorization:'Bearer '+token}),
  driveError:(status)=>Error('Drive permission '+status),
  privateFile:async()=>{fallbacks++;return {blob:async()=>new Blob([data])};},
  googleFetch:async(url,options)=>{
    const specified=options.headers.Range;
    requests.push(specified);
    const [start,end]=specified.match(/^bytes=(\d+)-(\d+)$/).slice(1).map(Number);
    const actual=mode==='bad-range'?'bytes 0-100/'+data.byteLength:
      'bytes '+start+'-'+end+'/'+data.byteLength;
    if(mode==='forbidden')return {status:403,body:{cancel:async()=>{}}};
    if(mode==='ignored')return {status:200,body:{cancel:async()=>{}}};
    return {status:206,headers:{get:()=>actual},
      arrayBuffer:async()=>data.slice(start,end+1).buffer};
  }
};
const {fastDownloadParts,fastPrivateBlob}=vm.runInNewContext(source+
  '\n({fastDownloadParts,fastPrivateBlob});',ctx);
assert.equal(fastDownloadParts(10*M),2,'24-MiB+ media must split when memory allows');
assert.equal(fastDownloadParts(192*M+1),1,'Oversized media must not be multiplied in RAM');
assert.equal(fastDownloadParts(64*M),2,'Phone memory protection limits parallelism');
requests=[];fallbacks=0;mode='ranges';
let blob=await fastPrivateBlob('fileABCDE','test-token',{size:data.byteLength});
assert.equal(requests.length,2,'Parallel Drive must issue two independent byte ranges');
assert.equal(fallbacks,0);
assert.equal(blob.size,data.byteLength);
assert.deepEqual(new Uint8Array(await blob.arrayBuffer()),data,
  'Assembled bytes must exactly match the original media file');
mode='ignored';requests=[];fallbacks=0;
blob=await fastPrivateBlob('fileABCDE','test-token',{size:data.byteLength});
assert.equal(fallbacks,1,'HTTP 200 to a Range request requires a single-stream fallback');
assert.deepEqual(new Uint8Array(await blob.arrayBuffer()),data);
mode='bad-range';requests=[];fallbacks=0;
blob=await fastPrivateBlob('fileABCDE','test-token',{size:data.byteLength});
assert.equal(fallbacks,1,'Invalid Content-Range requires a safe fallback');
assert.deepEqual(new Uint8Array(await blob.arrayBuffer()),data);
mode='forbidden';fallbacks=0;
await assert.rejects(fastPrivateBlob('fileABCDE','test-token',{size:data.byteLength}),/permission 403/);
assert.equal(fallbacks,0,'Authorization errors must never bypass Drive access control');
const controller=new AbortController();controller.abort();
await assert.rejects(fastPrivateBlob('fileABCDE','test-token',
  {size:data.byteLength,signal:controller.signal}),{name:'AbortError'});
ctx.navigator.connection.saveData=true;
assert.equal(fastDownloadParts(64*M),1,'User data saver must disable parallel download');
console.log('PASS: fast Drive upload sizing, parallel commit safety, 206 range integrity, 200 fallback, error/abort and memory limits');
