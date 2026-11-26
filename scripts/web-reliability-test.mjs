import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const read=name=>fs.readFileSync(new URL('../'+name,import.meta.url),'utf8');
const coreSource=read('cloud-import-core.js');
const context={Blob,TextDecoder,TextEncoder,console};
context.window=context;
vm.runInNewContext(coreSource,context,{filename:'cloud-import-core.js'});
const core=context.XStageImportCore;
const aac=header=>{
  const blob=new Blob([Buffer.from(header),Buffer.alloc(2048)]);
  blob.name='test.aac';return blob;
};
for(const signature of [[0xff,0xf0],[0xff,0xf1],[0xff,0xf8],[0xff,0xf9],[0x41,0x44,0x49,0x46]]){
  assert.equal(await core.validAudio(aac(signature)),true,'Accept AAC ADTS/ADIF '+signature.join(','));
}
assert.equal(await core.validAudio(aac([0,0,0,0])),false,'Reject malformed AAC');
const solo=core.lrcToJson('[00:01.00]ก่อนดนตรี\n[00:04.00]\n[00:13.00]หลังดนตรี\n','A101');
assert.equal(solo.lines.length,2,'Empty timed cues are not displayed as lyrics');
assert.equal(solo.lines[0].endTime,4,'Solo marker must end previous lyric');
assert.equal(solo.lines[1].startTime,13,'Next verse start preserved');
assert.throws(()=>core.lrcToJson('[00:02.00]\n','A102'),/ไม่มีบรรทัด/);

const app=read('app.js'),apk=read('android-apk-download.js'),midi=read('browser-midi.js'),
  importer=read('cloud-import.js'),meter=read('native-audio-meter.js'),
  pc=read('pc-extensions.js'),stage=read('stage-ui.js'),
  index=read('karaoke.html'),remote=read('stage-controls.js');
for(const [name,source] of [['app',app],['midi',midi],['importer',importer],['meter',meter],
  ['apk',apk],['pc',pc],['stage',stage],['remote',remote],]){
  assert.doesNotThrow(()=>new Function(source),name+' JavaScript must parse');
}
assert.match(app,/controller\?\.abort\(\);\s*\},seconds\*1000/,'Media timeout must abort work');
assert.match(app,/if \(reuseExistingSession && state\.token && state\.accountSub===account\.sub && state\.libraryRootId && !isRetiredDriveRoot\(state\.libraryRootId\)\)/,
  'Same-account refresh must bypass catalog and playback reset');
assert.match(app,/openDrive\(result\.access_token,authId,expiresAt,known\?\.sub\|\|'',true,fullReadGranted\)/,
  'OAuth renewal must reuse the session only for the verified same Google account');
assert.match(app,/await openDrive\(token,id,state\.tokenExpiresAt\);/,'Importer must force catalog reload after publishing');
assert.match(app,/scheduleLyricsDraw/,'Lyrics redraw must be event driven');
assert.doesNotMatch(app,/!lyrics\?\.schemaVersion!==1/,'Dead medley guard must not reappear');
assert.match(midi,/fontRefreshPromise/,'SoundFont selection waits for ongoing refresh');
assert.match(midi,/sequence!==fontRefreshSequence/,'Stale SoundFont results must not overwrite new library');
assert.match(importer,/response\.body\?\.getReader/,'Catalog JSON must be stream bounded');
assert.match(importer,/resumeAfterPicker=false/,'Folder cancel/resume flag must clear');
assert.match(meter,/sampleData=new Uint8Array/,'Meter samples should be allocated once per graph');
assert.match(meter,/cancelAnimationFrame\(frame\)/,'Meter rendering must stop when paused');
assert.match(apk,/X-Stage-Karaoke-Android-TV-v/,'Allow explicitly named Android TV APK');
assert.doesNotMatch(index,/rel="manifest"|pwa-install\.js|sw\.js/,'Web entry must not reference retired PWA assets');
assert.match(pc,/e\.isComposing/,'Do not steal IME composition events');
assert.match(stage,/webkitRequestFullscreen/,'WebKit fullscreen compatibility');
assert.match(index,/id="cloud-import-ios-help"/,'Safari folder picker must explain its iOS support and limitations');
assert.match(app,/requestNativePlaybackAudioFocus/,'Native playback must acquire Audio Focus');
assert.match(importer,/hasRelativePaths/,'Flat file-picker results should identify missing folder hierarchy');
assert.match(index,/<footer class="bottom-bar">[^]*?<\/footer>/,'Stage footer must close correctly');
assert.match(remote,/const nativeTvMode=\(\(\)=>/,'Native TV detection is a Boolean, not a function');

 // Simulate startup metadata outage, reconnect, request coalescing and recovery.
 {
   const handlers={},docHandlers={},warnings=[];
   const link={hidden:true,removeAttribute(key){delete this[key];}};
   let requests=0, pending, aborted=0, timer;
   const browser={
     navigator:{userAgent:'Android'},
     location:{href:'https://example.test/xstage/karaoke.html',search:''},
     document:{hidden:false,getElementById:id=>id==='android-tv-apk-download'?link:null,
       addEventListener:(name,fn)=>{docHandlers[name]=fn;}},
     addEventListener:(name,fn)=>{handlers[name]=fn;},
     URL,URLSearchParams,AbortController,
     setTimeout:fn=>{timer=fn;return 1;},clearTimeout:()=>{},
     console:{warn:(...args)=>warnings.push(args)},
     fetch:(_url,options)=>{
       requests++;
       assert.equal(options.cache,'no-store');
       assert.ok(options.signal);
       return new Promise((resolve,reject)=>{
         options.signal.addEventListener('abort',()=>{aborted++;reject(Error('timeout'));},{once:true});
         pending=resolve;
       });
     }
   };
   browser.window=browser;
   vm.runInNewContext(apk,browser);
   assert.equal(requests,1);
   handlers.online();docHandlers.visibilitychange();
   assert.equal(requests,1,'Reconnect events must not duplicate active requests');
   timer();
   for(let i=0;i<8;i++)await Promise.resolve();
   assert.equal(aborted,1);
   assert.equal(link.hidden,true);
   handlers.online();
   assert.equal(requests,2,'Metadata fetch must recover after startup timeout');
   pending({ok:true,json:async()=>({file:'X-Stage-Karaoke-Android-v1.0.220-build1220.apk',version:'1.0.220',build:1220,sha256:'a'.repeat(64)})});
   for(let i=0;i<12;i++)await Promise.resolve();
   assert.equal(link.hidden,false);
   assert.match(link.href,/downloads\/X-Stage-Karaoke-Android-v1\.0\.220-build1220\.apk$/);
   handlers.online();docHandlers.visibilitychange();
   assert.equal(requests,2,'Healthy metadata must not be refetched on every visibility event');
 }

console.log('PASS: AAC signatures, solo lyric timing, APK reconnect and Web reliability contracts');
