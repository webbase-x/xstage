/* Shared V2 catalog validation for the browser and Android WebView.
 * Pure code, no requests and no persistence of private user content. */
(function(global){
'use strict';
const TYPES=new Set(['m4a','mp3','midi','video']);
const VIDEO_TYPES=new Set(['avi','mpg','vcd','wmv','mp4']);
const MAX_SONGS=1_000_000;
function fail(message){throw Error('X-Stage DB V2: '+message);}
function string(value,label,{empty=false,max=1024}={}){
  if(typeof value!=='string'||value.length>max||(!empty&&!value.trim())||/[\x00-\x1f]/.test(value))
    fail(label+' ต้องเป็นข้อความที่ถูกต้อง');
  return value;
}
function key(value,label){
  string(value,label,{max:256});
  if(/[\\/?#]/.test(value))fail(label+' มีอักขระต้องห้าม');
  return value;
}
function safePath(value){
  string(value,'path',{max:2048});
  if(value.startsWith('/')||value.includes('\\')||value.includes(':')||
     value.split('/').some(x=>!x||x==='.'||x==='..'))fail('พาธสื่อไม่ปลอดภัย');
}
function locator(value,{cloud=false,label='media'}={}){
  if(!value||typeof value!=='object'||Array.isArray(value))fail(label+' ไม่ใช่ object');
  const file=value.fileId,local=value.localPath;
  if(cloud&&(local!==undefined||file===undefined))fail(label+' ต้องใช้ Google Drive File ID เท่านั้น');
  if(file!==undefined)key(file,label+'.fileId');
  if(local!==undefined){
    string(local,label+'.localPath');
    if(!/^(?:[A-Za-z]:[\\/]|\/)/.test(local))fail('localPath ต้องเป็นพาธสมบูรณ์');
  }
  if((file!==undefined)===(local!==undefined))fail(label+' ต้องมี fileId หรือ localPath เพียงชนิดเดียว');
  if(value.path!==undefined)safePath(value.path);
  if(value.size!==undefined&&(!Number.isSafeInteger(value.size)||value.size<0))fail(label+'.size ไม่ถูกต้อง');
  for(const [name,len] of [['sha256',64],['md5Checksum',32]])
    if(value[name]!==undefined&&(typeof value[name]!=='string'||
       value[name].length!==len||!/^[a-fA-F0-9]+$/.test(value[name])))fail(label+'.'+name+' ไม่ถูกต้อง');
  return value;
}
function songId(value){
  string(value,'id',{max:256});
  if(/[?#]/.test(value))fail('รหัสอ้างอิงเพลงไม่ถูกต้อง');
  return value;
}
function song(item,{cloud=false}={}){
  if(!item||typeof item!=='object'||Array.isArray(item))fail('เพลงไม่ใช่ object');
  songId(item.id);key(item.code,'code');
  if(item.code.length>64)fail('รหัสเพลงยาวเกิน 64 ตัว');
  if(item.webSongId!==undefined&&item.webSongId!==item.id)fail('id และ webSongId ไม่ตรงกัน');
  string(item.title,'title');
  string(item.artist??'','artist',{empty:true});
  const media=item.media;
  if(!media||typeof media!=='object'||Array.isArray(media)||!Object.keys(media).length)fail('ไม่มีไฟล์สื่อ');
  for(const [kind,ref] of Object.entries(media)){
    if(!TYPES.has(kind))fail('ชนิดสื่อไม่รองรับ: '+kind);
    locator(ref,{cloud,label:kind});
    if(kind==='midi'){
      if(!['ncn','emk'].includes(ref.type))fail('MIDI ต้องระบุ ncn หรือ emk');
      if(ref.type==='ncn'){
        locator(ref.lyr,{cloud,label:'midi.lyr'});
        locator(ref.cur,{cloud,label:'midi.cur'});
      }
    }
    if(kind==='video'&&!VIDEO_TYPES.has(ref.type))fail('ชนิดไฟล์ VIDEO ไม่รองรับ');
  }
  if(item.lyrics!==undefined&&item.lyrics!==null)locator(item.lyrics,{cloud,label:'lyrics'});
  return item;
}
function catalog(doc,{cloud=false,expectedCount=undefined}={}){
  if(!doc||doc.schemaVersion!==2||!Array.isArray(doc.songs)||doc.songs.length>MAX_SONGS)
    fail('ฐานเพลง V2 ไม่สมบูรณ์');
  if(doc.format!==undefined&&doc.format!=='xstage-unified-v2')fail('รูปแบบ Catalog ไม่ตรงมาตรฐาน');
  if(expectedCount!==undefined&&doc.songs.length!==expectedCount)fail('จำนวนเพลงไม่ตรงกับตัวชี้');
  const ids=new Set();
  for(const item of doc.songs){
    song(item,{cloud});
    if(ids.has(item.id))fail('ID เพลงซ้ำ: '+item.id);
    ids.add(item.id);
  }
  return doc;
}
function pointer(doc){
  if(!doc||doc.schemaVersion!==2||doc.format&&doc.format!=='xstage-unified-v2')fail('current.json V2 ผิดรูปแบบ');
  key(doc.generation,'generation');
  if(doc.catalogFileId!==undefined&&doc.catalogFiles!==undefined)
    fail('ต้องใช้ catalogFileId หรือ catalogFiles อย่างใดอย่างหนึ่ง');
  if(doc.catalogFiles!==undefined){
    if(!Array.isArray(doc.catalogFiles)||!doc.catalogFiles.length||doc.catalogFiles.length>1024)
      fail('จำนวน Catalog Shards ไม่ถูกต้อง');
    const ids=new Set();
    for(const part of doc.catalogFiles){
      if(!part||typeof part!=='object')fail('Shard ไม่ใช่ object');
      key(part.fileId,'shard.fileId');
      if(ids.has(part.fileId))fail('Shard ID ซ้ำ');
      ids.add(part.fileId);
      if(!Number.isSafeInteger(part.songCount)||part.songCount<0||part.songCount>MAX_SONGS)
        fail('Shard songCount ไม่ถูกต้อง');
    }
  }else key(doc.catalogFileId,'catalogFileId');
  const deltas=doc.deltaFileIds??[];
  if(!Array.isArray(deltas)||deltas.length>32||new Set(deltas).size!==deltas.length)
    fail('Delta references ไม่ถูกต้อง');
  for(const id of deltas)key(id,'deltaFileId');
  if(!Number.isSafeInteger(doc.songCount)||doc.songCount<0||doc.songCount>MAX_SONGS)fail('จำนวนเพลงไม่ถูกต้อง');
  if(doc.catalogFiles&&!deltas.length&&
     doc.catalogFiles.reduce((count,part)=>count+part.songCount,0)!==doc.songCount)
    fail('ผลรวมจำนวนเพลงใน Shards ไม่ตรงกัน');
  return doc;
}
function assemble(pointerDoc,parts,deltas=[]){
  pointer(pointerDoc);
  const shardRefs=pointerDoc.catalogFiles||[{fileId:pointerDoc.catalogFileId,songCount:null}];
  if(!Array.isArray(parts)||parts.length!==shardRefs.length||
     !Array.isArray(deltas)||deltas.length!==(pointerDoc.deltaFileIds||[]).length)
    fail('Catalog shards / deltas missing or out of order');
  const rows=new Map();
  for(let i=0;i<parts.length;i++){
    catalog(parts[i],{cloud:true,expectedCount:shardRefs[i].songCount??undefined});
    for(const item of parts[i].songs){
      if(rows.has(item.id))fail('ID เพลงซ้ำข้าม Catalog: '+item.id);
      rows.set(item.id,item);
    }
  }
  for(const delta of deltas){
    if(!delta||delta.schemaVersion!==2||
       delta.format!==undefined&&delta.format!=='xstage-unified-v2'||
       !Array.isArray(delta.upserts)||!Array.isArray(delta.removes)||
       delta.upserts.length>200||delta.removes.length>200)
      fail('Delta V2 ไม่สมบูรณ์หรือเกินขีดจำกัด');
    for(const id of delta.removes){songId(id);rows.delete(id);}
    for(const item of delta.upserts){song(item,{cloud:true});rows.set(item.id,item);}
  }
  const merged={schemaVersion:2,format:'xstage-unified-v2',
                generation:pointerDoc.generation,songs:[...rows.values()]};
  catalog(merged,{cloud:true,expectedCount:pointerDoc.songCount});
  const codes=new Map();
  for(const item of merged.songs){
    const code=item.code.toLocaleLowerCase('en-US');
    if(codes.has(code)&&codes.get(code)!==item.id)
      fail('รหัสเพลงซ้ำระหว่างรายการ '+item.code);
    codes.set(code,item.id);
  }
  return merged;
}
global.XStageCatalogV2=Object.freeze({schemaVersion:2,catalog,pointer,song,locator,assemble});
})(window);
