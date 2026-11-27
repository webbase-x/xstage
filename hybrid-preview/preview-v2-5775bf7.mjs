import {diagnoseGoogleRange} from './cors-diagnostics-v2-5775bf7.mjs';
const $=id=>document.getElementById(id),scope='https://www.googleapis.com/auth/drive.readonly';
const retired=new Set(window.XSTAGE_RETIRED_DRIVE_ROOT_IDS||[]);
const folder='application/vnd.google-apps.folder', validId=s=>typeof s==='string'&&/^[A-Za-z0-9_-]+$/.test(s);
let token='',roots=[],generation=0,busy=false,report='';
function status(s){$('status').textContent=s;}
function reset(){generation++;token='';roots=[];busy=false;report='';$('result').textContent='';$('copy').disabled=true;$('root').replaceChildren();$('choose').hidden=true;$('clear').hidden=true;$('connect').disabled=false;$('run').disabled=false;status('จบการทดสอบ · ไม่เก็บ token');}
async function list(q,localToken,current){
 const results=[];const seen=new Set();let pageToken='';
 do{
  if(!current())throw new DOMException('Cancelled','AbortError');
  const p=new URLSearchParams({q,fields:'nextPageToken,files(id,name,mimeType,parents,size,trashed)',pageSize:'100'});
  if(pageToken)p.set('pageToken',pageToken);
  const res=await fetch('https://www.googleapis.com/drive/v3/files?'+p,{headers:{Authorization:'Bearer '+localToken},cache:'no-store',redirect:'error',signal:AbortSignal.timeout(15000)});
  if(!res.ok)throw Error('Drive listing HTTP '+res.status);
  const d=await res.json();if(!Array.isArray(d.files))throw Error('Invalid Drive listing');
  results.push(...d.files);pageToken=d.nextPageToken||'';
  if(pageToken&&seen.has(pageToken))throw Error('Repeated page token');seen.add(pageToken);
  if(seen.size>20)throw Error('Too many matching folders; narrow the library');
 }while(pageToken);
 return results;
}
function exact(items,parent,name,type){const hits=items.filter(f=>validId(f.id)&&!f.trashed&&f.name===name&&f.parents?.includes(parent)&&(type?f.mimeType===type:f.mimeType!==folder));if(hits.length!==1)throw Error('Expected exactly one '+name+'; found '+hits.length);return hits[0];}
$('connect').onclick=()=>{
 if(busy)return;
 const gis=window.google?.accounts?.oauth2;
 if(!gis){status('Google OAuth ยังไม่พร้อม · ลองใหม่');return;}
 const id=++generation;busy=true;$('connect').disabled=true;
 const fail=()=>{if(id!==generation)return;busy=false;$('connect').disabled=false;status('Google OAuth ไม่สำเร็จหรือถูกยกเลิก');};
 try{
  const client=gis.initTokenClient({client_id:window.XSTAGE_CONFIG.googleClientId,scope,include_granted_scopes:false,callback:async response=>{
   if(id!==generation)return;
   if(response.error||!response.access_token||!gis.hasGrantedAllScopes(response,scope)){fail();return;}
   token=response.access_token;
   try{
    roots=(await list("name='XStageKaraoke' and mimeType='"+folder+"' and trashed=false",token,()=>id===generation)).filter(f=>validId(f.id)&&!retired.has(f.id)&&f.name==='XStageKaraoke'&&f.mimeType===folder&&!f.trashed);
    if(id!==generation)return;
    $('root').replaceChildren(...roots.map((r,i)=>new Option(r.name+' · คลัง '+(i+1)+' · …'+r.id.slice(-5),String(i))));
    $('choose').hidden=!roots.length;$('clear').hidden=false;status(roots.length?'เลือกคลังและกดตรวจ Range':'ไม่พบคลัง XStageKaraoke ที่อนุญาต');
   }catch(e){if(id===generation)status('เปิดคลังไม่สำเร็จ: '+e.message);}
   finally{if(id===generation){busy=false;$('connect').disabled=false;}}
  },error_callback:fail});
  client.requestAccessToken({prompt:'select_account'});
 }catch{fail();}
};
$('run').onclick=async()=>{
 if(busy||!token)return;
 const root=roots[Number($('root').value)];
 if(!root||retired.has(root.id))return;
 const id=generation,localToken=token,current=()=>id===generation&&token===localToken;
 busy=true;$('run').disabled=true;$('connect').disabled=true;$('copy').disabled=true;status('กำลังตรวจไฟล์ SQLite และ HTTP Range…');
 try{
  const db=exact(await list("'"+root.id+"' in parents and name='DB' and trashed=false",localToken,current),root.id,'DB',folder);
  const file=exact(await list("'"+db.id+"' in parents and name='songs.sqlite3' and trashed=false",localToken,current),db.id,'songs.sqlite3');
  const size=Number(file.size);if(!Number.isSafeInteger(size)||size<100)throw Error('Invalid SQLite size');
  const p=await diagnoseGoogleRange({fileId:file.id,token:localToken,size,current});
  if(!current())return;
  report=JSON.stringify({test:'X-Stage Hybrid Range Preview',date:new Date().toISOString(),browser:navigator.userAgent,size,status:p.status,diagnosticVersion:2,transportOk:p.transportOk===true,partialReadOk:p.partialReadOk===true,sqliteHeader:p.sqliteHeader,overlapMatches:p.overlapMatches,distinctBlocks:p.distinctBlocks,conditionalVerified:p.conditionalVerified,sqlReady:p.ok===true,wal:p.wal??null,samples:p.samples,bytes:p.bytes??null,elapsedMs:Number.isFinite(p.ms)?Math.round(p.ms):null,conditionalMs:Number.isFinite(p.conditionalMs)?Math.round(p.conditionalMs):null,reason:p.reason||null},null,2);
  $('result').textContent=report;$('copy').disabled=false;status(p.ok?'ผ่านการตรวจ Range และ header · ยังต้องทดสอบ SQL':p.transportOk?'Range ผ่าน · ยังไม่อนุญาต SQL':p.partialReadOk?'รับข้อมูลบางช่วงจริงแล้ว · ยังไม่ยืนยันรุ่นไฟล์หรือ Content-Range':'ยังไม่ผ่านเงื่อนไข Range');
 }catch(e){if(current()){report=JSON.stringify({test:'X-Stage Hybrid Range Preview',date:new Date().toISOString(),error:String(e.message||e)},null,2);$('result').textContent=report;$('copy').disabled=false;status('ทดสอบไม่สำเร็จ');}}
 finally{if(current()){busy=false;$('run').disabled=false;$('connect').disabled=false;}}
};
$('clear').onclick=reset;$('copy').onclick=async()=>{try{await navigator.clipboard.writeText(report);status('คัดลอกผลแล้ว');}catch{status('เลือกข้อความผลทดสอบเพื่อคัดลอก');}};
window.addEventListener('pagehide',reset);
