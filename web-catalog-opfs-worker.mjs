/* Dedicated worker for the staged OPFS catalog API.
 * No OAuth tokens or Drive URLs cross this boundary. */
import {importRevision,searchPage,lookupSong,randomSong} from './web-catalog-opfs-core.mjs';
const SQLITE_URL='https://cdn.jsdelivr.net/npm/@sqlite.org/sqlite-wasm@3.53.4-build1/dist/index.mjs';
let pool,ownerKey,active=null,staged=null,tail=Promise.resolve();
const fail=message=>{throw new Error(message);};
async function getPool(owner){
  if(!/^[a-f0-9]{64}$/.test(owner))fail('Invalid owner scope');
  if(pool){if(owner!==ownerKey)fail('Catalog owner changed');return pool;}
  const {default:sqlite3InitModule}=await import(SQLITE_URL);
  const sqlite3=await sqlite3InitModule();
  pool=await sqlite3.installOpfsSAHPoolVfs({name:'xstage-catalog-'+owner,directory:'xstage-sql-pool-v1/'+owner,initialCapacity:8,clearOnInit:false});
  ownerKey=owner;
  return pool;
}
function discard(entry){
  if(!entry||entry===active)return;
  entry.db.close();
  pool.unlink(entry.name);
}
async function dispatch({id,action,owner,file,md5,size,capability,term,cursor,code,title,artist,songId}){
  if(action==='stage'){
    const p=await getPool(owner);
    if(staged&&staged!==active){discard(staged);staged=null;}
    const name='/'+md5+'-'+size+'.sqlite3';
    if(active?.name===name)return {capability:active.capability,count:active.count,generation:active.generation,fromDisk:true};
    const entry=await importRevision(p,file,md5,size,(received,total)=>self.postMessage({id,progress:{received,total}}));
    staged={...entry,capability:crypto.randomUUID()};
    return {capability:staged.capability,count:staged.count,generation:staged.generation,fromDisk:staged.fromDisk};
  }
  if(!pool||owner!==ownerKey)fail('Catalog owner changed');
  if(action==='activate'){
    if(active?.capability===capability)return true;
    if(!staged||staged.capability!==capability)fail('Catalog revision not staged');
    const previous=active;active=staged;staged=null;
    discard(previous);
    return true;
  }
  if(action==='close'){
    if(staged&&staged!==active)discard(staged);
    staged=null;
    // The active revision is kept on disk for the next verified login.
    active?.db.close();active=null;
    pool.pauseVfs?.();
    return true;
  }
  if(!active||active.capability!==capability)fail('Catalog revision changed');
  if(action==='search')return searchPage(active.db,term,cursor??null);
  if(action==='lookup')return lookupSong(active.db,songId,code,title,artist);
  if(action==='random')return randomSong(active.db);
  fail('Unsupported catalog operation');
}
self.onmessage=event=>{
  const request=event.data;
  if(!request||typeof request.id!=='string')return;
  tail=tail.then(async()=>{
    try{self.postMessage({id:request.id,result:await dispatch(request)});}
    catch(error){self.postMessage({id:request.id,error:String(error?.message||error)});}
  });
};
