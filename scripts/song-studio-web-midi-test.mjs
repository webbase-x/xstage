import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const read=path=>fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const context={Uint8Array,ArrayBuffer,DataView,TextDecoder,Blob,console,setTimeout};
context.window=context;
context.document={getElementById:()=>null};
vm.runInNewContext(read('browser-midi.js'),context,{filename:'browser-midi.js'});
vm.runInNewContext(read('studio/web-midi-core.js'),context,{filename:'web-midi-core.js'});
const midi=context.XStageBrowserMidi,core=context.XStageStudioMidiCore;
assert.ok(midi&&core,'Web studio must reuse the same bundled MIDI/NCN parser as karaoke');
assert.equal(core.groupIdentity('MIDI/NCN/Song','02386.mid'),
  core.groupIdentity('MIDI/NCN/Lyrics','02386.lyr'));
assert.equal(core.groupIdentity('MIDI/NCN/Cursor','02386.cur'),
  core.groupIdentity('MIDI/NCN/Song','02386.mid'));
assert.notEqual(core.groupIdentity('A/NCN/Song','00001.mid'),
  core.groupIdentity('B/NCN/Song','00001.mid'),'Unrelated song folders must never collide');
assert.equal(core.companionState({midi:{name:'02386.mid'},lyr:{},cur:{}}).kind,'NCN');
assert.equal(core.companionState({midi:{name:'02386.mid'},lyr:{}}).complete,false);
assert.equal(core.companionState({midi:{name:'02386.ncn'}}).complete,false);
const track=[0,0xc0,0,0,0x90,60,100,0x60,0x80,60,0,0,0xff,0x2f,0];
const midiBytes=new Uint8Array([77,84,104,100,0,0,0,6,0,0,0,1,0,96,
  77,84,114,107,0,0,0,track.length,...track]);
const lyrBytes=new TextEncoder().encode('Test Song\nArtist\nC\n.\nHI\n');
const cursorBytes=new Uint8Array([0,0,0,0,24,0]);
const blob=(name,bytes)=>({name,size:bytes.length,
  arrayBuffer:async()=>bytes.slice().buffer});
const song={name:'NCN001',midi:blob('NCN001.mid',midiBytes),
  lyr:blob('NCN001.lyr',lyrBytes),cur:blob('NCN001.cur',cursorBytes),
  lyricsText:null,editedLyrics:false};
const info=await core.inspectSong(song,midi);
assert.equal(info.kind,'NCN');
assert.equal(info.safe,true);
assert.equal(info.safeLyrics,true);
assert.equal(info.document.lines[0].text,'HI');
assert.equal(info.document.lines[0].syllables[1].start,.5);
assert.match(info.lrc,/\[00:00.00\]HI/);
const original=Array.from(midiBytes);
const reversed={...song,cur:blob('NCN001.cur',new Uint8Array([0,0,24,0,0,0]))};
const warning=await core.inspectSong(reversed,midi);
assert.equal(warning.safe,false,'Backwards CUR may be previewed but must not be auto-exported');
assert.match(warning.warning,/CUR/);
await assert.rejects(core.inspectSong({...song,cur:null},midi),/MID \+ LYR \+ CUR/);
await assert.rejects(core.inspectSong({...song,cur:blob('NCN001.cur',new Uint8Array([0,0]))},midi),
  /LYR\/CUR/);
const instrumental=await core.inspectSong({name:'MIDI1',midi:blob('MIDI1.kar',midiBytes)},midi);
assert.equal(instrumental.kind,'KAR');
assert.equal(instrumental.lrc,'','Instrumental marker must not become fabricated LRC');
assert.equal(core.documentToLrc({lines:[{startTime:1.25,text:'ทดสอบ'}]}),'[00:01.25]ทดสอบ');
const validLrc=core.lrcToDocument('[00:01.20]ท่อนแรก\n[00:03.50]ท่อนสอง','T1','LRC');
assert.equal(validLrc.lines.length,2);
assert.equal(validLrc.lines[0].endTime,3.5);
assert.throws(()=>core.lrcToDocument('[00:03.00]หลัง\n[00:02.00]ก่อน','T1'),/ย้อนกลับ/);
assert.throws(()=>core.lrcToDocument('สวัสดี','T1'),/ไม่มีเนื้อร้อง/);
assert.equal(core.assessResources(120,0,8).ok,true);
assert.equal(core.assessResources(900,256*1048576,2).ok,false);
assert.equal(core.assessResources(901,0,8).ok,false);

// Exercise production asset builder with real NCN input bytes and format.
const web=read('studio/web.js');
const html=read('studio/web.html');
for(const id of ['midi-workspace','soundfont-select','soundfont-input','preview-midi',
  'stop-midi','midi-mixer','midi-channels','midi-transpose','export-format','resource-status']){
  assert.ok(html.includes('id="'+id+'"'),'Missing PC-parity control '+id);
}
assert.ok(html.indexOf('../browser-midi.js')<html.indexOf('./web-midi-core.js')&&
  html.indexOf('./web-midi-core.js')<html.indexOf('./web.js'),
  'Runtime dependencies must load before Web controller');
assert.ok(web.includes('await midiCore.inspectSong')&&
  web.includes('await renderMidiWave('),'PC-like preview and export must use real MIDI parser');
assert.ok(web.includes("if(!info.safe)throw Error("),
  'NCN with corrupt cursor timing must fail closed before export');
assert.ok(web.includes('assets.push({name:name+\'.lyr\''),
  'NCN source .LYR and .CUR must remain exportable unchanged');
assert.ok(!web.includes('FormData('),'No local music bytes may be uploaded to the server');
const start=web.indexOf('  async function createSongAssets(');
const end=web.indexOf('  async function reserveSongAssetNames(',start);
assert.ok(start>=0&&end>start);
const buildAssets=new Function('Blob','File','midiCore','midiRuntime','usesMidi','$',
  'lyricsFor','renderAudio','renderMidiWave','state','log','safeName','parseLrc','setProgress',
  web.slice(start,end)+'\nreturn createSongAssets;')(
  Blob,Blob,core,midi,()=>true,()=>({value:'xstage'}),
  async song=>song.lyricsText||song.midiInfo?.lrc||'',
  async()=>{throw Error('Original MIDI must not be transcoded in X-Stage mode');},
  async()=>{throw Error('No SoundFont render required for original source mode');},
  {cancelled:false},()=>{},v=>v,x=>[],()=>{}
);
song.midiInfo=info;
const assets=await buildAssets(song,1);
assert.deepEqual(assets.map(x=>x.name),
  ['NCN001.mid','NCN001.lyr','NCN001.cur','NCN001.json','NCN001.lrc']);
assert.deepEqual(Array.from(new Uint8Array(await assets[0].blob.arrayBuffer())),original,
  'MIDI source bytes must be preserved exactly');
assert.deepEqual(Array.from(new Uint8Array(await assets[1].blob.arrayBuffer())),
  Array.from(lyrBytes),'LYR CP874 bytes must remain unchanged');
assert.deepEqual(Array.from(new Uint8Array(await assets[2].blob.arrayBuffer())),
  Array.from(cursorBytes),'CUR bytes must remain unchanged');
assert.equal(JSON.parse(await assets[3].blob.text()).lines[0].syllables[1].start,.5);
await assert.rejects(buildAssets({...song,midiInfo:warning},1),/CUR/);
console.log('PASS: Song Studio Web NCN grouping, real CUR tempo, safe source preservation and resource gates');
