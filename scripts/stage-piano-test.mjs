import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const read=path=>fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const page=read('index.html'),css=read('xstage-ux.css'),app=read('app.js');
for(const id of ['stage-piano','stage-piano-keys','stage-piano-channel',
  'stage-piano-close','stage-piano-state','toggle-piano','mobile-piano-toggle'])
  assert.ok(page.includes('id="'+id+'"'),'Missing stage piano UI: '+id);
assert.ok(page.includes('stage-piano.js?v='),'Piano must be bundled with Web/Android shared shell');
assert.ok(css.includes('.stage-piano[hidden]'),'Hidden piano must not overlap stage lyrics');
assert.ok(css.includes('.stage-piano-key.white.midi-active'));
assert.ok(css.includes('.stage-piano-key.black.midi-active'));
assert.ok(css.includes('body.xstage-native-tv .stage .stage-piano'),
  'Native TV stays in its display-only layout');
assert.ok(app.includes("new CustomEvent('xstage:midi-ready'"),
  'The actual MIDI player must send rendered note timing to the piano');
assert.ok(app.includes("new Event('xstage:piano-clear')"),
  'Song changes must clear the previous MIDI piano timeline');
assert.ok(app.includes('Math.max(keyboardHeight,pianoHeight)'),
  'Lyrics must reserve space above keyboard and piano overlays');

class ClassList {
  constructor(){this.classes=new Set();}
  toggle(name,force){
    if(force===undefined)force=!this.classes.has(name);
    if(force)this.classes.add(name);else this.classes.delete(name);
  }
  contains(name){return this.classes.has(name);}
}
class Element {
  constructor(name='div'){
    this.name=name;this.style={};this.dataset={};this.children=[];
    this.listeners=new Map();this.attributes=new Map();
    this.classList=new ClassList();this.hidden=false;this.value='-1';
    this.textContent='';this.scrollLeft=0;
  }
  append(...children){this.children.push(...children);}
  add(child){this.children.push(child);}
  replaceChildren(...items){this.children=items;}
  setAttribute(k,v){this.attributes.set(k,String(v));}
  getAttribute(k){return this.attributes.get(k);}
  addEventListener(type,cb){
    const listeners=this.listeners.get(type)||[];
    listeners.push(cb);this.listeners.set(type,listeners);
  }
  emit(type,extra={}){for(const cb of this.listeners.get(type)||[])cb({type,preventDefault(){},...extra});}
  setPointerCapture(){}
  click(){this.emit('click');}
}
const ids=new Map();
for(const id of ['stage-piano','stage-piano-keys','player','toggle-piano',
  'mobile-piano-toggle','stage-piano-close','stage-piano-state',
  'stage-piano-channel','virtual-keyboard','virtual-close'])
  ids.set(id,new Element(id));
ids.get('virtual-keyboard').hidden=true;
const listeners=new Map();
const context={Uint8Array,ArrayBuffer,Map,Set,Number,console,
  innerWidth:1200,requestAnimationFrame:()=>1,cancelAnimationFrame:()=>{},
  AudioContext:class{
    constructor(){this.state='running';this.currentTime=0;this.destination={};}
    createOscillator(){return {type:'sine',frequency:{value:0},connect(){},start(){},stop(){}};}
    createGain(){return {gain:{
      setValueAtTime(){},exponentialRampToValueAtTime(){},
      cancelScheduledValues(){},setTargetAtTime(){}
    },connect(){}};}
  },
  Event:class{constructor(type){this.type=type;}},
  Option:class{constructor(text,value){this.text=text;this.value=value;}},
  document:{
    hidden:false,
    getElementById:id=>ids.get(id)||null,
    createElement:tag=>new Element(tag),
    addEventListener(){}
  },
  addEventListener(type,cb){
    const items=listeners.get(type)||[];items.push(cb);listeners.set(type,items);
  },
  dispatchEvent(event){for(const fn of listeners.get(event.type)||[])fn(event);}
};
context.window=context;
vm.runInNewContext(read('stage-piano.js'),context,{filename:'stage-piano.js'});
const core=context.XStagePianoCore;
assert.ok(core);
assert.equal(core.label(60),'C4');
assert.equal(core.label(61),'C♯4');
const notes=[
  {start:0,end:1,key:60,channel:0},
  {start:.5,end:2,key:60,channel:1},
  {start:1,end:2,key:61,channel:0},
  {start:2,end:3,key:20,channel:0},
  {start:1,end:0,key:70,channel:0}
];
const events=core.timelineEvents(notes);
assert.equal(events.length,6);
assert.deepEqual(Array.from(core.activeKeysAt(events,.75)),[60]);
assert.deepEqual(Array.from(core.activeKeysAt(events,1.2)),[60,61]);
assert.deepEqual(Array.from(core.activeKeysAt(events,1.2,0)),[61]);
assert.deepEqual(Array.from(core.activeKeysAt(events,1.2,1)),[60]);
assert.deepEqual(Array.from(core.activeKeysAt(events,2.5)),[]);
assert.equal(ids.get('stage-piano-keys').children.length,49);
const piano=ids.get('stage-piano'),toggle=ids.get('toggle-piano');
assert.equal(piano.hidden,true,'Piano starts collapsed');
context.dispatchEvent({type:'xstage:midi-ready',detail:{notes}});
assert.equal(piano.hidden,false,'Desktop MIDI auto-shows on-stage piano');
assert.equal(toggle.getAttribute('aria-expanded'),'true');
const key60=ids.get('stage-piano-keys').children.find(x=>x.dataset.note==='60');
const key61=ids.get('stage-piano-keys').children.find(x=>x.dataset.note==='61');
ids.get('player').currentTime=.75;
ids.get('player').emit('seeked');
assert.ok(key60.classList.contains('midi-active'));
assert.ok(!key61.classList.contains('midi-active'));
ids.get('stage-piano-channel').value='1';
ids.get('stage-piano-channel').emit('change');
assert.ok(key60.classList.contains('midi-active'));
ids.get('player').currentTime=1.2;
ids.get('player').emit('seeked');
assert.ok(!key61.classList.contains('midi-active'),'Channel filter cannot leak another channel');
key61.emit('pointerdown',{button:0,pointerId:1});
assert.ok(key61.classList.contains('manual-active'),'Keyboard must synthesize on a user gesture');
key61.emit('pointerup',{pointerId:1});
assert.ok(!key61.classList.contains('manual-active'));
context.dispatchEvent({type:'xstage:piano-clear'});
assert.ok(!key60.classList.contains('midi-active'),'Changing song clears stale notes');
ids.get('stage-piano-close').click();
assert.equal(piano.hidden,true);
ids.get('mobile-piano-toggle').click();
assert.equal(piano.hidden,false,'Mobile menu can reopen the piano');
context.dispatchEvent({type:'xstage:piano-collapse'});
assert.equal(piano.hidden,true,'Search typing keyboard hides the piano');
console.log('PASS: Web stage piano layout, key sound gestures, MIDI timing, channel filtering, seeks and reset');
