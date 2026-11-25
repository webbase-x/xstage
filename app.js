/* X-Stage Karaoke Online – single-page private Drive player.
 * A short-lived Google access token may be cached in this browser until its Google expiry
 * so reopening the site does not force a repeat login. No password or refresh token is stored.
 * Catalog metadata can be cached locally per verified Google account; media remain private/transient. */
'use strict';
const cfg = window.XSTAGE_CONFIG || {};
const driveLayout=window.XSTAGE_DRIVE_LAYOUT||{root:'XStageKaraoke',db:'DB'};
const retiredDriveRootIds=new Set(window.XSTAGE_RETIRED_DRIVE_ROOT_IDS||[]);
const isRetiredDriveRoot=id=>retiredDriveRootIds.has(String(id||''));
const $ = id => document.getElementById(id);
const ui = {
  status: $('status'), login: $('login'), gateLogin: $('gate-login'), gateStatus:$('gate-auth-status'), logout: $('logout'), gate: $('gate'), catalogLoading:$('catalog-loading'), catalogLoadingTitle:$('catalog-loading-title'), catalogLoadingDetail:$('catalog-loading-detail'), catalogProgress:$('catalog-progress'), catalogProgressValue:$('catalog-progress-value'),
  account: $('account'), libraryState: $('library-state'), libraryDriveLink:$('library-drive-link'), songTotal: $('song-total'), resultCount: $('result-count'), searchRefine:$('search-refine-hint'),
  librarySelect:$('library-select'),librarySwitcher:$('library-switcher'),
  search: $('search'), songs: $('songs'), queue: $('queue'), queueCount: $('queue-count'), clearQueue: $('clear-queue'),
  player: $('player'), stage: $('stage'), stageIdle: $('stage-idle'), stageCode: $('stage-code'),
  nowPlaying: $('now-playing'), nowArtist: $('now-artist'), songKey:$('tv-song-key'), toolbarSongKey:$('toolbar-song-key'), playStatus: $('play-status'),
  playPause: $('play-pause'), cancelCurrent:$('cancel-current'), restartCurrent:$('restart-current'), previous: $('previous'), next: $('next'),
  seek: $('seek'), elapsed: $('elapsed'), duration: $('duration'), speed: $('speed'), volume: $('volume'),
  repeat: $('repeat'), fullscreen: $('fullscreen'), lyrics: $('lyrics')
};
function transposeSongKey(key,semitones=0){
  const original=String(key||'').trim();
  const match=/^([A-Ga-g])([#♯b♭]?)(m|min)?$/i.exec(original);
  const shift=Math.trunc(Number(semitones)||0);
  if(!match||!shift)return original;
  const chromatic={C:0,D:2,E:4,F:5,G:7,A:9,B:11};
  const root=match[1].toUpperCase();
  const accidental=match[2]==='#'||match[2]==='♯'?1:
    match[2]==='b'||match[2]==='♭'?-1:0;
  const index=((chromatic[root]+accidental+shift)%12+12)%12;
  const sharps=['C','C♯','D','D♯','E','F','F♯','G','G♯','A','A♯','B'];
  const flats=['C','D♭','D','E♭','E','F','G♭','G','A♭','A','B♭','B'];
  const preferFlat=match[2]==='b'||match[2]==='♭';
  return (preferFlat?flats:sharps)[index]+(match[3]||'');
}
function setSongKeyDisplay(key){
  if(key!==undefined)state.originalSongKey=String(key||'').trim();
  else if(!state.current)state.originalSongKey='';
  const shift=state.liveMidiSource?Number($('midi-transpose')?.value||0):0;
  const actual=transposeSongKey(state.originalSongKey,shift);
  const label='คีย์ '+(actual||'—');
  if(ui.songKey)ui.songKey.textContent=label;
  if(ui.toolbarSongKey){
    ui.toolbarSongKey.textContent=label;
    ui.toolbarSongKey.title=actual?'คีย์เพลง: '+actual:'ยังไม่มีข้อมูลคีย์เพลง';
  }
}
const state = {
  token: '', tokenExpiresAt:0, accountSub: '', manifest: null, songs: [], shown: [], selectedIndex: 0,
  queue: [], history: [], current: null, lyrics: null, preparingSong:null, originalSongKey:'',
  objectUrl: '', liveMidiPlayback:null, liveMidiSource:null,
  requestId: 0, controller: null, authId: 0, loading: false,
  medley: false, medleyCache: null, medleyPrefetch: null,
  medleyUpcoming: null, medleyPoolSource: null, medleyPool: [], medleyRecent: [],
  userStopped: false, userPaused:false, resumeAfterInterruption:false, visualScale: 1,
  catalogPointerId:'',catalogGeneration:'',catalogPolling:false,catalogCache:new Map(),
  libraryRootId:'',libraryRootCanShare:false,libraryRootOwnedByMe:false,libraryRootOwnerEmail:'',availableLibraries:[],
  queuePreload:null,queuePrepared:null,queuePreloadTimer:null,queuePreloadVersion:0,
  queuePreparedCache:new Map(),queuePreloadSkipped:new Set(),
  transitionFill:null,medleyPreloadFailedSong:null,medleyPreloadRetryAt:0,
  activeBlobBytes:0,activeVideoBytes:0,
  playbackRestoreAttempted:false,
  awaitingSharedLibrary:false,
  updateAvailable:null,updateAfterTrack:false,nativeUpdateAvailable:null,nativeUpdateStatus:''
};

let nativeAudioFocusBlocked=false;
function requestNativePlaybackAudioFocus(){
  if(!androidTvNativeBridgeReady()||typeof window.XStageAndroid?.requestPlaybackAudioFocus!=='function')return true;
  try{
    if(window.XStageAndroid.requestPlaybackAudioFocus()){nativeAudioFocusBlocked=false;return true;}
  }catch(error){console.warn('Android audio focus:',error);}
  setPlayStatus('Android ไม่อนุญาตให้เริ่มเสียงขณะนี้ · ลองอีกครั้งเมื่อแอปอื่นหยุดเสียง');
  return false;
}
function releaseNativePlaybackAudioFocus(){
  try{window.XStageAndroid?.releasePlaybackAudioFocus?.();}catch{}
}
function syncNativeTextEditingState(){
  const field=document.activeElement;
  const editing=!!field&&(field.isContentEditable||field.tagName==='TEXTAREA'||
    (field.tagName==='INPUT'&&/^(text|search|number|email|url|tel|password)$/.test(field.type)));
  try{window.XStageAndroid?.setTextEditingActive?.(editing);}catch{}
}
document.addEventListener('focusin',syncNativeTextEditingState,true);
document.addEventListener('focusout',()=>setTimeout(syncNativeTextEditingState,0),true);
window.addEventListener('pageshow',syncNativeTextEditingState);
const XSTAGE_RELEASE=window.XSTAGE_RELEASE||{version:'0.0.0',build:0};
function appUpdateElements(){
  return {
    notice:$('app-update-notice'),text:$('app-update-text'),
    action:$('app-update-action'),after:$('app-update-after-song')
  };
}
function playbackBusyForUpdate(){
  return !!(state.loading||state.current&&player.src&&!player.ended&&(!player.paused||state.queue.length||state.medley));
}
let webUpdateStageBuild=0,webUpdateStageReady=false,webUpdateStagePromise=null;
let webUpdateStageFinished=false,webUpdateManualMessage='',webUpdateStageController=null;
let webUpdatePhase='notice',webUpdateCompletedBuild=0,webUpdateCheckTask=null,webUpdateCheckComplete=false;
if(typeof window!=='undefined')window.XStageWebUpdateState=()=>({checked:webUpdateCheckComplete,busy:!!state.updateAvailable||webUpdatePhase!=='notice'});
const WEB_UPDATE_HANDOFF='xstage-web-update-handoff-v1';
function renderAppUpdateNotice(){
  const {notice,text,action,after}=appUpdateElements();
  if(!notice||!text||!action)return;
  const remote=state.updateAvailable;
  if(!remote&&webUpdatePhase!=='complete'){notice.hidden=true;return;}
  notice.hidden=false;
  if(typeof document!=='undefined'){
    const apk=document.getElementById('xstage-apk-dialog');
    if(apk?.open)apk.close();
  }
  const busy=webUpdatePhase==='applying';
  const complete=webUpdatePhase==='complete';
  if(notice.dataset)notice.dataset.updatePhase=webUpdatePhase;
  if(busy||complete){
    text.textContent=complete?'ขั้นที่ 2/2 · อัปเดตสำเร็จ · Build '+webUpdateCompletedBuild:
      'ขั้นที่ 2/2 · '+(webUpdateManualMessage||'กำลังเปิดรุ่นใหม่…');
    action.hidden=true;action.disabled=true;
    if(after)after.hidden=true;
    const link=typeof $==='function'?$('app-update-direct'):null;if(link)link.hidden=true;
    return;
  }
  action.hidden=false;
  notice.classList.toggle('during-playback',playbackBusyForUpdate());
  const preparation=webUpdateStageBuild===remote.build
    ?(webUpdateStageReady?' · เตรียมไฟล์แล้ว':webUpdateStageFinished?' · เปิดรุ่นใหม่โดยตรงได้':' · กำลังเตรียมไฟล์…'):'';
  text.textContent='ขั้นที่ 1/2 · พบ X-Stage v'+remote.version+' · Build '+remote.build+preparation+(webUpdateManualMessage?' · '+webUpdateManualMessage:'');
  action.textContent='อัปเดตตอนนี้';
  action.disabled=false;
  const direct=typeof $==='function'?$('app-update-direct'):null;
  if(direct){const url=new URL('karaoke.html',location.href);url.searchParams.set('build',String(remote.build));url.searchParams.set('xstage_update',String(Date.now()));direct.href=url.href;direct.hidden=!!window.XStageDriveBuildBusy||!!webGoogleAuthFlow;}
  if(after){
    after.hidden=!playbackBusyForUpdate();
    after.textContent=state.updateAfterTrack?'ตั้งค่าแล้ว · หลังจบเพลง':'อัปเดตหลังจบเพลง';
    after.disabled=!!state.updateAfterTrack;
  }
}
// Prefetch ONLY public same-origin HTML/CSS/JS. Do not touch private Drive,
// Google tokens, service workers, or the active player. A newer shell can then
// start quickly after the user chooses Update Now / the next song boundary.
async function stageWebUpdateFiles(remote){
  const build=Number(remote?.build)||0;
  if(!build||androidTvNativeBridgeReady())return false;
  if(webUpdateStageBuild===build)
    return webUpdateStagePromise||Promise.resolve(webUpdateStageReady);
  webUpdateStageController?.abort();
  webUpdateStageBuild=build;webUpdateStageReady=false;webUpdateStageFinished=false;
  const controller=typeof AbortController==='function'?new AbortController():null;
  webUpdateStageController=controller;
  let timer;
  const work=(async()=>{
    if(navigator.connection?.saveData)return false;
    const page=new URL('karaoke.html',location.href);
    page.searchParams.set('xstage_stage',String(build));
    const html=await fetch(page.href,{cache:'reload',signal:controller?.signal});
    if(!html.ok)throw Error('ยังโหลดหน้าเว็บรุ่นใหม่ไม่ได้');
    const doc=new DOMParser().parseFromString(await html.text(),'text/html');
    const assets=[...doc.querySelectorAll('script[src],link[rel="stylesheet"][href]')]
      .map(node=>node.getAttribute('src')||node.getAttribute('href'))
      .filter(Boolean).map(href=>new URL(href,page.href))
      .filter(url=>url.origin===location.origin&&url.pathname.startsWith(new URL('./',page.href).pathname));
    // Two concurrent requests avoid saturating the link carrying live music.
    for(let i=0;i<assets.length;i+=2){
      const batch=assets.slice(i,i+2);
      const results=await Promise.allSettled(batch.map(async url=>{
        const response=await fetch(url.href,{cache:'reload',signal:controller?.signal});
        if(response.ok)await response.arrayBuffer(); // Complete download into browser HTTP cache.
        return response;
      }));
      if(results.some(result=>result.status!=='fulfilled'||!result.value.ok))
        throw Error('ไฟล์อัปเดตบางส่วนยังดาวน์โหลดไม่สำเร็จ');
      if(webUpdateStageBuild!==build||controller?.signal.aborted)return false;
    }
    if(webUpdateStageBuild!==build||controller?.signal.aborted||webUpdateStageFinished)return false;
    webUpdateStageReady=true;
    renderAppUpdateNotice();
    return true;
  })();
  const task=Promise.race([work,new Promise(resolve=>{
    timer=setTimeout(()=>{controller?.abort();resolve(false);},15000);
  })]).catch(error=>{
    console.warn('Web update prefetch deferred:',error?.message||error);
    return false;
  }).finally(()=>{
    clearTimeout(timer);
    if(webUpdateStageBuild===build){webUpdateStageFinished=true;renderAppUpdateNotice();}
  });
  webUpdateStagePromise=task;
  renderAppUpdateNotice();
  return task;
}
let preserveUpdateResumeOnUnload=false;
async function performAppUpdateReload({preserveSnapshot=false,manual=false}={}){
  if(webUpdatePhase==='applying')return false;
  if(window.XStageDriveBuildBusy){
    webUpdateManualMessage='กำลังสร้างฐานเพลง · ลองใหม่หลังเสร็จ';
    renderAppUpdateNotice();setStatus(webUpdateManualMessage);return false;
  }
  if(manual&&webGoogleAuthFlow){
    webUpdateManualMessage='Google กำลังยืนยันบัญชี · ลองใหม่หลังยืนยันเสร็จ';
    renderAppUpdateNotice();setStatus(webUpdateManualMessage);return false;
  }
  preserveUpdateResumeOnUnload=preserveSnapshot;
  if(!preserveSnapshot)try{savePlaybackResumeState();}catch{}
  // Navigation never depends on speculative prefetch or token recovery.
  // Keep the current origin, storage, query parameters and playback snapshot.
  const next=new URL('karaoke.html',location.href);
  const previous=new URL(location.href);
  next.search=previous.search;
  next.searchParams.delete('xstage_stage');
  next.searchParams.set('xstage_update',String(Date.now()));
  next.searchParams.set('build',String(state.updateAvailable?.build||XSTAGE_RELEASE.build));
  webUpdatePhase='applying';
  webUpdateManualMessage='กำลังเปิดหน้าเว็บรุ่นใหม่…';
  try{sessionStorage.setItem(WEB_UPDATE_HANDOFF,JSON.stringify({build:Number(state.updateAvailable?.build||XSTAGE_RELEASE.build),at:Date.now()}));}catch{}
  renderAppUpdateNotice();
  webUpdateStageController?.abort();
  try{location.replace(next.href);return true;}
  catch(error){
    webUpdatePhase='notice';webUpdateReloading=false;
    try{sessionStorage.removeItem(WEB_UPDATE_HANDOFF);}catch{}
    webUpdateManualMessage='เปิดอัตโนมัติไม่ได้ · ใช้ลิงก์เปิดรุ่นใหม่';renderAppUpdateNotice();
    const direct=$('app-update-direct');if(direct){direct.href=next.href;direct.hidden=false;}
    return false;
  }
}
// Automatic web hotfixes run on entry, never mid-song. Guard repeated
// redirects if an intermediary cache continues serving the older shell.
const WEB_AUTO_UPDATE_GUARD='xstage-web-auto-update-target-v1';
let webUpdateReloading=false;
function autoApplyWebUpdate(remote){
  if(androidTvNativeBridgeReady()||!remote||webUpdateReloading)return false;
  // Never navigate away while a GIS popup is returning or its token is being verified.
  if(webGoogleAuthFlow||state.authRecovering)return false;
  if(playbackBusyForUpdate()||window.XStageDriveBuildBusy)return false;
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
  if(webUpdateCheckTask)return webUpdateCheckTask;
  const task=checkAppVersionOnce();webUpdateCheckTask=task;
  try{return await task;}finally{
    if(webUpdateCheckTask===task)webUpdateCheckTask=null;
    webUpdateCheckComplete=true;
    window.dispatchEvent(new CustomEvent('xstage:web-update-check-complete'));
  }
}
async function checkAppVersionOnce(){
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
      if(webUpdatePhase==='complete')webUpdatePhase='notice';
      state.updateAvailable={version:String(remote.version||''),build:remoteBuild};
      renderAppUpdateNotice();
      if(changed){
        state.updateAfterTrack=false;
        window.dispatchEvent(new CustomEvent('xstage:web-update',{detail:state.updateAvailable}));
        // Prepare the shell while the song continues to play normally.
        void stageWebUpdateFiles(state.updateAvailable);
      }
      // Never automatically reload during a song, authentication or a popup.
      if(webUpdateStageFinished)autoApplyWebUpdate(state.updateAvailable);
      else void Promise.resolve(webUpdateStagePromise).then(()=>{if(state.updateAvailable?.build===remoteBuild)autoApplyWebUpdate(state.updateAvailable);});
      return true;
    }else{
      state.updateAvailable=null;
      state.updateAfterTrack=false;
      webUpdateStageController?.abort();webUpdateStageBuild=0;webUpdateStageReady=false;webUpdateStagePromise=null;webUpdateStageFinished=false;webUpdateManualMessage='';
      renderAppUpdateNotice();
      return false;
    }
  }catch{return null;/* Unknown status: never claim that an offline client is up to date. */}
}
async function triggerImmediateVersionUpdate(){
  if(androidTvNativeBridgeReady()){
    if(nativeUpdateInstalling)return;
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
  if(found===true){
    // Explicit user request: refresh now and restore the saved song position.
    await performAppUpdateReload({manual:true});
  }else if(found===false)setStatus('X-Stage เป็นเวอร์ชันล่าสุดแล้ว');
  else setStatus('ตรวจสอบเวอร์ชันไม่สำเร็จ กรุณาตรวจอินเทอร์เน็ตแล้วลองใหม่');
}
// Installed Android APKs load this hosted UI, including older builds. A live
// foreground poll also fixes missing mid-song update notices on those APKs.
// Keep the native APK channel separate from the Web version.json channel.
const XSTAGE_LIVE_UPDATE_CHECK_MS=15_000;
function checkLiveAppUpdate(){
  if(androidTvNativeBridgeReady()){
    if(typeof nativeUpdateInstalling!=='undefined'&&nativeUpdateInstalling)return;
    try{window.XStageAndroid.checkForAppUpdate?.();}catch{}
    return;
  }
  void checkAppVersion();
}
function setupAppUpdateWatcher(){
  if(!androidTvNativeBridgeReady()){
    try{
      const handoff=JSON.parse(sessionStorage.getItem(WEB_UPDATE_HANDOFF)||'null');
      if(handoff){
        sessionStorage.removeItem(WEB_UPDATE_HANDOFF);
        if(Number(handoff.build)===Number(XSTAGE_RELEASE.build)&&Date.now()-Number(handoff.at)<300000){
          webUpdatePhase='complete';webUpdateCompletedBuild=Number(handoff.build);renderAppUpdateNotice();
          setTimeout(()=>{if(webUpdatePhase==='complete'){webUpdatePhase='notice';renderAppUpdateNotice();}},3500);
        }
      }
    }catch{}
  }
  const {action,after}=appUpdateElements();
  action?.addEventListener('click',()=>{
    if(!state.updateAvailable)return;
    void performAppUpdateReload({manual:true});
  });
  after?.addEventListener('click',()=>{
    if(!state.updateAvailable)return;
    state.updateAfterTrack=true;
    renderAppUpdateNotice();
    if(!playbackBusyForUpdate())void performAppUpdateReload();
  });
  $('app-update-direct')?.addEventListener('click',event=>{
    if(!state.updateAvailable||webUpdateManualMessage.startsWith('เปิดอัตโนมัติไม่ได้'))return;event.preventDefault();void performAppUpdateReload({manual:true});
  });
  $('desktop-update-version')?.addEventListener('click',()=>{void triggerImmediateVersionUpdate();});
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
  const queuePanel=document.getElementById('xstage-tv-queue-panel');
  if(nativeTv&&xstageTvVisible(queuePanel))return queuePanel;
  const searchPanel=document.getElementById('xstage-tv-search-panel');
  if(nativeTv&&xstageTvVisible(searchPanel))return searchPanel;
  const quickMenu=document.getElementById('xstage-tv-quick-menu');
  if(nativeTv&&xstageTvVisible(quickMenu))return quickMenu;
  const selectors=[
    '.android-tv-update-panel:not([hidden]):not(.during-playback)',
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
// Android TV shares the Karaoke Online engine, queue and transport actions.
function xstageTvRefreshQuickMenu(panel){
  const current=state.current;
  const now=panel.querySelector('#xstage-tv-quick-now');
  if(now)now.textContent=current
    ?String(current.title||current.code||'เพลงปัจจุบัน')+
      (current.artist?' · '+String(current.artist):'')
    :'ยังไม่มีเพลงที่กำลังเล่น';
  const key=panel.querySelector('#xstage-tv-quick-key');
  if(key)key.textContent=ui.songKey?.textContent||'คีย์ —';
  const count=panel.querySelector('#xstage-tv-quick-queue-count');
  if(count)count.textContent='คิวถัดไป '+state.queue.length+' เพลง';
  const list=panel.querySelector('#xstage-tv-quick-queue-list');
  if(list){
    list.replaceChildren();
    const queued=state.queue.slice(0,3);
    if(!queued.length){
      const item=document.createElement('li');
      item.textContent='ยังไม่มีเพลงรอในคิว';
      list.append(item);
    }else{
      for(const song of queued){
        const item=document.createElement('li');
        item.textContent=String(song.title||song.code||'ไม่ทราบชื่อเพลง')+
          (song.artist?' · '+String(song.artist):'');
        list.append(item);
      }
    }
  }
  const login=panel.querySelector('#xstage-tv-quick-login');
  if(login)login.hidden=!!state.token;
  const search=panel.querySelector('#xstage-tv-quick-search');
  if(search)search.disabled=!state.token;
  for(const [quickId,controlId] of [
    ['xstage-tv-quick-play','play-pause'],
    ['xstage-tv-quick-next','next'],
    ['xstage-tv-quick-previous','previous'],
    ['xstage-tv-quick-restart','restart-current']
  ]){
    const quick=panel.querySelector('#'+quickId);
    const control=document.getElementById(controlId);
    if(quick)quick.disabled=!control||control.disabled;
  }
  const transpose=document.getElementById('midi-transpose-control');
  const midiReady=!!state.liveMidiSource&&!!transpose&&!transpose.hidden;
  for(const [quickId,controlId] of [
    ['xstage-tv-quick-key-down','midi-key-down'],
    ['xstage-tv-quick-key-up','midi-key-up']
  ]){
    const quick=panel.querySelector('#'+quickId);
    const control=document.getElementById(controlId);
    if(quick)quick.disabled=!midiReady||!control||control.disabled;
  }
}

/* Android TV searches the SAME private catalog and starts/queues through the
 * SAME Karaoke Online action as a mouse/touch song selection. No second DB. */
function xstageTvRenderSearch(panel){
  const input=panel.querySelector('#xstage-tv-search-input');
  const results=panel.querySelector('#xstage-tv-search-results');
  const status=panel.querySelector('#xstage-tv-search-status');
  if(!input||!results||!status)return;
  results.replaceChildren();
  const term=normalizeSearchText(input.value.trim());
  if(!state.token){
    status.textContent='กรุณาเข้าสู่ Google Drive ก่อนค้นหาเพลง';
    return;
  }
  if(!term){
    status.textContent='พิมพ์ชื่อเพลง ศิลปิน หรือรหัสเพลง';
    return;
  }
  const ranked=rankedSearchEntries(state.songs,term,8);
  status.textContent=ranked.total
    ?'พบ '+num(ranked.total)+' เพลง · แสดง '+ranked.results.length+' รายการที่ตรงที่สุด'
    :'ไม่พบเพลงที่ตรงกับคำค้น';
  for(const {song} of ranked.results){
    const button=document.createElement('button');
    button.type='button';
    button.className='xstage-tv-search-song';
    const title=document.createElement('strong');
    const artist=document.createElement('span');
    title.textContent=String(song.title||song.code||'ไม่ระบุชื่อเพลง');
    artist.textContent=[song.code,song.artist].filter(Boolean).map(String).join(' · ');
    button.append(title,artist);
    button.addEventListener('click',()=>{
      if(!state.token||!playable(song))return;
      xstageTvCloseSearch(false);
      chooseSearchSong(song);
    });
    results.append(button);
  }
}
function xstageTvSearchPanel(){
  let panel=document.getElementById('xstage-tv-search-panel');
  if(panel)return panel;
  panel=document.createElement('section');
  panel.id='xstage-tv-search-panel';
  panel.className='xstage-tv-search-panel';
  panel.hidden=true;
  panel.setAttribute('role','dialog');
  panel.setAttribute('aria-modal','true');
  panel.setAttribute('aria-label','ค้นหาเพลงบนทีวี');
  panel.innerHTML='<div class="xstage-tv-search-box">'+
    '<h2>ค้นหาเพลง · X-Stage Karaoke</h2>'+
    '<p>ค้นจากคลัง XStageKaraoke เดียวกับ Karaoke Online · กด OK เพื่อเลือกเพลง</p>'+
    '<input id="xstage-tv-search-input" type="search" autocomplete="off" placeholder="ชื่อเพลง / ศิลปิน / รหัสเพลง" aria-label="ค้นหาเพลงบนทีวี">'+
    '<div id="xstage-tv-search-status" role="status" aria-live="polite"></div>'+
    '<div id="xstage-tv-search-results" class="xstage-tv-search-results"></div>'+
    '<button id="xstage-tv-search-close" class="xstage-tv-search-close" type="button">กลับสู่เมนูทีวี</button>'+
    '</div>';
  document.body.append(panel);
  panel.querySelector('#xstage-tv-search-input').addEventListener('input',()=>xstageTvRenderSearch(panel));
  panel.querySelector('#xstage-tv-search-input').addEventListener('keydown',event=>{
    if(event.key==='Escape'){event.preventDefault();xstageTvCloseSearch(true);}
  });
  panel.querySelector('#xstage-tv-search-close').addEventListener('click',()=>xstageTvCloseSearch(true));
  return panel;
}
function xstageTvCloseSearch(returnToMenu=false){
  const panel=document.getElementById('xstage-tv-search-panel');
  if(!panel||panel.hidden)return;
  // Blurring the text field also releases native Android's D-pad editing mode.
  panel.contains(document.activeElement)&&document.activeElement?.blur?.();
  panel.hidden=true;
  if(returnToMenu)window.XStageTvOpenMenu?.();
}
function xstageTvOpenSearch(){
  if(!document.body.classList.contains('xstage-native-tv'))return false;
  const panel=xstageTvSearchPanel();
  document.getElementById('xstage-tv-quick-menu')?.setAttribute('hidden','');
  panel.hidden=false;
  xstageTvRenderSearch(panel);
  const input=panel.querySelector('#xstage-tv-search-input');
  input?.focus?.({preventScroll:true});
  return true;
}

/* The TV queue is a remote-friendly view of state.queue. All edits go through
 * the same queue mutation/preloading methods as Karaoke Online. */
function xstageTvRenderQueue(panel){
  const list=panel.querySelector('#xstage-tv-queue-items');
  const status=panel.querySelector('#xstage-tv-queue-status');
  if(!list||!status)return;
  list.replaceChildren();
  status.textContent=state.queue.length
    ?'คิวถัดไป '+num(state.queue.length)+' เพลง'+(state.queue.length>25?' · แสดง 25 รายการแรก':'')
    :'ยังไม่มีเพลงรอในคิว';
  state.queue.slice(0,25).forEach((song,index)=>{
    const row=document.createElement('div');
    row.className='xstage-tv-queue-row';
    const info=document.createElement('div');
    info.className='xstage-tv-queue-info';
    const name=document.createElement('strong');
    const detail=document.createElement('span');
    name.textContent=(index+1)+'. '+String(song.title||song.code||'ไม่ระบุชื่อเพลง');
    detail.textContent=[song.code,song.artist].filter(Boolean).map(String).join(' · ');
    info.append(name,detail);
    const controls=document.createElement('div');
    controls.className='xstage-tv-queue-actions';
    const action=(label,run,disabled=false)=>{
      const button=document.createElement('button');
      button.type='button';button.textContent=label;button.disabled=disabled;
      button.addEventListener('click',()=>{
        // A phone may have edited the shared queue while the TV menu was open.
        if(state.queue[index]!==song){xstageTvRenderQueue(panel);return;}
        run();
      });
      controls.append(button);
      return button;
    };
    action('เล่นเลย',()=>{
      state.queue.splice(index,1);renderQueue();
      xstageTvCloseQueue(false);void playSong(song);
    },!state.token);
    action('↑',()=>{
      moveQueue(index,-1);xstageTvRenderQueue(panel);
      panel.querySelectorAll('.xstage-tv-queue-row')[index-1]
        ?.querySelectorAll('button')[1]?.focus?.({preventScroll:true});
    },index===0);
    action('↓',()=>{
      moveQueue(index,1);xstageTvRenderQueue(panel);
      panel.querySelectorAll('.xstage-tv-queue-row')[index+1]
        ?.querySelectorAll('button')[2]?.focus?.({preventScroll:true});
    },index===state.queue.length-1);
    action('ลบ',()=>{
      state.queue.splice(index,1);renderQueue();xstageTvRenderQueue(panel);
      const rows=panel.querySelectorAll('.xstage-tv-queue-row');
      rows[Math.min(index,rows.length-1)]?.querySelector('button')?.focus?.({preventScroll:true});
      if(!rows.length)panel.querySelector('#xstage-tv-queue-close')?.focus?.({preventScroll:true});
    });
    row.append(info,controls);list.append(row);
  });
}
function xstageTvQueuePanel(){
  let panel=document.getElementById('xstage-tv-queue-panel');
  if(panel)return panel;
  panel=document.createElement('section');
  panel.id='xstage-tv-queue-panel';panel.className='xstage-tv-queue-panel';
  panel.hidden=true;
  panel.setAttribute('role','dialog');panel.setAttribute('aria-modal','true');
  panel.setAttribute('aria-label','จัดการคิวเพลงบนทีวี');
  panel.innerHTML='<div class="xstage-tv-queue-box">'+
    '<h2>คิวเพลง · X-Stage Karaoke</h2>'+
    '<div id="xstage-tv-queue-status" role="status" aria-live="polite"></div>'+
    '<div id="xstage-tv-queue-items" class="xstage-tv-queue-items"></div>'+
    '<button type="button" id="xstage-tv-queue-close">กลับสู่เมนูทีวี</button>'+
    '</div>';
  document.body.append(panel);
  panel.querySelector('#xstage-tv-queue-close').addEventListener('click',()=>xstageTvCloseQueue(true));
  return panel;
}
function xstageTvCloseQueue(returnToMenu=false){
  const panel=document.getElementById('xstage-tv-queue-panel');
  if(!panel||panel.hidden)return;
  panel.hidden=true;
  if(returnToMenu)window.XStageTvOpenMenu?.();
}
function xstageTvOpenQueue(){
  if(!document.body.classList.contains('xstage-native-tv'))return false;
  const panel=xstageTvQueuePanel();
  document.getElementById('xstage-tv-quick-menu')?.setAttribute('hidden','');
  xstageTvRenderQueue(panel);
  panel.hidden=false;
  panel.querySelector('#xstage-tv-queue-items button:not([disabled]),#xstage-tv-queue-close')
    ?.focus?.({preventScroll:true});
  return true;
}
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
    '<p>ใช้ลูกศรเลือกคำสั่ง กด OK เพื่อยืนยัน · ใช้ฐานเพลงเดียวกับ Karaoke Online</p>'+
    '<div class="xstage-tv-quick-summary" role="status" aria-live="polite">'+
      '<span id="xstage-tv-quick-now" class="xstage-tv-quick-now">ยังไม่มีเพลงที่กำลังเล่น</span>'+
      '<span id="xstage-tv-quick-key" class="xstage-tv-quick-key">คีย์ —</span>'+
      '<span id="xstage-tv-quick-queue-count">คิวถัดไป 0 เพลง</span>'+
      '<ol id="xstage-tv-quick-queue-list" class="xstage-tv-quick-queue-list"></ol>'+
    '</div>'+
    '<div class="xstage-tv-quick-actions">'+
    '<button type="button" id="xstage-tv-quick-login">เข้าสู่ระบบ Google Drive</button>'+
    '<button type="button" id="xstage-tv-quick-search">ค้นหาเพลงบนทีวี</button>'+
    '<button type="button" id="xstage-tv-quick-queue">จัดการคิวเพลง</button>'+
    '<button type="button" id="xstage-tv-quick-qr">แสดง QR รีโมทมือถือ</button>'+
    '<button type="button" id="xstage-tv-quick-new-qr">สร้าง QR ใหม่</button>'+
    '<button type="button" id="xstage-tv-quick-play">เล่น / พักเพลง</button>'+
    '<button type="button" id="xstage-tv-quick-previous">เพลงก่อนหน้า</button>'+
    '<button type="button" id="xstage-tv-quick-next">เพลงถัดไป</button>'+
    '<button type="button" id="xstage-tv-quick-restart">เริ่มเพลงใหม่</button>'+
    '<button type="button" id="xstage-tv-quick-key-down">ลดคีย์ MIDI −</button>'+
    '<button type="button" id="xstage-tv-quick-key-up">เพิ่มคีย์ MIDI +</button>'+
    '<button type="button" id="xstage-tv-quick-update">ตรวจสอบอัปเดต</button>'+
    '<button type="button" id="xstage-tv-quick-refresh">รีเฟรชหน้าจอทีวี</button>'+
    '<button type="button" id="xstage-tv-quick-home">เพิ่มไอคอนลงหน้าหลักทีวี</button>'+
    '<button type="button" id="xstage-tv-quick-close">กลับสู่เวที</button>'+
    '</div></div>';
  document.body.append(panel);
  panel.querySelector('#xstage-tv-quick-login').addEventListener('click',()=>{
    panel.hidden=true;
    if(!state.token)startAndroidTvDeviceLogin(false);
  });
  panel.querySelector('#xstage-tv-quick-search').addEventListener('click',()=>xstageTvOpenSearch());
  panel.querySelector('#xstage-tv-quick-queue').addEventListener('click',()=>xstageTvOpenQueue());
  panel.querySelector('#xstage-tv-quick-qr').addEventListener('click',()=>{
    window.XStageRemoteQr?.show(true);
    panel.hidden=true;
  });
  panel.querySelector('#xstage-tv-quick-new-qr').addEventListener('click',()=>{
    panel.hidden=true;
    window.XStageRemoteQr?.retry?.();
  });
  for(const [quickId,controlId] of [
    ['xstage-tv-quick-play','play-pause'],
    ['xstage-tv-quick-previous','previous'],
    ['xstage-tv-quick-next','next'],
    ['xstage-tv-quick-restart','restart-current'],
    ['xstage-tv-quick-key-down','midi-key-down'],
    ['xstage-tv-quick-key-up','midi-key-up']
  ]){
    panel.querySelector('#'+quickId).addEventListener('click',()=>{
      const control=document.getElementById(controlId);
      if(control&&!control.disabled)control.click();
      panel.hidden=true;
    });
  }
  panel.querySelector('#xstage-tv-quick-update').addEventListener('click',()=>{
    panel.hidden=true;
    void triggerImmediateVersionUpdate();
  });
  panel.querySelector('#xstage-tv-quick-refresh').addEventListener('click',()=>{panel.hidden=true;window.XStageTvRefreshPage?.();});
  panel.querySelector('#xstage-tv-quick-home').addEventListener('click',()=>{panel.hidden=true;try{window.XStageAndroid?.requestHomeIcon?.();}catch{} });
  panel.querySelector('#xstage-tv-quick-close').addEventListener('click',()=>{panel.hidden=true;});
  return panel;
}
window.XStageTvOpenMenu=()=>{
  if(!document.body.classList.contains('xstage-native-tv'))return false;
  if(['xstage-tv-search-panel','xstage-tv-queue-panel'].some(id=>{
    const modal=document.getElementById(id);return modal&&!modal.hidden;
  }))return false;
  if(['android-tv-auth-panel','android-tv-update-panel'].some(id=>{
    const element=document.getElementById(id);
    return element&&!element.hidden&&
      !(id==='android-tv-update-panel'&&element.classList.contains('during-playback'));
  }))return false;
  const panel=xstageTvQuickMenu();
  panel.hidden=!panel.hidden;
  if(!panel.hidden){
    xstageTvRefreshQuickMenu(panel);
    panel.querySelector('button:not([hidden]):not([disabled])')?.focus?.({preventScroll:true});
  }
  return true;
};
window.XStageTvHandleBack=()=>{
  const queue=document.getElementById('xstage-tv-queue-panel');
  if(queue&&!queue.hidden){xstageTvCloseQueue(true);return true;}
  const search=document.getElementById('xstage-tv-search-panel');
  if(search&&!search.hidden){xstageTvCloseSearch(true);return true;}
  const menu=document.getElementById('xstage-tv-quick-menu');
  if(menu&&!menu.hidden){menu.hidden=true;return true;}
  const update=document.getElementById('android-tv-update-panel');
  if(update&&!update.hidden){document.getElementById('android-tv-update-later')?.click();return true;}
  const auth=document.getElementById('android-tv-auth-panel');
  if(auth&&!auth.hidden){
    const cancel=document.getElementById('android-tv-auth-cancel');
    if(cancel&&!cancel.hidden){cancel.click();return true;}
    return false;
  }
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
    if(scope.id==='xstage-tv-search-panel'){
      const first=scope.querySelector('#xstage-tv-search-results button:not([disabled])');
      if(first){active.blur?.();first.focus({preventScroll:true});}
      return true;
    }
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
  // Native WebView lets a focused TV search input edit its caret normally.
  if((event.key==='ArrowLeft'||event.key==='ArrowRight')&&
     event.target?.matches?.('input,textarea,[contenteditable="true"]'))return;
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
    const id=String(map?.[sub]||'');
    return isRetiredDriveRoot(id)?'':id;
  }catch{return '';}
}
function savePreferredLibraryRoot(sub,rootId){
  if(!sub||!rootId||isRetiredDriveRoot(rootId))return;
  try{
    const map=JSON.parse(localStorage.getItem(LIBRARY_PREF_KEY)||'{}');
    map[sub]=String(rootId);
    localStorage.setItem(LIBRARY_PREF_KEY,JSON.stringify(map));
  }catch{}
}
function libraryLabel(root){
  const owner=String(root?.owners?.[0]?.emailAddress||'').trim();
  const base=root?.ownedByMe?'คลังของฉัน':owner?'แชร์โดย '+owner:'คลังที่แชร์ให้ฉัน';
  const duplicate=state.availableLibraries.filter(x=>
    String(x.name||driveLayout.root)===String(root?.name||driveLayout.root)).length>1;
  if(!duplicate)return (root?.name||driveLayout.root)+' · '+base;
  let created='';
  try{
    if(root.createdTime&&!Number.isNaN(Date.parse(root.createdTime)))
      created=new Date(root.createdTime).toLocaleString('th-TH',{
        day:'numeric',month:'short',hour:'2-digit',minute:'2-digit',hour12:false});
  }catch{}
  return (root.name||driveLayout.root)+' · '+base+
    (created?' · '+created:'')+' · …'+String(root.id||'').slice(-5);
}
function renderLibrarySelector(roots,activeId){
  state.availableLibraries=Array.isArray(roots)?roots.filter(root=>!isRetiredDriveRoot(root.id)):[];
  if(!ui.librarySelect||!ui.librarySwitcher)return;
  ui.librarySelect.replaceChildren();
  for(const root of state.availableLibraries){
    const option=document.createElement('option');
    option.value=String(root.id||'');
    option.textContent=libraryLabel(root);
    ui.librarySelect.append(option);
  }
  if(activeId)ui.librarySelect.value=String(activeId);
  ui.librarySwitcher.hidden=true;
}
async function loadLatestCachedCatalog(sub,rootId=''){
  if(!sub||isRetiredDriveRoot(rootId))return null;
  try{
    const saved=await catalogStorage('get',libraryCacheOwner(sub,rootId));
    const catalog=saved?.catalog;
    if(saved?.layoutVersion!==6||saved?.format!=='xstage-sqlite3-v1'||
       catalog?.schemaVersion!==1||!Array.isArray(catalog.songs))return null;
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
    if(saved?.generation!==String(pointer.generation)||saved.layoutVersion!==pointer.layoutVersion||
       saved.catalogFileId!==pointer.catalogFileId||
       JSON.stringify(saved.deltaFileIds||[])!==JSON.stringify(pointer.deltaFileIds||[]))return null;
    const catalog=saved.catalog;
    if(saved?.layoutVersion!==6||saved?.format!=='xstage-sqlite3-v1'||
       catalog?.schemaVersion!==1||!Array.isArray(catalog.songs))return null;
    if(Number.isSafeInteger(pointer.songCount)&&catalog.songs.length!==pointer.songCount)return null;
    return catalog;
  }catch{return null;}
}
async function saveCachedCatalog(ownerKey,pointer,catalog){
  if(!ownerKey||!pointer?.generation||!Array.isArray(catalog?.songs))return;
  try{await catalogStorage('put',ownerKey,{
    generation:String(pointer.generation),catalogFileId:pointer.catalogFileId,
    layoutVersion:pointer.layoutVersion,format:pointer.format,
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
const REMEMBERED_ACCOUNT_KEY = 'xstage-google-account-hint-v1';
const ACTIVE_AUTH_KEY = 'xstage-google-token-v2';
const PENDING_AUTH_KEY = 'xstage-google-pending-token-v1';
const LEGACY_ACTIVE_AUTH_KEY = 'xstage-tab-google-token-v1';
const AUTH_EXPIRY_MARGIN_MS = 90_000;
const DRIVE_READ_SCOPE='https://www.googleapis.com/auth/drive.readonly';
const DRIVE_FILE_SCOPE='https://www.googleapis.com/auth/drive.file';
let fullDriveReadToken='';
function hasFullDriveRead(){return !!state.token&&fullDriveReadToken===state.token;}
function rememberedFullDriveRead(sub){
  if(!sub)return false;
  try{return localStorage.getItem('xstage-drive-read-consent:'+sub)==='1';}catch{return false;}
}
function rememberFullDriveRead(sub){
  if(!sub)return;
  try{localStorage.setItem('xstage-drive-read-consent:'+sub,'1');}catch{}
}
function grantedDriveReadAndWrite(result){
  const scopes=new Set(String(result?.scope||'').split(/\s+/));
  return scopes.has(DRIVE_READ_SCOPE)&&scopes.has(DRIVE_FILE_SCOPE);
}
window.XStageDriveReadAccess=hasFullDriveRead;
// Google Identity Services token callbacks can arrive after Safari refocuses.
// Only Google callbacks, an explicit new attempt, or the full timeout can settle a flow.
let webGoogleAuthFlow=null;
function authRecordValid(current){
  return !!(current&&typeof current.token==='string'&&current.token.length>25&&
    typeof current.sub==='string'&&current.sub.length>0&&
    Number.isFinite(current.expiresAt)&&current.expiresAt>Date.now()+AUTH_EXPIRY_MARGIN_MS);
}
function clearActiveAuth(){
  fullDriveReadToken='';
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
  // Keep access tokens tab-scoped; remembered account metadata is separate.
  try{localStorage.removeItem(PENDING_AUTH_KEY);}catch{}
}
function readPendingAuth(){
  try{localStorage.removeItem(PENDING_AUTH_KEY);}catch{}
  for(const store of [(()=>{try{return sessionStorage}catch{return null}})()].filter(Boolean)){
    try{
      const current=JSON.parse(store.getItem(PENDING_AUTH_KEY)||'null');
      if(current&&typeof current.token==='string'&&current.token.length>25&&Number.isFinite(current.expiresAt)&&current.expiresAt>Date.now()+AUTH_EXPIRY_MARGIN_MS)return current;
    }catch{}
  }
  clearPendingAuth();return null;
}
function saveActiveAuth(token,expiresAt,sub){
  if(!authRecordValid({token,expiresAt,sub}))return;
  const readOnly=!!token&&token===fullDriveReadToken;
  const value=JSON.stringify({token,expiresAt,sub,readOnly});
  try{sessionStorage.setItem(ACTIVE_AUTH_KEY,value);}catch{}
  // Never persist bearer credentials across browser sessions. The remembered
  // account is still available for Google reauthorization on the next visit.
  try{localStorage.removeItem(ACTIVE_AUTH_KEY);localStorage.removeItem(LEGACY_ACTIVE_AUTH_KEY);}catch{}
}
function readActiveAuth(){
  const stores=[];
  try{stores.push(sessionStorage);}catch{}
  try{localStorage.removeItem(ACTIVE_AUTH_KEY);localStorage.removeItem(LEGACY_ACTIVE_AUTH_KEY);}catch{}
  for(const store of stores){
    try{
      const current=JSON.parse(store.getItem(ACTIVE_AUTH_KEY)||store.getItem(LEGACY_ACTIVE_AUTH_KEY)||'null');
      if(authRecordValid(current)){
        if(current.readOnly===true&&store===sessionStorage)fullDriveReadToken=current.token;
        return current;
      }
    }catch{}
  }
  clearActiveAuth();return null;
}
function hasRememberedLogin(){try{return localStorage.getItem(REMEMBERED_LOGIN_KEY)==='1';}catch{return false;}}
function rememberedGoogleAccount(){
  if(!hasRememberedLogin())return null;
  try{
    const account=JSON.parse(localStorage.getItem(REMEMBERED_ACCOUNT_KEY)||'null');
    if(!account||typeof account.sub!=='string'||!account.sub||
       typeof account.email!=='string'||!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(account.email))
      return null;
    return {sub:account.sub,email:account.email};
  }catch{return null;}
}
function rememberVerifiedGoogleAccount(account){
  if(!account?.sub||!account?.email_verified)return;
  rememberLogin(true);
  try{localStorage.setItem(REMEMBERED_ACCOUNT_KEY,JSON.stringify({
    sub:String(account.sub),email:String(account.email||'').trim()
  }));}catch{}
}
function rememberLogin(enabled){
  try{
    if(enabled)localStorage.setItem(REMEMBERED_LOGIN_KEY,'1');
    else{
      localStorage.removeItem(REMEMBERED_LOGIN_KEY);
      localStorage.removeItem(REMEMBERED_ACCOUNT_KEY);
    }
  }catch{/* Account hint is optional, never contains a token. */}
}
// MIDI owns its own transport clock. The DOM audio element remains the event
// surface for lyrics, queue, media controls and existing non-MIDI tracks.
// Cue only a verified silent MIDI tail; never cut an audible note or a
// time-coded lyric. The next song must already be fully prepared.
function midiTailHandoffCue(parsed,lyrics){
  const duration=Number(parsed?.duration);
  if(!Number.isFinite(duration)||duration<10||
     !Array.isArray(parsed?.notes)||!parsed.notes.length)return 0;
  let lastNote=0,lastLyric=0;
  for(const note of parsed.notes){
    const end=Number(note?.end);
    if(Number.isFinite(end))lastNote=Math.max(lastNote,end);
  }
  for(const line of Array.isArray(lyrics?.lines)?lyrics.lines:[]){
    for(const value of [line?.startTime,line?.endTime]){
      const time=Number(value);
      if(Number.isFinite(time)&&time>=0)lastLyric=Math.max(lastLyric,time);
    }
    for(const word of Array.isArray(line?.words)?line.words:[]){
      for(const value of [word?.startTime,word?.endTime]){
        const time=Number(value);
        if(Number.isFinite(time)&&time>=0)lastLyric=Math.max(lastLyric,time);
      }
    }
  }
  const lastContent=Math.max(lastNote,lastLyric);
  // Allow the tail/reverb to ring for one second. Ignore short gaps:
  // they are often a deliberate pause in the arrangement.
  return lastContent>0&&duration-lastContent>=2.5
    ?Math.min(duration-.25,lastContent+1):0;
}
const nativePlayer=ui.player;
const midiTransport={
  active:false,position:0,duration:0,handoffAt:0,paused:true,ended:false,seeking:false,audioSeekUntil:0,
  volume:1,rate:1,loop:false,startedAt:0,interval:null,
  emit(name){nativePlayer.dispatchEvent(new Event(name));},
  time(){
    if(this.paused||this.seeking)return this.position;
    // The worklet acknowledges seek messages asynchronously. Hold the
    // requested position briefly so Pause/Resume cannot jump backward.
    if(this.audioSeekUntil){
      const audioTime=Number(state.liveMidiPlayback?.currentTime?.());
      if(Number.isFinite(audioTime)&&Math.abs(audioTime-this.position)<.25)
        this.audioSeekUntil=0;
      else if(performance.now()<this.audioSeekUntil)
        return Math.min(this.duration,
          this.position+(performance.now()-this.startedAt)/1000*this.rate);
      else this.audioSeekUntil=0;
    }
    // Follow the audible sequencer clock, not a wall clock that keeps
    // advancing when a mobile OS temporarily suspends WebAudio.
    const audioTime=state.liveMidiPlayback?.scheduler==='audio-worklet'
      ?Number(state.liveMidiPlayback.currentTime?.()):NaN;
    if(Number.isFinite(audioTime)&&audioTime>=0)
      return Math.max(0,Math.min(this.duration,audioTime));
    return Math.min(this.duration,
      this.position+(performance.now()-this.startedAt)/1000*this.rate);
  },
  finish(){
    // A single natural completion must release the old MIDI engine and
    // advance the queue once, even if both the sequencer and timer notice it.
    if(!this.active||this.ended||this.paused)return false;
    if(this.loop){this.seek(0);return false;}
    this.position=this.duration;this.paused=true;this.ended=true;
    clearInterval(this.interval);this.interval=null;
    this.emit('timeupdate');this.emit('ended');
    return true;
  },
  tick(){
    if(!this.active||this.paused)return;
    // Native AudioWorklet time may stop just short of the parsed MIDI end.
    // A completed sequencer is authoritative, regardless of rounded time.
    if(state.liveMidiPlayback?.scheduler==='audio-worklet'&&
       state.liveMidiPlayback?.finished?.()===true){
      this.finish();return;
    }
    const now=this.time();
    if(now>=this.duration){
      if(this.loop){this.seek(0);return;}
      this.finish();
    }else{
      // Skip MIDI's confirmed empty end only when the successor is already
      // prepared. Otherwise let the song finish and use the SF2 handoff.
      const successorReady=state.queue?.length
        ?state.queuePreparedCache?.has(state.queue[0])
        :state.medley&&state.medleyCache?.song===state.medleyUpcoming;
      if(!this.loop&&this.handoffAt>0&&now>=this.handoffAt&&successorReady){
        this.finish();return;
      }
      this.emit('timeupdate');
    }
  },
  play(){
    if(this.ended){this.position=0;this.ended=false;}
    if(!this.paused)return Promise.resolve();
    this.paused=false;this.startedAt=performance.now();this.emit('play');
    this.interval=setInterval(()=>this.tick(),100);
    this.emit('playing');return Promise.resolve();
  },
  pause(){
    if(this.paused)return;
    this.position=this.time();this.paused=true;
    clearInterval(this.interval);this.interval=null;this.emit('pause');
  },
  seek(value){
    this.position=Math.max(0,Math.min(this.duration,Number(value)||0));
    this.startedAt=performance.now();this.ended=false;
    this.audioSeekUntil=performance.now()+1200;
    this.seeking=true;
    try{this.emit('seeking');this.emit('seeked');}
    finally{this.seeking=false;}
    this.emit('timeupdate');
  },
  clear(){
    this.pause();this.active=false;this.position=0;this.duration=0;this.handoffAt=0;
    this.ended=false;this.seeking=false;this.audioSeekUntil=0;clearInterval(this.interval);this.interval=null;
  },
  begin(duration,handoffAt=0){
    nativePlayer.pause();nativePlayer.removeAttribute('src');
    this.clear();this.active=true;this.duration=duration;
    this.handoffAt=Math.max(0,Math.min(duration-.25,Number(handoffAt)||0));this.paused=true;
    this.emit('loadedmetadata');this.emit('durationchange');
  }
};
const player=new Proxy(nativePlayer,{
  get(target,prop){
    if(midiTransport.active){
      if(prop==='src')return 'midi:live';
      if(prop==='currentTime')return midiTransport.time();
      if(prop==='duration')return midiTransport.duration;
      if(prop==='paused')return midiTransport.paused;
      if(prop==='ended')return midiTransport.ended;
      if(prop==='readyState')return 4;
      if(prop==='volume')return midiTransport.volume;
      if(prop==='playbackRate')return midiTransport.rate;
      if(prop==='loop')return midiTransport.loop;
      if(prop==='play')return ()=>midiTransport.play();
      if(prop==='pause')return ()=>midiTransport.pause();
      if(prop==='load')return ()=>{};
      if(prop==='removeAttribute')return name=>{
        if(name==='src'){midiTransport.clear();target.removeAttribute('src');}
        else target.removeAttribute(name);
      };
    }
    const value=Reflect.get(target,prop,target);
    return typeof value==='function'?value.bind(target):value;
  },
  set(target,prop,value){
    if(midiTransport.active){
      if(prop==='currentTime'){midiTransport.seek(value);return true;}
      if(prop==='volume'){midiTransport.volume=Math.max(0,Math.min(1,Number(value)||0));return true;}
      if(prop==='playbackRate'){midiTransport.position=midiTransport.time();midiTransport.rate=Number(value)||1;midiTransport.startedAt=performance.now();midiTransport.emit('ratechange');return true;}
      if(prop==='loop'){midiTransport.loop=!!value;return true;}
    }
    if(prop==='src'&&midiTransport.active)midiTransport.clear();
    return Reflect.set(target,prop,value,target);
  }
});

// Lighting and stage EQ must follow the same transport clock as the audible
// song. During MIDI playback the HTMLMediaElement is deliberately paused, so
// reading nativePlayer.paused/currentTime would always blank or freeze the LEDs.
window.XStageStagePlaybackClock=()=>({
  midi:midiTransport.active,
  playing:!player.paused&&!player.ended,
  currentTime:Number(player.currentTime)||0,
  muted:!!player.muted,
  volume:Number(player.volume)||0
});

// Only the currently attached MIDI synthesizer may complete a song. A
// delayed end event from a replaced SoundFont must never skip the next item.
function attachProfessionalMidiEngine(prepared,options){
  let active=null;
  const onEnded=()=>{
    if(state.liveMidiPlayback!==active||!midiTransport.active||
       midiTransport.paused||state.loading||state.userStopped||state.userPaused)return;
    midiTransport.finish();
  };
  active=prepared.attach(player,{...options,onEnded});
  return active;
}

const karaokeVideo = document.getElementById('karaoke-video');
const videoLyricsToggle=document.getElementById('video-lyrics-toggle');
const videoOriginalToggle=document.getElementById('video-original-toggle');
let videoObjectUrl='',videoLoadRevision=0;
let videoLyricsVisible=true,preferOriginalVideo=true,videoWasOriginal=false;
function originalVideoSupported(song){
  if(!karaokeVideo||!getFileId(song?.originalVideo)||!getFileId(song?.video)||
      getFileId(song.originalVideo)===getFileId(song.video))return false;
  const mime=window.XStageImportCore?.videoMime(song.originalVideo.path||'')||'';
  return !!(mime&&karaokeVideo.canPlayType(mime));
}
function updateOriginalVideoToggle(song){
  if(!videoOriginalToggle)return;
  const hasOriginal=!!getFileId(song?.originalVideo)&&
    getFileId(song.originalVideo)!==getFileId(song?.video);
  videoOriginalToggle.hidden=!hasOriginal;
  const supported=originalVideoSupported(song);
  videoOriginalToggle.disabled=!supported;
  videoOriginalToggle.title=supported
    ?'สลับภาพจากไฟล์ต้นฉบับกับ MP4 ที่เข้ากันได้ · เสียงใช้แทร็กหลัก'
    :'เบราว์เซอร์นี้ถอดรหัสวิดีโอต้นฉบับไม่ได้ · ใช้ MP4 และเก็บต้นฉบับบน Drive';
  videoOriginalToggle.setAttribute('aria-pressed',String(videoWasOriginal));
  videoOriginalToggle.textContent=hasOriginal
    ?videoWasOriginal?'ภาพวิดีโอ: ต้นฉบับ':'ภาพวิดีโอ: MP4':'';
}
function updateVideoLyricsToggle(){
  if(!videoLyricsToggle)return;
  const timed=!!state.lyrics?.lines?.length;
  videoLyricsToggle.hidden=!(karaokeVideo&&!karaokeVideo.hidden&&timed);
  videoLyricsToggle.setAttribute('aria-pressed',String(videoLyricsVisible));
  videoLyricsToggle.textContent=videoLyricsVisible?'เนื้อร้อง: แสดง':'เนื้อร้อง: ซ่อน';
  ui.stage.classList.toggle('video-lyrics-off',!videoLyricsVisible&&timed);
}
videoLyricsToggle?.addEventListener('click',()=>{
  videoLyricsVisible=!videoLyricsVisible;
  updateVideoLyricsToggle();
});
videoOriginalToggle?.addEventListener('click',()=>{
  const song=state.current;
  if(!song||!state.token||!originalVideoSupported(song))return;
  preferOriginalVideo=!preferOriginalVideo;
  resetSongVideo();
  void loadSongVideo(song,state.requestId,state.token,undefined,{forceCompatible:!preferOriginalVideo});
});
function resetSongVideo(){
  videoLoadRevision++;
  if(!karaokeVideo)return;
  videoLyricsVisible=true;videoWasOriginal=false;
  videoLyricsToggle&&(videoLyricsToggle.hidden=true);
  videoOriginalToggle&&(videoOriginalToggle.hidden=true);
  ui.stage.classList.remove('video-lyrics-off');
  karaokeVideo.pause();
  karaokeVideo.hidden=true;
  karaokeVideo.removeAttribute('src');
  karaokeVideo.load();
  if(videoObjectUrl){URL.revokeObjectURL(videoObjectUrl);videoObjectUrl='';}
  state.activeVideoBytes=0;
}
function syncSongVideo(){
  if(!karaokeVideo||karaokeVideo.hidden||!karaokeVideo.src)return;
  karaokeVideo.playbackRate=player.playbackRate;
  if(Number.isFinite(player.currentTime)&&
      Math.abs((karaokeVideo.currentTime||0)-player.currentTime)>.45){
    try{karaokeVideo.currentTime=player.currentTime;}catch{}
  }
  if(player.paused||player.ended){karaokeVideo.pause();}
  else if(karaokeVideo.paused)karaokeVideo.play().catch(()=>{
    // Playback keeps using verified audio if the source video is unavailable.
  });
}
async function loadSongVideo(song,request,token,signal,{forceCompatible=false}={}){
  if(!karaokeVideo||!getFileId(song?.video))return;
  const useOriginal=!forceCompatible&&preferOriginalVideo&&originalVideoSupported(song);
  const media=useOriginal?song.originalVideo:song.video;
  const revision=++videoLoadRevision;
  try{
    if(request!==state.requestId||signal?.aborted)return;
    if(getFileId(media)===getFileId(song.audio)&&state.objectUrl){
      karaokeVideo.src=state.objectUrl;
    }else{
      const response=useOriginal
        ?await privateFile(song.originalVideo.fileId,token,{signal})
        :await privateFile(song.video.fileId,token,{signal});
      const data=await response.blob();
      if(revision!==videoLoadRevision||request!==state.requestId||
          signal?.aborted||token!==state.token||state.current!==song)return;
      if(data.size<1024)throw Error('วิดีโอว่างเปล่า');
      const mime=window.XStageImportCore?.videoMime(media.path||'')||
        (String(media.path||'').toLowerCase().endsWith('.webm')?'video/webm':'video/mp4');
      if(videoObjectUrl)URL.revokeObjectURL(videoObjectUrl);
      videoObjectUrl=URL.createObjectURL(data.type===mime?data:new Blob([data],{type:mime}));
      state.activeVideoBytes=data.size;
      trimQueueCache();
      karaokeVideo.src=videoObjectUrl;
    }
    if(revision!==videoLoadRevision||request!==state.requestId)return;
    videoWasOriginal=useOriginal;
    karaokeVideo.muted=true;
    karaokeVideo.hidden=false;
    karaokeVideo.load();
    updateOriginalVideoToggle(song);
    updateVideoLyricsToggle();
    syncSongVideo();
  }catch(error){
    if(revision!==videoLoadRevision||request!==state.requestId||signal?.aborted)return;
    if(useOriginal){
      preferOriginalVideo=false;
      resetSongVideo();
      void loadSongVideo(song,request,token,signal,{forceCompatible:true});
      return;
    }
    resetSongVideo();
    console.warn('Video unavailable; using verified audio + timed lyrics:',error.message);
  }
}
if(karaokeVideo){
  karaokeVideo.addEventListener('loadedmetadata',()=>{updateVideoLyricsToggle();syncSongVideo();});
  karaokeVideo.addEventListener('canplay',syncSongVideo);
  karaokeVideo.addEventListener('error',()=>{
    if(videoWasOriginal&&state.current&&state.token){
      const song=state.current;
      preferOriginalVideo=false;resetSongVideo();
      setPlayStatus('Codec ต้นฉบับเล่นไม่ได้ · เปลี่ยนกลับเป็น MP4 อัตโนมัติ');
      void loadSongVideo(song,state.requestId,state.token,undefined,{forceCompatible:true});
      return;
    }
    console.warn('Video codec unsupported: using audio and available lyrics where possible');
    if(state.current?.lyricsMode==='embedded-video'||state.lyrics?.lyricsMode==='embedded-video')
      setPlayStatus('เบราว์เซอร์ไม่รองรับ Codec ของวิดีโอนี้ · ให้แปลงเป็น H.264/AAC MP4');
    resetSongVideo();
  });
}

function karaokeOutputGain(){
  // A paired Windows companion owns master volume; keep web/MIDI gain at
  // unity when linked, rather than attenuating the same signal twice.
  return window.XStageWindowsVolumeBridge?.connected?1:
    Math.max(0,Math.min(100,Number(ui.volume.value)||0))/100;
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
async function boundedPlaybackTask(task,seconds,message,controller=null){
  let timer;
  try{
    return await Promise.race([task,new Promise((_,reject)=>{
      timer=setTimeout(()=>{reject(Error(message));controller?.abort();},seconds*1000);
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
// PC-created catalogs preserve the same IDs/paths but Google Drive for
// desktop cannot expose API file IDs. Bind on *first playback* by walking the
// selected XStageKaraoke root and verifying exact path, bytes and package MD5.
async function resolvePcDriveLink(song,token,signal){
  if(song?.pendingDriveLink!==true)return;
  const media= song?.xmid?.path&&!getFileId(song.xmid)?song.xmid:
               song?.xsk?.path&&!getFileId(song.xsk)?song.xsk:null;
  if(!media)return;
  const root=state.libraryRootId;
  if(!root||!token)throw Error('กรุณาเชื่อมคลัง XStageKaraoke บน Google Drive');
  const raw=String(media.path||'').replace(/\\/g,'/');
  const parts=raw.split('/');
  if(parts[0]!=='SONGS'||parts.length<3||parts.length>20||
    parts.some(part=>!part||part==='.'||part==='..'||part.includes(':')))
    throw Error('ตำแหน่งเพลงจากฐาน PC ไม่ปลอดภัย: '+raw);
  const expected=String(media.md5Checksum||'').toLowerCase();
  const expectedSize=Number(media.size);
  if(!/^[0-9a-f]{32}$/.test(expected)||!Number.isSafeInteger(expectedSize)||expectedSize<1)
    throw Error('ฐาน PC ไม่มี MD5 และขนาดไฟล์ต้นฉบับสำหรับยืนยัน');
  const queryName=name=>name.replace(/\\/g,'\\\\').replace(/'/g,"\\'");
  const folderMime='application/vnd.google-apps.folder';
  let parent=root;
  for(let i=0;i<parts.length;i++){
    if(signal?.aborted)throw new DOMException('ยกเลิก','AbortError');
    if(token!==state.token)throw Error('บัญชี Google เปลี่ยนระหว่างตรวจเพลง');
    const name=parts[i],isFile=i===parts.length-1;
    const list=await driveList(
      "'"+parent+"' in parents and name='"+queryName(name)+"' and trashed=false",token);
    const matches=list.filter(item=>item.name===name&&
      item.parents?.includes(parent)&&
      (isFile?item.mimeType!==folderMime:item.mimeType===folderMime));
    if(matches.length!==1)
      throw Error('พบไฟล์หรือโฟลเดอร์ซ้ำ/ไม่พบใน XStageKaraoke: '+raw+
        ' · ตรวจ Google Drive for desktop แล้วอัปเดตฐานเพลง');
    const selected=matches[0];
    if(isFile){
      if(Number(selected.size)!==expectedSize||
        String(selected.md5Checksum||'').toLowerCase()!==expected)
        throw Error('ไฟล์บน Google Drive ไม่ตรงกับเพลงในฐาน PC (ขนาด/MD5): '+raw);
      if(!/^[A-Za-z0-9_-]{5,256}$/.test(String(selected.id||'')))
        throw Error('Google Drive File ID ของเพลงไม่ถูกต้อง');
      media.fileId=selected.id;
      song.pendingDriveLink=false;
    }else{
      parent=selected.id;
    }
  }
}
function playable(song) {
  // XSK2 is a complete, self-describing media+lyrics package on Drive.
  // Old catalog pairs remain supported without migration.
  return !!((song?.pendingDriveLink===true&&
      (song?.xmid?.path||song?.xsk?.path))||
    getFileId(song?.xmid) || getFileId(song?.xsk) ||
    (getFileId(song?.midi) && song?.sourceFormat==='KAR') ||
    (getFileId(song?.lyrics) && (getFileId(song?.audio) || getFileId(song?.midi))));
}
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
  // A Drive 404 is not proof that Google login expired: drive.file only grants
  // access to files created or explicitly opened with this OAuth application.
  const message=status===401?'สิทธิ์ Google หมดอายุ กรุณาเข้าสู่ระบบอีกครั้ง':
    status===403?'บัญชีนี้ไม่มีสิทธิ์เข้าถึง '+subject+' (ตรวจสิทธิ์ drive.file และบัญชีที่ซิงก์)':
    status===404?'แอปยังไม่ได้รับสิทธิ์อ่าน '+subject+' (HTTP 404) · ไฟล์อาจยังอยู่ใน Google Drive · ใช้การนำเข้าผ่าน X-Stage Karaoke Online เพื่ออนุญาตไฟล์':
    `อ่าน ${subject} ไม่สำเร็จ (HTTP ${status})`;
  const error=new Error(message);
  error.driveStatus=status;error.driveSubject=subject;
  return error;
}
async function driveList(q, token) {
  // Google Drive files.list can return fewer than pageSize results and provide
  // nextPageToken even for a page with no files. Never treat one page as a
  // complete library: a partial listing could select the wrong Drive root.
  const files = [];
  const seenPageTokens = new Set();
  let pageToken = '';
  do {
    const params = new URLSearchParams({q,fields:'nextPageToken,files(id,name,mimeType,parents,ownedByMe,createdTime,modifiedTime,md5Checksum,size,sharedWithMeTime,capabilities(canShare),owners(displayName,emailAddress))',pageSize:'1000'});
    if (pageToken) params.set('pageToken',pageToken);
    const result = await googleFetch(`https://www.googleapis.com/drive/v3/files?${params}`,
      {headers: requestHeaders(token),cache:'no-store'},'Google Drive');
    if (!result.ok) throw driveError(result.status, 'รายการไฟล์');
    const json = await result.json();
    if (!json || (json.files != null && !Array.isArray(json.files)) ||
        (json.nextPageToken != null && typeof json.nextPageToken !== 'string'))
      throw Error('Google Drive ส่งรายการไฟล์ที่มีโครงสร้างไม่ถูกต้อง');
    files.push(...(json.files || []));
    if (files.length > 300000)
      throw Error('Google Drive มีไฟล์มากเกินขีดจำกัด 300,000 รายการต่อการค้นหา');
    const next = json.nextPageToken || '';
    if (next && seenPageTokens.has(next))
      throw Error('Google Drive ส่งรหัสหน้าผลการค้นหาซ้ำ · หยุดเพื่อป้องกันการอ่านไม่ครบ');
    if (next) seenPageTokens.add(next);
    pageToken = next;
  } while (pageToken);
  return files;
}
async function selectedDriveRootById(id, token) {
  if(!/^[A-Za-z0-9_-]{5,256}$/.test(String(id||''))||isRetiredDriveRoot(id))
    throw Error('Folder ID ของคลังเพลงไม่ปลอดภัยหรือถูกยกเลิก');
  const fields='id,name,mimeType,trashed,parents,ownedByMe,createdTime,modifiedTime,capabilities(canShare),owners(displayName,emailAddress)';
  const response=await googleFetch(
    'https://www.googleapis.com/drive/v3/files/'+encodeURIComponent(id)+
    '?fields='+encodeURIComponent(fields),
    {headers:requestHeaders(token),cache:'no-store'},'โฟลเดอร์หลัก');
  if(!response.ok)throw driveError(response.status,'โฟลเดอร์หลักที่เลือก');
  const item=await response.json();
  if(item.id!==id||item.mimeType!=='application/vnd.google-apps.folder'||item.trashed)
    throw Error('Folder ID ไม่ใช่โฟลเดอร์หลักที่ใช้งานได้');
  return item;
}
async function privateFile(id, token, opts = {}) {
  const r = await googleFetch(`https://www.googleapis.com/drive/v3/files/${encodeURIComponent(id)}?alt=media`, {
    headers: requestHeaders(token), cache:'no-store',signal:opts.signal
  },'Google Drive');
  if (!r.ok) throw driveError(r.status, 'ไฟล์เพลงส่วนตัว');
  return r;
}
// High-throughput private Drive reads for bounded media files. Parallel
// requests are permitted only when Google returns *exact* 206 byte ranges.
// Otherwise fall back to the original single HTTP stream, with no truncation.
const FAST_DOWNLOAD_MIB=1024*1024;
function fastDownloadParts(bytes){
  if(!Number.isSafeInteger(bytes)||bytes<24*FAST_DOWNLOAD_MIB||
     bytes>192*FAST_DOWNLOAD_MIB||navigator.connection?.saveData)return 1;
  if(Number(navigator.deviceMemory||4)<=2)return 1;
  const mobile=/Android|iPhone|iPad|iPod/i.test(navigator.userAgent||'');
  return mobile?2:bytes>=64*FAST_DOWNLOAD_MIB?4:2;
}
async function fastPrivateBlob(id,token,opts={}){
  const size=Number(opts.size);
  const parts=fastDownloadParts(size);
  if(parts===1)return (await privateFile(id,token,opts)).blob();
  const url='https://www.googleapis.com/drive/v3/files/'+encodeURIComponent(id)+'?alt=media';
  const controller=new AbortController();
  const abort=()=>controller.abort();
  if(opts.signal?.aborted)throw new DOMException('Aborted','AbortError');
  opts.signal?.addEventListener?.('abort',abort,{once:true});
  const step=Math.ceil(size/parts/(256*1024))*(256*1024);
  const ranges=[];
  for(let from=0;from<size;from+=step)ranges.push([from,Math.min(size-1,from+step-1)]);
  try{
    const results=await Promise.allSettled(ranges.map(async([from,to])=>{
      const response=await googleFetch(url,{
        headers:{...requestHeaders(token),Range:'bytes='+from+'-'+to},
        signal:controller.signal,cache:'no-store'
      },'Google Drive',1);
      if(response.status===401||response.status===403||response.status===404){
        const error=driveError(response.status,'ไฟล์เพลงส่วนตัว');
        error.driveStatus=response.status;
        throw error;
      }
      if(response.status!==206){
        try{await response.body?.cancel?.();}catch{}
        throw Error('Google Drive ไม่รองรับการแบ่งช่วงไฟล์');
      }
      const range=String(response.headers?.get?.('Content-Range')||'');
      const match=range.match(/^bytes (\d+)-(\d+)\/(\d+)$/);
      if(!match||Number(match[1])!==from||Number(match[2])!==to||
         Number(match[3])!==size){
        try{await response.body?.cancel?.();}catch{}
        throw Error('Google Drive ส่ง Content-Range ไม่ตรงคำขอ');
      }
      const data=await response.arrayBuffer();
      if(data.byteLength!==to-from+1)
        throw Error('Google Drive ส่งข้อมูลช่วงไฟล์ไม่ครบ');
      return new Uint8Array(data);
    }));
    if(opts.signal?.aborted)throw new DOMException('Aborted','AbortError');
    const fatal=results.find(item=>item.status==='rejected'&&
      [401,403,404].includes(item.reason?.driveStatus));
    if(fatal)throw fatal.reason;
    if(results.some(item=>item.status==='rejected'))
      return (await privateFile(id,token,opts)).blob();
    const combined=new Blob(results.map(item=>item.value));
    if(combined.size!==size)
      throw Error('Google Drive คืนขนาดไฟล์ไม่ตรงฐานข้อมูล');
    return combined;
  }finally{
    opts.signal?.removeEventListener?.('abort',abort);
    controller.abort();
  }
}

async function privateJson(id, token, opts) {
  const response = await privateFile(id, token, opts);
  try { return await response.json(); }
  catch { throw Error('ไฟล์ JSON บน Drive ไม่ถูกต้อง'); }
}

function sharedLibraryFeatureReady(){return true;}
window.XStageSharedLibraryReady=sharedLibraryFeatureReady;
function setSharedLibraryGate(active,message=''){
  const button=$('gate-shared-library');
  const copy=$('gate-copy');
  const footnote=$('gate-footnote');
  state.awaitingSharedLibrary=!!active;
  if(active){
    ui.gate.hidden=false;
    ui.gateLogin.hidden=true;
    const ready=!!state.token;
    if(button){
      button.hidden=false;
      button.disabled=!ready;
      button.textContent=ready?'เลือกหรือสร้างคลังเพลง Google Drive':'เชื่อม Google ก่อนเลือกคลัง';
    }
    if(copy)copy.textContent=ready
      ? 'เลือกโฟลเดอร์เดิมหรือสร้างคลังชื่อใหม่ได้ · ยึด Folder ID ไม่ใช่ชื่อ'
      : 'เชื่อม Google ก่อนเลือกคลังหลัก';
    if(footnote)footnote.textContent=ready
      ? 'แสดงและใช้งานเฉพาะคลังหลักที่เลือก · ไม่คัดลอกไฟล์'
      : 'ไม่คัดลอกเพลงและไม่เปิดคลังอื่นอัตโนมัติ';
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
$('xstage-soundfont-authorize')?.addEventListener('click',async()=>{
  const status=$('xstage-drive-font-permission-status');
  const sub=state.accountSub,rootId=state.libraryRootId;
  try{
    const choice=window.XStageDriveFolders?.readSelections?.(sub,rootId)?.soundfont;
    if(!sub||!rootId||!state.token)throw Error('เชื่อม Google Drive และเปิดคลังหลักก่อน');
    const drive=new window.XStageCloudImport.Drive(()=>state.token,()=>{});
    // The fixed default folder can be verified even before a saved selection.
    const resolveFontFolder=async()=>{
      const saved=window.XStageDriveFolders?.readSelections?.(sub,rootId)?.soundfont;
      if(saved?.id)return saved.id;
      const matches=(await drive.list("'"+rootId+"' in parents and trashed=false"))
        .filter(x=>String(x.name||'').toUpperCase()==='SOUNDFONT');
      if(matches.length!==1||matches[0].name!=='SOUNDFONT'||
         matches[0].mimeType!=='application/vnd.google-apps.folder')
        throw Error('ตรวจโฟลเดอร์ SOUNDFONT ในคลังหลักก่อนอนุญาตไฟล์');
      return matches[0].id;
    };
    const folderId=choice?.id||await resolveFontFolder();
    await window.XStageDriveFolders.verifyFolder(drive,folderId,rootId,'soundfont');
    await ensureImporterGoogleAuth(true,true,true);
    if(sub!==state.accountSub||rootId!==state.libraryRootId||
       folderId!==await resolveFontFolder())
      throw Error('บัญชีหรือโฟลเดอร์เปลี่ยนระหว่างอนุญาตไฟล์');
    await window.XStageDriveFolders.verifyFolder(drive,folderId,rootId,'soundfont');
    await window.XStageBrowserMidi?.refreshFonts({token:state.token,sub,rootId,ownedByMe:state.libraryRootOwnedByMe});
  }catch(e){if(status)status.textContent=e.message;}
});
// Browse the already granted Drive folders using the current OAuth token.
 // No Google iframe or third-party cookies are needed on iOS/Safari.
async function chooseUserDriveFolder(kind){
  if(!['music','soundfont','fx'].includes(kind))throw Error('ประเภทโฟลเดอร์ไม่ถูกต้อง');
  if(!state.token||!state.accountSub||!state.libraryRootId||
     isRetiredDriveRoot(state.libraryRootId))throw Error('กรุณาเชื่อม Google Drive ก่อน');
  const account=state.accountSub,rootId=state.libraryRootId;
  const sameSession=()=>state.accountSub===account&&state.libraryRootId===rootId&&!!state.token;
  const result=await browseAuthorizedDriveFolders({
    rootId,kind,sameSession,
    list:async id=>{
      if(!sameSession())throw Error('บัญชีหรือคลังเปลี่ยนแล้ว');
      if(!/^[A-Za-z0-9_-]{5,256}$/.test(id)||isRetiredDriveRoot(id))throw Error('Folder ID ไม่ถูกต้อง');
      const folders=await driveList("'"+id+"' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",state.token);
      if(!sameSession())throw Error('บัญชีหรือคลังเปลี่ยนแล้ว');
      return folders;
    },
    allowGrant:!hasFullDriveRead()
  });
  if(result?.grant&&sameSession()){
    await ensureImporterGoogleAuth(true,true,true);
    if(sameSession())return chooseUserDriveFolder(kind);
    return null;
  }
  return result;
}
function browseAuthorizedDriveFolders({rootId,kind,sameSession,list,allowGrant}){
  const labels={music:'เพลง',soundfont:'SoundFont',fx:'FX'};
  return new Promise(resolve=>{
    const dialog=document.createElement('dialog');
    dialog.className='cloud-import-dialog';
    dialog.setAttribute('aria-label','เลือกโฟลเดอร์ '+labels[kind]);
    dialog.style.cssText='width:min(94vw,520px);max-height:82dvh;padding:16px;overflow:auto;background:#0c192b;color:#e7f6ff;border:1px solid #407d92;border-radius:14px';
    const title=document.createElement('h3');title.textContent='เลือกโฟลเดอร์ '+labels[kind];
    const path=document.createElement('p'),status=document.createElement('p'),items=document.createElement('div');
    status.setAttribute('role','status');
    const stack=[{id:rootId,name:'คลังเพลง'}];
    let done=false,sequence=0;
    function button(label,handler,parent=dialog){
      const el=document.createElement('button');el.type='button';el.textContent=label;
      el.style.cssText='display:block;width:100%;margin:8px 0;padding:12px;background:#163748;color:#e7f6ff;border:1px solid #407d92;border-radius:8px;white-space:normal;text-align:left';
      el.addEventListener('click',handler);parent.append(el);return el;
    }
    function finish(value){
      if(done)return;done=true;sequence++;
      if(dialog.open)dialog.close();
      dialog.remove();resolve(value);
    }
    dialog.append(title,path,status);
    const cancel=button('ปิด / ยกเลิก',()=>finish(null));
    const back=button('ย้อนกลับ',()=>{if(stack.length>1){stack.pop();void render();}});
    const select=button('ใช้โฟลเดอร์นี้',()=>{
      if(sameSession()&&stack.length>1)finish({...stack.at(-1)});
    });
    dialog.append(items);
    button('ลองโหลดรายการใหม่',()=>void render());
    if(allowGrant)button('ไม่พบโฟลเดอร์ · ขอสิทธิ์อ่านจาก Google',()=>finish({grant:true}));
    const help=document.createElement('p');
    help.textContent='แสดงเฉพาะโฟลเดอร์ภายในคลังหลักที่เลือก · ย้อนกลับได้ไม่เกินคลังหลัก';
    dialog.append(help);
    dialog.addEventListener('cancel',event=>{event.preventDefault();finish(null);});
    dialog.addEventListener('close',()=>finish(null));
    async function render(){
      if(done)return;
      const current=stack.at(-1),request=++sequence;
      path.textContent=stack.map(x=>x.name).join(' / ');
      items.replaceChildren();back.disabled=stack.length===1;select.disabled=true;
      status.textContent='กำลังอ่านโฟลเดอร์ที่มีสิทธิ์…';
      try{
        if(!sameSession())throw Error('บัญชีหรือคลังเปลี่ยนแล้ว');
        const folders=await list(current.id);
        if(done||request!==sequence)return;
        if(!sameSession())throw Error('บัญชีหรือคลังเปลี่ยนแล้ว');
        const seen=new Set(stack.map(x=>x.id));
        const choices=folders.filter(x=>x.mimeType==='application/vnd.google-apps.folder'&&
          /^[A-Za-z0-9_-]{5,256}$/.test(x.id)&&!isRetiredDriveRoot(x.id)&&
          Array.isArray(x.parents)&&x.parents.includes(current.id)&&!seen.has(x.id)&&!['DB','CACHE','BACKUP','LOGS'].includes(String(x.name).toUpperCase()));
        choices.sort((a,b)=>String(a.name).localeCompare(String(b.name)));
        for(const folder of choices){
          if(seen.has(folder.id))continue;seen.add(folder.id);
          button('📁 '+folder.name,()=>{stack.push({id:folder.id,name:folder.name});void render();},items);
        }
        select.disabled=stack.length===1;
        status.textContent=choices.length?'เลือกโฟลเดอร์หรือเปิดโฟลเดอร์ย่อย':'ไม่พบโฟลเดอร์ย่อยที่แอปมีสิทธิ์อ่าน · สามารถใช้โฟลเดอร์ปัจจุบันได้หากไม่ใช่คลังหลัก';
      }catch(error){
        if(done||request!==sequence)return;
        status.textContent=String(error.message||error);
      }
    }
    document.body.append(dialog);
    try{dialog.showModal();cancel.focus();void render();}
    catch(error){finish(null);}
  });
}
// App-owned picker. Select any existing Drive folder by Folder ID, or create a
// new named root only after user confirmation. Never choose based on name alone.
async function openSharedLibraryPicker(){
  if(!state.token||!state.accountSub){setStatus('กรุณาเข้าสู่ระบบ Google ก่อน','error');return;}
  if(window.XStageDriveBuildBusy||xstageCloudImporter?.running){
    setStatus('กรุณาให้งานนำเข้าหรือสร้างฐานเสร็จก่อนเปลี่ยนคลัง','error');return;
  }
  const account=state.accountSub,previousRoot=state.libraryRootId;
  const sameSession=()=>state.accountSub===account&&state.libraryRootId===previousRoot&&!!state.token;
  const dialog=document.createElement('dialog');dialog.className='cloud-import-dialog';
  dialog.style.cssText='width:min(94vw,600px);max-height:86dvh;padding:17px;overflow:auto;background:#0c192b;color:#e7f6ff;border:1px solid #407d92;border-radius:14px';
  dialog.setAttribute('aria-label','เลือกคลัง Google Drive');
  const title=document.createElement('h3');title.textContent='คลังเพลง Google Drive · เลือกชื่อเองได้';
  const status=document.createElement('p'),crumb=document.createElement('p'),
        items=document.createElement('div');
  status.setAttribute('role','status');
  dialog.append(title,status,crumb);
  const button=(label,action,parent=dialog)=>{
    const el=document.createElement('button');el.type='button';el.textContent=label;
    el.style.cssText='display:block;width:100%;margin:8px 0;padding:11px;background:#163748;color:#e7f6ff;border:1px solid #407d92;border-radius:8px;text-align:left';
    el.addEventListener('click',action);parent.append(el);return el;
  };
  const input=(placeholder,value='')=>{
    const el=document.createElement('input');el.type='text';el.placeholder=placeholder;el.value=value;
    el.style.cssText='display:block;width:100%;padding:11px;box-sizing:border-box;background:#091625;color:#e7f6ff;border:1px solid #407d92;border-radius:7px;margin:9px 0';
    dialog.append(el);return el;
  };
  const stack=[{id:'root',name:'My Drive'}];
  let closed=false,sequence=0,working=false;
  const finish=()=>{if(closed)return;closed=true;sequence++;if(dialog.open)dialog.close();dialog.remove();};
  const parentControl=button('ย้อนกลับ',()=>{
    if(stack.length>1){stack.pop();void render();}
  });
  const selectControl=button('ใช้โฟลเดอร์นี้เป็นคลังหลัก',()=>{
    if(stack.length>1)void activate(stack.at(-1).id);
  });
  dialog.append(items);
  const folderName=input('ตั้งชื่อโฟลเดอร์ใหม่ (ค่าแนะนำ XStageKaraoke)','XStageKaraoke');
  button('สร้างโฟลเดอร์ใหม่ใน My Drive',async()=>{
    const name=folderName.value.trim();
    if(!name||name.length>100||/[/\\\x00-\x1f]/.test(name)||
       ['SONGS','DB','SOUNDFONT','FX','BACKUP','CACHE','LOGS'].includes(name.toUpperCase())){
      status.textContent='ชื่อคลังหลักไม่ถูกต้องหรือชนกับชื่อโฟลเดอร์ระบบ';return;
    }
    if(!window.confirm('สร้างหรือเลือกโฟลเดอร์ชื่อ "'+name+'" ใน My Drive และตั้งค่าโครงสร้าง X-Stage?'))return;
    if(working||!sameSession())return;
    working=true;
    try{
      const Drive=window.XStageCloudImport?.Drive;
      if(!Drive)throw Error('ตัวจัดการ Google Drive ยังไม่พร้อม');
      const drive=new Drive(()=>state.token,()=>{
        if(!sameSession())throw Error('บัญชีหรือคลังเปลี่ยนระหว่างการตั้งค่า');
      });
      drive.ensureAuth=force=>ensureImporterGoogleAuth(force);
      const id=await drive.folder('root',name);
      const actual=await selectedDriveRootById(id,state.token);
      if(actual.name!==name)throw Error('ชื่อโฟลเดอร์ที่ได้ไม่ตรงกับที่ยืนยัน');
      working=false;
      await activate(id);
    }catch(error){if(!closed)status.textContent='ยังไม่ได้ตั้งค่าคลัง: '+error.message;}
    finally{working=false;}
  });
  const folderLink=input('วางลิงก์โฟลเดอร์ Google Drive หรือ Folder ID');
  button('ตรวจและใช้ Folder ID จากลิงก์',async()=>{
    const raw=folderLink.value.trim();
    const id=raw.match(/\/folders\/([A-Za-z0-9_-]{5,256})/)?.[1]||
      (/^[A-Za-z0-9_-]{5,256}$/.test(raw)?raw:'');
    if(!id||isRetiredDriveRoot(id)){status.textContent='Folder ID ไม่ถูกต้องหรือเป็นคลังที่ยกเลิก';return;}
    await activate(id);
  });
  button('รีเฟรชโฟลเดอร์ในตำแหน่งนี้',()=>void render());
  if(!hasFullDriveRead())button('ขอสิทธิ์อ่าน Google Drive เพิ่มเติม',async()=>{
    try{await ensureImporterGoogleAuth(true,true,true);if(sameSession())await render();}
    catch(error){status.textContent=error.message;}
  });
  button('ปิด / ยกเลิก',finish);
  dialog.addEventListener('cancel',event=>{event.preventDefault();finish();});
  dialog.addEventListener('close',finish);
  async function activate(id){
    if(working||closed||!sameSession()||window.XStageDriveBuildBusy)return;
    working=true;status.textContent='กำลังยืนยัน Folder ID และโครงสร้างของคลัง…';
    try{
      const actual=await selectedDriveRootById(id,state.token);
      if(['SONGS','DB','SOUNDFONT','FX','BACKUP','CACHE','LOGS']
          .includes(String(actual.name).toUpperCase()))
        throw Error('กรุณาเลือกโฟลเดอร์หลัก ไม่ใช่ SONGS, DB หรือโฟลเดอร์ระบบ');
      const Drive=window.XStageCloudImport?.Drive;
      if(!Drive)throw Error('ตัวจัดการ Drive ยังไม่พร้อม');
      const drive=new Drive(()=>state.token,()=>{
        if(!sameSession())throw Error('บัญชีหรือคลังเปลี่ยนระหว่างตั้งค่า');
      });
      drive.ensureAuth=force=>ensureImporterGoogleAuth(force);
      if(!hasFullDriveRead()&&actual.ownedByMe!==false)
        await ensureImporterGoogleAuth(true,true,true);
      await window.XStageDriveFolders.ensureLibraryLayout(drive,actual.id,{
        allowCreate:hasFullDriveRead()&&actual.ownedByMe!==false
      });
      if(!sameSession())throw Error('บัญชี Google เปลี่ยนแล้ว');
      savePreferredLibraryRoot(account,actual.id);
      finish();
      if(actual.id===previousRoot){await xstageDriveFolders?.discoverDefaults();return;}
      clearPlaybackResumeState();
      if(previousRoot){location.reload();return;}
      try{await openDrive(state.token,++state.authId,state.tokenExpiresAt,account,false);}
      catch(error){setSharedLibraryGate(true,error.message);}
    }catch(error){if(!closed)status.textContent=String(error.message||error);}
    finally{working=false;}
  }
  async function render(){
    if(closed||!sameSession())return;
    const current=stack.at(-1),request=++sequence;
    crumb.textContent=stack.map(item=>item.name).join(' / ');
    parentControl.disabled=stack.length===1;
    selectControl.disabled=stack.length===1;
    items.replaceChildren();status.textContent='กำลังอ่านโฟลเดอร์ใน Google Drive…';
    try{
      const rows=await driveList("'"+current.id+
        "' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",state.token);
      if(closed||request!==sequence||!sameSession())return;
      const seen=new Set(stack.map(x=>x.id));
      const folders=rows.filter(item=>item.mimeType==='application/vnd.google-apps.folder'&&
        /^[A-Za-z0-9_-]{5,256}$/.test(item.id)&&!isRetiredDriveRoot(item.id)&&
        item.parents?.includes(current.id)&&!seen.has(item.id));
      folders.sort((a,b)=>String(a.name).localeCompare(String(b.name),'th'));
      for(const folder of folders){
        button('เปิด · '+folder.name+' · …'+folder.id.slice(-6),()=>{
          if(stack.length>=10)return;
          stack.push({id:folder.id,name:folder.name});void render();
        },items);
      }
      status.textContent=folders.length
        ?'เลือกโฟลเดอร์ที่มีอยู่ หรือสร้างคลังชื่อใหม่ · Folder ID จะถูกจดจำ'
        :'ไม่มีโฟลเดอร์ย่อยในตำแหน่งนี้ · สามารถสร้างคลังใหม่ได้';
    }catch(error){if(!closed&&request===sequence)status.textContent=error.message;}
  }
  document.body.append(dialog);
  try{dialog.showModal();void render();}
  catch{finish();}
}

$('gate-shared-library')?.addEventListener('click',openSharedLibraryPicker);
$('xstage-drive-main-select')?.addEventListener('click',openSharedLibraryPicker);

// Player reads exclusively XStageKaraoke/DB/songs.sqlite3.

async function readPublishedCatalog(pointer,token,{sub='',onProgress=null}={}){
  if(pointer?.schemaVersion!==1||pointer?.layoutVersion!==6||
     pointer?.directFile!==true||pointer?.format!=='xstage-sqlite3-v1'||
     typeof pointer.catalogFileId!=='string'||!pointer.catalogFileId||
     (pointer.deltaFileIds||[]).length)
    throw Error('X-Stage รองรับเฉพาะ DB/songs.sqlite3 ไฟล์เดียว');
  const totalPieces=1;
  // A single canonical SQLite snapshot is enough; do not retain dozens of
  // decoded copies in RAM after Drive revisions change.
  const rememberCatalog=(key,data)=>{
    state.catalogCache.clear();
    state.catalogCache.set(key,data);
  };
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
    const cacheKey=pointer.directFile?id+':'+pointer.generation+(pointer.catalogMd5?':verified-md5-v1':''):id;
    if(state.catalogCache.has(cacheKey)){report(label+' · พร้อมแล้ว',true);return state.catalogCache.get(cacheKey);}
    const persisted=await loadCatalogPiece(sub,cacheKey);
    if(persisted){
      rememberCatalog(cacheKey,persisted);
      report(label+' · ใช้ส่วนที่โหลดไว้แล้ว',true);
      return persisted;
    }
    const codec=window.XStageDriveSQLite;
    if(!codec)throw Error('ไม่พบตัวอ่าน SQLite3 กรุณาโหลดหน้าเว็บใหม่');
    const response=await privateFile(id,token);
    const maxBytes=192*1048576;
    const advertised=Number(response.headers?.get?.('Content-Length')||0);
    if(advertised>maxBytes){
      try{await response.body?.cancel?.();}catch{}
      throw Error('ฐานข้อมูล SQLite3 ใหญ่เกิน 192 MB');
    }
    // Enforce the existing limit during streaming, not after allocating the
    // entire response. Fallback for browsers without a readable body.
    let bytes;
    if(response.body?.getReader){
      const reader=response.body.getReader();
      const chunks=[];let total=0;
      try{
        for(;;){
          const {done,value}=await reader.read();
          if(done)break;
          total+=value.byteLength;
          if(total>maxBytes)throw Error('ฐานข้อมูล SQLite3 ใหญ่เกิน 192 MB');
          chunks.push(value);
        }
      }catch(error){try{await reader.cancel();}catch{}throw error;}
      finally{reader.releaseLock();}
      bytes=new Uint8Array(total);let offset=0;
      for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.byteLength;}
      chunks.length=0;
    }else{
      const buffer=await response.arrayBuffer();
      if(buffer.byteLength>maxBytes)throw Error('ฐานข้อมูล SQLite3 ใหญ่เกิน 192 MB');
      bytes=new Uint8Array(buffer);
    }
    if(pointer.catalogMd5){
      if(!/^[a-f0-9]{32}$/i.test(pointer.catalogMd5)||
         !window.XStageImportCore?.hashBlob||
         await window.XStageImportCore.hashBlob(new Blob([bytes]))!==pointer.catalogMd5.toLowerCase())
        throw Error('MD5 ฐานเพลงไม่ตรงกับ Drive · ใช้ฐานเดิมก่อน');
    }
    const data=await codec.read(bytes);
    if(data.candidate)throw Error('ฐาน PC ยังไม่ผ่านการเผยแพร่ · ไม่เปิดเป็นฐานหลัก');
    rememberCatalog(cacheKey,data);
    await saveCatalogPiece(sub,cacheKey,data);
    report(label+' · ดาวน์โหลดแล้ว',false);
    return data;
  }
  const base=await fetchImmutable(pointer.catalogFileId,'ฐานหลัก');
  if(base?.schemaVersion!==1||base.kind!=='snapshot'||!Array.isArray(base.songs))
    throw Error('ฐานข้อมูล SQLite3 หลักบน Drive ไม่รองรับ');
  if(!base.generation||typeof base.generation!=='string')
    throw Error('ฐาน SQLite3 ไม่มีรุ่นข้อมูล');
  if(new Set(base.songs.map(song=>song?.webSongId)).size!==base.songs.length)
    throw Error('ฐาน SQLite3 มีรหัสอ้างอิงเพลงซ้ำ');
  return base;
}
// The canonical XStageKaraoke/DB/songs.sqlite3 file IS the manifest.
// File ID/MD5 from the songs.sqlite3 Drive listing identify revisions.
function directCatalogPointer(file){
  if(!file?.id||file.name!=='songs.sqlite3')throw Error('DB/songs.sqlite3 ไม่ถูกต้อง');
  return {schemaVersion:1,layoutVersion:6,format:'xstage-sqlite3-v1',
    directFile:true,catalogFileId:file.id,catalogMd5:String(file.md5Checksum||''),deltaFileIds:[],
    generation:'sqlite:'+file.id+':'+String(file.md5Checksum||file.modifiedTime||file.size||'')};
}
async function activeDriveCatalog(dbId,token){
  if(!dbId)return null;
  const direct=await driveList(`'${dbId}' in parents and name='songs.sqlite3' and trashed=false`,token);
  if(direct.length>1)throw Error('พบ songs.sqlite3 ซ้ำใน DB');
  return direct.length?{pointer:directCatalogPointer(direct[0])}:null;
}
async function pollPublishedCatalog(){
  if(!state.token||!state.catalogDbDirId||state.catalogPolling)return;
  const authId=state.authId,token=state.token;
  const dbId=state.catalogDbDirId,rootId=state.libraryRootId;
  const sameCatalogSession=()=>authId===state.authId&&token===state.token&&
    dbId===state.catalogDbDirId&&rootId===state.libraryRootId;
  state.catalogPolling=true;
  try{
    const published=await activeDriveCatalog(dbId,token);
    const pointer=published?.pointer;
    if(!pointer||!sameCatalogSession()||!pointer.generation||
       pointer.generation===state.catalogGeneration)return;
    const cacheOwner=libraryCacheOwner(state.accountSub,state.libraryRootId);
    const catalog=await readPublishedCatalog(pointer,token,{sub:cacheOwner});
    if(!sameCatalogSession())return;
    const countBefore=state.songs.length;
    state.manifest=catalog;
    state.songs=catalog.songs.filter(playable);
    state.catalogGeneration=pointer.generation;
    state.catalogPointerId='';
    void saveCachedCatalog(cacheOwner,pointer,catalog);
    state.medleyPoolSource=null;
    ui.songTotal.textContent=`${num(state.songs.length)} เพลง`;
    renderSongs();renderQueue();
    ui.libraryState.textContent='Google Drive · '+(state.libraryRootOwnedByMe?'คลังของฉัน':state.libraryRootOwnerEmail?'แชร์โดย '+state.libraryRootOwnerEmail:'คลังที่แชร์ให้ฉัน')+' · อัปเดตแล้ว';
    setStatus(`ฐานเพลงอัปเดต: ${num(countBefore)} → ${num(state.songs.length)} เพลง`,'success');
  }catch(error){
    if(state.token===token&&authId===state.authId)
      console.warn('X-Stage catalog refresh:',error?.message||error);
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

async function openDrive(token, authId, tokenExpiresAt=0, expectedSub='', reuseExistingSession=!!expectedSub, fullReadGranted=false) {
  setStatus('กำลังยืนยันบัญชี Google…');
  const accountResult = await googleFetch('https://openidconnect.googleapis.com/v1/userinfo', {headers:requestHeaders(token),cache:'no-store'},'Google Account');
  if (!accountResult.ok) throw driveError(accountResult.status,'ข้อมูลบัญชี Google');
  const account = await accountResult.json();
  if (!account.email_verified || !account.sub) throw Error('ไม่สามารถยืนยันบัญชี Google ได้');
  if (expectedSub && account.sub!==expectedSub) throw Error('บัญชี Google ไม่ตรงกับเซสชันเดิม กรุณาเข้าสู่ระบบอีกครั้ง');
  if (authId !== state.authId) return;

  // A new short-lived token for the SAME account must not reset the player,
  // downloaded audio, search results or queue. Only the credential changes.
  if (reuseExistingSession && state.token && state.accountSub===account.sub && state.libraryRootId && !isRetiredDriveRoot(state.libraryRootId)) {
    if(fullReadGranted){fullDriveReadToken=token;rememberFullDriveRead(account.sub);}
    state.token=token;
    state.tokenExpiresAt=tokenExpiresAt;
    rememberVerifiedGoogleAccount(account);
    saveActiveAuth(token,tokenExpiresAt,account.sub);
    clearPendingAuth();
    setStatus('ต่ออายุ Google Drive สำเร็จ · เพลงและคิวเดิมเล่นต่อเนื่อง','success');
    if(state.libraryRootId)void window.XStageBrowserMidi?.refreshFonts({token,rootId:state.libraryRootId,sub:account.sub,ownedByMe:state.libraryRootOwnedByMe})
      .catch(error=>console.warn('SoundFont auth refresh:',error.message));
    window.dispatchEvent(new CustomEvent('xstage:auth-refreshed',{detail:{sub:String(account.sub)}}));
    // An already verified same-account Drive session can reopen after renewal.
    if(androidTvVerifiedConnectionSub===account.sub)setAndroidTvStageAccess(true);
    return;
  }
  // Switch account only after Google confirms the new immutable account ID.
  if(state.accountSub && state.accountSub!==account.sub)resetPrivate({revoke:false,keepAuth:true});
  if(state.token && state.token!==token)state.catalogCache.clear();
  // Authentication is complete. Activate the account immediately.
  if(fullReadGranted){fullDriveReadToken=token;rememberFullDriveRead(account.sub);}
  state.token=token;
  state.tokenExpiresAt=tokenExpiresAt;
  state.accountSub=account.sub;
  window.dispatchEvent(new CustomEvent('xstage:auth-ready',{detail:{sub:String(account.sub)}}));
  rememberVerifiedGoogleAccount(account);
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

  // On a fresh library contract, NEVER display stale XStageSong catalogs
  // from an account-only/legacy root cache before confirming XStageKaraoke.
  const preferredRootId=readPreferredLibraryRoot(account.sub);
  let instant=null;
  if(authId!==state.authId)return;
  if(!applyInstantCatalog(instant)){
    showCatalogLoading('เตรียมใช้งานครั้งแรก','กำลังค้นหาคลัง '+driveLayout.root+'…',12);
    setStatus('เข้าสู่ระบบสำเร็จ · กำลังดาวน์โหลดฐานเพลงครั้งแรก…','success');
  }

  try{
    const defaultRoots=(await driveList("name='"+driveLayout.root+
      "' and mimeType='application/vnd.google-apps.folder' and trashed=false",token))
      .filter(root=>!isRetiredDriveRoot(root.id));
    let selectedRoot=null;
    if(preferredRootId){
      try{selectedRoot=await selectedDriveRootById(preferredRootId,token);}
      catch(error){console.warn('Selected Google Drive library is not accessible:',error?.message||error);}
    }
    // Any custom name must have been explicitly selected by its Folder ID.
    const roots=[...defaultRoots];
    if(selectedRoot&&!roots.some(item=>item.id===selectedRoot.id))roots.push(selectedRoot);
    if(!instant)showCatalogLoading('เตรียมใช้งานครั้งแรก','พบคลังเพลง · กำลังตรวจ DB/songs.sqlite3…',24);
    if(authId!==state.authId)return;
    if(!roots.length){
      // A verified empty Drive is NOT a valid cached library. An account
      // whose XStageKaraoke was deleted must never show ghost songs that fail 404.
      // Do not erase the user's browser cache permanently: their library may
      // reappear after a Google Drive permission grant or restored ownership.
      state.libraryRootId='';
      if(ui.libraryDriveLink)ui.libraryDriveLink.hidden=true;
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
      ui.resultCount.textContent='ยังไม่มีคลัง '+driveLayout.root;
      ui.libraryState.textContent='เชื่อม Google Drive แล้ว · ยังไม่มีคลังเพลงออนไลน์';
      setStatus('บัญชี Google พร้อมแล้ว · สร้าง '+driveLayout.root+' เพื่ออัปโหลดเพลงครั้งแรก','success');
      setSharedLibraryGate(true,'ยังไม่มี '+driveLayout.root+' ในบัญชีนี้ · อัปโหลดเพลงหรือเลือกคลังที่แชร์');
      return;
    }
    setSharedLibraryGate(false);
    const ownedRoots=roots.filter(item=>item.ownedByMe).sort((a,b)=>
      String(a.createdTime||'').localeCompare(String(b.createdTime||'')));
    const sharedRoots=roots.filter(item=>!item.ownedByMe).sort((a,b)=>
      String(b.sharedWithMeTime||'').localeCompare(String(a.sharedWithMeTime||'')));
    const preferred=preferredRootId&&roots.find(item=>String(item.id)===preferredRootId);
    const root=preferred||(!preferredRootId&&roots.length===1?roots[0]:null);
    if(!root){
      state.libraryRootId='';state.manifest=null;state.songs=[];state.shown=[];state.queue=[];
      releaseQueuePreload();renderSongs();renderQueue();hideCatalogLoading();
      setSearchAvailability(false);ui.songTotal.textContent='0 เพลง';
      ui.resultCount.textContent='กรุณาเลือกคลังหลัก';
      setSharedLibraryGate(true,preferredRootId?'คลังหลักเดิมไม่สามารถเข้าถึงได้ · เลือกใหม่เอง':'พบหลายคลัง · กรุณาเลือกโฟลเดอร์หลักก่อน');
      return;
    }
    if(preferredRootId&&String(root.id)!==preferredRootId&&instant){
      // Do not keep showing a cache for a library that is no longer accessible.
      instant=null;
      state.manifest=null;state.songs=[];state.shown=[];renderSongs();
    }
    state.libraryRootId=root.id;
    // Validate/repair the fixed layout before using any previously saved source.
    try{await xstageDriveFolders?.discoverDefaults();}catch(error){console.warn('Standard Drive layout:',error.message);}
    if(authId!==state.authId)return;
    void window.XStageBrowserMidi?.refreshFonts({token,rootId:root.id,sub:account.sub,ownedByMe:!!root.ownedByMe})
      .catch(error=>console.warn('SoundFont selector:',error.message));
    state.libraryRootOwnedByMe=!!root.ownedByMe;
    state.libraryRootCanShare=!!root.capabilities?.canShare;
    state.libraryRootOwnerEmail=String(root.owners?.[0]?.emailAddress||'');
    savePreferredLibraryRoot(account.sub,root.id);
    if(ui.libraryDriveLink){
      ui.libraryDriveLink.href='https://drive.google.com/drive/folders/'+encodeURIComponent(String(root.id));
      ui.libraryDriveLink.title='เปิด '+String(root.name||driveLayout.root)+' (Folder ID '+root.id+')';
      ui.libraryDriveLink.hidden=false;
    }
    renderLibrarySelector([...ownedRoots,...sharedRoots],root.id);
    window.dispatchEvent(new CustomEvent('xstage:librarychange',{detail:{
      accountSub:account.sub,rootId:String(root.id),label:libraryLabel(root),ownedByMe:!!root.ownedByMe
    }}));
    const cacheOwner=libraryCacheOwner(account.sub,root.id);
    if(!instant){
      const rootCached=await loadLatestCachedCatalog(account.sub,root.id);
      if(rootCached){instant=rootCached;applyInstantCatalog(instant);}
    }
    // DB/songs.sqlite3 is the only permitted catalog; never query JSON pointers.
    const dbDirs=await driveList(`'${root.id}' in parents and name='DB' and mimeType='application/vnd.google-apps.folder' and trashed=false`,token);
    if(dbDirs.length>1)throw Error('พบ DB ซ้ำใน '+String(root.name||'คลังเพลง'));
    const dbId=dbDirs[0]?.id||'';
    const canonical=dbId
      ?await driveList(`'${dbId}' in parents and name='songs.sqlite3' and trashed=false`,token)
      :[];
    if(canonical.length>1)throw Error('พบ songs.sqlite3 ซ้ำใน DB');
    if(!instant)showCatalogLoading('เตรียมใช้งานครั้งแรก','กำลังอ่านฐาน SQLite3 จาก DB โดยตรง…',34);
    if(!canonical.length){
      // A newly created XStageKaraoke may contain only empty category folders or
      // a SoundFont uploaded first. It is not a broken catalog. Discard the
      // previous session's visible songs, but NEVER delete any Drive data.
      // A missing pointer can also mean drive.file lacks permission; avoid
      // claiming definitively that the user's entire Drive is empty.
      if(authId!==state.authId)return;
      state.manifest=null;
      state.catalogPointerId='';
      state.catalogDbDirId=dbId;
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
      ui.libraryState.textContent='Google Drive · '+libraryLabel(root)+
        ' · ยังไม่มี DB/songs.sqlite3';
      hideCatalogLoading();
      setAndroidTvStageAccess(true,account.sub);
      setStatus('ยังไม่มี DB/songs.sqlite3 ที่แอปเข้าถึงได้ · เลือกไฟล์เพลงแล้วกดเริ่มนำเข้าเพื่อสร้างฐานใหม่','success');
      return;
    }
    const pointer=directCatalogPointer(canonical[0]);
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
    state.catalogPointerId='';
    state.catalogDbDirId=dbId;
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
    const duplicateRoots=roots.filter(x=>x.name===root.name).length;
    setStatus(`เชื่อมต่อแล้ว · ${num(state.songs.length)} เพลง · ${libraryLabel(root)}${duplicateRoots>1?' · พบ XStageKaraoke ชื่อซ้ำ '+duplicateRoots+' โฟลเดอร์ · เปลี่ยนได้ที่เมนูเลือกคลัง':''}${downloaded?' (อัปเดตฐานล่าสุดแล้ว)':sameAsInstant?' (ฐานในเครื่องเป็นรุ่นล่าสุด)':''}`,'success');
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

function login({automatic=false,remembered=false} = {}) {
  if(webGoogleAuthFlow?.phase==='verifying'){
    setStatus('ได้รับสิทธิ์จาก Google แล้ว · กำลังตรวจสอบบัญชีและคลังเพลง…');
    return;
  }
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
  const flow={id:authId,startedAt:Date.now(),phase:'waiting'};
  webGoogleAuthFlow=flow;
  let settled=false;
  const finish=()=>{
    settled=true;
    clearTimeout(watchdog);
    clearTimeout(retryTimer);
    if(webGoogleAuthFlow===flow)webGoogleAuthFlow=null;
    if(authId===state.authId)ui.login.disabled=ui.gateLogin.disabled=false;
  };
  const watchdog=setTimeout(()=>{
    if(settled||authId!==state.authId)return;
    finish();
    state.authId++;
    setStatus('Google ยังไม่ส่งผลการอนุญาตกลับมา · หากปิดหน้าต่าง Google แล้ว กรุณากดเข้าสู่ระบบอีกครั้ง','error');
  },90_000);
  // Safari may return focus before postMessage/callback; do not invalidate the
  // original request. An explicit second click is permitted if the popup hangs.
  const retryTimer=setTimeout(()=>{
    if(settled||authId!==state.authId||flow.phase!=='waiting'||state.token)return;
    ui.login.disabled=ui.gateLogin.disabled=false;
    setStatus('กำลังรอ Google ยืนยันสิทธิ์ · หากหน้าต่าง Google ปิดแล้วสามารถกดเข้าสู่ระบบอีกครั้ง');
  },12_000);
  try {
    const knownAccount=(automatic||remembered)?rememberedGoogleAccount():null;
    const restoreRead=rememberedFullDriveRead(knownAccount?.sub);
    const client = google.accounts.oauth2.initTokenClient({
      client_id:cfg.googleClientId,
      scope:'openid email https://www.googleapis.com/auth/drive.file'+(restoreRead?' '+DRIVE_READ_SCOPE:''),
      include_granted_scopes:false,
      callback: async result => {
        if(authId!==state.authId||settled)return;
        if(result?.error){finish();setStatus(googleAuthErrorMessage(result),'error');return;}
        if(!result?.access_token){finish();setStatus('ไม่ได้รับสิทธิ์จาก Google · กรุณากดเข้าสู่ระบบอีกครั้ง','error');return;}
        // Keep this request active while userinfo/Drive is verified. A Safari
        // focus/pageshow event must not start a competing pending-token recovery.
        settled=true;
        clearTimeout(watchdog);
        clearTimeout(retryTimer);
        flow.phase='verifying';
        setStatus('ได้รับสิทธิ์ Google แล้ว · กำลังตรวจสอบบัญชีและคลังเพลง…');
        // Do not reset a playing track until the new Google account is verified.
        const expiresIn=Number(result.expires_in);
        const expiresAt=Date.now()+Math.max(0,Math.min(3600,Number.isFinite(expiresIn)?expiresIn:3600))*1000;
        const fullReadGranted=restoreRead&&grantedDriveReadAndWrite(result);
        if(restoreRead&&!String(result.scope||'').split(/\s+/).includes(DRIVE_FILE_SCOPE)){
          finish();setStatus('Google ยังไม่ได้ให้สิทธิ์ไฟล์ของแอป · กรุณาเข้าสู่ระบบด้วยบัญชีเดิมและอนุญาตสิทธิ์ที่จำเป็น','error');return;
        }
        // Never persist a broad-scope token in the pending login store.
        if(!restoreRead)savePendingAuth(result.access_token,expiresAt);
        const known=knownAccount;
        try { await openDrive(result.access_token,authId,expiresAt,known?.sub||'',true,fullReadGranted); }
        catch (e) {
          if (authId === state.authId) {
            if(state.awaitingSharedLibrary){
              hideCatalogLoading();
              setStatus('เข้าสู่ระบบบัญชีผู้รับเชิญแล้ว · กรุณาเปิดคลังที่แชร์','success');
              return;
            }
            if(state.token&&state.accountSub&&state.tokenExpiresAt>Date.now()+AUTH_EXPIRY_MARGIN_MS){
              clearPendingAuth();setStatus('การเชื่อมต่อ Google ใหม่ไม่สำเร็จ · เพลงและคิวเดิมยังอยู่: '+e.message,'error');return;
            }
            clearActiveAuth();resetPrivate({keepAuth:true});
            if(!/เชื่อมต่อไม่สำเร็จ|ใช้เวลานาน|อินเทอร์เน็ต/.test(String(e.message||'')))clearPendingAuth();
            setStatus(e.message, 'error');
          }
        }finally{finish();}
      },
      error_callback: error => {
        // A delayed/duplicate popup event must not override a successful
        // token response while Drive userinfo is still being verified.
        if(authId!==state.authId||settled)return;
        finish();
        setStatus(googleAuthErrorMessage(error),'error');
      }
    });
    // A manual click should always use Google's normal account chooser. An empty
    // prompt is reserved for reconnecting an existing session and can leave a
    // stale/invalid OAuth warning flow open in some multi-account browser sessions.
    const hint=(automatic||remembered)?rememberedGoogleAccount():null;
    client.requestAccessToken(automatic||remembered
      ?{prompt:'',...(hint?.email?{login_hint:hint.email}:{})}
      :{prompt:'select_account'});
  } catch (e) { finish();setStatus(e.message, 'error'); }
}
function resetPrivate({revoke = false, keepAuth = false} = {}) {
  if(revoke){rememberLogin(false);clearActiveAuth();clearPendingAuth();}
  if (!keepAuth){state.authId++;webGoogleAuthFlow=null;}
  const pendingSearch=keepAuth?String(ui.search?.value||''):'';
  const oldToken = state.token;
  state.requestId++;
  state.controller?.abort(); state.controller = null; state.loading = false;
  window.XStageMIDIPiano?.setSong({bytes:null});
  state.liveMidiPlayback?.dispose();state.liveMidiPlayback=null;state.liveMidiSource=null;
  window.XStageIOSMidiAudio?.release?.();
  player.pause(); player.removeAttribute('src'); player.load();
  resetSongVideo();
  if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
  state.objectUrl = ''; state.token = '';fullDriveReadToken='';state.tokenExpiresAt=0; state.accountSub = ''; state.manifest = null;
  state.songs = [];state.shown = [];state.queue = [];state.history = [];
  state.catalogPointerId='';state.catalogDbDirId='';state.catalogGeneration='';state.catalogCache.clear();
  state.libraryRootId='';state.libraryRootCanShare=false;state.libraryRootOwnedByMe=false;state.libraryRootOwnerEmail='';state.availableLibraries=[];
  if(ui.librarySelect)ui.librarySelect.replaceChildren();
  if(ui.librarySwitcher)ui.librarySwitcher.hidden=true;
  if(ui.libraryDriveLink)ui.libraryDriveLink.hidden=true;
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
  setSongKeyDisplay();
  ui.stage.classList.remove('playing');ui.stageIdle.hidden = false;
  window.XStageStageLighting?.clearMidiNotes?.();
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
  const canShare=!!(state.token&&state.libraryRootId&&state.libraryRootOwnedByMe&&state.libraryRootCanShare);
  email.disabled=ack.disabled=!canShare;
  submit.disabled=true;
  if(!state.token)status.textContent='กรุณาเข้าสู่ระบบ Google ก่อนแชร์';
  else if(!state.libraryRootOwnedByMe)status.textContent='คลังนี้เป็นคลังที่ผู้อื่นแชร์ให้ จึงไม่สามารถแชร์ต่อจาก X-Stage ได้';
  else if(!state.libraryRootCanShare)status.textContent='บัญชีนี้ไม่มีสิทธิ์แชร์โฟลเดอร์ XStageKaraoke';
  dialog.showModal();
  if(canShare)setTimeout(()=>email.focus(),30);
}
async function shareLibraryWithEmail(email){
  if(!state.token)throw Error('กรุณาเข้าสู่ระบบ Google ก่อนแชร์');
  if(!state.libraryRootId||!state.libraryRootOwnedByMe||!state.libraryRootCanShare)
    throw Error('บัญชีนี้ไม่มีสิทธิ์แชร์คลังเพลง');
  const recipient=String(email||'').trim();
  if(!validShareEmail(recipient))throw Error('กรุณากรอกอีเมล Google ของผู้รับให้ถูกต้อง');
  const params=new URLSearchParams({
    sendNotificationEmail:'true',
    supportsAllDrives:'true',
    emailMessage:'X-Stage Karaoke: คุณได้รับสิทธิ์ดูคลังเพลง XStageKaraoke แบบอ่านอย่างเดียว กรุณาเข้า X-Stage ด้วยอีเมลนี้'
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
  // Drive reader-permission sharing does not require a Google Picker API key.
  for(const button of [$('pc-share-library'),$('mobile-share-library'),document.querySelector('#xstage-context-menu [data-cmd="share"]')]){
    if(button){button.hidden=false;button.disabled=false;}
  }
  const dialog=$('share-library-dialog');
  const email=$('share-library-email');
  const ack=$('share-library-ack');
  const submit=$('share-library-submit');
  const status=$('share-library-status');
  if(!dialog||!email||!ack||!submit||!status)return;
  const sync=()=>{submit.disabled=!(state.token&&ack.checked&&validShareEmail(email.value)&&state.libraryRootOwnedByMe&&state.libraryRootCanShare&&!submit.dataset.busy);};
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
      rootId:String(state.libraryRootId||''),
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
    // Song titles/codes can be identical in different folders. Never resume
    // another root's song merely because the metadata happens to match.
    if(!state.libraryRootId||String(saved.rootId||'')!==String(state.libraryRootId))return null;
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
// Never split a Thai consonant from its combining vowels or tone marks when
// highlighting a partial search match. Separate DOM nodes break glyph shaping
// on iOS Safari (e.g. a search for "ร" in "รู้" or "รัก").
function expandMatchToGrapheme(raw,start,end) {
  const clusters=typeof Intl.Segmenter==='function'
    ? Array.from(new Intl.Segmenter('th',{granularity:'grapheme'}).segment(raw),item=>item.segment)
    : Array.from(raw).reduce((parts,char)=>{
        if(/[\p{M}\u200d]/u.test(char)&&parts.length)parts[parts.length-1]+=char;
        else parts.push(char);
        return parts;
      },[]);
  let offset=0,from=start,to=end;
  for(const cluster of clusters){
    const next=offset+cluster.length;
    if(offset<=start&&start<next)from=offset;
    if(offset<end&&end<=next)to=next;
    offset=next;
  }
  return [from,to];
}
function renderMatchedText(node, value, term) {
  const raw=String(value ?? '');
  const hit=term ? raw.toLocaleLowerCase('th').indexOf(term) : -1;
  if(hit<0){node.textContent=raw;return;}
  const [start,end]=expandMatchToGrapheme(raw,hit,hit+term.length);
  node.append(document.createTextNode(raw.slice(0,start)));
  const match=document.createElement('mark');
  match.className='song-match';
  match.textContent=raw.slice(start,end);
  node.append(match,document.createTextNode(raw.slice(end)));
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
function searchScore(entry,term,words){
  if(!term)return Number.POSITIVE_INFINITY;
  if(entry.code===term)return 0;
  if(entry.title===term)return 10;
  if(entry.title.startsWith(term))return 20;
  if(entry.code.startsWith(term))return 30;
  if(entry.artist===term)return 40;
  if(entry.artist.startsWith(term))return 50;
  if(words.length>1&&words.every(word=>entry.combined.includes(word)))return 55;
  if(entry.title.includes(term))return 60;
  if(entry.artist.includes(term))return 70;
  if(entry.code.includes(term))return 80;
  if(entry.combined.includes(term))return 90;
  return Number.POSITIVE_INFINITY;
}
function rankedSearchEntries(songs,rawTerm,maxResults=5){
  const term=normalizeSearchText(rawTerm);
  if(!term)return {results:[],total:0};
  const words=term.split(' ').filter(Boolean);
  const requested=Number(maxResults);
  const limit=Number.isFinite(requested)?Math.max(0,Math.floor(requested)):5;
  const results=[];
  let total=0;
  // Full catalog scan is needed for substring matching, but the stage only
  // needs 5 winners (or 200 for remotes). Avoid sorting every match on each key.
  for(const entry of indexedSongs(songs)){
    const score=searchScore(entry,term,words);
    if(!Number.isFinite(score))continue;
    total++;
    if(!limit)continue;
    if(results.length>=limit){
      const worst=results[results.length-1];
      if(score>worst.score||(score===worst.score&&entry.index>=worst.index))
        continue;
    }
    const candidate={...entry,score};
    let low=0,high=results.length;
    while(low<high){
      const mid=(low+high)>>>1,old=results[mid];
      if(old.score<score||(old.score===score&&old.index<candidate.index))low=mid+1;
      else high=mid;
    }
    results.splice(low,0,candidate);
    if(results.length>limit)results.pop();
  }
  return {results,total};
}
window.XStageRankSearch=(songs,rawTerm,limit=5)=>
  rankedSearchEntries(songs,rawTerm,limit).results;

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
  const ranked=rankedSearchEntries(state.songs,term,5);
  state.shown=ranked.results.map(item=>item.song);
  state.selectedIndex=Math.max(0,Math.min(state.selectedIndex,state.shown.length-1));
  ui.resultCount.textContent=`พบ ${num(ranked.total)} เพลง${ranked.total>5?' · 5 ผลลัพธ์ที่ตรงที่สุด':''}`;
  if(ui.searchRefine){
    ui.searchRefine.hidden=ranked.total<=5;
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
    try{window.XStageIOSMidiAudio?.activate?.();}catch{}
    try{window.XStageResumeAudioGraph?.();}catch{}
    try{window.XStageBrowserMidi?.unlockAudio?.();}catch{}
    void playSong(song);
  }else{
    addToQueue(song);
  }
  clearSearchAfterChoice();
  return true;
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
    state.medleyPrefetch?.controller?.abort();
    state.medleyCache=null;state.medleyPrefetch=null;state.medleyUpcoming=null;
    state.medleyPreloadFailedSong=null;state.medleyPreloadRetryAt=0;
    player.volume=karaokeOutputGain();
  }
  setPlayStatus(state.medley
    ?'เปิดเมดเลย์สุ่มเพลงต่อเนื่อง · เพลงที่ขอในคิวจะเล่นก่อน'
    :'ปิดเมดเลย์สุ่มเพลง');
  window.dispatchEvent(new CustomEvent('xstage:medleychange',
    {detail:{enabled:state.medley}}));
  // Enabling medley during a song must NOT cut off the singer; prepare its
  // successor now and hand over at the natural end. Start a random track
  // only when the stage was idle.
  if(state.medley&&state.token){
    if(state.current){
      if(!player.paused)prefetchMedleyNext();
    }else if(state.queue.length){
      playNext();
    }else{
      state.userStopped=false;
      const song=randomMedleySong();
      if(song){state.medleyUpcoming=null;playSong(song);}
      else setPlayStatus('ไม่มีเพลงที่พร้อมเล่นในคลัง');
    }
  }
  return state.medley;
}
function setStageVisualScale(value){
  state.visualScale=Math.max(.7,Math.min(1.35,Math.round(Number(value)*100)/100));
  ui.stage.style.setProperty('--xstage-visual-scale',String(state.visualScale));
  saveUiPrefs({visualScale:state.visualScale});
  return state.visualScale;
}
// Play-on-demand must never wait indefinitely for a large GM SoundFont.
// A late bank can upgrade the running synth without restarting its clock.
const FAST_FONT_BUDGET_MS=/iPad|iPhone|iPod/.test(navigator.userAgent||'')?1100:2200;
async function getStartupSoundFont(token,signal){
  // selectedFont waits for refreshFonts. A blank selectedId here can mean
  // "the GM bank list has not loaded yet", NOT that the user chose 8-bit.
  // Skipping that promise caused the first song to use oscillators while
  // the next song sounded correct after refresh finished.
  const task=Promise.resolve().then(()=>
    window.XStageBrowserMidi.prefersCompactGm?.()
      ?window.XStageBrowserMidi.fastGmFont(token,signal)
      :window.XStageBrowserMidi.selectedFont(token,signal));
  // Handle a rejected fetch even when its result arrives after the deadline.
  const safe=task.catch(error=>{
    if(error?.name!=='AbortError')console.warn('SoundFont unavailable:',error);
    return null;
  });
  let timeout;
  try{
    const result=await Promise.race([
      safe.then(bytes=>({ready:true,bytes})),
      new Promise(resolve=>{timeout=setTimeout(()=>resolve({ready:false}),FAST_FONT_BUDGET_MS);})
    ]);
    return result.ready?{bytes:result.bytes,pending:null}:{bytes:null,pending:safe};
  }finally{clearTimeout(timeout);}
}
// Do not start a MIDI song with chip-style oscillators while its selected
// instrument bank is still downloading. A first play may take longer;
// subsequent songs reuse the validated SoundFont in memory.
async function ensureMidiInstrumentBank(fontBytes,pending,token,controller){
  let bank=fontBytes;
  if(!bank){
    setPlayStatus('กำลังเตรียมเสียงเครื่องดนตรีจริงสำหรับเพลงแรก…');
    const task=pending||window.XStageBrowserMidi.selectedFont(token,controller.signal);
    // Give the selected bank 12 seconds, not 45. Never start with
    // oscillator-only 8-bit sound: use a compact sampled GM bank instead.
    let timer;
    const outcome=await Promise.race([
      Promise.resolve(task).then(value=>({value}),error=>({error})),
      new Promise(resolve=>{timer=setTimeout(()=>resolve({expired:true}),12000);})
    ]).finally(()=>clearTimeout(timer));
    if(controller.signal.aborted)throw new DOMException('ยกเลิก','AbortError');
    bank=outcome.value||null;
    if(!bank&&window.XStageBrowserMidi.fastGmFont){
      setPlayStatus('ชุดเสียงที่เลือกยังไม่พร้อม · ใช้ GM 6 MB เพื่อเริ่มเพลง…');
      bank=await boundedPlaybackTask(
        window.XStageBrowserMidi.fastGmFont(token,controller.signal),18,
        'โหลด GM 6 MB ไม่สำเร็จ · ตรวจอินเทอร์เน็ตแล้วลองใหม่',controller);
    }
  }
  if(!bank){
    const detail=window.XStageBrowserMidi.fontStatus()?.warning||'';
    throw Error('SoundFont ยังไม่พร้อม จึงไม่เริ่มเพลงด้วยเสียง 8-bit'+
      (detail?' · '+detail:' · โปรดเลือกชุดเสียง GM/GS และตรวจการเชื่อมต่อ'));
  }
  return bank;
}

// Prefer the real MIDI sequencer. When it cannot initialize, the existing
// Web Audio fallback must still receive the loaded SF2 sample bank.
async function renderWithSoundFontRecovery(source,bank,token,controller,options={}){
  const midi=window.XStageBrowserMidi;
  midi.beginFontTrial?.(bank);
  try{
    const result=await midi.render(source,{...options,fontBytes:bank,signal:controller.signal});
    midi.finishFontTrial?.(bank);return result;
  }catch(error){
    if(controller.signal?.aborted||error?.name==='AbortError'){midi.finishFontTrial?.(bank);throw error;}
    if(!await midi.recoverFont?.(bank,error.message))throw error;
    const gm=await midi.selectedFont(token,controller.signal);
    return midi.render(source,{...options,fontBytes:gm,signal:controller.signal});
  }
}
async function prepareFirstMidiSynth(source,bank,options){
  if(!bank||!window.XStageProMidi?.available?.())return null;
  const task=window.XStageProMidi.prepare(source,bank,options);
  let timeout;
  try{
    const outcome=await Promise.race([
      task.then(engine=>({engine}),error=>({error})),
      new Promise(resolve=>{timeout=setTimeout(()=>resolve({expired:true}),25000);})
    ]);
    if(outcome.expired){
      // A delayed worklet must never attach to a song that has fallen back.
      void task.then(engine=>engine?.dispose()).catch(()=>{});
      console.warn('SpessaSynth initialization timed out; using the real SoundFont sampler');
      return null;
    }
    if(outcome.error){
      if(outcome.error?.name==='AbortError')throw outcome.error;
      console.warn('SpessaSynth unavailable; using the real SoundFont sampler:',outcome.error);
      return null;
    }
    return outcome.engine||null;
  }finally{clearTimeout(timeout);}
}
async function prepareXskPlayback(song,token,signal,onStatus=()=>{},prefetch=false){
  if(song?.pendingDriveLink===true)await resolvePcDriveLink(song,token,signal);
  const soundFontGeneration=state.xskSoundFontGeneration||0;
  const isXmid=!!getFileId(song?.xmid);
  const fileId=getFileId(isXmid?song?.xmid:song?.xsk);
  if(!fileId)throw Error('ไม่พบไฟล์ XMID/XSK2 ในฐานเพลง');
  if(!(isXmid?window.XStageXmid:window.XStageXsk)?.openPackage || !window.XStageBrowserMidi)
    throw Error('ตัวเล่น XMID/XSK2 หรือ MIDI ยังไม่พร้อม กรุณาอัปเดตเว็บ');
  if(signal?.aborted)throw new DOMException('ยกเลิก','AbortError');
  onStatus('กำลังโหลด XMID/XSK2 และ SoundFont จาก Google Drive…');
  // Queued tracks reuse the selected in-session SoundFont at play time.
  // Do not duplicate a large SF2/SF3 bank during speculative prefetch.
  const fontTask=prefetch?Promise.resolve({bytes:null,pending:null}):
    getStartupSoundFont(token,signal);
  const response=await privateFile(fileId,token,{signal});
  const {bytes:fontBytes,pending:lateFont}=await fontTask;
  const packed=await response.blob();
  if(signal?.aborted)throw new DOMException('ยกเลิก','AbortError');
  onStatus('กำลังตรวจและแยก XMID/XSK2 ในหน่วยความจำ…');
  const unpacked=await (isXmid?window.XStageXmid:window.XStageXsk).openPackage(packed);
  if(signal?.aborted)throw new DOMException('ยกเลิก','AbortError');
  // Never play a different song under a stale catalog title/code.
  // A distinct MIDI may share an embedded code with another export. The
  // catalog keeps a unique alias in song.code and the original package code
  // in sourceCode; validate against the latter without weakening title checks.
  if(String(song.sourceCode||song.code||'')!==unpacked.code ||
     String(song.title||'')!==String(unpacked.document.title||'') ||
     String(song.artist||'')!==String(unpacked.document.artist||''))
    throw Error('XMID/XSK2 ภายในไฟล์ไม่ตรงกับข้อมูลเพลงใน DB · กรุณานำเข้าอีกครั้ง');
  const midiBytes=new Uint8Array(await unpacked.midi.arrayBuffer());
  if(prefetch&&!window.XStageBrowserMidi?.supportsRealtime?.()){
    // OfflineAudioContext uses floating-point PCM before encoding to WAV.
    // Bound duration before rendering to protect low-RAM Android WebViews.
    const duration=Number(window.XStageBrowserMidi.parseMidi(midiBytes).duration);
    const lowMemory=Number(navigator.deviceMemory||8)<=4;
    const estimatedWorkingBytes=(duration+1)*32000*2*4*2;
    if(!Number.isFinite(duration)||
       estimatedWorkingBytes>(lowMemory?128:256)*1024*1024)
      return null; // The song remains playable on demand when its turn arrives.
  }
  if(window.XStageBrowserMidi?.supportsRealtime?.()){
    window.XStageBrowserMidi.parseMidi(midiBytes);
    onStatus(prefetch?'เพลง MIDI ถัดไปเตรียมข้อมูลพร้อมแล้ว':
      'MIDI/SoundFont พร้อมเล่นแบบเรียลไทม์');
    return {song,token,blob:null,lyrics:unpacked.document,
      liveMidi:midiBytes,liveFont:fontBytes,lateFont,
      bytes:prefetch?midiBytes.byteLength:0};
  }
  onStatus('กำลังสังเคราะห์ MIDI ของ XSK2 ด้วย SoundFont…');
  const verifiedBank=await ensureMidiInstrumentBank(fontBytes,lateFont,token,
    {signal,abort(){ /* XSK's outer controller owns cancellation. */ }});
  const rendered=await renderWithSoundFontRecovery(midiBytes,verifiedBank,token,{signal},{onStatus});
  if(signal?.aborted)throw new DOMException('ยกเลิก','AbortError');
  if(soundFontGeneration!==(state.xskSoundFontGeneration||0))
    throw Error('SoundFont เปลี่ยนระหว่างเตรียม XSK2 · ต้องเรนเดอร์ใหม่');
  if(!rendered?.audio?.size)throw Error('ไม่สามารถสังเคราะห์เสียงจาก XSK2 ได้');
  return {song,token,blob:rendered.audio,lyrics:unpacked.document};
}

// This is a bounded, voluntary cache: the active track and the selected
// SoundFont take priority. Never claim that deviceMemory is real free RAM.
function fontMemoryBytes(){
  const info=window.XStageBrowserMidi?.fontStatus?.();
  return Number(info?.fileBytes||0)+Number(info?.sampleBytes||0);
}
function cacheMemoryBytes(){
  let total=0;
  for(const item of state.queuePreparedCache.values())
    total+=Number(item.bytes||item.blob?.size||0);
  return total;
}
function memoryResources(extraBytes=0){
  return {fontBytes:fontMemoryBytes(),
    queuedBytes:cacheMemoryBytes()+Number(state.medleyCache?.bytes||state.medleyCache?.blob?.size||0),
    activeBytes:state.activeBlobBytes+state.activeVideoBytes,extraBytes};
}
function updateMemoryIndicators(){
  const monitor=window.XStageMemory;
  if(!monitor)return;
  const resources=memoryResources(),report=monitor.statusText(resources);
  const queueEl=document.getElementById('xstage-queue-memory');
  if(queueEl){
    queueEl.dataset.level=report.level;
    const waiting=state.queuePreload||state.medleyPrefetch;
    const preparedCount=state.queuePreparedCache.size+(state.medleyCache?1:0);
    queueEl.textContent=report.text+
      ' · '+preparedCount+' เพลงถัดไปพร้อม'+
      (waiting?' · กำลังเตรียม 1 เพลง':'');
    queueEl.title=report.note;
  }
  const fontEl=document.getElementById('xstage-font-memory');
  if(fontEl){
    const info=window.XStageBrowserMidi?.fontStatus?.()||{};
    const bytes=Number(info.fileBytes||0),sample=Number(info.sampleBytes||0);
    const p=monitor.plan(resources),hint=p.hint.gib;
    const concern=p.heapPressure||p.nativePressure||
      bytes+sample>hint*1024*1024*1024*.12;
    fontEl.dataset.level=info.warning||concern?'high':
      bytes+sample>hint*1024*1024*1024*.055?'medium':'low';
    fontEl.textContent=info.warning?info.warning:
      info.loaded?'SF ใน RAM '+monitor.fmt(bytes)+
      ' · ตัวอย่าง '+monitor.fmt(sample)+' · ใช้ซ้ำตลอดเซสชัน'+
      (p.native?' · RAM ว่างจริง '+monitor.fmt(p.native.available):''):
      info.selectedId?'SF กำลังโหลด · ประเมินตาม RAM ของอุปกรณ์':
      'SoundFont · ใช้เสียงพื้นฐาน (ไม่ใช้ RAM ของ SF)';
    fontEl.title='แสดงขนาดข้อมูลที่แอปเก็บ ไม่ใช่ RAM ว่างของระบบ · งบแคชประมาณการจาก '+hint+' GB ('+p.hint.source+')';
  }
}
function trimQueueCache(){
  // Delete stale entries first, then evict furthest songs at high pressure.
  for(const song of state.queuePreparedCache.keys()){
    if(!state.queue.includes(song))state.queuePreparedCache.delete(song);
  }
  for(const song of state.queuePreloadSkipped){
    if(!state.queue.includes(song))state.queuePreloadSkipped.delete(song);
  }
  const monitor=window.XStageMemory;
  if(monitor){
    let p=monitor.plan(memoryResources());
    if(p.heapPressure||p.nativePressure){
      state.medleyCache=null;
      state.medleyPrefetch?.controller?.abort();
      state.medleyPrefetch=null;
      p=monitor.plan(memoryResources());
    }
    const queueLimit=p.queueLimit;
    while(state.queuePreparedCache.size>queueLimit||
        (state.queuePreparedCache.size>0&&(p.heapPressure||p.nativePressure||p.ratio>.8))){
      const ranked=[...state.queuePreparedCache.keys()]
        .sort((a,b)=>state.queue.indexOf(b)-state.queue.indexOf(a));
      if(!ranked.length)break;
      state.queuePreparedCache.delete(ranked[0]);
      p=monitor.plan(memoryResources());
    }
  }
  // Compatibility with existing queue UI and remote controls.
  state.queuePrepared=state.queuePreparedCache.get(state.queue[0])||null;
  updateMemoryIndicators();
}
function releaseQueuePreload(){
  clearTimeout(state.queuePreloadTimer);state.queuePreloadTimer=null;
  state.queuePreloadVersion++;
  state.queuePreload?.controller.abort();
  state.queuePreload=null;
  state.queuePrepared=null;
  state.queuePreparedCache.clear();
  state.queuePreloadSkipped.clear();
  updateMemoryIndicators();
}
async function prepareQueuedSong(song,token,signal){
  const monitor=window.XStageMemory;
  if(!monitor)return null;
  const pressure=monitor.plan(memoryResources());
  if(pressure.heapPressure||pressure.nativePressure)return null;
  if(getFileId(song.xsk)||getFileId(song.xmid)){
    // The pack and the uncompressed bytes count against available space.
    const maxPacked=Math.max(0,monitor.plan(memoryResources()).remaining*.45);
    if(!Number((song.xmid||song.xsk).size)||Number((song.xmid||song.xsk).size)>maxPacked)return null;
    const result=await prepareXskPlayback(song,token,signal,()=>{},true);
    const size=Number(result?.bytes||result?.blob?.size||0);
    if(!size||!monitor.canHold(size,memoryResources()))return null;
    return {...result,bytes:size};
  }
  if(getFileId(song.midi)){
    const isLive=!!window.XStageBrowserMidi?.supportsRealtime?.();
    const sourceSize=Number(song.midi.size);
    if(!sourceSize||sourceSize>12*monitor.MiB||
       !monitor.canHold(sourceSize*2,memoryResources()))return null;
    const [source,fontBytes,lyrics]=await Promise.all([
      privateFile(song.midi.fileId,token,{signal}),
      isLive?null:window.XStageBrowserMidi?.selectedFont(token,signal),
      getFileId(song.lyrics)?privateJson(song.lyrics.fileId,token,{signal}):null
    ]);
    if(!window.XStageBrowserMidi)throw Error('ยังไม่พบตัวเรนเดอร์ MIDI');
    const bytes=new Uint8Array(await source.arrayBuffer());
    if(signal.aborted)throw new DOMException('Aborted','AbortError');
    const parsed=window.XStageBrowserMidi.parseMidi(bytes);
    if(isLive){
      const timedLyrics=lyrics||(song.sourceFormat==='KAR'
        ?window.XStageBrowserMidi.midiLyrics(parsed,song.code):null);
      if(timedLyrics?.schemaVersion!==1||!Array.isArray(timedLyrics.lines))return null;
      return {song,token,blob:null,lyrics:timedLyrics,liveMidi:bytes,
        liveFont:null,lateFont:null,bytes:bytes.byteLength};
    }
    const wavBytes=Math.ceil((parsed.duration+.5)*32000*4+44);
    const workingBytes=wavBytes*2;
    if(!monitor.canHold(workingBytes,memoryResources()))return null;
    const rendered=await window.XStageBrowserMidi.render(bytes,{fontBytes,signal});
    if(signal.aborted||!monitor.canHold(rendered.audio.size,memoryResources()))return null;
    const timedLyrics=lyrics||(song.sourceFormat==='KAR'
      ?window.XStageBrowserMidi.midiLyrics(parsed,song.code):null);
    if(timedLyrics?.schemaVersion!==1||!Array.isArray(timedLyrics.lines))return null;
    return {song,token,blob:rendered.audio,lyrics:timedLyrics,bytes:rendered.audio.size};
  }
  // Ordinary MP3/M4A/WAV/video + JSON: permit unknown catalog sizes,
  // but stream into a strict speculative RAM cap. Never pull an unlimited
  // Drive response into memory just because it is next in the queue.
  if(!getFileId(song.audio)||!getFileId(song.lyrics))return null;
  const size=Number(song.audio.size);
  const limit=Math.max(0,Math.floor(monitor.plan(memoryResources()).remaining*.72));
  if(!(limit>0)||(size>0&&(size>limit||
     !monitor.canHold(size*1.15,memoryResources()))))return null;
  const [response,lyrics]=await Promise.all([
    privateFile(song.audio.fileId,token,{signal}),
    privateJson(song.lyrics.fileId,token,{signal})
  ]);
  const reported=Number(response.headers?.get?.('Content-Length')||0);
  if(reported&&(reported>limit||!monitor.canHold(reported*1.15,memoryResources()))){
    await response.body?.cancel?.();return null;
  }
  // Stream only as far as the memory budget permits. This also covers old
  // song catalogs that do not include Drive file sizes.
  const reader=response.body?.getReader?.();
  let blob=null;
  if(reader){
    const chunks=[];let received=0;
    try{
      while(true){
        const part=await reader.read();
        if(part.done)break;
        if(signal.aborted)throw new DOMException('ยกเลิก','AbortError');
        received+=part.value.byteLength;
        if(received>limit){await reader.cancel();return null;}
        chunks.push(part.value);
      }
      blob=new Blob(chunks,{type:response.headers?.get?.('Content-Type')||''});
    }finally{reader.releaseLock?.();}
  }else if(size>0||reported>0){
    // Non-streaming WebView: only fetch when a catalog/header gives a bound.
    blob=await response.blob();
  }
  if(!blob||signal.aborted||blob.size>limit||
     !monitor.canHold(blob.size,memoryResources())||
     lyrics?.schemaVersion!==1||!Array.isArray(lyrics.lines))return null;
  // If the original video is separate, it will be loaded on demand at play;
  // never keep a second high-resolution video file in the speculative cache.
  return {song,token,blob,lyrics,bytes:blob.size};
}
function scheduleQueuePreload(){
  clearTimeout(state.queuePreloadTimer);
  trimQueueCache();
  if(!state.token)return;
  if(!state.queue.length){
    if(state.queuePreload||state.queuePreparedCache.size)releaseQueuePreload();
    // One next song is prepared for medley too, even when the queue is empty.
    // Never begin a speculative download while the stage is paused or idle.
    if(state.medley&&!state.loading&&!state.userStopped&&!state.userPaused&&
       state.current&&!player.paused)prefetchMedleyNext();
    return;
  }
  // A requested song in the queue always supersedes random medley preload.
  state.medleyPrefetch?.controller?.abort();
  state.medleyPrefetch=null;state.medleyCache=null;
  state.medleyUpcoming=null;
  if(state.loading){
    state.queuePreloadTimer=setTimeout(scheduleQueuePreload,250);
    return;
  }
  const monitor=window.XStageMemory;
  if(!monitor)return;
  const pressure=monitor.plan(memoryResources());
  if(pressure.heapPressure||pressure.nativePressure)return;
  if(state.queuePreload){
    if(state.token===state.queuePreload.token&&
       state.queue.includes(state.queuePreload.song))return;
    state.queuePreload.controller.abort();state.queuePreload=null;
  }
  const quota=monitor.plan(memoryResources()).queueLimit;
  const windowSongs=state.queue.slice(0,quota);
  const next=windowSongs.find(song=>!state.queuePreparedCache.has(song)&&
    !state.queuePreloadSkipped.has(song));
  if(!next)return;
  if(state.queuePreparedCache.size>=quota)return;
  // Start the next requested track's download on the next event-loop turn.
  // Do not delay a warm queue behind the random-medley scheduler.
  state.queuePreloadTimer=setTimeout(()=>{void preloadFirstQueueSong(next,state.token);},0);
}
function setMidiEngineStatus(engine){
  const label=$('xstage-midi-engine-status');
  if(!label)return;
  label.hidden=!engine;
  label.textContent=engine?.engine==='SpessaSynth'
    ?engine?.scheduler==='audio-worklet'
      ?'เครื่องเสียง: SpessaSynth · เล่นต่อเมื่อสลับแท็บ'
      :'เครื่องเสียง: SpessaSynth · โหมดสำรอง'
    :engine?'เครื่องเสียง: Web Audio สำรอง':'';
}
window.addEventListener('xstage:soundfont-change',()=>{
  // Keep the playing song and its transport clock. Switch the active synth
  // after the newly selected SoundFont has loaded; stale requests are ignored.
  const generation=state.xskSoundFontGeneration=(state.xskSoundFontGeneration||0)+1;
  releaseQueuePreload();
  if(state.liveMidiSource&&state.token&&midiTransport.active){
    const token=state.token,source=state.liveMidiSource;
    // Retire the old synth before allocating a new large SoundFont.
    state.liveMidiPlayback?.dispose();state.liveMidiPlayback=null;
    setPlayStatus('กำลังเปลี่ยน SoundFont โดยไม่หยุดเวลาเพลง…');
    void (async()=>{
      try{
        let fontBytes=await window.XStageBrowserMidi.selectedFont(token);
        if(!fontBytes)fontBytes=await window.XStageBrowserMidi.selectedFont(token);
        const isCurrent=()=>generation===state.xskSoundFontGeneration&&
          token===state.token&&source===state.liveMidiSource&&midiTransport.active;
        if(!isCurrent())return;
        window.XStageBrowserMidi.beginFontTrial?.(fontBytes);
        const options={
          fontBytes,onStatus:setPlayStatus,
          getTranspose:()=>Number($('midi-transpose')?.value||0),
          getProgram:()=>{const value=$('midi-instrument')?.value;
            return value===''?null:Number(value);}
        };
        let highQuality=null;
        if(fontBytes&&window.XStageProMidi?.available?.()){
          try{
            highQuality=await window.XStageProMidi.prepare(source,fontBytes,{
              onStatus:message=>{if(isCurrent())setPlayStatus(message);}
            });
          }catch(error){
            console.warn('Professional SoundFont engine unavailable:',error);
          }
        }
        if(!isCurrent()){highQuality?.dispose();return;}
        let nextEngine=null;
        try{
          nextEngine=highQuality
            ?attachProfessionalMidiEngine(highQuality,options)
            :window.XStageBrowserMidi.playRealtime(player,source,options);
        }catch(error){
          highQuality?.dispose();
          if(!highQuality)throw error;
          nextEngine=window.XStageBrowserMidi.playRealtime(player,source,options);
        }
        const previous=state.liveMidiPlayback;
        state.liveMidiPlayback=nextEngine;
        previous?.dispose();
        window.XStageBrowserMidi.finishFontTrial?.(fontBytes);
        setMidiEngineStatus(nextEngine);
        setPlayStatus('เปลี่ยน SoundFont สำเร็จ · '+(nextEngine.engine||'Web Audio สำรอง'));
      }catch(error){
        if(generation===state.xskSoundFontGeneration&&error?.name!=='AbortError'&&
           await window.XStageBrowserMidi.recoverFont?.(null,error.message))
          window.dispatchEvent(new CustomEvent('xstage:soundfont-change'));
        setPlayStatus('เปลี่ยน SoundFont ไม่สำเร็จ: '+error.message);
      }
    })();
  }
  scheduleQueuePreload();
});
window.addEventListener('xstage:font-memory',()=>{
  trimQueueCache();updateMemoryIndicators();
});
// Periodic passive pressure check: no network activity and no forced GC.
// Eviction releases references; the browser/OS manages actual RAM reclaim.
window.setInterval(()=>{
  if(state.queuePreparedCache.size){
    const before=state.queuePreparedCache.size;
    trimQueueCache();
    if(state.queuePreparedCache.size<before)renderQueue();
  }else updateMemoryIndicators();
},10000);
window.addEventListener('xstage:font-memory-error',event=>{
  const el=document.getElementById('xstage-font-memory');
  if(el){el.dataset.level='high';el.textContent='SoundFont: '+String(event.detail?.message||'ไม่พร้อม');}
});
async function preloadFirstQueueSong(song,token){
  if(!state.queue.includes(song)||state.token!==token||
     state.loading||state.queuePreparedCache.has(song))return;
  const controller=new AbortController(),version=++state.queuePreloadVersion;
  const task={song,token,controller,promise:null};state.queuePreload=task;
  // Preserve the same Promise if this queued song reaches playback before
  // pre-render finishes; avoids a redundant Drive fetch and MIDI render.
  task.promise=prepareQueuedSong(song,token,controller.signal);
  try{
    const result=await task.promise;
    if(version!==state.queuePreloadVersion||controller.signal.aborted||
       state.token!==token||!state.queue.includes(song))return;
    if(result)state.queuePreparedCache.set(song,result);
    else state.queuePreloadSkipped.add(song);
    trimQueueCache();
    // Avoid repainting the whole queue on every byte read.
    renderQueue();
  }catch(error){
    if(error.name!=='AbortError'){
      state.queuePreloadSkipped.add(song);
      console.warn('X-Stage queue prefetch:',error.message);
    }
  }finally{
    if(state.queuePreload===task)state.queuePreload=null;
    if(state.token===token&&!state.loading)
      state.queuePreloadTimer=setTimeout(scheduleQueuePreload,500);
  }
}
// Medley and manually queued songs share the SAME verified one-song
// preloader. No MIDI/XSK/XMID formats are silently skipped, no second
// SoundFont download is started, and a queue request always wins.
function prefetchMedleyNext(){
  if(!state.medley||!state.token||state.queue.length||state.loading||
     !state.current||player.paused||state.userStopped||state.userPaused)return;
  const song=nextMedleyCandidate(),token=state.token;
  if(!song)return;
  // Pressure, offline and corrupt-file failures must not trigger a new
  // private Drive request on every 100 ms playback tick.
  if(state.medleyPreloadFailedSong===song&&
     Date.now()<state.medleyPreloadRetryAt)return;
  if(state.medleyCache?.song===song&&state.medleyCache?.token===token)return;
  if(state.medleyPrefetch?.song===song&&state.medleyPrefetch?.token===token)return;
  state.medleyPrefetch?.controller?.abort();
  state.medleyCache=null;
  const controller=new AbortController();
  const task={song,token,controller,promise:null};
  state.medleyPrefetch=task;
  task.promise=prepareQueuedSong(song,token,controller.signal);
  void task.promise.then(result=>{
    if(controller.signal.aborted||state.medleyPrefetch!==task||
       !state.medley||state.queue.length||state.token!==token||
       nextMedleyCandidate()!==song)return;
    if(result&&(result.blob?.size||result.liveMidi?.byteLength)&&
       result.lyrics?.schemaVersion===1){
      state.medleyCache=result;
      state.medleyPreloadFailedSong=null;state.medleyPreloadRetryAt=0;
      updateMemoryIndicators();
    }else{
      state.medleyPreloadFailedSong=song;
      state.medleyPreloadRetryAt=Date.now()+30000;
    }
  }).catch(error=>{
    if(error?.name!=='AbortError'){
      state.medleyPreloadFailedSong=song;
      state.medleyPreloadRetryAt=Date.now()+30000;
      console.warn('X-Stage medley prefetch:',error?.message||error);
    }
  }).finally(()=>{
    if(state.medleyPrefetch===task)state.medleyPrefetch=null;
  });
}
function medleyTick(){
  if(!state.medley||state.loading||player.paused||state.queue.length)return;
  // Start preparing early, not only within 25 seconds of the end. Even a
  // large private file can arrive before the transition if RAM permits.
  prefetchMedleyNext();
}
function addToQueue(song) {
  if(!playable(song))return;
  // Requested songs take priority over speculative shuffled medley tracks.
  state.medleyPrefetch?.controller?.abort();
  state.medleyPrefetch=null;state.medleyCache=null;state.medleyUpcoming=null;
  state.medleyPreloadFailedSong=null;state.medleyPreloadRetryAt=0;
  state.queue.push(song);renderQueue();scheduleQueuePreload();
  setPlayStatus(`เพิ่มเข้าคิว: ${song.title||song.code}`);
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
    const info=element('div','queue-info');
    const waiting=state.queuePreload?.song===song;
    const ready=state.queuePreparedCache.has(song);
    info.append(element('strong','',song.title||'ไม่ระบุชื่อเพลง'),
      element('small','',(song.artist||song.code||'')+
        (ready?' · เตรียมพร้อมเล่นแล้ว':waiting?' · กำลังโหลดรอในงบ RAM':
          state.queuePreloadSkipped.has(song)?' · รอโหลดเมื่อถึงคิว':'')));
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
function stopSoundFontFill(){
  const fill=state.transitionFill;
  state.transitionFill=null;
  try{fill?.stop?.();}catch(error){console.warn('SoundFont bridge cleanup:',error);}
}
function releaseFinishedMedia(){
  // Drop the completed/aborted track's media objects, but preserve its
  // identity in history until playSong starts the next one.
  try{player.pause();}catch{}
  state.liveMidiPlayback?.dispose();state.liveMidiPlayback=null;state.liveMidiSource=null;
  // MIDI uses a synthetic transport source rather than an object URL.
  // Clear it even when state.objectUrl is empty; otherwise the next queue
  // item still sees the previous track as the active player.
  if(midiTransport.active)midiTransport.clear();
  if(state.objectUrl){
    URL.revokeObjectURL(state.objectUrl);
    state.objectUrl='';
  }
  nativePlayer.removeAttribute('src');
  resetSongVideo();
  state.activeBlobBytes=0;state.activeVideoBytes=0;
  trimQueueCache();
}
function playNext(){
  if(state.updateAfterTrack&&state.updateAvailable&&!webGoogleAuthFlow&&!state.authRecovering){
    // The outgoing song has ended or the owner skipped to the next one.
    // Preserve the requested next song instead of reloading into the
    // already-ended song. Do not consume/mutate the queue before snapshot.
    const upcoming=state.queue[0]||(state.medley?nextMedleyCandidate():null);
    if(upcoming){
      try{
        sessionStorage.setItem(PLAYBACK_RESUME_KEY,JSON.stringify({
          savedAt:Date.now(),rootId:String(state.libraryRootId||''),
          songKey:songIdentity(upcoming),
          songCode:String(upcoming.code||''),
          songTitle:String(upcoming.title||''),
          currentTime:0,wasPlaying:true,
          queueKeys:state.queue[0]===upcoming
            ?state.queue.slice(1).map(songIdentity):state.queue.map(songIdentity)
        }));
      }catch{}
    }else clearPlaybackResumeState();
    state.updateAfterTrack=false;
    void performAppUpdateReload({preserveSnapshot:true});
    return;
  }
  const queued=state.queue.shift();
  const preparedQueued=queued?(state.queuePreparedCache.get(queued)||null):null;
  if(queued)state.queuePreparedCache.delete(queued);
  // Promote an XSK2 pre-render that is still running to active playback.
  // The next queue's preloader must not abort this in-flight job.
  const pendingQueued=queued&&state.queuePreload?.song===queued?state.queuePreload:null;
  if(preparedQueued)state.queuePrepared=null;
  if(pendingQueued)state.queuePreload=null;
  state.queuePreloadSkipped.clear();
  const song=queued||(state.medley?nextMedleyCandidate():null);
  const pendingMedley=!queued&&song&&state.medleyPrefetch?.song===song
    ?state.medleyPrefetch:null;
  if(pendingMedley)state.medleyPrefetch=null;
  const nextIsMidi=!!song&&!!(getFileId(song.midi)||getFileId(song.xmid)||getFileId(song.xsk));
  window.XStageIOSMidiAudio?.keepPlayingBetweenSongs?.(nextIsMidi);
  stopSoundFontFill();
  if(song&&!state.userPaused&&!state.userStopped){
    // The outgoing GM/GS Worklet continues a subtle rhythm during the
    // next song's preparation. It is detached from the old transport and
    // stops when the new audio begins (or after its own safety timeout).
    try{
      const fill=state.liveMidiPlayback?.beginTransitionFill?.();
      if(fill?.stop){
        state.transitionFill=fill;
        state.liveMidiPlayback=null;
      }
    }catch(error){console.warn('SoundFont transition fill:',error);}
  }
  releaseFinishedMedia();
  scheduleQueuePreload();
  if(!queued)state.medleyUpcoming=null;
  state.userStopped=false;
  if(state.medleyCache&&state.medleyCache.song!==song)state.medleyCache=null;
  renderQueue();
  if(song){
    if(state.medley){
      state.medleyRecent.push(song);
      if(state.medleyRecent.length>MEDLEY_RECENT_LIMIT)state.medleyRecent.shift();
    }
    playSong(song,{preloaded:preparedQueued,pending:pendingQueued||pendingMedley});
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
      title:song.title||'ไม่ระบุชื่อเพลง',
      artist:song.artist||'ไม่ระบุศิลปิน',
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
  stopSoundFontFill();
  state.userStopped=true;
  state.requestId++;
  state.controller?.abort();
  state.controller=null;
  state.loading=false;
  state.liveMidiPlayback?.dispose();state.liveMidiPlayback=null;state.liveMidiSource=null;
  window.XStageIOSMidiAudio?.release?.();
  player.pause();
  releaseNativePlaybackAudioFocus();
  player.removeAttribute('src');
  player.load();
  if(state.objectUrl)URL.revokeObjectURL(state.objectUrl);
  state.objectUrl='';
  state.activeBlobBytes=0;
  state.activeVideoBytes=0;
  state.current=null;
  state.lyrics=null;
  clearPlaybackResumeState();
  clearMediaSession();
  state.medleyCache=null;
  state.medleyPrefetch=null;
  state.medleyUpcoming=null;
  releaseQueuePreload();
  if(midiKeyControl)midiKeyControl.hidden=true;
  window.XStageMIDIPiano?.setSong({bytes:null});
  ui.nowPlaying.textContent='ยังไม่มีเพลงกำลังเล่น';
  ui.nowArtist.textContent='';
  ui.stageCode.textContent='—';
  setSongKeyDisplay();
  ui.stage.classList.remove('playing');
  window.XStageStageLighting?.clearMidiNotes?.();
  ui.stageIdle.hidden=false;
  if(typeof pen!=='undefined')pen.clearRect(0,0,ui.lyrics.width,ui.lyrics.height);
  setPlayStatus(message);
  updateTransport();
  if(state.updateAfterTrack&&state.updateAvailable){
    state.updateAfterTrack=false;
    setTimeout(()=>performAppUpdateReload(),180);
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
  if(!requestNativePlaybackAudioFocus())return;
  player.play().catch(()=>setPlayStatus('เพลงพร้อมแล้ว · กด ▶ เพื่อเริ่มเล่น'));
  updateTransport();
}
async function resumePlaybackFromSystem(){
  try{window.XStageIOSMidiAudio?.activate?.();}catch{}
  if(state.loading)return false;
  if(!player.src){if(state.queue.length){playNext();return true;}return false;}
  if(!requestNativePlaybackAudioFocus())return false;
  state.userPaused=false;
  state.userStopped=false;
  state.resumeAfterInterruption=false;
  try{await window.XStageResumeAudioGraph?.();}catch{}
  try{
    await player.play();
    // Safari can resolve the virtual MIDI transport play() while its actual
    // SoundFont AudioContext or iPhone media relay remains suspended.
    if(midiTransport.active&&state.liveMidiPlayback?.resumeAudio){
      const audible=await state.liveMidiPlayback.resumeAudio();
      if(audible===false){
        state.resumeAfterInterruption=true;
        updateTransport();
        return false;
      }
    }
    updateTransport();return true;
  }catch{state.resumeAfterInterruption=true;updateTransport();return false;}
}
function togglePlayback(){
  try{window.XStageIOSMidiAudio?.activate?.();}catch{}
  try{window.XStageBrowserMidi?.unlockAudio?.();}catch{}
  if(state.loading)return;
  // iOS can report a running virtual transport with silent output after
  // lock-screen wake. A tap on Play must recover the audio route, not pause
  // the song and force the user to tap twice.
  if(wakeNeedsGesture&&!state.userPaused&&!state.userStopped){
    void recoverScreenAudio();
    return;
  }
  if(!player.src){
    if(state.queue.length)playNext();
    else if(state.shown.length)playSong(state.shown[state.selectedIndex]);
    else setPlayStatus('ยังไม่มีเพลงที่เลือก · ค้นหาชื่อเพลงหรือรหัสเพลง แล้วกด Enter เพื่อเริ่มเล่น');
    return;
  }
  if(player.paused)resumePlaybackFromSystem();
  else{state.userPaused=true;state.resumeAfterInterruption=false;screenSleepIntent=null;wakeNeedsGesture=false;player.pause();}
}

async function playSong(song,{remember=true,preloaded=null,pending=null,resumeAt=0,autoplay=true}={}) {
  // Capture the user gesture before asynchronous Drive/SF2 downloads.
  if(autoplay){
    try{window.XStageIOSMidiAudio?.activate?.();}catch{}
    try{window.XStageBrowserMidi?.unlockAudio?.();}catch{}
  }
  state.userStopped=false;
  if (!state.token) {setStatus('กรุณาเข้าสู่ระบบ Google ก่อนเล่นเพลง','error');return;}
  if (!playable(song)) {
    setPlayStatus('เพลงนี้ยังไม่มี XSK2 หรือไฟล์เสียง/MIDI พร้อม Lyrics JSON ที่พร้อมเล่น');
    return;
  }
  // Safari allows media playback most reliably when the output element is
  // started during the original tap, before asynchronous Google Drive reads.
  if(autoplay&&(getFileId(song.midi)||getFileId(song.xmid)||getFileId(song.xsk))){
    try{
      void window.XStageIOSMidiAudio?.prime?.(
        window.XStageBrowserMidi?.liveAudioContext?.()
      ).catch(error=>console.warn('iPhone MIDI media prime:',error?.message||error));
    }catch{}
  }
  const request=++state.requestId;
  window.XStageMIDIPiano?.setSong({bytes:null});
  state.liveMidiPlayback?.dispose();state.liveMidiPlayback=null;state.liveMidiSource=null;
  state.controller?.abort();const controller=new AbortController();state.controller=controller;
  const token=state.token;
  state.loading=true;
  state.preparingSong=song;
  updateTransport();
  // Paint metadata right away while private audio/SoundFont is still loading.
  scheduleLyricsDraw();
  setPlayStatus('กำลังเตรียมเพลง: '+(song.title||song.code||'ไม่ระบุชื่อ')+' · กำลังโหลดจาก Google Drive…');
  // Preload only public synth assets, in parallel with private Drive loading.
  // A browser cannot execute a downloaded BASSMIDI DLL. The local AudioWorklet
  // is the appropriate platform-safe equivalent; files use the browser cache.
  const isMidiSong=!!(getFileId(song?.midi)||getFileId(song?.xmid)||getFileId(song?.xsk));
  if(isMidiSong&&window.XStageProMidi?.available?.()){
    const engineLabel=$('xstage-midi-engine-status');
    if(engineLabel){engineLabel.hidden=false;engineLabel.textContent='กำลังเตรียมเครื่องเสียง MIDI…';}
    void window.XStageProMidi.preload({
      onStatus:message=>{
        if(request===state.requestId&&!state.liveMidiPlayback&&engineLabel)
          engineLabel.textContent=message;
      }
    }).catch(error=>{
      if(request===state.requestId&&!state.liveMidiPlayback&&engineLabel){
        engineLabel.textContent='เครื่องเสียงคุณภาพสูงไม่พร้อม · ตัวเล่นสำรองยังใช้งานได้';
      }
      console.warn('Local MIDI engine preloading:',error?.message||error);
    });
  }
  // Keep the title visible while the potentially slow MIDI renderer works.
  ui.nowPlaying.textContent=song.title||song.code||'กำลังเตรียมเพลง';
  ui.nowArtist.textContent=song.artist||'';
  const startedAt=Date.now();
  const loadingNotice=setInterval(()=>{
    if(request!==state.requestId||!state.loading)return;
    const elapsed=Math.floor((Date.now()-startedAt)/1000);
    if(elapsed>=15 && elapsed%5===0)
      setPlayStatus('กำลังเตรียม '+(song.title||song.code)+
        ' · '+elapsed+' วินาที · กำลังรับไฟล์เพลงหรือเตรียมเครื่องเสียง · กดหยุดเพื่อยกเลิกได้');
  },1000);
  publishPlaybackStatus('loading',song,'กำลังเตรียมไฟล์เพลงจาก Google Drive');
  try {
    const cached=state.queuePreparedCache.get(song);
    const prepared=(preloaded?.song===song&&preloaded.token===token?preloaded
      :cached?.token===token?cached
      :state.medleyCache?.song===song&&state.medleyCache.token===token
        ?state.medleyCache:null);
    if(prepared){
      state.queuePreparedCache.delete(song);
      if(state.queuePrepared===prepared)state.queuePrepared=null;
      if(state.medleyCache===prepared)state.medleyCache=null;
    }
    let pendingPrepared=null;
    if(!prepared&&pending?.song===song&&pending.token===token&&pending.promise){
      setPlayStatus('กำลังรับช่วงเพลงที่เตรียมล่วงหน้าอยู่…');
      const stopPending=()=>pending.controller.abort();
      controller.signal.addEventListener('abort',stopPending,{once:true});
      try{
        const result=await boundedPlaybackTask(pending.promise,120,
          'เตรียมเพลงที่อยู่ในคิวนานเกินไป',controller);
        if(result?.song===song&&result.token===token&&
           (result.blob?.size||result.liveMidi?.byteLength)&&
           result.lyrics?.schemaVersion===1)pendingPrepared=result;
      }catch(error){
        if(controller.signal.aborted)throw error;
        console.warn('Queued XSK pre-render unavailable, retry on demand:',error.message);
      }finally{
        controller.signal.removeEventListener('abort',stopPending);
      }
    }
    const readyPrepared=prepared||pendingPrepared;
    let embeddedKaraokeLyrics=null,liveMidiBytes=null,liveFontBytes=null,lateFontPromise=null;
    const loadMedia=async()=>{
      if(!getFileId(song.midi))return fastPrivateBlob(song.audio.fileId,token,
        {signal:controller.signal,size:Number(song.audio.size)||0});
      if(!window.XStageBrowserMidi)throw Error('ไม่พบเครื่องเล่น MIDI ของเว็บ กรุณาอัปเดตหน้าเว็บ');
      setPlayStatus('กำลังโหลด MIDI และ SoundFont จาก Google Drive…');
      const fontTask=getStartupSoundFont(token,controller.signal);
      const midiBlob=await fastPrivateBlob(song.midi.fileId,token,
        {signal:controller.signal,size:Number(song.midi.size)||0});
      const {bytes:fontBytes,pending:lateFont}=await fontTask;
      lateFontPromise=lateFont;
      if(controller.signal.aborted)throw new DOMException('ยกเลิก','AbortError');
      const midiBytes=new Uint8Array(await midiBlob.arrayBuffer());
      if(song.sourceFormat==='KAR'&&!getFileId(song.lyrics)){
        const parsed=window.XStageBrowserMidi.parseMidi(midiBytes);
        embeddedKaraokeLyrics=window.XStageBrowserMidi.midiLyrics(parsed,song.code);
      }
      if(window.XStageBrowserMidi.supportsRealtime?.()){
        const parsed=window.XStageBrowserMidi.parseMidi(midiBytes);
        liveMidiBytes=midiBytes;liveFontBytes=fontBytes;
        return null;
      }
      let verifiedBank=await ensureMidiInstrumentBank(fontBytes,lateFont,token,controller);
      const rendered=await renderWithSoundFontRecovery(midiBytes,verifiedBank,token,controller,{
        onStatus:message=>{if(request===state.requestId)setPlayStatus(message);}
      });
      return rendered.audio;
    };
    let audio,lyrics;
    if(readyPrepared){
      // XSK2 prepared fully or in progress while queued: consume its
      // verified audio directly, without duplicating download/render.
      ({blob:audio,lyrics}=readyPrepared);
      liveMidiBytes=readyPrepared.liveMidi||null;
      liveFontBytes=readyPrepared.liveFont||null;
      lateFontPromise=readyPrepared.lateFont||null;
    }else if(getFileId(song.xsk)||getFileId(song.xmid)||
             (song.pendingDriveLink===true&&(song.xsk?.path||song.xmid?.path))){
      const ready=await boundedPlaybackTask(
        prepareXskPlayback(song,token,controller.signal,message=>{
          if(request===state.requestId)setPlayStatus(message);
        }),120,'โหลดหรือแยก XSK2 จาก Google Drive นานเกินไป',controller);
      audio=ready.blob;lyrics=ready.lyrics;liveMidiBytes=ready.liveMidi||null;
      liveFontBytes=ready.liveFont||null;
      lateFontPromise=ready.lateFont||null;
    }else{
      [audio,lyrics]=await boundedPlaybackTask(Promise.all([
        loadMedia(),
        getFileId(song.lyrics)
          ?privateJson(song.lyrics.fileId,token,{signal:controller.signal})
          :Promise.resolve(null)
      ]),120,'เตรียมเพลงจาก Google Drive/เรนเดอร์ MIDI นานเกินไป',controller);
      if(!lyrics&&song.sourceFormat==='KAR')lyrics=embeddedKaraokeLyrics;
    }
    if (lyrics?.schemaVersion !== 1 || !Array.isArray(lyrics.lines)) throw Error('ไฟล์ Lyrics JSON ไม่รองรับ');
    if (request!==state.requestId||token!==state.token){controller.abort();return;}
    if(!liveMidiBytes&&!audio?.size)throw Error('ไฟล์เสียง/MIDI ว่างเปล่า');
    if(liveMidiBytes){
      if(!liveFontBytes&&!lateFontPromise){
        // Preloaded MIDI contains only verified song bytes and lyrics.
        // The SoundFont remains shared and loads from its session cache.
        const startup=await getStartupSoundFont(token,controller.signal);
        liveFontBytes=startup.bytes;lateFontPromise=startup.pending;
      }
      // First play used to skip the SoundFont after a 1–2 s loading budget,
      // so its oscillator notes sounded like an 8-bit game. Resolve the
      // pending bank BEFORE we start the first MIDI transport and emit audio.
      liveFontBytes=await ensureMidiInstrumentBank(
        liveFontBytes,lateFontPromise,token,controller);
      lateFontPromise=null;
      if(controller.signal.aborted||request!==state.requestId||
         token!==state.token)return;
    }
    const url=liveMidiBytes?'':URL.createObjectURL(audio);
    if (remember && state.current)state.history.push(state.current);
    player.pause();if(state.objectUrl)URL.revokeObjectURL(state.objectUrl);
    state.objectUrl=url;state.current=song;state.lyrics=lyrics;
    state.activeBlobBytes=audio?.size||0;trimQueueCache();
    resetSongVideo();
    preferOriginalVideo=true;
    if(getFileId(song.video))void loadSongVideo(song,request,token,controller.signal);
    syncMediaSessionMetadata(song);
    ui.nowPlaying.textContent=song.title||'ไม่ระบุชื่อเพลง';ui.nowArtist.textContent=song.artist||'ไม่ระบุศิลปิน';
    const metadataKey=song.key||song.musicKey||song.originalKey||song.keySignature||'';
    // A MIDI file may specify its musical key even when the song catalog
    // does not. Use its actual FF 59 signature, never guess from audio notes.
    const midiSignature=!metadataKey&&liveMidiBytes
      ?window.XStageBrowserMidi?.parseMidi(liveMidiBytes)?.keySignature||'':'';
    const musicalKey=String(metadataKey||midiSignature).trim();
    ui.stageCode.textContent=song.code||'—';
    setSongKeyDisplay(musicalKey);
    ui.stage.classList.add('playing');ui.stageIdle.hidden=true;
    if(midiKeyControl)midiKeyControl.hidden=!liveMidiBytes;
    if($('midi-instrument'))$('midi-instrument').value='';
    if(midiKeyValue){midiKeyValue.value='0';syncMidiKeyButtons();}
    if(liveMidiBytes){
      const midiOptions={
        fontBytes:liveFontBytes,onStatus:setPlayStatus,
        getTranspose:()=>Number(document.getElementById('midi-transpose')?.value||0),
        getProgram:()=>{const value=$('midi-instrument')?.value;return value===''?null:Number(value);}
      };
      const professionalOptions={
        signal:controller.signal,
        onStatus:message=>{if(request===state.requestId&&!state.liveMidiPlayback)setPlayStatus(message);}
      };
      // Keep the first notes silent until the real GM/GS sample bank and
      // synthesizer are ready. This prevents first-play 8-bit audio.
      setPlayStatus('กำลังเปิดเครื่องเสียง MIDI ด้วย SoundFont…');
      // The previous MIDI handoff owns a loaded SpessaSynth/GM bank and
      // continues a bounded rhythm. Reuse that SAME Worklet for MIDI->MIDI
      // rather than allocating another 200+ MB SoundFont and going silent.
      window.XStageBrowserMidi.beginFontTrial?.(liveFontBytes);
      let professional=null;
      const handoff=state.transitionFill;
      if(handoff?.prepareNextMidi){
        try{
          professional=await handoff.prepareNextMidi(
            liveMidiBytes,liveFontBytes,{signal:controller.signal});
        }catch(error){
          if(error?.name==='AbortError')throw error;
          console.warn('Warm GM medley handoff unavailable:',error);
        }
      }
      if(!professional)professional=await prepareFirstMidiSynth(
        liveMidiBytes,liveFontBytes,professionalOptions);
      if(!professional){
        // Prime cold SF2 sample buffers before the first audible MIDI note.
        setPlayStatus('กำลังเตรียมตัวอย่างเสียงเครื่องดนตรีก่อนเริ่มเพลง…');
        try{
          await window.XStageBrowserMidi.warmRealtimeSamples(liveMidiBytes,
            liveFontBytes,{signal:controller.signal,
              onStatus:message=>{if(request===state.requestId)setPlayStatus(message);}});
        }catch(error){
          if(controller.signal.aborted||error?.name==='AbortError'){
            window.XStageBrowserMidi.finishFontTrial?.(liveFontBytes);throw error;
          }
          if(!await window.XStageBrowserMidi.recoverFont?.(liveFontBytes,error.message))throw error;
          liveFontBytes=await ensureMidiInstrumentBank(null,null,token,controller);
          midiOptions.fontBytes=liveFontBytes;
          await window.XStageBrowserMidi.warmRealtimeSamples(liveMidiBytes,liveFontBytes,{signal:controller.signal});
        }
      }
      if(controller.signal.aborted||request!==state.requestId||
         token!==state.token){
        professional?.dispose();
        return;
      }
      state.liveMidiSource=liveMidiBytes;
      const parsedLiveMidi=window.XStageBrowserMidi.parseMidi(liveMidiBytes);
      window.XStageStageLighting?.setMidiNotes?.(parsedLiveMidi.notes,parsedLiveMidi.duration);
      midiTransport.begin(parsedLiveMidi.duration,midiTailHandoffCue(parsedLiveMidi,lyrics));
      try{
        state.liveMidiPlayback=professional
          ?attachProfessionalMidiEngine(professional,midiOptions)
          :window.XStageBrowserMidi.playRealtime(player,liveMidiBytes,midiOptions);
        setMidiEngineStatus(state.liveMidiPlayback);
        if(window.XStageBrowserMidi.isFastGmBytes?.(liveFontBytes)){
          const engine=$('xstage-midi-engine-status');
          if(engine){engine.hidden=false;engine.textContent+=' · GM 6 MB (โหลดเร็ว)';}
        }
      }catch(error){
        professional?.dispose();
        if(!professional)throw error;
        console.warn('Professional MIDI start:',error);
        state.liveMidiPlayback=window.XStageBrowserMidi.playRealtime(
          player,liveMidiBytes,midiOptions);
        setMidiEngineStatus(state.liveMidiPlayback);
      }
      window.XStageBrowserMidi.finishFontTrial?.(liveFontBytes);
      window.XStageMIDIPiano?.setSong({
        bytes:liveMidiBytes,
        getCurrentTime:()=>Number(player.currentTime)||0,
        isPlaying:()=>!player.paused&&!player.ended,
        previewNote:(note,on)=>!!state.liveMidiPlayback?.previewNote?.(
          note,on,$('midi-instrument')?.value||'')
      });
    }else{
      window.XStageStageLighting?.clearMidiNotes?.();
      window.XStageMIDIPiano?.setSong({bytes:null});
      setMidiEngineStatus(null);
      window.XStageIOSMidiAudio?.release?.();
      if(midiTransport.active)midiTransport.clear();
      player.src=url;
    }
    try{
      if('preservesPitch' in player)player.preservesPitch=true;
      if('mozPreservesPitch' in player)player.mozPreservesPitch=true;
      if('webkitPreservesPitch' in player)player.webkitPreservesPitch=true;
    }catch{}
    player.playbackRate=Number(ui.speed.value);player.loop=ui.repeat.checked;
    player.volume=karaokeOutputGain();
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
    if(!autoplay)stopSoundFontFill();
    if(autoplay){
      if(!requestNativePlaybackAudioFocus())throw Error('Android Audio Focus ไม่พร้อม · ยังไม่เริ่มเสียงเพลง');
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
  }catch(e){
    if(request!==state.requestId||e.name==='AbortError')return;
    // A failed automatic queue handoff must not keep a silent iPhone
    // MediaStream playing without an active synthesizer.
    if(!state.liveMidiPlayback){
      window.XStageIOSMidiAudio?.release?.();
      if(midiTransport.active)midiTransport.clear();
    }
    const message=e.message||'ไม่สามารถเล่นเพลงได้';
    stopSoundFontFill();
    setPlayStatus(message);publishPlaybackStatus('error',song,message);
    state.loading=false;updateTransport();
  }
  finally{
    clearInterval(loadingNotice);
    if(request===state.requestId){
      state.loading=false;state.preparingSong=null;state.controller=null;
      updateTransport();scheduleLyricsDraw();
    }
  }
}
function updateTransport(){
  ui.stage.classList.toggle('loading',!!state.loading);
  const musicLoader=document.getElementById('music-loader');
  if(musicLoader)musicLoader.setAttribute('aria-hidden',String(!state.loading));
  ui.playPause.disabled=state.loading||(!state.current&&!state.queue.length&&!state.shown.length);
  ui.playPause.textContent=player.src&&!player.paused&&!wakeNeedsGesture?'Ⅱ':'▶';
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
      const visibleSong=state.loading?state.preparingSong:state.current;
      if(visibleSong){
        const when=Math.max(0,player.currentTime+(Number(state.lyrics?.audioOffsetMs)||0)/1000);
        const lines=state.loading?[]:(Array.isArray(state.lyrics?.lines)?state.lyrics.lines:[]);
        let idx=-1;
        for(let i=0;i<lines.length;i++){if(Number(lines[i].startTime)<=when)idx=i;else break;}
        const fontSize=Math.min(76,w*.062,h*.14);
        // Keep both lyric lines above the integrated transport/virtual keyboard.
        const density=Math.min(window.devicePixelRatio||1,2);
        const transportBox=ui.stage.querySelector('.transport-panel')?.getBoundingClientRect();
        const transportHeight=transportBox?.height||0;
        const keyboard=ui.stage.querySelector('#virtual-keyboard');
        const keyboardHeight=keyboard&&!keyboard.hidden?keyboard.getBoundingClientRect().height+7:0;
        // Mobile transport sits ABOVE the docked search. Reserve the real
        // transport's top position rather than only its height, so neither
        // lyric line can slide underneath the player or the search field.
        const mobileBottomSearch=document.body.classList.contains('xstage-mobile-search-bottom');
        const canvasBox=ui.lyrics.getBoundingClientRect();
        const canvasScale=h/Math.max(1,canvasBox.height);
        const transportTop=transportBox?(transportBox.top-canvasBox.top)*canvasScale:h;
        const usableBottom=mobileBottomSearch
          ?Math.min(h-(keyboardHeight+12)*density,transportTop-16*density)
          :h-(transportHeight+keyboardHeight+12)*density;
        const lyricLift=fontSize*(mobileBottomSearch?1.8:1.45);
        let nextY=Math.max(h*.22,Math.min(h*.83,usableBottom-fontSize*.8)-lyricLift);
        let currentY=Math.max(h*.10,Math.min(h*.66,nextY-fontSize*1.45));
        if(mobileBottomSearch){
          nextY=Math.min(nextY,usableBottom-fontSize*.9);
          currentY=Math.min(currentY,nextY-fontSize*1.45);
        }
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
        if(idx<0){
          // Intro/selection card replaces premature first-line lyrics. It
          // clears as soon as the first real timed lyric begins; no overlap
          // with the syllable wipe or any subsequent lyric frame.
          drawLine(String(visibleSong.title||visibleSong.code||'ไม่ระบุชื่อเพลง'),
            Math.min(h*.72,currentY),lyricWidth,lyricFont,'#ecf7ff',null,lyricCenter);
          if(visibleSong.artist)drawLine(String(visibleSong.artist),
            nextY,lyricWidth,lyricFont*.76,'#aee9ed',null,lyricCenter);
        }
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
  if(!player.paused&&!player.ended)scheduleLyricsDraw();
}
let lyricsFrame=0;
function scheduleLyricsDraw(){
  if(lyricsFrame)return;
  lyricsFrame=requestAnimationFrame(()=>{lyricsFrame=0;drawLyrics();});
}
for(const name of ['play','playing','pause','ended','seeked','timeupdate','loadedmetadata','emptied']){
  player.addEventListener(name,()=>{
    if(name==='play'||name==='playing'||player.paused||player.ended)scheduleLyricsDraw();
  });
}

// The stage clock runs independently in index.html.
ui.librarySelect?.addEventListener('change',()=>{
  const rootId=String(ui.librarySelect.value||'');
  if(!rootId||!state.accountSub||isRetiredDriveRoot(rootId))return;
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
    'desktop-update-version','logout','toggle-keyboard',
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
    // Never leave private song titles in TV search/queue overlays after access loss.
    xstageTvCloseSearch(false);xstageTvCloseQueue(false);
    const quickMenu=document.getElementById('xstage-tv-quick-menu');
    if(quickMenu)quickMenu.hidden=true;
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
    '<img class="android-tv-auth-brand" src="assets/xstage-stage-logo.png?v=1124" width="2048" height="682" alt="X-Stage Karaoke Online">'+
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
    script.src='./assets/vendor/qrcode.min.js?v=1217';
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
    if(nativeUpdateInstalling)return;
    nativeUpdateInstalling=true;
    $('android-tv-update-title').textContent='ขั้นที่ 2/2 · กำลังอัปเดต X-Stage';
    const later=$('android-tv-update-later');if(later)later.hidden=true;
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
  if(!androidTvNativeBridgeReady()||nativeUpdateInstalling)return;
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
  $('android-tv-update-title').textContent='ขั้นที่ 1/2 · พบ X-Stage รุ่นใหม่ · Build '+next.build;
  const later=$('android-tv-update-later');if(later)later.hidden=false;
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
  const later=$('android-tv-update-later');if(later)later.hidden=false;
  const button=$('android-tv-update-now');
  if(button){button.disabled=false;button.textContent='ลองอัปเดตอีกครั้ง';}
};
window.XStageAndroidNoUpdate=()=>{
  if(nativeUpdateInstalling)return;
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
  // Explicit tap: reuse the last verified Google account and existing Drive
  // consent. Sign out first to deliberately choose a different account.
  login({remembered:!!rememberedGoogleAccount()});
}
ui.login.addEventListener('click',startManualGoogleLogin);ui.gateLogin.addEventListener('click',startManualGoogleLogin);
const googleSwitchButton=$('gate-switch-google');
function syncRememberedAccountChooser(){
  if(googleSwitchButton)googleSwitchButton.hidden=!rememberedGoogleAccount()||!!state.token;
}
googleSwitchButton?.addEventListener('click',()=>{
  // Explicitly forget the saved identity before opening Google's account picker.
  // A different Google account is never selected as part of silent renewal.
  rememberLogin(false);clearActiveAuth();clearPendingAuth();
  syncRememberedAccountChooser();
  login({remembered:false});
});
window.addEventListener('xstage:auth-ready',syncRememberedAccountChooser);
window.addEventListener('xstage:auth-cleared',syncRememberedAccountChooser);
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
const midiKeyControl=$('midi-transpose-control'),midiKeyValue=$('midi-transpose');
function syncMidiKeyButtons(){
  if(!midiKeyValue)return;
  const raw=Number(midiKeyValue.value);
  const value=Math.max(-12,Math.min(12,Number.isFinite(raw)?Math.trunc(raw):0));
  midiKeyValue.value=String(value);
  const label=$('midi-transpose-label');
  if(label)label.textContent=value>0?'+'+value:String(value);
  const down=$('midi-key-down'),up=$('midi-key-up');
  if(down)down.disabled=value<=-12;
  if(up)up.disabled=value>=12;
  setSongKeyDisplay();
}
function setMidiKey(delta){
  // The value remains editable while the song/synth swaps playback engines.
  // In particular, -12 must never lock the PLUS control.
  if(!midiKeyValue||midiKeyControl?.hidden)return;
  const before=Math.max(-12,Math.min(12,Number(midiKeyValue.value)||0));
  const value=Math.max(-12,Math.min(12,before+delta));
  if(value===before){syncMidiKeyButtons();return;}
  midiKeyValue.value=String(value);
  syncMidiKeyButtons();
  try{
    nativePlayer.dispatchEvent(new Event('xstage-midi-transpose'));
  }catch(error){
    console.warn('MIDI transpose engine notification:',error);
  }
}
$('midi-key-down')?.addEventListener('click',event=>{
  event.preventDefault();event.stopPropagation();setMidiKey(-1);
});
$('midi-key-up')?.addEventListener('click',event=>{
  event.preventDefault();event.stopPropagation();setMidiKey(1);
});
syncMidiKeyButtons();
$('midi-instrument')?.addEventListener('change',()=>{
  if(state.liveMidiPlayback)nativePlayer.dispatchEvent(new Event('xstage-midi-transpose'));
});
ui.speed.addEventListener('change',()=>{player.playbackRate=Number(ui.speed.value);saveUiPrefs({speed:Number(ui.speed.value)});});
ui.volume.addEventListener('input',()=>{
  const bridge=window.XStageWindowsVolumeBridge;
  const percent=Math.max(0,Math.min(100,Number(ui.volume.value)||0));
  player.volume=karaokeOutputGain();
  if(bridge?.connected&&!bridge.syncing)bridge.setVolume(percent);
  saveUiPrefs({volume:percent});
});
ui.repeat.addEventListener('change',()=>{player.loop=ui.repeat.checked;saveUiPrefs({repeat:ui.repeat.checked});});
player.addEventListener('volumechange',()=>saveUiPrefs(
  window.XStageWindowsVolumeBridge?.connected
    ?{volume:Number(ui.volume.value)||0,muted:false}
    :{volume:Math.round(player.volume*100),muted:player.muted}));
ui.seek.addEventListener('input',()=>{const d=Number.isFinite(player.duration)?player.duration:Number(state.current?.duration)||0;if(d>0)player.currentTime=d*Number(ui.seek.value)/1000;updateTransport();});
ui.fullscreen.addEventListener('click',async()=>{
  try{
    if(document.fullscreenElement||document.webkitFullscreenElement){
      if(document.exitFullscreen)await document.exitFullscreen();
      else await document.webkitExitFullscreen?.();
    }else if(ui.stage.requestFullscreen)await ui.stage.requestFullscreen();
    else if(ui.stage.webkitRequestFullscreen)await ui.stage.webkitRequestFullscreen();
    else throw Error('Fullscreen API unavailable');
  }catch{setPlayStatus('อุปกรณ์นี้ไม่รองรับการแสดงเต็มหน้าจอ');}
});

function setupMediaSession(){
  if(!('mediaSession' in navigator))return;
  const bind=(action,handler)=>{try{navigator.mediaSession.setActionHandler(action,handler);}catch{}};
  bind('play',()=>{resumePlaybackFromSystem();});
  bind('pause',()=>{state.userPaused=true;state.resumeAfterInterruption=false;screenSleepIntent=null;wakeNeedsGesture=false;player.pause();});
  bind('stop',stopSong);
  bind('nexttrack',()=>playNext());
  bind('previoustrack',playPrevious);
  bind('seekbackward',details=>{const step=Number(details.seekOffset)||10;player.currentTime=Math.max(0,player.currentTime-step);});
  bind('seekforward',details=>{const step=Number(details.seekOffset)||10;const d=Number.isFinite(player.duration)?player.duration:Infinity;player.currentTime=Math.min(d,player.currentTime+step);});
  bind('seekto',details=>{if(Number.isFinite(details.seekTime))player.currentTime=Math.max(0,Math.min(player.duration||details.seekTime,details.seekTime));});
}
setupMediaSession();

// Safari can suspend a MIDI AudioContext / MediaStream relay on screen lock
// WITHOUT pausing the virtual transport. Remember playback intent while hidden
// and restore the actual output graph on wake without restarting the song.
let screenSleepIntent=null;
let wakeRecoveryInFlight=false;
let wakeNeedsGesture=false;
function saveScreenSleepPlaybackIntent(){
  if(!state.current||state.loading||state.userPaused||state.userStopped)return;
  if(player.paused&&!state.resumeAfterInterruption)return;
  screenSleepIntent={song:state.current,requestId:state.requestId};
  savePlaybackResumeState();
}
function mayRestoreScreenAudio(){
  return !document.hidden&&!nativeAudioFocusBlocked&&!!state.current&&
    !state.loading&&!state.userPaused&&!state.userStopped&&
    (state.resumeAfterInterruption||
     screenSleepIntent?.song===state.current&&screenSleepIntent.requestId===state.requestId||
     midiTransport.active&&!player.paused);
}
async function boundedScreenAudioRecovery(action){
  // Some iOS Safari/PWA versions never settle AudioContext.resume().
  // Bound the attempt so a subsequent permitted user tap can retry in place.
  let timeout=0;
  try{
    const pending=action(); // Invoke immediately inside the user's gesture.
    return await Promise.race([
      Promise.resolve(pending),
      new Promise(resolve=>{timeout=setTimeout(()=>resolve(false),1800);})
    ]);
  }finally{
    if(timeout)clearTimeout(timeout);
  }
}
async function recoverScreenAudio(){
  if(wakeRecoveryInFlight||!mayRestoreScreenAudio())return false;
  wakeRecoveryInFlight=true;
  const requestId=state.requestId;
  try{
    let restored=true;
    if(player.paused){
      restored=await boundedScreenAudioRecovery(()=>resumePlaybackFromSystem());
    }else if(midiTransport.active){
      // Do not call the virtual player.play() again: it is already running.
      // Recover AudioContext + iOS HTMLMediaElement relay in place.
      if(state.liveMidiPlayback?.resumeAudio)
        restored=await boundedScreenAudioRecovery(()=>state.liveMidiPlayback.resumeAudio());
      else if(window.XStageBrowserMidi?.unlockAudio)
        restored=await boundedScreenAudioRecovery(()=>window.XStageBrowserMidi.unlockAudio());
    }else if(window.XStageResumeAudioGraph){
      restored=await boundedScreenAudioRecovery(()=>window.XStageResumeAudioGraph());
    }
    if(requestId!==state.requestId||!state.current||state.userPaused||state.userStopped)
      return false;
    if(restored===false){
      state.resumeAfterInterruption=true;
      wakeNeedsGesture=true;
      setPlayStatus('iPhone พักเสียงขณะล็อกหน้าจอ · แตะ ▶ เพื่อเล่นต่อจากตำแหน่งเดิม');
      updateTransport();
      return false;
    }
    wakeNeedsGesture=false;
    state.resumeAfterInterruption=false;
    screenSleepIntent=null;
    updateTransport();
    return true;
  }catch(error){
    if(requestId===state.requestId&&!state.userPaused&&!state.userStopped){
      state.resumeAfterInterruption=true;
      wakeNeedsGesture=true;
      setPlayStatus('ระบบเสียงถูกพัก · แตะ ▶ เพื่อเล่นต่อจากตำแหน่งเดิม');
      console.warn('Screen wake audio recovery:',error);
    }
    return false;
  }finally{wakeRecoveryInFlight=false;}
}
function tryRecoverInterruptedPlayback(){
  if(!mayRestoreScreenAudio())return;
  setTimeout(()=>{
    if(mayRestoreScreenAudio())void recoverScreenAudio();
  },180);
}
// iOS may require a fresh user gesture after screen lock. Reuse that gesture
// only when an automatic recovery was denied, never after manual pause/stop.
document.addEventListener('pointerdown',()=>{
  if(wakeNeedsGesture&&mayRestoreScreenAudio())void recoverScreenAudio();
},{capture:true,passive:true});
window.addEventListener('xstage-audio-interrupted',()=>{
  if(!state.userPaused&&!state.userStopped)state.resumeAfterInterruption=true;
});
window.addEventListener('xstage-native-audio-focus',event=>{
  const change=event?.detail?.state;
  if(change==='loss-transient'){
    nativeAudioFocusBlocked=true;
    if(state.current&&!state.userPaused&&!state.userStopped&&!player.paused){
      window.dispatchEvent(new Event('xstage-audio-interrupted'));
      player.pause();
    }
  }else if(change==='loss-permanent'){
    nativeAudioFocusBlocked=true;
    state.resumeAfterInterruption=false;
    state.userPaused=true;
    player.pause();
  }else if(change==='gain'){
    nativeAudioFocusBlocked=false;
    tryRecoverInterruptedPlayback();
  }
});
document.addEventListener('visibilitychange',()=>{
  // Record a playing song before Safari freezes its audio/context. Never
  // interpret an explicit user pause as permission to resume automatically.
  if(document.hidden){saveScreenSleepPlaybackIntent();return;}
  // Background MIDI is sequenced by AudioWorklet, not a hidden-tab timer.
  // On return, inspect the AUDIBLE engine even if the UI says "playing".
  if(!document.hidden){
    updateTransport();
    scheduleLyricsDraw();
    syncMediaSessionPosition();
    tryRecoverInterruptedPlayback();
  }
});
window.addEventListener('pageshow',tryRecoverInterruptedPlayback);
window.addEventListener('focus',tryRecoverInterruptedPlayback);

let playbackSnapshotTick=0;
player.addEventListener('timeupdate',()=>{
  updateTransport();
  medleyTick();
  const now=Date.now();
  if(now-playbackSnapshotTick>2000){playbackSnapshotTick=now;savePlaybackResumeState();}
});
// Release any between-song SF2 rhythm only once the NEXT transport is
// actually audible; keep it alive while Drive/Worklet prepares a queued song.
player.addEventListener('playing',()=>{
  stopSoundFontFill();
  if(state.queue.length)scheduleQueuePreload();
  // The successor is selected once playback is underway, so even long
  // private Drive downloads can complete before a medley handoff.
  if(state.medley&&!state.queue.length)prefetchMedleyNext();
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
window.addEventListener('pagehide',saveScreenSleepPlaybackIntent);
window.addEventListener('pagehide',()=>{if(!preserveUpdateResumeOnUnload)savePlaybackResumeState();});
window.addEventListener('beforeunload',()=>{if(!preserveUpdateResumeOnUnload)savePlaybackResumeState();stopSoundFontFill();state.liveMidiPlayback?.dispose();state.controller?.abort();resetSongVideo();if(state.objectUrl)URL.revokeObjectURL(state.objectUrl);});
renderSongs();renderQueue();updateTransport();scheduleLyricsDraw();setupNativeAndroidTvUi();setupAppUpdateWatcher();

let importerGoogleRenewal=null;
let importerGoogleRenewalRetryAfter=0;
// Browser-only Google access tokens expire. An ongoing import must reauthorize
// the SAME verified account without resetting catalog/queue or prompting users
// once per chunk. GIS prompt:'' reuses an existing consent when Google allows it;
// it can still require a real user gesture after revocation/blocked cookies.
async function ensureImporterGoogleAuth(force=false,interactive=false,readAll=false){
  const requestRead=readAll||hasFullDriveRead();
  const margin=3*60*1000;
  if(!force&&state.token&&state.accountSub&&
     state.tokenExpiresAt>Date.now()+margin)return true;
  if(importerGoogleRenewal){
    if(!readAll)return importerGoogleRenewal;
    throw Error('กำลังต่ออายุสิทธิ์ Google อยู่ · โปรดลองอีกครั้ง');
  }
  if(!state.accountSub||!state.token)
    throw Error('ยังไม่มีบัญชี Google ที่ยืนยันแล้ว · กรุณาเชื่อมต่อบัญชีเพื่อทำต่อ');
  if(!interactive&&Date.now()<importerGoogleRenewalRetryAfter)
    throw Error('Google ไม่อนุญาตให้ต่ออายุอัตโนมัติในขณะนี้ · กดเชื่อม Google หนึ่งครั้งแล้วทำต่อ');
  if(typeof google==='undefined'||!google.accounts?.oauth2?.initTokenClient||
     !cfg.googleClientId)
    throw Error('Google Sign-In ยังไม่พร้อม · ตรวจการเชื่อมต่อ แล้วกดเชื่อม Google');
  const expectedSub=state.accountSub,authId=state.authId;
  importerGoogleRenewal=(async()=>{
    let watchdog=0;
    try{
      const newToken=await new Promise((resolve,reject)=>{
        let done=false;
        const settle=(error,value)=>{
          if(done)return;
          done=true;clearTimeout(watchdog);
          if(error)reject(error);else resolve(value);
        };
        watchdog=setTimeout(()=>settle(Error('Google ไม่ตอบรับการต่ออายุโทเค็น')),25000);
        try{
          const client=google.accounts.oauth2.initTokenClient({
            client_id:cfg.googleClientId,
            scope:'openid email https://www.googleapis.com/auth/drive.file'+(requestRead?' '+DRIVE_READ_SCOPE:''),
            include_granted_scopes:false,
            callback:result=>{
              if(result?.error||!result?.access_token)
                settle(Error(googleAuthErrorMessage(result)));
              else settle(null,result);
            },
            error_callback:()=>settle(Error('Google ต้องการให้ผู้ใช้ยืนยันสิทธิ์อีกครั้ง'))
          });
          // Renewal is always tied to the already verified immutable
          // Google account ID. Reuse its consent and never switch accounts.
          const hint=rememberedGoogleAccount();
          client.requestAccessToken({
            prompt:readAll?'consent':'',
            ...(hint?.email?{login_hint:hint.email}:{})
          });
        }catch(error){settle(error);}
      });
      if(state.authId!==authId||state.accountSub!==expectedSub)
        throw Error('บัญชี Google เปลี่ยนระหว่างต่ออายุ · หยุดเพื่อป้องกันอัปโหลดผิดคลัง');
      const accountResult=await googleFetch(
        'https://openidconnect.googleapis.com/v1/userinfo',
        {headers:requestHeaders(newToken.access_token),cache:'no-store'},
        'Google Account',0);
      if(!accountResult.ok)throw driveError(accountResult.status,'ข้อมูลบัญชี Google');
      const account=await accountResult.json();
      if(!account.email_verified||account.sub!==expectedSub)
        throw Error('Google ส่งบัญชีที่ไม่ตรงกับงานเดิม · ไม่สลับบัญชีโดยอัตโนมัติ');
      const expiresIn=Number(newToken.expires_in);
      if(!Number.isFinite(expiresIn)||expiresIn<120)
        throw Error('Google ส่งอายุโทเค็นที่ใช้ต่ออายุไม่ได้');
      const expiresAt=Date.now()+Math.min(expiresIn,3600)*1000;
      if(state.authId!==authId||state.accountSub!==expectedSub)
        throw Error('บัญชี Google เปลี่ยนระหว่างตรวจสอบ');
      if(requestRead&&!grantedDriveReadAndWrite(newToken))
        throw Error('Google ยังไม่ได้อนุญาตทั้งการอ่านไฟล์ทั้งหมดและสิทธิ์ไฟล์ของแอป · สิทธิ์เดิมยังใช้ได้');
      fullDriveReadToken=requestRead?newToken.access_token:'';
      if(requestRead)rememberFullDriveRead(expectedSub);
      state.token=newToken.access_token;
      state.tokenExpiresAt=expiresAt;
      saveActiveAuth(state.token,expiresAt,expectedSub);
      clearPendingAuth();
      importerGoogleRenewalRetryAfter=0;
      window.dispatchEvent(new CustomEvent('xstage:auth-refreshed',
        {detail:{sub:expectedSub,source:'importer-auto-renew'}}));
      if(!readAll&&state.libraryRootId)void window.XStageBrowserMidi?.refreshFonts({
        token:state.token,sub:expectedSub,rootId:state.libraryRootId,ownedByMe:state.libraryRootOwnedByMe
      }).catch(error=>console.warn('SoundFont renewed token:',error.message));
      return true;
    }catch(error){
      importerGoogleRenewalRetryAfter=Date.now()+60000;
      throw error;
    }finally{clearTimeout(watchdog);}
  })();
  try{return await importerGoogleRenewal;}
  finally{importerGoogleRenewal=null;}
}
// A Google access token's lifetime is fixed by Google. This control appears
// before expiry and lets the user renew with one explicit tap; Google may
// still require consent. Never request an OAuth popup from a timer.
function updateGoogleRenewNotice(){
  const button=$('google-renew');
  if(!button)return;
  const remaining=Number(state.tokenExpiresAt||0)-Date.now();
  const needed=!androidTvNativeBridgeReady()&&!!state.token&&!!state.accountSub&&
    remaining<=8*60*1000;
  button.hidden=!needed;
  if(needed){
    button.textContent=remaining<=0?'เชื่อม Google อีกครั้ง':'ต่ออายุ Google';
    button.title='ยืนยัน Google เพื่อใช้งาน Drive ต่อโดยไม่ล้างเพลงและคิว';
  }
}
$('google-renew')?.addEventListener('click',async()=>{
  const button=$('google-renew');
  if(!state.token||!state.accountSub||!button||button.disabled)return;
  button.disabled=true;button.textContent='กำลังต่ออายุ…';
  try{
    await ensureImporterGoogleAuth(true,true);
    setStatus('ต่ออายุ Google Drive สำเร็จ · เพลงและคิวเดิมไม่เปลี่ยน','success');
  }catch(error){
    setStatus('Google ต้องการยืนยันสิทธิ์อีกครั้ง · '+String(error?.message||error),'error');
  }finally{button.disabled=false;updateGoogleRenewNotice();}
});
setInterval(updateGoogleRenewNotice,60_000);
window.addEventListener('focus',updateGoogleRenewNotice);
window.addEventListener('pageshow',updateGoogleRenewNotice);
window.addEventListener('xstage:auth-refreshed',updateGoogleRenewNotice);
document.addEventListener('visibilitychange',()=>{
  if(!document.hidden)updateGoogleRenewNotice();
});
updateGoogleRenewNotice();

function updateDriveReadNotice(){
  const main=$('xstage-drive-main-name'),pick=$('xstage-drive-main-select');
  if(main)main.textContent=state.libraryRootId?String(state.availableLibraries.find(x=>x.id===state.libraryRootId)?.name||'คลังเพลง')+' · …'+state.libraryRootId.slice(-6):'ยังไม่ได้เลือกคลังหลัก';
  if(pick)pick.disabled=!state.token||!state.accountSub;
  const button=$('xstage-drive-read-all'),status=$('xstage-drive-read-status');
  if(!button||!status)return;
  const full=hasFullDriveRead(),connected=!!state.token&&!!state.accountSub;
  button.hidden=full;
  button.disabled=!connected||androidTvNativeBridgeReady();
  status.textContent=full?'Google อนุญาตให้อ่านไฟล์ทั้งหมดแล้ว · ค้นหาเฉพาะโฟลเดอร์ที่เลือก':
    'ขณะนี้เห็นเฉพาะไฟล์ที่แอปได้รับสิทธิ์ · กดอนุญาตอ่านไฟล์ทั้งหมดเพื่อไม่ต้องเลือกไฟล์ทีละไฟล์';
}
$('xstage-drive-read-all')?.addEventListener('click',async()=>{
  const button=$('xstage-drive-read-all'),status=$('xstage-drive-read-status');
  if(!button||button.disabled||!state.token||!state.accountSub)return;
  if(window.XStageDriveBuildBusy){if(status)status.textContent='กรุณาให้การสร้างฐานเพลงเสร็จก่อนเปลี่ยนสิทธิ์';return;}
  const sub=state.accountSub,rootId=state.libraryRootId;
  button.disabled=true;
  if(status)status.textContent='กำลังขออนุญาตอ่านไฟล์ทั้งหมดจาก Google…';
  try{
    await ensureImporterGoogleAuth(true,true,true);
    if(sub!==state.accountSub||rootId!==state.libraryRootId)return;
    updateDriveReadNotice();
    if(rootId){
      await window.XStageBrowserMidi?.refreshFonts({token:state.token,rootId,sub,ownedByMe:state.libraryRootOwnedByMe});
      window.dispatchEvent(new CustomEvent('xstage:drive-fx-folder-change'));
      void xstageDriveFolders?.scanCounts();
    }
  }catch(error){
    updateDriveReadNotice();
    if(status)status.textContent='ยังไม่เปิดสิทธิ์อ่านทั้งหมด · '+String(error.message||error)+' · ใช้สิทธิ์เดิมต่อได้';
  }
});
for(const event of ['xstage:auth-ready','xstage:auth-refreshed','xstage:librarychange','xstage:auth-cleared','xstage:drive-sources-open'])
  window.addEventListener(event,updateDriveReadNotice);
window.XStageDriveFontAuth=()=>({token:state.token,rootId:state.libraryRootId,sub:state.accountSub,ownedByMe:state.libraryRootOwnedByMe});
window.XStageEnsureImporterGoogleAuth=ensureImporterGoogleAuth;
const xstageCloudImporter=window.XStageCloudImport?.init({
  // The browser importer obtains only an in-memory short-lived token and the
  // current verified account. No token, password or refresh token is stored.
  session:()=>({token:state.token,sub:state.accountSub,
    rootId:state.libraryRootId,owned:state.libraryRootOwnedByMe,
    expiresAt:state.tokenExpiresAt}),
  ensureAuth:ensureImporterGoogleAuth,
  reconnect:()=>ensureImporterGoogleAuth(true,true),
  refresh:async()=>{
    if(!state.token||!state.accountSub)return;
    // Reload only the canonical DB/songs.sqlite3 after publishing.
    // Use a NEW auth request ID but never silently switch Google accounts.
    const token=state.token,id=++state.authId;
    await openDrive(token,id,state.tokenExpiresAt);
  }
});
const xstageDriveFolders=window.XStageDriveFolders?.init({
  session:()=>({token:state.token,sub:state.accountSub,
    rootId:state.libraryRootId}),
  hasFullRead:hasFullDriveRead,
  ensureAuth:ensureImporterGoogleAuth,
  onSoundfontChange:()=>{
    if(!state.token||!state.accountSub||!state.libraryRootId)return;
    void window.XStageBrowserMidi?.refreshFonts({
      token:state.token,rootId:state.libraryRootId,sub:state.accountSub,
      ownedByMe:state.libraryRootOwnedByMe
    }).catch(error=>console.warn('Selected SoundFont folder:',error.message));
  },
  onFxChange:folderId=>window.dispatchEvent(new CustomEvent(
    'xstage:drive-fx-folder-change',{detail:{folderId}})),
  refresh:async()=>{
    if(!state.token||!state.accountSub)return;
    // Preserve an active song, the queue and the SoundFont when an existing
    // catalog is rebuilt. On the first build, discover the new DB directory.
    if(state.catalogDbDirId)await pollPublishedCatalog();
    else await openDrive(state.token,++state.authId,state.tokenExpiresAt);
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
      if([403,404].includes(error?.driveStatus)&&error?.driveSubject==='ไฟล์เพลงส่วนตัว'&&state.accountSub){
        hideCatalogLoading();setSearchAvailability(false);
        clearPendingAuth();
        ui.libraryState.textContent='Google Login สำเร็จ · ตรวจสิทธิ์ไฟล์เพลง';
        setStatus('บัญชี Google ยังใช้งานได้ แต่ต้องอนุญาตไฟล์เพลงให้แอป: '+error.message,'error');
      }else{
        resetPrivate({keepAuth:true});
        if(!/เชื่อมต่อไม่สำเร็จ|ใช้เวลานาน|อินเทอร์เน็ต/.test(String(error.message||'')))clearPendingAuth();
        setStatus('กู้คืนการเข้าสู่ระบบไม่สำเร็จ: '+error.message,'error');
      }
    }
    return false;
  }finally{
    state.authRecovering=false;
    if(id===state.authId)ui.login.disabled=ui.gateLogin.disabled=false;
  }
}
(function restoreTabSession(){
  syncRememberedAccountChooser();
  // Android APK login is owned by the encrypted native token store, not JS.
  if(androidTvNativeBridgeReady())return;
  const saved=readActiveAuth();
  if(!saved){
    if(readPendingAuth()){void recoverPendingGoogleAuth();}
    else if(rememberedGoogleAccount())setStatus('จำบัญชี Google เดิมไว้แล้ว · แตะเชื่อม Google อีกครั้งเพื่อรับสิทธิ์ใหม่ (ไม่ต้องเลือกบัญชีซ้ำ)');
    return;
  }
  ui.gate.hidden=true;
  ui.login.disabled=ui.gateLogin.disabled=true;
  setStatus('กำลังตรวจสอบเซสชัน Google เดิม…');
  const id=++state.authId;
  openDrive(saved.token,id,saved.expiresAt,saved.sub).catch(error=>{
    if(id!==state.authId)return;
    if([403,404].includes(error?.driveStatus)&&error?.driveSubject==='ไฟล์เพลงส่วนตัว'){
      hideCatalogLoading();
      setSearchAvailability(false);
      ui.libraryState.textContent='เชื่อม Google สำเร็จ · ฐานเพลงยังอ่านไม่ได้';
      setStatus('Google Login ยังใช้ได้ แต่แอปอ่านฐานเพลงไม่สำเร็จ: '+error.message,'error');
      return;
    }
    clearActiveAuth();
    resetPrivate({keepAuth:true});
    if(readPendingAuth())void recoverPendingGoogleAuth('เซสชันเดิมใช้ไม่ได้ · กำลังกู้คืนการเข้าสู่ระบบ…');
    else setStatus('ไม่สามารถเชื่อมต่อ Google Drive: '+error.message,'error');
  }).finally(()=>{
    if(id===state.authId)ui.login.disabled=ui.gateLogin.disabled=false;
  });
})();
window.addEventListener('offline',()=>setStatus('อุปกรณ์ออฟไลน์ · เพลงที่โหลดไว้แล้วอาจเล่นต่อได้ แต่ค้น/โหลดเพลงใหม่ไม่ได้','error'));
window.addEventListener('online',()=>{
  if(state.token)return;
  if(readPendingAuth()){void recoverPendingGoogleAuth('กลับมาออนไลน์แล้ว · กำลังกู้คืนการเข้าสู่ระบบ Google…');return;}
  const saved=readActiveAuth();
  if(!saved){if(rememberedGoogleAccount())setStatus('กลับมาออนไลน์แล้ว · แตะเชื่อมต่อ Google เดิมเพื่อรับสิทธิ์ใหม่');return;}
  ui.gate.hidden=true;ui.login.disabled=ui.gateLogin.disabled=true;
  setStatus('กลับมาออนไลน์แล้ว · กำลังกู้คืนเซสชัน Google…');
  const id=++state.authId;
  openDrive(saved.token,id,saved.expiresAt,saved.sub).catch(error=>{
    if(id!==state.authId)return;
    if([403,404].includes(error?.driveStatus)&&error?.driveSubject==='ไฟล์เพลงส่วนตัว'){
      hideCatalogLoading();setSearchAvailability(false);
      setStatus('Google Login ยังใช้ได้ แต่ฐานเพลงยังไม่ได้รับสิทธิ์: '+error.message,'error');
      return;
    }
    clearActiveAuth();resetPrivate({keepAuth:true});
    setStatus('กู้คืนเซสชันไม่สำเร็จ: '+error.message,'error');
  }).finally(()=>{if(id===state.authId)ui.login.disabled=ui.gateLogin.disabled=false;});
});

let oauthReturnRecoveryTimer=0;
function scheduleOAuthReturnRecovery(){
  clearTimeout(oauthReturnRecoveryTimer);
  if(document.hidden||state.token||androidTvNativeBridgeReady())return;
  oauthReturnRecoveryTimer=setTimeout(()=>{
    if(document.hidden||state.token||androidTvNativeBridgeReady())return;
    const flow=webGoogleAuthFlow;
    if(flow&&flow.id===state.authId){
      // A focus/pageshow event is NOT proof of OAuth failure: the popup may
      // still be open, and Safari can deliver the GIS callback seconds later.
      if(flow.phase==='verifying'){
        setStatus('ได้รับสิทธิ์จาก Google แล้ว · กำลังตรวจสอบบัญชีและคลังเพลง…');
      }else{
        setStatus('กลับมาที่ X-Stage แล้ว · กำลังรอ Google ส่งผลการอนุญาต…');
      }
      return;
    }
    if(!state.authRecovering&&readPendingAuth())
      void recoverPendingGoogleAuth('กลับจาก Google แล้ว · กำลังเชื่อมต่อคลังเพลงต่อ…');
  },2500);
}
document.addEventListener('visibilitychange',scheduleOAuthReturnRecovery);
window.addEventListener('pageshow',scheduleOAuthReturnRecovery);
window.addEventListener('focus',scheduleOAuthReturnRecovery);
setTimeout(bootAndroidTvAuthentication,0);
