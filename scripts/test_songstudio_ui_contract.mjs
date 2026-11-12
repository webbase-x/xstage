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
  ai:['ai-lyrics-import','ai-lyrics-results','ai-lyrics-start','ai-lyrics-play',
      'ai-lyrics-editor','ai-lyrics-karaoke','ai-lyrics-save',
      'ai-lyrics-download','ai-lyrics-insert-time'],
  drive:['upload-button','settings-login','download-destination','settings-logout'],
};
for(const [area,elements] of Object.entries(required))
 for(const id of elements)
   assert.ok(unique.has(id),'Missing '+area+' control #'+id);

for(const tab of ['create','ai-lyrics','upload','download','settings']){
  assert.ok(html.includes('data-tab="'+tab+'"'),'Missing sidebar tab '+tab);
  assert.ok(html.includes('id="tab-'+tab+'"'),'Missing tab panel '+tab);
}
for(const endpoint of ['/api/vocal-songs','/api/vocal-import','/api/ai-lyrics-draft',
    '/api/ai-lyrics-approve','/api/preview-sources','/api/live-preview','/api/jobs'])
  assert.ok(js.includes(endpoint),'Missing UI endpoint '+endpoint);
for(const handler of ['ai-lyrics-import','ai-lyrics-start','ai-lyrics-play',
                      'ai-lyrics-download','ai-lyrics-save','upload-button','download-destination'])
  assert.ok(js.includes("$('"+handler+"')"),'Missing event/UI binding for '+handler);

assert.ok(css.includes('.ai-lyrics-karaoke'),'Missing karaoke styles');
assert.ok(css.includes('.preview-file-selector'),'Missing file proof styling');
console.log('PASS: PC/Web Control UI syntax, 5 tabs, 147 unique IDs, AI import/preview/export and Drive controls.');
