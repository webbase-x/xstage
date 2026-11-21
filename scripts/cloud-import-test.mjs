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
assert.equal(result.songs.length,1,'MP3 plus timed LRC remains playable');
assert.equal(result.midis.length,1,'Complete NCN MIDI+LYR+CUR must be importable');
assert.equal(result.midis[0].kind,'NCN');
assert.equal(result.fonts.length,1);
assert.ok(!result.blocked.some(x=>x.key.includes('C300')),'Complete NCN must not be blocked');
assert.ok(result.blocked.some(x=>x.reason.includes('ไฟล์เสียงต้องมี LRC/JSON')));
assert.equal(core.groupKey('AUDIO/MP3/Songs/A/A100.mp3'),core.groupKey('AUDIO/MP3/Lyrics/A/A100.lrc'));
const media=core.scan([
  {file:fake('W100.wav'),relative:'AUDIO/WAV/Song/W100.wav'},
  {file:fake('W100.lrc',40),relative:'AUDIO/WAV/Lyrics/W100.lrc'},
  {file:fake('O100.ogg'),relative:'AUDIO/OGG/Song/O100.ogg'},
  {file:fake('O100.lrc',40),relative:'AUDIO/OGG/Lyrics/O100.lrc'},
  {file:fake('V100.mp4'),relative:'VIDEO/MP4/Song/V100.mp4'},
  {file:fake('V100.lrc',40),relative:'VIDEO/MP4/Lyrics/V100.lrc'}
]);
assert.deepEqual(Array.from(media.songs,x=>x.kind).sort(),['MP4','OGG','WAV'],
  'Native browser-audio and video containers must scan with timed lyrics');
assert.equal(media.songs.find(x=>x.kind==='MP4').video.kind,'mp4');
// New XStageKaraoke/SONGS contract: pair only within a format directory.
// KAR and XSK remain standalone, and NCN is MID+LYR+CUR.
const agreed=core.scan([
  {file:fake('00001.mid'),relative:'XStageKaraoke/SONGS/MIDI/MID/SONG/0/00001.mid'},
  {file:fake('00001.json',160),relative:'XStageKaraoke/SONGS/MIDI/MID/LYRICS/0/00001.json'},
  {file:fake('00002.mp3'),relative:'XStageKaraoke/SONGS/AUDIO/MP3/SONG/0/00002.mp3'},
  {file:fake('00002.json',160),relative:'XStageKaraoke/SONGS/AUDIO/MP3/LYRICS/0/00002.json'},
  {file:fake('00003.mp4'),relative:'XStageKaraoke/SONGS/VIDEO/MP4/SONG/0/00003.mp4'},
  {file:fake('00003.json',160),relative:'XStageKaraoke/SONGS/VIDEO/MP4/LYRICS/0/00003.json'},
  {file:fake('00004.kar'),relative:'XStageKaraoke/SONGS/MIDI/KAR/0/00004.kar'},
  {file:fake('00005.xsk',1000),relative:'XStageKaraoke/SONGS/MIDI/XSK/0/00005.xsk'},
  {file:fake('00006.mid'),relative:'XStageKaraoke/SONGS/MIDI/NCN/SONG/0/00006.mid'},
  {file:fake('00006.lyr',160),relative:'XStageKaraoke/SONGS/MIDI/NCN/LYR/0/00006.lyr'},
  {file:fake('00006.cur',160),relative:'XStageKaraoke/SONGS/MIDI/NCN/CUR/0/00006.cur'}
]);
assert.equal(agreed.songs.length,2,'MP3 and MP4 must pair with own JSON');
assert.equal(agreed.midis.length,3,'MID, KAR and NCN must import from distinct folders');
assert.equal(agreed.xsks.length,1,'Standalone XSK must import without extra JSON');
assert.equal(agreed.midis.find(x=>x.kind==='NCN')?.cur.kind,'cur');
assert.ok(!agreed.blocked.length,'All approved format-local bundles must pair cleanly');
assert.notEqual(core.groupKey('AUDIO/MP3/SONG/0/00001.mp3'),
                core.groupKey('VIDEO/MP4/SONG/0/00001.mp4'),
                'Identical song code in different formats must not collide');
const wavHead=Buffer.alloc(1500);
wavHead.write('RIFF',0);wavHead.write('WAVE',8);
const wavBlob=new Blob([wavHead]);wavBlob.name='sample.wav';
assert.equal(await core.validAudio(wavBlob),true,'WAV RIFF/WAVE signature');
const bad=new Blob([Buffer.alloc(1500)]);bad.name='sample.wav';
assert.equal(await core.validAudio(bad),false,'Invalid WAV must be rejected by signature');
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
function sfList(name,bytes=80){
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

const xskScan=core.scan([
  {file:fake('00001.xsk',19255),relative:'XStageKaraoke/SONGS/MIDI/XSK/0/00001.xsk'},
  {file:fake('XStageKaraoke-access.xskkey',260),relative:'XStageKaraoke-access.xskkey'}
]);
assert.equal(xskScan.xsks.length,1,'XSK is a first-class import candidate');
assert.equal(xskScan.blocked.length,1,'Legacy XSK key file is ignored and never uploaded');
assert.match(xskScan.blocked[0].reason,/ไม่ต้องใช้ไฟล์กุญแจ/);
const ncnIdentity=core.songIdentity({schemaVersion:1,songCode:'00001',
  metadata:{title:'ทำได้เพียง',artist:'25 Hours'}},'00001');
assert.equal(ncnIdentity.title,'ทำได้เพียง');
assert.equal(ncnIdentity.artist,'25 Hours');
assert.equal(ncnIdentity.identityComplete,true);
const missingIdentity=core.songIdentity({title:'00001',artist:'X-Stage Karaoke'},'00001');
assert.equal(missingIdentity.title,'ไม่ระบุชื่อเพลง');
assert.equal(missingIdentity.artist,'ไม่ระบุศิลปิน');
assert.equal(missingIdentity.identityComplete,false);
const keptIdentity=core.songIdentity({title:'00001'},'00001',{title:'เพลงแก้ไขแล้ว',artist:'ผู้ร้องจริง'});
assert.equal(keptIdentity.title,'เพลงแก้ไขแล้ว');
assert.equal(keptIdentity.artist,'ผู้ร้องจริง');

console.log('PASS: streaming MD5, song pairing, typed validation and timed LRC contracts');
