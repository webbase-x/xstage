import assert from 'node:assert/strict';
import fs from 'node:fs';

const read = path => fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const meter = read('native-audio-meter.js');
const main = read('pc-extensions.js');
const remote = read('remote.js');
const host = read('stage-controls.js');
const page = read('index.html');
const css = read('xstage-ux.css');

assert.ok(page.includes('native-audio-meter.js?v='),'native Android meter must be loaded from live Web UI');
assert.ok(main.includes('if(nativeAndroidTvAudioMode())return false;'),'native APK must block EQ graph creation');
assert.ok(main.includes("['android-tv','android-tablet']"),'both TV and tablet APK must bypass EQ');
assert.ok(!/\b(?:context|ctx)\.createMediaElementSource\s*\(/.test(meter),
  'meter must never redirect the HTMLMediaElement into Web Audio');
assert.ok(meter.includes('player.captureStream()'),'only media capture may feed the visual meter');
assert.ok(meter.includes('mute.gain.value=0'),'the meter output must always be silent');
assert.ok(host.includes('nativeAudioDirect:!!window.XStageNativeAudioBypass'),'remote must receive native audio bypass state');
assert.ok(host.includes('Android APK ใช้เสียงตรง · EQ ปิดถาวร'),'Owner EQ controls must be rejected on native APK');
assert.ok(remote.includes("eqSelect.disabled=direct"),'Owner remote must disable EQ on native APK');
assert.ok(css.includes('html body.xstage-native-tv.xstage-native-audio-direct.xstage-ui-v2 .stage .stage-hero #stage-viz-right'),
  'native TV must restore the right EQ meter beside the single banner');
assert.ok(meter.includes('const rightCanvas=document.getElementById(\'stage-viz-right\')'),
  'native meter must render on both physical EQ side canvases');
assert.ok(meter.includes('view.mirror?LEVELS-1-i:i'),
  'right meter must mirror real measured FFT bins, not play a fake animation');

function fakeEnvironment({native=true,captureSupported=true}={}){
  const listeners=new Map(),events=new Map(),edges=[],frames=[],changes=[];
  let stopCount=0,contexts=0,mediaElementGraph=0;
  const player={
    src:'blob:example',paused:false,ended:false,muted:false,volume:1,
    addEventListener:(event,fn)=>listeners.set(event,fn),
  };
  if(captureSupported)player.captureStream=()=>({
    getAudioTracks:()=>[{}],
    getTracks:()=>[{stop:()=>{stopCount++;}}]
  });
  const scene={append(node){changes.push(node)}};
  const stage={
    dataset:{},
    style:{setProperty(name,value){events.set(name,value);}},
    querySelector:()=>scene
  };
  const drawing=side=>({
    globalAlpha:1,
    clearRect(){},createLinearGradient(){return {addColorStop(){}};},
    fillRect(){events.set(side+'-bars',(events.get(side+'-bars')||0)+1);}
  });
  const canvas={width:320,height:80,getContext:()=>drawing('left'),
    getBoundingClientRect:()=>({width:320,height:80})};
  const rightCanvas={width:320,height:80,getContext:()=>drawing('right'),
    getBoundingClientRect:()=>({width:320,height:80})};
  const document={
    body:{classList:{add(name){events.set('class',name);}}},
    getElementById:id=>({player,stage,'stage-viz-left':canvas,'stage-viz-right':rightCanvas}[id]||null),
    createElement:()=>({className:'',textContent:'',setAttribute(){}}),
    addEventListener:(type,fn)=>{}
  };
  class GraphNode{
    constructor(kind){this.kind=kind;}
    connect(other){edges.push([this.kind,other.kind||'destination']);return other;}
    disconnect(){}
  }
  class FakeAudioContext{
    constructor(){contexts++;this.state='suspended';this.sampleRate=48000;this.destination=new GraphNode('destination');}
    createMediaElementSource(){mediaElementGraph++;throw Error('native media redirection is forbidden');}
    createMediaStreamSource(){return new GraphNode('capture-stream');}
    createAnalyser(){
      const n=new GraphNode('fft');
      n.frequencyBinCount=1024;n.fftSize=2048;
      n.getByteFrequencyData=d=>d.fill(110);
      return n;
    }
    createGain(){const n=new GraphNode('silent-gain');n.gain={value:1};return n;}
    resume(){this.state='running';return Promise.resolve();}
    close(){this.state='closed';return Promise.resolve();}
  }
  const window={AudioContext:FakeAudioContext,devicePixelRatio:1,
    addEventListener(){},
    XStageAndroid:native?{getAppVersion:()=> '1.0.79'}:undefined};
  const run=new Function('window','document','location','requestAnimationFrame',
    'cancelAnimationFrame','setTimeout','clearTimeout',meter);
  run(window,document,{search:''},fn=>{frames.push(fn);return frames.length},()=>{},()=>0,()=>{});
  return {window,player,stage,edges,events,frames,
    emit:event=>listeners.get(event)?.(),
    contexts:()=>contexts,mediaElementGraph:()=>mediaElementGraph,stops:()=>stopCount};
}

{
  const t=fakeEnvironment();
  t.emit('playing');
  assert.equal(t.contexts(),1,'meter makes one independent AudioContext for visualization');
  assert.equal(t.mediaElementGraph(),0,'native audio stays on player direct path');
  assert.deepEqual(t.edges,[['capture-stream','fft'],['fft','silent-gain'],['silent-gain','destination']]);
  assert.equal(t.window.XStageNativeMeterStatus().silentGain,true,'speaker-connected meter is exactly zero gain');
  t.frames.shift()(50);
  assert.equal(t.events.get('left-bars'),28,'left side renders 28 real FFT bands');
  assert.equal(t.events.get('right-bars'),28,'right side mirrors the same live 28 FFT bands');
  assert.equal(t.stage.dataset.nativeMeter,'active');
  t.emit('loadstart');
  assert.equal(t.stops(),1,'capture tracks are discarded when the song changes');
  assert.equal(t.window.XStageNativeMeterStatus().active,false);
}
{
  const t=fakeEnvironment({captureSupported:false});
  t.emit('playing');
  assert.equal(t.contexts(),0,'unsupported WebView must NOT fallback to media-element redirection');
  assert.equal(t.stage.dataset.nativeMeter,'unsupported','unsupported meter must give clear status');
  assert.equal(t.mediaElementGraph(),0);
}
{
  const t=fakeEnvironment({native:false});
  t.emit('playing');
  assert.equal(t.contexts(),0,'ordinary Web app must not open a separate meter context');
  assert.equal(t.window.XStageNativeMeterStatus,undefined);
}
console.log('Android direct audio / Web-identical dual-sided spectrum: 3 behavioral cases and mirrored 28-band FFT without rerouting speaker audio passed');
