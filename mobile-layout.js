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
  // Keep the existing search input, results, and listeners; physically move
  // that ONE dock out of the top toolbar on phones. Never duplicate its ID.
  const searchSlot=document.querySelector('.stage-search-slot');
  const searchToolbar=searchSlot?.parentNode||null;
  const searchAnchor=searchSlot&&searchToolbar?document.createComment('original search toolbar slot'):null;
  if(searchAnchor)searchToolbar.insertBefore(searchAnchor,searchSlot);
  const bottomSearchQuery=window.matchMedia('(max-width:820px), (max-height:540px) and (pointer:coarse)');
  // Move the original MIDI transpose and Next controls, never clone their IDs.
  const transpose=$('midi-transpose-control');
  const transposeToolbar=transpose?.parentNode||null;
  const transposeAnchor=transpose&&transposeToolbar?document.createComment('transpose toolbar position'):null;
  if(transposeAnchor)transposeToolbar.insertBefore(transposeAnchor,transpose);
  const transportPanel=stage.querySelector('.transport-panel');
  const transportRow=transportPanel?.querySelector('.transport-row');
  const mainControls=transportPanel?.querySelector('.transport-main');
  const nextButton=$('next'),cancelButton=$('cancel-current');
  const nextAnchor=nextButton&&mainControls?document.createComment('original next song position'):null;
  if(nextAnchor)mainControls.insertBefore(nextAnchor,nextButton);
  const visualViewport=window.visualViewport;
  function syncSearchKeyboardInset(){
    if(!document.body.classList.contains('xstage-mobile-search-bottom'))return;
    // The bottom search must stay just above the software keyboard.
    // Safari often retains the layout height while shrinking/panning its
    // visual viewport; Chromium can instead resize both viewports.
    const layoutHeight=document.documentElement.clientHeight||window.innerHeight;
    const visualHeight=visualViewport?.height||layoutHeight;
    const visualTop=visualViewport?.offsetTop||0;
    const editing=document.activeElement===$('search');
    const obscured=Math.max(0,Math.round(layoutHeight-visualHeight-visualTop));
    const inset=editing&&layoutHeight-visualHeight>80?obscured:0;
    document.documentElement.style.setProperty('--xs-search-keyboard-inset',inset+'px');
    document.documentElement.style.setProperty('--xs-search-visual-height',Math.round(visualHeight)+'px');
  }
  function syncBottomSearch(){
    if(!searchSlot||!searchToolbar)return;
    const mobile=bottomSearchQuery.matches&&!document.body.classList.contains('xstage-native-tv');
    if(mobile&&searchSlot.parentNode!==stage){
      stage.insertBefore(searchSlot,stage.querySelector('.mobile-stage-menu'));
    }else if(!mobile&&searchSlot.parentNode!==searchToolbar){
      searchToolbar.insertBefore(searchSlot,searchAnchor);
    }
    if(mobile){
      if(transpose&&transportPanel&&transportRow&&transpose.parentNode!==transportPanel)
        transportPanel.insertBefore(transpose,transportRow);
      if(nextButton&&cancelButton&&mainControls&&nextButton.nextElementSibling!==cancelButton)
        mainControls.insertBefore(nextButton,cancelButton);
    }else{
      if(transpose&&transposeToolbar&&transposeAnchor&&transpose.parentNode!==transposeToolbar)
        transposeToolbar.insertBefore(transpose,transposeAnchor);
      if(nextButton&&nextAnchor&&nextButton.nextSibling!==nextAnchor)
        nextAnchor.parentNode?.insertBefore(nextButton,nextAnchor);
    }
    document.body.classList.toggle('xstage-mobile-search-bottom',mobile);
    if(!mobile)document.documentElement.style.removeProperty('--xs-search-keyboard-inset');
    else syncSearchKeyboardInset();
  }
  bottomSearchQuery.addEventListener?.('change',syncBottomSearch);
  visualViewport?.addEventListener('resize',syncSearchKeyboardInset,{passive:true});
  visualViewport?.addEventListener('scroll',syncSearchKeyboardInset,{passive:true});
  window.addEventListener('resize',syncBottomSearch,{passive:true});
  window.addEventListener('orientationchange',syncBottomSearch,{passive:true});
  document.getElementById('search')?.addEventListener('focus',syncSearchKeyboardInset);
  document.getElementById('search')?.addEventListener('blur',syncSearchKeyboardInset);
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
  syncBottomSearch();
  setMenu(false);updateIndicators();
})();