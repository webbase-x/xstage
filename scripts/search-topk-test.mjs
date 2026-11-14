/* Verify bounded Top-K search equals the full stable legacy ranking,
 * using a synthetic 100,000-song library and no private user catalog. */
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const source=fs.readFileSync(new URL('../app.js',import.meta.url),'utf8');
const start=source.indexOf('function normalizeSearchText(value){');
const end=source.indexOf('function setLiveSearchExpanded(open){',start);
assert.ok(start>0&&end>start,'Search core must be present');
const ctx={window:{}};
vm.runInNewContext(source.slice(start,end)+
  '\nthis.__rank=rankedSearchEntries;this.__index=indexedSongs;'+
  'this.__score=searchScore;this.__normalize=normalizeSearchText;',ctx);
const songs=Array.from({length:100000},(_,i)=>({
  code:'A'+String(i).padStart(6,'0'),
  title:(i%3===0?'เพลงรัก ':'เพลงทั่วไป ')+String(i%600),
  artist:'ศิลปิน '+String(i%15)
}));
const indexed=ctx.__index(songs);
assert.equal(ctx.__index(songs),indexed,'Search index should reuse the same catalog');
assert.equal(indexed.length,100000);
const scoreFull=(query,limit)=>{
  const term=ctx.__normalize(query),words=term.split(' ').filter(Boolean);
  const matches=indexed.map(entry=>({...entry,score:ctx.__score(entry,term,words)}))
    .filter(entry=>Number.isFinite(entry.score))
    .sort((a,b)=>a.score-b.score||a.index-b.index);
  return {total:matches.length,results:matches.slice(0,limit)};
};
for(const [query,limit] of [['เพลง',5],['เพลงรัก',5],['A000042',5],
  ['ศิลปิน 7',200],['ไม่มีเพลงนี้',5],['เพลง',0]]){
  const expected=scoreFull(query,limit);
  const actual=ctx.__rank(songs,query,limit);
  assert.equal(actual.total,expected.total,'Match count: '+query);
  assert.deepEqual(Array.from(actual.results,r=>r.index),
    Array.from(expected.results,r=>r.index),'Stable Top-K order: '+query);
  assert.deepEqual(Array.from(ctx.window.XStageRankSearch(songs,query,limit),r=>r.index),
    Array.from(expected.results,r=>r.index),'External remote API: '+query);
  assert.ok(actual.results.length<=limit,'Only requested results should be retained');
}
assert.equal(ctx.__rank(songs,'').total,0,'Empty search must not list the library');
console.log('PASS: 100,000-song Top-K ranking, exact match counts and stable remote results');
