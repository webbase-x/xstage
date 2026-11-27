/* Actual SQLite WASM + verified XMID reader + MIDI parser in Chromium.
 * Generated source fixture; no real user files, account or hardware. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {chromium} from 'playwright';
const root=process.cwd(),dir=fs.mkdtempSync(path.join(os.tmpdir(),'xstage-verified-'));
const src=path.join(dir,'songs.sqlite3'),idx=path.join(dir,'songs.search.sqlite3'),verified=path.join(dir,'songs.verified.sqlite3');
const original=path.join(dir,'XMID'),xmid=path.join(original,'0','1.xmid');
let server,browser;
try{
 fs.mkdirSync(path.dirname(xmid),{recursive:true});
 execFileSync('python3',['-c',`import hashlib,sqlite3,struct,sys
src,xmid=sys.argv[1:]
def text(s):
 b=s.encode('utf8')
 return struct.pack('<I',len(b))+b
meta=b''.join(text(s) for s in ['fixture','1','v1','เพลงทดสอบ','ศิลปิน','verified'])+struct.pack('<I',0)
track=bytes([0,0x90,60,100,96,0x80,60,0,0,255,47,0])
midi=b'MThd'+struct.pack('>IHHH',6,0,1,96)+b'MTrk'+struct.pack('>I',len(track))+track
with open(xmid,'wb') as f:f.write(struct.pack('<8sIQQ32s32s',b'XSTGPLS1',1,len(meta),len(midi),hashlib.sha256(midi).digest(),hashlib.sha256(meta).digest())+meta+midi)
db=sqlite3.connect(src)
db.execute('CREATE TABLE songs(id INTEGER PRIMARY KEY,code TEXT,title TEXT,artist TEXT,path TEXT,playable INTEGER)')
db.execute('INSERT INTO songs VALUES(1,?,?,?,?,1)',('1','เพลงทดสอบ','ศิลปิน','SONGS/MIDI/XMID/0/1.xmid'))
db.commit();db.close()`,src,xmid]);
 execFileSync('python3',[path.join(root,'experiments/compact-search-index/build_search_index.py'),src,idx]);
 execFileSync('python3',['-m','karaoke.compact_verified_index',src,idx,original,verified,path.join(dir,'verify-journal.sqlite3')],{cwd:path.join(root,'windows-pc/source')});
 const md5=p=>createHash('md5').update(fs.readFileSync(p)).digest('hex');
 const source={md5:md5(src),size:fs.statSync(src).size};
 const pointer={contentMD5:md5(verified),contentBytes:fs.statSync(verified).size,verifiedSource:source};
 let transfers=0,sourceTransfers=0;
 const assets=new Set(['cloud-import-core.js','web-catalog-disk.js','web-catalog-opfs-client.mjs','web-catalog-opfs-worker.mjs','web-catalog-opfs-core.mjs','xmid-browser.js','browser-midi.js']);
 server=http.createServer((req,res)=>{
  const name=new URL(req.url,'http://localhost').pathname.slice(1);
  if(!name){res.writeHead(200,{'Content-Type':'text/html; charset=utf-8'});return res.end('<!doctype html><meta charset="utf-8"><script src="/cloud-import-core.js"></script><script src="/web-catalog-disk.js"></script><script src="/xmid-browser.js"></script><script src="/browser-midi.js"></script>');}
  if(name==='songs.sqlite3'){sourceTransfers++;return res.writeHead(500).end();}
  if(name==='songs.verified.sqlite3'||name==='fixture.xmid'){
   const file=name==='fixture.xmid'?xmid:verified;
   if(file===verified)transfers++;
   res.writeHead(200,{'Content-Type':'application/octet-stream','Content-Length':fs.statSync(file).size,'Cache-Control':'no-store'});return fs.createReadStream(file).pipe(res);
  }
  if(!assets.has(name))return res.writeHead(404).end();
  res.writeHead(200,{'Content-Type':'application/javascript','Cache-Control':'no-store'});fs.createReadStream(path.join(root,name)).pipe(res);
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const page=await browser.newPage();
 await page.goto('http://127.0.0.1:'+server.address().port+'/');
 const result=await page.evaluate(async pointer=>{
  const {createWebCatalogClient}=await import('/web-catalog-opfs-client.mjs');
  const owner='verified-fixture:root',options={pointer,fetcher:()=>fetch('/songs.verified.sqlite3')};
  let client=await createWebCatalogClient(owner);
  let stale=false,wrong=false,corrupt=false,notes=0,retained=false;
  try{
   const staged=await client.stage(options);await client.activate(staged);
   const result=await client.search('เพลง');const song=result.songs[0];
   const packed=await (await fetch('/fixture.xmid')).blob();
   const unpacked=await XStageXmid.openVerifiedPackage(packed,song);
   const parsed=XStageBrowserMidi.parseMidi(new Uint8Array(await unpacked.midi.arrayBuffer()));
   notes=parsed.notes.length;
   try{await XStageXmid.openVerifiedPackage(packed,{...song,title:'wrong'});}catch{wrong=true;}
   const broken=new Uint8Array(await packed.arrayBuffer());broken[broken.length-1]^=1;
   try{await XStageXmid.openVerifiedPackage(new Blob([broken]),song);}catch{corrupt=true;}
   try{await client.stage({...options,pointer:{...pointer,verifiedSource:{...pointer.verifiedSource,md5:'0'.repeat(32)}}});}catch{stale=true;}
   retained=(await client.lookup(song.webSongId))?.webSongId===song.webSongId;
  }finally{await client.close();}
  client=await createWebCatalogClient(owner);
  try{
   const staged=await client.stage(options);await client.activate(staged);
   return {count:staged.count,fromDisk:staged.fromDisk,stale,wrong,corrupt,notes,retained};
  }finally{await client.close();}
 },pointer);
 assert.deepEqual(result,{count:1,fromDisk:true,stale:true,wrong:true,corrupt:true,notes:1,retained:true});
 assert.equal(transfers,1);assert.equal(sourceTransfers,0);
 console.log('PASS: actual producer sidecar in Chromium OPFS, original MD5/SHA256, XMID decode and MIDI note parse; stale/corrupt/wrong identity blocked; cached reopen. No audio hardware test.');
}finally{if(browser)await browser.close();if(server)await new Promise(r=>server.close(r));fs.rmSync(dir,{recursive:true,force:true});}
