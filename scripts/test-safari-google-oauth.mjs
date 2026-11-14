import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const app=fs.readFileSync(new URL('../app.js',import.meta.url),'utf8');
function between(start,end){
  const a=app.indexOf(start);
  const b=app.indexOf(end,a+start.length);
  assert.ok(a>=0&&b>a,'OAuth source anchor must exist: '+start);
  return app.slice(a,b);
}
// Exercise the real source functions, not a rewritten version of the logic.
const authSource=between('function googleAuthErrorMessage(error){','function resetPrivate(');
const returnSource=between('let oauthReturnRecoveryTimer=0;','setTimeout(bootAndroidTvAuthentication,0);');
const updateSource=between('function autoApplyWebUpdate(remote){','async function checkAppVersion(){');
assert.doesNotMatch(returnSource,/state\.authId\+\+/,'refocus may not invalidate a pending OAuth callback');
assert.doesNotMatch(returnSource,/ยังไม่ได้ส่งสิทธิ์กลับมา/,'focus alone must not report Google authorization failure');
assert.match(authSource,/flow\.phase='verifying'/,'Google token callback must be protected during Drive verification');

function simulator(){
  let now=1_000_000,nextTimer=0,driveCalls=0,recoverCalls=0,reloadCalls=0;
  const timers=new Map(),events=new Map(),statuses=[],clients=[],store=new Map();
  let pending=null,openDriveOverride=null;
  const state={authId:0,authRecovering:false,token:'',accountSub:'',tokenExpiresAt:0};
  const ui={login:{disabled:false},gateLogin:{disabled:false},gate:{hidden:false}};
  const on=(name,fn)=>{const arr=events.get(name)||[];arr.push(fn);events.set(name,arr);};
  const browser={
    navigator:{onLine:true},
    cfg:{googleClientId:'unit-test.apps.googleusercontent.com'},
    ui,state,
    AUTH_EXPIRY_MARGIN_MS:90_000,
    Date:class extends Date {static now(){return now;}},
    console,
    setTimeout(fn,delay){const id=++nextTimer;timers.set(id,{at:now+Number(delay||0),fn});return id;},
    clearTimeout(id){timers.delete(id);},
    window:{addEventListener:on},
    document:{hidden:false,addEventListener:on},
    google:{accounts:{oauth2:{initTokenClient(config){
      clients.push({config,requested:0});
      const current=clients.at(-1);
      return {requestAccessToken(){current.requested++;}};
    }}}},
    popupPreflightForTv:()=>true,
    androidTvNativeBridgeReady:()=>false,
    isLikelyAndroidTvBrowser:()=>false,
    playbackBusyForUpdate:()=>false,
    setStatus:(message,kind)=>statuses.push({message,kind}),
    savePendingAuth(token,expiresAt){pending={token,expiresAt};},
    readPendingAuth:()=>pending,
    clearPendingAuth(){pending=null;},
    clearActiveAuth(){},
    resetPrivate(){state.token='';},
    hideCatalogLoading(){},
    recoverPendingGoogleAuth:async()=>{recoverCalls++;return false;},
    openDrive:async(token,id,expiresAt)=>{
      driveCalls++;
      if(openDriveOverride)return openDriveOverride(token,id,expiresAt);
      if(id===state.authId){state.token=token;state.accountSub='test-sub';state.tokenExpiresAt=expiresAt;}
    },
    sessionStorage:{
      getItem:key=>store.get(key)??null,
      setItem:(key,val)=>store.set(key,val),
      removeItem:key=>store.delete(key)
    },
    performAppUpdateReload:async()=>{reloadCalls++;},
    showTvPopupHelp(){},
  };
  vm.createContext(browser);
  vm.runInContext(`let webGoogleAuthFlow=null;let webUpdateReloading=false;
    const WEB_AUTO_UPDATE_GUARD='xstage-web-auto-update-target-v1';
    ${updateSource}
    ${authSource}
    ${returnSource}
    globalThis.oauthTest={login,scheduleOAuthReturnRecovery,autoApplyWebUpdate,
       phase:()=>webGoogleAuthFlow?.phase||null};`,browser,{filename:'app-oauth-functions.js'});
  function advance(ms){
    now+=ms;
    let limit=500;
    while(limit-->0){
      const due=[...timers].filter(([,timer])=>timer.at<=now).sort((a,b)=>a[1].at-b[1].at);
      if(!due.length)return;
      const [id,timer]=due[0];timers.delete(id);timer.fn();
    }
    throw Error('Fake timer event loop did not settle');
  }
  return {api:browser.oauthTest,state,ui,clients,statuses,
    fire:(name)=>{for(const fn of events.get(name)||[])fn();},
    advance,now:()=>now,
    setOpenDrive:fn=>{openDriveOverride=fn;},
    setPending:token=>{pending={token,expiresAt:now+3600_000};},
    get driveCalls(){return driveCalls;},
    get recoverCalls(){return recoverCalls;},
    get reloadCalls(){return reloadCalls;}
  };
}
const token=n=>'google-access-token-'+String(n).repeat(48);
async function testLateSuccess(){
  const x=simulator();
  x.api.login();
  assert.equal(x.clients.length,1);
  const originalId=x.state.authId;
  x.fire('focus');
  x.advance(2500);
  assert.equal(x.state.authId,originalId,'Safari refocus must preserve the auth request');
  assert.equal(x.api.phase(),'waiting');
  assert.equal(x.ui.login.disabled,true,'keep original request active while Google is pending');
  assert.equal(x.api.autoApplyWebUpdate({build:1101,version:'1.0.101'}),false,
    'scheduled web reload must not interrupt a Google popup');
  x.advance(10500);
  assert.equal(x.ui.login.disabled,false,'after a delay offer manual retry without discarding first callback');
  await x.clients[0].config.callback({access_token:token(1),expires_in:3600});
  assert.equal(x.state.token,token(1));
  assert.equal(x.driveCalls,1);
  assert.equal(x.api.phase(),null);
  assert.equal(x.ui.login.disabled,false);
  assert.equal(x.statuses.some(x=>x.message.includes('ยังไม่ได้ส่งสิทธิ์กลับมา')),false);
  assert.equal(x.api.autoApplyWebUpdate({build:1101,version:'1.0.101'}),true,
    'automatic update can continue after authorization finishes');
  assert.equal(x.reloadCalls,1);
}
async function testSlowDriveAndDuplicatePopupError(){
  const x=simulator();
  let resolveDrive;
  x.setOpenDrive((accessToken,id,expiresAt)=>new Promise(resolve=>{
    resolveDrive=()=>{x.state.token=accessToken;x.state.accountSub='sub';x.state.tokenExpiresAt=expiresAt;resolve();};
  }));
  x.api.login();
  const originalId=x.state.authId;
  const work=x.clients[0].config.callback({access_token:token(2),expires_in:3600});
  assert.equal(x.api.phase(),'verifying');
  x.fire('pageshow');
  x.advance(2500);
  assert.equal(x.state.authId,originalId);
  assert.equal(x.driveCalls,1,'do not launch a second Drive verification while callback is in progress');
  x.clients[0].config.error_callback({type:'popup_closed'});
  assert.equal(x.api.phase(),'verifying','a late popup-closed event must not cancel a received token');
  resolveDrive();await work;
  assert.equal(x.state.token,token(2));
  assert.equal(x.api.phase(),null);
}
async function testExplicitRetryAndTimeout(){
  const x=simulator();
  x.api.login();
  const stale=x.clients[0].config;
  x.advance(12000);
  assert.equal(x.ui.login.disabled,false);
  x.api.login();
  assert.equal(x.clients.length,2);
  await stale.callback({access_token:token(3),expires_in:3600});
  assert.equal(x.driveCalls,0,'an older callback must not supersede user-requested retry');
  await x.clients[1].config.callback({access_token:token(4),expires_in:3600});
  assert.equal(x.state.token,token(4));
  const timeout=simulator();timeout.api.login();
  const id=timeout.state.authId;
  timeout.advance(90_000);
  assert.equal(timeout.state.authId,id+1,'only the full timeout may invalidate an unanswered flow');
  assert.equal(timeout.ui.login.disabled,false);
  await timeout.clients[0].config.callback({access_token:token(5),expires_in:3600});
  assert.equal(timeout.driveCalls,0,'expired request cannot start a stale Drive authorization');
}
async function testPendingOnRefocusAndPopupClosed(){
  const x=simulator();
  x.setPending(token(6));
  x.fire('focus');x.advance(2500);
  await Promise.resolve();
  assert.equal(x.recoverCalls,1,'recover a stored Google token when no OAuth popup is in progress');
  const y=simulator();
  y.api.login();
  y.clients[0].config.error_callback({type:'popup_closed'});
  assert.equal(y.ui.login.disabled,false,'real GIS popup cancellation must restore controls');
  assert.equal(y.api.phase(),null);
}
await testLateSuccess();
await testSlowDriveAndDuplicatePopupError();
await testExplicitRetryAndTimeout();
await testPendingOnRefocusAndPopupClosed();
console.log('PASS: Safari OAuth refocus, slow callback, delayed Drive verification, retry, timeout, popup error and update guard');
