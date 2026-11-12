/* X-Stage Online: virtual keyboard and QR-paired mobile remote.
 * Pairing credentials live only in memory/URL fragments. Guest sends no Google token.
 * Owner sends one short-lived Google access token over WebRTC for same-account verification;
 * the TV verifies it against Google userinfo and does not store it. */
'use strict';
(function(){
  const byId = id => document.getElementById(id);
  const stage = byId('stage');
  const search = byId('search');
  const keyboard = byId('virtual-keyboard');
  const kbKeys = byId('virtual-keys');
  const kbToggle = byId('toggle-keyboard');
  const kbClose = byId('virtual-close');
  const kbLang = byId('virtual-language');
  const qrToggle = byId('toggle-remote');
  const qrPanel = byId('remote-pair-panel');
  const qrClose = byId('remote-pair-close');
  const qrCanvas = byId('remote-qr');
  const qrStatus = byId('remote-pair-status');
  const qrLink = byId('remote-link');
  const qrApprove = byId('remote-approve');
  const qrReject = byId('remote-reject');
  const qrEnd = byId('remote-end');
  if(!stage || !search || !keyboard || !kbKeys || !qrPanel) return;

  const layouts = {
    th: [
      ['ๆ','ไ','ำ','พ','ะ','ั','ี','ร','น','ย','บ','ล'],
      ['ฟ','ห','ก','ด','เ','้','่','า','ส','ว','ง'],
      ['ผ','ป','แ','อ','ิ','ื','ท','ม','ใ','ฝ'],
      ['๐','๑','๒','๓','๔','๕','๖','๗','๘','๙']
    ],
    en: [
      ['1','2','3','4','5','6','7','8','9','0'],
      ['q','w','e','r','t','y','u','i','o','p'],
      ['a','s','d','f','g','h','j','k','l'],
      ['z','x','c','v','b','n','m']
    ]
  };
  // Reserve exactly the space occupied by the onscreen keyboard for search results.
  function updateKeyboardHeight(){
    if(!keyboard.hidden)stage.style.setProperty('--virtual-keyboard-height',Math.ceil(keyboard.getBoundingClientRect().height)+'px');
  }
  if(typeof ResizeObserver!=='undefined')new ResizeObserver(updateKeyboardHeight).observe(keyboard);
  let layout = 'th';
  let shift = false;
  function hideKeyboard(){
    keyboard.hidden = true;
    stage.classList.remove('keyboard-open');
    kbToggle.setAttribute('aria-expanded','false');
    kbToggle.classList.remove('active');
    search.readOnly = false;
    search.blur();
  }
  function showKeyboard(){
    keyboard.hidden = false;
    stage.classList.add('keyboard-open');
    kbToggle.setAttribute('aria-expanded','true');
    kbToggle.classList.add('active');
    // Prevent a second native mobile keyboard from opening on top of the built-in one.
    search.readOnly = true;
    search.focus({preventScroll:true});
    search.dispatchEvent(new Event('input',{bubbles:true}));
    updateKeyboardHeight();
  }
  function editSearch(value,action){
    if(!state.token) { hideKeyboard(); return; }
    const start = Number.isInteger(search.selectionStart) ? search.selectionStart : search.value.length;
    const end = Number.isInteger(search.selectionEnd) ? search.selectionEnd : search.value.length;
    let next = search.value;
    let pos = start;
    if(action === 'clear') { next=''; pos=0; }
    else if(action === 'backspace') {
      if(end>start){ next=next.slice(0,start)+next.slice(end); }
      else if(start>0){ next=next.slice(0,start-1)+next.slice(end); pos=start-1; }
    }else{
      next=next.slice(0,start)+value+next.slice(end);
      pos=start+value.length;
    }
    search.value=next;
    search.dispatchEvent(new Event('input',{bubbles:true}));
    search.focus({preventScroll:true});
    try {search.setSelectionRange(pos,pos);}catch{}
  }
  function keyButton(text,action,cls){
    const b=document.createElement('button');
    b.type='button';b.textContent=text;b.className='virtual-key'+(cls?' '+cls:'');
    b.setAttribute('aria-label',text);
    b.addEventListener('pointerdown',e=>e.preventDefault());
    b.addEventListener('click',action);
    return b;
  }
  function drawKeyboard(){
    kbKeys.replaceChildren();
    kbLang.textContent=layout==='th'?'ภาษาไทย':'English';
    for(const letters of layouts[layout]){
      const row=document.createElement('div');row.className='virtual-key-row';
      for(const ch of letters){
        const val=layout==='en' && shift ? ch.toUpperCase() : ch;
        row.append(keyButton(val,()=>editSearch(val),'')); 
      }
      kbKeys.append(row);
    }
    const row=document.createElement('div');row.className='virtual-key-row virtual-key-actions';
    row.append(
      keyButton('TH / EN',()=>{layout=layout==='th'?'en':'th';drawKeyboard();},'wide'),
      keyButton('⇧',()=>{shift=!shift;drawKeyboard();},''),
      keyButton('เว้นวรรค',()=>editSearch(' '),'wide'),
      keyButton('↑',()=>search.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowUp',bubbles:true,cancelable:true})),''),
      keyButton('↓',()=>search.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true,cancelable:true})),''),
      keyButton('⌫',()=>editSearch('', 'backspace'),''),
      keyButton('ล้าง',()=>editSearch('', 'clear'),''),
      keyButton('Enter',()=>{
        if(!state.token)return;
        search.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));
        hideKeyboard();
      },'wide key-enter')
    );
    kbKeys.append(row);
    updateKeyboardHeight();
  }
  drawKeyboard();
  kbToggle.addEventListener('click',()=>keyboard.hidden?showKeyboard():hideKeyboard());
  kbClose.addEventListener('click',hideKeyboard);
  document.addEventListener('keydown',e=>{
    if(e.key==='Escape'&&!keyboard.hidden)hideKeyboard();
  });

  let remoteLibrariesPromise=null;
  function loadRemoteScript(src,id,test){
    if(test())return Promise.resolve();
    return new Promise((resolve,reject)=>{
      const stale=document.getElementById(id);
      // A failed script never emits another load/error event. Recreate it so
      // retry can recover instead of leaving the QR at "กำลังสร้าง".
      if(stale)stale.remove();
      const script=document.createElement('script');
      script.id=id;script.src=src;script.async=true;
      let settled=false;
      const finish=error=>{
        if(settled)return;
        settled=true;clearTimeout(timer);
        script.onload=null;script.onerror=null;
        if(error){script.remove();reject(error);}
        else{script.dataset.loaded='1';resolve();}
      };
      const timer=setTimeout(()=>finish(Error('โหลดระบบรีโมทนานเกินไป')),10000);
      script.onload=()=>finish(test()?null:Error('ไลบรารีรีโมทไม่พร้อม'));
      script.onerror=()=>finish(Error('โหลดระบบรีโมทไม่สำเร็จ'));
      document.head.append(script);
    });
  }
  async function ensureRemoteLibraries(){
    if(typeof Peer==='function'&&typeof QRCode!=='undefined')return;
    remoteLibrariesPromise ||= (async()=>{
      await loadRemoteScript('./assets/vendor/peerjs.min.js?v=1082','xstage-peerjs',()=>typeof Peer==='function');
      if(typeof window.XStageEnsureQrLibrary==='function')await window.XStageEnsureQrLibrary();
      else await loadRemoteScript('./assets/vendor/qrcode.min.js?v=1082','xstage-qrcode',()=>typeof QRCode!=='undefined');
    })();
    try{await remoteLibrariesPromise;}
    catch(error){remoteLibrariesPromise=null;throw error;}
  }

  // Mobile remote security model:
  // - Guest is QR-paired and gets only basic controls.
  // - Owner must authenticate with the same Google account as the TV. The short-lived
  //   mobile access token is verified against Google userinfo, compared by immutable sub,
  //   and is never stored by the TV.
  const requestPanel=byId('remote-request-panel');
  const requestList=byId('remote-request-list');
  const requestCount=byId('remote-request-count');
  const requestToggle=byId('remote-request-toggle');
  const requestClose=byId('remote-request-close');
  const nativeTvMode=(()=>{
    try{return new URLSearchParams(location.search).get('source')==='android-tv'||
      !!(window.XStageAndroid&&window.XStageAndroid.isAndroidTvApp?.());}
    catch{return false;}
  })();
  const guestPermissions={search:true,request:true,playpause:true,'volume-up':true,'volume-down':true,mute:true};
  const ownerPermissions={...guestPermissions,next:true,'cancel-current':true,'fullscreen-on':true,'fullscreen-off':true,medley:true};
  const activity=[];
  let session=null,sequence=0,pairingPaused=false,fullscreenPending=false;

  function status(value){if(qrStatus)qrStatus.textContent=value;}
  function send(conn,data){if(conn?.open)try{conn.send(data);}catch{}}
  function randomSecret(){
    const bytes=new Uint8Array(24);crypto.getRandomValues(bytes);
    return Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
  }
  function songSummary(song){
    return {title:String(song?.title||''),artist:String(song?.artist||''),code:String(song?.code||''),singer:String(song?.queueSinger||'')};
  }
  function entryPermissions(entry){return entry?.role==='owner'?ownerPermissions:guestPermissions;}
  function snapshot(entry){
    const duration=Number.isFinite(ui.player.duration)?ui.player.duration:Number(state.current?.duration)||0;
    const eq=byId('xstage-eq-preset');
    return {type:'status',ready:!!state.token,role:entry?.role==='owner'?'owner':'guest',
      ownerEmail:entry?.role==='owner'?String(ui.account?.textContent||''):'',
      platform:nativeTvMode?'android-tv':'web',
      playing:!!ui.player.src&&!ui.player.paused,now:songSummary(state.current),
      queue:state.queue.slice(0,150).map(songSummary),queueCount:state.queue.length,
      volume:Math.round(Number(ui.volume.value)||0),muted:ui.player.muted,medley:!!state.medley,
      repeat:!!ui.repeat?.checked,speed:Number(ui.speed?.value)||1,eqPreset:String(eq?.value||'auto'),eqActive:!!window.XStageEqIsActive?.(),
      nativeAudioDirect:!!window.XStageNativeAudioBypass?.(),nativeMeterStatus:window.XStageNativeMeterStatus?.()?.status||'',
      visualSettings:entry?.role==='owner'&&typeof window.XStageRemoteVisualSettings==='function'?window.XStageRemoteVisualSettings('state'):null,
      updateAvailable:entry?.role==='owner'?(state.nativeUpdateAvailable||state.updateAvailable||null):null,
      updateStatus:entry?.role==='owner'?String(state.nativeUpdateStatus||''):'',
      currentTime:Number.isFinite(ui.player.currentTime)?ui.player.currentTime:0,
      duration:Number.isFinite(duration)?duration:0,fullscreen:document.fullscreenElement===stage,
      fullscreenPending,pairingPaused,permissions:{...entryPermissions(entry)}};
  }
  function broadcastStatus(){
    if(!session)return;
    for(const entry of session.connections.values())if(entry.approved)send(entry.conn,snapshot(entry));
  }
  function hideFullscreenConfirm(){fullscreenPending=false;}
  document.addEventListener('fullscreenchange',broadcastStatus);
  async function setHostFullscreen(full,conn){
    if(full){
      if(document.fullscreenElement===stage){send(conn,snapshot([...session?.connections?.values?.()||[]].find(e=>e.conn===conn)));return;}
      if(typeof stage.requestFullscreen!=='function')send(conn,{type:'fullscreen-notice',message:'จอ TV ไม่รองรับ Fullscreen'});
      else try{await stage.requestFullscreen();}catch{send(conn,{type:'fullscreen-notice',message:'Android TV ไม่อนุญาตเปลี่ยน Fullscreen จากรีโมท'});}
    }else if(document.fullscreenElement===stage){
      try{await document.exitFullscreen();}catch{send(conn,{type:'fullscreen-notice',message:'ออกจาก Fullscreen ไม่สำเร็จ'});}
    }
    broadcastStatus();
  }
  function clearPeerSession(){
    if(!session)return;
    const active=session;session=null;
    for(const entry of active.connections.values())try{entry.conn.close();}catch{}
    try{active.peer?.destroy();}catch{}
    qrApprove.hidden=true;qrReject.hidden=true;hideFullscreenConfirm();
    qrLink.textContent='';qrLink.removeAttribute('href');qrCanvas.hidden=true;
    qrEnd.textContent='สร้าง QR ใหม่';pairingPaused=false;status('ปิดการเชื่อมต่อรีโมทแล้ว');
  }

  function redrawActivity(){
    if(!requestCount||!requestList)return;
    requestCount.textContent=String(activity.length);requestList.replaceChildren();
    if(!activity.length){const p=document.createElement('p');p.textContent='ยังไม่มีรายการขอเพลง';requestList.append(p);return;}
    for(const item of activity.slice().reverse()){
      const row=document.createElement('div');row.className='request-item';
      const info=document.createElement('div');info.className='request-info';
      const title=document.createElement('strong');title.textContent=item.title;
      const by=document.createElement('small');by.textContent=item.singer+' · '+item.result+(item.note?' · '+item.note:'');
      info.append(title,by);row.append(info);requestList.append(row);
    }
  }
  requestToggle?.addEventListener('click',()=>{requestPanel.hidden=!requestPanel.hidden;requestToggle.setAttribute('aria-expanded',String(!requestPanel.hidden));});
  requestClose?.addEventListener('click',()=>{requestPanel.hidden=true;requestToggle.setAttribute('aria-expanded','false');});
  redrawActivity();

  function acceptRequest(conn,msg,limits){
    const requestId=Number.isSafeInteger(msg?.requestId)?msg.requestId:null;
    const reply=(type,message)=>send(conn,{type,requestId,message});
    if(!state.token){reply('request-error','จอ TV ยังไม่เปิดคลังเพลง');return;}
    if(state.queue.length>=150){reply('request-error','คิวเต็มแล้ว กรุณารอ');return;}
    if(!Number.isSafeInteger(msg.index)||msg.index<0||msg.index>=state.songs.length){reply('request-error','ไม่พบเพลงที่เลือก กรุณาค้นหาใหม่');return;}
    const song=state.songs[msg.index];if(!playable(song)){reply('request-error','เพลงนี้ยังเล่นไม่ได้');return;}
    const now=Date.now();while(limits.length&&now-limits[0]>60_000)limits.shift();
    if(limits.length>=8){reply('request-error','ขอเพลงบ่อยเกินไป กรุณารอสักครู่');return;}
    limits.push(now);
    const singerName=String(msg.singer||'ไม่ระบุชื่อ').trim().slice(0,45)||'ไม่ระบุชื่อ';
    const noteText=String(msg.note||'').trim().slice(0,90);
    const queued={...song,queueSinger:singerName};
    const wasEmpty=state.queue.length===0;
    const inactive=!state.loading&&(!state.current||!ui.player.src||ui.player.ended||(ui.player.paused&&ui.player.currentTime<.5));
    addToQueue(queued);const playImmediately=wasEmpty&&inactive;if(playImmediately)playNext();
    activity.push({title:song.title||song.code,singer:singerName,note:noteText,result:playImmediately?'เล่นทันที':'เพิ่มเข้าคิว'});
    if(activity.length>30)activity.shift();redrawActivity();
    send(conn,{type:'request-received',id:++sequence,requestId,title:String(song.title||''),result:playImmediately?'playing':'queued'});
    broadcastStatus();
  }

  function handleControl(conn,msg,entry){
    const now=Date.now();if(now-entry.lastControl<120)return;entry.lastControl=now;
    const action=String(msg.action||''),permissions=entryPermissions(entry);
    if(!permissions[action])return;
    const audio=ui.player;
    if(action==='playpause')togglePlayback();
    else if(action==='cancel-current')cancelCurrentSong();
    else if(action==='next')playNext();
    else if(action==='volume-up'||action==='volume-down'){
      const next=Math.max(0,Math.min(100,Math.round(Number(ui.volume.value)||0)+(action==='volume-up'?5:-5)));
      ui.volume.value=String(next);ui.volume.dispatchEvent(new Event('input',{bubbles:true}));audio.muted=false;
    }else if(action==='mute')audio.muted=!audio.muted;
    else if(action==='fullscreen-on')void setHostFullscreen(true,conn);
    else if(action==='fullscreen-off')void setHostFullscreen(false,conn);
    else if(action==='medley')setMedleyMode(!state.medley);
    else return;
    broadcastStatus();
  }

  function clickHost(id){const el=byId(id);if(!el||el.disabled)return false;el.click();return true;}
  function adminResult(entry,action,ok,message,data){send(entry.conn,{type:'admin-result',action,ok,message,data});}
  function findSongForImport(item){
    const code=String(item?.code||'').trim(),title=String(item?.title||'').trim().toLocaleLowerCase('th'),artist=String(item?.artist||'').trim().toLocaleLowerCase('th');
    if(code){const hit=state.songs.find(song=>String(song.code||'').trim()===code&&playable(song));if(hit)return hit;}
    if(title)return state.songs.find(song=>String(song.title||'').trim().toLocaleLowerCase('th')===title&&(!artist||String(song.artist||'').trim().toLocaleLowerCase('th')===artist)&&playable(song))||null;
    return null;
  }
  async function handleAdmin(entry,msg){
    if(entry.role!=='owner'){adminResult(entry,String(msg.action||''),false,'คำสั่งนี้ต้องยืนยันบัญชี Owner');return;}
    const action=String(msg.action||''),value=msg.value;
    try{
      if(action==='previous')clickHost('previous');
      else if(action==='restart')clickHost('restart-current');
      else if(action==='next')clickHost('next');
      else if(action==='cancel-current')clickHost('cancel-current');
      else if(action==='medley')setMedleyMode(!state.medley);
      else if(action==='repeat-toggle'){ui.repeat.checked=!ui.repeat.checked;ui.repeat.dispatchEvent(new Event('change',{bubbles:true}));}
      else if(action==='speed'){
        const allowed=['0.75','0.9','1','1.1','1.25','1.5'],next=String(value||'1');
        if(!allowed.includes(next))throw Error('ค่าความเร็วไม่ถูกต้อง');
        ui.speed.value=next;ui.speed.dispatchEvent(new Event('change',{bubbles:true}));
      }else if(action==='loop-a')clickHost('pc-loop-a');
      else if(action==='loop-b')clickHost('pc-loop-b');
      else if(action==='loop-clear')clickHost('pc-loop-clear');
      else if(action==='fullscreen-toggle'){
        await setHostFullscreen(document.fullscreenElement!==stage,entry.conn);
      }else if(action==='shuffle')clickHost('stage-shuffle');
      else if(action==='clear-queue'){state.queue.length=0;renderQueue();}
      else if(action==='keyboard')clickHost('toggle-keyboard');
      else if(action==='stage-pop')clickHost('pc-stage-pop');
      else if(action==='update'){
        if(nativeTvMode&&typeof window.XStageAndroid?.installAvailableUpdate==='function'){
          window.XStageAndroid.installAvailableUpdate();
        }else{
          if(typeof triggerImmediateVersionUpdate!=='function')throw Error('ระบบอัปเดตยังไม่พร้อม');
          await triggerImmediateVersionUpdate();
        }
      }else if(action==='queue-move'){
        const index=Number(value?.index),delta=Number(value?.delta);
        if(!Number.isInteger(index)||![-1,1].includes(delta)||index<0||index>=state.queue.length)throw Error('ตำแหน่งคิวไม่ถูกต้อง');
        const target=index+delta;if(target<0||target>=state.queue.length)throw Error('เลื่อนคิวต่อไม่ได้');
        [state.queue[index],state.queue[target]]=[state.queue[target],state.queue[index]];renderQueue();
      }else if(action==='queue-remove'){
        const index=Number(value?.index);
        if(!Number.isInteger(index)||index<0||index>=state.queue.length)throw Error('ตำแหน่งคิวไม่ถูกต้อง');
        state.queue.splice(index,1);renderQueue();
      }else if(action==='queue-play'){
        const index=Number(value?.index);
        if(!Number.isInteger(index)||index<0||index>=state.queue.length)throw Error('ตำแหน่งคิวไม่ถูกต้อง');
        const song=state.queue.splice(index,1)[0];renderQueue();if(song)await playSong(song);
      }
      else if(action==='clear-cache'){
        if(typeof window.XStageClearCache!=='function')throw Error('ระบบล้างแคชยังไม่พร้อม');
        await window.XStageClearCache();
      }
      else if(action==='logout')ui.logout?.click();
      else if(action==='eq-preset'){
        if(window.XStageNativeAudioBypass?.())throw Error('Android APK ใช้เสียงตรง · EQ ปิดถาวร');
        const next=String(value||'flat');
        if(typeof window.XStageEnableEqPreset!=='function')throw Error('EQ ยังไม่พร้อม');
        await window.XStageEnableEqPreset(next);
      }else if(action==='eq-reset'){
        if(window.XStageNativeAudioBypass?.())throw Error('Android APK ใช้เสียงตรง · EQ ปิดถาวร');
        if(typeof window.XStageResetEq!=='function')throw Error('EQ ยังไม่พร้อม');
        await window.XStageResetEq();
      }else if(action==='eq-bypass'){
        if(window.XStageNativeAudioBypass?.())throw Error('Android APK ใช้เสียงตรง · EQ ปิดถาวร');
        if(typeof window.XStageToggleEqBypass!=='function')throw Error('EQ ยังไม่พร้อม');
        await window.XStageToggleEqBypass();
      }
      else if(action==='export-queue'){
        adminResult(entry,action,true,'ส่งออกคิวไปยังมือถือแล้ว',state.queue.slice(0,150).map(songSummary));return;
      }else if(action==='import-queue'){
        const items=Array.isArray(value)?value.slice(0,150):[];let added=0,missing=0;
        for(const item of items){const song=findSongForImport(item);if(song){addToQueue({...song,queueSinger:'นำเข้าจาก Owner'});added++;}else missing++;}
        adminResult(entry,action,true,'นำเข้าคิว '+added+' เพลง'+(missing?' · ไม่พบ '+missing+' เพลง':''));broadcastStatus();return;
      }else if(action==='visual-background'||action==='visual-brand-theme'||action==='visual-lyric-scale'||action==='visual-lyric-color'){
        if(typeof window.XStageRemoteVisualSettings!=='function')throw Error('ระบบตั้งค่าเวทียังไม่พร้อม');
        const map={
          'visual-background':'background',
          'visual-brand-theme':'brand-theme',
          'visual-lyric-scale':'lyric-scale',
          'visual-lyric-color':'lyric-color'
        };
        const ok=window.XStageRemoteVisualSettings(map[action],value);
        if(ok===false)throw Error('ค่าที่ส่งมาไม่ถูกต้อง');
      }else if(action==='history'){
        const data=typeof window.XStageRemoteHistory==='function'?window.XStageRemoteHistory():[];
        adminResult(entry,action,true,'โหลดประวัติแล้ว',data);return;
      }else if(action==='favorite-current'){
        const result=typeof window.XStageToggleCurrentFavorite==='function'?window.XStageToggleCurrentFavorite():{ok:false,message:'ระบบเพลงโปรดยังไม่พร้อม'};
        adminResult(entry,action,result?.ok!==false,String(result?.message||'อัปเดตเพลงโปรดแล้ว'),result);return;
      }else if(action==='share-library'){
        const email=String(value||'').trim();
        if(typeof shareLibraryWithEmail!=='function')throw Error('ระบบแชร์คลังยังไม่พร้อม');
        await shareLibraryWithEmail(email);adminResult(entry,action,true,'แชร์คลังให้ '+email+' แล้ว');return;
      }else if(action==='qr-pause'){pausePairing();adminResult(entry,action,true,'พัก QR แล้ว · ผู้ใช้เดิมยังเชื่อมต่ออยู่');return;}
      else if(action==='qr-resume'){await resumePairing();adminResult(entry,action,true,'เปิด QR ใหม่แล้ว');return;}
      else throw Error('ไม่รู้จักคำสั่งผู้ดูแล');
      adminResult(entry,action,true,'ดำเนินการแล้ว');broadcastStatus();
    }catch(error){adminResult(entry,action,false,String(error?.message||'ดำเนินการไม่สำเร็จ'));}
  }

  async function verifyOwner(entry,accessToken){
    if(!entry?.approved||!entry.conn?.open)return;
    if(!state.accountSub){send(entry.conn,{type:'role',role:'guest',message:'จอ TV ยังไม่ได้ล็อกอิน Google'});return;}
    const token=String(accessToken||'');
    if(!token||token.length>4096){send(entry.conn,{type:'role',role:'guest',message:'Google token ไม่ถูกต้อง'});return;}
    try{
      const response=await fetch('https://openidconnect.googleapis.com/v1/userinfo',{
        headers:{Authorization:'Bearer '+token},cache:'no-store'
      });
      if(!response.ok)throw Error('Google ไม่ยืนยัน token');
      const profile=await response.json();
      if(!profile?.sub||String(profile.sub)!==String(state.accountSub)){
        entry.role='guest';send(entry.conn,{type:'role',role:'guest',message:'บัญชี Google นี้ไม่ตรงกับบัญชีบนจอ TV'});send(entry.conn,snapshot(entry));return;
      }
      entry.role='owner';
      send(entry.conn,{type:'role',role:'owner',email:String(profile.email||ui.account?.textContent||'')});
      send(entry.conn,snapshot(entry));status('Owner ยืนยันบัญชีเดียวกับจอแล้ว');
    }catch{entry.role='guest';send(entry.conn,{type:'role',role:'guest',message:'ตรวจบัญชี Google ไม่สำเร็จ กรุณาลองใหม่'});}
  }

  function approveEntry(entry){
    if(!entry?.conn?.open||!session)return;
    if(session.pending===entry)session.pending=null;
    entry.approved=true;entry.role='guest';qrApprove.hidden=true;qrReject.hidden=true;
    send(entry.conn,{type:'ready'});send(entry.conn,snapshot(entry));
    status('เชื่อมต่อมือถือ Guest แล้ว · Owner ต้องยืนยัน Google บนมือถือ');
  }

  async function renderSessionQr(active){
    if(!active||session!==active||pairingPaused||!active.peerId)return;
    const url=new URL('remote.html',location.href);url.search='';url.searchParams.set('v',String(window.XSTAGE_RELEASE?.build||0));url.hash='p='+encodeURIComponent(active.peerId)+'&k='+encodeURIComponent(active.secret);
    qrLink.textContent='เปิดรีโมท X-Stage บนมือถือ';qrLink.href=url.href;
    try{
      qrCanvas.width=232;qrCanvas.height=232;
      await QRCode.toCanvas(qrCanvas,url.href,{width:232,margin:2,errorCorrectionLevel:'M'});
      if(session!==active||pairingPaused)return;
      qrCanvas.hidden=false;status(nativeTvMode?'สแกน QR เพื่อขอเพลงจากมือถือ':'สแกน QR แล้วรออนุมัติบนจอ');
    }catch{status('สร้าง QR ไม่สำเร็จ ใช้ลิงก์รีโมทแทน');}
  }
  function pausePairing(){
    pairingPaused=true;
    qrPanel.classList.add('pairing-paused');
    status(nativeTvMode?'รีโมทมือถือ · พัก':'QR แสดงอยู่ · พักรับผู้ใช้ใหม่ชั่วคราว · ผู้ใช้เดิมยังควบคุมได้');
    broadcastStatus();
  }
  async function resumePairing(){
    if(!session){pairingPaused=false;qrPanel.classList.remove('pairing-paused');await createSession();return;}
    pairingPaused=false;qrPanel.classList.remove('pairing-paused');
    session.secret=randomSecret();await renderSessionQr(session);broadcastStatus();
  }

  async function createSession(){
    clearPeerSession();pairingPaused=false;qrPanel.classList.remove('pairing-paused');status('กำลังเตรียมระบบรีโมท…');
    try{await ensureRemoteLibraries();}catch(error){status(error?.message||'โหลดระบบรีโมทไม่ได้ กรุณาตรวจอินเทอร์เน็ต');return;}
    if(typeof Peer!=='function'||typeof QRCode==='undefined'){status('ระบบรีโมทยังไม่พร้อม กรุณาตรวจอินเทอร์เน็ต');return;}
    if(!window.crypto?.getRandomValues){status('เบราว์เซอร์ไม่รองรับการเชื่อมต่ออย่างปลอดภัย');return;}
    const active={peer:null,peerId:'',secret:randomSecret(),connections:new Map(),pending:null};
    session=active;qrEnd.textContent='เปลี่ยน QR';status('กำลังติดต่อเซิร์ฟเวอร์รีโมท…');
    const peer=new Peer();active.peer=peer;
    const peerOpenTimer=setTimeout(()=>{
      if(session!==active)return;status(nativeTvMode?'สร้าง QR นานเกินไป · กด MENU > สร้าง QR ใหม่':'สร้าง QR นานเกินไป · กดลองใหม่');
      try{peer.destroy();}catch{}session=null;qrEnd.textContent='ลองใหม่';
    },12000);
    peer.on('open',async id=>{clearTimeout(peerOpenTimer);if(session!==active)return;active.peerId=id;await renderSessionQr(active);});
    peer.on('connection',conn=>{
      if(session!==active||pairingPaused){conn.close();return;}
      if(active.connections.size>=12){conn.close();return;}
      const entry={conn,approved:false,role:'guest',lastSearch:0,lastControl:0,requests:[]};
      active.connections.set(conn,entry);
      conn.on('data',msg=>{
        if(session!==active||!msg||typeof msg!=='object')return;
        if(!entry.approved){
          if(msg.type!=='hello'||msg.key!==active.secret||pairingPaused){conn.close();return;}
          if(nativeTvMode){approveEntry(entry);return;}
          if(active.pending&&active.pending!==entry){send(conn,{type:'error',message:'จอหลักกำลังอนุมัติมือถืออีกเครื่อง'});conn.close();return;}
          active.pending=entry;qrPanel.hidden=false;stage.classList.add('remote-visible');
          qrToggle.setAttribute('aria-expanded','true');qrApprove.hidden=false;qrReject.hidden=false;
          status('มือถือขอเชื่อมต่อ · กด “อนุญาต” หนึ่งครั้ง');send(conn,{type:'pending'});return;
        }
        if(msg.type==='owner-auth'){void verifyOwner(entry,msg.accessToken);return;}
        if(msg.type==='search'){
          if(!entryPermissions(entry).search){send(conn,{type:'results',items:[],query:String(msg.query||'').trim().toLocaleLowerCase('th')});return;}
          const now=Date.now();if(now-entry.lastSearch<150)return;entry.lastSearch=now;
          const term=String(msg.query||'').trim().slice(0,70).toLocaleLowerCase('th'),items=[];
          if(term&&state.token){
            const ranked=typeof window.XStageRankSearch==='function'?window.XStageRankSearch(state.songs,term,200):state.songs.map((song,index)=>({song,index}));
            for(const match of ranked){const song=match.song;if(!playable(song))continue;items.push({index:match.index,code:String(song.code||''),title:String(song.title||''),artist:String(song.artist||'')});if(items.length>=30)break;}
          }
          send(conn,{type:'results',items,query:term,notReady:!state.token});
        }else if(msg.type==='request')acceptRequest(conn,msg,entry.requests);
        else if(msg.type==='control')handleControl(conn,msg,entry);
        else if(msg.type==='admin')void handleAdmin(entry,msg);
        else if(msg.type==='refresh')send(conn,snapshot(entry));
      });
      const cleanup=()=>{active.connections.delete(conn);if(active.pending===entry){active.pending=null;qrApprove.hidden=true;qrReject.hidden=true;status('มือถือยกเลิกการเชื่อมต่อ');}};
      conn.on('close',cleanup);conn.on('error',cleanup);
    });
    peer.on('error',err=>{
      clearTimeout(peerOpenTimer);
      if(session!==active)return;
      status('เชื่อมต่อรีโมทไม่ได้ ('+(err?.type||'เครือข่าย')+') · '+(nativeTvMode?'กด MENU เพื่อสร้าง QR ใหม่':'กด “เปลี่ยน QR” เพื่อลองใหม่'));
      qrEnd.textContent='ลองสร้าง QR ใหม่';
      if(!active.peerId){
        try{peer.destroy();}catch{}
        session=null;
      }
    });
    peer.on('disconnected',()=>{
      if(session!==active)return;
      status('เซิร์ฟเวอร์จับคู่หลุด · กำลังเชื่อมต่อใหม่');
      try{if(!peer.destroyed&&peer.disconnected)peer.reconnect();}catch{
        status('เชื่อมต่อรีโมทไม่สำเร็จ · กด “เปลี่ยน QR”');
      }
    });
  }

  qrApprove.addEventListener('click',()=>{const entry=session?.pending;if(entry?.conn?.open)approveEntry(entry);});
  qrReject.addEventListener('click',()=>{const entry=session?.pending;if(entry){session.pending=null;entry.conn.close();}qrApprove.hidden=true;qrReject.hidden=true;status('ปฏิเสธการเชื่อมต่อมือถือ');});
  qrEnd.addEventListener('click',createSession);
  function showQR(open){
    qrPanel.hidden=!open;stage.classList.toggle('remote-visible',open);qrToggle.setAttribute('aria-expanded',String(open));qrToggle.classList.toggle('active',open);
    if(open&&!session)void createSession();
  }
  qrToggle.addEventListener('click',()=>showQR(qrPanel.hidden));
  qrClose.addEventListener('click',()=>{if(!nativeTvMode)showQR(false);});
  window.XStageRemoteQr={show:showQR,retry:createSession,pause:pausePairing,resume:resumePairing,status:()=>({paused:pairingPaused,connected:session?.connections?.size||0,hasQr:!!session?.peerId})};
  window.dispatchEvent(new CustomEvent('xstage:remote-ready'));
  window.addEventListener('xstage:auth-ready',()=>{if(nativeTvMode)showQR(true);});
  setInterval(broadcastStatus,1200);
  window.addEventListener('beforeunload',clearPeerSession);
  ui.logout.addEventListener('click',clearPeerSession);
  if(nativeTvMode)setTimeout(()=>showQR(true),0);
})();
