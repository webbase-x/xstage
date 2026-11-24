import assert from 'node:assert/strict';
import fs from 'node:fs';

const get=path=>fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const css=get('xstage-ux.css');
const html=get('karaoke.html');
const patch=css.split('/* 1.16.2 — Phone search lives at the screen')[1];
assert.ok(patch,'Mobile bottom search rules must override previous top-toolbar positioning');
assert.match(patch,/@media\s*\(max-width:820px\)/);
assert.match(patch,/@media\s*\(max-width:350px\)/);
assert.match(patch,/\(max-height:540px\)/);
assert.match(patch,/env\(safe-area-inset-left,0px\)/);
assert.match(patch,/env\(safe-area-inset-right,0px\)/);
assert.match(patch,/env\(safe-area-inset-bottom,0px\)/);
assert.match(patch,/--xs-search-keyboard-inset/);
assert.match(patch,/bottom:max\(env\(safe-area-inset-bottom,0px\),var\(--xs-search-keyboard-inset,0px\)\)/);
assert.match(patch,/--xs-search-visual-height/);
assert.match(patch,/\.stage-search-slot\{[\s\S]*?position:fixed!important/);
assert.match(patch,/\.search-dock\.pc-expanded\{[\s\S]*?flex-direction:column-reverse!important/);
assert.match(patch,/\.transport-panel\{[\s\S]*?bottom:calc\(55px/);
assert.match(patch,/#search\{[\s\S]*?font-size:16px!important/);
assert.match(html,/meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/);
assert.match(html,/id="search" type="search"/);
assert.doesNotMatch(html,/id="voice-search"/,'Voice microphone must be removed completely');
assert.match(html,/xstage-ux\.css\?v=1164-mobile-controls-lights/);
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
assert.ok(mobile.includes('layoutHeight-visualHeight-visualTop')&&
  mobile.includes('--xs-search-visual-height')&&
  mobile.includes('(max-width:820px)'),
  'Mobile keyboard and tablet-size phones must keep the bottom search visible');
assert.match(html,/mobile-layout\.js\?v=/,'Mobile layout script must be cache-busted');
const topHeader=html.split('<header class="mobile-stage-header stage-toolbar"')[1]?.split('</header>')[0]||'';
const songStatus=html.split('<div class="transport-song-info">')[1]?.split('<div class="timeline">')[0]||'';
const mobileRules=css.split('/* 1.16.4 — One lower-right menu')[1];
assert.ok(mobileRules,'The final responsive rule must place the menu at bottom right');
assert.match(mobileRules,/\.stage \.stage-toolbar\{[\s\S]*?display:none!important/,
  'Mobile top toolbar and clock must be hidden');
assert.match(mobileRules,/#mobile-stage-clock\{[\s\S]*?display:none!important/,
  'Phone clock must not occupy a row');
assert.match(mobileRules,/#stage-tools-toggle:not\(\[hidden\]\)\{[\s\S]*?display:grid!important/,
  'Original lower menu must be visible after the queue button');
assert.match(mobileRules,/\.transport-right-actions\{[\s\S]*?flex-direction:row!important/,
  'Queue and hamburger must share the lower-right row');
assert.ok(html.indexOf('id="stage-queue-toggle"')<html.indexOf('id="stage-tools-toggle"'),
  'Bottom menu belongs after the queue button in tab and visual order');
assert.match(topHeader,/id="midi-transpose-control"/,
  'The original transpose is initially in the toolbar for desktop');
assert.match(mobile,/transportPanel\.insertBefore\(transpose,transportRow\)/,
  'Same transpose must move into the lower transport row on phones');
assert.match(mobile,/transposeToolbar\.insertBefore\(transpose,transposeAnchor\)/,
  'Desktop must restore the transpose without duplicate controls');
assert.match(mobile,/mainControls\.insertBefore\(nextButton,cancelButton\)/,
  'Next must move directly after Play and before Stop/Cancel');
assert.match(mobile,/nextAnchor\.parentNode\?\.insertBefore\(nextButton,nextAnchor\)/,
  'Desktop Next button order must be restored');
assert.match(mobileRules,/#play-pause\{order:1\}/);
assert.match(mobileRules,/#next\{order:2\}/);
assert.match(mobileRules,/#cancel-current\{order:3\}/);
assert.match(app,/transportTop-16\*density/,
  'Lyric drawing must reserve the true top of the bottom player');
assert.match(songStatus,/id="toolbar-song-key"[^>]*>คีย์ —<\/span>/,
  'Musical key label stays in Song Status, not duplicated');
assert.match(html,/id="toggle-keyboard"[^>]*hidden/,
  'Remote keyboard must remain available via its existing handler');
assert.ok(topHeader.indexOf('id="midi-transpose-control"')<topHeader.indexOf('id="mobile-stage-clock"'));
assert.match(html,/<nav id="mobile-stage-menu"[\s\S]*?id="midi-keyboard-toggle"/,
  'MIDI keyboard remains accessible in the menu');
assert.doesNotMatch(html,/id="midi-keyboard-control"/);
console.log('PASS: bottom phone search, bottom-right queue and menu, clock hidden, MIDI transpose and next beside play, lyrics clear');
