import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {createHash,webcrypto} from 'node:crypto';

const read=path=>fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const u32=n=>{const b=Buffer.alloc(4);b.writeUInt32LE(n);return b;};
const f64=n=>{const b=Buffer.alloc(8);b.writeDoubleLE(n);return b;};
const str=value=>{const b=Buffer.from(value,'utf8');return Buffer.concat([u32(b.length),b]);};
function packageFile(id,midiBytes){
  const metadata=Buffer.concat([
    ...['song-'+id,'360','version-1',id,'','estimated'].map(str),
    u32(1),f64(0),f64(4),str('X-Stage Karaoke'),str('estimated'),u32(0)
  ]);
  const header=Buffer.alloc(92);
  header.write('XSTGPLS1',0,'ascii');header.writeUInt32LE(1,8);
  header.writeBigUInt64LE(BigInt(metadata.length),12);
  header.writeBigUInt64LE(BigInt(midiBytes.length),20);
  createHash('sha256').update(midiBytes).digest().copy(header,28);
  createHash('sha256').update(metadata).digest().copy(header,60);
  const bytes=Buffer.concat([header,metadata,midiBytes]);
  return {bytes:new Uint8Array(bytes),md5:createHash('md5').update(bytes).digest('hex')};
}
const midiA=Buffer.from([
  0x4d,0x54,0x68,0x64,0,0,0,6,0,0,0,1,0,96,
  0x4d,0x54,0x72,0x6b,0,0,0,4,0,0xff,0x2f,0
]);
const midiB=Buffer.from(midiA);midiB[13]=97;
const a=packageFile('00363',midiA);
const duplicated=packageFile('same-midi-different-meta',midiA);
const b=packageFile('another-midi',midiB);
const records=[
  {id:'file00001',name:'00001.XMID',size:String(a.bytes.length),mimeType:'application/octet-stream',md5Checksum:a.md5},
  {id:'file00002',name:'00002.XMID',size:String(duplicated.bytes.length),mimeType:'application/octet-stream',md5Checksum:duplicated.md5},
  {id:'file00003',name:'00003.XMID',size:String(b.bytes.length),mimeType:'application/octet-stream',md5Checksum:b.md5},
  {id:'other0001',name:'effects.wav',size:'128',mimeType:'audio/wav'}
];
const blobs=new Map([['file00001',a.bytes],['file00002',duplicated.bytes],['file00003',b.bytes]]);
const root='activeRoot1234',music='musicSource1234',font='fontSource1234',fx='effectSource1234';
const retiredId='1RYekUHCC3qs661cUrbxkNauUz_SuqZvy';
const parents=new Map([
  [music,root],[font,root],[fx,root]
]);
const names=new Map([[music,'XMID'],[font,'SOUNDFONT'],[fx,'FX']]);
let denied=false,cancelOnList=false,uploads=0,reads=0,published=0,lastRows=null,failOnce=false;
let existingRows=[];
class FakeDrive {
  async folderMetadata(id){
    if(!parents.has(id))throw Error('Not permitted');
    return {id,name:names.get(id),mimeType:'application/vnd.google-apps.folder',
      parents:[parents.get(id)],trashed:false};
  }
  async listChildren(id){
    if(denied)throw Error('HTTP 403: folder contents unavailable');
    if(id===music&&cancelOnList){cancelOnList=false;workflow.cancel();}
    if(id===music)return records;
    return [];
  }
  async getSqlite(id){reads++;if(failOnce&&id==='file00003'){failOnce=false;throw Error('Network timeout');}if(!blobs.has(id))throw Error('Unexpected media');return blobs.get(id);}
  async upload(){uploads++;throw Error('Builder must never upload songs');}
}
const values=new Map(),elements=new Map();
const element=id=>{
  if(!elements.has(id))elements.set(id,{
    id,disabled:false,textContent:'',addEventListener(){},value:''
  });
  return elements.get(id);
};
const storage={
  getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v)
};
const window={
  crypto:webcrypto,document:{getElementById:element},
  navigator:{},localStorage:storage,
  addEventListener(){},
  XSTAGE_RETIRED_DRIVE_ROOT_IDS:[retiredId]
};
window.window=window;
const context={window,document:window.document,navigator:window.navigator,localStorage:storage,
  Blob,TextDecoder,TextEncoder,Uint8Array,DataView,URL,URLSearchParams,crypto:webcrypto,
  console,setTimeout,clearTimeout,AbortController};Object.assign(window,{Blob,TextDecoder,TextEncoder});
vm.runInNewContext(read('cloud-import-core.js'),context,{filename:'cloud-import-core.js'});
vm.runInNewContext(read('xmid-browser.js'),context,{filename:'xmid-browser.js'});
window.XStageImportCore.hashBlob=async(blob)=>{
  const bytes=new Uint8Array(await blob.arrayBuffer());
  return createHash('md5').update(bytes).digest('hex');
};
window.XStageCloudImport={
  Drive:FakeDrive,
  loadCatalog:async()=>({pointer:null,rows:new Map(existingRows.map(row=>[row.webSongId,{...row}]))}),
  buildMidiIndex:async(rows)=>({hashes:new Map([...rows.values()].map(row=>[row.midiHash,row])),duplicates:0,backfilled:0}),
  distinctImportCode:(requested,hash,codes)=>
    codes.get(String(requested).toLowerCase())?.length
      ?requested+'-'+hash.slice(0,8):requested,
  publishSingleCatalog:async({rows})=>{published++;lastRows=[...rows.values()];}
};
vm.runInNewContext(read('cloud-drive-folders.js'),context,{filename:'cloud-drive-folders.js'});
let current={sub:'account1',rootId:root,token:'token1'},pick={id:music,name:'XMID'};
const savedMetadata=new Map();
const workflow=window.XStageDriveFolders.init({
  openCheckpoint:async()=>({get:async key=>savedMetadata.get(key),put:async(key,value)=>savedMetadata.set(key,value)}),
  session:()=>current,chooseFolder:async()=>pick,
  refresh:async()=>{},ensureAuth:async()=>{}
});
assert.equal(element('xstage-drive-build-db').disabled,true,'Build must require selection');
await workflow.choose('music');
assert.equal(workflow.getFolderId('account1',root,'music'),music);
assert.equal(element('xstage-drive-build-db').disabled,false);
pick={id:font,name:'SOUNDFONT'};await workflow.choose('soundfont');
pick={id:fx,name:'FX'};await workflow.choose('fx');
assert.equal(workflow.getFolderId('account1',root,'soundfont'),font);
assert.equal(workflow.getFolderId('account1',root,'fx'),fx);
assert.equal(workflow.getFolderId('another-account',root,'music'),'',
  'Stored folder IDs must not cross Google identities');
assert.equal(workflow.getFolderId('account1','anotherRoot123','music'),'',
  'Stored folder IDs must not cross library roots');
failOnce=true;
await workflow.rebuild();
assert.equal(published,0,'Interrupted scan never publishes an incomplete catalog');
assert.equal(savedMetadata.size,2,'Verified packages are checkpointed independently');
assert.match(element('xstage-drive-folder-status').textContent,/พักงานชั่วคราว/);
assert.equal(window.XStageDriveBuildBusy,false);
await workflow.rebuild();
assert.equal(published,1,'Build should publish one DB snapshot only');
assert.equal(lastRows.length,2,'Duplicate raw MIDI across distinct packages must collapse');
assert.equal(new Set(lastRows.map(x=>x.midiHash)).size,2);
assert.ok(lastRows.every(x=>x.xmid?.fileId&&x.originalFilename&&x.sourceCode==='360'));
assert.ok(lastRows.every(x=>x.metadataComplete===false),'Missing artist is explicitly pending');
assert.ok(lastRows.every(x=>x.lyricsMode==='unavailable'),'Placeholder lyrics are not real');
assert.notEqual(lastRows[0].code,lastRows[1].code,
  'Distinct MIDI with colliding embedded song code must receive an alias');
assert.equal(uploads,0,'Rebuilding must not upload any source file');
assert.equal(reads,4,'Resume reuses two verified packages and retries only the failed file');
assert.match(element('xstage-drive-folder-status').textContent,/ฐานเดิม 0 เพลง/);
assert.match(element('xstage-drive-folder-status').textContent,/MIDI ซ้ำ 1 \(มีในฐานแล้ว 0 · ซ้ำในรอบนี้ 1\)/);
assert.match(element('xstage-drive-folder-status').textContent,/รูปแบบอื่นที่ยังไม่ได้ทำดัชนี 1/);
existingRows=[...lastRows];
const readsBeforeRepeat=reads;
await workflow.rebuild();
assert.equal(published,1,'Existing songs must not be published again');
assert.equal(reads,readsBeforeRepeat,'Verified unchanged packages must reuse checkpoints');
assert.match(element('xstage-drive-folder-status').textContent,/ฐานเดิม 2 เพลง/);
assert.match(element('xstage-drive-folder-status').textContent,/เพิ่มใหม่ 0 เพลง/);
assert.match(element('xstage-drive-folder-status').textContent,/MIDI ซ้ำ 3 \(มีในฐานแล้ว 3 · ซ้ำในรอบนี้ 0\)/);
assert.match(element('xstage-drive-folder-status').textContent,/ฐานเพลงรวม 2 เพลง/);
cancelOnList=true;
await workflow.rebuild();
assert.equal(published,1,'Cancelled scan must never publish a partial SQLite catalog');
assert.match(element('xstage-drive-folder-status').textContent,/พักงานอย่างปลอดภัย/);
denied=true;
await workflow.rebuild();
assert.equal(published,1,'Folder permission failures must keep the last published DB unchanged');
denied=false;

const outside='externalFolder123',outsideParent='externalParent123';
parents.set(outside,outsideParent);parents.set(outsideParent,'root');
names.set(outside,'Outside');names.set(outsideParent,'Unrelated');
for(const kind of ['music','soundfont','fx']){
  await assert.rejects(window.XStageDriveFolders.verifyFolder(new FakeDrive(),outside,root,kind),/ภายในคลังหลัก/);
}
pick={id:outside,name:'Outside'};await workflow.choose('music');
assert.equal(workflow.getFolderId('account1',root,'music'),music);
pick={id:retiredId,name:'retired'};await workflow.choose('music');
assert.equal(workflow.getFolderId('account1',root,'music'),music,
  'Retired Drive root must never replace a live source');
pick={id:music,name:'XMID'};denied=true;
await workflow.choose('music');
assert.equal(workflow.getFolderId('account1',root,'music'),music,
  'Failed Drive permission check must not rewrite saved selections');
denied=false;
const selections=window.XStageDriveFolders.readSelections('account1',root);
assert.equal(selections.fx.id,fx);
assert.ok(!JSON.stringify([...values.values()]).includes('token1'),
  'OAuth token must never be persisted in folder choices');
const folderMime='application/vnd.google-apps.folder';
const inventoryDrive={listChildren:async id=>id==='fontSource1234'?
  [{id:'sf2nested123',name:'nested',mimeType:folderMime},{id:'bank0001',name:'a.SF2'}]:
  [{id:'bank0001',name:'a.SF2'},{id:'bank0002',name:'b.sf3'},
   {id:'fx000001',name:'c.wav',mimeType:'audio/wav'},{id:'song0001',name:'d.XMID'}]};
let openedUrl='',closedTabs=0;
window.open=()=>({opener:window,location:{replace:url=>{openedUrl=url;}},close(){closedTabs++;}});
await workflow.openDriveFolder('music');
assert.equal(openedUrl,'https://drive.google.com/drive/folders/'+music);
parents.set(music,outsideParent);openedUrl='';
await workflow.openDriveFolder('music');
assert.equal(openedUrl,'','Moved folder must never open outside the library');
assert.equal(closedTabs,1);
parents.set(music,root);
const defaultRoot='defaultRoot1234',defaultMusic='defaultSongs1234';
parents.set(defaultMusic,defaultRoot);names.set(defaultMusic,'SONGS');
const originalList=FakeDrive.prototype.listChildren;
FakeDrive.prototype.listChildren=async function(id){
  if(id===defaultRoot)return [{id:defaultMusic,name:'SONGS',mimeType:folderMime}];
  return originalList.call(this,id);
};
current={sub:'account1',rootId:defaultRoot,token:'token1'};
await workflow.discoverDefaults();
assert.equal(workflow.getFolderId('account1',defaultRoot,'music'),defaultMusic);
assert.equal(workflow.getFolderId('account1',root,'music'),music);
assert.equal(workflow.getFolderId('account1',defaultRoot,'soundfont'),'');
assert.equal(uploads,0,'Discovering standard folders must not upload or create any file');
const inventory=await window.XStageDriveFolders.countSourceFiles(inventoryDrive,font);
assert.equal(inventory.total,4);assert.equal(inventory.sf2,1);assert.equal(inventory.sf3,1);
assert.equal(inventory.fx,1);assert.equal(inventory.xmid,1);
console.log('PASS: Three user-picked Drive folders, account-scoped preferences, retired-folder safety, deferred one-time DB, and raw MIDI dedup');

const compare=window.XStageDriveFolders.compareCatalog;
const sig='a'.repeat(32),raw='b'.repeat(32),sig2='c'.repeat(32);
const mfile={id:'verifiedFile123',ext:'xmid',md5Checksum:sig,size:100};
const dbRows=new Map([['song',{webSongId:'song',xmid:{fileId:mfile.id,md5Checksum:sig,size:100},midiHash:raw,midiSize:40}]]);
const contextKey={sub:'account1',rootId:root};
assert.equal((await compare([mfile],dbRows,null,contextKey,music)).equal,true);
assert.equal((await compare([{...mfile,md5Checksum:sig2}],dbRows,null,contextKey,music)).equal,false,'Equal counts cannot conceal changed file content');
assert.equal((await compare([mfile,{...mfile,id:'duplicate123'}],dbRows,null,contextKey,music)).equal,true,'Verified identical package need not create another DB row');
const diff={...mfile,id:'otherFile123',md5Checksum:sig2};
assert.equal((await compare([mfile,diff],dbRows,null,contextKey,music)).newFiles,1);
assert.equal((await compare([mfile,diff],dbRows,{get:async()=>({packedMd5:sig2,midiHash:raw,midiSize:40})},contextKey,music)).equal,true,'Previously verified raw MIDI duplicate is represented');
assert.equal((await compare([{...mfile,md5Checksum:''}],dbRows,null,contextKey,music)).equal,false);
assert.equal((await compare([],dbRows,null,contextKey,music)).stale,1);
const pcFile={...mfile,relative:'MIDI/XMID/1/10001.xmid'};
const pcRows=new Map([['pc',{webSongId:'pc',pendingDriveLink:true,
  xmid:{fileId:'',path:'SONGS/'+pcFile.relative,md5Checksum:sig,size:100},midiHash:raw,midiSize:40}]]);
assert.equal((await compare([pcFile],pcRows,null,contextKey,music,()=>{},true)).equal,true);
assert.equal((await compare([pcFile],pcRows,null,contextKey,music)).equal,false);
assert.equal((await compare([{...pcFile,relative:'wrong.xmid'}],pcRows,null,contextKey,music,()=>{},true)).equal,false);
assert.equal((await compare([{...pcFile,md5Checksum:sig2}],pcRows,null,contextKey,music,()=>{},true)).equal,false);
assert.equal((await compare([pcFile,{...pcFile,id:'ambiguousFile123'}],pcRows,null,contextKey,music,()=>{},true)).equal,false);
assert.equal(window.XStageDriveFolders.verifiedPackageRows([pcFile],pcRows,true).size,1);
console.log('PASS: verified catalog reconciliation handles same-count changes, duplicates, missing checksums and stale rows');

current={sub:'account1',rootId:root,token:'token1'};
const verified=window.XStageDriveFolders.verifiedPackageRows(
  records.filter(f=>/\.xmid$/i.test(f.name)).map(f=>({...f,ext:'xmid'})),new Map(existingRows.map(r=>[r.webSongId,r])));
assert.equal(verified.size,2);
const readBeforeFast=reads;
savedMetadata.clear();
const midiC=Buffer.from(midiA);midiC[13]=99;
const fresh=packageFile('fresh-incremental',midiC);
records.push({...records[0],id:'copyOfKnown123',name:'copy.XMID'});
for(let i=0;i<10;i++){
  const id='newCopy'+String(i).padStart(3,'0');
  records.push({id,name:id+'.XMID',size:String(fresh.bytes.length),mimeType:'application/octet-stream',md5Checksum:fresh.md5});
  blobs.set(id,fresh.bytes);
}
await workflow.rebuild();
assert.equal(reads-readBeforeFast,2,'Only unknown different-metadata duplicate and one new package may download; known rows and byte-identical copies must skip');
assert.equal(published,2);
assert.equal(lastRows.length,3,'One new MIDI, despite ten identical copies');
assert.match(element('xstage-drive-folder-status').textContent,/ข้ามจากฐาน 3/);
assert.match(element('xstage-drive-folder-status').textContent,/ดาวน์โหลดตรวจจริง 2/);
const limits=window.XStageDriveFolders.inspectionLimits;
assert.equal(limits({connection:{saveData:true}}).workers,4);
assert.equal(limits({deviceMemory:8,connection:{effectiveType:'4g'}}).workers,12);
assert.equal(limits({}).workers,8);
const changedKnown={...records[0],ext:'xmid',md5Checksum:'f'.repeat(32)};
assert.equal(window.XStageDriveFolders.verifiedPackageRows([changedKnown],new Map(existingRows.map(r=>[r.webSongId,r]))).size,0,'Changed contents must never bypass inspection');
console.log('PASS: incremental scan bypasses verified database files, shares new identical packages across batches and preserves changed-file inspection');

const midiD=Buffer.from(midiA);midiD[13]=101;
const pausePackage=packageFile('pause-safe',midiD);
const pauseId='pauseFile123';
records.push({id:pauseId,name:'pause.XMID',size:String(pausePackage.bytes.length),mimeType:'application/octet-stream',md5Checksum:pausePackage.md5});
blobs.set(pauseId,pausePackage.bytes);
existingRows=[...lastRows];
const normalRead=FakeDrive.prototype.getSqlite;
let askedPause=false;
FakeDrive.prototype.getSqlite=async function(id){
  if(id===pauseId&&!askedPause){askedPause=true;workflow.cancel();}
  return normalRead.call(this,id);
};
const beforePausePublications=published;
await workflow.rebuild();
assert.equal(published,beforePausePublications,'Pause must not publish an incomplete catalog');
assert.match(element('xstage-drive-folder-status').textContent,/พักงานอย่างปลอดภัย/);
assert.match(element('xstage-drive-build-db').textContent,/ทำงานต่อจากจุดที่หยุด/);
const readsAtPause=reads;
await workflow.rebuild();
assert.equal(reads,readsAtPause,'Resume must reuse completed verification from the drained batch');
assert.equal(published,beforePausePublications+1);
assert.equal(lastRows.length,4);
console.log('PASS: safe pause drains active reads, persists results and resumes without downloading again');

// A new, unified PC/Online DB must ignore legacy rows but preserve media.
const priorPublished=published;
const obsolete={webSongId:'obsolete/local-only',code:'OLD',
  title:'obsolete',artist:'legacy',midiHash:'f'.repeat(32),midiSize:12};
existingRows=[...lastRows,obsolete];
names.set(music,'SONGS');
window.confirm=()=>true;
await workflow.rebuild({fresh:true});
assert.equal(published,priorPublished+1,
  'Explicit full rebuild publishes a new SQLite, even with no new files');
assert.equal(lastRows.length,4,
  'Full rebuild includes all distinct XMID MIDI and no legacy-only songs');
assert.ok(!lastRows.some(row=>row.webSongId==='obsolete/local-only'),
  'Rebuild must not preserve historical DB-only entries');
assert.ok(lastRows.every(row=>row.originalRelativePath&&row.xmid?.fileId),
  'PC and Online must share one SONGS-relative path and cloud media identity');
assert.match(element('xstage-drive-folder-status').textContent,/สร้างฐานเสร็จ/);
console.log('PASS: explicit shared PC/Online SQLite rebuild ignores legacy rows without deleting media');

