import assert from 'node:assert/strict';
import fs from 'node:fs';

// The original Google Picker top-layer regression was retired when the app
// switched to its own same-origin, OAuth-authorized folder browser.
// Exercise the actual app-owned folder-picker behavior instead.
await import('./direct-drive-picker-test.mjs');

const app=fs.readFileSync(new URL('../app.js',import.meta.url),'utf8');
assert.ok(app.includes('function browseAuthorizedDriveFolders({rootId,kind,sameSession,list,allowGrant})'),
  'Folder picker must be an app-owned native dialog with controlled traversal');
assert.ok(app.includes('async function openSharedLibraryPicker()'),
  'User must be able to select and create their primary Google Drive folder');
assert.ok(app.includes('async function selectedDriveRootById(id, token)'),
  'Selecting a root must verify exact immutable Folder ID');
assert.ok(app.includes('async function chooseUserDriveFolder(kind)'),
  'Song/SoundFont/FX folders must use the same authorized picker');
assert.ok(app.includes('dialog.showModal()')&&app.includes("dialog.addEventListener('cancel'"),
  'Native folder dialogs must be dismissible without losing the import state');
assert.ok(app.includes("const sameSession=()=>state.accountSub===account"),
  'Folder browsing must stop if the Google account/root changes');
assert.ok(app.includes("!isRetiredDriveRoot(x.id)")&&app.includes("item.parents?.includes(current.id)"),
  'Only descendants of the exact selected root may be offered');
assert.ok(!app.includes('new google.picker.PickerBuilder()'),
  'Do not load the retired external Google Picker iframe or require API keys');
assert.ok(app.includes('savePreferredLibraryRoot(account,actual.id)')&&
          app.includes("selectedDriveRootById(id,state.token)"),
  'The approved Folder ID must be validated before selection is persisted');
console.log('PASS: authorized same-origin Google Drive folder picker, account isolation and native dialog behavior');
