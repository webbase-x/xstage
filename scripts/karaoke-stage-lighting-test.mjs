import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const read=p=>fs.readFileSync(new URL('../'+p,import.meta.url),'utf8');
const html=read('karaoke.html');
const app=read('app.js');
const css=read('xstage-ux.css');
const source=read('stage-lighting.js');
assert.match(html,/stage-lighting\.js\?v=1164-midi-eq-bars/,'Web shell loads live lighting');
assert.ok(html.indexOf('app.js?v=1164-mobile-lyrics')<html.indexOf('stage-lighting.js?v=1164-midi-eq-bars'),
  'Playback code must load before its lighting hookup');
assert.match(app,/setMidiNotes\?\.\(parsedLiveMidi\.notes,parsedLiveMidi\.duration\)/);
const topRules=css.split('/* 1.0.136 — search must remain the topmost')[1];
assert.ok(topRules,'The final, highest-priority search layer must exist');
assert.match(topRules,/z-index:210!important/);
assert.match(topRules,/z-index:220!important/);
assert.match(topRules,/safe-area-inset-top|--xs-top/);
assert.match(topRules,/xstage-stage-lights/);
assert.match(topRules,/pointer-events:none/);
assert.match(topRules,/karaoke-video:not\(\[hidden\]\)/);
class Element{
  constructor(){this.children=[];this.style={props:{},setProperty:(k,v)=>this.style.props[k]=v,
    getPropertyValue:k=>this.style.props[k]||''};this.className='';
    this.classList={classes:new Set(),add:v=>this.classList.classes.add(v),
      remove:v=>this.classList.classes.delete(v),contains:v=>this.classList.classes.has(v)};}
  append(child){this.children.push(child);}
  before(child){this.insertedBefore=child;}
  setAttribute(){}
}
const stage=new Element(),hero=new Element(),media=new Element(),video={hidden:true};
const meterBars=[];
const makeMeter=()=>({
  width:320,height:190,getBoundingClientRect:()=>({width:96,height:60}),
  getContext:()=>({
    clearRect(){},
    createLinearGradient:()=>({addColorStop(){}}),
    fillRect(_x,_y,_w,height){meterBars.push(height);}
  })
});
const meters=[makeMeter(),makeMeter()];
stage.classList.add('playing');
stage.querySelector=sel=>sel==='.stage-hero'?hero:null;
media.currentTime=0;media.listeners={};
media.addEventListener=(name,fn)=>{(media.listeners[name]??=[]).push(fn);};
media.emit=name=>(media.listeners[name]||[]).forEach(fn=>fn());
let count=0;const frames=new Map();
const context={
  document:{getElementById:id=>id==='stage'?stage:id==='player'?media:id==='karaoke-video'?video:id==='stage-viz-left'?meters[0]:id==='stage-viz-right'?meters[1]:null,
    createElement:()=>new Element(),addEventListener(){}},
  window:{matchMedia:()=>({matches:false}),addEventListener(){}},
  requestAnimationFrame:cb=>{frames.set(++count,cb);return count;},
  cancelAnimationFrame:id=>frames.delete(id),
  getComputedStyle:el=>({getPropertyValue:k=>el.style.getPropertyValue(k)}),
  player:media,Array,Number,Float32Array,Math,console
};
vm.runInNewContext(source,context,{filename:'stage-lighting.js'});
const lights=context.window.XStageStageLighting;
assert.equal(lights.status().beamCount,4);
assert.equal(hero.insertedBefore.className,'xstage-stage-lights',
  'Concert lights must sit below the logo, not over search or lyrics');
const paint=t=>{const arr=[...frames.entries()];frames.clear();for(const [,cb] of arr)cb(t);};
media.emit('play');
lights.setMidiNotes([{start:1,end:1.25,key:40,velocity:127,channel:9,
  channelVolume:127,channelExpression:127}],3);
media.currentTime=1.05;paint(100);
assert.ok(meterBars.some(height=>height>2),
  'Real MIDI drum notes must illuminate the existing EQ canvases beside the banner');
assert.ok(meterBars.length>=14,
  'Both stage EQ canvases must receive visible bar paint operations');
assert.equal(lights.status().source,'midi');
assert.ok(lights.status().energy>0,'MIDI hits must create real light energy');
const brightness=Number(hero.insertedBefore.children[0].style.opacity);
assert.ok(brightness>.3,'MIDI notes must illuminate the actual concert beams');
media.emit('pause');
assert.equal(lights.status().active,false,'Pausing music must stop the lights');
assert.equal(hero.insertedBefore.children[0].style.opacity,'0');
lights.clearMidiNotes();
stage.style.setProperty('--xstage-viz-energy','.7');
stage.style.setProperty('--xstage-viz-bass','.8');
media.emit('playing');paint(200);
assert.equal(lights.status().source,'audio');
assert.ok(lights.status().energy>.5,'Audio lights use existing true analyser levels');
media.emit('ended');
assert.equal(lights.status().active,false);
console.log('PASS: stage left/right EQ bars and concert beams follow MIDI notes and real audio; pause stops lights');
