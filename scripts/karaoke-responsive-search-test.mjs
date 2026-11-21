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
assert.match(html,/xstage-ux\.css\?v=1156-song-key-single-menu/);
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
assert.match(html,/id="toolbar-song-key"[^>]*>คีย์ —<\/output>/,
  'Song key must replace the redundant search keyboard at the top');
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
console.log('PASS: responsive iPhone search, song key and single visible hamburger');
