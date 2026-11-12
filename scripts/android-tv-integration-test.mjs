import fs from 'node:fs';
import assert from 'node:assert/strict';

const read = path => fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const app = read('app.js');
const host = read('stage-controls.js');
const remote = read('remote.js');
const main = read('android-tv/app/src/main/java/com/webbasex/xstage/MainActivity.java');
const auth = read('android-tv/app/src/main/java/com/webbasex/xstage/GoogleDeviceAuth.java');
const updater = read('android-tv/app/src/main/java/com/webbasex/xstage/XStageUpdateManager.java');

function segment(src,begin,end){
  const start=src.indexOf(begin);
  const finish=src.indexOf(end,start+begin.length);
  assert.ok(start>=0&&finish>start,'missing executable segment: '+begin);
  return src.slice(start,finish);
}

const updateCallback=segment(app,'window.XStageAndroidUpdateAvailable=(version,build)=>{',
  'window.XStageAndroidUpdateStatus=');
function updateScenario({playing=true,dismissedBuild=0,manual=false}={}){
  const nodes=new Map(),events=[],installs=[];
  const panel={hidden:true,classes:new Map(),attributes:new Map(),
    classList:{toggle(k,v){panel.classes.set(k,v);}},
    setAttribute(k,v){panel.attributes.set(k,v);}};
  const $=id=>{
    if(!nodes.has(id))nodes.set(id,{textContent:'',disabled:false,
      focus(){},click(){installs.push(id);}});
    return nodes.get(id);
  };
  const window={XStageAndroid:{getAppBuild:()=>1087,getAppVersion:()=> '1.0.87',
    installAvailableUpdate(){installs.push('native');}},
    dispatchEvent(event){events.push(event);}};
  const state={nativeUpdateAvailable:null,nativeUpdateStatus:''};
  const make=new Function('window','state','androidTvNativeBridgeReady',
    'androidTvUpdatePanel','playbackBusyForUpdate','$','setTimeout','CustomEvent',
    'XSTAGE_RELEASE','nativeUpdateDismissedBuild','nativeUpdateManualCheck',
    updateCallback+'\nreturn window.XStageAndroidUpdateAvailable;');
  const callback=make(window,state,()=>true,()=>panel,()=>playing,$,()=>{},
    class{constructor(type,options){this.type=type;this.detail=options?.detail;}},
    {build:1087},dismissedBuild,manual);
  return {callback,state,panel,nodes,events,installs};
}
{
  const t=updateScenario();
  t.callback('1.0.88',1088);
  assert.equal(t.panel.hidden,false,'a newer APK must notify while singing');
  assert.equal(t.panel.classes.get('during-playback'),true,'live song must stay visible');
  assert.match(t.nodes.get('android-tv-update-version').textContent,/1088/);
  assert.equal(t.events.length,1,'notify the remote on the new build');
  assert.deepEqual(t.installs,[],'notification MUST NOT silently install an APK');
  t.panel.hidden=true;
  t.callback('1.0.88',1088);
  assert.equal(t.panel.hidden,true,'same build must not reopen a dismissed dialog');
  assert.equal(t.events.length,1,'same build must not spam Owner remote');
  t.callback('1.0.89',1089);
  assert.equal(t.panel.hidden,false,'a genuinely newer build must notify again');
  assert.equal(t.events.length,2);
  t.callback('1.0.80',1080);
  assert.equal(t.events.length,2,'older builds must not be offered');
}
{
  const t=updateScenario({dismissedBuild:1088});
  t.callback('1.0.88',1088);
  assert.equal(t.panel.hidden,true,'Later suppresses this exact build');
  t.callback('1.0.89',1089);
  assert.equal(t.panel.hidden,false,'Later cannot suppress a different build');
}
{
  const t=updateScenario({dismissedBuild:1088,manual:true,playing:false});
  t.callback('1.0.88',1088);
  assert.equal(t.panel.hidden,false,'manual Update command can reopen the same build');
  assert.equal(t.panel.classes.get('during-playback'),false);
}

const guardSrc=segment(app,'function guardAndroidTvSession(){',
  'setInterval(guardAndroidTvSession,30_000)');
function guardScenario({hasSession=true,ready=true,token='old-token',expiresSoon=true,loginBusy=false}={}){
  const state={token,tokenExpiresAt:Date.now()+(expiresSoon?5000:3600000),
    current:{title:'กำลังร้อง'},queue:[{title:'เพลงถัดไป'}]};
  const calls=[];
  const make=new Function('androidTvNativeBridgeReady','androidTvBootAuthStarted',
    'androidTvLoginCancelled','androidTvLoginInProgress','androidTvRefreshingSession',
    'state','androidTvHasStoredGoogleSession','restoreAndroidTvGoogleSession',
    'startAndroidTvDeviceLogin','androidTvAuthPanel','$','setStatus',
    guardSrc+'\nreturn guardAndroidTvSession;');
  const guard=make(()=>true,ready,false,loginBusy,false,state,()=>hasSession,
    ()=>calls.push('restore'),()=>calls.push('login'),()=>({hidden:true}),
    ()=>({textContent:'',hidden:true}),()=>{});
  guard();
  return {state,calls};
}
{
  const t=guardScenario();
  assert.deepEqual(t.calls,['restore'],'expiring token must refresh silently');
  assert.equal(t.state.token,'old-token','refresh cannot discard the current token before replacement');
  assert.equal(t.state.current.title,'กำลังร้อง','refresh must preserve song');
  assert.equal(t.state.queue.length,1,'refresh must preserve upcoming queue');
}
assert.deepEqual(guardScenario({expiresSoon:false}).calls,[],'valid token skips refresh');
assert.deepEqual(guardScenario({loginBusy:true}).calls,[],'no duplicate login while another is pending');
assert.deepEqual(guardScenario({hasSession:false,token:''}).calls,['login'],
  'missing native refresh token must request a new QR');

assert.ok(auth.includes('cancelActiveJob()')&&auth.includes('job.cancel(true)'),
  'Cancel/Retry interrupts an old OAuth polling worker');
assert.ok(auth.includes('if (!isCurrent(run)) return;')&&auth.includes('status(int run'),
  'old OAuth callbacks cannot reappear after cancellation');
assert.ok(app.includes('await openDrive(token,authId,expiresAt,existingSub)'),
  'token renewal must verify immutable Google account identity');
assert.ok(app.includes('state.accountSub===account.sub')&&app.includes('xstage:auth-refreshed'),
  'verified same-account refresh must keep the catalog and song');
assert.ok(updater.includes('checkInFlight.compareAndSet(false, true)'),
  'native update polling must coalesce simultaneous network checks');
assert.ok(updater.includes('activeDownloadId = -1L')&&updater.includes('verifyAndInstall'),
  'APK download must be hash checked before installation');
assert.ok(main.includes('settings.setMediaPlaybackRequiresUserGesture(false)'),
  'Android TV must permit automatic player playback for accepted requests');
assert.ok(main.includes('KEYCODE_DPAD_CENTER')&&main.includes('KEYCODE_MENU')&&main.includes('KEYCODE_BACK'),
  'remote D-pad, MENU and BACK must be wired to TV UI');
assert.ok(host.includes("type:'request-received'")&&host.includes('if(playImmediately)playNext()'),
  'phone request must start immediately only in the permitted empty-queue case');
assert.ok(remote.includes("data.type==='playback-status'"),
  'phone must receive actual stage playback success or error');

console.log('Android TV integration: update detection, nonintrusive toast, login refresh, remote & native safety passed');

assert.ok(app.includes("function setAndroidTvStageAccess(granted,accountSub='')"),'native stage access gate must exist');
assert.ok(app.includes("if(androidTvVerifiedConnectionSub&&(!state.token||"),'native stage must relock when token expires');
assert.ok(app.includes("if(androidTvNativeBridgeReady()&&!androidTvVerifiedConnectionSub)throw error;"),'offline cache cannot unlock a first-time TV login');
assert.ok(main.includes('onLoginScreenReady')&&main.includes('startupBanner.setVisibility(View.GONE)'),'native splash is dismissed only by login UI');
