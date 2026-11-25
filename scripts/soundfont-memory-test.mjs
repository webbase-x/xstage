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
assert.equal(ctx.XStageMemory.plan().queueLimit,1);
assert.ok(midi.includes("fontCache?.bytes===fontBytes&&fontCache.parsed"),
  'Selected SF2/SF3 must be parsed only once and reused for later songs');
assert.ok(midi.includes('warmRealtimeSamples')&&
  midi.includes('await sampleBuffer(font,index,ctx)'),
  'Cold MIDI sample prewarm must happen before the first song');
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

// Exercise the real streaming reader; missing Content-Length must not bypass RAM limits.
const readerStart=midi.indexOf('async function readBoundedFontResponse(');
const readerEnd=midi.indexOf('async function selectedFont(',readerStart);
assert.ok(readerStart>=0&&readerEnd>readerStart);
const readFont=new Function('fail',midi.slice(readerStart,readerEnd)+';return readBoundedFontResponse;')(msg=>{throw Error(msg)});
function streaming(parts,declared=0){
  let i=0,cancelled=false,released=false;
  const reader={async read(){return i<parts.length?{done:false,value:Uint8Array.from(parts[i++])}:{done:true}},async cancel(){cancelled=true},releaseLock(){released=true}};
  return {headers:{get:()=>String(declared)},body:{getReader:()=>reader,async cancel(){cancelled=true}},get cancelled(){return cancelled},get released(){return released}};
}
const exact=streaming([[1,2],[3,4]]);
assert.deepEqual(await readFont(exact,8,4),Uint8Array.of(1,2,3,4));assert.ok(exact.released);
const oversized=streaming([[1,2],[3,4]]);
await assert.rejects(readFont(oversized,3),/เกินขอบเขต/);assert.ok(oversized.cancelled&&oversized.released);
const short=streaming([[1,2]]);
await assert.rejects(readFont(short,8,4),/ไม่ครบ/);assert.ok(short.cancelled);
const mismatch=streaming([[1,2]],2);
await assert.rejects(readFont(mismatch,8,4),/ไม่ตรง/);assert.ok(mismatch.cancelled);
let ticks=0;const interrupted=streaming([[1,2],[3,4]]);
await assert.rejects(readFont(interrupted,8,4,()=>{if(++ticks===3)throw Error('pause')}),/pause/);assert.ok(interrupted.cancelled&&interrupted.released);
console.log('PASS: bounded SoundFont streaming, exact size, cancellation and truncated payload');
