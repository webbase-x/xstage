import assert from 'node:assert/strict';
import {RangeSource,googleRangeResponse} from '../experiments/hybrid-sqlite/range-source.mjs';
import {catalogSchema,planSearch,pageResult} from '../experiments/hybrid-sqlite/catalog-query.mjs';
const size=201338880;
let requests=[];
const response=(start,end,options)=>{requests.push({start,end,options});return new Response(new Uint8Array(end-start+1).fill(start/65536%251),{status:206,headers:{'Content-Range':'bytes '+start+'-'+end+'/'+size,ETag:'"rev1"'}});};
const make=opts=>new RangeSource({size,etag:'"rev1"',readResponse:response,...opts});
{
 const s=make({cacheBytes:2*65536});const b=new Uint8Array(4);
 assert.equal(await s.read(65534,b),true);assert.deepEqual([...b],[0,0,1,1]);
 assert.equal(s.stats().requests,2);await s.read(65536,b);assert.equal(s.stats().hits,1);
 await s.read(131072,b);assert.equal(s.stats().cacheBlocks,2);
 await s.read(0,b);assert.equal(s.stats().requests,4);
 const last=new Uint8Array(4);assert.equal(await s.read(size-2,last),false);
 assert.equal(last[2],0);assert.equal(last[3],0);s.close();
 await assert.rejects(s.read(0,b),/invalid/);
}
{
 const s=make({requestLimit:1});await s.read(0,new Uint8Array(1));
 await assert.rejects(s.read(65536,new Uint8Array(1)),/budget/);
 s.beginQuery();await s.read(65536,new Uint8Array(1));
}
for(const failure of ['http200','etag','range','overflow','truncated']){
 let cancelled=false;
 const s=make({readResponse:async(start,end)=>{
  const len=end-start+1;
  const body=new ReadableStream({start(c){if(failure!=='http200'){c.enqueue(new Uint8Array(failure==='overflow'?len+1:failure==='truncated'?len-1:len));c.close();}},cancel(){cancelled=true;}});
  return new Response(body,{status:failure==='http200'?200:206,headers:{'Content-Range':failure==='range'?'bytes 0-0/100':'bytes '+start+'-'+end+'/'+size,ETag:failure==='etag'?'"rev2"':'"rev1"'}});
 }});
 await assert.rejects(s.read(0,new Uint8Array(1)));
 if(failure==='http200')assert.equal(cancelled,true);
 assert.equal(s.stats().cacheBlocks,0);
}
{
 const fetcher=async(url,opts)=>{assert.match(url,/^https:\/\/www\.googleapis\.com\/drive\/v3\/files\/valid_id\?alt=media$/);
 assert.equal(opts.headers.Range,'bytes=0-4095');assert.equal(opts.headers['If-Match'],'"rev1"');
 assert.equal(opts.headers.Authorization,'Bearer mock');assert.equal(opts.redirect,'error');return {};};
 await googleRangeResponse({fileId:'valid_id',token:'mock',fetcher})(0,4095,{etag:'"rev1"'});
 assert.throws(()=>googleRangeResponse({fileId:'https://example.org',token:'mock'}));
}
{
 const schema=catalogSchema(['songs','song_fts'],['id','code','title','artist','playable','search','path']);
 assert.equal(schema.kind,'pc-local');
 const plan=planSearch(schema,'รัก');assert.equal(plan.mode,'contains');
 assert.match(plan.sql,/song_fts MATCH \?/);assert.equal(plan.bind[0],'"รัก"');
 const prefix=planSearch(schema,'%_');assert.equal(prefix.mode,'title');assert.equal(prefix.bind[0],'\\%\\_%');
 assert.match(prefix.sql,/ESCAPE/);
 assert.equal(planSearch(schema,'1').mode,'code');
 const page=pageResult(schema,plan,Array.from({length:6},(_,i)=>[i+1,'code','title','artist','path']));
 assert.equal(page.songs.length,5);assert.equal(page.hasMore,true);assert.equal(page.cursor.id,5);assert.equal(page.total,null);
 assert.equal(page.songs[0].previewOnly,true);
 assert.match(planSearch(schema,'รัก',{cursor:page.cursor}).sql,/id>\?/);
 const literal=planSearch(schema,'abc" OR');assert.equal(literal.bind[0],'"abc"" OR"');
 assert.throws(()=>planSearch({...schema,fts:false},'รัก',{mode:'contains'}));
 assert.throws(()=>catalogSchema(['songs'],['id']));
}
console.log('PASS: strict 206, revision guards, byte budgets, LRU, indexed five-row queries, PC preview only');
