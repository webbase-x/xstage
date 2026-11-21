import fs from 'node:fs';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import initSqlJs from 'sql.js';

const read=path=>fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const source=read('drive-sqlite.js');
const app=read('app.js'),importer=read('cloud-import.js'),page=read('karaoke.html');
const version=JSON.parse(read('version.json'));
assert.equal(version.build,1132);
assert.ok(page.indexOf('drive-sqlite.js?v=1132')<page.indexOf('cloud-import.js?v=1132'));
assert.ok(app.includes('codec.read(new Uint8Array(buffer))'));
assert.ok(importer.includes("application/vnd.sqlite3"));
assert.ok(importer.includes("catalog-delta-'+generation+'.sqlite3"));
assert.ok(importer.includes("songs-'+generation+'.sqlite3"));
assert.ok(!importer.includes("catalog-base-'+generation+'.json"));
assert.ok(app.includes("pointer?.layoutVersion!==5"));
assert.ok(importer.includes("pointer.layoutVersion!==5"));

const SQL=await initSqlJs();
const scope={initSqlJs:()=>Promise.resolve(SQL),Uint8Array,ArrayBuffer,Blob,
  Promise,Error,Object,Set,Array,JSON,String,Number,console};
scope.window=scope;
vm.runInNewContext(source,scope,{filename:'drive-sqlite.js'});
const codec=scope.XStageDriveSQLite;
assert.equal(codec.format,'xstage-sqlite3-v1');
const songA={webSongId:'drive/X100',code:'X100',title:'ทดสอบเสียง',artist:'ศิลปิน ก',
 sourceFormat:'XMID',midi:{fileId:'file_01',path:'SONGS/MIDI/XMID/X/X100.xmid'}};
const songB={webSongId:'drive/X200',code:'X200',title:'ความรัก',artist:'ศิลปิน ข',
 sourceFormat:'MP3',audio:{fileId:'file_02',path:'SONGS/AUDIO/MP3/SONG/X/X200.mp3'}};
const bytes=await codec.create('snapshot',[songA,songB],[],'releaseA');
assert.equal(Buffer.from(bytes).subarray(0,16).toString('latin1'),'SQLite format 3\0');
assert.ok(bytes.length>=4096);
const db=new SQL.Database(bytes);
assert.deepEqual(db.exec("PRAGMA integrity_check")[0].values,[['ok']]);
assert.equal(db.exec('SELECT count(*) FROM songs')[0].values[0][0],2);
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
await assert.rejects(codec.read(new Uint8Array(400)),/ไม่ใช่ฐานข้อมูล SQLite3/);
console.log('PASS: real SQLite3 binary (SQLite format 3), schema, immutable snapshot/delta, Thai titles, integrity and corruption guard');
