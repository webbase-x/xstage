import {googleRangeResponse,RangeSource} from './range-source.mjs';
import {openRangeCatalog} from './range-catalog.mjs';
import {createPathResolver,portableXmidPath} from './path-resolver.mjs';
// Do not load WASM from third-party origins in an authenticated page.
// The experiment build copies the pinned package into this same-origin path.
const vendor=new URL('./vendor/',import.meta.url);
export async function probeGoogleRange({fileId,token,size,current=()=>true,fetcher=fetch}){
  const assertCurrent=()=>{if(!current())throw new DOMException('Library changed','AbortError');};
  assertCurrent();
  const read=googleRangeResponse({fileId,token,fetcher});
  const started=performance.now(),end=Math.min(size,65536)-1;
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
  let response,body;
  try{
    response=await read(0,end,{signal:controller.signal,etag:null});assertCurrent();
    const status=response.status,range=response.headers.get('content-range'),etag=response.headers.get('etag');
    if(status!==206||range!=='bytes 0-'+end+'/'+size){
      try{await response.body?.cancel();}catch{}
      return {ok:false,status,reason:'Expected HTTP 206 and exact exposed Content-Range'};
    }
    if(!etag||!/^"[^"]+"$/.test(etag)){
      try{await response.body?.cancel();}catch{}
      return {ok:false,status,reason:'Strong ETag not exposed; immutable revision not established'};
    }
    // Enforce the byte budget even if the server advertises a correct range.
    const first=new RangeSource({size,etag,readResponse:async()=>response,requestLimit:1,byteLimit:65536});
    body=new Uint8Array(end+1);await first.read(0,body);first.close();assertCurrent();
    const header=new TextDecoder().decode(body.subarray(0,16));
    if(header!=='SQLite format 3\0')throw Error('Invalid SQLite header');
    const wal=body[18]===2||body[19]===2;
    // Refuse a WAL-mode standalone file until the producer certifies a
    // checkpointed snapshot. Reading the main file alone can be stale.
    if(wal)return {ok:false,status,etag,wal,bytes:body.length,ms:performance.now()-started,reason:'WAL header: checkpointed immutable snapshot must be certified'};
    const conditional=new RangeSource({size,etag,readResponse:read,requestLimit:1,byteLimit:65536});
    const t=performance.now();await conditional.read(0,new Uint8Array(100));conditional.close();assertCurrent();
    return {ok:true,status,etag,wal,bytes:body.length*2,ms:performance.now()-started,conditionalMs:performance.now()-t};
  }finally{clearTimeout(timer);if(!current())controller.abort();}
}
export async function openGoogleExperiment({pointer,token,current,list,rootId,retiredRoots,fetcher=fetch}){
  const size=Number(pointer.contentBytes),fileId=pointer.catalogFileId;
  if(!Number.isSafeInteger(size)||size<100)throw Error('Missing verified Drive file size');
  const probe=await probeGoogleRange({fileId,token,size,current,fetcher});
  if(!probe.ok)return {probe};
  if(!current())throw new DOMException('Library changed','AbortError');
  const [{default:factory},SQLite,{FacadeVFS}]=await Promise.all([
    import(new URL('dist/wa-sqlite-async.mjs',vendor)),import(new URL('src/sqlite-api.js',vendor)),import(new URL('src/FacadeVFS.js',vendor))]);
  const module=await factory();
  const googleRead=googleRangeResponse({fileId,token,fetcher});
  const readResponse=async(...args)=>{if(!current())throw new DOMException('Library changed','AbortError');const r=await googleRead(...args);if(!current()){try{await r.body?.cancel();}catch{}throw new DOMException('Library changed','AbortError');}return r;};
  const reader=await openRangeCatalog({SQLite,module,FacadeVFS,sourceOptions:{size,etag:probe.etag,readResponse}});
  if(!current()){await reader.close();throw new DOMException('Library changed','AbortError');}
  const resolve=createPathResolver({rootId,list,current,retiredRoots});
  return {probe,reader,resolve};
}
