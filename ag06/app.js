import {AG06AudioEngine} from "./audio-engine.js";
import {StudioSession,clamp} from "./studio-session.js";
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
const studio=new StudioSession();
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
  $("studio-add-take").disabled=true;
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
    $("studio-add-take").disabled=false;
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
window.addEventListener("pagehide",()=>{studio.stop();void engine.disconnect();if(latestUrl)URL.revokeObjectURL(latestUrl);});
if(navigator.mediaDevices?.addEventListener)navigator.mediaDevices.addEventListener("devicechange",()=>{if(!engine.connected)void refreshDevices();});
// All track editing and bounce operations are local, never sent to a server.
const studioStatus=(message,error=false)=>{const el=$("studio-state");el.textContent=message;el.style.color=error?"#ffafaf":"#95a6ba";};
function studioRender(){
 const root=$("studio-tracks");root.replaceChildren();
 if(!studio.tracks.length){const p=document.createElement("p");p.className="subtle-text";p.textContent="ยังไม่มีแทร็ก · เริ่มจากนำเข้าไฟล์เสียง";root.append(p);return;}
 for(const track of studio.tracks){
  const item=document.createElement("div");item.className="studio-track";
  const title=document.createElement("strong");title.textContent=track.name+" · "+track.buffer.duration.toFixed(1)+" วินาที";item.append(title);
  const controls=document.createElement("div");controls.className="studio-controls";
  const number=(label,key,min,max,step)=>{
   const wrap=document.createElement("label");wrap.textContent=label;
   const field=document.createElement("input");field.type="number";field.min=min;field.max=max;field.step=step;field.value=track[key];
   field.setAttribute("aria-label",label+" "+track.name);
   field.addEventListener("change",()=>{const v=clamp(field.value,+min,+max);track[key]=key==="start"?Math.min(v,track.end-.01):key==="end"?Math.max(v,track.start+.01):v;field.value=track[key];studio.stop();});
   wrap.append(field);controls.append(wrap);
  };
  number("Volume","volume",0,2,.1);number("Start (s)","start",0,track.buffer.duration,.1);
  number("End (s)","end",.01,track.buffer.duration,.1);number("Offset (s)","offset",0,600,.1);
  for(const [key,label] of [["mute","Mute"],["solo","Solo"]]){
   const wrap=document.createElement("label");wrap.className="studio-check";
   const check=document.createElement("input");check.type="checkbox";check.checked=track[key];
   check.addEventListener("change",()=>{track[key]=check.checked;studio.stop();});
   wrap.append(check,document.createTextNode(label));controls.append(wrap);
  }
  const remove=document.createElement("button");remove.type="button";remove.className="button subtle";remove.textContent="ลบแทร็ก";
  remove.addEventListener("click",()=>{studio.stop();studio.remove(track.id);studioRender();});
  controls.append(remove);item.append(controls);root.append(item);
 }
}
async function studioImport(files){
 studio.stop();
 for(const file of files){
  try{studioStatus("กำลังอ่านไฟล์ "+file.name+"…");await studio.addFile(file);}
  catch(error){studioStatus("ข้าม "+file.name+": "+error.message,true);}
  studioRender();
 }
 if(studio.tracks.length)studioStatus("พร้อมมิกซ์ "+studio.tracks.length+" แทร็ก · "+studio.duration().toFixed(1)+" วินาที");
}
$("studio-files").addEventListener("change",async e=>{await studioImport([...e.target.files]);e.target.value="";});
$("studio-add-take").addEventListener("click",async()=>{
 if(!latestBlob)return;
 await studioImport([new File([latestBlob],"Recorded take."+("webm"),{type:latestBlob.type})]);
});
$("studio-play").addEventListener("click",async()=>{
 try{studioStatus("กำลังเล่นมิกซ์…");await studio.play();}
 catch(e){studioStatus("เล่นไม่สำเร็จ: "+e.message,true);}
});
$("studio-stop").addEventListener("click",()=>{studio.stop();studioStatus("หยุดเล่นแล้ว");});
$("studio-export").addEventListener("click",async()=>{
 const button=$("studio-export");button.disabled=true;studio.stop();
 try{
  studioStatus("กำลังเรนเดอร์ WAV ในเครื่อง…");
  const wav=await studio.bounce(),url=URL.createObjectURL(wav),link=document.createElement("a");
  link.href=url;link.download="X-Stage-Audio-Mix-"+new Date().toISOString().slice(0,19).replace(/:/g,"-")+".wav";
  document.body.append(link);link.click();link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),60000);
  studioStatus("ส่งออก WAV สำเร็จ · "+(wav.size/1048576).toFixed(1)+" MB");
 }catch(e){studioStatus("ส่งออกไม่สำเร็จ: "+e.message,true);}
 finally{button.disabled=false;}
});
renderParams();
changeState(false);
void refreshDevices();
