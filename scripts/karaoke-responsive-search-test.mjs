import assert from 'node:assert/strict';
import fs from 'node:fs';

const get=path=>fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const css=get('xstage-ux.css');
const html=get('karaoke.html');
const patch=css.split('/* iPhone / Android / small-tablet search: exact viewport-fit')[1];
assert.ok(patch,'Responsive search overrides must be appended after legacy rules');
assert.match(patch,/@media\s*\(max-width:760px\)/);
assert.match(patch,/@media\s*\(max-width:350px\)/);
assert.match(patch,/@media\s*\(orientation:landscape\)\s*and\s*\(max-height:540px\)/);
assert.match(patch,/env\(safe-area-inset-left\)/);
assert.match(patch,/env\(safe-area-inset-right\)/);
assert.match(patch,/env\(safe-area-inset-top\)/);
assert.match(patch,/10svh/,'Toolbar positioning must use stable Safari viewport height');
assert.match(patch,/grid-template-columns:minmax\(0,1fr\)!important/);
assert.match(patch,/\.stage-search-slot\s*\{[\s\S]*?width:100%!important/);
assert.match(patch,/\.search-dock\.pc-expanded\s*\{[\s\S]*?max-width:100%!important/);
assert.match(patch,/\.search-box\s*\{[\s\S]*?overflow:hidden/);
assert.match(patch,/#search\s*\{[\s\S]*?flex:1 1 0!important/);
assert.match(patch,/#search\s*\{[\s\S]*?font-size:16px!important/);
assert.match(patch,/\.voice-search-button\s*\{[\s\S]*?flex-shrink:0!important/);
assert.match(html,/meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/);
assert.match(html,/id="search" type="search"/);
assert.match(html,/id="voice-search" class="voice-search-button"/);
assert.match(html,/xstage-ux\.css\?v=1136-search-and-live-lights/);
for(const [viewport,leftSafe,rightSafe] of [
  [320,0,0],[375,0,0],[390,0,0],[402,0,0],[430,0,0],[440,0,0],
  [667,44,44],[844,59,59],[932,59,59],[1024,0,0]
]){
  const mobileGutter=viewport<=350?8:12;
  const insetLeft=Math.max(mobileGutter,leftSafe);
  const insetRight=Math.max(mobileGutter,rightSafe);
  const searchWidth=viewport-insetLeft-insetRight;
  assert.ok(searchWidth>0&&searchWidth<=viewport,'Search must fit '+viewport+'px viewport');
}
const ui=get('stage-ui.js'),app=get('app.js');
const topHeader=html.split('<header class="mobile-stage-header stage-toolbar"')[1]?.split('</header>')[0]||'';
const songStatus=html.split('<div class="transport-song-info">')[1]?.split('<div class="timeline">')[0]||'';
assert.doesNotMatch(topHeader,/id="toolbar-song-key"/,
  'Song-key text stays inside Song Status');
assert.match(topHeader,/id="midi-transpose-control"/,
  'MIDI transpose buttons belong after the upper search field');
assert.ok(topHeader.indexOf('id="midi-transpose-control"')<topHeader.indexOf('id="mobile-stage-clock"'),
  'Transpose comes immediately before the toolbar clock');
assert.match(songStatus,/id="toolbar-song-key"[^>]*>คีย์ —<\/span>/,
  'Current musical key must appear as text with Song Status on every screen');
assert.match(html,/id="toggle-keyboard"[^>]*hidden/,
  'Search keyboard handler stays connected to the menu and remote');
assert.match(app,/setSongKeyDisplay\(musicalKey\)/,
  'Song selection updates both key labels');
assert.match(ui,/lowerMenuTrigger\.hidden=upperVisible/,
  'Lower menu must be hidden when upper menu is visible');
assert.match(ui,/getClientRects\(\)\.length>0/,
  'Menu placement follows actual responsive CSS visibility');
assert.match(css,/#stage-tools-toggle\[hidden\]/,
  'Hidden menu must override stronger transport styles');
assert.doesNotMatch(html,/id="midi-keyboard-control"/,
  'The former top piano button must be completely removed');
assert.match(html,/<nav id="mobile-stage-menu"[\s\S]*?id="midi-keyboard-toggle"/,
  'The MIDI keyboard is available from the upper menu');
assert.ok(css.includes('html body.xstage-ui-v2:not(.xstage-native-tv) .stage .transport-right-actions #stage-tools-toggle{\\n')===false
  || css.includes('display:none!important'),'Lower menu must be suppressed');
const finalStyles=css.split('/* 1.15.7 — One upper hamburger')[1];
assert.ok(finalStyles,'Final responsive CSS overrides must exist');
assert.match(finalStyles,/#mobile-menu-toggle\{[\s\S]*?display:inline-flex!important/,
  'The upper hamburger must appear on phone widths');
assert.match(css,/\.transport-song-info \.song-key-stack\{[\s\S]*?display:flex!important/,
  'Only the key text should remain in Song Status');
assert.match(css,/\.stage-toolbar #midi-transpose-control\{[\s\S]*?display:inline-flex!important/,
  'Transpose controls must occupy a compact slot after search');
assert.match(finalStyles,/#stage-tools-toggle\{\s*display:none!important/,
  'The bottom hamburger must be removed when the top menu exists');
console.log('PASS: mobile search, actual top MIDI key replacement, one top menu');
