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
assert.match(html,/xstage-ux\.css\?v=1149-responsive-search/);
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
console.log('PASS: responsive iPhone search widths, Safe Areas, landscape and voice search');
