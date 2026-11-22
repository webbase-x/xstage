import fs from 'node:fs';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import initSqlJs from 'sql.js';

const read=path=>fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const source=read('drive-sqlite.js');
const app=read('app.js'),importer=read('cloud-import.js'),page=read('karaoke.html');
const version=JSON.parse(read('version.json'));
assert.equal(version.build,1140);
assert.ok(page.indexOf('drive-sqlite.js?v=1170-single-sqlite')<page.indexOf('cloud-import.js?v=1175-mid-bytes-and-md5'));
assert.ok(app.includes('codec.read(new Uint8Array(buffer))'));
assert.ok(importer.includes("application/vnd.sqlite3"));
assert.ok(!importer.includes("catalog-delta-'+generation+'.sqlite3"));
assert.ok(importer.includes("'songs.sqlite3'"));
assert.ok(importer.includes("publishSingleCatalog"));
assert.ok(importer.includes("const canonical=dbChildren.filter(x=>x.name==='songs.sqlite3'"));
assert.ok(importer.includes("x.name==='current.json'||x.name==='.xstage-songstudio-staging.json'"));
assert.ok(!importer.includes("drive.upload(dbRoot,marker,'current.json'"));
assert.ok(app.includes("name='songs.sqlite3' and trashed=false"));
assert.ok(app.includes("function directCatalogPointer(file)"));
assert.ok(app.includes('xstageCloudImporter.consolidate()'),
  'Legacy user libraries must automatically migrate with the verified web OAuth session');
assert.ok(app.includes('onConsolidationStatus:message=>setStatus(message'),
  'One-time migration must expose progress/error status on the main player');
assert.ok(importer.includes('acquireCatalogLease(drive,cacheRoot,check,status)'),
  'Multi-computer imports must coordinate a Drive writer lease');
assert.ok(importer.includes("const {hashes:byMidi,duplicates:olderDuplicates,backfilled:olderHashes}"),
  'All existing MID/XSK/XMID sources must be indexed globally');
assert.ok(app.includes("activeDriveCatalog(state.catalogDbDirId,token)"));
assert.ok(importer.includes("moveToFolder"));
assert.ok(!importer.includes("catalog-base-'+generation+'.json"));
assert.ok(app.includes("pointer?.layoutVersion!==6"));
assert.ok(importer.includes("![5,6].includes(pointer.layoutVersion)"));
assert.ok(app.includes("pointer?.directFile!==true"));

const SQL=await initSqlJs();
const scope={initSqlJs:()=>Promise.resolve(SQL),Uint8Array,ArrayBuffer,Blob,
  Promise,Error,Object,Set,Array,JSON,String,Number,console};
scope.window=scope;
vm.runInNewContext(source,scope,{filename:'drive-sqlite.js'});
const codec=scope.XStageDriveSQLite;
assert.equal(codec.format,'xstage-sqlite3-v1');
const songA={webSongId:'drive/X100',code:'00001-aaaaaaaa',sourceCode:'00001',
 title:'ทดสอบเสียง',artist:'ศิลปิน ก',sourceFormat:'XMID',
 originalFilename:'00001.XMID',originalRelativePath:'batch-A/00001.XMID',
 originalFileSize:32768,midiSize:11294,midiHash:'a'.repeat(32),
 xmid:{fileId:'file_01',path:'SONGS/MIDI/XMID/X/aaaaaaaa/00001.XMID'}};
const songB={webSongId:'drive/X200',code:'X200',title:'ความรัก',artist:'ศิลปิน ข',
 sourceFormat:'MP3',audio:{fileId:'file_02',path:'SONGS/AUDIO/MP3/SONG/X/X200.mp3'}};
const bytes=await codec.create('snapshot',[songA,songB],[],'releaseA');
assert.equal(Buffer.from(bytes).subarray(0,16).toString('latin1'),'SQLite format 3\0');
assert.ok(bytes.length>=4096);
const db=new SQL.Database(bytes);
assert.deepEqual(db.exec("PRAGMA integrity_check")[0].values,[['ok']]);
assert.equal(db.exec('SELECT count(*) FROM songs')[0].values[0][0],2);
const details=db.exec("SELECT original_filename,original_relative_path,original_file_size,source_code,midi_size,midi_md5 FROM songs WHERE web_song_id='drive/X100'")[0].values[0];
assert.deepEqual(details,['00001.XMID','batch-A/00001.XMID',32768,
  '00001',11294,'a'.repeat(32)],'Filename, source code and raw MIDI content identity must persist in SQLite');
assert.equal(db.exec("SELECT count(*) FROM sqlite_master WHERE type='index' AND name='songs_midi_md5_uq'")[0].values[0][0],1);
assert.equal(db.exec("SELECT count(*) FROM sqlite_master WHERE type='index' AND name='songs_midi_size_idx'")[0].values[0][0],1);
assert.equal(db.exec("SELECT name FROM sqlite_master WHERE type='table' AND name='songs'")[0].values[0][0],'songs');
db.close();
const parsed=await codec.read(bytes);
assert.equal(parsed.kind,'snapshot');
assert.equal(parsed.generation,'releaseA');
assert.deepEqual(JSON.parse(JSON.stringify(parsed.songs)),[songA,songB]);
const deltaBytes=await codec.create('delta',[{...songA,title:'เพลงแก้ไข'}],['drive/X200'],'releaseB');
const delta=await codec.read(deltaBytes);
assert.equal(delta.kind,'delta');
assert.equal(delta.upserts.length,1);
assert.deepEqual(Array.from(delta.removes),['drive/X200']);
assert.equal(delta.upserts[0].title,'เพลงแก้ไข');
await assert.rejects(codec.create('snapshot',[songA,songA]),/รหัสเพลงว่างหรือซ้ำ/);
await assert.rejects(codec.create('snapshot',[songA,{
  ...songA,webSongId:'drive/DIFFERENT',code:'00001-bbbbbbbb',
  originalFilename:'00001.XMID',midiSize:11294
}]),/MIDI ซ้ำในฐาน SQLite/,
  'Repeated XMID filename with identical MIDI MD5 must be rejected at the database layer');
const sameSizeDifferentMidi=await codec.create('snapshot',[songA,{
  ...songA,webSongId:'drive/DIFFERENT',code:'00001-bbbbbbbb',
  originalFilename:'00001.XMID',midiHash:'b'.repeat(32),midiSize:11294
}],[],'otherBatch');
assert.equal((await codec.read(sameSizeDifferentMidi)).songs.length,2,
  'Different MIDI recordings sharing a byte size and filename must remain separate');
const legacyDb=new SQL.Database();
legacyDb.run("CREATE TABLE catalog_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);");
legacyDb.run("CREATE TABLE songs(web_song_id TEXT PRIMARY KEY,code TEXT NOT NULL,title TEXT NOT NULL,artist TEXT NOT NULL,source_format TEXT NOT NULL,payload TEXT NOT NULL);");
legacyDb.run("CREATE TABLE removed_songs(web_song_id TEXT PRIMARY KEY);");
legacyDb.run("INSERT INTO catalog_meta VALUES ('format','xstage-sqlite3-v1'),('schemaVersion','1'),('kind','snapshot'),('generation','legacy');");
const legacyStmt=legacyDb.prepare('INSERT INTO songs VALUES (?,?,?,?,?,?)');
legacyStmt.run(['legacy/one','L001','เพลงเก่า','ศิลปินเก่า','SMF',
  JSON.stringify({webSongId:'legacy/one',code:'L001',title:'เพลงเก่า',artist:'ศิลปินเก่า',sourceFormat:'SMF'})]);
legacyStmt.free();
const legacyBytes=legacyDb.export();legacyDb.close();
assert.equal((await codec.read(legacyBytes)).songs.length,1,
  'Legacy SQLite catalogs with no MIDI fingerprint columns must remain readable');

await assert.rejects(codec.read(new Uint8Array(400)),/ไม่ใช่ฐานข้อมูล SQLite3/);
console.log('PASS: real SQLite3 binary (SQLite format 3), schema, single canonical snapshot, legacy delta reader, Thai titles, integrity and corruption guard');
