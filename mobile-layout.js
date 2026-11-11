/* Compact-screen layout: keep the stage and search front and centre.
 * All original controls remain functional, revealed by the in-stage menu. */
'use strict';
(function(){
  const $ = id => document.getElementById(id);
  const stage=$('stage'), menu=$('mobile-stage-menu'), toggle=$('mobile-menu-toggle');
  const queue=$('mobile-queue-toggle'), tools=$('mobile-tools-toggle');
  const keyboard=$('mobile-keyboard-toggle'), remote=$('toggle-remote');
  const fullscreen=$('mobile-fullscreen-toggle');
  const signin=$('mobile-login-toggle'), signout=$('mobile-logout-toggle');
  const queueDock=document.querySelector('.queue-dock');
  const stageColumn=document.querySelector('.stage-column');
  const count=$('mobile-queue-count'), status=$('mobile-menu-status');
  const pullRefresh=$('pull-refresh'), pullRefreshText=$('pull-refresh-text');
  if(!stage||!menu||!toggle||!queueDock||!stageColumn)return;
  const mq=window.matchMedia('(max-width: 820px), (max-height: 520px) and (pointer: coarse)');
  const isCompact=()=>mq.matches;
  function setMenu(open){
    menu.hidden=!open;
    toggle.setAttribute('aria-expanded',String(open));
    toggle.setAttribute('aria-label',open?'ปิดเมนู':'เปิดเมนู');
    toggle.firstChild.textContent=open?'✕ ':'☰ ';
    if(!document.body.classList.contains('xstage-native-tv'))$('stage-tools-toggle')?.setAttribute('aria-expanded',String(open));
    stage.classList.toggle('mobile-menu-open',open);
  }
  function updateIndicators(){
    const logoutButton=$('logout');
    const loggedIn=!!(logoutButton&&!logoutButton.hidden);
    signin.hidden=loggedIn;
    signout.hidden=!loggedIn;
    count.textContent=$('queue-count')?.textContent||'0';
    const total=String($('song-total')?.textContent||'').trim();
    status.textContent=loggedIn
      ? ('Google Drive พร้อมใช้งาน'+(total?' · '+total:''))
      : 'ยังไม่ได้เชื่อมต่อ Google Drive';
    queue.setAttribute('aria-expanded',String(queueDock.classList.contains('mobile-expanded')));
    tools.setAttribute('aria-expanded',String(stageColumn.classList.contains('mobile-tools-expanded')));
  }
  toggle.addEventListener('click',()=>{setMenu(menu.hidden);updateIndicators();});
  $('mobile-menu-close')?.addEventListener('click',()=>setMenu(false));
  // Menu actions close their menu unless the user is expanding a nested group.
  menu.addEventListener('click',e=>{
    const button=e.target.closest('button');
    if(!button||!menu.contains(button))return;
    if(button.closest('summary,details') && button.matches('summary'))return;
    queueMicrotask(()=>{if(!menu.hidden)setMenu(false);});
  });
  function finish(){setMenu(false);updateIndicators();}
  queue.addEventListener('click',async()=>{
    const willShow=!queueDock.classList.contains('mobile-expanded');
    queueDock.classList.toggle('mobile-expanded',willShow);
    finish();
  });
  tools.addEventListener('click',async()=>{
    const willShow=!stageColumn.classList.contains('mobile-tools-expanded');
    stageColumn.classList.toggle('mobile-tools-expanded',willShow);
    finish();
    if(willShow)stageColumn.querySelector('.pc-tools')?.scrollIntoView({behavior:'smooth',block:'nearest'});
  });
  keyboard.addEventListener('click',()=>{finish();$('toggle-keyboard')?.click();});
  remote.addEventListener('click',finish);
  $('remote-request-toggle')?.addEventListener('click',finish);
  fullscreen.addEventListener('click',()=>{finish();$('fullscreen')?.click();});
  signin.addEventListener('click',()=>{
    finish();
    const gate=$('gate');
    if(gate){
      gate.hidden=false;
      $('gate-login')?.focus();
    }
  });
  signout.addEventListener('click',()=>{finish();$('logout')?.click();});
  stage.addEventListener('pointerdown',e=>{
    if(!menu.hidden&&!menu.contains(e.target)&&!toggle.contains(e.target))setMenu(false);
  });
  document.addEventListener('keydown',e=>{
    if(e.key==='Escape'&&!menu.hidden){e.preventDefault();setMenu(false);toggle.focus();}
  });

  // Pull-to-refresh for compact screens/Web App. Ignore all interactive/scrolling surfaces.
  let pullStartY=0,pullDistance=0,pullActive=false,pullReady=false;
  const pullThreshold=88;
  const blockedPullTarget=target=>!!target.closest(
    'button,input,select,textarea,a,[contenteditable="true"],.stage-toolbar,.transport-panel,.mobile-stage-menu,.search-dock,.queue-dock,.pc-tools,.remote-pair-panel,.remote-request-panel,.xstage-eq-panel,.virtual-keyboard,.pc-dialog'
  );
  function resetPullRefresh(){
    pullActive=false;pullReady=false;pullDistance=0;
    if(pullRefresh){
      pullRefresh.hidden=true;
      pullRefresh.classList.remove('ready','refreshing');
      pullRefresh.style.setProperty('--pull-distance','0px');
    }
    if(pullRefreshText)pullRefreshText.textContent='ดึงลงเพื่อรีเฟรช';
  }
  stage.addEventListener('touchstart',event=>{
    if(!isCompact()||event.touches.length!==1||blockedPullTarget(event.target))return;
    pullStartY=event.touches[0].clientY;
    pullDistance=0;pullActive=true;pullReady=false;
  },{passive:true});
  stage.addEventListener('touchmove',event=>{
    if(!pullActive||event.touches.length!==1)return;
    const dy=event.touches[0].clientY-pullStartY;
    if(dy<=0){resetPullRefresh();return;}
    pullDistance=Math.min(130,dy*.62);
    if(dy>8)event.preventDefault();
    if(pullRefresh){
      pullRefresh.hidden=false;
      pullRefresh.style.setProperty('--pull-distance',pullDistance+'px');
    }
    const ready=dy>=pullThreshold;
    if(ready!==pullReady){
      pullReady=ready;
      pullRefresh?.classList.toggle('ready',ready);
      if(pullRefreshText)pullRefreshText.textContent=ready?'ปล่อยเพื่อรีเฟรช':'ดึงลงเพื่อรีเฟรช';
    }
  },{passive:false});
  stage.addEventListener('touchend',()=>{
    if(!pullActive)return;
    const refresh=pullReady;
    pullActive=false;
    if(refresh){
      if(pullRefresh){
        pullRefresh.hidden=false;
        pullRefresh.classList.add('refreshing');
        pullRefresh.classList.remove('ready');
      }
      if(pullRefreshText)pullRefreshText.textContent='กำลังรีเฟรช…';
      setTimeout(async()=>{
        let handled=false;
        try{
          if(typeof window.XStageSoftRefresh==='function'){
            handled=!!(await window.XStageSoftRefresh());
          }
        }catch(error){
          console.warn('X-Stage soft refresh:',error?.message||error);
        }
        if(handled){
          resetPullRefresh();
          return;
        }
        window.location.reload();
      },90);
    }else resetPullRefresh();
  },{passive:true});
  stage.addEventListener('touchcancel',resetPullRefresh,{passive:true});

  if(mq.addEventListener)mq.addEventListener('change',()=>{
    updateIndicators();
  });
  const observer=new MutationObserver(updateIndicators);
  const accountLogout=$('logout'),queueCount=$('queue-count'),songTotal=$('song-total');
  if(accountLogout)observer.observe(accountLogout,{attributes:true,attributeFilter:['hidden']});
  if(queueCount)observer.observe(queueCount,{childList:true,subtree:true,characterData:true});
  if(songTotal)observer.observe(songTotal,{childList:true,subtree:true,characterData:true});
  setMenu(window.innerWidth>=1100);updateIndicators();
})();