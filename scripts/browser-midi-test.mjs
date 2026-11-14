import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const source=fs.readFileSync(new URL('../browser-midi.js',import.meta.url),'utf8');
const context={Uint8Array,ArrayBuffer,DataView,TextDecoder,Blob,console};
context.window=context;
context.document={getElementById:()=>null};
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
  createOscillator(){return new StubNode();}
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
const ascii=new TextEncoder().encode('Test Song\nArtist\nC\n\nHI\n');
const cursors=new Uint8Array([0,0,24,0]);
const ncn=runtime.ncnLyrics(ascii,cursors,'A100',parsed.duration);
assert.equal(ncn.title,'Test Song');
assert.equal(ncn.artist,'Artist');
assert.equal(ncn.lines[0].text,'HI');
assert.equal(ncn.lines[0].syllables.length,2);
assert.throws(()=>runtime.ncnLyrics(ascii,new Uint8Array([0,0]),'A100',2),/CUR/);
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
console.log('PASS: self-contained MIDI parsing, NCN LYR/CUR timing, bounded WAV output');
