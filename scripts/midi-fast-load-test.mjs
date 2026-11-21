import fs from 'node:fs';
import assert from 'node:assert/strict';

const midi=fs.readFileSync(new URL('../browser-midi.js',import.meta.url),'utf8');
const html=fs.readFileSync(new URL('../karaoke.html',import.meta.url),'utf8');
const app=fs.readFileSync(new URL('../app.js',import.meta.url),'utf8');
assert.ok(html.includes('gsi/client" async'),'GIS must not block HTML parsing or DOMContentLoaded');
assert.ok(html.includes('browser-midi.js?v=1127-fast-gm-cache'),'Updated SoundFont loader must bypass old browser cache');
assert.ok(midi.includes('void loadBuiltinGm().catch'),'Default GM download must overlap the Drive folder scan');
assert.ok(midi.includes('const bytes=await loadBuiltinGm(signal)'),'A foreground song reuses the prefetched public GM bytes');
assert.ok(midi.includes("const PUBLIC_GM_CACHE='xstage-public-timgm6mb-v1'"));
assert.ok(!midi.includes("store.put('https://www.googleapis.com/drive"),'Never persist private Drive assets');
assert.ok(app.includes("gis.addEventListener('load'"),'Late Google GIS completion must show an actionable status');
const begin=midi.indexOf('const BUILTIN_GM_ID=');
const end=midi.indexOf('let context=null',begin);
assert.ok(begin>=0&&end>begin,'Public GM loader present');
const source=midi.slice(begin,end);
let requests=0,validations=0,stored=null;
const bank=new Uint8Array(120000);
bank.set([82,73,70,70,0,0,0,0,115,102,98,107]);
const cache={
  match:async()=>stored?.clone()||null,
  put:async(key,response)=>{stored=response.clone();},
  delete:async()=>{stored=null;}
};
const scope={caches:{open:async()=>cache}};
const fetch=async(url,opts)=>{
  requests++;
  assert.ok(url.includes('TimGM6mb.sf2'));
  assert.equal(opts.cache,'force-cache');
  assert.equal(opts.headers,undefined,'Public bank must not include private Drive token');
  return {ok:true,headers:{get:()=>String(bank.byteLength)},
    arrayBuffer:async()=>bank.buffer.slice(0)};
};
const factory=new Function('scope','fetch','validateFontContainer','fail','Response','Uint8Array','DOMException',
  source+'\nreturn {loadBuiltinGm};');
const fresh=()=>factory(scope,fetch,()=>{validations++},message=>{throw Error(message);},Response,Uint8Array,DOMException);
const first=fresh();
const [one,two]=await Promise.all([first.loadBuiltinGm(),first.loadBuiltinGm()]);
assert.equal(requests,1,'Simultaneous requests share one network download');
assert.equal(one.byteLength,bank.byteLength);
assert.equal(two,one);
await new Promise(resolve=>setImmediate(resolve)); // settle optional public cache write
assert.ok(stored,'Public GM successfully cached');
const next=fresh();
const cached=await next.loadBuiltinGm();
assert.equal(cached.byteLength,bank.byteLength);
assert.equal(requests,1,'New page session reuses the public GM from CacheStorage');
const cancelled=new AbortController();cancelled.abort();
await assert.rejects(next.loadBuiltinGm(cancelled.signal),error=>error.name==='AbortError');
assert.ok(validations>=2);
console.log('PASS: async GIS, background default GM preload, concurrent requests, validated public cache and abort');
