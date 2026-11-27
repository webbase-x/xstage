/* Read-only disk catalog for Web. Never deserialize a full SQLite file or
 * materialize the entire song table. Called inside a dedicated worker. */
export const CHUNK_BYTES=1024*1024;
export const PAGE_SIZE=5;
const FORMAT='xstage-sqlite3-v1';
const fail=message=>{throw new Error(message);};
const scalar=(db,sql,bind=[])=>db.exec({sql,bind,rowMode:'array',returnValue:'resultRows'})[0]?.[0];
const rows=(db,sql,bind=[])=>db.exec({sql,bind,rowMode:'array',returnValue:'resultRows'});
export function revisionName(md5,size){
  if(!/^[a-f0-9]{32}$/.test(String(md5))||!Number.isSafeInteger(size)||size<100)fail('Invalid catalog identity');
  return '/'+md5+'-'+size+'.sqlite3';
}
export function chunkSource(file,onProgress=()=>{}){
  if(!file||!Number.isSafeInteger(file.size)||file.size<100)fail('Invalid SQLite file');
  let offset=0;
  return async()=>{
    if(offset===file.size)return undefined;
    const end=Math.min(file.size,offset+CHUNK_BYTES);
    const bytes=new Uint8Array(await file.slice(offset,end).arrayBuffer());
    if(bytes.length!==end-offset)fail('Incomplete catalog file');
    offset=end;onProgress(offset,file.size);
    return bytes;
  };
}
export function openReadOnly(pool,name){
  const db=new pool.OpfsSAHPoolDb(name,'r');
  try{
    db.exec('PRAGMA query_only=ON; PRAGMA cache_size=-8192; PRAGMA mmap_size=0; PRAGMA trusted_schema=OFF;');
    if(scalar(db,'PRAGMA quick_check(1)')!=='ok')fail('SQLite integrity check failed');
    const meta=Object.fromEntries(rows(db,'SELECT key,value FROM catalog_meta'));
    if(meta.format!==FORMAT||meta.schemaVersion!=='1'||meta.kind!=='snapshot'||!meta.generation)
      fail('Unsupported SQLite catalog');
    const columns=new Set(rows(db,'PRAGMA table_info(songs)').map(row=>row[1]));
    for(const col of ['id','web_song_id','search','playable','payload','code','title','artist'])
      if(!columns.has(col))fail('Missing SQLite column: '+col);
    const count=scalar(db,'SELECT count(*) FROM songs WHERE playable=1');
    if(!Number.isSafeInteger(count)||count<0)fail('Invalid catalog count');
    return {db,count,generation:meta.generation};
  }catch(error){db.close();throw error;}
}
function decode(row){
  if(!row)return null;
  const song=JSON.parse(row[1]);
  if(!song||typeof song.webSongId!=='string'||!song.webSongId||song.webSongId!==row[0])
    fail('Invalid song identity in SQLite');
  return song;
}
export function searchPage(db,raw,cursor=null){
  const term=String(raw||'').normalize('NFC').toLocaleLowerCase('th').trim().slice(0,256);
  if(!term)return {songs:[],total:0,cursor:null,hasMore:false};
  const words=term.split(/\s+/u).filter(Boolean).slice(0,16);
  if(cursor!==null&&!Number.isSafeInteger(cursor))fail('Invalid search cursor');
  const where='playable=1 AND '+words.map(()=> 'instr(search,?)>0').join(' AND ');
  const total=scalar(db,'SELECT count(*) FROM songs WHERE '+where,words);
  const clause=cursor===null?'':' AND id>?';
  const page=rows(db,'SELECT web_song_id,payload,id FROM songs WHERE '+where+clause+' ORDER BY id LIMIT '+(PAGE_SIZE+1),cursor===null?words:[...words,cursor]);
  const hasMore=page.length>PAGE_SIZE;
  const selected=page.slice(0,PAGE_SIZE);
  return {songs:selected.map(decode),total,cursor:selected.at(-1)?.[2]??null,hasMore};
}
export function lookupSong(db,id='',code='',title='',artist=''){
  const find=(sql,bind)=>decode(rows(db,sql,bind)[0]);
  if(id){const song=find('SELECT web_song_id,payload FROM songs WHERE playable=1 AND web_song_id=? LIMIT 1',[String(id)]);if(song)return song;}
  if(code){const song=find('SELECT web_song_id,payload FROM songs WHERE playable=1 AND code=? ORDER BY id LIMIT 1',[String(code)]);if(song)return song;}
  if(title)return find('SELECT web_song_id,payload FROM songs WHERE playable=1 AND title=?'+(artist?' AND artist=?':'')+' ORDER BY id LIMIT 1',artist?[String(title),String(artist)]:[String(title)]);
  return null;
}
export function randomSong(db){
  return decode(rows(db,'SELECT web_song_id,payload FROM songs WHERE playable=1 ORDER BY random() LIMIT 1')[0]);
}
export async function importRevision(pool,file,md5,size,onProgress){
  const name=revisionName(md5,size);
  if(file.size!==size)fail('Catalog size changed');
  // A caller must first verify MD5 of the source file using the streaming
  // web-catalog-disk adapter. The VFS import may change SQLite journal flags.
  if(pool.getFileNames().includes(name)){
    try{return {...openReadOnly(pool,name),name,fromDisk:true};}
    catch{pool.unlink(name);}
  }
  try{
    const written=await pool.importDb(name,chunkSource(file,onProgress));
    if(written!==size)fail('Incomplete SQLite import');
    return {...openReadOnly(pool,name),name,fromDisk:false};
  }catch(error){pool.unlink(name);throw error;}
}
