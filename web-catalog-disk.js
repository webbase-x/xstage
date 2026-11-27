/* Persistent, content-addressed canonical SQLite files for Karaoke Web.
 * OPFS stores bytes on disk. This adapter does not pretend sql.js can query
 * OPFS directly; until the OPFS SQL worker is wired, the legacy parser
 * still has its bounded memory limit.
 * No Google access token is stored. A caller must first verify the library.
 */
(function(scope){
'use strict';
const RESERVE=32*1048576;
function available(){
  return !!(scope.navigator?.storage?.getDirectory&&scope.crypto?.subtle&&scope.XStageImportCore?.MD5);
}
function identity(pointer){
  const md5=String(pointer?.contentMD5||'').toLowerCase(),size=Number(pointer?.contentBytes);
  return /^[a-f0-9]{32}$/.test(md5)&&Number.isSafeInteger(size)&&size>=100?{md5,size,name:md5+'-'+size+'.sqlite3'}:null;
}
async function folder(owner){
  if(!owner||!available())return null;
  const digest=await scope.crypto.subtle.digest('SHA-256',new TextEncoder().encode(owner));
  const name=Array.from(new Uint8Array(digest),v=>v.toString(16).padStart(2,'0')).join('');
  const root=await scope.navigator.storage.getDirectory();
  const catalog=await root.getDirectoryHandle('xstage-catalog-v1',{create:true});
  return catalog.getDirectoryHandle(name,{create:true});
}
function check(current,signal){
  if(signal?.aborted||!current())throw new DOMException('Catalog owner changed','AbortError');
}
async function verified(file,id,current,signal){
  if(file.size!==id.size)return false;
  const reader=file.stream().getReader(),hash=new scope.XStageImportCore.MD5();
  try{
    while(true){
      check(current,signal);
      const part=await reader.read();
      if(part.done)break;
      hash.append(part.value);
    }
    return hash.end()===id.md5;
  }finally{
    try{await reader.cancel();}catch{}
    reader.releaseLock();
  }
}
async function getOrFetch({owner,pointer,fetcher,current=()=>true,signal}){
  const id=identity(pointer);
  if(!id||!available())return null;
  check(current,signal);
  const dir=await folder(owner);
  if(!dir)return null;
  const run=async()=>{
    check(current,signal);
    let handle;
    try{
      handle=await dir.getFileHandle(id.name);
      const existing=await handle.getFile();
      if(await verified(existing,id,current,signal))return {file:existing,fromDisk:true};
    }catch(error){if(error?.name==='AbortError')throw error;if(error?.name!=='NotFoundError')throw error;}
    const estimate=await scope.navigator.storage.estimate?.();
    if(estimate&&Number.isFinite(estimate.quota)&&Number.isFinite(estimate.usage)&&estimate.quota-estimate.usage<id.size+RESERVE)
      throw Error('พื้นที่จัดเก็บฐานเพลงในเครื่องไม่พอ');
    try{await scope.navigator.storage.persist?.();}catch{}
    // createWritable commits the replacement only at close; abort retains
    // an existing file. The name is content-keyed, not tied to a Drive ID.
    handle=await dir.getFileHandle(id.name,{create:true});
    const out=await handle.createWritable({keepExistingData:false});
    let reader,committed=false,timer;
    const bounded=task=>Promise.race([task,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('ดาวน์โหลดฐานเพลงหยุดตอบสนอง')),30000);})]).finally(()=>clearTimeout(timer));
    try{
      const response=await fetcher();
      check(current,signal);
      if(!response?.ok||!response.body?.getReader)throw Error('เบราว์เซอร์ไม่รองรับการเขียนฐานแบบสตรีม');
      const advertised=Number(response.headers?.get('Content-Length')||0);
      if(advertised&&advertised!==id.size)throw Error('ขนาดฐาน Cloud เปลี่ยน');
      reader=response.body.getReader();
      const hash=new scope.XStageImportCore.MD5();
      let received=0;
      while(true){
        check(current,signal);
        const {done,value}=await bounded(reader.read());
        if(done)break;
        received+=value.byteLength;
        if(received>id.size)throw Error('ฐานเพลงมีขนาดเกินข้อมูลที่ตรวจสอบ');
        hash.append(value);
        await out.write(value);
      }
      check(current,signal);
      if(received!==id.size||hash.end()!==id.md5)throw Error('MD5 หรือขนาดฐานเพลงไม่ตรง Cloud');
      await out.close();committed=true;
      return {file:await handle.getFile(),fromDisk:false};
    }finally{
      if(!committed)try{await out.abort();}catch{}
      if(reader){try{void reader.cancel().catch(()=>{});}catch{}try{reader.releaseLock();}catch{}}
    }
  };
  // Cross-tab lock if supported. If unavailable, fail back rather than have
  // two writers publish the same revision concurrently.
  if(!scope.navigator.locks?.request)return null;
  return scope.navigator.locks.request('xstage-catalog:'+owner+':'+id.name,run);
}
async function prune(owner,pointer){
  const id=identity(pointer);
  if(!id||!available()||!scope.navigator.locks?.request)return;
  // Do not remove another revision while another tab may still read it.
  // Retention and quota management are handled by a future OPFS SQL session.
}
async function clear(){
  if(!available())return;
  const root=await scope.navigator.storage.getDirectory();
  try{await root.removeEntry('xstage-catalog-v1',{recursive:true});}catch(error){if(error?.name!=='NotFoundError')throw error;}
}
scope.XStageWebCatalogDisk=Object.freeze({available,identity,getOrFetch,clear});
})(window);
