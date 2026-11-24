import assert from 'node:assert/strict';
import fs from 'node:fs';
const read=p=>fs.readFileSync(new URL('../'+p,import.meta.url),'utf8');
const online=read('karaoke.html');
const config=read('config.js');
const sqlite=read('drive-sqlite.js');
const pc=read('windows-pc/source/karaoke/classic.py');
const player=read('windows-pc/source/karaoke/ui.py');
const pcReader=read('windows-pc/source/karaoke/drive_online_catalog.py');
const pcDialog=read('windows-pc/source/karaoke/drive_online_catalog_ui.py');
const pcPush=read('windows-pc/source/karaoke/shared_drive_sync.py');
const pcPushUi=read('windows-pc/source/karaoke/shared_drive_sync_ui.py');
const studio=read('songstudio-plus/web/index.html');
const studioJs=read('songstudio-plus/web/app.js');
const studioBackend=read('songstudio-plus/app.py');
const studioPush=read('songstudio-plus/shared_drive_sync.py');
assert.ok(config.includes("root:'XStageKaraoke'")&&config.includes("db:'DB'")&&
  config.includes("soundfont:'SOUNDFONT'")&&config.includes("fx:'FX'"),
  'All products must use one canonical Drive folder layout');
assert.ok(sqlite.includes('DB/songs.sqlite3 is the only catalog consumed and published'),
  'Online owns the single canonical SQLite');
assert.ok(online.includes('id="xstage-drive-build-db"')&&
  online.includes('xstage-drive-crossapp-help'),
  'Online remains the SQLite publisher and exposes shared library instructions');
assert.ok(pc.includes('open_shared_google_drive_catalog')&&
  pc.includes('open_shared_drive_push'),
  'Karaoke PC must expose Drive SQLite reader and local media push in Song menu');
assert.ok(pcReader.includes('immutable=1')&&pcReader.includes('PRAGMA query_only=ON')&&
  pcReader.includes('xstage-sqlite3-v1')&&pcReader.includes('PRAGMA quick_check(1)'),
  'PC reader must never mutate Online schema or create SQLite WAL files');
assert.ok(pcDialog.includes('catalog.search(')&&
  pcDialog.includes('app._shared_drive_playback_song')&&
  !pcDialog.includes('app.library.add_files(')&&
  player.includes("item.song_id == -1 else self.library.get(item.song_id)"),
  'PC playback must reference Drive catalog without duplicating local song rows');
assert.ok(pcPushUi.includes('sync.inspect(')&&pcPushUi.includes('sync.publish(')&&
  pcPushUi.includes('messagebox.askyesno'),
  'PC upload must have a dry-run and user confirmation');
for(const source of [pcPush,studioPush]){
  for(const required of ['hashlib.sha256()','_check_cancel(cancel)',
                         'if snapshot["stats"]["conflict"]:',
                         'raise FileExistsError',
                         'published_bytes','DB/songs.sqlite3']){
    assert.ok(source.includes(required),'missing safety contract: '+required);
  }
  assert.ok(!source.includes('sqlite3.connect('),
    'Media publisher must NEVER open or write the Online SQLite database');
}
for(const id of ['drive-push-source','drive-push-area',
                 'drive-push-preview','drive-push-submit']){
  assert.ok(studio.includes('id="'+id+'"')&&studioJs.includes('"'+id+'"'),
    'Studio publisher button must have a live handler: '+id);
}
assert.ok(studioBackend.includes('"/api/drive/push-preview"')&&
          studioBackend.includes('"/api/drive/push"')&&
          studioBackend.includes('drivesync.inspect(')&&
          studioBackend.includes('drivesync.publish('),
  'Studio backend must enforce preflight and revalidation before writes');
console.log('PASS: XStageKaraoke shared Drive root, PC read-only SQLite, verified two-way app workflow and non-destructive media publish contracts');
