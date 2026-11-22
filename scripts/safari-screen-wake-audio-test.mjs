import assert from 'node:assert/strict';
import fs from 'node:fs';
const read=path=>fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const app=read('app.js');
const pro=read('midi-pro-engine.js');
const fallback=read('browser-midi.js');
const ios=read('ios-midi-audio.js');
const html=read('karaoke.html');
const start=app.indexOf('// Safari can suspend a MIDI AudioContext / MediaStream relay');
const end=app.indexOf("\nwindow.addEventListener('xstage-audio-interrupted'",start);
assert.ok(start>0&&end>start,'Safari screen-lock recovery functions must be present');
const code=app.slice(start,end);
function setup({midi=true,recover=true}={}){
  const song={id:1},listeners=new Map(),messages=[],timers=[];
  const state={current:song,loading:false,userPaused:false,userStopped:false,
    resumeAfterInterruption:false,requestId:7};
  const player={paused:false,currentTime:42,src:'midi:live'};
  const midiTransport={active:midi};
  let engineCalls=0,playCalls=0,snapshotCalls=0;
  const window={XStageBrowserMidi:{unlockAudio:async()=>true}};
  const document={hidden:false,addEventListener:(name,listener)=>listeners.set(name,listener)};
  const engine={async resumeAudio(){engineCalls++;return recover;}};
  state.liveMidiPlayback=engine;
  const factory=new Function('state','player','midiTransport','window','document',
    'nativeAudioFocusBlocked','savePlaybackResumeState','setPlayStatus','updateTransport',
    'resumePlaybackFromSystem','setTimeout','console',code+
    '\nreturn {saveScreenSleepPlaybackIntent,mayRestoreScreenAudio,recoverScreenAudio,tryRecoverInterruptedPlayback};');
  const api=factory(state,player,midiTransport,window,document,false,
    ()=>snapshotCalls++,message=>messages.push(message),()=>{},
    async()=>{playCalls++;player.paused=false;return recover;},
    fn=>{timers.push(fn);return timers.length},console);
  return {api,state,player,document,listeners,timers,messages,
    engineCalls:()=>engineCalls,playCalls:()=>playCalls,snapshotCalls:()=>snapshotCalls};
}
{
  const t=setup();
  t.document.hidden=true;
  t.api.saveScreenSleepPlaybackIntent();
  assert.equal(t.snapshotCalls(),1,'Hide must persist current song/time');
  t.document.hidden=false;
  assert.equal(await t.api.recoverScreenAudio(),true,'Wake should restore existing MIDI output');
  assert.equal(t.engineCalls(),1,'MIDI AudioContext should be resumed in place');
  assert.equal(t.playCalls(),0,'Do not restart an already-playing virtual MIDI transport');
  assert.equal(t.player.currentTime,42,'Preserve the exact song position on wake');
  assert.equal(t.state.resumeAfterInterruption,false);
}
{
  let allowed=false;
  const t=setup({recover:false});
  t.document.hidden=true;t.api.saveScreenSleepPlaybackIntent();t.document.hidden=false;
  assert.equal(await t.api.recoverScreenAudio(),false,'Autoplay denial must be reported');
  assert.equal(t.state.resumeAfterInterruption,true,'Blocked output must remain resumable');
  assert.match(t.messages.at(-1),/แตะ ▶/);
  t.state.userPaused=true;
  assert.equal(await t.api.recoverScreenAudio(),false,'Explicit pause prevents auto restart');
  assert.equal(t.engineCalls(),1,'Manual pause must suppress additional recovery attempts');
  t.state.userPaused=false;
  assert.equal(await t.api.recoverScreenAudio(),false,'Still blocked until user permits playback');
  assert.equal(t.engineCalls(),2);
}
{
  const t=setup({midi:false});
  t.document.hidden=true;t.api.saveScreenSleepPlaybackIntent();
  t.player.paused=true;t.state.resumeAfterInterruption=true;
  t.document.hidden=false;
  assert.equal(await t.api.recoverScreenAudio(),true,'Resume a paused HTML audio stream');
  assert.equal(t.playCalls(),1,'Only a genuinely paused transport calls play');
  assert.equal(t.player.currentTime,42,'Resume must not seek to zero');
}
{
  const t=setup();
  t.state.userPaused=true;
  t.document.hidden=true;t.api.saveScreenSleepPlaybackIntent();
  assert.equal(t.snapshotCalls(),0,'Manually paused songs cannot capture a playing intent');
  t.document.hidden=false;
  assert.equal(await t.api.recoverScreenAudio(),false);
  assert.equal(t.engineCalls(),0);
}
{
  const t=setup();
  t.document.hidden=true;t.api.saveScreenSleepPlaybackIntent();
  t.document.hidden=false;
  t.api.tryRecoverInterruptedPlayback();
  assert.equal(t.timers.length,1,'Focus/visibility recovery must be deferred once');
  await t.timers.shift()();
  await Promise.resolve();
  assert.equal(t.engineCalls(),1,'Deferred wake resumes the audio engine');
}
assert.ok(app.includes("window.addEventListener('pagehide',saveScreenSleepPlaybackIntent)"),
  'Safari pagehide must preserve playing intent');
assert.ok(app.includes("document.addEventListener('pointerdown'"),
  'An autoplay-blocked Safari tab must recover on an allowed user gesture');
assert.ok(pro.includes('async resumeAudio()')&&fallback.includes('async resumeAudio()'),
  'Both professional and fallback SoundFont engines must restore audio context');
assert.ok(ios.includes('async resume(){'),'The existing iPhone relay must support wake recovery');
assert.ok(html.includes('ios-midi-audio.js?v='),'iPhone media output script must be loaded');
console.log('PASS: iPhone screen lock wake, output context resume, paused media, manual pause, denied audio and gesture fallback');
