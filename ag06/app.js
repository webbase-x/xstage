import {AG06AudioEngine} from "./audio-engine.js";
import {DEFAULT_PRESET,PRESETS,sanitizeParams,formatParam} from "./presets.js";

const $=(id)=>document.getElementById(id);
const engine=new AG06AudioEngine();
const settingsKey="xstage-ag06-studio-v1";
let settings={preset:DEFAULT_PRESET,params:{...PRESETS[DEFAULT_PRESET]}};
try{
  const saved=JSON.parse(localStorage.getItem(settingsKey)||"null");
  if(saved&&typeof saved==="object"&&saved.params){
    settings={preset:PRESETS[saved.preset]?saved.preset:"custom",params:sanitizeParams(saved.params)};
  }
}catch{}
let latestBlob=null,latestUrl=null,recordTimer=null,busy=false;
const setStatus=(message,error=false)=>{const el=$("status-message");el.textContent=message;el.style.color=error?"#ffafaf":"#91e7d0";};
function persist(){try{localStorage.setItem(settingsKey,JSON.stringify(settings));}catch{}}
function renderParams(){
  document.querySelectorAll("[data-param]").forEach(el=>{
    const key=el.dataset.param;
    el.value=String(settings.params[key]);
    document.querySelector('[data-output="'+key+'"]').textContent=formatParam(key,settings.params[key]);
  });
  document.querySelectorAll("[data-preset]").forEach(button=>{
    button.setAttribute("aria-pressed",String(settings.preset===button.dataset.preset));
  });
  engine.applyParams(settings.params);
}
function changeState(connected){
  $("toggle-audio").textContent=connected?"หยุดรับเสียง":"เริ่มรับเสียง";
  $("connection").classList.toggle("active",connected);
  $("connection").innerHTML=connected?"<i></i>กำลังรับเสียง":"<i></i>ยังไม่เชื่อมต่อเสียง";
  $("record-button").disabled=!connected||!AG06AudioEngine.canRecord();
  $("source-select").disabled=connected;
}
function formatDb(value){
  return value<=-95?"−∞ dBFS":Math.round(value)+" dBFS";
}
function setMeter(id,output,db){
  $(id).style.width=(Math.max(0,Math.min(100,(db+60)/60*100)))+"%";
  $(output).textContent=formatDb(db);
}
engine.onMeter=(left,right)=>{
  setMeter("meter-left","db-left",left);
  setMeter("meter-right","db-right",right);
};
engine.onDisconnected=message=>{
  changeState(false);$("actual-rate").textContent="อุปกรณ์หยุดทำงาน";
  $("monitor-toggle").checked=false;stopTimer();setStatus(message,true);
};
async function refreshDevices(){
  const select=$("source-select"),previous=select.value;
  if(!navigator.mediaDevices?.enumerateDevices){
    setStatus("เบราว์เซอร์นี้ไม่รองรับการค้นหาอุปกรณ์เสียง",true);return;
  }
  try{
    const devices=(await navigator.mediaDevices.enumerateDevices()).filter(d=>d.kind==="audioinput");
    select.replaceChildren(new Option("อุปกรณ์เสียงเริ่มต้น",""));
    devices.forEach((d,i)=>select.add(new Option(d.label||"ไมโครโฟน "+(i+1),d.deviceId)));
    const match=devices.find(d=>/AG0[36]/i.test(d.label));
    select.value=devices.some(d=>d.deviceId===previous)?previous:(match?.deviceId||"");
    setStatus(devices.length?"พบอุปกรณ์เสียง "+devices.length+" รายการ":"ยังไม่มีอุปกรณ์เสียงที่ตรวจพบ");
  }catch(error){setStatus("ตรวจหาอุปกรณ์เสียงไม่สำเร็จ: "+error.message,true);}
}
async function withBusy(work){
  if(busy)return;
  busy=true;$("toggle-audio").disabled=true;$("refresh-devices").disabled=true;
  try{await work();}finally{busy=false;$("toggle-audio").disabled=false;$("refresh-devices").disabled=false;}
}
async function toggleAudio(){
  await withBusy(async()=>{
    if(engine.connected){
      if(engine.recorder)await finishRecording();
      await engine.disconnect();
      changeState(false);
      $("actual-rate").textContent="ยังไม่เริ่มรับเสียง";
      $("monitor-toggle").checked=false;
      setStatus("หยุดรับเสียงแล้ว");
      return;
    }
    setStatus("กำลังขออนุญาตไมโครโฟนและเชื่อมต่ออุปกรณ์…");
    try{
      const result=await engine.connect($("source-select").value);
      changeState(true);
      $("monitor-toggle").checked=false;
      $("actual-rate").textContent=(result.sampleRate/1000)+" kHz · ACTUAL";
      $("input-hint").textContent="กำลังรับเสียงจาก: "+result.label+" · ความละเอียดเสียงจริงขึ้นกับอุปกรณ์และระบบปฏิบัติการ";
      setStatus("เชื่อมต่อรับเสียงสำเร็จ · มอนิเตอร์ลำโพงปิดอยู่");
      await refreshDevices();
    }catch(error){
      changeState(false);
      setStatus("เชื่อมต่อไม่สำเร็จ: "+(error.name==="NotAllowedError"?"โปรดอนุญาตไมโครโฟน":error.message),true);
    }
  });
}
function stopTimer(){
  if(recordTimer)clearInterval(recordTimer);
  recordTimer=null;
}
function formatDuration(seconds){
  return String(Math.floor(seconds/60)).padStart(2,"0")+":"+String(seconds%60).padStart(2,"0");
}
function startTimer(){
  stopTimer();
  recordTimer=setInterval(()=>{
    $("record-timer").textContent=formatDuration(Math.floor((Date.now()-engine.recordingStartedAt)/1000));
  },250);
}
function clearOldRecording(){
  if(latestUrl)URL.revokeObjectURL(latestUrl);
  latestBlob=null;latestUrl=null;
  $("download-recording").hidden=true;
}
async function finishRecording(){
  stopTimer();
  $("record-button").disabled=true;
  try{
    const file=await engine.stopRecording();
    if(!file)return;
    if(!file.blob.size)throw new Error("ไม่พบข้อมูลเสียงที่บันทึก");
    latestBlob=file.blob;
    latestUrl=URL.createObjectURL(file.blob);
    const link=$("download-recording");
    link.href=latestUrl;
    link.download="X-Stage-Audio-"+new Date().toISOString().replace(/[:.]/g,"-")+"."+file.extension;
    link.textContent=window.AG06Android?"บันทึกไฟล์ลง Android":"ดาวน์โหลดไฟล์ "+file.extension.toUpperCase();
    link.hidden=false;
    $("record-info").textContent="บันทึกแล้ว "+(file.blob.size/1024/1024).toFixed(1)+" MB · "+file.type+" · ไฟล์ยังอยู่ในหน่วยความจำจนกดบันทึก";
    setStatus("บันทึกเสียงเสร็จแล้ว เลือกดาวน์โหลดหรือบันทึกลงเครื่อง");
  }catch(error){setStatus("บันทึกไม่สำเร็จ: "+error.message,true);}
  finally{$("record-button").classList.remove("active");$("record-button").textContent="● เริ่มบันทึกเสียง";$("record-button").disabled=!engine.connected;}
}
async function toggleRecording(){
  if(engine.recorder){await finishRecording();return;}
  clearOldRecording();
  try{
    engine.startRecording();
    $("record-button").classList.add("active");
    $("record-button").textContent="■ หยุดบันทึก";
    $("record-timer").textContent="00:00";
    startTimer();
    setStatus("กำลังบันทึกเสียงภายในเครื่อง");
  }catch(error){setStatus("เริ่มบันทึกไม่ได้: "+error.message,true);}
}
async function saveAndroidAudio(event){
  if(!window.AG06Android||!latestBlob)return;
  event.preventDefault();
  // Do not cross the JavaScript bridge with unbounded recordings.
  if(latestBlob.size>24*1024*1024){
    setStatus("ไฟล์ใหญ่กว่า 24 MB: ใช้หน้าเว็บในเบราว์เซอร์เพื่อดาวน์โหลดไฟล์แทน",true);return;
  }
  $("download-recording").textContent="กำลังบันทึกลง Android…";
  try{
    const reader=new FileReader();
    const dataUrl=await new Promise((resolve,reject)=>{
      reader.onload=()=>resolve(reader.result);
      reader.onerror=()=>reject(reader.error);
      reader.readAsDataURL(latestBlob);
    });
    window.AG06Android.saveAudio(dataUrl);
    setStatus("ส่งไฟล์ให้ Android แล้ว กำลังบันทึกลงโฟลเดอร์ Music");
  }catch(error){setStatus("บันทึกลง Android ไม่สำเร็จ: "+error.message,true);}
  finally{$("download-recording").textContent="บันทึกไฟล์ลง Android";}
}
window.AG06SaveResult=(ok,message)=>setStatus(message,!ok);
$("toggle-audio").addEventListener("click",toggleAudio);
$("refresh-devices").addEventListener("click",refreshDevices);
$("record-button").addEventListener("click",toggleRecording);
$("download-recording").addEventListener("click",saveAndroidAudio);
$("monitor-toggle").addEventListener("change",event=>{
  const enabled=event.target.checked;
  engine.setMonitor(enabled);
  setStatus(enabled?"เปิดมอนิเตอร์เสียงแล้ว · โปรดใช้หูฟัง":"ปิดมอนิเตอร์เสียงแล้ว");
});
document.querySelectorAll("[data-preset]").forEach(button=>button.addEventListener("click",()=>{
  const preset=button.dataset.preset;
  settings={preset,params:{...PRESETS[preset]}};
  renderParams();persist();
  setStatus("ใช้พรีเซ็ต "+button.textContent+" (ซอฟต์แวร์)");
}));
document.querySelectorAll("[data-param]").forEach(slider=>slider.addEventListener("input",()=>{
  settings.params[slider.dataset.param]=Number(slider.value);
  settings.preset="custom";
  renderParams();persist();
}));
document.addEventListener("visibilitychange",()=>{if(document.visibilityState==="visible"&&engine.connected)void refreshDevices();});
window.addEventListener("pagehide",()=>{void engine.disconnect();if(latestUrl)URL.revokeObjectURL(latestUrl);});
if(navigator.mediaDevices?.addEventListener)navigator.mediaDevices.addEventListener("devicechange",()=>{if(!engine.connected)void refreshDevices();});
renderParams();
changeState(false);
void refreshDevices();
