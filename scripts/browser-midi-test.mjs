import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const source=fs.readFileSync(new URL('../browser-midi.js',import.meta.url),'utf8');
const context={Uint8Array,ArrayBuffer,DataView,TextDecoder,Blob,console,setTimeout};
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
assert.equal(rendered.notes.length,1,'MIDI render exports visible on-stage piano timing');
assert.equal(rendered.notes[0].key,60);
assert.equal(rendered.notes[0].channel,0);
assert.equal(rendered.notes[0].start,0);
assert.ok(Math.abs(rendered.notes[0].end-.5)<1e-8);
const transpose=await runtime.render(file,{transpose:2});
assert.equal(transpose.notes[0].key,62,'Transpose moves sounding key by 2 semitones');
assert.equal(transpose.notes[0].start,0,'Transpose must not change timestamp');
assert.equal(transpose.notes[0].end,.5,'Transpose must not change note duration');
const defaults=Array.from({length:16},()=>({gain:1,mute:false,solo:false}));
const mute=defaults.map(x=>({...x}));mute[0].mute=true;
const silent=await runtime.render(file,{channels:mute});
assert.equal(silent.notes.length,0,'Channel mute must remove notes from output');
const low=defaults.map(x=>({...x}));low[0].gain=.3;
const transformed=runtime.transformNotes(parsed.notes,{transpose:-3,channels:low});
assert.equal(transformed[0].key,57);
assert.ok(Math.abs(transformed[0].level-parsed.notes[0].level*.3)<1e-9);
const solo=defaults.map(x=>({...x}));solo[1].solo=true;
assert.equal(runtime.transformNotes(parsed.notes,{channels:solo}).length,0,
  'Solo another channel must silence channel 1');
assert.throws(()=>runtime.transformNotes(parsed.notes,{transpose:13}),/Transpose/);
assert.throws(()=>runtime.transformNotes(parsed.notes,{channels:[{}]}),/16/);
const drum=runtime.transformNotes([{key:38,start:0,end:1,channel:9,level:1}],{transpose:7});
assert.equal(drum[0].key,38,'GM percussion channel 10 must keep original drum key');
const wave=new Uint8Array(await rendered.audio.slice(0,44).arrayBuffer());
assert.equal(String.fromCharCode(...wave.subarray(0,4)),'RIFF');
assert.equal(String.fromCharCode(...wave.subarray(8,12)),'WAVE');
assert.ok(rendered.audio.size>44);
console.log('PASS: self-contained MIDI parsing, NCN LYR/CUR timing, bounded WAV output');
