/* Real first-run function contract under simulated private Google Drive API.
 * No network, user credentials, public music, or remote Drive is accessed. */
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';
const app=readFileSync(new URL('../app.js',import.meta.url),'utf8');
const first=app.indexOf('async function createDriveV2Folder(');
const next=app.indexOf('async function privateFile(',first);
assert.ok(first>0&&next>first,'V2 bootstrap functions must be present');
const bootstrap=app.slice(first,next);
assert.doesNotMatch(bootstrap,/StageWeb\/current\.json|schemaVersion:1/);
let seq=0;
const files=new Map();
function list(q){
  const parent=q.match(/'([^']+)' in parents/)?.[1]||'root';
  const name=q.match(/name='([^']+)'/)?.[1];
  return [...files.values()].filter(x=>x.parent===parent&&(!name||x.name===name))
    .map(({id,name,mimeType})=>({id,name,mimeType,ownedByMe:true}));
}
const result=(obj,status=200)=>({ok:status>=200&&status<300,status,
  json:async()=>obj});
async function googleFetch(url,opts={}){
  assert.equal(opts.headers.Authorization,'Bearer private-token');
  if(url.includes('/upload/drive/v3/files')){
    const raw=await opts.body.text();
    assert.doesNotMatch(raw,/private-token/);
    const parts=raw.split('\r\n\r\n');
    const meta=JSON.parse(parts[1].split('\r\n--')[0]);
    const doc=JSON.parse(parts[2].split('\r\n--')[0]);
    assert.equal(doc.schemaVersion,2);
    const id='file'+(++seq);
    files.set(id,{id,parent:meta.parents[0],name:meta.name,mimeType:'application/json',doc});
    return result({id,md5Checksum:'a'.repeat(32)});
  }
  assert.ok(url.startsWith('https://www.googleapis.com/drive/v3/files?fields='));
  const meta=JSON.parse(opts.body);
  assert.equal(meta.mimeType,'application/vnd.google-apps.folder');
  const id='folder'+(++seq);
  files.set(id,{id,parent:meta.parents[0],name:meta.name,mimeType:meta.mimeType});
  return result({id});
}
const window={XStageCatalogV2:{pointer:(doc)=>{
  assert.equal(doc.schemaVersion,2);
  assert.equal(doc.format,'xstage-unified-v2');
  assert.ok(doc.catalogFileId);
}}};
const context={crypto:webcrypto,Blob,window,requestHeaders:token=>({Authorization:'Bearer '+token}),
  googleFetch,driveError:(code,label)=>new Error(label+' HTTP '+code),
  driveList:async q=>list(q),privateJson:async id=>files.get(id).doc,
  Error,JSON,Array,Uint8Array,Map};
vm.runInNewContext(bootstrap,context);
const setup=vm.runInNewContext('initializeWebV2Library',context);
const root=await setup('private-token');
const rootFile=files.get(root);
assert.equal(rootFile.name,'XStageWeb');
const db=[...files.values()].find(f=>f.parent===root&&f.name==='DB');
assert.ok(db,'create XStageWeb/DB');
const ptr=[...files.values()].find(f=>f.parent===db.id&&f.name==='current.json');
assert.ok(ptr,'create V2 DB/current.json');
assert.equal(ptr.doc.songCount,0);
const base=files.get(ptr.doc.catalogFileId);
assert.ok(base,'pointer references immutable private base');
assert.deepEqual(Array.from(base.doc.songs),[]);
const previousCount=files.size;
assert.equal(await setup('private-token',root),root);
assert.equal(files.size,previousCount,'do not duplicate or overwrite a published pointer');
const rootNames=[...files.values()].filter(f=>f.parent==='root').map(f=>f.name);
assert.deepEqual(rootNames,['XStageWeb']);
console.log('Private V2 Google Drive bootstrap mocked API: fresh + idempotent PASS');
