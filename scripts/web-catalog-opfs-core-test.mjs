import assert from 'node:assert/strict';
import {chunkSource,revisionName,CHUNK_BYTES,searchPage,lookupSong,importRevision} from '../web-catalog-opfs-core.mjs';
const id='a'.repeat(32),size=256*1024*1024+123;
let peak=0,total=0,calls=0;
const file={size,slice(start,end){const n=end-start;peak=Math.max(peak,n);return {async arrayBuffer(){calls++;return new ArrayBuffer(n);}};}};
for(const bytes of [size,512*1024*1024+17,1024*1024*1024+31,2*1024*1024*1024+9]){
  const fake={...file,size:bytes};
  const next=chunkSource(fake);
  let received=0;
  for(;;){const part=await next();if(part===undefined)break;received+=part.length;}
  assert.equal(received,bytes);
}
assert.ok(peak<=CHUNK_BYTES);
assert.throws(()=>revisionName('../bad',size));
const songs=Array.from({length:13},(_,i)=>['id'+i,JSON.stringify({webSongId:'id'+i,title:'เพลง'}),i+1]);
let closed=0,unlinked=[];
class DB{
  constructor(name,flags){assert.equal(flags,'r');}
  close(){closed++;}
  exec(arg){
    if(typeof arg==='string')return this;
    const {sql,bind}=arg;
    if(sql.includes('quick_check'))return [['ok']];
    if(sql.includes('catalog_meta'))return [['format','xstage-sqlite3-v1'],['schemaVersion','1'],['kind','snapshot'],['generation','g1']];
    if(sql.includes('table_info'))return ['id','web_song_id','search','playable','payload','code','title','artist'].map((c,i)=>[i,c]);
    if(sql.includes('count(*)'))return [[songs.length]];
    if(sql.includes('web_song_id=?'))return songs.filter(r=>r[0]===bind[0]).slice(0,1);
    if(sql.includes('ORDER BY id LIMIT 6')){
      assert.equal(bind[0],'เพลง');
      return songs.filter(r=>r[2]>(bind[1]??0)).slice(0,6);
    }
    throw Error(sql);
  }
}
const pool={OpfsSAHPoolDb:DB,getFileNames:()=>[],unlink:n=>unlinked.push(n),async importDb(name,read){assert.equal(name,revisionName(id,size));assert.equal(typeof read,'function');let n=0;for(;;){const part=await read();if(part===undefined)break;assert.ok(part.length<=CHUNK_BYTES);n+=part.length;}return n;}};
const stage=await importRevision(pool,file,id,size,(received)=>{total=received;});
assert.equal(total,size);assert.equal(stage.count,13);
const one=searchPage(stage.db,'เพลง'),two=searchPage(stage.db,'เพลง',one.cursor),three=searchPage(stage.db,'เพลง',two.cursor);
assert.deepEqual([one.songs.length,two.songs.length,three.songs.length],[5,5,3]);
assert.deepEqual([one.hasMore,two.hasMore,three.hasMore],[true,true,false]);
assert.equal(new Set([...one.songs,...two.songs,...three.songs].map(s=>s.webSongId)).size,13);
assert.equal(lookupSong(stage.db,'id5').webSongId,'id5');
stage.db.close();
assert.equal(closed,1);
assert.deepEqual(unlinked,[]);
await assert.rejects(importRevision({...pool,importDb:async()=>12},file,id,size),/Incomplete/);
assert.deepEqual(unlinked,[revisionName(id,size)]);
console.log('PASS: simulated chunk source 256 MiB–2 GiB, bounded import, read-only paging, lookup and failed import cleanup; not a real browser OPFS test');
