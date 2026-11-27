/* X-Stage private media: verified raw files in browser-managed persistent storage.
 * Never store an access token in CacheStorage, or return bytes across account/root scopes.
 * Prepared MIDI/audio remains subject to the separate RAM budget.
 */
(function(scope){
'use strict';
const MiB=1048576,MAX_CACHE=512*MiB,RESERVE=32*MiB;
const pending=new Map();
function cacheable(media){
  return /^[A-Za-z0-9_-]{5,256}$/.test(String(media?.fileId||''))&&
    /^[a-f0-9]{32}$/i.test(String(media?.md5Checksum||''))&&
    Number.isSafeInteger(Number(media?.size))&&Number(media.size)>0&&Number(media.size)<=MAX_CACHE;
}
function available(){
  return !!(scope.caches&&scope.crypto?.subtle&&scope.XStageImportCore?.MD5&&
    typeof scope.TransformStream==='function'&&typeof scope.Response==='function');
}
function check(signal,current){
  if(signal?.aborted||!current())throw new DOMException('Private media scope changed','AbortError');
}
async function cacheName(owner){
  const digest=await scope.crypto.subtle.digest('SHA-256',new TextEncoder().encode(owner));
  const hash=Array.from(new Uint8Array(digest),x=>x.toString(16).padStart(2,'0')).join('');
  return 'xstage-private-media-v1-'+hash;
}
function mediaKey(media){
  const url=new URL('./__xstage_private_media__/'+encodeURIComponent(media.fileId),scope.location.href);
  url.searchParams.set('md5',String(media.md5Checksum).toLowerCase());
  url.searchParams.set('bytes',String(media.size));
  return url.href;
}
function cachedBytes(key){
  try{return Math.max(0,Number(new URL(key.url||key).searchParams.get('bytes'))||0);}catch{return 0;}
}
async function reserve(cache,bytes,protectedKeys){
  let quota=MAX_CACHE,free=Infinity;
  try{
    const info=await scope.navigator?.storage?.estimate?.();
    if(Number(info?.quota)>0){
      quota=Math.min(MAX_CACHE,Math.floor(info.quota*.10));
      free=Math.max(0,info.quota-(Number(info.usage)||0)-RESERVE);
    }
  }catch{}
  if(bytes>quota)return false;
  const keys=await cache.keys();
  let total=keys.reduce((sum,key)=>sum+cachedBytes(key),0);
  for(const key of keys){
    if(total+bytes<=quota&&bytes<=free)break;
    const href=key.url||String(key);
    if(protectedKeys.has(href))continue;
    if(await cache.delete(key)){
      const n=cachedBytes(key);total-=n;free+=n;
    }
  }
  return total+bytes<=quota&&bytes<=free;
}
// Preserve a partial raw file on OPFS when a verified range transport is available.
// Cross-tab lock scopes the writer to the account/root and content revision.
// No token, URL or unverified bytes enter the playable CacheStorage entry.
async function resumeRaw(owner,media,rangeFetcher,signal,current){
  if(!rangeFetcher||!scope.navigator?.storage?.getDirectory||!scope.navigator?.locks?.request)return null;
  const name=await cacheName(owner),size=Number(media.size),expected=String(media.md5Checksum).toLowerCase();
  const root=await scope.navigator.storage.getDirectory();
  const partials=await root.getDirectoryHandle('xstage-media-partials-v1',{create:true});
  const dir=await partials.getDirectoryHandle(name,{create:true});
  const filename=expected+'-'+size+'.part';
  return scope.navigator.locks.request(name+':'+filename,async()=>{
    check(signal,current);
    const handle=await dir.getFileHandle(filename,{create:true});
    let file=await handle.getFile();
    let received=file.size<=size?file.size:0;
    let digest=new scope.XStageImportCore.MD5();
    if(received){
      const prefix=file.stream().getReader();
      try{
        while(true){
          check(signal,current);
          const {done,value}=await prefix.read();
          if(done)break;
          digest.append(value);
        }
      }finally{try{prefix.releaseLock();}catch{}}
    }
    let response=null,out=null,reader=null;
    try{
      if(received<size){
        response=await rangeFetcher(received);
        check(signal,current);
        if(received&&response.status===200){received=0;digest=new scope.XStageImportCore.MD5();}
        else if(received&&(
          response.status!==206||response.headers.get('Content-Range')!=='bytes '+received+'-'+(size-1)+'/'+size))
          throw Error('Private media resume range mismatch');
        else if(!received&&response.status!==200)throw Error('Private media download status mismatch');
        const advertised=Number(response.headers.get('Content-Length')||0);
        if(advertised&&advertised!==size-received)throw Error('Private media resume size mismatch');
        if(!response.body?.getReader)return null;
        out=await handle.createWritable({keepExistingData:received>0});
        if(received)await out.seek(received);
        reader=response.body.getReader();
        while(true){
          check(signal,current);
          const {done,value}=await reader.read();
          if(done)break;
          if(received+value.byteLength>size)throw Error('Private media size mismatch');
          await out.write(value);
          digest.append(value);received+=value.byteLength;
        }
        await out.close();out=null;
      }
      check(signal,current);
      if(received!==size)throw Error('Private media download interrupted');
      if(digest.end()!==expected){
        await dir.removeEntry(filename);
        throw Error('Private media MD5/size mismatch');
      }
      file=await handle.getFile();
      if(file.size!==size)throw Error('Private media stored size mismatch');
      return {response:new scope.Response(file.stream(),{status:200,headers:{
        'Content-Type':response?.headers?.get('Content-Type')||'application/octet-stream',
        'Content-Length':String(size)}}),remove:()=>dir.removeEntry(filename)};
    }catch(error){
      // Commit only the bounded partial prefix on interruption. It is never
      // exposed as a playable file until full MD5/size validation succeeds.
      if(out){try{await out.close();}catch{try{await out.abort();}catch{}}}
      throw error;
    }finally{
      if(reader){try{void reader.cancel().catch(()=>{});}catch{}try{reader.releaseLock();}catch{}}
    }
  });
}
async function fill(cache,key,media,fetcher,signal,current,protectedKeys,owner,rangeFetcher){
  const size=Number(media.size),expected=String(media.md5Checksum).toLowerCase();
  if(!await reserve(cache,size,protectedKeys))return false;
  check(signal,current);
  const partial=await resumeRaw(owner,media,rangeFetcher,signal,current);
  const response=partial?.response||await fetcher();
  if(!response?.body?.pipeThrough||!response.ok)return false;
  let streamError=null,received=0;
  const hash=new scope.XStageImportCore.MD5();
  const verified=response.body.pipeThrough(new scope.TransformStream({
    transform(chunk,controller){
      try{
        check(signal,current);
        received+=chunk.byteLength;
        if(received>size)throw Error('Private media size mismatch');
        hash.append(chunk);
        controller.enqueue(chunk);
      }catch(error){streamError=error;throw error;}
    },
    flush(){
      try{
        check(signal,current);
        if(received!==size||hash.end()!==expected)throw Error('Private media MD5/size mismatch');
      }catch(error){streamError=error;throw error;}
    }
  }));
  const headers={'Content-Type':response.headers?.get?.('Content-Type')||'application/octet-stream',
    'Content-Length':String(size),'X-XStage-Verified-MD5':expected};
  try{
    await cache.put(key,new scope.Response(verified,{status:200,headers}));
    check(signal,current);
    if(partial)try{await partial.remove();}catch{}
    return true;
  }catch(error){
    if(streamError)throw streamError;
    check(signal,current);
    // Cache quota or a storage implementation failure: never mark a partial hit.
    return false;
  }
}
async function getOrFetch({owner,media,fetcher,rangeFetcher,signal,current=()=>true,pinned=[],cacheOnly=false}){
  check(signal,current);
  if(!owner||!available()||!cacheable(media))return cacheOnly?null:fetcher();
  let name,cache,key;
  try{
    name=await cacheName(owner);cache=await scope.caches.open(name);key=mediaKey(media);
    const hit=await cache.match(key);
    check(signal,current);
    if(hit&&hit.headers.get('X-XStage-Verified-MD5')===String(media.md5Checksum).toLowerCase()&&
      Number(hit.headers.get('Content-Length'))===Number(media.size))return hit;
    if(hit)await cache.delete(key);
  }catch(error){
    check(signal,current);
    return cacheOnly?null:fetcher();
  }
  const protect=new Set(pinned.filter(cacheable).map(mediaKey));protect.add(key);
  const workKey=name+':'+key;
  let job=pending.get(workKey);
  if(!job){
    job=fill(cache,key,media,fetcher,signal,current,protect,owner,rangeFetcher);
    pending.set(workKey,job);
  }
  try{
    const saved=await job;
    check(signal,current);
    if(saved){
      const hit=await cache.match(key);
      check(signal,current);
      if(hit)return hit;
    }
    return cacheOnly?null:fetcher();
  }catch(error){
    check(signal,current);
    if(error?.name==='AbortError')return cacheOnly?null:fetcher();
    throw error;
  }finally{
    if(pending.get(workKey)===job)pending.delete(workKey);
  }
}
scope.XStagePrivateMediaCache=Object.freeze({available,cacheable,getOrFetch});
})(window);
