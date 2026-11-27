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
