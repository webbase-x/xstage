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
const exportBackend=read('songstudio-plus/app.py');
const exportStyle=read('songstudio-plus/web/style.css');
// The outer section is a semantic container, not an element whose value changes.
assert.ok(source.includes('id="build-operation-progress"'),
  'missing visible export progress container');
for(const id of ['build-progress-percent','build-progress-count',
                 'build-progress-results','build-progress-fill','build-progress-track',
                 'build-progress-state','build-progress-current']){
  assert.ok(source.includes('id="'+id+'"'),'missing visible export progress element: '+id);
  assert.ok(js.includes('"'+id+'"'),'missing live update for '+id);
}
assert.ok(js.includes('100*done/total'),'export percent must use actual processed songs');
assert.ok(js.includes('job.kind==="build"')&&js.includes('||job.kind==="build")&&p.total>0'),
  'shared progress bar must use real build counters');
assert.ok(exportBackend.includes('progress(dict(total),f"เริ่มตรวจและสร้างไฟล์'),
  'build job must publish an initial 0/N progress sample');
assert.ok(exportStyle.includes('.build-operation-progress'),
  'export progress must have responsive styles');
const installer=read('songstudio-plus/installer/XStageSongStudioPro.iss');
assert.ok(workflow.includes('--name "XStageSongStudioPro"'),
 'PyInstaller must build the same stable application payload for every release');
assert.ok(workflow.includes('dist/XStageSongStudioPro/XStageSongStudioPro.exe'),
 'Windows build must verify the native desktop payload');
const installerVersion=installer.match(/#define MyAppVersion "([0-9]+[.][0-9]+[.][0-9]+)"/)?.[1];
assert.ok(installerVersion,'installer must declare semantic version');
const setupExe=`X-Stage-Song-Studio-Pro-v${installerVersion}-win-x64-Setup.exe`;
assert.ok(workflow.includes('path: songstudio-plus/installer/output/'+setupExe),
 'The published app must be an installer, not a portable EXE');
assert.ok(installer.includes('DefaultDirName={autopf}\\X-Stage\\Song Studio Pro'),
 '64-bit installer must place binaries in Program Files');
assert.ok(installer.includes('PrivilegesRequired=admin')&&
          installer.includes('ArchitecturesInstallIn64BitMode=x64'),
 'The installer must request Windows administrator permission');
assert.ok(installer.includes(String.raw`Source: "dist\XStageSongStudioPro\*"`) && installer.includes('recursesubdirs'),
 'The installer must bundle the complete onedir runtime');
assert.ok(workflow.includes('--onedir --windowed'), 'Windows executable must use onedir');
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
