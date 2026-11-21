import fs from 'node:fs';
import assert from 'node:assert/strict';

// Extract the production transport + queue handoff functions unchanged.
// Verify that natural MIDI ended (without tapping Cancel) advances a queue
// entry, revokes the old player, and does not double consume songs.
const app=fs.readFileSync(new URL('../app.js',import.meta.url),'utf8');
const transportBegin=app.indexOf('const nativePlayer=ui.player;');
const transportEnd=app.indexOf('const karaokeVideo =',transportBegin);
const queueBegin=app.indexOf('function stopSoundFontFill(){');
const queueEnd=app.indexOf('// Release the finished media and lyrics, not merely the transport label.',queueBegin);
assert.ok(transportBegin>0&&transportEnd>transportBegin);
assert.ok(queueBegin>0&&queueEnd>queueBegin);
const songA={id:'song-A',title:'เพลงที่จบ',midi:{fileId:'old'}};
const songB={id:'song-B',title:'เพลงรอคิว',midi:{fileId:'next'}};
let oldDisposed=0,queueLoads=[],clearedUrls=[],relayHandoffs=[],clockJob=null;
const state={
  current:songA,queue:[songB],queuePreparedCache:new Map(),
  queuePreload:null,queuePreloadSkipped:new Set(),queuePrepared:null,
  medley:false,medleyCache:null,medleyUpcoming:null,medleyRecent:[],
  objectUrl:'',activeBlobBytes:42,activeVideoBytes:0,
  liveMidiSource:new Uint8Array([1]),
  liveMidiPlayback:{scheduler:'audio-worklet',currentTime:()=>1,
    finished:()=>false,dispose(){oldDisposed++;}},
  userStopped:false,loading:false
};
const listeners=new Map();
const native={
  src:'',paused:true,volume:1,playbackRate:1,loop:false,
  pause(){this.paused=true;this.dispatchEvent(new Event('pause'));},
  removeAttribute(name){if(name==='src')this.src='';},
  addEventListener(name,handler){
    const current=listeners.get(name)||[];current.push(handler);
    listeners.set(name,current);
  },
  removeEventListener(name,handler){
    listeners.set(name,(listeners.get(name)||[]).filter(fn=>fn!==handler));
  },
  dispatchEvent(event){
    for(const handler of listeners.get(event.type)||[])handler(event);
    return true;
  }
};
const run=new Function(
 'ui','state','performance','setInterval','clearInterval','Event','URL',
 'resetSongVideo','trimQueueCache','scheduleQueuePreload','getFileId','window',
 'renderQueue','nextMedleyCandidate','MEDLEY_RECENT_LIMIT','playSong','clearIdleStage',
 app.slice(transportBegin,transportEnd)+app.slice(queueBegin,queueEnd)+
 '\nreturn {player,midiTransport,playNext};'
);
const {player,midiTransport,playNext}=run(
 {player:native},state,{now:()=>1000},handler=>{clockJob=handler;return 1;},
 ()=>{clockJob=null;},Event,{revokeObjectURL:url=>clearedUrls.push(url)},
 ()=>{},()=>{},()=>{},input=>input?.fileId||'',
 {XStageIOSMidiAudio:{keepPlayingBetweenSongs(value){relayHandoffs.push(value);}}},
 ()=>{},()=>null,12,
 song=>queueLoads.push(song),
 message=>{throw Error('Unexpected idle stage: '+message);}
);
player.addEventListener('ended',()=>{
  if(state.queue.length) {
    // Same action as the application's registered ended listener.
    // playNext is an intentional closure in the extracted production code.
    playNext();
  }
});

midiTransport.begin(60);
await player.play();
state.liveMidiPlayback.finished=()=>true;
clockJob();
assert.deepEqual(queueLoads,[songB],
  'Natural end must immediately hand the next song to playSong');
assert.equal(state.queue.length,0,'Only the first queued song is consumed');
assert.equal(oldDisposed,1,'The old synth must be disposed before next track');
assert.equal(midiTransport.active,false,'The old virtual MIDI source must be cleared');
assert.equal(state.liveMidiSource,null);
assert.deepEqual(relayHandoffs,[true],
  'iPhone media audio focus must stay active between queued MIDI songs');
assert.equal(midiTransport.finish(),false,'Old MIDI must not emit an extra ended');
assert.deepEqual(queueLoads,[songB],'A double ended event must not skip another song');

console.log('PASS: natural MIDI song end hands queued song to playSong and clears audio');
