/* Preserve authenticated PC pairing links; otherwise open true browser-only Studio. */
(function () {
  const isPublic = location.hostname === 'webbase-x.github.io' &&
    location.pathname.replace(/\/+/g, '/').startsWith('/xstage/studio/');
  if (!isPublic) return;
  const query = new URLSearchParams(location.search);
  const paired = new URLSearchParams(location.hash.replace(/^#/, ''));
  if (query.get('mode') === 'pc') return;
  if (paired.get('auth') && paired.get('engine')) return;
  location.replace(new URL('./web.html', location.href).href);
})();