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
  console,setTimeout,clearTimeout};Object.assign(window,{Blob,TextDecoder,TextEncoder});
vm.runInNewContext(read('cloud-import-core.js'),context,{filename:'cloud-import-core.js'});
vm.runInNewContext(read('xmid-browser.js'),context,{filename:'xmid-browser.js'});
window.XStageImportCore.hashBlob=async(blob)=>{
  const bytes=new Uint8Array(await blob.arrayBuffer());
  return createHash('md5').update(bytes).digest('hex');
};
window.XStageCloudImport={
  Drive:FakeDrive,
  loadCatalog:async()=>({pointer:null,rows:new Map()}),
  buildMidiIndex:async()=>({hashes:new Map(),duplicates:0,backfilled:0}),
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
assert.match(element('xstage-drive-folder-status').textContent,/MIDI ซ้ำ 1/);
assert.match(element('xstage-drive-folder-status').textContent,/รูปแบบอื่นที่ยังไม่ได้ทำดัชนี 1/);
cancelOnList=true;
await workflow.rebuild();
assert.equal(published,1,'Cancelled scan must never publish a partial SQLite catalog');
assert.match(element('xstage-drive-folder-status').textContent,/ยกเลิกการสร้างฐาน/);
denied=true;
await workflow.rebuild();
assert.equal(published,1,'Folder permission failures must keep the last published DB unchanged');
denied=false;

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
console.log('PASS: Three user-picked Drive folders, account-scoped preferences, retired-folder safety, deferred one-time DB, and raw MIDI dedup');
