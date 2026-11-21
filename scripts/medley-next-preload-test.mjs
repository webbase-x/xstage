/* Medley preloads exactly ONE upcoming song, including live MIDI/XSK, and
 * gives explicit queue requests precedence over random shuffles.
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const app=fs.readFileSync(new URL('../app.js',import.meta.url),'utf8');
const begin=app.indexOf('function prefetchMedleyNext(){');
const end=app.indexOf('function renderQueue() {',begin);
assert.ok(begin>0&&end>begin,'Locate production medley prefetch and queue logic');
const current={code:'A',title:'เพลงกำลังเล่น'};
const next={code:'B',title:'MIDI ถัดไป',midi:{fileId:'m1',size:1024}};
const requested={code:'C',title:'เพลงที่ขอ'};
const lyrics={schemaVersion:1,lines:[{startTime:0,text:'♪'}]};
const prepared={song:next,token:'t',blob:null,
  liveMidi:Uint8Array.of(77,84,104,100),lyrics,bytes:4};
let downloads=0,memoryUpdates=0,queueRepaints=0,latestMessage='';
let resolvePending=null;
const state={
  medley:true,token:'t',queue:[],current,loading:false,
  userStopped:false,userPaused:false,medleyCache:null,
  medleyPrefetch:null,medleyUpcoming:next
};
const player={paused:false};
const sandbox={
  state,player,AbortController,Promise,console,
  nextMedleyCandidate:()=>next,
  prepareQueuedSong:async()=>{
    downloads++;
    return prepared;
  },
  updateMemoryIndicators:()=>{memoryUpdates++;},
  playable:()=>true,renderQueue:()=>{queueRepaints++;},
  scheduleQueuePreload:()=>{},
  setPlayStatus:msg=>{latestMessage=msg;}
};
vm.runInNewContext(app.slice(begin,end),sandbox,{filename:'medley-prefetch.js'});
sandbox.prefetchMedleyNext();
sandbox.prefetchMedleyNext();
assert.equal(downloads,1,'Only one next song should be fetched, never two');
await Promise.resolve();await Promise.resolve();
assert.equal(state.medleyCache?.song,next,'The next live MIDI must be ready in RAM');
assert.equal(state.medleyCache.liveMidi?.byteLength,4);
assert.equal(state.medleyCache.token,'t','A ready cache must be tied to the account');
assert.ok(memoryUpdates>0,'RAM indicator should report prepared medley media');
sandbox.medleyTick();await Promise.resolve();
assert.equal(downloads,1,'Time updates must not re-fetch a prepared song');
sandbox.addToQueue(requested);
assert.equal(state.queue[0],requested,'Manually requested queue takes priority');
assert.equal(state.medleyCache,null,'A requested song frees random medley RAM');
assert.equal(state.medleyPrefetch,null,'Stale randomized work is aborted');
assert.ok(queueRepaints>0&&latestMessage.includes('เพิ่มเข้าคิว'));
state.queue=[];state.medleyUpcoming=next;
let inFlight=null;
sandbox.prepareQueuedSong=()=>{
  downloads++;
  return new Promise(resolve=>{inFlight=resolve;});
};
sandbox.prefetchMedleyNext();
assert.ok(state.medleyPrefetch?.controller,
  'The next song can preload after queue is drained');
sandbox.addToQueue(requested);
assert.equal(state.medleyPrefetch,null,'A new request aborts an in-flight medley load');
inFlight(prepared);
await Promise.resolve();await Promise.resolve();
assert.equal(state.medleyCache,null,'An aborted request must not resurrect stale audio');
assert.equal(downloads,2,'Never exceed one speculative song at a time');
// A failed speculative request cannot be retried on every lyric/time tick.
state.queue=[];state.medleyUpcoming=next;state.medleyCache=null;
sandbox.prepareQueuedSong=async()=>{downloads++;return null;};
sandbox.prefetchMedleyNext();
await Promise.resolve();await Promise.resolve();
assert.ok(state.medleyPreloadRetryAt>Date.now(),
  'A failed/oversized medley track must have a bounded retry backoff');
const failedDownloads=downloads;
for(let i=0;i<50;i++)sandbox.medleyTick();
assert.equal(downloads,failedDownloads,
  'Playback ticks must not hammer Drive after a failed preload');
assert.ok(app.includes('pending:pendingQueued||pendingMedley'),
  'An in-flight medley download is promoted when its song is selected');
assert.ok(app.includes('handoff.prepareNextMidi('),
  'Next MIDI hands off through the already-loaded GM synthesizer');
console.log('PASS: early one-song medley MIDI prefetch, cache promotion, abort, queue priority and SoundFont reuse');
