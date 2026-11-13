import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const src=readFileSync(new URL('../device-runtime.js',import.meta.url),'utf8');
function make({agent='Mozilla/5.0',memory=8,cores=8,m4a=true,mp3=true,worklet=true}={}){
  const storage=new Map();
  const window={
    localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},
    navigator:{userAgent:agent,deviceMemory:memory,hardwareConcurrency:cores},
    document:{createElement:()=>({canPlayType:type=>type.includes('mp4')?m4a?'probably':'':type.includes('mpeg')?mp3?'maybe':'':''})},
    AudioWorkletNode:worklet?function(){}:undefined,AudioContext:worklet?function(){}:undefined,
    XStageMidiEngine:{ready:worklet}
  };
  const sandbox={window,WebAssembly};
  vm.runInNewContext(src,sandbox);
  return {api:window.XStageRuntime,storage};
}
const modern=make().api;
assert.equal(modern.chooseFormat({media:{midi:{fileId:'a'},m4a:{fileId:'b'}}}),'m4a');
assert.equal(modern.chooseFormat({media:{midi:{fileId:'a'}}}),'midi');
assert.equal(modern.setting().mode,'auto');
assert.equal(modern.setting().quality,'balanced');
assert.equal(modern.setting().soundFontCache,true);
assert.equal(modern.deviceInfo().conservative,false);
const low=make({agent:'Android',memory:2,cores:2,worklet:false});
assert.equal(low.api.deviceInfo().conservative,true);
assert.equal(low.api.deviceInfo().maxPreloadBytes,2*1024*1024);
assert.equal(low.api.chooseFormat({media:{midi:{fileId:'a'},m4a:{fileId:'b'}}}),'m4a');
assert.equal(low.api.chooseFormat({media:{midi:{fileId:'a'}}}),null);
const pref=make();
pref.storage.set('xstage-runtime-v2',JSON.stringify({mode:'midi'}));
assert.equal(pref.api.chooseFormat({media:{midi:{fileId:'a'},m4a:{fileId:'b'}}}),'midi');
assert.doesNotMatch(src,/indexedDB\.open\(.*song|localStorage\.setItem\(.*token/i);
console.log('Device selection and preload caps passed.');
