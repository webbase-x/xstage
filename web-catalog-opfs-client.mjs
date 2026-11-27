/* Async catalog RPC. The verified raw SQLite remains in OPFS and the worker
 * imports it through bounded slices; no SQLite bytes or credentials are sent
 * as a full JavaScript buffer. Each caller owns one account/library session. */
export async function createWebCatalogClient(owner,{disk=globalThis.XStageWebCatalogDisk,workerFactory=()=>new Worker(new URL('./web-catalog-opfs-worker.mjs',import.meta.url),{type:'module'})}={}){
  if(!owner||!disk?.available())throw Error('Web catalog disk unavailable');
  const hash=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(owner));
  const ownerKey=Array.from(new Uint8Array(hash),x=>x.toString(16).padStart(2,'0')).join('');
  const worker=workerFactory(),pending=new Map();
  let closed=false,active=null;
  function dispose(error){
    if(closed)return;
    closed=true;active=null;worker.terminate();
    for(const p of pending.values()){clearTimeout(p.timer);p.reject(error);}
    pending.clear();
  }
  worker.onmessage=({data})=>{
    const p=pending.get(data?.id);if(!p)return;
    if(data.progress){p.arm();try{p.onProgress?.(data.progress);}catch{}return;}
    clearTimeout(p.timer);pending.delete(data.id);
    if(data.error)p.reject(Error(data.error));else p.resolve(data.result);
  };
  worker.onerror=event=>dispose(Error(event.message||'SQLite worker unavailable'));
  worker.onmessageerror=()=>dispose(Error('SQLite worker response invalid'));
  function rpc(action,args={},onProgress){
    if(closed)return Promise.reject(Error('SQLite worker closed'));
    const id=crypto.randomUUID();
    return new Promise((resolve,reject)=>{
      const p={resolve,reject,onProgress,arm(){clearTimeout(p.timer);p.timer=setTimeout(()=>dispose(Error('SQLite worker timed out')),120000);}};
      pending.set(id,p);p.arm();
      try{worker.postMessage({id,action,owner:ownerKey,...args});}
      catch(error){clearTimeout(p.timer);pending.delete(id);reject(error);}
    });
  }
  const assertCurrent=(current,signal)=>{if(!current()||signal?.aborted||closed)throw new DOMException('Catalog owner changed','AbortError');};
  async function stage({pointer,fetcher,current=()=>true,signal,onProgress}){
    assertCurrent(current,signal);
    const verified=await disk.getOrFetch({owner,pointer,fetcher,current,signal});
    assertCurrent(current,signal);
    if(!verified?.file)throw Error('Verified OPFS catalog unavailable');
    const onAbort=()=>dispose(new DOMException('Catalog owner changed','AbortError'));
    signal?.addEventListener('abort',onAbort,{once:true});
    try{
      const candidate=await rpc('stage',{file:verified.file,md5:pointer.contentMD5,size:pointer.contentBytes},onProgress);
      assertCurrent(current,signal);
      return candidate;
    }finally{signal?.removeEventListener('abort',onAbort);}
  }
  async function activate(candidate){
    if(!candidate?.capability)throw Error('No staged catalog');
    await rpc('activate',{capability:candidate.capability});
    active=candidate;
  }
  function query(action,args={}){
    if(!active)return Promise.reject(Error('No active catalog'));
    return rpc(action,{capability:active.capability,...args});
  }
  return Object.freeze({stage,activate,search:(term,cursor=null)=>query('search',{term,cursor}),lookup:(songId,code,title,artist)=>query('lookup',{songId,code,title,artist}),random:()=>query('random'),close:async()=>{try{if(!closed)await rpc('close');}finally{dispose(new DOMException('Catalog closed','AbortError'));}},abort:()=>dispose(new DOMException('Catalog closed','AbortError'))});
}
