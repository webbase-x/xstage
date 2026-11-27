import assert from 'node:assert/strict';
import fs from 'node:fs';
const app=fs.readFileSync(new URL('../app.js',import.meta.url),'utf8');
const start=app.indexOf('async function pollPublishedCatalog(){');
const end=app.indexOf('\nsetInterval(pollPublishedCatalog,45000);',start);
assert.ok(start>=0&&end>start);
const source=app.slice(start,end);
const make=new Function('state','isRetiredDriveRoot','driveList','activeDriveCatalog',
  'stageWebCatalog','activateWebCatalog','restoreWebQueue','playbackHasActiveIntent','ui','num',
  'renderSongs','renderQueue','setStatus','console',source+'\nreturn pollPublishedCatalog;');
function fixture(){
  const state={authId:1,token:'token',accountSub:'account',libraryRootId:'root1',
    catalogDbDirId:'',catalogGeneration:'',songs:[],queue:[{code:'Q'}],current:{code:'NOW'}};
  const ui={songTotal:{},libraryState:{}};
  const f={state,ui,folders:[],pointer:null,readCount:0,renderCount:0,warnings:[],saved:[],
    beforeRead:null,queries:[]};
  f.poll=make(state,id=>id==='retired',async(q,t)=>{
    f.queries.push(q);assert.equal(t,'token');
    assert.match(q,/^'root1' in parents and name='DB'/);return f.folders;
  },async(id,t)=>{assert.equal(id,'db1');assert.equal(t,'token');return f.pointer?{pointer:f.pointer}:null;},
  async(pointer,sub,root,token,current)=>{
    assert.equal(sub,'account');assert.equal(root,'root1');assert.equal(token,'token');
    assert.equal(current(),true);f.readCount++;f.beforeRead?.();
    return {pointer,candidate:{count:1},holder:{owner:sub+':'+root}};
  },async(staged,dbId,current)=>{
    assert.equal(current(),true);assert.equal(dbId,'db1');
    state.webCatalog={count:staged.candidate.count,revision:staged.pointer.generation};
    state.catalogGeneration=staged.pointer.generation;
    assert.deepEqual(state.songs,[],'Do not hydrate the catalog into JS');
    f.saved.push([staged.holder.owner,staged.pointer.generation]);
    ui.songTotal.textContent=staged.candidate.count+' เพลง';
  },async()=>{},()=>false,
  ui,String,()=>f.renderCount++,()=>{},()=>{},{warn:msg=>f.warnings.push(msg)});
  return f;
}
{
  const f=fixture();
  await f.poll();assert.equal(f.readCount,0);
  f.folders=[{id:'db1'}];f.pointer={generation:'pc-v1'};
  await f.poll();
  assert.equal(f.readCount,0,'queued tracks take priority over staging the disk catalog');
  f.state.queue=[];
  await f.poll();
  assert.equal(f.state.catalogDbDirId,'db1');
  assert.equal(f.state.webCatalog.revision,'pc-v1');
  assert.equal(f.state.catalogGeneration,'pc-v1');
  assert.equal(f.ui.songTotal.textContent,'1 เพลง');
  assert.equal(f.saved[0][0],'account:root1');
  await f.poll();assert.equal(f.readCount,1);
  f.state.queue=[{code:'Q'}];
  f.pointer={generation:'web-v2'};await f.poll();
  assert.equal(f.state.webCatalog.revision,'pc-v1');
  assert.deepEqual(f.state.queue,[{code:'Q'}]);
  f.state.queue=[];await f.poll();
  assert.equal(f.state.webCatalog.revision,'web-v2');
  assert.deepEqual(f.state.current,{code:'NOW'});
  f.folders=[];await f.poll();assert.equal(f.state.webCatalog.revision,'web-v2');
}
{
  const f=fixture();f.folders=[{id:'db1'},{id:'db2'}];await f.poll();
  assert.equal(f.readCount,0);assert.equal(f.warnings.length,1);
}
{
  const f=fixture();f.folders=[{id:'db1'}];f.pointer={generation:'pc-v1'};f.state.queue=[];
  f.beforeRead=()=>{f.state.libraryRootId='root2';};
  await f.poll();assert.equal(f.state.songs.length,0);assert.equal(f.state.webCatalog,undefined);assert.equal(f.saved.length,0);
  assert.equal(f.state.catalogPolling,false);
}
{
  const f=fixture();f.state.libraryRootId='retired';await f.poll();
  assert.equal(f.queries.length,0);
}
{
  const f=fixture();f.folders=[{id:'db1'}];f.pointer={generation:'verified-v1'};f.state.queue=[];
  f.state.androidTvCatalogRetryPending=true;
  await f.poll();
  assert.equal(f.queries.length,0,'Pending catalog retry must not start background Drive polling');
  assert.equal(f.readCount,0);
  f.state.androidTvCatalogRetryPending=false;
  f.pointer={generation:'preview-v1',previewOnly:true};
  await f.poll();assert.equal(f.readCount,0,'Search-only preview must never activate playback catalog');
  f.pointer={generation:'verified-v1'};
  await f.poll();assert.equal(f.state.catalogGeneration,'verified-v1','Verified catalog refresh resumes after retry completes');
}
console.log('PASS: Android/Web discovers PC-created SQLite, refreshes revisions and preserves playback; duplicate/retired/switch guards');
