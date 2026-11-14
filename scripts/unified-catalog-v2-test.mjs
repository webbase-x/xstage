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
const local={...song,media:{mp3:{localPath:'C:/Music/00001.mp3'}}};
assert.equal(api.song(local,{cloud:false}),local);
assert.throws(()=>api.song(local,{cloud:true}),/Google Drive/);
console.log('Unified Catalog V2 JavaScript contract: cloud, local, duplicates and path safety PASS');
