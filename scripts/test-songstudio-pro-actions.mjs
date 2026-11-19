import assert from 'node:assert/strict';
import fs from 'node:fs';
const root=new URL('../',import.meta.url);
const read=path=>fs.readFileSync(new URL(path,root),'utf8');
const html=read('songstudio-plus/web/index.html');
const js=read('songstudio-plus/web/app.js');
const timeline=read('songstudio-plus/web/timeline-ui.js');
const server=read('songstudio-plus/app.py');
const desktop=read('songstudio-plus/desktop_ui.py');
const picker=read('songstudio-plus/windows_picker.py');
const sources=[js,timeline].join('\n');
const buttons=[...html.matchAll(/<button\b[^>]*\bid="([^"]+)"/g)].map(match=>match[1]);
assert.equal(buttons.length,new Set(buttons).size,'duplicate button id');
assert.ok(buttons.length>=79,'all menus should retain original interactive buttons');
const missing=buttons.filter(id=>!sources.includes('"'+id+'"'));
assert.deepEqual(missing,[],'all named controls must be referenced in the action code');
for(const page of ['import','lyrics','media','preview','manual','build','library','risks']){
  assert.ok(html.includes('data-view="'+page+'"'),'missing menu '+page);
}
for(const [name,call] of [
  ['source-browse','openPicker("folder","source-folder")'],
  ['lrc-browse','openPicker("lrc","media-lrc")'],
  ['source-open','openLocalFolder("source")'],
  ['diagnostic-open-log','/api/open-log'],
  ['workspace-open','openLocalFolder("workspace")'],
  ['pro-update-check','checkProUpdate()'],
  ['pro-update-install','beginProUpdate()'],
  ['import-start','startJob("import"'],
  ['recover-lyrics','startJob("recover"'],
  ['lyrics-apply','applyLyrics()'],
  ['lyrics-undo','undoLyrics()'],
  ['lyrics-cancel','/api/job/cancel'],
  ['media-attach','attachLrc()'],
  ['build-start','startJob("build"'],
  ['manual-save','manualSave()'],
  ['manual-skip','manualSkip()'],
  ['manual-approve','manualApprove()'],
  ['preview-play','playPreview()'],
  ['preview-pause','pausePreview()'],
  ['risk-scan','startJob("swipe-audit"']
]){
  assert.ok(js.includes('"'+name+'"'),'button is missing: '+name);
  assert.ok(js.includes(call),'button action is missing: '+name+' '+call);
}
for(const route of [
  '/api/pick','/api/open-folder','/api/open-log','/api/diagnostic','/api/import','/api/jobs',
  '/api/status','/api/recover-lyrics','/api/edit/apply',
  '/api/edit/undo','/api/preview','/api/attach-lrc',
  '/api/manual/save','/api/manual/approve','/api/manual/skip',
  '/api/build','/api/update/check','/api/update/install',
  '/api/swipe/scan','/api/swipe/open-source'
])assert.ok(server.includes('"'+route+'"'),'API route missing: '+route);
assert.ok(!server.includes('import tkinter as tk'),
 'Native Windows app must never open tkinter in the HTTP worker thread');
assert.ok(server.includes('self.state.native_picker('),
 'Picker API must call the registered Windows picker backend');
assert.ok(server.includes('import windows_picker'),
 'Windows picker backend must be registered by the local engine');
assert.ok(picker.includes('System.Windows.Forms.FolderBrowserDialog'),
 'Folder selection must use Windows Forms directly');
assert.ok(picker.includes('System.Windows.Forms.OpenFileDialog'),
 'LRC selection must use a Windows file dialog directly');
assert.ok(picker.includes('"powershell.exe","-NoProfile","-STA"'),
 'Windows picker must run PowerShell in STA mode');
assert.ok(desktop.includes('def run_browser_host('),
 'Windows browser host is required');
assert.ok(server.includes('run_browser_host(server,url'),
 'Default Windows UI must use the browser host');
assert.ok(desktop.includes('os.startfile(url)'),
 'Browser host must open localhost through the Windows shell');
assert.ok(desktop.indexOf('worker.start()') < desktop.indexOf('QTimer.singleShot(100,open_ui)'),
 'Local PC Engine must start before the Windows browser is opened');
assert.ok(server.includes('song-studio-pro.log')&&server.includes('def diagnostic('),
 'Persistent diagnostic log is required');
assert.ok(!js.includes('state.ready=true;'), 'Do not fake engine state');
console.log('PASS: '+buttons.length+' visible action buttons, eight menus, 19 critical actions, APIs, Windows picker, browser host and diagnostic log');
