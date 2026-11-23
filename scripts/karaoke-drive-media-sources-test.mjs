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
  html.includes('pc-extensions.js?v=1190-selected-drive-fx')&&
  html.includes('browser-midi.js?v=1187-selected-font-folder'),
  'Page must load updated Drive folder, SoundFont and FX implementations');
assert.ok(app.includes('async function chooseUserDriveFolder(kind)')&&
  app.includes('.setSelectFolderEnabled(true)')&&
  app.includes('const xstageDriveFolders=window.XStageDriveFolders?.init({')&&
  app.includes('ensureAuth:ensureImporterGoogleAuth')&&
  app.includes('onFxChange:folderId=>window.dispatchEvent'),
  'Folder picker must use verified app OAuth and dispatch selected media sources');
assert.ok(settings.includes("const STORE='xstage-drive-source-folders-v1'")&&
  settings.includes('const verifiedSession=session()')&&
  settings.includes('retired.has(parent)')&&
  settings.includes("if(cancelButton)cancelButton.disabled=!busy;")&&
  settings.includes('scope.XStageCloudImport.publishSingleCatalog({'),
  'Source choices must be account-scoped, prevent retired folders and build an atomic SQLite file');
assert.ok(soundfont.includes('const chosenFolder=scope.XStageDriveFolders?.readSelections?.(sub,rootId)')&&
  soundfont.includes('context?.fontFolderId===chosenFolder')&&
  soundfont.includes('const direct=await listFolder(sourceId,auth.token);')&&
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
console.log('PASS: Google Drive music, SoundFont, FX source selection; deferred SQLite; scoped auth and media safety');
