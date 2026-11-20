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
const run=new Function('ui','performance','setInterval','clearInterval','Event',
  app.slice(start,end)+'\nreturn {player,midiTransport};');
const {player,midiTransport}=run({player:original},{now:()=>now},
  fn=>{job=fn;return 1;},()=>{job=null;},Event);
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
console.log('PASS: MIDI live clock, seek, tempo, pause, end and audio handoff');
