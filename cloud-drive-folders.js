/* X-Stage: user-selected Drive sources and deferred canonical SQLite build.
 * Private files stay in Google Drive. Only folder IDs/labels are persisted locally.
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
    if(kind==='music'&&['DB','CACHE','BACKUP','LOGS'].includes(String(meta.name||'').toUpperCase()))
      fail('ไม่สามารถใช้โฟลเดอร์ฐานข้อมูลหรือสำรองเป็นแหล่งเพลง');
    parent=meta.parents?.[0]||'';
    if(parent===root)break;
  }
  if(depth>=MAX_DEPTH+30)fail('โครงสร้างโฟลเดอร์ลึกเกินขอบเขตที่อนุญาต');
  return first;
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
        if(ext==='xmid'||ext==='xsk')
          files.push({...item,relative:folder.path+item.name,ext});
      }
    }
    if(seen.size%10===0)progress?.('สแกน '+seen.size+' โฟลเดอร์ · พบ XMID/XSK '+files.length+' ไฟล์');
  }
  return {files,otherCount:count-files.length,folders:seen.size};
}
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
  return {file,parsed,midiHash,midiSize,packedMd5,identity};
}
function createWorkflow(options={}){
  const labels={music:'คลังเพลง',soundfont:'SoundFont',fx:'FX'};
  const nodes=Object.fromEntries(KIND.map(k=>[k,$('xstage-drive-folder-'+k+'-name')]));
  const status=$('xstage-drive-folder-status'),buildButton=$('xstage-drive-build-db');
  let busy=false,controller=null;
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
  function render(){
    const s=options.session?.()||{};
    const valid=!!(s.token&&s.sub&&isId(s.rootId)&&!retired.has(s.rootId));
    const pref=valid?readSelections(s.sub,s.rootId):{};
    for(const kind of KIND){
      if(nodes[kind])nodes[kind].textContent=pref[kind]?.name||
        (valid?'ยังไม่เลือกโฟลเดอร์':'เชื่อม Google Drive ก่อน');
      const button=$('xstage-drive-folder-'+kind);
      if(button)button.disabled=busy||!valid;
    }
    if(buildButton)buildButton.disabled=busy||!pref.music?.id;
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
      await drive.listChildren(choice.id);
      const values=readSelections(s.sub,s.rootId);
      values[kind]={id:choice.id,name:meta.name||choice.name||choice.id};
      saveSelections(s.sub,s.rootId,values);
      display('เลือก'+labels[kind]+'แล้ว · '+values[kind].name+
        ' · ใช้ไฟล์จากโฟลเดอร์เดิมโดยไม่คัดลอก');
      if(kind==='soundfont')options.onSoundfontChange?.(choice.id);
      if(kind==='fx')options.onFxChange?.(choice.id);
    }catch(error){display('เลือกโฟลเดอร์ไม่ได้: '+String(error?.message||error));}
    finally{render();}
  }
  async function rebuild(){
    if(busy)return;
    let initial;
    try{initial=session();}
    catch(error){display(error.message);return;}
    const chosen=readSelections(initial.sub,initial.rootId).music;
    if(!chosen?.id){display('เลือกโฟลเดอร์เพลงบน Google Drive ก่อนสร้างฐาน');return;}
    const work=async()=>{
      busy=true;controller=new AbortController();render();
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
        await verifyFolder(drive,chosen.id,initial.rootId,'music');
        display('กำลังอ่าน DB/songs.sqlite3 ที่ใช้งานอยู่…');
        const existing=await scope.XStageCloudImport.loadCatalog(drive,initial.rootId);
        const rows=existing.rows;
        const indexed=await scope.XStageCloudImport.buildMidiIndex(rows,drive,check);
        const hashes=indexed.hashes;
        const codes=new Map();
        for(const row of rows.values()){
          const k=String(row.code||'').toLowerCase();
          if(!codes.has(k))codes.set(k,[]);
          codes.get(k).push(row);
        }
        const listing=await walkMusic(drive,chosen.id,check,display);
        if(!listing.files.length)
          fail('ไม่พบ XMID/XSK ที่อ่านได้ในโฟลเดอร์นี้ · ยังไม่ได้แก้ไข DB');
        let added=0,duplicates=0,invalid=0;
        // Bounded parallel reads, sequential catalog merge. The SQLite file
        // is published once, and only after all Drive assets are verified.
        for(let offset=0;offset<listing.files.length;offset+=4){
          check();
          const batch=listing.files.slice(offset,offset+4);
          const outcomes=await Promise.allSettled(batch.map(file=>
            inspectPackage(drive,file,check)));
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
              duplicates++;continue;
            }
            const code=scope.XStageCloudImport.distinctImportCode(
              item.parsed.code,item.midiHash,codes);
            const kind=item.file.ext;
            const ident='browser/'+kind+'/'+item.packedMd5;
            if(rows.has(ident)){duplicates++;continue;}
            const media={fileId:item.file.id,md5Checksum:item.packedMd5,
              size:Number(item.file.size),path:chosen.name+'/'+item.file.relative};
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
          if(offset%16===0||offset+4>=listing.files.length)
            display('ตรวจ '+Math.min(offset+4,listing.files.length)+' / '+listing.files.length+
              ' · เพิ่ม '+added+' · MIDI ซ้ำ '+duplicates+' · ไฟล์ผิดรูปแบบ '+invalid);
        }
        check();
        if(added||indexed.duplicates||indexed.backfilled){
          display('ตรวจเสร็จ · กำลังสร้างและยืนยัน DB/songs.sqlite3 ครั้งเดียว…');
          await scope.XStageCloudImport.publishSingleCatalog({
            drive,rootId:initial.rootId,pointer:existing.pointer,rows,check,status:display
          });
        }
        display('สร้างฐานเสร็จ · เพิ่ม '+added+' เพลง · ข้าม MIDI ซ้ำ '+duplicates+
          ' · ไฟล์ผิดรูปแบบ '+invalid+
          ' · รูปแบบอื่นที่ยังไม่ได้ทำดัชนี '+listing.otherCount+
          ' · ฐานเพลงรวม '+rows.size+' เพลง');
        try{await options.refresh?.();}catch(error){
          console.warn('Catalog refresh deferred:',error?.message||error);
        }
      }catch(error){
        display('สร้างฐานไม่สำเร็จ: '+String(error?.message||error)+
          ' · DB เดิมยังคงอยู่ (หากเผยแพร่ไม่ผ่าน ระบบพยายามคืนฐานเดิม)');
      }finally{busy=false;controller=null;render();}
    };
    if(scope.navigator?.locks?.request){
      await scope.navigator.locks.request('xstage-drive-import-'+initial.sub,
        {mode:'exclusive',ifAvailable:true},async lock=>{
          if(!lock){display('มีงานนำเข้าหรือสร้าง DB ในแท็บอื่น · ไม่เริ่มซ้อน');return;}
          await work();
        });
    }else await work();
  }
  for(const kind of KIND)
    $('xstage-drive-folder-'+kind)?.addEventListener('click',()=>void choose(kind));
  buildButton?.addEventListener('click',()=>void rebuild());
  for(const event of ['xstage:auth-ready','xstage:auth-refreshed','xstage:librarychange',
    'xstage:auth-cleared'])scope.addEventListener?.(event,render);
  render();
  return {render,choose,rebuild,getFolderId:selectedId,
    getSelection:(sub,root,kind)=>readSelections(sub,root)[kind]||null,
    cancel:()=>controller?.abort()};
}
scope.XStageDriveFolders={init:createWorkflow,readSelections,walkMusic,verifyFolder};
})(typeof window!=='undefined'?window:globalThis);
