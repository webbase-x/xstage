import assert from 'node:assert/strict';
import fs from 'node:fs';

const read=p=>fs.readFileSync(new URL('../'+p,import.meta.url),'utf8');
const html=read('index.html');
const app=read('storefront.js');
const device=read('storefront-device.js');
const workflow=read('.github/workflows/test-songstudio-pro.yml');
const source=read('songstudio-plus/web/index.html');
const js=read('songstudio-plus/web/app.js');
const data=JSON.parse(read('downloads/song-studio-pro-latest.json'));
assert.equal(data.name,'X-Stage Song Studio Pro');
assert.match(data.version,/^\d+\.\d+\.\d+$/,'public feed must have a valid version');
if(data.available){
  assert.match(data.sha256,/^[a-f0-9]{64}$/i,'published EXE requires SHA-256');
  assert.ok(data.download_url.startsWith(
    'https://github.com/webbase-x/xstage/releases/download/song-studio-pro-v'),
    'published EXE must come from the verified Pro GitHub release');
  assert.ok(data.download_url.endsWith('.exe'),'Windows Pro release must be an EXE');
}else{
  assert.ok(!data.download_url,'unavailable Pro release cannot advertise a download');
}
assert.equal((html.match(/data-app="studio-pro"/g)||[]).length,1,'Pro must be the sole Song Studio app card');
for(const name of ['studio-pc','studio-plus','studio-web']){
  assert.ok(!html.includes('data-app="'+name+'"'),'Legacy studio card still visible: '+name);
  assert.ok(!app.includes('"'+name+'":{'),'Legacy studio app definition: '+name);
  assert.ok(!device.includes('"'+name+'":{'),'Legacy device catalog entry: '+name);
}
assert.ok(app.includes('["studio-pc","studio-web","studio-plus"].includes(requested)'),
 'Old app detail links must map to the unified Pro page');
assert.ok(app.includes('downloads/song-studio-pro-latest.json'),'Storefront must fetch Pro metadata');
assert.ok(html.includes('X-Stage Song Studio Pro'),'Pro card must use the new brand');
assert.ok(source.includes('X-Stage Song Studio Pro'),'Desktop web shell brand must match');
assert.ok(js.includes('manual-cue-token')&&js.includes('manual-advanced-times')&&
 js.includes('manualCueUndo'),'New cue editor must be connected');
const proExeMatch=workflow.match(/--name "(X-Stage-Song-Studio-Pro-v[0-9]+[.][0-9]+[.][0-9]+-preview)"/);
assert.ok(proExeMatch,'Windows Preview must build only the Pro EXE');
const proExe=proExeMatch[1]+'.exe';
assert.ok(workflow.includes('dist/'+proExe),
 'Windows Preview must verify the same Pro EXE that it builds');
assert.ok(workflow.includes('path: dist/'+proExe),
 'Windows Preview must upload only the same Pro EXE as its artifact');
assert.ok(!/--name "(?!X-Stage-Song-Studio-Pro-)[^"]+"/.test(workflow),
 'Windows Preview must not build another Studio executable');
assert.ok(!fs.existsSync(new URL('../songstudio-pc',import.meta.url)),
 'Retired native PC source must not be present on current branch');
assert.ok(!fs.existsSync(new URL('../studio',import.meta.url)),
 'Retired standalone Studio Web source must not remain');
for(const feed of ['song-studio-latest.json','song-studio-plus-latest.json',
                   'song-studio-source-preview-latest.json']){
 assert.ok(!fs.existsSync(new URL('../downloads/'+feed,import.meta.url)),
  'Retired public release feed must be removed: '+feed);
}
console.log('PASS: one Pro app, retired Studio entry points removed, backward links mapped, Pro Windows build contract');
