import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {createHash,webcrypto} from 'node:crypto';

const files=new Map();
let fetches=0;
const context={URL,TextEncoder,Uint8Array,ArrayBuffer,Response,TransformStream,DOMException,
  crypto:webcrypto,location:{href:'https://example.test/xstage/karaoke.html'},
  navigator:{storage:{estimate:async()=>({quota:10*1024**3,usage:0})}},
  caches:{open:async name=>{
    if(!files.has(name))files.set(name,new Map());
    const map=files.get(name);
    return {keys:async()=>[...map.keys()].map(url=>({url})),
      match:async key=>map.get(typeof key==='string'?key:key.url)?.clone(),
      delete:async key=>map.delete(typeof key==='string'?key:key.url),
      put:async(key,response)=>{
        // Model atomic CacheStorage commit after the full stream succeeds.
        const bytes=await response.arrayBuffer();
        map.set(key,new Response(bytes,{headers:response.headers}));
      }};
  }}};
context.window=context;
for(const p of ['cloud-import-core.js','private-media-cache.js'])
  vm.runInNewContext(fs.readFileSync(new URL('../'+p,import.meta.url),'utf8'),context);
const api=context.XStagePrivateMediaCache;
const bytes=new TextEncoder().encode('MIDI test payload');
const md5=createHash('md5').update(bytes).digest('hex');
const media={fileId:'file0001',size:bytes.length,md5Checksum:md5};
const fetcher=async()=>{fetches++;return new Response(bytes);};
const request=(owner='owner:root:a',extra={})=>api.getOrFetch({owner,media,fetcher,...extra});
assert.equal(await (await request()).text(),'MIDI test payload');
assert.equal(await (await request()).text(),'MIDI test payload');
assert.equal(fetches,1,'identical verified file must be reused');
assert.equal(await (await request('owner:root:b')).text(),'MIDI test payload');
assert.equal(fetches,2,'other library must not reuse private media');
await assert.rejects(request('owner:root:c',{fetcher:async()=>new Response(new Uint8Array(bytes.length))}),/MD5\/size mismatch/);
assert.equal([...files.values()].reduce((n,map)=>n+map.size,0),2,'bad file must not be committed');
assert.equal(await request('owner:root:c',{cacheOnly:true,media:{...media,md5Checksum:''}}),null,'do not preload unverifiable files');
const abort=new AbortController();abort.abort();
await assert.rejects(request('owner:root:a',{signal:abort.signal}),{name:'AbortError'});
console.log('PASS: persistent private song cache reuses MD5/size, scopes accounts/roots, rejects corrupt and cancelled transfers');

// OPFS simulation models a retained prefix across a short response and
// reopens a new writable handle with its previously committed contents.
const disk=new Map();
function folder(path){
  return {getDirectoryHandle:async name=>folder(path+'/'+name),
    removeEntry:async name=>{disk.delete(path+'/'+name);},
    getFileHandle:async name=>{
      const key=path+'/'+name;
      if(!disk.has(key))disk.set(key,new Uint8Array());
      return {getFile:async()=>new Blob([disk.get(key)]),
        createWritable:async({keepExistingData})=>{
          let buffer=keepExistingData?disk.get(key).slice():new Uint8Array(),pos=0;
          return {seek:async offset=>{pos=offset;},
            write:async data=>{
              const result=new Uint8Array(Math.max(buffer.length,pos+data.length));
              result.set(buffer);result.set(data,pos);pos+=data.length;buffer=result;
            },
            close:async()=>disk.set(key,buffer),abort:async()=>{}};
        }};
    }};
}
context.navigator.storage.getDirectory=async()=>folder('');
context.navigator.locks={request:async(_key,fn)=>fn()};
const offsets=[];
const rangeFetcher=async offset=>{
  offsets.push(offset);
  if(!offset)return new Response(bytes.slice(0,6));
  return new Response(bytes.slice(offset),{status:206,headers:{
    'Content-Range':'bytes '+offset+'-'+(bytes.length-1)+'/'+bytes.length}});
};
await assert.rejects(request('owner:resume',{rangeFetcher}),/interrupted/);
assert.equal(await (await request('owner:resume',{rangeFetcher})).text(),'MIDI test payload');
assert.deepEqual(offsets,[0,6]);
assert.equal(disk.size,0,'partial removed only after full verified cache commit');
console.log('PASS: media prefix survives interrupted download, HTTP 206 resumes and verifies');
