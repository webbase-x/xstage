import fs from 'node:fs';
import assert from 'node:assert/strict';

// Font download remains timeboxed while fetching the MIDI file. Before any
// audible note starts, the player must wait for the actual SoundFont and
// professional engine (or use an SF2 sample-based compatibility renderer).
const source=fs.readFileSync(new URL('../app.js',import.meta.url),'utf8');
const begin=source.indexOf('const FAST_FONT_BUDGET_MS=');
const end=source.indexOf('async function prepareXskPlayback(',begin);
assert.ok(begin>0&&end>begin,'Timeboxed SoundFont startup helper exists');
let completeFont;
const slow=new Promise(resolve=>{completeFont=resolve;});
const settings={
  navigator:{userAgent:'Mozilla/5.0 (iPhone; CPU iPhone OS 27_2)'},
  window:{XStageBrowserMidi:{
    fontStatus:()=>({selectedId:'bank-1'}),
    selectedFont:()=>slow
  }},
  setTimeout(callback){queueMicrotask(callback);return 1;},
  clearTimeout(){},
  console
};
const factory=new Function('navigator','window','setTimeout','clearTimeout','console',
  source.slice(begin,end)+'\nreturn {getStartupSoundFont,FAST_FONT_BUDGET_MS};');
const {getStartupSoundFont,FAST_FONT_BUDGET_MS:budget}=factory(...[
  settings.navigator,settings.window,settings.setTimeout,settings.clearTimeout,
  settings.console
]);
assert.ok(budget<=1500,'iPhone should have a short SoundFont startup budget');
const first=await getStartupSoundFont('token',new AbortController().signal);
assert.equal(first.bytes,null,'Slow bank can be deferred while MIDI file downloads');
assert.ok(first.pending,'Pending SoundFont must be preserved for the first-song gate');
const bank=Uint8Array.of(1,2,3);
completeFont(bank);
assert.equal(await first.pending,bank,'Completed SoundFont is available to the first-song gate');
settings.window.XStageBrowserMidi.fontStatus=()=>({selectedId:''});
settings.window.XStageBrowserMidi.selectedFont=async()=>null;
const noBank=await getStartupSoundFont('token',new AbortController().signal);
assert.deepEqual({bytes:noBank.bytes,pending:noBank.pending},
  {bytes:null,pending:null},'An explicitly selected no-SoundFont mode stays available');
// First play regression: a bank selector may still show an empty ID while
// refreshFonts is scanning Drive. Do not interpret that as an 8-bit request.
let refreshed=false;
settings.window.XStageBrowserMidi.selectedFont=async()=>{
  refreshed=true;
  return bank;
};
const refreshedBank=await getStartupSoundFont('token',new AbortController().signal);
assert.equal(refreshedBank.bytes,bank);
assert.equal(refreshed,true,'First startup must query the bank even before selector refresh');

// Exercise the exact production helpers, without browser/audio/network mocks.
const gateFactory=new Function('navigator','window','setTimeout','clearTimeout','console',
  'setPlayStatus','boundedPlaybackTask',source.slice(begin,end)+
  '\nreturn {ensureMidiInstrumentBank,prepareFirstMidiSynth};');
const warnings=[];
const gate=gateFactory(settings.navigator,settings.window,
  (fn,ms)=>{if(ms<5000)queueMicrotask(fn);return 2;},
  ()=>{},console,message=>warnings.push(message),task=>Promise.resolve(task));
const controller=new AbortController();
let completeSlow;
const unresolved=new Promise(resolve=>{completeSlow=resolve;});
let songStarted=false;
const gateResult=gate.ensureMidiInstrumentBank(null,unresolved,'token',controller)
  .then(value=>{songStarted=true;return value;});
await Promise.resolve();
assert.equal(songStarted,false,'The first note must stay silent while the SF2 bank loads');
completeSlow(bank);
assert.equal(await gateResult,bank,'The first song receives real samples, not oscillators');

settings.window.XStageBrowserMidi.fontStatus=()=>({
  selectedId:'builtin:TimGM6mb',warning:'GM bank unavailable'
});
settings.window.XStageBrowserMidi.selectedFont=async()=>null;
await assert.rejects(
  gate.ensureMidiInstrumentBank(null,null,'token',controller),
  /ไม่เริ่มเพลงด้วยเสียง 8-bit/,
  'A failed selected bank must report an error rather than playing chip sounds'
);

settings.window.XStageProMidi={
  available:()=>true,
  prepare:async()=>({dispose(){}})
};
assert.ok(await gate.prepareFirstMidiSynth(Uint8Array.of(1),bank,{}),
  'A ready high-quality synth is used for the first note');
settings.window.XStageProMidi.prepare=async()=>{throw Error('No AudioWorklet');};
assert.equal(await gate.prepareFirstMidiSynth(Uint8Array.of(1),bank,{}),null,
  'If AudioWorklet fails, playback can use loaded SF2 samples, not bare oscillators');

assert.ok(source.includes('liveFontBytes=await ensureMidiInstrumentBank('),
  'The first song must wait for its SoundFont instead of playing oscillators');
assert.ok(source.includes('const professional=await prepareFirstMidiSynth('),
  'Initial playback must await the professional synth before emitting notes');
assert.ok(source.includes('playRealtime(player,liveMidiBytes,midiOptions)'),
  'The compatibility synthesizer must receive the real SoundFont');
assert.ok(!source.includes('...midiOptions,fontBytes:null'),
  'Selected SoundFonts must never be discarded by the fallback');
assert.ok(!source.includes('void upgradeWhenReady(lateEngine)'),
  'Do not play 8-bit audio while waiting to upgrade during the first track');
const fontSource=fs.readFileSync(new URL('../browser-midi.js',import.meta.url),'utf8');
assert.ok(fontSource.includes('validateFontContainer(bytes)'),
  'SoundFont loading must validate RIFF without parsing full sample data on UI thread');
console.log('PASS: font preload remains bounded while downloading MIDI; first audible note uses real bank and synth');
