import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// The SpessaSynth built-in Sequencer must run without a main-thread
// setInterval note pump. Hidden-tab timers can be throttled or suspended.
const source=fs.readFileSync(new URL('../midi-pro-engine.js',import.meta.url),'utf8')
  .replace("import('./'+MODULE)","Promise.resolve(contextModule)");
const messages=[],workletModules=[];
let schedulerTimers=0,assetRequests=0;
class P{constructor(){this.value=0;}}
class Node{
  constructor(){
    this.gain=new P();
    for(const k of ['threshold','knee','ratio','attack','release'])this[k]=new P();
  }
  connect(){}disconnect(){}
}
class Context{
  constructor(){this.state='running';this.destination=new Node();
    this.audioWorklet={addModule:async path=>workletModules.push(path)};}
  createGain(){return new Node();}
  createDynamicsCompressor(){return new Node();}
  resume(){return Promise.resolve();}
  close(){return Promise.resolve();}
}
class Synth{
  constructor(){
    this.isReady=Promise.resolve();
    this.soundBankManager={addSoundBank:async()=>{}};
    this.midiChannels=Array.from({length:16},()=>({
      setSystemParameter:(name,value)=>messages.push(['channel',name,value])
    }));
  }
  connect(){}stopAll(){}destroy(){}
  programChange(ch,program){messages.push(['program',ch,program]);}
}
class Sequencer{
  constructor(){
    this.currentTime=0;this.playbackRate=1;this.loopCount=0;
    this.paused=true;Sequencer.instance=this;
    this.handlers=new Map();
    this.eventHandler={
      addEvent:(name,id,callback)=>this.handlers.set(name+':'+id,callback),
      removeEvent:(name,id)=>this.handlers.delete(name+':'+id)
    };
  }
  loadNewSongList(files){
    this.files=files;messages.push(['load']);
    // Real SpessaSynth parses the MIDI asynchronously in its AudioWorklet.
    queueMicrotask(()=>{
      for(const [id,cb] of this.handlers){
        if(id.startsWith('songChange:'))cb({midiData:{duration:180}});
      }
    });
  }
  play(){this.paused=false;messages.push(['play']);}
  pause(){this.paused=true;messages.push(['pause']);}
}
const visibility=new Map();
const page={
  hidden:false,
  addEventListener:(name,listener)=>visibility.set(name,listener),
  removeEventListener:(name)=>visibility.delete(name)
};
const scope={
  AudioContext:Context,AudioWorkletNode:class{},document:page,
  XStageBrowserMidi:{parseMidi:()=>({
    duration:180,notes:[{start:0,end:1,key:60,channel:0,bank:0,
      program:0,velocity:100,level:1}]
  })}
};
const sandbox={
  window:scope,contextModule:{WorkletSynthesizer:Synth,Sequencer},
  Uint8Array,ArrayBuffer,DOMException,console,Promise,Number,Math,
  setTimeout,clearTimeout,queueMicrotask,
  fetch:async ()=>{
    assetRequests++;
    return {ok:true,status:200,headers:{get:()=>null},
      arrayBuffer:async()=>new Uint8Array(1024).buffer};
  },
  setInterval:()=>{schedulerTimers++;return 1;},
  clearInterval:()=>{}
};
vm.runInNewContext(source,sandbox,{filename:'midi-pro-engine.js'});
const midi=new Uint8Array(32);midi.set([77,84,104,100],0); // MThd
const prepared=await scope.XStageProMidi.prepare(midi,Uint8Array.of(1,2,3));
assert.equal(Sequencer.instance.handlers.has('songChange:xstage-midi-initial-song-ready'),false,
  'The first-song readiness listener must be cleaned up after worklet notification');
const listeners=new Map();
const player={
  paused:false,ended:false,currentTime:0,volume:1,muted:false,
  playbackRate:1,
  addEventListener(name,listener){listeners.set(name,listener);},
  removeEventListener(name){listeners.delete(name);}
};
let shift=2,program=null;
const live=prepared.attach(player,{
  getTranspose:()=>shift,getProgram:()=>program
});
assert.equal(live.engine,'SpessaSynth');
assert.equal(live.scheduler,'audio-worklet');
assert.equal(schedulerTimers,0,'Audio-thread note sequencing must never use JS timers');
assert.equal(Sequencer.instance.paused,false);
assert.equal(Sequencer.instance.files.length,1);
assert.equal(Sequencer.instance.files[0].fileName,'X-Stage.mid');
assert.ok(messages.some(item=>item[0]==='channel'&&
  item[1]==='keyShift'&&item[2]===2));
assert.equal(messages.filter(item=>item[0]==='channel'&&
  item[1]==='keyShift').length,14,
  'Never transpose GM percussion or the isolated keyboard preview channel');

// Background page must not pause or stop note scheduling.
page.hidden=true;
visibility.get('visibilitychange')();
assert.equal(Sequencer.instance.paused,false,
  'Switching tabs must not pause the MIDI sequencer');
assert.equal(schedulerTimers,0);

// Restore UI clock from the audible audio sequencer.
Sequencer.instance.currentTime=42;
player.currentTime=40;
page.hidden=false;
visibility.get('visibilitychange')();
assert.equal(player.currentTime,42,'Returning tab should resync lyrics clock');

// User-initiated pause must remain paused after switching tabs.
player.paused=true;listeners.get('pause')();
assert.equal(Sequencer.instance.paused,true);
page.hidden=true;visibility.get('visibilitychange')();
page.hidden=false;visibility.get('visibilitychange')();
assert.equal(Sequencer.instance.paused,true);

// Explicit seek/tempo and transposition still work.
player.currentTime=70;listeners.get('seeking')();
assert.equal(Sequencer.instance.currentTime,70);
player.playbackRate=1.25;listeners.get('ratechange')();
assert.equal(Sequencer.instance.playbackRate,1.25);
shift=-3;listeners.get('xstage-midi-transpose')();
assert.ok(messages.some(item=>item[0]==='channel'&&
  item[1]==='keyShift'&&item[2]===-3));
live.dispose();
assert.equal(listeners.size,0);
assert.equal(visibility.size,0);
assert.equal(assetRequests,1);
console.log('PASS: background MIDI sequencer, UI resync, manual pause, tempo, key and disposal');
