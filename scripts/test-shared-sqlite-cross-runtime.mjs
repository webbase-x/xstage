/* Real cross-runtime acceptance: SQL.js publishes the DB, Python/Karaoke PC
 * reads that exact file without changing it or creating SQLite sidecars. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import {spawnSync} from 'node:child_process';
import initSqlJs from 'sql.js';

const rootDir=fs.mkdtempSync(path.join(os.tmpdir(),'xstage-shared-db-'));
try{
  const libraryRoot=path.join(rootDir,'XStageKaraoke');
  for(const dir of ['DB','SONGS/MIDI/XMID/1','SONGS/AUDIO/MP3/SONG/2','SOUNDFONT','FX'])
    fs.mkdirSync(path.join(libraryRoot,dir),{recursive:true});
  fs.writeFileSync(path.join(libraryRoot,'SONGS/MIDI/XMID/1/10001.xmid'),Buffer.from('XMID-placeholder'));
  fs.writeFileSync(path.join(libraryRoot,'SONGS/AUDIO/MP3/SONG/2/20001.mp3'),Buffer.from('MP3-placeholder'));
  const SQL=await initSqlJs();
  const scope={initSqlJs:()=>Promise.resolve(SQL),Uint8Array,ArrayBuffer,Blob,TextEncoder,
    Promise,Error,Object,Set,Array,JSON,String,Number,console};
  scope.window=scope;
  const js=fs.readFileSync(new URL('../drive-sqlite.js',import.meta.url),'utf8');
  vm.runInNewContext(js,scope,{filename:'drive-sqlite.js'});
  const songs=[
    {webSongId:'browser/xmid/abc01',code:'10001',title:'เพลงตัวอย่าง',artist:'นักร้อง ก',
      sourceFormat:'XMID',originalRelativePath:'MIDI/XMID/1/10001.xmid',
      originalFilename:'10001.xmid',midiHash:'a'.repeat(32),midiSize:218,
      xmid:{fileId:'drive-file-xmid-1',path:'SONGS/MIDI/XMID/1/10001.xmid'}},
    {webSongId:'browser/audio/def02',code:'20001',title:'เสียงตัวอย่าง',artist:'นักร้อง ข',
      sourceFormat:'MP3',originalRelativePath:'AUDIO/MP3/SONG/2/20001.mp3',
      originalFilename:'20001.mp3',
      audio:{fileId:'drive-file-mp3-1',path:'SONGS/AUDIO/MP3/SONG/2/20001.mp3'}}
  ];
  const bytes=await scope.XStageDriveSQLite.create('snapshot',songs,[],'pc-online-test');
  fs.writeFileSync(path.join(libraryRoot,'DB/songs.sqlite3'),Buffer.from(bytes));
  const database=new SQL.Database(bytes);
  const records=database.exec('SELECT id,web_song_id,path,code FROM songs ORDER BY code')[0].values;
  assert.equal(records.length,2);
  const ids=records.map(([id])=>id);
  assert.equal(new Set(ids).size,2);
  assert.ok(ids.every(id=>Number.isSafeInteger(id)&&id>0));
  database.close();
  const python=`
import hashlib, json, os, sys
sys.path.insert(0, sys.argv[1])
from karaoke.shared_song_library import SharedSongLibrary
root=sys.argv[2]; expected=json.loads(sys.argv[3])
database=os.path.join(root,'DB','songs.sqlite3')
before=hashlib.sha256(open(database,'rb').read()).hexdigest()
lib=SharedSongLibrary(root,{})
assert lib.count()==2
rows=lib.search('',limit=20)
assert sorted(x['id'] for x in rows)==sorted(expected)
assert {r['code'] for r in rows}=={'10001','20001'}
assert {r['kind'] for r in rows}=={'MIDI','AUDIO'}
for row in rows:
    found=lib.get(row['id'])
    assert found is not None and os.path.isfile(found['path'])
    assert found['code']==row['code']
reader=lib.open_reader()
try:
    assert reader.warm_up()==2
finally:
    reader.close()
after=hashlib.sha256(open(database,'rb').read()).hexdigest()
assert before==after,'Karaoke PC must not rewrite Online database'
assert not os.path.exists(database+'-wal')
assert not os.path.exists(database+'-shm')
assert len(os.listdir(os.path.dirname(database)))==1
print('PASS: PC sees exactly the same 2 songs/IDs/paths as Online with no DB writes')
`;
  const pythonExe=process.env.PYTHON|| (process.platform==='win32'?'python':'python3');
  const result=spawnSync(pythonExe,['-c',python,
    new URL('../windows-pc/source/',import.meta.url).pathname,
    libraryRoot,JSON.stringify(ids)],{encoding:'utf8'});
  if(result.status!==0)
    throw Error('Python PC reader failed: '+(result.stderr||result.stdout||result.error?.message));
  process.stdout.write(result.stdout);
  const read=await scope.XStageDriveSQLite.read(bytes);
  assert.equal(read.songs.length,2);
  console.log('PASS: shared SQL.js/Python SQLite, stable song IDs, identical metadata and no extra PC database');
}finally{
  fs.rmSync(rootDir,{recursive:true,force:true});
}
