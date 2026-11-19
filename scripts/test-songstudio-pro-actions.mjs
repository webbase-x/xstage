import assert from 'node:assert/strict';
import fs from 'node:fs';
const root=new URL('../',import.meta.url);
const read=path=>fs.readFileSync(new URL(path,root),'utf8');
const html=read('songstudio-plus/web/index.html');
const js=read('songstudio-plus/web/app.js');
const timeline=read('songstudio-plus/web/timeline-ui.js');
const server=read('songstudio-plus/app.py');
const desktop=read('songstudio-plus/desktop_ui.py');
const picker=read('songstudio-plus/native_picker.py');
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
  '/api/pick','/api/open-folder','/api/import','/api/jobs',
  '/api/status','/api/recover-lyrics','/api/edit/apply',
  '/api/edit/undo','/api/preview','/api/attach-lrc',
  '/api/manual/save','/api/manual/approve','/api/manual/skip',
  '/api/build','/api/update/check','/api/update/install',
  '/api/swipe/scan','/api/swipe/open-source'
])assert.ok(server.includes('"'+route+'"'),'API route missing: '+route);
assert.ok(!server.includes('import tkinter as tk'),
 'Native Windows app must never open tkinter in the HTTP worker thread');
assert.ok(server.includes('self.state.native_picker('),
 'Picker must use GUI-thread bridge');
assert.ok(picker.includes('QFileDialog(self.parent_window)'),
 'Picker must be owned by the application window');
assert.ok(picker.includes('QFileDialog.Option.DontUseNativeDialog'),
 'Use embedded Qt picker to avoid hidden Windows native dialogs');
assert.ok(picker.includes('QFileDialog.FileMode.Directory'),
 'Folder picker mode missing');
assert.ok(picker.includes('QFileDialog.FileMode.ExistingFile'),
 'LRC file picker mode missing');
assert.ok(picker.includes('dialog.exec()'),
 'Picker must display a modal dialog');
assert.ok(picker.includes('Qt.ConnectionType.QueuedConnection'),
 'Picker must be dispatched to GUI thread');
assert.ok(desktop.includes('state.native_picker=picker.pick'));
const uiLoad=desktop.indexOf('window.web.load(QUrl(url))');
assert.ok(uiLoad>0,'Desktop UI must explicitly load localhost');
assert.ok(desktop.indexOf('state.native_picker=picker.pick') < uiLoad,
 'Folder picker must be registered before the web UI loads');
assert.ok(desktop.indexOf('worker.start()') < uiLoad,
 'Local PC Engine must start before QWebEngineView loads localhost');
assert.ok(!js.includes('state.ready=true;'), 'Do not fake engine state');
console.log('PASS: '+buttons.length+' visible action buttons, eight menus, 19 critical actions, APIs and GUI-thread pickers');
