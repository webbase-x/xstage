/* SoundFont session RAM lifetime, sample memory cap, UI/Android contracts. */
import fs from 'node:fs';
import assert from 'node:assert/strict';
import vm from 'node:vm';

const read=path=>fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const midi=read('browser-midi.js'),memory=read('memory-budget.js'),
  app=read('app.js'),html=read('karaoke.html'),css=read('xstage-ux.css'),
  android=read('android-tv/app/src/main/java/com/webbasex/xstage/MainActivity.java');
const ctx={navigator:{deviceMemory:2,userAgent:'Android'},
  performance:{memory:{usedJSHeapSize:100,jsHeapSizeLimit:2000}},
  addEventListener:()=>{},dispatchEvent:()=>{},
  TextDecoder,TextEncoder,Uint8Array,DataView,Blob,console,
  document:{getElementById:()=>null}};
ctx.window=ctx;
vm.runInNewContext(memory,ctx);
vm.runInNewContext(midi,ctx);
const info=ctx.XStageBrowserMidi.fontStatus();
assert.equal(info.loaded,false);
assert.equal(info.fileBytes,0);
assert.equal(ctx.XStageMemory.plan().queueLimit,2);
assert.ok(midi.includes("fontCache?.bytes===fontBytes&&fontCache.parsed"),
  'Selected SF2/SF3 must be parsed only once and reused for later songs');
assert.ok(midi.includes("font.cacheBytes+weight>limit")&&
  midi.includes("font.cacheBytes-=removed.length*removed.numberOfChannels*4"),
  'Decoded AudioBuffer samples must have a hard memory budget');
assert.ok(midi.includes("fontStatusChanged()")&&
  midi.includes("xstage:font-memory"),
  'SoundFont loaded/sample-change events must update UI');
assert.ok(midi.includes('BUILTIN_GM_ID')&&
  midi.includes('TimGM6mb.sf2')&&
  midi.includes('selected===BUILTIN_GM_ID')&&
  midi.includes('validateFontContainer(bytes)')&&
  midi.includes('fontCache.parsed=parseFont(fontBytes)'),
  'GM SoundFont must validate header quickly and parse samples on demand');
assert.ok(midi.includes('Number(option.dataset.size)')&&
  midi.includes('gmCandidates'),
  'Only compatible GM banks should be selected automatically from private Drive');
assert.ok(midi.includes("native?.lowMemory"),
  'Do not allocate a large font when Android reports low system RAM');
assert.ok(app.includes("state.activeBlobBytes=audio?.size||0")&&
  app.includes("state.activeVideoBytes=data.size"),
  'Active audio and separate video must count against queue memory budget');
assert.ok(app.includes("state.medleyCache=null;")&&
  app.includes("state.medleyPrefetch?.controller?.abort()"),
  'Medley speculative media must be releasable');
assert.ok(app.includes("state.queuePreloadSkipped.clear()")&&
  app.includes("releaseFinishedMedia()"),
  'Queue cleanup must release played and canceled entries');
assert.ok(html.includes('id="xstage-font-memory"')&&
  html.includes('id="xstage-queue-memory"')&&
  html.includes('memory-budget.js?v='),
  'Memory state must be visible in the karaoke UI');
assert.ok(css.includes('.xstage-memory-indicator[data-level="high"]')&&
  css.includes('.xstage-memory-indicator[data-level="medium"]'),
  'Memory indicator must use green/amber/red pressure colors');
assert.ok(android.includes('public String memorySnapshot()')&&
  android.includes('manager.getMemoryInfo(info)'),
  'Native Android WebView must expose measured system RAM');
console.log('PASS: SoundFont parsed/session cache, bounded SF samples, memory-colored UI, Android RAM and active video accounting');
