/* Real SQLite WASM/Asyncify in Chromium; a generated fixture is served via
 * strict byte ranges. The real private catalog is never uploaded to GitHub. */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {chromium} from 'playwright';
const root=process.cwd(),dir=fs.mkdtempSync(path.join(os.tmpdir(),'xstage-range-'));
const db=path.join(dir,'fixture.sqlite3');
let server,browser;
try{
 execFileSync('python3',['-c',`import sqlite3,sys
db=sqlite3.connect(sys.argv[1])
db.executescript("CREATE TABLE songs(id INTEGER PRIMARY KEY, path TEXT UNIQUE,code TEXT,title TEXT COLLATE NOCASE,artist TEXT,search TEXT,playable INTEGER); CREATE INDEX songs_code ON songs(code); CREATE INDEX songs_title ON songs(title COLLATE NOCASE,id); CREATE VIRTUAL TABLE song_fts USING fts5(search,content='songs',content_rowid='id',tokenize='trigram'); CREATE TABLE padding(data BLOB);")
db.executemany("INSERT INTO songs VALUES (?,?,?,?,?,?,1)",[(i,'XMID/0/'+str(i)+'.xmid',str(i),'รักทดสอบ '+str(i),'ศิลปิน','รักทดสอบ '+str(i)+' ศิลปิน') for i in range(1,24)])
db.execute("INSERT INTO song_fts(song_fts) VALUES ('rebuild')")
db.execute("INSERT INTO padding VALUES (zeroblob(?))",(200*1024*1024,))
db.commit()
db.close()`,db],{timeout:120000});
 const size=fs.statSync(db).size;
 let requests=0,bytes=0;
 server=http.createServer((req,res)=>{
  const url=new URL(req.url,'http://localhost');
  if(url.pathname==='/'){
   res.writeHead(200,{'Content-Type':'text/html'});return res.end('<!doctype html><meta charset="utf-8">');
  }
  if(url.pathname==='/fixture.sqlite3'){
   const m=/^bytes=(\d+)-(\d+)$/.exec(req.headers.range||'');
   if(!m||req.headers['if-match']!=='"fixture-v1"'){res.writeHead(412).end();return;}
   const start=Number(m[1]),end=Number(m[2]);
   if(end>=size||start>end||end-start+1>262144){res.writeHead(416).end();return;}
   requests++;bytes+=end-start+1;
   res.writeHead(206,{'Content-Type':'application/octet-stream','Content-Length':end-start+1,'Content-Range':'bytes '+start+'-'+end+'/'+size,ETag:'"fixture-v1"','Cache-Control':'no-store'});
   fs.createReadStream(db,{start,end}).pipe(res);return;
  }
  const file=path.resolve(root,'.'+url.pathname);
  if(!file.startsWith(root+path.sep)||(!url.pathname.startsWith('/node_modules/@journeyapps/wa-sqlite/')&&!url.pathname.startsWith('/experiments/hybrid-sqlite/'))||!fs.existsSync(file)){res.writeHead(404).end();return;}
  const type=file.endsWith('.wasm')?'application/wasm':'application/javascript';
  res.writeHead(200,{'Content-Type':type});fs.createReadStream(file).pipe(res);
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const page=await browser.newPage();await page.goto('http://127.0.0.1:'+server.address().port+'/');
 const result=await page.evaluate(async size=>{
  const pkg='/node_modules/@journeyapps/wa-sqlite/';
  const [{default:factory},SQLite,{FacadeVFS},{openRangeCatalog}]=await Promise.all([
    import(pkg+'dist/wa-sqlite-async.mjs'),import(pkg+'src/sqlite-api.js'),import(pkg+'src/FacadeVFS.js'),
    import('/experiments/hybrid-sqlite/range-catalog.mjs')]);
  const module=await factory();
  const reader=await openRangeCatalog({SQLite,module,FacadeVFS,sourceOptions:{size,etag:'"fixture-v1"',readResponse:(start,end,{signal,etag})=>fetch('/fixture.sqlite3',{headers:{Range:'bytes='+start+'-'+end,'If-Match':etag},signal})}});
  try{
   const a=await reader.search('รัก'),b=await reader.search('รัก',{cursor:a.cursor}),c=await reader.search('1'),d=await reader.search('ร',{mode:'title'});
   return {schema:reader.schema,pages:[a.songs.length,b.songs.length],ids:[...a.songs,...b.songs].map(x=>x.id),code:c.songs[0]?.code,titleCount:d.songs.length,stats:reader.stats()};
  }finally{await reader.close();}
 },size);
 assert.equal(result.schema.kind,'pc-local');assert.equal(result.schema.fts,true);
 assert.deepEqual(result.pages,[5,5]);assert.equal(new Set(result.ids).size,10);
 assert.equal(result.code,'1');assert.equal(result.titleCount,5);
 assert.equal(requests,result.stats.requests);assert.equal(bytes,result.stats.bytes);
 assert.ok(bytes<size/10,'Indexed queries must not fetch the entire DB');
 console.log('PASS: SQLite WASM over actual HTTP 206, '+requests+' ranges / '+bytes+' bytes of '+size);
}finally{if(browser)await browser.close();if(server)await new Promise(resolve=>server.close(resolve));fs.rmSync(dir,{recursive:true,force:true});}
