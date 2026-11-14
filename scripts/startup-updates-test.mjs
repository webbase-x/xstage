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
  'webGoogleAuthFlow','state',
  app.slice(start,end)+'\nreturn autoApplyWebUpdate;');

function scenario({busy=false,native=false,oauth=false,recovering=false}={}){
  const data=new Map();let reloads=0;
  const storage={
    getItem:key=>data.get(key)||null,
    setItem:(key,value)=>data.set(key,value)
  };
  const apply=makeWebUpdate(()=>native,()=>busy,storage,()=>{reloads++;},
    oauth?{id:1,phase:'waiting'}:null,{authRecovering:recovering});
  return {apply,reloads:()=>reloads};
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
const ready=JSON.parse(read('downloads/song-studio-latest.json'));
assert.equal(ready.package_type,'portable_zip','PC Ready must never masquerade as an EXE installer');
assert.equal(ready.installer_available,false);
assert.match(ready.sha256,/^[a-f0-9]{64}$/);
assert.ok(publishedApk.build>0&&/^[a-fA-F0-9]{64}$/.test(publishedApk.sha256),'published APK metadata must identify an actual signed artifact');
console.log('X-Stage startup updater contract: 4 web behaviors and 12 release/channel safety checks passed');
