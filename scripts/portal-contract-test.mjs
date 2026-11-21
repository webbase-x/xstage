import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const read=path=>fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const html=read('index.html');
const storefront=read('storefront.js');
const portal=read('portal.js');
const css=read('portal.css');
const storefrontCss=read('storefront.css');
const config=read('portal-config.js');
const device=read('storefront-device.js');
const migration=read('supabase/xstage_portal.sql');
const manifest=read('apps-portal/app/src/main/AndroidManifest.xml');
const native=read('apps-portal/app/src/main/java/com/webbasex/appsportal/MainActivity.java');
const workflow=read('.github/workflows/build-xstage-apps-portal.yml');
const feed=JSON.parse(read('downloads/apps-portal-latest.json'));
for(const [name,src] of Object.entries({storefront,portal,config,device})){
  assert.doesNotThrow(()=>new vm.Script(src,{filename:name+'.js'}),name+' is not valid JavaScript');
}
assert(html.includes('data-app="studio-pro"') && !html.includes('data-app="studio-pc"') &&
 !html.includes('data-app="studio-web"') && !html.includes('data-app="studio-plus"'),
 'only Song Studio Pro may be shown');
assert(storefront.includes('"studio-pro":{') &&
 !storefront.includes('"studio-pc":{') && !storefront.includes('"studio-web":{'),
 'retired Studio definitions must not remain');
assert(html.indexOf('data-app="apps-portal"')>0,'Portal Android card missing');
assert(html.indexOf('data-app="apps-portal"')<html.indexOf('data-app="karaoke-web"'),'Portal Android must be first card');
assert.match(html,/id="portal-login"/,'Google Login button missing');
assert.match(storefrontCss,/--xstage-status-safe-top:env\(safe-area-inset-top,0px\)/,'iPhone status-bar safe area must be reserved');
assert.match(storefrontCss,/\.site-header\{top:var\(--xstage-status-safe-top\);z-index:70\}/,'sticky header must remain below Dynamic Island while scrolling');
assert.match(storefrontCss,/\.site-header \.header-launch\{display:none\}/,'mobile header must not be overcrowded by duplicate Karaoke button');
assert.match(css,/\.portal-account #portal-user\{display:none\}/,'mobile Google profile must remain compact');
assert.match(html,/storefront\.css\?brand=(?:[9]|[1-9][0-9]+)/,'updated storefront CSS must bypass old browser cache');
assert.match(html,/portal\.css\?version=[4-9][0-9]*/,'updated profile CSS must bypass old browser cache');
assert.match(html,/id="portal-review-form"/,'review form missing');
assert.match(html,/id="portal-history-list"/,'user history missing');
assert.match(html,/portal-privacy\.html/,'privacy document missing');
assert.match(storefront,/portalNative/);
assert.match(storefront,/document\.querySelectorAll\('\.portal-self-card'\)/,'APK must hide its own download card');
assert.match(storefront,/id==="apps-portal"/,'signed portal feed handler missing');
assert.match(storefront,/channel==="signed"/,'only signed production feed is offered');
assert.match(portal,/signInWithOAuth/);
assert.match(portal,/exchangeCodeForSession/);
assert.match(portal,/xstage_download_events/);
assert.match(portal,/installation_confirmed/);
assert.match(portal,/xstage_reviews/);
assert.match(portal,/user_id:user\.id/,'writes must attribute their actual authenticated user');
assert.match(css,/#portal-review-form\[hidden\]/,'hidden rating form must stay hidden');
assert(!/['\"]sb_secret_[a-z0-9_-]{8,}/i.test(config),'public config must not include private keys');
const expectedTables=['xstage_profiles','xstage_admins','xstage_download_events','xstage_reviews'];
for(const name of expectedTables){
  assert(migration.includes('create table if not exists public.'+name),'missing '+name);
  assert(migration.includes('alter table public.'+name+' enable row level security'),'missing RLS '+name);
}
for(const match of migration.matchAll(/create table if not exists public\.([a-z_]+)/g)){
  assert(match[1].startsWith('xstage_'),'all tables must use xstage_ prefix');
}
assert.match(migration,/xstage_reviews_public_read/);
assert.match(migration,/xstage_events_self_or_admin_read/);
assert.match(manifest,/android:scheme="xstageapps" android:host="auth"/);
assert.match(native,/XStageAppsPortal\/1/);
assert.match(native,/xstageapps/);
assert.match(native,/\.supabase/,'OAuth must be handled through a trusted external browser');
assert.match(native,/setAllowFileAccess\(false\)/);
assert.match(workflow,/apksigner/,'signed APK verification must be in release job');
if(feed.available){
  assert.equal(feed.channel,'signed','Published Apps Portal APK must be in the signed channel');
  assert.match(feed.sha256||'',/^[a-fA-F0-9]{64}$/,'Published APK requires a verified SHA-256');
  assert.match(feed.signer_sha256||'',/^[a-fA-F0-9]{64}$/,'Published APK requires a verified signing certificate');
  assert.match(feed.download_url||'',/^https:\/\/webbase-x\.github\.io\/xstage\/downloads\//,
    'Published Apps Portal APK must have an app download URL');
}else assert.equal(feed.download_url??null,null,
  'Unpublished Apps Portal APK must not expose a stale download URL');
console.log('PASS: X-Stage portal UI, Google auth PKCE, RLS table prefix, Android identity, signed APK feed.');
