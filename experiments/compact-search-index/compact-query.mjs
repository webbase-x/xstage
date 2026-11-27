/* Read-only compact index consumer. For use in a disk-backed SQLite worker.
 * Discovery only: rows do not carry trusted media hashes or Drive file IDs. */
const rows=(db,sql,bind=[])=>db.exec({sql,bind,rowMode:'array',returnValue:'resultRows'});
export function validateCompactIndex(db,source){
  db.exec('PRAGMA query_only=ON; PRAGMA cache_size=-8192; PRAGMA mmap_size=0; PRAGMA trusted_schema=OFF;');
  const meta=Object.fromEntries(rows(db,'SELECT key,value FROM index_meta'));
  if(meta.format!=='xstage-search-index-v1'||meta.source_schema!=='pc-local'||meta.media_identity!=='unverified-preview-only')throw Error('Unsupported search index');
  if(!/^[a-f0-9]{32}$/.test(meta.source_md5)||!source||source.md5!==meta.source_md5||String(source.size)!==meta.source_bytes)throw Error('Search index is stale or belongs to another catalog');
  const count=Number(meta.count);
  if(!Number.isSafeInteger(count)||count<0)throw Error('Invalid song count');
  return Object.freeze({count,format:meta.format,sourceMd5:meta.source_md5});
}
export function searchCompactIndex(db,raw,{mode='auto',cursor=null}={}){
  const term=String(raw??'').normalize('NFC').trim().slice(0,120);
  if(!term)return {songs:[],hasMore:false,cursor:null};
  if(mode==='auto')mode=/^[0-9]+$/.test(term)?'code':[...term].length>=3?'contains':'title';
  if(!['code','title','artist','contains'].includes(mode))throw Error('Unsupported search mode');
  if(cursor!==null&&(!Number.isSafeInteger(cursor.id)||cursor.id<1||cursor.term!==term||cursor.mode!==mode))throw Error('Invalid search cursor');
  const fields='id,code,title,artist,path';
  let where,order,bind;
  if(mode==='title'||mode==='artist'){
    where=mode+" LIKE ? ESCAPE '\\'";
    bind=[term.replace(/[\\%_]/g,'\\$&')+'%'];
    order=mode+' COLLATE NOCASE,id';
    if(cursor){if(typeof cursor.value!=='string')throw Error('Invalid prefix cursor');where+=' AND ('+mode+' COLLATE NOCASE,id)>(?,?)';bind.push(cursor.value,cursor.id);}
  }else{
    if(mode==='contains'&&[...term].length<3)throw Error('FTS5 requires three characters');
    where=mode==='code'?'code=?':'id IN (SELECT rowid FROM song_fts WHERE song_fts MATCH ?)';
    bind=[mode==='code'?term:'"'+term.replace(/"/g,'""')+'"'];order='id';
    if(cursor){where+=' AND id>?';bind.push(cursor.id);}
  }
  const result=rows(db,'SELECT '+fields+' FROM songs WHERE '+where+' ORDER BY '+order+' LIMIT 6',bind);
  const songs=result.slice(0,5).map(([id,code,title,artist,path])=>({id,code,title,artist,sourcePath:path,previewOnly:true}));
  const last=songs.at(-1);
  return {songs,hasMore:result.length>5,cursor:last?{mode,term,id:last.id,...(['title','artist'].includes(mode)?{value:last[mode]}:{})}:null};
}
