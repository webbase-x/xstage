import fs from 'node:fs';
import assert from 'node:assert/strict';

const read = path => fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const app = read('app.js');
const host = read('stage-controls.js');
const remote = read('remote.js');
const main = read('android-tv/app/src/main/java/com/webbasex/xstage/MainActivity.java');
const auth = read('android-tv/app/src/main/java/com/webbasex/xstage/GoogleDeviceAuth.java');
assert.ok(main.includes('public String memorySnapshot()')&&
  main.includes('manager.getMemoryInfo(info)')&&
  main.includes('data.put("available", info.availMem)')&&
  main.includes('data.put("lowMemory", info.lowMemory)'),
  'Android bridge must safely report real RAM availability for prefetch pressure');

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
    'nativeUpdateInstalling',
    updateCallback+'\nreturn window.XStageAndroidUpdateAvailable;');
  const callback=make(window,state,()=>true,()=>panel,()=>playing,$,()=>{},
    class{constructor(type,options){this.type=type;this.detail=options?.detail;}},
    {build:1087},dismissedBuild,manual,false);
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
    'androidTvVerifiedConnectionSub','setAndroidTvStageAccess',
    'state','androidTvHasStoredGoogleSession','restoreAndroidTvGoogleSession',
    'startAndroidTvDeviceLogin','androidTvAuthPanel','$','setStatus',
    guardSrc+'\nreturn guardAndroidTvSession;');
  const guard=make(()=>true,ready,false,loginBusy,false,
    token?'verified-google-sub':'',()=>calls.push('lock'),state,()=>hasSession,
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

// TV remote actions must reuse the hosted Karaoke Online controls and queue.
assert.ok(app.includes('function xstageTvRefreshQuickMenu(panel){'),
  'TV quick menu must display fresh Online playback state');
for(const id of ['xstage-tv-quick-play','xstage-tv-quick-previous',
  'xstage-tv-quick-next','xstage-tv-quick-restart',
  'xstage-tv-quick-key-down','xstage-tv-quick-key-up',
  'xstage-tv-quick-queue-list']){
  assert.ok(app.includes(id),'missing TV transport or queue action: '+id);
}
assert.ok(app.includes('xstageTvRefreshQuickMenu(panel);')&&
  app.includes("panel.querySelector('button:not([hidden]):not([disabled])')"),
  'TV menu must refresh and focus an enabled visible button');
assert.ok(app.includes("'.android-tv-update-panel:not([hidden]):not(.during-playback)'"),
  'nonblocking APK notification cannot steal D-pad menu focus');
assert.ok(main.includes('if (event.getRepeatCount() == 0) activateWebFocus();')&&
  main.includes('if (event != null && event.getRepeatCount() > 0)'),
  'holding OK or media remote keys must not repeat actions');
const refreshCode=segment(app,'function xstageTvRefreshQuickMenu(panel){','function xstageTvQuickMenu(){');
{
  const controls=new Map();
  for(const id of ['play-pause','next','previous','restart-current',
    'midi-key-down','midi-key-up','midi-transpose-control'])
    controls.set(id,{disabled:id==='previous',hidden:false});
  const nodes=new Map(),list={items:[],replaceChildren(){this.items=[];},
    append(item){this.items.push(item);}};
  for(const id of ['xstage-tv-quick-now','xstage-tv-quick-key',
    'xstage-tv-quick-queue-count','xstage-tv-quick-login',
    'xstage-tv-quick-play','xstage-tv-quick-previous',
    'xstage-tv-quick-next','xstage-tv-quick-restart',
    'xstage-tv-quick-key-down','xstage-tv-quick-key-up'])
    nodes.set(id,{textContent:'',hidden:false,disabled:false});
  nodes.set('xstage-tv-quick-queue-list',list);
  const panel={querySelector(s){return nodes.get(s.slice(1));}};
  const document={getElementById(id){return controls.get(id)||null;},
    createElement(){return {textContent:''};}};
  const state={current:{title:'เพลงที่กำลังร้อง',artist:'นักร้อง'},
    queue:[{title:'คิว ๑',artist:'ศิลปิน'},{title:'คิว ๒'}],
    liveMidiSource:{},token:'logged-in'};
  const ui={songKey:{textContent:'คีย์ C'}};
  const refresh=new Function('state','document','ui',
    refreshCode+'\nreturn xstageTvRefreshQuickMenu;')(state,document,ui);
  refresh(panel);
  assert.equal(nodes.get('xstage-tv-quick-now').textContent,'เพลงที่กำลังร้อง · นักร้อง');
  assert.equal(nodes.get('xstage-tv-quick-key').textContent,'คีย์ C');
  assert.equal(nodes.get('xstage-tv-quick-queue-count').textContent,'คิวถัดไป 2 เพลง');
  assert.deepEqual(list.items.map(x=>x.textContent),['คิว ๑ · ศิลปิน','คิว ๒']);
  assert.equal(nodes.get('xstage-tv-quick-login').hidden,true);
  assert.equal(nodes.get('xstage-tv-quick-previous').disabled,true);
  assert.equal(nodes.get('xstage-tv-quick-key-up').disabled,false);
  state.liveMidiSource=null;state.queue=[];state.token='';
  refresh(panel);
  assert.equal(nodes.get('xstage-tv-quick-login').hidden,false);
  assert.equal(nodes.get('xstage-tv-quick-key-up').disabled,true);
  assert.equal(list.items[0].textContent,'ยังไม่มีเพลงรอในคิว');
}


// Android TV song search is a bounded view of the hosted Online catalog.
const tvSearchSource=segment(app,'function xstageTvRenderSearch(panel){','function xstageTvSearchPanel(){');
{
  const song={code:'A01',title:'เพลงทดสอบ',artist:'นักร้อง'};
  const called=[],selected=[],closed=[];
  const makeNode=()=>{
    const handlers={};
    return {value:'',textContent:'',children:[],
      replaceChildren(){this.children=[];},
      append(...items){this.children.push(...items);},
      addEventListener(type,fn){handlers[type]=fn;},
      click(){handlers.click?.();}};
  };
  const input=makeNode(),status=makeNode(),results=makeNode();
  const panel={querySelector(id){return ({
    '#xstage-tv-search-input':input,
    '#xstage-tv-search-results':results,
    '#xstage-tv-search-status':status
  })[id];}};
  const state={token:'private-user',songs:[song]};
  const render=new Function('state','document','normalizeSearchText',
    'rankedSearchEntries','num','playable','chooseSearchSong','xstageTvCloseSearch',
    tvSearchSource+'\nreturn xstageTvRenderSearch;')(
    state,{createElement:makeNode},s=>s.trim().toLowerCase(),
    (songs,term,limit)=>{
      called.push({songs,term,limit});
      return {total:1,results:[{song}]};
    },String,()=>true,s=>selected.push(s),v=>closed.push(v));
  render(panel);
  assert.equal(results.children.length,0,'no blank-search catalog exposure');
  assert.equal(called.length,0);
  input.value='เพลง';
  render(panel);
  assert.equal(called[0].songs,state.songs,'uses exactly Online catalog');
  assert.equal(called[0].limit,8,'bounded TV results');
  assert.equal(results.children[0].children[0].textContent,song.title);
  results.children[0].click();
  assert.deepEqual(selected,[song],'TV songs invoke Online playback/queue');
  assert.deepEqual(closed,[false],'chosen song returns to the stage');
  state.token='';
  render(panel);
  assert.equal(results.children.length,0,'sign-out removes all results');
  assert.equal(called.length,1,'sign-out blocks catalog search');
}

// TV queue actions mutate only the hosted Karaoke Online queue.
const tvQueueSource=segment(app,'function xstageTvRenderQueue(panel){','function xstageTvQueuePanel(){');
{
  const song={code:'Q1',title:'เพลงคิว',artist:'ศิลปิน'};
  const queue=[song],plays=[],closes=[];
  const makeNode=()=>{
    const listeners={};
    return {textContent:'',disabled:false,children:[],
      replaceChildren(){this.children=[];},
      append(...items){this.children.push(...items);},
      addEventListener(type,fn){listeners[type]=fn;},
      click(){listeners.click?.();}};
  };
  const list=makeNode(),status=makeNode();
  const panel={querySelector(id){return ({
    '#xstage-tv-queue-items':list,
    '#xstage-tv-queue-status':status
  })[id]||null;}};
  const state={queue,token:'private-user'};
  let onlineRenders=0;
  const render=new Function('state','document','num','renderQueue','moveQueue',
    'xstageTvCloseQueue','playSong',
    tvQueueSource+'\nreturn xstageTvRenderQueue;')(
    state,{createElement:makeNode},String,()=>{onlineRenders++;},
    ()=>{},v=>closes.push(v),song=>plays.push(song));
  render(panel);
  assert.equal(list.children.length,1,'TV queue reads Online queue');
  assert.equal(list.children[0].children[1].children.length,4,'TV queue offers play, up, down, remove');
  list.children[0].children[1].children[0].click();
  assert.equal(queue.length,0,'playing queued song removes it from Online queue');
  assert.deepEqual(plays,[song],'TV queue uses Online playSong');
  assert.equal(onlineRenders,1,'TV queue re-renders Online controls');
  assert.deepEqual(closes,[false],'TV returns directly to stage');
}
assert.ok(app.includes('xstage-tv-quick-queue')&&
  app.includes('xstageTvCloseSearch(false);xstageTvCloseQueue(false);')&&
  app.includes("const queue=document.getElementById('xstage-tv-queue-panel');"),
  'TV queue must support Back and clear on Google sign-out');
assert.ok(read('xstage-ux.css').includes('.xstage-tv-queue-panel[hidden]')&&
  read('xstage-ux.css').includes('.xstage-tv-queue-actions button'),
  'TV queue controls need visible D-pad focus');

assert.ok(app.includes('xstage-tv-quick-search')&&
  app.includes("const search=document.getElementById('xstage-tv-search-panel');")&&
  app.includes('xstageTvCloseSearch(true);return true;'),
  'TV search command and Back should work');
assert.ok(app.includes("event.target?.matches?.('input,textarea,[contenteditable=\"true\"]')"),
  'TV remote arrows should not steal the search caret');
const tvSearchCss=read('xstage-ux.css');
assert.ok(tvSearchCss.includes('.xstage-tv-search-panel[hidden]')&&
  tvSearchCss.includes('.xstage-tv-search-song')&&
  tvSearchCss.includes('max-height:94dvh'),
  'TV search must stay readable and keyboard-focusable at 720p/1080p');

console.log('Android TV integration: update detection, nonintrusive toast, login refresh, remote & native safety passed');

assert.ok(app.includes("function setAndroidTvStageAccess(granted,accountSub='')"),'native stage access gate must exist');
assert.ok(app.includes("if(androidTvVerifiedConnectionSub&&(!state.token||"),'native stage must relock when token expires');
assert.ok(app.includes("if(androidTvNativeBridgeReady()&&!androidTvVerifiedConnectionSub)throw error;"),'offline cache cannot unlock a first-time TV login');
assert.ok(main.includes('onLoginScreenReady')&&main.includes('startupBanner.setVisibility(View.GONE)'),'native splash is dismissed only by login UI');

const ux = read('xstage-ux.css');
const unified = ux.slice(ux.lastIndexOf('/* v1.0.91: Android TV stage shares the WEB stage design exactly.'));
assert.ok(unified.includes('top:37%!important')&&unified.includes('width:min(72cqw,760px)!important'),'native TV uses identical WEB stage placement');
assert.ok(unified.includes('grid-template-columns:minmax(0,1fr) minmax(0,4fr) minmax(0,1fr)!important'),'native TV EQ stays beside the official logo');
assert.ok(unified.includes('z-index:90!important'),'native TV lyrics stay above the stage banner');
assert.ok(app.includes("document.body.classList.add('xstage-native-tv')"),'native TV retains its dedicated remote/login behavior');


const parityFix=ux.slice(ux.lastIndexOf('/* v1.0.93 Android TV/Web stage parity'));
const nativeMeter=read('native-audio-meter.js');
assert.ok(parityFix.includes('top:37%!important')&&parityFix.includes('width:min(72cqw,760px)!important'),
  'Native Audio Direct TV must share Web stage geometry, including while playing');
assert.ok(parityFix.includes('.stage.playing .stage-hero')&&parityFix.includes('transform:translate(-50%,-50%)!important'),
  'TV banner must remain centered and stationary during playback');
assert.ok(parityFix.includes('.stage-hero #stage-viz-left')&&parityFix.includes('.stage-hero #stage-viz-right'),
  'Both native EQ meters must be beside the banner, not floating below or hidden');
assert.ok(parityFix.includes('position:static!important')&&parityFix.includes('display:block!important'),
  'Old Audio Direct absolute-position and hidden-right-meter CSS must be overridden');
assert.ok(parityFix.includes('#lyrics')&&parityFix.includes('z-index:90!important'),
  'TV lyrics must overlay visual elements just like the Web stage');
assert.ok(nativeMeter.includes("document.getElementById('stage-viz-right')")&&
  nativeMeter.includes('view.mirror?LEVELS-1-index:index'),
  'TV must paint both visual meters from live media-capture FFT levels');

// Restored-token startup must explain why QR is not shown and report catalog progress.
assert.ok(app.includes('ได้รับสิทธิ์แล้ว')&&app.includes('ไม่ต้องสแกน QR ซ้ำ'));
assert.ok(app.includes("const status=$('android-tv-auth-status');")&&app.includes("Math.round(Number(progress))+'%'"));
const ambiguousRoot=app.slice(app.indexOf('if(!root){',app.indexOf('async function openDrive(')),app.indexOf('if(preferredRootId&&String(root.id)',app.indexOf('async function openDrive(')));
assert.ok(ambiguousRoot.includes('state.songs=[]')&&ambiguousRoot.includes('setSharedLibraryGate(true')&&ambiguousRoot.includes('setAndroidTvStageAccess(true,account.sub)'), 'Verified ambiguous root must expose only empty library selection, not deadlock behind QR');
assert.ok(app.includes('if(authId!==state.authId)return;\n    state.manifest=catalog;'),'Cancelled catalog load cannot activate stale library');

// QR-first cold launch must not consult or restore a remembered token.
{
  const bootSrc=segment(app,'function bootAndroidTvAuthentication(){','// Re-check the native Drive session');
  const calls=[];
  const boot=new Function('androidTvBootAuthStarted','androidTvNativeBridgeReady','state','startAndroidTvDeviceLogin','androidTvHasStoredGoogleSession','restoreAndroidTvGoogleSession',bootSrc+'\nreturn bootAndroidTvAuthentication;')(false,()=>true,{},()=>calls.push('qr'),()=>{throw Error('Cold launch must not consult stored session');},()=>{throw Error('Cold launch must not restore stored session');});
  boot();boot();
  assert.deepEqual(calls,['qr'],'cold launch requests QR exactly once');
}
assert.deepEqual(guardScenario({hasSession:true,token:''}).calls,['login'],'no silent restore before QR authorization even when a remembered token exists');
assert.ok(app.includes("void renderAndroidTvLoginQr('https://www.google.com/device')"),'Show official QR before Google issues a unique code');
assert.ok(app.includes('if(sequence!==androidTvQrRenderSequence)return;'),'Late QR render must not overwrite verified login UI');

// Native URL resolution must not concatenate karaoke.html and downloads.
assert.ok(updater.includes('return new URL(new URL(BuildConfig.XSTAGE_WEB_URL), relative);'));
for(const path of ['downloads/android-tv-latest.json?t=', 'downloads/android-play-latest.json?t=', 'downloads/'])assert.ok(updater.includes('updateUrl("'+path+'"'));
assert.ok(!updater.includes('BuildConfig.XSTAGE_WEB_URL + "downloads/'));
const publishWorkflow=read('.github/workflows/build-android-tv.yml');
assert.ok(publishWorkflow.includes('cp downloads/android-tv-latest.json karaoke.htmldownloads/android-tv-latest.json')&&publishWorkflow.includes('cmp "downloads/${APK_NAME}" "karaoke.htmldownloads/${APK_NAME}"'),'Legacy installed APK feed must publish the exact same release bytes');
