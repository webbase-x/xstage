import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {createHash,webcrypto} from 'node:crypto';

const read=path=>fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const page=read('karaoke.html'),app=read('app.js'),style=read('cloud-import.css');
const ids=['cloud-import-open','cloud-import-dialog','cloud-import-pick','cloud-import-input',
  'cloud-import-ready','cloud-import-fonts','cloud-import-blocked','cloud-import-start',
  'cloud-import-done','cloud-import-progress','cloud-import-allow-create'];
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
// Legacy JSON files are inert: never read, migrate, or delete them.
await assert.rejects(loadCatalog({
  listChildren:async()=>[{name:'current.json',mimeType:'application/json',id:'fake1234'}]
},'root'),/โครงสร้าง XStageKaraoke/);
await assert.rejects(loadCatalog({
  listChildren:async()=>[
    {name:'DB',mimeType:'application/vnd.google-apps.folder',id:'newdb123'},
    {name:'DB',mimeType:'application/vnd.google-apps.folder',id:'newdb456'}
  ]
},'root'),/โฟลเดอร์ DB ซ้ำ/);
let jsonReadCount=0;
const ignored=await loadCatalog({
  listChildren:async id=>id==='root'
    ?[{name:'DB',mimeType:'application/vnd.google-apps.folder',id:'newdb123'}]
    :[{name:'current.json',mimeType:'application/json',id:'fake1234'},
      {name:'.xstage-songstudio-staging.json',id:'old-stage'}],
  getJson:async()=>{jsonReadCount++;throw Error('Legacy JSON must never be fetched');}
},'root');
assert.equal(ignored.rows.size,0);
assert.equal(ignored.pointer,null);
assert.equal(jsonReadCount,0);
assert.ok(!read('cloud-import.js').includes('async consolidate()')&&
  !read('cloud-import.js').includes("x.name==='current.json'"),
  'Browser importer must have zero legacy migration logic');
assert.ok(!app.includes("xstageCloudImporter.consolidate()")&&
  !app.includes("name='current.json' and trashed=false"),
  'Player must never search a retired JSON pointer');
const canonicalSong={webSongId:'browser/one',code:'001',title:'เพลงหนึ่ง',artist:'ทดสอบ'};
ctx.XStageDriveSQLite={read:async()=>({
  schemaVersion:1,kind:'snapshot',generation:'direct-generation',songs:[canonicalSong]
})};
const directDrive={
  listChildren:async id=>id==='root'
    ?[{name:'DB',mimeType:'application/vnd.google-apps.folder',id:'db123456'}]
    :[{name:'songs.sqlite3',mimeType:'application/vnd.sqlite3',
       id:'sqlite98765',md5Checksum:'direct-md5'}],
  getSqlite:async id=>{assert.equal(id,'sqlite98765');return new Uint8Array(100);}
};
const canonical=await loadCatalog(directDrive,'root');
assert.equal(canonical.rows.size,1);
assert.equal(canonical.pointer.directFile,true);
assert.equal(canonical.pointer.catalogFileId,'sqlite98765');
assert.equal(canonical.pointer.catalogMd5,'direct-md5');
assert.ok(!('pointerFile' in canonical),'Canonical SQLite has no legacy pointer');
await assert.rejects(loadCatalog({
  listChildren:async id=>id==='root'
    ?[{name:'DB',mimeType:'application/vnd.google-apps.folder',id:'db123456'}]
    :[{name:'songs.sqlite3',id:'sqlite98765'},
      {name:'songs.sqlite3',id:'sqlite22222'}]
},'root'),/songs.sqlite3 ซ้ำ/);
delete ctx.XStageDriveSQLite;
// Imports from different folders/computers MUST compare raw MIDI bytes, not
// code, filename, JSON lyric digest, or wrapped XSK/XMID package digest.
const {buildMidiIndex,distinctImportCode}=ctx.XStageCloudImport;
const digestA='a'.repeat(32),digestB='b'.repeat(32);
const legacyRecords=new Map([
  ['old', {webSongId:'old',code:'100',midi:{md5Checksum:digestA}}],
  ['old_duplicate_different_filename', {webSongId:'old_duplicate_different_filename',
    code:'999',midi:{md5Checksum:digestA}}],
  ['another_mid_same_code', {webSongId:'another_mid_same_code',
    code:'100',midi:{md5Checksum:digestB}}]
]);
const {sourceXmidName,sameMidiBytes}=ctx.XStageCloudImport;
assert.equal(sourceXmidName('00001.XMID'),'00001.XMID');
assert.equal(sourceXmidName('00000001.xmid'),'00001.XMID');
assert.equal(sourceXmidName('00002.xmid'),'00002.XMID');
assert.equal(sourceXmidName('batch/Song-A.XMID'),'Song-A.XMID');
assert.throws(()=>sourceXmidName('00001.mid'),/XMID/);
const exampleSize=240;
const md5ContentA='1'.repeat(32),md5ContentB='2'.repeat(32);
const fingerprints=new Map([[md5ContentA,{midiSize:exampleSize}]]);
assert.equal(sameMidiBytes(fingerprints,md5ContentA,exampleSize),true,
  'Repeated source filenames with matching inner-MIDI bytes and MD5 are duplicates');
assert.equal(sameMidiBytes(fingerprints,md5ContentB,exampleSize),false,
  'Equal file size alone must NEVER discard different MIDI content');
assert.equal(sameMidiBytes(fingerprints,md5ContentB,exampleSize+1),false,
  'Different byte size and hash must be distinct');
assert.throws(()=>sameMidiBytes(fingerprints,md5ContentA,exampleSize+1),/ขนาดไบต์ต่างกัน/,
  'An inconsistent hash/byte-size pair must fail rather than lose a different MIDI');
const xmidCode=read('cloud-import.js');
assert.ok(xmidCode.includes("const sourceCode=opened.code")&&
  xmidCode.includes("const name=isXmid?sourceXmidName(item.file.name)")&&
  xmidCode.includes("if(isXmid)path.push(rawMidiHash)")&&
  xmidCode.includes("midiSize:rawMidiSize,originalFilename:item.file.name"),
  'Every 00001.XMID batch must preserve the source basename but isolate distinct MIDI content');
const indexed=await buildMidiIndex(legacyRecords,{getSqlite:async()=>{throw Error('unexpected fetch');}},()=>{});
assert.equal(indexed.duplicates,1,'Repeated MIDI must collapse even if codes differ');
assert.equal(legacyRecords.size,2,'A different MIDI must remain available');
assert.equal(indexed.hashes.size,2);
assert.equal(distinctImportCode('100','c'.repeat(32),new Map([
  ['100',[{webSongId:'old'}]]
])),'100-cccccccc','Distinct MIDI from other source must receive safe code alias');
assert.equal(distinctImportCode('101','c'.repeat(32),new Map()),'101');
// Validate old XSK and XMID packages against existing naked MIDI recordings,
// so a different container format does not bypass content deduplication.
const rawBytes=Buffer.from('MThd-cross-format-midi-fixture');
const rawMd5=createHash('md5').update(rawBytes).digest('hex');
const packages=new Map([['wrappedA',new Uint8Array([1,2,3])],['wrappedB',new Uint8Array([4,5,6])]]);
ctx.XStageXmid={openPackage:async()=>({midi:new Blob([rawBytes])})};
ctx.XStageXsk={openPackage:async()=>({midi:new Blob([rawBytes])})};
const crossFormat=new Map([
  ['raw', {webSongId:'raw',code:'R1',midi:{md5Checksum:rawMd5}}],
  ['xmid', {webSongId:'xmid',code:'R2',xmid:{fileId:'wrappedA'}}],
  ['xsk', {webSongId:'xsk',code:'R3',xsk:{fileId:'wrappedB'}}]
]);
const crossResult=await buildMidiIndex(crossFormat,{
  getSqlite:async id=>{assert.ok(packages.has(id));return packages.get(id);}
},()=>{});
assert.equal(crossResult.duplicates,2);
assert.equal(crossResult.backfilled,2);
assert.equal(crossFormat.size,1);
assert.equal(crossResult.hashes.get(rawMd5).webSongId,'raw');
const importerText=read('cloud-import.js');
assert.ok(importerText.includes('core.hashBlob(opened.midi,()=>this.check())'),
  'Wrapped XMID/XSK input must hash the internal MIDI content');
assert.ok(importerText.includes('sameMidiBytes(byMidi,midiHash,midiSize)') &&
  importerText.includes('byMidi.set(midiHash,record)'),
  'Every import must compare MIDI byte length and MD5 before uploading media');
assert.ok(importerText.includes('const CATALOG_BATCH_SIZE=200')&&
  importerText.includes('if(revisions.length>=CATALOG_BATCH_SIZE)await publish();'),
  'Large imports should publish a verified SQLite snapshot in batches, not after every song');
assert.ok(importerText.includes('originalRelativePath:item.relative||item.file.name')&&
  importerText.includes('originalRelativePath:item.midi?.relative||midiFile.name'),
  'All MIDI import paths must preserve the local source filename and relative directory');
assert.ok(!importerText.includes('if(revisions.length>=25)await publish();'),
  'Publishing the full catalog every 25 files causes avoidable Drive I/O');
// Two computers share a Drive-scoped publication lease in CACHE, never DB.
// The holder verifies ownership and releases the app-owned lock after success.
const leases=new Map();
let releasedLockId='';
const fakeLeasingDrive={
  upload:async(parent,blob,name,mime,md5)=>{
    assert.equal(parent,'cacheFolder123');
    assert.ok(name.startsWith('.xstage-import-lock-')&&name.endsWith('.json'));
    assert.equal(mime,'application/json');
    const id='lock-file-001';
    leases.set(id,{id,name,createdTime:new Date().toISOString(),md5Checksum:md5});
    return {id};
  },
  list:async query=>{
    assert.ok(query.includes("'cacheFolder123' in parents"));
    return [...leases.values()];
  },
  trashFile:async id=>{assert.ok(leases.has(id));leases.delete(id);releasedLockId=id;}
};
const lease=await ctx.XStageCloudImport.acquireCatalogLease(fakeLeasingDrive,
  'cacheFolder123',()=>{},()=>{});
await lease.assertOwner();
await lease.release();
assert.equal(releasedLockId,'lock-file-001');
assert.equal(leases.size,0,'Writer lease must not linger after publication');
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
assert.equal(await indexedDrive.folder(duplicateParent,'duplicate'),'dupA',
  'Multiple empty same-name folders must reuse a stable existing ID without creating more');
const populatedParent=id();
ensure(populatedParent).push(
  {id:'popA',name:'MIDI',mimeType:'application/vnd.google-apps.folder'},
  {id:'popB',name:'MIDI',mimeType:'application/vnd.google-apps.folder'});
ensure('popB').push({id:'song-existing',name:'001.mid',mimeType:'audio/midi'});
assert.equal(await indexedDrive.folder(populatedParent,'MIDI'),'popB',
  'Reuse the only populated MIDI folder without modifying songs');
ensure('popA').push({id:'song-other',name:'002.mid',mimeType:'audio/midi'});
// Use a fresh Drive to avoid stale cached parent listings.
const conflictDrive=new Drive(()=> 'token_TEST',()=>{});
await assert.rejects(conflictDrive.folder(populatedParent,'MIDI'),
  error=>/มีข้อมูลมากกว่าหนึ่งแห่ง/.test(error.message)&&
    error.message.includes('popA')&&error.message.includes('popB'),
  'Two populated MIDI folders must report both IDs rather than silently losing songs');
const collidingParent=id();
ensure(collidingParent).push(
  {id:'folder-one',name:'MIDI',mimeType:'application/vnd.google-apps.folder'},
  {id:'file-one',name:'MIDI',mimeType:'application/octet-stream'});
await assert.rejects(indexedDrive.folder(collidingParent,'MIDI'),/ชื่อชนกับไฟล์/);
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

// An upload may exceed Google's short-lived access token lifetime. The first
// HTTP 401 must renew the same account, then retry exactly that request once.
const beforeRenewFetch=ctx.fetch;
let activeToken='expired-token',requests=[],forcedRenewals=0,attemptedRenewals=0;
ctx.fetch=async(url,options={})=>{
  requests.push({url:String(url),method:options.method||'GET',
    authorization:options.headers?.Authorization,range:options.headers?.['Content-Range']});
  if(options.headers?.Authorization==='Bearer expired-token')
    return reply(401,{error:'invalid_token'});
  if(String(url).includes('upload_id='))return reply(308,null,{Range:'bytes=0-7'});
  return reply(200,{files:[]});
};
try{
  const renewDrive=new Drive(()=>activeToken,()=>{});
  renewDrive.ensureAuth=async force=>{
    attemptedRenewals++;
    if(force){forcedRenewals++;activeToken='renewed-token';}
  };
  const rows=await renewDrive.list("'root' in parents");
  assert.equal(rows.length,0);
  assert.equal(forcedRenewals,1,'A 401 should trigger one Google token renewal');
  assert.deepEqual(requests.map(x=>x.authorization),
    ['Bearer expired-token','Bearer renewed-token']);
  requests=[];activeToken='expired-token';
  const chunk=await renewDrive.signedFetch('https://www.googleapis.com/upload/drive/v3/files?upload_id=TEST',{
    method:'PUT',headers:{'Content-Range':'bytes 0-7/64'},body:new Blob(['12345678'])
  });
  assert.equal(chunk.status,308,'Resumable Drive chunk should continue after OAuth renewal');
  assert.equal(forcedRenewals,2);
  assert.deepEqual(requests.map(x=>x.range),['bytes 0-7/64','bytes 0-7/64'],
    'Retry must preserve the exact uploaded chunk range');
  requests=[];activeToken='expired-token';
  renewDrive.ensureAuth=async force=>{
    if(force)throw Error('Google requires explicit user reconnection');
  };
  await assert.rejects(
    renewDrive.signedFetch('https://www.googleapis.com/drive/v3/files'),
    error=>error.code==='XSTAGE_AUTH_REQUIRED'&&/explicit user/.test(error.message),
    'A failed silent renewal must stop safely after one 401');
  assert.equal(requests.length,1,'Never loop Google Login on a rejected token');
}finally{ctx.fetch=beforeRenewFetch;}
assert.ok(app.includes('async function ensureImporterGoogleAuth(force=false,interactive=false)')&&
  app.includes('state.accountSub!==expectedSub')&&
  app.includes("client.requestAccessToken({")&&app.includes("login_hint:hint.email"),
  'Importer renewal must verify and preserve the same Google account');
const footerHtml=page.split('class="cloud-import-footer-buttons"')[1]?.split('</div>')[0]||'';
assert.equal((footerHtml.match(/<button /g)||[]).length,2,
  'Import footer must expose only Start/Pause and Close');
for(const obsolete of ['cloud-import-consolidate','cloud-import-resume',
  'cloud-import-pause','cloud-import-reauthorize','cloud-import-cancel'])
  assert.ok(!page.includes('id="'+obsolete+'"'),'Remove obsolete footer button '+obsolete);
assert.ok(importerUsesSingleToggle(),
  'Start/Pause must be wired to the same button');
function importerUsesSingleToggle(){
  const src=read('cloud-import.js');
  return src.includes("this.toggleStartPause()")&&
    src.includes("this.running?'พัก':'เริ่ม'");
}

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
assert.ok(page.includes('cloud-import.js?v=1178-sqlite-only')&&
  page.includes('cloud-import.css?v=1172-direct-db-layout')&&
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
    session:()=>({token:'test-token',sub:'SUB_UI_TEST'}),refresh:async()=>{}
  });
  await importer.acceptFiles([
    {file:sourceFile,relative:'MIDI/NCN/SONG/R/READY.mid'},
    {file:videoFile,relative:'VIDEO/MP4/SONG/R/REVIEW.mp4'}
  ],null);
  assert.equal(importer.chosenItems.size,1,'Verified bundles must be preselected');
  assert.equal(importer.dom.start.disabled,false,'Start must be enabled after valid folder selection');
  assert.equal(importer.dom.start.hidden,false,'Start must be visible before uploading');
  assert.equal(importer.dom.start.textContent,'เริ่ม');
  assert.ok(importer.dom.status.textContent.includes('กด “เริ่ม”'));
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
  assert.equal(importer.dom.start.disabled,false,'Paused upload must use the same Start button');
  assert.equal(importer.dom.start.textContent,'เริ่ม');
  importer.running=true;importer.refreshButtons();
  assert.equal(importer.dom.start.textContent,'พัก','Start switches to Pause during upload');
  assert.equal(importer.dom.start.disabled,false,'Pause stays available while running');
  importer.running=false;importer.refreshButtons();
  const fullyVerified=importer.options.session;
  importer.options.session=()=>({token:'test-token',sub:''});
  importer.refreshButtons();
  assert.equal(importer.dom.start.disabled,true,'Unverified account must not start a Drive import');
  assert.equal(importer.dom.open.hidden,true,'Upload entry must await verified Google identity');
  importer.options.session=fullyVerified;
  importer.refreshButtons();
  assert.equal(importer.dom.open.hidden,false,'Upload opens once Google account is verified');
}finally{
  ctx.document=oldDoc;ctx.addEventListener=oldAdd;
  ctx.XStageImportCore.scan=oldScan;delete ctx.XStageVideoEditor;
}

// Exercise the *actual* Google GIS renewal helper with simulated Google
// accounts and token expiry: single-flight refresh, unchanged account identity,
// and explicit pairing only when silent authorization is refused.
const renewalStart=app.indexOf('let importerGoogleRenewal=null;');
const renewalEnd=app.indexOf('// A Google access token',renewalStart);
assert.ok(renewalStart>0&&renewalEnd>renewalStart);
const renewalSource=app.slice(renewalStart,renewalEnd);
const simulatedState={
  token:'initial-token',accountSub:'SUB_A',tokenExpiresAt:Date.now()+3000,authId:4
};
let googleRequests=0,googlePrompt=[],userInfoSub='SUB_A',activeRenewedToken='fresh-token';
const activeAuth=[];
const googleScope={
  state:simulatedState,
  cfg:{googleClientId:'test.apps.googleusercontent.com'},
  rememberedGoogleAccount:()=>({sub:'SUB_A',email:'owner@example.com'}),
  google:{accounts:{oauth2:{initTokenClient:config=>({
    requestAccessToken:({prompt})=>{
      googleRequests++;googlePrompt.push(prompt);
      config.callback({access_token:activeRenewedToken,expires_in:3599});
    }
  })}}},
  googleFetch:async(_url,options)=>{
    assert.equal(options.headers.Authorization,'Bearer '+activeRenewedToken);
    return {ok:true,json:async()=>({sub:userInfoSub,email_verified:true})};
  },
  requestHeaders:token=>({Authorization:'Bearer '+token}),
  saveActiveAuth:(token,expiry,sub)=>activeAuth.push([token,expiry,sub]),
  clearPendingAuth(){},driveError:()=>Error('invalid user info'),
  window:{dispatchEvent(){}},CustomEvent:class{constructor(type,init){this.type=type;this.detail=init.detail;}},
  setTimeout,clearTimeout,Date,Error,console
};
vm.runInNewContext(renewalSource+
  '\nwindow.renew=ensureImporterGoogleAuth;',googleScope,{filename:'app.js importer renewal'});
await Promise.all([googleScope.window.renew(),googleScope.window.renew()]);
assert.equal(googleRequests,1,'Concurrent Drive chunks must share one Google OAuth refresh');
assert.equal(simulatedState.token,'fresh-token');
assert.equal(googlePrompt[0],'','Existing Google consent should be reused without account selection');
assert.equal(activeAuth.length,1);
assert.equal(activeAuth[0][2],'SUB_A');
activeRenewedToken='interactive-token';
await googleScope.window.renew(true,true);
assert.equal(googlePrompt.at(-1),'','One-tap reconnection should reuse Google consent for the verified account');
assert.equal(simulatedState.token,'interactive-token');
userInfoSub='SUB_OTHER';activeRenewedToken='wrong-account-token';
const accepted=simulatedState.token;
await assert.rejects(googleScope.window.renew(true,true),/บัญชี.*ไม่ตรง/);
assert.equal(simulatedState.token,accepted,
  'Google refresh must never switch an active upload to a different account');

console.log('PASS: WEB upload DOM, visible Start, selection/review/resume, Drive chunks, MD5 and catalog safety');
