/* X-Stage Guest Song Requests: mobile never authenticates to Google Drive.
 * A host paired by WebRTC returns only basic searchable song metadata. */
'use strict';
(function(){
  const $=id=>document.getElementById(id);
  const status=$('remote-status'),controls=$('remote-controls'),search=$('remote-search');
  const results=$('remote-results'),singer=$('remote-singer'),note=$('remote-note');
  const requestHistory=$('remote-request-history');
  const params=new URLSearchParams(location.hash.replace(/^#/,''));
  const hostId=params.get('p'),secret=params.get('k');
  let peer=null,conn=null,connected=false,ready=false,searchTimer=null,querySequence=0;
  function report(value){status.textContent=value;}
  function send(message){if(connected&&conn?.open){try{conn.send(message);}catch{}}}
  controls.hidden=true;
  function showResults(items){
    results.replaceChildren();
    if(!Array.isArray(items)||!items.length){
      const p=document.createElement('p');p.className='remote-empty';
      p.textContent=search.value.trim()?'ไม่พบเพลงที่ตรงกับคำค้น':'พิมพ์ชื่อเพลง รหัส หรือศิลปิน';
      results.append(p);return;
    }
    for(const entry of items.slice(0,25)){
      if(!Number.isSafeInteger(entry.index)||entry.index<0)continue;
      const row=document.createElement('article');row.className='remote-song';
      const info=document.createElement('div');info.className='remote-song-info';
      const name=document.createElement('strong');name.textContent=String(entry.code||'')+' · '+String(entry.title||'');
      const artist=document.createElement('small');artist.textContent=String(entry.artist||'');
      const btn=document.createElement('button');btn.type='button';btn.className='remote-request-button';btn.textContent='ขอเพลง';
      btn.addEventListener('click',()=>{
        if(!ready){report('จอหลักยังไม่พร้อมรับคำขอเพลง');return;}
        const person=String(singer.value||'').trim().slice(0,45);
        if(!person){singer.focus();report('กรุณาระบุชื่อผู้ขอเพลงก่อน');return;}
        btn.disabled=true;btn.textContent='ส่งแล้ว';
        send({type:'request',index:entry.index,singer:person,note:String(note.value||'').trim().slice(0,90)});
      });
      info.append(name,artist);row.append(info,btn);results.append(row);
    }
  }
  function onMessage(data){
    if(!data||typeof data!=='object')return;
    if(data.type==='ready'){
      connected=true;controls.hidden=false;
      report('เชื่อมต่อแล้ว · ค้นหาและส่งคำขอเพลงได้ ไม่ต้องล็อกอิน Google');
      if(search.value.trim())search.dispatchEvent(new Event('input'));else showResults([]);
      return;
    }
    if(data.type==='status'){
      ready=!!data.ready;
      if(!ready)report('เชื่อมต่อแล้ว · รอเจ้าของเวทีเปิดคลังเพลง Google Drive');
      else if(controls.hidden===false&&status.textContent.includes('รอเจ้าของเวที'))
        report('พร้อมขอเพลง · เลือกเพลงด้านล่าง');
    }
    if(data.type==='results'){
      if(data.notReady){report('เจ้าของเวทียังไม่ได้เปิดคลังเพลง');return;}
      showResults(data.items);
    }
    if(data.type==='request-received'){
      const text='ส่งคำขอเพลงแล้ว: '+String(data.title||'')+' · รอเจ้าของเวทีเพิ่มลงคิว';
      const p=document.createElement('p');p.className='request-receipt';p.textContent=text;
      requestHistory.prepend(p);report(text);
    }
    if(data.type==='request-result'){
      const text=data.accepted?'เจ้าของเวทีรับคำขอและเพิ่มเพลงเข้าคิวแล้ว':'เจ้าของเวทีปฏิเสธคำขอเพลง';
      const p=document.createElement('p');p.className='request-receipt';p.textContent=text;
      requestHistory.prepend(p);report(text);
    }
    if(data.type==='request-error')report(String(data.message||'ส่งคำขอไม่สำเร็จ'));
  }
  search.addEventListener('input',()=>{
    clearTimeout(searchTimer);
    const term=search.value.trim();
    if(!term){results.replaceChildren();return;}
    const n=++querySequence;
    searchTimer=setTimeout(()=>{if(n===querySequence)send({type:'search',query:term.slice(0,70)});},250);
  });
  if(!hostId||!secret||!/^[a-z0-9_-]+$/i.test(hostId)||!/^[a-f0-9]{48}$/i.test(secret)){
    report('ลิงก์ QR ไม่ถูกต้อง กรุณาสแกน QR ที่จอ X-Stage อีกครั้ง');return;
  }
  if(typeof Peer!=='function'){report('โหลดการเชื่อมต่อรีโมทไม่สำเร็จ กรุณาตรวจอินเทอร์เน็ต');return;}
  report('กำลังเชื่อมต่อจอ X-Stage เพื่อส่งคำขอเพลง…');
  try{
    peer=new Peer();
    peer.on('open',()=>{
      conn=peer.connect(hostId,{reliable:true,serialization:'json'});
      conn.on('open',()=>{
        report('ตรวจสอบรหัส QR กับจอหลัก…');
        conn.send({type:'hello',key:secret});
      });
      conn.on('data',onMessage);
      conn.on('close',()=>{connected=false;ready=false;controls.hidden=true;report('การเชื่อมต่อสิ้นสุด กรุณาสแกน QR ใหม่');});
      conn.on('error',()=>{connected=false;controls.hidden=true;report('เชื่อมต่อจอหลักไม่สำเร็จ');});
    });
    peer.on('error',err=>report('เชื่อมต่อไม่ได้: '+String(err?.type||'เครือข่ายไม่พร้อม')));
  }catch{report('เริ่มระบบขอเพลงไม่สำเร็จ');}
  window.addEventListener('beforeunload',()=>{try{conn?.close();peer?.destroy();}catch{}});
})();