import assert from 'node:assert/strict';
import fs from 'node:fs';

const read = path => fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const app = read('app.js');
const apk = read('android-apk-download.js');
const windows = read('windows-pc/Check-Update.ps1');
const launcher = read('windows-pc/Start-XStage-With-Updates.ps1');
const android = read('android-tv/app/src/main/java/com/webbasex/xstage/XStageUpdateManager.java');
const publishedApk = JSON.parse(read('downloads/android-tv-latest.json'));
const play = JSON.parse(read('downloads/android-play-latest.json'));
const windowsRelease = JSON.parse(read('downloads/windows-pc-latest.json'));

const start = app.indexOf("const WEB_AUTO_UPDATE_GUARD=");
const end = app.indexOf('async function checkAppVersion(){',start);
assert.ok(start>=0&&end>start,'automatic web update function must be available');
const makeWebUpdate = new Function('androidTvNativeBridgeReady','playbackBusyForUpdate','sessionStorage','performAppUpdateReload',
  'webGoogleAuthFlow','state','window',
  app.slice(start,end)+'\nreturn autoApplyWebUpdate;');

function scenario({busy=false,native=false,oauth=false,recovering=false,building=false}={}){
  const flags={busy,building};
  const data=new Map();let reloads=0;
  const storage={
    getItem:key=>data.get(key)||null,
    setItem:(key,value)=>data.set(key,value)
  };
  const apply=makeWebUpdate(()=>native,()=>flags.busy,storage,()=>{reloads++;},
    oauth?{id:1,phase:'waiting'}:null,{authRecovering:recovering},
    {get XStageDriveBuildBusy(){return flags.building;}});
  return {apply,reloads:()=>reloads,flags};
}
{
  const test=scenario();
  assert.equal(test.apply({version:'1.0.78',build:1078}),true,'startup should apply a newer published web build');
  assert.equal(test.reloads(),1);
  assert.equal(test.apply({version:'1.0.78',build:1078}),false,'same session cannot repeatedly reload');
  assert.equal(test.reloads(),1);
}
{
  const test=scenario({busy:true});
  assert.equal(test.apply({version:'1.0.78',build:1078}),false,'do not interrupt an active karaoke song');
  assert.equal(test.reloads(),0);
}
{
  const test=scenario({native:true});
  assert.equal(test.apply({version:'1.0.78',build:1078}),false,'native APK uses its own updater');
  assert.equal(test.reloads(),0);
}
{
  const test=scenario({oauth:true});
  assert.equal(test.apply({version:'1.0.101',build:1101}),false,'pending Google OAuth popup must block automatic web reload');
  assert.equal(test.reloads(),0);
}
{
  const test=scenario({recovering:true});
  assert.equal(test.apply({version:'1.0.101',build:1101}),false,'stored Google token recovery must block automatic web reload');
  assert.equal(test.reloads(),0);
}
// The rejected checks must not consume the update guard; when work ends,
// the very same published build must still be eligible for one reload.
for(const flags of [{busy:true},{building:true},{busy:true,building:true}]){
  const test=scenario(flags),remote={version:'1.0.207',build:1207};
  assert.equal(test.apply(remote),false,'active playback or database build must defer update');
  assert.equal(test.reloads(),0);
  test.flags.busy=false;test.flags.building=false;
  assert.equal(test.apply(remote),true,'deferred update can proceed once idle');
  assert.equal(test.apply(remote),false,'only one automatic reload per session');
  assert.equal(test.reloads(),1);
}
// Exercise the real playback predicate, including the live MIDI proxy source.
const busyStart=app.indexOf('function playbackBusyForUpdate(){');
const busyEnd=app.indexOf('let webUpdateStageBuild=',busyStart);
assert.ok(busyStart>=0&&busyEnd>busyStart);
const realBusy=new Function('state','player',app.slice(busyStart,busyEnd)+'\nreturn playbackBusyForUpdate;');
for(const [label,state,player,expected] of [
  ['idle',{loading:false,current:null,queue:[]},{src:'',paused:true,ended:false},false],
  ['loading',{loading:true,current:null,queue:[]},{src:'',paused:true,ended:false},true],
  ['audio',{current:{},queue:[]},{src:'blob:audio',paused:false,ended:false},true],
  ['live MIDI',{current:{},queue:[]},{src:'midi:live',paused:false,ended:false},true],
  ['queued pause',{current:{},queue:[{}]},{src:'midi:live',paused:true,ended:false},true],
  ['medley pause',{current:{},queue:[],medley:true},{src:'midi:live',paused:true,ended:false},true],
  ['finished',{current:{},queue:[]},{src:'midi:live',paused:true,ended:true},false]
]){
  assert.equal(realBusy(state,player)(),expected,label+' playback update guard');
}
const nativeMain=read('android-tv/app/src/main/java/com/webbasex/xstage/MainActivity.java');
const remote=read('remote.js');
const host=read('stage-controls.js');
const css=read('style.css');
const liveStart=app.indexOf('const XSTAGE_LIVE_UPDATE_CHECK_MS=');
const liveEnd=app.indexOf('function setupAppUpdateWatcher(){',liveStart);
assert.ok(liveStart>=0&&liveEnd>liveStart,'live update watcher must be available');
const makeLiveChecker=new Function('androidTvNativeBridgeReady','window','checkAppVersion',
  app.slice(liveStart,liveEnd)+'\nreturn {checkLiveAppUpdate,XSTAGE_LIVE_UPDATE_CHECK_MS};');
{
  let nativeChecks=0,webChecks=0;
  const native=makeLiveChecker(()=>true,{XStageAndroid:{checkForAppUpdate(){nativeChecks++;}}},()=>{webChecks++;});
  assert.ok(native.XSTAGE_LIVE_UPDATE_CHECK_MS<=20000,'updates should be checked within twenty seconds while playing');
  native.checkLiveAppUpdate();native.checkLiveAppUpdate();
  assert.equal(nativeChecks,2,'native APK must be checked repeatedly while in the foreground');
  assert.equal(webChecks,0,'APK must not use web-only version.json update channel');
  const web=makeLiveChecker(()=>false,{},()=>{webChecks++;});
  web.checkLiveAppUpdate();
  assert.equal(webChecks,1,'browser must also check its own version regularly');
}
// Mid-song web updates must appear without navigation. Prefetch only the
// public shell and its same-origin scripts/styles, never private Drive media.
assert.ok(app.includes("notice.classList.toggle('during-playback',playbackBusyForUpdate())"),
  'New release must remain visible while a song is playing');
assert.ok(app.includes('state.updateAfterTrack=true;')&&
  app.includes("void performAppUpdateReload({preserveSnapshot:true})"),
  'Update after song must preserve the next queued song across reload');
assert.ok(app.includes("sessionStorage.setItem(PLAYBACK_RESUME_KEY,JSON.stringify({"),
  'Song boundary must save resumable queue state');
const html=read('karaoke.html'),updateCss=read('xstage-ux.css');
assert.ok(html.includes('id="app-update-action"')&&
  html.includes('id="app-update-after-song"'),
  'Web update must offer Update Now and After Current Song');
assert.ok(updateCss.includes('.app-update-notice.during-playback'),
  'Mid-song update notice must remain compact and non-modal');
const stageStart=app.indexOf('let webUpdateStageBuild=0,webUpdateStageReady=false');
const stageEnd=app.indexOf('async function performAppUpdateReload(',stageStart);
assert.ok(stageStart>=0&&stageEnd>stageStart,'Web update prefetch must be available');
let prefetched=[],parsed=0,cacheReloads=0;
const mockPage={href:'https://webbase-x.github.io/xstage/karaoke.html',origin:'https://webbase-x.github.io'};
const mockElements=new Map([
 ['app-update-notice',{hidden:true,classList:{toggle(){}}}],
 ['app-update-text',{textContent:''}],
 ['app-update-action',{textContent:'',disabled:false}],
 ['app-update-after-song',{hidden:false,textContent:'',disabled:false}]
]);
const fakeDOMParser=class{
  parseFromString(){
    parsed++;
    return {querySelectorAll:()=>[
      {getAttribute:key=>key==='src'?'app.js?v=NEW':null},
      {getAttribute:key=>key==='href'?'xstage-ux.css?v=NEW':null},
      {getAttribute:key=>key==='src'?'https://www.googleapis.com/drive/v3/files/PRIVATE':null}
    ]};
  }
};
const stageState={updateAvailable:{version:'1.0.137',build:1137},updateAfterTrack:false};
const makeStager=new Function('androidTvNativeBridgeReady','navigator','location','fetch',
 'DOMParser','URL','state','appUpdateElements','playbackBusyForUpdate','console',
 app.slice(stageStart,stageEnd)+
 '\nreturn {stageWebUpdateFiles,isReady:()=>webUpdateStageReady};');
const stage=makeStager(()=>false,{connection:{saveData:false}},mockPage,
 async(url,opts)=>{
   prefetched.push(String(url));
   if(opts.cache!=='reload')throw Error('Assets must enter browser HTTP cache');
   cacheReloads++;
   if(String(url).includes('karaoke.html'))
     return {ok:true,text:async()=>'<html></html>'};
   return {ok:true,arrayBuffer:async()=>new ArrayBuffer(8)};
 },fakeDOMParser,URL,stageState,()=>({
  notice:mockElements.get('app-update-notice'),
  text:mockElements.get('app-update-text'),
  action:mockElements.get('app-update-action'),
  after:mockElements.get('app-update-after-song')
 }),()=>true,{warn(){}});
assert.equal(await stage.stageWebUpdateFiles(stageState.updateAvailable),true);
assert.equal(stage.isReady(),true);
assert.equal(cacheReloads,3,'Only public HTML, JS and CSS should be staged');
assert.ok(prefetched.every(url=>url.startsWith('https://webbase-x.github.io/xstage/')),
 'Private Drive API requests must NEVER be prefetched');
assert.equal(await stage.stageWebUpdateFiles(stageState.updateAvailable),true);
assert.equal(cacheReloads,3,'Same build must not download its assets repeatedly');
const failedStage=makeStager(()=>false,{connection:{saveData:false}},mockPage,
 async()=>({ok:false}),fakeDOMParser,URL,stageState,()=>({
  notice:mockElements.get('app-update-notice'),text:mockElements.get('app-update-text'),
  action:mockElements.get('app-update-action'),after:mockElements.get('app-update-after-song')
 }),()=>false,{warn(){}});
assert.equal(await failedStage.stageWebUpdateFiles(stageState.updateAvailable),false);
assert.match(mockElements.get('app-update-text').textContent,/เปิดรุ่นใหม่โดยตรงได้/);
assert.equal(mockElements.get('app-update-action').disabled,false);
const reloadStart=app.indexOf('async function performAppUpdateReload(');
const reloadEnd=app.indexOf('const WEB_AUTO_UPDATE_GUARD=',reloadStart);
let navigated='',snapshots=0;
const reload=new Function('window','state','location','URL','webGoogleAuthFlow','XSTAGE_RELEASE','savePlaybackResumeState','renderAppUpdateNotice','setStatus',
 'let preserveUpdateResumeOnUnload=false,webUpdateManualMessage="",webUpdateStageController=null,webUpdatePhase="notice",webUpdateReloading=false;const WEB_UPDATE_HANDOFF="test-handoff";'+app.slice(reloadStart,reloadEnd)+';return performAppUpdateReload;')(
 {},{authRecovering:true,updateAvailable:{build:1146}},{href:'https://webbase-x.github.io/xstage/karaoke.html?keep=1',replace:url=>{navigated=url;}},URL,null,{build:1145},()=>{snapshots++;},()=>{},()=>{});
assert.equal(await reload({manual:true}),true,'Manual update works while stored credentials recover');
assert.match(navigated,/build=1146/);
assert.match(navigated,/keep=1/);
assert.equal(snapshots,1);
assert.equal(await reload({manual:true}),false,'Second click must not start a second update');
assert.equal(snapshots,1);
assert.ok(app.includes("webUpdatePhase='applying'")&&app.includes("webUpdatePhase='complete'"));
assert.ok(app.includes('ขั้นที่ 1/2')&&app.includes('ขั้นที่ 2/2'));
assert.ok(apk.includes('xstage:web-update-check-complete')&&apk.includes('if(update?.busy||'));
assert.ok(html.includes('id="app-update-direct"'),'A direct navigation fallback must be visible');

assert.ok(app.includes('if(!newlyPublished&&!manuallyChecked)return;'),'same Android build must not reopen a dismissed notice during background checks');
assert.ok(app.includes('nativeUpdateDismissedBuild===next.build'),'Later must suppress repeat dialogs for the same build');
assert.ok(app.includes("panel.classList.toggle('during-playback',active)"),'notification must be compact during karaoke');
assert.ok(css.includes('.android-tv-update-panel.during-playback'),'live APK notice must leave lyrics visible');
assert.ok(android.includes('private final Runnable periodicUpdateCheck'),'native fallback must monitor releases during playback');
assert.ok(android.includes('main.postDelayed(this, CHECK_INTERVAL_MS)'),'native fallback must continue monitoring');
assert.ok(nativeMain.includes('updateManager.startMonitoring()')&&nativeMain.includes('updateManager.stopMonitoring()'),
  'native monitor must follow activity foreground lifecycle');
assert.ok(host.includes("'xstage:native-update',broadcastStatus"),'paired remotes should receive the new build promptly');
assert.ok(remote.includes('lastNotifiedUpdateBuild'),'Owner mobile should show one clear notification per new build');

assert.ok(app.includes("window.XStageAndroidUpdateAvailable=(version,build)=>"),'older APKs must receive live release notices');
assert.ok(app.includes("android-tv-update-now')?.addEventListener('click'"),'APK installation must require a real user action');
assert.ok(!app.includes("button?.click();"),'APK release notification cannot silently start installer');
assert.ok(android.includes('BuildConfig.DEBUG ? fetchLatest() : fetchPlayLatest()'),'test APK must remain separate from production Play channel');
assert.ok(android.includes('MessageDigest.getInstance("SHA-256")'),'APK updates must verify downloads');
assert.ok(apk.includes('offerPublishedAndroidApk(apk)'),'Android browser visitors must see an APK-or-Web choice');
assert.ok(apk.includes('ANDROID_APK_NEVER_ASK_KEY'),'APK offer must support opt-out');
assert.ok(!apk.includes('ANDROID_TV_APK_FALLBACK'),'do not offer an unverified stale APK link');
assert.ok(windows.includes('Get-FileHash')&&windows.includes('available -ne $true'),'Windows updates require a published installer and SHA-256');
assert.ok(launcher.includes("'-Install'")&&launcher.includes("'-Startup'"),'Windows legacy launcher must start the verified updater');
assert.equal(play.available,false,'never claim that Google Play production update is published');
assert.equal(windowsRelease.available,false,'never claim that unbuilt Windows installer is available');
assert.ok(launcher.includes("Join-Path $PSScriptRoot 'XStageKaraoke.exe'"),'Launcher must support portable installation paths');
assert.ok(windows.includes("if ($CurrentBuild -le 0 -and $CurrentVersion -ne '0.0.0')"),
  'Updater must read local manifest if the running app does not supply its build number');
const pro=JSON.parse(read('downloads/song-studio-pro-latest.json'));
assert.equal(pro.name,'X-Stage Song Studio Pro');
assert.match(pro.version,/^\d+\.\d+\.\d+$/,'Song Studio Pro version must be valid');
if(pro.available){
  assert.match(pro.sha256||'',/^[a-fA-F0-9]{64}$/,'Pro preview must declare a verified SHA-256');
  assert.match(pro.download_url||'',/^https:\/\/github\.com\/webbase-x\/xstage\/releases\/download\//,
    'Published Song Studio Pro preview must link to a specific release');
  assert.equal(pro.code_signed,false,'Unsigned preview must not claim a code signature');
}else assert.equal(pro.download_url??null,null,
  'Unavailable Song Studio Pro release must not advertise a download');
assert.ok(publishedApk.build>0&&/^[a-fA-F0-9]{64}$/.test(publishedApk.sha256),'published APK metadata must identify an actual signed artifact');
console.log('PASS: startup/live update, playback and database-build deferral, idle retry, native release/channel safety');
