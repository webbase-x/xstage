/* Diagnostic only: CORS-hidden headers must never grant SQL access.
 * Two overlapping reads, at most 128 KiB total. No full-file fallback.
 * The production VFS retains strict Content-Range + strong ETag checks. */
import {googleRangeResponse} from './range-source.mjs';
export async function diagnoseGoogleRange({fileId,token,size,current=()=>true,fetcher=fetch}){
 if(!Number.isSafeInteger(size)||size<100)throw Error('Invalid SQLite file size');
 const read=googleRangeResponse({fileId,token,fetcher});
 const started=performance.now(),block=Math.min(size,65536),offset=Math.min(Math.floor(block/2),size-block);
 const samples=[];let received=0;
 const assertCurrent=()=>{if(!current())throw new DOMException('Library changed','AbortError');};
 const summary={ok:false,transportOk:false,partialReadOk:false,wal:null,sqliteHeader:false,overlapMatches:null,distinctBlocks:null,conditionalVerified:false};
 async function sample(start,length,etag=null){
  assertCurrent();const controller=new AbortController();const t=performance.now(),timer=setTimeout(()=>controller.abort(),15000);
  let response,reader;
  const info={requested:'bytes='+start+'-'+(start+length-1),status:null,contentRange:null,contentLength:null,etagVisible:false,strongEtag:false,bytes:0,elapsedMs:null};
  samples.push(info);
  try{
   response=await read(start,start+length-1,{signal:controller.signal,etag});
   info.status=response.status;info.contentRange=response.headers.get('content-range');info.contentLength=response.headers.get('content-length');
   const actualTag=response.headers.get('etag');info.etagVisible=actualTag!==null;info.strongEtag=!!actualTag&&/^"[^"]+"$/.test(actualTag);
   if(response.status!==206)throw Error('Expected HTTP 206, received '+response.status);
   if(info.contentRange!==null&&info.contentRange!=='bytes '+start+'-'+(start+length-1)+'/'+size)throw Error('Exposed Content-Range mismatch');
   if(etag&&actualTag!==etag)throw Error('Conditional revision mismatch');
   if(!response.body?.getReader)throw Error('Streaming response unavailable');
   reader=response.body.getReader();const data=new Uint8Array(length);
   while(true){
    assertCurrent();const part=await reader.read();if(part.done)break;
    received+=part.value.byteLength;info.bytes+=part.value.byteLength;
    if(info.bytes>length){controller.abort();throw Error('Range response exceeds requested length');}
    data.set(part.value,info.bytes-part.value.byteLength);
   }
   if(info.bytes!==length)throw Error('Truncated range response');
   assertCurrent();return {data,tag:info.strongEtag?actualTag:null};
  }finally{
   clearTimeout(timer);controller.abort();
   try{if(reader)await reader.cancel();else await response?.body?.cancel();}catch{}
   try{reader?.releaseLock();}catch{}
   info.elapsedMs=Math.round(performance.now()-t);
  }
 }
 try{
  const first=await sample(0,block);
  summary.sqliteHeader=new TextDecoder().decode(first.data.subarray(0,16))==='SQLite format 3\0';
  if(!summary.sqliteHeader)throw Error('Invalid SQLite header');
  summary.wal=first.data[18]===2||first.data[19]===2;
  const second=await sample(offset,block,first.tag);
  summary.conditionalVerified=!!first.tag&&first.tag===second.tag;
  summary.overlapMatches=first.data.subarray(offset).every((b,i)=>b===second.data[i]);
  summary.distinctBlocks=offset>0&&first.data.some((b,i)=>b!==second.data[i]);
  summary.partialReadOk=summary.overlapMatches&&summary.distinctBlocks;
  if(!summary.overlapMatches)throw Error('Overlapping byte ranges do not match');
  if(!summary.distinctBlocks)throw Error('Range offset not independently demonstrated');
  summary.transportOk=summary.partialReadOk&&samples.every(s=>s.contentRange!==null)&&summary.conditionalVerified;
  summary.ok=summary.transportOk&&!summary.wal;
  summary.reason=!summary.transportOk?'Partial reads verified by length and overlap, but Content-Range or strong revision validator is not exposed':summary.wal?'WAL header: checkpointed immutable snapshot must be certified':null;
 }catch(e){summary.reason=String(e.message||e);}
 return {...summary,status:samples[0]?.status??null,bytes:received,ms:performance.now()-started,conditionalMs:samples[1]?.elapsedMs??null,samples};
}
