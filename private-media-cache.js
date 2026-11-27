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
async function fill(cache,key,media,fetcher,signal,current,protectedKeys){
  const size=Number(media.size),expected=String(media.md5Checksum).toLowerCase();
  if(!await reserve(cache,size,protectedKeys))return false;
  check(signal,current);
  const response=await fetcher();
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
    return true;
  }catch(error){
    if(streamError)throw streamError;
    check(signal,current);
    // Cache quota or a storage implementation failure: never mark a partial hit.
    return false;
  }
}
async function getOrFetch({owner,media,fetcher,signal,current=()=>true,pinned=[],cacheOnly=false}){
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
    job=fill(cache,key,media,fetcher,signal,current,protect);
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
