/* X-Stage paired remote: host approves first connection. Commands are whitelisted
 * on the host and never expose OAuth tokens, audio URLs, lyrics or Drive IDs. */
'use strict';
(function(){
  const $=id=>document.getElementById(id);
  const status=$('remote-status'),controls=$('remote-controls');
  const search=$('remote-search'),results=$('remote-results');
  const singer=$('remote-singer'),note=$('remote-note'),history=$('remote-request-history');
  const queueList=$('remote-queue-list'),queueCount=$('remote-queue-count');
  const nowTitle=$('remote-now'),nowArtist=$('remote-now-artist');
  const params=new URLSearchParams(location.hash.replace(/^#/,''));
  const hostId=params.get('p'),secret=params.get('k');
  let peer=null,conn=null,connected=false,ready=false;
  let searchTimer=null,querySequence=0,activeTab='search';
  const pendingButtons=new Set();
  const reconnectButton=document.createElement('button');
  reconnectButton.type='button';reconnectButton.textContent='↻ เชื่อมต่ออีกครั้ง';
  reconnectButton.hidden=true;status.after(reconnectButton);
  const scanLink=document.createElement('a');
  scanLink.href='remote.html';scanLink.textContent='📷 สแกน QR ใหม่';
  scanLink.hidden=true;reconnectButton.after(scanLink);
  function disconnected(message){
    connected=false;ready=false;controls.hidden=true;
    reconnectButton.hidden=!hostId||!secret;
    scanLink.hidden=false;report(message);
  }
  function report(message){status.textContent=message;}
  function send(msg){if(connected&&conn?.open)try{conn.send(msg);}catch{}}
  function control(action){send({type:'control',action});}
  function setTab(tab){
    activeTab=tab;
    for(const id of ['search','queue','control']){
      const visible=id===tab;
      $('remote-panel-'+id).hidden=!visible;
      $('remote-tab-'+id).setAttribute('aria-selected',String(visible));
    }
    if(tab==='queue')send({type:'refresh'});
  }
  for(const id of ['search','queue','control'])$('remote-tab-'+id).addEventListener('click',()=>setTab(id));
  controls.hidden=true;
  setTab('search');
  function resetButtons(){
    for(const b of pendingButtons){b.disabled=false;b.textContent='ขอเพลง';}
    pendingButtons.clear();
  }
  function drawResults(items){
    results.replaceChildren();pendingButtons.clear();
    if(!Array.isArray(items)||!items.length){
      const p=document.createElement('p');p.className='remote-empty';
      p.textContent=search.value.trim()?'ไม่พบเพลงที่ตรงกับคำค้น':'พิมพ์เพื่อค้นหาเพลง';
      results.append(p);return;
    }
    for(const item of items.slice(0,30)){
      if(!Number.isSafeInteger(item.index)||item.index<0)continue;
      const row=document.createElement('article');row.className='remote-song';
      const info=document.createElement('div');info.className='remote-song-info';
      const title=document.createElement('strong');
      title.textContent=String(item.code||'')+' · '+String(item.title||'');
      const artist=document.createElement('small');artist.textContent=String(item.artist||'');
      const btn=document.createElement('button');btn.type='button';
      btn.className='remote-request-button';btn.textContent='ขอเพลง';
      btn.addEventListener('click',()=>{
        if(!ready){report('จอหลักยังไม่พร้อม กรุณาให้เจ้าของเวทีเปิดคลังเพลง');return;}
        if(!connected)return;
        btn.disabled=true;btn.textContent='กำลังส่ง';
        pendingButtons.add(btn);
        send({type:'request',index:item.index,
          singer:String(singer.value||'ไม่ระบุชื่อ').trim().slice(0,45)||'ไม่ระบุชื่อ',
          note:String(note.value||'').trim().slice(0,90)});
      });
      info.append(title,artist);row.append(info,btn);results.append(row);
    }
  }
  function drawQueue(items,total){
    queueCount.textContent=String(Number(total)||0);
    queueList.replaceChildren();
    if(!Array.isArray(items)||!items.length){
      const empty=document.createElement('p');empty.className='remote-empty';
      empty.textContent='คิวว่าง · เพลงใหม่จะเริ่มเล่นทันทีหากไม่มีเพลงกำลังเล่น';
      queueList.append(empty);return;
    }
    items.slice(0,50).forEach((song,index)=>{
      const row=document.createElement('article');row.className='remote-queue-row';
      const number=document.createElement('span');number.className='queue-number';
      number.textContent=String(index+1);
      const info=document.createElement('div'),title=document.createElement('strong'),subtitle=document.createElement('small');
      title.textContent=String(song?.title||song?.code||'ไม่ทราบชื่อเพลง');
      subtitle.textContent=[song?.artist,song?.singer?'ผู้ขอ: '+song.singer:''].filter(Boolean).join(' · ');
      info.append(title,subtitle);row.append(number,info);queueList.append(row);
    });
  }
  function receipt(value){
    const item=document.createElement('p');item.className='request-receipt';
    item.textContent=value;history.prepend(item);
    while(history.children.length>12)history.lastElementChild.remove();
    report(value);
  }
  function handleMessage(data){
    if(!data||typeof data!=='object')return;
    if(data.type==='pending'){
      report('กำลังรอเจ้าของเวทีอนุมัติการเชื่อมต่อครั้งแรก…');return;
    }
    if(data.type==='ready'){
      connected=true;controls.hidden=false;
      reconnectButton.hidden=true;scanLink.hidden=true;
      report('เชื่อมต่อแล้ว · ขอเพลงและควบคุมเวทีได้ ไม่ต้องล็อกอิน Google');
      if(search.value.trim())search.dispatchEvent(new Event('input'));else drawResults([]);
      send({type:'refresh'});return;
    }
    if(data.type==='error'){report(String(data.message||'เชื่อมต่อไม่ได้'));return;}
    if(!connected)return;
    if(data.type==='status'){
      ready=!!data.ready;
      nowTitle.textContent=String(data.now?.title||'ยังไม่ได้เลือกเพลง');
      nowArtist.textContent=String(data.now?.artist||'X-Stage Karaoke');
      drawQueue(data.queue,data.queueCount);
      $('remote-playpause').textContent=data.playing?'⏸ พัก':'▶ เล่น';
      $('remote-volume-label').textContent=String(Math.round(Number(data.volume)||0))+'%';
      const mute=$('remote-mute');
      mute.setAttribute('aria-pressed',String(!!data.muted));
      mute.textContent=data.muted?'🔇 เปิดเสียง':'🔊 ปิดเสียง';
      const medley=$('remote-medley');medley.setAttribute('aria-pressed',String(!!data.medley));
      medley.textContent=data.medley?'♫ ปิดสุ่มเพลงต่อเนื่อง':'♫ เปิดสุ่มเพลงต่อเนื่อง';
      const full=!!data.fullscreen;
      $('remote-screen-state').textContent=full
        ?'จอหลักอยู่ในโหมด Fullscreen · กด “ย่อจอหลัก” เพื่อออก'
        :data.fullscreenPending
          ?'รอยืนยันเปิด Fullscreen · แตะปุ่มที่แสดงบนจอหลักหนึ่งครั้ง'
          :'จอหลักแสดงแบบปกติ · กด “เต็มจอหลัก” เพื่อขอเปิด Fullscreen';
      $('remote-fullscreen-on').disabled=full;
      $('remote-fullscreen-off').disabled=!full&&!data.fullscreenPending;
      if(!ready && !status.textContent.includes('ยังไม่พร้อม'))
        report('เชื่อมต่อแล้ว · เจ้าของเวทีต้องเปิดคลัง Google Drive ก่อนขอเพลง');
    }else if(data.type==='results'){
      if(data.notReady){report('จอหลักยังไม่ได้เปิดคลังเพลง');drawResults([]);return;}
      if(String(data.query||'')===search.value.trim().toLocaleLowerCase('th'))drawResults(data.items);
    }else if(data.type==='request-received'){
      resetButtons();
      clearTimeout(searchTimer);querySequence++;
      search.value='';results.replaceChildren();
      const outcome=data.result==='playing'?'เริ่มเล่นทันที':'เพิ่มเข้าคิวแล้ว';
      receipt('ส่งเพลง '+String(data.title||'')+' สำเร็จ · '+outcome);
      send({type:'refresh'});
    }else if(data.type==='request-error'){
      resetButtons();
      report(String(data.message||'ขอเพลงไม่สำเร็จ'));
    }
  }
  search.addEventListener('input',()=>{
    clearTimeout(searchTimer);
    const term=search.value.trim().toLocaleLowerCase('th');
    if(!term){querySequence++;results.replaceChildren();return;}
    const n=++querySequence;
    searchTimer=setTimeout(()=>{if(n===querySequence)send({type:'search',query:term.slice(0,70)});},250);
  });
  for(const [id,action] of [
    ['remote-playpause','playpause'],['remote-stop','stop'],['remote-next','next'],
    ['remote-vol-down','volume-down'],['remote-vol-up','volume-up'],
    ['remote-mute','mute'],['remote-fullscreen-on','fullscreen-on'],
    ['remote-fullscreen-off','fullscreen-off'],['remote-medley','medley']
  ])$(id).addEventListener('click',()=>control(action));
  if(!hostId||!secret||!/^[a-z0-9_-]+$/i.test(hostId)||!/^[a-f0-9]{48}$/i.test(secret)){
    report('QR ไม่ถูกต้อง กรุณาสแกน QR ใหม่จากจอ X-Stage');return;
  }
  if(typeof Peer!=='function'){report('โหลดระบบจับคู่ไม่สำเร็จ กรุณาตรวจอินเทอร์เน็ต');return;}
  report('กำลังเชื่อมต่อรีโมท X-Stage…');
  function connect(){
    if(peer){try{peer.destroy();}catch{}}
    peer=new Peer();
    peer.on('open',()=>{
      conn=peer.connect(hostId,{reliable:true,serialization:'json'});
      conn.on('open',()=>{
        report('กำลังยืนยัน QR กับจอหลัก…');
        conn.send({type:'hello',key:secret});
      });
      conn.on('data',handleMessage);
      conn.on('close',()=>disconnected('ขาดการเชื่อมต่อ · เชื่อมต่ออีกครั้งหรือสแกน QR ใหม่'));
      conn.on('error',()=>disconnected('เชื่อมต่อกับเวทีไม่ได้'));
    });
    peer.on('error',err=>disconnected('เครือข่ายไม่พร้อม: '+String(err?.type||'ไม่ทราบสาเหตุ')));
  }
  reconnectButton.addEventListener('click',()=>{try{connect();reconnectButton.hidden=true;report('กำลังเชื่อมต่อ…');}catch{disconnected('เชื่อมต่อไม่สำเร็จ');}});
  try{connect();}catch{disconnected('เริ่มระบบรีโมทไม่สำเร็จ');}
  window.addEventListener('beforeunload',()=>{try{conn?.close();peer?.destroy();}catch{}});
})();