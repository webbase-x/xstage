import fs from 'node:fs';
import assert from 'node:assert/strict';

const read=name=>fs.readFileSync(new URL('../'+name,import.meta.url),'utf8');
const html=read('karaoke.html');
const settings=read('cloud-drive-folders.js');
const app=read('app.js');
const soundfont=read('browser-midi.js');
const fx=read('pc-extensions.js');
const importer=read('cloud-import.js');

for(const id of ['xstage-drive-folder-music','xstage-drive-folder-soundfont',
  'xstage-drive-folder-fx','xstage-drive-build-db','xstage-drive-cancel-db',
  'cloud-import-upload-only'])
  assert.ok(html.includes('id="'+id+'"'),'Missing media source control: '+id);
assert.ok(html.includes('cloud-drive-folders.js?v=')&&
  html.includes('pc-extensions.js?v=1206-scoped-fx')&&
  html.includes('browser-midi.js?v=1206-scoped-soundfont'),
  'Page must load updated Drive folder, SoundFont and FX implementations');
assert.ok(app.includes('ensureLibraryLayout(drive,actual.id,')&&
  app.includes('xstage-drive-main-select')&&!app.includes('new google.picker.PickerBuilder()')&&
  app.includes('const xstageDriveFolders=window.XStageDriveFolders?.init({')&&
  app.includes('ensureAuth:ensureImporterGoogleAuth')&&
  app.includes('onFxChange:folderId=>window.dispatchEvent'),
  'Folder picker must use verified app OAuth and dispatch selected media sources');
assert.ok(settings.includes("const STORE='xstage-drive-source-folders-v1'")&&
  settings.includes('async function ensureLibraryLayout(')&&settings.includes('meta.name!==FIXED_NAMES[kind]')&&
  settings.includes('retired.has(parent)')&&
  settings.includes("if(cancelButton)cancelButton.disabled=!busy;")&&
  settings.includes('scope.XStageCloudImport.publishSingleCatalog({'),
  'Source choices must be account-scoped, prevent retired folders and build an atomic SQLite file');
assert.ok(soundfont.includes('const chosen=scope.XStageDriveFolders?.readSelections?.(sub,rootId)?.soundfont')&&
  soundfont.includes('context?.fontFolderId===chosenFolder')&&
  soundfont.includes('const entries=await listFolder(id,auth.token);')&&
  soundfont.includes('/\\.sf[23]$/i.test(x.name)'),
  'MIDI player must enumerate both direct and nested SF2/SF3 from selected Drive folder');
assert.ok(fx.includes('function stageEffects()')&&
  fx.includes("const current=window.XStageDriveFolders?.readSelections?.(")&&
  fx.includes("const children=await driveList(")&&
  fx.includes("const response=await privateFile(file.id,state.token);")&&
  fx.includes('total+blob.size>48*1048576')&&
  fx.includes('!stillSelected()')&&
  fx.includes("window.addEventListener('xstage:drive-fx-folder-change',clearStageFx)"),
  'FX must load only bounded, accessible Drive audio files from current selected folder');
assert.ok(importer.includes("const uploadOnly=!!this.dom.uploadOnly?.checked")&&
  importer.includes('if(uploadOnly)return;')&&
  importer.includes("if(!uploadOnly){")&&
  importer.includes("['SONGS','SOUNDFONT','FX','BACKUP','CACHE','LOGS']"),
  'Upload-only mode must defer publishing while allowing empty FX folder in active root');
assert.ok(!settings.includes('localStorage.setItem(STORE,JSON.stringify({token'),
  'Drive access tokens must never be stored in folder settings');
const menu=html.slice(html.indexOf('id="mobile-stage-menu"'),html.indexOf('id="mobile-home-toggle"'));
const sourcePanel=html.slice(html.indexOf('id="xstage-drive-sources"'),html.indexOf('class="cloud-import-lead"'));
assert.ok(!menu.includes('xstage-soundfont-authorize'),'Playback menu must not grant Drive files');
assert.equal((html.match(/id="xstage-soundfont-authorize"/g)||[]).length,1);
assert.ok(sourcePanel.includes('id="xstage-soundfont-authorize" type="button" hidden'));
assert.ok(app.includes("verifyFolder(drive,choice.id,rootId,'soundfont')"));
assert.ok(html.includes('id="xstage-drive-main-select"'));
assert.ok(settings.includes('if(parent===root)return first;'));
assert.ok(app.includes('Array.isArray(x.parents)&&x.parents.includes(current.id)'));
assert.ok(app.includes('!preferredRootId&&roots.length===1'));
assert.ok(settings.includes("ids.MIDI=await child(ids.SONGS,'MIDI'")&&!settings.includes("add('เปลี่ยนโฟลเดอร์'"));
assert.ok(app.includes("dialog.addEventListener('cancel',event=>{event.preventDefault();finish();})"));
assert.ok(soundfont.includes('showPermission(!fullRead&&!!chosenFolder'));
assert.ok(importer.includes('xstage:drive-sources-open')&&settings.includes('xstage:drive-sources-open'));
assert.ok(html.includes('id="xstage-drive-read-all"')&&html.includes('id="xstage-drive-scan-counts"'));
assert.ok(app.includes('ensureImporterGoogleAuth(true,true,true)')&&app.includes('grantedDriveReadAndWrite(newToken)'));
assert.ok(settings.includes('async function countSourceFiles('));
console.log('PASS: Google Drive music, SoundFont, FX source selection; deferred SQLite; scoped auth and media safety');
