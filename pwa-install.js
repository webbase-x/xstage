/* Install UI for X-Stage Karaoke Online.
 * Install prompts are supported in Chromium only; iOS needs Add to Home Screen.
 * No OAuth token or private music is cached by this feature. */
'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const menuButton = $('mobile-install-app');
  const toolsButton = $('pc-install-app');
  const dialog = $('xstage-install-dialog');
  const content = $('xstage-install-content');
  const closeButton = $('xstage-install-close');
  if(!menuButton || !dialog || !content || !closeButton) return;
  let deferredPrompt = null;
  const isInstalled = () =>
    window.matchMedia('(display-mode: standalone)').matches ||
    window.navigator.standalone === true;
  function updateButtons() {
    const installed = isInstalled();
    menuButton.textContent = installed ? '✓ X-Stage ติดตั้งแล้ว' : '⬇ ติดตั้ง X-Stage เป็นแอป';
    menuButton.disabled = installed;
    if(toolsButton){
      toolsButton.textContent = installed ? '✓ ติดตั้งแล้ว' : '⬇ ติดตั้งแอป';
      toolsButton.disabled = installed;
    }
  }
  function information() {
    content.replaceChildren();
    const os = navigator.userAgent || '';
    const ios = /iPad|iPhone|iPod/.test(os) || (/Macintosh/.test(os) && navigator.maxTouchPoints > 1);
    const mac = !ios && /Macintosh|Mac OS X/.test(os);
    const android = /Android/i.test(os);
    const lines = ios
      ? ['เปิดเว็บนี้ใน Safari หรือเบราว์เซอร์ที่รองรับ', 'แตะปุ่มแชร์ (สี่เหลี่ยมพร้อมลูกศรขึ้น) แล้วเลือก “เพิ่มไปยังหน้าจอโฮม” (Add to Home Screen)', 'เลือกเปิดเป็นเว็บแอป (ถ้ามีตัวเลือก) จากนั้นแตะ “เพิ่ม”']
      : android
        ? ['ใน Chrome หรือ Samsung Internet ให้แตะเมนู ⋮', 'เลือก “ติดตั้งแอป” หรือ “เพิ่มไปยังหน้าจอหลัก” แล้วกดยืนยัน', 'หากไม่มีเมนูดังกล่าว ลองเปิดเว็บด้วย Chrome รุ่นล่าสุด']
        : mac
          ? ['ใน Safari เลือก File → Add to Dock', 'ใน Chrome หรือ Edge เปิดเมนู ⋮ แล้วเลือก Install X-Stage Karaoke หรือ Install page as app']
          : ['ใน Chrome หรือ Microsoft Edge คลิกไอคอนติดตั้งในแถบที่อยู่ หรือเปิดเมนู ⋮', 'เลือก “ติดตั้ง X-Stage Karaoke Online” หรือ “Install page as app” แล้วกดยืนยัน', 'หากเบราว์เซอร์ไม่รองรับ ให้ใช้ตัวเลือกสร้างทางลัดจากเมนูเบราว์เซอร์'];
    const intro=document.createElement('p');
    intro.textContent='เพิ่มไอคอน X-Stage ไว้บน Home Screen หรือ Desktop เพื่อเปิดโปรแกรมได้เหมือนแอป';
    content.append(intro);
    const ol=document.createElement('ol');
    for(const line of lines){const li=document.createElement('li');li.textContent=line;ol.append(li);}
    content.append(ol);
    const note=document.createElement('p');
    note.className='xstage-install-note';
    note.textContent='การติดตั้งไม่คัดลอกเพลงจาก Google Drive มายังอุปกรณ์ และยังต้องใช้อินเทอร์เน็ตเพื่อลงชื่อเข้าใช้และเล่นเพลง';
    content.append(note);
  }
  function showInstructions(){
    if(isInstalled()){updateButtons();return;}
    information();
    if(!dialog.open)dialog.showModal();
  }
  async function install(){
    if(isInstalled()){updateButtons();return;}
    const prompt=deferredPrompt;
    if(!prompt){showInstructions();return;}
    deferredPrompt=null;
    try{
      // Must be invoked directly in the click event before awaiting anything else.
      const didPrompt=prompt.prompt();
      await didPrompt;
      await prompt.userChoice;
    }catch{
      showInstructions();
    }
    updateButtons();
  }
  menuButton.addEventListener('click',install);
  toolsButton?.addEventListener('click',install);
  closeButton.addEventListener('click',()=>dialog.close());
  dialog.addEventListener('click',e=>{if(e.target===dialog)dialog.close();});
  window.addEventListener('beforeinstallprompt',e=>{
    e.preventDefault();
    deferredPrompt=e;
    updateButtons();
  });
  window.addEventListener('appinstalled',()=>{
    deferredPrompt=null;
    updateButtons();
    if(dialog.open)dialog.close();
  });
  updateButtons();
})();