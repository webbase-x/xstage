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
  const shuffle=$('stage-shuffle');
  if(!stage||!queueDock||!queueBtn||!volume||!repeat)return;
  // Speed and legacy repeat inputs remain available from the tools drawer.
  const toolsNav=document.querySelector('.pc-tools');
  if(toolsNav){
    for(const selector of ['.speed-control','.repeat-control']){
      const option=document.querySelector('.transport-right '+selector);
      if(option)toolsNav.append(option);
    }
  }

  function syncQueue(){
    const n=$('queue-count')?.textContent?.trim()||'0';
    if(count)count.textContent=n;
    const open=queueDock.classList.contains('mobile-expanded');
    queueBtn.setAttribute('aria-expanded',String(open));
    queueBtn.title=open?'ซ่อนคิวเพลง':'แสดงคิวเพลง';
  }
  function syncVolume(){
    const n=Math.round(Number(volume.value)||0);
    if(volumeLabel)volumeLabel.textContent=n+'%';
  }
  function syncRepeat(){
    if(repeatBtn){
      repeatBtn.setAttribute('aria-pressed',String(repeat.checked));
      repeatBtn.title=repeat.checked?'ปิดการวนเพลง':'เปิดการวนเพลง';
    }
  }
  queueBtn.addEventListener('click',()=>$('mobile-queue-toggle')?.click());
  shuffle?.addEventListener('click',()=>$('pc-random')?.click());
  repeatBtn?.addEventListener('click',()=>{
    repeat.checked=!repeat.checked;
    repeat.dispatchEvent(new Event('change',{bubbles:true}));
  });
  volume.addEventListener('input',syncVolume);
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
    for(const description of [
      'X-Stage Karaoke Online — เว็บแอปคาราโอเกะสำหรับคลังเพลง Google Drive ส่วนตัว',
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
      notice.hidden=!error;
      if(error)notice.textContent=legacyStatus.textContent;
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