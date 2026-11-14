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
  index=read('index.html'),remote=read('stage-controls.js');
for(const [name,source] of [['app',app],['midi',midi],['importer',importer],['meter',meter],
  ['apk',apk],['pc',pc],['stage',stage],['remote',remote],]){
  assert.doesNotThrow(()=>new Function(source),name+' JavaScript must parse');
}
assert.match(app,/controller\?\.abort\(\);\s*\},seconds\*1000/,'Media timeout must abort work');
assert.match(app,/if \(reuseExistingSession && state\.token && state\.accountSub===account\.sub && state\.libraryRootId\)/,
  'Same-account refresh must bypass catalog and playback reset');
assert.match(app,/openDrive\(result\.access_token,authId,expiresAt,'',true\)/,'OAuth renewal opts into session reuse');
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
console.log('PASS: AAC signatures, solo lyric timing and Web reliability contracts');
