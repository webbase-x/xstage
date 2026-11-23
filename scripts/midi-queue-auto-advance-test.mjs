import fs from 'node:fs';
import assert from 'node:assert/strict';

const app=fs.readFileSync(new URL('../app.js',import.meta.url),'utf8');
const start=app.indexOf('const nativePlayer=ui.player;');
const end=app.indexOf('const karaokeVideo =',start);
assert.ok(start>0&&end>start,'MIDI transport and engine bridge must exist');
assert.match(app,/player\.addEventListener\('ended',\(\)=>\{[\s\S]*?if\(state\.queue\.length\|\|state\.medley\)playNext\(\);/,
  'Natural song end must automatically promote the queued track');
assert.match(app,/function releaseFinishedMedia\(\)\{[\s\S]*?if\(midiTransport\.active\)midiTransport\.clear\(\)/,
  'Finished MIDI transport must be released even if no audio blob URL exists');

const events=new Map();
const original={
  src:'',volume:1,playbackRate:1,loop:false,paused:true,ended:false,
  currentTime:0,readyState:0,
  addEventListener(name,fn){
    if(!events.has(name))events.set(name,[]);
    events.get(name).push(fn);
  },
  removeEventListener(name,fn){
    events.set(name,(events.get(name)||[]).filter(x=>x!==fn));
  },
  dispatchEvent(event){for(const fn of [...(events.get(event.type)||[])])fn(event);return true;},
  pause(){this.paused=true;this.dispatchEvent(new Event('pause'));},
  play(){this.paused=false;this.dispatchEvent(new Event('play'));return Promise.resolve();},
  removeAttribute(name){if(name==='src')this.src='';},
  load(){}
};
let now=1000,tick=null,ended=0,queue=['song B','song C'];
const state={
  liveMidiPlayback:null,loading:false,userStopped:false,userPaused:false
};
const make=new Function('ui','state','performance','setInterval','clearInterval','Event','window',
  app.slice(start,end)+'\nreturn {player,midiTransport,attachProfessionalMidiEngine};');
const {player,midiTransport,attachProfessionalMidiEngine}=make(
  {player:original},state,{now:()=>now},fn=>(tick=fn,1),
  ()=>{tick=null;},Event,{}
);
const played=[];
player.addEventListener('ended',()=>{
  ended++;
  played.push(queue.shift()||'idle');
  midiTransport.clear();
});
function begin(remaining=30){
  midiTransport.begin(remaining);
  return player.play();
}
// An actual sequencer end callback should move precisely one queued song.
await begin();
let completed=null;
const prep={attach(_transport,{onEnded}){
  completed=onEnded;return {engine:'SpessaSynth',scheduler:'audio-worklet',
    finished:()=>false,dispose(){}};
}};
state.liveMidiPlayback=attachProfessionalMidiEngine(prep,{});
completed();
assert.deepEqual(played,['song B']);
assert.equal(ended,1);
assert.equal(midiTransport.active,false);
completed();
tick?.();
assert.equal(ended,1,'Duplicate worklet end must not skip another song');

// A fresh MIDI track reaches the next item even if worklet time is stale.
await begin();
const first=state.liveMidiPlayback;
state.liveMidiPlayback={scheduler:'audio-worklet',finished:()=>true,
  currentTime:()=>.1};
tick();
assert.equal(ended,2);
assert.deepEqual(played,['song B','song C']);
assert.equal(midiTransport.active,false);

// Pause and cancellation are not natural endings.
await begin();
const pending=attachProfessionalMidiEngine(prep,{});
state.liveMidiPlayback=pending;
state.userPaused=true;
completed();
assert.equal(ended,2,'Paused songs must not advance automatically');
state.userPaused=false;
player.pause();
completed();
assert.equal(ended,2,'Paused transport must ignore songEnded');
state.liveMidiPlayback={scheduler:'audio-worklet'};
await player.play();
completed();
assert.equal(ended,2,'Stale sequencer callback must not advance a new track');
console.log('PASS: MIDI natural end advances queue once, timer fallback, old engine cleanup, manual pause and stale-callback protection');
