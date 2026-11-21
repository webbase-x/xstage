/* Verify the actual MIDI silent-tail cue and prepared successor handoff. */
import fs from 'node:fs';
import assert from 'node:assert/strict';
const app=fs.readFileSync(new URL('../app.js',import.meta.url),'utf8');
const start=app.indexOf('function midiTailHandoffCue(');
const end=app.indexOf('const nativePlayer=ui.player;',start);
assert.ok(start>0&&end>start,'MIDI cue function exists');
const cue=new Function(app.slice(start,end)+'\nreturn midiTailHandoffCue;')();
const notes=[{start:0,end:24,key:60}];
assert.equal(cue({duration:30,notes},{lines:[{startTime:19,endTime:23}]}),25,
  'A verified five-second MIDI silent tail can transition after its one-second ring-out');
assert.equal(cue({duration:30,notes},{lines:[{startTime:19,endTime:27}]}),28,
  'A later timed lyric must never be truncated');
assert.equal(cue({duration:30,notes:[{end:28}]},{lines:[]}),0,
  'A normal tail is not shortened');
assert.equal(cue({duration:30,notes:[]},{lines:[]}),0,
  'Missing note evidence must not invent a silence cue');
assert.equal(cue({duration:5,notes},{lines:[]}),0,
  'Very short sound effects do not auto-trim');
const transportSrc=app.slice(end,app.indexOf('const karaokeVideo =',end));
const create=new Function('ui','state','performance','setInterval','clearInterval','Event',
  transportSrc+'\nreturn {midiTransport,player};');
function session({ready=false,medley=false}={}){
  let clock=0,ended=0,interval=null;
  const events=new Map();
  const native={
    src:'',paused:true,volume:1,playbackRate:1,loop:false,
    pause(){this.paused=true;},
    removeAttribute(name){if(name==='src')this.src='';},
    addEventListener(name,fn){
      const list=events.get(name)||[];list.push(fn);events.set(name,list);
    },
    removeEventListener(name,fn){events.set(name,(events.get(name)||[]).filter(x=>x!==fn));},
    dispatchEvent(event){for(const fn of events.get(event.type)||[])fn(event);return true;}
  };
  const next={code:'B'};
  const state={queue:medley?[]:[next],medley,
    medleyUpcoming:next,medleyCache:ready?{song:next}:null,
    queuePreparedCache:new Map(ready?[[next,{song:next}]]:[])};
  const {midiTransport,player}=create({player:native},state,
    {now:()=>clock},fn=>{interval=fn;return 1;},()=>{interval=null;},Event);
  native.addEventListener('ended',()=>ended++);
  return {midiTransport,player,state,
    advance(ms){clock=ms;interval?.();},
    ended:()=>ended};
}
const queued=session({ready:true});
queued.midiTransport.begin(30,25);
await queued.player.play();
queued.advance(24900);
assert.equal(queued.ended(),0,'No early end during audible material');
queued.advance(25200);
assert.equal(queued.ended(),1,'Ready queue track advances at silent-tail cue');
queued.advance(30000);
assert.equal(queued.ended(),1,'A MIDI end may be delivered only once');
const waiting=session({ready:false});
waiting.midiTransport.begin(30,25);
await waiting.player.play();
waiting.advance(25500);
assert.equal(waiting.ended(),0,'An unprepared successor cannot clip the outgoing track');
waiting.advance(30000);
assert.equal(waiting.ended(),1,'The natural end still occurs without preload');
const shuffle=session({ready:true,medley:true});
shuffle.midiTransport.begin(30,25);
await shuffle.player.play();
shuffle.advance(26000);
assert.equal(shuffle.ended(),1,'A preloaded medley track also transitions at the cue');
const repeat=session({ready:true});
repeat.midiTransport.begin(30,25);
repeat.player.loop=true;
await repeat.player.play();
repeat.advance(26000);
assert.equal(repeat.ended(),0,'Repeat mode must never trigger the next song');
assert.ok(app.includes('setTimeout(()=>{void preloadFirstQueueSong(next,state.token);},0)'),
  'The next requested song starts downloading without a speculative delay');
assert.ok(app.includes('reader.cancel()'),'A large Drive stream is cancelled at the RAM limit');
console.log('PASS: prepared queue/medley, verified silent MIDI tail, no premature end, loop safety, bounded stream');
