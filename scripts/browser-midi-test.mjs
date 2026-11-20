import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const source=fs.readFileSync(new URL('../browser-midi.js',import.meta.url),'utf8');
const context={Uint8Array,ArrayBuffer,DataView,TextDecoder,Blob,console,setTimeout};
context.window=context;
context.document={getElementById:()=>null};
const oscillatorNodes=[];
class StubNode{
  constructor(){this.gain={value:0,setValueAtTime(){},linearRampToValueAtTime(){},exponentialRampToValueAtTime(){}};
    this.frequency={value:0};}
  connect(){}
  start(){}
  stop(){}
}
context.OfflineAudioContext=class{
  constructor(channels,length,sampleRate){this.length=length;this.rate=sampleRate;this.destination={};}
  createGain(){return new StubNode();}
  createOscillator(){const node=new StubNode();oscillatorNodes.push(node);return node;}
  async startRendering(){
    const data=new Float32Array(this.length);
    return {length:this.length,numberOfChannels:2,sampleRate:this.rate,getChannelData:()=>data};
  }
};
vm.runInNewContext(source,context,{filename:'browser-midi.js'});
const runtime=context.XStageBrowserMidi;
assert.ok(runtime,'Bundled browser MIDI runtime must load without a CDN');
const track=[0,0xc0,0,0,0x90,60,100,0x60,0x80,60,0,0,0xff,0x2f,0];
const header=[77,84,104,100,0,0,0,6,0,0,0,1,0,96];
const file=new Uint8Array([...header,77,84,114,107,0,0,0,track.length,...track]);
const parsed=runtime.parseMidi(file);
assert.equal(parsed.notes.length,1);
assert.equal(parsed.notes[0].key,60);
assert.equal(parsed.notes[0].end,.5);
assert.equal(parsed.duration,1.5);
assert.throws(()=>runtime.parseMidi(new Uint8Array(30)),/MIDI/);
const lyrics=runtime.midiLyrics(parsed,'A100');
assert.equal(lyrics.schemaVersion,1);
assert.equal(lyrics.lines.length,1,'Instrumental MIDI gets an explicit music-only marker');
const ascii=new TextEncoder().encode('Test Song\nArtist\nC\n.\nHI\n');
const cursors=new Uint8Array([0,0,0,0,24,0]); // line marker + H + I
const ncn=runtime.ncnLyrics(ascii,cursors,'A100',parsed);
assert.equal(ncn.title,'Test Song');
assert.equal(ncn.artist,'Artist');
assert.equal(ncn.lines[0].text,'HI');
assert.equal(ncn.lines[0].syllables.length,2);
assert.equal(ncn.lines[0].syllables[1].start,.5,'24 CUR positions = one MIDI quarter');
assert.equal(ncn.metadata.timingComplete,true);
assert.throws(()=>runtime.ncnLyrics(ascii,new Uint8Array([0,0]),'A100',parsed),/LYR\/CUR/);
assert.throws(()=>runtime.ncnLyrics(ascii,cursors,'A100',parsed.duration),/Tempo/);

// Tempo changes must affect NCN lyrics at the SAME MIDI clock as the audio.
const tempoTrack=[0,255,81,3,7,161,32,0,144,60,100,
  131,96,255,81,3,15,66,64,131,96,128,60,0,0,255,47,0];
const tempoMidi=new Uint8Array([77,84,104,100,0,0,0,6,0,0,0,1,1,224,
  77,84,114,107,0,0,0,tempoTrack.length,...tempoTrack]);
const tempoSong=runtime.parseMidi(tempoMidi);
assert.equal(tempoSong.division,480);
assert.equal(tempoSong.tempoMap.length,2);
assert.ok(Math.abs(tempoSong.tempoMap[1].seconds-.5)<1e-9);
assert.ok(Math.abs(tempoSong.duration-2.5)<1e-9);
const titleAndLyrics=new TextEncoder().encode('Song\nArtist\nC\n.\nABCD\n');
// A Thai combining mark uses a *separate CP874 byte* but one displayed glyph.
const lyricsBytes=new Uint8Array([...titleAndLyrics,161,212,162,10]);
const uint16=(...values)=>new Uint8Array(values.flatMap(value=>[value&255,value>>8]));
const timed=uint16(0,0,12,24,48,48,48,48,60);
const actualCues=runtime.ncnLyrics(lyricsBytes,timed,'T100',tempoSong);
assert.equal(actualCues.lines.length,2);
assert.deepEqual(Array.from(actualCues.lines[1].syllables,x=>x.text),['กิ','ข']);
assert.equal(actualCues.lines[0].syllables[3].start,1.5,
  'NCN position 48 must cross the 120-to-60 BPM tempo change');
assert.equal(actualCues.lines[1].syllables[1].start,2,
  'NCN position 60 must use the new 60 BPM tempo');
assert.equal(actualCues.metadata.cursorValues,9);
assert.equal(actualCues.metadata.unusedCursorValues,0);
assert.equal(actualCues.metadata.timingComplete,true);
// Legacy NCN files can contain unused trailing FFFF sentinels and a DOS FF tail.
const legacy=new Uint8Array([...timed,...Array(200).fill(255),255]);
const legacyDoc=runtime.ncnLyrics(lyricsBytes,legacy,'T100',tempoSong);
assert.equal(legacyDoc.metadata.unusedCursorValues,100);
assert.equal(legacyDoc.metadata.timingComplete,true);
assert.equal(legacyDoc.lines.length,2);
assert.equal(legacyDoc.lines[1].text,'กิข');
// The invisible marker is not a glyph; backward historical positions are
// clamped like the PC renderer, not turned into a negative syllable duration.
const backwards=uint16(65535,0,12,6,48,48,48,48,60);
const backwardDoc=runtime.ncnLyrics(lyricsBytes,backwards,'T100',tempoSong);
assert.equal(backwardDoc.lines[0].syllables[2].start,
  backwardDoc.lines[0].syllables[1].start);
assert.ok(backwardDoc.metadata.timingWarnings.some(x=>x.includes('ย้อนกลับ')));
assert.equal(backwardDoc.metadata.timingComplete,true);
// Truncated CUR cannot produce fabricated timestamps; mark import invalid.
const incomplete=runtime.ncnLyrics(lyricsBytes,uint16(0,0,12,24,48,48,48),'T100',tempoSong);
assert.equal(incomplete.metadata.timingComplete,false);
assert.ok(incomplete.metadata.timingWarnings.length);
assert.throws(()=>runtime.ncnLyrics(lyricsBytes,new Uint8Array([0,0,1]),'T100',tempoSong),
  /CUR NCN/);

// A minimal in-memory SF2 preset exercises real RIFF/zone/sample mapping.
const pack=(...chunks)=>Buffer.concat(chunks.map(x=>Buffer.from(x)));
const word=n=>{const b=Buffer.alloc(2);b.writeUInt16LE(n);return b;};
const riffChunk=(name,payload)=>{const n=Buffer.alloc(4);n.writeUInt32LE(payload.length);
  return pack(Buffer.from(name),n,payload,payload.length%2?Buffer.alloc(1):Buffer.alloc(0));};
const list=(name,...children)=>riffChunk('LIST',pack(Buffer.from(name),...children));
const phdr=Buffer.alloc(76);phdr.writeUInt16LE(1,38+24);
const pbag=pack(word(0),word(0),word(1),word(0));
const inst=Buffer.alloc(44);inst.writeUInt16LE(1,22+20);
const shdr=Buffer.alloc(92);shdr.writeUInt32LE(1000,24);shdr.writeUInt32LE(100,28);
shdr.writeUInt32LE(900,32);shdr.writeUInt32LE(22050,36);
shdr[40]=60;shdr.writeUInt16LE(1,44);
const sf2=riffChunk('RIFF',pack(Buffer.from('sfbk'),
  list('INFO',riffChunk('ifil',pack(word(2),word(1)))),
  list('sdta',riffChunk('smpl',Buffer.alloc(2000))),
  list('pdta',riffChunk('phdr',phdr),riffChunk('pbag',pbag),
    riffChunk('pgen',pack(word(41),word(0))),riffChunk('inst',inst),
    riffChunk('ibag',pbag),riffChunk('igen',pack(word(53),word(0))),
    riffChunk('shdr',shdr))));
const font=runtime.parseFont(sf2);
assert.equal(font.find(0,0,60,100).length,1,'SF2 preset must resolve MIDI note to its sample');
assert.equal(font.find(0,0,30,100).length,1,'SF2 without key range must accept all pitches');
assert.throws(()=>runtime.parseFont(new Uint8Array(300)),/SoundFont/);
const rendered=await runtime.render(file);
assert.equal(rendered.audio.type,'audio/wav');
const wave=new Uint8Array(await rendered.audio.slice(0,44).arrayBuffer());
assert.equal(String.fromCharCode(...wave.subarray(0,4)),'RIFF');
assert.equal(String.fromCharCode(...wave.subarray(8,12)),'WAVE');
assert.ok(rendered.audio.size>44);
// Browser-only studio can transpose melody without moving percussion channel 10.
const baseline=oscillatorNodes.length;
await runtime.render(file,{transpose:12});
assert.equal(oscillatorNodes.length,baseline+1);
assert.ok(Math.abs(oscillatorNodes.at(-1).frequency.value/
  oscillatorNodes.at(-2).frequency.value-2)<.001,
  'Transpose +12 must raise MIDI pitch by exactly one octave');
const beforeMute=oscillatorNodes.length;
await runtime.render(file,{channelMutes:[true]});
assert.equal(oscillatorNodes.length,beforeMute,'Muted MIDI channel must not render audio');
await runtime.render(file,{channelVolumes:[0]});
assert.equal(oscillatorNodes.length,beforeMute,'Zero MIDI channel gain must not render audio');
console.log('PASS: self-contained MIDI parsing, NCN LYR/CUR timing, 16-channel mute and transpose');


// Regression: the primary MIDI player must schedule real notes without building
// any WAV. The HTML transport clock is supplied by the app's MIDI transport.
const scheduledNotes=[];
let liveCompressor=null,masterSignal=null;
class LiveGain {
  constructor(){this.gain={value:1,setValueAtTime(value){this.value=value;},linearRampToValueAtTime(value){this.value=value;},exponentialRampToValueAtTime(value){this.value=value;}};}
  connect(node){if(node?.threshold)masterSignal=this;}
  disconnect(){}
}
class LiveSource {
  constructor(){this.frequency={value:440,setValueAtTime(value){this.value=value;}};
    this.playbackRate={value:1};}
  connect(){}disconnect(){}
  start(when){scheduledNotes.push({when,pitch:this.frequency.value,source:this});}
  stop(){} 
}
context.AudioContext=class {
  constructor(){this.currentTime=1;this.destination={};this.state='running';}
  createGain(){return new LiveGain();}
  createOscillator(){return new LiveSource();}
  createDynamicsCompressor(){
    const setting=()=>({value:0});
    liveCompressor={threshold:setting(),knee:setting(),ratio:setting(),
      attack:setting(),release:setting(),connect(){},disconnect(){}};
    return liveCompressor;
  }
  resume(){return Promise.resolve();}
};
context.setInterval=()=>1;
context.clearInterval=()=>{};
assert.equal(runtime.supportsRealtime(),true);
assert.equal(runtime.unlockAudio(),true);
const listeners=new Map();
const transport={
  currentTime:0,paused:false,ended:false,volume:.8,muted:false,playbackRate:1,
  addEventListener(name,fn){if(!listeners.has(name))listeners.set(name,[]);
    listeners.get(name).push(fn);},
  removeEventListener(name,fn){listeners.set(name,(listeners.get(name)||[]).filter(x=>x!==fn));}
};
let semitones=0;
const synth=runtime.playRealtime(transport,file,{getTranspose:()=>semitones});
assert.ok(liveCompressor,'Live MIDI must use one final compressor/limiter');
assert.ok(liveCompressor.threshold.value<=-12,'Limiter threshold must protect headroom');
assert.ok(liveCompressor.ratio.value>=8,'Limiter needs a high compression ratio');
assert.ok(masterSignal.gain.value<=.3,'The master gain must leave mixing headroom');
assert.ok(scheduledNotes.length>0,'Live MIDI must schedule a note without OfflineAudioContext');
const first=scheduledNotes.at(-1).pitch;
semitones=12;
for(const cb of listeners.get('xstage-midi-transpose')||[])cb();
assert.ok(scheduledNotes.at(-1).pitch>first*1.99,
  'Changing the live key must raise the next note by one octave');
synth.dispose();
assert.equal(listeners.get('play')?.length,0,'Live MIDI listeners must be removed on disposal');
assert.equal(typeof runtime.silentClock,'undefined',
  'The bundled MIDI synthesizer must not expose a synthetic WAV clock');
console.log('PASS: real-time MIDI note scheduling, key shift and cleanup without WAV clock');
