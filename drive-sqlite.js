/* X-Stage Karaoke Online: real SQLite catalog snapshots on private Drive.
 * SQL.js (SQLite compiled to WebAssembly, MIT) is initialized only when the
 * user downloads/publishes a catalog. No OAuth token goes to the CDN.
 * DB/songs.sqlite3 is the canonical song catalog. A legacy current.json is
 * readable for one-time migration only; new catalogs need no JSON pointer.
 */
(function(scope){
'use strict';
const VERSION=1;
const FORMAT='xstage-sqlite3-v1';
const CDN='https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.13.0/';
const CDN_FALLBACK='https://cdn.jsdelivr.net/npm/sql.js@1.13.0/dist/';
const MAX_BYTES=192*1048576;
let enginePromise=null;
const fail=message=>{throw Error('SQLite: '+message);};
function script(url){
  return new Promise((resolve,reject)=>{
    const el=document.createElement('script');
    el.src=url;el.async=true;el.crossOrigin='anonymous';
    let done=false;
    const finish=(error)=>{
      if(done)return;done=true;clearTimeout(timer);el.onload=el.onerror=null;
      if(error){el.remove();reject(error);}else resolve();
    };
    const timer=setTimeout(()=>finish(Error('โหลดเครื่องอ่าน SQLite ไม่ทัน')),20000);
    el.onload=()=>finish();el.onerror=()=>finish(Error('โหลด SQLite จาก CDN ไม่สำเร็จ'));
    document.head.append(el);
  });
}
async function engine(){
  if(!enginePromise)enginePromise=(async()=>{
    let selected=CDN;
    if(typeof scope.initSqlJs!=='function'){
      try{await script(CDN+'sql-wasm.js');}
      catch{selected=CDN_FALLBACK;await script(CDN_FALLBACK+'sql-wasm.js');}
    }
    if(typeof scope.initSqlJs!=='function')fail('ไม่พบ sql.js');
    return scope.initSqlJs({locateFile:name=>selected+name});
  })().catch(err=>{enginePromise=null;throw Error('SQLite WebAssembly ไม่พร้อม: '+err.message);});
  return enginePromise;
}
const validId=id=>typeof id==='string'&&id.length>0&&id.length<512;
function checkHeader(bytes){
  if(!(bytes instanceof Uint8Array)||bytes.length<100||bytes.length>MAX_BYTES)
    fail('ขนาดฐานข้อมูลไม่ถูกต้อง');
  if(Array.from(bytes.subarray(0,16)).map(x=>String.fromCharCode(x)).join('')!=='SQLite format 3\0')
    fail('ไฟล์นี้ไม่ใช่ฐานข้อมูล SQLite3');
}
function createSchema(db,kind,generation){
  db.run(`CREATE TABLE catalog_meta (
    key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL
  );
  CREATE TABLE songs (
    web_song_id TEXT PRIMARY KEY NOT NULL,
    code TEXT NOT NULL, title TEXT NOT NULL, artist TEXT NOT NULL,
    source_format TEXT NOT NULL, payload TEXT NOT NULL
  );
  CREATE INDEX songs_code_idx ON songs(code);
  CREATE INDEX songs_title_idx ON songs(title);
  CREATE INDEX songs_artist_idx ON songs(artist);
  CREATE TABLE removed_songs (web_song_id TEXT PRIMARY KEY NOT NULL);`);
  const insert=db.prepare('INSERT INTO catalog_meta(key,value) VALUES (?,?)');
  for(const [key,value] of Object.entries({format:FORMAT,schemaVersion:VERSION,kind,generation})){
    insert.run([key,String(value)]);insert.reset();
  }
  insert.free();
}
async function create(kind,songs,removes=[],generation=''){
  if(!['snapshot','delta'].includes(kind))fail('ชนิดฐานเพลงไม่รองรับ');
  if(!Array.isArray(songs)||!Array.isArray(removes))fail('ข้อมูลเพลงไม่ครบ');
  const SQL=await engine();
  const db=new SQL.Database();
  try{
    createSchema(db,kind,generation);
    db.run('BEGIN TRANSACTION');
    const upsert=db.prepare(
      'INSERT INTO songs(web_song_id,code,title,artist,source_format,payload) VALUES (?,?,?,?,?,?)');
    const seen=new Set();
    try{
      for(const row of songs){
        if(!row||!validId(row.webSongId)||seen.has(row.webSongId))
          fail('รหัสเพลงว่างหรือซ้ำ');
        seen.add(row.webSongId);
        upsert.run([row.webSongId,String(row.code||''),String(row.title||''),
          String(row.artist||''),String(row.sourceFormat||''),JSON.stringify(row)]);
        upsert.reset();
      }
    }finally{upsert.free();}
    if(kind==='delta'){
      const deleted=db.prepare('INSERT INTO removed_songs(web_song_id) VALUES (?)');
      try{
        for(const id of removes){
          if(!validId(id))fail('รหัสเพลงที่ลบไม่ถูกต้อง');
          deleted.run([id]);deleted.reset();
        }
      }finally{deleted.free();}
    }else if(removes.length)fail('Snapshot ห้ามมีรายการลบ');
    db.run('COMMIT');
    const bytes=db.export();
    checkHeader(bytes);
    return bytes;
  }finally{db.close();}
}
async function read(bytes){
  if(bytes instanceof ArrayBuffer)bytes=new Uint8Array(bytes);
  checkHeader(bytes);
  const SQL=await engine();
  const db=new SQL.Database(bytes);
  try{
    const check=db.exec('PRAGMA quick_check(1)');
    if(!check.length||check[0].values[0][0]!=='ok')
      fail('ฐานข้อมูลไม่ผ่านการตรวจความสมบูรณ์');
    const metadata=Object.fromEntries(
      (db.exec('SELECT key,value FROM catalog_meta')[0]?.values)||[]);
    if(metadata.format!==FORMAT||Number(metadata.schemaVersion)!==VERSION||
       !['snapshot','delta'].includes(metadata.kind))
      fail('ฐานเพลง SQLite ไม่ตรงเวอร์ชันหรือชนิดที่รองรับ');
    const songRows=(db.exec('SELECT web_song_id,payload FROM songs')[0]?.values)||[];
    const songs=[];
    for(const [id,payload] of songRows){
      let song;
      try{song=JSON.parse(payload);}catch{fail('ข้อมูล JSON ในแถว SQLite ไม่ถูกต้อง');}
      if(!validId(id)||song?.webSongId!==id)fail('รหัสอ้างอิงในฐานเพลงไม่ตรงกัน');
      songs.push(song);
    }
    const removes=(db.exec('SELECT web_song_id FROM removed_songs')[0]?.values||[]).map(x=>x[0]);
    return {schemaVersion:1,generation:metadata.generation||'',
      kind:metadata.kind, ...(metadata.kind==='snapshot'?{songs}:{upserts:songs,removes})};
  }finally{db.close();}
}
scope.XStageDriveSQLite=Object.freeze({create,read,engine,format:FORMAT});
})(window);
