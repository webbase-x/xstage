// Pre-release DOM/JavaScript contract checks; no browser credentials needed.
import fs from 'node:fs';
import assert from 'node:assert/strict';

const html=fs.readFileSync('studio/index.html','utf8');
const js=fs.readFileSync('studio/app.js','utf8');
const css=fs.readFileSync('studio/style.css','utf8');
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
      'ai-lyrics-paste','ai-lyrics-align','ai-lyrics-align-review'],
  drive:['upload-button','settings-login','download-destination','settings-logout'],
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
                      'ai-lyrics-download','ai-lyrics-save','upload-button','download-destination'])
  assert.ok(js.includes("$('"+handler+"')"),'Missing event/UI binding for '+handler);

assert.ok(js.includes("run('ai-align'"),'Missing AI alignment job handler');
assert.ok(js.includes('pendingAiAlignment'),'Missing safeguard for pasted original lyrics');
assert.ok(css.includes('.ai-lyrics-paste-panel'),'Missing pasted lyrics UX styles');
assert.ok(js.includes("run('lyric-groups-replace'"),'Missing safe grouped lyrics replace job');
assert.ok(js.includes("run('lyric-groups-undo'"),'Missing bulk edit undo job');
assert.ok(js.includes("run('lyric-groups-scan'"),'Missing grouped text scan job');
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
assert.ok(css.includes('.ai-lyrics-karaoke'),'Missing karaoke styles');
assert.ok(css.includes('.preview-file-selector'),'Missing file proof styling');
console.log('PASS: PC/Web Control UI syntax, bulk multi-select, lyric-body search, AI and Drive controls.');
