/* Optional X-Stage Karaoke Online <-> Windows Core Audio companion.
 * Local Windows consent enables automatic pairing. Tokens remain in memory;
 * no connection to hosts other than loopback.
 */
'use strict';
(function(){
  const BASE='http://127.0.0.1:48731';
  const $=id=>document.getElementById(id);
  const button=$('windows-volume-connect');
  const dialog=$('windows-volume-dialog');
  const pairButton=$('windows-volume-pair');
  const disconnectButton=$('windows-volume-disconnect');
  const closeButton=$('windows-volume-close');
  const status=$('windows-volume-status');
  const slider=$('volume');
  if(!button||!dialog||!slider)return;
  let token='',connected=false,muted=false,level=80,syncing=false;
  let pollTimer=0,activePoll=false,pendingVolume=null,writing=false;
  let currentRequestId=0, pairing=false, autoEnabled=true;

  const clamp=value=>Math.max(0,Math.min(100,Math.round(Number(value)||0)));
  const show=message=>{if(status)status.textContent=message;};
  const broadcast=()=>window.dispatchEvent(new CustomEvent('xstage:windows-volume',
    {detail:{connected,volume:level,muted}}));
  function indicator(){
    button.textContent=connected?'● Win':'↔ Win';
    button.title=connected?'กำลังควบคุมระดับเสียงหลัก Windows':'เชื่อมระดับเสียงหลัก Windows ผ่านโปรแกรมช่วย';
    button.setAttribute('aria-pressed',String(connected));
    button.classList.toggle('is-connected',connected);
    if(disconnectButton)disconnectButton.hidden=!connected;
    if(pairButton)pairButton.disabled=connected;
    broadcast();
  }
  async function request(path,method='GET',payload,authenticate=false){
    const controller=new AbortController();
    const timeout=setTimeout(()=>controller.abort(),2200);
    try{
      const response=await fetch(BASE+path,{
        method,mode:'cors',cache:'no-store',credentials:'omit',
        headers:{...(payload?{'Content-Type':'application/json'}:{}),
          ...(authenticate&&token?{Authorization:'Bearer '+token}:{})},
        ...(payload?{body:JSON.stringify(payload)}:{}),signal:controller.signal
      });
      const data=await response.json();
      if(!response.ok)throw Error(data.error||'Windows volume HTTP '+response.status);
      return data;
    }finally{clearTimeout(timeout);}
  }
  function reflect(data,force=false){
    if(!connected)return;
    level=clamp(data.volume);
    muted=!!data.muted;
    if(force||Number(slider.value)!==level){
      syncing=true;
      try{
        slider.value=String(level);
        slider.dispatchEvent(new Event('input',{bubbles:true}));
      }finally{syncing=false;}
    }
    broadcast();
  }
  function disconnect(reason=''){
    token='';connected=false;muted=false;
    currentRequestId++;pendingVolume=null;writing=false;
    if(pollTimer){clearInterval(pollTimer);pollTimer=0;}
    // Return to independent browser volume without changing Windows volume.
    syncing=true;
    try{slider.dispatchEvent(new Event('input',{bubbles:true}));}
    finally{syncing=false;}
    indicator();
    show(reason||'ยกเลิกการเชื่อมแล้ว · เว็บใช้เสียงของแอปตามปกติ');
  }
  async function poll(){
    if(!connected||activePoll||writing||pendingVolume!==null)return;
    const epoch=currentRequestId;
    activePoll=true;
    try{
      const result=await request('/v1/volume','GET',null,true);
      if(connected&&epoch===currentRequestId)reflect(result);
    }catch(error){
      if(connected&&epoch===currentRequestId)
        disconnect('ไม่สามารถอ่านเสียง Windows ได้ · '+error.message+' · ตรวจว่าโปรแกรมช่วยยังเปิดอยู่');
    }finally{activePoll=false;}
  }
  async function flush(){
    if(!connected||writing)return;
    writing=true;
    const epoch=currentRequestId;
    try{
      while(connected&&epoch===currentRequestId&&pendingVolume!==null){
        const value=pendingVolume;
        pendingVolume=null;
        const result=await request('/v1/volume','PUT',{volume:value},true);
        // Another wheel step arrived while writing: never regress the UI.
        if(pendingVolume===null&&epoch===currentRequestId)reflect(result);
      }
    }catch(error){
      if(connected&&epoch===currentRequestId)
        disconnect('ปรับเสียง Windows ไม่สำเร็จ · '+error.message);
    }finally{
      writing=false;
      if(connected&&pendingVolume!==null)void flush();
    }
  }
  function setVolume(value){
    if(!connected||syncing)return false;
    pendingVolume=clamp(value);
    void flush();
    return true;
  }
  async function toggleMute(){
    if(!connected)return false;
    const epoch=currentRequestId;
    try{
      const result=await request('/v1/mute','PUT',{muted:!muted},true);
      if(connected&&epoch===currentRequestId)reflect(result,true);
    }catch(error){
      if(connected&&epoch===currentRequestId)
        disconnect('ปิด/เปิดเสียง Windows ไม่สำเร็จ · '+error.message);
    }
    return true;
  }
  async function pair(automatic=false){
    if(connected||pairing||(!autoEnabled&&automatic))return;
    pairing=true;
    const epoch=currentRequestId;
    pairButton.disabled=true;
    show('กำลังเชื่อมกับโปรแกรมช่วยบนเครื่องนี้…');
    try{
      const result=await request('/v1/connect','POST',{});
      if(epoch!==currentRequestId||!autoEnabled)return;
      if(!result.token||typeof result.token!=='string')throw Error('ไม่ได้รับโทเค็นที่ตรวจสอบได้');
      token=result.token;connected=true;muted=!!result.muted;
      currentRequestId++;
      const media=$('player');
      if(media?.muted)media.muted=false;
      // The browser media gain must become unity when the displayed slider
      // controls the Windows master, avoiding double attenuation.
      reflect(result,true);
      indicator();
      show('เชื่อมแล้ว · ล้อเมาส์/แถบเสียงควบคุมระดับเสียงหลัก Windows และอ่านค่ากลับทุก 0.5 วินาที');
      if(dialog.open&&dialog.close)dialog.close();
      pollTimer=setInterval(()=>{void poll();},500);
    }catch(error){
      show('เชื่อม Windows ไม่สำเร็จ: '+error.message+
        ' · เปิด XStageWindowsVolumeBridge.exe ก่อน และอนุญาต Local network access หาก Chrome ถาม');
      token='';connected=false;
    }finally{
      pairing=false;
      if(pairButton)pairButton.disabled=connected;
      indicator();
    }
  }
  button.addEventListener('click',()=>{
    if(!dialog.open){if(dialog.showModal)dialog.showModal();else dialog.setAttribute('open','');}
    if(connected)show('เชื่อมกับระดับเสียงหลัก Windows อยู่ · การหมุนล้อเมาส์จะเปลี่ยนเสียงระบบ');
    else show('เปิดโปรแกรมช่วย Windows รุ่นใหม่และอนุญาตครั้งแรก · ไม่ต้องกรอกรหัส');
  });
  pairButton?.addEventListener('click',()=>{autoEnabled=true;void pair();});
  disconnectButton?.addEventListener('click',()=>{autoEnabled=false;disconnect();});
  closeButton?.addEventListener('click',()=>{
    if(dialog.close)dialog.close();else dialog.removeAttribute('open');
  });
  window.addEventListener('pagehide',()=>{
    if(pollTimer)clearInterval(pollTimer);
    pollTimer=0;token='';connected=false;autoEnabled=false;currentRequestId++;
  });
  window.XStageWindowsVolumeBridge={
    get connected(){return connected;},
    get muted(){return muted;},
    get syncing(){return syncing;},
    setVolume,toggleMute,disconnect
  };
  indicator();
  if(/Windows/i.test(navigator.userAgent||'')){
    // Never open a modal automatically; retry only while disconnected.
    void pair(true);
    setInterval(()=>{if(autoEnabled&&!connected)void pair(true);},10000);
  }
})();
