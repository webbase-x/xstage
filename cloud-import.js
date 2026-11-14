/* X-Stage Karaoke Online: owner-only, browser-based private Drive importer.
 * Never stores Google access tokens or file bytes. Resume is at verified
 * immutable-file boundaries; an in-flight partial file may be retried.
 * Requires cloud-import-core.js, same app OAuth and explicit user consent.
 */
(function(scope){
'use strict';
const core=scope.XStageImportCore;
if(!core)throw Error('Cloud Import: format validation module missing');
const $=id=>document.getElementById(id);
const MIME_FOLDER='application/vnd.google-apps.folder';
const API='https://www.googleapis.com/drive/v3/files';
const UPLOAD='https://www.googleapis.com/upload/drive/v3/files';
const CHUNK=8*1024*1024,MAX_LRC=2*1024*1024,MAX_JSON=128*1024*1024;
function fail(message){throw Error(message);}
function driveId(value){
  const id=String(value||'');
  if(!/^[A-Za-z0-9_-]{5,256}$/.test(id))fail('Drive File ID ไม่ถูกต้อง');
  return id;
}
function safeName(value){
  return String(value||'').normalize('NFC').replace(/[\/\\<>:"|?*\u0000-\u001f]/g,'_')
    .replace(/^\.+/,'').trim().slice(0,105)||'song';
}
function sleep(ms){return new Promise(r=>setTimeout(r,ms));}
function aborted(error){return error?.name==='AbortError'||String(error?.message||'').includes('หยุดงาน');}
function encode(document){return new Blob([JSON.stringify(document)],{type:'application/json'});}
function pathFor(code,kind,role,name){
  const group=core.bucket(code);
  return [kind==='sf2'||kind==='sf3'?'SOUNDFONT':'AUDIO',
    kind==='sf2'||kind==='sf3'?kind.toUpperCase():kind.toUpperCase(),
    ...(kind==='sf2'||kind==='sf3'?[]:[role,group]),name];
}
async function db(){
  if(!('indexedDB' in scope))return null;
  return await new Promise((resolve,reject)=>{
    const req=indexedDB.open('xstage-cloud-import-jobs-v1',1);
    req.onupgradeneeded=()=>{if(!req.result.objectStoreNames.contains('jobs'))req.result.createObjectStore('jobs');};
    req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);
  });
}
async function checkpoint(account,value){
  if(!account)return null;
  let database=null;
  try{
    database=await db();if(!database)return null;
    return await new Promise((resolve,reject)=>{
      const tx=database.transaction('jobs','readwrite');
      const req=value===undefined?tx.objectStore('jobs').get(account):
        value===null?tx.objectStore('jobs').delete(account):
        tx.objectStore('jobs').put(value,account);
      req.onsuccess=()=>resolve(req.result||null);req.onerror=()=>reject(req.error);
    });
  }catch(error){console.warn('Import resume metadata unavailable:',error?.message||error);return null;}
  finally{try{database?.close();}catch{}}
}
class Drive {
  constructor(getToken,assertLive){this.getToken=getToken;this.assertLive=assertLive;this.children=new Map();}
  headers(extra={}){const token=this.getToken();if(!token)fail('Google Login หมดอายุ กรุณาเข้าสู่ระบบใหม่');return {Authorization:'Bearer '+token,...extra};}
  async fetch(url,options={}){
    this.assertLive();
    const response=await fetch(url,{...options,headers:this.headers(options.headers),cache:'no-store'});
    this.assertLive();
    if(!response.ok){
      if(response.status===401)fail('Google Login หมดอายุ กรุณาล็อกอินใหม่แล้วกดทำต่อ');
      if(response.status===403)fail('ไม่มีสิทธิ์เขียน/อ่าน XStageWeb ใน Google Drive นี้ · ตรวจบัญชีและ drive.file');
      if(response.status===429||response.status>=500)fail('Google Drive ให้ลองใหม่ภายหลัง (HTTP '+response.status+')');
      fail('Google Drive ไม่สำเร็จ (HTTP '+response.status+')');
    }
    return response;
  }
  async list(q){
    const rows=[];let next='';
    do{
      this.assertLive();
      const params=new URLSearchParams({q,fields:'nextPageToken,files(id,name,mimeType,size,md5Checksum,ownedByMe,parents)',
        pageSize:'1000'});
      if(next)params.set('pageToken',next);
      const result=await (await this.fetch(API+'?'+params)).json();
      rows.push(...(Array.isArray(result.files)?result.files:[]));
      next=String(result.nextPageToken||'');
      if(rows.length>300000)fail('พบไฟล์บน Drive มากเกินขีดจำกัดการตรวจต่อครั้ง');
    }while(next);
    return rows;
  }
  async listChildren(id){
    if(this.children.has(id))return this.children.get(id);
    const query="'"+(id==='root'?'root':driveId(id))+"' in parents and trashed=false";
    const files=await this.list(query);
    this.children.set(id,files);
    return files;
  }
  async folder(parent,name){
    const files=(await this.listChildren(parent)).filter(x=>x.name===name);
    if(files.length>1)fail('โฟลเดอร์บน Drive ซ้ำกัน: '+name);
    if(files.length===1){
      if(files[0].mimeType!==MIME_FOLDER)fail('พบชื่อชนกับไฟล์ใน Drive: '+name);
      return files[0].id;
    }
    const response=await this.fetch(API+'?fields=id,name,mimeType,parents',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({name,mimeType:MIME_FOLDER,parents:[parent]})
    });
    const created=await response.json();
    if(!created.id)fail('สร้างโฟลเดอร์บน Drive ไม่สำเร็จ: '+name);
    this.children.get(parent).push(created);
    return created.id;
  }
  async ensurePath(root,parts){
    let id=root;
    for(const part of parts)id=await this.folder(id,part);
    return id;
  }
  async getJson(fileId){
    const response=await this.fetch(API+'/'+driveId(fileId)+'?alt=media');
    const size=Number(response.headers.get('Content-Length')||0);
    if(size>MAX_JSON)fail('ฐานเพลงใหญ่เกินขอบเขตการอ่านอย่างปลอดภัย');
    const document=await response.json().catch(()=>fail('ไฟล์ฐานเพลง JSON ไม่ถูกต้อง'));
    if(!document||typeof document!=='object'||Array.isArray(document))fail('โครงสร้าง JSON ของฐานเพลงไม่ถูกต้อง');
    return document;
  }
  async metadata(id){
    const r=await this.fetch(API+'/'+driveId(id)+'?fields=id,name,mimeType,md5Checksum,size');
    return await r.json();
  }
  async upload(parent,file,name,mime,md5,onBytes){
    this.assertLive();
    const matches=(await this.listChildren(parent)).filter(x=>x.name===name);
    if(matches.length>1)fail('มีไฟล์ชื่อซ้ำหลายรายการใน Drive: '+name);
    if(matches.length===1){
      const old=matches[0];
      const check=old.md5Checksum?old:await this.metadata(old.id);
      if(String(check.md5Checksum||'').toLowerCase()!==md5.toLowerCase()||
         Number(check.size||0)!==file.size)fail('มีไฟล์ชื่อเดิมแต่ MD5/ขนาดต่างกัน: '+name);
      if(onBytes)onBytes(file.size,file.size);
      return {id:old.id,md5Checksum:md5,size:file.size,reused:true};
    }
    const meta={name,mimeType:mime,parents:[parent]};
    const initiate=await this.fetch(UPLOAD+'?uploadType=resumable&fields=id,name,mimeType,md5Checksum,size',{
      method:'POST',headers:{'Content-Type':'application/json; charset=UTF-8',
        'X-Upload-Content-Type':mime,'X-Upload-Content-Length':String(file.size)},
      body:JSON.stringify(meta)
    });
    const session=initiate.headers.get('Location');
    if(!session)fail('Google Drive ไม่เปิดเผย URL ของ Resumable Upload ในเบราว์เซอร์นี้');
    const location=new URL(session);
    if(location.protocol!=='https:'||location.hostname!=='www.googleapis.com'||
       !location.pathname.startsWith('/upload/drive/v3/files'))
      fail('Google Drive คืน Upload URL ที่ไม่อยู่ในโดเมนที่อนุญาต');
    // Google requires Range verification for every 308 response. Never
    // assume a chunk was committed when the Range header is absent.
    let answer=null,start=0,retries=0;
    const uploadStatus=async()=>{
      this.assertLive();
      const response=await fetch(location.href,{method:'PUT',cache:'no-store',
        headers:this.headers({'Content-Range':'bytes */'+file.size}),
        signal:this.signal?.()});
      if(response.status===308){
        const match=String(response.headers.get('Range')||'').match(/^bytes=0-(\d+)$/);
        return {position:match?Number(match[1])+1:0};
      }
      if(response.ok)return {complete:await response.json(),position:file.size};
      fail('สอบถามตำแหน่งอัปโหลด Drive ไม่สำเร็จ (HTTP '+response.status+')');
    };
    while(start<file.size){
      this.assertLive();
      const end=Math.min(start+CHUNK,file.size);
      let response=null;
      try{
        response=await fetch(location.href,{method:'PUT',cache:'no-store',
          headers:this.headers({'Content-Type':mime,
            'Content-Range':'bytes '+start+'-'+(end-1)+'/'+file.size}),
          body:file.slice(start,end),signal:this.signal?.()});
      }catch(error){
        if(error?.name==='AbortError'||this.signal?.()?.aborted)throw error;
        if(++retries>4)fail('การเชื่อมต่อ Google Drive ขาดหลายครั้ง · หยุดและทำต่อภายหลัง');
        await sleep(Math.min(4000,350*2**retries));
        const status=await uploadStatus();
        if(status.complete){answer=status.complete;start=file.size;break;}
        start=status.position;continue;
      }
      if(response.status===308){
        const match=String(response.headers.get('Range')||'').match(/^bytes=0-(\d+)$/);
        const accepted=match?Number(match[1])+1:0;
        if(accepted>end)fail('Google Drive ตอบช่วงไฟล์เกินขนาดที่ส่ง');
        if(accepted<=start){
          if(++retries>4)fail('Google Drive ไม่ยืนยันช่วงข้อมูลที่ส่ง · หยุดอย่างปลอดภัย');
          await sleep(Math.min(4000,350*2**retries));
          const status=await uploadStatus();
          if(status.complete){answer=status.complete;start=file.size;break;}
          start=status.position;
          continue;
        }
        start=accepted;retries=0;
      }else if(response.ok){
        answer=await response.json();
        start=file.size;retries=0;
      }else if(response.status===429||response.status>=500){
        if(++retries>4)fail('Google Drive ขัดข้องซ้ำหลายครั้ง (HTTP '+response.status+')');
        await sleep(Math.min(4000,350*2**retries));
        const status=await uploadStatus();
        if(status.complete){answer=status.complete;start=file.size;break;}
        start=status.position;
      }else{
        if(response.status===401||response.status===403)fail('สิทธิ์ Google Drive หมดอายุหรือไม่อนุญาตให้อัปโหลด');
        fail('ส่งข้อมูลขึ้น Google Drive ไม่สำเร็จ (HTTP '+response.status+')');
      }
      if(onBytes)onBytes(start,file.size);
    }
    if(!answer?.id)fail('Google Drive ไม่คืน File ID หลังอัปโหลด');
    const verified=answer.md5Checksum?answer:await this.metadata(answer.id);
    if(String(verified.md5Checksum||'').toLowerCase()!==md5.toLowerCase()||
       Number(verified.size)!==file.size)fail('MD5/ขนาดไฟล์ที่ Google Drive คืนมาไม่ตรงต้นฉบับ');
    const entry={...verified,id:answer.id,name,md5Checksum:md5,size:file.size};
    this.children.get(parent).push(entry);
    return {id:answer.id,md5Checksum:md5,size:file.size,reused:false};
  }
  async updatePointer(id,blob,hash){
    const response=await this.fetch(UPLOAD+'/'+driveId(id)+'?uploadType=media&fields=id,name,md5Checksum,size',{
      method:'PATCH',headers:{'Content-Type':'application/json'},body:blob});
    const result=await response.json();
    const meta=result.md5Checksum?result:await this.metadata(id);
    if(String(meta.md5Checksum||'').toLowerCase()!==hash||Number(meta.size)!==blob.size)
      fail('อัปเดต current.json แล้ว Google Drive ยืนยัน MD5 ไม่ตรง');
  }
}
async function loadCatalog(drive,root){
  const children=await drive.listChildren(root);
  const pointers=children.filter(x=>x.name==='current.json'&&x.mimeType!==MIME_FOLDER);
  if(pointers.length>1)fail('พบ current.json ซ้ำ · หยุดเพื่อไม่ให้ DB เสีย');
  if(!pointers.length){
    const marker=children.find(x=>x.name==='.xstage-songstudio-staging.json');
    const unknown=children.filter(x=>!['SOUNDFONT','AUDIO','VIDEO','MIDI','DB',
      '.xstage-songstudio-staging.json'].includes(x.name));
    if(unknown.length)fail('พบไฟล์ใน XStageWeb แต่ไม่มี current.json · ต้องตรวจคลังเดิมก่อน');
    if(!marker&&children.some(x=>x.name!=='SOUNDFONT'))
      fail('XStageWeb ยังไม่มี current.json หรือหลักฐานนำเข้าที่ปลอดภัย · ไม่เริ่มทับ');
    if(marker){
      const data=await drive.getJson(marker.id);
      if(data.format!=='xstage-songstudio-upload-staging-v1')
        fail('ตัวระบุการนำเข้าครั้งก่อนบน Drive ไม่ถูกต้อง');
    }
    return {pointerFile:null,pointer:null,rows:new Map()};
  }
  const pointer=await drive.getJson(pointers[0].id);
  if(pointer.schemaVersion!==1||typeof pointer.catalogFileId!=='string'||
     !Array.isArray(pointer.deltaFileIds)||pointer.deltaFileIds.length>32||
     new Set(pointer.deltaFileIds).size!==pointer.deltaFileIds.length)
    fail('current.json ไม่ตรงสัญญาฐานเพลง X-Stage Online');
  const base=await drive.getJson(pointer.catalogFileId);
  if(base.schemaVersion!==1||!Array.isArray(base.songs))
    fail('Catalog หลักของ XStageWeb ไม่ถูกต้อง');
  const rows=new Map();
  for(const x of base.songs){if(!x||typeof x.webSongId!=='string')fail('เพลงใน Catalog หลักไม่ถูกต้อง');rows.set(x.webSongId,x);}
  for(const fileId of pointer.deltaFileIds){
    const delta=await drive.getJson(fileId);
    if(delta.schemaVersion!==1||!Array.isArray(delta.upserts)||!Array.isArray(delta.removes))
      fail('Catalog ส่วนอัปเดตไม่ถูกต้อง');
    for(const id of delta.removes){if(typeof id!=='string')fail('รายการลบเพลงไม่ถูกต้อง');rows.delete(id);}
    for(const row of delta.upserts){if(!row||typeof row.webSongId!=='string')fail('รายการเพลงใหม่ไม่ถูกต้อง');rows.set(row.webSongId,row);}
  }
  if(pointer.songCount!==rows.size)fail('จำนวนเพลงบน Drive ไม่ตรงกับ Catalog');
  return {pointerFile:pointers[0],pointer,rows};
}
class Importer {
  constructor(options){
    this.options=options;this.selected=null;this.plan=null;this.running=false;this.paused=false;this.stopRequested=false;
    this.controller=null;this.folderHandle=null;this.saved=null;this.stats={newSongs:0,updated:0,duplicates:0,conflicts:0,fonts:0,errors:0};
    this.dom={};
    for(const key of ['open','dialog','close','pick','input','scan','start','pause','resume','cancel',
      'allow-create','source','total','ready','fonts','blocked','examples','progress','progress-label',
      'status','detail'])this.dom[key]=$('cloud-import-'+key);
    this.dom.open?.addEventListener('click',()=>this.open());
    this.dom.close?.addEventListener('click',()=>this.close());
    this.dom.dialog?.addEventListener('cancel',event=>{event.preventDefault();this.close();});
    this.dom.pick?.addEventListener('click',()=>this.choose());
    this.dom.scan?.addEventListener('click',()=>this.inspect());
    this.dom.start?.addEventListener('click',()=>this.start());
    this.dom.pause?.addEventListener('click',()=>this.stop('พักงาน'));
    this.dom.cancel?.addEventListener('click',()=>this.stop('ยกเลิกงาน · เก็บรายการที่ทำเสร็จไว้บน Drive'));
    this.dom.resume?.addEventListener('click',()=>this.resume());
    this.dom.input?.addEventListener('change',()=>this.acceptFiles(Array.from(this.dom.input.files||[]).map(file=>({
      file,relative:file.webkitRelativePath||file.name})),null));
    scope.addEventListener('pagehide',()=>this.stop('ปิดหน้าเว็บ · หยุดและจดจำจุดทำต่อ'));
    scope.addEventListener('xstage:auth-ready',()=>this.updateOpen());
    scope.addEventListener('xstage:auth-refreshed',()=>this.updateOpen());
    scope.addEventListener('xstage:auth-cleared',()=>{
      this.stop('ออกจาก Google · พักงานทันที');
      this.selected=null;this.plan=null;this.folderHandle=null;this.selectedSub='';
      this.updateOpen();this.refreshButtons();
    });
    this.updateOpen();
  }
  session(){return this.options.session();}
  updateOpen(){
    if(!this.dom.open)return;
    const auth=this.session();
    this.dom.open.hidden=!auth?.token;
    this.dom.open.disabled=this.running;
  }
  status(message){if(this.dom.status)this.dom.status.textContent=message;}
  progress(index,total,ratio=0){
    const percent=Math.max(0,Math.min(100,Math.round((index+ratio)*100/Math.max(1,total))));
    this.dom.progress.value=percent;
    this.dom['progress-label'].textContent=percent+'%';
  }
  refreshButtons(){
    const selected=!!this.plan&&(this.plan.songs.length+this.plan.fonts.length)>0;
    this.dom.start.disabled=this.running||!selected;
    this.dom.pause.disabled=!this.running;
    this.dom.cancel.disabled=!this.running;
    this.dom.resume.disabled=this.running||(!selected&&!this.saved);
    this.dom.pick.disabled=this.running;
    this.dom.scan.disabled=this.running||!this.selected;
    this.updateOpen();
  }
  async open(){
    if(!this.session()?.token){this.status('กรุณาเชื่อมต่อ Google Drive ก่อน');return;}
    if(!this.dom.dialog.open){
      if(this.dom.dialog.showModal)this.dom.dialog.showModal();
      else this.dom.dialog.setAttribute('open','');
    }
    this.saved=await checkpoint(this.session().sub,undefined);
    if(this.saved&&!this.selected){
      this.status('พบงานค้างของบัญชีนี้ · กดทำต่อ (อาจต้องอนุญาตโฟลเดอร์เดิม)');
      this.dom.source.textContent='งานเดิม: '+String(this.saved.label||'โฟลเดอร์เพลง');
      if(this.saved.handle)this.folderHandle=this.saved.handle;
    }
    this.refreshButtons();
  }
  close(){
    if(this.running)this.stop('ปิดหน้าต่าง · งานถูกพักโดยไม่ลบไฟล์ที่ส่งสำเร็จ');
    if(this.dom.dialog.close)this.dom.dialog.close();
    else this.dom.dialog.removeAttribute('open');
  }
  async choose(){
    if(this.running)return;
    if(typeof scope.showDirectoryPicker==='function'){
      try{
        const handle=await scope.showDirectoryPicker({mode:'read'});
        const list=await this.collect(handle);
        await this.acceptFiles(list,handle);
        return;
      }catch(e){
        if(e?.name==='AbortError')return;
        this.status('อ่านโฟลเดอร์ด้วยระบบใหม่ไม่ได้ · เลือกด้วยตัวเลือกปกติ: '+e.message);
      }
    }
    this.dom.input.value='';
    this.dom.input.click();
  }
  async collect(handle){
    const files=[],stack=[{handle,path:''}];
    while(stack.length){
      const dir=stack.pop();
      for await(const child of dir.handle.values()){
        const relative=dir.path+child.name;
        if(child.kind==='directory')stack.push({handle:child,path:relative+'/'});
        else if(child.kind==='file'){
          const file=await child.getFile();
          files.push({file,relative});
          if(files.length%500===0){this.status('กำลังตรวจชื่อไฟล์ '+files.length.toLocaleString('th-TH')+' รายการ');await sleep(0);}
        }
      }
    }
    return files;
  }
  async acceptFiles(files,handle){
    this.selected=files;this.folderHandle=handle;
    this.selectedSub=this.session()?.sub||'';
    this.plan=core.scan(files);
    this.dom.source.textContent='เลือกแล้ว '+files.length.toLocaleString('th-TH')+' ไฟล์'+(handle?' (จำสิทธิ์โฟลเดอร์สำหรับทำต่อได้ถ้าเบราว์เซอร์อนุญาต)':' (เปิดใหม่ต้องเลือกโฟลเดอร์เดิมอีกครั้ง)');
    this.dom.total.textContent=this.plan.files.toLocaleString('th-TH');
    this.dom.ready.textContent=this.plan.songs.length.toLocaleString('th-TH');
    this.dom.fonts.textContent=this.plan.fonts.length.toLocaleString('th-TH');
    this.dom.blocked.textContent=this.plan.blocked.length.toLocaleString('th-TH');
    const samples=this.plan.blocked.slice(0,7).map(x=>x.key+' · '+x.reason);
    this.dom.examples.textContent=samples.join('\n')+(this.plan.blocked.length>7?'\nและอีก '+(this.plan.blocked.length-7)+' ชุด':'');
    this.progress(0,1);
    this.status('ตรวจชื่อไฟล์แล้ว · กดเริ่มเพื่อตรวจข้อมูลจริง/MD5 และอัปโหลดเฉพาะรายการที่สมบูรณ์');
    await this.save({status:'selected',done:0,total:this.plan.songs.length+this.plan.fonts.length});
    this.refreshButtons();
  }
  async save(extra={}){
    const auth=this.session();
    if(!auth?.sub)return;
    const data={version:1,label:this.dom.source.textContent,updatedAt:Date.now(),
      count:this.plan?.songs.length||0,fonts:this.plan?.fonts.length||0,...extra};
    if(this.folderHandle)data.handle=this.folderHandle;
    this.saved=data;await checkpoint(auth.sub,data);
  }
  stop(message){
    if(!this.running)return;
    this.stopRequested=true;
    this.controller?.abort();
    this.status(message+' · สามารถกดทำต่อได้หลังเชื่อม Google Drive');
  }
  check(){
    if(this.stopRequested)throw new DOMException('ผู้ใช้หยุดงาน','AbortError');
    const auth=this.session();
    if(!auth?.token||!auth.sub||auth.sub!==this.account)fail('บัญชี Google เปลี่ยนหรือสิทธิ์หมดอายุ · หยุดเพื่อความปลอดภัย');
  }
  async resume(){
    if(this.running)return;
    if(!this.selected){
      const auth=this.session();
      const record=this.saved||await checkpoint(auth?.sub,undefined);
      if(record?.handle){
        try{
          const permission=await record.handle.queryPermission({mode:'read'});
          if(permission!=='granted'){
            const asked=await record.handle.requestPermission({mode:'read'});
            if(asked!=='granted')fail('ยังไม่ได้อนุญาตอ่านโฟลเดอร์เดิม');
          }
          await this.acceptFiles(await this.collect(record.handle),record.handle);
        }catch(e){this.status('เปิดโฟลเดอร์เดิมไม่ได้ กรุณาเลือกใหม่: '+e.message);return;}
      }else{
        this.status('กรุณาเลือกโฟลเดอร์เดิมอีกครั้ง · ระบบตรวจ MD5/Drive และข้ามไฟล์ที่ส่งสำเร็จแล้ว');
        await this.choose();
        if(!this.selected)return;
      }
    }
    await this.start();
  }
  async start(){
    if(this.running||!this.plan)return;
    const auth=this.session();
    if(!auth?.token||!auth.sub){this.status('กรุณาล็อกอิน Google ก่อน');return;}
    if(this.selectedSub!==auth.sub){this.status('บัญชี Google เปลี่ยน · กรุณาเลือกโฟลเดอร์อีกครั้งเพื่อป้องกันนำเข้าผิดบัญชี');return;}
    this.account=auth.sub;
    this.running=true;this.stopRequested=false;this.stats={newSongs:0,updated:0,duplicates:0,conflicts:0,fonts:0,errors:0};
    this.progress(0,1);this.refreshButtons();
    this.controller=new AbortController();
    const drive=new Drive(()=>this.session()?.token,()=>this.check());
    drive.signal=()=>this.controller.signal;
    try{
      this.status('กำลังตรวจคลัง XStageWeb และ current.json บน Google Drive…');
      const rootQuery="'root' in parents and (name='XStageWeb' or name='StageWeb') and mimeType='"+MIME_FOLDER+"' and trashed=false";
      const roots=await drive.list(rootQuery);
      if(roots.length>1)fail('พบ StageWeb และ XStageWeb หลายโฟลเดอร์ · หยุดป้องกันฐานแยก');
      let rootId;
      if(roots.length){
        if(roots[0].ownedByMe===false)fail('ไม่สามารถนำเข้าไปยังโฟลเดอร์ที่ไม่ได้เป็นเจ้าของโดยไม่ได้อนุญาต');
        rootId=roots[0].id;
      }else{
        if(!this.dom['allow-create'].checked)
          fail('ไม่พบ XStageWeb ที่บัญชีนี้เข้าถึงได้ · ให้ยืนยันการสร้างคลังใหม่ก่อน (หากมีคลังเดิมที่มองไม่เห็นอย่าเพิ่งสร้าง)');
        rootId=await drive.folder('root','XStageWeb');
      }
      let {pointerFile,pointer,rows}=await loadCatalog(drive,rootId);
      if(!pointerFile){
        const rootFiles=await drive.listChildren(rootId);
        if(!rootFiles.some(x=>x.name==='.xstage-songstudio-staging.json')){
          const marker=encode({format:'xstage-songstudio-upload-staging-v1',schemaVersion:1,
            note:'Private browser import; no playable catalog published yet'});
          const hash=await core.hashBlob(marker,()=>this.check());
          await drive.upload(rootId,marker,'.xstage-songstudio-staging.json','application/json',hash);
        }
      }
      const byPair=new Map(),byCode=new Map();
      function addMaps(row){
        const code=String(row.code||'').toLowerCase();
        if(!byCode.has(code))byCode.set(code,[]);
        byCode.get(code).push(row);
        const a=row.audio?.md5Checksum,l=row.lyrics?.md5Checksum;
        if(a&&l)byPair.set(a.toLowerCase()+':'+l.toLowerCase(),row);
      }
      for(const row of rows.values())addMaps(row);
      const work=[...this.plan.fonts.map(x=>({...x,isFont:true})),
        ...this.plan.songs.map(x=>({...x,isFont:false}))];
      let revisions=[],finished=0;
      const show=(text,part=0)=>{this.status(text);this.progress(finished,work.length,part);};
      const uploadMedia=async(file,code,parts,name,mime,hash,from=0,span=1)=>{
        this.check();
        const parent=await drive.ensurePath(rootId,parts);
        const item=await drive.upload(parent,file,name,mime,hash,
          (done,total)=>show('อัปโหลด '+(file.name||name)+' · '+(done/1024/1024).toFixed(1)+' / '+(total/1024/1024).toFixed(1)+' MB',
            Math.min(.99,from+(done/Math.max(1,total))*span)));
        return {fileId:item.id,path:[...parts,name].join('/'),md5Checksum:hash,size:file.size};
      };
      const publish=async()=>{
        if(!revisions.length)return;
        this.check();
        const generation=Array.from(scope.crypto.getRandomValues(new Uint8Array(12)))
          .map(x=>x.toString(16).padStart(2,'0')).join('');
        let catalogId,deltaIds;
        const dbRoot=await drive.ensurePath(rootId,['DB']);
        const pushJson=async(name,value)=>{
          const blob=encode(value),digest=await core.hashBlob(blob,()=>this.check());
          const item=await drive.upload(dbRoot,blob,name,'application/json',digest);
          return item.id;
        };
        if(pointer&&pointer.deltaFileIds.length<32){
          const deltaId=await pushJson('catalog-delta-'+generation+'.json',
            {schemaVersion:1,upserts:revisions,removes:[]});
          catalogId=pointer.catalogFileId;
          deltaIds=[...pointer.deltaFileIds,deltaId];
        }else{
          catalogId=await pushJson('catalog-base-'+generation+'.json',
            {schemaVersion:1,songs:[...rows.values()]});
          deltaIds=[];
        }
        const next={schemaVersion:1,layoutVersion:2,generation,catalogFileId:catalogId,
          deltaFileIds:deltaIds,songCount:rows.size};
        // Verify the pointer generation again. Never blindly overwrite a PC
        // publish performed while the browser was uploading a long batch.
        const pointers=(await drive.listChildren(rootId)).filter(x=>x.name==='current.json');
        if(pointerFile){
          const current=await drive.getJson(pointerFile.id);
          if(current.generation!==pointer.generation)
            fail('มีการอัปเดตฐานเพลงจากอีกอุปกรณ์ระหว่างงาน · หยุดเพื่อไม่เขียนทับ');
        }else{
          const again=await drive.list("'"+driveId(rootId)+"' in parents and name='current.json' and trashed=false");
          if(again.length)fail('พบ current.json ใหม่จากอีกอุปกรณ์ · ยกเลิกเพื่อป้องกันฐานซ้ำ');
        }
        const blob=encode(next),hash=await core.hashBlob(blob,()=>this.check());
        if(pointerFile){
          await drive.updatePointer(pointerFile.id,blob,hash);
        }else{
          const item=await drive.upload(rootId,blob,'current.json','application/json',hash);
          pointerFile={id:item.id,name:'current.json'};
        }
        pointer=next;revisions=[];this.check();
        await this.save({status:'publishing',done:finished,total:work.length,
          generation,songCount:rows.size});
        this.status('เผยแพร่ DB แล้ว · '+rows.size.toLocaleString('th-TH')+' เพลง');
      };
      for(const item of work){
        this.check();
        try{
          if(item.isFont){
            if(!await core.validFont(item.file))throw Error('SF2/SF3 ไม่มีหัว RIFF sfbk หรือขนาดไม่สมบูรณ์');
            const hash=await core.hashBlob(item.file,()=>this.check());
            const suffix=core.ext(item.file.name),stem=safeName(item.file.name.replace(/\.[^.]+$/,''));
            const name=stem+'-'+hash.slice(0,16)+'.'+suffix;
            const path=pathFor(stem,suffix,'',name);
            await uploadMedia(item.file,stem,path.slice(0,-1),name,'application/octet-stream',hash);
            this.stats.fonts++;
          }else{
            const {audio,lrc,code,kind}=item;
            if(!await core.validAudio(audio.file))throw Error('ไฟล์ '+kind+' ไม่ผ่านการตรวจหัวไฟล์ต้นฉบับ');
            if(lrc.file.size>MAX_LRC)throw Error('LRC ใหญ่เกิน 2 MB');
            const raw=await lrc.file.text();
            const doc=core.lrcToJson(raw,code);
            const json=encode(doc);
            const [audioHash,jsonHash]=await Promise.all([
              core.hashBlob(audio.file,()=>this.check()),
              core.hashBlob(json,()=>this.check())
            ]);
            const pair=audioHash+':'+jsonHash;
            if(byPair.has(pair)){this.stats.duplicates++;finished++;show('ข้ามเพลงซ้ำ MD5: '+code);continue;}
            const candidates=byCode.get(code.toLowerCase())||[];
            const same=candidates.find(x=>String(x.audio?.md5Checksum||'').toLowerCase()===audioHash);
            if(candidates.length&&!same){this.stats.conflicts++;finished++;show('รหัสเพลงชนแต่ข้อมูลต่างกัน: '+code+' · ไม่เขียนทับ');continue;}
            const base=safeName(code);
            const folder=core.bucket(code),prefix=['AUDIO',kind];
            let media=same?.audio;
            if(!media){
              const name=base+'-'+audioHash.slice(0,16)+'.'+kind.toLowerCase();
              media=await uploadMedia(audio.file,code,[...prefix,'Songs',folder],name,
                kind==='MP3'?'audio/mpeg':'audio/mp4',audioHash,0,.83);
            }
            const jname=base+'-'+jsonHash.slice(0,16)+'.json';
            const lyric=await uploadMedia(json,code,[...prefix,'Lyrics',folder],jname,'application/json',jsonHash,.83,.09);
            const rawBlob=new Blob([raw],{type:'text/plain'});
            const lrcHash=await core.hashBlob(rawBlob,()=>this.check());
            const lname=base+'-'+lrcHash.slice(0,16)+'.lrc';
            const lrcInfo=await uploadMedia(rawBlob,code,[...prefix,'Lyrics',folder],lname,'text/plain',lrcHash,.92,.08);
            const ident=same?.webSongId||('browser/'+audioHash);
            if(rows.has(ident)&&!same)throw Error('รหัสอ้างอิงออนไลน์ชนกับเพลงอื่น');
            // Preserve the original linked MIDI/video/vocal media when only
            // a same-audio song's timed lyrics have changed.
            const record={...(same||{}),webSongId:ident,code,title:doc.title||code,
              artist:doc.artist||'',sourceFormat:kind,audio:media,lyrics:lyric,lrc:lrcInfo};
            if(same){
              const oldPair=String(same.audio?.md5Checksum||'').toLowerCase()+':'+
                String(same.lyrics?.md5Checksum||'').toLowerCase();
              byPair.delete(oldPair);
              byCode.set(code.toLowerCase(),candidates.filter(x=>x.webSongId!==ident));
            }
            rows.set(ident,record);addMaps(record);byPair.set(pair,record);
            revisions.push(record);
            this.stats[same?'updated':'newSongs']++;
            if(revisions.length>=25)await publish();
          }
        }catch(error){
          if(aborted(error)||this.stopRequested)throw error;
          // Only corrupt/incomplete LOCAL files are skippable. Drive failures,
          // auth changes and DB integrity errors must abort the whole job.
          if(!/^(?:ไฟล์ |LRC |SF2\/SF3 |รูปแบบไฟล์)/.test(String(error.message||'')))throw error;
          this.stats.errors++;
          console.warn('Skipped invalid import item:',item.key||item.relative||item.code,error?.message||error);
          this.dom.detail.textContent='ข้าม '+(item.code||item.file?.name)+': '+error.message+
            ' · ตรวจไฟล์ต้นฉบับแล้วลองใหม่ · ไม่ทำลายข้อมูลเดิม';
        }
        finished++;
        show('ตรวจเสร็จ '+finished+' / '+work.length+
          ' · ใหม่ '+this.stats.newSongs+' · อัปเดต '+this.stats.updated+
          ' · ซ้ำ '+this.stats.duplicates+' · SoundFont '+this.stats.fonts+
          ' · ผิดพลาด '+this.stats.errors);
        if(finished%5===0)await this.save({status:'uploading',done:finished,total:work.length});
      }
      await publish();
      await this.save({status:'completed',done:finished,total:work.length});
      this.progress(1,1);
      this.status('เสร็จสิ้น · เพลงใหม่ '+this.stats.newSongs+' · แก้เนื้อร้อง '+this.stats.updated+
        ' · ข้ามซ้ำ '+this.stats.duplicates+' · รหัสชน '+this.stats.conflicts+
        ' · SoundFont '+this.stats.fonts+' · ข้ามผิดพลาด '+this.stats.errors);
      try{await this.options.refresh();}catch(error){console.warn('Catalog refresh deferred:',error?.message||error);}
    }catch(error){
      this.status(aborted(error)||this.stopRequested?
        'หยุดงานแล้ว · ไฟล์ที่ส่งสำเร็จยังอยู่ · เปิดใหม่และกดทำต่อ':
        'หยุดเพราะข้อผิดพลาด: '+(error.message||error)+' · ตรวจแล้วกดทำต่อ');
      await this.save({status:'paused',total:this.plan.songs.length+this.plan.fonts.length,
        error:aborted(error)?'paused':String(error.message||error)});
    }finally{
      this.running=false;this.controller=null;this.refreshButtons();
    }
  }
}
scope.XStageCloudImport={init:(options)=>new Importer(options),Drive,loadCatalog};
})(window);
