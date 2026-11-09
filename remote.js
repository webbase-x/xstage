/* X-Stage mobile remote; no Google Drive sign-in or credentials on this device. */
'use strict';
(function(){
  const $=id=>document.getElementById(id);
  const status=$('remote-status');
  const controls=$('remote-controls');
  const search=$('remote-search');
  const results=$('remote-results');
  const now=$('remote-now');
  const artist=$('remote-artist');
  const queue=$('remote-queue');
  const volume=$('remote-volume');
  const play=$('remote-play');
  const params=new URLSearchParams(location.hash.replace(/^#/,''));
  const hostId=params.get('p'),secret=params.get('k');
  let peer=null,conn=null,approved=false,searchTimer=null;
  function report(value){status.textContent=value;}
  function send(message){if(approved&&conn?.open){try{conn.send(message);}catch{}}}
  function control(action,value){send({type:'control',action,value});}
  controls.hidden=true;
  $('remote-prev').addEventListener('click',()=>control('previous'));
  play.addEventListener('click',()=>control('play'));
  $('remote-stop').addEventListener('click',()=>control('stop'));
  $('remote-next').addEventListener('click',()=>control('next'));
  volume.addEventListener('input',()=>control('volume',Number(volume.value)));
  search.addEventListener('input',()=>{
    clearTimeout(searchTimer);
    if(!search.value.trim()){results.replaceChildren();return;}
    searchTimer=setTimeout(()=>send({type:'search',query:search.value.trim().slice(0,70)}),220);
  });
  function button(label,fn,cls){
    const b=document.createElement('button');b.type='button';b.textContent=label;
    if(cls)b.className=cls;b.addEventListener('click',fn);return b;
  }
  function drawResults(items){
    results.replaceChildren();
    if(!Array.isArray(items))return;
    if(!items.length){const p=document.createElement('p');p.className='remote-empty';p.textContent='ไม่พบเพลง';results.append(p);return;}
    for(const item of items.slice(0,30)){
      if(!Number.isSafeInteger(item.index))continue;
      const row=document.createElement('article');row.className='remote-song';
      const info=document.createElement('div');info.className='remote-song-info';
      const title=document.createElement('strong');title.textContent=String(item.code||'')+' · '+String(item.title||'');
      const subtitle=document.createElement('small');subtitle.textContent=String(item.artist||'');
      info.append(title,subtitle);
      const actions=document.createElement('div');actions.className='remote-song-actions';
      actions.append(button('▶',()=>send({type:'song',index:item.index,mode:'now'}),'remote-play-now'),
        button('+',()=>send({type:'song',index:item.index,mode:'queue'}),'remote-add-queue'));
      row.append(info,actions);results.append(row);
    }
  }
  function onMessage(data){
    if(!data||typeof data!=='object')return;
    if(data.type==='ready'){
      approved=true;controls.hidden=false;report('เชื่อมต่อแล้ว · ควบคุมเพลงจากมือถือได้');
      search.focus();return;
    }
    if(!approved)return;
    if(data.type==='results'){drawResults(data.items);return;}
    if(data.type==='status'){
      now.textContent=data.now||'ยังไม่ได้เลือกเพลง';
      artist.textContent=data.artist||'X-Stage Karaoke';
      queue.textContent=String(Number(data.queue)||0);
      volume.value=String(Math.max(0,Math.min(100,Number(data.volume)||0)));
      play.textContent=data.paused?'▶':'⏸';
      if(!data.ready){report('จอหลักต้องเข้าสู่ระบบ Google ก่อน');}
    }
  }
  if(!hostId||!secret||!/^[-_a-z0-9]+$/i.test(hostId)||!/^[a-f0-9]{48}$/i.test(secret)){
    report('ไม่พบข้อมูลจับคู่ที่ถูกต้อง กรุณาสแกน QR จากจอ X-Stage อีกครั้ง');
    return;
  }
  if(typeof Peer!=='function'){
    report('ไม่สามารถโหลดระบบรีโมทได้ กรุณาตรวจอินเทอร์เน็ต');
    return;
  }
  report('กำลังเชื่อมต่อจอ X-Stage…');
  try{
    peer=new Peer();
    peer.on('open',()=>{
      conn=peer.connect(hostId,{reliable:true,serialization:'json'});
      conn.on('open',()=>{
        report('กำลังรออนุญาตจากหน้าจอหลัก…');
        conn.send({type:'hello',key:secret});
      });
      conn.on('data',onMessage);
      conn.on('close',()=>{approved=false;controls.hidden=true;report('การเชื่อมต่อสิ้นสุด กรุณาสแกน QR ใหม่');});
      conn.on('error',()=>{approved=false;controls.hidden=true;report('เชื่อมต่อจอหลักไม่สำเร็จ');});
    });
    peer.on('error',err=>{report('เกิดปัญหาเครือข่ายหรือจับคู่ไม่ได้: '+String(err?.type||'ไม่ทราบสาเหตุ'));});
  }catch{
    report('เริ่มระบบรีโมทไม่สำเร็จ');
  }
  window.addEventListener('beforeunload',()=>{
    try{conn?.close();peer?.destroy();}catch{}
  });
})();