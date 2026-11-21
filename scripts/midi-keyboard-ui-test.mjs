import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const read=p=>fs.readFileSync(new URL('../'+p,import.meta.url),'utf8');
const ui=read('midi-keyboard-ui.js'),html=read('karaoke.html'),
  app=read('app.js'),engine=read('midi-pro-engine.js'),pc=read('windows-pc/source/karaoke/keyboard_controls.py');
assert.ok(html.includes('id="midi-keyboard-panel"'),'The PC-style piano panel must exist');
assert.ok(html.includes('midi-piano-title">🎹 MIDI KEYBOARD</strong>')&&
  !html.includes('แบบ X-Stage Karaoke PC ·'),'The redundant keyboard subtitle is removed');
assert.ok(html.includes('id="midi-keyboard-toggle"')&&html.includes('aria-controls="midi-keyboard-panel"'),
  'The single menu must expose an accessible MIDI piano');
assert.ok(!html.includes('id="midi-keyboard-control"')&&!html.includes('id="midi-instrument-control"'),
  'No redundant instrument or MIDI keyboard button on the stage');
assert.ok(ui.includes('trigger.hidden=false')&&ui.includes('trigger.hidden=true'),
  'The piano is offered in the menu only when a MIDI song is loaded');
assert.ok(html.includes('midi-keyboard-ui.js?v='),'Piano module must be cache-busted');
const pcPrograms=[...pc.matchAll(/\('([^']+)',(\d+)\)/g)]
  .filter(m=>Number(m[2])<=127).map(m=>({name:m[1],program:Number(m[2])}));
assert.equal(pcPrograms.length,18,'Source PC keyboard exposes 18 instrument choices');
for(const {name,program} of pcPrograms)
  assert.ok(html.includes('<option value="'+program+'">'+name+'</option>'),
    'Online piano must preserve the PC GM instrument '+name);
assert.ok(app.includes('XStageMIDIPiano?.setSong({')&&
  app.includes('state.liveMidiPlayback?.previewNote?.('),
  'MIDI player must connect keyboard position and preview to the active synth');
assert.ok(engine.includes('const previewChannel=')&&
  engine.includes('previewNote')&&engine.includes('usedChannels'),
  'Audition notes must use a spare channel, not the song channel');

class Classes{
  constructor(){this.values=new Set();}
  add(value){this.values.add(value);}remove(value){this.values.delete(value);}
  toggle(value,on){if(on)this.values.add(value);else this.values.delete(value);}
  contains(value){return this.values.has(value);}
}
class El{
  constructor(id=''){
    this.id=id;this.children=[];this.listeners=new Map();this.attributes={};
    this.style={};this.dataset={};this.classList=new Classes();
    this.value='';this.textContent='';this.hidden=false;this.clientWidth=850;
    this.scrollLeft=0;this.selectedOptions=[{textContent:'ตามเพลง MIDI'}];
    this.tagName='DIV';this.disabled=false;this.className='';
  }
  append(...xs){this.children.push(...xs);}
  replaceChildren(...xs){this.children=xs;}
  addEventListener(key,fn){this.listeners.set(key,fn);}
  setAttribute(key,value){this.attributes[key]=value;}
  focus(){}
  contains(target){return target===this;}
  closest(){return this;}
  setPointerCapture(){}
  emit(type,event={}){this.listeners.get(type)?.(event);}
}
const ids=['midi-keyboard-panel','midi-keyboard-toggle','midi-keyboard-close',
  'midi-keyboard-range','midi-keyboard-channel','midi-instrument','midi-piano-keys',
  'midi-piano-scroll','midi-keyboard-notes','midi-piano-info',
  'midi-keyboard-oct-down','midi-keyboard-oct-up'];
const elements=Object.fromEntries(ids.map(id=>[id,new El(id)]));
elements['midi-keyboard-panel'].hidden=true;
elements['midi-keyboard-toggle'].hidden=true;
elements['midi-keyboard-range'].value='61';
elements['midi-keyboard-channel'].value='all';
const document={
  getElementById:id=>elements[id]||null,
  createDocumentFragment:()=>new El('fragment'),
  createElement:tag=>{const el=new El(tag);el.tagName=tag.toUpperCase();return el;}
};
const preview=[];
const browser={addEventListener(){},console:{warn(){}},
  XStageBrowserMidi:{parseMidi:()=>({notes:[
    {start:1,end:2,channel:0,key:60},
    {start:1.2,end:1.8,channel:1,key:64}
  ]})}};
let raf=0,clock=200;
vm.runInNewContext(ui,{
  window:browser,document,Uint8Array,ResizeObserver:undefined,
  performance:{now:()=>clock},
  requestAnimationFrame:()=>++raf,cancelAnimationFrame:()=>{}
},{filename:'midi-keyboard-ui.js'});
browser.XStageMIDIPiano.setSong({
  bytes:Uint8Array.of(1,2,3),
  getCurrentTime:()=>1.5,isPlaying:()=>true,
  previewNote:(note,on)=>{preview.push([note,on]);return true;}
});
assert.equal(elements['midi-keyboard-panel'].hidden,false,'Piano opens automatically for MIDI songs');
assert.equal(elements['midi-keyboard-toggle'].hidden,false,'MIDI button appears inside the top menu for MIDI tracks');
elements['midi-keyboard-toggle'].emit('click');
assert.equal(elements['midi-keyboard-panel'].hidden,true,'The menu action collapses the piano');
elements['midi-keyboard-toggle'].emit('click');
assert.equal(elements['midi-keyboard-panel'].hidden,false,'The menu action restores the piano');
assert.equal(elements['midi-keyboard-toggle'].attributes['aria-expanded'],'true');
const pianoKeys=()=>elements['midi-piano-keys'].children[0].children;
assert.equal(pianoKeys().length,61,'PC compact piano must show exactly 61 keys');
assert.equal(elements['midi-keyboard-notes'].textContent,'C4 E4');
elements['midi-keyboard-channel'].value='0';
elements['midi-keyboard-channel'].emit('change');
assert.equal(elements['midi-keyboard-notes'].textContent,'C4','MIDI channel filter must work');
elements['midi-keyboard-range'].value='128';
elements['midi-keyboard-range'].emit('change');
assert.equal(pianoKeys().length,128,'Full MIDI note range must show 128 keys');
assert.equal(elements['midi-keyboard-oct-up'].disabled,true,'128-note view cannot scroll an octave');
elements['midi-keyboard-range'].value='61';
elements['midi-keyboard-range'].emit('change');
elements['midi-keyboard-oct-up'].emit('click');
assert.equal(pianoKeys().length,61,'Octave navigation must retain 61-note view');
const c4=pianoKeys().find(key=>key.dataset.note==='60');
assert.ok(c4,'The piano must have MIDI C4');
elements['midi-piano-keys'].emit('pointerdown',{target:c4,pointerId:7,button:0});
elements['midi-piano-keys'].emit('pointerup',{pointerId:7});
assert.deepEqual(preview.slice(-2),[[60,true],[60,false]],
  'Touch notes must trigger SoundFont noteOn and noteOff');
elements['midi-instrument'].selectedOptions=[{textContent:'Nylon Guitar'}];
elements['midi-instrument'].emit('change');
assert.equal(elements['midi-instrument-label'],undefined,'Do not render a duplicate instrument label');
elements['midi-keyboard-close'].emit('click');
assert.equal(elements['midi-keyboard-panel'].hidden,true);
browser.XStageMIDIPiano.setSong({bytes:null});
assert.equal(elements['midi-keyboard-toggle'].hidden,true,'MIDI menu control hides for non-MIDI playback');
console.log('PASS: menu MIDI keyboard, no stage toolbar button, PC instrument parity, 61/128 keys, channels, note highlighting, preview and cleanup');
