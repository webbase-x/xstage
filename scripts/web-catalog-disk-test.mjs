import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {webcrypto,createHash} from 'node:crypto';
import vm from 'node:vm';
const core=readFileSync(new URL('../cloud-import-core.js',import.meta.url),'utf8');
const src=readFileSync(new URL('../web-catalog-disk.js',import.meta.url),'utf8');
const folders=new Map(),files=new Map();
function dir(path){
  return {
    async getDirectoryHandle(name){const key=path+'/'+name;if(!folders.has(key))folders.set(key,dir(key));return folders.get(key);},
    async getFileHandle(name,opts={}){
      const key=path+'/'+name;
      if(!files.has(key)&&!opts.create)throw new DOMException('Missing','NotFoundError');
      if(!files.has(key))files.set(key,new Blob());
      return {getFile:async()=>files.get(key),async createWritable(){
        const parts=[];
        return {write:async v=>parts.push(v.slice()),close:async()=>files.set(key,new Blob(parts)),abort:async()=>{}};
      }};
    }
  };
}
const env={Blob,Response,TextEncoder,TextDecoder,DOMException,setTimeout,clearTimeout,console,crypto:webcrypto,
  navigator:{storage:{getDirectory:async()=>dir(''),estimate:async()=>({quota:1e9,usage:0}),persist:async()=>true},
    locks:{request:async(_name,run)=>run()}}};
env.window=env;vm.runInNewContext(core,env);vm.runInNewContext(src,env);
const api=env.XStageWebCatalogDisk;
const bytes=new Uint8Array(200).fill(11);
const md5=value=>createHash('md5').update(value).digest('hex');
const pointer={contentMD5:md5(bytes),contentBytes:bytes.length,catalogFileId:'drive-A'};
let requests=0;
const fetcher=async()=>{requests++;return new Response(bytes);};
let got=await api.getOrFetch({owner:'account:root',pointer,fetcher});
assert.equal(got.fromDisk,false);assert.equal(requests,1);
got=await api.getOrFetch({owner:'account:root',pointer:{...pointer,catalogFileId:'drive-B'},fetcher});
assert.equal(got.fromDisk,true);assert.equal(requests,1,'identical bytes with a different Drive ID must not download again');
const changed=new Uint8Array(200).fill(22),changedPointer={...pointer,contentMD5:md5(changed)};
await assert.rejects(api.getOrFetch({owner:'account:root',pointer:changedPointer,fetcher}),/MD5/);
got=await api.getOrFetch({owner:'account:root',pointer,fetcher});
assert.equal(got.fromDisk,true,'failed replacement preserves previous verified revision');
got=await api.getOrFetch({owner:'account:root',pointer:changedPointer,fetcher:async()=>new Response(changed)});
assert.equal(got.fromDisk,false);
got=await api.getOrFetch({owner:'another-account:root',pointer,fetcher});
assert.equal(got.fromDisk,false,'never expose other account bytes');
console.log('PASS: simulated OPFS streaming persistence, revision reuse, checksum and account scope');
