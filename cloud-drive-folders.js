/* X-Stage: user-selected Drive sources and deferred canonical SQLite build.
 * Private files stay in Google Drive. Folder settings and verified song metadata
 * checkpoints are stored locally, scoped to the account and selected library.
 * Does not read retired libraries, migrate files, or publish partial catalogs.
 */
(function(scope){
'use strict';
const $=id=>scope.document?.getElementById(id);
const FOLDER='application/vnd.google-apps.folder';
const STORE='xstage-drive-source-folders-v1';
const KIND=['music','soundfont','fx'];
const MAX_FILES=300000,MAX_FOLDERS=20000,MAX_DEPTH=12;
const isId=id=>/^[A-Za-z0-9_-]{5,256}$/.test(String(id||''));
const retired=new Set(scope.XSTAGE_RETIRED_DRIVE_ROOT_IDS||[]);
const fail=message=>{throw Error(message);};
const entryKey=(sub,root)=>String(sub)+':'+String(root);
function readSelections(sub,root){
  if(!sub||!isId(root)||retired.has(root))return {};
  try{
    const saved=JSON.parse(scope.localStorage?.getItem(STORE)||'{}');
    const values=saved?.[entryKey(sub,root)]||{};
    const filtered={};
    for(const kind of KIND){
      const item=values[kind];
      if(isId(item?.id)&&!retired.has(item.id))
        filtered[kind]={id:String(item.id),name:String(item.name||'').slice(0,150)};
    }
    return filtered;
  }catch{return {};}
}
function saveSelections(sub,root,values){
  const saved=JSON.parse(scope.localStorage?.getItem(STORE)||'{}');
  saved[entryKey(sub,root)]=values;
  scope.localStorage?.setItem(STORE,JSON.stringify(saved));
}
async function verifyFolder(drive,id,root,kind){
  if(!isId(id)||retired.has(id)||id===root)
    fail('กรุณาเลือกโฟลเดอร์ย่อยที่ใช้งานอยู่ ไม่ใช่คลังหลักหรือคลังที่ยกเลิก');
  const seen=new Set();
  let parent=id,depth=0,first=null;
  while(parent&&parent!=='root'&&depth++<MAX_DEPTH+30){
    if(!isId(parent)||retired.has(parent)||seen.has(parent))
      fail('ตำแหน่งโฟลเดอร์ไม่ปลอดภัยหรืออยู่ในคลังที่ยกเลิก');
    seen.add(parent);
    const meta=await drive.folderMetadata(parent);
    if(!first)first=meta;
    if(meta.mimeType!==FOLDER||meta.trashed===true)
      fail('รายการที่เลือกไม่ใช่โฟลเดอร์ Google Drive ที่ใช้งานได้');
    if(['DB','CACHE','BACKUP','LOGS'].includes(String(meta.name||'').toUpperCase()))
      fail('ไม่สามารถใช้โฟลเดอร์ฐานข้อมูลหรือสำรองเป็นแหล่งเพลง');
    parent=meta.parents?.[0]||'';
    if(parent===root)return first;
  }
  fail('โฟลเดอร์ต้องอยู่ภายในคลังหลัก XStageKaraoke ที่เลือกเท่านั้น');
}
// Metadata only; do not download, copy or modify any file during inventory.
async function countSourceFiles(drive,start,check=()=>{},collect=null){
  const folders=[{id:start,depth:0,path:''}],visited=new Set(),files=new Set();
  const counts={total:0,xmid:0,xsk:0,sf2:0,sf3:0,fx:0,other:0};
  while(folders.length){
    check();
    const batch=[];
    while(folders.length&&batch.length<4){
      const {id,depth,path}=folders.shift();
      if(!isId(id)||retired.has(id))fail('พบโฟลเดอร์ที่ไม่อนุญาต');
      if(visited.has(id))continue;
      visited.add(id);
      if(visited.size>MAX_FOLDERS)fail('จำนวนโฟลเดอร์เกินขอบเขต');
      batch.push({id,depth,path});
    }
    const pages=await Promise.all(batch.map(x=>drive.listChildren(x.id)));
    check();
    for(let page=0;page<pages.length;page++){
      const {depth,path}=batch[page];
      for(const item of pages[page]){
      if(!isId(item.id)||retired.has(item.id))fail('พบ File ID ที่ไม่อนุญาต');
      if(item.mimeType===FOLDER){
        if(depth>=MAX_DEPTH)fail('โครงสร้างโฟลเดอร์ลึกเกินขอบเขต');
        folders.push({id:item.id,depth:depth+1,path:path+item.name+'/'});
        continue;
      }
      if(files.has(item.id))continue;
      files.add(item.id);
      if(files.size>MAX_FILES)fail('จำนวนไฟล์เกินขอบเขต');
      counts.total++;
      const name=String(item.name||'');
      const ext=name.split('.').pop().toLowerCase();
      if(item.mimeType==='application/vnd.google-apps.shortcut')counts.other++;
      else if(['xmid','xsk','sf2','sf3'].includes(ext)){counts[ext]++;if(ext==='xmid'||ext==='xsk')collect?.({...item,ext,relative:path+name});}
      else if(/^audio\//.test(item.mimeType||'')||/\.(wav|mp3|m4a|aac|ogg|flac|opus)$/i.test(name))counts.fx++;
      else counts.other++;
      }
    }
  }
  return counts;
}
async function walkMusic(drive,start,check,progress){
  const folders=[{id:start,path:'',depth:0}],seen=new Set();
  const files=[];let count=0;
  while(folders.length){
    check();
    const folder=folders.shift();
    if(seen.has(folder.id)||retired.has(folder.id))fail('พบโฟลเดอร์วนซ้ำหรือคลังที่ยกเลิก');
    seen.add(folder.id);
    if(seen.size>MAX_FOLDERS)fail('จำนวนโฟลเดอร์เพลงมากเกินขอบเขตการตรวจ');
    const children=await drive.listChildren(folder.id);
    for(const item of children){
      if(!isId(item.id))fail('Google Drive คืน File ID ไม่ถูกต้อง');
      if(item.mimeType===FOLDER){
        if(folder.depth>=MAX_DEPTH)fail('โครงสร้างเพลงลึกเกิน 12 ชั้น');
        if(retired.has(item.id))fail('พบคลังที่ถูกยกเลิกภายในรายการที่เลือก');
        folders.push({id:item.id,path:folder.path+item.name+'/',depth:folder.depth+1});
      }else{
        count++;
        if(count>MAX_FILES)fail('จำนวนไฟล์เกิน 300,000 รายการ');
        const ext=String(item.name||'').split('.').pop().toLowerCase();
        if(item.mimeType!=='application/vnd.google-apps.shortcut'&&(ext==='xmid'||ext==='xsk'))
          files.push({...item,relative:folder.path+item.name,ext});
      }
    }
    if(seen.size%10===0)progress?.('สแกน '+seen.size+' โฟลเดอร์ · พบ XMID/XSK '+files.length+' ไฟล์');
  }
  return {files,otherCount:count-files.length,folders:seen.size};
}
// Persistent verified metadata, not audio, credentials or a second SQLite catalog.
// Reuse only when Drive ID, package checksum, size and format are unchanged.
const JOB='xstage-drive-build-pending-v1:';
const checkpointKey=(s,folder,file)=>/^[a-f0-9]{32}$/i.test(file.md5Checksum||'')
  ?JSON.stringify([s.sub,s.rootId,folder,file.id,String(file.md5Checksum).toLowerCase(),String(file.size),file.ext]):null;
function openCheckpoint(){
  return new Promise(resolve=>{
    try{
      if(!scope.indexedDB){resolve(null);return;}
      const request=scope.indexedDB.open('xstage-drive-build-checkpoints-v1',1);
      request.onupgradeneeded=()=>request.result.createObjectStore('verified');
      request.onerror=request.onblocked=()=>resolve(null);
      request.onsuccess=()=>{
        const db=request.result;
        db.onversionchange=()=>db.close();
        resolve({
          get:key=>new Promise(done=>{
            try{const r=db.transaction('verified').objectStore('verified').get(key);
              r.onsuccess=()=>done(r.result||null);r.onerror=()=>done(null);
            }catch{done(null);}
          }),
          put:(key,value)=>new Promise(done=>{
            try{const t=db.transaction('verified','readwrite');
              t.objectStore('verified').put(value,key);
              t.oncomplete=()=>done(true);t.onerror=t.onabort=()=>done(false);
            }catch{done(false);}
          }),
          close:()=>db.close()
        });
      };
    }catch{resolve(null);}
  });
}
function pendingKey(s){return JOB+entryKey(s.sub,s.rootId);}
function pending(s){try{return scope.localStorage?.getItem(pendingKey(s))||'';}catch{return '';}}
function setPending(s,id){try{scope.localStorage?.setItem(pendingKey(s),id||'');}catch{}}
function freshPendingKey(s){return pendingKey(s)+':fresh';}
function isFreshPending(s){try{return scope.localStorage?.getItem(freshPendingKey(s))==='1';}catch{return false;}}
function setFreshPending(s,fresh){try{scope.localStorage?.setItem(freshPendingKey(s),fresh?'1':'');}catch{}}
function pausedKey(s){return pendingKey(s)+':paused';}
function paused(s,folder){try{return scope.localStorage?.getItem(pausedKey(s))===folder;}catch{return false;}}
function setPaused(s,folder){try{scope.localStorage?.setItem(pausedKey(s),folder||'');}catch{}}
async function inspectPackage(drive,file,check){
  check();
  if(!Number.isSafeInteger(Number(file.size))||Number(file.size)>96*1024*1024)
    fail('ไฟล์ XMID/XSK มีขนาดผิดปกติ');
  const bytes=await drive.getSqlite(file.id);
  check();
  const blob=new Blob([bytes]);
  const packedMd5=await scope.XStageImportCore.hashBlob(blob,check);
  if(file.md5Checksum&&packedMd5!==String(file.md5Checksum).toLowerCase())
    fail('MD5 ของไฟล์บน Google Drive ไม่ตรงกับข้อมูลที่ดาวน์โหลด');
  const reader=file.ext==='xmid'?scope.XStageXmid:scope.XStageXsk;
  if(!reader?.openPackage)fail('ยังไม่โหลดตัวอ่าน '+file.ext.toUpperCase());
  const parsed=await reader.openPackage(blob);
  const midiHash=await scope.XStageImportCore.hashBlob(parsed.midi,check);
  const midiSize=parsed.midi.size;
  const identity=scope.XStageImportCore.songIdentity(parsed.document,parsed.code);
  return {file,parsed:{code:parsed.code,document:{lyricsMode:parsed.document.lyricsMode}},
    midiHash,midiSize,packedMd5,identity};
}
// A count match alone is never proof. Match package IDs, checksums, sizes
// and verified MIDI identities; duplicates need not occupy another DB row.
const packageSignature=file=>/^[a-f0-9]{32}$/i.test(file?.md5Checksum||'')&&Number.isSafeInteger(Number(file.size))&&Number(file.size)>0
  ?String(file.md5Checksum).toLowerCase()+':'+Number(file.size):'';
// Only trust rows whose source is still present with the same package checksum and size.
function packagePathIndex(files){
  const map=new Map();
  for(const file of files){
    if(typeof file.relative!=='string')continue;
    const path='SONGS/'+file.relative;
    map.set(path,map.has(path)?null:file);
  }
  return map;
}
function matchingPackageFile(row,byId,byPath){
  const media=row.xmid||row.xsk;
  if(!media)return null;
  const sig=packageSignature(media);
  const file=media.fileId?byId.get(media.fileId):
    row.pendingDriveLink===true?byPath?.get(media.path):null;
  return file&&sig&&sig===packageSignature(file)&&file.ext===(row.xmid?'xmid':'xsk')?file:null;
}
function verifiedPackageRows(files,rows,canonical=false){
  const byId=new Map(files.map(file=>[file.id,file])),known=new Map(),byPath=canonical?packagePathIndex(files):null;
  for(const row of rows.values()){
    const media=row.xmid||row.xsk,kind=row.xmid?'xmid':'xsk';
    const file=matchingPackageFile(row,byId,byPath),sig=packageSignature(media);
    const hash=String(row.midiHash||row.midi?.md5Checksum||'').toLowerCase();
    const size=Number(row.midiSize||row.midi?.size||0);
    if(file&&file.ext===kind&&sig&&sig===packageSignature(file)&&/^[a-f0-9]{32}$/.test(hash)&&Number.isSafeInteger(size)&&size>0)
      known.set(kind+':'+sig,row);
  }
  return known;
}
function inspectionLimits(navigator={}){
  const conn=navigator.connection||{},memory=Number(navigator.deviceMemory)||0;
  const low=conn.saveData||/^(slow-2g|2g|3g)$/.test(conn.effectiveType||'')||(memory>0&&memory<=2);
  if(low)return {workers:4,bytes:16*1024*1024};
  if(memory>=8&&conn.effectiveType==='4g')return {workers:12,bytes:48*1024*1024};
  return {workers:8,bytes:24*1024*1024};
}
async function compareCatalog(files,rows,checkpoint,s,folder,check=()=>{},canonical=false){
  const byId=new Map(files.map(f=>[f.id,f])),validIds=new Set(),packages=new Set(),midi=new Set(),midiSeen=new Set();
  const byPath=canonical?packagePathIndex(files):null;
  let stale=0,other=0,duplicateRows=0,matchedRows=0,uncertain=0,newFiles=0,duplicates=0;
  for(const row of rows.values()){
    const mh=String(row.midiHash||row.midi?.md5Checksum||'').toLowerCase(),ms=Number(row.midiSize||row.midi?.size||0);
    const identity=/^[a-f0-9]{32}$/.test(mh)&&Number.isSafeInteger(ms)&&ms>0?mh+':'+ms:'';
    if(identity){if(midiSeen.has(identity))duplicateRows++;midiSeen.add(identity);}
    const media=row.xmid||row.xsk;
    if(!media){other++;continue;}
    const file=matchingPackageFile(row,byId,byPath),sig=packageSignature(media);
    if(!file||!sig||sig!==packageSignature(file)||file.ext!==(row.xmid?'xmid':'xsk')){stale++;continue;}
    matchedRows++;validIds.add(file.id);packages.add(file.ext+':'+sig);
    if(identity)midi.add(identity);else uncertain++;
  }
  const pending=[];
  for(const file of files){
    if(validIds.has(file.id))continue;
    const sig=packageSignature(file);
    if(!sig){uncertain++;continue;}
    if(packages.has(file.ext+':'+sig)){duplicates++;continue;}
    pending.push(file);
  }
  for(let i=0;i<pending.length;i+=64){
    check();
    await Promise.all(pending.slice(i,i+64).map(async file=>{
      const key=checkpointKey(s,folder,file);
      const saved=key&&checkpoint?await checkpoint.get(key):null;
      if(saved&&saved.packedMd5===String(file.md5Checksum).toLowerCase()&&
        /^[a-f0-9]{32}$/i.test(saved.midiHash||'')&&Number.isSafeInteger(saved.midiSize)&&saved.midiSize>0&&
        midi.has(saved.midiHash.toLowerCase()+':'+saved.midiSize))duplicates++;
      else newFiles++;
    }));
  }
  check();
  return {matchedRows,duplicates,newFiles,stale,other,duplicateRows,uncertain,
    equal:!newFiles&&!stale&&!duplicateRows&&!uncertain&&matchedRows+duplicates===files.length};
}
function createWorkflow(options={}){
  const labels={music:'คลังเพลง',soundfont:'SoundFont',fx:'FX'};
  const nodes=Object.fromEntries(KIND.map(k=>[k,$('xstage-drive-folder-'+k+'-name')]));
  const status=$('xstage-drive-folder-status'),buildButton=$('xstage-drive-build-db'),
    cancelButton=$('xstage-drive-cancel-db');
  let busy=false,controller=null,scanSequence=0,discoverTask=null,stopRequested=false,publishing=false,activeJob=null;
  const memoryChecks=new Map();
  const pausedJobs=new Set();
  const jobKey=(s,folder)=>JSON.stringify([s.sub,s.rootId,folder]);
  const isPaused=(s,folder)=>pausedJobs.has(jobKey(s,folder))||paused(s,folder);
  function markPaused(s,folder,value){const key=jobKey(s,folder);if(value)pausedJobs.add(key);else pausedJobs.delete(key);setPaused(s,value?folder:'');}
  function requestPause(){
    if(!busy||!activeJob||publishing||stopRequested)return;
    stopRequested=true;markPaused(activeJob.session,activeJob.folder,true);
    display('กำลังหยุดอย่างปลอดภัย · รอชุดที่กำลังตรวจบันทึกผลให้เสร็จ');render();
  }
  const defaultNames={music:'SONGS',soundfont:'SOUNDFONT',fx:'FX'};
  const scanButton=$('xstage-drive-scan-counts');
  const rebuildButton=$('xstage-drive-rebuild-db');
  const countNodes=Object.fromEntries(KIND.map(k=>[k,$('xstage-drive-count-'+k)]));
  const dbCount=$('xstage-drive-db-count'),comparison=$('xstage-drive-compare-status');
  let scanTask=null,comparisonState='unknown',catalogCache=null,scanTimer=null;
  const format=n=>Number(n).toLocaleString('th-TH');
  function compareStatus(message,state='unknown'){comparisonState=state;if(comparison){comparison.textContent=message;comparison.setAttribute?.('data-state',state);}render();}
  async function catalogForCheck(drive,s,check){
    const root=await drive.listChildren(s.rootId);check();
    const dirs=root.filter(x=>x.name==='DB'&&x.mimeType===FOLDER);
    if(dirs.length>1)fail('พบโฟลเดอร์ DB ซ้ำ');
    const entries=dirs.length?await drive.listChildren(dirs[0].id):[];check();
    const db=entries.filter(x=>x.name==='songs.sqlite3'&&x.mimeType!==FOLDER);
    if(db.length>1)fail('พบ songs.sqlite3 ซ้ำ');
    const sig=db.length&&packageSignature(db[0]);
    const key=sig?JSON.stringify([s.sub,s.rootId,db[0].id,sig]):'';
    if(key&&catalogCache?.key===key)return catalogCache.value;
    const value=await scope.XStageCloudImport.loadCatalog(drive,s.rootId,{verifyChecksum:true});check();
    if(key&&value.pointer?.catalogFileId===db[0].id&&String(value.pointer.catalogMd5).toLowerCase()===String(db[0].md5Checksum).toLowerCase())catalogCache={key,value};
    return value;
  }
  async function scanCounts(only=''){
    if(busy)return;
    let s;try{s=session();}catch{return;}
    const choices=readSelections(s.sub,s.rootId);
    const key=JSON.stringify([s.sub,s.rootId,...KIND.map(k=>choices[k]?.id||''),!!options.hasFullRead?.()]);
    if(scanTask?.key===key)return scanTask.promise;
    const seq=++scanSequence;
    const check=()=>{
      if(busy||seq!==scanSequence||!sameSession(s)||KIND.some(k=>readSelections(s.sub,s.rootId)[k]?.id!==choices[k]?.id))
        fail('เปลี่ยนบัญชีหรือคลังแล้ว');
    };
    const drive=new scope.XStageCloudImport.Drive(()=>options.session()?.token,check);
    drive.ensureAuth=force=>options.ensureAuth?.(force);
    const task={key};
    compareStatus('กำลังตรวจจำนวนไฟล์และฐานข้อมูล…','checking');
    if(dbCount)dbCount.textContent='กำลังตรวจ…';
    const musicFiles=[];
    let canonicalMusic=false;
    task.promise=(async()=>{
      const results=await Promise.allSettled([
        ...KIND.map(async kind=>{
          const node=countNodes[kind],choice=choices[kind];
          if(!choice?.id){if(node)node.textContent='ยังไม่เลือกโฟลเดอร์';return null;}
          if(node)node.textContent='กำลังตรวจนับ…';
          try{
            const meta=await verifyFolder(drive,choice.id,s.rootId,kind);check();
            if(kind==='music')canonicalMusic=meta.name==='SONGS'&&meta.parents?.includes(s.rootId);
            const c=await countSourceFiles(drive,choice.id,check,kind==='music'?file=>musicFiles.push(file):null);check();
            const n=kind==='music'?c.xmid+c.xsk:kind==='soundfont'?c.sf2+c.sf3:c.fx;
            if(node)node.textContent=format(n)+' ไฟล์'+(c.total!==n?' · ทั้งหมด '+format(c.total)+' ไฟล์':'')+(options.hasFullRead?.()?'':' · เท่าที่มีสิทธิ์');
            return c;
          }catch(error){if(seq===scanSequence&&!busy&&node)node.textContent='ตรวจนับไม่ครบ';throw error;}
        }),
        catalogForCheck(drive,s,check)
      ]);
      check();
      const db=results[3];
      if(db.status!=='fulfilled'){if(dbCount)dbCount.textContent='ตรวจฐานไม่สำเร็จ';compareStatus('ยังยืนยันฐานเพลงไม่ได้ · '+String(db.reason?.message||db.reason),'unknown');return;}
      const {rows,pointer}=db.value;
      if(dbCount)dbCount.textContent=format(rows.size)+' รายการ'+(pointer?'':' · ยังไม่มีฐาน');
      if(!choices.music?.id||results[0].status!=='fulfilled'){compareStatus('ยังตรวจคลังเพลงไม่ครบ','unknown');return;}
      let checkpoint=null;
      try{
        checkpoint=await (options.openCheckpoint||openCheckpoint)();
        const result=await compareCatalog(musicFiles,rows,checkpoint,s,choices.music.id,check,canonicalMusic);
        check();
        const detail=' · เพลงตรงฐาน '+format(result.matchedRows)+' · ไฟล์ซ้ำ '+format(result.duplicates);
        if(!options.hasFullRead?.()||result.uncertain){
          compareStatus('ยังยืนยันทั้งหมดไม่ได้ · ตรวจเฉพาะไฟล์ที่เข้าถึงได้หรือมี MD5'+detail,'unknown');return;
        }
        if(pointer&&result.equal){
          compareStatus('ตรงกันแล้ว'+detail+(result.other?' · ฐานรูปแบบอื่น '+format(result.other):''),'equal');return;
        }
        compareStatus('แนะนำให้อัปเดตฐานเพลง · ไฟล์รอตรวจ '+format(result.newFiles)+
          ' · รายการเดิมนอกคลัง/เปลี่ยน '+format(result.stale)+(result.duplicateRows?' · แถวซ้ำ '+format(result.duplicateRows):'')+detail,'different');
      }finally{checkpoint?.close?.();}
    })().catch(error=>{if(seq===scanSequence&&!busy&&sameSession(s))compareStatus('ตรวจไม่ครบ · '+String(error.message||error),'unknown');})
      .finally(()=>{if(scanTask===task)scanTask=null;});
    scanTask=task;return task.promise;
  }
  function scheduleScan(){
    if(!$('cloud-import-dialog')?.open||busy||scope.document?.hidden)return;
    if(scanTimer)clearTimeout(scanTimer);
    if(!scanTask&&comparisonState==='equal')compareStatus('กำลังยืนยันข้อมูลล่าสุด…','checking');
    scanTimer=setTimeout(()=>{scanTimer=null;if($('cloud-import-dialog')?.open&&!busy)void discoverDefaults().then(()=>scanCounts());},250);
  }
  scanButton?.addEventListener('click',()=>void scanCounts());
  function session(){
    const s=options.session?.()||{};
    if(!s.token||!s.sub||!isId(s.rootId)||retired.has(s.rootId))
      fail('กรุณาเชื่อม Google และเลือก XStageKaraoke ที่ใช้งานอยู่ก่อน');
    return {sub:String(s.sub),rootId:String(s.rootId),token:s.token};
  }
  function selectedId(sub,root,kind){
    if(!KIND.includes(kind))return '';
    return readSelections(sub,root)[kind]?.id||'';
  }
  function display(message){if(status)status.textContent=message;}
  function sameSession(s){const now=options.session?.();return now?.sub===s.sub&&now?.rootId===s.rootId&&!!now.token;}
  async function discoverDefaults(){
    if(busy)return;
    let s;try{s=session();}catch{return;}
    if(KIND.every(k=>readSelections(s.sub,s.rootId)[k]?.id))return;
    if(discoverTask?.sub===s.sub&&discoverTask?.rootId===s.rootId)return discoverTask.promise;
    const task={sub:s.sub,rootId:s.rootId};
    task.promise=(async()=>{
      const drive=new scope.XStageCloudImport.Drive(()=>options.session()?.token,()=>{if(!sameSession(s))fail('เปลี่ยนบัญชีหรือคลังแล้ว');});
      drive.ensureAuth=force=>options.ensureAuth?.(force);
      const children=await drive.listChildren(s.rootId);
      const found={};
      for(const kind of KIND){
        if(readSelections(s.sub,s.rootId)[kind]?.id)continue;
        const matches=children.filter(x=>x.mimeType===FOLDER&&String(x.name||'').toUpperCase()===defaultNames[kind]&&isId(x.id)&&!retired.has(x.id));
        if(matches.length!==1)continue;
        const meta=await verifyFolder(drive,matches[0].id,s.rootId,kind);
        found[kind]={id:meta.id,name:meta.name||defaultNames[kind]};
      }
      if(!sameSession(s)||busy)return;
      const values=readSelections(s.sub,s.rootId),changed=[];
      for(const kind of KIND)if(!values[kind]?.id&&found[kind]){values[kind]=found[kind];changed.push(kind);}
      if(changed.length){saveSelections(s.sub,s.rootId,values);render();
        if(changed.includes('soundfont'))options.onSoundfontChange?.(values.soundfont.id);
        if(changed.includes('fx'))options.onFxChange?.(values.fx.id);
      }
    })().catch(error=>{if(sameSession(s)&&!busy)display('ตรวจโฟลเดอร์ไม่ได้ · '+String(error.message||error));}).finally(()=>{if(discoverTask===task)discoverTask=null;render();});
    discoverTask=task;return task.promise;
  }
  async function openDriveFolder(kind){
    let s,choice;try{s=session();choice=readSelections(s.sub,s.rootId)[kind];}catch(error){display(error.message);return;}
    if(!choice?.id){await choose(kind);return;}
    // Open synchronously in the click handler to preserve browser popup activation.
    const tab=scope.open?.('about:blank','_blank');
    if(!tab){if(!busy)display('เบราว์เซอร์ปิดกั้นหน้าต่างใหม่ · กรุณาอนุญาตป๊อปอัปแล้วลองอีกครั้ง');return;}
    try{
      tab.opener=null;
      const drive=new scope.XStageCloudImport.Drive(()=>options.session()?.token,()=>{if(!sameSession(s))fail('เปลี่ยนบัญชีหรือคลังแล้ว');});
      drive.ensureAuth=force=>options.ensureAuth?.(force);
      await verifyFolder(drive,choice.id,s.rootId,kind);
      if(!sameSession(s)||readSelections(s.sub,s.rootId)[kind]?.id!==choice.id)fail('โฟลเดอร์เปลี่ยนระหว่างตรวจสอบ');
      tab.location.replace('https://drive.google.com/drive/folders/'+encodeURIComponent(choice.id));
    }catch(error){try{tab.close();}catch{}if(!busy)display('เปิดโฟลเดอร์ไม่ได้ · '+String(error.message||error));}
  }
  let folderMenu=null;
  function closeFolderMenu(){
    if(!folderMenu)return;
    const dialog=folderMenu;folderMenu=null;
    if(dialog.open)dialog.close();
    dialog.remove();
  }
  async function manageFolder(kind){
    if(busy||!KIND.includes(kind))return;
    let s;try{s=session();}catch(error){display(error.message);return;}
    const choice=readSelections(s.sub,s.rootId)[kind];
    if(!choice?.id){await choose(kind);return;}
    if(folderMenu)return;
    const doc=scope.document;
    const dialog=doc.createElement('dialog');
    dialog.className='xstage-drive-folder-menu';
    dialog.setAttribute('aria-label','จัดการโฟลเดอร์ '+labels[kind]);
    const heading=doc.createElement('h3');heading.textContent='จัดการโฟลเดอร์ '+labels[kind];
    const name=doc.createElement('p');name.textContent=choice.name;
    dialog.append(heading,name);
    const add=(label,handler,primary=false)=>{
      const button=doc.createElement('button');button.type='button';button.textContent=label;
      if(primary)button.className='primary';
      button.addEventListener('click',()=>{
        closeFolderMenu();
        if(!sameSession(s)||busy)return;
        handler();
      });
      dialog.append(button);
    };
    add('เปิดใน Google Drive ↗',()=>void openDriveFolder(kind),true);
    add('เปลี่ยนโฟลเดอร์',()=>void choose(kind));
    add('ยกเลิก',()=>{});
    dialog.addEventListener('cancel',event=>{event.preventDefault();closeFolderMenu();});
    dialog.addEventListener('close',()=>{if(folderMenu===dialog){folderMenu=null;dialog.remove();}});
    folderMenu=dialog;doc.body.append(dialog);
    try{dialog.showModal();}catch(error){closeFolderMenu();display('เปิดเมนูไม่ได้ · '+String(error.message||error));}
  }
  function render(){
    const s=options.session?.()||{};
    const valid=!!(s.token&&s.sub&&isId(s.rootId)&&!retired.has(s.rootId));
    const pref=valid?readSelections(s.sub,s.rootId):{};
    for(const kind of KIND){
      if(nodes[kind])nodes[kind].textContent=pref[kind]?.name||
        (valid?'ยังไม่เลือกโฟลเดอร์':'เชื่อม Google Drive ก่อน');
      const button=$('xstage-drive-folder-'+kind);
      if(button){
        button.disabled=busy||!valid;
        button.textContent='จัดการโฟลเดอร์';
        button.setAttribute?.('aria-label','จัดการโฟลเดอร์ '+labels[kind]);
        button.title=busy?'กำลังสร้างฐานเพลง · เปลี่ยนโฟลเดอร์ได้เมื่อเสร็จหรือยกเลิก':
          (!valid?'กรุณาเชื่อม Google Drive และเลือกคลังที่ใช้งานอยู่':'เปิดหรือเปลี่ยนโฟลเดอร์');
      }
    }
    if(scanButton)scanButton.disabled=!valid||busy;
    if(rebuildButton)rebuildButton.disabled=!valid||busy||!pref.music?.id;
    const waiting=valid&&pref.music?.id&&isPaused(s,pref.music.id);
    if(buildButton){buildButton.disabled=busy||!pref.music?.id||(!waiting&&(comparisonState==='equal'||comparisonState==='checking'));
      buildButton.textContent=busy?(publishing?'กำลังยืนยันฐานเพลง…':stopRequested?'กำลังพักงาน…':'กำลังตรวจเพลง…'):waiting?'ทำงานต่อจากจุดที่หยุด':comparisonState==='equal'?'ฐานเพลงเป็นปัจจุบัน':comparisonState==='checking'?'กำลังตรวจฐานเพลง…':'ตรวจไฟล์และอัปเดตฐานเพลง';}
    if(cancelButton)cancelButton.disabled=!busy;
    if(cancelButton){cancelButton.hidden=!busy;cancelButton.disabled=!busy||stopRequested||publishing;
      cancelButton.textContent=publishing?'กำลังบันทึกฐานอย่างปลอดภัย':stopRequested?'กำลังพักงาน…':'พัก / ยกเลิกอย่างปลอดภัย';}
  }
  async function choose(kind){
    if(busy||!KIND.includes(kind))return;
    try{
      const s=session();
      const choice=await options.chooseFolder?.(kind);
      if(!choice)return;
      const current=session();
      if(s.sub!==current.sub||s.rootId!==current.rootId)
        fail('บัญชีหรือคลังเพลงเปลี่ยนระหว่างเลือกโฟลเดอร์');
      if(!isId(choice.id)||retired.has(choice.id))fail('Folder ID จาก Google Picker ไม่ถูกต้อง');
      const drive=new scope.XStageCloudImport.Drive(()=>options.session()?.token,()=>{});
      drive.ensureAuth=force=>options.ensureAuth?.(force);
      const meta=await verifyFolder(drive,choice.id,s.rootId,kind);
      // Permission to select a folder is not always permission to read its
      // children under drive.file. Verify it before saving the choice.
      const available=await drive.listChildren(choice.id);
      const verifiedSession=session();
      if(verifiedSession.sub!==s.sub||verifiedSession.rootId!==s.rootId)
        fail('บัญชี Google หรือคลังเพลงเปลี่ยนระหว่างตรวจสิทธิ์โฟลเดอร์');
      const values=readSelections(s.sub,s.rootId);
      values[kind]={id:choice.id,name:meta.name||choice.name||choice.id};
      saveSelections(s.sub,s.rootId,values);
      display('เลือก'+labels[kind]+'แล้ว · '+values[kind].name+
        ' · พบ '+available.filter(item=>item.mimeType!==FOLDER).length+
        ' ไฟล์ในระดับนี้ · ไม่มีการคัดลอกหรือย้ายไฟล์');
      if(kind==='soundfont')options.onSoundfontChange?.(choice.id);
      if(kind==='fx')options.onFxChange?.(choice.id);
      comparisonState='unknown';
      if($('cloud-import-dialog')?.open)scheduleScan();
    }catch(error){display('เลือกโฟลเดอร์ไม่ได้: '+String(error?.message||error));}
    finally{render();}
  }
  async function rebuild({fresh=false}={}){
    if(busy)return;
    let initial;
    try{initial=session();}
    catch(error){display(error.message);return;}
    const chosen=readSelections(initial.sub,initial.rootId).music;
    if(!chosen?.id){display('เลือกโฟลเดอร์เพลงบน Google Drive ก่อนสร้างฐาน');return;}
    const resumingFresh=pending(initial)===chosen.id&&isFreshPending(initial);
    if(resumingFresh)fresh=true;
    if(!fresh&&!isPaused(initial,chosen.id)&&(comparisonState==='equal'||comparisonState==='checking'))return;
    if(fresh&&!resumingFresh){
      const confirmed=scope.confirm?.(
        'สร้างฐานเพลงร่วม PC / Online ใหม่จาก XMID/XSK ทุกไฟล์ใน XStageKaraoke/SONGS?\\n'+
        'รายการใน DB เดิมจะถูกแทนที่โดยฐานใหม่ที่ตรวจสำเร็จแล้วเท่านั้น\\n'+
        'ไฟล์ SONGS, SoundFont และ FX ไม่ถูกลบ และ Song Studio Pro ยังใช้ฐานผลิตเพลงของตัวเอง\\n'+
        'หมายเหตุ: ตัวสร้าง DB จาก Drive รองรับ XMID/XSK เท่านั้นในขั้นนี้');
      if(!confirmed)return;
    }
    const work=async()=>{
      if(busy)return;
      ++scanSequence;scanTask=null;comparisonState='unknown';
      busy=true;scope.XStageDriveBuildBusy=true;controller=new AbortController();stopRequested=false;publishing=false;
      activeJob={session:initial,folder:chosen.id};markPaused(initial,chosen.id,false);
      setFreshPending(initial,fresh);setPending(initial,chosen.id);render();
      let checkpoint=null,persisted=0,sessionOnly=0,unverifiable=0,lastProgress='';
      const pauseBoundary=()=>{if(stopRequested)fail('พักงานตามคำสั่งผู้ใช้');};
      const check=()=>{
        if(controller.signal.aborted)fail('ยกเลิกการสร้างฐาน');
        const now=options.session?.();
        if(!now||now.sub!==initial.sub||now.rootId!==initial.rootId)
          fail('บัญชี Google หรือคลัง XStageKaraoke เปลี่ยนระหว่างทำงาน');
      };
      const drive=new scope.XStageCloudImport.Drive(()=>options.session()?.token,check);
      drive.ensureAuth=force=>options.ensureAuth?.(force);
      drive.signal=()=>controller.signal;
      try{
        const musicRoot=await verifyFolder(drive,chosen.id,initial.rootId,'music');
        if(fresh&&(musicRoot.name!=='SONGS'||!musicRoot.parents?.includes(initial.rootId)))
          fail('สร้างฐานร่วมใหม่ต้องเลือกโฟลเดอร์ SONGS โดยตรงใต้ XStageKaraoke เพื่อให้พาธเพลง PC และ Online ตรงกัน');
        checkpoint=await (options.openCheckpoint||openCheckpoint)();
        check();pauseBoundary();
        display('กำลังอ่าน DB/songs.sqlite3 ที่ใช้งานอยู่…');
        const existing=fresh
          ?await (async()=>{
            // Full rebuild does not depend on the old table schema, but still
            // pins the existing Drive file identity for safe replacement.
            const folders=await drive.listChildren(initial.rootId);check();
            const dirs=folders.filter(x=>x.name==='DB'&&x.mimeType===FOLDER);
            if(dirs.length>1)fail('พบโฟลเดอร์ DB ซ้ำ');
            const files=dirs.length?await drive.listChildren(dirs[0].id):[];
            const active=files.filter(x=>x.name==='songs.sqlite3'&&x.mimeType!==FOLDER);
            if(active.length>1)fail('พบฐาน songs.sqlite3 ซ้ำ');
            const previous=active[0];
            return {rows:new Map(),pointer:previous?{
              directFile:true,catalogFileId:previous.id,
              catalogMd5:String(previous.md5Checksum||'')
            }:null};
          })()
          :await scope.XStageCloudImport.loadCatalog(drive,initial.rootId,{verifyChecksum:true});
        pauseBoundary();
        const rows=existing.rows;
        const originalCount=rows.size;
        const baseLabel='ฐานเดิม '+originalCount+' เพลง';
        display(baseLabel+' · กำลังตรวจดัชนี MIDI เดิม…');
        const indexed=await scope.XStageCloudImport.buildMidiIndex(rows,drive,()=>{check();pauseBoundary();});
        pauseBoundary();
        const hashes=indexed.hashes;
        const existingIds=new Set(rows.keys());
        const retainedCount=rows.size;
        const existingLabel=baseLabel+(indexed.duplicates?' · ซ้ำในฐานเดิม '+indexed.duplicates:'');
        const codes=new Map();
        for(const row of rows.values()){
          const k=String(row.code||'').toLowerCase();
          if(!codes.has(k))codes.set(k,[]);
          codes.get(k).push(row);
        }
        const listing=await walkMusic(drive,chosen.id,()=>{check();pauseBoundary();},message=>display(existingLabel+' · '+message));
        pauseBoundary();
        if(!listing.files.length)
          fail('ไม่พบ XMID/XSK ที่อ่านได้ในโฟลเดอร์นี้ · ยังไม่ได้แก้ไข DB');
        let added=0,duplicates=0,alreadyRegistered=0,duplicateInBatch=0,invalid=0,reused=0,skipped=0,downloaded=0,shared=0;
        const known=verifiedPackageRows(listing.files,rows),remaining=[];
        const markDuplicate=row=>{
          duplicates++;
          if(existingIds.has(row.webSongId))alreadyRegistered++;
          else duplicateInBatch++;
        };
        const duplicateLabel=()=> 'MIDI ซ้ำ '+duplicates+' (มีในฐานแล้ว '+alreadyRegistered+' · ซ้ำในรอบนี้ '+duplicateInBatch+')';
        const progress=processed=>{lastProgress=existingLabel+' · ตรวจ '+processed+' / '+listing.files.length+
          ' ('+Math.floor(processed*100/listing.files.length)+'%) · ข้ามจากฐาน '+skipped+
          ' · ดาวน์โหลดตรวจจริง '+downloaded+' · ใช้จุดบันทึก '+reused+' · ใช้ผลไฟล์เหมือนกัน '+shared+
          ' · เพิ่มใหม่ '+added+' · '+duplicateLabel()+' · ไฟล์ผิดรูปแบบ '+invalid+
          ' · คาดว่าฐานรวม '+(retainedCount+added)+' เพลง';display((stopRequested?'กำลังพักอย่างปลอดภัย · ':'')+lastProgress);};
        for(const file of listing.files){
          check();
          const sig=packageSignature(file),row=sig&&known.get(file.ext+':'+sig);
          if(row){markDuplicate(row);skipped++;}else remaining.push(file);
        }
        const limits=inspectionLimits(scope.navigator);
        progress(skipped);
        // Reuse one verified result for byte-identical packages, including
        // copies under a different Drive ID. Never infer MIDI equality from a filename.
        const inFlight=new Map(),signatureCounts=new Map();
        const signatureOf=file=>{const sig=packageSignature(file);return sig?file.ext+':'+sig:'';};
        for(const file of remaining){const sig=signatureOf(file);if(sig)signatureCounts.set(sig,(signatureCounts.get(sig)||0)+1);}
        const inspect=async file=>{
          check();
          const key=checkpointKey(initial,chosen.id,file);
          const saved=key?(memoryChecks.get(key)||(checkpoint?await checkpoint.get(key):null)):null;
          check();
          if(saved&&saved.packedMd5===String(file.md5Checksum).toLowerCase()&&
              /^[a-f0-9]{32}$/i.test(saved.midiHash)&&Number.isSafeInteger(saved.midiSize)&&
              saved.midiSize>0&&saved.parsed?.document&&saved.identity){
            reused++;
            const sig=signatureOf(file);
            if(sig&&signatureCounts.get(sig)>1&&!inFlight.has(sig))inFlight.set(sig,Promise.resolve(saved));
            return {...saved,file};
          }
          const signature=signatureOf(file);
          let task=signature&&inFlight.get(signature);
          if(task)shared++;
          else{
            downloaded++;
            task=inspectPackage(drive,file,check);
            if(signature&&signatureCounts.get(signature)>1)inFlight.set(signature,task);
          }
          const result=await task;
          const item={...result,file};
          check();
          if(key){
            const {file:ignored,...metadata}=item;
            // A completed verification survives a user pause. Keep a memory fallback
            // when IndexedDB is disabled, full or unavailable; do not claim durability.
            let written=false;
            try{if(checkpoint)written=(await checkpoint.put(key,metadata))!==false;}catch{}
            if(written){persisted++;memoryChecks.delete(key);}
            else{memoryChecks.set(key,metadata);sessionOnly++;}
          }else unverifiable++;
          return item;
        };
        // Bounded parallel reads, sequential catalog merge. The SQLite file
        // is published once, and only after all Drive assets are verified.
        for(let offset=0;offset<remaining.length;){
          check();pauseBoundary();
          const batch=[];let bytes=0;
          while(offset<remaining.length&&batch.length<limits.workers){
            const file=remaining[offset],size=Number(file.size)||limits.bytes;
            if(batch.length&&bytes+size>limits.bytes)break;
            batch.push(file);bytes+=size;offset++;
          }
          const outcomes=await Promise.allSettled(batch.map(file=>
            inspect(file)));
          for(let i=0;i<outcomes.length;i++){
            check();
            const result=outcomes[i];
            if(result.status==='rejected'){
              const reason=String(result.reason?.message||result.reason);
              // Invalid packages are reported but never silently accepted.
              if(/^(?:XMID:|XSK:)/.test(reason)){invalid++;continue;}
              throw result.reason;
            }
            const item=result.value;
            const old=hashes.get(item.midiHash);
            if(old){
              if(Number(old.midiSize||old.midi?.size||0)>0&&
                 Number(old.midiSize||old.midi?.size)!==item.midiSize)
                fail('พบ MD5 MIDI ตรงกันแต่ขนาดข้อมูลต่างกัน');
              markDuplicate(old);continue;
            }
            const code=scope.XStageCloudImport.distinctImportCode(
              item.parsed.code,item.midiHash,codes);
            const kind=item.file.ext;
            const ident='browser/'+kind+'/'+item.packedMd5;
            if(rows.has(ident)){markDuplicate(rows.get(ident));continue;}
            const media={fileId:item.file.id,md5Checksum:item.packedMd5,
              size:Number(item.file.size),path:musicRoot.name+'/'+item.file.relative};
            const row={webSongId:ident,code,sourceCode:item.parsed.code,
              midiHash:item.midiHash,midiSize:item.midiSize,
              originalFilename:item.file.name,originalRelativePath:item.file.relative,
              originalFileSize:Number(item.file.size),
              title:item.identity.title,artist:item.identity.artist,
              metadataComplete:Boolean(item.identity.identityComplete),
              lyricsMode:item.parsed.document.lyricsMode||'timed',
              sourceFormat:kind.toUpperCase(),
              ...(kind==='xmid'?{xmid:media}:{xsk:media})};
            rows.set(ident,row);hashes.set(item.midiHash,row);
            const k=code.toLowerCase();if(!codes.has(k))codes.set(k,[]);
            codes.get(k).push(row);added++;
          }
          // Retain decoded metadata only for signatures that still have copies
          // to process, including copies in later batches. No song bytes retained.
          for(const file of batch){const sig=signatureOf(file);if(!sig)continue;
            const left=(signatureCounts.get(sig)||1)-1;
            if(left){signatureCounts.set(sig,left);}else{signatureCounts.delete(sig);inFlight.delete(sig);}
          }
          progress(skipped+offset);
          pauseBoundary();
        }
        check();pauseBoundary();
        const needsPublication=Boolean(fresh||added||indexed.duplicates||indexed.backfilled);
        if(needsPublication){
          publishing=true;render();
          display(existingLabel+' · เพิ่มใหม่ '+added+' · '+duplicateLabel()+' · กำลังสร้างและยืนยัน DB/songs.sqlite3 ครั้งเดียว…');
          await scope.XStageCloudImport.publishSingleCatalog({
            drive,rootId:initial.rootId,pointer:existing.pointer,rows,check,status:display
          });
        }
        setPending(initial,'');setFreshPending(initial,false);markPaused(initial,chosen.id,false);
        display((needsPublication?'สร้างฐานเสร็จ':'ตรวจเสร็จ · ไม่มีข้อมูลใหม่ให้เผยแพร่')+
          ' · '+existingLabel+' · เพิ่มใหม่ '+added+' เพลง · ข้าม '+duplicateLabel()+
          ' · ข้ามจากฐาน '+skipped+' · ดาวน์โหลดตรวจจริง '+downloaded+' · ใช้จุดบันทึก '+reused+' · ใช้ผลไฟล์เหมือนกัน '+shared+
          ' · ไฟล์ผิดรูปแบบ '+invalid+
          ' · รูปแบบอื่นที่ยังไม่ได้ทำดัชนี '+listing.otherCount+
          ' · ฐานเพลงรวม '+rows.size+' เพลง');
        try{await options.refresh?.();}catch(error){
          console.warn('Catalog refresh deferred:',error?.message||error);
        }
      }catch(error){
        const reason=String(error?.message||error);
        const interrupted=!controller.signal.aborted&&
          /network|fetch|timeout|offline|HTTP (?:401|429|5\d\d)|Google.*(?:ต่ออายุ|ยืนยัน|เชื่อม|หมดอายุ)|การเชื่อมต่อ/i.test(reason);
        if(stopRequested){
          markPaused(initial,chosen.id,true);setPending(initial,chosen.id);
          display('พักงานอย่างปลอดภัย · ฐานเดิมยังไม่ถูกแทนที่ · '+(lastProgress?lastProgress+' · ':'')+
            'บันทึกผลตรวจถาวรเพิ่ม '+persisted+' ไฟล์'+(sessionOnly?' · เก็บในแท็บนี้ '+sessionOnly+' ไฟล์ (อย่าปิดแท็บ)':'')+
            (unverifiable?' · ไม่มี checksum ต้องตรวจใหม่ '+unverifiable+' ไฟล์':'')+' · กด “ทำงานต่อจากจุดที่หยุด”');
        }else{
        if(!interrupted){setPending(initial,'');setFreshPending(initial,false);}
        display((interrupted?'พักงานชั่วคราว · จะทำต่อเมื่อเชื่อมต่อหรือกลับมาเปิดแท็บ: ':'สร้างฐานไม่สำเร็จ: ')+reason+
          ' · DB เดิมยังคงอยู่ (หากเผยแพร่ไม่ผ่าน ระบบพยายามคืนฐานเดิม)');
        }
      }finally{
        checkpoint?.close?.();busy=false;scope.XStageDriveBuildBusy=false;controller=null;activeJob=null;publishing=false;stopRequested=false;catalogCache=null;render();scheduleScan();
      }
    };
    if(scope.navigator?.locks?.request){
      await scope.navigator.locks.request('xstage-drive-import-'+initial.sub,
        {mode:'exclusive',ifAvailable:true},async lock=>{
          if(!lock){display('มีงานนำเข้าหรือสร้าง DB ในแท็บอื่น · ไม่เริ่มซ้อน');return;}
          await work();
        });
    }else await work();
  }
  for(const kind of KIND){
    $('xstage-drive-folder-'+kind)?.addEventListener('click',()=>void manageFolder(kind));
  }
  buildButton?.addEventListener('click',()=>void rebuild());
  rebuildButton?.addEventListener('click',()=>void rebuild({fresh:true}));
  cancelButton?.addEventListener('click',requestPause);
  function resume(){
    if(busy||scope.document?.hidden)return;
    let s;try{s=session();}catch{return;}
    const chosen=readSelections(s.sub,s.rootId).music;
    if(chosen?.id&&pending(s)===chosen.id&&!isPaused(s,chosen.id)){
      comparisonState='unknown';void rebuild({fresh:isFreshPending(s)});
    }
  }
  for(const event of ['xstage:auth-ready','xstage:auth-refreshed','xstage:librarychange',
    'xstage:auth-cleared'])scope.addEventListener?.(event,()=>{if(event==='xstage:librarychange'||event==='xstage:auth-cleared'){closeFolderMenu();++scanSequence;scanTask=null;comparisonState='unknown';catalogCache=null;for(const n of Object.values(countNodes))if(n)n.textContent='';if(dbCount)dbCount.textContent='—';if(comparison)comparison.textContent='';}render();resume();scheduleScan();});
  scope.addEventListener?.('xstage:drive-sources-open',()=>{
    render();
    if(!busy){comparisonState='unknown';render();scheduleScan();}
  });
  for(const event of ['online','pageshow','focus'])scope.addEventListener?.(event,()=>{resume();scheduleScan();});
  scope.document?.addEventListener?.('visibilitychange',()=>{resume();scheduleScan();});
  render();resume();
  return {render,choose,rebuild,scanCounts,discoverDefaults,openDriveFolder,manageFolder,getFolderId:selectedId,
    getSelection:(sub,root,kind)=>readSelections(sub,root)[kind]||null,
    cancel:requestPause};
}
scope.XStageDriveFolders={init:createWorkflow,readSelections,walkMusic,verifyFolder,countSourceFiles,compareCatalog,verifiedPackageRows,inspectionLimits};
})(typeof window!=='undefined'?window:globalThis);
