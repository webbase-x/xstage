/* Install UI for X-Stage Karaoke Online.
 * Login is intentionally deferred until the installed Web App is opened when possible,
 * so users do not authenticate in a browser tab and then repeat authentication in the PWA.
 * No OAuth token or private music is cached by this feature. */
'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const menuButton = $('mobile-install-app');
  const toolsButton = $('pc-install-app');
  const toolbarButton = $('toolbar-install-app');
  const dialog = $('xstage-install-dialog');
  const content = $('xstage-install-content');
  const closeButton = $('xstage-install-close');
  if(!menuButton || !dialog || !content || !closeButton) return;

  const INSTALLED_HINT_KEY='xstage-pwa-installed-v1';
  const ANDROID_TV_LATEST_URL='./downloads/android-tv-latest.json';
  const ANDROID_TV_APK_FALLBACK='./downloads/X-Stage-Karaoke-Android-TV-v1.0.59-build1059.apk';
  const apkMenuLink=document.getElementById('android-tv-apk-download');
  const isAndroidDevice=()=>/Android/i.test(navigator.userAgent||'');
  let androidTvApkUrl=ANDROID_TV_APK_FALLBACK;

  async function refreshAndroidTvApkLink(){
    try{
      const metaUrl=new URL(ANDROID_TV_LATEST_URL,location.href);
      metaUrl.searchParams.set('_',String(Date.now()));
      const response=await fetch(metaUrl,{cache:'no-store'});
      if(!response.ok)throw new Error('HTTP '+response.status);
      const meta=await response.json();
      const file=String(meta?.file||'').trim();
      if(!/^X-Stage-Karaoke-Android-TV-v[0-9A-Za-z._-]+-build[0-9]+\.apk$/.test(file)){
        throw new Error('invalid APK filename');
      }
      androidTvApkUrl=new URL('./downloads/'+file,location.href).href;
      if(apkMenuLink){
        apkMenuLink.href=androidTvApkUrl;
        apkMenuLink.setAttribute('download',file);
        apkMenuLink.textContent='ดาวน์โหลด Android TV APK '+String(meta.version||'')+' (Build '+String(meta.build||'')+')';
      }
      return androidTvApkUrl;
    }catch(error){
      console.warn('X-Stage Android TV APK link:',error?.message||error);
      if(apkMenuLink)apkMenuLink.href=ANDROID_TV_APK_FALLBACK;
      return androidTvApkUrl;
    }
  }
  void refreshAndroidTvApkLink();
  const downloadAndroidTvApk=async()=>{location.href=await refreshAndroidTvApkLink();};
  const SKIP_INSTALL_PROMPT_KEY='xstage-skip-install-prompt-v1';
  const skipInstallPrompt=()=>{try{return localStorage.getItem(SKIP_INSTALL_PROMPT_KEY)==='1';}catch{return false;}};
  const setSkipInstallPrompt=skip=>{try{if(skip)localStorage.setItem(SKIP_INSTALL_PROMPT_KEY,'1');else localStorage.removeItem(SKIP_INSTALL_PROMPT_KEY);}catch{}};
  const standaloneQuery=window.matchMedia('(display-mode: standalone)');
  let deferredPrompt=null;
  let pendingLogin=null;
  let installForLogin=false;
  let installCompletionHandled=false;
  let launchFallbackTimer=0;

  async function ensureXStageServiceWorker(){
    if(!('serviceWorker' in navigator))return null;
    try{
      const registration=await navigator.serviceWorker.register('./sw.js',{scope:'./',updateViaCache:'none'});
      void registration.update();
      return registration;
    }catch(error){
      console.warn('X-Stage service worker:',error?.message||error);
      return null;
    }
  }
  let serviceWorkerRegistration=null;
  void ensureXStageServiceWorker().then(registration=>{serviceWorkerRegistration=registration;});
  setInterval(()=>{void serviceWorkerRegistration?.update?.();},30*60*1000);

  const isInstalled = () =>
    standaloneQuery.matches ||
    window.navigator.standalone === true;
  const hasInstalledHint=()=>{try{return localStorage.getItem(INSTALLED_HINT_KEY)==='1';}catch{return false;}};
  const markInstalled=()=>{try{localStorage.setItem(INSTALLED_HINT_KEY,'1');}catch{}};
  const canPromptInstall=()=>typeof navigator.install==='function'||!!deferredPrompt;
  const installCapabilityWaitMs=1800;
  const waitForInstallCapability=()=>new Promise(resolve=>{
    if(canPromptInstall()){resolve(true);return;}
    const started=performance.now();
    const timer=setInterval(()=>{
      if(canPromptInstall()){clearInterval(timer);resolve(true);return;}
      if(performance.now()-started>=installCapabilityWaitMs){clearInterval(timer);resolve(false);}
    },100);
  });
  const launchUrl=()=>new URL('./?source=installed&after_install=1',location.href).href;

  function syncStandaloneUi(){
    const installed=isInstalled();
    document.body.classList.toggle('xstage-webapp-mode',installed);
    document.documentElement.classList.toggle('xstage-webapp-mode',installed);
    return installed;
  }
  function updateButtons() {
    const installed = syncStandaloneUi();
    if(apkMenuLink)apkMenuLink.hidden=!isAndroidDevice();
    const knownInstalled=installed||hasInstalledHint();
    menuButton.textContent = knownInstalled ? '✓ X-Stage ติดตั้งแล้ว' : '⬇ ติดตั้ง X-Stage เป็นแอป';
    menuButton.disabled = installed;
    if(toolsButton){
      toolsButton.textContent = knownInstalled ? '✓ ติดตั้งแล้ว' : '⬇ ติดตั้งแอป';
      toolsButton.disabled = installed;
    }
    if(toolbarButton){
      toolbarButton.disabled = installed;
      toolbarButton.title = knownInstalled ? 'X-Stage ติดตั้งแล้ว' : 'ติดตั้ง X-Stage Karaoke เป็นเว็บแอป';
    }
  }

  function clearContent(){
    content.replaceChildren();
    dialog.classList.remove('is-install-first','is-install-success');
  }
  function paragraph(textValue,className=''){
    const node=document.createElement('p');
    node.textContent=textValue;
    if(className)node.className=className;
    return node;
  }
  function actionButton(label,kind,handler){
    const button=document.createElement('button');
    button.type='button';
    button.className='xstage-install-action '+kind;
    button.textContent=label;
    button.addEventListener('click',handler);
    return button;
  }
  function actionRow(...buttons){
    const row=document.createElement('div');
    row.className='xstage-install-actions';
    row.append(...buttons);
    return row;
  }
  function appendSkipInstallChoice(){
    if(content.querySelector('#xstage-skip-install-prompt'))return;
    const label=document.createElement('label');
    label.className='xstage-install-note';
    label.style.cssText='display:flex;align-items:center;gap:10px;cursor:pointer;margin:16px 0 8px;';
    const checkbox=document.createElement('input');
    checkbox.type='checkbox';
    checkbox.id='xstage-skip-install-prompt';
    checkbox.checked=skipInstallPrompt();
    checkbox.style.cssText='width:18px;height:18px;flex-shrink:0;accent-color:#20c6d8;';
    checkbox.addEventListener('change',()=>setSkipInstallPrompt(checkbox.checked));
    const text=document.createElement('span');
    text.textContent='ไม่ต้องแสดงหน้าต่างนี้อีกในครั้งต่อไป';
    label.append(checkbox,text);
    content.append(label);
  }
  function openDialog(){
    if(dialog.classList.contains('is-install-first'))appendSkipInstallChoice();
    if(!dialog.open)dialog.showModal();
  }

  function information() {
    clearContent();
    const os = navigator.userAgent || '';
    const ios = /iPad|iPhone|iPod/.test(os) || (/Macintosh/.test(os) && navigator.maxTouchPoints > 1);
    const mac = !ios && /Macintosh|Mac OS X/.test(os);
    const android = /Android/i.test(os);
    const lines = ios
      ? ['เปิดเว็บนี้ใน Safari หรือเบราว์เซอร์ที่รองรับ', 'แตะปุ่มแชร์ แล้วเลือก “เพิ่มไปยังหน้าจอโฮม” (Add to Home Screen)', 'เลือกเปิดเป็นเว็บแอป (ถ้ามี) จากนั้นแตะ “เพิ่ม”']
      : android
        ? ['เปิดเมนูของเบราว์เซอร์', 'เลือก “ติดตั้งแอป” หรือ “เพิ่มไปยังหน้าจอหลัก” แล้วกดยืนยัน', 'จากนั้นเปิดไอคอน X-Stage ที่หน้าจอหลักก่อนเข้าสู่ระบบ Google']
        : mac
          ? ['ใน Safari เลือก File → Add to Dock', 'ใน Chrome หรือ Edge เปิดเมนูแล้วเลือก Install X-Stage Karaoke หรือ Install page as app']
          : ['ใน Chrome หรือ Microsoft Edge คลิกไอคอนติดตั้งในแถบที่อยู่ หรือเปิดเมนู', 'เลือก “ติดตั้ง X-Stage Karaoke Online” หรือ “Install page as app” แล้วกดยืนยัน'];
    content.append(paragraph('เพิ่ม X-Stage ไว้บน Home Screen หรือ Desktop เพื่อเปิดโปรแกรมได้เหมือนแอป'));
    const ol=document.createElement('ol');
    for(const line of lines){const li=document.createElement('li');li.textContent=line;ol.append(li);}
    content.append(ol);
    content.append(paragraph('แนะนำให้ติดตั้งก่อนเข้าสู่ระบบ Google เพื่อให้การอนุญาตบัญชีเกิดใน Web App ที่จะใช้งานจริง','xstage-install-note'));
  }

  function runPendingLogin(){
    const callback=pendingLogin;
    pendingLogin=null;
    installForLogin=false;
    if(dialog.open)dialog.close();
    if(typeof callback==='function')callback();
  }
  function cancelPendingLogin(){
    pendingLogin=null;
    installForLogin=false;
  }

  function openInstalledApp(){
    const anchor=document.createElement('a');
    anchor.href=launchUrl();
    anchor.target='_blank';
    anchor.rel='noopener';
    anchor.hidden=true;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
  }

  function showLaunchFallback(){
    if(document.hidden||isInstalled())return;
    clearContent();
    dialog.classList.add('is-install-success');
    document.querySelector('#xstage-install-title').textContent='ติดตั้ง X-Stage เสร็จแล้ว';
    content.append(
      paragraph('กำลังพยายามเปิด X-Stage ที่ติดตั้งไว้ หากเบราว์เซอร์ยังไม่เปิดแอปอัตโนมัติ ให้กดปุ่มด้านล่างหนึ่งครั้ง'),
      actionRow(
        actionButton('เปิด X-Stage','primary',openInstalledApp)
      ),
      paragraph('ยังไม่ต้องเข้าสู่ระบบ Google ในแท็บเบราว์เซอร์นี้ ให้เข้าสู่ระบบหลังเปิด X-Stage แบบ Web App แล้ว','xstage-install-note')
    );
    openDialog();
  }

  function attemptImmediateLaunch(){
    clearTimeout(launchFallbackTimer);
    if(dialog.open)dialog.close();
    setTimeout(openInstalledApp,180);
    launchFallbackTimer=setTimeout(showLaunchFallback,1300);
  }

  function finishInstallation(){
    if(installCompletionHandled)return;
    installCompletionHandled=true;
    deferredPrompt=null;
    markInstalled();
    updateButtons();
    if(installForLogin){
      // Never authenticate in the browser tab after choosing install-first.
      pendingLogin=null;
      installForLogin=false;
      attemptImmediateLaunch();
    }else if(dialog.open){
      dialog.close();
    }
  }

  function shouldAskInstallOnEntry(){
    if(isInstalled()||skipInstallPrompt())return false;
    const params=new URLSearchParams(location.search);
    if(params.get('source')==='installed'||params.get('source')==='android-tv')return false;
    const gate=document.getElementById('gate');
    return !!(gate&&!gate.hidden);
  }

  async function showInitialInstallChoice(message=''){
    if(!shouldAskInstallOnEntry())return;
    clearContent();
    dialog.classList.add('is-install-first');
    document.querySelector('#xstage-install-title').textContent=hasInstalledHint()
      ? 'เปิด X-Stage ที่ติดตั้งแล้วก่อนเข้าสู่ระบบ'
      : 'ติดตั้ง X-Stage ก่อนเข้าสู่ระบบ';
    content.append(paragraph(
      hasInstalledHint()
        ? 'ตรวจพบว่าอุปกรณ์นี้เคยติดตั้ง X-Stage แล้ว แนะนำให้เปิด Web App ที่ติดตั้งไว้ก่อนเชื่อมต่อ Google Drive'
        : 'กำลังตรวจสอบว่าเบราว์เซอร์นี้ติดตั้ง X-Stage โดยตรงได้หรือไม่…'
    ));
    openDialog();

    if(!hasInstalledHint()&&!canPromptInstall()){
      const ready=await waitForInstallCapability();
      if(!dialog.open||!shouldAskInstallOnEntry())return;
      clearContent();
      dialog.classList.add('is-install-first');
      document.querySelector('#xstage-install-title').textContent='ติดตั้ง X-Stage ก่อนเข้าสู่ระบบ';
      if(!ready){
        const unsupportedActions=[];
        if(isAndroidDevice())unsupportedActions.push(actionButton('ดาวน์โหลด APK X-Stage','primary',downloadAndroidTvApk));
        unsupportedActions.push(actionButton('ใช้เบราว์เซอร์ต่อ','secondary',()=>{
          installForLogin=false;pendingLogin=null;
          if(dialog.open)dialog.close();
          document.getElementById('gate-login')?.focus?.();
        }));
        unsupportedActions.push(actionButton('ลองตรวจ PWA อีกครั้ง','secondary',()=>{void showInitialInstallChoice('กำลังตรวจสอบอีกครั้ง…');}));
        content.append(
          paragraph(isAndroidDevice()
            ? 'เบราว์เซอร์นี้ไม่รองรับการติดตั้ง PWA โดยตรง แต่สามารถดาวน์โหลด X-Stage Android TV APK จาก GitHub Pages ได้'
            : 'เบราว์เซอร์นี้ไม่รองรับการติดตั้ง Web App จากหน้าเว็บโดยตรง จึงไม่สามารถแสดงปุ่มติดตั้งจริงได้'),
          paragraph(isAndroidDevice()
            ? 'หลังดาวน์โหลด Android อาจขออนุญาต “ติดตั้งแอปที่ไม่รู้จัก” สำหรับเบราว์เซอร์นี้ก่อนติดตั้ง APK'
            : 'การติดตั้ง PWA ต้องอาศัยความสามารถของตัวเบราว์เซอร์เอง','xstage-install-note'),
          actionRow(...unsupportedActions)
        );
        appendSkipInstallChoice();
        return;
      }
    }else{
      clearContent();
      dialog.classList.add('is-install-first');
      document.querySelector('#xstage-install-title').textContent=hasInstalledHint()
        ? 'เปิด X-Stage ที่ติดตั้งแล้วก่อนเข้าสู่ระบบ'
        : 'ติดตั้ง X-Stage ก่อนเข้าสู่ระบบ';
    }

    if(message)content.append(paragraph(message,'xstage-install-status'));
    if(hasInstalledHint()){
      content.append(
        paragraph('เปิด X-Stage ที่ติดตั้งไว้ก่อน แล้วค่อยเชื่อมต่อ Google Drive'),
        actionRow(
          actionButton('เปิด X-Stage','primary',openInstalledApp),
          actionButton('ใช้เบราว์เซอร์ต่อ','secondary',()=>{
            installForLogin=false;pendingLogin=null;
            if(dialog.open)dialog.close();
            document.getElementById('gate-login')?.focus?.();
          })
        )
      );
    }else{
      content.append(
        paragraph('เบราว์เซอร์นี้พร้อมติดตั้ง X-Stage เป็น Web App'),
        actionRow(
          actionButton('ติดตั้ง X-Stage ตอนนี้','primary',()=>{installForLogin=true;void install({forLogin:true});}),
          actionButton('ใช้เบราว์เซอร์ต่อ','secondary',()=>{
            installForLogin=false;pendingLogin=null;
            if(dialog.open)dialog.close();
            document.getElementById('gate-login')?.focus?.();
          })
        ),
        paragraph('หลังติดตั้ง ระบบจะพยายามเปิด X-Stage ที่ติดตั้งทันที และจะไม่เปิด Google Login ในแท็บเบราว์เซอร์นี้','xstage-install-note')
      );
    }
    appendSkipInstallChoice();
    setTimeout(()=>content.querySelector('.xstage-install-action.primary')?.focus(),30);
  }

  function showPreLoginChoice(message=''){
    if(isInstalled()||skipInstallPrompt()){runPendingLogin();return;}
    if(!hasInstalledHint()&&!canPromptInstall()){void showInitialInstallChoice(message);return;}
    clearContent();
    dialog.classList.add('is-install-first');
    document.querySelector('#xstage-install-title').textContent=hasInstalledHint()
      ? 'เปิด X-Stage ที่ติดตั้งแล้วก่อนเข้าสู่ระบบ'
      : 'ติดตั้ง X-Stage ก่อนเข้าสู่ระบบไหม?';
    content.append(paragraph(
      hasInstalledHint()
        ? 'ตรวจพบว่าเคยติดตั้ง X-Stage แล้ว แนะนำให้เปิด Web App ก่อน แล้วค่อยเชื่อมต่อ Google Drive'
        : 'แนะนำให้ติดตั้ง Web App ก่อน เพื่อไม่ต้องเข้าสู่ระบบในเบราว์เซอร์ แล้วไปเข้าสู่ระบบซ้ำอีกครั้งในแอปที่ติดตั้ง'
    ));
    if(message)content.append(paragraph(message,'xstage-install-status'));

    const buttons=[];
    if(canPromptInstall()){
      buttons.push(actionButton(
        hasInstalledHint()?'ติดตั้ง/เปิด X-Stage':'ติดตั้งและเปิด X-Stage',
        'primary',
        ()=>{void install({forLogin:true});}
      ));
    }else if(hasInstalledHint()){
      buttons.push(actionButton('เปิด X-Stage','primary',openInstalledApp));
    }else{
      buttons.push(actionButton('ลองตรวจการติดตั้งอีกครั้ง','primary',()=>{void showInitialInstallChoice(message);}));
    }
    buttons.push(actionButton('ใช้เบราว์เซอร์ต่อ','secondary',runPendingLogin));
    content.append(
      actionRow(...buttons),
      paragraph('ถ้าเลือกติดตั้ง ระบบจะไม่เปิด Google Login ในแท็บนี้ และจะพยายามเปิด X-Stage ที่ติดตั้งทันที','xstage-install-note')
    );
    openDialog();
    setTimeout(()=>content.querySelector('.xstage-install-action.primary')?.focus(),30);
  }

  function showInstructions(){
    if(isInstalled()){updateButtons();return;}
    information();
    if(canPromptInstall()){
      content.append(actionRow(actionButton('ติดตั้ง X-Stage','primary',()=>{void install({forLogin:false});})));
    }
    openDialog();
  }

  async function install({forLogin=false}={}) {
    if(isInstalled()){
      updateButtons();
      if(forLogin)runPendingLogin();
      return;
    }
    installForLogin=forLogin||installForLogin;
    installCompletionHandled=false;
    try{
      if(typeof navigator.install==='function'){
        await navigator.install();
        finishInstallation();
        return;
      }
      const prompt=deferredPrompt;
      if(!prompt){
        if(forLogin)showPreLoginChoice('เบราว์เซอร์นี้ยังไม่ส่งคำสั่งติดตั้งอัตโนมัติ');
        else showInstructions();
        return;
      }
      deferredPrompt=null;
      await prompt.prompt();
      const choice=await prompt.userChoice;
      if(choice?.outcome==='accepted'){
        // appinstalled may fire first; finishInstallation is idempotent.
        finishInstallation();
      }else{
        installCompletionHandled=false;
        if(forLogin)showPreLoginChoice('ยกเลิกการติดตั้งแล้ว คุณยังเลือกใช้เบราว์เซอร์ต่อได้');
        else showInstructions();
      }
    }catch(error){
      installCompletionHandled=false;
      const cancelled=error?.name==='AbortError'||error?.name==='NotAllowedError';
      if(forLogin)showPreLoginChoice(cancelled?'ยกเลิกการติดตั้งแล้ว':'ไม่สามารถเริ่มติดตั้งอัตโนมัติได้');
      else showInstructions();
    }
  }

  // Called by app.js before any manual Google login. Returning true means this
  // module owns the flow; returning false lets app.js call login synchronously.
  window.XStageBeforeGoogleLogin=proceed=>{
    if(window.XStageAndroid&&typeof window.XStageAndroid.requestGoogleLogin==='function')return false;
    if(typeof proceed!=='function'||isInstalled()||skipInstallPrompt())return false;
    pendingLogin=proceed;
    installForLogin=true;
    showPreLoginChoice();
    return true;
  };

  menuButton.addEventListener('click',()=>{void install({forLogin:false});});
  toolsButton?.addEventListener('click',()=>{void install({forLogin:false});});
  toolbarButton?.addEventListener('click',()=>{void install({forLogin:false});});
  closeButton.addEventListener('click',()=>{cancelPendingLogin();dialog.close();});
  dialog.addEventListener('cancel',cancelPendingLogin);
  dialog.addEventListener('click',e=>{if(e.target===dialog){cancelPendingLogin();dialog.close();}});

  window.addEventListener('beforeinstallprompt',e=>{
    e.preventDefault();
    deferredPrompt=e;
    updateButtons();
    if(installForLogin&&dialog.open)showPreLoginChoice();
    else if(dialog.open&&shouldAskInstallOnEntry())void showInitialInstallChoice();
  });
  window.addEventListener('appinstalled',finishInstallation);
  standaloneQuery.addEventListener?.('change',()=>{
    updateButtons();
    if(isInstalled()){clearTimeout(launchFallbackTimer);if(dialog.open)dialog.close();}
  });
  window.addEventListener('pageshow',()=>{
    updateButtons();
    if(shouldAskInstallOnEntry()&&!dialog.open)setTimeout(()=>{void showInitialInstallChoice();},0);
  });
  updateButtons();
  if(shouldAskInstallOnEntry())setTimeout(()=>{void showInitialInstallChoice();},0);
})();