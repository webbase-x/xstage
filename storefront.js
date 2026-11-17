"use strict";
// Storefront only. It never initializes a karaoke player or accesses private Drive data.
(function(){
  const REPO="https://github.com/webbase-x/xstage";
  const RELEASES=REPO+"/releases";
  const SHA256=/^[a-f0-9]{64}$/i;
  const deviceGuide=window.XStageDeviceGuide;
  const currentDevice=deviceGuide?deviceGuide.detect(navigator):{kind:"unknown",label:"อุปกรณ์นี้"};
  function suitability(id){return deviceGuide?deviceGuide.forApp(currentDevice,id):{level:"unknown",text:"โปรดตรวจสอบระบบที่รองรับ",target:"ตรวจสอบรายละเอียดอุปกรณ์ที่รองรับ",fallback:[]};}
  function populateDeviceGuide(){
    document.getElementById("device-advice-title").textContent="อุปกรณ์ที่ตรวจพบ: "+currentDevice.label;
    document.getElementById("device-advice-message").textContent=deviceGuide?deviceGuide.overview(currentDevice):"ตรวจสอบอุปกรณ์ที่รองรับในรายละเอียดแต่ละแอป";
    for(const id of Object.keys(appInfo)){
      const tag=document.querySelector('[data-device-app="'+id+'"]');
      if(!tag)continue;
      const item=suitability(id);
      tag.className="device-compat "+item.level;
      tag.textContent=item.level==="supported"?"เหมาะกับอุปกรณ์นี้":item.level==="other"?"ต้องใช้อุปกรณ์อื่น":"ตรวจสอบความเข้ากันได้";
      tag.title=item.text+" · "+item.target;
    }
  }
  function renderDeviceInfo(id){
    const support=suitability(id);
    const label=document.getElementById("detail-device-label");
    const title=document.getElementById("detail-device-title");
    const message=document.getElementById("detail-device-message");
    const target=document.getElementById("detail-device-target");
    const alternatives=document.getElementById("detail-device-alternatives");
    label.className="detail-device-label "+support.level;
    label.textContent=support.level==="supported"?"✓ อุปกรณ์ที่เหมาะสม":support.level==="other"?"! ต้องใช้อุปกรณ์อื่น":"i ตรวจสอบเพิ่มเติม";
    title.textContent="สำหรับ "+currentDevice.label;
    message.textContent=support.text;
    target.textContent="อุปกรณ์ที่แนะนำ: "+support.target;
    alternatives.replaceChildren();
    const names={"karaoke-web":"Karaoke Online","studio-web":"Song Studio Web"};
    if(support.level!=="supported"){
      for(const alt of support.fallback){
        if(alt===id||!appInfo[alt])continue;
        const a=document.createElement("a");a.href="?app="+encodeURIComponent(alt);
        a.textContent="แนะนำ "+(names[alt]||appInfo[alt].title)+" ↗";
        alternatives.appendChild(a);
      }
    }
  }
  const appInfo={
    "karaoke-web":{
      title:"X-Stage Karaoke Online",category:"WEB · KARAOKE",
      subtitle:"ร้องเพลงจากคลังส่วนตัวบนเว็บ",
      description:"เครื่องเล่นคาราโอเกะบนเบราว์เซอร์สำหรับคลังเพลง Google Drive ส่วนตัว พร้อมระบบค้นหา คิวเพลง แสดงเนื้อร้อง และความสามารถเกี่ยวกับ MIDI/SoundFont ตามชนิดไฟล์ที่รองรับ ใช้โดยไม่ต้องติดตั้งโปรแกรม Windows",
      features:["ค้นหาเพลง จัดคิว และแสดงเนื้อร้องแบบสัมพันธ์กับเวลา","รองรับเพลงเสียง วิดีโอ และ MIDI ในรูปแบบที่เบราว์เซอร์รองรับ","เลือก SoundFont สำหรับเพลง MIDI ได้","ใช้ Google Drive เป็นคลังเพลงส่วนตัว ไม่ใช่บริการแจกเพลงสาธารณะ"],
      hero:"คาราโอเกะที่พร้อมไปกับคุณ",blurb:"เวทีส่วนตัวของคุณในหนึ่งแท็บ",preview:"KARAOKE ONLINE · YOUR STAGE",
      type:"web",url:"./karaoke.html",secondary:{label:"เปิดรีโมทเพลงบนมือถือ",url:"./remote.html"},
      note:"เปิดเว็บได้ทันที การใช้คลังเพลงจาก Google Drive ต้องลงชื่อเข้าใช้และอนุญาตสิทธิ์ตามที่ระบบกำหนด"
    },
    "karaoke-pc":{
      title:"X-Stage Karaoke PC",category:"WINDOWS · KARAOKE",
      subtitle:"เวทีคาราโอเกะบนคอมพิวเตอร์ Windows",
      description:"โปรแกรมคาราโอเกะสำหรับ Windows ในโครงการ X-Stage ออกแบบสำหรับจัดการและเล่นคลังเพลงบนคอมพิวเตอร์ รุ่น PC แยกจาก Karaoke Online โดยเฉพาะ",
      features:["ใช้งานคาราโอเกะบนเครื่อง Windows","จัดการการเล่นเพลงและคิวเพลงในโปรแกรม PC","พัฒนาการรองรับไฟล์เพลงและข้อมูลคลังร่วมกับ X-Stage Song Studio","แยกส่วนการทำงานจาก Google Drive ของ Karaoke Online"],
      hero:"เวทีเต็มรูปแบบบน PC",blurb:"คุมเสียงเพลงจากคอมพิวเตอร์ของคุณ",preview:"KARAOKE PC · WINDOWS",
      type:"manifest",manifest:"./downloads/windows-pc-latest.json",
      candidate:{label:"ดูผล Build และไฟล์ทดสอบ Windows",url:"https://github.com/webbase-x/xstage/actions/workflows/build-windows-pc.yml"},
      note:"ดาวน์โหลดได้ต่อเมื่อโครงการเผยแพร่ตัวติดตั้ง Windows ที่ตรวจสอบแล้วเท่านั้น หากยังไม่มี กรุณาดูประกาศที่ GitHub Releases",
      fallback:"ยังไม่มีตัวติดตั้ง Windows ที่ยืนยัน"
    },
    "studio-pc":{
      title:"X-Stage Song Studio PC",category:"WINDOWS · MUSIC TOOLS",
      subtitle:"เครื่องมือเตรียมเพลงและเนื้อร้องบน Windows",
      description:"เครื่องมือจัดการเพลงสำหรับ PC ตั้งแต่ตรวจเพลงซ้ำ แปลง MIDI เป็น XSK หรือ Lyrics JSON จัดการเนื้อร้อง ไปจนถึงส่งออกคลังเพลงให้ระบบคาราโอเกะ X-Stage",
      features:["ตรวจเพลงซ้ำจากข้อมูลไฟล์จริง","สร้าง MIDI to .XSK และ MIDI to Lyrics JSON","จัดการและตรวจแก้เนื้อร้องแบบกลุ่ม","ส่งออกไฟล์เพลงและฐานข้อมูลสำหรับระบบคาราโอเกะ"],
      hero:"สร้างและจัดการเพลงในที่เดียว",blurb:"เปลี่ยนไฟล์ต้นทางเป็นเพลงพร้อมขึ้นเวที",preview:"SONG STUDIO PC · MUSIC WORKFLOW",
      type:"manifest",manifest:"./downloads/song-studio-latest.json",
      note:"ไฟล์ PC Ready เป็น ZIP แบบพกพา (portable) สำหรับ Windows และอาจเป็นรุ่นทดสอบ ไม่ใช่ตัวติดตั้ง EXE กรุณาตรวจหมายเหตุรุ่นและค่า SHA-256 ก่อนใช้งาน",
      fallback:"ยังยืนยันไฟล์ดาวน์โหลด Song Studio PC ไม่ได้"
    },
    "studio-web":{
      title:"X-Stage Song Studio Web",category:"WEB · MUSIC TOOLS",
      subtitle:"ทำงานกับ MIDI และเนื้อร้องผ่านเบราว์เซอร์",
      description:"เครื่องมือเตรียมไฟล์เพลงและเนื้อร้องในเว็บ ช่วยตรวจและทดลองฟังไฟล์จากอุปกรณ์ รองรับการเลือกไฟล์ MIDI/KAR/NCN และ SoundFont ตามความสามารถของเบราว์เซอร์",
      features:["เลือกเพลงและโฟลเดอร์จากเครื่อง","ตรวจ MIDI/KAR/NCN ก่อนเตรียมไฟล์","ทดลองฟังและทำงานกับ SoundFont บนเว็บ","ส่งออกไฟล์ผลลัพธ์จากงานที่รองรับ โดยไม่จำเป็นต้องอัปโหลดไฟล์ต้นฉบับ"],
      hero:"สตูดิโอที่เปิดใช้ได้ทันที",blurb:"เครื่องมือเพลงในเบราว์เซอร์ของคุณ",preview:"SONG STUDIO WEB · MUSIC TOOLS",
      type:"web",url:"./studio/web.html",secondary:{label:"เปิด Web Control ของ Song Studio",url:"./studio/"},
      note:"การประมวลผลและการรองรับโค้ดเสียงขึ้นกับเบราว์เซอร์และอุปกรณ์ งานบางชนิดต้องใช้ PC Engine"
    },
    "karaoke-android":{
      title:"X-Stage Karaoke Android",category:"ANDROID TV · TABLET",
      subtitle:"คาราโอเกะสำหรับจอทีวีและแท็บเล็ต Android",
      description:"แอปคาราโอเกะ Android สำหรับ Android TV และแท็บเล็ต เข้าสู่เวที X-Stage ผ่านตัวแอป รองรับฟังก์ชันของเวอร์ชันเว็บที่เชื่อมกับแอป และตรวจสอบอัปเดตได้ตามช่องทางของรุ่น",
      features:["ออกแบบสำหรับ Android TV และแท็บเล็ต","เข้าถึงเครื่องเล่นคาราโอเกะในแอป","เชื่อมคลังเพลงส่วนตัวตามขั้นตอนของระบบ","มีช่องทางอัปเดต APK รุ่นทดสอบเมื่อเผยแพร่"],
      hero:"เวทีขนาดใหญ่ในห้องนั่งเล่น",blurb:"ย้ายความสนุกจากเว็บไปสู่ทีวี",preview:"ANDROID TV · TABLET",
      type:"manifest",manifest:"./downloads/android-tv-latest.json",
      note:"APK ที่ให้ดาวน์โหลดเป็นรุ่นทดสอบสำหรับติดตั้งเอง (sideload) ไม่ใช่แอปที่เผยแพร่ผ่าน Google Play ควรตรวจความเข้ากันได้กับอุปกรณ์ก่อนติดตั้ง",
      fallback:"ยังตรวจสอบไฟล์ APK ที่ยืนยันไม่ได้"
    },
    "mirror-tv":{
      title:"X-Stage Mirror TV",category:"ANDROID TV · DISPLAY",
      subtitle:"รับภาพจาก iPhone และ iPad บนจอ Android TV",
      description:"โครงการตัวรับภาพหน้าจอสำหรับ Android TV เพื่อแสดงหน้าจอจาก iPhone หรือ iPad โดยใช้ฟังก์ชัน Screen Mirroring ของ iOS หน้าคู่มือแนะนำการเชื่อมต่อและเงื่อนไขเครือข่าย",
      features:["ใช้การส่งหน้าจอจากเมนู Screen Mirroring ของ iOS","มีคู่มือเชื่อมต่อบนทีวีและการตั้งชื่อตัวรับ","ออกแบบเพื่อรับภาพจากอุปกรณ์ใน Wi-Fi เดียวกัน","การเล่นเนื้อหาบางชนิดอาจถูกจำกัดด้วย DRM และความสามารถของอุปกรณ์"],
      hero:"ให้ทุกหน้าจอมีพื้นที่ของตัวเอง",blurb:"ส่งภาพจากมือถือสู่จอที่ใหญ่กว่า",preview:"MIRROR TV · SCREEN SHARING",
      type:"manifest",manifest:"./mirror-tv/latest.json",testManifest:"./mirror-tv/test-latest.json",secondary:{label:"ดูคู่มือการเชื่อมต่อ",url:"./mirror-tv/"},
      candidate:{label:"ดู APK รุ่นทดสอบใน GitHub Actions",url:"https://github.com/webbase-x/xstage/actions/workflows/build-xstage-mirror-tv.yml"},
      note:"สถานะเผยแพร่ของตัวรับ Mirror TV ตรวจสอบจากประกาศเวอร์ชันของโครงการ การมีคู่มือไม่ได้หมายความว่ามี APK ที่ติดตั้งได้แล้ว",
      fallback:"กำลังเตรียมการเผยแพร่ APK"
    }
  };
  const states={};
  const cards=Array.from(document.querySelectorAll(".app-card"));
  const home=document.getElementById("store-home");
  const detail=document.getElementById("app-detail");
  const detailElements={
    category:document.getElementById("detail-category"),
    title:document.getElementById("detail-title"),
    subtitle:document.getElementById("detail-subtitle"),
    status:document.getElementById("detail-status"),
    icon:document.getElementById("detail-icon"),
    actions:document.getElementById("detail-actions"),
    showcaseTitle:document.getElementById("detail-showcase-title"),
    showcaseCopy:document.getElementById("detail-showcase-copy"),
    preview:document.getElementById("detail-preview"),
    description:document.getElementById("detail-description"),
    features:document.getElementById("detail-features"),
    note:document.getElementById("detail-download-note")
  };
  for(const id of Object.keys(appInfo)){
    states[id]={status:appInfo[id].type==="web"?"พร้อมใช้งาน":"กำลังตรวจสอบไฟล์เผยแพร่",available:appInfo[id].type==="web",url:appInfo[id].url||"",version:"",kind:appInfo[id].type==="web"?"web":"pending"};
  }
  function sameOriginFile(file,folder,pattern){
    return typeof file==="string" && pattern.test(file) ? "./"+folder+"/"+encodeURIComponent(file) : "";
  }
  function verifiedReleaseUrl(value,extension){
    if(typeof value!=="string")return "";
    try{
      const url=new URL(value);
      if(url.protocol!=="https:" || url.hostname!=="github.com" || !url.pathname.startsWith("/webbase-x/xstage/releases/download/") || !url.pathname.toLowerCase().endsWith(extension))return "";
      return url.href;
    }catch{return "";}
  }
  function getRelease(id,data){
    if(!data||typeof data!=="object")throw Error("invalid release data");
    if(id==="studio-pc"){
      const url=data.available===true && SHA256.test(data.sha256||"") ? verifiedReleaseUrl(data.download_url,".zip") : "";
      return url?{available:true,url:url,status:"ZIP รุ่น "+String(data.version||"ล่าสุด")+" · ทดลองใช้งาน",kind:"download",version:String(data.version||"")}:
        {available:false,url:"",status:"ยังไม่มี ZIP รุ่นที่ตรวจสอบได้",kind:"pending"};
    }
    if(id==="karaoke-android"){
      const url=data.available!==false && SHA256.test(data.sha256||"") ? sameOriginFile(data.file,"downloads",/^X-Stage-Karaoke-Android-v\d+\.\d+\.\d+-build\d+\.apk$/) : "";
      return url?{available:true,url:url,status:"APK v"+String(data.version||"ล่าสุด")+" · รุ่นทดสอบ",kind:"download",version:String(data.version||"")}:
        {available:false,url:"",status:"ยังไม่มี APK ที่ตรวจสอบได้",kind:"pending"};
    }
    if(id==="karaoke-pc"){
      const remote=data.installer_published===true||data.available===true;
      const verified=remote && SHA256.test(data.sha256||"");
      const url=verified?verifiedReleaseUrl(data.download_url||data.installer_url,".exe"):"";
      return url?{available:true,url:url,status:"Windows v"+String(data.version||"ล่าสุด"),kind:"download",version:String(data.version||"")}:
        {available:false,url:"",status:"ยังไม่มีตัวติดตั้ง Windows ที่ยืนยัน",kind:"pending"};
    }
    if(id==="mirror-tv"){
      const verified=data.available===true && SHA256.test(data.sha256||"");
      if(verified && data.channel==="test-preview"){
        const url=verifiedReleaseUrl(data.download_url,".apk");
        return url?{available:true,url,status:"APK v"+String(data.version||"ล่าสุด")+" · รุ่นทดสอบ (ไม่ใช่รุ่นลงนามทางการ)",kind:"download",version:String(data.version||""),test:true}:
          {available:false,url:"",status:"ยังไม่มี APK ทดสอบ Mirror TV ที่ตรวจสอบได้",kind:"pending"};
      }
      const releaseUrl=verified && /^X-Stage-Mirror-TV-v\d+\.\d+\.\d+-build\d+\.apk$/.test(data.file||"") && /^\d+\.\d+\.\d+$/.test(data.version||"") && Number.isSafeInteger(data.build)
        ? "https://github.com/webbase-x/xstage/releases/download/xstage-mirror-tv-v"+data.version+"-build"+data.build+"/"+data.file : "";
      const url=verified?verifiedReleaseUrl(data.download_url||releaseUrl,".apk"):"";
      return url?{available:true,url:url,status:"APK v"+String(data.version||"ล่าสุด"),kind:"download",version:String(data.version||"")}:
        {available:false,url:"",status:"ยังไม่มี APK Mirror TV เผยแพร่",kind:"pending"};
    }
    return {available:false,url:"",status:"ยังไม่มีไฟล์เผยแพร่",kind:"pending"};
  }
  function updateCardStatus(id){
    const el=document.querySelector('[data-status="'+id+'"]');
    if(!el)return;
    el.textContent=states[id].status;
    el.classList.toggle("ready",states[id].available);
    el.classList.toggle("pending",!states[id].available);
    if(new URLSearchParams(location.search).get("app")===id)renderDetail(id);
  }
  async function loadLatest(id,manifest){
    try{
      const response=await fetch(manifest,{cache:"no-store",credentials:"omit"});
      if(!response.ok)throw Error("HTTP "+response.status);
      const data=await response.json();
      states[id]=getRelease(id,data);
      if(id==="mirror-tv"&&!states[id].available&&appInfo[id].testManifest){
        try{
          const previewResponse=await fetch(appInfo[id].testManifest,{cache:"no-store",credentials:"omit"});
          if(previewResponse.ok)states[id]=getRelease(id,await previewResponse.json());
        }catch{} // The production signing feed remains authoritative.
      }
    }catch{
      states[id]={available:false,url:"",status:"ตรวจสอบรุ่นล่าสุดไม่ได้",kind:"pending",version:""};
    }
    updateCardStatus(id);
  }
  function createAction(label,url,kind,external){
    const a=document.createElement("a");
    a.className="detail-action "+kind;
    a.textContent=label;
    a.href=url;
    if(external){a.target="_blank";a.rel="noopener noreferrer";}
    return a;
  }
  function renderActions(id){
    const info=appInfo[id],state=states[id],container=detailElements.actions;
    container.replaceChildren();
    if(info.type==="web"){
      container.appendChild(createAction("เข้าสู่เว็บไซต์ ↗",info.url,"primary",false));
    }else if(state.available && state.url){
      const label=id==="studio-pc"?"ดาวน์โหลด ZIP สำหรับ Windows ↗":
        id==="karaoke-pc"?"ดาวน์โหลดตัวติดตั้ง Windows EXE ↗":
        id==="karaoke-android"?"ดาวน์โหลด APK รุ่นทดสอบ ↗":"ดาวน์โหลด APK ↗";
      const support=suitability(id);
      const adjusted=support.level==="other"?"ไฟล์สำหรับอุปกรณ์ที่รองรับ ↗":label;
      container.appendChild(createAction(adjusted,state.url,"primary",!state.url.startsWith("./")));
    }else{
      const pending=document.createElement("span");
      pending.className="detail-action disabled";
      pending.setAttribute("aria-disabled","true");
      pending.textContent="ยังไม่เปิดดาวน์โหลด";
      container.appendChild(pending);
      container.appendChild(createAction("ดูประกาศรุ่นบน GitHub ↗",RELEASES,"secondary",true));
      if(info.candidate){
        container.appendChild(createAction(info.candidate.label+" ↗",info.candidate.url,"secondary",true));
      }
    }
    if(info.secondary){
      container.appendChild(createAction(info.secondary.label+" ↗",info.secondary.url,"secondary",info.secondary.url.startsWith("https://")));
    }
  }
  function renderDetail(id){
    const info=appInfo[id];
    if(!info)return false;
    const state=states[id],card=cards.find(card=>card.dataset.app===id);
    detailElements.category.textContent=info.category;
    detailElements.title.textContent=info.title;
    detailElements.subtitle.textContent=info.subtitle;
    detailElements.status.textContent=state.status;
    detailElements.description.textContent=info.description;
    detailElements.showcaseTitle.textContent=info.hero;
    detailElements.showcaseCopy.textContent=info.blurb;
    detailElements.note.textContent=info.note+(state.kind==="pending"?" · "+state.status:"")+
      (state.test?" · Mirror TV รุ่นทดสอบลงนามด้วยกุญแจ Debug ของ CI; การติดตั้งทับรุ่นก่อนหรือการอัปเดตอัตโนมัติอาจใช้ไม่ได้ ต้องถอนการติดตั้งก่อนหากลายเซ็นไม่ตรงกัน":"");
    renderDeviceInfo(id);
    detailElements.features.replaceChildren();
    for(const feature of info.features){
      const li=document.createElement("li");li.textContent=feature;detailElements.features.appendChild(li);
    }
    detailElements.icon.replaceChildren();
    detailElements.icon.className="detail-app-icon";
    const cardArt=card&&card.querySelector(".app-art");
    if(cardArt){
      for(const cls of cardArt.classList){if(cls!=="app-art")detailElements.icon.classList.add(cls);}
      const icon=cardArt.firstElementChild;
      if(icon)detailElements.icon.appendChild(icon.cloneNode(true));
    }
    const preview=detailElements.preview;
    preview.replaceChildren();
    preview.className="detail-preview";
    if(id.startsWith("studio-"))preview.classList.add("is-studio");
    else if(id==="karaoke-android")preview.classList.add("is-tv");
    else if(id==="mirror-tv")preview.classList.add("is-mirror");
    if(id==="mirror-tv"&&cardArt){
      preview.appendChild(cardArt.firstElementChild.cloneNode(true));
    }else{
      const img=document.createElement("img");
      img.src=({ "karaoke-web":"./assets/xstage-app-icon.svg","karaoke-pc":"./assets/app-icons/karaoke-pc.svg","studio-pc":"./studio/app-icon.svg","studio-web":"./studio/web-app-icon.svg","karaoke-android":"./assets/app-icons/karaoke-android.svg","mirror-tv":"./assets/app-icons/mirror-tv.svg" })[id]||"./assets/xstage-stage-logo.png";
      img.alt="";
      preview.appendChild(img);
    }
    const label=document.createElement("span");label.className="preview-label";label.textContent=info.preview;preview.appendChild(label);
    renderActions(id);
    document.title=info.title+" | X-Stage Apps";
    return true;
  }
  function routeToCurrent(){
    const id=new URLSearchParams(location.search).get("app");
    if(id && renderDetail(id)){
      home.hidden=true;detail.hidden=false;
      window.scrollTo({top:0,behavior:"instant"});
    }else{
      detail.hidden=true;home.hidden=false;
      document.title="X-Stage Apps | เวทีของคุณ เริ่มที่นี่";
    }
  }
  document.addEventListener("click",function(event){
    const anchor=event.target.closest && event.target.closest('a[href^="?app="]');
    if(!anchor || event.defaultPrevented || event.button!==0 || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey)return;
    const target=new URL(anchor.href);
    if(target.origin!==location.origin || target.pathname!==location.pathname)return;
    event.preventDefault();
    history.pushState(null,"",target.pathname+target.search);
    routeToCurrent();
  });
  document.getElementById("detail-back").addEventListener("click",function(event){
    if(event.button!==0 || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey)return;
    event.preventDefault();
    history.pushState(null,"",location.pathname+"#catalog");
    routeToCurrent();
    document.getElementById("catalog").scrollIntoView({block:"start"});
  });
  window.addEventListener("popstate",routeToCurrent);
  const filterButtons=Array.from(document.querySelectorAll("[data-filter]"));
  const search=document.getElementById("app-search");
  let selectedFilter="all";
  function applyFilters(){
    const query=search.value.trim().toLocaleLowerCase("th-TH");
    let visible=0;
    cards.forEach(card=>{
      const cat=card.dataset.category;
      const matches=(selectedFilter==="all"||cat===selectedFilter) && (!query||card.dataset.name.toLocaleLowerCase("th-TH").includes(query));
      card.hidden=!matches;
      if(matches)visible++;
    });
    document.getElementById("catalog-empty").hidden=visible!==0;
  }
  filterButtons.forEach(button=>button.addEventListener("click",function(){
    selectedFilter=button.dataset.filter;
    filterButtons.forEach(other=>{
      const active=other===button;
      other.classList.toggle("active",active);
      other.setAttribute("aria-pressed",String(active));
    });
    applyFilters();
  }));
  search.addEventListener("input",applyFilters);
  populateDeviceGuide();
  routeToCurrent();
  for(const id of Object.keys(appInfo)){
    if(appInfo[id].manifest)loadLatest(id,appInfo[id].manifest);
  }
})();
