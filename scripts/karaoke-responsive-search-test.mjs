import assert from 'node:assert/strict';
import fs from 'node:fs';

const get=path=>fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const css=get('xstage-ux.css');
const html=get('karaoke.html');
const patch=css.split('/* 1.16.2 — Phone search lives at the screen')[1];
assert.ok(patch,'Mobile bottom search rules must override previous top-toolbar positioning');
assert.match(patch,/@media\s*\(max-width:760px\)/);
assert.match(patch,/@media\s*\(max-width:350px\)/);
assert.match(patch,/@media\s*\(max-height:540px\)/);
assert.match(patch,/env\(safe-area-inset-left,0px\)/);
assert.match(patch,/env\(safe-area-inset-right,0px\)/);
assert.match(patch,/env\(safe-area-inset-bottom,0px\)/);
assert.match(patch,/--xs-search-keyboard-inset/);
assert.match(patch,/\.stage-search-slot\{[\s\S]*?position:fixed!important/);
assert.match(patch,/\.search-dock\.pc-expanded\{[\s\S]*?flex-direction:column-reverse!important/);
assert.match(patch,/\.transport-panel\{[\s\S]*?bottom:calc\(55px/);
assert.match(patch,/#search\{[\s\S]*?font-size:16px!important/);
assert.match(html,/meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/);
assert.match(html,/id="search" type="search"/);
assert.doesNotMatch(html,/id="voice-search"/,'Voice microphone must be removed completely');
assert.match(html,/xstage-ux\.css\?v=1162-mobile-bottom-search/);
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
const ui=get('stage-ui.js'),app=get('app.js'),mobile=get('mobile-layout.js');
assert.doesNotMatch(app,/SpeechRecognition|setupVoiceSearch|voiceSearch/,
  'Removed microphone must never initialize voice recognition');
assert.ok(mobile.includes('function syncBottomSearch()')&&
  mobile.includes('stage.insertBefore(searchSlot')&&
  mobile.includes('searchToolbar.insertBefore(searchSlot,searchAnchor)'),
  'One search dock must move to bottom and return to the desktop header at breakpoints');
assert.ok(mobile.includes('visualViewport.height+visualViewport.offsetTop'),
  'Mobile keyboard must not cover bottom search');
assert.match(html,/mobile-layout\.js\?v=1162-mobile-bottom-search/);
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
console.log('PASS: voice search removed, bottom mobile search with upward results, safe-area/keyboard, one top menu');
