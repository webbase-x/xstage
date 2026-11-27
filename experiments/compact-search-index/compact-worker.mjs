import {validateCompactIndex,searchCompactIndex} from './compact-query.mjs';
const url='https://cdn.jsdelivr.net/npm/@sqlite.org/sqlite-wasm@3.54.1-build1/dist/index.mjs';
let db,pool,active=null,tail=Promise.resolve();
async function dispatch(m){
 if(m.action==='open'){
  if(db)throw Error('Index already open');
  if(!/^[a-f0-9]{64}$/.test(m.owner)||!m.file||m.file.size!==m.size||!(/^[a-f0-9]{32}$/.test(m.md5)))throw Error('Invalid index identity');
  const {default:init}=await import(url);
  const sqlite=await init();
  pool=await sqlite.installOpfsSAHPoolVfs({name:'xstage-compact-'+m.owner,directory:'xstage-compact-v1-'+m.owner,initialCapacity:4,clearOnInit:false});
  const name='/'+m.md5+'-'+m.size+'.sqlite3';
  if(!pool.getFileNames().includes(name)){
   let offset=0;
   try{
    const n=await pool.importDb(name,async()=>{
     if(offset===m.size)return undefined;
     const end=Math.min(m.size,offset+1048576),bytes=new Uint8Array(await m.file.slice(offset,end).arrayBuffer());
     if(bytes.length!==end-offset)throw Error('Incomplete index');
     offset=end;return bytes;
    });
    if(n!==m.size)throw Error('Incomplete import');
   }catch(e){try{pool.unlink(name);}catch{}throw e;}
  }
  try{
   db=new pool.OpfsSAHPoolDb(name,'r');
   db.exec('PRAGMA query_only=ON; PRAGMA cache_size=-8192; PRAGMA mmap_size=0; PRAGMA trusted_schema=OFF;');
   if(db.exec({sql:'PRAGMA quick_check(1)',rowMode:'array',returnValue:'resultRows'})[0]?.[0]!=='ok')throw Error('Index integrity check failed');
   active=validateCompactIndex(db,m.source);
   return active;
  }catch(e){db?.close();db=null;try{pool.unlink(name);}catch{}throw e;}
 }
 if(m.action==='close'){db?.close();db=null;active=null;pool?.pauseVfs?.();return true;}
 if(!db||!active)throw Error('Index not opened');
 if(m.action==='search')return searchCompactIndex(db,m.term,{mode:m.mode,cursor:m.cursor});
 throw Error('Unsupported operation');
}
self.onmessage=({data})=>{if(!data||typeof data.id!=='string')return;tail=tail.then(async()=>{try{self.postMessage({id:data.id,result:await dispatch(data)});}catch(e){self.postMessage({id:data.id,error:String(e.message||e)});}});};
