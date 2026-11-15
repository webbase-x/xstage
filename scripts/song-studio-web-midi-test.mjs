import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const read=name=>fs.readFileSync(new URL('../'+name,import.meta.url),'utf8');
const ctx={Uint8Array,ArrayBuffer,DataView,TextDecoder,Blob,console,setTimeout};
ctx.window=ctx;
ctx.document={getElementById:()=>null};
vm.runInNewContext(read('browser-midi.js'),ctx,{filename:'browser-midi.js'});
vm.runInNewContext(read('studio/web-midi-core.js'),ctx,{filename:'web-midi-core.js'});
const midi=ctx.XStageBrowserMidi,core=ctx.XStageStudioMidiCore;
assert.ok(midi&&core,'Bundled MIDI and studio lyric pair parsers must be available');
assert.equal(core.groupIdentity('MIDI/NCN/Song','02386.mid'),
  core.groupIdentity('MIDI/NCN/Lyrics','02386.json'));
assert.notEqual(core.groupIdentity('A/NCN/Song','00001.mid'),
  core.groupIdentity('B/NCN/Song','00001.lrc'));
assert.equal(core.companionState({midi:{name:'02386.mid'}}).complete,false,
  'Bare MIDI is not a ready karaoke song');
assert.equal(core.companionState({
  midi:{name:'02386.mid'},lrc:{},json:{}
}).complete,false,'Two lyric companions are ambiguous');
assert.equal(core.companionState({
  midi:{name:'02386.mid'},lyr:{},cur:{}
}).complete,false,'Legacy NCN trio is no longer supported for import');
assert.match(core.companionState({
  midi:{name:'02386.mid'},lyr:{},cur:{}
}).message,/ยกเลิก/);

const track=[0,0xc0,0,0,0x90,60,100,0x60,0x80,60,0,0,0xff,0x2f,0];
const midiBytes=new Uint8Array([77,84,104,100,0,0,0,6,0,0,0,1,0,96,
  77,84,114,107,0,0,0,track.length,...track]);
function file(name,content){
  const blob=new Blob([content]);blob.name=name;
  return blob;
}
const song={name:'PAIR001',midi:file('PAIR001.mid',midiBytes),
  lrc:file('PAIR001.lrc','[00:00.00]ทดสอบแรก\n[00:00.50]ท่อนสอง'),
  lyricsText:null,editedLyrics:false};
const info=await core.inspectSong(song,midi);
assert.equal(info.kind,'MIDI');
assert.equal(info.safe,true);
assert.equal(info.document.lines.length,2);
assert.match(info.lrc,/\[00:00.00\]ทดสอบแรก/);
assert.equal(info.document.lines[1].startTime,.5);
assert.equal(core.documentToLrc({lines:[{startTime:1.25,text:'ทดสอบ'}]}),
  '[00:01.25]ทดสอบ');

const json={schemaVersion:1,songCode:'PAIR001',sourceFormat:'LRC',
  lines:[{startTime:1,endTime:2,text:'ทดสอบ JSON'}]};
const fromJson=await core.inspectSong({...song,lrc:null,
  json:file('PAIR001.json',JSON.stringify(json))},midi);
assert.equal(fromJson.document.lines[0].text,'ทดสอบ JSON');
await assert.rejects(core.inspectSong({...song,lrc:null},midi),/LRC|JSON/);
await assert.rejects(core.inspectSong({...song,lyr:{},cur:{}},midi),/ยกเลิก/);
await assert.rejects(core.inspectSong({...song,json:file('PAIR001.json',JSON.stringify(json))},midi),
  /หนึ่งไฟล์/);
await assert.rejects(core.inspectSong({...song,
  lrc:file('PAIR001.lrc','[00:03.00]หลัง\n[00:02.00]ก่อน')},midi),/ย้อนกลับ/);
const pending={...json,requiresReview:true};
await assert.rejects(core.inspectSong({...song,lrc:null,
  json:file('PAIR001.json',JSON.stringify(pending))},midi),/ตรวจเวลา/);
assert.equal(core.assessResources(120,0,8).ok,true);
assert.equal(core.assessResources(900,256*1048576,2).ok,false);
assert.equal(core.assessResources(901,0,8).ok,false);

const html=read('studio/web.html'),web=read('studio/web.js');
for(const id of ['midi-workspace','soundfont-select','soundfont-input','preview-midi',
 'stop-midi','midi-mixer','midi-channels','midi-transpose','export-format','resource-status'])
  assert.ok(html.includes('id="'+id+'"'),'Missing studio control '+id);
assert.ok(html.indexOf('../browser-midi.js')<html.indexOf('./web-midi-core.js')&&
  html.indexOf('./web-midi-core.js')<html.indexOf('./web.js'));
assert.ok(web.includes('await midiCore.inspectSong')&&
  web.includes('await renderMidiWave('),'Browser must reuse the real MIDI engine');
assert.ok(!web.includes("assets.push({name:name+'.lyr'"),
  'Do not include .LYR/.CUR as third/fourth output files');
assert.ok(!web.includes('FormData('),'Never upload local source audio to a server');
const start=web.indexOf('  async function createSongAssets(');
const end=web.indexOf('  async function reserveSongAssetNames(',start);
assert.ok(start>=0&&end>start);
const build=new Function('Blob','File','midiCore','midiRuntime','usesMidi','$',
  'lyricsFor','renderAudio','renderMidiWave','state','log','safeName','parseLrc','setProgress','extOf',
  web.slice(start,end)+'\nreturn createSongAssets;')(
  Blob,Blob,core,midi,()=>true,()=>({value:'xstage'}),
  async()=>await song.lrc.text(),
  async()=>{throw Error('MIDI must not transcode in original mode');},
  async()=>{throw Error('No soundfont render needed in original mode');},
  {cancelled:false},()=>{},v=>v,()=>[],()=>{},
  name=>String(name).split('.').pop().toLowerCase());
song.midiInfo=info;
const assets=await build(song,1);
assert.deepEqual(assets.map(x=>x.name),['PAIR001.mid','PAIR001.json'],
  'One source MIDI and one timed JSON; no third file');
assert.deepEqual(Array.from(new Uint8Array(await assets[0].blob.arrayBuffer())),
  Array.from(midiBytes),'Original MIDI bytes must not change');
assert.equal(JSON.parse(await assets[1].blob.text()).lines[1].text,'ท่อนสอง');
console.log('PASS: two-file Web studio MIDI/lyrics grouping, timing, source preservation and resource guard');
