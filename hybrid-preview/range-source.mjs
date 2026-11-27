/* Experimental read-only range transport. No OAuth token persists; never
 * read an HTTP 200 response as a substitute for a 206. The session must
 * be pinned to a strong ETag or an immutable revision URL. */
export class RangeSource {
  constructor({size,readResponse,etag=null,immutable=false,blockSize=65536,cacheBytes=8*1048576,requestLimit=256,byteLimit=16*1048576}){
    if(!Number.isSafeInteger(size)||size<100)throw Error('Invalid SQLite size');
    if(!immutable&&(!etag||!/^"[^"]+"$/.test(etag)))throw Error('Strong revision validator required');
    if(!Number.isSafeInteger(blockSize)||blockSize<4096||blockSize>262144||cacheBytes<blockSize)throw Error('Invalid block cache');
    this.size=size;this.etag=etag;this.readResponse=readResponse;this.blockSize=blockSize;
    this.capacity=Math.floor(cacheBytes/blockSize);this.requestLimit=requestLimit;this.byteLimit=byteLimit;
    this.cache=new Map();this.requests=0;this.bytes=0;this.hits=0;this.queryRequests=0;this.queryBytes=0;this.invalid=false;
  }
  beginQuery(){if(this.invalid)throw Error('SQLite revision invalid');this.queryRequests=0;this.queryBytes=0;}
  stats(){return {requests:this.requests,bytes:this.bytes,hits:this.hits,cacheBlocks:this.cache.size,queryRequests:this.queryRequests,queryBytes:this.queryBytes};}
  async block(index){
    if(this.invalid)throw Error('SQLite revision invalid');
    if(this.cache.has(index)){const data=this.cache.get(index);this.cache.delete(index);this.cache.set(index,data);this.hits++;return data;}
    const start=index*this.blockSize,end=Math.min(this.size,start+this.blockSize)-1,length=end-start+1;
    if(length<=0)throw Error('Invalid Range offset');
    if(this.queryRequests>=this.requestLimit||this.queryBytes+length>this.byteLimit)throw Error('Range query budget exceeded; refine search or choose Offline Mode');
    this.queryRequests++;this.requests++;
    const ctrl=new AbortController();const timeout=setTimeout(()=>ctrl.abort(),15000);
    let reader;
    try{
      const response=await this.readResponse(start,end,{signal:ctrl.signal,etag:this.etag});
      if(response.status!==206||response.headers.get('content-range')!=='bytes '+start+'-'+end+'/'+this.size||
        (this.etag&&response.headers.get('etag')!==this.etag)){
        this.invalid=true;this.cache.clear();ctrl.abort();try{await response.body?.cancel();}catch{}
        throw Error('Range or SQLite revision mismatch');
      }
      if(!response.body?.getReader)throw Error('Streaming response required');
      reader=response.body.getReader();const output=new Uint8Array(length);let n=0;
      for(;;){const part=await reader.read();if(part.done)break;
        if(n+part.value.byteLength>length){this.invalid=true;this.cache.clear();ctrl.abort();throw Error('Oversized Range response');}
        output.set(part.value,n);n+=part.value.byteLength;this.bytes+=part.value.byteLength;this.queryBytes+=part.value.byteLength;}
      if(n!==length)throw Error('Truncated Range response');
      while(this.cache.size>=this.capacity)this.cache.delete(this.cache.keys().next().value);
      this.cache.set(index,output);return output;
    }finally{clearTimeout(timeout);if(reader){try{await reader.cancel();}catch{}try{reader.releaseLock();}catch{}}}
  }
  async read(offset,target){
    if(!Number.isSafeInteger(offset)||offset<0||!Number.isSafeInteger(target.length))throw Error('Invalid read');
    target.fill(0);let written=0;
    while(written<target.length&&offset<this.size){
      const data=await this.block(Math.floor(offset/this.blockSize));
      const within=offset%this.blockSize,take=Math.min(data.length-within,target.length-written);
      target.set(data.subarray(within,within+take),written);written+=take;offset+=take;
    }
    return written===target.length;
  }
  close(){this.invalid=true;this.cache.clear();}
}
// Only verified Google Drive file IDs are accepted. Tokens are held in the
// closure in memory; the client cannot use an arbitrary URL as a destination.
export function googleRangeResponse({fileId,token,fetcher=fetch}){
  if(!/^[A-Za-z0-9_-]+$/.test(fileId)||typeof token!=='string'||!token)throw Error('Invalid Google session');
  const url='https://www.googleapis.com/drive/v3/files/'+encodeURIComponent(fileId)+'?alt=media';
  return (start,end,{signal,etag})=>fetcher(url,{method:'GET',headers:{Authorization:'Bearer '+token,Range:'bytes='+start+'-'+end,...(etag?{'If-Match':etag}:{})},signal,cache:'no-store',redirect:'error'});
}
