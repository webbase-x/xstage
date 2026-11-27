/* Preview dialog intentionally does not insert a PC path into playback/queue.
 * All output uses textContent. Close or switch account invalidates the reader. */
import {openGoogleExperiment} from './google-live.mjs';
import {portableXmidPath} from './path-resolver.mjs';
const element=(tag,value)=>{const e=document.createElement(tag);if(value!==undefined)e.textContent=value;return e;};
export async function showHybridExperiment(options){
  document.getElementById('xstage-hybrid-experiment')?.close();
  const dialog=element('dialog');dialog.id='xstage-hybrid-experiment';
  dialog.style.cssText='width:min(620px,94vw);max-height:85vh;overflow:auto;padding:20px;background:#102235;color:#fff;border:1px solid #5396b5;border-radius:12px';
  const heading=element('h2','Hybrid SQLite · ทดลองอ่านจาก Google Drive');
  const notice=element('p','อ่านอย่างเดียว · ไม่ดาวน์โหลดฐานเต็ม · ยังไม่แก้คิวหรือเล่นเพลง');
  const status=element('p','กำลังตรวจ HTTP Range…');status.setAttribute('role','status');
  const close=element('button','ปิด / กลับโหมดปกติ');close.type='button';
  const search=element('input');search.type='search';search.placeholder='รหัสเพลง / ชื่อ / ศิลปิน';search.disabled=true;search.maxLength=120;
  const submit=element('button','ค้นหา');submit.disabled=true;
  const more=element('button','5 เพลงถัดไป');more.disabled=true;
  const results=element('div');results.setAttribute('aria-live','polite');
  const stats=element('p');
  const form=element('form');form.append(search,submit,more);more.type='button';
  dialog.append(heading,notice,status,form,results,stats,close);document.body.append(dialog);
  let session=null,closed=false,busy=false,cursor=null,term='',hasMore=false;
  const current=()=>!closed&&options.current();
  const cleanup=async()=>{closed=true;try{if(session?.reader&&!busy)await session.reader.close();}catch{}dialog.remove();};
  close.onclick=()=>dialog.close();
  dialog.addEventListener('close',()=>{void cleanup();},{once:true});
  dialog.showModal();
  async function page(reset){
    if(!current()||busy||!session?.reader)return;
    if(reset){term=search.value.trim();cursor=null;hasMore=true;results.replaceChildren();}
    if(!term||!hasMore)return;
    busy=true;submit.disabled=more.disabled=true;
    try{
      const started=performance.now();const data=await session.reader.search(term,{cursor});
      if(!current())return;
      cursor=data.cursor;hasMore=data.hasMore;
      for(const song of data.songs){
        const row=element('div');row.style.cssText='padding:9px 0;border-bottom:1px solid #456';
        row.append(element('span',[song.code,song.title,song.artist].filter(Boolean).join(' · ')));
        if(song.sourcePath){
          const verify=element('button','ตรวจไฟล์ใน Drive');verify.type='button';
          verify.onclick=async()=>{if(!current())return;verify.disabled=true;
            try{const t=performance.now();const linked=await session.resolve(song.sourcePath);
              if(current())verify.textContent='พบไฟล์ · '+linked.size.toLocaleString()+' ไบต์ · '+Math.round(performance.now()-t)+' ms (ยังไม่ยืนยันเนื้อหาเทียบ PC)';
            }catch(e){if(current())verify.textContent=String(e.message||e);}finally{verify.disabled=false;}};
          row.append(document.createTextNode(' '),verify);
        }
        results.append(row);
      }
      const s=session.reader.stats();
      stats.textContent='ค้นหา '+Math.round(performance.now()-started)+' ms · '+s.queryRequests+' requests · '+s.queryBytes.toLocaleString()+' ไบต์ · รวม '+s.bytes.toLocaleString()+' ไบต์';
      status.textContent=data.songs.length?'ค้นหาเสร็จ · '+(hasMore?'เลื่อนดูเพิ่มได้':'ครบผลลัพธ์'):'ไม่พบเพลง';
    }catch(e){if(current())status.textContent=String(e.message||e);}
    finally{busy=false;if(!current()){try{await session.reader.close();}catch{}return;}submit.disabled=false;more.disabled=!hasMore;}
  }
  form.onsubmit=e=>{e.preventDefault();void page(true);};more.onclick=()=>void page(false);
  try{
    session=await openGoogleExperiment({...options,current});
    if(!current()){await session.reader?.close();return;}
    const p=session.probe;
    stats.textContent='HTTP '+p.status+(p.bytes?' · '+p.bytes.toLocaleString()+' ไบต์':'')+(Number.isFinite(p.ms)?' · '+Math.round(p.ms)+' ms':'');
    if(!p.ok){status.textContent='ยังไม่อนุมัติ Range: '+p.reason;return;}
    status.textContent='ผ่านการตรวจ Range · '+session.reader.schema.kind;
    search.disabled=submit.disabled=false;search.focus();
  }catch(e){if(current())status.textContent='ทดสอบไม่สำเร็จ: '+String(e.message||e);}
}
