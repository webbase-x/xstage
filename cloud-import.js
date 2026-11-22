/* X-Stage Karaoke Online: owner-only, browser-based private Drive importer.
 * Never stores Google access tokens or file bytes. Resume is at verified
 * immutable-file boundaries; an in-flight partial file may be retried.
 * Requires cloud-import-core.js, same app OAuth and explicit user consent.
 */
(function(scope){
'use strict';
const core=scope.XStageImportCore;
const driveLayout=scope.XSTAGE_DRIVE_LAYOUT||{root:'XStageKaraoke',songs:'SONGS',db:'DB',soundfont:'SOUNDFONT'};
const retiredDriveRootIds=new Set(scope.XSTAGE_RETIRED_DRIVE_ROOT_IDS||[]);
const isRetiredDriveRoot=id=>retiredDriveRootIds.has(String(id||''));
if(!core)throw Error('Cloud Import: format validation module missing');
const $=id=>document.getElementById(id);
const MIME_FOLDER='application/vnd.google-apps.folder';
const API='https://www.googleapis.com/drive/v3/files';
const UPLOAD='https://www.googleapis.com/upload/drive/v3/files';
const MiB=1024*1024,CHUNK=8*MiB,MAX_CHUNK=32*MiB,MAX_LRC=2*MiB,MAX_JSON=128*MiB;
// Larger acknowledged resumable chunks reduce request overhead on fast links.
// Every non-final Drive chunk remains a multiple of 256 KiB, and only one
// chunk per resumable session is in flight so Range checkpoints stay reliable.
function nextUploadChunk(current,bytesPerSecond,fileSize){
  if(fileSize<32*MiB)return CHUNK;
  if(bytesPerSecond>=16*MiB)return MAX_CHUNK;
  if(bytesPerSecond>=6*MiB)return 16*MiB;
  return current;
}
const MEDIA_MIME={MP3:'audio/mpeg',M4A:'audio/mp4',WAV:'audio/wav',
  AAC:'audio/aac',FLAC:'audio/flac',OGG:'audio/ogg',OGA:'audio/ogg',
  MP4:'video/mp4',WEBM:'video/webm'};
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
// Fresh XStageKaraoke layout. Catalogs refer to real Drive File IDs;
// never read, copy, or migrate the separate XStageSong library.
function pathFor(code,kind,role,name){
  const suffix=core.ext(name),id=String(code||'').toUpperCase();
  const bucket=/^[0-9A-Z]/.test(id)?id[0]:'_';
  const video=['mp4','webm','avi','mkv','mov','wmv','flv','mpeg','mpg','vob','dat'].includes(suffix);
  if(suffix==='sf2'||suffix==='sf3')return [driveLayout.soundfont,suffix.toUpperCase(),name];
  if(suffix==='xsk'||suffix==='xmid')return [driveLayout.songs,'MIDI',suffix.toUpperCase(),bucket,name];
  if(suffix==='kar')return [driveLayout.songs,'MIDI','KAR',bucket,name];
  if(suffix==='mid'||suffix==='midi')
    return [driveLayout.songs,'MIDI','MID','SONG',bucket,name];
  if(suffix==='json'||kind==='json'){
    if(role==='NCN')return [driveLayout.songs,'MIDI','NCN','LYRICS',bucket,name];
    if(role==='MID')return [driveLayout.songs,'MIDI','MID','LYRICS',bucket,name];
    if(video||['mp4','webm','avi','mkv','mov','wmv','flv','mpeg','mpg','vob','dat'].includes(String(role).toLowerCase()))
      return [driveLayout.songs,'VIDEO',String(role).toUpperCase(),'LYRICS',bucket,name];
    if(role&&role!=='KAR'&&role!=='XSK')
      return [driveLayout.songs,'AUDIO',String(role).toUpperCase(),'LYRICS',bucket,name];
    return [driveLayout.songs,'LYRICS',bucket,name]; // legacy isolated JSON path
  }
  if(video)return [driveLayout.songs,'VIDEO',suffix.toUpperCase(),'SONG',bucket,name];
  return [driveLayout.songs,'AUDIO',suffix.toUpperCase(),'SONG',bucket,name];
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
  constructor(getToken,assertLive){this.getToken=getToken;this.assertLive=assertLive;this.children=new Map();this.childNames=new Map();}
  headers(extra={}){const token=this.getToken();if(!token)fail('Google Login หมดอายุ กรุณาเข้าสู่ระบบใหม่');return {Authorization:'Bearer '+token,...extra};}
  async signedFetch(url,options={}){
    this.assertLive();
    // Google tokens last about an hour. Refresh once before a request and
    // retry a rejected 401 with the new token; do not repeat any other error.
    if(this.ensureAuth){
      try{await this.ensureAuth(false);}
      catch(error){error.code='XSTAGE_AUTH_REQUIRED';throw error;}
    }
    this.assertLive();
    let response=await fetch(url,{...options,headers:this.headers(options.headers),cache:'no-store'});
    this.assertLive();
    if(response.status===401&&this.ensureAuth){
      try{await this.ensureAuth(true);}
      catch(error){error.code='XSTAGE_AUTH_REQUIRED';throw error;}
      this.assertLive();
      response=await fetch(url,{...options,headers:this.headers(options.headers),cache:'no-store'});
      this.assertLive();
    }
    return response;
  }
  async fetch(url,options={}){
    const response=await this.signedFetch(url,options);
    if(!response.ok){
      if(response.status===401)fail('Google ไม่ยืนยันสิทธิ์ Drive หลังต่ออายุ · กดเชื่อม Google แล้วทำต่อ');
      if(response.status===403)fail('ไม่มีสิทธิ์เขียน/อ่าน XStageKaraoke ใน Google Drive นี้ · ตรวจบัญชีและ drive.file');
      if(response.status===429||response.status>=500)fail('Google Drive ให้ลองใหม่ภายหลัง (HTTP '+response.status+')');
      fail('Google Drive ไม่สำเร็จ (HTTP '+response.status+')');
    }
    return response;
  }
  async list(q){
    const rows=[],seenPageTokens=new Set();let next='';
    do{
      this.assertLive();
      const params=new URLSearchParams({q,fields:'nextPageToken,files(id,name,mimeType,size,md5Checksum,createdTime,modifiedTime,ownedByMe,parents)',
        pageSize:'1000'});
      if(next)params.set('pageToken',next);
      const result=await (await this.fetch(API+'?'+params)).json();
      if(!result || (result.files!=null&&!Array.isArray(result.files)) ||
         (result.nextPageToken!=null&&typeof result.nextPageToken!=='string'))
        fail('Google Drive ส่งรายการไฟล์ที่มีโครงสร้างไม่ถูกต้อง');
      rows.push(...(result.files||[]));
      next=result.nextPageToken||'';
      if(rows.length>300000)fail('พบไฟล์บน Drive มากเกินขีดจำกัดการตรวจต่อครั้ง');
      if(next&&seenPageTokens.has(next))
        fail('Google Drive ส่งรหัสหน้ารายการซ้ำ · หยุดเพื่อไม่ให้สแกนวนหรืออ่านฐานเพลงไม่ครบ');
      if(next)seenPageTokens.add(next);
    }while(next);
    return rows;
  }
  indexChild(parent,entry){
    const names=this.childNames.get(parent);
    if(!names)return;
    const previous=names.get(entry.name);
    // The common case is unique filenames: hold a single object rather
    // than allocating a 1-element array for every song in a huge library.
    if(!previous)names.set(entry.name,entry);
    else if(Array.isArray(previous))previous.push(entry);
    else names.set(entry.name,[previous,entry]);
  }
  async listChildren(id){
    if(this.children.has(id))return this.children.get(id);
    const query="'"+(id==='root'?'root':driveId(id))+"' in parents and trashed=false";
    const files=await this.list(query);
    const names=new Map();
    this.children.set(id,files);
    this.childNames.set(id,names);
    for(const entry of files)this.indexChild(id,entry);
    return files;
  }
  async namedChildren(parent,name){
    await this.listChildren(parent);
    const found=this.childNames.get(parent).get(name);
    return !found?[]:Array.isArray(found)?found:[found];
  }
  rememberChild(parent,entry){
    this.children.get(parent).push(entry);
    this.indexChild(parent,entry);
  }
  async folder(parent,name){
    const files=await this.namedChildren(parent,name);
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
    this.rememberChild(parent,created);
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
    // Content-Length may be omitted for chunked Drive responses. Enforce
    // the byte limit while streaming, before allocating an unbounded JSON body.
    let raw='';
    if(response.body?.getReader){
      const reader=response.body.getReader(),decoder=new TextDecoder();
      let total=0;
      try{
        while(true){
          this.assertLive();
          const {done,value}=await reader.read();
          if(done)break;
          total+=value.byteLength;
          if(total>MAX_JSON){await reader.cancel();fail('ฐานเพลงใหญ่เกินขอบเขตการอ่านอย่างปลอดภัย');}
          raw+=decoder.decode(value,{stream:true});
        }
        raw+=decoder.decode();
      }finally{try{reader.releaseLock();}catch{}}
    }else{
      // Legacy response mocks and older browsers without ReadableStream.
      raw=await response.text();
      if(new TextEncoder().encode(raw).byteLength>MAX_JSON)
        fail('ฐานเพลงใหญ่เกินขอบเขตการอ่านอย่างปลอดภัย');
    }
    let document;
    try{document=JSON.parse(raw);}catch{fail('ไฟล์ฐานเพลง JSON ไม่ถูกต้อง');}
    if(!document||typeof document!=='object'||Array.isArray(document))fail('โครงสร้าง JSON ของฐานเพลงไม่ถูกต้อง');
    return document;
  }
  async getSqlite(id){
    const response=await this.fetch(API+'/'+driveId(id)+'?alt=media');
    const max=192*1048576;
    if(Number(response.headers.get('Content-Length')||0)>max)
      fail('ฐานข้อมูล SQLite3 ใหญ่เกิน 192 MB');
    let data;
    if(response.body?.getReader){
      const reader=response.body.getReader(),pieces=[];let size=0;
      try{
        for(;;){
          this.assertLive();
          const {done,value}=await reader.read();
          if(done)break;
          size+=value.byteLength;
          if(size>max){await reader.cancel();fail('SQLite3 ใหญ่เกินขอบเขต');}
          pieces.push(value);
        }
        data=new Uint8Array(size);let offset=0;
        for(const part of pieces){data.set(part,offset);offset+=part.length;}
      }finally{try{reader.releaseLock();}catch{}}
    }else{
      data=new Uint8Array(await response.arrayBuffer());
      if(data.length>max)fail('ฐานข้อมูล SQLite3 ใหญ่เกิน 192 MB');
    }
    return data;
  }
  async metadata(id){
    const r=await this.fetch(API+'/'+driveId(id)+'?fields=id,name,mimeType,md5Checksum,size');
    return await r.json();
  }
  async upload(parent,file,name,mime,md5,onBytes){
    this.assertLive();
    const matches=await this.namedChildren(parent,name);
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
    let answer=null,start=0,retries=0,chunkSize=CHUNK,speed=0;
    const startedAt=Date.now();
    const uploadStatus=async()=>{
      // Retry only transient failures; never guess a committed byte range.
      for(let attempt=0;attempt<4;attempt++){
        this.assertLive();
        try{
          const response=await this.signedFetch(location.href,{method:'PUT',
            headers:{'Content-Range':'bytes */'+file.size},
            signal:this.signal?.()});
          if(response.status===308){
            const match=String(response.headers.get('Range')||'').match(/^bytes=0-(\d+)$/);
            return {position:match?Number(match[1])+1:0};
          }
          if(response.ok)return {complete:await response.json(),position:file.size};
          if(response.status===401)fail('Google ยังปฏิเสธโทเค็นที่ต่ออายุ · เชื่อม Google แล้วทำต่อ');
          if(response.status!==429&&response.status<500)
            fail('สอบถามตำแหน่งอัปโหลด Drive ไม่สำเร็จ (HTTP '+response.status+')');
        }catch(error){
          if(aborted(error)||error?.code==='XSTAGE_AUTH_REQUIRED'||this.signal?.()?.aborted)throw error;
          if(attempt===3)throw error;
        }
        if(attempt===3)fail('สอบถามตำแหน่งอัปโหลด Drive ไม่สำเร็จหลังลองซ้ำ');
        await sleep(Math.min(4000,350*2**attempt));
      }
      fail('ไม่สามารถยืนยันตำแหน่งอัปโหลดกับ Google Drive');
    };
    while(start<file.size){
      this.assertLive();
      const end=Math.min(start+chunkSize,file.size);
      const chunkStarted=Date.now(),chunkStartingAt=start;
      let response=null;
      try{
        response=await this.signedFetch(location.href,{method:'PUT',
          headers:{'Content-Type':mime,
            'Content-Range':'bytes '+start+'-'+(end-1)+'/'+file.size},
          body:file.slice(start,end),signal:this.signal?.()});
      }catch(error){
        if(error?.name==='AbortError'||error?.code==='XSTAGE_AUTH_REQUIRED'||
           this.signal?.()?.aborted)throw error;
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
        const duration=Math.max(.001,(Date.now()-chunkStarted)/1000);
        const currentRate=(accepted-chunkStartingAt)/duration;
        if(Number.isFinite(currentRate)&&currentRate>0){
          speed=speed?speed*.65+currentRate*.35:currentRate;
          chunkSize=nextUploadChunk(chunkSize,speed,file.size);
        }
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
      // Always report committed bytes, never bytes merely sent to the socket.
      if(onBytes){
        const elapsed=Math.max(.001,(Date.now()-startedAt)/1000);
        const measured=start/elapsed;
        onBytes(start,file.size,Number.isFinite(measured)?measured:0);
      }
    }
    if(!answer?.id)fail('Google Drive ไม่คืน File ID หลังอัปโหลด');
    const verified=answer.md5Checksum?answer:await this.metadata(answer.id);
    if(String(verified.md5Checksum||'').toLowerCase()!==md5.toLowerCase()||
       Number(verified.size)!==file.size)fail('MD5/ขนาดไฟล์ที่ Google Drive คืนมาไม่ตรงต้นฉบับ');
    const entry={...verified,id:answer.id,name,md5Checksum:md5,size:file.size};
    this.rememberChild(parent,entry);
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
  async trashFile(id){
    const response=await this.fetch(API+'/'+driveId(id)+'?fields=id,trashed',{
      method:'PATCH',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({trashed:true})
    });
    const updated=await response.json();
    if(updated.id!==id||updated.trashed!==true)
      fail('ปลดล็อกการนำเข้าบน Google Drive ไม่สำเร็จ');
  }
  async moveToFolder(id,from,to,name){
    const url=API+'/'+driveId(id)+'?addParents='+encodeURIComponent(driveId(to))+
      '&removeParents='+encodeURIComponent(driveId(from))+
      '&fields=id,name,parents';
    const response=await this.fetch(url,{method:'PATCH',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(name?{name}:{})});
    const updated=await response.json();
    if(updated.id!==id||!Array.isArray(updated.parents)||!updated.parents.includes(to))
      fail('ย้ายไฟล์ SQLite3 ไปโฟลเดอร์ใหม่ไม่สำเร็จ');
    this.children.delete(from);this.children.delete(to);
    this.childNames.delete(from);this.childNames.delete(to);
  }
}
function chooseImportRoot(roots,activeRootId){
  if(!Array.isArray(roots))fail('รายการคลังเพลงไม่ถูกต้อง');
  if(activeRootId&&isRetiredDriveRoot(activeRootId))
    fail('คลัง Google Drive ที่เลือกถูกยกเลิกแล้ว · กรุณาเปิดคลังเพลงใหม่');
  roots=roots.filter(root=>!isRetiredDriveRoot(root.id));
  const selected=activeRootId
    ?roots.find(item=>String(item.id)===String(activeRootId))
    :roots.length===1?roots[0]:null;
  if(roots.length>1&&!selected)
    fail('พบ XStageKaraoke ชื่อซ้ำหลายโฟลเดอร์ · กรุณาเลือกคลังที่ต้องการจากเมนูคลังเพลงก่อนนำเข้า');
  if(roots.length&&!selected)
    fail('คลัง XStageKaraoke ที่เลือกไม่ตรงกับบัญชีปัจจุบัน · กรุณาเปิดคลังใหม่');
  if(selected?.ownedByMe===false)
    fail('ไม่สามารถนำเข้าไปยังโฟลเดอร์ที่ไม่ได้เป็นเจ้าของโดยไม่ได้อนุญาต');
  return selected?.id||'';
}
async function loadCatalog(drive,root){
  const children=await drive.listChildren(root);
  const dbDirs=children.filter(x=>x.name===driveLayout.db&&x.mimeType===MIME_FOLDER);
  if(dbDirs.length>1)fail('พบโฟลเดอร์ DB ซ้ำใน XStageKaraoke');
  if(!dbDirs.length){
    const unexpected=children.filter(x=>!['SONGS','SOUNDFONT','BACKUP','CACHE','LOGS'].includes(x.name));
    if(unexpected.length)fail('โครงสร้าง XStageKaraoke ไม่ตรงรูปแบบใหม่ · ตรวจ DB ก่อนนำเข้า');
    return {pointerFile:null,pointer:null,rows:new Map()};
  }
  const dbChildren=await drive.listChildren(dbDirs[0].id);
  // Canonical mode: discover the one SQLite file by its name within the
  // selected XStageKaraoke/DB folder. No JSON index or external file ID.
  const canonical=dbChildren.filter(x=>x.name==='songs.sqlite3'&&x.mimeType!==MIME_FOLDER);
  if(canonical.length>1)fail('พบ songs.sqlite3 ซ้ำใน DB · ไม่เลือกไฟล์โดยคาดเดา');
  if(canonical.length){
    if(!scope.XStageDriveSQLite)fail('ไม่พบตัวอ่าน SQLite3');
    const base=await scope.XStageDriveSQLite.read(await drive.getSqlite(canonical[0].id));
    if(base.schemaVersion!==1||base.kind!=='snapshot'||!Array.isArray(base.songs))
      fail('DB/songs.sqlite3 ไม่ใช่ฐานข้อมูลเพลงที่ถูกต้อง');
    const rows=new Map();
    for(const row of base.songs){
      if(!row||typeof row.webSongId!=='string'||rows.has(row.webSongId))
        fail('ฐานเพลงมีรหัสซ้ำหรือข้อมูลไม่ถูกต้อง');
      rows.set(row.webSongId,row);
    }
    return {pointerFile:null,rows,pointer:{schemaVersion:1,layoutVersion:6,
      format:'xstage-sqlite3-v1',directFile:true,generation:base.generation,
      catalogFileId:canonical[0].id,catalogMd5:String(canonical[0].md5Checksum||''),
      deltaFileIds:[],songCount:rows.size}};
  }
  // Read current.json only to migrate an older v5 library. New publications
  // never create this file and archive the legacy copy after verification.
  const pointers=dbChildren.filter(x=>x.name==='current.json'&&x.mimeType!==MIME_FOLDER);
  if(pointers.length>1)fail('พบ current.json ซ้ำใน DB · หยุดเพื่อไม่ให้ฐานเสีย');
  if(!pointers.length){
    const markers=dbChildren.filter(x=>x.name==='.xstage-songstudio-staging.json');
    const unexpected=dbChildren.filter(x=>x.name!=='.xstage-songstudio-staging.json');
    if(unexpected.length)fail('พบข้อมูล DB แต่ไม่มี current.json · หยุดตรวจคลังใหม่ก่อน');
    if(markers.length>1)fail('พบไฟล์ staging ซ้ำใน DB');
    if(markers.length){
      const data=await drive.getJson(markers[0].id);
      if(data.format!=='xstage-songstudio-upload-staging-v1')
        fail('ตัวระบุการนำเข้าครั้งก่อนบน Drive ไม่ถูกต้อง');
    }
    return {pointerFile:null,pointer:null,rows:new Map()};
  }
  const pointer=await drive.getJson(pointers[0].id);
  if(pointer.schemaVersion!==1||![5,6].includes(pointer.layoutVersion)||
     pointer.format!=='xstage-sqlite3-v1'||typeof pointer.catalogFileId!=='string'||
     !Array.isArray(pointer.deltaFileIds)||pointer.deltaFileIds.length>32||
     new Set(pointer.deltaFileIds).size!==pointer.deltaFileIds.length||
     (pointer.layoutVersion===6&&pointer.deltaFileIds.length!==0))
    fail('DB/current.json ต้องอ้างอิงฐานเพลง .sqlite3 รูปแบบที่รองรับเท่านั้น');
  if(!scope.XStageDriveSQLite)fail('ไม่พบตัวอ่าน SQLite3');
  const base=await scope.XStageDriveSQLite.read(await drive.getSqlite(pointer.catalogFileId));
  if(base.schemaVersion!==1||base.kind!=='snapshot'||!Array.isArray(base.songs))
    fail('ฐานเพลง SQLite3 หลักของ XStageKaraoke ไม่ถูกต้อง');
  if(pointer.layoutVersion===6&&base.generation!==pointer.generation)
    fail('ฐานเพลงกำลังเปลี่ยนรุ่นจากอีกอุปกรณ์ · กรุณาโหลดใหม่');
  const rows=new Map();
  for(const x of base.songs){if(!x||typeof x.webSongId!=='string')fail('เพลงใน Catalog หลักไม่ถูกต้อง');rows.set(x.webSongId,x);}
  for(const fileId of pointer.deltaFileIds){
    const delta=await scope.XStageDriveSQLite.read(await drive.getSqlite(fileId));
    if(delta.schemaVersion!==1||delta.kind!=='delta'||
       !Array.isArray(delta.upserts)||!Array.isArray(delta.removes))
      fail('ฐานเพลง SQLite3 ส่วนอัปเดตไม่ถูกต้อง');
    for(const id of delta.removes){if(typeof id!=='string')fail('รายการลบเพลงไม่ถูกต้อง');rows.delete(id);}
    for(const row of delta.upserts){if(!row||typeof row.webSongId!=='string')fail('รายการเพลงใหม่ไม่ถูกต้อง');rows.set(row.webSongId,row);}
  }
  if(pointer.songCount!==rows.size)fail('จำนวนเพลงบน Drive ไม่ตรงกับ Catalog');
  return {pointerFile:pointers[0],pointer,rows};
}
// Publish the catalog as DB/songs.sqlite3 without current.json. All media,
// legacy delta IDs and older snapshots remain recoverable in BACKUP.
// Advisory cross-computer publisher lease. All browser devices use the same
// Drive CACHE directory and OAuth app; no lock or pointer is stored inside DB.
// Server-side version revalidation remains mandatory: Drive does not provide
// a documented transaction for the move/rename pair.
async function acquireCatalogLease(drive,cacheRoot,check,status){
  const id=Array.from(scope.crypto.getRandomValues(new Uint8Array(12)))
    .map(b=>b.toString(16).padStart(2,'0')).join('');
  const name='.xstage-import-lock-'+id+'.json';
  const blob=encode({format:'xstage-catalog-import-lock-v1',
    token:id,createdAt:new Date().toISOString()});
  const hash=await core.hashBlob(blob,check);
  const mine=await drive.upload(cacheRoot,blob,name,'application/json',hash);
  let released=false;
  const listLocks=async()=>{
    check();
    const found=await drive.list("'"+driveId(cacheRoot)+"' in parents and trashed=false");
    const now=Date.now();
    return found.filter(x=>x.name?.startsWith('.xstage-import-lock-')&&
      (!x.createdTime||now-Date.parse(x.createdTime)<5*60*1000)).sort((a,b)=>{
        const byTime=String(a.createdTime||'').localeCompare(String(b.createdTime||''));
        return byTime||String(a.id).localeCompare(String(b.id));
      });
  };
  const assertOwner=async()=>{
    const first=(await listLocks())[0];
    if(!first||first.id!==mine.id)
      fail('อีกเครื่องกำลังเผยแพร่ฐานเพลง · จะตรวจฐานล่าสุดก่อนทำต่อ');
  };
  const release=async()=>{
    if(released)return;released=true;
    try{await drive.trashFile(mine.id);}
    catch(error){console.warn('Drive lock release deferred:',error.message);}
  };
  try{
    // Give competing Drive clients a chance to publish their lock entries
    // before electing a writer. Stale locks expire after five minutes.
    await sleep(650);
    for(let attempt=0;attempt<120;attempt++){
      check();
      if((await listLocks())[0]?.id===mine.id)
        return {assertOwner,release};
      status?.('อีกเครื่องกำลังอัปเดต songs.sqlite3 · รอคิวเผยแพร่');
      await sleep(1000);
    }
    fail('มีเครื่องอื่นใช้งานฐานเพลงนานเกินไป · โปรดลองใหม่');
  }catch(error){await release();throw error;}
}
async function publishSingleCatalog({drive,rootId,pointerFile,pointer,rows,check,status}){
  check();
  const dbRoot=await drive.ensurePath(rootId,['DB']);
  const cacheRoot=await drive.ensurePath(rootId,['CACHE']);
  const backupRoot=await drive.ensurePath(rootId,['BACKUP']);
  const lease=await acquireCatalogLease(drive,cacheRoot,check,status);
  try{
  const codec=scope.XStageDriveSQLite;
  if(!codec)fail('ไม่พบตัวอ่าน SQLite3 บนเว็บ');
  const generation=Array.from(scope.crypto.getRandomValues(new Uint8Array(12)))
    .map(x=>x.toString(16).padStart(2,'0')).join('');
  const verifySource=async()=>{
    check();
    // Query Drive directly, not its cached folder listing. A different
    // browser/computer may have published while this batch was uploading.
    const canonical=await drive.list("'"+driveId(dbRoot)+
      "' in parents and name='songs.sqlite3' and trashed=false");
    if(canonical.length>1)fail('พบ songs.sqlite3 ซ้ำใน DB');
    if(pointer?.directFile){
      if(canonical.length!==1||canonical[0].id!==pointer.catalogFileId)
        fail('ฐาน songs.sqlite3 เปลี่ยนจากอีกอุปกรณ์ระหว่างนำเข้า');
      const meta=await drive.metadata(pointer.catalogFileId);
      if(pointer.catalogMd5&&String(meta.md5Checksum||'')!==pointer.catalogMd5)
        fail('ฐาน SQLite ถูกแก้ไขจากอีกอุปกรณ์ · หยุดเพื่อไม่เขียนทับ');
    }else{
      if(canonical.length)fail('มีฐาน songs.sqlite3 ใหม่แล้ว · เปิดคลังใหม่ก่อนเผยแพร่');
      const legacy=await drive.list("'"+driveId(dbRoot)+
        "' in parents and name='current.json' and trashed=false");
      if(pointerFile){
        if(legacy.length!==1||legacy[0].id!==pointerFile.id)
          fail('ฐานเดิม current.json เปลี่ยนจากอีกอุปกรณ์');
        const old=await drive.getJson(pointerFile.id);
        if(old.generation!==pointer.generation||
          old.catalogFileId!==pointer.catalogFileId)
          fail('มีการนำเข้าจากอีกอุปกรณ์ระหว่างงาน · หยุดเพื่อรักษาข้อมูล');
      }else if(legacy.length){
        fail('มีฐานเดิมเพิ่งถูกสร้างจากอีกอุปกรณ์ · หยุดเพื่อไม่เขียนทับ');
      }
    }
  };
  await verifySource();
  status?.('กำลังสร้าง DB/songs.sqlite3 สำหรับ '+rows.size.toLocaleString('th-TH')+' เพลง');
  const bytes=await codec.create('snapshot',[...rows.values()],[],generation);
  const local=await codec.read(bytes);
  if(local.kind!=='snapshot'||local.songs.length!==rows.size||
     local.generation!==generation)fail('ฐาน SQLite3 ในเครื่องตรวจสอบไม่ผ่าน');
  const blob=new Blob([bytes],{type:'application/vnd.sqlite3'});
  const digest=await core.hashBlob(blob,check);
  const staged=await drive.upload(cacheRoot,blob,'songs-stage-'+generation+'.sqlite3',
    'application/vnd.sqlite3',digest);
  const uploaded=await codec.read(await drive.getSqlite(staged.id));
  if(uploaded.kind!=='snapshot'||uploaded.generation!==generation||
     uploaded.songs.length!==rows.size)
    fail('ฐาน SQLite3 บน Drive ตรวจสอบไม่ผ่าน · ยังไม่แทนที่ฐานเดิม');
  await lease.assertOwner();
  await verifySource();
  // File IDs of the old v5 snapshots/deltas remain valid after moving them.
  // The old pointer stays available until the new DB is verified in place.
  const older=(await drive.listChildren(dbRoot)).filter(x=>
    /\.sqlite3$/i.test(x.name)&&x.mimeType!==MIME_FOLDER);
  for(let i=0;i<older.length;i++){
    check();
    status?.('สำรองฐานก่อนหน้า '+(i+1)+'/'+older.length);
    await drive.moveToFolder(older[i].id,dbRoot,backupRoot);
  }
  try{
    await drive.moveToFolder(staged.id,cacheRoot,dbRoot,'songs.sqlite3');
    const active=(await drive.listChildren(dbRoot)).filter(x=>
      /\.sqlite3$/i.test(x.name)&&x.mimeType!==MIME_FOLDER);
    if(active.length!==1||active[0].id!==staged.id||active[0].name!=='songs.sqlite3')
      fail('DB ต้องมี songs.sqlite3 เพียงไฟล์เดียว');
    const final=await codec.read(await drive.getSqlite(staged.id));
    if(final.kind!=='snapshot'||final.generation!==generation||
       final.songs.length!==rows.size)
      fail('อ่าน SQLite3 จาก DB หลังเผยแพร่ไม่ผ่าน · สำเนาเก่าอยู่ BACKUP');
  }catch(error){
    // Restore the same known-good DB File ID if an in-place switch fails.
    if(pointer?.directFile){
      try{
        const suspect=await drive.list("'"+driveId(dbRoot)+
          "' in parents and name='songs.sqlite3' and trashed=false");
        for(const file of suspect){
          if(file.id===pointer.catalogFileId)continue;
          await drive.moveToFolder(file.id,dbRoot,backupRoot,
            'songs-failed-'+generation+'.sqlite3');
        }
        const present=await drive.list("'"+driveId(dbRoot)+
          "' in parents and name='songs.sqlite3' and trashed=false");
        if(!present.some(x=>x.id===pointer.catalogFileId))
          await drive.moveToFolder(pointer.catalogFileId,backupRoot,dbRoot,'songs.sqlite3');
      }catch(restoreError){
        console.error('Cannot restore last verified SQLite; BACKUP is preserved',restoreError);
      }
    }
    throw error;
  }
  // Only after the playable snapshot is verified may the legacy JSON pointer
  // and temporary import marker leave DB. Never delete their backups.
  const oldJson=(await drive.listChildren(dbRoot)).filter(x=>
    x.mimeType!==MIME_FOLDER&&
    (x.name==='current.json'||x.name==='.xstage-songstudio-staging.json'));
  for(const legacy of oldJson)await drive.moveToFolder(legacy.id,dbRoot,backupRoot);
  const next={schemaVersion:1,layoutVersion:6,format:'xstage-sqlite3-v1',
    directFile:true,generation,catalogFileId:staged.id,catalogMd5:digest,
    deltaFileIds:[],songCount:rows.size};
  status?.('เผยแพร่ DB/songs.sqlite3 โดยตรง · '+rows.size.toLocaleString('th-TH')+' เพลง');
  return {pointerFile:null,pointer:next};
  }finally{await lease.release();}
}
// Global raw-MIDI content identity. Package filenames, lyrics, source codes and
// folders cannot create a second song when the enclosed MIDI bytes match.
async function buildMidiIndex(rows,drive,check){
  const hashes=new Map();
  let duplicates=0,backfilled=0;
  for(const [id,row] of rows){
    check();
    let hash=String(row.midiHash||row.midi?.md5Checksum||'').toLowerCase();
    if(!/^[0-9a-f]{32}$/.test(hash)){
      const kind=row.xmid?'xmid':row.xsk?'xsk':'';
      if(!kind)continue;
      const media=row[kind];
      if(!media?.fileId)fail('ฐานเพลงมี '+kind.toUpperCase()+' ที่ไม่พบ File ID');
      const reader=kind==='xmid'?scope.XStageXmid:scope.XStageXsk;
      if(!reader?.openPackage)fail('ไม่พบเครื่องอ่าน '+kind.toUpperCase());
      const packed=new Blob([await drive.getSqlite(media.fileId)]);
      const opened=await reader.openPackage(packed);
      hash=await core.hashBlob(opened.midi,check);
      row.midiHash=hash;backfilled++;
    }
    if(!/^[0-9a-f]{32}$/.test(hash))continue;
    const prev=hashes.get(hash);
    if(prev&&prev.webSongId!==id){
      // Old catalog is preserved in BACKUP; new canonical DB keeps one entry.
      rows.delete(id);duplicates++;continue;
    }
    hashes.set(hash,row);
  }
  return {hashes,duplicates,backfilled};
}
function distinctImportCode(requested,rawMidiHash,byCode){
  const code=String(requested||'').trim();
  if(!byCode.get(code.toLowerCase())?.length)return code;
  const stem=code.slice(0,Math.max(1,64-17));
  for(let size=8;size<=16;size+=4){
    const alias=stem+'-'+rawMidiHash.slice(0,size);
    if(!byCode.get(alias.toLowerCase())?.length)return alias;
  }
  fail('เพลง MIDI ต่างแหล่งมีรหัสที่แยกกันไม่ได้');
}
class Importer {
  constructor(options){
    this.options=options;this.selected=null;this.plan=null;this.running=false;this.paused=false;this.stopRequested=false;
    this.controller=null;this.folderHandle=null;this.saved=null;this.chosenItems=new Set();this.completed=false;this.authRequired=false;this.stats={newSongs:0,updated:0,duplicates:0,conflicts:0,fonts:0,errors:0};
    this.dom={};
    for(const key of ['open','dialog','close','pick','input','scan','start','pause','resume','cancel',
      'allow-create',
      'source','total','ready','fonts','blocked','examples','progress','progress-label',
      'status','detail'])this.dom[key]=$('cloud-import-'+key);
    this.dom.pickFallback=$('cloud-import-pick-fallback');
    this.dom.selection=$('cloud-import-selection');
    this.dom.selectionList=$('cloud-import-selection-list');
    this.dom.selectionCount=$('cloud-import-selection-count');
    this.dom.actionHint=$('cloud-import-action-hint');
    this.dom.done=$('cloud-import-done');
    this.dom.reauthorize=$('cloud-import-reauthorize');
    this.dom.consolidate=$('cloud-import-consolidate');
    this.dom.consolidate?.addEventListener('click',()=>{void this.consolidate();});
    this.dom.reauthorize?.addEventListener('click',()=>{void this.reauthorize();});
    this.dom.done?.addEventListener('click',()=>this.close());
    $('cloud-import-select-all')?.addEventListener('click',()=>this.selectEveryItem(true));
    $('cloud-import-select-none')?.addEventListener('click',()=>this.selectEveryItem(false));
    this.expandedGroups=new Set();
    this.groupPageSizes=new Map();
    this.dom.selectionList?.addEventListener('click',event=>{
      const trigger=event.target.closest?.('[data-import-toggle],[data-import-more]');
      if(!trigger)return;
      const key=trigger.dataset.importToggle||trigger.dataset.importMore;
      if(trigger.dataset.importToggle){
        if(this.expandedGroups.has(key))this.expandedGroups.delete(key);
        else this.expandedGroups.add(key);
      }else this.groupPageSizes.set(key,(this.groupPageSizes.get(key)||80)+80);
      this.renderSelection();
    });
    this.dom.selectionList?.addEventListener('change',event=>{
      const input=event.target;
      if(!input?.matches?.('input[data-import-group],input[data-import-item]'))return;
      if(input.dataset.importItem!==undefined){
        // A song may be a MIDI + lyrics + timing bundle. Select the whole
        // validated entry to avoid importing incomplete songs.
        if(input.checked)this.chosenItems.add(input.dataset.importItem);
        else this.chosenItems.delete(input.dataset.importItem);
      }else{
        const group=this.importGroups().find(group=>group.key===input.dataset.importGroup);
        if(!group)return;
        for(const entry of group.entries){
          if(input.checked)this.chosenItems.add(entry.key);
          else this.chosenItems.delete(entry.key);
        }
      }
      this.renderSelection();this.refreshButtons();
    });
    this.videoEditor=scope.XStageVideoEditor?.init(this)||null;
    this.dom.open?.addEventListener('click',()=>this.open());
    this.dom.gateOpen=$('cloud-import-open-gate');
    this.dom.gateOpen?.addEventListener('click',()=>this.open());
    this.dom.close?.addEventListener('click',()=>this.close());
    this.dom.dialog?.addEventListener('cancel',event=>{event.preventDefault();this.close();});
    this.dom.pick?.addEventListener('click',()=>this.choose());
    this.dom.pickFallback?.addEventListener('click',()=>this.chooseLegacy());
    this.dom.scan?.addEventListener('click',()=>this.inspect());
    this.dom.start?.addEventListener('click',()=>this.start());
    this.dom.pause?.addEventListener('click',()=>this.stop('พักงาน'));
    this.dom.cancel?.addEventListener('click',()=>this.stop('ยกเลิกงาน · เก็บรายการที่ทำเสร็จไว้บน Drive'));
    this.dom.resume?.addEventListener('click',()=>this.resume());
    this.dom.input?.addEventListener('change',async()=>{
      const files=Array.from(this.dom.input.files||[]);
      const shouldResume=this.resumeAfterPicker;
      this.resumeAfterPicker=false;
      try{
        if(!files.length)return;
        await this.acceptFiles(files.map(file=>({file,relative:file.webkitRelativePath||file.name})),null);
        if(shouldResume)await this.start();
      }catch(error){this.status('ตรวจโฟลเดอร์ไม่สำเร็จ: '+error.message);}
      finally{this.dom.input.value='';}
    });
    this.dom.input?.addEventListener('cancel',()=>{this.resumeAfterPicker=false;});
    scope.addEventListener('pagehide',()=>this.stop('ปิดหน้าเว็บ · หยุดและจดจำจุดทำต่อ'));
    const authUpdated=()=>{
      const auth=this.session();
      // Explicit login performed elsewhere in the app may renew the same
      // account. Preserve the plan and clear only its expired-token warning.
      if(auth?.sub&&auth.sub===this.selectedSub&&
         Number(auth.expiresAt)>Date.now()+60000&&this.authRequired){
        this.authRequired=false;
        if(this.saved){
          this.saved.error='';
          void checkpoint(auth.sub,this.saved);
        }
        this.status('Google เชื่อมต่อแล้ว · กดทำต่อเพื่อใช้ไฟล์ที่ยังไม่เสร็จ');
      }
      this.updateOpen();this.refreshButtons();
    };
    scope.addEventListener('xstage:auth-ready',authUpdated);
    scope.addEventListener('xstage:auth-refreshed',authUpdated);
    scope.addEventListener('xstage:auth-cleared',()=>{
      this.stop('ออกจาก Google · พักงานทันที');
      this.selected=null;this.plan=null;this.folderHandle=null;this.selectedSub='';
      this.videoEditor?.releasePreview();this.videoEditor?.setPlan(null);
      this.updateOpen();this.refreshButtons();
    });
    this.updateOpen();
  }
  session(){return this.options.session();}
  updateOpen(){
    if(!this.dom.open)return;
    const auth=this.session();
    const verified=!!auth?.token&&!!auth?.sub;
    this.dom.open.hidden=!verified;
    this.dom.open.disabled=this.running||this.lockPending||!verified;
    if(this.dom.gateOpen){this.dom.gateOpen.hidden=!verified;
      this.dom.gateOpen.disabled=this.running||this.lockPending||!verified;}
  }
  status(message){if(this.dom.status)this.dom.status.textContent=message;}
  progress(index,total,ratio=0){
    const percent=Math.max(0,Math.min(100,Math.round((index+ratio)*100/Math.max(1,total))));
    this.dom.progress.value=percent;
    this.dom['progress-label'].textContent=percent+'%';
  }
  updateVideoStats(){
    if(!this.plan)return;
    const editor=this.videoEditor;
    const pending=editor?.pendingCount()||0;
    const ready=this.plan.songs.length-pending+this.plan.midis.length+
      this.plan.xsks.length;
    this.dom.ready.textContent=ready.toLocaleString('th-TH');
    this.dom.blocked.textContent=(this.plan.blocked.length+pending).toLocaleString('th-TH');
    const samples=this.plan.blocked.slice(0,6).map(x=>x.key+' · '+x.reason);
    if(pending)samples.push('วิดีโอ '+pending+' รายการรอตรวจชื่อเพลง/นักร้องและยืนยันรูปแบบเนื้อร้อง');
    this.dom.examples.textContent=samples.join('\n')+
      (this.plan.blocked.length>6?'\nและอีก '+(this.plan.blocked.length-6)+' ชุด':'');
    this.refreshButtons();
  }
  itemKey(item){
    return String(item.relative||item.key||item.file?.name||item.midi?.relative||
      item.audio?.relative||item.code||'').normalize('NFC');
  }
  selectableItems(){
    if(!this.plan)return [];
    return [...this.plan.songs.map(item=>({item,label:item.code||item.audio?.file?.name||item.key,type:'เพลง'})),
      ...this.plan.midis.map(item=>({item,label:item.code||item.midi?.file?.name||item.key,type:'MIDI/NCN'})),
      ...this.plan.xsks.map(item=>({item,label:item.code||item.file?.name||item.key,type:item.kind})),
      ...this.plan.fonts.map(item=>({item,label:item.file?.name||item.relative,type:'SoundFont'}))]
      .map((entry,index)=>({...entry,key:index+':'+this.itemKey(entry.item)}));
  }
  importFileList(item){
    const found=[];
    const seen=new Set();
    for(const value of [item.file,item.audio,item.video,item.midi,item.lyr,
                        item.cur,item.lrc,item.json]){
      const file=value?.file||value;
      if(!file||typeof file.size!=='number'||!file.name)continue;
      const key=String(value?.relative||file.webkitRelativePath||file.name)+'|'+file.size;
      if(seen.has(key))continue;
      seen.add(key);found.push({file,relative:String(value?.relative||file.webkitRelativePath||file.name)});
    }
    return found;
  }
  importGroups(){
    if(this.groupCache)return this.groupCache;
    const groups=new Map();
    for(const entry of this.selectableItems()){
      const files=this.importFileList(entry.item);
      const relative=String(entry.item.relative||entry.item.midi?.relative||
        entry.item.audio?.relative||files[0]?.relative||'').replace(/\\/g,'/');
      // Only display a 0–9/A–Z directory when it really exists in the
      // selected folder. Never invent empty alphabet buckets.
      const folders=relative.split('/').slice(0,-1);
      const actual=folders.find(folder=>/^[0-9A-Za-z]$/.test(folder));
      const groupKey=entry.type==='SoundFont'?'soundfont':actual?'folder:'+actual.toUpperCase():'root';
      if(!groups.has(groupKey))groups.set(groupKey,{
        key:groupKey,label:groupKey==='soundfont'?'SoundFont':
          actual?'โฟลเดอร์ '+actual.toUpperCase():'ไฟล์นอกโฟลเดอร์ 0–9 / A–Z',
        entries:[],bytes:0,fileCount:0
      });
      const group=groups.get(groupKey);
      group.entries.push(entry);
      group.bytes+=files.reduce((sum,file)=>sum+file.file.size,0);
      group.fileCount+=files.length;
    }
    this.groupCache=[...groups.values()].sort((a,b)=>{
      const score=g=>g.key.startsWith('folder:')?0:g.key==='root'?1:2;
      return score(a)-score(b)||a.label.localeCompare(b.label,'en',{numeric:true});
    });
    return this.groupCache;
  }
  importSize(bytes){
    if(!Number.isFinite(bytes)||bytes<0)return '0 B';
    if(bytes<1024)return bytes+' B';
    const units=['KB','MB','GB','TB'];
    let n=bytes/1024,index=0;
    while(n>=1024&&index<units.length-1){n/=1024;index++;}
    return n.toLocaleString('th-TH',{maximumFractionDigits:1})+' '+units[index];
  }
  selectEveryItem(checked){
    if(this.running)return;
    for(const entry of this.selectableItems()){
      if(checked)this.chosenItems.add(entry.key);
      else this.chosenItems.delete(entry.key);
    }
    this.renderSelection();this.refreshButtons();
  }
  renderSelectionCount(){
    const groups=this.importGroups();
    const selected=groups.filter(group=>
      group.entries.every(entry=>this.chosenItems.has(entry.key)));
    const songs=groups.reduce((n,group)=>n+group.entries.filter(entry=>this.chosenItems.has(entry.key)).length,0);
    const size=groups.reduce((n,group)=>n+group.entries.reduce((sum,entry)=>
      sum+(this.chosenItems.has(entry.key)?
        this.importFileList(entry.item).reduce((x,f)=>x+f.file.size,0):0),0),0);
    if(this.dom.selectionCount)this.dom.selectionCount.textContent=
      selected.length+' / '+groups.length+' กลุ่ม · '+songs+' รายการ · '+this.importSize(size);
  }
  renderSelection(){
    if(!this.dom.selectionList)return;
    const groups=this.importGroups();
    this.dom.selection.hidden=!groups.length;
    const fragment=document.createDocumentFragment();
    for(const group of groups){
      const wrapper=document.createElement('div');
      wrapper.className='cloud-import-folder';
      const row=document.createElement('div');
      row.className='cloud-import-selection-item';
      const check=document.createElement('input');
      check.type='checkbox';check.dataset.importGroup=group.key;
      check.setAttribute('aria-label','เลือกนำเข้าทั้งกลุ่ม '+group.label);
      const count=group.entries.filter(entry=>this.chosenItems.has(entry.key)).length;
      check.checked=count===group.entries.length;
      check.indeterminate=count>0&&count<group.entries.length;
      check.disabled=this.running;
      const toggle=document.createElement('button');
      toggle.type='button';toggle.className='cloud-import-folder-toggle';
      toggle.dataset.importToggle=group.key;
      const expanded=this.expandedGroups.has(group.key);
      toggle.setAttribute('aria-expanded',String(expanded));
      toggle.textContent=(expanded?'▾ ':'▸ ')+group.label;
      const type=document.createElement('small');
      type.textContent=group.entries.length.toLocaleString('th-TH')+' รายการ · '+
        group.fileCount.toLocaleString('th-TH')+' ไฟล์ · '+this.importSize(group.bytes);
      row.append(check,toggle,type);
      wrapper.append(row);
      if(expanded){
        const detailContainer=document.createElement('div');
        detailContainer.className='cloud-import-folder-files';
        // Only create visible rows. Large music folders may have 100,000+ files.
        const pageSize=this.groupPageSizes.get(group.key)||80;
        // Show individual selectable import entries. For NCN or media+lyrics
        // sets, one entry remains atomic so that its required sidecars travel
        // together. Only the visible slice creates DOM nodes.
        const visible=group.entries.slice(0,pageSize);
        for(const entry of visible){
          const files=this.importFileList(entry.item);
          const row=document.createElement('label');
          row.className='cloud-import-file-row cloud-import-file-choice';
          const checkbox=document.createElement('input');
          checkbox.type='checkbox';
          checkbox.dataset.importItem=entry.key;
          checkbox.checked=this.chosenItems.has(entry.key);
          checkbox.disabled=this.running;
          const label=document.createElement('span');
          const main=files[0];
          label.textContent=main?.file.name||entry.label||'รายการเพลง';
          label.title=files.map(f=>f.relative).join('\\n');
          const detail=document.createElement('small');
          const size=files.reduce((sum,f)=>sum+f.file.size,0);
          detail.textContent=(files.length>1?files.length+' ไฟล์ · ':'')+
            this.importSize(size);
          row.append(checkbox,label,detail);
          detailContainer.append(row);
        }
        if(group.entries.length>pageSize){
          const more=document.createElement('button');
          more.type='button';more.className='cloud-import-show-more';
          more.dataset.importMore=group.key;
          more.textContent='แสดงอีก '+Math.min(80,group.entries.length-pageSize).toLocaleString('th-TH')+' รายการ';
          detailContainer.append(more);
        }
        wrapper.append(detailContainer);
      }
      fragment.append(wrapper);
    }
    const scrollTop=this.dom.selectionList.scrollTop;
    this.dom.selectionList.replaceChildren(fragment);
    this.dom.selectionList.scrollTop=scrollTop;
    this.renderSelectionCount();
  }
  refreshButtons(){
    const candidates=this.selectableItems();
    const approved=candidates.filter(entry=>this.chosenItems.has(entry.key)&&
      (!entry.item.video||this.videoEditor?.get(entry.item)));
    const resumable=!!this.saved&&['uploading','publishing','paused','running'].includes(this.saved.status);
    const needsGoogle=this.authRequired||(
      resumable&&/auth-required|Google Login หมดอายุ|Google ต้องการ|Google ไม่ยืนยันสิทธิ์/i.test(
        String(this.saved?.error||'')));
    for(const input of this.dom.selectionList?.querySelectorAll('input[type="checkbox"]')||[])
      input.disabled=this.running;
    this.dom.start.textContent=this.completed?
      'เริ่มตรวจ MD5 และนำเข้าเพิ่ม ('+approved.length.toLocaleString('th-TH')+')':
      'เริ่มตรวจ MD5 และนำเข้า ('+approved.length.toLocaleString('th-TH')+')';
    if(this.dom.done)this.dom.done.textContent=this.completed?'เสร็จแล้ว · ปิด':'ปิดหน้าต่าง';
    const verified=!!this.session()?.token&&!!this.session()?.sub;
    this.dom.start.disabled=this.running||this.lockPending||!approved.length||!verified||needsGoogle;
    if(this.dom.consolidate)this.dom.consolidate.disabled=
      this.running||this.lockPending||!verified||needsGoogle;
    if(this.dom.done)this.dom.done.disabled=false;
    this.dom.start.hidden=!!this.running;
    this.dom.pause.disabled=!this.running;
    this.dom.pause.hidden=!this.running;
    this.dom.cancel.disabled=!this.running;
    this.dom.cancel.hidden=true;
    this.dom.resume.disabled=this.running||this.lockPending||!resumable||!verified||needsGoogle;
    this.dom.resume.hidden=this.running||!resumable||needsGoogle;
    if(this.dom.reauthorize){
      this.dom.reauthorize.hidden=this.running||!needsGoogle;
      this.dom.reauthorize.disabled=this.running||this.lockPending||!this.options.reconnect;
    }
    this.dom.pick.disabled=this.running;
    if(this.dom.pickFallback)this.dom.pickFallback.disabled=this.running;
    this.dom.scan.disabled=this.running||!this.selected;
    this.dom.scan.hidden=!this.selected||this.running;
    if(this.dom.actionHint){
      const pending=this.videoEditor?.pendingCount()||0;
      this.dom.actionHint.textContent=this.running?
        'กำลังตรวจสอบและนำเข้า · หยุดชั่วคราวได้โดยไม่ลบไฟล์ที่อัปโหลดสำเร็จ':
        needsGoogle?'Google ต้องการยืนยันสิทธิ์ใหม่ · กด “เชื่อม Google ใหม่และทำต่อ” ครั้งเดียว':
        !verified?'กำลังรอยืนยันบัญชี Google · ปุ่มนำเข้าจะพร้อมเมื่อยืนยันเสร็จ':
        this.lockPending?'กำลังเตรียมงานนำเข้า…':
        approved.length?'พร้อมตรวจเนื้อหา/MD5 และนำเข้า '+approved.length.toLocaleString('th-TH')+
          ' รายการ · จะข้ามไฟล์ซ้ำและชุดที่ตรวจไม่ผ่าน':
        candidates.some(entry=>!entry.item.video||this.videoEditor?.get(entry.item))?
          'ยังไม่ได้เลือกรายการ · เลือกในรายการด้านบนหรือกด “เลือกทั้งหมด”':
        pending?'มีวิดีโอ '+pending.toLocaleString('th-TH')+
          ' รายการรอยืนยันข้อมูล · บันทึกข้อมูลวิดีโอหรือเลือกไฟล์เพลงอื่นก่อนเริ่ม':
        candidates.length?'ยังไม่ได้เลือกรายการ · เลือกในรายการด้านบนหรือกด “เลือกทั้งหมด”':
        'เลือกโฟลเดอร์เพลงก่อนเริ่ม · ระบบยังไม่มีรายการพร้อมนำเข้า';
    }
    this.updateOpen();
  }
  onVideoApproved(item){
    const entry=this.selectableItems().find(entry=>entry.item===item);
    if(entry)this.chosenItems.add(entry.key);
    this.renderSelection();
    this.updateVideoStats();
    this.status('บันทึกข้อมูลวิดีโอแล้ว · พร้อมตรวจ MD5 และนำเข้ารายการที่เลือก');
  }
  async open(){
    if(!this.session()?.token||!this.session()?.sub){
      this.status('กรุณารอ Google Login ยืนยันบัญชีให้เสร็จก่อนเปิดงานนำเข้า');return;
    }
    if(!this.dom.dialog.open){
      if(this.dom.dialog.showModal)this.dom.dialog.showModal();
      else this.dom.dialog.setAttribute('open','');
    }
    this.saved=await checkpoint(this.session().sub,undefined);
    if(this.saved&&['uploading','publishing','paused','running'].includes(this.saved.status)&&!this.selected){
      this.status('พบงานค้างของบัญชีนี้ · กดทำต่อ (อาจต้องอนุญาตโฟลเดอร์เดิม)');
      this.dom.source.textContent='งานเดิม: '+String(this.saved.label||'โฟลเดอร์เพลง');
      if(this.saved.handle)this.folderHandle=this.saved.handle;
    }
    this.refreshButtons();
  }
  close(){
    this.resumeAfterPicker=false;
    if(this.running)this.stop('ปิดหน้าต่าง · งานถูกพักโดยไม่ลบไฟล์ที่ส่งสำเร็จ');
    this.videoEditor?.releasePreview();
    if(this.dom.dialog.close)this.dom.dialog.close();
    else this.dom.dialog.removeAttribute('open');
  }
  chooseLegacy(){
    if(this.running)return;
    // The upload-style directory picker is a user-initiated alternative when
    // Chromium blocks a sensitive folder in showDirectoryPicker. It only reads
    // the user-selected files, never modifies the workspace or system files.
    this.dom.input.value='';
    this.dom.input.click();
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
        if(e?.name==='AbortError'){
          // Chromium uses AbortError both for Cancel and for a restricted
          // folder ('contains system files'). Do not silently retry a cancelled
          // picker; offer an explicit upload-style directory picker instead.
          this.resumeAfterPicker=false;
          this.status('ยกเลิกการเลือก หรือ Chrome ไม่อนุญาตโฟลเดอร์นี้ · หากขึ้นข้อความว่ามีไฟล์ระบบ ให้เลือกโฟลเดอร์เพลงย่อยหรือกด “เลือกโฟลเดอร์ (วิธีสำรอง)”');
          return;
        }
        this.status('ตัวเลือกโฟลเดอร์หลักทำงานไม่ได้ · กด “เลือกโฟลเดอร์ (วิธีสำรอง)” หรือเลือกเฉพาะโฟลเดอร์เพลงย่อย: '+e.message);
        return;
      }
    }
    this.chooseLegacy();
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
    this.completed=false;
    this.selected=files;this.folderHandle=handle;
    this.selectedSub=this.session()?.sub||'';
    this.plan=core.scan(files);
    this.groupCache=null;
    this.expandedGroups.clear();
    this.groupPageSizes.clear();
    this.chosenItems=new Set();
    this.videoEditor?.setPlan(this.plan,this.saved?.videoEdits);
    // A newly scanned, complete song is selected by default. The previous
    // empty selection disabled the only import action despite telling users
    // to press Start. Unreviewed videos remain excluded until confirmed.
    for(const entry of this.selectableItems()){
      if(!entry.item.video||this.videoEditor?.get(entry.item))
        this.chosenItems.add(entry.key);
    }
    this.renderSelection();
    const hasRelativePaths=files.some(entry=>String(entry.relative||'').includes('/'));
    const totalBytes=files.reduce((sum,entry)=>sum+(entry.file||entry).size,0);
    this.dom.source.textContent='เลือกแล้ว '+files.length.toLocaleString('th-TH')+' ไฟล์ · '+this.importSize(totalBytes)+
      (handle?' (จำสิทธิ์โฟลเดอร์สำหรับทำต่อได้ถ้าเบราว์เซอร์อนุญาต)'
        :hasRelativePaths?' (เปิดใหม่ต้องเลือกโฟลเดอร์เดิมอีกครั้ง)'
        :' (เบราว์เซอร์ไม่ได้ส่งโครงสร้างโฟลเดอร์ · ตรวจสอบชุดเพลงให้ครบก่อนนำเข้า)');
    this.dom.total.textContent=this.plan.files.toLocaleString('th-TH');
    this.dom.ready.textContent=(this.plan.songs.length+this.plan.midis.length+
      this.plan.xsks.length).toLocaleString('th-TH');
    this.dom.fonts.textContent=this.plan.fonts.length.toLocaleString('th-TH');
    this.dom.blocked.textContent=this.plan.blocked.length.toLocaleString('th-TH');
    const samples=this.plan.blocked.slice(0,7).map(x=>x.key+' · '+x.reason);
    this.dom.examples.textContent=samples.join('\n')+(this.plan.blocked.length>7?'\nและอีก '+(this.plan.blocked.length-7)+' ชุด':'');
    const recognized=this.plan.songs.length+this.plan.midis.length+
      this.plan.xsks.length+this.plan.fonts.length;
    const ignored=Math.max(0,this.plan.files-recognized-this.plan.blocked.length);
    if(!recognized){
      const extensions=[...new Set(files.map(entry=>
        core.ext((entry.file||entry).name||'')).filter(Boolean))].slice(0,12);
      const details='ไม่พบไฟล์เพลงที่ระบบรองรับจาก '+files.length+' ไฟล์'+
        (extensions.length?' · ประเภทไฟล์: '+extensions.join(', '):'')+
        ' · XMID ต้องเป็นไฟล์ .xmid ที่สร้างจาก Song Studio Pro';
      this.dom.examples.textContent=[details,...samples].join('\n');
      this.dom.detail.textContent=details;
    }else if(ignored){
      this.dom.examples.textContent=[...samples,
        'ข้ามไฟล์ที่ไม่ได้อยู่ในรูปแบบที่รองรับ '+ignored+' ไฟล์'].join('\n');
    }
    this.updateVideoStats();
    this.progress(0,1);
    const selectedReady=this.selectableItems().filter(entry=>this.chosenItems.has(entry.key)&&
      (!entry.item.video||this.videoEditor?.get(entry.item))).length;
    this.status(selectedReady?'ตรวจชื่อไฟล์แล้ว · เลือกไว้ '+selectedReady.toLocaleString('th-TH')+
      ' รายการ · กด “เริ่มตรวจ MD5 และนำเข้า” ด้านล่าง':
      recognized?'ตรวจชื่อไฟล์แล้ว แต่ยังไม่มีรายการที่ผ่านเงื่อนไข · ตรวจ/บันทึกข้อมูลวิดีโอหรือเลือกไฟล์ที่พร้อม':
      'ไม่พบเพลงพร้อมนำเข้า · ตรวจชนิดไฟล์และโครงสร้างโฟลเดอร์ แล้วเลือกใหม่');
    await this.save({status:'selected',done:0,total:this.plan.songs.length+this.plan.midis.length+this.plan.xsks.length+this.plan.fonts.length});
    this.refreshButtons();
  }
  async save(extra={}){
    const auth=this.session();
    if(!auth?.sub)return;
    const data={version:1,label:this.dom.source.textContent,updatedAt:Date.now(),
      count:(this.plan?.songs.length||0)+(this.plan?.midis.length||0)+(this.plan?.xsks.length||0),
      fonts:this.plan?.fonts.length||0,videoEdits:this.videoEditor?.exportEdits()||[],...extra};
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
  async reauthorize(){
    if(this.running||this.lockPending||!this.options.reconnect)return;
    this.lockPending=true;this.refreshButtons();
    let ready=false;
    try{
      this.status('กำลังต่ออายุ Google สำหรับบัญชีเดิม · รายการที่ส่งสำเร็จจะไม่อัปโหลดซ้ำ…');
      await this.options.reconnect();
      if(this.selectedSub&&this.selectedSub!==this.session()?.sub)
        fail('บัญชี Google ไม่ตรงกับงานเดิม · จะไม่อัปโหลดไปยังบัญชีอื่น');
      ready=true;
      this.authRequired=false;
      if(this.saved){
        this.saved.error='';
        await checkpoint(this.session().sub,this.saved);
      }
      this.status('ต่ออายุ Google สำเร็จ · กำลังทำงานต่อจากไฟล์ที่ยังไม่เสร็จ');
    }catch(error){
      this.authRequired=true;
      this.status('Google ยังต้องการการยืนยันจากผู้ใช้: '+(error.message||error)+
        ' · งานนำเข้ายังค้างอยู่และไม่ลบไฟล์เดิม');
    }finally{
      this.lockPending=false;this.refreshButtons();
    }
    // File picker requires a fresh user gesture after authorization; never
    // try to silently open a protected folder after an async OAuth popup.
    if(ready){
      if(this.selected&&this.plan)await this.start();
      else this.status('Google พร้อมแล้ว · กด “ทำต่อ” เพื่อเลือกโฟลเดอร์เดิม');
    }
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
        this.resumeAfterPicker=true;
        await this.choose();
        if(!this.selected)return;
        this.resumeAfterPicker=false;
      }
    }
    await this.start();
  }
  async consolidate(){
    if(this.running||this.lockPending)return;
    const auth=this.session();
    const notify=message=>{
      this.status(message);this.options.onConsolidationStatus?.(message);
    };
    if(!auth?.token||!auth.sub){notify('กรุณาเชื่อม Google ก่อนรวมฐานเพลง');return;}
    const work=async()=>{
      this.running=true;this.stopRequested=false;this.account=auth.sub;
      this.controller=new AbortController();this.refreshButtons();
      const drive=new Drive(()=>this.session()?.token,()=>this.check());
      drive.ensureAuth=force=>this.options.ensureAuth?.(force);
      drive.signal=()=>this.controller.signal;
      try{
        const rootQuery="name='"+driveLayout.root+"' and mimeType='"+MIME_FOLDER+"' and trashed=false";
        const roots=(await drive.list(rootQuery)).filter(x=>!isRetiredDriveRoot(x.id));
        const rootId=chooseImportRoot(roots,String(auth.rootId||''));
        if(!rootId)fail('ไม่พบโฟลเดอร์ XStageKaraoke · ไม่สร้างคลังใหม่ขณะรวมฐาน');
        const {pointerFile,pointer,rows}=await loadCatalog(drive,rootId);
        if(!pointer){notify('ยังไม่มีฐานเพลงบน Drive ให้รวม');return;}
        const currentFiles=(await drive.listChildren(await drive.ensurePath(rootId,['DB'])))
          .filter(x=>/\.sqlite3$/i.test(x.name));
        if(pointer.directFile&&currentFiles.length===1&&
           currentFiles[0].name==='songs.sqlite3'&&
           currentFiles[0].id===pointer.catalogFileId&&
           !(await drive.listChildren(await drive.ensurePath(rootId,['DB']))).some(
             x=>x.name==='current.json'||x.name==='.xstage-songstudio-staging.json')){
          notify('ฐานเพลงเป็นมาตรฐานเดียวแล้ว · DB/songs.sqlite3 1 ไฟล์ · '+
            rows.size.toLocaleString('th-TH')+' เพลง');
          return;
        }
        const indexed=await buildMidiIndex(rows,drive,()=>this.check());
        if(indexed.duplicates||indexed.backfilled)
          notify('ตรวจ MIDI เดิมครบ · ซ้ำ '+indexed.duplicates+
            ' · ปรับลายนิ้วมือ MIDI '+indexed.backfilled);
        const result=await publishSingleCatalog({drive,rootId,pointerFile,pointer,rows,
          check:()=>this.check(),status:notify});
        notify('รวมฐาน SQLite3 สำเร็จ · '+
          result.pointer.songCount.toLocaleString('th-TH')+
          ' เพลง · ไฟล์เก่าทั้งหมดอยู่ BACKUP');
        await this.options.refresh?.();
      }catch(error){
        // A second machine may have completed the migration first.
        if(/จากอีกอุปกรณ์|มีฐาน songs.sqlite3 ใหม่แล้ว/.test(String(error.message||''))){
          drive.children.clear();drive.childNames.clear();
          try{
            const current=await loadCatalog(drive,
              chooseImportRoot((await drive.list("name='"+driveLayout.root+
                "' and mimeType='"+MIME_FOLDER+"' and trashed=false")).filter(
                  x=>!isRetiredDriveRoot(x.id)),String(auth.rootId||'')));
            if(current.pointer?.directFile){
              notify('อีกเครื่องรวมฐานเพลงสำเร็จแล้ว · โหลด songs.sqlite3 ล่าสุด');
              await this.options.refresh?.();
              return;
            }
          }catch(recheckError){console.warn('Retry migration status:',recheckError);}
        }
        notify('รวมฐานไม่สำเร็จ · '+error.message+
          ' · เก็บไฟล์เดิมไว้ทั้งหมดเพื่อให้ตรวจสอบได้');
      }finally{
        this.running=false;this.controller=null;this.refreshButtons();
      }
    };
    this.lockPending=true;this.refreshButtons();
    try{
      if(scope.navigator?.locks?.request){
        await scope.navigator.locks.request('xstage-drive-import-'+auth.sub,
          {mode:'exclusive',ifAvailable:true},async lock=>{
            if(!lock){notify('มีงานนำเข้าในอีกแท็บ · รวมฐานหลังงานนั้นเสร็จ');return;}
            await work();
          });
      }else await work();
    }finally{this.lockPending=false;this.refreshButtons();}
  }
  async start(){
    if(this.running||this.lockPending||!this.plan)return;
    const auth=this.session();
    if(!auth?.sub){this.status('กรุณาล็อกอิน Google ก่อน');return;}
    this.lockPending=true;this.refreshButtons();
    try{
      if(scope.navigator?.locks?.request){
        await scope.navigator.locks.request('xstage-drive-import-'+auth.sub,
          {mode:'exclusive',ifAvailable:true},async lock=>{
            if(!lock){this.status('บัญชีนี้มีงานนำเข้าในอีกแท็บ · หยุดงานซ้ำเพื่อป้องกัน DB ชนกัน');return;}
            await this.performStart();
          });
      }else await this.performStart();
    }finally{this.lockPending=false;this.refreshButtons();}
  }
  async performStart(){
    if(this.running||!this.plan)return;
    if(!this.selectableItems().some(entry=>this.chosenItems.has(entry.key)&&
      (!entry.item.video||this.videoEditor?.get(entry.item)))){
      this.status('ยังไม่มีรายการที่พร้อมนำเข้า · เลือกรายการเพลงหรือยืนยันข้อมูลวิดีโอก่อน');return;
    }
    if(!this.plan.songs.length&&!this.plan.midis.length&&!this.plan.xsks.length&&!this.plan.fonts.length){
      this.status('ไม่มีไฟล์ที่พร้อมนำเข้า · กรุณาเลือกโฟลเดอร์ใหม่หรืออัปเดตหน้าเว็บ');
      return;
    }
    const auth=this.session();
    if(!auth?.token||!auth.sub){this.status('กรุณาล็อกอิน Google ก่อน');return;}
    if(this.selectedSub!==auth.sub){this.status('บัญชี Google เปลี่ยน · กรุณาเลือกโฟลเดอร์อีกครั้งเพื่อป้องกันนำเข้าผิดบัญชี');return;}
    this.account=auth.sub;
    this.videoEditor?.releasePreview();
    this.running=true;this.stopRequested=false;this.stats={newSongs:0,updated:0,duplicates:0,conflicts:0,fonts:0,errors:0};
    this.progress(0,1);this.refreshButtons();
    this.controller=new AbortController();
    const drive=new Drive(()=>this.session()?.token,()=>this.check());
    drive.ensureAuth=force=>this.options.ensureAuth?.(force);
    drive.signal=()=>this.controller.signal;
    try{
      if(this.plan.xsks.some(x=>x.kind==='XSK')&&!scope.XStageXsk)
        fail('ยังไม่โหลดตัวอ่าน XSK2 ของเบราว์เซอร์');
      if(this.plan.xsks.some(x=>x.kind==='XMID')&&!scope.XStageXmid)
        fail('ยังไม่โหลดตัวอ่าน XMID ของเบราว์เซอร์');
      this.status('กำลังตรวจ XStageKaraoke/DB/current.json บน Google Drive…');
      // Discover the same accessible libraries as Karaoke Online, including
      // folders nested in My Drive and folders shared by another owner.
      // Restricting this search to 'root' would create another XStageKaraoke
      // when an existing library was moved or shared.
      const rootQuery="name='"+driveLayout.root+"' and mimeType='"+MIME_FOLDER+"' and trashed=false";
      const roots=(await drive.list(rootQuery)).filter(root=>!isRetiredDriveRoot(root.id));
      // Pin new uploads to the folder actually selected in Karaoke Online.
      // Do not silently use the first same-name root or create a third copy.
      const activeRootId=String(auth.rootId||'');
      if(activeRootId&&!roots.some(item=>String(item.id)===activeRootId))
        fail('โฟลเดอร์ XStageKaraoke ที่เลือกไม่พบแล้ว · กรุณาเปิดคลังเพลงใหม่');
      let rootId=chooseImportRoot(roots,activeRootId);
      if(!rootId){
        if(!this.dom['allow-create'].checked)
          fail('ไม่พบ XStageKaraoke · กรุณาอนุญาตสร้างคลังใหม่ก่อนนำเข้า');
        // Recheck immediately before creation: another tab/device may have
        // created the root since the initial listing.
        const latestRoots=(await drive.list(rootQuery)).filter(root=>!isRetiredDriveRoot(root.id));
        if(latestRoots.length)
          fail('พบ XStageKaraoke บน Google Drive ระหว่างนำเข้า · เปิดคลังที่มีอยู่ใหม่ก่อน ไม่สร้างซ้ำ');
        rootId=await drive.folder('root',driveLayout.root);
      }
      let {pointerFile,pointer,rows}=await loadCatalog(drive,rootId);
      // Create only missing directories in the NEW root, never migrate old files.
      for(const folder of ['SONGS','DB','SOUNDFONT','BACKUP','CACHE','LOGS'])
        await drive.folder(rootId,folder);
      if(pointer && ![5,6].includes(pointer.layoutVersion))
        fail('ฐานเพลงใน XStageKaraoke มีรูปแบบที่ไม่รองรับ · หยุดเพื่อไม่เขียนทับ');
      // No JSON marker is created in DB. Incomplete uploads are resumed from
      // browser checkpoints and verified media IDs; only a published SQLite
      // file becomes authoritative for playback.
      const {hashes:byMidi,duplicates:olderDuplicates,backfilled:olderHashes}=
        await buildMidiIndex(rows,drive,()=>this.check());
      if(olderDuplicates||olderHashes)this.status(
        'ตรวจฐาน MIDI เดิม: ซ้ำ '+olderDuplicates+' · ระบุลายนิ้วมือ '+olderHashes);
      const byPair=new Map(),byCode=new Map();
      function addMaps(row){
        const code=String(row.code||'').toLowerCase();
        if(!byCode.has(code))byCode.set(code,[]);
        byCode.get(code).push(row);
        const a=(row.audio||row.midi)?.md5Checksum,l=row.lyrics?.md5Checksum;
        if(a&&l)byPair.set(a.toLowerCase()+':'+l.toLowerCase(),row);
      }
      for(const row of rows.values())addMaps(row);
      // Filter the original scan objects before copying their work metadata.
      // This stays O(n) for very large music libraries (no per-file list search).
      const selectedObjects=new Set(this.selectableItems()
        .filter(entry=>this.chosenItems.has(entry.key)).map(entry=>entry.item));
      const work=[...this.plan.fonts.filter(x=>selectedObjects.has(x))
          .map(x=>({...x,isFont:true})),
        ...this.plan.songs.filter(x=>selectedObjects.has(x)&&
          (!x.video||this.videoEditor?.get(x)))
          .map(x=>({...x,isFont:false,isMidi:false})),
        ...this.plan.midis.filter(x=>selectedObjects.has(x))
          .map(x=>({...x,isFont:false,isMidi:true})),
        ...this.plan.xsks.filter(x=>selectedObjects.has(x))
          .map(x=>({...x,isFont:false,isMidi:false,isXsk:true}))];
      const pendingVideos=this.videoEditor?.pendingCount()||0;
      if(pendingVideos)this.dom.detail.textContent='ข้ามวิดีโอรอตรวจ '+pendingVideos+
        ' รายการ · กรอกข้อมูล/เนื้อร้องและบันทึกก่อนนำเข้ารอบถัดไป';
      let revisions=[],finished=0,lastProgressItem=-1,peakPart=0;
      const show=(text,part=0)=>{
        if(finished!==lastProgressItem){lastProgressItem=finished;peakPart=0;}
        peakPart=Math.max(peakPart,Math.min(1,Math.max(0,part)));
        this.status(text);this.progress(finished,work.length,peakPart);
      };
      const uploadMedia=async(file,code,parts,name,mime,hash,from=0,span=1)=>{
        this.check();
        const parent=await drive.ensurePath(rootId,parts);
        const item=await drive.upload(parent,file,name,mime,hash,
          (done,total,bytesPerSecond=0)=>show('อัปโหลด '+(file.name||name)+' · '+(done/MiB).toFixed(1)+' / '+(total/MiB).toFixed(1)+' MB'+
            (bytesPerSecond>0?' · '+(bytesPerSecond/MiB).toFixed(1)+' MB/s':''),
            Math.min(.99,from+(done/Math.max(1,total))*span)));
        return {fileId:item.id,path:[...parts,name].join('/'),md5Checksum:hash,size:file.size};
      };
      // Independent immutable song+lyrics files may upload simultaneously.
      // Await BOTH completions before updating catalog rows or publishing DB.
      // If either fails, the verified successful file is safely reused on retry.
      const uploadPair=async(first,second)=>{
        const tasks=await Promise.allSettled([first(),second()]);
        const failure=tasks.find(task=>task.status==='rejected');
        if(failure)throw failure.reason;
        return tasks.map(task=>task.value);
      };
      let normalizePending=!!(olderDuplicates||olderHashes);
      const publish=async()=>{
        if(!revisions.length&&!normalizePending&&(!pointer||pointer.directFile))return;
        for(let attempt=0;attempt<3;attempt++){
          try{
            ({pointerFile,pointer}=await publishSingleCatalog({
              drive,rootId,pointerFile,pointer,rows,check:()=>this.check(),
              status:message=>this.status(message)
            }));
            revisions=[];normalizePending=false;
            await this.save({status:'publishing',done:finished,total:work.length,
              generation:pointer.generation,songCount:rows.size});
            return;
          }catch(error){
            if(attempt>=2||!/จากอีกอุปกรณ์|มีฐาน songs.sqlite3 ใหม่แล้ว|ฐานเดิม current.json เปลี่ยน/.test(
              String(error.message||'')))throw error;
            // Another computer published before ours. Re-read the ONE current
            // DB, rebase our newly uploaded song references, and retry. Never
            // replace the other writer's songs with our stale snapshot.
            this.status('มีการนำเข้าเพลงจากเครื่องอื่น · รวมข้อมูลล่าสุดแล้วลองใหม่');
            await sleep(200*(attempt+1));
            drive.children.clear();drive.childNames.clear();
            const fresh=await loadCatalog(drive,rootId);
            const indexed=await buildMidiIndex(fresh.rows,drive,()=>this.check());
            const pending=[...revisions];
            const newCodes=new Map();
            for(const row of fresh.rows.values()){
              const code=String(row.code||'').toLowerCase();
              if(!newCodes.has(code))newCodes.set(code,[]);
              newCodes.get(code).push(row);
            }
            for(const row of pending){
              const midiHash=String(row.midiHash||row.midi?.md5Checksum||'').toLowerCase();
              if(midiHash&&indexed.hashes.has(midiHash)){
                this.stats.duplicates++;continue;
              }
              if(fresh.rows.has(row.webSongId)){
                this.stats.duplicates++;continue;
              }
              const code=String(row.code||'').toLowerCase();
              if(newCodes.get(code)?.length){
                if(!midiHash){this.stats.conflicts++;continue;}
                row.sourceCode ||= row.code;
                row.code=distinctImportCode(row.sourceCode,midiHash,newCodes);
              }
              fresh.rows.set(row.webSongId,row);
              if(midiHash)indexed.hashes.set(midiHash,row);
              const alias=String(row.code||'').toLowerCase();
              if(!newCodes.has(alias))newCodes.set(alias,[]);
              newCodes.get(alias).push(row);
            }
            rows=fresh.rows;pointer=fresh.pointer;pointerFile=fresh.pointerFile;
            revisions=pending.filter(row=>rows.get(row.webSongId)===row);
            normalizePending=!!(indexed.backfilled||indexed.duplicates);
            byPair.clear();byCode.clear();byMidi.clear();
            for(const row of rows.values())addMaps(row);
            for(const [hash,row] of indexed.hashes)byMidi.set(hash,row);
            if(!revisions.length&&!normalizePending&&pointer?.directFile)return;
          }
        }
      };
      for(const originalItem of work){
        this.check();
        let item=originalItem;
        try{
          if(item.isXsk){
            // Keep the original XSK2 on Drive. Read only its timed JSON
            // metadata now. Extract and SHA-256-verify the MIDI at play time,
            // or progressively for the first song waiting in the queue.
            const isXmid=item.kind==='XMID';
            const reader=isXmid?scope.XStageXmid:scope.XStageXsk;
            const opened=await reader.openPackage(item.file);
            const sourceCode=opened.code;
            const rawMidiHash=await core.hashBlob(opened.midi,()=>this.check());
            if(byMidi.has(rawMidiHash)){
              this.stats.duplicates++;finished++;
              show('ข้าม MIDI ซ้ำในแพ็กเกจต่างแหล่ง: '+sourceCode);continue;
            }
            const code=distinctImportCode(sourceCode,rawMidiHash,byCode);
            const identity=core.songIdentity(opened.document,sourceCode);
            if(!identity.identityComplete)
              throw Error('XSK: ชื่อเพลงหรือศิลปินจริงไม่ครบ');
            const xskHash=await core.hashBlob(item.file,()=>this.check());
            const ident='browser/'+(isXmid?'xmid':'xsk')+'/'+xskHash;
            const candidates=byCode.get(code.toLowerCase())||[];
            if(rows.has(ident)||candidates.some(x=>
              String((isXmid?x.xmid:x.xsk)?.md5Checksum||'').toLowerCase()===xskHash)){
              this.stats.duplicates++;finished++;
              show('ข้าม XSK ซ้ำ MD5: '+code);continue;
            }
            const name=safeName(code)+'-'+xskHash.slice(0,16)+(isXmid?'.xmid':'.xsk');
            const packed=await uploadMedia(item.file,code,pathFor(code,isXmid?'xmid':'xsk','',name).slice(0,-1),name,
              'application/octet-stream',xskHash,0,1);
            const record={webSongId:ident,code,sourceCode,midiHash:rawMidiHash,
              title:identity.title,artist:identity.artist,
              sourceFormat:isXmid?'XMID':'XSK',lyricsMode:'timed',
              ...(isXmid?{xmid:packed}:{xsk:packed})};
            rows.set(ident,record);addMaps(record);byMidi.set(rawMidiHash,record);
            revisions.push(record);this.stats.newSongs++;
            if(revisions.length>=25)await publish();
          }else if(item.isMidi){
            const runtime=scope.XStageBrowserMidi;
            if(!runtime)fail('ไม่พบระบบ MIDI ที่ติดมากับหน้าเว็บ · อัปเดตเว็บก่อนนำเข้า');
            const midiFile=item.midi.file,sourceCode=item.code;
            const midiHash=await core.hashBlob(midiFile,()=>this.check());
            if(byMidi.has(midiHash)){
              this.stats.duplicates++;finished++;
              show('ข้าม MIDI ซ้ำแม้ต่างชื่อ/รหัส/โฟลเดอร์: '+sourceCode);continue;
            }
            const code=distinctImportCode(sourceCode,midiHash,byCode);
            let parsed,doc,json;
            try{
              parsed=runtime.parseMidi(await midiFile.arrayBuffer());
              if(item.lyr&&item.cur){
                doc=runtime.ncnLyrics(new Uint8Array(await item.lyr.file.arrayBuffer()),
                  new Uint8Array(await item.cur.file.arrayBuffer()),code,parsed);
                // A complete MID/LYR/CUR trio can still have missing character
                // timing. Do not publish an apparently complete karaoke song
                // when the original CUR cannot time the entire LYR body.
                if(doc.metadata?.timingComplete===false)
                  throw Error('NCN CUR มีเวลาเนื้อร้องไม่ครบ · ไม่เผยแพร่ Lyrics JSON ที่มีเพียงบางส่วน');
              }else if(item.json){
                if(item.json.file.size>8*1024*1024)throw Error('Lyrics JSON ใหญ่เกิน 8 MB');
                doc=core.validLyricsJson(await item.json.file.text(),code);
              }else if(item.lrc){
                if(item.lrc.file.size>MAX_LRC)throw Error('LRC ใหญ่เกิน 2 MB');
                doc=core.lrcToJson(await item.lrc.file.text(),code);
              }else doc=runtime.midiLyrics(parsed,code);
              doc.songCode=code;
              json=encode(doc);
            }catch(error){throw Error('ไฟล์ MIDI/NCN ไม่สมบูรณ์: '+error.message);}
            const jsonHash=await core.hashBlob(json,()=>this.check());
            const pair=midiHash+':'+jsonHash;
            if(byPair.has(pair)){this.stats.duplicates++;finished++;show('ข้าม MIDI ซ้ำ MD5: '+code);continue;}
            const candidates=byCode.get(code.toLowerCase())||[];
            const same=null;
            if(candidates.length)fail('เพลง MIDI คนละแหล่งมีรหัสที่แยกกันไม่ได้');
            const type=item.kind==='XSK'?'XSK':item.kind==='NCN'?'NCN':
              item.kind==='KAR'?'KAR':'SMF';
            const base=safeName(code);
            let media=same?.midi;
            const name=base+'-'+midiHash.slice(0,16)+'.'+core.ext(midiFile.name);
            const midiFolder=item.kind==='NCN'
              ? [driveLayout.songs,'MIDI','NCN','SONG',pathFor(code,'midi','',name)[4]]
              : pathFor(code,'midi','',name).slice(0,-1);
            // KAR embeds its lyrics and needs no second artifact.
            const jname=base+'-'+jsonHash.slice(0,16)+'.json';
            const [verifiedMidi,lyrics]=await uploadPair(
              ()=>media||uploadMedia(midiFile,code,midiFolder,name,
                'audio/midi',midiHash,0,.75),
              ()=>item.kind==='KAR'?null:uploadMedia(json,code,
                pathFor(code,'json',item.kind==='NCN'?'NCN':'MID',jname).slice(0,-1),
                jname,'application/json',jsonHash,.75,.25)
            );
            media=verifiedMidi;
            // Keep lossless NCN sources in their native folders alongside the
            // separately verified timed JSON used for all player platforms.
            let ncnSource=same?.ncnSource||null;
            if(item.kind==='NCN'&&item.lyr&&item.cur&&!ncnSource){
              const bucket=pathFor(code,'midi','',code+'.mid')[4];
              const sourcePart=async(source,role,extension)=>{
                const hash=await core.hashBlob(source.file,()=>this.check());
                const sourceName=base+'-'+hash.slice(0,16)+'.'+extension;
                return uploadMedia(source.file,code,[driveLayout.songs,'MIDI','NCN',role,bucket],
                  sourceName,'application/octet-stream',hash);
              };
              const nativeMidi=media.path?.startsWith(driveLayout.songs+'/MIDI/NCN/SONG/')
                ? media : await sourcePart(item.midi,'SONG',core.ext(midiFile.name));
              const sourceLyrics=await sourcePart(item.lyr,'LYR','lyr');
              const sourceCursor=await sourcePart(item.cur,'CUR','cur');
              ncnSource={midi:nativeMidi,lyr:sourceLyrics,cur:sourceCursor};
            }
            const ident=same?.webSongId||('browser/midi/'+midiHash);
            if(rows.has(ident)&&!same)throw Error('รหัสอ้างอิง MIDI ชนเพลงอื่น');
            const identity=core.songIdentity(doc,code,same);
            const record={...(same||{}),webSongId:ident,code,sourceCode,midiHash,
              title:identity.title,artist:identity.artist,
              sourceFormat:type,midi:media,lyrics,
              ...(ncnSource?{ncnSource}: {})};
            delete record.lyr;delete record.cur;delete record.lrc;
            if(same){
              byPair.delete(String(same.midi?.md5Checksum||'').toLowerCase()+':'+
                String(same.lyrics?.md5Checksum||'').toLowerCase());
              const oldCode=String(same.code||'').toLowerCase();
              byCode.set(oldCode,(byCode.get(oldCode)||[]).filter(x=>x.webSongId!==ident));
            }
            rows.set(ident,record);addMaps(record);byPair.set(pair,record);
            byMidi.set(midiHash,record);
            revisions.push(record);this.stats[same?'updated':'newSongs']++;
            if(revisions.length>=25)await publish();
          }else if(item.isFont){
            if(!await core.validFont(item.file))throw Error('SF2/SF3 ไม่มีหัว RIFF sfbk หรือขนาดไม่สมบูรณ์');
            const hash=await core.hashBlob(item.file,()=>this.check());
            const suffix=core.ext(item.file.name),stem=safeName(item.file.name.replace(/\.[^.]+$/,''));
            const name=stem+'-'+hash.slice(0,16)+'.'+suffix;
            const path=pathFor(stem,suffix,'',name);
            await uploadMedia(item.file,stem,path.slice(0,-1),name,'application/octet-stream',hash);
            this.stats.fonts++;
          }else{
            const {audio,video,lrc,json:lyricsJson,kind}=item;
            const videoMeta=video?this.videoEditor?.get(item):null;
            if(video&&!videoMeta)throw Error('วิดีโอ: ยังไม่ได้ยืนยันข้อมูลเพลง/เนื้อร้อง');
            let code=videoMeta?.code||item.code;
            let audioFile=audio.file,videoFile=video?.file||null,uploadKind=kind;
            const originalVideoFile=video?.file||null;
            let sourceVideoMd5=null;
            if(originalVideoFile&&!await core.validVideo(originalVideoFile))
              throw Error('วิดีโอ: ไฟล์ต้นฉบับไม่ผ่านการตรวจหัวไฟล์');
            if(originalVideoFile)
              sourceVideoMd5=await core.hashBlob(originalVideoFile,()=>this.check());
            if(videoFile&&core.needsVideoConversion(videoFile.name)){
              if(!scope.XStageVideoTranscode)throw Error('วิดีโอ: ไม่พบตัวแปลงวิดีโอของเว็บ · กรุณาอัปเดตหน้าเว็บ');
              const wasPrimary=videoFile===audioFile;
              videoFile=await scope.XStageVideoTranscode.convert(videoFile,{
                signal:this.controller.signal,requireAudio:wasPrimary,
                onStatus:message=>show(message,.12)
              });
              this.check();
              if(wasPrimary){audioFile=videoFile;uploadKind='MP4';}
            }
            if(!await core.validAudio(audioFile))throw Error('ไฟล์ '+uploadKind+' ไม่ผ่านการตรวจหัวไฟล์ต้นฉบับ');
            if(videoFile&&!await core.validVideo(videoFile))
              throw Error('วิดีโอ: ไฟล์วิดีโอไม่ผ่านการตรวจหัวไฟล์ต้นฉบับ');
            let raw=null,doc,json;
            if(videoMeta?.mode==='embedded'){
              doc=core.embeddedVideoLyrics(code);
              json=encode(doc);
            }else if(videoMeta?.mode==='timed'&&videoMeta.lrc.trim()){
              raw=videoMeta.lrc;
              doc=core.lrcToJson(raw,code);
              json=encode(doc);
            }else if(lyricsJson){
              if(lyricsJson.file.size>8*1024*1024)throw Error('Lyrics JSON ใหญ่เกิน 8 MB');
              const source=await lyricsJson.file.text();
              try{doc=core.validLyricsJson(source,code);}
              catch(error){throw Error('Lyrics JSON ไม่สมบูรณ์: '+error.message);}
              if(!videoMeta)code=String(doc.songCode||code);
              json=lyricsJson.file; // Keep original JSON bytes for ordinary audio songs.
              if(lrc){
                if(lrc.file.size>MAX_LRC)throw Error('LRC ใหญ่เกิน 2 MB');
                raw=await lrc.file.text();
              }else if(typeof doc.rawLrc==='string'&&doc.rawLrc.length<=MAX_LRC)raw=doc.rawLrc;
            }else if(lrc){
              if(lrc.file.size>MAX_LRC)throw Error('LRC ไม่ครบหรือใหญ่เกิน 2 MB');
              raw=await lrc.file.text();
              doc=core.lrcToJson(raw,code);
              json=encode(doc);
            }else if(videoFile){
              throw Error('วิดีโอ: ไม่มีเนื้อร้องพร้อมเวลา · เพิ่ม LRC หรือยืนยันว่ามีเนื้อร้องฝังภาพ');
            }else throw Error('LRC ต้องมีเวลาจริงสำหรับเพลงเสียง');
            if(videoMeta){
              doc={...doc,songCode:code,title:videoMeta.title,artist:videoMeta.artist,
                lyricsMode:videoMeta.mode==='embedded'?'embedded-video':'timed'};
              json=encode(doc);
            }
            const [audioHash,jsonHash]=await Promise.all([
              core.hashBlob(audioFile,()=>this.check()),
              core.hashBlob(json,()=>this.check())
            ]);
            const pair=audioHash+':'+jsonHash;
            const matchedPair=byPair.get(pair);
            const sameMetadata=videoMeta&&matchedPair&&
              matchedPair.code===videoMeta.code&&
              matchedPair.title===videoMeta.title&&
              matchedPair.artist===videoMeta.artist&&
              (matchedPair.album||'')===videoMeta.album&&
              (matchedPair.composer||'')===videoMeta.composer&&
              (matchedPair.genre||'')===videoMeta.genre&&
              (matchedPair.language||'')===videoMeta.language&&
              (matchedPair.year||null)===videoMeta.year&&
              matchedPair.originalVideo?.fileId&&
              matchedPair.originalVideo.md5Checksum===sourceVideoMd5;
            if(matchedPair&&(!videoMeta||sameMetadata)){
              this.stats.duplicates++;finished++;show('ข้ามเพลงซ้ำ MD5: '+code);continue;
            }
            const candidates=byCode.get(code.toLowerCase())||[];
            let same=candidates.find(x=>String(x.audio?.md5Checksum||'').toLowerCase()===audioHash);
            // Same bytes with a different filename/code are a duplicate, not
            // a fatal primary-key collision. Never overwrite another record.
            const existingAudio=rows.get('browser/'+audioHash);
            if(existingAudio&&!same){
              if(videoMeta&&!candidates.length)same=existingAudio;
              else{
                this.stats.duplicates++;finished++;
                show('ข้ามไฟล์เพลงซ้ำ MD5 แม้เปลี่ยนชื่อ/รหัส: '+code);continue;
              }
            }
            if(candidates.length&&!same){this.stats.conflicts++;finished++;show('รหัสเพลงชนแต่ข้อมูลต่างกัน: '+code+' · ไม่เขียนทับ');continue;}
            const base=safeName(code);
            const prefix=pathFor(code,uploadKind,'',base+'.'+uploadKind.toLowerCase()).slice(0,-1);
            const name=base+'-'+audioHash.slice(0,16)+'.'+uploadKind.toLowerCase();
            const jname=base+'-'+jsonHash.slice(0,16)+'.json';
            const [media,lyric]=await uploadPair(
              ()=>same?.audio||uploadMedia(audioFile,code,prefix,name,
                MEDIA_MIME[uploadKind]||'application/octet-stream',audioHash,0,.83),
              ()=>uploadMedia(json,code,pathFor(code,'json',uploadKind,jname).slice(0,-1),
                jname,'application/json',jsonHash,.83,.09)
            );
            // LRC is a local input/editing format; JSON is the only
            // lyric artifact stored on Drive in layout v3.
            let videoMedia=same?.video;
            if(videoFile){
              if(videoFile===audioFile)videoMedia=media;
              else{
                const vh=await core.hashBlob(videoFile,()=>this.check());
                const ve=core.ext(videoFile.name).toUpperCase();
                videoMedia=await uploadMedia(videoFile,code,pathFor(code,ve,'',base+'.'+ve.toLowerCase()).slice(0,-1),
                  base+'-'+vh.slice(0,16)+'.'+ve.toLowerCase(),
                  MEDIA_MIME[ve]||'application/octet-stream',vh);
              }
            }
            let originalVideoMedia=same?.originalVideo||null;
            if(originalVideoFile){
              if(originalVideoFile===videoFile)originalVideoMedia=videoMedia;
              else if(!originalVideoMedia||originalVideoMedia.md5Checksum!==sourceVideoMd5){
                const originalKind=core.ext(originalVideoFile.name).toUpperCase();
                const originalName=base+'-'+sourceVideoMd5.slice(0,16)+
                  '.'+originalKind.toLowerCase();
                originalVideoMedia=await uploadMedia(originalVideoFile,code,
                  pathFor(code,originalKind,'',originalName).slice(0,-1),
                  originalName,core.videoMime(originalVideoFile.name)||
                  'application/octet-stream',sourceVideoMd5);
              }
            }
            const ident=same?.webSongId||('browser/'+audioHash);
            if(rows.has(ident)&&!same)throw Error('รหัสอ้างอิงออนไลน์ชนกับเพลงอื่น');
            const identity=core.songIdentity(doc,code,same);
            const record={...(same||{}),webSongId:ident,code,
              title:identity.title,artist:identity.artist,sourceFormat:uploadKind,
              lyricsMode:doc.lyricsMode==='embedded-video'?'embedded-video':'timed',
              audio:media,lyrics:lyric,
              ...(videoMedia?{video:videoMedia}:{}),
              ...(originalVideoMedia?{originalVideo:originalVideoMedia}:{}),
              ...(videoMeta?{album:videoMeta.album,composer:videoMeta.composer,
                genre:videoMeta.genre,language:videoMeta.language,year:videoMeta.year}:{}),
              ...(sourceVideoMd5?{sourceVideoMd5,
                originalVideoFormat:core.ext(originalVideoFile.name).toUpperCase()}:{})};
            delete record.lrc;delete record.lyr;delete record.cur;
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
          if(!/^(?:XSK:|XMID:|ไฟล์ |วิดีโอ:|LRC |Lyrics JSON |SF2\/SF3 |รูปแบบไฟล์)/.test(String(error.message||'')))throw error;
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
      await checkpoint(this.account,null);this.saved=null;
      this.completed=true;
      this.progress(1,1);
      this.refreshButtons();
      this.status('เสร็จสิ้น · เพลงใหม่ '+this.stats.newSongs+' · แก้เนื้อร้อง '+this.stats.updated+
        ' · ข้ามซ้ำ '+this.stats.duplicates+' · รหัสชน '+this.stats.conflicts+
        ' · SoundFont '+this.stats.fonts+' · ข้ามผิดพลาด '+this.stats.errors);
      try{await this.options.refresh();}catch(error){console.warn('Catalog refresh deferred:',error?.message||error);}
    }catch(error){
      this.authRequired=error?.code==='XSTAGE_AUTH_REQUIRED'||
        /Google Login หมดอายุ|Google ต้องการการยืนยัน|Google ไม่ยืนยันสิทธิ์/.test(
          String(error.message||error));
      this.status(aborted(error)||this.stopRequested?
        'หยุดงานแล้ว · ไฟล์ที่ส่งสำเร็จยังอยู่ · เปิดใหม่และกดทำต่อ':
        this.authRequired?'Google ต้องการยืนยันสิทธิ์ · กด “เชื่อม Google ใหม่และทำต่อ” (ไม่เริ่มใหม่)':
        'หยุดเพราะข้อผิดพลาด: '+(error.message||error)+' · ตรวจแล้วกดทำต่อ');
      await this.save({status:'paused',total:this.plan.songs.length+
        this.plan.midis.length+this.plan.xsks.length+this.plan.fonts.length,
        error:aborted(error)?'paused':this.authRequired?
          'auth-required: '+String(error.message||error):String(error.message||error)});
    }finally{
      this.running=false;this.controller=null;this.renderSelection();this.refreshButtons();
    }
  }
}
scope.XStageCloudImport={init:(options)=>new Importer(options),Drive,loadCatalog,buildMidiIndex,distinctImportCode,acquireCatalogLease};
})(window);
