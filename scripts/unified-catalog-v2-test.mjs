import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const src=readFileSync(new URL('../unified-catalog-v2.js',import.meta.url),'utf8');
const context={window:{}};
vm.runInNewContext(src,context);
const api=context.window.XStageCatalogV2;
const song={id:'audio/0/00001',webSongId:'audio/0/00001',code:'00001',
  title:'ทดสอบ',artist:'ศิลปิน',
  media:{mp3:{fileId:'audio_id',path:'AUDIO/MP3/Songs/0/00001.mp3'}},
  lyrics:{fileId:'lyric_id',path:'AUDIO/MP3/Lyrics/0/00001.json'}};
const catalog={schemaVersion:2,format:'xstage-unified-v2',songs:[song]};
assert.equal(api.catalog(catalog,{cloud:true,expectedCount:1}),catalog);
assert.equal(api.pointer({schemaVersion:2,format:'xstage-unified-v2',
  generation:'abc12',catalogFileId:'drive_123',songCount:1}).songCount,1);
assert.throws(()=>api.catalog({...catalog,songs:[song,song]},{cloud:true}),/ID เพลงซ้ำ/);
assert.throws(()=>api.catalog(catalog,{cloud:true,expectedCount:2}),/จำนวนเพลง/);
assert.throws(()=>api.song({...song,media:{video:{type:'exe',fileId:'v'}}},{cloud:true}));
assert.throws(()=>api.song({...song,media:{midi:{type:'ncn',fileId:'a'}}},{cloud:true}));
assert.throws(()=>api.song({...song,media:{mp3:{fileId:'a',localPath:'/private/b'}}},{cloud:true}));
assert.throws(()=>api.song({...song,media:{mp3:{fileId:'a',path:'../../etc'}}},{cloud:true}));
assert.throws(()=>api.song({...song,media:{mp3:{fileId:'a',size:-1}}},{cloud:true}));
assert.throws(()=>api.pointer({schemaVersion:2,generation:'a',catalogFileId:'b',songCount:-1}));
const shards={schemaVersion:2,format:'xstage-unified-v2',generation:'shards_1',
  songCount:2501,catalogFiles:[{fileId:'shard_1',bucket:'0',songCount:2500},
    {fileId:'shard_2',bucket:'0',songCount:1}]};
assert.equal(api.pointer(shards),shards);
assert.throws(()=>api.pointer({...shards,catalogFileId:'old'}));
assert.throws(()=>api.pointer({...shards,songCount:2500}),/ผลรวม/);
assert.throws(()=>api.pointer({...shards,catalogFiles:[shards.catalogFiles[0],shards.catalogFiles[0]]}),/ซ้ำ/);
assert.equal(api.pointer({...shards,deltaFileIds:['delta_v1'],songCount:2502}).songCount,2502);
assert.throws(()=>api.pointer({...shards,deltaFileIds:['delta_v1','delta_v1']}),/Delta/);
const local={...song,media:{mp3:{localPath:'C:/Music/00001.mp3'}}};
assert.equal(api.song(local,{cloud:false}),local);
assert.throws(()=>api.song(local,{cloud:true}),/Google Drive/);
const studioHtml=readFileSync(new URL('../studio/index.html',import.meta.url),'utf8');
const studioJs=readFileSync(new URL('../studio/app.js',import.meta.url),'utf8');
const studioEngine=readFileSync(new URL('../songstudio-pc/engine.py',import.meta.url),'utf8');
assert.match(studioHtml,/id="catalog-v2-setup"/);
assert.match(studioHtml,/XStageWeb\/DB\/current\.json/);
assert.match(studioJs,/await run\('initialize-cloud-v2'\)/);
assert.match(studioEngine,/elif action == "initialize-cloud-v2"/);
assert.doesNotMatch(studioJs,/migrate-catalog-v2|catalog-v2-dry-run|upload-create-library/);
assert.match(studioEngine,/read_code_registry\(\)/);
console.log('Unified Catalog V2 JavaScript contract: cloud, local, duplicates and path safety PASS');
