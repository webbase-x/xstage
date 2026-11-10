/* X-Stage full-stage UI event bindings. Keeps legacy song, auth and Drive code intact. */
'use strict';
(function(){
  const $=id=>document.getElementById(id);
  const stage=$('stage');
  const queueDock=$('stage-queue-panel');
  const queueBtn=$('stage-queue-toggle');
  const count=$('stage-queue-count');
  const volume=$('volume'),volumeLabel=$('stage-volume-value');
  const repeat=$('repeat'),repeatBtn=$('stage-repeat');
  const install=$('toolbar-install-app');
  const home=$('mobile-home-toggle');
  const about=$('mobile-about-toggle');
  const fullscreen=$('fullscreen');
  const fullscreenSupported=!!(document.fullscreenEnabled&&typeof stage?.requestFullscreen==='function'&&typeof document.exitFullscreen==='function');
  document.body.classList.toggle('xstage-no-fullscreen',!fullscreenSupported);
  document.documentElement.classList.toggle('xstage-no-fullscreen',!fullscreenSupported);
  if(!fullscreenSupported){
    if(fullscreen)fullscreen.hidden=true;
    const mobileFullscreen=$('mobile-fullscreen-toggle');if(mobileFullscreen)mobileFullscreen.hidden=true;
    const ctxFullscreen=document.querySelector('#xstage-context-menu [data-cmd="fullscreen"]');if(ctxFullscreen)ctxFullscreen.hidden=true;
  }
  const shuffle=$('stage-shuffle');
  if(!stage||!queueDock||!queueBtn||!volume||!repeat)return;
  // Keep speed and repeat beside the player. Utility commands live in one canonical menu.

  function syncQueue(){
    const n=$('queue-count')?.textContent?.trim()||'0';
    if(count)count.textContent=n;
    const open=queueDock.classList.contains('mobile-expanded');
    queueBtn.setAttribute('aria-expanded',String(open));
    queueBtn.title=open?'ซ่อนคิวเพลง':'แสดงคิวเพลง';
  }
  function syncVolume(){
    const n=Math.round(Number(volume.value)||0);
    const player=$('player');
    const muted=!!player?.muted;
    if(volumeLabel){
      volumeLabel.textContent=muted?'ปิดเสียง · '+n+'%':n+'%';
      volumeLabel.classList.toggle('is-muted',muted);
    }
  }
  function syncRepeat(){
    if(repeatBtn){
      repeatBtn.setAttribute('aria-pressed',String(repeat.checked));
      repeatBtn.title=repeat.checked?'ปิดการวนเพลง':'เปิดการวนเพลง';
    }
  }
  queueBtn.addEventListener('click',()=>$('mobile-queue-toggle')?.click());
  const stageToolsBtn=$('stage-tools-toggle');
  stageToolsBtn?.addEventListener('click',()=>{
    $('mobile-menu-toggle')?.click();
    stageToolsBtn.setAttribute('aria-expanded',String($('mobile-menu-toggle')?.getAttribute('aria-expanded')==='true'));
  });
  const mobileSpeed=$('mobile-speed-select');
  function syncMobileSpeed(){if(mobileSpeed)mobileSpeed.value=String(ui.speed.value);}
  mobileSpeed?.addEventListener('change',()=>{
    ui.speed.value=String(mobileSpeed.value);
    ui.speed.dispatchEvent(new Event('change',{bubbles:true}));
  });
  ui.speed?.addEventListener('change',syncMobileSpeed);
  syncMobileSpeed();
  shuffle?.addEventListener('click',()=>$('pc-random')?.click());
  const medleyMenu=$('mobile-medley-toggle');
  function syncMedleyMenu(){
    if(!medleyMenu)return;
    medleyMenu.setAttribute('aria-pressed',String(!!state.medley));
    medleyMenu.textContent=state.medley?'♫ ปิดเมดเลย์สุ่มเพลง':'♫ เปิดเมดเลย์สุ่มเพลงต่อเนื่อง';
  }
  medleyMenu?.addEventListener('click',()=>{setMedleyMode(!state.medley);syncMedleyMenu();});
  window.addEventListener('xstage:medleychange',syncMedleyMenu);
  syncMedleyMenu();
  // Preserve every legacy X-Stage feature by routing visible commands to
  // the original handlers; no parallel playback/queue implementations.
  const closeMenu=()=>{
    if($('mobile-menu-toggle')?.getAttribute('aria-expanded')==='true')$('mobile-menu-toggle').click();
  };
  const legacyCommands={
    'mobile-stage-pop':'pc-stage-pop',
    'mobile-random':'pc-random',
    'mobile-history':'pc-history',
    'mobile-lyrics':'pc-lyrics-settings',
    'mobile-eq':'pc-eq',
    'mobile-ab-a':'pc-loop-a',
    'mobile-ab-b':'pc-loop-b',
    'mobile-ab-clear':'pc-loop-clear',
    'mobile-import-queue':'pc-import',
    'mobile-export-queue':'pc-export',
    'mobile-more-tools':'pc-other-tools'
  };
  Object.entries(legacyCommands).forEach(([id,target])=>{
    $(id)?.addEventListener('click',()=>{
      $(target)?.click(); // Open the second screen synchronously within this user gesture.
      closeMenu();
    });
  });

  const contextMenu=$('xstage-context-menu');
  function hideContextMenu(){if(contextMenu)contextMenu.hidden=true;}
  document.addEventListener('contextmenu',event=>{
    if(!contextMenu)return;
    if(event.target.closest('input,textarea,select,[contenteditable="true"],.pc-dialog,.remote-pair-panel'))return;
    if(event.target.closest('.song-item'))return;
    const stageHit=event.target.closest('.stage,.stage-column,.transport-panel,.stage-toolbar,.mobile-stage-menu');
    if(!stageHit)return;
    event.preventDefault();
    contextMenu.hidden=false;
    const pad=8,w=contextMenu.offsetWidth||190,h=contextMenu.offsetHeight||300;
    const left=Math.min(event.clientX,innerWidth-w-pad),top=Math.min(event.clientY,innerHeight-h-pad);
    contextMenu.style.left=Math.max(pad,left)+'px';
    contextMenu.style.top=Math.max(pad,top)+'px';
  });
  document.addEventListener('pointerdown',event=>{if(contextMenu&&!contextMenu.hidden&&!event.target.closest('#xstage-context-menu'))hideContextMenu();});
  window.addEventListener('blur',hideContextMenu);
  window.addEventListener('resize',hideContextMenu);
  contextMenu?.addEventListener('click',event=>{
    const button=event.target.closest('button[data-cmd]');if(!button)return;
    const cmd=button.dataset.cmd;hideContextMenu();
    if(cmd==='find')$('pc-find')?.click();
    else if(cmd==='queue')$('stage-queue-toggle')?.click();
    else if(cmd==='eq')$('pc-eq')?.click();
    else if(cmd==='stage')$('pc-stage-pop')?.click();
    else if(cmd==='medley')$('mobile-medley-toggle')?.click();
    else if(cmd==='tools')$('stage-tools-toggle')?.click();
    else if(cmd==='share')$('pc-share-library')?.click();
    else if(cmd==='fullscreen')$('fullscreen')?.click();
  });

  const favoriteToggle=$('pc-favorites-only'),favoriteMenu=$('mobile-favorites');
  favoriteMenu?.addEventListener('click',()=>{
    if(!favoriteToggle)return;
    favoriteToggle.checked=!favoriteToggle.checked;
    favoriteToggle.dispatchEvent(new Event('change',{bubbles:true}));
    favoriteMenu.setAttribute('aria-pressed',String(favoriteToggle.checked));
    favoriteMenu.textContent=favoriteToggle.checked?'★ เพลงโปรด (เปิดตัวกรอง)':'★ เพลงโปรด';
    closeMenu();
  });
  repeatBtn?.addEventListener('click',()=>{
    repeat.checked=!repeat.checked;
    repeat.dispatchEvent(new Event('change',{bubbles:true}));
  });
  volume.addEventListener('input',syncVolume);
  $('player')?.addEventListener('volumechange',syncVolume);
  // Wheel adjusts audio without scrolling the stage; never intercept normal page scrolling elsewhere.
  stage.addEventListener('wheel',event=>{
    if(event.ctrlKey||event.altKey||event.metaKey||event.target.closest('input,textarea,select,.remote-pair-panel,.mobile-stage-menu'))return;
    event.preventDefault();
    const next=Math.max(0,Math.min(100,Number(volume.value)+(event.deltaY<0?5:-5)));
    if(Number(volume.value)!==next){
      volume.value=String(next);volume.dispatchEvent(new Event('input',{bubbles:true}));
    }
  },{passive:false});
  const speaker=document.querySelector('.volume-control span[aria-hidden]');
  if(speaker){
    speaker.style.cursor='pointer';speaker.setAttribute('role','button');
    speaker.setAttribute('tabindex','0');speaker.setAttribute('aria-label','ปิดหรือเปิดเสียง');
    function syncMute(){const player=$('player');if(!player)return;
      speaker.textContent=player.muted?'🔇':'🔊';
      speaker.setAttribute('aria-pressed',String(player.muted));
      speaker.title=player.muted?'เปิดเสียง':'ปิดเสียง';
      syncVolume();}
    function toggleMute(){const player=$('player');if(!player)return;player.muted=!player.muted;syncMute();}
    speaker.addEventListener('click',toggleMute);
    speaker.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();toggleMute();}});
    $('player')?.addEventListener('volumechange',syncMute);syncMute();
  }
  repeat.addEventListener('change',syncRepeat);
  const queueCount=$('queue-count');
  if(queueCount)new MutationObserver(syncQueue).observe(queueCount,{childList:true,subtree:true,characterData:true});
  new MutationObserver(syncQueue).observe(queueDock,{attributes:true,attributeFilter:['class']});
  fullscreen?.addEventListener('click',()=>queueDock.classList.remove('mobile-expanded'));
  document.addEventListener('fullscreenchange',()=>{
    if(!fullscreen)return;
    const full=document.fullscreenElement===stage;
    fullscreen.setAttribute('aria-label',full?'ออกจากเต็มหน้าจอ':'แสดงเต็มหน้าจอ');
    fullscreen.title=full?'ออกจากเต็มหน้าจอ':'เต็มหน้าจอ';
  });
  home?.addEventListener('click',()=>{
    $('search').value='';
    $('search').dispatchEvent(new Event('input',{bubbles:true}));
    if($('pc-search')?.classList.contains('pc-expanded'))$('pc-hide-search')?.click();
    queueDock.classList.remove('mobile-expanded');
    document.querySelector('.stage-column')?.classList.remove('mobile-tools-expanded');
    if($('mobile-menu-toggle')?.getAttribute('aria-expanded')==='true')$('mobile-menu-toggle').click();
  });
  about?.addEventListener('click',()=>{
    const dialog=$('pc-dialog'),title=$('pc-dialog-title'),body=$('pc-dialog-body');
    if(!dialog||!title||!body)return;
    title.textContent='เกี่ยวกับ X-Stage Karaoke Online';
    body.replaceChildren();
    const release=window.XSTAGE_RELEASE||{version:'-',build:'-'};
    for(const description of [
      'X-Stage Karaoke Online · Web '+release.version+' · Build '+release.build,
      'เว็บแอปคาราโอเกะสำหรับคลังเพลง Google Drive ส่วนตัว',
      'ค้นหาเพลงแบบเรียลไทม์ด้วยรหัส ชื่อเพลง หรือศิลปิน · จัดคิว · แป้นพิมพ์บนเวที · รีโมทมือถือผ่าน QR',
      'ไฟล์เพลงและข้อมูล Google OAuth ไม่ได้ถูกเผยแพร่ใน GitHub Pages หรือส่งไปยังรีโมทมือถือ'
    ]){
      const p=document.createElement('p');p.textContent=description;body.append(p);
    }
    if($('mobile-menu-toggle')?.getAttribute('aria-expanded')==='true')$('mobile-menu-toggle').click();
    if(!dialog.open)dialog.showModal();
  });
  // Show OAuth/Drive errors even when the legacy status strip is hidden.
  const legacyStatus=$('status');
  if(legacyStatus){
    const notice=document.createElement('div');
    notice.className='stage-status-toast';
    notice.setAttribute('role','status');
    notice.hidden=true;
    stage.append(notice);
    const sync=()=>{
      const error=legacyStatus.classList.contains('error');
      const raw=String(legacyStatus.textContent||'').trim();
      const punctuationOnly=!raw||/^[\s.,;:!?'"“”‘’·…\-–—_/\\]+$/u.test(raw);
      const message=punctuationOnly?'เกิดข้อผิดพลาดในการเชื่อมต่อ กรุณาลองใหม่อีกครั้ง':raw;
      notice.hidden=!error;
      if(error)notice.textContent=message;
    };
    new MutationObserver(sync).observe(legacyStatus,{attributes:true,attributeFilter:['class'],childList:true,subtree:true,characterData:true});
    sync();
  }
  // A click outside transient panels closes the queue only if it is not the player/queue trigger.
  stage.addEventListener('pointerdown',event=>{
    if(queueDock.classList.contains('mobile-expanded')
       &&!queueDock.contains(event.target)
       &&!queueBtn.contains(event.target)
       &&!$('mobile-queue-toggle')?.contains(event.target)){
      queueDock.classList.remove('mobile-expanded');
    }
  });
  syncQueue();syncRepeat();syncVolume();
})();