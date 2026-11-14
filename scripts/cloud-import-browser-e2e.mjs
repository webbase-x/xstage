/* Real Chromium UI flow with an in-memory, authenticated mock Drive API.
 * No Google credentials or user data are used in CI.
 */
import http from 'node:http';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {chromium} from 'playwright';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const mime={'.html':'text/html;charset=utf-8','.js':'application/javascript;charset=utf-8',
  '.css':'text/css;charset=utf-8','.json':'application/json;charset=utf-8',
  '.png':'image/png','.jpg':'image/jpeg','.svg':'image/svg+xml','.webmanifest':'application/manifest+json'};
const server=http.createServer((req,res)=>{
  const pathname=decodeURIComponent(new URL(req.url,'http://localhost').pathname);
  const target=path.resolve(root,'.'+pathname);
  if(!target.startsWith(root+path.sep)&&target!==root){res.writeHead(403).end();return;}
  const filename=fs.existsSync(target)&&fs.statSync(target).isDirectory()?path.join(target,'index.html'):target;
  if(!fs.existsSync(filename)){res.writeHead(404).end();return;}
  res.writeHead(200,{'Content-Type':mime[path.extname(filename)]||'application/octet-stream',
    'Cache-Control':'no-store'});fs.createReadStream(filename).pipe(res);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const port=server.address().port,records=new Map(),children=new Map(),sessions=new Map();
let serial=0,sessionIndex=0,payloadUploads=0,rootCreated=0;
const id=()=>('drive'+String(++serial).padStart(8,'0'));
const group=parent=>{if(!children.has(parent))children.set(parent,[]);return children.get(parent);};
const ref={rootId:null};
async function routeDrive(route){
  const req=route.request(),url=new URL(req.url()),method=req.method();
  const cors={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Methods':'GET,POST,PATCH,PUT,OPTIONS',
    'Access-Control-Allow-Headers':'authorization,content-type,content-range,x-upload-content-type,x-upload-content-length',
    'Access-Control-Expose-Headers':'Location,Range,Content-Length'};
  const send=(status,json,extra={})=>route.fulfill({status,headers:{...cors,...extra,
    'Content-Type':'application/json;charset=utf-8'},body:json==null?'':JSON.stringify(json)});
  if(method==='OPTIONS')return send(204,null);
  assert.ok(req.headers().authorization==='Bearer TEST_BEARER_FOR_E2E_1234567890123456',
    'All Drive requests must use the same verified account token');
  if(url.pathname==='/drive/v3/files'&&method==='GET'){
    const q=url.searchParams.get('q')||'';
    const parent=q.match(/'([^']+)' in parents/)?.[1]||'root';
    let items=group(parent);
    if(q.includes("name='current.json'"))items=items.filter(x=>x.name==='current.json');
    if(q.includes("name='StageWeb' or name='XStageWeb'"))items=items.filter(x=>['StageWeb','XStageWeb'].includes(x.name));
    return send(200,{files:items});
  }
  if(url.pathname==='/drive/v3/files'&&method==='POST'){
    const meta=JSON.parse(req.postData());
    assert.equal(meta.mimeType,'application/vnd.google-apps.folder');
    const item={...meta,id:id(),ownedByMe:true};
    group(meta.parents[0]).push(item);group(item.id);
    if(meta.parents[0]==='root')rootCreated++;
    return send(200,item);
  }
  if(url.pathname==='/upload/drive/v3/files'&&method==='POST'){
    const meta=JSON.parse(req.postData());
    const uploadId='upload'+(++sessionIndex);
    sessions.set(uploadId,{meta,parts:[],size:0});
    return send(200,null,{Location:'https://www.googleapis.com/upload/drive/v3/files?upload_id='+uploadId});
  }
  if(url.pathname==='/upload/drive/v3/files'&&method==='PUT'){
    const session=sessions.get(url.searchParams.get('upload_id'));
    assert.ok(session,'Unknown Google upload session');
    const range=req.headers()['content-range'];
    if(range.startsWith('bytes */'))return send(308,null,session.size?{Range:'bytes=0-'+(session.size-1)}:{});
    const m=range.match(/^bytes (\d+)-(\d+)\/(\d+)$/);
    assert.ok(m,'Invalid browser Content-Range header');
    const bytes=req.postDataBuffer(),start=Number(m[1]),end=Number(m[2]),total=Number(m[3]);
    assert.equal(start,session.size);
    assert.equal(bytes.length,end-start+1);
    session.size+=bytes.length;session.parts.push(bytes);
    if(session.size<total)return send(308,null,{Range:'bytes=0-'+(session.size-1)});
    const data=Buffer.concat(session.parts);
    const record={...session.meta,id:id(),ownedByMe:true,md5Checksum:createHash('md5').update(data).digest('hex'),
      size:String(data.length)};
    group(session.meta.parents[0]).push(record);
    records.set(record.id,{...record,data});payloadUploads++;
    return send(200,record);
  }
  if(url.pathname.startsWith('/drive/v3/files/')&&method==='GET'){
    const itemId=url.pathname.split('/').pop();
    const item=records.get(itemId);assert.ok(item,'Unknown Drive file ID '+itemId);
    if(url.searchParams.get('alt')==='media')
      return route.fulfill({status:200,headers:{...cors,'Content-Type':'application/json',
        'Content-Length':String(item.data.length)},body:item.data});
    return send(200,item);
  }
  if(url.pathname.startsWith('/upload/drive/v3/files/')&&method==='PATCH'){
    const itemId=url.pathname.split('/').pop();
    const existing=records.get(itemId);
    assert.ok(existing,'Update must target an existing current.json ID');
    const bytes=req.postDataBuffer();
    existing.data=bytes;existing.size=String(bytes.length);
    existing.md5Checksum=createHash('md5').update(bytes).digest('hex');
    return send(200,existing);
  }
  return send(400,{error:'Unexpected mock Drive operation: '+method+' '+url.pathname});
}
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'xstage-cloud-e2e-'));
function soundfontFixture(){
  function part(label){const content=Buffer.alloc(84);content.write(label,0,'ascii');
    const header=Buffer.alloc(8);header.write('LIST');header.writeUInt32LE(content.length,4);
    return Buffer.concat([header,content]);}
  const body=Buffer.concat([Buffer.from('sfbk'),part('INFO'),part('sdta'),part('pdta')]);
  const prefix=Buffer.alloc(8);prefix.write('RIFF');prefix.writeUInt32LE(body.length,4);
  return Buffer.concat([prefix,body]);
}
fs.writeFileSync(path.join(dir,'X100.mp3'),Buffer.concat([Buffer.from('ID3'),Buffer.alloc(4096)]));
fs.writeFileSync(path.join(dir,'X100.lrc'),'[ti:ทดสอบเว็บ]\n[ar:ศิลปินทดสอบ]\n[00:01.00]สวัสดี\n[00:04.00]ขอบคุณ\n');
fs.writeFileSync(path.join(dir,'General.sf2'),soundfontFixture());
fs.writeFileSync(path.join(dir,'Unconverted.mid'),Buffer.from('MThd0000'));
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
try{
  const context=await browser.newContext({serviceWorkers:'block'});
  await context.addInitScript(()=>{
    localStorage.setItem('xstage-google-token-v2',JSON.stringify({
      token:'TEST_BEARER_FOR_E2E_1234567890123456',sub:'SUB_MOCK_E2E',
      expiresAt:Date.now()+3600000}));
  });
  const page=await context.newPage();
  const scriptErrors=[];page.on('pageerror',error=>scriptErrors.push(error.message));
  await page.route('https://accounts.google.com/**',route=>route.fulfill({status:200,
    headers:{'Access-Control-Allow-Origin':'*','Content-Type':'application/javascript'},body:''}));
  await page.route('https://openidconnect.googleapis.com/**',route=>route.fulfill({status:200,
    headers:{'Access-Control-Allow-Origin':'*','Content-Type':'application/json'},
    body:JSON.stringify({sub:'SUB_MOCK_E2E',email:'owner@example.com',email_verified:true})}));
  await page.route('https://www.googleapis.com/**',routeDrive);
  await page.goto('http://127.0.0.1:'+port+'/',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>{const el=document.getElementById('cloud-import-open-gate');return el&&!el.hidden;},null,{timeout:20000});
  await page.click('#cloud-import-open-gate');
  await page.locator('#cloud-import-dialog[open]').waitFor();
  await page.locator('#cloud-import-input').setInputFiles(dir);
  await page.waitForFunction(()=>document.getElementById('cloud-import-ready').textContent==='1');
  assert.equal(await page.locator('#cloud-import-fonts').textContent(),'1');
  assert.equal(await page.locator('#cloud-import-blocked').textContent(),'1');
  await page.check('#cloud-import-allow-create');
  await page.click('#cloud-import-start');
  await page.waitForFunction(()=>document.getElementById('cloud-import-status').textContent.startsWith('เสร็จสิ้น'),
    {timeout:60000});
  const status=await page.locator('#cloud-import-status').textContent();
  assert.ok(status.includes('เพลงใหม่ 1'),status);
  assert.ok(status.includes('SoundFont 1'),status);
  assert.equal(rootCreated,1,'Only one private XStageWeb root should be created');
  assert.ok([...records.values()].some(x=>x.name==='current.json'),'Playable DB pointer must be created');
  const pointer=[...records.values()].find(x=>x.name==='current.json');
  assert.equal(JSON.parse(pointer.data.toString('utf8')).songCount,1);
  assert.ok([...records.values()].some(x=>x.name.endsWith('.sf2')));
  const firstCount=payloadUploads;
  // After first DB exists, reopen the importer from the visible stage menu.
  await page.click('#cloud-import-close');
  await page.click('#mobile-menu-toggle');
  await page.locator('#mobile-stage-menu').waitFor({state:'visible'});
  await page.click('#cloud-import-open');
  await page.locator('#cloud-import-dialog[open]').waitFor();
  await page.click('#cloud-import-start');
  await page.waitForFunction(()=>document.getElementById('cloud-import-status').textContent.startsWith('เสร็จสิ้น')&&
    document.getElementById('cloud-import-status').textContent.includes('ข้ามซ้ำ 1'),{timeout:60000});
  assert.equal(payloadUploads,firstCount,'Second upload should be 100% deduplicated by MD5');
  assert.deepEqual(scriptErrors,[], 'No browser JavaScript errors are allowed');
  console.log('PASS: Chromium folder selection, Google session, private Drive uploads, pointer/catalog and replay-safe MD5 dedup');
  await context.close();
}finally{
  await browser.close();server.close();fs.rmSync(dir,{recursive:true,force:true});
}
