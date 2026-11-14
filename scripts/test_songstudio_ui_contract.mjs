// Pre-release DOM/JavaScript contract checks; no browser credentials needed.
import fs from 'node:fs';
import assert from 'node:assert/strict';

const html=fs.readFileSync('studio/index.html','utf8');
const js=fs.readFileSync('studio/app.js','utf8');
const css=fs.readFileSync('studio/style.css','utf8');
const onlinePlayer=fs.readFileSync('app.js','utf8');
const onlinePublisher=fs.readFileSync('songstudio-pc/online_publish.py','utf8');
const folderUploader=fs.readFileSync('songstudio-pc/folder_upload.py','utf8');
assert.ok(onlinePlayer.includes('pointer.catalogFileId') &&
          onlinePlayer.includes('pointer.deltaFileIds') &&
          onlinePlayer.includes('privateFile(song.audio.fileId') &&
          onlinePlayer.includes('privateJson(song.lyrics.fileId'),
          'Online player must consume publisher catalog IDs and private media');
assert.ok(onlinePublisher.includes('"catalogFileId": catalog_id') &&
          onlinePublisher.includes('"deltaFileIds": delta_ids') &&
          onlinePublisher.includes('"audio": audio, "lyrics": lyrics') &&
          onlinePublisher.includes('replace_pointer=True'),
          'Publisher must expose the exact online reader fields and atomically switch pointer');
assert.ok(folderUploader.includes('publisher.publish(') &&
          folderUploader.includes('validator(library["root"], row)') &&
          folderUploader.includes('export.lrc_to_json('),
          'Folder upload must publish verified timed lyrics through the existing online schema');
assert.ok(folderUploader.includes('"webMidiReady": False') &&
          !onlinePlayer.includes('SOUNDFONT/SF2'),
          'Do not claim browser SoundFont playback when only private Drive storage exists');

const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(x=>x[1]);
const unique=new Set(ids);
assert.equal(ids.length,unique.size,'HTML IDs must be unique');
for(const [,ref] of js.matchAll(/\$\('([^']+)'\)/g))
  assert.ok(unique.has(ref),'UI references missing element: #'+ref);
assert.doesNotThrow(()=>new Function(js),'PC Control JS must parse');

const required={
  create:['scan-button','song-rows','create-soundfont','preview-button',
          'preview-file-type','preview-lyrics-lines','build-button','build-audio-button'],
  lyrics_bulk:['lyric-group-scan','lyric-group-results','lyric-group-apply',
               'lyric-group-undo','lyric-group-replacement','lyric-group-examples',
               'lyric-group-search','lyric-group-repeats','lyric-group-stats',
               'lyric-group-select-page','lyric-group-clear','lyric-group-selected-count'],
  ai:['ai-lyrics-import','ai-lyrics-results','ai-lyrics-start','ai-lyrics-play',
      'ai-lyrics-editor','ai-lyrics-karaoke','ai-lyrics-save',
      'ai-lyrics-download','ai-lyrics-insert-time',
      'ai-lyrics-paste','ai-lyrics-align','ai-lyrics-align-review',
      'ai-lyrics-separate','ai-lyrics-use-vocals','ai-lyrics-vocals-status',
      'ai-mic-start','ai-mic-stop','ai-mic-save','ai-mic-discard',
      'ai-mic-preview','ai-mic-status','ai-mic-timer'],
  drive:['upload-folder-button','upload-folder','upload-inspect','upload-allow-new','settings-login','download-destination','settings-logout'],
};
for(const [area,elements] of Object.entries(required))
 for(const id of elements)
   assert.ok(unique.has(id),'Missing '+area+' control #'+id);

for(const tab of ['create','ai-lyrics','lyric-head-tail','upload','download','settings']){
  assert.ok(html.includes('data-tab="'+tab+'"'),'Missing sidebar tab '+tab);
  assert.ok(html.includes('id="tab-'+tab+'"'),'Missing tab panel '+tab);
}
for(const endpoint of ['/api/vocal-songs','/api/vocal-import','/api/ai-lyrics-draft',
    '/api/ai-lyrics-approve','/api/vocal-remove','/api/preview-sources','/api/live-preview','/api/jobs'])
  assert.ok(js.includes(endpoint),'Missing UI endpoint '+endpoint);
for(const handler of ['ai-lyrics-import','ai-lyrics-start','ai-lyrics-play',
                      'ai-lyrics-download','ai-lyrics-save','upload-folder-button','download-destination'])
  assert.ok(js.includes("$('"+handler+"')"),'Missing event/UI binding for '+handler);

assert.ok(js.includes("run('ai-align'"),'Missing AI alignment job handler');
assert.ok(js.includes("previewAudio.addEventListener('playing', startKaraokeAnimation)"),
  'Karaoke lyric animation must recover after streaming resumes');
assert.ok(js.includes("previewAudio.addEventListener('timeupdate',()=>{"),
  'Streaming lyric clock must update from decoded audio position');
assert.ok(js.includes("previewLyricClockHealth()"),
  'Long playback must diagnose stalled media time or exhausted lyric timestamps');
assert.ok(js.includes("previewLyricCoverageWarned"),
  'Missing lyrics after the last timestamp must be reported once, not silently freeze');
for (const id of ['ai-export-button','ai-export-lyrics','ai-export-instrumental',
                 'ai-export-choose-folder','ai-export-folder']) {
  assert.ok(html.includes('id="'+id+'"'), 'Missing selectable AI export UI: '+id);
}
assert.ok(js.includes("run('ai-export',{id,lyrics,instrumental})"),
  'AI export selections must reach the authenticated local engine');
assert.ok(js.includes("saveInputs(['download-destination'])"),
  'AI export must persist the selected destination');
assert.ok(js.includes("run('ai-separate-vocals'"),
  'AI Lyrics separation button must start backend HTDemucs job');
assert.ok(js.includes("useSeparatedVocals:$('ai-lyrics-use-vocals').checked"),
  'Whisper must honor the selected separated vocal M4A');
assert.ok(js.includes("source_choice:$('ai-lyrics-use-vocals').checked?'ai-vocals'"),
  'Lyrics preview must support auditioning separated vocals');
assert.ok(js.includes('navigator.mediaDevices.getUserMedia') &&
  js.includes('new MediaRecorder('),'Microphone recording must request consent');
assert.ok(js.includes('/api/ai-recording-upload') &&
  js.includes("run('ai-recording-save'"),
  'Microphone recording must upload to local engine and explicitly convert M4A');
assert.ok(css.includes('.ai-microphone-panel'),
  'Missing microphone recording visual controls');
assert.ok(js.includes('pendingAiAlignment'),'Missing safeguard for pasted original lyrics');
assert.ok(css.includes('.ai-lyrics-paste-panel'),'Missing pasted lyrics UX styles');
assert.ok(js.includes("run('lyric-groups-replace'"),'Missing safe grouped lyrics replace job');
assert.ok(js.includes("run('lyric-groups-undo'"),'Missing bulk edit undo job');
assert.ok(html.includes('id="lyric-group-replacement-mode"') &&
          html.includes('<option value="custom" selected>') &&
          html.includes('<option value="X-Stage Karaoke">') &&
          html.includes('<option value="X-Stage Karaoke Online">') &&
          html.includes('<option value="X-Stage Song Studio">'),
  'Bulk lyrics require branded presets and a custom-entry choice');
assert.ok(js.includes("$('lyric-group-replacement-mode').addEventListener('change'") &&
          js.includes("$('lyric-group-replacement-mode').value='custom'") &&
          js.includes("$('lyric-group-replacement').value!==chosen"),
  'Preset selection must populate editable text, while manual typing restores custom mode');
assert.ok(css.includes('.lyric-group-edit .lyric-replacement-mode'),
  'Preset menu must fit inside the lyric editor');
assert.ok(js.includes("run('lyric-groups-scan'"),'Missing grouped text scan job');
assert.ok(html.includes('id="create-export-format"') &&
  html.includes('<option value="xstage" selected>') &&
  html.includes('<option value="m4a">'),
  'Song Studio must default to original MIDI + timed JSON with optional M4A');
assert.ok(js.includes("export_format:audioOnly?'m4a'") &&
  js.includes("'create-export-format': 'export_format'"),
  'Export selection must reach the engine and persist');
for(const id of ['lyric-group-folder','lyric-group-reset','lyric-group-source-status']){
  assert.ok(html.includes('id="'+id+'"'), 'JSON lyrics editor folder selector missing: '+id);
}
assert.ok(html.includes('Lyrics JSON') && html.includes('ไม่แก้ MIDI'),
  'Bulk editing must describe JSON-only behavior, preserving original media');
assert.ok(html.includes('data-pick="lyric_source"'),
  'The Windows lyrics editor must offer a native source folder picker');
assert.ok(js.includes("'lyric-group-folder': 'lyric_source'") &&
          js.includes("saveInputs(['lyric-group-folder'])") &&
          js.includes("config({lyric_source:''})") &&
          js.includes("phraseInvalidate()"),
  'Bulk lyric source must persist, reset and invalidate stale selected groups');
assert.ok(js.includes('phraseSelected'),'Missing multi-group selection state');
assert.ok(js.includes('/api/lyric-groups-plan'),'Missing server-side multi-group preview');
assert.ok(js.includes('data-lyric-group'),'Missing per-row selected checkbox');
assert.ok(js.includes('phraseReady=true') && js.includes('await refreshPhraseGroups()'),
  'Remaining unedited groups must refresh automatically after replacement');
assert.ok(css.includes('.lyric-group-row'),'Missing grouped lyric frequency styles');
assert.ok(js.includes('aiRemoveImportedSong('),'Missing AI imported song removal workflow');
assert.ok(js.includes('data-ai-remove') || js.includes('dataset.aiRemove'),'Missing per-row remove action');
assert.ok(js.includes('นำออกจากรายการ') && js.includes('ไม่ลบไฟล์เพลงต้นฉบับ'),'Missing destructive-action warning');
assert.ok(css.includes('.ai-lyrics-song-remove'),'Missing remove button styling');
assert.ok(js.includes('karaokeWipeSpan('),'Missing real-time karaoke sweep spans');
assert.ok(js.includes('karaokeUpdateSpans('),'Missing karaoke sweep update loop');
assert.ok(js.includes('aiStartKaraokeAnimation'),'Missing smooth AI lyrics animation');
assert.ok(css.includes('.karaoke-wipe-text') && css.includes('--karaoke-wipe'),
  'MIDI/LRC sweep spans require real color clipping CSS');
assert.ok(css.includes('linear-gradient(to right'),'Karaoke color wipe must fill left-to-right');
const stage=fs.readFileSync('app.js','utf8');
const begin=stage.indexOf('function lineProgress(line,when){');
const end=stage.indexOf('\nfunction drawLyrics(){',begin);
assert.ok(begin>=0 && end>begin,'Online stage is missing MIDI timed sweep');
const stageProgress=new Function('pen','return ('+stage.slice(begin,end)+')')({
  measureText(s){return {width:[...s].reduce((sum,ch)=>sum+(ch==='M'?20:5),0)};}
});
const note={text:'MW',startTime:0,endTime:2,
  syllables:[{text:'M',start:0,duration:1},{text:'W',start:1,duration:1}]};
assert.ok(Math.abs(stageProgress(note,.5)-.4)<.001,
  'MIDI sweep must follow measured glyph width, not character count');
assert.ok(Math.abs(stageProgress(note,1.5)-.9)<.001,
  'MIDI sweep must continue smoothly into the next timed syllable');
assert.equal(stageProgress({text:'AB',startTime:0,endTime:2},1),.5,
  'Untimed standard LRC must use approximate whole-line interpolation');
const tied={text:'MWX',startTime:0,endTime:3,
  syllables:[{text:'M',start:0,duration:0},{text:'W',start:0,duration:0},
             {text:'X',start:2,duration:1}]};
const duringTie=[.25,.5,1,1.5,1.9].map(time=>stageProgress(tied,time));
assert.ok(duringTie.every((value,i)=>i===0||value>duringTie[i-1]),
  'Simultaneous MIDI/CUR cursor cues must animate smoothly, never remain frozen');
assert.ok(duringTie[0]>0 && duringTie.at(-1)<1,
  'The sweep must move continuously through a multi-glyph tied timestamp');
const wholeLine={text:'MWX',startTime:0,endTime:4,
  syllables:[{text:'M',start:0,duration:0},{text:'W',start:0,duration:0},
             {text:'X',start:0,duration:0}]};
assert.equal(stageProgress(wholeLine,2),.5,
  'When every MIDI cursor cue has identical timing, use smooth line approximation');
const outroPause={text:'MW',startTime:0,endTime:12,
  syllables:[{text:'M',start:0,duration:1},{text:'W',start:1,duration:11}]};
assert.ok(stageProgress(outroPause,3)>.99,
  'The final glyph should finish naturally rather than creeping across a long instrumental rest');
const beginning=js.indexOf('  function karaokeCueWindows(');
const ending=js.indexOf('  function karaokeWipeSpan(',beginning);
assert.ok(beginning>=0&&ending>beginning,
  'Studio preview requires safe interpolation for duplicate CUR timestamps');
const studioCueWindows=new Function('return ('+js.slice(beginning,ending).trim()+')')();
const windows=studioCueWindows([
  {text:'ก',startTime:0},{text:'า',startTime:0},{text:'ข',startTime:2}
],0,3);
assert.deepEqual(windows.map(x=>Number(x.start.toFixed(2))),[0,1,2],
  'Studio must distribute tied cursor letters across the next available beat');
assert.deepEqual(windows.map(x=>Number(x.end.toFixed(2))),[1,2,3],
  'Studio preview must not leave gaps or flash simultaneous letters');
assert.equal(studioCueWindows([
  {text:'A',startTime:0},{text:'B',startTime:0}
],0,4),null,
  'Studio should use smooth whole-line LRC approximation when no usable character times exist');
assert.ok(css.includes('.ai-lyrics-karaoke'),'Missing karaoke styles');
assert.ok(css.includes('.preview-file-selector'),'Missing file proof styling');
console.log('PASS: PC/Web Control UI syntax, bulk multi-select, lyric-body search, AI and Drive controls.');
