import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const read=path=>fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const html=read('karaoke.html');
const app=read('app.js');
const stage=read('stage-ui.js');
const bridgeCode=read('windows-volume-bridge.js');
const css=read('xstage-ux.css');

for(const id of ['windows-volume-connect','windows-volume-dialog','windows-volume-code',
  'windows-volume-pair','windows-volume-disconnect','windows-volume-close',
  'windows-volume-status','stage-volume-value']){
  assert.ok(html.includes('id="'+id+'"'),'Missing Windows volume control '+id);
}
assert.ok(html.includes('windows-volume-bridge.js?v='),'Bridge must be loaded on Karaoke Online');
assert.ok(html.includes('stage-ui.js?v=1164-bottom-menu'),'Wheel updates must bypass cached stage UI');
assert.ok(css.includes('.windows-volume-dialog')&&css.includes('.windows-volume-connect'));
assert.ok(stage.includes("volumeControl.addEventListener('wheel',adjustWheelVolume"),
  'Wheel over the volume slider must work even when slider is inside stage');
assert.ok(stage.includes("event.deltaMode===1")&&stage.includes('Math.trunc(wheelRemainder/100)'),
  'Wheel must accumulate precision-trackpad deltas rather than jump on every pixel');
assert.ok(stage.includes('bridge.toggleMute()'),'Paired speaker button must toggle Windows master mute');
assert.ok(app.includes('function karaokeOutputGain()')&&app.includes('player.volume=karaokeOutputGain()'),
  'Song changes must maintain unity browser audio when Windows owns master volume');
assert.ok(app.includes('bridge.setVolume(percent)'),
  'Remote and slider input must use the same Windows volume path');
assert.ok(!bridgeCode.includes('localStorage.')&&!bridgeCode.includes('sessionStorage.'),
  'Local Windows pairing bearer must remain only in page memory');
assert.ok(bridgeCode.includes("http://127.0.0.1:48731")&&!bridgeCode.includes('0.0.0.0'),
  'Bridge requests must target one local endpoint, never a LAN host');

const elementIds=['windows-volume-connect','windows-volume-dialog','windows-volume-code',
  'windows-volume-pair','windows-volume-disconnect','windows-volume-close',
  'windows-volume-status','volume','player'];
const dom=new Map(elementIds.map(id=>[id,{
  id,value:id==='volume'?'80':'',hidden:false,disabled:false,textContent:'',
  muted:false,volume:.8,open:false,listeners:{},classList:{toggle(){}},
  setAttribute(){},
  addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);},
  dispatchEvent(event){for(const fn of this.listeners[event.type]||[])fn(event);},
  showModal(){this.open=true;},close(){this.open=false;}
}]));
const slider=dom.get('volume'),media=dom.get('player');
const tickers=[],events=[],writes=[];
let osLevel=63,osMuted=false,pairedToken='';
const fakeFetch=async(url,options)=>{
  const path=String(url).replace('http://127.0.0.1:48731','');
  const response=(status,data)=>({ok:status>=200&&status<300,status,json:async()=>data});
  if(path==='/v1/pair'&&options.method==='POST'){
    assert.equal(JSON.parse(options.body).code,'1234567890');
    pairedToken='TEST_SESSION_TOKEN_12345678901234567890123456789';
    return response(200,{token:pairedToken,volume:osLevel,muted:osMuted});
  }
  assert.equal(options.headers.Authorization,'Bearer '+pairedToken);
  if(path==='/v1/volume'&&options.method==='GET')
    return response(200,{volume:osLevel,muted:osMuted});
  if(path==='/v1/volume'&&options.method==='PUT'){
    osLevel=JSON.parse(options.body).volume;osMuted=osLevel===0;
    writes.push(osLevel);return response(200,{volume:osLevel,muted:osMuted});
  }
  if(path==='/v1/mute'&&options.method==='PUT'){
    osMuted=JSON.parse(options.body).muted;
    return response(200,{volume:osLevel,muted:osMuted});
  }
  throw Error('Unexpected request '+path+' '+options.method);
};
class Event {constructor(type,init={}){this.type=type;this.bubbles=init.bubbles;}}
class CustomEvent extends Event {constructor(type,init={}){super(type,init);this.detail=init.detail;}}
const context={
  document:{getElementById:id=>dom.get(id)||null},
  Event,CustomEvent,console,AbortController,fetch:fakeFetch,
  setTimeout,clearTimeout,
  setInterval:fn=>{tickers.push(fn);return tickers.length;},clearInterval(){},
  addEventListener(){},dispatchEvent:e=>events.push(e)
};
context.window=context;
vm.runInNewContext(bridgeCode,context,{filename:'windows-volume-bridge.js'});
const bridge=context.XStageWindowsVolumeBridge;
assert.ok(bridge&&!bridge.connected);
slider.addEventListener('input',()=>{
  media.volume=bridge.connected?1:Number(slider.value)/100;
  if(bridge.connected&&!bridge.syncing)bridge.setVolume(Number(slider.value));
});
const emit=(id,type)=>{for(const fn of dom.get(id).listeners[type]||[])fn({type});};
const settle=()=>new Promise(resolve=>setTimeout(resolve,20));
emit('windows-volume-connect','click');
assert.equal(dom.get('windows-volume-dialog').open,true);
dom.get('windows-volume-code').value='1234567890';
emit('windows-volume-pair','click');
await settle();
assert.equal(bridge.connected,true);
assert.equal(Number(slider.value),63,'Pairing reads actual Windows master volume');
assert.equal(media.volume,1,'Browser output goes to unity gain; no double attenuation');
slider.value='68';slider.dispatchEvent(new Event('input'));
await settle();
assert.deepEqual(writes,[68],'One user slider change writes Windows endpoint once');
osLevel=32;
await tickers[0]();
await settle();
assert.equal(Number(slider.value),32,'External Windows volume change updates browser slider');
assert.equal(writes.length,1,'Polling must not create a feedback loop');
await bridge.toggleMute();
assert.equal(bridge.muted,true,'Mute button reports actual OS mute state');
await bridge.toggleMute();
assert.equal(bridge.muted,false);
bridge.disconnect();
assert.equal(bridge.connected,false);
assert.equal(media.volume,.32,'Disconnect restores independent browser volume');
assert.equal(osLevel,32,'Disconnect must not modify Windows master volume');
assert.ok(events.some(e=>e.type==='xstage:windows-volume'));
console.log('PASS: Windows pairing, true OS readback, one-way wheel/slider writes, mute, disconnect and browser gain');
