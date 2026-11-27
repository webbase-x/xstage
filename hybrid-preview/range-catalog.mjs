/* Experimental SQLite WASM adapter: Asyncify, no SharedArrayBuffer required.
 * Supply the pinned wa-sqlite module/API and FacadeVFS from a trusted local
 * build. Do not import code from a CDN after accepting an OAuth token. */
import {RangeSource} from './range-source.mjs';
import {catalogSchema,planSearch,pageResult} from './catalog-query.mjs';
export async function openRangeCatalog({SQLite,module,FacadeVFS,sourceOptions}){
  const source=new RangeSource(sourceOptions);
  const sqlite=SQLite.Factory(module);
  class ReadOnlyVFS extends FacadeVFS{
    constructor(){super('xstage-range',module);this.files=new Set();this.lastError=null;}
    jOpen(name,id,flags,out){
      if(!(flags&SQLite.SQLITE_OPEN_MAIN_DB)||!name||!(flags&SQLite.SQLITE_OPEN_READONLY))return SQLite.SQLITE_CANTOPEN;
      this.files.add(id);out.setInt32(0,SQLite.SQLITE_OPEN_READONLY,true);return SQLite.SQLITE_OK;
    }
    jClose(id){this.files.delete(id);return SQLite.SQLITE_OK;}
    async jRead(id,target,offset){
      if(!this.files.has(id))return SQLite.SQLITE_IOERR_READ;
      try{return (await source.read(offset,target))?SQLite.SQLITE_OK:SQLite.SQLITE_IOERR_SHORT_READ;}
      catch(e){this.lastError=e;return SQLite.SQLITE_IOERR_READ;}
    }
    jFileSize(id,out){out.setBigInt64(0,BigInt(source.size),true);return SQLite.SQLITE_OK;}
    jAccess(name,flags,out){out.setInt32(0,0,true);return SQLite.SQLITE_OK;}
    jWrite(){return SQLite.SQLITE_READONLY;}
    jTruncate(){return SQLite.SQLITE_READONLY;}
    jDelete(){return SQLite.SQLITE_READONLY;}
    jDeviceCharacteristics(){return SQLite.SQLITE_IOCAP_IMMUTABLE;}
    jSectorSize(){return 4096;}
  }
  const vfs=new ReadOnlyVFS();await vfs.isReady();sqlite.vfs_register(vfs,false);
  let db,closed=false,busy=false;
  async function rows(sql,bind=[]){
    const result=[];
    for await(const stmt of sqlite.statements(db,sql)){
      sqlite.bind_collection(stmt,bind);
      while(await sqlite.step(stmt)===SQLite.SQLITE_ROW)result.push(sqlite.row(stmt));
    }
    return result;
  }
  async function run(fn){
    if(closed||busy)throw Error('Catalog closed or busy');
    busy=true;source.beginQuery();vfs.lastError=null;
    try{return await fn();}catch(e){throw vfs.lastError||e;}finally{busy=false;}
  }
  try{
    db=await sqlite.open_v2('catalog.sqlite3',SQLite.SQLITE_OPEN_READONLY,'xstage-range');
    // Avoid quick_check and COUNT(*) here: both can download most of a remote file.
    await sqlite.exec(db,'PRAGMA query_only=ON; PRAGMA cache_size=-4096; PRAGMA mmap_size=0; PRAGMA temp_store=MEMORY; PRAGMA trusted_schema=OFF;');
    const tables=(await rows("SELECT name FROM sqlite_master WHERE type='table'")).map(x=>x[0]);
    const columns=(await rows('PRAGMA table_info(songs)')).map(x=>x[1]);
    const schema=catalogSchema(tables,columns);
    if(schema.kind==='shared-v1'){
      const meta=Object.fromEntries(await rows('SELECT key,value FROM catalog_meta'));
      if(meta.format!=='xstage-sqlite3-v1'||meta.schemaVersion!=='1'||meta.kind!=='snapshot')throw Error('Unsupported shared schema');
    }
    return Object.freeze({schema,stats:()=>source.stats(),async search(term,opts){
      return run(async()=>{const plan=planSearch(schema,term,opts);
        if(!plan)return {songs:[],hasMore:false,cursor:null,total:null};
        return pageResult(schema,plan,await rows(plan.sql,plan.bind));});
      },async close(){if(busy)throw Error('Query in progress');if(closed)return;closed=true;try{await sqlite.close(db);}finally{source.close();}}});
  }catch(e){if(db!==undefined)try{await sqlite.close(db);}catch{}source.close();throw vfs.lastError||e;}
}
