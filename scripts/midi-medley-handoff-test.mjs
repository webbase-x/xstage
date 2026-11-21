/* Hot handoff between two MIDI songs uses one real SoundFont instance. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source=fs.readFileSync(new URL('../midi-pro-engine.js',import.meta.url),'utf8')
  .replace("import('./'+MODULE)","Promise.resolve(contextModule)");
let bankLoads=0,synths=0,destroyed=0,sequenceLoads=0,drums=0;
class Param{constructor(){this.value=0;}}
class Node{
  constructor(){
    for(const key of ['gain','threshold','knee','ratio','attack','release'])
      this[key]=new Param();
  }
  connect(){}disconnect(){}
}
class AudioContext{
  constructor(){
    this.state='running';this.destination=new Node();
    this.audioWorklet={addModule:async()=>{}};
  }
  createGain(){return new Node();}
  createDynamicsCompressor(){return new Node();}
  resume(){return Promise.resolve();}
  close(){return Promise.resolve();}
}
class Synth{
  constructor(){
    synths++;
    this.isReady=Promise.resolve();
    this.soundBankManager={addSoundBank:async()=>{bankLoads++;}};
    this.midiChannels=Array.from({length:16},()=>({setSystemParameter(){}}));
  }
  connect(){}stopAll(){}destroy(){destroyed++;}
  noteOn(channel){if(channel===9)drums++;}
  noteOff(){}controllerChange(){}programChange(){}
}
class Sequencer{
  constructor(){
    this.handlers=new Map();
    this.eventHandler={
      addEvent:(type,id,callback)=>this.handlers.set(type+':'+id,callback),
      removeEvent:(type,id)=>this.handlers.delete(type+':'+id)
    };
    this.currentTime=0;this.playbackRate=1;this.loopCount=0;this.paused=true;
    Sequencer.latest=this;
  }
  loadNewSongList(files){
    sequenceLoads++;this.files=files;this.isFinished=false;
    queueMicrotask(()=>{
      for(const [name,callback] of this.handlers)
        if(name.startsWith('songChange:'))callback({midiData:{duration:20}});
    });
  }
  play(){this.paused=false;}
  pause(){this.paused=true;}
}
const scope={
  AudioContext,AudioWorkletNode:class{},
  document:{hidden:false,addEventListener(){},removeEventListener(){}},
  addEventListener(){},removeEventListener(){},
  XStageBrowserMidi:{parseMidi:()=>({duration:20,tempoMap:[],
    notes:[{start:0,end:18,channel:0,key:60,bank:0,program:0,velocity:100}]})}
};
vm.runInNewContext(source,{
  window:scope,contextModule:{WorkletSynthesizer:Synth,Sequencer},
  fetch:async()=>({ok:true,headers:{get:()=>null},
    arrayBuffer:async()=>new Uint8Array(1024).buffer}),
  setTimeout,clearTimeout,setInterval,clearInterval,
  queueMicrotask,Uint8Array,ArrayBuffer,DOMException,Promise,console,Number,Math
},{filename:'midi-pro-engine.js'});
const midi=n=>Uint8Array.from([77,84,104,100,n,0,0,0]);
const bank=Uint8Array.of(1,2,3);
const ready=await scope.XStageProMidi.prepare(midi(1),bank);
const listeners=new Map();
const player={
  paused:false,ended:false,loop:false,currentTime:0,volume:1,muted:false,playbackRate:1,
  addEventListener(name,fn){listeners.set(name,fn);},
  removeEventListener(name){listeners.delete(name);}
};
const first=ready.attach(player,{});
assert.equal(first.scheduler,'audio-worklet');
const fill=first.beginTransitionFill();
assert.equal(typeof fill.prepareNextMidi,'function');
assert.ok(drums>0,'Actual GM drum notes bridge the end of the first song');
const sameEngine=await fill.prepareNextMidi(midi(2),bank);
assert.equal(sameEngine,ready,'Same prepared Worklet is handed to next song');
assert.equal(Sequencer.latest.handlers.has('songChange:xstage-midi-handoff-song-ready'),false,
  'Handoff listener must be released after song has loaded');
const second=sameEngine.attach(player,{});
fill.stop();
assert.equal(destroyed,0,'Stopping the old bridge must NOT destroy the new song synth');
assert.equal(bankLoads,1,'SoundFont must not be uploaded again');
assert.equal(synths,1,'A second huge AudioWorklet synth must not be allocated');
assert.equal(sequenceLoads,2,'Both MIDI songs must load into the same Sequencer');
assert.equal(second.scheduler,'audio-worklet');
second.dispose();
assert.equal(destroyed,1,'Shared engine closes after the new song is done');
assert.equal(listeners.size,0,'No listener leaks after handoff');
const another=await scope.XStageProMidi.prepare(midi(3),bank);
const third=another.attach(player,{});
const changedFont=third.beginTransitionFill();
assert.equal(await changedFont.prepareNextMidi(midi(4),Uint8Array.of(4,5)),null,
  'Changing banks must never reuse the wrong SoundFont');
changedFont.stop();
assert.equal(destroyed,2,'Untransferred old synth must be released normally');
console.log('PASS: MIDI medley reuses one SoundFont and Sequencer; bridge never destroys next track; switched bank is rejected');
