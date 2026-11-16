/* Adaptive queued media cache: all formats, RAM guard, eviction, font reuse. */
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const app=fs.readFileSync(new URL('../app.js',import.meta.url),'utf8');
const memory=fs.readFileSync(new URL('../memory-budget.js',import.meta.url),'utf8');
const handlers=new Map(),timers=new Map();
let timerId=0,downloads=[],renders=0,unpacks=0;
const media=(id,size)=>({fileId:id,size});
const audio={code:'001',title:'เพลงเสียง',artist:'นักร้อง',audio:media('a1',1024),lyrics:media('j1',100)};
const video={code:'002',title:'เพลงวิดีโอ',artist:'นักร้อง',audio:media('v1',1024),lyrics:media('j2',100)};
const midi={code:'003',title:'เพลง MIDI',artist:'นักร้อง',midi:media('m1',1024),lyrics:media('j3',100)};
const xsk={code:'004',title:'เพลง XSK',artist:'นักร้อง',xsk:media('x1',1024)};
const list=[audio,video,midi,xsk];
const file=new Blob(['valid media']),wav=new Blob(['rendered audio']);
const lyrics={schemaVersion:1,lines:[{startTime:1.1,text:'เนื้อร้อง'}]};
const state={token:'t',queue:list,queuePreload:null,queuePrepared:null,
  queuePreloadTimer:null,queuePreloadVersion:0,
  queuePreparedCache:new Map(),queuePreloadSkipped:new Set(),
  activeBlobBytes:0,activeVideoBytes:0,loading:false};
const indicators={};
const sandbox={
  navigator:{deviceMemory:2,userAgent:'Android'},
  performance:{memory:{usedJSHeapSize:150,jsHeapSizeLimit:1000}},
  AbortController,DOMException,Blob,Uint8Array,console,
  document:{getElementById:id=>indicators[id]||=({dataset:{},textContent:'',title:''})},
  setTimeout:cb=>{const id=++timerId;timers.set(id,cb);return id;},
  clearTimeout:id=>{timers.delete(id);},
  window:{addEventListener:(name,fn)=>handlers.set(name,fn),
    setInterval:()=>1,
    XStageBrowserMidi:{
      selectedFont:async()=>null,
      fontStatus:()=>({fileBytes:2*1024*1024,sampleBytes:0,loaded:true}),
      parseMidi:()=>({duration:1}),
      render:async()=>{renders++;return {audio:wav}}
    },
    XStageXsk:{openPackage:async()=>{unpacks++;return {
      code:'004',document:{...lyrics,code:'004',title:'เพลง XSK',artist:'นักร้อง'},
      midi:new Blob(['MIDI'])}}},
  },
  privateFile:async(id)=>{downloads.push(id);return {blob:async()=>file,
    arrayBuffer:async()=>Uint8Array.of(1,2,3).buffer,
    headers:{get:()=>null},body:{cancel:async()=>{}}}},
  privateJson:async()=>lyrics,
  prepareXskPlayback:async(song,token)=>({song,token,blob:wav,lyrics}),
  renderQueue:()=>{},
  getFileId:r=>r?.fileId||''
};
sandbox.window.window=sandbox.window;
sandbox.window.navigator=sandbox.navigator;
sandbox.window.performance=sandbox.performance;
vm.runInNewContext(memory,sandbox);
sandbox.window.XStageMemory=sandbox.XStageMemory||sandbox.window.XStageMemory;
const monitor=sandbox.window.XStageMemory;
assert.ok(monitor,'Memory policy should load');
assert.equal(monitor.plan().queueLimit,2);
// Hard cap is universal, even when desktop reports abundant RAM.
for(const ram of [1,2,4,8,16]){
  sandbox.navigator.deviceMemory=ram;
  assert.equal(monitor.plan().queueLimit,2,'At most two NEXT songs on '+ram+' GiB device');
}
sandbox.navigator.deviceMemory=2;
assert.equal(monitor.canHold(1024,{}),true);
const a=app.indexOf('function fontMemoryBytes(){'),b=app.indexOf('function prefetchMedleyNext(){',a);
assert.ok(a>=0&&b>a,'Adaptive queue functions must exist in app.js');
vm.runInNewContext(app.slice(a,b),sandbox,{filename:'XStage-queue-functions.js'});
assert.equal(typeof sandbox.prepareQueuedSong,'function');
const controller=new AbortController();
let prepared=await sandbox.prepareQueuedSong(audio,'t',controller.signal);
assert.equal(prepared.blob.size,file.size);
prepared=await sandbox.prepareQueuedSong(video,'t',controller.signal);
assert.equal(prepared.blob.size,file.size);
prepared=await sandbox.prepareQueuedSong(midi,'t',controller.signal);
assert.equal(prepared.blob.size,wav.size);
prepared=await sandbox.prepareQueuedSong(xsk,'t',controller.signal);
assert.equal(prepared.blob.size,wav.size);
assert.ok(downloads.includes('v1')&&downloads.includes('a1')&&downloads.includes('m1')&&downloads.includes('x1'));
assert.equal(unpacks,1);
assert.equal(renders,2);
assert.equal(sandbox.window.XStageMemory.plan({fontBytes:3*1048576,queuedBytes:100*1048576}).level,'high');
state.queuePreparedCache.set(audio,{song:audio,token:'t',blob:file,bytes:1024});
state.queuePreparedCache.set(video,{song:video,token:'t',blob:file,bytes:1024});
state.queuePreparedCache.set(midi,{song:midi,token:'t',blob:file,bytes:1024});
sandbox.trimQueueCache();
assert.ok(state.queuePreparedCache.size<=2,'Queue can keep at most two prepared songs on low RAM');
assert.ok(indicators['xstage-font-memory'].textContent.includes('SF ใน RAM'));
assert.ok(indicators['xstage-queue-memory'].textContent.includes('งบเตรียม'));
sandbox.performance.memory.usedJSHeapSize=990;
sandbox.trimQueueCache();
assert.equal(state.queuePreparedCache.size,0,'Memory pressure evicts queue cache');
sandbox.performance.memory.usedJSHeapSize=150;
state.queuePreparedCache.set(audio,{song:audio,token:'t',blob:file,bytes:1024});
handlers.get('xstage:soundfont-change')();
assert.equal(state.queuePreparedCache.size,0,'SoundFont selection invalidates already-rendered queued audio');
assert.ok(app.includes('state.queuePreparedCache.get(queued)'),'Player promotes completed queued song');
assert.ok(app.includes('pending.promise'),'Player adopts an in-flight queued task');
assert.ok(app.includes('releaseFinishedMedia()'),'Player releases already-played media');
console.log('PASS: all media types, bounded multi-song RAM, UI level, SoundFont change, eviction and in-flight promotion');
