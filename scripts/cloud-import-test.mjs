import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {createHash,randomBytes} from 'node:crypto';

const text=fs.readFileSync(new URL('../cloud-import-core.js',import.meta.url),'utf8');
const context={Blob,TextDecoder,TextEncoder,console};
context.window=context;
vm.runInNewContext(text,context,{filename:'cloud-import-core.js'});
const core=context.XStageImportCore;
assert.ok(core,'Web upload source should export testable library');
const md5=buf=>createHash('md5').update(buf).digest('hex');
for(const b of [Buffer.alloc(0),Buffer.from('abc'),randomBytes(63),
  randomBytes(64),randomBytes(65),randomBytes(1024),randomBytes(1024*1024+29)]){
  const h=new core.MD5();
  for(let offset=0;offset<b.length;offset+=37)h.append(b.subarray(offset,offset+37));
  assert.equal(h.end(),md5(b),'Incremental MD5 mismatch');
  assert.equal(await core.hashBlob(new Blob([b])),md5(b),'Blob MD5 mismatch');
}
const fake=(name,size=2048,lastModified=1)=>({name,size,lastModified});
const result=core.scan([
  {file:fake('A100.mp3'),relative:'AUDIO/MP3/Songs/A/A100.mp3'},
  {file:fake('A100.lrc',80),relative:'AUDIO/MP3/Lyrics/A/A100.lrc'},
  {file:fake('B200.m4a'),relative:'B200.m4a'},
  {file:fake('C300.mid'),relative:'MIDI/NCN/Song/C300.mid'},
  {file:fake('C300.lyr',200),relative:'MIDI/NCN/Lyrics/C300.lyr'},
  {file:fake('C300.cur',200),relative:'MIDI/NCN/Cursor/C300.cur'},
  {file:fake('SF-General.sf2',1024),relative:'SOUNDFONT/SF2/SF-General.sf2'}
]);
assert.equal(result.songs.length,1,'Only audio plus timed LRC must enter playable candidate queue');
assert.equal(result.fonts.length,1);
assert.ok(result.blocked.some(x=>x.reason.includes('Song Studio PC')),'MIDI cannot be silently claimed playable');
assert.ok(result.blocked.some(x=>x.reason.includes('ต้องมีไฟล์ MP3')));
assert.equal(core.groupKey('AUDIO/MP3/Songs/A/A100.mp3'),core.groupKey('AUDIO/MP3/Lyrics/A/A100.lrc'));
assert.equal(core.bucket('1234'),'1');
assert.equal(core.bucket('คำไทย'),'_');
const lrc=core.lrcToJson('[ti:เพลงทดสอบ]\n[ar:ศิลปิน]\n[00:01.50]สวัสดี\n[00:03.00]ขอบคุณ\n','AB100');
assert.equal(lrc.lines.length,2);
assert.equal(lrc.lines[0].startTime,1.5);
assert.equal(lrc.lines[0].endTime,3);
assert.equal(lrc.title,'เพลงทดสอบ');
assert.equal(lrc.artist,'ศิลปิน');
assert.throws(()=>core.lrcToJson('ข้อความไม่มีเวลา','A'),/ไม่มีบรรทัด/);
const sampleMp3=new Blob([Buffer.from([73,68,51]),Buffer.alloc(1500)],{type:'audio/mpeg'});
sampleMp3.name='sound.mp3';
assert.equal(await core.validAudio(sampleMp3),true);
// SoundFonts must declare a bounded RIFF sfbk with INFO, sdta and pdta.
function sfList(name,bytes=64){
  const body=Buffer.alloc(4+bytes);
  body.write(name,0,'ascii');
  const head=Buffer.alloc(8);head.write('LIST',0,'ascii');head.writeUInt32LE(body.length,4);
  return Buffer.concat([head,body]);
}
const sfBody=Buffer.concat([Buffer.from('sfbk'),sfList('INFO'),sfList('sdta'),sfList('pdta')]);
const sfHead=Buffer.alloc(8);sfHead.write('RIFF',0,'ascii');sfHead.writeUInt32LE(sfBody.length,4);
const sfFile=new Blob([sfHead,sfBody]);sfFile.name='General.sf2';
assert.equal(await core.validFont(sfFile),true,'Complete RIFF SoundFont must pass');
const truncated=new Blob([Buffer.concat([sfHead,Buffer.from('sfbk')])]);
truncated.name='Incomplete.sf2';
assert.equal(await core.validFont(truncated),false,'Truncated SoundFont cannot be imported');
const corrupt=Buffer.concat([sfHead,sfBody]);
corrupt.write('WRNG',12,'ascii');
const corruptFile=new Blob([corrupt]);corruptFile.name='Corrupt.sf3';
assert.equal(await core.validFont(corruptFile),false,'SoundFont missing INFO LIST must fail');

console.log('PASS: streaming MD5, song pairing, typed validation and timed LRC contracts');
