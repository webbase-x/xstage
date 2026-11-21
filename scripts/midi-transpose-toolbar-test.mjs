import assert from 'node:assert/strict';
import fs from 'node:fs';

const read=path=>fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const html=read('karaoke.html'),css=read('xstage-ux.css'),app=read('app.js');
const header=html.split('<header class="mobile-stage-header stage-toolbar"')[1]?.split('</header>')[0]||'';
const status=html.split('<div class="transport-song-info">')[1]?.split('<div class="timeline">')[0]||'';
const transportRight=html.split('<div class="transport-right">')[1]?.split('<div class="transport-right-actions">')[0]||'';
assert.match(status,/<span class="transport-now-caption">สถานะเพลง<\/span>/);
assert.match(status,/<span id="toolbar-song-key"[^>]*>คีย์ —<\/span>/,
  'The musical key is plain text beside the current song');
assert.doesNotMatch(status,/id="midi-transpose-control"/,
  'Do not repeat transpose buttons in Song Status');
assert.doesNotMatch(header,/id="toolbar-song-key"/,
  'The song-key text stays beside the playing song');
assert.match(header,/<div id="midi-transpose-control"[^>]*hidden/,
  'Transpose controls start hidden in the upper toolbar');
for(const id of ['midi-key-down','midi-transpose-label','midi-key-up'])
  assert.ok(header.includes('id="'+id+'"'),id+' must belong to toolbar');
assert.ok(header.indexOf('class="stage-search-slot"')<
  header.indexOf('id="midi-transpose-control"')&&
  header.indexOf('id="midi-transpose-control"')<
  header.indexOf('id="mobile-stage-clock"'),
  'Search must be followed by transpose and then clock');
assert.ok(!transportRight.includes('midi-transpose-control'),
  'No duplicate transpose controls inside the volume/tempo panel');
assert.equal((html.match(/id="midi-key-up"/g)||[]).length,1);
assert.equal((html.match(/id="midi-key-down"/g)||[]).length,1);
assert.match(css,/#midi-transpose-control\[hidden\]\{\s*display:none!important/);
assert.match(css,/\.transport-song-info \.transport-song-detail\{/);
assert.match(css,/\.stage-toolbar #midi-transpose-control\{/,
  'The transpose buttons are laid out in the upper toolbar');
assert.match(css,/:has\(#midi-transpose-control\[hidden\]\)/,
  'Hidden MIDI controls return space to mobile search');
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
// Cached HTML may still contain the old status layout; the real DOM
// migration must move (not clone) the original controls, preserving clicks.
const stageUi=read('stage-ui.js');
assert.match(stageUi,/function migrateSongKeyToToolbar\(\)/);
assert.match(stageUi,/info\.insertBefore\(detail,info\.firstChild\)/);
assert.match(stageUi,/if\(stack\.parentNode!==detail\)detail\.append\(stack\)/);
assert.match(stageUi,/toolbar\.insertBefore\(transpose,clock\|\|null\)/);
assert.match(stageUi,/transpose\.classList\.remove\('speed-control'\)/);
console.log('PASS: plain Song Status key; search then live MIDI -/+ then clock; -12/+12 and cached DOM relocation');
