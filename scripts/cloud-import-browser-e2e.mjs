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
import initSqlJs from 'sql.js';
import {execFileSync} from 'node:child_process';
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
    // Match Google Drive's server-side name predicate, including DB lookups
    // during player auth restore. Returning all sibling folders made a valid
    // XStageKaraoke appear to contain duplicate DBs and logged the user out.
    const requestedName=q.match(/(?:^|\s)name='([^']+)'/)?.[1];
    if(requestedName)items=items.filter(item=>item.name===requestedName);
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
  if(url.pathname==='/upload/drive/v3/files'&&method==='POST'&&
     url.searchParams.get('uploadType')==='multipart'){
    const boundary=req.headers()['content-type']?.match(/boundary=([^;]+)/)?.[1];
    assert.ok(boundary,'Multipart upload requires a boundary');
    const buffer=req.postDataBuffer(),marker=Buffer.from('\r\n--'+boundary);
    const metaStart=buffer.indexOf(Buffer.from('\r\n\r\n'))+4;
    const metaEnd=buffer.indexOf(marker,metaStart);
    assert.ok(metaStart>=4&&metaEnd>metaStart,'Multipart metadata section missing');
    const meta=JSON.parse(buffer.subarray(metaStart,metaEnd).toString('utf8'));
    const mediaStart=buffer.indexOf(Buffer.from('\r\n\r\n'),metaEnd)+4;
    const mediaEnd=buffer.indexOf(marker,mediaStart);
    assert.ok(mediaStart>metaEnd&&mediaEnd>mediaStart,'Multipart media section missing');
    const data=buffer.subarray(mediaStart,mediaEnd);
    const record={...meta,id:id(),ownedByMe:true,
      md5Checksum:createHash('md5').update(data).digest('hex'),size:String(data.length)};
    group(meta.parents[0]).push(record);
    records.set(record.id,{...record,data});payloadUploads++;
    return send(200,record);
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
  if(url.pathname.startsWith('/drive/v3/files/')&&method==='PATCH'){
    const itemId=url.pathname.split('/').pop();
    const item=records.get(itemId);assert.ok(item,'Move or trash must target a real Drive file');
    const metadata=JSON.parse(req.postData()||'{}');
    if(metadata.trashed===true){
      for(const values of children.values()){
        const index=values.findIndex(x=>x.id===itemId);
        if(index>=0){values.splice(index,1);break;}
      }
      item.trashed=true;
      return send(200,{id:itemId,trashed:true});
    }
    const from=url.searchParams.get('removeParents');
    const to=url.searchParams.get('addParents');
    assert.ok(from&&to&&from!==to,'Move must specify source and target folder');
    const before=group(from);
    const index=before.findIndex(x=>x.id===itemId);
    assert.ok(index>=0,'Moved file must be in its current folder');
    before.splice(index,1);
    Object.assign(item,metadata,{parents:[to]});
    group(to).push(item);
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
const m4a=Buffer.alloc(4096);m4a.write('ftyp',4,'ascii');
fs.writeFileSync(path.join(dir,'J200.m4a'),m4a);
const mp4=Buffer.alloc(4096);mp4.write('ftyp',4,'ascii');mp4.write('XSTAGE-UNIQUE-VDO',32,'ascii');
fs.writeFileSync(path.join(dir,'V400.mp4'),mp4); // embedded VDO metadata; codec not exercised here
execFileSync('ffmpeg',['-hide_banner','-loglevel','error','-y',
  '-f','lavfi','-i','testsrc2=duration=1:size=128x72:rate=8',
  '-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-t','1',
  '-c:v','mpeg4','-c:a','mp3','-f','avi',path.join(dir,'A500.avi')],{timeout:30000});
fs.writeFileSync(path.join(dir,'J200.json'),JSON.stringify({
  schemaVersion:1,songCode:'J200',lines:[{startTime:1,endTime:4,text:'Lyrics JSON พร้อมเวลา'}]
}));
fs.writeFileSync(path.join(dir,'General.sf2'),soundfontFixture());
fs.writeFileSync(path.join(dir,'Unconverted.mid'),Buffer.from('MThd0000'));
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
try{
  const context=await browser.newContext({serviceWorkers:'block'});
  await context.addInitScript(()=>{
    try{Object.defineProperty(window,'showDirectoryPicker',{value:undefined,configurable:true});}catch{}
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
  // This test owns Drive imports, not portal download behavior.
  // Keep portal tests opt-in so a Mirroring APK cannot block cloud regression.
  if(process.env.XSTAGE_TEST_STOREFRONT==='1'){
  // The public project homepage is a standalone app collection. Verify it in
  // a real browser before proceeding into the preserved karaoke player.
  await page.goto('http://127.0.0.1:'+port+'/',{waitUntil:'domcontentloaded'});
  await page.locator('#intro-title').waitFor();
  const catalogCount=await page.locator('.app-card').count();
  assert.ok(catalogCount>=10,'storefront must display the full supported app collection');
  // Legacy source query must not turn a TV browser into the Karaoke player.
  await page.goto('http://127.0.0.1:'+port+'/?source=android-tv',
                  {waitUntil:'domcontentloaded'});
  await page.locator('#intro-title').waitFor();
  assert.ok(!page.url().includes('karaoke.html'),'TV browser must remain in the apps hub');
  await page.goto('http://127.0.0.1:'+port+'/',{waitUntil:'domcontentloaded'});
  await page.locator('#intro-title').waitFor();

  const logoSources=await page.locator('.app-card .app-art img').evaluateAll(nodes=>nodes.map(n=>new URL(n.src).pathname));
  assert.equal(logoSources.length,catalogCount,'all app entries must have a visual identity');
  assert.equal(new Set(logoSources).size,catalogCount,'each X-Stage application must have a distinct icon asset');

  await page.locator('#device-advice-title').waitFor();
  assert.equal(await page.locator('[data-device-app]').count(),catalogCount,'all apps expose device compatibility');
  const iphoneGuidance=await page.evaluate(()=>{
    const api=window.XStageDeviceGuide;
    const p=api.detect({userAgent:'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)',platform:'iPhone'});
    return {name:p.label,mirror:api.forApp(p,'mirror-tv'),windows:api.forApp(p,'karaoke-pc')};
  });
  assert.equal(iphoneGuidance.mirror.level,'other','iPhone must be a Mirror sender, not an Android TV APK receiver');
  assert.ok(iphoneGuidance.mirror.text.includes('Android TV'),'iOS users must be told the compatible TV type');
  assert.equal(iphoneGuidance.windows.level,'other','iOS users must not be offered Windows PC installation as compatible');

  assert.equal(await page.locator('.app-card .app-art img').evaluateAll(nodes=>nodes.every(n=>n.complete&&n.naturalWidth>0)),true,
    'unique app icons must load in the real browser');

  assert.match(await page.locator('#intro-title').textContent(),/หนึ่งเวที/);
  assert.equal(await page.locator('.new-wordmark img').evaluate(img=>img.complete&&img.naturalWidth>0),true,
    'new X-Stage Apps wordmark must load in browser');
  assert.equal(await page.locator('.brand-hero-insignia img').evaluate(img=>img.complete&&img.naturalWidth>0),true,
    'new X-Stage Apps icon must load in browser');
  await page.locator('[data-filter="studio"]').click();
  assert.equal(await page.locator('.app-card:visible').count(),1,'studio filter must expose the consolidated Song Studio Pro');
  await page.locator('[data-filter="all"]').click();
  await page.locator('.app-card[data-app="studio-pro"] .app-detail-link').click();
  await page.locator('#app-detail:not([hidden])').waitFor();
  assert.equal(await page.locator('#detail-title').textContent(),'X-Stage Song Studio Pro');
  // The Linux CI machine must see a Windows-only compatibility warning rather than
  // a misleading "install here" label; the verified ZIP link remains accessible.
  const windowsDownload=page.locator('#detail-actions .detail-action.primary[href$=".zip"],#detail-actions .detail-action.primary[href$=".exe"]').first();
  await windowsDownload.waitFor({timeout:10000});
  assert.ok((await windowsDownload.textContent()).includes('อุปกรณ์ที่รองรับ'),
    'non-Windows viewers must be guided to transfer the ZIP to Windows');
  await page.locator('#detail-back').click();
  await page.locator('#catalog:not([hidden])').waitFor();
  console.log('PASS: X-Stage Apps premium brand, current catalog, filters, deep-linked details, and verified download CTA');

  // Simulate the verified direct-download feed before the binary is mirrored by CI.
  // Android TV/TrueID browsers must never be forced into a GitHub popup.
  // The production Mirror TV channel can already be available. Force its
  // unavailability only in this isolated browser test so the test actually
  // exercises the preview direct-download fallback, not the stable APK URL.
  await page.route('**/mirror-tv/latest.json',route=>route.fulfill({status:404,body:''}));
  const mirrorFeed=JSON.parse(fs.readFileSync(path.join(root,'mirror-tv/test-latest.json'),'utf8'));
  const mirrorName=mirrorFeed.file;
  await page.route('**/mirror-tv/test-latest.json',route=>route.fulfill({
    status:200,headers:{'Content-Type':'application/json;charset=utf-8','Cache-Control':'no-store'},
    body:JSON.stringify({...mirrorFeed,direct_download_available:true,
      direct_download_file:mirrorName,direct_download_sha256:mirrorFeed.sha256,
      direct_download_url:'https://webbase-x.github.io/xstage/downloads/'+mirrorName})
  }));
  await page.goto('http://127.0.0.1:'+port+'/?app=mirror-tv',{waitUntil:'domcontentloaded'});
  const mirrorAction=page.locator('#detail-actions a.detail-action.primary[href$=".apk"]');
  await mirrorAction.waitFor({timeout:15000});
  assert.equal(await mirrorAction.getAttribute('href'),'./downloads/'+mirrorName,
    'TrueID APK must be a first-party website download, not a GitHub release redirect');
  assert.equal(await mirrorAction.getAttribute('target'),null,
    'TrueID APK must open without target=_blank, which TV browsers may block');
  assert.equal(await mirrorAction.getAttribute('download'),mirrorName,
    'Android TV browsers should receive an explicit APK download hint');
  const quick=page.locator('[data-download-app="mirror-tv"]');
  assert.equal(await quick.getAttribute('hidden'),null,'Mirror TV card must display a direct APK action');
  await page.unroute('**/mirror-tv/test-latest.json');
  await page.unroute('**/mirror-tv/latest.json');
  console.log('PASS: TrueID/Android TV same-origin APK navigation and visible card download');

  await page.goto('http://127.0.0.1:'+port+'/karaoke.html',{waitUntil:'domcontentloaded'});
  }else{
    await page.goto('http://127.0.0.1:'+port+'/karaoke.html',{waitUntil:'domcontentloaded'});
  }
  // The experimental MIDI mixer was rolled back; do not require it for
  // validating fresh Drive imports.
  await page.waitForFunction(()=>{const el=document.getElementById('cloud-import-open-gate');return el&&!el.hidden;},null,{timeout:20000});
  await page.click('#cloud-import-open-gate');
  await page.locator('#cloud-import-dialog[open]').waitFor();
  // Local file import is intentionally an expandable fallback. Expand it
  // before clicking controls which must not overlay the main Drive-first UI.
  await page.locator('#cloud-import-local-options summary').click();
  // Chromium may reject sensitive directories with AbortError, even when the
  // user did not intend to cancel. Keep an explicit legacy picker available.
  await page.evaluate(()=>Object.defineProperty(window,'showDirectoryPicker',{
    configurable:true,value:()=>Promise.reject(new DOMException('Restricted directory','AbortError'))
  }));
  await page.click('#cloud-import-pick');
  await page.waitForFunction(()=>document.getElementById('cloud-import-status').textContent.includes('Chrome'));
  const fallbackChooser=page.waitForEvent('filechooser');
  await page.click('#cloud-import-pick-fallback');
  await (await fallbackChooser).setFiles(dir);
  await page.waitForFunction(()=>document.getElementById('cloud-import-ready').textContent==='2');
  // A successful name scan must provide an immediately usable Start action;
  // the tall metadata editor may scroll, but the action bar must not disappear.
  const originalViewport=page.viewportSize();
  for(const [width,height] of [[390,680],[600,800],[768,720],[1280,800]]){
    await page.setViewportSize({width,height});
    const layout=await page.evaluate(()=>{
      const dialog=document.getElementById('cloud-import-dialog');
      const body=document.getElementById('cloud-import-body');
      const footer=dialog.querySelector('.cloud-import-footer');
      const start=document.getElementById('cloud-import-start');
      body.scrollTop=body.scrollHeight;
      const bounds=node=>{const r=node.getBoundingClientRect();return {
        top:r.top,bottom:r.bottom,left:r.left,right:r.right,height:r.height
      };};
      return {button:bounds(start),footer:bounds(footer),dialog:bounds(dialog),
        scrollable:getComputedStyle(body).overflowY,
        disabled:start.disabled,hidden:start.hidden,
        hint:document.getElementById('cloud-import-action-hint').textContent,
        selected:document.getElementById('cloud-import-selection-count').textContent};
    });
    assert.ok(!layout.disabled&&!layout.hidden,
      'Start must be enabled after selecting valid files at '+width+'x'+height);
    assert.ok(layout.button.height>=40&&layout.button.top>=0&&
      layout.button.bottom<=height+3&&layout.button.left>=-2&&
      layout.button.right<=width+3,
      'Start must remain onscreen at '+width+'x'+height+': '+JSON.stringify(layout));
    assert.ok(layout.footer.top>=layout.dialog.top-2&&
      layout.footer.bottom<=layout.dialog.bottom+3&&layout.scrollable==='auto',
      'Action bar must remain inside dialog while body scrolls: '+JSON.stringify(layout));
    assert.ok(layout.hint.includes('พร้อมตรวจเนื้อหา/MD5')&&
      layout.selected.includes('รายการ'),
      'Selected song count and action guidance must agree');
  }
  await page.setViewportSize(originalViewport);
  assert.equal(await page.locator('#cloud-import-fonts').textContent(),'1');
  assert.equal(await page.locator('#cloud-import-blocked').textContent(),'3',
    'Two unreviewed videos must not silently become embedded karaoke');
  await page.locator('#cloud-import-video-editor:not([hidden])').waitFor();
  const videoPick=page.locator('#cloud-import-video-select');
  await videoPick.selectOption(await videoPick.locator('option',{hasText:'V400.mp4'}).getAttribute('value'));
  await page.locator('#cloud-import-video-title').fill('วิดีโอทดสอบ');
  await page.locator('#cloud-import-video-artist').fill('นักร้องตัวอย่าง');
  await page.locator('#cloud-import-video-album').fill('อัลบั้มทดสอบ');
  await page.locator('#cloud-import-video-mode').selectOption('embedded');
  await page.click('#cloud-import-video-save');
  await page.waitForFunction(()=>document.getElementById('cloud-import-ready').textContent==='3');
  await videoPick.selectOption(await videoPick.locator('option',{hasText:'A500.avi'}).getAttribute('value'));
  await page.locator('#cloud-import-video-title').fill('วิดีโอ AVI ไม่มีเนื้อร้องฝัง');
  await page.locator('#cloud-import-video-artist').fill('นักร้อง AVI');
  await page.locator('#cloud-import-video-mode').selectOption('timed');
  await page.locator('#cloud-import-video-lrc').fill(['[00:00.10]ทดสอบเสียงและภาพ AVI','[00:00.60]สร้าง LRC จากเวลาจริง'].join(String.fromCharCode(10)));
  await page.click('#cloud-import-video-save');
  await page.waitForFunction(()=>document.getElementById('cloud-import-ready').textContent==='4');
  assert.equal(await page.locator('#cloud-import-blocked').textContent(),'1');
  await page.click('#cloud-import-select-all');
  await page.check('#cloud-import-allow-create');
  await page.locator('#cloud-import-start:not([disabled])').waitFor({timeout:15000});
  await page.click('#cloud-import-start');
  try{
    await page.waitForFunction(()=>document.getElementById('cloud-import-status').textContent.startsWith('เสร็จสิ้น'),
      null,{timeout:90000});
  }catch(error){
    console.error('Video import browser status:',await page.locator('#cloud-import-status').textContent(),
      'detail:',await page.locator('#cloud-import-detail').textContent(),
      'errors:',scriptErrors);
    throw error;
  }
  const status=await page.locator('#cloud-import-status').textContent();
  assert.ok(status.includes('เพลงใหม่ 4'),status);
  assert.ok(status.includes('SoundFont 1'),status);
  assert.equal(rootCreated,1,'Only one private XStageKaraoke root should be created');
  assert.ok(![...records.values()].some(x=>x.name==='current.json'),
    'Single SQLite database must not create current.json');
  assert.ok(![...records.values()].some(x=>x.name.startsWith('catalog-delta-')),
    'Single SQLite database must not create a delta index');
  assert.ok([...records.values()].some(x=>x.name.endsWith('.mp4')));
  // Only one SQLite catalog may be active in DB; previous snapshots belong
  // to BACKUP and are still available by immutable Google Drive File ID.
  const rootId=group('root').find(x=>x.name==='XStageKaraoke').id;
  const dbId=group(rootId).find(x=>x.name==='DB').id;
  const activeDbFiles=()=>group(dbId).filter(x=>x.name.endsWith('.sqlite3'));
  assert.deepEqual(activeDbFiles().map(x=>x.name),['songs.sqlite3']);
  assert.equal(group(dbId).some(x=>x.name==='current.json'),false);
  const published=[...records.values()].filter(x=>x.name==='songs.sqlite3');
  assert.equal(published.length,1,'First upload publishes exactly one SQLite3 DB');
  assert.ok(published.every(x=>x.data.subarray(0,16).toString('latin1')==='SQLite format 3\0'),
    'All published catalogs must contain SQLite3 bytes, not renamed JSON');
  const SQL=await initSqlJs();
  const publishedRows=published.flatMap(file=>{
    const database=new SQL.Database(new Uint8Array(file.data));
    try{
      const rows=database.exec('SELECT payload FROM songs');
      return (rows[0]?.values||[]).map(item=>JSON.parse(item[0]));
    }finally{database.close();}
  });
  assert.ok(publishedRows.some(x=>x.lyricsMode==='embedded-video'),
    'Standalone video must publish metadata without invented timed lyrics');
  const videoRow=publishedRows.find(x=>x.code==='V400');
  assert.ok(videoRow&&videoRow.title==='วิดีโอทดสอบ'&&
    videoRow.artist==='นักร้องตัวอย่าง','Artist/title metadata must be published');
  assert.equal(videoRow.originalVideo?.fileId,videoRow.video?.fileId,
    'Native MP4 should retain source reference without duplicate Drive upload');
  const legacyRow=publishedRows.find(x=>x.code==='A500');
  assert.ok(legacyRow&&legacyRow.artist==='นักร้อง AVI'&&legacyRow.lyricsMode==='timed',
    'AVI without burned-in lyrics must use user-authored timed LRC');
  assert.notEqual(legacyRow.originalVideo?.fileId,legacyRow.video?.fileId,
    'AVI source must be preserved separately from the compatible MP4');
  const orig=records.get(legacyRow.originalVideo.fileId);
  assert.ok(orig&&orig.name.endsWith('.avi')&&orig.data.length>1024,
    'Drive must store the original AVI bytes');
  const derivative=records.get(legacyRow.video.fileId);
  assert.ok(derivative&&derivative.name.endsWith('.mp4'),
    'WEB/TV video must point to the playable MP4');
  const textDoc=records.get(legacyRow.lyrics.fileId);
  assert.ok(textDoc&&JSON.parse(textDoc.data.toString('utf8')).lines.length===2,
    'Manually timed LRC must become real lyrics JSON');
  assert.ok([...records.values()].some(x=>x.name.endsWith('.sf2')));
  const firstCount=payloadUploads;
  // After first DB exists, reopen the importer from the visible stage menu.
  await page.click('#cloud-import-close');
  await page.click('#mobile-menu-toggle');
  await page.locator('#mobile-stage-menu').waitFor({state:'visible'});
  await page.click('#cloud-import-open');
  await page.locator('#cloud-import-dialog[open]').waitFor();
  await page.click('#cloud-import-select-all');
  await page.click('#cloud-import-start');
  await page.waitForFunction(()=>document.getElementById('cloud-import-status').textContent.startsWith('เสร็จสิ้น')&&
    document.getElementById('cloud-import-status').textContent.includes('ข้ามซ้ำ 4'),{timeout:60000});
  assert.equal(payloadUploads,firstCount,'Second upload should be 100% deduplicated by MD5');
  // Cancel/pause while an additional large file is being prepared. A browser
  // restart should not lose the completed DB and can reselect the same folder.
  const k300=Buffer.alloc(9*1024*1024+77);k300.write('ID3',0,'ascii');
  fs.writeFileSync(path.join(dir,'K300.mp3'),k300);
  fs.writeFileSync(path.join(dir,'K300.lrc'),'[00:01.00]เพลงที่หยุดกลางทาง\n');
  await page.locator('#cloud-import-input').setInputFiles(dir);
  await page.waitForFunction(()=>document.getElementById('cloud-import-ready').textContent==='5');
  await page.click('#cloud-import-select-all');
  await page.click('#cloud-import-start');
  await page.locator('#cloud-import-start:not([disabled])').waitFor();
  assert.equal((await page.locator('#cloud-import-start').textContent()).trim(),'พัก');
  await page.click('#cloud-import-start');
  await page.waitForFunction(()=>document.getElementById('cloud-import-status').textContent.includes('หยุดงานแล้ว'),null,{timeout:30000});
  await page.reload({waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>{const item=document.getElementById('cloud-import-open');return item&&!item.hidden;});
  // The floating mobile menu is intentionally hidden at desktop viewport
  // widths. Trigger the same existing import button handler directly.
  await page.evaluate(()=>document.getElementById('cloud-import-open').click());
  await page.locator('#cloud-import-dialog[open]').waitFor();
  await page.locator('#cloud-import-start:not([disabled])').waitFor();
  assert.equal((await page.locator('#cloud-import-start').textContent()).trim(),'เริ่ม');
  const chooserPromise=page.waitForEvent('filechooser');
  await page.click('#cloud-import-start');
  const chooser=await chooserPromise;
  await chooser.setFiles(dir);
  try {
    await page.waitForFunction(()=>document.getElementById('cloud-import-status').textContent.startsWith('เสร็จสิ้น'),null,{timeout:90000});
  } catch (error) {
    const diagnostic=await page.evaluate(()=>({
      status:document.getElementById('cloud-import-status')?.textContent,
      ready:document.getElementById('cloud-import-ready')?.textContent,
      startDisabled:document.getElementById('cloud-import-start')?.disabled,
      startLabel:document.getElementById('cloud-import-start')?.textContent
    }));
    throw new Error('Cloud import resume stalled: '+JSON.stringify(diagnostic),{cause:error});
  }
  assert.deepEqual(activeDbFiles().map(x=>x.name),['songs.sqlite3'],
    'Repeated browser imports must leave exactly one SQLite file in DB');
  assert.equal(group(dbId).some(x=>x.name.endsWith('.json')),false,
    'No index or staging JSON may remain in the final DB directory');
  const finalBytes=records.get(activeDbFiles()[0].id)?.data;
  assert.ok(finalBytes,'Canonical song DB must still be directly readable');
  const finalDb=new SQL.Database(new Uint8Array(finalBytes));
  try{
    assert.deepEqual(finalDb.exec('PRAGMA integrity_check')[0].values,[['ok']]);
    assert.equal(finalDb.exec('SELECT count(*) FROM songs')[0].values[0][0],5,
      'Resuming must preserve four existing songs and publish the missing fifth');
  }finally{finalDb.close();}
  assert.deepEqual(scriptErrors,[], 'No browser JavaScript errors are allowed');
  console.log('PASS: Chromium folder selection, Google session, private Drive uploads, single SQLite catalog and replay-safe MD5 dedup');
  await context.close();
}finally{
  await browser.close();server.close();fs.rmSync(dir,{recursive:true,force:true});
}
