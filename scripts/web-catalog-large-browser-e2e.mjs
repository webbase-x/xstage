/* Real Chromium OPFS test, using a generated private fixture, not user data.
 * The SQLite file deliberately exceeds the former 192 MiB reader ceiling.
 * Node and HTTP serve it from disk; the browser must stream and query it. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'xstage-large-db-'));
const dbPath=path.join(tmp,'songs.sqlite3');
const python=`import sqlite3,sys,json
db=sqlite3.connect(sys.argv[1])
db.executescript("""
CREATE TABLE catalog_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE songs(id INTEGER PRIMARY KEY,web_song_id TEXT UNIQUE,search TEXT,playable INTEGER,payload TEXT,code TEXT,title TEXT,artist TEXT);
CREATE INDEX songs_code ON songs(code);
CREATE TABLE fixture_padding(data BLOB);
""")
db.executemany('INSERT INTO catalog_meta VALUES (?,?)',[('format','xstage-sqlite3-v1'),('schemaVersion','1'),('kind','snapshot'),('generation','large-fixture')])
for i in range(1,14):
 s={'webSongId':str(i),'code':str(i),'title':'เพลงทดสอบ','artist':'ศิลปิน','xmid':{'fileId':'fixture-'+str(i)}}
 db.execute('INSERT INTO songs VALUES (?,?,?,?,?,?,?,?)',(i,str(i),'เพลงทดสอบ ศิลปิน '+str(i),1,json.dumps(s,ensure_ascii=False),str(i),s['title'],s['artist']))
db.execute('INSERT INTO fixture_padding VALUES (zeroblob(?))',(256*1024*1024,))
db.commit()
db.close()`;
let server,browser;
try{
  execFileSync('python3',['-c',python,dbPath],{timeout:120000});
  const size=fs.statSync(dbPath).size;
  assert.ok(size>192*1048576);
  const digest=createHash('md5');
  for await(const chunk of fs.createReadStream(dbPath))digest.update(chunk);
  const md5=digest.digest('hex');
  let transfers=0;
  const mime={'.js':'application/javascript','.mjs':'application/javascript','.wasm':'application/wasm'};
  const assets=new Set(['cloud-import-core.js','web-catalog-disk.js','web-catalog-opfs-client.mjs','web-catalog-opfs-worker.mjs','web-catalog-opfs-core.mjs']);
  server=http.createServer((req,res)=>{
    const url=new URL(req.url,'http://localhost');
    if(url.pathname==='/'){
      res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'});
      return res.end('<!doctype html><meta charset="utf-8"><script src="/cloud-import-core.js"></script><script src="/web-catalog-disk.js"></script>');
    }
    if(url.pathname==='/songs.sqlite3'){
      transfers++;
      res.writeHead(200,{'Content-Type':'application/octet-stream','Content-Length':size,'Cache-Control':'no-store'});
      fs.createReadStream(dbPath).pipe(res);return;
    }
    const name=url.pathname.slice(1);
    if(!assets.has(name)){res.writeHead(404).end();return;}
    res.writeHead(200,{'Content-Type':mime[path.extname(name)],'Cache-Control':'no-store'});
    fs.createReadStream(path.join(root,name)).pipe(res);
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  browser=await chromium.launch({headless:true,args:['--no-sandbox']});
  const page=await browser.newPage();
  const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:'+server.address().port+'/');
  const result=await page.evaluate(async({md5,size})=>{
    const {createWebCatalogClient}=await import('/web-catalog-opfs-client.mjs');
    const pointer={contentMD5:md5,contentBytes:size};
    const options={pointer,fetcher:()=>fetch('/songs.sqlite3')};
    const owner='large-fixture:root';
    let client=await createWebCatalogClient(owner);
    let ready,first,second,third,found,failed,stillActive,reopened;
    try{
      ready=await client.stage(options);
      await client.activate(ready);
      first=await client.search('เพลงทดสอบ');
      second=await client.search('เพลงทดสอบ',first.cursor);
      third=await client.search('เพลงทดสอบ',second.cursor);
      found=await client.lookup('13');
      try{
        await client.stage({pointer:{contentMD5:'0'.repeat(32),contentBytes:size+1},fetcher:()=>new Response(new Uint8Array(10))});
      }catch(e){failed=true;}
      stillActive=await client.lookup('13');
    }finally{await client.close();}
    client=await createWebCatalogClient(owner);
    try{
      reopened=await client.stage(options);
      await client.activate(reopened);
      return {count:ready.count,pages:[first.songs.length,second.songs.length,third.songs.length],
        ids:[...first.songs,...second.songs,...third.songs].map(x=>x.webSongId),found:found.webSongId,
        failed,stillActive:stillActive.webSongId,fromDisk:reopened.fromDisk};
    }finally{await client.close();}
  },{md5,size});
  assert.equal(result.count,13);
  assert.deepEqual(result.pages,[5,5,3]);
  assert.equal(new Set(result.ids).size,13);
  assert.equal(result.found,'13');
  assert.equal(result.failed,true);
  assert.equal(result.stillActive,'13');
  assert.equal(result.fromDisk,true);
  assert.equal(transfers,1,'Reopen must not download the verified catalog again');
  assert.deepEqual(errors,[]);
  console.log('PASS: real '+size+'-byte SQLite in Chromium OPFS, five-row paging, lookup, failed revision retains active DB, persistent reopen');
}finally{
  if(browser)await browser.close();
  if(server)await new Promise(resolve=>server.close(resolve));
  fs.rmSync(tmp,{recursive:true,force:true});
}
