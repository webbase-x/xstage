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
  // Remember the preferred Owner account and the short-lived TV pairing only.
  // Google OAuth access tokens and Owner permissions are NEVER persisted.
  const OWNER_PREF_KEY='xstage-remote-owner-preference-v1';
  const OWNER_PAIR_KEY='xstage-remote-owner-pair-v1';
  const OWNER_REMEMBER_MS=7*24*60*60*1000;
  function rememberRead(key){
    try {
      const value=JSON.parse(localStorage.getItem(key)||'null');
      if(!value||!Number.isFinite(value.at)||value.at>Date.now()+60000||
         Date.now()-value.at>OWNER_REMEMBER_MS)return null;
      return value;
    }catch{return null;}
  }
  function rememberWrite(key,value){try{localStorage.setItem(key,JSON.stringify({...value,at:Date.now()}));}catch{}}
  function rememberClear(key){try{localStorage.removeItem(key);}catch{}}
  const rememberedOwner=rememberRead(OWNER_PREF_KEY);
  const params=new URLSearchParams(location.hash.replace(/^#/,''));
  let hostId=params.get('p'),secret=params.get('k');
  function validPair(p,k){return /^[a-z0-9_-]+$/i.test(String(p||''))&&/^[a-f0-9]{48}$/i.test(String(k||''));}
  // Reopen the bookmarked remote on the same phone without re-scanning QR
  // while the TV's ephemeral pairing key remains valid.
  if(!validPair(hostId,secret)&&rememberedOwner){
    const pair=rememberRead(OWNER_PAIR_KEY);
    if(pair&&validPair(pair.hostId,pair.secret)){
      hostId=pair.hostId;secret=pair.secret;
      const savedFragment=new URLSearchParams({p:hostId,k:secret});
      history.replaceState(null,'',location.pathname+location.search+'#'+savedFragment.toString());
    }
  }
  let peer=null,conn=null,connected=false,ready=false,connectWatchdog=0;
  let lastNotifiedUpdateBuild=0;
  let searchTimer=null,querySequence=0,activeTab='search',role='guest';
  let ownerAccessToken='';
  let ownerAuthRequest=0,ownerLoginBusy=false,ownerAutoAttempted=false;
  const pendingRequests=new Map();
  let nextRequestId=0;
  let reconnectTimer=0,reconnectAttempts=0;
  let lastQueueRendering='';

  const reconnectButton=document.createElement('button');
  reconnectButton.type='button';reconnectButton.textContent='↻ เชื่อมต่ออีกครั้ง';
  reconnectButton.hidden=true;status.after(reconnectButton);
  const scanLink=document.createElement('a');
  scanLink.href='#scan-qr';scanLink.textContent='📷 สแกน QR ใหม่';
  scanLink.hidden=true;reconnectButton.after(scanLink);

  function clearConnectWatchdog(){if(connectWatchdog){clearTimeout(connectWatchdog);connectWatchdog=0;}}
  function armConnectWatchdog(delay=30000){
    clearConnectWatchdog();
    connectWatchdog=setTimeout(()=>{
      disconnected('การจับคู่หมดเวลา · ตรวจ QR บนจอ แล้วลองเชื่อมต่ออีกครั้ง');
    },delay);
  }
  function releaseRequest(id){
    const entry=pendingRequests.get(id);
    if(!entry)return;
    clearTimeout(entry.timer);
    entry.button.disabled=false;
    entry.button.textContent='ส่งเพลงขึ้นเวที';
    pendingRequests.delete(id);
  }
  function resetButtons(){for(const id of [...pendingRequests.keys()])releaseRequest(id);}
  function scheduleReconnect(){
    if(reconnectTimer||!hostId||!secret||document.hidden||navigator.onLine===false||reconnectAttempts>=3)return;
    const wait=[1500,3500,8000][reconnectAttempts++];
    reconnectTimer=setTimeout(()=>{
      reconnectTimer=0;
      if(!connected&&document.visibilityState!=='hidden')connect();
    },wait);
  }
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
  // Keyboard accessibility for tab navigation; mobile touch stays unchanged.
  document.querySelector('.remote-tabs')?.addEventListener('keydown',event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    const tabs=['search','queue','control','owner'];
    const current=Math.max(0,tabs.indexOf(activeTab));
    let index=current;
    if(event.key==='Home')index=0;
    else if(event.key==='End')index=tabs.length-1;
    else index=(current+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
    event.preventDefault();
    setTab(tabs[index]);$('remote-tab-'+tabs[index]).focus();
  });
  controls.hidden=true;setTab('search');setRole('guest');

  function disconnected(message){
    clearConnectWatchdog();resetButtons();
    connected=false;ready=false;controls.hidden=true;setRole('guest');
    ownerAuthRequest++;ownerLoginBusy=false;ownerAutoAttempted=false;discardOwnerToken();
    reconnectButton.hidden=!hostId||!secret;scanLink.hidden=false;report(message,'disconnected');
    scheduleReconnect();
  }
  function drawResults(items){
    results.replaceChildren();
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
      const btn=document.createElement('button');btn.type='button';btn.className='remote-request-button';btn.textContent='ส่งเพลงขึ้นเวที';
      btn.addEventListener('click',()=>{
        if(!ready){report('จอ TV ยังไม่พร้อม กรุณารอให้เปิดคลังเพลง');return;}
        if(!connected||!conn?.open){report('รีโมทขาดการเชื่อมต่อ กรุณาเชื่อมต่อกับจอ TV อีกครั้ง','error');return;}
        btn.disabled=true;btn.textContent='กำลังส่งขึ้นเวที…';
        const requestId=++nextRequestId;
        const timer=setTimeout(()=>{
          releaseRequest(requestId);
          report('ไม่ได้รับคำตอบการขอเพลง · ตรวจการเชื่อมต่อ แล้วลองอีกครั้ง','error');
        },18000);
        pendingRequests.set(requestId,{button:btn,timer});
        send({type:'request',requestId,index:item.index,
          singer:String(singer.value||'ไม่ระบุชื่อ').trim().slice(0,45)||'ไม่ระบุชื่อ',
          note:String(note.value||'').trim().slice(0,90)});
      });
      info.append(title,artist);row.append(info,btn);results.append(row);
    }
  }
  function drawQueue(items,total){
    const signature=JSON.stringify([role,total,items]);
    if(signature===lastQueueRendering)return;
    lastQueueRendering=signature;
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
  function discardOwnerToken(){
    // An already validated ephemeral Google token is immediately removed
    // from JS memory. Revoking its OAuth grant would break remembered login.
    ownerAccessToken='';
  }
  function clearRememberedOwner(){
    rememberClear(OWNER_PREF_KEY);
    rememberClear(OWNER_PAIR_KEY);
  }
  function ownerLogoutMobile(){
    // Logging out the mobile owner does NOT sign out the karaoke TV/Drive.
    ownerAuthRequest++;
    ownerLoginBusy=false;
    discardOwnerToken();
    clearRememberedOwner();
    setRole('guest');
    if(connected)send({type:'owner-signout'});
    ownerStatus.textContent='ออกจากระบบผู้ดูแลบนมือถือแล้ว · ใช้ Guest ได้ต่อ';
    report('ออกจากระบบผู้ดูแลบนมือถือแล้ว · จอ TV ยังคงเล่นเพลงได้','connected');
    setTab('owner');
  }
  $('owner-logout-mobile').addEventListener('click',ownerLogoutMobile);
  function ownerLogin({automatic=false}={}){
    if(!connected){ownerStatus.textContent='ยังไม่ได้เชื่อมต่อจอ TV';return;}
    if(ownerLoginBusy)return;
    const cfg=window.XSTAGE_CONFIG||{};
    if(!cfg.googleClientId){ownerStatus.textContent='เว็บไซต์ยังไม่ได้ตั้ง Google OAuth Web Client ID';return;}
    if(!window.google?.accounts?.oauth2?.initTokenClient){
      ownerStatus.textContent='กำลังโหลด Google Sign-In · กรุณากดอีกครั้ง';return;
    }
    ownerLoginBusy=true;
    const request=++ownerAuthRequest,activeConnection=conn;
    ownerStatus.textContent=automatic
      ?'พบผู้ดูแลที่จำไว้ · กำลังยืนยันกับ Google และจอ TV อีกครั้ง…'
      :'กำลังเปิด Google เพื่อยืนยันบัญชี…';
    try{
      const client=google.accounts.oauth2.initTokenClient({
        client_id:cfg.googleClientId,
        scope:'openid email',
        callback:result=>{
          if(request!==ownerAuthRequest||conn!==activeConnection)return;
          ownerLoginBusy=false;
          if(result?.error||!result?.access_token){
            ownerStatus.textContent=automatic
              ?'จำบัญชีผู้ดูแลไว้แล้ว · แตะเข้าสู่ระบบเพื่อยืนยันอีกครั้ง'
              :'ยืนยัน Google ไม่สำเร็จ';
            return;
          }
          ownerAccessToken=String(result.access_token);
          ownerStatus.textContent='กำลังตรวจว่าบัญชีตรงกับจอ TV…';
          send({type:'owner-auth',accessToken:ownerAccessToken});
        },
        error_callback:()=>{
          if(request!==ownerAuthRequest)return;
          ownerLoginBusy=false;
          ownerStatus.textContent=automatic
            ?'จำบัญชีไว้แล้ว · เบราว์เซอร์ต้องให้แตะเข้าสู่ระบบอีกครั้ง'
            :'ไม่สามารถเปิด Google Sign-In ได้';
        }
      });
      // GIS OAuth may require a user gesture even when Google remembers the
      // account. If the browser blocks automatic reuse, show the login button.
      client.requestAccessToken({prompt:automatic?'':'select_account'});
    }catch(error){
      if(request!==ownerAuthRequest)return;
      ownerLoginBusy=false;
      ownerStatus.textContent=automatic
        ?'จำบัญชีไว้แล้ว · แตะเข้าสู่ระบบเพื่อยืนยันสิทธิ์'
        :String(error?.message||'เปิด Google Sign-In ไม่สำเร็จ');
    }
  }
  function restoreOwnerLogin(){
    if(!rememberedOwner||ownerAutoAttempted||!connected)return;
    ownerAutoAttempted=true;
    ownerStatus.textContent='กำลังตรวจสิทธิ์ Owner ที่จำไว้…';
    const connectionAtStart=conn;
    // The Google GIS script is loaded with defer and may not be ready when
    // the PeerJS channel opens. Retry loading only; never loop consent popups.
    const check=(tries=0)=>{
      if(!connected||conn!==connectionAtStart||role==='owner')return;
      if(window.google?.accounts?.oauth2?.initTokenClient){ownerLogin({automatic:true});return;}
      if(tries>=20){
        ownerStatus.textContent='จำบัญชีผู้ดูแลไว้แล้ว · แตะเข้าสู่ระบบเพื่อยืนยันอีกครั้ง';
        return;
      }
      setTimeout(()=>check(tries+1),300);
    };
    check();
  }
  $('remote-owner-login').addEventListener('click',()=>ownerLogin());

  function downloadQueue(data){
    const body=JSON.stringify({schema:'xstage-remote-queue-v1',exportedAt:new Date().toISOString(),items:Array.isArray(data)?data:[]},null,2);
    const blob=new Blob([body],{type:'application/json'});
    const url=URL.createObjectURL(blob),a=document.createElement('a');
    a.href=url;a.download='X-Stage-Queue-'+new Date().toISOString().slice(0,10)+'.json';
    document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }

  function handleMessage(data){
    if(!data||typeof data!=='object')return;
    if(data.type==='pending'){armConnectWatchdog(45000);report('กำลังรอจอหลักอนุมัติการเชื่อมต่อครั้งแรก…','pending');return;}
    if(data.type==='ready'){
      clearConnectWatchdog();reconnectAttempts=0;
      connected=true;controls.hidden=false;reconnectButton.hidden=true;scanLink.hidden=true;setRole('guest');
      report('เชื่อมต่อแล้ว · Guest ใช้คำสั่งพื้นฐานได้ทันที','connected');
      if(search.value.trim())search.dispatchEvent(new Event('input'));else drawResults([]);
      send({type:'refresh'});
      restoreOwnerLogin();
      return;
    }
    if(data.type==='role'){
      discardOwnerToken();
      ownerLoginBusy=false;
      if(data.role==='owner'){
        // Save only a validated account hint and the ephemeral QR pairing,
        // never an OAuth token or unverified Owner privilege.
        rememberWrite(OWNER_PREF_KEY,{email:String(data.email||'')});
        if(validPair(hostId,secret))rememberWrite(OWNER_PAIR_KEY,{hostId,secret});
        setRole('owner',String(data.email||''));
        report('Owner ยืนยันแล้ว · จำบัญชีบนมือถือเครื่องนี้ · ออกจากระบบได้','connected');
        send({type:'refresh'});
      }else{
        if(data.signedOut)clearRememberedOwner();
        setRole('guest');
        ownerStatus.textContent=String(data.message||'บัญชีไม่ตรงกับจอ TV');
        report(ownerStatus.textContent,data.signedOut?'connected':'error');
        send({type:'refresh'});
      }
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
        const direct=!!data.nativeAudioDirect;
        const eqSelect=$('owner-eq-preset');
        eqSelect.disabled=direct;
        for(const button of document.querySelectorAll('[data-admin="eq-reset"],[data-admin="eq-bypass"]'))button.disabled=direct;
        $('owner-eq-state').textContent=direct
          ? 'ANDROID DIRECT · เสียงออกลำโพงตรง · มิเตอร์แสดงผลเท่านั้น'+
            (data.nativeMeterStatus==='unsupported'?' · WebView ไม่รองรับมิเตอร์สด':'')
          : data.eqActive?'EQ ทำงาน · '+String(data.eqPreset||'').toUpperCase():'เสียง Native · EQ ยังไม่ทำงาน';
        const visual=data.visualSettings||{};
        if(visual.background&&[...$('owner-background').options].some(o=>o.value===visual.background))$('owner-background').value=visual.background;
        if(visual.brandTheme&&[...$('owner-brand-theme').options].some(o=>o.value===visual.brandTheme))$('owner-brand-theme').value=visual.brandTheme;
        if(visual.lyricScale)$('owner-lyric-scale').value=String(visual.lyricScale);
        if(/^#[0-9a-f]{6}$/i.test(String(visual.lyricColor||'')))$('owner-lyric-color').value=String(visual.lyricColor);
        $('remote-qr-state').textContent=data.pairingPaused?'QR แสดงอยู่ · พักรับผู้ใช้ใหม่':'QR แสดงถาวร · เปิดรับผู้ใช้ใหม่';
        const updateButton=$('owner-update');
        if(updateButton){
          const release=data.updateAvailable;
          const build=Number(release?.build)||0;
          updateButton.textContent=build
            ?'อัปเดต X-Stage v'+String(release.version||'')+' · Build '+build
            :'ตรวจสอบ / อัปเดต X-Stage';
          updateButton.title=String(data.updateStatus||'ตรวจสอบเวอร์ชันล่าสุด');
          if(build>0&&build!==lastNotifiedUpdateBuild){
            lastNotifiedUpdateBuild=build;
            receipt('มี X-Stage v'+String(release.version||'')+' (Build '+build+') ใหม่ · กดอัปเดตเมื่อต้องการ ไม่ตัดเพลงที่กำลังเล่น');
          }
        }
        $('owner-qr-pause').disabled=!!data.pairingPaused;
        $('owner-qr-resume').disabled=!data.pairingPaused;
      }
      if(!ready&&!status.textContent.includes('ยังไม่พร้อม'))report('เชื่อมต่อแล้ว · รอจอ TV เปิดคลัง Google Drive','connected');
    }else if(data.type==='results'){
      if(data.notReady){report('จอ TV ยังไม่ได้เปิดคลังเพลง');drawResults([]);return;}
      if(String(data.query||'')===search.value.trim().toLocaleLowerCase('th'))drawResults(data.items);
    }else if(data.type==='request-received'){
      if(Number.isSafeInteger(data.requestId))releaseRequest(data.requestId);
      else resetButtons();
      clearTimeout(searchTimer);querySequence++;search.value='';results.replaceChildren();
      const outcome=data.result==='starting'||data.result==='playing'?'กำลังเตรียมเปิดบนเวที (รอผลเล่นจริง)':'เพิ่มท้ายคิวแล้ว';
      receipt('รับคำขอเพลง '+String(data.title||'')+' แล้ว · '+outcome);send({type:'refresh'});
    }else if(data.type==='playback-status'){
      const title=String(data.title||'เพลงที่เลือก');
      const message=String(data.message||'');
      if(data.state==='loading')report('จอ TV กำลังโหลดเพลง '+title+' จาก Drive…','connected');
      else if(data.state==='playing')report('▶ เริ่มเล่นบนเวทีแล้ว · '+title,'connected');
      else if(data.state==='blocked'||data.state==='error'){
        receipt('เล่นเพลง '+title+' ไม่สำเร็จบนจอ TV · '+(message||'โปรดตรวจสอบระบบเสียงและสิทธิ์ไฟล์'));
        report('ไม่สามารถเล่นเพลงบนจอ TV · '+(message||'กรุณาตรวจสอบระบบเสียง'),'error');
      }
    }else if(data.type==='request-error'){
      if(Number.isSafeInteger(data.requestId))releaseRequest(data.requestId);
      else resetButtons();
      report(String(data.message||'ขอเพลงไม่สำเร็จ'),'error');
    }
  }

  search.addEventListener('input',()=>{
    clearTimeout(searchTimer);
    const term=search.value.trim().toLocaleLowerCase('th');
    if(!term){querySequence++;results.replaceChildren();return;}
    if(!ready){results.textContent='รอจอหลักเปิดคลังเพลงก่อนค้นหา';return;}
    results.textContent='กำลังค้นหาเพลง…';
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

  if(!validPair(hostId,secret)){
    scanLink.hidden=false;reconnectButton.hidden=true;report('ยังไม่มีรหัส QR · แตะ 📷 เพื่อสแกนจากจอ TV');return;
  }
  if(typeof Peer!=='function'){report('โหลดระบบจับคู่ไม่สำเร็จ กรุณาตรวจอินเทอร์เน็ต');return;}
  report('กำลังเชื่อมต่อรีโมท X-Stage…','connecting');

  function connect(){
    clearConnectWatchdog();
    if(reconnectTimer){clearTimeout(reconnectTimer);reconnectTimer=0;}
    setRole('guest');
    ownerAuthRequest++;ownerLoginBusy=false;ownerAutoAttempted=false;discardOwnerToken();
    const previous=peer;
    if(previous){try{previous.destroy();}catch{}}
    const current=new Peer();peer=current;conn=null;
    armConnectWatchdog(18000);
    current.on('open',()=>{
      if(peer!==current)return;
      report('พบเซิร์ฟเวอร์รีโมท · กำลังจับคู่กับเวที…','connecting');
      const channel=current.connect(hostId,{reliable:true,serialization:'json'});
      conn=channel;
      channel.on('open',()=>{
        if(peer!==current||conn!==channel)return;
        // Do not clear the watchdog before receiving the authenticated
        // "ready" message. A WebRTC connection can open but never be approved.
        armConnectWatchdog(30000);
        connected=true;report('กำลังยืนยัน QR กับจอหลัก…','pending');
        channel.send({type:'hello',key:secret});
      });
      channel.on('data',message=>{
        if(peer===current&&conn===channel)handleMessage(message);
      });
      channel.on('close',()=>{
        if(peer===current&&conn===channel)disconnected('การเชื่อมต่อหลุด · กำลังลองเชื่อมต่อใหม่');
      });
      channel.on('error',()=>{
        if(peer===current&&conn===channel)disconnected('เชื่อมต่อกับเวทีไม่ได้');
      });
    });
    current.on('error',err=>{
      if(peer===current)disconnected('เครือข่ายไม่พร้อม: '+String(err?.type||'ไม่ทราบสาเหตุ'));
    });
  }
  reconnectButton.addEventListener('click',()=>{
    reconnectAttempts=0;
    try{connect();reconnectButton.hidden=true;report('กำลังเชื่อมต่ออีกครั้ง…','reconnecting');}
    catch{disconnected('เชื่อมต่อไม่สำเร็จ');}
  });
  window.addEventListener('online',()=>{if(!ready){reconnectAttempts=0;connect();}});
  document.addEventListener('visibilitychange',()=>{
    if(!document.hidden&&!ready){reconnectAttempts=0;connect();}
  });
  try{connect();}catch{disconnected('เริ่มระบบรีโมทไม่สำเร็จ');}
  window.addEventListener('beforeunload',()=>{
    clearConnectWatchdog();resetButtons();
    if(reconnectTimer)clearTimeout(reconnectTimer);
    discardOwnerToken();try{conn?.close();peer?.destroy();}catch{}
  });
})();