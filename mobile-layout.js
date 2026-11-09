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
  if(!stage||!menu||!toggle||!queueDock||!stageColumn)return;
  const mq=window.matchMedia('(max-width: 820px), (max-height: 520px) and (pointer: coarse)');
  const isCompact=()=>mq.matches;
  function setMenu(open){
    menu.hidden=!open;
    toggle.setAttribute('aria-expanded',String(open));
    toggle.setAttribute('aria-label',open?'ปิดเมนู':'เปิดเมนู');
    toggle.firstChild.textContent=open?'✕ ':'☰ ';
    stage.classList.toggle('mobile-menu-open',open);
  }
  function updateIndicators(){
    const loginButton=$('login'), logoutButton=$('logout');
    signin.hidden=!!(loginButton?.hidden);
    signout.hidden=!!(logoutButton?.hidden);
    count.textContent=$('queue-count')?.textContent||'0';
    status.textContent=$('status')?.textContent||'';
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
  signin.addEventListener('click',()=>{finish();$('login')?.click();});
  signout.addEventListener('click',()=>{finish();$('logout')?.click();});
  stage.addEventListener('pointerdown',e=>{
    if(!menu.hidden&&!menu.contains(e.target)&&!toggle.contains(e.target))setMenu(false);
  });
  document.addEventListener('keydown',e=>{
    if(e.key==='Escape'&&!menu.hidden){e.preventDefault();setMenu(false);toggle.focus();}
  });
  if(mq.addEventListener)mq.addEventListener('change',()=>{
    updateIndicators();
  });
  const observer=new MutationObserver(updateIndicators);
  const accountLogin=$('login'),accountLogout=$('logout'),queueCount=$('queue-count'),line=$('status');
  if(accountLogin)observer.observe(accountLogin,{attributes:true,attributeFilter:['hidden']});
  if(accountLogout)observer.observe(accountLogout,{attributes:true,attributeFilter:['hidden']});
  if(queueCount)observer.observe(queueCount,{childList:true,subtree:true,characterData:true});
  if(line)observer.observe(line,{childList:true,subtree:true,characterData:true});
  setMenu(window.innerWidth>=1100);updateIndicators();
})();