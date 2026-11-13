import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const src=readFileSync(new URL('../midi-stage-adapter.js',import.meta.url),'utf8');
const engineSrc=readFileSync(new URL('../midi-soundfont-engine.js',import.meta.url),'utf8');
const app=readFileSync(new URL('../app.js',import.meta.url),'utf8');
class FakeMedia{
  constructor(){this.src='blob:test';this.paused=false;this.duration=200;this.currentTime=11;this.loop=false;this.volume=1;}
  play(){this.paused=false;return Promise.resolve();}
  pause(){this.paused=true;}
  load(){this.loaded=true;}
  removeAttribute(s){if(s==='src')this.src='';}
  addEventListener(){}
}
const midi={active:false,paused:false,duration:120,currentTime:25,
  playbackRate:1,volume:.8,loop:false,
  play(){this.paused=false;return Promise.resolve();},
  pause(){this.paused=true;},stop(){this.active=false;}};
const audio=new FakeMedia();
const window={XStageMidiEngine:midi};
vm.runInNewContext(src,{window,Proxy,Reflect,Object});
const proxy=window.XStageCreatePlayerAdapter(audio);
assert.equal(proxy.src,'blob:test');
assert.equal(proxy.currentTime,11);
proxy.pause();assert.equal(audio.paused,true);
midi.active=true;
assert.equal(proxy.currentTime,25);
assert.equal(proxy.duration,120);
assert.equal(proxy.src,'midi://xstage-current');
proxy.currentTime=35;assert.equal(midi.currentTime,35);
proxy.playbackRate=1.25;assert.equal(midi.playbackRate,1.25);
proxy.volume=.4;assert.equal(midi.volume,.4);
proxy.pause();assert.equal(midi.paused,true);
await proxy.play();assert.equal(midi.paused,false);
proxy.removeAttribute('src');
assert.equal(midi.active,false);
assert.equal(audio.src,'');
assert.match(engineSrc,/soundBankManager\.addSoundBank/);
assert.match(engineSrc,/AudioWorklet/);
assert.match(engineSrc,/indexedDB\.open/);
assert.match(app,/async function playMidiSong/);
assert.match(app,/privateFile\(media\.fileId,token/);
assert.match(app,/window\.XStageMidiEngine\?\.stop\(\)/);
console.log('MIDI transport adapter and private Drive stage bridge contracts passed.');
