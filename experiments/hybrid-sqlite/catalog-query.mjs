/* Read-only catalog query plan. No COUNT(*) or arbitrary SQL from UI.
 * A short search is a title prefix, never an unbounded substring scan.
 * The PC schema has local paths, not verified Drive IDs: return a preview,
 * do not treat those paths as playable media references. */
export const PAGE_SIZE=5;
const escapeLike=s=>s.replace(/[\\%_]/g,'\\$&')+'%';
const text=s=>String(s??'').normalize('NFC').trim().slice(0,120);
export function catalogSchema(tables,columns){
  const names=new Set(tables),cols=new Set(columns);
  for(const col of ['id','code','title','artist','playable','search'])if(!cols.has(col))throw Error('Unsupported catalog column: '+col);
  const shared=names.has('catalog_meta')&&cols.has('web_song_id')&&cols.has('payload');
  if(!shared&&!cols.has('path'))throw Error('Unknown catalog schema');
  return {kind:shared?'shared-v1':'pc-local',fts:names.has('song_fts')};
}
export function planSearch(schema,raw,{mode='auto',cursor=null}={}){
  const term=text(raw);if(!term)return null;
  if(!['auto','code','title','contains'].includes(mode))throw Error('Invalid search mode');
  if(mode==='auto')mode=/^[0-9]+$/.test(term)?'code':schema.fts&&[...term].length>=3?'contains':'title';
  const fields='id,code,title,artist'+(schema.kind==='shared-v1'?',web_song_id':',path');
  if(mode==='code'){
    if(cursor!==null&&(!Number.isSafeInteger(cursor.id)||cursor.id<0))throw Error('Invalid cursor');
    return {mode,sql:'SELECT '+fields+' FROM songs WHERE playable=1 AND code=?'+(cursor?' AND id>?':'')+' ORDER BY id LIMIT 6',bind:cursor?[term,cursor.id]:[term]};
  }
  if(mode==='contains'){
    if(!schema.fts||[...term].length<3)throw Error('Substring search requires FTS5 and at least 3 characters');
    if(cursor!==null&&(!Number.isSafeInteger(cursor.id)||cursor.id<0))throw Error('Invalid cursor');
    // Quoted FTS literal prevents query syntax injection.
    const literal='"'+term.replace(/"/g,'""')+'"';
    return {mode,sql:'SELECT '+fields+' FROM songs WHERE id IN (SELECT rowid FROM song_fts WHERE song_fts MATCH ?) AND playable=1'+(cursor?' AND id>?':'')+' ORDER BY id LIMIT 6',bind:cursor?[literal,cursor.id]:[literal]};
  }
  if(cursor!==null&&(!Number.isSafeInteger(cursor.id)||typeof cursor.title!=='string'))throw Error('Invalid cursor');
  return {mode:'title',sql:'SELECT '+fields+" FROM songs WHERE playable=1 AND title LIKE ? ESCAPE '\\'"+(cursor?' AND (title COLLATE NOCASE,id)>(?,?)':'')+' ORDER BY title COLLATE NOCASE,id LIMIT 6',bind:cursor?[escapeLike(term),cursor.title,cursor.id]:[escapeLike(term)]};
}
export function pageResult(schema,plan,rows){
  const page=rows.slice(0,PAGE_SIZE).map(r=>({id:r[0],code:r[1],title:r[2],artist:r[3],...(schema.kind==='shared-v1'?{webSongId:r[4]}:{sourcePath:r[4],previewOnly:true})}));
  const last=page.at(-1);
  return {songs:page,hasMore:rows.length>PAGE_SIZE,cursor:last?{id:last.id,...(plan.mode==='title'?{title:last.title}:{})}:null,mode:plan.mode,total:null};
}
