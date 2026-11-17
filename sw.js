/* One-time decommission worker for the retired X-Stage Karaoke PWA.
 *
 * Historically /xstage/sw.js controlled the whole project site and cached
 * karaoke's old index.html. Removing that file altogether left an already
 * installed worker on some TVs because failed update checks cannot replace it.
 *
 * Serve a tiny replacement AT THE SAME URL. It does not intercept requests,
 * cache pages, register another worker, or touch Google Drive/private data.
 */
'use strict';

self.addEventListener('install',event=>{
  event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate',event=>{
  event.waitUntil((async()=>{
    try{
      const keys=await caches.keys();
      await Promise.all(keys
        .filter(name=>name.startsWith('xstage-shell-'))
        .map(name=>caches.delete(name)));
    }catch{/* Storage may be unavailable in restricted TV browsers. */}
    // Unregister the old root PWA. New pages are normal websites and
    // previously installed native Android Karaoke apps remain separate.
    await self.registration.unregister();
  })());
});
