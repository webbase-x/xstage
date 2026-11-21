/* Adaptive queued media cache: all formats, RAM guard, eviction, font reuse. */
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const app=fs.readFileSync(new URL('../app.js',import.meta.url),'utf8');
const memory=fs.readFileSync(new URL('../memory-budget.js',import.meta.url),'utf8');
const handlers=new Map(),timers=new Map();
let timerId=0,downloads=[],renders=0,preparedXsk=0;
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
  // Extracted queue functions run outside app.js's lexical closure here.
  // Supply its real app state explicitly; the production page defines it at startup.
  state,
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
    XStageXsk:{openPackage:async()=>{return {
      code:'004',document:{...lyrics,code:'004',title:'เพลง XSK',artist:'นักร้อง'},
      midi:new Blob(['MIDI'])}}},
  },
  privateFile:async(id)=>{downloads.push(id);return {blob:async()=>file,
    arrayBuffer:async()=>Uint8Array.of(1,2,3).buffer,
    headers:{get:()=>null},body:{cancel:async()=>{}}}},
  privateJson:async()=>lyrics,
  prepareXskPlayback:async(song,token)=>{preparedXsk++;return {song,token,blob:wav,lyrics};},
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
assert.equal(monitor.plan().queueLimit,1);
// Hard cap is universal, even when desktop reports abundant RAM.
for(const ram of [1,2,4,8,16]){
  sandbox.navigator.deviceMemory=ram;
  assert.equal(monitor.plan().queueLimit,1,'At most one NEXT song on '+ram+' GiB device');
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
assert.ok(downloads.includes('v1')&&downloads.includes('a1')&&downloads.includes('m1'),
  'ordinary queued audio/video/MIDI must use their source media');
assert.equal(preparedXsk,1,'XSK queue must delegate to verified XSK preparation');

 // Old catalogs may omit file size. A bounded stream still allows one next
 // track to be fully ready without fetching an unbounded private Drive file.
const originalPrivateFile=sandbox.privateFile;
let streamCanceled=0;
const unknown={...audio,code:'005',audio:{fileId:'unknown-audio'}};
const streamResponse=()=>({
  headers:{get:()=>null},
  body:{getReader(){
    let sent=false;
    return {
      async read(){
        if(sent)return {done:true};
        sent=true;return {done:false,value:Uint8Array.of(1,2,3,4)};
      },
      async cancel(){streamCanceled++;},
      releaseLock(){}
    };
  }}
});
sandbox.privateFile=async id=>id==='unknown-audio'?streamResponse():originalPrivateFile(id);
const unknownPrepared=await sandbox.prepareQueuedSong(unknown,'t',controller.signal);
assert.equal(unknownPrepared?.blob?.size,4,
  'Unknown-size private audio can be preloaded using a bounded stream');
const originalPlan=monitor.plan;
monitor.plan=(...args)=>({...originalPlan(...args),remaining:2});
const oversized=await sandbox.prepareQueuedSong(unknown,'t',controller.signal);
assert.equal(oversized,null,'Speculative stream exceeding the RAM cap is rejected');
assert.equal(streamCanceled,1,'Over-budget private media stream is canceled immediately');
monitor.plan=originalPlan;
sandbox.privateFile=originalPrivateFile;

assert.equal(renders,1,'MIDI queue renders once; mocked XSK has its own preparation path');
// Live MIDI must prefetch its actual MIDI data, NOT ignore the next queued
// song or allocate another SoundFont on the speculative path.
sandbox.window.XStageBrowserMidi.supportsRealtime=()=>true;
sandbox.window.XStageBrowserMidi.midiLyrics=()=>lyrics;
const beforeRender=renders;
const live=await sandbox.prepareQueuedSong(midi,'t',controller.signal);
assert.ok(live.liveMidi?.byteLength>0&&live.blob===null,
  'Queue preloads live MIDI bytes without creating a WAV');
assert.equal(live.lyrics,lyrics,'Queue preloads lyrics alongside MIDI');
assert.equal(renders,beforeRender,'Live MIDI prefetch must not offline-render audio');
assert.equal(live.liveFont,null,'Queue must not duplicate a large GM SoundFont');
assert.equal(sandbox.window.XStageMemory.plan({fontBytes:3*1048576,queuedBytes:100*1048576}).level,'high');
state.queuePreparedCache.set(audio,{song:audio,token:'t',blob:file,bytes:1024});
state.queuePreparedCache.set(video,{song:video,token:'t',blob:file,bytes:1024});
state.queuePreparedCache.set(midi,{song:midi,token:'t',blob:file,bytes:1024});
sandbox.trimQueueCache();
assert.ok(state.queuePreparedCache.size<=1,'Queue can keep only one prepared song on any device');
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
const realNative={XStageAndroid:{memorySnapshot:()=>JSON.stringify({
  total:2*1024*1024*1024,available:200*1024*1024,
  threshold:350*1024*1024,lowMemory:true})}};
const nativeCtx={navigator:{deviceMemory:2},performance:{memory:{usedJSHeapSize:100,
  jsHeapSizeLimit:1000}},...realNative};
nativeCtx.window=nativeCtx;
vm.runInNewContext(memory,nativeCtx);
const nativeBudget=nativeCtx.XStageMemory.plan();
assert.equal(nativeBudget.nativePressure,true,
  'Android low-memory signal must override browser deviceMemory hint');
assert.equal(nativeCtx.XStageMemory.canHold(1024,{}),false,
  'No speculative fetch while Android reports low-memory');
assert.equal(nativeBudget.level,'high');
assert.ok(app.includes('releaseFinishedMedia()'),'Player releases already-played media');
console.log('PASS: all media types, bounded multi-song RAM, UI level, SoundFont change, eviction and in-flight promotion');
