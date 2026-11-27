import {createPathResolver} from '../../hybrid-preview/path-resolver.mjs';
const $=id=>document.getElementById(id),scope='https://www.googleapis.com/auth/drive.readonly';
const retired=new Set(window.XSTAGE_RETIRED_DRIVE_ROOT_IDS||[]);
const folder='application/vnd.google-apps.folder', validId=s=>typeof s==='string'&&/^[A-Za-z0-9_-]+$/.test(s);
let token='',roots=[],generation=0,busy=false,session=null,owner='',cursor=null,term='',mode='auto';
function status(s){$('status').textContent=s;}
function reset(){generation++;token='';roots=[];busy=false;closeSession();$('result').textContent='';$('search-form').hidden=true;$('songs').replaceChildren();$('more').hidden=true;$('root').replaceChildren();$('choose').hidden=true;$('clear').hidden=true;$('connect').disabled=false;$('run').disabled=false;status('จบการทดสอบ · ไม่เก็บ token');}
async function list(q,localToken,current){
 const results=[];const seen=new Set();let pageToken='';
 do{
  if(!current())throw new DOMException('Cancelled','AbortError');
  const p=new URLSearchParams({q,fields:'nextPageToken,files(id,name,mimeType,parents,size,trashed,md5Checksum)',pageSize:'100'});
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
 closeSession();$('search-form').hidden=true;$('songs').replaceChildren();$('more').hidden=true;const id=++generation;busy=true;$('connect').disabled=true;
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
    $('choose').hidden=!roots.length;$('clear').hidden=false;status(roots.length?'เลือกคลังและกดเปิดดัชนี':'ไม่พบคลัง XStageKaraoke ที่อนุญาต');
   }catch(e){if(id===generation)status('เปิดคลังไม่สำเร็จ: '+e.message);}
   finally{if(id===generation){busy=false;$('connect').disabled=false;}}
  },error_callback:fail});
  client.requestAccessToken({prompt:'select_account'});
 }catch{fail();}
};

function closeSession(){
 const s=session;session=null;cursor=null;
 if(s){s.abort.abort();s.worker.terminate();s.release();for(const p of s.pending.values()){clearTimeout(p.timer);p.reject(Error('Index closed'));}s.pending.clear();}
}
function rpc(s,action,args={}){
 return new Promise((resolve,reject)=>{
  if(session!==s){reject(Error('Index session closed'));return;}
  const id=crypto.randomUUID(),timer=setTimeout(()=>{if(session===s)closeSession();},120000);
  s.pending.set(id,{resolve,reject,timer});
  try{s.worker.postMessage({id,action,...args});}catch(e){clearTimeout(timer);s.pending.delete(id);reject(e);}
 });
}
async function openWorker(key,current){
 let release,grant,deny;
 const hold=new Promise(r=>release=r),ready=new Promise((r,j)=>{grant=r;deny=j;});
 void navigator.locks.request('xstage-compact:'+key,{ifAvailable:true},async lock=>{if(!lock){deny(Error('ดัชนีเปิดอยู่ในแท็บอื่น'));return;}grant();await hold;}).catch(deny);
 await ready;
 if(!current()){release();throw Error('Library changed');}
 let worker;
 try{worker=new Worker(new URL('./compact-worker.mjs',import.meta.url),{type:'module'});}catch(e){release();throw e;}
 const s={worker,release,pending:new Map(),abort:new AbortController()};
 session=s;
 worker.onmessage=({data})=>{const p=s.pending.get(data?.id);if(!p)return;clearTimeout(p.timer);s.pending.delete(data.id);data.error?p.reject(Error(data.error)):p.resolve(data.result);};
 worker.onerror=()=>{if(session===s){status('SQLite worker ไม่พร้อม');closeSession();}};
 return s;
}
$('run').onclick=async()=>{
 if(busy||!token)return;
 const root=roots[Number($('root').value)];if(!root||retired.has(root.id))return;
 closeSession();$('search-form').hidden=true;$('songs').replaceChildren();$('more').hidden=true;
 const id=++generation,localToken=token,current=()=>id===generation&&token===localToken;
 busy=true;$('run').disabled=true;$('connect').disabled=true;status('กำลังตรวจ revision ของฐานและดัชนี…');
 try{
  const db=exact(await list("'"+root.id+"' in parents and name='DB' and trashed=false",localToken,current),root.id,'DB',folder);
  const files=await list("'"+db.id+"' in parents and (name='songs.sqlite3' or name='songs.search.sqlite3') and trashed=false",localToken,current);
  const source=exact(files,db.id,'songs.sqlite3'),index=exact(files,db.id,'songs.search.sqlite3');
  const md5=String(index.md5Checksum||'').toLowerCase(),size=Number(index.size),sourceMd5=String(source.md5Checksum||'').toLowerCase(),sourceSize=Number(source.size);
  if(!/^[a-f0-9]{32}$/.test(md5)||!Number.isSafeInteger(size)||size<100||!(/^[a-f0-9]{32}$/.test(sourceMd5))||!Number.isSafeInteger(sourceSize))throw Error('Drive ไม่มี MD5 หรือขนาดที่ตรวจสอบได้');
  const about=await fetch('https://www.googleapis.com/drive/v3/about?fields=user(permissionId)',{headers:{Authorization:'Bearer '+localToken},cache:'no-store',signal:AbortSignal.timeout(15000)});
  if(!about.ok)throw Error('ตรวจบัญชี Drive ไม่สำเร็จ');
  const account=(await about.json()).user?.permissionId;if(!account||!current())throw Error('บัญชีเปลี่ยน');
  const key=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(account+':'+root.id))),v=>v.toString(16).padStart(2,'0')).join('');
  if(!current())return;
  if(!window.XStageWebCatalogDisk?.available()||!navigator.locks?.request)throw Error('เบราว์เซอร์ไม่รองรับ OPFS ที่ต้องใช้');
  const s=await openWorker(key,current);
  const started=performance.now();
  status('กำลังเตรียมดัชนี '+(size/1048576).toFixed(2)+' MiB ลงดิสก์…');
  const verified=await window.XStageWebCatalogDisk.getOrFetch({owner:'compact:'+key,pointer:{contentMD5:md5,contentBytes:size},current,signal:s.abort.signal,
    fetcher:()=>fetch('https://www.googleapis.com/drive/v3/files/'+index.id+'?alt=media',{headers:{Authorization:'Bearer '+localToken},signal:s.abort.signal,cache:'no-store',redirect:'error'})});
  if(!verified?.file||!current())throw Error('เปิดไฟล์ดัชนีไม่ได้');
  const meta=await rpc(s,'open',{owner:key,file:verified.file,md5,size,source:{md5:sourceMd5,size:sourceSize}});
  if(!current())return;
  s.resolve=createPathResolver({rootId:root.id,list:q=>list(q,localToken,current),current,retiredRoots:[...retired]});
  $('result').textContent=JSON.stringify({count:meta.count,indexBytes:size,sourceBytes:sourceSize,fromDisk:verified.fromDisk,openMs:Math.round(performance.now()-started)},null,2);
  status('พร้อมค้นหา '+meta.count.toLocaleString('th-TH')+' เพลง · '+(verified.fromDisk?'ใช้ดัชนีที่เก็บไว้':'ตรวจ MD5 และเปิด SQLite สำเร็จ'));
  $('search-form').hidden=false;$('term').focus();
 }catch(e){if(current()){closeSession();status('เปิดดัชนีไม่สำเร็จ: '+String(e.message||e));}}
 finally{if(current()){busy=false;$('run').disabled=false;$('connect').disabled=false;}}
};
async function search(reset){
 if(busy||!session)return;
 const s=session;if(reset){term=$('term').value.trim();mode=$('mode').value;cursor=null;$('songs').replaceChildren();}
 if(!term)return;
 busy=true;$('search').disabled=true;$('more').disabled=true;
 try{
  const t=performance.now(),p=await rpc(s,'search',{term,mode,cursor});
  if(session!==s)return;
  cursor=p.cursor;
  for(const song of p.songs){
   const row=document.createElement('div');row.style.cssText='border-top:1px solid #476079;padding:8px 0';
   const title=document.createElement('span');title.textContent=[song.code,song.title,song.artist].filter(Boolean).join(' · ');row.append(title,document.createTextNode(' '));
   const verify=document.createElement('button');verify.type='button';verify.textContent='ตรวจไฟล์เพลง';
   verify.onclick=async()=>{if(session!==s)return;verify.disabled=true;try{const m=await s.resolve(song.sourcePath);if(session===s)verify.textContent='พบไฟล์ '+m.size.toLocaleString()+' ไบต์ · ยังไม่รับรองการเล่น';}catch(e){if(session===s)verify.textContent=e.message;}finally{verify.disabled=false;}};
   row.append(verify);$('songs').append(row);
  }
  $('more').hidden=!p.hasMore;status('ค้นหา '+p.songs.length+' เพลง · '+Math.round(performance.now()-t)+' ms');
 }catch(e){status(String(e.message||e));}finally{busy=false;$('search').disabled=false;$('more').disabled=false;}
}
$('search-form').onsubmit=e=>{e.preventDefault();void search(true);};$('more').onclick=()=>void search(false);
$('clear').onclick=reset;window.addEventListener('pagehide',reset);
