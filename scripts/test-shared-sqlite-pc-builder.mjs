import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import initSqlJs from 'sql.js';

const temp=fs.mkdtempSync(path.join(os.tmpdir(),'xstage-pc-db-writer-'));
try{
  const root=path.join(temp,'XStageKaraoke');
  for(const dir of ['SONGS/MIDI/XMID/1','DB','SOUNDFONT','FX'])
    fs.mkdirSync(path.join(root,dir),{recursive:true});
  const packText=x=>{const b=Buffer.from(x,'utf8'),n=Buffer.alloc(4);
    n.writeUInt32LE(b.length);return Buffer.concat([n,b]);};
  function makeXmid(code,title,artist,midi){
    const meta=Buffer.concat([...['studio-id',code,'v1',title,artist,'timed'].map(packText),
      Buffer.alloc(4)]);
    const header=Buffer.alloc(92);
    header.write('XSTGPLS1',0,'ascii');
    header.writeUInt32LE(1,8);
    header.writeBigUInt64LE(BigInt(meta.length),12);
    header.writeBigUInt64LE(BigInt(midi.length),20);
    createHash('sha256').update(midi).digest().copy(header,28);
    createHash('sha256').update(meta).digest().copy(header,60);
    return Buffer.concat([header,meta,midi]);
  }
  const midi1=Buffer.from([0x4d,0x54,0x68,0x64,0,0,0,6,0,0,0,1,0,96,
    0x4d,0x54,0x72,0x6b,0,0,0,4,0,0xff,0x2f,0]);
  const midi2=Buffer.from(midi1);midi2[13]=97;
  const directory=path.join(root,'SONGS/MIDI/XMID/1');
  fs.writeFileSync(path.join(directory,'10001.xmid'),makeXmid('10001','เพลงทดสอบหนึ่ง','ศิลปิน ก',midi1));
  fs.writeFileSync(path.join(directory,'10002.xmid'),makeXmid('10002','เพลงทดสอบสอง','ศิลปิน ข',midi2));
  fs.writeFileSync(path.join(directory,'10003.xmid'),makeXmid('10003','ไฟล์เพลงซ้ำ','ศิลปิน ค',midi1));
  const python=process.env.PYTHON||(process.platform==='win32'?'python':'python3');
  const source=fileURLToPath(new URL('../windows-pc/source/',import.meta.url));
  const pc=[
    "import json,sys,os",
    "from karaoke.shared_catalog_builder import build",
    "from karaoke.shared_song_library import SharedSongLibrary",
    "root=sys.argv[1]",
    "preview=build(root,publish=False)",
    "assert preview['accepted']==2 and preview['duplicates']==1,preview",
    "assert not os.path.exists(os.path.join(root,'DB','songs.sqlite3'))",
    "output=build(root,publish=True)",
    "assert output['accepted']==2 and output['duplicates']==1,output",
    "pc=SharedSongLibrary(root,{})",
    "assert pc.count()==2",
    "assert {song['title'] for song in pc.search('เพลง')}=={'เพลงทดสอบหนึ่ง','เพลงทดสอบสอง'}",
    "assert all(pc.get(song['id'])['path'] for song in pc.search(''))",
    "print(json.dumps(output,ensure_ascii=False))"
  ].join('\n');
  const py=spawnSync(python,['-c',pc,root],{
    encoding:'utf8',env:{...process.env,PYTHONPATH:source}});
  assert.equal(py.status,0,py.stderr||py.stdout||String(py.error));
  const output=JSON.parse(py.stdout.trim().split(/\r?\n/).at(-1));
  assert.equal(output.accepted,2);
  assert.equal(output.pending_drive_ids,2,'PC cannot invent Drive File IDs');
  const dbBytes=fs.readFileSync(path.join(root,'DB/songs.sqlite3'));
  const SQL=await initSqlJs();
  const scope={initSqlJs:()=>Promise.resolve(SQL),Uint8Array,ArrayBuffer,Blob,TextEncoder,
    Promise,Error,Object,Set,Array,JSON,String,Number,console};
  scope.window=scope;
  vm.runInNewContext(fs.readFileSync(new URL('../drive-sqlite.js',import.meta.url),'utf8'),
    scope,{filename:'drive-sqlite.js'});
  const catalog=await scope.XStageDriveSQLite.read(new Uint8Array(dbBytes));
  assert.equal(catalog.kind,'snapshot');
  assert.equal(catalog.songs.length,2);
  assert.equal(catalog.songs.map(song=>song.code).join(','),'10001,10002');
  assert.ok(catalog.songs.every(song=>
    song.pendingDriveLink===true&&song.xmid?.path.startsWith('SONGS/')&&
    /^[0-9a-f]{32}$/.test(song.xmid.md5Checksum)));
  const regenerated=await scope.XStageDriveSQLite.create('snapshot',catalog.songs,[], 'from-online');
  assert.equal((await scope.XStageDriveSQLite.read(regenerated)).songs.length,2);
  const sqlite=new SQL.Database(dbBytes);
  assert.equal(sqlite.exec('PRAGMA quick_check(1)')[0].values[0][0],'ok');
  sqlite.close();
  assert.equal(fs.readdirSync(path.join(root,'DB')).length,1);
  console.log('PASS: Karaoke PC creates real shared SQLite, Online reads and republishes it, 2 songs match, duplicate MIDI is rejected');
}finally{
  fs.rmSync(temp,{recursive:true,force:true});
}
