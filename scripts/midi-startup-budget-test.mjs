import fs from 'node:fs';
import assert from 'node:assert/strict';

// Startup should never await an arbitrarily slow SoundFont or AudioWorklet
// before starting the MIDI transport on mobile. The sound bank upgrades live.
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
assert.equal(first.bytes,null,'Slow bank must not hold the start button');
assert.ok(first.pending,'Late SoundFont should remain eligible to upgrade');
const bank=Uint8Array.of(1,2,3);
completeFont(bank);
assert.equal(await first.pending,bank,'Completed sound bank must be offered for live upgrade');
settings.window.XStageBrowserMidi.fontStatus=()=>({selectedId:''});
const noBank=await getStartupSoundFont('token',new AbortController().signal);
assert.deepEqual({bytes:noBank.bytes,pending:noBank.pending},
  {bytes:null,pending:null},'No selected bank should start MIDI immediately');
assert.ok(source.includes('void upgradeWhenReady(lateEngine)'),
  'Expensive synthesizer prep must upgrade after startup, never block indefinitely');
assert.ok(source.includes('void lateFontPromise.then(bytes=>'),
  'Late SoundFonts must upgrade the playing song');
assert.ok(source.includes('state.liveMidiPlayback=updated'),
  'Upgrade must replace the synth without replacing the current song');
const fontSource=fs.readFileSync(new URL('../browser-midi.js',import.meta.url),'utf8');
assert.ok(fontSource.includes('validateFontContainer(bytes)'),
  'SoundFont loading must validate RIFF without parsing full sample data on UI thread');
console.log('PASS: iPhone bounded MIDI start, deferred bank upgrade and no SoundFont main-thread parsing');
