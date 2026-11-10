import fs from 'node:fs';
import assert from 'node:assert/strict';

const read=name=>fs.readFileSync(new URL('../'+name,import.meta.url),'utf8');
const app=read('app.js');
const pc=read('pc-extensions.js');
const host=read('stage-controls.js');
const remote=read('remote.js');
const index=read('index.html');
const css=read('xstage-ux.css');
const config=read('config.js');
const sw=read('sw.js');
const version=JSON.parse(read('version.json'));

for(const [name,source] of [['app.js',app],['pc-extensions.js',pc],['stage-controls.js',host],['remote.js',remote],['stage-ui.js',read('stage-ui.js')],['mobile-layout.js',read('mobile-layout.js')],['pwa-install.js',read('pwa-install.js')]]){
  assert.doesNotThrow(()=>new Function(source),name+' must parse');
}

const eqMatch=pc.match(/function eqFreqLabel\(f\)\{([\s\S]*?)\n\}/);
assert.ok(eqMatch,'eqFreqLabel must exist');
const eqFreqLabel=new Function('f',eqMatch[1]);
assert.equal(eqFreqLabel(1000),'1k');
assert.equal(eqFreqLabel(10000),'10k');
assert.equal(eqFreqLabel(12500),'12.5k');
assert.equal(eqFreqLabel(20000),'20k');

assert.match(app,/function playbackHasActiveIntent\(\)/);
assert.match(app,/if\(!playbackHasActiveIntent\(\)\)[\s\S]*playSong\(song\)[\s\S]*else\{[\s\S]*addToQueue\(song\)/);
assert.match(app,/libraryCacheOwner\(sub,rootId/);
assert.match(app,/xstage:librarychange/);
assert.match(app,/checkAppVersion/);
assert.match(app,/sharedLibraryFeatureReady/);

assert.ok(!host.includes("action==='stop'"),'host must not expose legacy stop action');
assert.ok(host.includes("action==='cancel-current'"),'host must cancel current song');
assert.ok(remote.includes("'cancel-current'"),'remote must request cancel-current');
assert.ok(!index.includes('cdnjs.cloudflare.com/ajax/libs/peerjs'),'main page must lazy-load PeerJS');
assert.ok(!index.includes('cdnjs.cloudflare.com/ajax/libs/qrcode'),'main page must lazy-load QRCode');
assert.ok(!index.includes('apis.google.com/js/api.js'),'main page must lazy-load Google Picker API');

assert.ok(index.includes('class="stage-brand-lockup"'),'professional stage brand lockup must exist');
assert.ok(!index.includes('class="stage-hero-name"'),'obsolete hero markup must stay removed');
assert.ok(css.includes('font-size:22px!important'),'desktop karaoke search text must stay large');
assert.ok(css.includes('font-size:20px!important'),'touch karaoke search text must stay large');

let braces=0;
for(const ch of css){if(ch==='{')braces++;else if(ch==='}')braces--;}
assert.equal(braces,0,'xstage-ux.css braces must balance');

assert.ok(sw.includes("xstage-shell-"),'service worker must use X-Stage cache namespace');
assert.ok(!sw.includes('ai-thai-browser'),'legacy service-worker cache name must stay removed');

const releaseMatch=config.match(/XSTAGE_RELEASE\s*=\s*\{\s*version:\s*'([^']+)',\s*build:\s*(\d+)\s*\}/);
assert.ok(releaseMatch,'config release metadata must exist');
assert.equal(version.version,releaseMatch[1],'version.json version must match config');
assert.equal(Number(version.build),Number(releaseMatch[2]),'version.json build must match config');

console.log('X-Stage regression checks passed');
