import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

// Exercise the *real* SpessaSynth adapter with a fake AudioWorklet sequencer.
// The old player got stuck because it never forwarded songEnded to the queue.
const source=fs.readFileSync(new URL('../midi-pro-engine.js',import.meta.url),'utf8')
  .replace("import('./'+MODULE)","Promise.resolve(contextModule)");
let calls=[],timer=null,completed=0,disposed=0;
class Param{constructor(){this.value=0;}}
class Node{constructor(){this.gain=new Param();
  for(const k of ['threshold','knee','ratio','attack','release'])this[k]=new Param();}
  connect(){}disconnect(){}
}
class AudioCtx{
  constructor(){this.destination={};this.state='running';
    this.audioWorklet={addModule:async()=>{}};}
  createGain(){return new Node();}
  createDynamicsCompressor(){return new Node();}
  resume(){return Promise.resolve();}
  close(){return Promise.resolve();}
}
class Synth{
  constructor(){this.isReady=Promise.resolve();
    this.soundBankManager={addSoundBank:async()=>{}};
    this.midiChannels=Array.from({length:16},()=>({setSystemParameter(){}}));}
  connect(){}stopAll(){}destroy(){disposed++;}
}
class Seq{
  constructor(){
    Seq.latest=this;this.currentTime=0;this.playbackRate=1;this.isFinished=false;
    this.handlers=new Map();this.loopCount=0;
    this.eventHandler={
      addEvent:(type,id,fn)=>this.handlers.set(type+':'+id,fn),
      removeEvent:(type,id)=>this.handlers.delete(type+':'+id)
    };
  }
  loadNewSongList(){
    queueMicrotask(()=>{
      for(const [id,callback] of this.handlers)
        if(id.startsWith('songChange:'))callback({midiData:{duration:60}});
    });
  }
  play(){calls.push('play');this.paused=false;}
  pause(){calls.push('pause');this.paused=true;}
  signalEnd(){
    this.isFinished=true;
    const cb=this.handlers.get('songEnded:xstage-midi-natural-finish');
    assert.equal(typeof cb,'function','SpessaSynth completion must be subscribed');
    cb();
  }
}
const scope={
  AudioContext:AudioCtx,AudioWorkletNode:class{},
  XStageBrowserMidi:{parseMidi:()=>({duration:60,notes:[{
    start:0,end:3,key:60,channel:0,bank:0,program:0,velocity:100,level:1
  }]})}
};
const context={
  window:scope,contextModule:{WorkletSynthesizer:Synth,Sequencer:Seq},
  Uint8Array,ArrayBuffer,DOMException,Number,Math,Promise,console,
  setTimeout,clearTimeout,queueMicrotask,
  fetch:async()=>({ok:true,headers:{get:()=>null},
    arrayBuffer:async()=>Uint8Array.of(1,2,3).buffer}),
  setInterval:fn=>{timer=fn;return 1;},
  clearInterval:()=>{timer=null;}
};
vm.runInNewContext(source,context,{filename:'midi-pro-engine.js'});
const midi=Uint8Array.from([77,84,104,100,...Array(16).fill(0)]);
const ready=await scope.XStageProMidi.prepare(midi,Uint8Array.of(1,2,3));
const listeners=new Map(),player={
  paused:false,ended:false,loop:false,currentTime:0,volume:1,playbackRate:1,
  addEventListener(type,fn){listeners.set(type,fn);},
  removeEventListener(type){listeners.delete(type);}
};
const engine=ready.attach(player,{onEnded:()=>{completed++;player.paused=true;}});
assert.equal(engine.scheduler,'audio-worklet');
assert.equal(engine.finished(),false);
Seq.latest.signalEnd();
await Promise.resolve();
assert.equal(completed,1,'Normal MIDI completion must forward exactly once');
assert.equal(engine.finished(),true,'Queued transport watchdog can also read native completion');
Seq.latest.signalEnd();
await Promise.resolve();
assert.equal(completed,1,'Duplicate completion signals must not skip two songs');
engine.dispose();
assert.equal(Seq.latest.handlers.size,0,'Song end listener must be removed');
assert.equal(listeners.size,0,'Player listeners must be released');
assert.equal(disposed,1,'Old MIDI engine must be disposed before next queue song');

// User initiated pause must never auto-skip to the next queued song.
const second=await scope.XStageProMidi.prepare(midi,Uint8Array.of(1,2,3));
player.paused=false;
const pausedEngine=second.attach(player,{onEnded:()=>{completed++;}});
player.paused=true;listeners.get('pause')();
Seq.latest.signalEnd();
await Promise.resolve();
assert.equal(completed,1,'Paused song must not advance the queue');
pausedEngine.dispose();

// Repeat mode restarts the same song instead of consuming queued songs.
const third=await scope.XStageProMidi.prepare(midi,Uint8Array.of(1,2,3));
player.paused=false;player.loop=true;
let seekTo=NaN;let current=8;
Object.defineProperty(player,'currentTime',{get:()=>current,set:value=>{
  current=value;seekTo=value;listeners.get('seeking')?.();
}});
const repeating=third.attach(player,{onEnded:()=>{completed++;}});
Seq.latest.signalEnd();
await Promise.resolve();
assert.equal(completed,1,'Repeat must not consume queued songs');
assert.equal(seekTo,0,'Repeat restarts the MIDI timeline');
repeating.dispose();
assert.equal(timer,null,'The short SoundFont edge-gap timer must stop when playback is disposed');
console.log('PASS: MIDI songEnded advances once, manual pause does not skip, repeat and engine disposal');
