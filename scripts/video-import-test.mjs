import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const read=path=>fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const ctx={Blob,console};ctx.window=ctx;
vm.runInNewContext(read('cloud-import-core.js'),ctx);
const core=ctx.XStageImportCore;
const file=(name,size=2048)=>({name,size,lastModified:1});
const plan=core.scan([
  {file:file('VideoOne.mp4'),relative:'VIDEO/MP4/Songs/V/VideoOne.mp4'},
  {file:file('AviOld.avi'),relative:'VIDEO/AVI/Song/AviOld.avi'},
  {file:file('MovieFromVCD.dat'),relative:'VIDEO/VCD/Song/MovieFromVCD.dat'},
  {file:file('Clip.mkv'),relative:'VIDEO/MKV/Songs/Clip.mkv'},
  {file:file('Silent.mp3'),relative:'AUDIO/MP3/Song/Silent.mp3'},
  {file:file('Dual.mp3'),relative:'AUDIO/MP3/Song/Dual.mp3'},
  {file:file('Dual.mov'),relative:'VIDEO/MOV/Songs/Dual.mov'},
]);
assert.equal(plan.songs.length,5,'Native VDO, legacy VDO and paired audio/video must be grouped');
assert.equal(plan.blocked.length,1,'Audio-only without timed lyrics must remain blocked');
assert.equal(plan.songs.find(s=>s.code==='Dual').video.kind,'mov');
assert.ok(core.needsVideoConversion('karaoke.DAT'));
assert.ok(core.needsVideoConversion('karaoke.MOV'));
assert.ok(!core.needsVideoConversion('karaoke.mp4'));
assert.ok(!core.needsVideoConversion('karaoke.webm'));
const embedded=core.embeddedVideoLyrics('VIDEO100');
assert.equal(embedded.schemaVersion,1);
assert.equal(embedded.lyricsMode,'embedded-video');
assert.equal(embedded.lines.length,0);
const fromBytes=(name,bytes)=>{
  const arr=Buffer.alloc(2048);
  for(let i=0;i<bytes.length;i++)arr[i]=bytes[i];
  const b=new Blob([arr]);b.name=name;return b;
};
const ascii=(name,text,offset=0)=>{
  const bytes=Buffer.alloc(2048);bytes.write(text,offset);
  return fromBytes(name,bytes);
};
const avi=Buffer.alloc(2048);avi.write('RIFF',0);avi.write('AVI ',8);
assert.equal(await core.validVideo(fromBytes('x.avi',avi)),true);
const mpeg=fromBytes('vcd.dat',Buffer.concat([Buffer.from([0,0,1,0xba]),Buffer.alloc(2044)]));
assert.equal(await core.validVideo(mpeg),true,'MPEG-PS signature for VCD DAT');
assert.equal(await core.validVideo(fromBytes('x.mkv',Buffer.concat([Buffer.from([0x1a,0x45,0xdf,0xa3]),Buffer.alloc(2044)]))),true);
assert.equal(await core.validVideo(ascii('fake.avi','RIFF')),false,'AVI without AVI marker must fail');
assert.equal(await core.validVideo(ascii('fake.mkv','NOPE')),false);
assert.equal(await core.validVideo(ascii('fake.dat','RANDOM')),false);
const videoScript=read('video-transcode.js');
assert.doesNotThrow(()=>new Function(videoScript),'Video transcode script parses');
const workerScript=read('video-transcode-worker.js');
assert.doesNotThrow(()=>new Function(workerScript),'Isolated worker script parses');
assert.ok(videoScript.includes('new Worker(')&&!videoScript.includes('import(urls[0])'),
  'Third-party codec code must not run in the OAuth-enabled main window');
assert.ok(workerScript.includes('requireAudio')&&workerScript.includes('0:a:0'),
  'Video-only songs must preserve a real audio track');
assert.ok(workerScript.includes('libx264'));
assert.ok(videoScript.includes('192*1024*1024'),'Browser conversion must have a safe memory cap');
const importer=read('cloud-import.js'),page=read('index.html'),app=read('app.js'),css=read('style.css');
assert.ok(importer.includes('embeddedVideoLyrics(code)')&&
  importer.includes('XStageVideoTranscode.convert'),'Legacy video conversion must happen before Drive upload');
assert.ok(page.includes('video-transcode.js?v=')&&page.includes('id="video-lyrics-toggle"'));
assert.ok(app.includes('updateVideoLyricsToggle()')&&
  app.includes('signal?.aborted'),'Video loading must handle cancel and captions');
assert.ok(css.includes('.stage.video-lyrics-off #lyrics'));
const videoItem=plan.songs.find(item=>item.code==='VideoOne');
assert.equal(core.videoMime('a.mov'),'video/quicktime');
assert.equal(core.videoMime('a.avi'),'video/x-msvideo');
assert.equal(core.videoMime('a.dat'),'video/mpeg');
assert.ok(core.videoFingerprint(videoItem).includes('VideoOne.mp4'));
assert.throws(()=>core.validateVideoDetails(videoItem,{
  code:'V400',title:'ตัวอย่าง',artist:'',mode:'embedded'
}),/นักร้อง/,'Artist is a required catalog field');
assert.throws(()=>core.validateVideoDetails(videoItem,{
  code:'V400',title:'ตัวอย่าง',artist:'นักร้อง',mode:'review'
}),/ต้องเลือก/,'Unconfirmed embedded subtitles cannot be silently inferred');
assert.throws(()=>core.validateVideoDetails(videoItem,{
  code:'V400',title:'ตัวอย่าง',artist:'นักร้อง',mode:'timed',lrc:'ไม่มีเวลา'
}),/LRC/,'Video without embedded lyrics needs verified LRC timestamps');
const verified=core.validateVideoDetails(videoItem,{
  code:'V400',title:'ตัวอย่าง',artist:'นักร้อง',mode:'timed',
  lrc:'[00:01.00]เนื้อร้องบรรทัดแรก\\n[00:03.40]บรรทัดสอง',
  album:'อัลบั้ม',composer:'ผู้แต่ง',genre:'ลูกทุ่ง',year:'2025',language:'ไทย'
});
assert.equal(verified.year,2025);
assert.equal(verified.album,'อัลบั้ม');
assert.equal(core.lrcToJson(verified.lrc,verified.code).lines.length,2);
assert.throws(()=>core.validateVideoDetails(videoItem,{
  code:'../bad',title:'ตัวอย่าง',artist:'นักร้อง',mode:'embedded'
}),/ปลอดภัย/);
const embeddedDetails=core.validateVideoDetails(videoItem,{
  code:'V400',title:'ตัวอย่าง',artist:'นักร้อง',mode:'embedded'
});
assert.equal(embeddedDetails.lrc,'');
assert.equal(embeddedDetails.mode,'embedded');
const script=read('video-metadata-editor.js');
assert.doesNotThrow(()=>new Function(script),'Metadata editor must parse');
assert.ok(script.includes('validateVideoDetails')&&script.includes('insertStamp')&&
  script.includes('previewCurrent'),'Editor must include validation and real-time LRC preview');
assert.ok(importer.includes('originalVideo:originalVideoMedia')&&
  importer.includes("['AUDIO']"),
  'Original video source stays private in flat AUDIO, not replaced by conversion');
assert.ok(page.includes('id="cloud-import-video-artist"')&&
  page.includes('id="cloud-import-video-lrc"')&&page.includes('id="video-original-toggle"'));
assert.ok(app.includes('originalVideoSupported(song)')&&
  app.includes('forceCompatible:true'),'Native source playback must fall back to compatible MP4');

console.log('PASS: VDO classification, signatures, embedded lyrics, converter safety and stage control');
