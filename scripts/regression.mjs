import fs from 'node:fs';
import assert from 'node:assert/strict';

const read=name=>fs.readFileSync(new URL('../'+name,import.meta.url),'utf8');
const requireBannerSource=()=>fs.readFileSync(new URL('../assets/xstage-stage-logo.png',import.meta.url));
const app=read('app.js');
const pc=read('pc-extensions.js');
const host=read('stage-controls.js');
const remote=read('remote.js');
const index=read('karaoke.html');
const storefront=read('index.html');
const storefrontScript=read('storefront.js');
const css=read('xstage-ux.css');
const style=read('style.css');
const apk=read('android-apk-download.js');
const config=read('config.js');
const version=JSON.parse(read('version.json'));
const pkg=JSON.parse(read('package.json'));
const remoteHtml=read('remote.html');
const stageUi=read('stage-ui.js');
const mobile=read('mobile-layout.js');
const iconSvg=read('assets/xstage-app-icon.svg');
const iconBuilder=read('scripts/build_xstage_icons.py');
const iconWorkflow=read('.github/workflows/build-xstage-icons.yml');
const singerStage=read('stage.html');
const androidGradle=read('android-tv/app/build.gradle');
const androidManifest=read('android-tv/app/src/main/AndroidManifest.xml');
const androidMain=read('android-tv/app/src/main/java/com/webbasex/xstage/MainActivity.java');
const androidAuth=read('android-tv/app/src/main/java/com/webbasex/xstage/GoogleDeviceAuth.java');
const androidUpdate=read('android-tv/app/src/main/java/com/webbasex/xstage/XStageUpdateManager.java');
const androidDebugManifest=read('android-tv/app/src/debug/AndroidManifest.xml');
const androidWorkflow=read('.github/workflows/build-android-tv.yml');

assert.doesNotThrow(()=>new Function(storefrontScript),'storefront JavaScript must parse');
assert.match(storefront,/id="store-home"/,'root must be the X-Stage Apps storefront');
assert.match(storefront,/id="app-detail"/,'every app must have a shareable detail view');

const storeLogo=read('assets/xstage-apps-logo.svg');
const storeIcon=read('assets/xstage-apps-icon.svg');
const storeStyle=read('storefront.css');
assert.match(storeLogo,/<svg[^>]+viewBox="0 0 1210 254"/,'storefront must ship a dedicated SVG X-Stage Apps wordmark');
assert.match(storeLogo,/>X-STAGE</,'full X-Stage Apps wordmark must display X-STAGE');
assert.match(storeLogo,/>APPS</,'full X-Stage Apps wordmark must display APPS');
assert.match(storeIcon,/<svg[^>]+viewBox="0 0 512 512"/,'storefront must ship a scalable app icon');
assert.match(storefront,/class="wordmark new-wordmark"[^>]*>[^]*?xstage-apps-logo\.svg/,'new brand logo must replace karaoke logo in header');
assert.match(storefront,/class="footer-logo new-footer-logo"[^>]*>[^]*?xstage-apps-logo\.svg/,'new brand logo must appear in footer');
assert.match(storefront,/id="intro-title">หนึ่งเวที/,'new hero headline must render');
assert.match(storefront,/class="intro section-wrap new-home-hero"/,'editorial hero must be present');
assert.match(storeStyle,/\.intro\.new-home-hero\{/,'redesigned hero styling must load');
assert.match(storefront,/storefront\.css\?brand=[1-9]\d*/,'storefront refresh must bust the cached stylesheet');
assert.ok(Number(storefront.match(/storefront\.js\?brand=(\d+)/)?.[1]) >= 12,'installer download UI must bust stale cached storefront script');
assert.ok(!storefront.includes('xstage-app-icon-192.png" width="38"'),'storefront header must not reuse old Karaoke icon');

// The public URL must stay on the app hub for television browsers (even
// when a legacy Android query parameter is present). Only an installed
// versioned Karaoke APK is migrated to the dedicated player URL.
const nativeRedirectScript=storefront.match(
  /<script id="legacy-native-karaoke-entry">([\s\S]*?)<\/script>/)?.[1];
assert.ok(nativeRedirectScript,'the legacy native fallback must be narrowly gated');
const runStorefrontRedirect=(search, nativeBridge=false)=>{
  const navigations=[];
  const location={search,hash:'',replace:url=>navigations.push(url)};
  const window={};
  if(nativeBridge)window.XStageAndroid={};
  new Function('window','location','URLSearchParams',nativeRedirectScript)(
    window,location,URLSearchParams);
  return navigations;
};
assert.deepEqual(runStorefrontRedirect(''),[],
  'public site root must show the X-Stage Apps hub');
assert.deepEqual(runStorefrontRedirect('?source=android-tv'),[],
  'TV browser query must not redirect the public app hub');
assert.deepEqual(runStorefrontRedirect('?source=android-tablet&native_version=1.0.119'),[],
  'native-looking query without the installed Android bridge must stay on the app hub');
assert.deepEqual(runStorefrontRedirect(''),[],
  'opening /index.html in an ordinary browser must stay on the app hub');
assert.deepEqual(runStorefrontRedirect('?source=android-tv&native_version=1.0.119',true),
  ['./karaoke.html?source=android-tv&native_version=1.0.119'],
  'a legacy installed Karaoke APK must retain its player entry point');
assert.match(read('android-tv/app/build.gradle'),
  /XSTAGE_WEB_URL", quoteBuildConfig\("https:\/\/webbase-x\.github\.io\/xstage\/karaoke\.html"\)/,
  'new Android Karaoke APKs must launch the dedicated player URL');
assert.match(storefront,/\.\/*karaoke\.html/,'karaoke web must remain reachable after the homepage change');
for(const slug of ['karaoke-web','karaoke-pc','studio-pro','karaoke-android','mirror-tv','mirror-ios-pc','mirror-android-pc','file-share']){
  assert.ok(storefront.includes('href="?app='+slug+'"'),'storefront must expose detail route for '+slug);
  assert.ok(storefront.includes('data-app="'+slug+'"'),'storefront must show card for '+slug);
}
assert.ok(storefrontScript.includes('downloads/song-studio-pro-latest.json')&&storefrontScript.includes('downloads/windows-pc-latest.json'),'desktop download status must come from published manifest');
assert.ok(storefrontScript.includes('downloads/android-tv-latest.json')&&storefrontScript.includes('mirror-tv/latest.json'),'TV download status must come from published manifest');
assert.ok(!storefront.includes('rel="manifest"'),'storefront must not restore retired karaoke PWA registration');

const uniqueApps=[
  ['karaoke-pc','assets/app-icons/karaoke-pc.svg','KARAOKE PC'],
  ['karaoke-android','assets/app-icons/karaoke-android.svg','KARAOKE TV'],
  ['mirror-tv','assets/app-icons/mirror-tv.svg','MIRROR TV'],
  ['file-share','assets/app-icons/file-share.svg','FILE SHARE']
];
for(const [slug,path,label] of uniqueApps){
  const icon=read(path);
  assert.ok(icon.includes(label),'Unique product icon must identify '+slug);
  const card=storefront.match(new RegExp('<article class="app-card" data-app="'+slug+'"[^]*?<\\/article>'))?.[0];
  assert.ok(card&&card.includes(path.replace(/^assets\//,'./assets/').replace(/^studio\//,'./studio/')),
    'App collection must display its own logo for '+slug);
}
assert.ok(storefront.includes('songstudio-plus/web/icon.svg'),'Song Studio Pro card must show its own distinct icon');
assert.ok(storefront.includes('data-app="studio-pro"')&&!storefront.includes('data-app="studio-pc"'),'only Pro app card is allowed');
assert.ok(storefront.includes('assets/xstage-apps-apple-touch-icon.png'),'X-Stage Apps iOS artwork must remain');
assert.ok(read('mirror-tv/index.html').includes('mirror-tv-apple-touch-icon.png'),'Mirror TV pairing guide keeps separate artwork');
for(const asset of ['assets/xstage-apps-apple-touch-icon.png','assets/app-icons/mirror-tv-apple-touch-icon.png']){
 const data=fs.readFileSync(new URL('../'+asset,import.meta.url));
 assert.ok(data.byteLength>1024&&data[0]===137&&data[1]===80,'Expected generated PNG '+asset);
}
assert.ok(read('.github/workflows/build-windows-pc.yml').includes('scripts/build_karaoke_pc_icon.py'),'Windows candidate must generate distinct PC icon before bundling');
assert.ok(read('xstage-mirror-tv/prepare_upstream.py').includes('Distinct X-Stage Mirror TV cast icon'),'Mirror TV native launcher must have a separate cast identity');
assert.ok(read('mirror-tv/index.html').includes('../assets/app-icons/mirror-tv.svg'),'Mirror pairing guide must show its own icon');
const tvReload=read('tv-refresh.js');
assert.doesNotThrow(()=>new Function(tvReload),'TV refresh JS must parse');
assert.ok(index.includes('id="tv-refresh-window"')&&index.includes('tv-refresh.js?v=1119'),'TV player must expose refresh button and logic');
assert.ok(app.includes('xstage-tv-quick-refresh')&&app.includes('window.XStageTvRefreshPage?.()'),'Android TV remote quick menu must contain a working refresh action');
assert.ok(css.includes('body.xstage-ui-v2 .stage #tv-refresh-window:not([hidden])'),'TV refresh must override stage overlay hiding');
assert.ok(singerStage.includes('id="refresh-window"')&&singerStage.includes('window.location.reload()'),'separate TV stage must have clickable reload');
assert.ok(read('mirror-tv/index.html').includes('id="mirror-refresh-window"')&&read('mirror-tv/index.html').includes('window.location.reload()'),'Mirror TV website must expose a refresh button');
assert.ok(read('mirror-tv/index.html').includes('BlueStacks 5')&&read('mirror-tv/index.html').includes('../?app=mirror-ios-pc'),'Mirror TV guide must explain emulator limitations and link to native Windows receiver');
assert.ok(read('xstage-mirror-tv/README.md').includes('BlueStacks 5 emulator limitation'),'Mirror TV README must document unsupported emulator receiver testing');
assert.ok(storefrontScript.includes('windows-pc-preview-latest.json'),'Public storefront must advertise only a verified Windows binary preview, not an unbuilt EXE');
assert.ok(read('SOURCE_DISTRIBUTION_POLICY.md').includes('GPLv3'),'Repository policy must preserve the GPLv3 source obligation for Mirror TV');


const guideSource=read('storefront-device.js');
const guideModule={exports:{}};
assert.doesNotThrow(()=>new Function('module',guideSource)(guideModule),'device guidance module must parse');
const deviceGuide=guideModule.exports;
const iphone=deviceGuide.detect({userAgent:'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15',platform:'iPhone'});
const ipad=deviceGuide.detect({userAgent:'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15)',platform:'MacIntel',maxTouchPoints:5});
const windows=deviceGuide.detect({userAgent:'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',platform:'Win32'});
const androidTv=deviceGuide.detect({userAgent:'Mozilla/5.0 (Linux; Android 12; SHIELD Android TV)',platform:'Linux'});
const androidPhone=deviceGuide.detect({userAgent:'Mozilla/5.0 (Linux; Android 14; Pixel 9) Mobile Safari/537.36',platform:'Linux'});
assert.equal(iphone.kind,'ios','iPhone must be detected');
assert.equal(ipad.kind,'ios','iPadOS desktop user-agent must not be mistaken for macOS');
assert.equal(windows.kind,'windows','Windows must be detected');
assert.equal(androidTv.kind,'android_tv','Android TV must be detected');
assert.equal(deviceGuide.detect({userAgent:'Mozilla/5.0 (Linux; Android 10; TrueIDTV Box) AppleWebKit',platform:'Linux'}).kind,'android_tv','TrueID TV box should be recognized as an Android TV device');
assert.equal(androidPhone.kind,'android_phone','Android phone must be distinguished from TV');
assert.equal(deviceGuide.forApp(iphone,'mirror-tv').level,'other','iPhone must be labelled sender, not Mirror APK receiver');
assert.equal(deviceGuide.forApp(iphone,'karaoke-android').level,'other','iOS must not be labelled Android-compatible');
assert.equal(deviceGuide.forApp(windows,'karaoke-pc').level,'supported','Windows should recommend Karaoke PC');
assert.equal(deviceGuide.forApp(androidTv,'mirror-tv').level,'supported','Android TV should recommend Mirror receiver');
assert.equal(deviceGuide.forApp(androidPhone,'karaoke-android').level,'unknown','Android phone must not be advertised as TV/tablet compatible');
assert.equal(deviceGuide.forApp(iphone,'studio-pro').level,'other','Song Studio Pro must require Windows x64');
assert.ok(storefront.includes('id="device-advice-title"')&&storefront.includes('id="detail-device-info"'),'storefront must have contextual guidance on catalog and detail');
assert.equal((storefront.match(/data-device-app=/g)||[]).length,(storefront.match(/<article class="app-card[^>]* data-app=/g)||[]).length,'all catalog cards need device-compatibility hints');
assert.equal(deviceGuide.forApp(windows,'download-manager').level,'supported','Download Manager is supported on Windows');
assert.equal(deviceGuide.forApp(iphone,'download-manager').level,'other','Download Manager is not an iOS app');
assert.ok(storefront.includes('data-app="download-manager"') && storefrontScript.includes('download-manager-preview-latest.json'),'new Download Manager card and manifest must remain discoverable');
const downloadManagerRelease=JSON.parse(read('downloads/download-manager-preview-latest.json'));
assert.equal(downloadManagerRelease.channel,'preview','Download Manager must remain labelled preview');
if(downloadManagerRelease.available===true){
  assert.match(downloadManagerRelease.sha256,/^[a-f0-9]{64}$/,'published Windows EXE must have SHA-256');
  assert.match(downloadManagerRelease.file,/^X-Stage-Download-Manager-v\d+\.\d+\.\d+-build\d+-win-x64-Setup\.exe$/,'only installer EXE is allowed');
  assert.equal(downloadManagerRelease.download_url,'https://github.com/webbase-x/xstage/releases/download/xstage-download-manager-v'+downloadManagerRelease.version+'-build'+downloadManagerRelease.build+'-preview/'+downloadManagerRelease.file,'EXE must be published to verified GitHub Release');
}else assert.equal(downloadManagerRelease.available,false,'an unpublished Windows EXE must stay hidden');
assert.ok(/storefront-device\.js\?brand=[1-9]\d*/.test(storefront) && storefront.indexOf('storefront-device.js') < storefront.indexOf('storefront.js'),'device guidance must be loaded before storefront controller');
assert.ok(storefrontScript.includes('mirror-tv/test-latest.json'),'storefront may discover strictly separated Mirror test feed');
assert.ok(storefront.includes('data-download-app="mirror-ios-pc"')&&storefront.includes('data-download-app="mirror-android-pc"'),'both standalone Windows mirror apps must have separate download actions');
assert.ok(storefrontScript.includes('mirror-ios-pc-preview-latest.json')&&storefrontScript.includes('mirror-android-pc-preview-latest.json'),'both standalone receiver apps must check their own latest release feeds');
assert.equal(deviceGuide.forApp(windows,'mirror-ios-pc').level,'supported','Windows supports Mirror iOS PC');
assert.equal(deviceGuide.forApp(windows,'mirror-android-pc').level,'supported','Windows supports Mirror Android PC control app');
assert.equal(deviceGuide.forApp(iphone,'mirror-ios-pc').level,'other','iOS sends to the Windows receiver, not the other way around');
for(const id of ['mirror-ios-pc','mirror-android-pc']){
  const manifest=JSON.parse(read('downloads/'+id+'-preview-latest.json'));
  assert.equal(manifest.channel,'preview','standalone receiver release channel must be Preview');
  if(manifest.available){
    assert.match(manifest.sha256,/^[a-f0-9]{64}$/,'receiver Setup EXE must have SHA-256');
    assert.ok(manifest.download_url.endsWith('-Setup.exe'),'website must download full Setup EXE');
    assert.ok(manifest.download_url.includes('xstage-'+id+'-v'),'receiver release tag must match its own app');
  }
}
assert.ok(read('mirror-ios-pc/ReceiverIdentity.cs').includes('RandomNumberGenerator.GetInt32(1000, 10000)'),'receiver number must be cryptographically randomized and persisted');
assert.ok(read('mirror-android-pc/MainForm.cs').includes('MakeLabel(Environment.MachineName') && !read('mirror-android-pc/MainForm.cs').includes('ReceiverIdentity'),'Mirror Android PC must show its real Windows hostname, not a No./ID number');
const mirrorPcRelease=JSON.parse(read('downloads/mirror-pc-preview-latest.json'));
assert.equal(mirrorPcRelease.channel,'preview','Mirror PC preview channel must remain explicit');
if(mirrorPcRelease.available){
  assert.match(mirrorPcRelease.sha256,/^[a-f0-9]{64}$/,'public Mirror PC ZIP must advertise SHA-256');
  assert.ok(mirrorPcRelease.download_url.includes('/releases/download/xstage-mirror-pc-v'),'Mirror PC ZIP must come from a public verified release');
  assert.ok(mirrorPcRelease.source_url?.endsWith('-GPLv3-source.tar.gz'),'Mirror PC must include GPL source distribution');
}

assert.ok(storefront.includes('data-filter="files"')&&storefront.includes('data-download-app="file-share"'),'File Share must have its own filter and APK card action');
const expectedPlatformCards={
  'apps-portal':'android',
  'karaoke-web':'website',
  'karaoke-pc':'windows',
  'download-manager':'windows',
  'studio-pro':'windows',
  'karaoke-android':'android',
  'mirror-ios-pc':'windows',
  'mirror-android-pc':'windows',
  'mirror-tv':'android',
  'file-share':'android'
};
const platformCards=[...storefront.matchAll(/<article class="app-card[^"]*" data-app="([^"]+)" data-category="([^"]+)" data-platform="([^"]+)" data-name="/g)];
assert.equal(platformCards.length,Object.keys(expectedPlatformCards).length,'all catalog apps must declare a platform');
for(const card of platformCards){
  assert.equal(card[3],expectedPlatformCards[card[1]],'wrong platform classification: '+card[1]);
}
for(const platform of ['all','windows','android','website']){
  assert.ok(storefront.includes('data-platform-filter="'+platform+'"'),'missing platform filter '+platform);
}
assert.match(storefrontScript,/const platformMatches=selectedPlatform==="all"/,'platform filter must combine with category filters');
assert.match(storefrontScript,/const matches=categoryMatches&&platformMatches&&textMatches/,'category platform and search must compose');
assert.match(storefrontScript,/platformButtons\.forEach\(button=>button\.addEventListener\("click"/,'platform controls must respond to user selection');
assert.match(read('storefront.css'),/\.platform-pill\.active/,'platform filter active state must be visible');
assert.equal(deviceGuide.forApp(androidPhone,'file-share').level,'supported','Android phones support the File Share host APK');
assert.equal(deviceGuide.forApp(iphone,'file-share').level,'other','iOS joins File Share through browser instead of APK');
const fileShareRelease=JSON.parse(read('downloads/file-share-latest.json'));
assert.equal(fileShareRelease.channel,'preview','File Share APK must be labelled Preview');
assert.match(fileShareRelease.sha256,/^[a-f0-9]{64}$/,'File Share APK SHA-256 must be specified');
assert.ok(fileShareRelease.download_url.includes('xstage-file-share-v')&&fileShareRelease.download_url.endsWith('.apk'),'File Share must link to a published APK binary');
assert.ok(storefrontScript.includes('downloads/file-share-latest.json'),'File Share must load its verified public APK feed');

const mirrorTest=JSON.parse(read('mirror-tv/test-latest.json'));
assert.equal(mirrorTest.channel,'test-preview','Mirror TV cannot be represented as a production-signed release');
assert.equal(mirrorTest.available,true,'verified test release must be advertised');
assert.match(mirrorTest.sha256,/^[a-f0-9]{64}$/,'Mirror TV test SHA256 must be present');
assert.ok(storefront.includes('data-download-app="mirror-tv"'),'Mirror TV card must provide a visible APK action when available');
assert.ok(storefrontScript.includes('direct_download_available')&&
          storefrontScript.includes('sameOriginFile(data.file,"downloads"'),
          'Android TV users should receive same-origin APK downloads before external GitHub redirects');
assert.ok(storeStyle.includes('.app-card .app-card-download[hidden]'),'Mirror TV direct action must not show until APK is verified');
assert.ok(storefrontScript.includes('if(id==="mirror-tv"&&appInfo[id].testManifest)'),
          'Mirror TV test APK should still be discoverable when production feed fails');
assert.ok(read('mirror-tv/index.html').includes('id="mirror-download-direct"'),
          'Mirror TV connection guide must provide a direct install button');
const mirrorBuilder=read('.github/workflows/build-xstage-mirror-tv.yml');
assert.ok(mirrorBuilder.includes('gh release create')&&
          mirrorBuilder.includes('actual!=os.environ["SHA256"]')&&
          mirrorBuilder.includes('direct_download_available')&&
          mirrorBuilder.includes('git add mirror-tv/test-latest.json "downloads/$APK_FILE"'),
          'Every new Mirror TV APK must be verified and published directly on X-Stage Pages');
assert.ok(!read('.github/workflows/publish-mirror-tv-direct-apk.yml').includes('gh release download'),
          'Legacy standalone publisher must not re-publish an obsolete Mirror TV APK');
const receiverPolicy=read('xstage-mirror-tv/ReceiverNamePolicy.kt');
const receiverEditor=read('xstage-mirror-tv/ReceiverNameEditor.kt');
const receiverBuild=read('xstage-mirror-tv/prepare_upstream.py');
const receiverRecipe=read('xstage-mirror-tv/test_build_recipe.py');

const receiverUpdater=read('xstage-mirror-tv/MirrorUpdateManager.kt');
const mirrorReleaseWorkflow=read('.github/workflows/release-xstage-mirror-tv.yml');
assert.ok(receiverUpdater.includes('official.signerSha256 != installedSigner')&&
          receiverUpdater.includes('offerIncompatibleOfficial()')&&
          receiverUpdater.includes('installedSignerSha256()'),
          'Mirror TV must screen update signing identities before Android install');
assert.ok(mirrorBuilder.includes('LEGACY_APK="X-Stage-Mirror-TV-test-v0.2.5-build107.apk"')&&
          mirrorBuilder.includes('STABLE_SHA=$(python3')&&
          mirrorReleaseWorkflow.includes('"signing_mode":"persistent"')&&
          mirrorReleaseWorkflow.includes('"signer_sha256":os.environ["SIGNER_SHA256"]'),
          'Mirror release process must audit legacy signing and pin new releases');

assert.ok(receiverPolicy.includes('const val PREFIX = "X-Stage Mirror TV"')&&
          receiverPolicy.includes('fun migratePreviousName(context: Context)')&&
          receiverPolicy.includes('fun fromSuffix(rawSuffix: String)'),
          'Mirror TV must retain the fixed brand prefix and preserve previously saved names');
assert.ok(receiverEditor.includes('เปลี่ยนชื่ออุปกรณ์')&&
          receiverEditor.includes('namePreview')&&
          receiverEditor.includes('viewModel.set(Prefs.SERVER_NAME, namePreview)')&&
          receiverEditor.includes('enabled = canEdit'),
          'Mirror TV overview and Settings must provide a safe save-only suffix editor');
assert.ok(receiverEditor.includes('onDone = { saveName() }')&&
          receiverEditor.includes('Key.NumPadEnter')&&
          receiverEditor.includes('fieldBringIntoView.bringIntoView()')&&
          receiverEditor.includes('right = cancelFocus')&&
          !receiverEditor.includes('AlertDialog('),
          'Mirror receiver name must stay visible and save on keyboard Enter');
const receiverHome=read('xstage-mirror-tv/XStageReceiverHome.kt');
assert.ok(receiverHome.includes('ReceiverNameEditor(viewModel, canEdit = true, onFinished = { editingName = false })')&&
          receiverHome.includes('text = serverName,')&&
          receiverHome.includes('if (mirroringActive && connections > 0)')&&
          receiverHome.includes('onSettings: () -> Unit')&&
          !receiverHome.includes('startServer')&&!receiverHome.includes('stopServer'),
          'The primary Mirror TV receiver must be uncluttered, nameable and show picture without controls');
assert.ok(receiverBuild.includes('XStageReceiverHome(')&&
          receiverBuild.includes('BackHandler(enabled = !confirmExit.value)')&&
          receiverBuild.includes('title = { Text("ปิด X-Stage Mirror TV?") }')&&
          receiverBuild.includes('Text("ปิด")')&&receiverBuild.includes('Text("ไม่ปิด")')&&
          receiverBuild.includes('ReceiverNamePolicy.migratePreviousName(this)')&&
          receiverRecipe.includes('ReceiverNameEditor(viewModel, canEdit = activeConnections == 0)'),
          'The Android build must start automatically and ask before closing on Back');
assert.ok(receiverBuild.includes('VERSION = os.environ.get("XSTAGE_MIRROR_VERSION"') &&
          receiverBuild.includes('BUILD = os.environ.get("XSTAGE_MIRROR_BUILD"'),
          'Mirror TV clean receiver must declare configurable version and build');
if(mirrorTest.direct_download_available===true){
  const name=mirrorTest.direct_download_file;
  assert.match(name,/^X-Stage-Mirror-TV-test-v\d+\.\d+\.\d+-build\d+\.apk$/);
  assert.equal(mirrorTest.direct_download_sha256,mirrorTest.sha256,
    'published direct APK SHA256 must match source release');
  assert.equal(mirrorTest.direct_download_url,"https://webbase-x.github.io/xstage/downloads/"+name);
  const full=new URL('../downloads/'+name,import.meta.url);
  assert.ok(fs.existsSync(full),'Published APK file is required for active Mirror TV direct-download flag');
}

assert.ok(read('.github/workflows/build-xstage-mirror-tv.yml').includes('gh release create')&&
          read('.github/workflows/build-xstage-mirror-tv.yml').includes('test-latest.json'),
          'Mirror public test APK must be published only after checks, separate from production feed');
assert.ok(read('.github/workflows/release-xstage-mirror-tv.yml').includes('workflow_dispatch:')&&
          !read('.github/workflows/release-xstage-mirror-tv.yml').includes('branches: [main]'),
          'production Mirror signed release must not fail automatically when owner secrets are missing');



for(const [name,source] of [['app.js',app],['pc-extensions.js',pc],['stage-controls.js',host],['remote.js',remote],['stage-ui.js',stageUi],['mobile-layout.js',mobile],['android-apk-download.js',apk]]){
  assert.doesNotThrow(()=>new Function(source),name+' must parse');
}

for(const [i,script] of [...singerStage.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m=>m[1]).entries()){
  assert.doesNotThrow(()=>new Function(script),'stage.html inline script '+i+' must parse');
}

const eqMatch=pc.match(/function eqFreqLabel\(f\)\{([\s\S]*?)\n\}/);
assert.ok(eqMatch,'eqFreqLabel must exist');
const eqFreqLabel=new Function('f',eqMatch[1]);
assert.equal(eqFreqLabel(1000),'1k');
assert.equal(eqFreqLabel(10000),'10k');
assert.equal(eqFreqLabel(12500),'12.5k');
assert.equal(eqFreqLabel(20000),'20k');

assert.match(app,/function playbackHasActiveIntent\(\)/);
assert.match(app,/if\(!playbackHasActiveIntent\(\)\)[\s\S]*playSong\(song\)[\s\S]*else\{[\s\S]*addToQueue\(song\)/);
assert.match(app,/libraryCacheOwner\(sub,rootId/);
assert.match(app,/xstage:librarychange/);
assert.match(app,/checkAppVersion/);
assert.match(app,/sharedLibraryFeatureReady/);
assert.ok(app.includes('window.XStageSharedLibraryReady=sharedLibraryFeatureReady'),'shared-library readiness must be diagnosable without pretending Picker is configured');
assert.ok(app.includes("คลังที่แชร์ · ต้องตั้งค่า Google Picker"),'missing Picker configuration must be explicit in the shared-library gate');

assert.ok(!host.includes("action==='stop'"),'host must not expose legacy stop action');
assert.ok(host.includes("action==='cancel-current'"),'host must cancel current song');
assert.ok(remoteHtml.includes('data-admin="cancel-current"'),'Owner remote must expose cancel-current');
assert.ok(host.includes("const guestPermissions={search:true,request:true,playpause:true,'volume-up':true,'volume-down':true,mute:true}"),'Guest must be restricted to search/request/play-pause/volume/mute');
assert.ok(!host.match(/const guestPermissions=.*cancel-current/),'Guest must not receive cancel-current');
assert.ok(!index.includes('cdnjs.cloudflare.com/ajax/libs/peerjs'),'main page must lazy-load PeerJS');
assert.ok(host.includes(`./assets/vendor/peerjs.min.js?v=${version.build}`),'host remote must load same-origin PeerJS for Android WebView reliability');
assert.ok(host.includes(`./assets/vendor/qrcode.min.js?v=${version.build}`),'host remote must load same-origin QRCode');
assert.ok(remoteHtml.includes(`assets/vendor/peerjs.min.js?v=${version.build}`),'mobile remote must load same-origin PeerJS');
assert.ok(!host.includes('cdnjs.cloudflare.com/ajax/libs/peerjs'),'host remote must not depend on PeerJS CDN');
assert.ok(!remoteHtml.includes('cdnjs.cloudflare.com/ajax/libs/peerjs'),'mobile remote must not depend on PeerJS CDN');
assert.ok(host.includes('peerOpenTimer'),'host remote must time out when PeerJS never obtains an ID');
assert.ok(style.includes('--xstage-remote-qr-size')&&style.includes('width:var(--xstage-remote-qr-size)!important')&&style.includes('height:var(--xstage-remote-qr-size)!important'),'remote QR must render as an exact square on PC web and Android');
assert.ok(style.includes('--xstage-auth-qr-size')&&style.includes('width:var(--xstage-auth-qr-size)!important')&&style.includes('height:var(--xstage-auth-qr-size)!important'),'Google login QR must render as an exact square on Android');
assert.ok(host.includes('qrCanvas.width=232;qrCanvas.height=232'),'remote QR backing canvas must stay 1:1');
assert.ok(app.includes('canvas.width=248;canvas.height=248'),'Google login QR backing canvas must stay 1:1');
assert.ok(remote.includes('connectWatchdog'),'mobile remote must time out instead of hanging during pairing');
assert.ok(remote.includes('armConnectWatchdog(30000)'),'a connected Peer must still wait for the authenticated ready handshake');
assert.ok(remote.includes('requestId,index:item.index')&&host.includes('requestId,title:String(song.title'),'song requests must receive per-request acknowledgements');
assert.ok(remote.includes('scheduleReconnect()'),'remote should offer bounded reconnect attempts');
assert.ok(host.includes('window.XStageEnsureQrLibrary'),'mobile pairing and Android login must share the same QR renderer');
assert.ok(app.includes('window.XStageEnsureQrLibrary=ensureAndroidTvQrLibrary'),'Android login must provide a single QR script loader');
assert.ok(remoteHtml.includes('remote.js?v='+version.build),'mobile remote JS must match the released web build');
assert.ok(remoteHtml.includes('config.js?v='+version.build),'mobile remote config must not stay pinned to a stale build');

assert.ok(host.includes("url.searchParams.set('v',String(window.XSTAGE_RELEASE?.build||0))"),'pairing QR must bust stale cached mobile HTML');
assert.ok(remoteHtml.includes('min-height:48px'),'mobile controls must preserve accessible touch targets');
assert.ok(host.includes('retry:createSession'),'TV must have a user-triggered QR repair path');
assert.ok(app.includes('xstage-tv-quick-new-qr'),'TV D-pad menu must expose QR regeneration');

assert.ok(css.includes('.xstage-tv-quick-menu'),'TV quick menu needs legible TV-focus styles');
assert.ok(app.includes('window.XStageTvOpenMenu=()=>'),'physical Android TV remote must be able to open its quick menu');
assert.ok(app.includes('return window.XStageTvOpenMenu?.()||false'),'OK key must open quick menu on TrueID remotes without MENU');
assert.ok(app.includes('window.XStageTvHandleBack=()=>'),'Android TV Back must dismiss modal controls safely');
assert.ok(androidMain.includes('KEYCODE_MENU')&&androidMain.includes('KEYCODE_SEARCH'),'physical TV remote must support MENU and SEARCH buttons');
const tokenStore=read('android-tv/app/src/main/java/com/webbasex/xstage/GoogleTokenStore.java');
assert.ok(tokenStore.includes('AndroidKeyStore')&&tokenStore.includes('AES/GCM/NoPadding'),'refresh token storage must use authenticated encryption');
assert.ok(androidAuth.includes('tokenStore.write(refreshToken)')&&!androidAuth.includes('prefs.edit().putString(REFRESH_TOKEN'),'native auth must never persist a new refresh token in plaintext');

assert.ok(!index.includes('cdnjs.cloudflare.com/ajax/libs/qrcode'),'main page must lazy-load QRCode');
assert.ok(!index.includes('apis.google.com/js/api.js'),'main page must lazy-load Google Picker API');
assert.ok(pc.includes("FAVORITES_STORE='xstage-favorites-v2'"),'favorites must persist');
assert.ok(pc.includes("HISTORY_STORE='xstage-play-history-v1'"),'play history must persist');
assert.ok(index.includes('id="library-select"'),'multi-library selector must exist');
assert.ok(index.includes('id="gate-close"'),'login gate must be dismissible for stage preview');
assert.ok(app.includes('function androidTvNativeBridgeReady()'),'web app must detect the native Android TV bridge');
assert.ok(app.includes('window.XStageAndroidDeviceCode'),'web app must render Google device codes from Android');
assert.ok(app.includes('function bootAndroidTvAuthentication()'),'Android TV app must bootstrap authentication automatically');
assert.ok(app.includes('startAndroidTvDeviceLogin(true)'),'Android TV must open device login immediately when no stored session exists');
assert.ok(app.includes("id=\"android-tv-auth-qr\""),'Android TV login overlay must include a QR canvas');
assert.ok(app.includes(`./assets/vendor/qrcode.min.js?v=${version.build}`),'Android login must load the same-origin QR renderer');
assert.ok(app.includes('armAndroidTvLoginWatchdog()'),'Android login must time out instead of hanging while waiting for a Google device code');
assert.ok(app.includes('async function boundedPlaybackTask(')&&app.includes('publishPlaybackStatus(\'blocked\''),'Android TV must show actionable playback failure instead of leaving a song on preload');
assert.ok(host.includes("type:'playback-status'")&&remote.includes("data.type==='playback-status'"),'mobile remote must receive real playback outcome from TV');
assert.ok(app.includes('function armAndroidTvLoginWatchdog(){')&&app.includes('function clearAndroidTvLoginWatchdog(){'),'Google QR login watchdog MUST be implemented, not just called');
assert.ok(app.includes('androidTvLoginInProgress')&&app.includes('androidTvLoginCancelled'),'Google login cancellation and restoration must not race into duplicate QR requests');
assert.ok(app.includes("#xstage-tv-quick-login"),'TV quick menu must allow re-login after cancellation');
assert.ok(app.includes('void renderAndroidTvLoginQr(verificationUrl)'),'Google device URL must be rendered as QR when the code arrives');
assert.ok(app.includes('androidTvHasStoredGoogleSession()'),'Android TV must restore an existing Google session before requesting a new QR');
assert.ok(androidAuth.includes('boolean hasStoredSession()'),'native Google auth must expose whether a refresh token is stored');
assert.ok(androidMain.includes('public boolean hasStoredGoogleSession()'),'Android JS bridge must expose the stored-session check');
assert.ok(app.includes('window.XStageReceiveAndroidToken'),'web app must accept the Android TV OAuth access token');
assert.ok(androidGradle.includes("applicationId 'com.webbasex.xstage'"),'Android TV package id must stay stable for Google Play');
assert.ok(androidGradle.includes('minSdk 23'),'Android TV app must remain compatible with Android 10 and older supported TVs');
assert.ok(androidGradle.includes('targetSdk 34'),'Android TV app must meet the current Google Play TV target requirement');
assert.ok(androidManifest.includes('android.intent.category.LEANBACK_LAUNCHER'),'Android TV launcher category must be declared');
assert.ok(androidManifest.includes('android.software.leanback')&&androidManifest.includes('android:required="false"'),'leanback must be optional so the same APK installs on tablets');
assert.ok(androidManifest.includes('android.intent.category.LAUNCHER'),'tablet launcher category must be declared');
assert.ok(androidManifest.includes('android.hardware.touchscreen')&&androidManifest.includes('android:required="false"'),'Android TV app must not require touchscreen hardware');
assert.ok(androidMain.includes('addJavascriptInterface(new AndroidBridge(), "XStageAndroid")'),'native Android bridge must be exposed only inside the trusted X-Stage WebView');
assert.ok(androidMain.includes('"android-tv" : "android-tablet"'),'Android app must identify TV versus tablet to the hosted X-Stage web runtime');
assert.ok(androidMain.includes('Configuration.UI_MODE_TYPE_TELEVISION'),'native app must detect television mode instead of assuming every Android device is a TV');
assert.ok(androidAuth.includes('https://oauth2.googleapis.com/device/code'),'Android TV login must use Google device authorization');
assert.ok(androidAuth.includes('https://oauth2.googleapis.com/token'),'Android TV login must poll the Google token endpoint');
assert.ok(androidAuth.includes('https://www.googleapis.com/auth/drive.file'),'Android TV login must keep the existing private Drive scope');
assert.ok(androidWorkflow.includes('assembleDebug assembleRelease bundleRelease'),'CI must build APK and AAB from the same Android source');
assert.ok(androidWorkflow.includes('actions/upload-artifact@v4'),'CI must publish Android TV build artifacts');
assert.ok(androidWorkflow.includes('Validate Google TV OAuth credentials'),'CI must block publishing Android APKs without Google TV OAuth configuration');
assert.ok(androidWorkflow.includes('XSTAGE_TV_OAUTH_CLIENT_ID')&&androidWorkflow.includes('XSTAGE_TV_OAUTH_CLIENT_SECRET'),'CI must require both Google TV OAuth secrets');
assert.ok(app.includes('ยังไม่ได้ตั้งค่า Google OAuth สำหรับ APK รุ่นนี้'),'Android login UI must clearly explain a missing OAuth configuration instead of looking frozen');
assert.ok(androidWorkflow.includes('APK_NAME="X-Stage-Karaoke-Android-v${VERSION}-build${BUILD}.apk"'),'CI must publish a versioned TV/tablet Android APK filename on main');
assert.ok(androidWorkflow.includes("git push origin HEAD:main"),'CI must commit the latest test APK back to main after a successful main build');
assert.ok(fs.existsSync(new URL('../android-tv/test-signing/xstage-test-update.jks',import.meta.url)),'stable Android TV test signing key must exist');
assert.ok(androidGradle.includes('signingConfig signingConfigs.testSideload'),'debug APK must use the stable sideload signing key');
assert.ok(androidGradle.includes('xstage-test-update.jks'),'stable sideload key path must stay configured');
assert.ok(androidDebugManifest.includes('android.permission.REQUEST_INSTALL_PACKAGES'),'test APK must request package-install permission for in-app sideload updates');
assert.ok(!androidManifest.includes('android.permission.REQUEST_INSTALL_PACKAGES'),'Google Play release manifest must not request sideload install permission');
assert.ok(androidUpdate.includes('downloads/android-tv-latest.json'),'native updater must check the GitHub Pages latest-version metadata');
assert.ok(androidUpdate.includes('CHECK_INTERVAL_MS'),'native updater must periodically re-check for newer APK builds');
assert.ok(androidUpdate.includes('MessageDigest.getInstance("SHA-256")'),'downloaded APK must be verified before installation');
assert.ok(androidUpdate.includes('Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES'),'test APK must guide Android unknown-source permission when required');
assert.ok(androidUpdate.includes('manager.getUriForDownloadedFile(id)'),'native updater must pass the completed APK to the Android installer');
assert.ok(androidMain.includes('updateManager.checkForUpdates(true)'),'Android TV must check for APK updates immediately after the hosted UI loads');
assert.ok(androidMain.includes('public void installAvailableUpdate()'),'Android JS bridge must expose the update installer');
assert.ok(androidMain.includes('public boolean dispatchKeyEvent(KeyEvent event)'),'Android TV must intercept remote key events before WebView consumes them');
assert.ok(androidMain.includes('KEYCODE_DPAD_CENTER')&&androidMain.includes('KEYCODE_ENTER')&&androidMain.includes('KEYCODE_NUMPAD_ENTER')&&androidMain.includes('KEYCODE_BUTTON_A'),'Android TV OK/Enter variants must activate the focused web control');
assert.ok(androidMain.includes('KEYCODE_DPAD_LEFT')&&androidMain.includes('KEYCODE_DPAD_RIGHT')&&androidMain.includes('KEYCODE_DPAD_UP')&&androidMain.includes('KEYCODE_DPAD_DOWN'),'Android TV D-pad directions must drive web focus');
assert.ok(androidMain.includes('!webTextEditingActive')&&androidMain.includes('void setTextEditingActive(boolean active)')&&app.includes("document.addEventListener('focusin',syncNativeTextEditingState,true)"),
  'Android TV must let the WebView/IME handle arrows and Enter when text is being edited');
assert.ok(androidMain.includes('AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)')&&
          androidMain.includes('setWillPauseWhenDucked(true)')&&
          androidMain.includes('requestPlaybackAudioFocus()')&&
          androidMain.includes('releasePlaybackAudioFocus()'),
  'Android native audio focus must be acquired before playback and released when idle');
assert.ok(app.includes("window.addEventListener('xstage-native-audio-focus'")&&
          app.includes("change==='loss-transient'")&&app.includes("change==='loss-permanent'")&&
          app.includes("nativeAudioFocusBlocked||!state.resumeAfterInterruption"),
  'Android audio interruptions must preserve manual pause and block autoplay until focus returns');
assert.ok(androidAuth.includes('synchronized boolean hasStoredSession()'),
  'Google session inspection must serialize with login and logout');
assert.ok(app.includes('window.XStageTvMoveFocus=direction=>'),'hosted UI must expose spatial focus navigation for TV remotes');
assert.ok(app.includes('window.XStageTvActivateFocused=()=>'),'hosted UI must expose focused-control activation for TV remotes');
assert.ok(app.includes('function setupNativeAndroidTvUi()'),'native Android TV must have a dedicated display-only UI setup');
assert.ok(app.includes("...(nativeTv?[]:['.remote-pair-panel:not([hidden])'])"),'passive TV remote QR must never hijack D-pad active scope');
assert.ok(app.includes("if(document.body.classList.contains('xstage-native-tv')&&scope===document)return []"),'TV display mode must expose no ordinary D-pad-focusable web controls');
assert.ok(app.includes("'toggle-keyboard'")&&app.includes("'virtual-keyboard'")&&app.includes("'pc-search'"),'TV display mode must explicitly remove search and onscreen keyboard UI');
assert.ok(app.includes("queue.tabIndex=-1;queue.hidden=true;queue.style.pointerEvents='none'"),'TV queue control must be completely hidden and non-interactive');
assert.ok(androidMain.includes('callJavascript("window.XStageTvOpenMenu'),'Android TV MENU key must open the accessible TV quick menu');
assert.ok(androidMain.includes('if (isTelevisionDevice())')&&androidMain.includes('window.XStageTvOpenMenu'),'Android TV SEARCH key must open TV quick menu instead of focusing hidden search');
assert.ok(androidMain.includes('settings.setUseWideViewPort(true)')&&androidMain.includes('settings.setTextZoom(100)'),'Android TV WebView must use stable viewport and text scaling');
assert.ok(androidManifest.includes('android:usesCleartextTraffic="false"')&&androidManifest.includes('android:hardwareAccelerated="true"'),'Android TV app must use HTTPS-only traffic and hardware acceleration');
assert.ok(androidGradle.includes('b.setColor(java.awt.Color.WHITE)')&&androidGradle.includes('b.fillRect(0,0,320,180)'),'Android TV launcher banner must use a pure white 16:9 background');
assert.ok(androidGradle.includes('rootProject.file("../assets/xstage-stage-logo.png")')&&
          androidGradle.includes('splashFile.bytes = logoSource.bytes')&&
          androidGradle.includes('b.drawImage(icon,17,28,115,115,null)')&&
          androidGradle.includes('b.drawString("KARAOKE",142,100)')&&
          androidGradle.includes('b.drawString("TV",143,122)')&&
          androidGradle.includes('b.drawString("X-STAGE",142,65)'),
          'Android TV must preserve original splash while using its dedicated Karaoke icon and navy text on a white 320x180 banner');
assert.ok(androidGradle.includes('drawable-nodpi/xstage_tv_banner.png'),'TV launcher banner must use nodpi without Android density rescaling');
assert.ok(androidGradle.includes('def label = "KARAOKE TV"')&&androidGradle.includes('g.fillPolygon([222,222,306]')&&!androidGradle.includes('g.drawImage(sourceLogo,iconLeft,iconTop,iconW,iconH,null)'),'Android launcher must render its own TV/play/remote icon, not the Web or stage-banner art');
assert.ok(!androidGradle.includes('g.drawRoundRect(218,160,76,140')&&!androidGradle.includes('g.drawLine(205,398,307,398)'),'obsolete synthetic microphone launcher icon must not be regenerated');
assert.ok(androidManifest.includes('android:roundIcon="@drawable/xstage_app_icon"')&&androidManifest.includes('android:logo="@drawable/xstage_app_icon"'),'app-grid launcher icon fallbacks must all use the new logo');
assert.ok(androidManifest.match(/android:banner="@drawable\/xstage_tv_banner"/g)?.length===2,'activity and application must use the same official banner');

assert.ok(androidManifest.includes('android.intent.category.LEANBACK_LAUNCHER')&&
          androidManifest.includes('android.intent.category.LAUNCHER'),
          'Karaoke TV must be discoverable and addable in TV Launcher app rows');
const homeShortcut=read('android-tv/app/src/main/java/com/webbasex/xstage/TvHomeShortcut.java');
const nativeTvMain=read('android-tv/app/src/main/java/com/webbasex/xstage/MainActivity.java');
assert.ok(homeShortcut.includes('isRequestPinShortcutSupported()')&&
          homeShortcut.includes('requestPinShortcut(shortcut, null)')&&
          homeShortcut.includes('Intent.CATEGORY_HOME'),
          'Karaoke TV must offer explicit pinning when supported and TV Home fallback');
assert.ok(nativeTvMain.includes('public void requestHomeIcon()')&&
          nativeTvMain.includes('TvHomeShortcut.request(MainActivity.this)'),
          'Karaoke TV must safely expose native requestHomeIcon bridge');
assert.ok(app.includes('xstage-tv-quick-home')&&
          app.includes('window.XStageAndroid?.requestHomeIcon?.()'),
          'Karaoke TV remote quick menu must offer a Home shortcut action');
const mirrorRecipe=read('xstage-mirror-tv/prepare_upstream.py');
const mirrorHome=read('xstage-mirror-tv/TvHomeShortcut.kt');
assert.ok(mirrorRecipe.includes('im = Image.new("RGB", size, (255,255,255))')&&
          mirrorRecipe.includes('banner((320,180))')&&mirrorRecipe.includes('banner((640,360))'),
          'Mirror TV must publish white 16:9 banners at both Android drawable densities');
assert.ok(mirrorRecipe.includes('TvHomeShortcut.request(homeShortcutContext)')&&
          mirrorRecipe.includes('for filename in ("ReceiverNamePolicy.kt", "TvHomeShortcut.kt")'),
          'Mirror TV Home screen must provide a pin/favorites action');
assert.ok(mirrorHome.includes('isRequestPinShortcutSupported')&&
          mirrorHome.includes('requestPinShortcut(shortcut, null)')&&
          mirrorHome.includes('Intent.CATEGORY_HOME'),
          'Mirror TV must use supported shortcut API or guide to TV favorites');

const actualBannerSourceSha=await import('node:crypto').then(x=>x.createHash('sha256').update(requireBannerSource()).digest('hex'));
assert.equal(actualBannerSourceSha,'5cc34771ae31287ef70ff032d56763a45e5942b3f27a8623c0c81ea72f8f0622','Android logo source must be pixel-identical to the user-supplied PNG');
assert.ok(css.includes('1.0.71 Android TV display-only stage'),'TV-specific final layout must live in the last-loaded UX stylesheet');
assert.ok(css.includes('body.xstage-native-tv .topbar')&&css.includes('body.xstage-native-tv #pc-search')&&css.includes('body.xstage-native-tv #virtual-keyboard'),'TV must hide all search/menu/keyboard chrome');
assert.ok(css.includes('left:clamp(18px,2vw,30px)!important')&&css.includes('right:clamp(18px,2vw,30px)!important'),'TV brand and QR must occupy opposite top corners');
assert.ok(css.includes('body.xstage-native-tv.xstage-ui-v2 .stage .transport-panel')&&css.includes('bottom:clamp(14px,2vh,24px)!important'),'TV song/progress strip must stay anchored at the bottom');
assert.ok(index.includes('id="tv-song-key"'),'TV song strip must expose a dedicated musical-key field');
assert.ok(app.includes("song.key||song.musicKey||song.originalKey||song.keySignature"),'TV musical key must use real key metadata when available');
assert.ok(host.includes("if(nativeTvMode)setTimeout(()=>showQR(true),0)"),'TV must show the mobile remote QR automatically');

assert.ok(app.includes("event.key==='Enter'||event.key==='Accept'"),'hosted UI must handle TV Enter/Accept as a fallback for older APKs');
assert.ok(app.includes('window.XStageAndroidUpdateAvailable'),'hosted UI must receive Android TV update notifications');
assert.ok(app.includes('state.nativeUpdateAvailable=next;')&&app.includes("window.dispatchEvent(new CustomEvent('xstage:native-update'"),'native TV updates must notify on both TV display and Owner remote');
assert.ok(app.includes('if(androidTvNativeBridgeReady())return null;'),'native Android must never mistake a web-only update for an APK update');
assert.ok(app.includes('id="android-tv-update-now"'),'Android TV update prompt must offer an update-now button');
assert.ok(app.includes('WEB_AUTO_UPDATE_GUARD'),'web must guard against stale-cache automatic reload loops');
assert.ok(app.includes('autoApplyWebUpdate(state.updateAvailable)'),'older web shells must automatically apply newer published builds');
assert.ok(app.includes('if(playbackBusyForUpdate())return false;'),'automatic web upgrades must not interrupt active karaoke playback');
assert.ok(app.includes("window.XStageAndroidUpdateAvailable=(version,build)=>"),'older installed APKs must receive new release notifications through the hosted UI');
assert.ok(app.includes("android-tv-update-now')?.addEventListener('click'")&&app.includes("installAvailableUpdate"),'native APK upgrades must require the explicit Update Now button');
assert.ok(!app.includes("button?.click();"),'a new release notification must never auto-tap the installer button');

assert.ok(index.includes('id="desktop-update-version"')&&index.includes('id="mobile-update-version"'),'version update controls must be available on desktop and compact/mobile UI');
assert.ok(app.includes('triggerImmediateVersionUpdate'),'all version-update controls must share the immediate update path');
assert.ok(app.includes("action.textContent='อัปเดตตอนนี้'")&&app.includes('action.disabled=false'),'web update notice must always expose an active update-now button');
assert.ok(!app.includes("action.textContent=playbackBusyForUpdate()?'อัปเดตเมื่อจบ':'อัปเดตตอนนี้'"),'web updates must not wait for playback to finish');
assert.ok(androidUpdate.includes('CHECK_INTERVAL_MS = 60L * 1000L'),'native update checks must refresh promptly');
assert.ok(androidUpdate.includes('installRequested'),'one update tap must continue automatically after native metadata arrives');
assert.ok(androidMain.includes('updateManager.checkForUpdates(true)'),'Android must force an update check as soon as the hosted UI is ready');
assert.ok(style.includes('calc(100% - 24px)')&&style.includes('overflow-x:hidden'),'QR rendering must remain contained inside its panel');
assert.ok(app.includes('installAvailableUpdate'),'update-now button must invoke the native updater');
assert.ok(index.includes('id="android-tv-apk-download"'),'main menu must expose a direct Android TV APK download link');
assert.ok(app.includes('function startManualGoogleLogin()')&&!app.includes('XStageBeforeGoogleLogin'),'Google login must not use the removed PWA gate');
assert.ok(app.includes('let webGoogleAuthFlow=null;')&&app.includes("flow.phase='verifying'")&&
          app.includes('if(webGoogleAuthFlow||state.authRecovering)return false;'),
          'Google GIS token flow must guard Safari callbacks and defer web auto-update during authorization');
assert.ok(app.includes("document.addEventListener('visibilitychange',scheduleOAuthReturnRecovery)")&&
          !app.includes('กลับจาก Google แล้วแต่ Safari ยังไม่ได้ส่งสิทธิ์กลับมา'),
          'Safari refocus must not declare failure or invalidate a late Google callback');
assert.ok(app.includes('clearTimeout(retryTimer)')&&app.includes('if(authId!==state.authId||settled)return;'),
          'OAuth retry and popup error callbacks must not cancel a verified token');
assert.ok(index.includes('android-apk-download.js?v='+version.build),'browser must load the APK-only helper');
assert.ok(!index.includes('rel="manifest"')&&!index.includes('mobile-install-app')&&!index.includes('pc-install-app'),'browser must not advertise PWA installation');
assert.ok(!fs.existsSync(new URL('../pwa-install.js',import.meta.url)),
  'retired PWA installation UI must remain removed');
const obsoleteWorker=read('sw.js');
assert.match(storefront,/id="retire-stale-karaoke-pwa"/,
  'public apps landing page must remove old root service-worker registrations');
assert.match(storefront,/reg\.scope===expected/,
  'cleanup must not unregister unrelated app workers');
assert.match(storefront,/key\.startsWith\('xstage-shell-'\)/,
  'cleanup must remove only X-Stage legacy shell cache');
assert.ok(!obsoleteWorker.includes("addEventListener('fetch'") &&
          !obsoleteWorker.includes('addEventListener("fetch"'),
  'retirement worker must not intercept navigations or serve Karaoke cache');
assert.ok(!obsoleteWorker.includes('caches.open(') &&
          !obsoleteWorker.includes('serviceWorker.register('),
  'retirement worker must never re-create a PWA or cache public pages');
const retireHandlers={};
const deletedShellCaches=[];
let retirementUnregistered=0, retirementSkipped=0, retirementWait=null;
const retiredRootWorker={
  addEventListener:(name,handler)=>{retireHandlers[name]=handler;},
  skipWaiting:async()=>{retirementSkipped++;},
  registration:{unregister:async()=>{retirementUnregistered++;return true;}}
};
const legacyCaches={
  keys:async()=>['xstage-shell-v1097','xstage-shell-v1078','songstudio-cache','private-catalog'],
  delete:async key=>{deletedShellCaches.push(key);return true;}
};
new Function('self','caches',obsoleteWorker)(retiredRootWorker,legacyCaches);
assert.deepEqual(Object.keys(retireHandlers).sort(),['activate','install'],
  'old PWA replacement may only install and immediately retire');
retireHandlers.install({waitUntil:p=>{retirementWait=p;}});
await retirementWait;
retireHandlers.activate({waitUntil:p=>{retirementWait=p;}});
await retirementWait;
assert.equal(retirementSkipped,1);
assert.equal(retirementUnregistered,1);
assert.deepEqual(deletedShellCaches.sort(),['xstage-shell-v1078','xstage-shell-v1097'],
  'worker must preserve other app and private database caches');
assert.ok(!fs.existsSync(new URL('../xstage.webmanifest',import.meta.url))&&!fs.existsSync(new URL('../manifest.webmanifest',import.meta.url)),'retired root web manifests must be removed');
assert.ok(apk.includes('retireLegacyPwa()')&&apk.includes('reg.unregister()')&&!apk.includes('serviceWorker.register'),'old scoped PWA worker must be removed, never re-registered');
assert.ok(apk.includes('offerPublishedAndroidApk(apk)')&&apk.includes("actionButton('ใช้ X-Stage Web ต่อ'"),'APK offer must still allow web-only operation');
assert.ok(apk.includes('ANDROID_APK_NEVER_ASK_KEY')&&apk.includes('verifiedAndroidApk'),'APK must respect opt-out and validated metadata');
assert.ok(apk.includes("ANDROID_TV_LATEST_URL='./downloads/android-tv-latest.json'")&&apk.includes('refreshAndroidTvApkLink()'),'APK must use the latest versioned artifact metadata');
assert.ok(!apk.includes('beforeinstallprompt')&&!index.includes('apple-mobile-web-app-capable'),'PWA affordances must stay removed');
assert.ok(index.includes('property="og:title"'),'Open Graph title must exist');
assert.ok(index.includes(`src="assets/xstage-app-icon.svg?v=${version.build}"`),'topbar must use the canonical stage emblem at the current build');
assert.ok(index.includes('assets/xstage-favicon-32.png'),'web favicon must use the stage-emblem icon set');
assert.ok(!index.includes('xstage-logo.jpg'),'legacy photographic logo must not remain in the live page');
assert.ok(iconSvg.includes('M18 18 78 78M78 18 18 78'),'canonical app icon must reuse the exact X geometry from the stage emblem');
assert.ok(iconSvg.includes('M32 48v5a16 16 0 0 0 32 0v-5M48 69v10M38 80h20'),'canonical app icon must reuse the stage microphone/stand geometry');
assert.ok(iconBuilder.includes('SOURCE = ASSETS / "xstage-app-icon.svg"'),'Icon PNG builder must render from the canonical stage emblem SVG');
assert.ok(iconBuilder.includes('xstage-favicon-32.png'),'icon builder must generate a browser favicon');
assert.ok(iconWorkflow.includes('assets/xstage-app-icon.svg'),'icon workflow must trigger from the canonical stage emblem');
assert.ok(!iconWorkflow.includes('assets/xstage-logo.jpg'),'icon workflow must not rebuild from the retired photographic logo');
assert.ok(!index.includes('data-cmd="find">⌕'),'context menu must not depend on fragile symbol glyphs');
assert.ok(app.includes('function setSearchAvailability'),'search auth state must be explicit');
assert.ok(app.includes('function dismissLoginGate'),'login gate preview behavior must exist');
assert.ok(index.includes('placeholder="ค้นหาเพลง ชื่อศิลปิน หรือรหัสเพลง"'),'search placeholder must stay readable without clipped punctuation');
assert.ok(!index.includes('placeholder="ค้นหาเพลง, ศิลปิน หรือรหัสเพลง..."'),'legacy punctuation-heavy placeholder must stay removed');
assert.ok(!index.includes('id="search" type="search" role="combobox" aria-autocomplete="list" aria-controls="songs" aria-expanded="false" autocomplete="off" placeholder="ค้นหาเพลง ชื่อศิลปิน หรือรหัสเพลง" aria-label="ค้นหาเพลง ชื่อศิลปิน หรือรหัสเพลง" aria-disabled="false" data-library-ready="false" readonly'),'search must not be readonly before login');
assert.ok(!app.includes("ui.search.addEventListener('focus',()=>{\n  if(state.token)return;\n  ui.gate.hidden=false"),'search focus must not reopen login gate');
assert.ok(app.includes("const pendingSearch=keepAuth?String(ui.search?.value||''):''"),'typed search must survive Google auth handoff');
assert.ok(app.includes("renderSongs();\n  updateTransport();\n  if(ui.search.value.trim())setLiveSearchExpanded(true);"),'typing must immediately resync the transport play button');
assert.ok(app.includes('function normalizeSearchText'),'search text must be normalized once through the indexed search path');
assert.ok(app.includes('function indexedSongs'),'catalog search index must exist for larger libraries');
assert.ok(app.includes('function searchScore'),'search relevance scoring must exist');
assert.ok(app.includes('function rankedSearchEntries'),'ranked search helper must exist');
assert.ok(app.includes("state.shown=ranked.results.map(item=>item.song);"),'live search must show only the five highest-ranked songs');
assert.ok(app.includes("ranked.total>5?' · 5 ผลลัพธ์ที่ตรงที่สุด':''"),'search summary must describe ranked five-result output');
assert.ok(index.includes('id="search-refine-hint"'),'search must offer a refinement hint when many songs match');
assert.ok(!app.includes("matches.slice(0,120)"),'legacy 120-result live search limit must stay removed');
assert.ok(css.includes("/* 1.0.44: karaoke-scale search input and five-result presentation. */"),'large karaoke search styling must exist');
assert.ok(css.includes("font-size:clamp(1.28rem,2.15vw,1.85rem)!important"),'desktop typed search text must remain prominently sized');
assert.ok(css.includes("font-size:clamp(1.12rem,1.8vw,1.5rem)!important"),'desktop song-title results must remain prominently sized');
assert.ok(app.includes("renderSongs();\n    updateTransport();\n    if(!state.token)"),'Enter must refresh current search results before choosing a song');
assert.match(app,/if\(!player\.src\)\s*\{\s*if\(state\.queue\.length\)playNext\(\);\s*else if\(state\.shown\.length\)playSong\(state\.shown\[state\.selectedIndex\]\)/,
  'Play on idle should use queue first, then the selected search result');
assert.ok(app.includes("ui.elapsed.textContent=hasLoadedSong?timeLabel(player.currentTime):'--:--'"),'idle player must not look stuck at 00:00');
assert.ok(index.includes('<span class="transport-now-caption">สถานะเพลง</span>'),'idle player caption must not claim that audio is already playing');
assert.ok(!index.includes('id="mobile-home-toggle">⌂'),'drawer should use explicit text labels instead of icon-only prefixes');
assert.ok(index.includes('id="login" class="button button-google" type="button"><span class="google-g" aria-hidden="true">G</span> เชื่อมต่อ Google Drive'),'secondary account trigger must not duplicate the primary Google Sign-In CTA');
assert.ok(index.includes('id="mobile-login-toggle">เชื่อมต่อ Google Drive</button>'),'drawer account trigger must route through the canonical login gate');
assert.ok(index.includes('id="gate-login" class="button button-primary" type="button"><span class="google-white-g" aria-hidden="true">G</span> เข้าสู่ระบบ Google</button>'),'PRIVATE STAGE must keep one primary Google Sign-In CTA');
assert.ok(!css.includes('font:800 .76rem/1.2 Inter,Tahoma,sans-serif'),'context menu must use Thai-safe font stack');
assert.ok(css.includes('"Noto Sans Thai"'),'Thai-safe fallback font must be present');
assert.ok(css.includes('body.xstage-ui-v2 .stage .login-gate{\n  z-index:120!important;'),'PRIVATE STAGE must render above the persistent drawer');
assert.ok(css.includes('body.xstage-ui-v2.xstage-gate-active .stage .mobile-stage-menu'),'drawer must be suppressed while PRIVATE STAGE is active');
assert.ok(css.includes('.stage-search-slot #search::placeholder{\n  font-family:"Leelawadee UI","Noto Sans Thai"'),'search placeholder must force a Thai-safe font');
assert.ok(app.includes('function cleanStatusMessage'),'status sanitizer must exist');
assert.ok(app.includes('const punctuationOnly='),'punctuation-only auth errors must be rejected');
assert.ok(stageUi.includes('const punctuationOnly='),'visible stage toast must independently reject punctuation-only errors');
assert.ok(!mobile.includes("status.textContent=$('status')?.textContent||''"),'drawer must not copy raw auth/error status text');
assert.ok(mobile.includes("'Google Drive พร้อมใช้งาน'"),'drawer must show a stable Google Drive summary');
assert.ok(mobile.includes("gate.hidden=false"),'drawer Google action must open the canonical PRIVATE STAGE gate');
assert.ok(pc.includes('createMediaElementSource(audio)'),'player EQ must remain wired to HTML5 Audio through Web Audio');
assert.ok(pc.includes('createAnalyser()'),'audio visualizer/analyser path must remain wired');
assert.equal((pc.match(/createMediaElementSource\(audio\)/g)||[]).length,1,'stage visualizer must reuse the single existing HTML5 Audio source');
assert.ok(index.includes('id="stage-viz-left"'),'main stage must expose the left live visualizer canvas');
const nativeMeter=read('native-audio-meter.js');
assert.ok(index.includes('native-audio-meter.js?v='+version.build),'the silent native meter must share the current asset build');
assert.ok(nativeMeter.includes('player.captureStream()')&&nativeMeter.includes('mute.gain.value=0'),'Android meter must sample the playing song with zero audible output');
assert.ok(!/\b(?:context|ctx)\.createMediaElementSource\s*\(/.test(nativeMeter),'native visualizer must never reroute the main media output');
assert.ok(pc.includes("['android-tv','android-tablet']"),'native direct sound path must include APK TV and tablet modes');
assert.ok(host.includes('nativeAudioDirect:!!window.XStageNativeAudioBypass'),'Owner remote must report direct-audio bypass');
assert.ok(remote.includes('eqSelect.disabled=direct'),'Owner EQ must be disabled on Android APK');
assert.ok(css.includes('.xstage-native-audio-direct'),'Android stage must render the live meter in its native layout');

assert.ok(index.includes('id="stage-viz-right"'),'main stage must expose the right live visualizer canvas');
assert.ok(index.includes('id="stage-viz-wave"'),'main stage must expose the center waveform canvas');
assert.ok(index.includes('assets/xstage-stage-logo.png?v='+version.build),'stage must reference the exact original branded PNG at current build');
assert.ok(index.includes('class="stage-official-banner"'),'main stage must show the original PNG only');
assert.ok(!index.includes('class="stage-brand-copy"'),'synthesized old text logo must be removed');
assert.ok(singerStage.includes('assets/xstage-stage-logo.png?v='+version.build),'singer screen must reference the same single original PNG');
assert.ok(pc.includes("['premium-neon','Premium Neon']"),'Premium Neon stage theme must exist');
assert.ok(pc.includes("['modern-concert','Modern Concert']"),'Modern Concert stage theme must exist');
assert.ok(pc.includes("['futuristic-audio-tech','Futuristic Audio Tech']"),'Futuristic Audio Tech stage theme must exist');
assert.ok(pc.includes('ธีมโลโก้ X-Stage Online + Audio Visualizer'),'background settings must expose brand/visualizer themes');
assert.ok(pc.includes('stageFrequencyLevels(bins)'),'stage visualizer must derive levels from real analyser frequency bins');
assert.ok(pc.includes('eqAnalyser.getByteFrequencyData(bins)'),'stage visualizer must read the existing audio analyser');
assert.ok(pc.includes("if(nativeAndroidTvAudioMode())return true;")&&pc.includes("if(!ensureEqAudio())return false;"),'PC Web must keep the shared EQ/visualizer audio graph while Android TV preserves the native media path by default');
assert.ok(pc.includes("screen.postMessage({type:'xstage-brand-viz'"),'main stage must synchronize live visualizer data to the singer screen');
assert.ok(singerStage.includes('id="brand-viz-left"'),'singer screen must include live visualizer canvases');
assert.ok(singerStage.includes("e.data?.type==='xstage-brand-viz'"),'singer screen must render analyser-fed visualizer data');
assert.ok(css.includes('[data-brand-theme="premium-neon"]'),'Premium Neon theme CSS must exist');
assert.ok(css.includes('[data-brand-theme="modern-concert"]'),'Modern Concert theme CSS must exist');
assert.ok(css.includes('[data-brand-theme="futuristic-audio-tech"]'),'Futuristic Audio Tech theme CSS must exist');
assert.ok(!pc.includes("classList.toggle('stage-hero-hidden',mode==='photo')"),'photo artwork must no longer hide the redesigned X-Stage Online identity');
assert.equal((remoteHtml.match(/<body(?:\\s|>)/g)||[]).length,1,'remote.html must contain exactly one body element');
assert.equal((remoteHtml.match(/<\/body>/g)||[]).length,1,'remote.html must contain exactly one closing body tag');
assert.equal((remoteHtml.match(/<\/html>/g)||[]).length,1,'remote.html must contain exactly one closing html tag');
assert.ok(remoteHtml.indexOf('</style>')>=0&&remoteHtml.indexOf('</style>')<remoteHtml.indexOf('<body>'),'remote.html CSS must close before visible body markup');
assert.ok(!remoteHtml.includes('.role-note{m<body>'),'remote.html must never embed body markup inside CSS');
assert.ok(remoteHtml.includes('grid-template-columns:repeat(4,minmax(0,1fr))'),'remote navigation must visibly fit all four tabs');
assert.ok(!remoteHtml.includes('⏹ หยุด'),'remote UI must not expose redundant stop');
assert.ok(pc.includes("เพิ่ม/นำออกจากเพลงโปรด · บันทึกในเบราว์เซอร์นี้"),'favorite tooltip must describe persistent browser storage accurately');
assert.ok(pc.includes('function autoPresetMetadata'),'AUTO EQ must distinguish metadata-based selection from audio analysis');
assert.ok(pc.includes('AUTO: FLAT · ไม่มีข้อมูลแนวเพลง'),'AUTO EQ must clearly explain metadata fallback');
assert.ok(stageUi.includes("volumeLabel.textContent=muted?'ปิดเสียง · '+n+'%':n+'%'"),'main player must preserve volume while clearly labeling mute');
assert.ok(css.includes('/* 1.0.45: one canonical utilities menu, clearer search refinement and mute state. */'),'1.0.45 utility menu polish must exist');
assert.ok(css.includes('/* 1.0.49: EQ always fits the visible viewport on desktop, tablet, phone, portrait and landscape. */'),'responsive EQ viewport rules must exist');
assert.ok(css.includes('grid-template-columns:repeat(31,minmax(0,1fr))!important'),'main EQ must fit all 31 bands without horizontal overflow');
assert.ok(css.includes('overflow:hidden!important;'),'responsive EQ must prevent band-strip overflow');
assert.ok(css.includes('@media(max-width:520px)'),'main EQ must include a phone-specific compact layout');
assert.ok(css.includes('@media(orientation:landscape) and (max-height:520px)'),'main EQ must include a short-landscape layout');
assert.ok(pc.includes('function fitEqPanelToViewport()'),'main EQ must clamp a dragged/resized panel back into the viewport');
assert.ok(pc.includes("window.addEventListener('orientationchange',()=>setTimeout(fitEqPanelToViewport,80))"),'main EQ must refit after device rotation');
assert.ok(singerStage.includes('/* 1.0.49: singer-screen EQ responsive fit for every viewport. */'),'singer-screen EQ must have matching responsive rules');
assert.ok(singerStage.includes('function fitSeqToViewport()'),'singer-screen EQ must clamp itself to the viewport');
assert.ok(singerStage.includes("window.addEventListener('orientationchange',()=>setTimeout(fitSeqToViewport,80))"),'singer-screen EQ must refit after rotation');
assert.ok(css.includes('.stage-column.mobile-tools-expanded .transport-panel .pc-tools{\n  display:none!important;'),'duplicate legacy tools flyout must stay hidden');
assert.ok(index.includes('id="mobile-speed-select"'),'playback speed must remain available after consolidating utilities');
assert.ok(stageUi.includes("const mobileSpeed=$('mobile-speed-select')"),'canonical menu speed selector must stay synchronized');
assert.ok(host.includes("window.XStageRankSearch(state.songs,term,200)"),'remote search must reuse ranked catalog search');
assert.ok(host.includes('currentTime:Number.isFinite(ui.player.currentTime)?ui.player.currentTime:0'),'remote status must include playback position');
assert.ok(host.includes('duration:Number.isFinite(duration)?duration:0'),'remote status must include track duration');
assert.ok(remoteHtml.includes('id="remote-now-time"'),'remote queue view must show synchronized track time');
assert.ok(remote.includes("nowTime.textContent=timeLabel(data.currentTime)+' / '+timeLabel(data.duration)"),'remote must render synchronized track time');
assert.ok(remote.includes("status.dataset.state=state"),'remote connection state must have a visible semantic state');
assert.ok(remoteHtml.includes('id="remote-tab-owner"')&&remoteHtml.includes('id="remote-owner-login"'),'mobile remote must have a separate Owner area');
assert.ok(remoteHtml.includes('https://accounts.google.com/gsi/client'),'Owner login must use Google Identity Services');
assert.ok(host.includes("https://openidconnect.googleapis.com/v1/userinfo"),'TV must verify the mobile Google access token against Google userinfo');
assert.ok(host.includes("String(profile.sub)!==String(state.accountSub)"),'Owner access must require the same immutable Google sub as the TV account');
assert.ok(host.includes("entry.role='owner'")&&host.includes("entry.role='guest'"),'TV must enforce Guest/Owner roles server-side');
assert.ok(!host.includes('entry.accessToken'),'TV must not persist the mobile Owner access token');
assert.ok(host.includes('function pausePairing()')&&host.includes('pairingPaused=true'),'Owner must be able to pause new QR pairing');
assert.ok(host.includes("qrPanel.classList.add('pairing-paused')")&&!host.includes("qrCanvas.hidden=true;qrLink.textContent='';qrLink.removeAttribute('href');"),'pausing new pairing must leave the QR permanently visible on TV');
assert.ok(host.includes("queue:state.queue.slice(0,150).map(songSummary)"),'Owner remote must receive the full supported queue, not only the first 50 songs');
assert.ok(css.includes('body.xstage-native-tv #remote-pair-panel.pairing-paused #remote-qr'),'paused permanent QR must stay visible with an inactive visual state');
assert.ok(css.includes('1.0.72 TV cleanup'),'TV cleanup regression guard must exist');
assert.ok(css.includes('body.xstage-native-tv.xstage-ui-v2 #toggle-keyboard')&&css.includes('body.xstage-native-tv.xstage-ui-v2 #mobile-keyboard-toggle'),'TV must explicitly hide every keyboard icon');
assert.ok(css.includes('body.xstage-native-tv.xstage-ui-v2 #mobile-stage-clock'),'TV must hide the toolbar clock so only one clock remains');
assert.ok(css.includes('body.xstage-native-tv.xstage-ui-v2 .stage .stage-metrics')&&css.includes('display:flex!important')&&css.includes('body.xstage-native-tv.xstage-ui-v2 #stage-clock')&&css.includes('display:block!important'),'TV must keep exactly one visible stage clock at the top-right');
assert.ok(css.includes('body.xstage-native-tv #remote-pair-panel{\n  top:clamp(62px,8.4vh,82px)!important'),'permanent QR must be positioned below the top-right clock without overlap');
assert.ok(css.includes('body.xstage-native-tv #remote-pair-panel .remote-pair-top{\n  display:none!important'),'TV QR must not show a verbose heading');
assert.ok(host.includes("status(nativeTvMode?'รีโมทมือถือ':'สแกน QR แล้วรออนุมัติบนจอ')"),'TV QR label must be short and identify it only as the mobile remote');
assert.ok(host.includes("status(nativeTvMode?'รีโมทมือถือ · พัก':'QR แสดงอยู่ · พักรับผู้ใช้ใหม่ชั่วคราว · ผู้ใช้เดิมยังควบคุมได้')"),'paused TV QR label must remain short');
assert.ok(remoteHtml.includes('id="owner-update"'),'Owner remote must own the APK update control when TV is display-only');
assert.ok(host.includes('session.secret=randomSecret()'),'resuming QR pairing must rotate the pairing secret');
assert.ok(host.includes("pairingPaused=true")&&host.includes("if(session!==active||pairingPaused){conn.close();return;}")&&!host.includes("for(const entry of active.connections.values())try{entry.conn.close();}catch{}\n    try{active.peer?.destroy();}catch{}\n    qrApprove.hidden=true;qrReject.hidden=true;hideFullscreenConfirm();\n    qrLink.textContent='';qrLink.removeAttribute('href');qrCanvas.hidden=true;\n    qrEnd.textContent='สร้าง QR ใหม่';pairingPaused=false;status('ปิดการเชื่อมต่อรีโมทแล้ว');\n  }\n  function pausePairing()"),'pausing QR must reject only new pairings without closing existing remotes');
assert.ok(remoteHtml.includes('id="owner-qr-pause"')&&remoteHtml.includes('id="owner-qr-resume"'),'Owner remote must expose QR pause/resume controls');
assert.ok(remote.includes("'queue-play'")&&remote.includes("'queue-move'")&&remote.includes("'queue-remove'"),'Owner remote must provide play/reorder/remove controls for every queued song');
assert.ok(host.includes("action==='queue-play'")&&host.includes("action==='queue-move'")&&host.includes("action==='queue-remove'"),'TV host must enforce Owner queue operations directly');
assert.ok(!host.includes("else if(action==='history')clickHost('pc-history')"),'Owner history must return to mobile instead of opening a hidden TV dialog');
assert.ok(host.includes("platform:nativeTvMode?'android-tv':'web'"),'remote status must identify Android TV so unsupported controls can be disabled');
assert.ok(remoteHtml.includes('id="owner-stage-pop"')&&remote.includes("stagePop.disabled=androidTv"),'second-screen control must be disabled on Android TV instead of appearing broken');
assert.ok(host.includes("window.XStageAndroid.installAvailableUpdate()"),'Owner update action must invoke the native APK updater directly on Android TV');
assert.ok(remoteHtml.includes('https://accounts.google.com/gsi/client" defer'),'Owner Google login script must load deterministically before the remote UI');
assert.ok(remoteHtml.includes('id="owner-background"')&&remoteHtml.includes('id="owner-brand-theme"')&&remoteHtml.includes('id="owner-lyric-scale"')&&remoteHtml.includes('id="owner-lyric-color"'),'visual/lyric settings removed from TV must live on Owner remote');
assert.ok(remoteHtml.includes('id="owner-eq-preset"')&&remoteHtml.includes('id="owner-eq-state"'),'EQ control and native/EQ state must live on Owner remote');
assert.ok(pc.includes('function nativeAndroidTvAudioMode()'),'audio code must distinguish Android TV APK from PC Web');
assert.ok(pc.includes("if(nativeAndroidTvAudioMode())return true;")&&pc.includes("if(!ensureEqAudio())return false;"),'Android TV must keep native audio by default while PC Web keeps the existing WebAudio/EQ path');
assert.ok(pc.includes("window.XStageEnableEqPreset=async function")&&pc.includes("if(nativeAndroidTvAudioMode())return false;"),'Android APK EQ must never activate, including from the Owner remote');
assert.ok(pc.includes("window.XStageEqIsActive=()=>!nativeAndroidTvAudioMode()&&!!eqContext"),'Owner EQ status must report inactive whenever the native Android audio bypass is engaged');
assert.ok(app.includes("player.preservesPitch=true"),'playback must preserve pitch when the browser supports it');
assert.ok(singerStage.includes('id="track-time"'),'separate singer screen must show playback time');
assert.ok(singerStage.includes("document.querySelector('#play-state').textContent=e.data.playing?'กำลังเล่น':'พัก'"),'separate singer screen must show play/pause state');
assert.ok(pc.includes('duration:Number.isFinite(audio.duration)?audio.duration:Number(state.current?.duration)||0'),'main stage must send duration to singer screen');
assert.ok(mobile.includes("$('stage-tools-toggle')?.setAttribute('aria-expanded',String(open))"),'canonical utilities menu state must stay synchronized');

assert.ok(index.includes('class="stage-brand-lockup"'),'professional stage brand lockup must exist');
assert.ok(!index.includes('class="stage-hero-name"'),'obsolete hero markup must stay removed');
for(const legacy of ['stage-hero-emblem','stage-hero-x','stage-hero-mic','stage-hero-name','stage-hero-karaoke','stage-hero-online'])
  assert.ok(!css.includes(legacy),'obsolete '+legacy+' CSS must stay removed');
assert.ok(css.includes('.stage.playing .stage-brand-lockup'),'playing brand priority rule must exist');
assert.ok(css.includes('font-size:22px!important'),'desktop karaoke search text must stay large');
assert.ok(css.includes('font-size:20px!important'),'touch karaoke search text must stay large');

let braces=0;
for(const ch of css){if(ch==='{')braces++;else if(ch==='}')braces--;}
assert.equal(braces,0,'xstage-ux.css braces must balance');


const releaseMatch=config.match(/XSTAGE_RELEASE\s*=\s*\{\s*version:\s*'([^']+)',\s*build:\s*(\d+)\s*\}/);
assert.ok(releaseMatch,'config release metadata must exist');
assert.equal(version.version,releaseMatch[1],'version.json version must match config');
assert.equal(Number(version.build),Number(releaseMatch[2]),'version.json build must match config');
assert.equal(pkg.version,version.version,'package version must match release');
const localAssetVersions=[...index.matchAll(/(?:src|href)="([^"]+)\?v=(\d+)(?:-[\w-]+)?"/g)]
  .map(match=>({asset:match[1],build:Number(match[2])}));
assert.ok(localAssetVersions.length>0,'karaoke page must version its local assets');
assert.ok(localAssetVersions.every(item=>item.build>=Number(version.build)),
  'asset cache versions must not fall behind the published release build');
// Individual scripts intentionally get newer cache keys when a hotfix ships
// without changing the whole product release/version.json.
for(const asset of ['app.js','browser-midi.js','midi-pro-engine.js','ios-midi-audio.js'])
  assert.ok(localAssetVersions.some(item=>item.asset===asset),
    'iPhone MIDI playback asset must be versioned: '+asset);

// Shared update contract: unavailable is not the same as latest, and APK installs require integrity metadata.
assert.ok(app.includes("else setStatus('ตรวจสอบเวอร์ชันไม่สำเร็จ"),'web update must report offline or metadata failures');
assert.ok(androidUpdate.includes('sha256.matches("[0-9a-f]{64}")'),'native APK updates must require SHA-256');
assert.ok(androidUpdate.includes('file.matches("X-Stage-Karaoke-Android-v'),'native APK update filenames must be constrained');
assert.ok(androidMain.includes('uri.getPath().equals(XSTAGE_PATH_PREFIX)'),'native JavaScript bridge must limit WebView navigation to the app path');
assert.ok(androidManifest.includes('android:screenOrientation="unspecified"'),'tablet must be allowed to rotate');
const androidPlayMeta=JSON.parse(read('downloads/android-play-latest.json'));
assert.equal(androidPlayMeta.available,false,'Google Play alerts must not advertise an unpublished release');
assert.equal(androidPlayMeta.package,'com.webbasex.xstage','Play metadata must target the production package');
// Google Play is not being published; its version does not track Web/sideload APK.
assert.match(androidPlayMeta.version,/^\d+\.\d+\.\d+$/,'Unpublished Play version metadata must be valid');
assert.ok(Number.isInteger(androidPlayMeta.build)&&androidPlayMeta.build>0,
  'Unpublished Play build metadata must be valid');
assert.ok(androidUpdate.includes('BuildConfig.DEBUG ? fetchLatest() : fetchPlayLatest()'),'test APK and Play updates must use separate channels');
assert.ok(androidUpdate.includes('if (update.playStore)'),'production Android install action must open the Play Store');
assert.ok(androidMain.includes('public boolean usesGooglePlayUpdates()'),'native UI must identify its update channel');
assert.ok(app.includes('if(androidTvNativeBridgeReady())return null;'),'Android must not confuse a web reload with installing an APK');
const windowsUpdateMetadata=JSON.parse(read('downloads/windows-pc-latest.json'));
const windowsSourceManifest=JSON.parse(read('windows-pc/manifest.json'));
// Windows installers have their own release channel; Android/Web may ship a
// hotfix without falsely advertising a Windows installer at the same version.
assert.equal(windowsUpdateMetadata.version,windowsSourceManifest.version,'Windows metadata must match its own Windows source version');
assert.equal(windowsUpdateMetadata.build,windowsSourceManifest.build,'Windows metadata must match its own Windows build');
const windowsUpdateHelper=read('windows-pc/Check-Update.ps1');
const windowsStartupLauncher=read('windows-pc/Start-XStage-With-Updates.ps1');
assert.ok(windowsStartupLauncher.includes("Start-Process -FilePath $executable"),'Windows launcher must start the installed app');
assert.ok(windowsStartupLauncher.includes("'-Install'")&&windowsStartupLauncher.includes("'-Startup'"),'Windows launcher must check and start a verified update automatically');
assert.ok(windowsUpdateHelper.includes('Get-FileHash')&&windowsUpdateHelper.includes('available -ne $true'),'Windows updater may only launch a hash-verified published installer');
assert.equal(windowsUpdateMetadata.available,false,'Windows update metadata must not advertise an unverified installer');
assert.ok(windowsStartupLauncher.includes("[string]$AppPath = ''")&&
          windowsStartupLauncher.includes("Join-Path $PSScriptRoot 'XStageKaraoke.exe'")&&
          windowsStartupLauncher.includes("Test-Path -LiteralPath $candidate"),
          'Windows launcher must search portable/installed paths rather than require D:');
assert.ok(windowsUpdateHelper.includes("if ($CurrentBuild -le 0 -and $CurrentVersion -ne '0.0.0')")&&
          windowsUpdateHelper.includes('ConvertFrom-Json')&&windowsUpdateHelper.includes('$newBuild -gt $CurrentBuild'),
          'Windows updater must resolve installed Build from a matching manifest before comparison');
assert.equal(windowsSourceManifest.source_imported,true,'Verified Windows source must remain imported; installer still requires its own build gate');
assert.equal(windowsSourceManifest.windows_build_verified,false,'Windows unverified build must remain explicitly unverified');
assert.equal(windowsSourceManifest.installer_published,false,'Windows source ZIP is not a published installer');
assert.equal(windowsSourceManifest.status,'SOURCE_IMPORTED_NOT_A_WINDOWS_RELEASE',
  'Windows manifest must distinguish imported source from an unverified installer');
const proRelease=JSON.parse(read('downloads/song-studio-pro-latest.json'));
assert.equal(proRelease.name,'X-Stage Song Studio Pro','only Pro release feed may be advertised');
assert.equal(proRelease.version,'0.1.11');
assert.equal(proRelease.available,false,'Windows Pro EXE must not be advertised without a verified downloadable artifact');
assert.ok(storefrontScript.includes('song-studio-pro-latest.json'));
assert.ok(windowsUpdateHelper.includes('Get-FileHash')&&windowsUpdateHelper.includes('Start-Process'),'Windows updater must verify a downloaded installer before launching it');

// An empty new Drive must never retain orphaned songs from IndexedDB or
// present guest-only instructions to the owner who cleared the library.
const noRootBranch=app.split('if(!roots.length){')[1]?.split('    setSharedLibraryGate(false);')[0]||'';
assert.ok(noRootBranch.includes('state.songs=[]') &&
          noRootBranch.includes('state.shown=[]') &&
          noRootBranch.includes('state.catalogCache.clear()') &&
          noRootBranch.includes('X-Stage Song Studio') &&
          !noRootBranch.includes('if(instant){'),
          'Empty Drive should show a clean catalog and actionable first-upload instructions');

// Newly created XStageSong may be empty or contain SOUNDFONT first. The
// player should stay usable with 0 entries, not throw a missing DB error.
const missingPointerBranch=app.split('if(!pointers.length){')[1]?.split("if(pointers.length!==1)throw")[0]||'';
assert.ok(missingPointerBranch.includes('state.songs=[]') &&
          missingPointerBranch.includes('state.queue=[]') &&
          missingPointerBranch.includes('state.catalogCache.clear()') &&
          missingPointerBranch.includes("ui.songTotal.textContent='0 เพลง'") &&
          missingPointerBranch.includes('setAndroidTvStageAccess(true,account.sub)') &&
          missingPointerBranch.includes('X-Stage Song Studio'),
          'Empty or SoundFont-first XStageSong must show a clean 0-song stage');
assert.ok(app.includes("พบ current.json หลายรายการ · ไม่เลือกฐานเพลงโดยคาดเดา"),
          'Duplicate current pointers must remain an explicit integrity error');

// WEB/APK use the same HTML5 stage. Video must be optional, muted and
// synchronized to the authoritative audio clock, never cover karaoke lyrics.
assert.ok(index.includes('browser-midi.js?v='+version.build),
          'Bundled MIDI renderer must load without a third-party installation');
assert.ok(index.includes('id="xstage-soundfont-select"'),
          'SoundFont selector must be present in the stage menu');
assert.ok(app.includes("window.XStageBrowserMidi.render(midiBytes"),
          'Main player must send MIDI songs through the bundled synthesizer');
assert.ok(index.includes('id="karaoke-video"') &&
          index.includes('playsinline muted preload="metadata"'),
          'WEB and Android stage must have a safe muted video layer');
assert.ok(app.includes('await privateFile(song.video.fileId,token,{signal})') &&
          app.includes('signal?.aborted') &&
          app.includes('function syncSongVideo()') &&
          app.includes('karaokeVideo.playbackRate=player.playbackRate'),
          'Video must load from the private Drive ID and follow audio speed');
assert.match(app,/function clearIdleStage\(message\)\{\s*resetSongVideo\(\)/,
             'Stop, cancel and exhausted queue must release any old video');
assert.ok(app.includes("console.warn('Video unavailable; using verified audio + timed lyrics:") &&
          app.includes('function playable(song) {') &&
          app.includes('getFileId(song?.xsk)') &&
          app.includes('(getFileId(song?.lyrics) && (getFileId(song?.audio) || getFileId(song?.midi)))'),
          'Unsupported MP4 must not prevent original AAC + timed lyrics playback');
assert.ok(style.includes('#karaoke-video[hidden]') &&
          style.includes('.stage:has(#karaoke-video:not([hidden])) #lyrics'),
          'Video must hide when stopped and lyrics must stay above the video');

console.log('X-Stage regression checks passed for '+version.version+' build '+version.build);

assert.ok(index.includes('xstage-native-auth-pending'),'native stage must be locked before first paint');
assert.ok(style.includes('html.xstage-native-auth-pending .app-shell'),'no stage before Drive login');
assert.ok(app.includes('setAndroidTvStageAccess(true,account.sub)'),'only verified Google Drive can unlock stage');
assert.ok(app.includes('if(androidTvNativeBridgeReady())return;\n  const saved=readActiveAuth();'),'native QR login must not be bypassed by stale web credentials');
assert.ok(androidMain.includes('R.drawable.xstage_tv_splash')&&androidMain.includes('public void onLoginScreenReady()'),'native splash must remain until login UI is ready');
assert.ok(androidGradle.includes('splashFile.bytes = logoSource.bytes'),'the exact uploaded logo bytes must become native splash');
assert.ok(singerStage.includes('class="stage-official-banner"'),'separate singer stage must use one original image');

const stageParityStart=css.lastIndexOf('/* v1.0.91: Android TV stage shares the WEB stage design exactly.');
assert.ok(stageParityStart>0,'shared WEB / Android TV stage parity rules must be last');
const stageParity=css.slice(stageParityStart);
assert.ok(!stageParity.includes(':not(.xstage-native-tv)'),'final stage appearance must not diverge between Web and Android TV');
assert.ok(stageParity.includes('top:37%!important')&&stageParity.includes('width:min(72cqw,760px)!important'),'all devices must share the exact stationary Web hero geometry');
assert.ok(stageParity.includes('grid-template-columns:minmax(0,1fr) minmax(0,4fr) minmax(0,1fr)!important'),'both stages must share the same EQ/banner/EQ layout');
assert.ok(stageParity.includes('height:clamp(36px,9cqh,110px)!important'),'live EQ side meters must match Web');
assert.ok(stageParity.includes('#stage-viz-wave{display:none!important}'),'web and TV use the same EQ visualizer placement');
assert.ok(stageParity.includes('z-index:90!important')&&stageParity.includes('z-index:100!important'),'lyrics must be above the banner without blocking controls');
assert.ok(stageParity.includes('.stage:not(.playing) .stage-hero')&&stageParity.includes('.stage.playing .stage-hero'),'TV and Web banners may not move or shrink while singing');
