import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const source=fs.readFileSync(new URL('../midi-pro-engine.js',import.meta.url),'utf8')
  .replace("import('./'+MODULE)","Promise.resolve(contextModule)");
assert.ok(source.includes('spessasynth_processor.min.js'),'Professional synth must load locally');
assert.ok(!source.includes('https://'),'Private MIDI playback must not fetch remote scripts');
let received=[],stops=0,destroyed=0,modules=[];
class Param{constructor(){this.value=0;}}
class FakeNode{constructor(){this.gain=new Param();this.threshold=new Param();
  this.knee=new Param();this.ratio=new Param();this.attack=new Param();this.release=new Param();}
  connect(){}disconnect(){}
}
class FakeAudioContext{
  constructor(){this.destination=new FakeNode();this.state='running';
    this.audioWorklet={addModule:async path=>{modules.push(path);}};}
  createGain(){return new FakeNode();}
  createDynamicsCompressor(){return new FakeNode();}
  resume(){return Promise.resolve();}
  close(){return Promise.resolve();}
}
class FakeSynth{
  constructor(){this.isReady=Promise.resolve();
    this.soundBankManager={addSoundBank:async(data,name)=>{
      assert.equal(name,'X-Stage GM');assert.equal(data.byteLength,3);
    }};}
  connect(){}
  controllerChange(channel,cc,value){received.push(['cc',channel,cc,value]);}
  programChange(channel,program){received.push(['program',channel,program]);}
  noteOn(channel,key,velocity){received.push(['on',channel,key,velocity]);}
  noteOff(channel,key){received.push(['off',channel,key]);}
  stopAll(){stops++;}
  destroy(){destroyed++;}
}
let interval=null,disposed=false;
const scope={AudioContext:FakeAudioContext,AudioWorkletNode:class {},
  XStageBrowserMidi:{parseMidi:()=>({duration:1.5,notes:[{
    start:0,end:.5,key:60,channel:0,bank:0,program:0,velocity:100,level:1
  }]})}};
const sandbox={window:scope,contextModule:{WorkletSynthesizer:FakeSynth},Uint8Array,
  ArrayBuffer,DOMException,Number,Math,Promise,console,setInterval:fn=>(interval=fn,1),
  clearInterval:()=>{interval=null;}};
vm.runInNewContext(source,sandbox,{filename:'midi-pro-engine.js'});
assert.equal(scope.XStageProMidi.available(),true);
const ready=await scope.XStageProMidi.prepare(new Uint8Array([0]),
  new Uint8Array([1,2,3]));
assert.ok(modules[0].includes('spessasynth_processor.min.js'));
const listeners=new Map(),player={currentTime:0,paused:false,ended:false,muted:false,
  volume:1,playbackRate:1,addEventListener(k,fn){listeners.set(k,fn);},
  removeEventListener(k){listeners.delete(k);}};
const active=ready.attach(player,{getTranspose:()=>12,getProgram:()=>24});
assert.equal(active.engine,'SpessaSynth');
assert.ok(received.some(x=>x[0]==='on'&&x[2]===72));
assert.ok(received.some(x=>x[0]==='program'&&x[2]===24));
player.currentTime=.5;interval();
assert.ok(received.some(x=>x[0]==='off'));
active.dispose();
assert.equal(destroyed,1);
assert.ok(stops>=1);
assert.equal(listeners.size,0);
assert.equal(interval,null);
console.log('PASS: self-hosted professional MIDI AudioWorklet, bank, note schedule, key/program and disposal');
