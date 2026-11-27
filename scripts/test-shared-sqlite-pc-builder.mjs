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

  // Reproduce the actual P0: a legacy SongLibrary DB (no catalog_meta)
  // exported via the PC migration path, not a separately invented Web DB.
  for(let n=4;n<=7;n++){
    const code=String(10000+n);
    fs.writeFileSync(path.join(directory,code+'.xmid'),makeXmid(code,'เพลงทดสอบ '+code,'ศิลปิน',midi1));
  }
  const home=path.join(temp,'PC');
  fs.mkdirSync(path.join(home,'DB'),{recursive:true});
  const studioSource=fileURLToPath(new URL('../songstudio-plus/',import.meta.url));
  const migrate=[
    "import hashlib,json,sqlite3,sys",
    "from pathlib import Path",
    "from contextlib import closing",
    "from karaoke.library import SongLibrary",
    "from karaoke.local_master import prepare_legacy_export,export_portable",
    "from karaoke.shared_song_library import SharedSongLibrary",
    "sys.path.insert(0,sys.argv[3])",
    "from xmid_library_manager import scan",
    "home,root=map(Path,sys.argv[1:3])",
    "source=home/'DB/songs.sqlite3'",
    "lib=SongLibrary(source)",
    "lib.upsert_catalog([dict(path=str(f),code=f.stem,title='เพลง '+f.stem,artist='',kind='midi',format='xmid',playable=1,first_lyric='เนื้อเดิม') for f in sorted((root/'SONGS').rglob('*.xmid'))])",
    "with closing(sqlite3.connect(source)) as db:",
    "    original=dict(db.execute('SELECT code,id FROM songs'))",
    "    assert len(original)==7",
    "    assert not db.execute(\"SELECT 1 FROM sqlite_master WHERE name='catalog_meta'\").fetchone()",
    "prepared=prepare_legacy_export(home,source,root)",
    "assert prepared['accepted']==7",
    "out=export_portable(home,root,pending=True,overwrite=True)",
    "before=hashlib.sha256(out.read_bytes()).hexdigest()",
    "pc=SharedSongLibrary(root,{})",
    "assert pc.count()==7",
    "assert set(r['code'] for r in pc.search('เพลง',limit=20))==set(original)",
    "# Host executes the same bounded SQLite search used by Android. This",
    "# validates the exact database bytes, not Android device instrumentation.",
    "with closing(sqlite3.connect(out.as_uri()+'?mode=ro',uri=True)) as db:",
    "    assert dict(db.execute('SELECT key,value FROM catalog_meta'))['pcSchema']=='shared-v1'",
    "    sql=\"SELECT web_song_id,payload FROM songs WHERE playable=1 AND instr(lower(code)||' '||lower(title)||' '||lower(artist),?)>0 ORDER BY ordinal,id LIMIT 5 OFFSET ?\"",
    "    pages=[db.execute(sql,('เพลง',offset)).fetchall() for offset in (0,5)]",
    "    assert list(map(len,pages))==[5,2]",
    "    payloads=[json.loads(payload) for page in pages for ident,payload in page]",
    "    assert all(r['legacyPcId']==original[r['code']] for r in payloads)",
    "    assert all(r['firstLyric']=='เนื้อเดิม' for r in payloads)",
    "for folder in (root,root/'SONGS'):",
    "    plan=scan(str(out),str(folder))",
    "    assert plan['schema']=='shared-v1' and len(plan['rows'])==7",
    "    assert all(r['webSongId'] and r['stamp'] and not r['actionable'] for r in plan['rows'])",
    "assert hashlib.sha256(out.read_bytes()).hexdigest()==before",
    "assert [f.name for f in out.parent.iterdir()]==['songs.sqlite3']",
    "print(json.dumps(dict(ids=original,sha256=before)))"
  ].join('\n');
  const migrated=spawnSync(python,['-c',migrate,home,root,studioSource],
    {encoding:'utf8',env:{...process.env,PYTHONPATH:source}});
  assert.equal(migrated.status,0,migrated.stderr||migrated.stdout||String(migrated.error));
  const proof=JSON.parse(migrated.stdout.trim().split(/\r?\n/).at(-1));
  const sameBytes=fs.readFileSync(path.join(root,'DB/songs.sqlite3'));
  assert.equal(createHash('sha256').update(sameBytes).digest('hex'),proof.sha256);
  const portable=await scope.XStageDriveSQLite.read(new Uint8Array(sameBytes));
  assert.equal(portable.songs.length,7);
  for(const song of portable.songs){
    assert.equal(song.legacyPcId,proof.ids[song.code]);
    assert.equal(song.firstLyric,'เนื้อเดิม');
    assert.equal(song.xmid.md5Checksum,createHash('md5')
      .update(fs.readFileSync(path.join(root,song.xmid.path))).digest('hex'));
  }
  console.log('PASS: one PC legacy-migrated SQLite file; all 7 songs, original IDs, metadata and checksums match in PC, Web, Android host paging and Studio read-only audit');
}finally{
  fs.rmSync(temp,{recursive:true,force:true});
}
