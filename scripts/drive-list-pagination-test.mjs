/* Google Drive root discovery must consume ALL result pages, not only 1000.
 * Run with: node scripts/drive-list-pagination-test.mjs
 * Uses a request stub, never real Drive credentials or user files. */
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

const code=readFileSync(new URL('../app.js',import.meta.url),'utf8');
const match=code.match(/^async function driveList\(q, token\) \{[\s\S]*?^\}/m);
assert.ok(match,'driveList(q,token) must remain testable and explicitly paginated');

function fixture(pages,{failedStatus=0}={}){
  const requests=[];
  const list=runInNewContext('('+match[0]+')',{
    URLSearchParams,
    requestHeaders:token=>({Authorization:'Bearer '+token}),
    googleFetch:async(url,opts,label)=>{
      const parsed=new URL(url);
      assert.equal(parsed.origin,'https://www.googleapis.com');
      assert.equal(parsed.pathname,'/drive/v3/files');
      assert.equal(parsed.searchParams.get('q'),"name='XStageWeb'");
      assert.equal(parsed.searchParams.get('pageSize'),'1000');
      assert.match(parsed.searchParams.get('fields'),/nextPageToken/);
      assert.equal(opts.headers.Authorization,'Bearer test-access-token');
      assert.equal(opts.cache,'no-store');
      assert.equal(label,'Google Drive');
      const token=parsed.searchParams.get('pageToken')||'';
      requests.push(token);
      if(failedStatus&&token==='second')return {ok:false,status:failedStatus};
      assert.ok(Object.hasOwn(pages,token),'Unknown Drive page token '+token);
      return {ok:true,json:async()=>pages[token]};
    },
    driveError:(status)=>new Error('Google Drive HTTP '+status)
  });
  return {list:()=>list("name='XStageWeb'",'test-access-token'),requests};
}
const first=Array.from({length:1000},(_,i)=>({id:'file'+i}));
const after=[{id:'file1000'},{id:'file1001'}];
const run=fixture({'':{files:first,nextPageToken:'second'},
  second:{files:[],nextPageToken:'third'},third:{files:after}});
const found=await run.list();
assert.equal(found.length,1002);
assert.equal(found[1001].id,'file1001');
assert.deepEqual(run.requests,['','second','third'],
  'Follow even empty pages with nextPageToken');

const repeated=fixture({'':{files:[],nextPageToken:'second'},
  second:{files:[{id:'a'}],nextPageToken:'second'}});
await assert.rejects(repeated.list(),/รหัสหน้าผลการค้นหาซ้ำ/);
assert.deepEqual(repeated.requests,['','second']);

const bad=fixture({'':{files:'invalid'}});
await assert.rejects(bad.list(),/โครงสร้างไม่ถูกต้อง/);
const failed=fixture({'':{files:first,nextPageToken:'second'}},{failedStatus:403});
await assert.rejects(failed.list(),/HTTP 403/);

const empty=fixture({'':{files:[]}});
assert.equal((await empty.list()).length,0);
console.log('PASS: Drive discovery reads all pages, prevents cursor loops, and fails closed');
