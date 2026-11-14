/* X-Stage Karaoke Online – single-page private Drive player.
 * A short-lived Google access token may be cached in this browser until its Google expiry
 * so reopening the site does not force a repeat login. No password or refresh token is stored.
 * Catalog metadata can be cached locally per verified Google account; media remain private/transient. */
'use strict';
const cfg = window.XSTAGE_CONFIG || {};
const $ = id => document.getElementById(id);
const ui = {
  status: $('status'), login: $('login'), gateLogin: $('gate-login'), gateStatus:$('gate-auth-status'), logout: $('logout'), gate: $('gate'), catalogLoading:$('catalog-loading'), catalogLoadingTitle:$('catalog-loading-title'), catalogLoadingDetail:$('catalog-loading-detail'), catalogProgress:$('catalog-progress'), catalogProgressValue:$('catalog-progress-value'),
  account: $('account'), libraryState: $('library-state'), songTotal: $('song-total'), resultCount: $('result-count'), searchRefine:$('search-refine-hint'),
  librarySelect:$('library-select'),librarySwitcher:$('library-switcher'),
  search: $('search'), voiceSearch:$('voice-search'), songs: $('songs'), queue: $('queue'), queueCount: $('queue-count'), clearQueue: $('clear-queue'),
  player: $('player'), stage: $('stage'), stageIdle: $('stage-idle'), stageCode: $('stage-code'),
  nowPlaying: $('now-playing'), nowArtist: $('now-artist'), songKey:$('tv-song-key'), playStatus: $('play-status'),
  playPause: $('play-pause'), cancelCurrent:$('cancel-current'), restartCurrent:$('restart-current'), previous: $('previous'), next: $('next'),
  seek: $('seek'), elapsed: $('elapsed'), duration: $('duration'), speed: $('speed'), volume: $('volume'),
  repeat: $('repeat'), fullscreen: $('fullscreen'), lyrics: $('lyrics')
};
const state = {
  token: '', tokenExpiresAt:0, accountSub: '', manifest: null, songs: [], shown: [], selectedIndex: 0,
  queue: [], history: [], current: null, lyrics: null, objectUrl: '',
  requestId: 0, controller: null, authId: 0, loading: false,
  medley: false, medleyCache: null, medleyPrefetch: null,
  medleyUpcoming: null, medleyPoolSource: null, medleyPool: [], medleyRecent: [],
  userStopped: false, userPaused:false, resumeAfterInterruption:false, visualScale: 1,
  catalogPointerId:'',catalogGeneration:'',catalogPolling:false,catalogCache:new Map(),
  libraryRootId:'',libraryRootCanShare:false,libraryRootOwnedByMe:false,libraryRootOwnerEmail:'',availableLibraries:[],
  queuePreload:null,queuePrepared:null,queuePreloadTimer:null,queuePreloadVersion:0,
  playbackRestoreAttempted:false,
  awaitingSharedLibrary:false,
  updateAvailable:null,updateAfterTrack:false,nativeUpdateAvailable:null,nativeUpdateStatus:''
};

const XSTAGE_RELEASE=window.XSTAGE_RELEASE||{version:'0.0.0',build:0};
function appUpdateElements(){
  return {notice:$('app-update-notice'),text:$('app-update-text'),action:$('app-update-action')};
}
function playbackBusyForUpdate(){
  return !!(state.loading||state.current&&player.src&&!player.ended&&(!player.paused||state.queue.length||state.medley));
}
function renderAppUpdateNotice(){
  const {notice,text,action}=appUpdateElements();
  if(!notice||!text||!action)return;
  const remote=state.updateAvailable;
  if(!remote){notice.hidden=true;return;}
  state.updateAfterTrack=false;
  notice.hidden=false;
  text.textContent='มี X-Stage v'+remote.version+' · Build '+remote.build+' พร้อมอัปเดต';
  action.textContent='อัปเดตตอนนี้';
  action.disabled=false;
}
async function performAppUpdateReload(){
  try{savePlaybackResumeState();}catch{}
  try{
    const registrations=await navigator.serviceWorker?.getRegistrations?.();
    if(Array.isArray(registrations))await Promise.race([
      Promise.all(registrations.map(registration=>registration.update().catch(()=>{}))),
      new Promise(resolve=>setTimeout(resolve,4000))
    ]);
  }catch{}
  const next=new URL(location.href);
  next.searchParams.set('xstage_update',String(Date.now()));
  location.replace(next.href);
}
// Automatic web hotfixes run on entry, never mid-song. Guard repeated
// redirects if a CDN or Service Worker continues serving the older shell.
const WEB_AUTO_UPDATE_GUARD='xstage-web-auto-update-target-v1';
let webUpdateReloading=false;
function autoApplyWebUpdate(remote){
  if(androidTvNativeBridgeReady()||!remote||webUpdateReloading)return false;
  if(playbackBusyForUpdate())return false;
  const target=Number(remote.build);
  try{
    const previous=JSON.parse(sessionStorage.getItem(WEB_AUTO_UPDATE_GUARD)||'null');
    if(previous?.build===target&&Date.now()-Number(previous.at||0)<120000)return false;
    sessionStorage.setItem(WEB_AUTO_UPDATE_GUARD,JSON.stringify({build:target,at:Date.now()}));
  }catch{}
  webUpdateReloading=true;
  void performAppUpdateReload();
  return true;
}
async function checkAppVersion(){
  // Native APK updates must use the native channel, never a web-only reload.
  if(androidTvNativeBridgeReady())return null;
  try{
    const url=new URL('version.json',location.href);
    url.searchParams.set('_',String(Date.now()));
    const response=await fetch(url,{cache:'no-store'});
    if(!response.ok)throw new Error('HTTP '+response.status);
    const remote=await response.json();
    const remoteBuild=Number(remote?.build)||0;
    if(!Number.isSafeInteger(remoteBuild)||remoteBuild<1||typeof remote?.version!=='string')throw new Error('ข้อมูลเวอร์ชันไม่ถูกต้อง');
    const currentBuild=Number(XSTAGE_RELEASE.build)||0;
    if(remoteBuild>currentBuild){
      const changed=state.updateAvailable?.build!==remoteBuild||
        state.updateAvailable?.version!==String(remote.version||'');
      state.updateAvailable={version:String(remote.version||''),build:remoteBuild};
      renderAppUpdateNotice();
      if(changed)window.dispatchEvent(new CustomEvent('xstage:web-update',{detail:state.updateAvailable}));
      // Reload the old web app as soon as a newer published web release is
      // confirmed. During active playback, preserve the song and show the
      // existing Update Now button instead.
      autoApplyWebUpdate(state.updateAvailable);
      return true;
    }else{
      state.updateAvailable=null;
      state.updateAfterTrack=false;
      renderAppUpdateNotice();
      return false;
    }
  }catch{return null;/* Unknown status: never claim that an offline client is up to date. */}
}
async function triggerImmediateVersionUpdate(){
  if(androidTvNativeBridgeReady()){
    nativeUpdateManualCheck=true;
    const panel=androidTvUpdatePanel();
    panel.hidden=false;
    const active=playbackBusyForUpdate();
    panel.classList.toggle('during-playback',active);
    panel.setAttribute('aria-modal',String(!active));
    $('android-tv-update-title').textContent='ตรวจสอบอัปเดต X-Stage';
    $('android-tv-update-status').textContent='กำลังตรวจสอบเวอร์ชันล่าสุด…';
    const button=$('android-tv-update-now');
    if(button){button.disabled=false;button.textContent='อัปเดตตอนนี้';}
    try{window.XStageAndroid.checkForAppUpdate?.();}catch(error){window.XStageAndroidUpdateError(error?.message||'ตรวจสอบอัปเดตไม่สำเร็จ');}
    return;
  }
  const found=await checkAppVersion();
  if(found===true)await performAppUpdateReload();
  else if(found===false)setStatus('X-Stage เป็นเวอร์ชันล่าสุดแล้ว');
  else setStatus('ตรวจสอบเวอร์ชันไม่สำเร็จ กรุณาตรวจอินเทอร์เน็ตแล้วลองใหม่');
}
// Installed Android APKs load this hosted UI, including older builds. A live
// foreground poll also fixes missing mid-song update notices on those APKs.
// Keep the native APK channel separate from the Web version.json channel.
const XSTAGE_LIVE_UPDATE_CHECK_MS=15_000;
function checkLiveAppUpdate(){
  if(androidTvNativeBridgeReady()){
    try{window.XStageAndroid.checkForAppUpdate?.();}catch{}
    return;
  }
  void checkAppVersion();
}
function setupAppUpdateWatcher(){
  const {action}=appUpdateElements();
  action?.addEventListener('click',()=>{if(state.updateAvailable)void performAppUpdateReload();});
  $('desktop-update-version')?.addEventListener('click',()=>{void triggerImmediateVersionUpdate();});
  $('mobile-update-version')?.addEventListener('click',()=>{void triggerImmediateVersionUpdate();});
  // An older native APK might finish loading the WebView before its deferred
  // JS update callback exists. Recheck once after hosted scripts initialize.
  if(androidTvNativeBridgeReady()){
    setTimeout(()=>{try{window.XStageAndroid.checkForAppUpdate?.();}catch{}},350);
  }
  checkLiveAppUpdate();
  setInterval(checkLiveAppUpdate,XSTAGE_LIVE_UPDATE_CHECK_MS);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)checkLiveAppUpdate();});
  window.addEventListener('focus',checkLiveAppUpdate);
  window.addEventListener('online',checkLiveAppUpdate);
  window.addEventListener('pageshow',checkLiveAppUpdate);
}

function xstageTvVisible(element){
  if(!element||element.hidden||element.getAttribute?.('aria-hidden')==='true')return false;
  const style=getComputedStyle(element);
  if(style.display==='none'||style.visibility==='hidden'||Number(style.opacity)===0)return false;
  const rect=element.getBoundingClientRect();
  return rect.width>0&&rect.height>0;
}
function xstageTvActiveScope(){
  const nativeTv=document.body.classList.contains('xstage-native-tv');
  const selectors=[
    '.android-tv-update-panel:not([hidden])',
    '.android-tv-auth-panel:not([hidden])',
    '.xstage-tv-quick-menu:not([hidden])',
    ...(nativeTv?[]:['.remote-pair-panel:not([hidden])']),
    '.remote-request-panel:not([hidden])',
    'dialog[open]',
    '.mobile-stage-menu:not([hidden])',
    '.login-gate:not([hidden])'
  ];
  const visible=selectors.flatMap(selector=>[...document.querySelectorAll(selector)]).filter(xstageTvVisible);
  if(!visible.length)return document;
  return visible.sort((a,b)=>{
    const za=Number.parseInt(getComputedStyle(a).zIndex,10)||0;
    const zb=Number.parseInt(getComputedStyle(b).zIndex,10)||0;
    return za-zb;
  }).at(-1);
}
function xstageTvFocusable(scope=xstageTvActiveScope()){
  if(document.body.classList.contains('xstage-native-tv')&&scope===document)return [];
  const selector='button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
  return [...scope.querySelectorAll(selector)].filter(xstageTvVisible);
}
// Minimal TV-only control surface. The stage stays clean; physical MENU/Back
// gives D-pad users a way to reach pairing, playback and updates.
function xstageTvQuickMenu(){
  let panel=document.getElementById('xstage-tv-quick-menu');
  if(panel)return panel;
  panel=document.createElement('section');
  panel.id='xstage-tv-quick-menu';
  panel.className='xstage-tv-quick-menu';
  panel.hidden=true;
  panel.setAttribute('role','dialog');
  panel.setAttribute('aria-modal','true');
  panel.setAttribute('aria-label','เมนูรีโมททีวี X-Stage');
  panel.innerHTML='<div class="xstage-tv-quick-box">'+
    '<strong>X-STAGE · รีโมททีวี</strong>'+
    '<p>ใช้ปุ่มลูกศรเลือกคำสั่ง กด OK เพื่อยืนยัน</p>'+
    '<div class="xstage-tv-quick-actions">'+
    '<button type="button" id="xstage-tv-quick-login">เข้าสู่ระบบ Google Drive</button>'+ 
    '<button type="button" id="xstage-tv-quick-qr">แสดง QR รีโมทมือถือ</button>'+
    '<button type="button" id="xstage-tv-quick-new-qr">สร้าง QR ใหม่</button>'+
    '<button type="button" id="xstage-tv-quick-play">เล่น / พักเพลง</button>'+
    '<button type="button" id="xstage-tv-quick-update">ตรวจสอบอัปเดต</button>'+
    '<button type="button" id="xstage-tv-quick-close">กลับสู่เวที</button>'+
    '</div></div>';
  document.body.append(panel);
  panel.querySelector('#xstage-tv-quick-login').addEventListener('click',()=>{
    panel.hidden=true;
    if(!state.token)startAndroidTvDeviceLogin(false);
  });
  panel.querySelector('#xstage-tv-quick-qr').addEventListener('click',()=>{
    window.XStageRemoteQr?.show(true);
    panel.hidden=true;
  });
  panel.querySelector('#xstage-tv-quick-new-qr').addEventListener('click',()=>{
    panel.hidden=true;
    window.XStageRemoteQr?.retry?.();
  });
  panel.querySelector('#xstage-tv-quick-play').addEventListener('click',()=>{
    document.getElementById('play-pause')?.click();
    panel.hidden=true;
  });
  panel.querySelector('#xstage-tv-quick-update').addEventListener('click',()=>{
    panel.hidden=true;
    void triggerImmediateVersionUpdate();
  });
  panel.querySelector('#xstage-tv-quick-close').addEventListener('click',()=>{panel.hidden=true;});
  return panel;
}
window.XStageTvOpenMenu=()=>{
  if(!document.body.classList.contains('xstage-native-tv'))return false;
  if(['android-tv-auth-panel','android-tv-update-panel'].some(id=>{
    const element=document.getElementById(id);
    return element&&!element.hidden&&
      !(id==='android-tv-update-panel'&&element.classList.contains('during-playback'));
  }))return false;
  const panel=xstageTvQuickMenu();
  panel.hidden=!panel.hidden;
  if(!panel.hidden)panel.querySelector('button')?.focus?.({preventScroll:true});
  return true;
};
window.XStageTvHandleBack=()=>{
  const menu=document.getElementById('xstage-tv-quick-menu');
  if(menu&&!menu.hidden){menu.hidden=true;return true;}
  const update=document.getElementById('android-tv-update-panel');
  if(update&&!update.hidden){document.getElementById('android-tv-update-later')?.click();return true;}
  const auth=document.getElementById('android-tv-auth-panel');
  if(auth&&!auth.hidden){document.getElementById('android-tv-auth-cancel')?.click();return true;}
  return false;
};
window.XStageTvMoveFocus=direction=>{
  const scope=xstageTvActiveScope();
  const items=xstageTvFocusable(scope);
  if(!items.length)return false;
  const active=document.activeElement;
  if((active?.matches?.('input,textarea')||false)&&(direction==='left'||direction==='right')&&scope===document){
    const key=direction==='left'?'ArrowLeft':'ArrowRight';
    active.dispatchEvent(new KeyboardEvent('keydown',{key,code:key,bubbles:true,cancelable:true}));
    return true;
  }
  if(!items.includes(active)){
    const preferred=scope.classList?.contains('during-playback')
      ?scope.querySelector?.('#android-tv-update-later:not([disabled])')
      :scope.querySelector?.('#android-tv-update-now:not([disabled]),#android-tv-auth-retry:not([disabled]),button:not([disabled])');
    const target=preferred&&items.includes(preferred)?preferred:items[0];
    try{target.focus({preventScroll:true});}catch{target.focus();}
    target.scrollIntoView?.({block:'nearest',inline:'nearest'});
    return true;
  }
  const ar=active.getBoundingClientRect(),ax=ar.left+ar.width/2,ay=ar.top+ar.height/2;
  let best=null,bestScore=Infinity;
  for(const item of items){
    if(item===active)continue;
    const r=item.getBoundingClientRect(),cx=r.left+r.width/2,cy=r.top+r.height/2;
    const dx=cx-ax,dy=cy-ay;
    const valid=direction==='left'?dx<-2:direction==='right'?dx>2:direction==='up'?dy<-2:dy>2;
    if(!valid)continue;
    const primary=Math.abs(direction==='left'||direction==='right'?dx:dy);
    const secondary=Math.abs(direction==='left'||direction==='right'?dy:dx);
    const score=primary+secondary*2.75;
    if(score<bestScore){bestScore=score;best=item;}
  }
  if(!best){
    const index=items.indexOf(active);
    const delta=(direction==='left'||direction==='up')?-1:1;
    best=items[(index+delta+items.length)%items.length];
  }
  try{best.focus({preventScroll:true});}catch{best.focus();}
  best.scrollIntoView?.({block:'nearest',inline:'nearest'});
  return true;
};
window.XStageTvActivateFocused=()=>{
  const scope=xstageTvActiveScope();
  const items=xstageTvFocusable(scope);
  // In display-only mode, all stage controls are intentionally hidden. Never
  // query a hidden DOM button as a fallback: OK must reveal the actual menu.
  if(document.body.classList.contains('xstage-native-tv')&&scope===document)
    return window.XStageTvOpenMenu?.()||false;
  let active=document.activeElement;
  if(!items.includes(active)){
    active=(scope.classList?.contains('during-playback')
      ?scope.querySelector?.('#android-tv-update-later:not([disabled])')
      :scope.querySelector?.('#android-tv-update-now:not([disabled]),button:not([disabled]),a[href]'))||items[0];
    if(!active)return false;
    try{active.focus({preventScroll:true});}catch{active.focus();}
  }
  if(active.matches?.('input:not([type]),input[type="text"],input[type="search"],textarea')){
    active.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',code:'Enter',bubbles:true,cancelable:true}));
    return true;
  }
  active.click?.();
  return true;
};
document.addEventListener('keydown',event=>{
  if(!event.isTrusted)return;
  const nativeTv=androidTvNativeBridgeReady()||/Android TV|XStageAndroidTV/i.test(navigator.userAgent||'');
  if(!nativeTv)return;
  const map={ArrowLeft:'left',ArrowRight:'right',ArrowUp:'up',ArrowDown:'down'};
  if(map[event.key]){
    event.preventDefault();event.stopPropagation();
    window.XStageTvMoveFocus(map[event.key]);
  }else if(event.key==='Enter'||event.key==='Accept'){
    event.preventDefault();event.stopPropagation();
    window.XStageTvActivateFocused();
  }
},true);

const CATALOG_DB_NAME='xstage-private-catalog-v1';
const CATALOG_DB_STORE='catalogs';
function openCatalogDatabase(){
  return new Promise((resolve,reject)=>{
    if(!('indexedDB' in window)){reject(Error('IndexedDB unavailable'));return;}
    const request=indexedDB.open(CATALOG_DB_NAME,1);
    request.onupgradeneeded=()=>{if(!request.result.objectStoreNames.contains(CATALOG_DB_STORE))request.result.createObjectStore(CATALOG_DB_STORE);};
    request.onsuccess=()=>resolve(request.result);
    request.onerror=()=>reject(request.error||Error('IndexedDB unavailable'));
  });
}
async function catalogStorage(action,key,value){
  const db=await openCatalogDatabase();
  try{return await new Promise((resolve,reject)=>{
    const tx=db.transaction(CATALOG_DB_STORE,action==='get'?'readonly':'readwrite');
    const store=tx.objectStore(CATALOG_DB_STORE);
    const request=action==='get'?store.get(key):action==='delete'?store.delete(key):store.put(value,key);
    request.onsuccess=()=>resolve(request.result);
    request.onerror=()=>reject(request.error);
    tx.onerror=()=>reject(tx.error);
  });}finally{db.close();}
}
const LIBRARY_PREF_KEY='xstage-library-choice-v1';
function libraryCacheOwner(sub,rootId=''){
  return rootId?sub+':root:'+rootId:sub;
}
function readPreferredLibraryRoot(sub){
  if(!sub)return '';
  try{
    const map=JSON.parse(localStorage.getItem(LIBRARY_PREF_KEY)||'{}');
    return String(map?.[sub]||'');
  }catch{return '';}
}
function savePreferredLibraryRoot(sub,rootId){
  if(!sub||!rootId)return;
  try{
    const map=JSON.parse(localStorage.getItem(LIBRARY_PREF_KEY)||'{}');
    map[sub]=String(rootId);
    localStorage.setItem(LIBRARY_PREF_KEY,JSON.stringify(map));
  }catch{}
}
function libraryLabel(root){
  if(root?.ownedByMe)return 'คลังของฉัน';
  const owner=String(root?.owners?.[0]?.emailAddress||'').trim();
  return owner?'แชร์โดย '+owner:'คลังที่แชร์ให้ฉัน';
}
function renderLibrarySelector(roots,activeId){
  state.availableLibraries=Array.isArray(roots)?roots.slice():[];
  if(!ui.librarySelect||!ui.librarySwitcher)return;
  ui.librarySelect.replaceChildren();
  for(const root of state.availableLibraries){
    const option=document.createElement('option');
    option.value=String(root.id||'');
    option.textContent=libraryLabel(root);
    ui.librarySelect.append(option);
  }
  if(activeId)ui.librarySelect.value=String(activeId);
  ui.librarySwitcher.hidden=state.availableLibraries.length<2;
}
async function loadLatestCachedCatalog(sub,rootId=''){
  if(!sub)return null;
  try{
    const saved=await catalogStorage('get',libraryCacheOwner(sub,rootId));
    const catalog=saved?.catalog;
    if(catalog?.schemaVersion!==1||!Array.isArray(catalog.songs))return null;
    return {
      catalog,
      generation:String(saved.generation||''),
      catalogFileId:String(saved.catalogFileId||''),
      deltaFileIds:Array.isArray(saved.deltaFileIds)?saved.deltaFileIds:[]
    };
  }catch{return null;}
}
async function loadCatalogPiece(sub,id){
  if(!sub||!id)return null;
  try{
    const saved=await catalogStorage('get','piece:'+sub+':'+id);
    return saved?.data&&typeof saved.data==='object'?saved.data:null;
  }catch{return null;}
}
async function saveCatalogPiece(sub,id,data){
  if(!sub||!id||!data||typeof data!=='object')return;
  try{await catalogStorage('put','piece:'+sub+':'+id,{data,savedAt:Date.now()});}
  catch(error){console.warn('X-Stage catalog piece cache:',error?.message||error);}
}
async function loadCachedCatalog(ownerKey,pointer){
  if(!ownerKey||!pointer?.generation)return null;
  try{
    const saved=await catalogStorage('get',ownerKey);
    if(saved?.generation!==String(pointer.generation)||saved.catalogFileId!==pointer.catalogFileId||
       JSON.stringify(saved.deltaFileIds||[])!==JSON.stringify(pointer.deltaFileIds||[]))return null;
    const catalog=saved.catalog;
    if(catalog?.schemaVersion!==1||!Array.isArray(catalog.songs))return null;
    if(Number.isSafeInteger(pointer.songCount)&&catalog.songs.length!==pointer.songCount)return null;
    return catalog;
  }catch{return null;}
}
async function saveCachedCatalog(ownerKey,pointer,catalog){
  if(!ownerKey||!pointer?.generation||!Array.isArray(catalog?.songs))return;
  try{await catalogStorage('put',ownerKey,{
    generation:String(pointer.generation),catalogFileId:pointer.catalogFileId,
    deltaFileIds:pointer.deltaFileIds||[],catalog
  });}catch(error){console.warn('X-Stage local catalog cache:',error?.message||error);}
}
async function clearCatalogStorage(){
  try{
    const db=await openCatalogDatabase();
    db.close();
    await new Promise((resolve,reject)=>{
      const req=indexedDB.deleteDatabase(CATALOG_DB_NAME);
      req.onsuccess=()=>resolve();req.onerror=()=>reject(req.error);
      req.onblocked=()=>reject(Error('กรุณาปิดแท็บ X-Stage อื่นก่อน'));
    });
  }catch(error){throw Error('ล้างฐานเพลงแคชไม่ได้: '+(error?.message||error));}
}
const UI_PREFS_KEY='xstage-ui-settings-v1';
function readUiPrefs(){
  try{
    const value=JSON.parse(localStorage.getItem(UI_PREFS_KEY)||'{}');
    return value&&typeof value==='object'?value:{};
  }catch{return {};}
}
function saveUiPrefs(patch){
  try{
    const next={...readUiPrefs(),...patch};
    localStorage.setItem(UI_PREFS_KEY,JSON.stringify(next));
    return next;
  }catch{return readUiPrefs();}
}
window.XStageUiPrefs={read:readUiPrefs,save:saveUiPrefs};
const initialUiPrefs=readUiPrefs();
const REMEMBERED_LOGIN_KEY = 'xstage-remembered-google-login';
const ACTIVE_AUTH_KEY = 'xstage-google-token-v2';
const PENDING_AUTH_KEY = 'xstage-google-pending-token-v1';
const LEGACY_ACTIVE_AUTH_KEY = 'xstage-tab-google-token-v1';
const AUTH_EXPIRY_MARGIN_MS = 90_000;
function authRecordValid(current){
  return !!(current&&typeof current.token==='string'&&current.token.length>25&&
    typeof current.sub==='string'&&current.sub.length>0&&
    Number.isFinite(current.expiresAt)&&current.expiresAt>Date.now()+AUTH_EXPIRY_MARGIN_MS);
}
function clearActiveAuth(){
  try{sessionStorage.removeItem(ACTIVE_AUTH_KEY);sessionStorage.removeItem(LEGACY_ACTIVE_AUTH_KEY);}catch{}
  try{localStorage.removeItem(ACTIVE_AUTH_KEY);}catch{}
}
function clearPendingAuth(){
  try{sessionStorage.removeItem(PENDING_AUTH_KEY);}catch{}
  try{localStorage.removeItem(PENDING_AUTH_KEY);}catch{}
}
function savePendingAuth(token,expiresAt){
  if(!token||!(expiresAt>Date.now()+AUTH_EXPIRY_MARGIN_MS))return;
  const value=JSON.stringify({token,expiresAt});
  try{sessionStorage.setItem(PENDING_AUTH_KEY,value);}catch{}
  try{localStorage.setItem(PENDING_AUTH_KEY,value);}catch{}
}
function readPendingAuth(){
  for(const store of [(()=>{try{return sessionStorage}catch{return null}})(),(()=>{try{return localStorage}catch{return null}})()].filter(Boolean)){
    try{
      const current=JSON.parse(store.getItem(PENDING_AUTH_KEY)||'null');
      if(current&&typeof current.token==='string'&&current.token.length>25&&Number.isFinite(current.expiresAt)&&current.expiresAt>Date.now()+AUTH_EXPIRY_MARGIN_MS)return current;
    }catch{}
  }
  clearPendingAuth();return null;
}
function saveActiveAuth(token,expiresAt,sub){
  if(!authRecordValid({token,expiresAt,sub}))return;
  const value=JSON.stringify({token,expiresAt,sub});
  try{sessionStorage.setItem(ACTIVE_AUTH_KEY,value);}catch{}
  // This is still only Google's short-lived access token; never a password/refresh token.
  try{localStorage.setItem(ACTIVE_AUTH_KEY,value);}catch{}
}
function readActiveAuth(){
  const stores=[];
  try{stores.push(sessionStorage);}catch{}
  try{stores.push(localStorage);}catch{}
  for(const store of stores){
    try{
      const current=JSON.parse(store.getItem(ACTIVE_AUTH_KEY)||store.getItem(LEGACY_ACTIVE_AUTH_KEY)||'null');
      if(authRecordValid(current))return current;
    }catch{}
  }
  clearActiveAuth();return null;
}
function hasRememberedLogin(){try{return localStorage.getItem(REMEMBERED_LOGIN_KEY)==='1';}catch{return false;}}
function rememberLogin(enabled){try{if(enabled)localStorage.setItem(REMEMBERED_LOGIN_KEY,'1');else localStorage.removeItem(REMEMBERED_LOGIN_KEY);}catch{/* Optional preference only. */}}
const player = ui.player;
const karaokeVideo = document.getElementById('karaoke-video');
let videoObjectUrl = '';
function resetSongVideo(){
  if(!karaokeVideo)return;
  karaokeVideo.pause();
  karaokeVideo.hidden=true;
  karaokeVideo.removeAttribute('src');
  karaokeVideo.load();
  if(videoObjectUrl){URL.revokeObjectURL(videoObjectUrl);videoObjectUrl='';}
}
function syncSongVideo(){
  if(!karaokeVideo||karaokeVideo.hidden||!karaokeVideo.src)return;
  karaokeVideo.playbackRate=player.playbackRate;
  if(Number.isFinite(player.currentTime)&&
      Math.abs((karaokeVideo.currentTime||0)-player.currentTime)>.45){
    try{karaokeVideo.currentTime=player.currentTime;}catch{}
  }
  if(player.paused||player.ended){karaokeVideo.pause();}
  else karaokeVideo.play().catch(()=>{
    // Unsupported video or autoplay policy should never stop the audio.
    // HTML5 audio+timed lyrics remain the playable fallback.
  });
}
async function loadSongVideo(song,request,token){
  if(!karaokeVideo||!getFileId(song?.video))return;
  try{
    const response=await privateFile(song.video.fileId,token);
    const data=await response.blob();
    if(request!==state.requestId||token!==state.token||state.current!==song)return;
    if(data.size<1024)throw Error('วิดีโอว่างเปล่า');
    videoObjectUrl=URL.createObjectURL(data.type==='video/mp4' ? data :
      new Blob([data],{type:'video/mp4'}));
    karaokeVideo.src=videoObjectUrl;
    karaokeVideo.muted=true;
    karaokeVideo.hidden=false;
    karaokeVideo.load();
    syncSongVideo();
  }catch(error){
    if(request!==state.requestId)return;
    resetSongVideo();
    console.warn('Video unavailable; using verified audio + timed lyrics:',error.message);
  }
}
if(karaokeVideo){
  karaokeVideo.addEventListener('loadedmetadata',syncSongVideo);
  karaokeVideo.addEventListener('canplay',syncSongVideo);
  karaokeVideo.addEventListener('error',()=>{
    console.warn('Unsupported MP4 video: continue karaoke using audio and lyrics');
    resetSongVideo();
  });
}

const initialVolume=Math.max(0,Math.min(100,Number(initialUiPrefs.volume)));
if(Number.isFinite(initialVolume)){
  ui.volume.value=String(initialVolume);
  player.volume=initialVolume/100;
}else player.volume=0.8;
if([.75,.9,1,1.1,1.25,1.5].includes(Number(initialUiPrefs.speed)))ui.speed.value=String(initialUiPrefs.speed);
if(typeof initialUiPrefs.repeat==='boolean')ui.repeat.checked=initialUiPrefs.repeat;
if(typeof initialUiPrefs.muted==='boolean')player.muted=initialUiPrefs.muted;
if(Number.isFinite(Number(initialUiPrefs.visualScale)))setTimeout(()=>setStageVisualScale(Number(initialUiPrefs.visualScale)),0);

function cleanStatusMessage(message,kind=''){
  const raw=String(message??'').trim();
  const punctuationOnly=!raw||/^[\s.,;:!?'"“”‘’·…\-–—_/\\]+$/u.test(raw);
  return punctuationOnly
    ? (kind==='error'?'เกิดข้อผิดพลาดในการเชื่อมต่อ กรุณาลองใหม่อีกครั้ง':'พร้อมใช้งาน')
    : raw;
}
function setStatus(message, kind = '') {
  const safeMessage=cleanStatusMessage(message,kind);
  ui.status.textContent = safeMessage;
  ui.status.className = 'status-line' + (kind ? ' ' + kind : '');
  if(ui.gateStatus){
    ui.gateStatus.textContent=safeMessage;
    ui.gateStatus.dataset.kind=kind||'info';
  }
}
function setSearchAvailability(ready,{busy=false}={}){
  if(!ui.search)return;
  ui.search.disabled=!!busy;
  ui.search.readOnly=false;
  ui.search.setAttribute('aria-disabled',String(!!busy));
  ui.search.dataset.libraryReady=String(!!ready);
  ui.search.placeholder='ค้นหาเพลง ชื่อศิลปิน หรือรหัสเพลง';
}
function syncLoginGateState(){
  const active=!!(ui.gate&&!ui.gate.hidden);
  document.body.classList.toggle('xstage-gate-active',active);
  if(ui.gate){
    ui.gate.setAttribute('aria-hidden',String(!active));
    if(active)ui.gate.removeAttribute('inert');
    else ui.gate.setAttribute('inert','');
  }
}
function dismissLoginGate(){
  // Cancellation must allow the TV viewer to close the welcome gate; the
  // private song library still remains locked until Google authenticates.
  if(androidTvNativeBridgeReady()&&!state.token&&!androidTvLoginCancelled)return;
  if(!ui.gate||ui.gate.hidden)return;
  ui.gate.hidden=true;
  syncLoginGateState();
  setStatus('โหมดชมหน้าเวที · พิมพ์คำค้นได้ทันที และเชื่อมต่อ Google Drive เมื่อต้องการเปิดผลเพลง');
  setTimeout(()=>ui.search?.focus?.(),0);
}
function showCatalogLoading(title,detail,progress=null){
  if(ui.catalogLoadingTitle)ui.catalogLoadingTitle.textContent=title||'กำลังเตรียมฐานเพลง';
  if(ui.catalogLoadingDetail)ui.catalogLoadingDetail.textContent=detail||'โปรดรอสักครู่…';
  if(Number.isFinite(Number(progress))){
    const value=Math.max(0,Math.min(100,Math.round(Number(progress))));
    if(ui.catalogProgress)ui.catalogProgress.value=value;
    if(ui.catalogProgressValue)ui.catalogProgressValue.textContent=value+'%';
  }
  if(ui.catalogLoading)ui.catalogLoading.hidden=false;
}
function hideCatalogLoading(){
  if(ui.catalogLoading)ui.catalogLoading.hidden=true;
  if(ui.catalogProgress)ui.catalogProgress.value=0;
  if(ui.catalogProgressValue)ui.catalogProgressValue.textContent='0%';
}

function publishPlaybackStatus(state,song,message=''){
  window.dispatchEvent(new CustomEvent('xstage:playback-status',{
    detail:{state,title:String(song?.title||song?.code||''),message:String(message||'')}
  }));
}
async function boundedPlaybackTask(task,seconds,message){
  let timer;
  try{
    return await Promise.race([task,new Promise((_,reject)=>{
      timer=setTimeout(()=>reject(Error(message)),seconds*1000);
    })]);
  }finally{clearTimeout(timer);}
}
function setPlayStatus(message) {
  // Track title and playback state already appear in the bottom transport.
  // Keep only loading, errors and actionable notices in the status area.
  ui.playStatus.textContent=/^กำลังเล่น\s*·/.test(String(message||''))?'':message;
}
async function clearPerformanceCache(){
  // Never clear localStorage, sessionStorage or Google credentials.
  releaseQueuePreload();
  state.catalogCache.clear();
  state.medleyCache=null;state.medleyPrefetch=null;state.medleyUpcoming=null;
  await clearCatalogStorage();
  if('caches' in window){
    try{
      const keys=await caches.keys();
      await Promise.all(keys.filter(key=>/xstage/i.test(key)).map(key=>caches.delete(key)));
    }catch(error){console.warn('Static cache cleanup:',error);}
  }
  setStatus('ล้างแคชฐานเพลงและไฟล์เว็บแล้ว · ยังลงชื่อเข้าใช้ Google อยู่', 'success');
  return true;
}
window.XStageClearCache=clearPerformanceCache;
function num(n) { return Number(n).toLocaleString('th-TH'); }
function timeLabel(t) {
  if (!Number.isFinite(t) || t < 0) return '00:00';
  const seconds = Math.floor(t); const h = Math.floor(seconds / 3600);
  const m = String(Math.floor(seconds / 60) % 60).padStart(2, '0');
  const s = String(seconds % 60).padStart(2, '0');
  return h ? `${h}:${m}:${s}` : `${m}:${s}`;
}
function getFileId(data) {
  return typeof data?.fileId === 'string' && data.fileId.length > 0 ? data.fileId : '';
}
function playable(song) { return !!(getFileId(song?.audio) && getFileId(song?.lyrics)); }
function requestHeaders(token) { return { Authorization: `Bearer ${token}` }; }
const GOOGLE_FETCH_TIMEOUT_MS=18_000;
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function googleFetch(url,options={},label='Google',retries=1){
  const external=options.signal;
  for(let attempt=0;;attempt++){
    const controller=new AbortController();
    const abortExternal=()=>controller.abort();
    if(external?.aborted)throw new DOMException('Aborted','AbortError');
    external?.addEventListener?.('abort',abortExternal,{once:true});
    const timer=setTimeout(()=>controller.abort(),GOOGLE_FETCH_TIMEOUT_MS);
    try{
      const response=await fetch(url,{...options,signal:controller.signal});
      if((response.status===429||response.status>=500)&&attempt<retries){
        await delay(450*(attempt+1));continue;
      }
      return response;
    }catch(error){
      if(external?.aborted)throw new DOMException('Aborted','AbortError');
      if(attempt<retries&&(error?.name==='AbortError'||error instanceof TypeError)){
        await delay(450*(attempt+1));continue;
      }
      if(error?.name==='AbortError')throw Error(label+' ใช้เวลานานเกินไป กรุณาตรวจอินเทอร์เน็ตแล้วลองใหม่');
      throw Error(label+' เชื่อมต่อไม่สำเร็จ กรุณาตรวจอินเทอร์เน็ตแล้วลองใหม่');
    }finally{
      clearTimeout(timer);external?.removeEventListener?.('abort',abortExternal);
    }
  }
}
function driveError(status, subject) {
  if (status === 401) return new Error('สิทธิ์ Google หมดอายุ กรุณาเข้าสู่ระบบอีกครั้ง');
  if (status === 403) return new Error('บัญชีนี้ไม่มีสิทธิ์เข้าถึง ' + subject + ' (ตรวจสิทธิ์ drive.file และบัญชีที่ซิงก์)');
  if (status === 404) return new Error('ไม่พบ ' + subject + ' ใน Google Drive ของบัญชีนี้');
  return new Error(`อ่าน ${subject} ไม่สำเร็จ (HTTP ${status})`);
}
async function driveList(q, token) {
  const params = new URLSearchParams({q,fields:'nextPageToken,files(id,name,mimeType,parents,ownedByMe,sharedWithMeTime,capabilities(canShare),owners(displayName,emailAddress))',pageSize:'1000'});
  const result = await googleFetch(`https://www.googleapis.com/drive/v3/files?${params}`, {headers: requestHeaders(token),cache:'no-store'},'Google Drive');
  if (!result.ok) throw driveError(result.status, 'รายการไฟล์');
  const json = await result.json();
  return Array.isArray(json.files) ? json.files : [];
}
async function privateFile(id, token, opts = {}) {
  const r = await googleFetch(`https://www.googleapis.com/drive/v3/files/${encodeURIComponent(id)}?alt=media`, {
    headers: requestHeaders(token), cache:'no-store',signal:opts.signal
  },'Google Drive');
  if (!r.ok) throw driveError(r.status, 'ไฟล์เพลงส่วนตัว');
  return r;
}
async function privateJson(id, token, opts) {
  const response = await privateFile(id, token, opts);
  try { return await response.json(); }
  catch { throw Error('ไฟล์ JSON บน Drive ไม่ถูกต้อง'); }
}

function sharedLibraryFeatureReady(){
  return !!(String(cfg.googlePickerApiKey||'').trim()&&String(cfg.googleAppId||'').trim());
}
window.XStageSharedLibraryReady=sharedLibraryFeatureReady;
function setSharedLibraryGate(active,message=''){
  const button=$('gate-shared-library');
  const copy=$('gate-copy');
  const footnote=$('gate-footnote');
  state.awaitingSharedLibrary=!!active;
  if(active){
    ui.gate.hidden=false;
    ui.gateLogin.hidden=true;
    const ready=sharedLibraryFeatureReady();
    if(button){
      button.hidden=false;
      button.disabled=!ready;
      button.textContent=ready?'ใช้คลังเพลงจากผู้แชร์':'คลังที่แชร์ · ต้องตั้งค่า Google Picker';
    }
    if(copy)copy.textContent=ready
      ? 'บัญชีนี้ได้รับเชิญให้ใช้คลังเพลงของผู้แชร์ กรุณาอนุญาต X-Stage ให้เปิดโฟลเดอร์นั้นหนึ่งครั้ง'
      : 'บัญชีนี้ล็อกอินสำเร็จ แต่ระบบใช้คลังเพลงที่แชร์ยังไม่เปิดใช้งานบนเว็บไซต์นี้';
    if(footnote)footnote.textContent=ready
      ? 'เล่นจาก Google Drive ของผู้แชร์โดยตรง · ไม่คัดลอกไฟล์ ไม่บันทึกเพลงลง Drive ของผู้รับ'
      : 'เจ้าของเว็บไซต์ต้องตั้งค่า Google Picker API ก่อน · ไม่มีการคัดลอกเพลงลง Drive ของผู้รับ';
    if(message)ui.gateStatus.textContent=message;
    else if(!ready)ui.gateStatus.textContent='ฟังก์ชันคลังที่แชร์ยังไม่พร้อมใช้งาน';
  }else{
    if(button){button.hidden=true;button.disabled=false;button.textContent='ใช้คลังเพลงจากผู้แชร์';}
    ui.gateLogin.hidden=false;
    if(copy)copy.textContent='เข้าสู่ระบบด้วย Google เพื่อค้นหา จัดคิว และเล่นเพลงที่คุณซิงก์ไว้ใน Drive ของบัญชีนี้';
    if(footnote)footnote.textContent='ไฟล์เพลงอยู่ใน Google Drive ส่วนตัวของคุณเท่านั้น';
  }
}
let googlePickerScriptPromise=null;
function loadScriptOnce(src,id){
  const existing=id?document.getElementById(id):null;
  if(existing&&existing.dataset.loaded==='1')return Promise.resolve(existing);
  return new Promise((resolve,reject)=>{
    const script=existing||document.createElement('script');
    if(!existing){
      script.src=src;script.async=true;if(id)script.id=id;document.head.append(script);
    }
    const done=()=>{script.dataset.loaded='1';resolve(script);};
    script.addEventListener('load',done,{once:true});
    script.addEventListener('error',()=>reject(Error('โหลดบริการ Google ไม่สำเร็จ')),{once:true});
  });
}
async function loadGooglePickerApi(){
  if(window.google?.picker)return;
  if(typeof window.gapi==='undefined'){
    googlePickerScriptPromise ||= loadScriptOnce('https://apis.google.com/js/api.js','xstage-google-api');
    await googlePickerScriptPromise;
  }
  await new Promise((resolve,reject)=>{
    let done=false;
    const timer=setTimeout(()=>{if(!done){done=true;reject(Error('Google Picker ใช้เวลานานเกินไป กรุณาลองอีกครั้ง'));}},8000);
    try{
      gapi.load('picker',()=>{
        if(done)return;
        done=true;clearTimeout(timer);
        if(window.google?.picker)resolve();
        else reject(Error('ไม่สามารถเปิด Google Picker ได้'));
      });
    }catch(error){
      if(!done){done=true;clearTimeout(timer);reject(error);}
    }
  });
}
async function openSharedLibraryPicker(){
  if(!state.token){setSharedLibraryGate(true,'กรุณาเข้าสู่ระบบด้วยอีเมลที่ได้รับเชิญก่อน');return;}
  const key=String(cfg.googlePickerApiKey||'').trim();
  const appId=String(cfg.googleAppId||'').trim();
  if(!key||!appId){
    setSharedLibraryGate(true,'คลังที่แชร์ยังไม่พร้อม · ต้องตั้งค่า Google Picker API key ที่จำกัดเฉพาะโดเมน X-Stage และ Google Picker/Drive API');
    return;
  }
  ui.gateStatus.textContent='กำลังเปิดรายการโฟลเดอร์ที่แชร์…';
  try{
    await loadGooglePickerApi();
    const view=new google.picker.DocsView(google.picker.ViewId.DOCS)
      .setIncludeFolders(true)
      .setMimeTypes('application/vnd.google-apps.folder')
      .setSelectFolderEnabled(true)
      .setOwnedByMe(false)
      .setQuery('XStageWeb')
      .setMode(google.picker.DocsViewMode.LIST);
    const picker=new google.picker.PickerBuilder()
      .addView(view)
      .setOAuthToken(state.token)
      .setDeveloperKey(key)
      .setAppId(appId)
      .setOrigin(location.origin)
      .setTitle('ใช้ XStageWeb ของผู้แชร์โดยตรง · ไม่มีการคัดลอกไฟล์')
      .setCallback(async data=>{
        const action=data?.[google.picker.Response.ACTION];
        if(action===google.picker.Action.CANCEL){
          ui.gateStatus.textContent='ยังไม่ได้เลือกคลังที่แชร์';
          return;
        }
        if(action!==google.picker.Action.PICKED)return;
        const doc=data?.[google.picker.Response.DOCUMENTS]?.[0];
        const id=String(doc?.[google.picker.Document.ID]||'');
        const name=String(doc?.[google.picker.Document.NAME]||'');
        if(!id){
          ui.gateStatus.textContent='ไม่ได้รับรหัสโฟลเดอร์จาก Google Picker';
          return;
        }
        if(name&&name!=='StageWeb'&&name!=='XStageWeb'){
          ui.gateStatus.textContent='กรุณาเลือกโฟลเดอร์ StageWeb หรือ XStageWeb ที่เจ้าของแชร์ให้';
          return;
        }
        ui.gateStatus.textContent='อนุญาตคลังที่แชร์แล้ว · กำลังเปิดเพลง…';
        setSharedLibraryGate(false);
        const idNow=state.authId;
        try{
          await openDrive(state.token,idNow,state.tokenExpiresAt,state.accountSub);
        }catch(error){
          setSharedLibraryGate(true,error?.message||'ยังเปิดคลังที่แชร์ไม่ได้ กรุณาเลือก XStageWeb อีกครั้ง');
        }
      })
      .build();
    picker.setVisible(true);
  }catch(error){
    setSharedLibraryGate(true,error?.message||'ไม่สามารถเปิด Google Picker ได้');
  }
}
$('gate-shared-library')?.addEventListener('click',openSharedLibraryPicker);

// The Windows sync publisher switches current.json after each verified batch.
// Older snapshots contain songs[]; newer pointers may include immutable deltas.
// Catalog media URLs remain private and are never exposed outside this account.
async function readPublishedCatalog(pointer,token,{sub='',onProgress=null}={}){
  if(pointer?.schemaVersion!==1 || typeof pointer.catalogFileId!=='string' || !pointer.catalogFileId)
    throw Error('รูปแบบ current.json ไม่รองรับ');
  const deltaIds=pointer.deltaFileIds||[];
  if(!Array.isArray(deltaIds)||deltaIds.length>32||new Set(deltaIds).size!==deltaIds.length)
    throw Error('รายการอัปเดตฐานเพลงบน Drive ไม่ถูกต้อง');
  const totalPieces=1+deltaIds.length;
  let completedPieces=0;
  const report=(message,fromCache=false)=>{
    completedPieces++;
    if(typeof onProgress==='function')onProgress({
      completed:completedPieces,total:totalPieces,message,fromCache,
      percent:42+Math.round((completedPieces/Math.max(1,totalPieces))*48)
    });
  };
  async function fetchImmutable(id,label){
    if(typeof id!=='string'||!id)throw Error('ฐานเพลงไม่มี Drive File ID');
    if(state.catalogCache.has(id)){report(label+' · พร้อมแล้ว',true);return state.catalogCache.get(id);}
    const persisted=await loadCatalogPiece(sub,id);
    if(persisted){
      state.catalogCache.set(id,persisted);
      report(label+' · ใช้ส่วนที่โหลดไว้แล้ว',true);
      return persisted;
    }
    const data=await privateJson(id,token);
    state.catalogCache.set(id,data);
    await saveCatalogPiece(sub,id,data);
    if(state.catalogCache.size>40){
      const oldest=state.catalogCache.keys().next().value;
      state.catalogCache.delete(oldest);
    }
    report(label+' · ดาวน์โหลดแล้ว',false);
    return data;
  }
  const base=await fetchImmutable(pointer.catalogFileId,'ฐานหลัก');
  if(base?.schemaVersion!==1||!Array.isArray(base.songs))
    throw Error('ฐานเพลงหลักบน Drive ไม่รองรับ');
  if(!deltaIds.length){
    if(Number.isSafeInteger(pointer.songCount)&&base.songs.length!==pointer.songCount)
      throw Error('ฐานเพลงชุดนี้มีจำนวนเพลงไม่ตรงกับข้อมูลเผยแพร่');
    return base;
  }
  const songs=new Map();
  for(const song of base.songs){
    if(song && typeof song.webSongId==='string')songs.set(song.webSongId,song);
  }
  for(let deltaIndex=0;deltaIndex<deltaIds.length;deltaIndex++){
    const id=deltaIds[deltaIndex];
    const delta=await fetchImmutable(id,'ส่วนอัปเดต '+(deltaIndex+1)+'/'+deltaIds.length);
    if(delta?.schemaVersion!==1 || !Array.isArray(delta.upserts)||!Array.isArray(delta.removes))
      throw Error('ข้อมูลอัปเดตเพลงบางชุดไม่ถูกต้อง');
    for(const key of delta.removes){
      if(typeof key!=='string')throw Error('ข้อมูลลบเพลงไม่ถูกต้อง');
      songs.delete(key);
    }
    for(const song of delta.upserts){
      if(!song || typeof song.webSongId!=='string')throw Error('รายการเพลงที่อัปเดตไม่ถูกต้อง');
      songs.set(song.webSongId,song);
    }
  }
  if(Number.isSafeInteger(pointer.songCount) && songs.size!==pointer.songCount)
    throw Error('จำนวนเพลงที่เผยแพร่บางชุดไม่ตรงกัน กรุณาตรวจการซิงค์');
  return {schemaVersion:1,generation:pointer.generation,songs:[...songs.values()]};
}
async function pollPublishedCatalog(){
  if(!state.token||!state.catalogPointerId||state.catalogPolling)return;
  const authId=state.authId,token=state.token;
  state.catalogPolling=true;
  try{
    const pointer=await privateJson(state.catalogPointerId,token);
    if(authId!==state.authId||state.token!==token||!pointer?.generation||
       pointer.generation===state.catalogGeneration)return;
    const cacheOwner=libraryCacheOwner(state.accountSub,state.libraryRootId);
    const catalog=await readPublishedCatalog(pointer,token,{sub:cacheOwner});
    if(authId!==state.authId||state.token!==token)return;
    const countBefore=state.songs.length;
    state.manifest=catalog;
    state.songs=catalog.songs.filter(playable);
    state.catalogGeneration=pointer.generation;
    void saveCachedCatalog(cacheOwner,pointer,catalog);
    state.medleyPoolSource=null;
    ui.songTotal.textContent=`${num(state.songs.length)} เพลง`;
    renderSongs();renderQueue();
    ui.libraryState.textContent='Google Drive · '+(state.libraryRootOwnedByMe?'คลังของฉัน':state.libraryRootOwnerEmail?'แชร์โดย '+state.libraryRootOwnerEmail:'คลังที่แชร์ให้ฉัน')+' · อัปเดตแล้ว';
    setStatus(`ฐานเพลงอัปเดต: ${num(countBefore)} → ${num(state.songs.length)} เพลง`,'success');
  }catch(error){
    // Keep the last known good catalog playable if a batch is unreachable.
    if(state.token===token&&authId===state.authId){
      console.warn('X-Stage catalog refresh:',error?.message||error);
    }
  }finally{state.catalogPolling=false;}
}
setInterval(pollPublishedCatalog,45000);

function applyInstantCatalog(instant){
  if(!instant)return false;
  state.manifest=instant.catalog;
  state.catalogGeneration=instant.generation;
  state.songs=instant.catalog.songs.filter(playable);
  state.selectedIndex=0;
  setSearchAvailability(true);
  ui.libraryState.textContent='ฐานเพลงในเครื่องพร้อมใช้ · กำลังตรวจอัปเดตเบื้องหลัง';
  ui.songTotal.textContent=`${num(state.songs.length)} เพลง`;
  ui.resultCount.textContent='พิมพ์เพื่อค้นหาเพลง';
  hideCatalogLoading();
  renderSongs();renderQueue();
  setStatus(`พร้อมใช้งานทันที · ${num(state.songs.length)} เพลงจากฐานในเครื่อง · กำลังตรวจอัปเดตเบื้องหลัง`,'success');
  void restorePlaybackAfterReload();
  if(!readPlaybackResumeState())ui.search.focus();
  return true;
}

async function openDrive(token, authId, tokenExpiresAt=0, expectedSub='') {
  setStatus('กำลังยืนยันบัญชี Google…');
  const accountResult = await googleFetch('https://openidconnect.googleapis.com/v1/userinfo', {headers:requestHeaders(token),cache:'no-store'},'Google Account');
  if (!accountResult.ok) throw driveError(accountResult.status,'ข้อมูลบัญชี Google');
  const account = await accountResult.json();
  if (!account.email_verified || !account.sub) throw Error('ไม่สามารถยืนยันบัญชี Google ได้');
  if (expectedSub && account.sub!==expectedSub) throw Error('บัญชี Google ไม่ตรงกับเซสชันเดิม กรุณาเข้าสู่ระบบอีกครั้ง');
  if (authId !== state.authId) return;

  // A new short-lived token for the SAME account must not reset the player,
  // downloaded audio, search results or queue. Only the credential changes.
  if (expectedSub && state.token && state.accountSub===account.sub) {
    state.token=token;
    state.tokenExpiresAt=tokenExpiresAt;
    rememberLogin(true);
    saveActiveAuth(token,tokenExpiresAt,account.sub);
    clearPendingAuth();
    setStatus('ต่ออายุ Google Drive สำเร็จ · เพลงและคิวเดิมเล่นต่อเนื่อง','success');
    window.dispatchEvent(new CustomEvent('xstage:auth-refreshed',{detail:{sub:String(account.sub)}}));
    // An already verified same-account Drive session can reopen after renewal.
    if(androidTvVerifiedConnectionSub===account.sub)setAndroidTvStageAccess(true);
    return;
  }
  if(state.token && state.token!==token)state.catalogCache.clear();
  // Authentication is complete. Activate the account immediately.
  state.token=token;
  state.tokenExpiresAt=tokenExpiresAt;
  state.accountSub=account.sub;
  window.dispatchEvent(new CustomEvent('xstage:auth-ready',{detail:{sub:String(account.sub)}}));
  rememberLogin(true);
  saveActiveAuth(token,tokenExpiresAt,account.sub);
  clearPendingAuth();
  ui.account.textContent=account.email||'Google';
  ui.account.hidden=false;
  ui.logout.hidden=false;
  ui.login.hidden=true;
  ui.gate.hidden=true;
  setSearchAvailability(false,{busy:true});
  ui.libraryState.textContent='เข้าสู่ระบบแล้ว · กำลังเปิดฐานเพลงในเครื่อง';
  ui.songTotal.textContent='กำลังโหลด…';
  ui.resultCount.textContent='กำลังเปิดฐานเพลง';
  showCatalogLoading('เข้าสู่ระบบสำเร็จ','กำลังตรวจฐานเพลงในเครื่อง…',6);

  // Use the last selected library's verified cache first. Legacy account-only
  // cache remains a migration fallback until the first root-specific save.
  const preferredRootId=readPreferredLibraryRoot(account.sub);
  let instant=await loadLatestCachedCatalog(account.sub,preferredRootId);
  if(!instant&&!preferredRootId)instant=await loadLatestCachedCatalog(account.sub);
  if(authId!==state.authId)return;
  if(!applyInstantCatalog(instant)){
    showCatalogLoading('เตรียมใช้งานครั้งแรก','กำลังค้นหาคลัง XStageWeb…',12);
    setStatus('เข้าสู่ระบบสำเร็จ · กำลังดาวน์โหลดฐานเพลงครั้งแรก…','success');
  }

  try{
    const roots=await driveList("(name='StageWeb' or name='XStageWeb') and mimeType='application/vnd.google-apps.folder' and trashed=false",token);
    if(!instant)showCatalogLoading('เตรียมใช้งานครั้งแรก','พบคลังเพลง · กำลังตรวจ current.json…',24);
    if(authId!==state.authId)return;
    if(!roots.length){
      // A verified empty Drive is NOT a valid cached library. An account
      // whose XStageWeb was deleted must never show ghost songs that fail 404.
      // Do not erase the user's browser cache permanently: their library may
      // reappear after a Google Drive permission grant or restored ownership.
      state.libraryRootId='';
      state.catalogPointerId='';
      state.catalogGeneration='';
      state.manifest=null;
      state.songs=[];
      state.shown=[];
      state.catalogCache.clear();
      state.queue=[];
      releaseQueuePreload();
      renderSongs();
      renderQueue();
      setAndroidTvStageAccess(true,account.sub);
      hideCatalogLoading();
      ui.songTotal.textContent='0 เพลง';
      ui.resultCount.textContent='ยังไม่มีคลัง XStageWeb';
      ui.libraryState.textContent='เชื่อม Google Drive แล้ว · ยังไม่มีคลังเพลงออนไลน์';
      setStatus('บัญชี Google พร้อมแล้ว · ใช้ X-Stage Song Studio สร้าง XStageWeb และอัปโหลดเพลงครั้งแรก','success');
      setSharedLibraryGate(true,'ยังไม่มี XStageWeb ในบัญชีนี้ · อัปโหลดด้วย Song Studio หรือเลือกคลังที่แชร์');
      return;
    }
    setSharedLibraryGate(false);
    const ownedRoots=roots.filter(item=>item.ownedByMe);
    const sharedRoots=roots.filter(item=>!item.ownedByMe).sort((a,b)=>String(b.sharedWithMeTime||'').localeCompare(String(a.sharedWithMeTime||'')));
    const preferred=preferredRootId&&roots.find(item=>String(item.id)===preferredRootId);
    const root=preferred||ownedRoots[0]||sharedRoots[0]||roots[0];
    if(preferredRootId&&String(root.id)!==preferredRootId&&instant){
      // Do not keep showing a cache for a library that is no longer accessible.
      instant=null;
      state.manifest=null;state.songs=[];state.shown=[];renderSongs();
    }
    state.libraryRootId=root.id;
    state.libraryRootOwnedByMe=!!root.ownedByMe;
    state.libraryRootCanShare=!!root.capabilities?.canShare;
    state.libraryRootOwnerEmail=String(root.owners?.[0]?.emailAddress||'');
    savePreferredLibraryRoot(account.sub,root.id);
    renderLibrarySelector([...ownedRoots,...sharedRoots],root.id);
    window.dispatchEvent(new CustomEvent('xstage:librarychange',{detail:{
      accountSub:account.sub,rootId:String(root.id),label:libraryLabel(root),ownedByMe:!!root.ownedByMe
    }}));
    const cacheOwner=libraryCacheOwner(account.sub,root.id);
    if(!instant){
      const rootCached=await loadLatestCachedCatalog(account.sub,root.id);
      if(rootCached){instant=rootCached;applyInstantCatalog(instant);}
    }
    const pointers=await driveList(`'${root.id}' in parents and name='current.json' and trashed=false`,token);
    if(!instant)showCatalogLoading('เตรียมใช้งานครั้งแรก','กำลังอ่านข้อมูลรุ่นฐานเพลง…',34);
    if(!pointers.length){
      // A newly created XStageWeb may contain only empty category folders or
      // a SoundFont uploaded first. It is not a broken catalog. Discard the
      // previous session's visible songs, but NEVER delete any Drive data.
      // A missing pointer can also mean drive.file lacks permission; avoid
      // claiming definitively that the user's entire Drive is empty.
      if(authId!==state.authId)return;
      state.manifest=null;
      state.catalogPointerId='';
      state.catalogGeneration='';
      state.songs=[];
      state.shown=[];
      state.queue=[];
      state.selectedIndex=0;
      state.catalogCache.clear();
      releaseQueuePreload();
      if(state.current || player.src)clearIdleStage('ยังไม่มีเพลงในคลังนี้');
      renderSongs();
      renderQueue();
      setSearchAvailability(true);
      ui.songTotal.textContent='0 เพลง';
      ui.resultCount.textContent='ยังไม่มีเพลงพร้อมเล่น';
      ui.libraryState.textContent='Google Drive · '+libraryLabel(root)+' · ยังไม่มี DB เพลงที่เข้าถึงได้';
      hideCatalogLoading();
      setAndroidTvStageAccess(true,account.sub);
      setStatus('เชื่อม Google Drive แล้ว · ยังไม่พบ current.json ที่เข้าถึงได้ · สร้าง DB/อัปโหลดเพลงผ่าน X-Stage Song Studio','success');
      return;
    }
    if(pointers.length!==1)throw Error('พบ current.json หลายรายการ · ไม่เลือกฐานเพลงโดยคาดเดา');
    const pointer=await privateJson(pointers[0].id,token);
    if(!instant)showCatalogLoading('เตรียมใช้งานครั้งแรก','กำลังดาวน์โหลดเฉพาะฐานรายชื่อเพลง…',42);
    if(authId!==state.authId)return;

    const sameAsInstant=!!instant&&
      instant.generation===String(pointer.generation||'')&&
      instant.catalogFileId===pointer.catalogFileId&&
      JSON.stringify(instant.deltaFileIds||[])===JSON.stringify(pointer.deltaFileIds||[]);

    let catalog=instant?.catalog||null;
    let downloaded=false;
    if(!sameAsInstant){
      if(!instant)showCatalogLoading('กำลังเตรียมฐานเพลงครั้งแรก','ดาวน์โหลดเฉพาะข้อมูลค้นหาเพลง · ยังไม่โหลดไฟล์ M4A',42);
      else setStatus(`กำลังอัปเดตฐานเพลงเบื้องหลัง · ยังใช้ ${num(state.songs.length)} เพลงเดิมได้ตามปกติ`);
      catalog=await readPublishedCatalog(pointer,token,{
        sub:cacheOwner,
        onProgress:info=>{
          if(instant)return;
          showCatalogLoading('กำลังเตรียมฐานเพลงครั้งแรก',
            info.message+' · '+info.completed+'/'+info.total+' ส่วน',
            info.percent);
        }
      });
      downloaded=true;
      if(authId!==state.authId)return;
      if(!instant){
        showCatalogLoading('กำลังบันทึกฐานเพลง','จัดเก็บฐานไว้ในเครื่องสำหรับเปิดครั้งต่อไป…',96);
        await saveCachedCatalog(cacheOwner,pointer,catalog);
      }else{
        void saveCachedCatalog(cacheOwner,pointer,catalog);
      }
    }

    state.manifest=catalog;
    state.catalogPointerId=pointers[0].id;
    state.catalogGeneration=String(pointer.generation||'');
    if(downloaded||!instant){
      state.songs=catalog.songs.filter(playable);
      state.selectedIndex=0;
      ui.songTotal.textContent=`${num(state.songs.length)} เพลง`;
      renderSongs();renderQueue();
    }
    setSearchAvailability(true);
    ui.libraryState.textContent='Google Drive · '+libraryLabel(root)+' · พร้อมใช้งาน';
    ui.resultCount.textContent=ui.search.value.trim() ? ui.resultCount.textContent : 'พิมพ์เพื่อค้นหาเพลง';
    if(!instant)showCatalogLoading('พร้อมใช้งาน','ฐานเพลงครั้งแรกพร้อมแล้ว',100);
    hideCatalogLoading();
    void saveCachedCatalog(cacheOwner,pointer,catalog);
    setStatus(`เชื่อมต่อแล้ว · ${num(state.songs.length)} เพลง · ${libraryLabel(root)}${downloaded?' (อัปเดตฐานล่าสุดแล้ว)':sameAsInstant?' (ฐานในเครื่องเป็นรุ่นล่าสุด)':''}`,'success');
    setAndroidTvStageAccess(true,account.sub);
    void restorePlaybackAfterReload();
    if(!readPlaybackResumeState())ui.search.focus();
  }catch(error){
    hideCatalogLoading();
    if(instant&&state.token===token&&authId===state.authId){
      // Initial Android login requires LIVE Google Drive verification;
      // cached songs must not silently bypass authorization.
      if(androidTvNativeBridgeReady()&&!androidTvVerifiedConnectionSub)throw error;
      // Local catalog stays usable when update checking is slow/offline/fails.
      setSearchAvailability(true);
      ui.libraryState.textContent='ใช้ฐานเพลงในเครื่อง · ตรวจอัปเดตภายหลัง';
      setStatus(`พร้อมใช้งานจากฐานในเครื่อง · ตรวจอัปเดต Google Drive ไม่สำเร็จ: ${error.message}`,'success');
      return;
    }
    throw error;
  }
}
const XSTAGE_TV_POPUP_HELP_ID='xstage-tv-popup-help';
function isLikelyAndroidTvBrowser(){
  const ua=String(navigator.userAgent||'');
  if(!/Android/i.test(ua))return false;
  const noTouch=Number(navigator.maxTouchPoints||0)===0;
  const wideScreen=Math.max(Number(screen?.width||0),Number(screen?.height||0))>=960;
  return noTouch&&wideScreen;
}
function hideTvPopupHelp(){
  document.getElementById(XSTAGE_TV_POPUP_HELP_ID)?.remove();
}
function showTvPopupHelp(message=''){
  hideTvPopupHelp();
  const host=location.host||'webbase-x.github.io';
  const panel=document.createElement('section');
  panel.id=XSTAGE_TV_POPUP_HELP_ID;
  panel.setAttribute('role','dialog');
  panel.setAttribute('aria-modal','true');
  panel.setAttribute('aria-label','ตั้งค่า Pop-up สำหรับ Google Login บน TV Bro');
  Object.assign(panel.style,{
    position:'fixed',inset:'0',zIndex:'2147483647',display:'grid',placeItems:'center',
    background:'rgba(0,0,0,.82)',padding:'24px',fontFamily:'system-ui,sans-serif'
  });
  const box=document.createElement('div');
  Object.assign(box.style,{
    width:'min(760px,92vw)',maxHeight:'88vh',overflow:'auto',background:'#071525',
    color:'#fff',border:'2px solid rgba(255,255,255,.22)',borderRadius:'22px',
    padding:'26px',boxShadow:'0 20px 70px rgba(0,0,0,.55)',lineHeight:'1.55'
  });
  const title=document.createElement('h2');
  title.textContent='อนุญาต Pop-up ใน TV Bro ก่อนเข้าสู่ Google';
  title.style.margin='0 0 12px';
  const intro=document.createElement('p');
  intro.textContent=message||'TV Bro กำลังบล็อกหน้าต่าง Google Login สำหรับ X-Stage';
  const steps=document.createElement('ol');
  steps.style.paddingInlineStart='1.5em';
  for(const line of [
    'กด Menu ของ TV Bro เพื่อเปิดแถบเครื่องมือ',
    'เลือกการตั้งค่า Pop-up / New windows แล้วอนุญาต Pop-up สำหรับเว็บไซต์ '+host,
    'กลับมาหน้า X-Stage แล้วกด “ตรวจอีกครั้งและเข้าสู่ระบบ” ด้านล่าง'
  ]){
    const li=document.createElement('li');li.textContent=line;li.style.margin='8px 0';steps.append(li);
  }
  const note=document.createElement('p');
  note.textContent='อนุญาตเฉพาะเว็บไซต์ X-Stage ก็พอ ไม่จำเป็นต้องปิดตัวบล็อก Pop-up สำหรับทุกเว็บไซต์';
  note.style.opacity='.82';
  const actions=document.createElement('div');
  Object.assign(actions.style,{display:'flex',gap:'12px',flexWrap:'wrap',marginTop:'18px'});
  const retry=document.createElement('button');
  retry.type='button';retry.textContent='ตรวจอีกครั้งและเข้าสู่ระบบ';
  Object.assign(retry.style,{fontSize:'20px',fontWeight:'700',padding:'14px 20px',borderRadius:'14px',cursor:'pointer'});
  const close=document.createElement('button');
  close.type='button';close.textContent='ปิด';
  Object.assign(close.style,{fontSize:'18px',padding:'14px 20px',borderRadius:'14px',cursor:'pointer'});
  retry.addEventListener('click',()=>{hideTvPopupHelp();login({automatic:false});});
  close.addEventListener('click',hideTvPopupHelp);
  actions.append(retry,close);
  box.append(title,intro,steps,note,actions);
  panel.append(box);
  document.body.append(panel);
  setTimeout(()=>retry.focus(),30);
}
function popupPreflightForTv(){
  if(!isLikelyAndroidTvBrowser())return true;
  let testWindow=null;
  try{
    testWindow=window.open('about:blank','xstage_popup_test','width=160,height=120');
  }catch{}
  if(!testWindow){
    showTvPopupHelp('ตรวจพบว่า TV Bro บล็อกหน้าต่างใหม่ จึงยังเปิด Google Login ไม่ได้');
    return false;
  }
  try{testWindow.close();}catch{}
  return true;
}

function googleAuthErrorMessage(error){
  const type=String(error?.type||error?.error||'').trim();
  const detail=String(error?.error_description||error?.message||'').trim();
  if(type==='popup_closed')return 'ยกเลิกการเข้าสู่ระบบ Google แล้ว · กดเข้าสู่ระบบอีกครั้งเมื่อต้องการ';
  if(/popup|window|blocked/i.test(type)){if(isLikelyAndroidTvBrowser())setTimeout(()=>showTvPopupHelp('TV Bro บล็อกหน้าต่าง Google Login กรุณาอนุญาต Pop-up สำหรับเว็บไซต์นี้'),0);return 'เบราว์เซอร์บล็อกหน้าต่าง Google · อนุญาต Pop-up สำหรับ X-Stage แล้วลองอีกครั้ง';}
  if(/access_denied|denied|cancel/i.test(type))return 'Google ไม่อนุญาตการเข้าถึง · กรุณาเลือกบัญชีและอนุญาตสิทธิ์ที่จำเป็น';
  if(/invalid_client|origin|redirect/i.test(type+' '+detail))return 'การตั้งค่า Google OAuth ไม่ตรงกับเว็บไซต์นี้ · ตรวจ Authorized JavaScript origin: https://webbase-x.github.io';
  if(detail&&detail!=='.')return 'เข้าสู่ระบบ Google ไม่สำเร็จ · '+detail;
  if(type&&type!=='.')return 'เข้าสู่ระบบ Google ไม่สำเร็จ · '+type;
  return 'เข้าสู่ระบบ Google ไม่สำเร็จ · กรุณาตรวจอินเทอร์เน็ต การอนุญาต Pop-up และการตั้งค่า OAuth แล้วลองอีกครั้ง';
}

function login({automatic=false} = {}) {
  if(!automatic&&!popupPreflightForTv())return;
  if(!navigator.onLine){setStatus('อุปกรณ์ออฟไลน์ · กรุณาเชื่อมต่ออินเทอร์เน็ตแล้วลองใหม่','error');return;}
  if (typeof google === 'undefined' || !google.accounts?.oauth2?.initTokenClient) {
    setStatus('ไม่สามารถโหลด Google Sign-In ได้ กรุณาตรวจอินเทอร์เน็ตและรีเฟรชหน้า', 'error'); return;
  }
  if (!cfg.googleClientId || !String(cfg.googleClientId).endsWith('.apps.googleusercontent.com')) {
    setStatus('ยังไม่ได้กำหนด Google OAuth Web Client ID สำหรับเว็บไซต์นี้', 'error'); return;
  }
  ui.login.disabled = ui.gateLogin.disabled = true;
  setStatus(automatic?'กำลังเชื่อมต่อบัญชี Google ที่เคยใช้…':'กำลังเปิดการอนุญาต Google…');
  const authId = ++state.authId;
  let settled=false;
  const finish=()=>{settled=true;clearTimeout(watchdog);ui.login.disabled=ui.gateLogin.disabled=false;};
  const watchdog=setTimeout(()=>{
    if(settled||authId!==state.authId)return;
    state.authId++;
    ui.login.disabled=ui.gateLogin.disabled=false;
    setStatus('Google Sign-In ไม่ตอบกลับภายในเวลาที่กำหนด · ปิดหน้าต่าง Google ที่ค้างแล้วกดเข้าสู่ระบบอีกครั้ง','error');
  },90_000);
  try {
    const client = google.accounts.oauth2.initTokenClient({
      client_id:cfg.googleClientId,
      scope:'openid email https://www.googleapis.com/auth/drive.file',
      callback: async result => {
        if (authId !== state.authId) return;
        finish();
        if(result?.error){setStatus(googleAuthErrorMessage(result),'error');return;}
        if (!result?.access_token) { setStatus('ไม่ได้รับสิทธิ์จาก Google · กรุณากดเข้าสู่ระบบอีกครั้ง', 'error'); return; }
        resetPrivate({revoke:false, keepAuth:true});
        const expiresIn=Number(result.expires_in);
        const expiresAt=Date.now()+Math.max(0,Math.min(3600,Number.isFinite(expiresIn)?expiresIn:3600))*1000;
        savePendingAuth(result.access_token,expiresAt);
        try { await openDrive(result.access_token,authId,expiresAt); }
        catch (e) {
          if (authId === state.authId) {
            if(state.awaitingSharedLibrary){
              hideCatalogLoading();
              setStatus('เข้าสู่ระบบบัญชีผู้รับเชิญแล้ว · กรุณาเปิดคลังที่แชร์','success');
              return;
            }
            clearActiveAuth();resetPrivate({keepAuth:true});
            if(!/เชื่อมต่อไม่สำเร็จ|ใช้เวลานาน|อินเทอร์เน็ต/.test(String(e.message||'')))clearPendingAuth();
            setStatus(e.message, 'error');
          }
        }
      },
      error_callback: error => {
        if (authId !== state.authId) return;
        finish();
        setStatus(googleAuthErrorMessage(error),'error');
      }
    });
    // A manual click should always use Google's normal account chooser. An empty
    // prompt is reserved for reconnecting an existing session and can leave a
    // stale/invalid OAuth warning flow open in some multi-account browser sessions.
    client.requestAccessToken(automatic?{prompt:''}:{prompt:'select_account'});
  } catch (e) { finish();setStatus(e.message, 'error'); }
}
function resetPrivate({revoke = false, keepAuth = false} = {}) {
  if(revoke){rememberLogin(false);clearActiveAuth();clearPendingAuth();}
  if (!keepAuth) state.authId++;
  const pendingSearch=keepAuth?String(ui.search?.value||''):'';
  const oldToken = state.token;
  state.requestId++;
  state.controller?.abort(); state.controller = null; state.loading = false;
  player.pause(); player.removeAttribute('src'); player.load();
  resetSongVideo();
  if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
  state.objectUrl = ''; state.token = '';state.tokenExpiresAt=0; state.accountSub = ''; state.manifest = null;
  state.songs = [];state.shown = [];state.queue = [];state.history = [];
  state.catalogPointerId='';state.catalogGeneration='';state.catalogCache.clear();
  state.libraryRootId='';state.libraryRootCanShare=false;state.libraryRootOwnedByMe=false;state.libraryRootOwnerEmail='';state.availableLibraries=[];
  if(ui.librarySelect)ui.librarySelect.replaceChildren();
  if(ui.librarySwitcher)ui.librarySwitcher.hidden=true;
  state.awaitingSharedLibrary=false;
  const sharedGate=$('gate-shared-library');if(sharedGate)sharedGate.hidden=true;
  releaseQueuePreload();
  state.medleyCache=null;state.medleyPrefetch=null;state.medleyUpcoming=null;
  state.medleyPoolSource=null;state.medleyPool=[];state.medleyRecent=[];state.userStopped=false;
  state.current = null;state.lyrics = null;state.selectedIndex = 0;
  clearMediaSession();
  ui.account.textContent = '';ui.account.hidden = true;ui.logout.hidden = true;ui.login.hidden = false;
  ui.gate.hidden = false;hideCatalogLoading();setSearchAvailability(false);ui.search.value = pendingSearch;
  ui.songTotal.textContent = '0 เพลง';ui.resultCount.textContent = 'กรุณาเข้าสู่ระบบ';
  ui.libraryState.textContent = 'คลังส่วนตัว · ไม่มีการเผยแพร่เพลงสาธารณะ';
  ui.nowPlaying.textContent = 'ยังไม่ได้เลือกเพลง';ui.nowArtist.textContent='X-Stage Karaoke Online';ui.stageCode.textContent='—';
  if(ui.songKey)ui.songKey.textContent='คีย์ —';
  ui.stage.classList.remove('playing');ui.stageIdle.hidden = false;
  setPlayStatus(''); updateTransport();renderSongs();renderQueue();
  if (revoke && oldToken && typeof google !== 'undefined') {
    try { google.accounts.oauth2.revoke(oldToken,()=>{}); } catch { /* session is already cleared */ }
  }
}

function songIdentity(song) { return String(song?.webSongId || `${song?.code}:${song?.title}:${song?.artist}`); }
function validShareEmail(value){
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(value||'').trim());
}
function openShareLibraryDialog(){
  const dialog=$('share-library-dialog');
  const email=$('share-library-email');
  const ack=$('share-library-ack');
  const submit=$('share-library-submit');
  const status=$('share-library-status');
  if(!dialog||!email||!ack||!submit||!status)return;
  status.textContent='';
  email.value='';
  ack.checked=false;
  const pickerReady=sharedLibraryFeatureReady();
  const canShare=!!(pickerReady&&state.token&&state.libraryRootId&&state.libraryRootOwnedByMe&&state.libraryRootCanShare);
  email.disabled=ack.disabled=!canShare;
  submit.disabled=true;
  if(!pickerReady)status.textContent='ยังไม่เปิดใช้งานการแชร์ · เจ้าของเว็บไซต์ต้องตั้งค่า Google Picker API ก่อน';
  else if(!state.token)status.textContent='กรุณาเข้าสู่ระบบ Google ก่อนแชร์';
  else if(!state.libraryRootOwnedByMe)status.textContent='คลังนี้เป็นคลังที่ผู้อื่นแชร์ให้ จึงไม่สามารถแชร์ต่อจาก X-Stage ได้';
  else if(!state.libraryRootCanShare)status.textContent='บัญชีนี้ไม่มีสิทธิ์แชร์โฟลเดอร์ XStageWeb';
  dialog.showModal();
  if(canShare)setTimeout(()=>email.focus(),30);
}
async function shareLibraryWithEmail(email){
  if(!sharedLibraryFeatureReady())throw Error('ระบบแชร์ยังไม่พร้อม · กรุณาตั้งค่า Google Picker API ก่อน');
  if(!state.token)throw Error('กรุณาเข้าสู่ระบบ Google ก่อนแชร์');
  if(!state.libraryRootId||!state.libraryRootOwnedByMe||!state.libraryRootCanShare)
    throw Error('บัญชีนี้ไม่มีสิทธิ์แชร์คลังเพลง');
  const recipient=String(email||'').trim();
  if(!validShareEmail(recipient))throw Error('กรุณากรอกอีเมล Google ของผู้รับให้ถูกต้อง');
  const params=new URLSearchParams({
    sendNotificationEmail:'true',
    supportsAllDrives:'true',
    emailMessage:'X-Stage Karaoke: คุณได้รับสิทธิ์ดูคลังเพลง XStageWeb แบบอ่านอย่างเดียว กรุณาเข้า X-Stage ด้วยอีเมลนี้'
  });
  const response=await googleFetch(
    `https://www.googleapis.com/drive/v3/files/${encodeURIComponent(state.libraryRootId)}/permissions?${params}`,
    {
      method:'POST',
      headers:{...requestHeaders(state.token),'Content-Type':'application/json'},
      body:JSON.stringify({type:'user',role:'reader',emailAddress:recipient}),
      cache:'no-store'
    },
    'Google Drive'
  );
  if(!response.ok){
    let message='';
    try{const body=await response.json();message=String(body?.error?.message||'');}catch{}
    if(response.status===403&&/sharingRateLimitExceeded/i.test(message))throw Error('Google จำกัดความถี่การแชร์ชั่วคราว กรุณาลองใหม่ภายหลัง');
    if(response.status===403)throw Error(message||'บัญชี Google นี้ไม่อนุญาตให้แชร์โฟลเดอร์นี้');
    if(response.status===400)throw Error(message||'อีเมลผู้รับหรือการตั้งค่าการแชร์ไม่ถูกต้อง');
    throw Error(message||`แชร์ไม่สำเร็จ (HTTP ${response.status})`);
  }
  return true;
}
function setupLibrarySharing(){
  const sharingReady=sharedLibraryFeatureReady();
  for(const button of [$('pc-share-library'),$('mobile-share-library'),document.querySelector('#xstage-context-menu [data-cmd="share"]')]){
    if(button){button.hidden=!sharingReady;button.disabled=!sharingReady;}
  }
  const dialog=$('share-library-dialog');
  const email=$('share-library-email');
  const ack=$('share-library-ack');
  const submit=$('share-library-submit');
  const status=$('share-library-status');
  if(!dialog||!email||!ack||!submit||!status)return;
  const sync=()=>{submit.disabled=!(ack.checked&&validShareEmail(email.value)&&state.libraryRootOwnedByMe&&state.libraryRootCanShare&&!submit.dataset.busy);};
  email.addEventListener('input',sync);ack.addEventListener('change',sync);
  $('share-library-close')?.addEventListener('click',()=>dialog.close());
  $('share-library-cancel')?.addEventListener('click',()=>dialog.close());
  $('pc-share-library')?.addEventListener('click',openShareLibraryDialog);
  $('mobile-share-library')?.addEventListener('click',openShareLibraryDialog);
  submit.addEventListener('click',async()=>{
    if(submit.disabled)return;
    submit.dataset.busy='1';submit.disabled=true;status.textContent='กำลังแชร์…';
    try{
      await shareLibraryWithEmail(email.value);
      status.textContent='แชร์สำเร็จ · ผู้รับต้องเข้า X-Stage ด้วยอีเมลนี้';
      email.value='';ack.checked=false;
    }catch(error){
      status.textContent=error?.message||'แชร์ไม่สำเร็จ';
    }finally{
      delete submit.dataset.busy;sync();
    }
  });
}
setupLibrarySharing();


const PLAYBACK_RESUME_KEY='xstage-playback-resume-v1';
function clearPlaybackResumeState(){
  try{sessionStorage.removeItem(PLAYBACK_RESUME_KEY);}catch{}
}
function savePlaybackResumeState(){
  try{
    if(!state.current||!player.src||player.ended||state.userStopped){
      clearPlaybackResumeState();
      return;
    }
    sessionStorage.setItem(PLAYBACK_RESUME_KEY,JSON.stringify({
      savedAt:Date.now(),
      songKey:songIdentity(state.current),
      songCode:String(state.current.code||''),
      songTitle:String(state.current.title||''),
      currentTime:Math.max(0,Number(player.currentTime)||0),
      wasPlaying:!state.userPaused&&!state.userStopped&&(!player.paused||state.resumeAfterInterruption),
      queueKeys:state.queue.map(songIdentity)
    }));
  }catch{}
}
function readPlaybackResumeState(){
  try{
    const saved=JSON.parse(sessionStorage.getItem(PLAYBACK_RESUME_KEY)||'null');
    if(!saved||Date.now()-Number(saved.savedAt||0)>2*60*60*1000)return null;
    return saved;
  }catch{return null;}
}
function findResumeSong(key,code,title){
  return state.songs.find(song=>songIdentity(song)===String(key||''))||
    state.songs.find(song=>code&&String(song.code||'')===String(code))||
    state.songs.find(song=>title&&String(song.title||'')===String(title))||null;
}
async function restorePlaybackAfterReload(){
  if(state.playbackRestoreAttempted||!state.songs.length)return false;
  const saved=readPlaybackResumeState();
  if(!saved)return false;
  state.playbackRestoreAttempted=true;
  const song=findResumeSong(saved.songKey,saved.songCode,saved.songTitle);
  if(!song){clearPlaybackResumeState();return false;}
  const restoredQueue=(Array.isArray(saved.queueKeys)?saved.queueKeys:[])
    .map(key=>state.songs.find(item=>songIdentity(item)===String(key)))
    .filter(Boolean);
  state.queue.splice(0,state.queue.length,...restoredQueue);
  renderQueue();
  await playSong(song,{remember:false,resumeAt:Number(saved.currentTime)||0,autoplay:!!saved.wasPlaying});
  return true;
}
function element(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}
function control(label,handler,title = label) {
  const b = element('button','',label); b.type='button';b.title=title;b.setAttribute('aria-label',title);
  b.addEventListener('click',handler);return b;
}
function renderMatchedText(node, value, term) {
  const raw=String(value ?? '');
  const hit=term ? raw.toLocaleLowerCase('th').indexOf(term) : -1;
  if(hit<0){node.textContent=raw;return;}
  node.append(document.createTextNode(raw.slice(0,hit)));
  const match=document.createElement('mark');
  match.className='song-match';
  match.textContent=raw.slice(hit,hit+term.length);
  node.append(match,document.createTextNode(raw.slice(hit+term.length)));
}

function normalizeSearchText(value){
  return String(value??'')
    .normalize('NFKC')
    .toLocaleLowerCase('th')
    .replace(/\s+/g,' ')
    .trim();
}
let searchIndexSource=null;
let searchIndex=[];
function indexedSongs(songs){
  if(searchIndexSource===songs)return searchIndex;
  searchIndexSource=songs;
  searchIndex=(Array.isArray(songs)?songs:[]).map((song,index)=>{
    const code=normalizeSearchText(song?.code);
    const title=normalizeSearchText(song?.title);
    const artist=normalizeSearchText(song?.artist);
    return {song,index,code,title,artist,combined:[code,title,artist].filter(Boolean).join(' ')};
  });
  return searchIndex;
}
function searchScore(entry,term){
  if(!term)return Number.POSITIVE_INFINITY;
  if(entry.code===term)return 0;
  if(entry.title===term)return 10;
  if(entry.title.startsWith(term))return 20;
  if(entry.code.startsWith(term))return 30;
  if(entry.artist===term)return 40;
  if(entry.artist.startsWith(term))return 50;
  const words=term.split(' ').filter(Boolean);
  if(words.length>1&&words.every(word=>entry.combined.includes(word)))return 55;
  if(entry.title.includes(term))return 60;
  if(entry.artist.includes(term))return 70;
  if(entry.code.includes(term))return 80;
  if(entry.combined.includes(term))return 90;
  return Number.POSITIVE_INFINITY;
}
function rankedSearchEntries(songs,rawTerm){
  const term=normalizeSearchText(rawTerm);
  if(!term)return [];
  return indexedSongs(songs)
    .map(entry=>({entry,score:searchScore(entry,term)}))
    .filter(item=>Number.isFinite(item.score))
    .sort((a,b)=>a.score-b.score||a.entry.index-b.entry.index)
    .map(item=>({...item.entry,score:item.score}));
}
window.XStageRankSearch=(songs,rawTerm,limit=5)=>
  rankedSearchEntries(songs,rawTerm).slice(0,Math.max(0,Number(limit)||0));

function setLiveSearchExpanded(open){
  const dock=ui.search?.closest('.search-dock');
  if(!dock)return;
  dock.classList.toggle('pc-expanded',!!open);
  ui.search.setAttribute('aria-expanded',String(!!open));
}
function restoreViewportAfterKeyboard(){
  const settle=()=>{
    try{window.scrollTo({left:0,top:0,behavior:'instant'});}catch{window.scrollTo(0,0);}
    const vv=window.visualViewport;
    if(!vv||vv.scale<=1.01)return;
    const meta=document.querySelector('meta[name="viewport"]');
    if(!meta)return;
    const original=meta.getAttribute('content')||'width=device-width, initial-scale=1, viewport-fit=cover';
    meta.setAttribute('content','width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover');
    setTimeout(()=>{
      meta.setAttribute('content',original);
      try{window.scrollTo(0,0);}catch{}
    },140);
  };
  requestAnimationFrame(()=>setTimeout(settle,80));
}
function clearSearchAfterChoice(){
  ui.search.value='';
  state.shown=[];
  state.selectedIndex=0;
  renderSongs();
  setLiveSearchExpanded(false);
  // Release the mobile/iPad software keyboard and restore the full visual viewport.
  if(document.activeElement===ui.search)ui.search.blur();
  else document.activeElement?.blur?.();
  restoreViewportAfterKeyboard();
}
function renderSongs() {
  ui.songs.replaceChildren();
  const rawTerm=ui.search.value.trim();
  const term=normalizeSearchText(rawTerm);
  const highlightTerm=rawTerm.toLocaleLowerCase('th');
  if (!state.token) {
    state.shown=[];state.selectedIndex=0;
    if(ui.searchRefine)ui.searchRefine.hidden=true;
    ui.search.removeAttribute('aria-activedescendant');
    if(term){
      setLiveSearchExpanded(true);
      ui.resultCount.textContent='พิมพ์คำค้นไว้แล้ว · เข้าสู่ระบบ Google เพื่อค้นหาจากคลังส่วนตัว';
      ui.songs.append(element('div','empty-state','เชื่อมต่อ Google Drive แล้วระบบจะค้นหาคำที่พิมพ์ไว้นี้ให้ทันที'));
    }else{
      setLiveSearchExpanded(false);
      ui.resultCount.textContent='พิมพ์คำค้นได้ · เชื่อมต่อ Google เมื่อต้องการดูผลเพลง';
      ui.songs.append(element('div','empty-state','ค้นหาด้วยชื่อเพลง ศิลปิน หรือรหัสเพลง'));
    }
    return;
  }
  if(!term){
    setLiveSearchExpanded(false);
    // Empty search is not a request to list the complete private catalog.
    state.shown=[];state.selectedIndex=0;
    if(ui.searchRefine)ui.searchRefine.hidden=true;
    ui.resultCount.textContent='พิมพ์เพื่อค้นหาเพลง';
    ui.search.removeAttribute('aria-activedescendant');
    return;
  }
  setLiveSearchExpanded(true);
  const ranked=rankedSearchEntries(state.songs,term);
  state.shown=ranked.slice(0,5).map(item=>item.song);
  state.selectedIndex=Math.max(0,Math.min(state.selectedIndex,state.shown.length-1));
  ui.resultCount.textContent=`พบ ${num(ranked.length)} เพลง${ranked.length>5?' · 5 ผลลัพธ์ที่ตรงที่สุด':''}`;
  if(ui.searchRefine){
    ui.searchRefine.hidden=ranked.length<=5;
    ui.searchRefine.textContent='พิมพ์เพิ่มเพื่อเจาะจงผลค้นหา';
  }
  if (!state.shown.length) {
    if(ui.searchRefine)ui.searchRefine.hidden=true;
    ui.search.removeAttribute('aria-activedescendant');
    ui.songs.append(element('div','empty-state',term?'ไม่พบเพลงที่ค้นหา':'ยังไม่มีเพลงที่พร้อมเล่น'));return;
  }
  const fragment = document.createDocumentFragment();
  state.shown.forEach((song,i) => {
    const row=element('div','song-item'+(i===state.selectedIndex?' selected':''));
    row.role='option';row.id='song-option-'+i;row.setAttribute('aria-selected',String(i===state.selectedIndex));
    row.tabIndex = -1;row.title=state.current||state.loading?'เลือกเพื่อเพิ่มเข้าคิว':'เลือกเพื่อเล่นทันที';
    const details=element('div','song-details');
    const code=element('div','song-code'),title=element('strong'),artist=element('small');
    renderMatchedText(code,song.code||'—',highlightTerm);
    renderMatchedText(title,song.title||'ไม่ระบุชื่อเพลง',highlightTerm);
    renderMatchedText(artist,song.artist||'ไม่ระบุศิลปิน',highlightTerm);
    details.append(code,title,artist);
    const add=element('button','song-add','+');add.type='button';add.title='เพิ่มเพลงเข้าคิว';add.setAttribute('aria-label','เพิ่มเพลง '+(song.title||'')+' เข้าคิว');
    add.addEventListener('click',e=>{e.stopPropagation();selectSong(i,false);addToQueue(song);clearSearchAfterChoice();});
    row.append(details,add);
    row.addEventListener('click',()=>{
      selectSong(i,false);
      chooseSearchSong(song);
    });
    fragment.append(row);
  });
  ui.songs.append(fragment);
  if(state.shown.length)ui.search.setAttribute('aria-activedescendant','song-option-'+state.selectedIndex);
  else ui.search.removeAttribute('aria-activedescendant');
}
function selectSong(i,scroll=true) {
  if (i<0||i>=state.shown.length) return;
  state.selectedIndex = i;
  for (const [j,row] of [...ui.songs.querySelectorAll('.song-item')].entries()) {
    row.classList.toggle('selected',i===j);row.setAttribute('aria-selected',String(i===j));
    if(i===j){ui.search.setAttribute('aria-activedescendant',row.id);if(scroll)row.scrollIntoView({block:'nearest'});}
  }
}

function playbackHasActiveIntent(){
  return !!state.loading||!!(
    state.current&&player.src&&!player.ended&&
    (!player.paused||(state.resumeAfterInterruption&&!state.userPaused))
  );
}
function chooseSearchSong(song){
  if(!song)return false;
  // A direct tap is a valuable playback gesture on iPhone/iPad: wake the
  // WebAudio/EQ graph immediately before any asynchronous Drive download.
  if(!playbackHasActiveIntent()){
    state.userPaused=false;
    state.resumeAfterInterruption=false;
    try{window.XStageResumeAudioGraph?.();}catch{}
    void playSong(song);
  }else{
    addToQueue(song);
  }
  clearSearchAfterChoice();
  return true;
}
function normalizeVoiceExact(value){
  return String(value??'')
    .normalize('NFKC')
    .toLocaleLowerCase('th')
    .replace(/[\s\p{P}\p{S}]+/gu,'')
    .trim();
}
function firstVoiceExactMatch(transcript){
  const first=state.shown[0];
  if(!first)return null;
  const heard=normalizeVoiceExact(transcript);
  if(!heard)return null;
  return [first.code,first.title,first.artist].some(value=>normalizeVoiceExact(value)===heard)?first:null;
}
// X-Stage medley means shuffled, continuous music from the private M4A
// catalog. Requested songs in the queue always take priority over random songs.
// The next file is prepared in memory, but songs are never cached permanently.
const MEDLEY_RECENT_LIMIT=10;
function medleyPool(){
  if(state.medleyPoolSource!==state.songs){
    state.medleyPoolSource=state.songs;
    state.medleyPool=state.songs.filter(playable);
  }
  return state.medleyPool;
}
function randomMedleySong(){
  const pool=medleyPool();
  if(!pool.length)return null;
  const recent=new Set([state.current,...(state.medleyRecent||[])]);
  let candidate=pool[Math.floor(Math.random()*pool.length)];
  // Avoid repeating the active or recently played song when the library allows.
  if(pool.length>recent.size){
    for(let i=0;i<35&&recent.has(candidate);i++)
      candidate=pool[Math.floor(Math.random()*pool.length)];
    if(recent.has(candidate))candidate=pool.find(song=>!recent.has(song))||candidate;
  }else if(pool.length>1&&candidate===state.current){
    for(let i=0;i<20&&candidate===state.current;i++)
      candidate=pool[Math.floor(Math.random()*pool.length)];
  }
  return candidate;
}
function nextMedleyCandidate(){
  if(state.queue.length)return state.queue[0];
  if(!state.medley)return null;
  if(!state.medleyUpcoming||state.medleyUpcoming===state.current)
    state.medleyUpcoming=randomMedleySong();
  return state.medleyUpcoming;
}
function setMedleyMode(enabled){
  state.medley=!!enabled;
  if(state.medley&&ui.repeat.checked){
    ui.repeat.checked=false;
    ui.repeat.dispatchEvent(new Event('change',{bubbles:true}));
  }
  if(!state.medley){
    state.medleyCache=null;state.medleyPrefetch=null;state.medleyUpcoming=null;
    player.volume=Number(ui.volume.value)/100;
  }
  setPlayStatus(state.medley
    ?'เปิดเมดเลย์สุ่มเพลงต่อเนื่อง · เพลงที่ขอในคิวจะเล่นก่อน'
    :'ปิดเมดเลย์สุ่มเพลง');
  window.dispatchEvent(new CustomEvent('xstage:medleychange',
    {detail:{enabled:state.medley}}));
  // Clicking the enabled mode starts a shuffled track immediately.
  // Queue requests are preserved and take priority after the current track.
  if(state.medley&&state.token){
    state.userStopped=false;
    const song=randomMedleySong();
    if(song){
      state.medleyUpcoming=null;
      playSong(song);
    }else setPlayStatus('ไม่มีเพลงที่พร้อมเล่นในคลัง');
  }
  return state.medley;
}
function setStageVisualScale(value){
  state.visualScale=Math.max(.7,Math.min(1.35,Math.round(Number(value)*100)/100));
  ui.stage.style.setProperty('--xstage-visual-scale',String(state.visualScale));
  saveUiPrefs({visualScale:state.visualScale});
  return state.visualScale;
}
function releaseQueuePreload(){
  clearTimeout(state.queuePreloadTimer);state.queuePreloadTimer=null;
  state.queuePreloadVersion++;
  state.queuePreload?.controller.abort();
  state.queuePreload=null;state.queuePrepared=null;
}
function scheduleQueuePreload(){
  clearTimeout(state.queuePreloadTimer);
  if(!state.token||!state.queue.length){releaseQueuePreload();return;}
  const song=state.queue[0],token=state.token;
  if(state.queuePrepared?.song===song&&state.queuePrepared.token===token)return;
  if(state.queuePrepared?.song!==song)state.queuePrepared=null;
  if(state.queuePreload?.song===song&&state.queuePreload.token===token)return;
  state.queuePreloadTimer=setTimeout(()=>{void preloadFirstQueueSong(song,token);},300);
}
async function preloadFirstQueueSong(song,token){
  if(state.queue[0]!==song||state.token!==token)return;
  const controller=new AbortController(),version=++state.queuePreloadVersion;
  state.queuePreload?.controller.abort();
  const task={song,token,controller};state.queuePreload=task;
  try{
    const [response,lyrics]=await Promise.all([
      privateFile(song.audio.fileId,token,{signal:controller.signal}),
      privateJson(song.lyrics.fileId,token,{signal:controller.signal})
    ]);
    const blob=await response.blob();
    if(version!==state.queuePreloadVersion||state.queue[0]!==song||state.token!==token||
       !blob.size||lyrics?.schemaVersion!==1||!Array.isArray(lyrics.lines))return;
    state.queuePrepared={song,token,blob,lyrics};
  }catch(error){if(error.name!=='AbortError')console.warn('X-Stage queue prefetch:',error.message);}
  finally{if(state.queuePreload===task)state.queuePreload=null;}
}
function prefetchMedleyNext(){
  if(!state.medley||!state.token||state.loading)return;
  const song=nextMedleyCandidate(),token=state.token;
  if(!song||state.medleyCache?.song===song||state.medleyPrefetch?.song===song)return;
  const task={song,token};state.medleyPrefetch=task;
  Promise.all([privateFile(song.audio.fileId,token),privateJson(song.lyrics.fileId,token)])
    .then(async ([response,lyrics])=>{
      const blob=await response.blob();
      if(state.medleyPrefetch!==task||!state.medley||state.token!==token||
          nextMedleyCandidate()!==song)return;
      if(!blob.size||lyrics?.schemaVersion!==1||!Array.isArray(lyrics.lines))return;
      state.medleyCache={song,blob,lyrics};
    })
    .catch(()=>{/* Playback falls back to loading the next song normally. */})
    .finally(()=>{if(state.medleyPrefetch===task)state.medleyPrefetch=null;});
}
function medleyTick(){
  if(!state.medley||state.loading||player.paused)return;
  const duration=player.duration;
  if(!Number.isFinite(duration)||duration<=0)return;
  // Keep the entire track; start the next random/queued song on the ended event.
  if(duration-player.currentTime<=25)prefetchMedleyNext();
}
function addToQueue(song) {
  if (!playable(song)) return;
  state.queue.push(song);renderQueue();scheduleQueuePreload();setPlayStatus(`เพิ่มเข้าคิว: ${song.title||song.code}`);
}
function renderQueue() {
  scheduleQueuePreload();
  ui.queue.replaceChildren();ui.queueCount.textContent=String(state.queue.length);
  ui.clearQueue.disabled=!state.queue.length;
  ui.next.disabled=!state.queue.length;
  ui.previous.disabled=!state.history.length;
  if (!state.queue.length) {ui.queue.append(element('li','empty-state','ยังไม่มีเพลงในคิว'));return;}
  state.queue.forEach((song,i)=>{
    const item=element('li','queue-item');
    const info=element('div','queue-info');info.append(element('strong','',song.title||'ไม่ระบุชื่อเพลง'),element('small','',song.artist||song.code||''));
    const buttons=element('div','queue-controls');
    const up=control('↑',()=>moveQueue(i,-1),'เลื่อนขึ้น');up.disabled=i===0;
    const down=control('↓',()=>moveQueue(i,1),'เลื่อนลง');down.disabled=i===state.queue.length-1;
    const remove=control('×',()=>{state.queue.splice(i,1);renderQueue();},'นำออกจากคิว');
    buttons.append(up,down,remove);
    const n=element('span','queue-number',String(i+1));
    item.append(n,info,buttons);item.title='คลิกสองครั้งเพื่อเล่นเพลงนี้ทันที';
    item.addEventListener('dblclick',e=>{if(e.target.closest('button'))return;state.queue.splice(i,1);renderQueue();playSong(song);});
    ui.queue.append(item);
  });
}
function moveQueue(index,step){const target=index+step;if(target<0||target>=state.queue.length)return;[state.queue[index],state.queue[target]]=[state.queue[target],state.queue[index]];renderQueue();}
function playNext(){
  const queued=state.queue.shift();
  const preparedQueued=queued&&state.queuePrepared?.song===queued?state.queuePrepared:null;
  if(preparedQueued)state.queuePrepared=null;
  scheduleQueuePreload();
  const song=queued||(state.medley?nextMedleyCandidate():null);
  if(!queued)state.medleyUpcoming=null;
  state.userStopped=false;
  if(state.medleyCache&&state.medleyCache.song!==song)state.medleyCache=null;
  renderQueue();
  if(song){
    if(state.medley){
      state.medleyRecent.push(song);
      if(state.medleyRecent.length>MEDLEY_RECENT_LIMIT)state.medleyRecent.shift();
    }
    playSong(song,{preloaded:preparedQueued});
  }else{
    clearIdleStage('จบเพลงแล้ว · ไม่มีเพลงรอในคิว');
  }
}
// Release the finished media and lyrics, not merely the transport label.
// Keeps the stage blank/idle even when the queue is empty and a user has
// selected the previous song in the search results.
function clearMediaSession(){
  if(!('mediaSession' in navigator))return;
  try{navigator.mediaSession.metadata=null;}catch{}
  try{navigator.mediaSession.playbackState='none';}catch{}
}
function syncMediaSessionMetadata(song){
  if(!('mediaSession' in navigator)||typeof MediaMetadata!=='function'||!song)return;
  try{
    navigator.mediaSession.metadata=new MediaMetadata({
      title:song.title||song.code||'X-Stage Karaoke',
      artist:song.artist||'X-Stage Karaoke',
      album:'X-Stage Karaoke Online',
      artwork:[
        {src:new URL('assets/xstage-app-icon-192.png',location.href).href,sizes:'192x192',type:'image/png'},
        {src:new URL('assets/xstage-apple-touch-icon.png',location.href).href,sizes:'180x180',type:'image/png'}
      ]
    });
  }catch(error){console.warn('X-Stage media metadata:',error?.message||error);}
}
function syncMediaSessionPosition(){
  if(!('mediaSession' in navigator)||typeof navigator.mediaSession.setPositionState!=='function')return;
  const duration=Number.isFinite(player.duration)?player.duration:Number(state.current?.duration||0);
  const position=Math.max(0,Math.min(duration||0,Number(player.currentTime)||0));
  if(!(duration>0))return;
  try{navigator.mediaSession.setPositionState({duration,playbackRate:player.playbackRate||1,position});}catch{}
}
function clearIdleStage(message){
  resetSongVideo();
  state.userStopped=true;
  state.requestId++;
  state.controller?.abort();
  state.controller=null;
  state.loading=false;
  player.pause();
  player.removeAttribute('src');
  player.load();
  if(state.objectUrl)URL.revokeObjectURL(state.objectUrl);
  state.objectUrl='';
  state.current=null;
  state.lyrics=null;
  clearPlaybackResumeState();
  clearMediaSession();
  state.medleyCache=null;
  state.medleyPrefetch=null;
  state.medleyUpcoming=null;
  releaseQueuePreload();
  ui.nowPlaying.textContent='ยังไม่มีเพลงกำลังเล่น';
  ui.nowArtist.textContent='';
  ui.stageCode.textContent='—';
  if(ui.songKey)ui.songKey.textContent='คีย์ —';
  ui.stage.classList.remove('playing');
  ui.stageIdle.hidden=false;
  if(typeof pen!=='undefined')pen.clearRect(0,0,ui.lyrics.width,ui.lyrics.height);
  setPlayStatus(message);
  updateTransport();
  if(state.updateAfterTrack&&state.updateAvailable){
    setTimeout(performAppUpdateReload,180);
  }
}
function stopSong(){
  state.userPaused=true;
  state.resumeAfterInterruption=false;
  if(state.medley)setMedleyMode(false);
  clearIdleStage('หยุดเล่นแล้ว');
}
function cancelCurrentSong(){
  if(!state.current&&!state.loading)return;
  if(state.queue.length||state.medley)playNext();
  else clearIdleStage('ยกเลิกเพลงแล้ว · คิวว่าง');
}
function restartCurrentSong(){
  if(!state.current||state.loading)return;
  try{player.currentTime=0;}catch{}
  player.play().catch(()=>setPlayStatus('เพลงพร้อมแล้ว · กด ▶ เพื่อเริ่มเล่น'));
  updateTransport();
}
async function resumePlaybackFromSystem(){
  if(state.loading)return false;
  if(!player.src){if(state.queue.length){playNext();return true;}return false;}
  state.userPaused=false;
  state.userStopped=false;
  state.resumeAfterInterruption=false;
  try{await window.XStageResumeAudioGraph?.();}catch{}
  try{await player.play();updateTransport();return true;}
  catch{state.resumeAfterInterruption=true;updateTransport();return false;}
}
function togglePlayback(){
  if(state.loading)return;
  if(!player.src){if(state.queue.length)playNext();else if(state.shown.length)playSong(state.shown[state.selectedIndex]);return;}
  if(player.paused)resumePlaybackFromSystem();
  else{state.userPaused=true;state.resumeAfterInterruption=false;player.pause();}
}

async function playSong(song,{remember=true,preloaded=null,resumeAt=0,autoplay=true}={}) {
  state.userStopped=false;
  if (!state.token) {setStatus('กรุณาเข้าสู่ระบบ Google ก่อนเล่นเพลง','error');return;}
  if (!playable(song)) {setPlayStatus('เพลงนี้ยังไม่มี M4A/JSON ที่พร้อมเล่น');return;}
  const request=++state.requestId;
  state.controller?.abort();const controller=new AbortController();state.controller=controller;
  const token=state.token;
  state.loading=true;updateTransport();setPlayStatus('กำลังโหลดเสียงและเนื้อร้องจาก Google Drive…');
  publishPlaybackStatus('loading',song,'กำลังเตรียมไฟล์เพลงจาก Google Drive');
  try {
    const prepared=(preloaded?.song===song&&preloaded.token===token?preloaded
      :state.queuePrepared?.song===song&&state.queuePrepared.token===token
      ?state.queuePrepared:state.medleyCache?.song===song&&state.token===token?state.medleyCache:null);
    if(prepared){if(state.queuePrepared===prepared)state.queuePrepared=null;if(state.medleyCache===prepared)state.medleyCache=null;}
    const [audio,lyrics]=prepared
      ? [prepared.blob,prepared.lyrics]
      : await boundedPlaybackTask(Promise.all([
          privateFile(song.audio.fileId,token,{signal:controller.signal}).then(r=>r.blob()),
          privateJson(song.lyrics.fileId,token,{signal:controller.signal})
        ]),90,'โหลดเพลงจาก Google Drive นานเกินไป กรุณาตรวจการเชื่อมต่อ');
    if (lyrics?.schemaVersion !== 1 || !Array.isArray(lyrics.lines)) throw Error('ไฟล์ Lyrics JSON ไม่รองรับ');
    if (request!==state.requestId||token!==state.token)return;
    if (!audio.size)throw Error('ไฟล์เสียงว่างเปล่า');
    const url=URL.createObjectURL(audio);
    if (remember && state.current)state.history.push(state.current);
    player.pause();if(state.objectUrl)URL.revokeObjectURL(state.objectUrl);
    state.objectUrl=url;state.current=song;state.lyrics=lyrics;
    resetSongVideo();
    if(getFileId(song.video))void loadSongVideo(song,request,token);
    syncMediaSessionMetadata(song);
    ui.nowPlaying.textContent=song.title||'ไม่ระบุชื่อเพลง';ui.nowArtist.textContent=song.artist||'ไม่ระบุศิลปิน';
    const musicalKey=String(song.key||song.musicKey||song.originalKey||song.keySignature||'').trim();
    ui.stageCode.textContent=song.code||'—';
    if(ui.songKey)ui.songKey.textContent='คีย์ '+(musicalKey||'—');
    ui.stage.classList.add('playing');ui.stageIdle.hidden=true;
    player.src=url;
    try{
      if('preservesPitch' in player)player.preservesPitch=true;
      if('mozPreservesPitch' in player)player.mozPreservesPitch=true;
      if('webkitPreservesPitch' in player)player.webkitPreservesPitch=true;
    }catch{}
    player.playbackRate=Number(ui.speed.value);player.loop=ui.repeat.checked;
    player.volume=Number(ui.volume.value)/100;
    const resumeTarget=Math.max(0,Number(resumeAt)||0);
    if(resumeTarget>0){
      const applyResumePosition=()=>{
        try{
          const d=Number.isFinite(player.duration)?player.duration:0;
          player.currentTime=d>0?Math.min(resumeTarget,Math.max(0,d-.25)):resumeTarget;
        }catch{}
      };
      if(player.readyState>=1)applyResumePosition();
      else player.addEventListener('loadedmetadata',applyResumePosition,{once:true});
    }
    state.loading=false;renderQueue();updateTransport();
    state.userPaused=!autoplay;state.resumeAfterInterruption=false;
    if(autoplay){
      try{await window.XStageResumeAudioGraph?.();}catch{}
      try{
        await boundedPlaybackTask(player.play(),18,'ทีวีไม่เริ่มเล่นเสียงภายใน 18 วินาที');
        if(request===state.requestId){
          setPlayStatus('กำลังเล่น · '+(song.title||song.code));
          publishPlaybackStatus('playing',song,'เริ่มเล่นเพลงบนจอแล้ว');
        }
      }catch(error){
        if(request===state.requestId){
          state.userPaused=true;state.resumeAfterInterruption=false;
          const reason=error?.name==='NotAllowedError'
            ?'Android TV ไม่อนุญาตให้เริ่มเล่นอัตโนมัติ · ลองกด ▶ บนรีโมท'
            :error?.name==='NotSupportedError'
            ?'Android TV ไม่รองรับรูปแบบไฟล์เสียงของเพลงนี้'
            :error?.message||'ไม่สามารถเริ่มเสียงบน TV ได้';
          setPlayStatus(reason);
          publishPlaybackStatus('blocked',song,reason);
        }
      }
    }else{
      player.pause();
      setPlayStatus('เพลงพร้อมเล่นต่อจากตำแหน่งเดิม');
      updateTransport();
    }
  }catch(e){if(request!==state.requestId || e.name==='AbortError')return;const message=e.message||'ไม่สามารถเล่นเพลงได้';setPlayStatus(message);publishPlaybackStatus('error',song,message);state.loading=false;updateTransport();}
  finally{if(request===state.requestId){state.loading=false;state.controller=null;updateTransport();}}
}
function updateTransport(){
  ui.stage.classList.toggle('loading',!!state.loading);
  const musicLoader=document.getElementById('music-loader');
  if(musicLoader)musicLoader.setAttribute('aria-hidden',String(!state.loading));
  ui.playPause.disabled=state.loading||(!state.current&&!state.queue.length&&!state.shown.length);
  ui.playPause.textContent=player.src&&!player.paused?'Ⅱ':'▶';
  const searchReady=!player.src&&!state.current&&!!state.shown.length;
  ui.playPause.title=searchReady?'เล่นเพลงที่เลือกจากผลค้นหา':'เล่น/พัก (F5)';
  ui.playPause.setAttribute('aria-label',searchReady?'เล่นเพลงที่เลือกจากผลค้นหา':'เล่นหรือพัก');
  ui.cancelCurrent.disabled=!state.current&&!state.loading;
  ui.restartCurrent.disabled=!state.current||state.loading;
  ui.previous.disabled=!state.history.length;
  ui.next.disabled=!state.queue.length;
  const duration=Number.isFinite(player.duration)?player.duration:Number(state.current?.duration||0);
  const hasLoadedSong=!!state.current;
  ui.elapsed.textContent=hasLoadedSong?timeLabel(player.currentTime):'--:--';
  ui.duration.textContent=hasLoadedSong?timeLabel(duration):'--:--';
  ui.seek.disabled=!(duration>0&&state.current);
  if (!ui.seek.matches(':active'))ui.seek.value=duration>0?String(Math.round((player.currentTime/duration)*1000)):'0';
  if('mediaSession' in navigator){
    try{navigator.mediaSession.playbackState=player.src?(player.paused?'paused':'playing'):'none';}catch{}
    syncMediaSessionPosition();
  }
}
function onSearchKey(e){
  if(e.key==='ArrowDown'){e.preventDefault();if(state.shown.length)selectSong(Math.min(state.selectedIndex+1,state.shown.length-1));}
  else if(e.key==='ArrowUp'){e.preventDefault();if(state.shown.length)selectSong(Math.max(0,state.selectedIndex-1));}
  else if(e.key==='Enter'){
    if(e.isComposing)return;
    e.preventDefault();
    renderSongs();
    updateTransport();
    if(!state.token){
      setStatus(ui.search.value.trim()
        ? 'เก็บคำค้นไว้แล้ว · เชื่อมต่อ Google Drive เพื่อค้นหาในคลังเพลงส่วนตัว'
        : 'พิมพ์ชื่อเพลง ศิลปิน หรือรหัสเพลงก่อนค้นหา');
      return;
    }
    const song=state.shown[state.selectedIndex];
    if(!song){
      ui.resultCount.textContent=ui.search.value.trim()?'ไม่พบเพลงที่ตรงกับคำค้น':'พิมพ์เพื่อค้นหาเพลง';
      return;
    }
    chooseSearchSong(song);
  }
}

function setupVoiceSearch(){
  const button=ui.voiceSearch;
  if(!button)return;
  const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
  const touchDevice=window.matchMedia?.('(pointer:coarse)').matches||navigator.maxTouchPoints>0;
  if(typeof Recognition!=='function'||!touchDevice){button.hidden=true;return;}
  button.hidden=false;

  const isiOS=/iPad|iPhone|iPod/.test(navigator.userAgent)||
    (navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1);
  let recognition=null,listening=false,sessionId=0,watchdog=0,stopFallback=0,voiceAutoChosen=false;
  const originalPlaceholder=ui.search.placeholder;

  const clearTimers=()=>{
    if(watchdog){clearTimeout(watchdog);watchdog=0;}
    if(stopFallback){clearTimeout(stopFallback);stopFallback=0;}
  };
  const setListening=active=>{
    listening=active;
    button.classList.toggle('listening',active);
    button.setAttribute('aria-pressed',String(active));
    button.title=active?'หยุดฟัง':'ค้นหาด้วยเสียง';
    button.setAttribute('aria-label',active?'หยุดค้นหาด้วยเสียง':'ค้นหาเพลงด้วยเสียง');
    ui.search.placeholder=active?'กำลังฟัง… พูดชื่อเพลงหรือศิลปิน':originalPlaceholder;
  };
  const showVoiceMessage=message=>{
    if(ui.resultCount)ui.resultCount.textContent=message;
  };
  const finishSession=(rec,id)=>{
    if(id!==sessionId)return;
    clearTimers();
    if(recognition===rec)recognition=null;
    setListening(false);
  };
  const abortStale=()=>{
    const old=recognition;
    recognition=null;
    clearTimers();
    setListening(false);
    if(old){try{old.abort();}catch{}}
  };
  const candidateScore=text=>{
    const heard=normalizeVoiceExact(text);
    if(!heard)return -1;
    let best=-1;
    for(const song of state.songs){
      const fields=[song.code,song.title,song.artist].map(normalizeVoiceExact).filter(Boolean);
      for(const field of fields){
        if(field===heard)best=Math.max(best,10000);
        else if(field.startsWith(heard)||heard.startsWith(field))best=Math.max(best,1800);
        else if(field.includes(heard)||heard.includes(field))best=Math.max(best,900);
      }
      if(best===10000)break;
    }
    return best;
  };
  const chooseBestTranscript=event=>{
    const candidates=[];
    const results=event.results||[];
    for(let i=0;i<results.length;i++){
      const result=results[i];
      for(let j=0;j<Math.min(result.length||0,5);j++){
        const text=String(result[j]?.transcript||'').trim();
        if(text)candidates.push({text,confidence:Number(result[j]?.confidence)||0});
      }
    }
    if(!candidates.length)return '';
    candidates.sort((a,b)=>{
      const diff=candidateScore(b.text)-candidateScore(a.text);
      return diff||b.confidence-a.confidence;
    });
    return candidates[0].text;
  };
  const exactSongFor=text=>{
    const heard=normalizeVoiceExact(text);
    if(!heard)return null;
    return state.songs.find(song=>
      [song.code,song.title,song.artist].some(value=>normalizeVoiceExact(value)===heard)
    )||null;
  };

  button.addEventListener('click',()=>{
    if(ui.search.disabled)return;
    if(listening&&recognition){
      const rec=recognition,id=sessionId;
      try{rec.stop();}catch{finishSession(rec,id);return;}
      stopFallback=setTimeout(()=>{
        if(id!==sessionId)return;
        try{rec.abort();}catch{}
        finishSession(rec,id);
      },900);
      return;
    }

    abortStale();
    const id=++sessionId;
    voiceAutoChosen=false;
    let rec;
    try{
      rec=new Recognition();
      recognition=rec;
      rec.lang='th-TH';
      rec.continuous=false;
      // Safari/iPad is materially more reliable with final results only.
      rec.interimResults=!isiOS;
      rec.maxAlternatives=5;

      rec.onstart=()=>{
        if(id!==sessionId)return;
        setListening(true);
        showVoiceMessage('กำลังฟัง… พูดชื่อเพลง ศิลปิน หรือรหัสเพลง');
        if(watchdog){clearTimeout(watchdog);watchdog=0;}
        watchdog=setTimeout(()=>{
          if(id!==sessionId||recognition!==rec)return;
          try{rec.abort();}catch{}
          finishSession(rec,id);
          showVoiceMessage('แตะไมค์เพื่อค้นหาด้วยเสียงอีกครั้ง');
        },12000);
      };
      rec.onresult=event=>{
        if(id!==sessionId)return;
        const transcript=chooseBestTranscript(event);
        if(!transcript)return;
        ui.search.value=transcript;
        state.selectedIndex=0;
        ui.search.dispatchEvent(new Event('input',{bubbles:true}));
        setLiveSearchExpanded(true);

        let final=true;
        for(let i=0;i<(event.results?.length||0);i++){
          if(!event.results[i]?.isFinal){final=false;break;}
        }
        if(final&&!voiceAutoChosen){
          const exact=exactSongFor(transcript);
          if(exact){
            voiceAutoChosen=true;
            chooseSearchSong(exact);
            try{rec.stop();}catch{}
          }
        }
      };
      rec.onnomatch=()=>{
        if(id!==sessionId)return;
        showVoiceMessage('ไม่พบคำที่ตรง · แตะไมค์แล้วพูดใหม่ได้ทันที');
      };
      rec.onerror=event=>{
        if(id!==sessionId)return;
        const code=String(event?.error||'');
        finishSession(rec,id);
        if(code==='aborted')return;
        if(code==='no-speech')showVoiceMessage('ไม่ได้ยินเสียง · แตะไมค์แล้วลองพูดอีกครั้ง');
        else if(code==='not-allowed'||code==='service-not-allowed')showVoiceMessage('ไม่สามารถใช้ไมโครโฟนได้ · กรุณาอนุญาตไมโครโฟน/เปิด Siri แล้วลองใหม่');
        else if(code==='audio-capture')showVoiceMessage('ไม่พบไมโครโฟนที่พร้อมใช้งาน');
        else if(code==='network')showVoiceMessage('ค้นหาด้วยเสียงเชื่อมต่อไม่สำเร็จ · ตรวจอินเทอร์เน็ตแล้วลองใหม่');
        else showVoiceMessage('ค้นหาด้วยเสียงไม่สำเร็จ · แตะไมค์เพื่อลองใหม่');
      };
      rec.onend=()=>finishSession(rec,id);

      // If Safari never fires onstart, release the stale session instead of
      // leaving the microphone button stuck for the next attempt.
      watchdog=setTimeout(()=>{
        if(id!==sessionId||recognition!==rec||listening)return;
        try{rec.abort();}catch{}
        finishSession(rec,id);
        showVoiceMessage('ไมโครโฟนยังไม่เริ่ม · แตะอีกครั้งเพื่อค้นหา');
      },2800);
      rec.start();
    }catch(error){
      if(rec){try{rec.abort();}catch{}}
      finishSession(rec,id);
      showVoiceMessage('อุปกรณ์นี้ยังไม่พร้อมใช้การค้นหาด้วยเสียง · แตะเพื่อลองใหม่');
      console.warn('X-Stage voice search:',error?.message||error);
    }
  });

  document.addEventListener('visibilitychange',()=>{
    if(document.hidden&&recognition)abortStale();
  });
}

setupVoiceSearch();

// Draw timed karaoke lyrics on the same stage as the Windows player's background.
const pen=ui.lyrics.getContext('2d');
const graphemeCount = s => {
  if (typeof Intl.Segmenter === 'function') return [...new Intl.Segmenter('th',{granularity:'grapheme'}).segment(s)].length;
  return Array.from(s).length;
};
function resizeCanvas(){
  const r=ui.lyrics.getBoundingClientRect();
  if(!r.width||!r.height)return {w:0,h:0};
  const dpr=Math.min(window.devicePixelRatio||1,2),w=Math.round(r.width*dpr),h=Math.round(r.height*dpr);
  if(ui.lyrics.width!==w||ui.lyrics.height!==h){ui.lyrics.width=w;ui.lyrics.height=h;}
  return {w,h};
}
function drawLine(text,y,maxWidth,fontSize,fill,progress=null,centerX=ui.lyrics.width/2){
  if(!text)return;
  const w=ui.lyrics.width;
  let sz=fontSize;
  do {pen.font=`900 ${Math.round(sz)}px "Leelawadee UI","Noto Sans Thai",Tahoma,sans-serif`;if(pen.measureText(text).width<=maxWidth)break;sz*=.92;}while(sz>14);
  pen.textAlign='center';pen.textBaseline='middle';
  pen.lineWidth=Math.max(3,sz*.13);pen.strokeStyle='#010613';pen.lineJoin='round';pen.shadowColor='#000';pen.shadowBlur=6;
  // Canvas maxWidth keeps the entire text inside the reserved region even
  // when its Thai glyphs cannot shrink further (e.g. QR beside lyrics).
  const displayedWidth=Math.min(pen.measureText(text).width,maxWidth);
  pen.strokeText(text,centerX,y,maxWidth);pen.shadowBlur=0;pen.fillStyle=fill;pen.fillText(text,centerX,y,maxWidth);
  if(progress!==null){
    pen.save();pen.beginPath();
    // A precise MIDI/CUR sweep uses the measured display width of each
    // timed syllable, not raw character count (Thai combining marks have
    // variable / zero painted width). LRC-only songs use a clearly
    // approximate line-duration wipe, never invented syllable timestamps.
    const clipWidth=Math.max(0,Math.min(1,progress))*displayedWidth;
    pen.rect(centerX-displayedWidth/2-1,y-sz*.8,clipWidth+1,sz*1.65);
    pen.clip();pen.fillStyle='#ffd76a';pen.fillText(text,centerX,y,maxWidth);pen.restore();
  }
}
function lineProgress(line,when){
  const start=Number(line.startTime)||0;
  const end=Number(line.endTime)||start+1;
  const clamp=x=>Math.max(0,Math.min(1,x));
  const fallback=clamp((when-start)/Math.max(.01,end-start));
  const units=Array.isArray(line.syllables)?line.syllables:[];
  if(!units.length)return fallback;
  const pieces=units.map(u=>String(u.text||''));
  const text=String(line.text||'');
  if(pieces.join('')!==text)return fallback;
  const times=units.map(u=>Number(u.start));
  if(times.some((value,i)=>!Number.isFinite(value)||value<0||
      (i&&value<times[i-1]-.001)))return fallback;
  // If a cursor marks an entire line at one instant, the recording contains
  // no usable intra-line timing. Sweep that line evenly rather than jumping.
  if(times.length===1||times.every(t=>Math.abs(t-times[0])<.001))
    return fallback;
  const totalWidth=pen.measureText(text).width;
  if(!totalWidth)return fallback;
  // Measure each prefix, not glyph count: Thai vowels and tone marks are not
  // equally wide, and some occupy no horizontal advance.
  const widths=[0];let prefix='';
  for(const part of pieces){
    prefix+=part;
    widths.push(Math.max(widths[widths.length-1],
      pen.measureText(prefix).width));
  }
  const measured=widths[widths.length-1];
  if(!measured)return fallback;
  let painted=0;
  const distinct=[];
  for(let i=0;i<times.length;i++)
    if(i===0||times[i]>times[i-1]+.001)distinct.push(times[i]);
  const gaps=distinct.slice(1).map((t,i)=>t-distinct[i])
    .filter(d=>d>.001).sort((a,b)=>a-b);
  const cadence=gaps.length?gaps[Math.floor(gaps.length/2)]:.45;
  for(let i=0;i<units.length;){
    let j=i+1;
    while(j<units.length&&Math.abs(times[j]-times[i])<=.001)j++;
    const from=times[i],next=j<units.length?times[j]:NaN;
    let finish;
    if(j-i>1){
      // Multiple CUR/KAR letters at the same tick used to flash instantly.
      // Paint their combined displayed width over the next available beat.
      // If the next cue is too close to render, use the safe line fallback.
      finish=Number.isFinite(next)?next:Math.min(end,from+Math.max(.12,
        Math.min(1.2,cadence)));
      if(finish-from<.04*(j-i))return fallback;
    }else{
      const duration=Number(units[i].duration);
      const derived=Number.isFinite(next)?Math.max(.01,next-from):
        Math.max(.15,Math.min(1.25,cadence));
      // The last syllable must not creep across a lengthy instrumental rest
      // merely because endTime equals the NEXT lyric line's start.
      const limit=Number.isFinite(next)?Math.max(.04,next-from):
        Math.max(.15,Math.min(1.25,cadence*1.25));
      finish=from+(Number.isFinite(duration)&&duration>0
        ? Math.min(duration,limit):Math.min(derived,limit));
    }
    const fraction=clamp((when-from)/Math.max(.01,finish-from));
    painted+=(widths[j]-widths[i])*fraction;
    i=j;
  }
  return clamp(painted/measured);
}
function drawLyrics(){
  try {
    const {w,h}=resizeCanvas();
    if(w&&h){pen.clearRect(0,0,w,h);
      if(state.lyrics?.lines?.length && state.current){
        const when=Math.max(0,player.currentTime+(Number(state.lyrics.audioOffsetMs)||0)/1000);
        const lines=state.lyrics.lines;
        let idx=-1;
        for(let i=0;i<lines.length;i++){if(Number(lines[i].startTime)<=when)idx=i;else break;}
        const fontSize=Math.min(76,w*.062,h*.14);
        // Keep both lyric lines above the integrated transport/virtual keyboard.
        const density=Math.min(window.devicePixelRatio||1,2);
        const transportHeight=ui.stage.querySelector('.transport-panel')?.getBoundingClientRect().height||0;
        const keyboard=ui.stage.querySelector('#virtual-keyboard');
        const keyboardHeight=keyboard&&!keyboard.hidden?keyboard.getBoundingClientRect().height+7:0;
        const usableBottom=h-(transportHeight+keyboardHeight+12)*density;
        // Lift both karaoke rows by about one full lyric line while preserving spacing.
        const lyricLift=fontSize*1.45;
        let nextY=Math.max(h*.22,Math.min(h*.83,usableBottom-fontSize*.8)-lyricLift);
        let currentY=Math.max(h*.10,Math.min(h*.66,nextY-fontSize*1.45));
        // WEB lyrics overlay the banner instead of shrinking to avoid it.
        // Retain transport and QR collision handling on both platforms.
        let lyricCenter=w/2,lyricWidth=w*.93,lyricFont=fontSize*state.visualScale;

        // Keep the stage identity stationary while lyrics paint above its dimmed sign.
        // Only reserve logo space if lyrics are being drawn without an active song stage.
        if(matchMedia('(orientation: landscape)').matches && !ui.stage.classList.contains('stage-hero-hidden')){
          const canvasBox=ui.lyrics.getBoundingClientRect();
          const hero=ui.stage.querySelector('.stage-hero');
          if(hero){
            const heroBox=hero.getBoundingClientRect();
            const scale=w/Math.max(1,canvasBox.width);
            const heroBottom=(heroBox.bottom-canvasBox.top)*scale;
            const gap=Math.max(10*density,fontSize*.22);
            let minCurrentY=heroBottom+gap+lyricFont*.72;
            let requiredNextY=minCurrentY+lyricFont*1.35;
            const maxNextY=usableBottom-lyricFont*.72;
            if(requiredNextY>maxNextY){
              const available=Math.max(28,usableBottom-(heroBottom+gap));
              lyricFont=Math.min(lyricFont,Math.max(18,available/2.75));
              minCurrentY=heroBottom+gap+lyricFont*.7;
              requiredNextY=minCurrentY+lyricFont*1.28;
            }
            if(currentY<minCurrentY){
              currentY=minCurrentY;
              nextY=Math.max(nextY,requiredNextY);
            }
            const finalMaxNext=usableBottom-lyricFont*.68;
            if(nextY>finalMaxNext){
              nextY=finalMaxNext;
              currentY=Math.min(currentY,nextY-lyricFont*1.28);
            }
          }
        }
        const qrPanel=ui.stage.querySelector('#remote-pair-panel');
        if(qrPanel&&!qrPanel.hidden){
          const canvasBox=ui.lyrics.getBoundingClientRect();
          const qrBox=qrPanel.getBoundingClientRect();
          const scale=w/Math.max(1,canvasBox.width);
          const qrTop=(qrBox.top-canvasBox.top)*scale;
          const qrBottom=(qrBox.bottom-canvasBox.top)*scale;
          if(qrTop<nextY+fontSize*.8 && qrBottom>currentY-fontSize*.8){
            // Prefer drawing below QR; on short landscape screens reserve the space to its left.
            const afterCurrent=qrBottom+fontSize*.95;
            const afterNext=afterCurrent+fontSize*1.5;
            if(afterNext+fontSize*.7<usableBottom){
              currentY=afterCurrent;nextY=afterNext;
            }else{
              const openWidth=Math.max(0,(qrBox.left-canvasBox.left)*scale-14*scale);
              if(openWidth>w*.28){
                lyricCenter=openWidth/2;
                lyricWidth=openWidth*.94;
                lyricFont=Math.min(fontSize,Math.max(12,openWidth*.075));
              }
            }
          }
        }
        if(idx<0){drawLine(String(lines[0].text||''),Math.min(h*.72,currentY),lyricWidth,lyricFont,'#bfe2ef',null,lyricCenter);}
        else{
          const current=lines[idx];
           // Match measurement font to the rendered line before evaluating
           // per-syllable sweep distances.
           let sweepFont=lyricFont;
           do {
             pen.font=`900 ${Math.round(sweepFont)}px "Leelawadee UI","Noto Sans Thai",Tahoma,sans-serif`;
             if(pen.measureText(String(current.text||'')).width<=lyricWidth)break;
             sweepFont*=.92;
           }while(sweepFont>14);
           drawLine(String(current.text||''),currentY,lyricWidth,lyricFont,
             '#ecf7ff',lineProgress(current,when),lyricCenter);
          const next=lines[idx+1];if(next)drawLine(String(next.text||''),nextY,lyricWidth,lyricFont*.88,'#b7d2e0',null,lyricCenter);
        }
      }
    }
  }catch(e){/* Preserve audio playback even if a malformed lyric line cannot draw. */}
  requestAnimationFrame(drawLyrics);
}

// The stage clock runs independently in index.html.
ui.librarySelect?.addEventListener('change',()=>{
  const rootId=String(ui.librarySelect.value||'');
  if(!rootId||!state.accountSub)return;
  savePreferredLibraryRoot(state.accountSub,rootId);
  if(rootId===String(state.libraryRootId||''))return;
  const target=state.availableLibraries.find(item=>String(item.id)===rootId);
  const targetLabel=target?libraryLabel(target):'คลังที่เลือก';
  const busy=!!(state.loading||state.current&&player.src&&!player.ended&&!player.paused);
  if(busy){
    ui.librarySelect.value=String(state.libraryRootId||'');
    ui.libraryState.textContent='เลือก '+targetLabel+' ไว้แล้ว · จะใช้เมื่อเปิด/รีเฟรชครั้งถัดไป';
    setPlayStatus('บันทึกการเปลี่ยนคลังแล้ว · เพลงปัจจุบันเล่นต่อโดยไม่ถูกตัด');
    return;
  }
  clearPlaybackResumeState();
  setStatus('กำลังเปลี่ยนไปยัง '+targetLabel+'…','success');
  location.reload();
});
function androidTvNativeBridgeReady(){
  try{return !!(window.XStageAndroid&&typeof window.XStageAndroid.requestGoogleLogin==='function');}
  catch{return false;}
}
function isNativeAndroidTvMode(){
  try{
    if(androidTvNativeBridgeReady()&&typeof window.XStageAndroid.isAndroidTvApp==='function'){
      return !!window.XStageAndroid.isAndroidTvApp();
    }
  }catch{}
  try{return new URLSearchParams(location.search).get('source')==='android-tv';}
  catch{return false;}
}
function setupNativeAndroidTvUi(){
  if(!isNativeAndroidTvMode())return;
  document.body.classList.add('xstage-native-tv');
  ui.stage?.classList.add('tv-display-only');

  // Android TV is a pure display surface after sign-in.
  // All search, queue and advanced controls live on the mobile remote.
  for(const id of [
    'mobile-stage-menu','mobile-menu-toggle','stage-tools-toggle','fullscreen',
    'desktop-update-version','logout','voice-search','toggle-keyboard',
    'virtual-keyboard','pc-search','stage-queue-panel','remote-request-panel'
  ]){
    const el=document.getElementById(id);
    if(el)el.hidden=true;
  }
  const queue=document.getElementById('stage-queue-toggle');
  if(queue){queue.tabIndex=-1;queue.hidden=true;queue.style.pointerEvents='none';}
}

let androidTvVerifiedConnectionSub='';
function setAndroidTvStageAccess(granted,accountSub=''){
  if(!androidTvNativeBridgeReady())return;
  if(granted){
    if(accountSub)androidTvVerifiedConnectionSub=accountSub;
    document.documentElement.classList.remove('xstage-native-auth-pending');
    document.body.classList.remove('xstage-native-auth-pending');
    try{window.XStageAndroid.onLoginScreenReady?.();}catch{}
  }else{
    document.documentElement.classList.add('xstage-native-auth-pending');
    document.body.classList.add('xstage-native-auth-pending');
  }
}
function notifyAndroidTvLoginReady(){
  try{window.XStageAndroid?.onLoginScreenReady?.();}catch{}
}
// Google device-code requests have a bounded wait. Missing watchdog helpers
// previously threw ReferenceError before the QR callback could render.
let androidTvLoginWatchdog=0;
let androidTvLoginInProgress=false;
function clearAndroidTvLoginWatchdog(){
  if(androidTvLoginWatchdog){clearTimeout(androidTvLoginWatchdog);androidTvLoginWatchdog=0;}
}
function armAndroidTvLoginWatchdog(){
  clearAndroidTvLoginWatchdog();
  androidTvLoginWatchdog=setTimeout(()=>{
    androidTvLoginWatchdog=0;
    if(androidTvLoginCancelled||state.token||!androidTvLoginInProgress)return;
    androidTvLoginInProgress=false;
    try{window.XStageAndroid?.cancelGoogleLogin?.();}catch{}
    window.XStageAndroidAuthError?.('Google ยังไม่ส่งรหัสเข้าสู่ระบบภายใน 30 วินาที · ตรวจอินเทอร์เน็ตแล้วกด ลองใหม่');
  },30000);
}
function androidTvAuthPanel(){
  let panel=$('android-tv-auth-panel');
  if(panel)return panel;
  panel=document.createElement('section');
  panel.id='android-tv-auth-panel';
  panel.className='android-tv-auth-panel';
  panel.hidden=true;
  panel.setAttribute('role','dialog');
  panel.setAttribute('aria-modal','true');
  panel.setAttribute('aria-labelledby','android-tv-auth-title');
  panel.innerHTML='<div class="android-tv-auth-box">'+
    '<img class="android-tv-auth-brand" src="assets/xstage-stage-logo.png?v=1093" width="2048" height="682" alt="X-Stage Karaoke Online">'+
    '<span class="android-tv-auth-kicker">X-STAGE ANDROID · <b id="android-tv-auth-version">กำลังอ่านรุ่น…</b></span>'+
    '<h2 id="android-tv-auth-title">เข้าสู่ระบบ Google ผ่านมือถือ</h2>'+
    '<p class="android-tv-auth-copy">สแกน QR ด้วยมือถือหรืออุปกรณ์อื่น แล้วกรอกรหัสที่แสดง</p>'+
    '<div class="android-tv-auth-grid">'+
      '<div class="android-tv-auth-qr-wrap"><canvas id="android-tv-auth-qr" width="248" height="248" hidden aria-label="QR สำหรับเปิดหน้า Google Device Login"></canvas><div id="android-tv-auth-qr-wait">กำลังสร้าง QR…</div></div>'+
      '<div class="android-tv-auth-details">'+
        '<div id="android-tv-auth-url" class="android-tv-auth-url">https://www.google.com/device</div>'+
        '<div class="android-tv-auth-code-label">รหัสเข้าสู่ระบบ</div>'+
        '<div id="android-tv-auth-code" class="android-tv-auth-code">----</div>'+
        '<div id="android-tv-auth-status" class="android-tv-auth-status">กำลังเตรียมรหัส…</div>'+
      '</div>'+
    '</div>'+
    '<div class="android-tv-auth-actions"><button id="android-tv-auth-retry" type="button" hidden>ลองใหม่</button><button id="android-tv-auth-cancel" type="button">ยกเลิก</button></div>'+
    '<small>ไม่ต้องกรอกรหัสผ่าน Google ใน X-Stage · การอนุญาตเกิดบนหน้า Google ที่ปลอดภัย</small>'+
    '</div>';
  document.body.append(panel);
  // Native APK requires sign-in before showing a stage. BACK exits the app.
  if(androidTvNativeBridgeReady())$('android-tv-auth-cancel').hidden=true;
  try{
    const rawVersion=String(window.XStageAndroid?.getAppVersion?.()||window.XSTAGE_RELEASE?.version||'').replace(/-debug$/,'');
    const build=Number(window.XStageAndroid?.getAppBuild?.()||window.XSTAGE_RELEASE?.build||0);
    const versionText=$('android-tv-auth-version');
    if(versionText)versionText.textContent=(rawVersion?'v'+rawVersion:'ไม่ทราบรุ่น')+(build?' · Build '+build:'');
  }catch{
    const versionText=$('android-tv-auth-version');
    if(versionText)versionText.textContent='v'+String(window.XSTAGE_RELEASE?.version||'');
  }
  $('android-tv-auth-retry')?.addEventListener('click',()=>{
    $('android-tv-auth-retry').hidden=true;
    startAndroidTvDeviceLogin(true);
  });
  $('android-tv-auth-cancel')?.addEventListener('click',()=>{
    // Cancel the native device-code poll as well as the UI. Do not automatically
    // reopen the login dialog until the user explicitly requests sign-in again.
    androidTvLoginCancelled=true;
    androidTvLoginInProgress=false;
    androidTvRefreshingSession=false;
    clearAndroidTvLoginWatchdog();
    try{window.XStageAndroid?.cancelGoogleLogin?.();}catch{}
    panel.hidden=true;
    ui.login.disabled=ui.gateLogin.disabled=false;
    setStatus('ยกเลิกการเข้าสู่ระบบแล้ว · กดเข้าสู่ระบบ Google เมื่อต้องการเปิดคลังเพลง');
    try{ui.gateLogin?.focus?.();}catch{}
    if(document.body.classList.contains('xstage-native-tv')&&ui.gate?.hidden){
      // Without the welcome gate, physical MENU/OK can reopen Google login.
      window.XStageTvOpenMenu?.();
    }
  });
  return panel;
}
let androidTvQrLibraryPromise=null;
function ensureAndroidTvQrLibrary(){
  if(typeof QRCode!=='undefined')return Promise.resolve();
  if(androidTvQrLibraryPromise)return androidTvQrLibraryPromise;
  // Both the native Google login and mobile-remote QR must share a single
  // loader. Replacing each other's <script> caused intermittent endless QR.
  androidTvQrLibraryPromise=new Promise((resolve,reject)=>{
    const stale=document.getElementById('xstage-qrcode');
    if(stale)stale.remove();
    const script=document.createElement('script');
    script.id='xstage-qrcode';
    script.src='./assets/vendor/qrcode.min.js?v=1095';
    script.async=true;
    let done=false;
    const finish=error=>{
      if(done)return;
      done=true;clearTimeout(timer);script.onload=null;script.onerror=null;
      if(error){script.remove();reject(error);}else resolve();
    };
    const timer=setTimeout(()=>finish(Error('QR library timeout')),10000);
    script.onload=()=>finish(typeof QRCode!=='undefined'?null:Error('QR library unavailable'));
    script.onerror=()=>finish(Error('QR library unavailable'));
    document.head.append(script);
  }).catch(error=>{androidTvQrLibraryPromise=null;throw error;});
  return androidTvQrLibraryPromise;
}
window.XStageEnsureQrLibrary=ensureAndroidTvQrLibrary;
async function renderAndroidTvLoginQr(url){
  const canvas=$('android-tv-auth-qr');
  const wait=$('android-tv-auth-qr-wait');
  if(!canvas)return;
  canvas.hidden=true;
  if(wait){wait.hidden=false;wait.textContent='กำลังสร้าง QR…';}
  try{
    await ensureAndroidTvQrLibrary();
    canvas.width=248;canvas.height=248;
    await QRCode.toCanvas(canvas,String(url||'https://www.google.com/device'),{
      width:248,margin:2,errorCorrectionLevel:'M',
      color:{dark:'#07131f',light:'#ffffff'}
    });
    canvas.hidden=false;
    if(wait)wait.hidden=true;
  }catch{
    if(wait){wait.hidden=false;wait.textContent='เปิด google.com/device บนมือถือ แล้วกรอกรหัสด้านขวา';}
  }
}
function showAndroidTvAuthPanel(){
  const panel=androidTvAuthPanel();
  setAndroidTvStageAccess(false);
  panel.hidden=false;
  notifyAndroidTvLoginReady();
  $('android-tv-auth-code').textContent='----';
  $('android-tv-auth-status').textContent='กำลังเตรียมรหัส…';
  $('android-tv-auth-retry').hidden=true;
  const qr=$('android-tv-auth-qr');if(qr)qr.hidden=true;
  const qrWait=$('android-tv-auth-qr-wait');if(qrWait){qrWait.hidden=false;qrWait.textContent='กำลังขอรหัสจาก Google…';}
  setTimeout(()=>$('android-tv-auth-cancel')?.focus?.(),20);
}
function hideAndroidTvAuthPanel(){
  const panel=$('android-tv-auth-panel');
  if(panel)panel.hidden=true;
}
window.XStageAndroidDeviceCode=payload=>{
  if(androidTvLoginCancelled)return;
  clearAndroidTvLoginWatchdog();
  let data={};
  try{data=typeof payload==='string'?JSON.parse(payload):payload||{};}catch{}
  const panel=androidTvAuthPanel();
  panel.hidden=false;
  const verificationUrl=String(data.verification_url||'https://www.google.com/device');
  $('android-tv-auth-url').textContent=verificationUrl;
  $('android-tv-auth-code').textContent=String(data.user_code||'----');
  $('android-tv-auth-status').textContent='สแกน QR และอนุญาตบนมือถือ…';
  $('android-tv-auth-retry').hidden=true;
  void renderAndroidTvLoginQr(verificationUrl);
};
window.XStageAndroidAuthStatus=message=>{
  if(androidTvLoginCancelled)return;
  const status=$('android-tv-auth-status');
  if(status)status.textContent=String(message||'กำลังเชื่อมต่อ Google…');
  setStatus(String(message||'กำลังเชื่อมต่อ Google…'));
};
window.XStageAndroidAuthError=message=>{
  if(androidTvLoginCancelled)return;
  clearAndroidTvLoginWatchdog();
  androidTvLoginInProgress=false;
  androidTvRefreshingSession=false;
  const text=String(message||'เข้าสู่ระบบ Google ไม่สำเร็จ');
  const panel=androidTvAuthPanel();
  panel.hidden=false;
  const missingOauth=text.includes('ยังไม่ได้ตั้งค่า Google OAuth')||text.includes('XSTAGE_TV_OAUTH_CLIENT_ID');
  if(missingOauth){
    const qr=$('android-tv-auth-qr');if(qr)qr.hidden=true;
    const wait=$('android-tv-auth-qr-wait');
    if(wait){wait.hidden=false;wait.textContent='ยังไม่ได้ตั้งค่า Google OAuth สำหรับ APK รุ่นนี้';}
    $('android-tv-auth-url').textContent='ต้องตั้งค่า OAuth Client สำหรับ TV / Limited Input';
    $('android-tv-auth-code').textContent='CONFIG';
    $('android-tv-auth-status').textContent='ผู้ดูแลต้องเพิ่ม GitHub Secrets: XSTAGE_TV_OAUTH_CLIENT_ID และ XSTAGE_TV_OAUTH_CLIENT_SECRET แล้ว Build APK ใหม่';
    $('android-tv-auth-retry').hidden=true;
  }else{
    $('android-tv-auth-status').textContent=text;
    $('android-tv-auth-retry').hidden=false;
  }
  ui.login.disabled=ui.gateLogin.disabled=false;
  setStatus(text,'error');
};
window.XStageReceiveAndroidToken=async(token,expiresIn=3600)=>{
  if(androidTvLoginCancelled)return;
  clearAndroidTvLoginWatchdog();
  if(!token)return;
  const existingSub=state.token&&state.accountSub?state.accountSub:'';
  // Silent background refresh must never place a full-screen dialog on lyrics.
  if(!existingSub){
    androidTvAuthPanel().hidden=false;
    $('android-tv-auth-status').textContent='กำลังตรวจสอบบัญชีและสิทธิ์ Google Drive…';
  }
  ui.login.disabled=ui.gateLogin.disabled=true;
  setStatus('มือถืออนุญาตแล้ว · กำลังเปิด Google Drive…','success');
  const authId=++state.authId;
  const safeExpires=Math.max(60,Math.min(3600,Number(expiresIn)||3600));
  const expiresAt=Date.now()+safeExpires*1000;
  savePendingAuth(token,expiresAt);
  try{
    await openDrive(token,authId,expiresAt,existingSub);
    if(authId===state.authId&&state.token){
      if(!document.documentElement.classList.contains('xstage-native-auth-pending'))hideAndroidTvAuthPanel();
      androidTvRefreshingSession=false;
    }
  }catch(error){
    if(authId===state.authId){
      if(existingSub&&state.token){
        // Renewal may fail while Google is briefly offline. Keep the existing
        // audio and queue; retry via the native refresh-token watchdog.
        clearPendingAuth();
      }else{
        setAndroidTvStageAccess(false);
        clearActiveAuth();resetPrivate({keepAuth:true});
      }
      window.XStageAndroidAuthError(error?.message||'เปิด Google Drive ไม่สำเร็จ');
    }
  }finally{
    androidTvLoginInProgress=false;
    if(authId===state.authId)ui.login.disabled=ui.gateLogin.disabled=false;
  }
};
window.XStageAndroidSignedOut=()=>{
  clearAndroidTvLoginWatchdog();
  androidTvVerifiedConnectionSub='';
  setAndroidTvStageAccess(false);
  if(state.token)resetPrivate({keepAuth:false});
  if(androidTvNativeBridgeReady())startAndroidTvDeviceLogin(true);
  setStatus('ออกจากระบบ Google ในแอป Android แล้ว');
};
function androidTvUpdatePanel(){
  let panel=$('android-tv-update-panel');
  if(panel)return panel;
  panel=document.createElement('section');
  panel.id='android-tv-update-panel';
  panel.className='android-tv-update-panel';
  panel.hidden=true;
  panel.setAttribute('role','dialog');
  panel.setAttribute('aria-modal','true');
  panel.setAttribute('aria-labelledby','android-tv-update-title');
  panel.innerHTML='<div class="android-tv-update-box">'+
    '<span class="android-tv-update-kicker">X-STAGE ANDROID UPDATE</span>'+
    '<h2 id="android-tv-update-title">มี X-Stage เวอร์ชันใหม่</h2>'+
    '<p id="android-tv-update-version" class="android-tv-update-version"></p>'+
    '<p id="android-tv-update-status" class="android-tv-update-status">พร้อมอัปเดต</p>'+
    '<div class="android-tv-update-actions">'+
      '<button id="android-tv-update-now" type="button">อัปเดตตอนนี้</button>'+
      '<button id="android-tv-update-later" type="button">ภายหลัง</button>'+
    '</div>'+
    '<small>ระบบจะดาวน์โหลด APK จาก GitHub Pages ตรวจ SHA-256 แล้วเปิดหน้าติดตั้งของ Android ให้ยืนยัน</small>'+
    '</div>';
  document.body.append(panel);
  if(window.XStageAndroid?.usesGooglePlayUpdates?.()){
    const hint=panel.querySelector('small');
    if(hint)hint.textContent='ระบบจะเปิดหน้าแอปใน Google Play ให้ยืนยันการอัปเดต ไม่ติดตั้ง APK ทดสอบทับรุ่น Google Play';
  }
  $('android-tv-update-now')?.addEventListener('click',()=>{
    nativeUpdateInstalling=true;
    const button=$('android-tv-update-now');
    if(button){button.disabled=true;button.textContent='กำลังอัปเดต…';}
    try{window.XStageAndroid?.installAvailableUpdate?.();}
    catch(error){window.XStageAndroidUpdateError(error?.message||'เริ่มอัปเดตไม่สำเร็จ');}
  });
  $('android-tv-update-later')?.addEventListener('click',()=>{
    nativeUpdateManualCheck=false;
    panel.hidden=true;
    if(state.nativeUpdateAvailable?.build){
      nativeUpdateDismissedBuild=state.nativeUpdateAvailable.build;
    }
    ui.search?.focus?.({preventScroll:true});
  });
  return panel;
}
let nativeUpdateDismissedBuild=0;
let nativeUpdateManualCheck=false;
let nativeUpdateInstalling=false;
window.XStageAndroidUpdateAvailable=(version,build)=>{
  if(!androidTvNativeBridgeReady())return;
  const manuallyChecked=nativeUpdateManualCheck;
  nativeUpdateManualCheck=false;
  const next={version:String(version||''),build:Number(build)||0};
  const currentBuild=Number(window.XStageAndroid?.getAppBuild?.()||XSTAGE_RELEASE.build)||0;
  if(!Number.isSafeInteger(next.build)||next.build<=currentBuild)return;
  const previous=state.nativeUpdateAvailable;
  const newlyPublished=!previous||previous.build!==next.build||previous.version!==next.version;
  state.nativeUpdateAvailable=next;
  state.nativeUpdateStatus='พบ X-Stage v'+next.version+' · Build '+next.build+' พร้อมอัปเดต';
  // Status snapshots advertise each available build to the Owner remote.
  // A recurring check of the SAME build must not reopen a dismissed notice.
  if(!newlyPublished&&!manuallyChecked)return;
  if(newlyPublished)window.dispatchEvent(new CustomEvent('xstage:native-update',{detail:next}));
  const panel=androidTvUpdatePanel();
  const current=(()=>{try{return String(window.XStageAndroid.getAppVersion?.()||'รุ่นปัจจุบัน');}catch{return 'รุ่นปัจจุบัน';}})();
  if(nativeUpdateDismissedBuild===next.build&&!manuallyChecked)return;
  panel.hidden=false;
  const active=playbackBusyForUpdate();
  panel.classList.toggle('during-playback',active);
  panel.setAttribute('aria-modal',String(!active));
  $('android-tv-update-title').textContent='พบ X-Stage รุ่นใหม่ · Build '+next.build;
  $('android-tv-update-version').textContent='ปัจจุบัน '+current+' → ใหม่ v'+next.version+' (Build '+next.build+')';
  $('android-tv-update-status').textContent=active
    ?'เพลงกำลังเล่นต่อเนื่อง · เลือกอัปเดตตอนนี้หรือภายหลัง'
    :'มีรุ่นใหม่พร้อมติดตั้ง';
  const button=$('android-tv-update-now');
  if(button){button.disabled=false;button.textContent='อัปเดตตอนนี้';}
  if(!active)setTimeout(()=>$('android-tv-update-now')?.focus?.(),30);
  // Inform immediately, but NEVER start an Android package installer without
  // the user's explicit Update Now action, even when the stage is idle.
  // Android itself will still request install confirmation and permissions.
};
window.XStageAndroidUpdateStatus=message=>{
  state.nativeUpdateStatus=String(message||'กำลังอัปเดต X-Stage…');
  window.dispatchEvent(new CustomEvent('xstage:native-update-status',{detail:{message:state.nativeUpdateStatus}}));
  const panel=androidTvUpdatePanel();
  // Background polling must never take over the stage or reopen a dismissed notice.
  if(!nativeUpdateManualCheck&&!nativeUpdateInstalling&&panel.hidden)return;
  panel.hidden=false;
  $('android-tv-update-status').textContent=state.nativeUpdateStatus;
};
window.XStageAndroidUpdateError=message=>{
  state.nativeUpdateStatus=String(message||'อัปเดตไม่สำเร็จ');
  window.dispatchEvent(new CustomEvent('xstage:native-update-status',{detail:{message:state.nativeUpdateStatus,error:true}}));
  const wasUserInitiated=nativeUpdateManualCheck||nativeUpdateInstalling;
  nativeUpdateManualCheck=false;
  nativeUpdateInstalling=false;
  const panel=androidTvUpdatePanel();
  // Network errors during the 15-second check stay in Owner diagnostics.
  // They are NOT permission to interrupt karaoke with a full-screen dialog.
  if(!wasUserInitiated&&panel.hidden)return;
  panel.hidden=false;
  $('android-tv-update-status').textContent=state.nativeUpdateStatus;
  const button=$('android-tv-update-now');
  if(button){button.disabled=false;button.textContent='ลองอัปเดตอีกครั้ง';}
};
window.XStageAndroidNoUpdate=()=>{
  nativeUpdateManualCheck=false;
  nativeUpdateInstalling=false;
  state.nativeUpdateAvailable=null;
  state.nativeUpdateStatus='X-Stage เป็นเวอร์ชันล่าสุดแล้ว';
  window.dispatchEvent(new CustomEvent('xstage:native-update-status',{detail:{message:state.nativeUpdateStatus}}));
  // Show update notice on the TV itself as well as the Owner remote.
  const panel=$('android-tv-update-panel');
  if(panel&&!panel.hidden){
    $('android-tv-update-status').textContent='X-Stage เป็นเวอร์ชันล่าสุดแล้ว';
    setTimeout(()=>{if(panel&&!panel.hidden)panel.hidden=true;},1300);
  }
};
let androidTvBootAuthStarted=false;
let androidTvLoginCancelled=false;
function androidTvHasStoredGoogleSession(){
  if(!androidTvNativeBridgeReady())return false;
  try{return !!window.XStageAndroid.hasStoredGoogleSession?.();}catch{return false;}
}
function restoreAndroidTvGoogleSession(){
  if(!androidTvNativeBridgeReady()||androidTvLoginCancelled)return;
  androidTvLoginInProgress=true;
  try{window.XStageAndroid.restoreGoogleSession?.();armAndroidTvLoginWatchdog();}
  catch(error){androidTvLoginInProgress=false;window.XStageAndroidAuthError?.(error?.message||'คืนค่า Google Session ไม่สำเร็จ');}
}
function startAndroidTvDeviceLogin(automatic=false){
  if(!androidTvNativeBridgeReady())return;
  androidTvLoginCancelled=false;
  androidTvLoginInProgress=true;
  ui.login.disabled=ui.gateLogin.disabled=true;
  showAndroidTvAuthPanel();
  setStatus(automatic?'กำลังเตรียม QR Login ในแอป Android…':'กำลังสร้างรหัสเข้าสู่ระบบสำหรับมือถือ…');
  try{window.XStageAndroid.requestGoogleLogin();armAndroidTvLoginWatchdog();}
  catch(error){
    androidTvLoginInProgress=false;
    ui.login.disabled=ui.gateLogin.disabled=false;
    window.XStageAndroidAuthError(error?.message||'เรียก Android Login ไม่สำเร็จ');
  }
}
function bootAndroidTvAuthentication(){
  if(androidTvBootAuthStarted||!androidTvNativeBridgeReady()||state.token)return;
  androidTvBootAuthStarted=true;
  if(androidTvHasStoredGoogleSession()){
    const panel=androidTvAuthPanel();
    panel.hidden=false;
    $('android-tv-auth-status').textContent='กำลังตรวจสอบสิทธิ์ Google Drive ที่บันทึกไว้…';
    $('android-tv-auth-retry').hidden=false;
    setAndroidTvStageAccess(false);
    notifyAndroidTvLoginReady();
    setStatus('กำลังกู้คืน Google Drive ในแอป Android…');
    restoreAndroidTvGoogleSession();
    return;
  }
  startAndroidTvDeviceLogin(true);
}
// Re-check the native Drive session before access tokens expire and after TV wake.
let androidTvRefreshingSession=false;
function guardAndroidTvSession(){
  if(!androidTvNativeBridgeReady()||!androidTvBootAuthStarted||androidTvLoginCancelled)return;
  if(androidTvVerifiedConnectionSub&&(!state.token||
    (state.tokenExpiresAt>0&&state.tokenExpiresAt<=Date.now())))setAndroidTvStageAccess(false);
  if(androidTvLoginInProgress)return;
  const expired=!state.token||!state.tokenExpiresAt||state.tokenExpiresAt<=Date.now()+90_000;
  if(!expired){androidTvRefreshingSession=false;return;}
  if(androidTvRefreshingSession)return;
  androidTvRefreshingSession=true;
  if(androidTvHasStoredGoogleSession()){
    if(state.token) {
      // Keep currently loaded audio and the queue alive while restoring the
      // encrypted native refresh token for the same Google account.
      setStatus('กำลังต่ออายุ Google Drive โดยไม่ขัดจังหวะเพลง…');
    }else{
      const panel=androidTvAuthPanel();
      panel.hidden=false;
      $('android-tv-auth-status').textContent='กำลังกู้คืน Google Drive ที่บันทึกไว้…';
      $('android-tv-auth-retry').hidden=false;
    }
    restoreAndroidTvGoogleSession();
  }else{
    // No refresh token exists. Google must show a new device-code prompt;
    // do not destroy the current audio Blob while requesting authorization.
    startAndroidTvDeviceLogin(true);
  }
}
setInterval(guardAndroidTvSession,30_000);
window.addEventListener('focus',guardAndroidTvSession);
window.addEventListener('pageshow',guardAndroidTvSession);
function startManualGoogleLogin(){
  if(androidTvNativeBridgeReady()){
    startAndroidTvDeviceLogin(false);
    return;
  }
  const gate=window.XStageBeforeGoogleLogin;
  if(typeof gate==='function'&&gate(()=>login()))return;
  login();
}
ui.login.addEventListener('click',startManualGoogleLogin);ui.gateLogin.addEventListener('click',startManualGoogleLogin);
$('gate-close')?.addEventListener('click',dismissLoginGate);
ui.gate?.addEventListener('click',event=>{if(event.target===ui.gate)dismissLoginGate();});
if(ui.gate)new MutationObserver(syncLoginGateState).observe(ui.gate,{attributes:true,attributeFilter:['hidden']});
syncLoginGateState();
ui.logout.addEventListener('click',()=>{
  if(androidTvNativeBridgeReady()){
    androidTvVerifiedConnectionSub='';
    setAndroidTvStageAccess(false);
    try{window.XStageAndroid.logoutGoogle?.();}catch{}
  }
  resetPrivate({revoke:true});
  window.dispatchEvent(new Event('xstage:auth-cleared'));
  syncLoginGateState();
  setStatus('ออกจากระบบแล้ว · ข้อมูลเพลงส่วนตัวถูกล้างจากหน้าเว็บ');
});
ui.search.addEventListener('input',()=>{
  state.selectedIndex=0;
  renderSongs();
  updateTransport();
  if(ui.search.value.trim())setLiveSearchExpanded(true);
});
ui.search.addEventListener('keydown',onSearchKey);
ui.search.addEventListener('blur',restoreViewportAfterKeyboard);

ui.clearQueue.addEventListener('click',()=>{state.queue.length=0;renderQueue();setPlayStatus('ล้างคิวแล้ว');});
ui.playPause.addEventListener('click',togglePlayback);
ui.cancelCurrent.addEventListener('click',cancelCurrentSong);
ui.restartCurrent.addEventListener('click',restartCurrentSong);
function playPrevious(){const old=state.history.pop();renderQueue();if(old)playSong(old,{remember:false});}
ui.previous.addEventListener('click',playPrevious);
ui.next.addEventListener('click',playNext);
ui.speed.addEventListener('change',()=>{player.playbackRate=Number(ui.speed.value);saveUiPrefs({speed:Number(ui.speed.value)});});
ui.volume.addEventListener('input',()=>{player.volume=Number(ui.volume.value)/100;saveUiPrefs({volume:Number(ui.volume.value)});});
ui.repeat.addEventListener('change',()=>{player.loop=ui.repeat.checked;saveUiPrefs({repeat:ui.repeat.checked});});
player.addEventListener('volumechange',()=>saveUiPrefs({volume:Math.round(player.volume*100),muted:player.muted}));
ui.seek.addEventListener('input',()=>{const d=Number.isFinite(player.duration)?player.duration:Number(state.current?.duration)||0;if(d>0)player.currentTime=d*Number(ui.seek.value)/1000;updateTransport();});
ui.fullscreen.addEventListener('click',async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await ui.stage.requestFullscreen();}catch{setPlayStatus('อุปกรณ์นี้ไม่รองรับการแสดงเต็มหน้าจอ');}});

function setupMediaSession(){
  if(!('mediaSession' in navigator))return;
  const bind=(action,handler)=>{try{navigator.mediaSession.setActionHandler(action,handler);}catch{}};
  bind('play',()=>{resumePlaybackFromSystem();});
  bind('pause',()=>{state.userPaused=true;state.resumeAfterInterruption=false;player.pause();});
  bind('stop',stopSong);
  bind('nexttrack',()=>playNext());
  bind('previoustrack',playPrevious);
  bind('seekbackward',details=>{const step=Number(details.seekOffset)||10;player.currentTime=Math.max(0,player.currentTime-step);});
  bind('seekforward',details=>{const step=Number(details.seekOffset)||10;const d=Number.isFinite(player.duration)?player.duration:Infinity;player.currentTime=Math.min(d,player.currentTime+step);});
  bind('seekto',details=>{if(Number.isFinite(details.seekTime))player.currentTime=Math.max(0,Math.min(player.duration||details.seekTime,details.seekTime));});
}
setupMediaSession();

function tryRecoverInterruptedPlayback(){
  if(!state.resumeAfterInterruption||state.userPaused||state.userStopped||!state.current||state.loading)return;
  setTimeout(()=>{if(state.resumeAfterInterruption&&!state.userPaused&&!state.userStopped)resumePlaybackFromSystem();},180);
}
window.addEventListener('xstage-audio-interrupted',()=>{state.resumeAfterInterruption=true;});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)tryRecoverInterruptedPlayback();});
window.addEventListener('pageshow',tryRecoverInterruptedPlayback);
window.addEventListener('focus',tryRecoverInterruptedPlayback);

let playbackSnapshotTick=0;
player.addEventListener('timeupdate',()=>{
  updateTransport();
  medleyTick();
  const now=Date.now();
  if(now-playbackSnapshotTick>2000){playbackSnapshotTick=now;savePlaybackResumeState();}
});
player.addEventListener('loadedmetadata',updateTransport);
player.addEventListener('durationchange',updateTransport);
player.addEventListener('play',()=>{state.userPaused=false;state.resumeAfterInterruption=false;syncSongVideo();updateTransport();});
player.addEventListener('timeupdate',syncSongVideo);
player.addEventListener('seeked',syncSongVideo);
player.addEventListener('ratechange',syncSongVideo);
player.addEventListener('pause',()=>{
  if(karaokeVideo)karaokeVideo.pause();
  if(state.current&&!state.loading&&!state.userPaused&&!state.userStopped&&!player.ended&&player.currentTime>0){
    state.resumeAfterInterruption=true;
  }
  updateTransport();
});
player.addEventListener('ended',()=>{
  if(karaokeVideo)karaokeVideo.pause();
  if(player.loop)return;
  if(state.queue.length||state.medley)playNext();
  else clearIdleStage('จบเพลงแล้ว · คิวว่าง');
});
player.addEventListener('error',()=>{
  if(!state.current)return;
  const code=player.error?.code;
  const message=code===4?'Android TV ไม่รองรับไฟล์เสียงนี้หรือรูปแบบไฟล์ไม่ถูกต้อง'
    :code===3?'Android TV ถอดรหัสไฟล์เสียงเพลงนี้ไม่ได้'
    :'เกิดข้อผิดพลาดระหว่างเปิดไฟล์เสียงเพลงบนจอ';
  setPlayStatus(message);publishPlaybackStatus('error',state.current,message);
});
document.addEventListener('keydown',e=>{
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='f'&&state.token){e.preventDefault();ui.search.focus();ui.search.select();return;}
  if(['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName))return;
  if(e.key==='F5'){e.preventDefault();togglePlayback();}
  if(e.key==='F6'){e.preventDefault();playNext();}
  if(e.key==='F8'){e.preventDefault();cancelCurrentSong();}
  if(e.key==='Escape'&&document.fullscreenElement){document.exitFullscreen();}
});
window.addEventListener('pagehide',savePlaybackResumeState);
window.addEventListener('beforeunload',()=>{savePlaybackResumeState();state.controller?.abort();resetSongVideo();if(state.objectUrl)URL.revokeObjectURL(state.objectUrl);});
renderSongs();renderQueue();updateTransport();requestAnimationFrame(drawLyrics);setupNativeAndroidTvUi();setupAppUpdateWatcher();
const xstageCloudImporter=window.XStageCloudImport?.init({
  // The browser importer obtains only an in-memory short-lived token and the
  // current verified account. No token, password or refresh token is stored.
  session:()=>({token:state.token,sub:state.accountSub,
    rootId:state.libraryRootId,owned:state.libraryRootOwnedByMe}),
  refresh:async()=>{
    if(!state.token||!state.accountSub)return;
    // Reload the canonical XStageWeb current.json/catalog after publishing.
    // Use a NEW auth request ID but never silently switch Google accounts.
    const token=state.token,id=++state.authId;
    await openDrive(token,id,state.tokenExpiresAt);
  }
});

window.XStageSoftRefresh=async function(){
  if(state.current||player.src){
    savePlaybackResumeState();
    renderSongs();renderQueue();updateTransport();
    if(state.token)void pollPublishedCatalog();
    return true;
  }
  if(state.token){
    await pollPublishedCatalog();
    renderSongs();renderQueue();updateTransport();
    return true;
  }
  return false;
};

// Restore a still-valid short-lived token from this browser. After Google expiry,
// GIS token-model reauthorization still requires an explicit user gesture.
async function recoverPendingGoogleAuth(reason='กำลังกู้คืนการเข้าสู่ระบบ Google…'){
  if(state.token||state.authRecovering)return false;
  const pending=readPendingAuth();if(!pending)return false;
  state.authRecovering=true;
  ui.gate.hidden=false;ui.login.disabled=ui.gateLogin.disabled=true;
  setStatus(reason);
  const id=++state.authId;
  try{
    await openDrive(pending.token,id,pending.expiresAt);
    return !!state.token;
  }catch(error){
    if(id===state.authId){
      resetPrivate({keepAuth:true});
      if(!/เชื่อมต่อไม่สำเร็จ|ใช้เวลานาน|อินเทอร์เน็ต/.test(String(error.message||'')))clearPendingAuth();
      setStatus('กู้คืนการเข้าสู่ระบบไม่สำเร็จ: '+error.message,'error');
    }
    return false;
  }finally{
    state.authRecovering=false;
    if(id===state.authId)ui.login.disabled=ui.gateLogin.disabled=false;
  }
}
(function restoreTabSession(){
  // Android APK login is owned by the encrypted native token store, not JS.
  if(androidTvNativeBridgeReady())return;
  const saved=readActiveAuth();
  if(!saved){
    if(readPendingAuth()){void recoverPendingGoogleAuth();}
    else if(hasRememberedLogin())setStatus('เคยเข้าสู่ระบบแล้ว · กรุณากดเชื่อมต่อ Google เมื่อเซสชันหมดอายุ');
    return;
  }
  ui.gate.hidden=true;
  ui.login.disabled=ui.gateLogin.disabled=true;
  setStatus('กำลังตรวจสอบเซสชัน Google เดิม…');
  const id=++state.authId;
  openDrive(saved.token,id,saved.expiresAt,saved.sub).catch(error=>{
    if(id!==state.authId)return;
    clearActiveAuth();
    resetPrivate({keepAuth:true});
    if(readPendingAuth())void recoverPendingGoogleAuth('เซสชันเดิมใช้ไม่ได้ · กำลังกู้คืนการเข้าสู่ระบบ…');
    else setStatus('เซสชันหมดอายุหรือเข้าถึงคลังไม่ได้: '+error.message,'error');
  }).finally(()=>{
    if(id===state.authId)ui.login.disabled=ui.gateLogin.disabled=false;
  });
})();
window.addEventListener('offline',()=>setStatus('อุปกรณ์ออฟไลน์ · เพลงที่โหลดไว้แล้วอาจเล่นต่อได้ แต่ค้น/โหลดเพลงใหม่ไม่ได้','error'));
window.addEventListener('online',()=>{
  if(state.token)return;
  if(readPendingAuth()){void recoverPendingGoogleAuth('กลับมาออนไลน์แล้ว · กำลังกู้คืนการเข้าสู่ระบบ Google…');return;}
  const saved=readActiveAuth();
  if(!saved){if(hasRememberedLogin())setStatus('กลับมาออนไลน์แล้ว · กดเข้าสู่ระบบ Google เพื่อเชื่อมต่ออีกครั้ง');return;}
  ui.gate.hidden=true;ui.login.disabled=ui.gateLogin.disabled=true;
  setStatus('กลับมาออนไลน์แล้ว · กำลังกู้คืนเซสชัน Google…');
  const id=++state.authId;
  openDrive(saved.token,id,saved.expiresAt,saved.sub).catch(error=>{
    if(id!==state.authId)return;clearActiveAuth();resetPrivate({keepAuth:true});setStatus('กู้คืนเซสชันไม่สำเร็จ: '+error.message,'error');
  }).finally(()=>{if(id===state.authId)ui.login.disabled=ui.gateLogin.disabled=false;});
});

let oauthReturnRecoveryTimer=0;
function scheduleOAuthReturnRecovery(){
  clearTimeout(oauthReturnRecoveryTimer);
  if(document.hidden||state.token)return;
  oauthReturnRecoveryTimer=setTimeout(()=>{
    if(state.token)return;
    if(readPendingAuth())void recoverPendingGoogleAuth('กลับจาก Google แล้ว · กำลังเชื่อมต่อคลังเพลงต่อ…');
    else if(ui.login.disabled||ui.gateLogin.disabled){
      state.authId++;
      ui.login.disabled=ui.gateLogin.disabled=false;
      setStatus('กลับจาก Google แล้วแต่ Safari ยังไม่ได้ส่งสิทธิ์กลับมา · กดเข้าสู่ระบบ Google อีกครั้งได้ทันที','error');
    }
  },2500);
}
document.addEventListener('visibilitychange',scheduleOAuthReturnRecovery);
window.addEventListener('pageshow',scheduleOAuthReturnRecovery);
window.addEventListener('focus',scheduleOAuthReturnRecovery);
setTimeout(bootAndroidTvAuthentication,0);
