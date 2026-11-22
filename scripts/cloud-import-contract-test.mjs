import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {createHash,webcrypto} from 'node:crypto';

const read=path=>fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const page=read('karaoke.html'),app=read('app.js'),style=read('cloud-import.css');
const ids=['cloud-import-open','cloud-import-dialog','cloud-import-pick','cloud-import-input',
  'cloud-import-ready','cloud-import-fonts','cloud-import-blocked','cloud-import-start',
  'cloud-import-pause','cloud-import-resume','cloud-import-cancel','cloud-import-progress',
  'cloud-import-allow-create'];
for(const id of ids)assert.ok(page.includes('id="'+id+'"'),'Missing cloud importer control: '+id);
assert.ok(page.includes('cloud-import-core.js?v=')&&page.includes('cloud-import.js?v=')&&
  page.includes('cloud-import.css?v='),'Browser importer must be loaded with the main WEB shell');
assert.ok(style.includes('.cloud-import-dialog')&&style.includes('@media(max-width:700px)'));
assert.ok(app.includes('XStageCloudImport?.init')&&app.includes('refresh:async()=>')&&
          app.includes("xstage:auth-cleared"),'Import must receive the verified session and refresh canonical catalog');
const ctx={Blob,URL,URLSearchParams,DOMException,console,setTimeout,clearTimeout,crypto:webcrypto};
ctx.window=ctx;
ctx.document={getElementById:()=>null};
vm.runInNewContext(read('cloud-import-core.js'),ctx,{filename:'cloud-import-core.js'});
vm.runInNewContext(read('cloud-import.js'),ctx,{filename:'cloud-import.js'});
assert.ok(ctx.XStageCloudImport?.Drive&&ctx.XStageCloudImport.loadCatalog);
const {Drive,loadCatalog}=ctx.XStageCloudImport;
assert.equal((await loadCatalog({listChildren:async()=>[]},'root')).rows.size,0);
// Legacy catalog pointers at the root are unsafe in the new layout. Reject
// them rather than mistaking them for DB/current.json duplicates.
await assert.rejects(loadCatalog({
  listChildren:async()=>[{name:'current.json',mimeType:'application/json',id:'fake1234'}]
},'root'),/โครงสร้าง XStageKaraoke/);
// Only duplicate pointers *inside* the unique DB directory use the more
// specific duplicate-current.json diagnostic.
await assert.rejects(loadCatalog({
  listChildren:async()=>[
    {name:'DB',mimeType:'application/vnd.google-apps.folder',id:'newdb123'},
    {name:'DB',mimeType:'application/vnd.google-apps.folder',id:'newdb456'}
  ]
},'root'),/โฟลเดอร์ DB ซ้ำ/);
await assert.rejects(loadCatalog({
  listChildren:async id=>id==='root'
    ?[{name:'DB',mimeType:'application/vnd.google-apps.folder',id:'newdb123'}]
    :[{name:'current.json',mimeType:'application/json',id:'fake1234'},
      {name:'current.json',mimeType:'application/json',id:'fake5678'}]
},'root'),/current.json ซ้ำ/);
const uploaded=new Map(),children=new Map(),sessions=new Map();
let serial=0,sessionNumber=0,putRequests=0;
const id=()=>('item'+String(++serial).padStart(7,'0'));
const ensure=parent=>{if(!children.has(parent))children.set(parent,[]);return children.get(parent);};
function reply(status,json,headers={}){
  return {status,ok:status>=200&&status<300,headers:{get:key=>headers[key]||headers[key.toLowerCase()]||null},
    json:async()=>json};
}
ctx.fetch=async(raw,options={})=>{
  const url=new URL(raw);
  assert.equal(url.hostname,'www.googleapis.com','Private upload must use only the official Drive domain');
  assert.ok(options.headers?.Authorization==='Bearer token_TEST','Drive calls must include owner OAuth');
  const method=options.method||'GET';
  if(url.pathname==='/drive/v3/files'&&method==='GET'){
    const q=url.searchParams.get('q')||'';
    const parent=q.match(/'([^']+)' in parents/)?.[1];
    return reply(200,{files:ensure(parent||'root')});
  }
  if(url.pathname==='/drive/v3/files'&&method==='POST'){
    const meta=JSON.parse(options.body);
    assert.equal(meta.mimeType,'application/vnd.google-apps.folder');
    const created={...meta,id:id()};
    ensure(meta.parents[0]).push(created);
    ensure(created.id);
    return reply(200,created);
  }
  if(url.pathname==='/upload/drive/v3/files'&&method==='POST'){
    const meta=JSON.parse(options.body);
    const key='session'+(++sessionNumber);
    sessions.set(key,{meta,buffers:[],received:0});
    return reply(200,null,{Location:'https://www.googleapis.com/upload/drive/v3/files?upload_id='+key});
  }
  if(url.pathname==='/upload/drive/v3/files'&&method==='PUT'){
    const session=sessions.get(url.searchParams.get('upload_id'));
    assert.ok(session,'Upload must use a previously initiated session');
    const range=options.headers['Content-Range'];
    if(range.startsWith('bytes */'))return reply(308,null,session.received?
      {Range:'bytes=0-'+(session.received-1)}:{});
    const match=range.match(/^bytes (\d+)-(\d+)\/(\d+)$/);
    assert.ok(match,'Chunk requires a valid Content-Range');
    const [start,end,total]=match.slice(1).map(Number);
    assert.equal(start,session.received,'Upload must resume after acknowledged byte');
    const chunk=Buffer.from(await options.body.arrayBuffer());
    assert.equal(chunk.length,end-start+1);
    session.received+=chunk.length;
    session.buffers.push(chunk);putRequests++;
    if(session.received<total)return reply(308,null,{Range:'bytes=0-'+(session.received-1)});
    const data=Buffer.concat(session.buffers);
    const record={...session.meta,id:id(),size:String(data.length),
      md5Checksum:createHash('md5').update(data).digest('hex')};
    ensure(session.meta.parents[0]).push(record);
    uploaded.set(record.id,{meta:record,data});
    return reply(200,record);
  }
  if(url.pathname.startsWith('/drive/v3/files/')&&method==='GET'){
    const fileId=url.pathname.split('/').pop();
    const found=uploaded.get(fileId);
    assert.ok(found,'Only previously uploaded file metadata may be requested');
    return reply(200,found.meta);
  }
  throw Error('Unmocked Drive API call: '+method+' '+url.href);
};
const drive=new Drive(()=> 'token_TEST',()=>{});
const root=await drive.folder('root','XStageKaraoke');
assert.ok(root.startsWith('item'));
const target=await drive.ensurePath(root,['SONGS','AUDIO','MP3','SONG','1']);
const payload=new Blob([Buffer.alloc(9*1024*1024+117,0x42)],{type:'audio/mpeg'});
const digest=createHash('md5').update(Buffer.alloc(9*1024*1024+117,0x42)).digest('hex');
const snapshots=[];
const result=await drive.upload(target,payload,'111-'+digest.slice(0,16)+'.mp3','audio/mpeg',digest,
  (done,total)=>snapshots.push([done,total]));
assert.equal(result.reused,false);
assert.equal(putRequests,2,'Large assets should upload in bounded 8 MiB chunks');
assert.equal(snapshots.at(-1)[0],payload.size);
const again=await drive.upload(target,payload,'111-'+digest.slice(0,16)+'.mp3','audio/mpeg',digest);
assert.equal(again.id,result.id);
assert.equal(again.reused,true);
assert.equal(putRequests,2,'MD5 duplicate must skip sending the same asset again');
await assert.rejects(drive.upload(target,payload,'111-'+digest.slice(0,16)+'.mp3','audio/mpeg',
  'f'.repeat(32)),/MD5/);
// Fast exact-name index: loading a 30,000-file folder builds the index once.
// Subsequent folder checks must not re-scan every existing song.
const heavyParent=id(),heavyFiles=ensure(heavyParent);
let inspectedNames=0;
for(let i=0;i<30000;i++){
  const name='song-'+String(i).padStart(5,'0');
  const entry={id:'existing-'+String(i),mimeType:'application/vnd.google-apps.folder'};
  Object.defineProperty(entry,'name',{enumerable:true,get(){inspectedNames++;return name;}});
  heavyFiles.push(entry);
}
const indexedDrive=new Drive(()=> 'token_TEST',()=>{});
await indexedDrive.listChildren(heavyParent);
const beforeLookup=inspectedNames;
for(let i=0;i<400;i++){
  const found=await indexedDrive.folder(heavyParent,'song-'+String(i).padStart(5,'0'));
  assert.equal(found,'existing-'+i);
}
assert.ok(inspectedNames-beforeLookup<50,
  'Exact-name lookup must not repeatedly inspect 30,000 siblings');
const duplicateParent=id();
ensure(duplicateParent).push(
  {id:'dupA',name:'duplicate',mimeType:'application/vnd.google-apps.folder'},
  {id:'dupB',name:'duplicate',mimeType:'application/vnd.google-apps.folder'});
await assert.rejects(indexedDrive.folder(duplicateParent,'duplicate'),/ซ้ำ/);
const newParent=id();
ensure(newParent);
const created=await indexedDrive.folder(newParent,'new-folder');
assert.equal(await indexedDrive.folder(newParent,'new-folder'),created,
  'Newly created folders must enter the exact-name index immediately');

// A broken Drive cursor must fail closed rather than spin forever.
const originalFetch=ctx.fetch;
let paginationRequests=0;
ctx.fetch=async()=>{
  if(++paginationRequests>3)throw Error('Unbounded Drive page loop');
  return reply(200,{files:[],nextPageToken:'same-token'});
};
try {
  await assert.rejects(indexedDrive.list("'root' in parents"),/รหัสหน้ารายการซ้ำ/);
  assert.equal(paginationRequests,2);
} finally { ctx.fetch=originalFetch; }

const importUi=read('cloud-import.js');
assert.ok(importUi.includes('input[data-import-group],input[data-import-item]')&&
  importUi.includes('checkbox.dataset.importItem=entry.key'),
  'Expanded folders must support selecting individual import entries');
assert.ok(importUi.includes('this.chosenItems.has(entry.key)')&&
  importUi.includes('const selectedObjects=new Set('),
  'Checkbox state must control the actual upload queue, not only the UI');
assert.ok(importUi.includes('group.entries.slice(0,pageSize)')&&
  importUi.includes('this.dom.selectionList.scrollTop=scrollTop'),
  'Folder expansion must limit DOM rows and preserve scroll position');
assert.ok(!read('cloud-import.js').includes('localStorage.setItem('),
  'Never persist Drive bearer tokens or upload session URLs in localStorage');

// User-visible workflow contract: the footer must stay outside the scrollable
// file list, a verified bundle must enable Start immediately, and an unreviewed
// video must never be silently eligible for upload.
const openDialog=page.indexOf('<dialog id="cloud-import-dialog"');
const bodyStart=page.indexOf('class="cloud-import-body"',openDialog);
const bodyEnd=page.indexOf('</div>\n      <footer class="cloud-import-footer"',bodyStart);
const footerStart=page.indexOf('<footer class="cloud-import-footer"',bodyEnd);
const startBtn=page.indexOf('id="cloud-import-start"',footerStart);
const hint=page.indexOf('id="cloud-import-action-hint"',footerStart);
assert.ok(openDialog>=0&&bodyStart>openDialog&&bodyEnd>bodyStart&&
  footerStart>bodyEnd&&startBtn>footerStart&&hint>footerStart,
  'The import action bar must sit outside the scrollable content and include clear guidance');
assert.ok(style.includes('.cloud-import-body{')&&
  style.includes('overflow-y:auto')&&
  style.includes('.cloud-import-footer-buttons{')&&
  style.includes('flex:0 0 auto'),
  'Import Start and status must be anchored outside scrollable contents');
assert.ok(page.includes('cloud-import.js?v=1138-visible-import-cta')&&
  page.includes('cloud-import.css?v=1138-visible-import-cta')&&
  page.includes('video-metadata-editor.js?v=1138-verified-video-selection'),
  'Updated scripts and styles must bypass stale browser caches');
const oldDoc=ctx.document,oldAdd=ctx.addEventListener,oldScan=ctx.XStageImportCore.scan;
const fakeNodes=new Map();
const node=id=>{
  if(id==='cloud-import-selection-list')return null;
  if(!fakeNodes.has(id))fakeNodes.set(id,{
    hidden:false,disabled:false,textContent:'',value:'',
    addEventListener(){},setAttribute(){},removeAttribute(){}
  });
  return fakeNodes.get(id);
};
let videoApproved=false;
const sourceFile={name:'READY.mid',size:31};
const videoFile={name:'REVIEW.mp4',size:79};
const verified={key:'song-ready',midi:{file:sourceFile,relative:'MIDI/NCN/SONG/R/READY.mid'}};
const unreviewed={key:'video-review',video:{file:videoFile,relative:'VIDEO/MP4/SONG/R/REVIEW.mp4'}};
ctx.document={getElementById:node};
ctx.addEventListener=()=>{};
ctx.XStageVideoEditor={init:()=>({
  setPlan(){},get:item=>item===unreviewed&&videoApproved?{title:'Verified'}:null,
  pendingCount:()=>videoApproved?0:1,eligibleCount:()=>videoApproved?1:0,
  exportEdits:()=>[]
})};
ctx.XStageImportCore.scan=()=>({
  files:2,songs:[unreviewed],midis:[verified],xsks:[],fonts:[],blocked:[]
});
try{
  const importer=ctx.XStageCloudImport.init({
    session:()=>({token:'test-token',sub:''}),refresh:async()=>{}
  });
  await importer.acceptFiles([
    {file:sourceFile,relative:'MIDI/NCN/SONG/R/READY.mid'},
    {file:videoFile,relative:'VIDEO/MP4/SONG/R/REVIEW.mp4'}
  ],null);
  assert.equal(importer.chosenItems.size,1,'Verified bundles must be preselected');
  assert.equal(importer.dom.start.disabled,false,'Start must be enabled after valid folder selection');
  assert.equal(importer.dom.start.hidden,false,'Start must be visible before uploading');
  assert.ok(importer.dom.start.textContent.includes('(1)'));
  assert.equal(importer.dom.resume.hidden,true,'Resume must not appear for a brand-new selection');
  assert.ok(importer.dom.status.textContent.includes('กด “เริ่มตรวจ MD5 และนำเข้า”'));
  importer.selectEveryItem(false);
  assert.equal(importer.dom.start.disabled,true,'Clearing selection disables unsafe empty import');
  assert.ok(importer.dom.actionHint.textContent.includes('ยังไม่ได้เลือกรายการ'));
  videoApproved=true;
  importer.onVideoApproved(unreviewed);
  assert.equal(importer.dom.start.disabled,false,'Approved video must enable Start');
  assert.equal(importer.chosenItems.size,1,'Only the newly approved video is selected');
  assert.ok(importer.dom.status.textContent.includes('พร้อมตรวจ MD5'));
  importer.saved={status:'paused'};
  importer.refreshButtons();
  assert.equal(importer.dom.resume.hidden,false,'A paused upload must expose Resume');
}finally{
  ctx.document=oldDoc;ctx.addEventListener=oldAdd;
  ctx.XStageImportCore.scan=oldScan;delete ctx.XStageVideoEditor;
}

console.log('PASS: WEB upload DOM, visible Start, selection/review/resume, Drive chunks, MD5 and catalog safety');
