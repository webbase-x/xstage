import assert from 'node:assert/strict';
import fs from 'node:fs';

const read=path=>fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const html=read('karaoke.html'),css=read('xstage-ux.css'),app=read('app.js');
const header=html.split('<header class="mobile-stage-header stage-toolbar"')[1]?.split('</header>')[0]||'';
const transport=html.split('<div class="transport-right">')[1]?.split('<div class="transport-right-actions">')[0]||'';
assert.match(header,/<output id="toolbar-song-key"/,'Song key stays in the upper toolbar');
assert.match(header,/<div id="midi-transpose-control"[^>]*hidden/,'Transpose controls start hidden');
assert.match(header,/<button type="button" id="midi-key-down"/);
assert.match(header,/<output id="midi-transpose-label"/);
assert.match(header,/<button type="button" id="midi-key-up"/);
assert.ok(header.indexOf('id="toolbar-song-key"')<header.indexOf('id="midi-transpose-control"'),
  'Minus, value, plus must appear immediately BELOW the song key');
assert.ok(!transport.includes('midi-transpose-control'),
  'The old bottom transpose control must be removed');
assert.ok(!header.includes('คีย์ MIDI'),'The redundant MIDI key heading must not appear');
assert.equal((html.match(/id="midi-key-up"/g)||[]).length,1);
assert.equal((html.match(/id="midi-key-down"/g)||[]).length,1);
assert.match(css,/#midi-transpose-control\[hidden\]\{\s*display:none!important/);
assert.match(css,/\.stage-toolbar:has\(#midi-transpose-control:not\(\[hidden\]\)\)/,
  'Compact toolbar must expand to fit both song key and transpose');
assert.match(css,/\.song-key-stack\{/,'Song key and buttons share one vertical group');

const start=app.indexOf("const midiKeyControl=$('midi-transpose-control')");
const end=app.indexOf("$('midi-instrument')?.addEventListener",start);
assert.ok(start>0&&end>start,'Find the actual production MIDI transpose handlers');
const snippet=app.slice(start,end);
const elems={
  'midi-transpose-control':{hidden:false},
  'midi-transpose':{value:'0'},
  'midi-transpose-label':{textContent:''},
  'midi-key-up':{disabled:false,listeners:[],addEventListener(_,fn){this.listeners.push(fn);}},
  'midi-key-down':{disabled:false,listeners:[],addEventListener(_,fn){this.listeners.push(fn);}}
};
const dollar=id=>elems[id]||null;
let sent=0,warnings=0;
const media={dispatchEvent(){sent++;if(sent===13)throw Error('synth temporarily reinitializing');}};
const simulator=new Function('$','nativePlayer','Event','console',
  snippet+'\nreturn {setMidiKey,syncMidiKeyButtons};')(
  dollar,media,class Event{constructor(type){this.type=type;}},{warn(){warnings++;}});
const click=id=>{
  const button=elems[id];
  if(button.disabled)return;
  for(const fn of button.listeners)fn({preventDefault(){},stopPropagation(){}});
};
for(let i=0;i<12;i++)click('midi-key-down');
assert.equal(elems['midi-transpose'].value,'-12');
assert.equal(elems['midi-transpose-label'].textContent,'-12');
assert.equal(elems['midi-key-down'].disabled,true);
assert.equal(elems['midi-key-up'].disabled,false,'PLUS must still work at minus twelve');
click('midi-key-up');
assert.equal(elems['midi-transpose'].value,'-11','PLUS reverses after minimum key');
assert.equal(warnings,1,'Synth exception must not lock the displayed key');
for(let i=0;i<23;i++)click('midi-key-up');
assert.equal(elems['midi-transpose'].value,'12');
assert.equal(elems['midi-transpose-label'].textContent,'+12');
assert.equal(elems['midi-key-up'].disabled,true);
assert.equal(elems['midi-key-down'].disabled,false,'MINUS must still work at plus twelve');
click('midi-key-down');
assert.equal(elems['midi-transpose'].value,'11');
elems['midi-transpose-control'].hidden=true;
click('midi-key-down');
assert.equal(elems['midi-transpose'].value,'11','Hidden control must not change key');
assert.ok(sent>=36,'Every successful transpose notifies the live engine');
console.log('PASS: transpose moved under song key; -12 to +12 reversible; synth errors isolated; mobile layout and duplicate controls verified');
