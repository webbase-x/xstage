/* X-Stage Karaoke Online service worker.
 * Code and navigation are network-first so deployed fixes are not trapped behind stale cache.
 * Private Google Drive media is cross-origin and is never cached here. */
const CACHE='xstage-shell-v1080';

self.addEventListener('install',event=>{
  event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate',event=>{
  event.waitUntil((async()=>{
    const keys=await caches.keys();
    await Promise.all(keys
      .filter(key=>key.startsWith('xstage-shell-'))
      .filter(key=>key!==CACHE)
      .map(key=>caches.delete(key)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch',event=>{
  if(event.request.method!=='GET')return;
  const url=new URL(event.request.url);
  if(url.origin!==self.location.origin)return;

  const isNavigation=event.request.mode==='navigate';
  const isCode=/\.(?:html|js|css|json|webmanifest)$/.test(url.pathname);
  if(isNavigation||isCode){
    event.respondWith((async()=>{
      try{
        const response=await fetch(event.request,{cache:'no-store'});
        if(response.ok){
          const cache=await caches.open(CACHE);
          await cache.put(event.request,response.clone());
        }
        return response;
      }catch{
        const cached=await caches.match(event.request);
        if(cached)return cached;
        if(isNavigation){
          const fallback=await caches.match('./index.html');
          if(fallback)return fallback;
        }
        return Response.error();
      }
    })());
    return;
  }

  if(/\/assets\//.test(url.pathname)){
    event.respondWith((async()=>{
      const cached=await caches.match(event.request);
      if(cached)return cached;
      const response=await fetch(event.request);
      if(response.ok){
        const cache=await caches.open(CACHE);
        await cache.put(event.request,response.clone());
      }
      return response;
    })());
  }
});
