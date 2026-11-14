import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {createHash,webcrypto} from 'node:crypto';

const read=path=>fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const page=read('index.html'),app=read('app.js'),style=read('cloud-import.css');
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
await assert.rejects(loadCatalog({
  listChildren:async()=>[{name:'current.json',mimeType:'application/json',id:'fake1234'},
                        {name:'current.json',mimeType:'application/json',id:'fake5678'}]
},'root'),/รุ่นเก่าไม่รองรับ/);
await assert.rejects(loadCatalog({
  listChildren:async id=>id==='root'
    ?[{name:'LYRICS',mimeType:'application/vnd.google-apps.folder',id:'folder'}]
    :[{name:'current.json',mimeType:'application/json',id:'a'},
      {name:'current.json',mimeType:'application/json',id:'b'}]
},'root'),/current.json ซ้ำ/);
// A Drive root without current.json is NOT empty merely because it has
// the two v4 folder names. Stranded audio must be rejected on both PC and Web.
const noPointer = file => ({
  listChildren:async id => id==='root'
    ? [{name:'AUDIO',id:'audio-id',mimeType:'application/vnd.google-apps.folder'},
       {name:'LYRICS',id:'lyrics-id',mimeType:'application/vnd.google-apps.folder'}]
    : id==='audio-id' ? (file?[{name:file,id:'orphan',mimeType:'audio/mpeg'}]:[]) : []
});
for(const name of ['song.mp3','song.mid','movie.mp4']){
  await assert.rejects(loadCatalog(noPointer(name),'root'),/current.json/,
    'Web importer must not initialize over unindexed '+name);
}
assert.equal((await loadCatalog(noPointer('piano.sf2'),'root')).rows.size,0,
  'SoundFont-only v4 library may be initialized safely');

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
const root=await drive.folder('root','XStageWeb');
assert.ok(root.startsWith('item'));
const target=await drive.ensurePath(root,['AUDIO','MP3','Songs','1']);
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
assert.ok(!read('cloud-import.js').includes('localStorage.setItem('),
  'Never persist Drive bearer tokens or upload session URLs in localStorage');
console.log('PASS: WEB upload DOM, Drive resumable chunks, MD5 dedup, catalog safety and auth isolation');
