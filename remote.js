/* X-Stage mobile remote.
 * Guest: QR-paired basic controls only.
 * Owner: Google access token is sent once over the encrypted WebRTC data channel,
 * verified by the TV against Google userinfo + the TV account sub, then discarded. */
'use strict';
(function(){
  const $=id=>document.getElementById(id);
  const status=$('remote-status'),controls=$('remote-controls');
  const search=$('remote-search'),results=$('remote-results');
  const singer=$('remote-singer'),note=$('remote-note'),history=$('remote-request-history');
  const queueList=$('remote-queue-list'),queueCount=$('remote-queue-count');
  const nowTitle=$('remote-now'),nowArtist=$('remote-now-artist'),nowTime=$('remote-now-time');
  const ownerGate=$('remote-owner-gate'),ownerPanel=$('remote-owner-panel');
  const ownerStatus=$('remote-owner-status'),ownerBadge=$('remote-owner-badge');
  const roleNote=$('remote-role-note');
  const params=new URLSearchParams(location.hash.replace(/^#/,''));
  const hostId=params.get('p'),secret=params.get('k');
  let peer=null,conn=null,connected=false,ready=false,connectWatchdog=0;
  let searchTimer=null,querySequence=0,activeTab='search',role='guest';
  let ownerAccessToken='';
  const pendingButtons=new Set();

  const reconnectButton=document.createElement('button');
  reconnectButton.type='button';reconnectButton.textContent='↻ เชื่อมต่ออีกครั้ง';
  reconnectButton.hidden=true;status.after(reconnectButton);
  const scanLink=document.createElement('a');
  scanLink.href='#scan-qr';scanLink.textContent='📷 สแกน QR ใหม่';
  scanLink.hidden=true;reconnectButton.after(scanLink);

  function clearConnectWatchdog(){if(connectWatchdog){clearTimeout(connectWatchdog);connectWatchdog=0;}}
  function report(message,state='info'){status.textContent=message;status.dataset.state=state;}
  function timeLabel(value){
    const n=Number(value);if(!Number.isFinite(n)||n<0)return '--:--';
    const total=Math.floor(n),h=Math.floor(total/3600),m=String(Math.floor(total/60)%60).padStart(2,'0'),sec=String(total%60).padStart(2,'0');
    return h?String(h)+':'+m+':'+sec:m+':'+sec;
  }
  function send(msg){if(connected&&conn?.open)try{conn.send(msg);}catch{}}
  function control(action){send({type:'control',action});}
  function admin(action,value){if(role==='owner')send({type:'admin',action,value});}
  function setRole(next,email=''){
    role=next==='owner'?'owner':'guest';
    document.body.dataset.remoteRole=role;
    ownerGate.hidden=role==='owner';
    ownerPanel.hidden=role!=='owner';
    roleNote.textContent=role==='owner'
      ? 'โหมด Owner · ควบคุมเวทีและระบบได้เต็มรูปแบบ'
      : 'โหมด Guest · ค้นหา/ขอเพลง ดูคิว เล่น–พัก และปรับเสียงพื้นฐาน';
    if(role==='owner'){
      ownerBadge.textContent='✓ Owner · '+(email||'บัญชีเดียวกับจอ TV');
      ownerStatus.textContent='ยืนยันบัญชีเรียบร้อย';
    }else{
      ownerStatus.textContent='ยังไม่ได้ยืนยันสิทธิ์ผู้ดูแล';
    }
  }
  function setTab(tab){
    activeTab=tab;
    for(const id of ['search','queue','control','owner']){
      const visible=id===tab;
      $('remote-panel-'+id).hidden=!visible;
      $('remote-tab-'+id).setAttribute('aria-selected',String(visible));
    }
    if(tab==='queue'||tab==='owner')send({type:'refresh'});
  }
  for(const id of ['search','queue','control','owner'])$('remote-tab-'+id).addEventListener('click',()=>setTab(id));
  controls.hidden=true;setTab('search');setRole('guest');

  function disconnected(message){
    clearConnectWatchdog();
    connected=false;ready=false;controls.hidden=true;setRole('guest');
    reconnectButton.hidden=!hostId||!secret;scanLink.hidden=false;report(message,'disconnected');
  }
  function resetButtons(){for(const b of pendingButtons){b.disabled=false;b.textContent='ขอเพลง';}pendingButtons.clear();}
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
      const title=document.createElement('strong');title.textContent=String(item.code||'')+' · '+String(item.title||'');
      const artist=document.createElement('small');artist.textContent=String(item.artist||'');
      const btn=document.createElement('button');btn.type='button';btn.className='remote-request-button';btn.textContent='ขอเพลง';
      btn.addEventListener('click',()=>{
        if(!ready){report('จอ TV ยังไม่พร้อม กรุณารอให้เปิดคลังเพลง');return;}
        if(!connected)return;
        btn.disabled=true;btn.textContent='กำลังส่ง';pendingButtons.add(btn);
        send({type:'request',index:item.index,
          singer:String(singer.value||'ไม่ระบุชื่อ').trim().slice(0,45)||'ไม่ระบุชื่อ',
          note:String(note.value||'').trim().slice(0,90)});
      });
      info.append(title,artist);row.append(info,btn);results.append(row);
    }
  }
  function drawQueue(items,total){
    queueCount.textContent=String(Number(total)||0);queueList.replaceChildren();
    if(!Array.isArray(items)||!items.length){
      const empty=document.createElement('p');empty.className='remote-empty';
      empty.textContent='คิวว่าง · เพลงใหม่จะเริ่มเล่นทันทีหากไม่มีเพลงกำลังเล่น';
      queueList.append(empty);return;
    }
    items.slice(0,50).forEach((song,index)=>{
      const row=document.createElement('article');row.className='remote-queue-row';
      const number=document.createElement('span');number.className='queue-number';number.textContent=String(index+1);
      const info=document.createElement('div'),title=document.createElement('strong'),subtitle=document.createElement('small');
      title.textContent=String(song?.title||song?.code||'ไม่ทราบชื่อเพลง');
      subtitle.textContent=[song?.artist,song?.singer?'ผู้ขอ: '+song.singer:''].filter(Boolean).join(' · ');
      info.append(title,subtitle);row.append(number,info);
      if(role==='owner'){
        const actions=document.createElement('div');actions.className='remote-queue-actions';
        const make=(label,action,value,disabled=false)=>{
          const button=document.createElement('button');button.type='button';button.textContent=label;button.disabled=disabled;
          button.addEventListener('click',()=>admin(action,value));return button;
        };
        actions.append(
          make('▶','queue-play',{index}),
          make('↑','queue-move',{index,delta:-1},index===0),
          make('↓','queue-move',{index,delta:1},index===items.length-1),
          make('×','queue-remove',{index})
        );
        row.append(actions);
      }
      queueList.append(row);
    });
  }
  function receipt(value){
    const item=document.createElement('p');item.className='request-receipt';item.textContent=value;history.prepend(item);
    while(history.children.length>12)history.lastElementChild.remove();report(value);
  }
  function revokeOwnerToken(){
    const token=ownerAccessToken;ownerAccessToken='';
    if(token&&window.google?.accounts?.oauth2?.revoke)try{google.accounts.oauth2.revoke(token,()=>{});}catch{}
  }
  function ownerLogin(){
    if(!connected){ownerStatus.textContent='ยังไม่ได้เชื่อมต่อจอ TV';return;}
    const cfg=window.XSTAGE_CONFIG||{};
    if(!cfg.googleClientId){ownerStatus.textContent='เว็บไซต์ยังไม่ได้ตั้ง Google OAuth Web Client ID';return;}
    if(!window.google?.accounts?.oauth2?.initTokenClient){
      ownerStatus.textContent='กำลังโหลด Google Sign-In · กรุณากดอีกครั้ง';return;
    }
    ownerStatus.textContent='กำลังเปิด Google เพื่อยืนยันบัญชี…';
    try{
      const client=google.accounts.oauth2.initTokenClient({
        client_id:cfg.googleClientId,
        scope:'openid email',
        callback:result=>{
          if(result?.error||!result?.access_token){
            ownerStatus.textContent='ยืนยัน Google ไม่สำเร็จ';return;
          }
          ownerAccessToken=String(result.access_token);
          ownerStatus.textContent='กำลังตรวจว่าบัญชีตรงกับจอ TV…';
          send({type:'owner-auth',accessToken:ownerAccessToken});
        },
        error_callback:()=>{ownerStatus.textContent='ไม่สามารถเปิด Google Sign-In ได้';}
      });
      client.requestAccessToken({prompt:'select_account'});
    }catch(error){ownerStatus.textContent=String(error?.message||'เปิด Google Sign-In ไม่สำเร็จ');}
  }
  $('remote-owner-login').addEventListener('click',ownerLogin);

  function downloadQueue(data){
    const body=JSON.stringify({schema:'xstage-remote-queue-v1',exportedAt:new Date().toISOString(),items:Array.isArray(data)?data:[]},null,2);
    const blob=new Blob([body],{type:'application/json'});
    const url=URL.createObjectURL(blob),a=document.createElement('a');
    a.href=url;a.download='X-Stage-Queue-'+new Date().toISOString().slice(0,10)+'.json';
    document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }

  function handleMessage(data){
    if(!data||typeof data!=='object')return;
    if(data.type==='pending'){report('กำลังรอจอ TV อนุมัติการเชื่อมต่อครั้งแรก…','pending');return;}
    if(data.type==='ready'){
      connected=true;controls.hidden=false;reconnectButton.hidden=true;scanLink.hidden=true;setRole('guest');
      report('เชื่อมต่อแล้ว · Guest ใช้คำสั่งพื้นฐานได้ทันที','connected');
      if(search.value.trim())search.dispatchEvent(new Event('input'));else drawResults([]);
      send({type:'refresh'});return;
    }
    if(data.type==='role'){
      revokeOwnerToken();
      if(data.role==='owner'){setRole('owner',String(data.email||''));report('Owner ยืนยันแล้ว · ควบคุมเต็มระบบ','connected');send({type:'refresh'});}
      else{setRole('guest');ownerStatus.textContent=String(data.message||'บัญชีไม่ตรงกับจอ TV');report(ownerStatus.textContent,'error');send({type:'refresh'});}
      return;
    }
    if(data.type==='error'){report(String(data.message||'เชื่อมต่อไม่ได้'),'error');return;}
    if(data.type==='fullscreen-notice'){report(String(data.message||'ไม่สามารถเปลี่ยนโหมดจอได้'),'error');return;}
    if(data.type==='admin-result'){
      const message=String(data.message||'ดำเนินการแล้ว');
      if(data.action==='export-queue'&&Array.isArray(data.data))downloadQueue(data.data);
      if(data.action==='share-library')$('owner-share-status').textContent=message;
      else if(data.action==='history'){
        const box=$('owner-history-list');box.replaceChildren();
        const items=Array.isArray(data.data)?data.data:[];
        if(!items.length)box.textContent='ยังไม่มีประวัติการเล่น';
        else for(const item of items.slice(0,20)){
          const p=document.createElement('p');
          p.textContent=[item.code,item.title,item.artist].filter(Boolean).join(' · ');
          box.append(p);
        }
      }else if(data.action==='favorite-current'){
        $('owner-favorite-current').textContent=data.data?.favorite?'★ เอาเพลงปัจจุบันออกจากโปรด':'☆ เพิ่มเพลงปัจจุบันเป็นโปรด';
        report(message,data.ok===false?'error':'connected');
      }else report(message,data.ok===false?'error':'connected');
      return;
    }
    if(!connected)return;
    if(data.type==='status'){
      ready=!!data.ready;
      if(data.role==='owner'&&role!=='owner')setRole('owner',String(data.ownerEmail||''));
      if(data.role!=='owner'&&role==='owner')setRole('guest');
      const stagePop=$('owner-stage-pop');
      if(stagePop){
        const androidTv=data.platform==='android-tv';
        stagePop.disabled=androidTv;
        stagePop.textContent=androidTv?'จอร้องแยก · PC Web เท่านั้น':'จอร้องแยก';
      }
      const perms=data.permissions||{};
      $('remote-search').disabled=perms.search===false;
      if(perms.search===false){results.replaceChildren();results.textContent='จอ TV ปิดการค้นหาเพลง';}
      document.querySelectorAll('.remote-request-button').forEach(b=>b.disabled=perms.request===false);
      for(const [id,key] of [['remote-playpause','playpause'],['remote-vol-down','volume-down'],['remote-vol-up','volume-up'],['remote-mute','mute']]){
        $(id).disabled=perms[key]===false;
      }
      nowTitle.textContent=String(data.now?.title||'ยังไม่ได้เลือกเพลง');
      nowArtist.textContent=String(data.now?.artist||'X-Stage Karaoke');
      nowTime.textContent=timeLabel(data.currentTime)+' / '+timeLabel(data.duration);
      drawQueue(data.queue,data.queueCount);
      $('remote-playpause').textContent=data.playing?'⏸ พัก':'▶ เล่น';
      const volumeText=String(Math.round(Number(data.volume)||0))+'%';
      $('remote-volume-label').textContent=data.muted?'ปิดเสียง · '+volumeText:volumeText;
      const mute=$('remote-mute');mute.setAttribute('aria-pressed',String(!!data.muted));mute.textContent=data.muted?'🔇 เปิดเสียง':'🔊 ปิดเสียง';
      if(role==='owner'){
        $('owner-medley').setAttribute('aria-pressed',String(!!data.medley));
        $('owner-medley').textContent=data.medley?'♫ ปิดเมดเลย์':'♫ เปิดเมดเลย์';
        $('owner-repeat').setAttribute('aria-pressed',String(!!data.repeat));
        $('owner-repeat').textContent=data.repeat?'⇄ ปิดวนเพลง':'⇄ เปิดวนเพลง';
        if(data.speed)$('owner-speed').value=String(data.speed);
        if(data.eqPreset&&[...$('owner-eq-preset').options].some(o=>o.value===data.eqPreset))$('owner-eq-preset').value=data.eqPreset;
        $('owner-eq-state').textContent=data.eqActive?'EQ ทำงาน · '+String(data.eqPreset||'').toUpperCase():'เสียง Native · EQ ยังไม่ทำงาน';
        const visual=data.visualSettings||{};
        if(visual.background&&[...$('owner-background').options].some(o=>o.value===visual.background))$('owner-background').value=visual.background;
        if(visual.brandTheme&&[...$('owner-brand-theme').options].some(o=>o.value===visual.brandTheme))$('owner-brand-theme').value=visual.brandTheme;
        if(visual.lyricScale)$('owner-lyric-scale').value=String(visual.lyricScale);
        if(/^#[0-9a-f]{6}$/i.test(String(visual.lyricColor||'')))$('owner-lyric-color').value=String(visual.lyricColor);
        $('remote-qr-state').textContent=data.pairingPaused?'QR แสดงอยู่ · พักรับผู้ใช้ใหม่':'QR แสดงถาวร · เปิดรับผู้ใช้ใหม่';
        const updateButton=$('owner-update');
        if(updateButton){
          const release=data.updateAvailable;
          updateButton.textContent=release?.version?'อัปเดต X-Stage '+String(release.version):'ตรวจสอบ / อัปเดต X-Stage';
          updateButton.title=String(data.updateStatus||'ตรวจสอบเวอร์ชันล่าสุด');
        }
        $('owner-qr-pause').disabled=!!data.pairingPaused;
        $('owner-qr-resume').disabled=!data.pairingPaused;
      }
      if(!ready&&!status.textContent.includes('ยังไม่พร้อม'))report('เชื่อมต่อแล้ว · รอจอ TV เปิดคลัง Google Drive','connected');
    }else if(data.type==='results'){
      if(data.notReady){report('จอ TV ยังไม่ได้เปิดคลังเพลง');drawResults([]);return;}
      if(String(data.query||'')===search.value.trim().toLocaleLowerCase('th'))drawResults(data.items);
    }else if(data.type==='request-received'){
      resetButtons();clearTimeout(searchTimer);querySequence++;search.value='';results.replaceChildren();
      const outcome=data.result==='playing'?'เริ่มเล่นทันที':'เพิ่มเข้าคิวแล้ว';
      receipt('ส่งเพลง '+String(data.title||'')+' สำเร็จ · '+outcome);send({type:'refresh'});
    }else if(data.type==='request-error'){
      resetButtons();report(String(data.message||'ขอเพลงไม่สำเร็จ'),'error');
    }
  }

  search.addEventListener('input',()=>{
    clearTimeout(searchTimer);
    const term=search.value.trim().toLocaleLowerCase('th');
    if(!term){querySequence++;results.replaceChildren();return;}
    const n=++querySequence;
    searchTimer=setTimeout(()=>{if(n===querySequence)send({type:'search',query:term.slice(0,70)});},250);
  });
  for(const [id,action] of [['remote-playpause','playpause'],['remote-vol-down','volume-down'],['remote-vol-up','volume-up'],['remote-mute','mute']])
    $(id).addEventListener('click',()=>control(action));

  document.querySelectorAll('[data-admin]').forEach(button=>button.addEventListener('click',()=>admin(button.dataset.admin)));
  $('owner-speed').addEventListener('change',()=>admin('speed',$('owner-speed').value));
  $('owner-eq-preset').addEventListener('change',()=>admin('eq-preset',$('owner-eq-preset').value));
  $('owner-background').addEventListener('change',()=>admin('visual-background',$('owner-background').value));
  $('owner-brand-theme').addEventListener('change',()=>admin('visual-brand-theme',$('owner-brand-theme').value));
  $('owner-lyric-scale').addEventListener('change',()=>admin('visual-lyric-scale',$('owner-lyric-scale').value));
  $('owner-lyric-color').addEventListener('change',()=>admin('visual-lyric-color',$('owner-lyric-color').value));
  $('owner-history').addEventListener('click',()=>admin('history'));
  $('owner-favorite-current').addEventListener('click',()=>admin('favorite-current'));
  $('owner-qr-pause').addEventListener('click',()=>admin('qr-pause'));
  $('owner-qr-resume').addEventListener('click',()=>admin('qr-resume'));
  $('owner-export-queue').addEventListener('click',()=>admin('export-queue'));
  $('owner-import-queue').addEventListener('click',()=>$('owner-import-file').click());
  $('owner-import-file').addEventListener('change',async()=>{
    const file=$('owner-import-file').files?.[0];if(!file)return;
    try{
      const parsed=JSON.parse(await file.text());
      const items=Array.isArray(parsed)?parsed:Array.isArray(parsed?.items)?parsed.items:[];
      admin('import-queue',items.slice(0,150).map(item=>({code:String(item?.code||''),title:String(item?.title||''),artist:String(item?.artist||'')})));
    }catch{report('ไฟล์คิวไม่ถูกต้อง','error');}
    $('owner-import-file').value='';
  });
  $('owner-share').addEventListener('click',()=>{
    const email=String($('owner-share-email').value||'').trim();
    $('owner-share-status').textContent='กำลังแชร์…';admin('share-library',email);
  });

  $('owner-about').addEventListener('click',()=>{
    const release=window.XSTAGE_RELEASE||{};
    alert('X-Stage Karaoke Online\nเวอร์ชัน '+String(release.version||'')+' · Build '+String(release.build||'')+'\nรีโมท Owner · บัญชี Google เดียวกับจอ TV');
  });

  scanLink.addEventListener('click',async event=>{
    event.preventDefault();
    if(!navigator.mediaDevices?.getUserMedia||typeof BarcodeDetector==='undefined'){
      report('เบราว์เซอร์นี้ยังไม่รองรับสแกน QR ด้วยกล้อง กรุณาใช้กล้องมือถือสแกน QR บนจอ TV');return;
    }
    let stream;const video=document.createElement('video');video.autoplay=true;video.playsInline=true;
    video.style.cssText='display:block;width:100%;max-height:250px;margin:10px 0;border-radius:10px';
    const stop=document.createElement('button');stop.type='button';stop.textContent='ปิดกล้อง';scanLink.after(video,stop);
    let active=true;const close=()=>{active=false;stream?.getTracks().forEach(track=>track.stop());video.remove();stop.remove();};
    stop.addEventListener('click',close);
    try{
      stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment'},audio:false});video.srcObject=stream;await video.play();
      const detector=new BarcodeDetector({formats:['qr_code']});
      const check=async()=>{
        if(!active)return;
        try{
          for(const code of await detector.detect(video)){
            const url=new URL(code.rawValue,location.href),parsed=new URLSearchParams(url.hash.replace(/^#/,''));
            if(url.origin===location.origin&&url.pathname.endsWith('/remote.html')&&/^[a-f0-9]{48}$/i.test(parsed.get('k')||'')&&/^[a-z0-9_-]+$/i.test(parsed.get('p')||'')){
              close();location.assign(url.href);return;
            }
          }
        }catch{}
        if(active)setTimeout(check,300);
      };check();
    }catch{close();report('ไม่สามารถเปิดกล้องได้ กรุณาตรวจสิทธิ์กล้อง');}
  });

  if(!hostId||!secret||!/^[a-z0-9_-]+$/i.test(hostId)||!/^[a-f0-9]{48}$/i.test(secret)){
    scanLink.hidden=false;reconnectButton.hidden=true;report('ยังไม่มีรหัส QR · แตะ 📷 เพื่อสแกนจากจอ TV');return;
  }
  if(typeof Peer!=='function'){report('โหลดระบบจับคู่ไม่สำเร็จ กรุณาตรวจอินเทอร์เน็ต');return;}
  report('กำลังเชื่อมต่อรีโมท X-Stage…','connecting');

  function connect(){
    clearConnectWatchdog();setRole('guest');
    if(peer){try{peer.destroy();}catch{}}
    peer=new Peer();
    connectWatchdog=setTimeout(()=>{disconnected('เชื่อมต่อเวทีนานเกินไป · ตรวจอินเทอร์เน็ตแล้วลองอีกครั้ง');try{peer?.destroy();}catch{}},15000);
    peer.on('open',()=>{
      report('พบเซิร์ฟเวอร์รีโมทแล้ว · กำลังเชื่อมต่อเวที…','connecting');
      conn=peer.connect(hostId,{reliable:true,serialization:'json'});
      conn.on('open',()=>{clearConnectWatchdog();connected=true;report('กำลังยืนยัน QR กับจอ TV…','pending');conn.send({type:'hello',key:secret});});
      conn.on('data',handleMessage);
      conn.on('close',()=>disconnected('ขาดการเชื่อมต่อ · เชื่อมต่ออีกครั้งหรือสแกน QR ใหม่'));
      conn.on('error',()=>disconnected('เชื่อมต่อกับเวทีไม่ได้'));
    });
    peer.on('error',err=>disconnected('เครือข่ายไม่พร้อม: '+String(err?.type||'ไม่ทราบสาเหตุ')));
  }
  reconnectButton.addEventListener('click',()=>{try{connect();reconnectButton.hidden=true;report('กำลังเชื่อมต่ออีกครั้ง…','reconnecting');}catch{disconnected('เชื่อมต่อไม่สำเร็จ');}});
  try{connect();}catch{disconnected('เริ่มระบบรีโมทไม่สำเร็จ');}
  window.addEventListener('beforeunload',()=>{clearConnectWatchdog();revokeOwnerToken();try{conn?.close();peer?.destroy();}catch{}});
})();