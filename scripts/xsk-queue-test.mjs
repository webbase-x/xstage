// Execute the actual XSK queue-loader functions from app.js in isolation.
// Tests bounded prefetch, on-demand fallback, metadata integrity and cleanup.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const app=fs.readFileSync(new URL('../app.js',import.meta.url),'utf8');
const begin=app.indexOf('async function prepareXskPlayback(');
const end=app.indexOf('function prefetchMedleyNext(){',begin);
assert.ok(begin>=0&&end>begin,'XSK just-in-time/queued functions exist');
const source=app.slice(begin,end);
let fetched=0,unzipped=0,rendered=0,painted=0,failed=false,onFontChange=null;
const file={fileId:'file-001',size:4096};
const song={code:'00001',title:'ทำได้เพียง',artist:'25 Hours',xsk:file};
const state={token:'token-001',queue:[song],queuePreload:null,queuePrepared:null,
  queuePreloadTimer:null,queuePreloadVersion:0,
  queuePreparedCache:new Map(),queuePreloadSkipped:new Set(),
  activeBlobBytes:0,activeVideoBytes:0,loading:false};
const packed=new Blob(['XSK2 fake']),audio=new Blob(['rendered wave']);
const mimeDoc={schemaVersion:1,songCode:'00001',title:'ทำได้เพียง',
  artist:'25 Hours',lines:[{startTime:1.0,text:'ทดสอบ'}]};
let timers=[];
const sandbox={
  state,navigator:{deviceMemory:4},document:{getElementById:()=>null},
  AbortController,DOMException,Uint8Array,Blob,
  console:{warn:()=>{failed=true}},setTimeout(fn){timers.push(fn);return timers.length;},
  clearTimeout(){},
  getStartupSoundFont:async()=>({bytes:null,pending:null}),
  getFileId:record=>record?.fileId||'',
  privateFile:async(id,token,{signal})=>{
    assert.equal(id,'file-001');assert.equal(token,'token-001');
    assert.equal(signal.aborted,false);fetched++;
    return {blob:async()=>packed};
  },
  privateJson:async()=>{throw Error('XSK must never retrieve a separate Lyrics JSON file')},
  renderQueue:()=>{painted++},
  window:{XStageMemory:{
    MiB:1048576,plan:()=>({heapPressure:false,remaining:100*1048576,
      queueLimit:2,budget:100*1048576,ratio:0,level:'low',hint:{gib:4}}),
    canHold:()=>true,statusText:()=>({level:'low',text:'ปกติ',note:''}),fmt:()=> '0 MB'
  },setInterval:()=>0,addEventListener:(event,callback)=>{
    if(event==='xstage:soundfont-change')onFontChange=callback;
  },XStageXsk:{openPackage:async blob=>{
    assert.equal(blob,packed);unzipped++;
    return {code:'00001',document:mimeDoc,midi:new Blob([Uint8Array.of(1,2,3)])};
  }},XStageBrowserMidi:{
    parseMidi:()=>({duration:45}),
    selectedFont:async()=>null,
    render:async(bytes,{signal})=>{
      rendered++;assert.deepEqual(Array.from(bytes),[1,2,3]);
      assert.equal(signal.aborted,false);
      return {audio};
    }
  }}
};
vm.runInNewContext(source,sandbox,{filename:'app-xsk-queue.js'});
const prefetch=sandbox.preloadFirstQueueSong;
const schedule=sandbox.scheduleQueuePreload;
assert.equal(typeof prefetch,'function');
await prefetch(song,'token-001');
assert.equal(fetched,1);assert.equal(unzipped,1);assert.equal(rendered,1);
assert.equal(state.queuePrepared.blob,audio);
assert.equal(state.queuePrepared.lyrics,mimeDoc);
assert.equal(painted,1);
const timersBefore=timers.length;
schedule();
assert.equal(timers.length,timersBefore,
  'Already prepared XSK must not be queued for reprocessing');
assert.equal(state.queuePreparedCache.get(song).blob,audio);
assert.equal(typeof onFontChange,'function');
onFontChange();
assert.equal(state.queuePrepared,null,
  'Changing SoundFont must invalidate already synthesized queued audio');

state.queue=[{...song,xsk:{...file,size:70*1024*1024}}];
await prefetch(state.queue[0],'token-001');
assert.equal(fetched,1,'Large XSK on memory-constrained APK stays on-demand');

state.queue=[song];
const wrong={...song,code:'99999'};
await assert.rejects(()=>sandbox.prepareXskPlayback(wrong,'token-001',
  new AbortController().signal),/DB/);
assert.equal(fetched,2);
assert.equal(rendered,1,'Reject mismatched catalog identity before audio rendering');

const prepared=await sandbox.prepareXskPlayback(song,'token-001',
  new AbortController().signal);
assert.equal(prepared.blob,audio);
assert.equal(rendered,2,'On-demand fallback can render one verified XSK');

assert.ok(app.includes('if(readyPrepared){'),
  'Actual player must reuse completed or in-flight queued XSK audio');
assert.ok(app.includes('prepareXskPlayback(song,token,controller.signal'),
  'Unprepared XSK must be playable directly on demand');
assert.ok(app.includes('state.queue.shift()')&&app.includes('scheduleQueuePreload();'),
  'Queue advances then prepares its new first song');
// Exercise the real playNext queue transition: the existing pre-render
// must be transferred to playback, not aborted by the new front's preload.
const nextBegin=app.indexOf('function playNext(){');
const nextEnd=app.indexOf('// Release the finished media and lyrics',nextBegin);
assert.ok(nextBegin>=0&&nextEnd>nextBegin);
const runner=new Function('state','scheduleQueuePreload','renderQueue',
  'playSong','clearIdleStage','nextMedleyCandidate','MEDLEY_RECENT_LIMIT','releaseFinishedMedia',
  app.slice(nextBegin,nextEnd)+'\nreturn playNext;');
const active={song,token:'token-001',promise:Promise.resolve({blob:audio,
  lyrics:mimeDoc,song,token:'token-001'}),controller:new AbortController()};
let accepted=null;
const transition=runner(state,()=>{},()=>{},(picked,opts)=>{
  accepted={picked,opts};
},()=>{},()=>null,10,()=>{});
state.queue=[song,{code:'00002',title:'ถัดไป'}];
state.queuePreload=active;state.queuePrepared=null;
transition();
assert.equal(state.queuePreload,null,'Pending pre-render must be detached from next queue');
assert.equal(accepted.picked,song);
assert.equal(accepted.opts.pending,active,'Playback must consume same in-flight Promise');
assert.equal(active.controller.signal.aborted,false,'Do not abort promoted XSK pre-render');
assert.equal(state.queue.length,1);

assert.ok(app.includes('song.midi||song.xsk'),
  'Medley must not accidentally fetch XSK as an ordinary audio file');

console.log('PASS: XSK queue-first pre-render, on-demand fallback, code/title/artist integrity, bounded memory and cleanup');
