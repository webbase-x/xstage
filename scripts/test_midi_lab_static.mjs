import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const html=readFileSync(new URL('../midi-lab.html',import.meta.url),'utf8');
const js=readFileSync(new URL('../midi-lab.js',import.meta.url),'utf8');
const app=readFileSync(new URL('../app.js',import.meta.url),'utf8');
for(const id of ['mode','quality','cache','font','midi','play','pause','stop','clear','seek','speed','speed-value','status','position']){
  assert.match(html,new RegExp('id="'+id+'"'),'missing control '+id);
}
assert.match(html,/<option value="auto"[^>]*>อัตโนมัติ/);
assert.match(html,/<option value="balanced"[^>]*>สมดุล/);
assert.match(html,/id="cache" checked/);
assert.match(js,/loadNewSongList\(\[\{binary\}\]\)/);
assert.match(js,/soundBankManager\.addSoundBank/);
assert.match(js,/cachePut\(/);
assert.match(js,/cacheClear\(/);
assert.match(js,/MThd|hasMidiHeader/);
assert.match(app,/function playable\(song\) \{ return !!\(getFileId\(song\?\.audio\)/);
assert.doesNotMatch(js,/accounts\.google\.com|drive\.google\.com|Bearer /i);
console.log('MIDI SoundFont lab static contract checks passed (runtime/device checks remain manual).');
