import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {chromium} from 'playwright';
const root=process.cwd(),dir=fs.mkdtempSync(path.join(os.tmpdir(),'xstage-compact-'));
const src=path.join(dir,'songs.sqlite3'),idx=path.join(dir,'songs.search.sqlite3');
const prefix='/experiments/compact-search-index/';
let server,browser;
try{
 execFileSync('python3',['-c',`import sqlite3,sys
c=sqlite3.connect(sys.argv[1])
c.execute("CREATE TABLE songs(id INTEGER PRIMARY KEY,code TEXT,title TEXT,artist TEXT,path TEXT,playable INTEGER)")
for i in range(1,14):
 for n,base in [(i,'D:/XMID/0/'),(i+100,'G:/My Drive/XStageKaraoke/SONGS/MIDI/XMID/0/')]:
  c.execute("INSERT INTO songs VALUES(?,?,?,?,?,1)",(n,str(i),'รักเพลง '+str(i),'ศิลปิน',base+str(i)+'.xmid'))
c.commit();c.close()`,src]);
 execFileSync('python3',[path.join(root,prefix.slice(1),'build_search_index.py'),src,idx]);
 const md5=p=>createHash('md5').update(fs.readFileSync(p)).digest('hex');
 const size=fs.statSync(idx).size,source={md5:md5(src),size:fs.statSync(src).size},indexMd5=md5(idx);
 let transfers=0,sourceTransfers=0;
 const files=[
  {id:'rootFixture',name:'XStageKaraoke',mimeType:'application/vnd.google-apps.folder',parents:['root']},
  {id:'dbFixture',name:'DB',mimeType:'application/vnd.google-apps.folder',parents:['rootFixture']},
  {id:'sourceFixture',name:'songs.sqlite3',mimeType:'application/vnd.sqlite3',parents:['dbFixture'],size:String(source.size),md5Checksum:source.md5},
  {id:'indexFixture',name:'songs.search.sqlite3',mimeType:'application/vnd.sqlite3',parents:['dbFixture'],size:String(size),md5Checksum:indexMd5}];
 server=http.createServer((req,res)=>{
  const p=new URL(req.url,'http://localhost').pathname;
  const local=path.resolve(root,'.'+p);
  if(!local.startsWith(root+path.sep)||!fs.existsSync(local)||!fs.statSync(local).isFile()){res.writeHead(404).end();return;}
  res.writeHead(200,{'Content-Type':local.endsWith('.html')?'text/html; charset=utf-8':'application/javascript','Cache-Control':'no-store'});
  fs.createReadStream(local).pipe(res);
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('https://accounts.google.com/gsi/client',r=>r.fulfill({contentType:'application/javascript',body:"window.google={accounts:{oauth2:{hasGrantedAllScopes:()=>true,initTokenClient:o=>({requestAccessToken:()=>o.callback({access_token:'fixture-token'})})}}}"}));
 await page.route('https://www.googleapis.com/drive/v3/**',async r=>{
  const u=new URL(r.request().url());
  const headers={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'authorization','Access-Control-Allow-Methods':'GET,OPTIONS'};
  if(r.request().method()==='OPTIONS')return r.fulfill({status:204,headers});
  if(u.pathname.endsWith('/about'))return r.fulfill({json:{user:{permissionId:'fixture-owner'}},headers});
  if(u.pathname.endsWith('/files')){
   const q=u.searchParams.get('q')||'';
   const hits=q.includes("'dbFixture'")?files.slice(2):q.includes("'rootFixture'")?files.slice(1,2):files.slice(0,1);
   return r.fulfill({json:{files:hits},headers});
  }
  if(u.pathname.endsWith('/sourceFixture')){sourceTransfers++;return r.fulfill({status:500,headers});}
  if(u.pathname.endsWith('/indexFixture')){transfers++;return r.fulfill({body:fs.readFileSync(idx),headers:{...headers,'Content-Type':'application/octet-stream','Content-Length':String(size)}});}
  return r.fulfill({status:404,headers});
 });
 const url='http://127.0.0.1:'+server.address().port+prefix+'index.html';
 async function open(){
  await page.goto(url);await page.waitForFunction(()=>!!window.google?.accounts?.oauth2);
  await page.click('#connect');await page.waitForSelector('#choose',{state:'visible'});await page.click('#run');
  await page.waitForSelector('#search-form',{state:'visible',timeout:120000});
  return JSON.parse(await page.locator('#result').textContent());
 }
 const first=await open();assert.equal(first.count,13);assert.equal(first.fromDisk,false);
 await page.fill('#term','รัก');await page.click('#search');await page.waitForFunction(()=>document.querySelector('#songs').children.length===5);
 await page.click('#more');await page.waitForFunction(()=>document.querySelector('#songs').children.length===10);
 await page.click('#more');await page.waitForFunction(()=>document.querySelector('#songs').children.length===13);
 const rows=await page.locator('#songs > div > span').allTextContents();assert.equal(new Set(rows).size,13);
 await page.click('#clear');const again=await open();assert.equal(again.fromDisk,true);
 assert.equal(transfers,1);assert.equal(sourceTransfers,0);assert.deepEqual(errors,[]);
 console.log('PASS: actual Chromium compact OPFS search, 5/5/3, dedup, verified cache reopen, zero source catalog downloads');
}finally{if(browser)await browser.close();if(server)await new Promise(r=>server.close(r));fs.rmSync(dir,{recursive:true,force:true});}
