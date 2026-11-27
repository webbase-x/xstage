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

import {portableXmidPath,createPathResolver} from '../experiments/hybrid-sqlite/path-resolver.mjs';
import {probeGoogleRange} from '../experiments/hybrid-sqlite/google-live.mjs';
{
 const d='D:\\xstagesong\\xmid\\0\\00074652.xmid',g='G:\\My Drive\\XStageKaraoke\\SONGS\\MIDI\\XMID\\0\\00074652.xmid';
 assert.deepEqual(portableXmidPath(d),portableXmidPath(g));
 assert.deepEqual(portableXmidPath(d),['SONGS','MIDI','XMID','0','00074652.xmid']);
 assert.throws(()=>portableXmidPath('XMID/../bad.xmid'));
 const files=['SONGS','MIDI','XMID','0','00074652.xmid'];
 let calls=0,active=true,duplicate=false;
 const resolver=createPathResolver({rootId:'root',current:()=>active,list:async q=>{
   calls++;const i=files.findIndex(n=>q.includes("name='"+n+"'"));
   const parent=i===0?'root':'id'+(i-1);
   assert.ok(q.includes("'"+parent+"' in parents"));
   const f={name:files[i],id:'id'+i,parents:[parent],mimeType:i===4?'application/octet-stream':'application/vnd.google-apps.folder',size:'116527',md5Checksum:'a'.repeat(32)};
   return duplicate&&i===4?[f,{...f,id:'another'}]:[f];
 }});
 const first=await resolver(d);assert.equal(first.fileId,'id4');assert.equal(first.identityVerified,false);assert.equal(calls,5);
 const second=await resolver(g);assert.equal(second.fileId,first.fileId);assert.equal(calls,6);
 duplicate=true;await assert.rejects(resolver(d),/Duplicate/);
 active=false;await assert.rejects(resolver(d),/Library changed/);
}
{
 const header=new Uint8Array(65536);header.set(new TextEncoder().encode('SQLite format 3\0'));header[18]=header[19]=1;
 for(const kind of ['ok','missing-etag','wal','full','changed']){
   let count=0;header[18]=header[19]=kind==='wal'?2:1;
   const result=await probeGoogleRange({fileId:'mock',token:'mock',size:65536,fetcher:async(url,opts)=>{
     count++;assert.equal(opts.headers.Range,'bytes=0-65535');
     if(count>1)assert.equal(opts.headers['If-Match'],'"r1"');
     return new Response(header,{status:kind==='full'?200:206,headers:{'Content-Range':'bytes 0-65535/65536',...(kind==='missing-etag'?{}:{ETag:kind==='changed'&&count>1?'"r2"':'"r1"'})}});
   }}).catch(error=>({ok:false,error:error.message}));
   assert.equal(result.ok,kind==='ok',kind);
   if(kind==='wal')assert.equal(result.wal,true);
   assert.equal(count,['ok','changed'].includes(kind)?2:1);
 }
}
console.log('PASS: selected-root XMID mapping, duplicate/identity safety, Google Range and WAL rejection');
