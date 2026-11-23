import fs from 'node:fs';
import assert from 'node:assert/strict';

const app=fs.readFileSync(new URL('../app.js',import.meta.url),'utf8');
const start=app.indexOf('const nativePlayer=ui.player;');
const end=app.indexOf('const karaokeVideo =',start);
assert.ok(start>0&&end>start,'Live MIDI transport must exist in app.js');
const listeners=new Map();
const original={
  src:'',currentTime:0,duration:0,paused:true,ended:false,volume:1,
  playbackRate:1,loop:false,readyState:0,
  pause(){this.paused=true;this.dispatchEvent(new Event('pause'));},
  play(){this.paused=false;this.dispatchEvent(new Event('play'));return Promise.resolve();},
  removeAttribute(key){if(key==='src')this.src='';},
  load(){},
  addEventListener(type,fn){if(!listeners.has(type))listeners.set(type,[]);listeners.get(type).push(fn);},
  removeEventListener(type,fn){listeners.set(type,(listeners.get(type)||[]).filter(x=>x!==fn));},
  dispatchEvent(evt){for(const fn of listeners.get(evt.type)||[])fn(evt);return true;}
};
let now=1000,job=null,ended=0;
const state={liveMidiPlayback:null};
const run=new Function('ui','performance','setInterval','clearInterval','Event','state','window',
  app.slice(start,end)+'\nreturn {player,midiTransport};');
const {player,midiTransport}=run({player:original},{now:()=>now},
  fn=>{job=fn;return 1;},()=>{job=null;},Event,state,{});
player.addEventListener('ended',()=>{ended++;});
midiTransport.begin(120);
assert.equal(player.src,'midi:live');
await player.play();
now+=10000;
assert.equal(player.currentTime,10);
player.currentTime=30;
assert.equal(player.currentTime,30,'MIDI seeking uses its own clock');
player.playbackRate=2;
now+=5000;
assert.equal(player.currentTime,40,'MIDI tempo changes update the playback clock');
player.pause();
assert.equal(player.paused,true);
assert.equal(player.currentTime,40);
await player.play();
now+=40000;
job();
assert.equal(ended,1,'MIDI clock must end at song duration');
player.src='blob:next-track';
assert.equal(midiTransport.active,false,'Native audio tracks clear MIDI transport');
assert.equal(player.src,'blob:next-track');
// When the browser pauses UI timers, the audible audio sequencer remains
// authoritative. Wall time must not accidentally skip the song.
midiTransport.begin(120);
state.liveMidiPlayback={scheduler:'audio-worklet',currentTime:()=>15};
await player.play();now+=400000;
assert.equal(player.currentTime,15,'Audio-thread time must win over throttled tab wall time');
job();
assert.equal(player.ended,false,'Background timer throttling must not finish audible MIDI prematurely');
state.liveMidiPlayback.currentTime=()=>40;
assert.equal(player.currentTime,40,'Lyrics transport catches up with the audio sequencer');
player.pause();
assert.equal(player.currentTime,40);
// SpessaSynth may finish before its main-thread time reaches the duration.
// The authoritative worklet completion must still dispatch ended exactly once.
midiTransport.begin(120);
state.liveMidiPlayback={scheduler:'audio-worklet',
  currentTime:()=>119.7,finished:()=>false};
await player.play();
job();
assert.equal(ended,1,'A near-end but still-playing MIDI may not skip the queue');
state.liveMidiPlayback.finished=()=>true;
job();
assert.equal(ended,2,'SpessaSynth finished status must trigger an ended event');
assert.equal(player.ended,true);
assert.equal(midiTransport.finish(),false,'Repeated end notifications must be ignored');
assert.equal(ended,2,'A song cannot advance two queue entries');
console.log('PASS: MIDI clock, worklet natural end, once-only transition, seek and background time');
