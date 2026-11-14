/* X-Stage Karaoke Online: Android APK offer and cleanup for the retired PWA.
 * Browser playback remains a standard website; no new service worker is installed. */
'use strict';
(() => {
  const $=id=>document.getElementById(id);
  const apkMenuLink=$('android-tv-apk-download'),dialog=$('xstage-apk-dialog');
  const content=$('xstage-apk-content'),closeButton=$('xstage-apk-close'),title=$('xstage-apk-title');
  const ANDROID_TV_LATEST_URL='./downloads/android-tv-latest.json';
  const ANDROID_APK_NEVER_ASK_KEY='xstage-android-apk-never-ask-v1';
  const ANDROID_APK_OFFERED_KEY='xstage-android-apk-offered-build-v1';
  let verifiedAndroidApk=null;
  // Remove only the old X-Stage worker for this page scope and its shell cache.
  // Do not disturb the separate Song Studio scope, private media or OAuth state.
  async function retireLegacyPwa(){
    try{
      if('serviceWorker' in navigator){
        const expected=new URL('./',location.href).href;
        const registrations=await navigator.serviceWorker.getRegistrations();
        await Promise.all(registrations.filter(reg=>reg.scope===expected).map(reg=>reg.unregister()));
      }
    }catch(error){console.warn('Legacy worker cleanup:',error?.message||error);}
    try{
      if('caches' in window){
        const names=await caches.keys();
        await Promise.all(names.filter(name=>name.startsWith('xstage-shell-')).map(name=>caches.delete(name)));
      }
    }catch(error){console.warn('Legacy shell cache cleanup:',error?.message||error);}
  }
  void retireLegacyPwa();
  const isAndroidBrowser=()=>{
    if(!/Android/i.test(navigator.userAgent||'')||window.XStageAndroid)return false;
    const source=new URLSearchParams(location.search).get('source');
    return source!=='android-tv'&&source!=='android-tablet';
  };
  async function refreshAndroidTvApkLink(){
    try{
      const metaUrl=new URL(ANDROID_TV_LATEST_URL,location.href);
      metaUrl.searchParams.set('_',String(Date.now()));
      const response=await fetch(metaUrl,{cache:'no-store'});
      if(!response.ok)throw Error('HTTP '+response.status);
      const meta=await response.json();
      const file=String(meta?.file||'').trim();
      const version=String(meta?.version||'').trim();
      const build=Number(meta?.build);
      const hash=String(meta?.sha256||'').trim();
      if(!/^X-Stage-Karaoke-Android(?:-TV)?-v[0-9A-Za-z._-]+-build[0-9]+\.apk$/.test(file)||
        !/^\d+\.\d+\.\d+$/.test(version)||!Number.isSafeInteger(build)||build<1||
        !new Set(['X-Stage-Karaoke-Android-v'+version+'-build'+build+'.apk',
          'X-Stage-Karaoke-Android-TV-v'+version+'-build'+build+'.apk']).has(file)||
        !/^[a-fA-F0-9]{64}$/.test(hash))throw Error('ข้อมูล APK ไม่ผ่านการตรวจสอบ');
      verifiedAndroidApk={url:new URL('./downloads/'+file,location.href).href,file,version,build};
      if(apkMenuLink){
        apkMenuLink.href=verifiedAndroidApk.url;
        apkMenuLink.download=file;
        apkMenuLink.textContent='ดาวน์โหลด Android APK v'+version+' (Build '+build+')';
        apkMenuLink.hidden=!isAndroidBrowser();
      }
      return verifiedAndroidApk;
    }catch(error){
      console.warn('APK availability:',error?.message||error);
      verifiedAndroidApk=null;
      if(apkMenuLink){
        apkMenuLink.removeAttribute('href');apkMenuLink.removeAttribute('download');
        apkMenuLink.hidden=true;
      }
      return null;
    }
  }
  const downloadAndroidTvApk=async()=>{
    const apk=verifiedAndroidApk||await refreshAndroidTvApkLink();
    if(apk)location.href=apk.url;
  };
  const paragraph=(message,className='')=>{
    const el=document.createElement('p');el.textContent=message;
    if(className)el.className=className;return el;
  };
  const actionButton=(label,kind,handler)=>{
    const el=document.createElement('button');el.type='button';
    el.className='xstage-install-action '+kind;el.textContent=label;
    el.addEventListener('click',handler);return el;
  };
  function offerPublishedAndroidApk(apk){
    if(!apk||!isAndroidBrowser()||!dialog||!content||!title)return;
    try{
      if(localStorage.getItem(ANDROID_APK_NEVER_ASK_KEY)==='1')return;
      if(sessionStorage.getItem(ANDROID_APK_OFFERED_KEY)===String(apk.build))return;
      sessionStorage.setItem(ANDROID_APK_OFFERED_KEY,String(apk.build));
    }catch{}
    content.replaceChildren();
    title.textContent='ดาวน์โหลด X-Stage Android APK หรือไม่?';
    const webBuild=Number(window.XSTAGE_RELEASE?.build||0);
    const row=document.createElement('div');row.className='xstage-install-actions';
    row.append(
      actionButton('ดาวน์โหลด APK ตอนนี้','primary',()=>{dialog.close();void downloadAndroidTvApk();}),
      actionButton('ใช้ X-Stage Web ต่อ','secondary',()=>dialog.close())
    );
    content.append(
      paragraph('มี X-Stage Android สำหรับ TV/แท็บเล็ต v'+apk.version+' (Build '+apk.build+') พร้อมดาวน์โหลด'),
      paragraph(apk.build<webBuild
        ? 'APK ที่เผยแพร่ยังเก่ากว่าหน้าเว็บ เมื่อ APK รุ่นใหม่เผยแพร่ ระบบในแอปจะตรวจอัปเดตอีกครั้ง'
        : 'หน้าเว็บสามารถใช้งานต่อได้โดยไม่ต้องติดตั้งแอป','xstage-install-note'),
      paragraph('APK ทดสอบติดตั้งนอก Google Play โปรดยืนยันการติดตั้งใน Android ด้วยตนเอง','xstage-install-note'),
      row
    );
    const never=document.createElement('label');never.className='xstage-install-note';
    never.style.cssText='display:flex;align-items:center;gap:10px;cursor:pointer;margin:12px 0 0';
    const checkbox=document.createElement('input');checkbox.type='checkbox';
    checkbox.id='xstage-android-apk-never-ask';
    checkbox.addEventListener('change',()=>{
      try{if(checkbox.checked)localStorage.setItem(ANDROID_APK_NEVER_ASK_KEY,'1');
        else localStorage.removeItem(ANDROID_APK_NEVER_ASK_KEY);}catch{}
    });
    never.append(checkbox,document.createTextNode('ไม่ต้องถามดาวน์โหลด APK อีก'));
    content.append(never);
    if(!dialog.open)dialog.showModal();
  }
  closeButton?.addEventListener('click',()=>dialog.close());
  dialog?.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});
  if(isAndroidBrowser()){
    void refreshAndroidTvApkLink().then(apk=>{if(apk)offerPublishedAndroidApk(apk);});
  }else if(apkMenuLink){apkMenuLink.hidden=true;}
})();