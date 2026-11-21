import assert from 'node:assert/strict';
import fs from 'node:fs';

const read=path=>fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const html=read('karaoke.html'),css=read('xstage-ux.css'),app=read('app.js');
const header=html.split('<header class="mobile-stage-header stage-toolbar"')[1]?.split('</header>')[0]||'';
const status=html.split('<div class="transport-song-info">')[1]?.split('<div class="timeline">')[0]||'';
const transportRight=html.split('<div class="transport-right">')[1]?.split('<div class="transport-right-actions">')[0]||'';
assert.doesNotMatch(header,/id="toolbar-song-key"|id="midi-transpose-control"/,
  'Song key and MIDI buttons must not occupy search toolbar');
assert.match(status,/<span class="transport-now-caption">สถานะเพลง<\/span>/);
assert.match(status,/<output id="toolbar-song-key"/,
  'Song key must appear in Song Status');
assert.match(status,/<div id="midi-transpose-control"[^>]*hidden/,
  'Transpose controls start hidden inside Song Status');
assert.match(status,/<button type="button" id="midi-key-down"/);
assert.match(status,/<output id="midi-transpose-label"/);
assert.match(status,/<button type="button" id="midi-key-up"/);
assert.ok(status.indexOf('id="toolbar-song-key"')<status.indexOf('id="midi-transpose-control"'),
  'Minus, value, plus stay below the Song Status key');
assert.ok(!transportRight.includes('midi-transpose-control'),
  'No duplicate key controls in volume/tempo area');
assert.ok(!status.includes('คีย์ MIDI'),'The redundant MIDI heading must be removed');
assert.equal((html.match(/id="midi-key-up"/g)||[]).length,1);
assert.equal((html.match(/id="midi-key-down"/g)||[]).length,1);
assert.match(css,/#midi-transpose-control\[hidden\]\{\s*display:none!important/);
assert.match(css,/\.transport-song-info \.transport-song-detail\{/,
  'Song Status title, artist and key share a compact flexible row');
assert.match(css,/\.transport-song-info \.song-key-stack\{/,
  'The vertical key and MIDI buttons are styled inside status');

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
// Earlier cached HTML may still have key controls in the top toolbar or
// volume controls below. The script must relocate the original DOM nodes.
const stageUi=read('stage-ui.js');
assert.match(stageUi,/function migrateSongKeyToStatus\(\)/);
assert.match(stageUi,/info\.insertBefore\(detail,info\.firstChild\)/);
assert.match(stageUi,/if\(stack\.parentNode!==detail\)detail\.append\(stack\)/);
assert.match(stageUi,/if\(transpose\.parentNode!==stack\)stack\.append\(transpose\)/);
assert.match(stageUi,/transpose\.classList\.remove\('speed-control'\)/);
console.log('PASS: song key moved into Song Status; MIDI -12/+12 remains reversible; cached toolbar DOM relocates');
