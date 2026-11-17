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
      type:"manifest",manifest:"./downloads/windows-pc-latest.json",previewManifest:"./downloads/windows-pc-preview-latest.json",
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
    "file-share":{
      title:"X-Stage File Share",category:"ANDROID · FILE TRANSFER",
      subtitle:"รับ–ส่งไฟล์ผ่าน LAN และอินเทอร์เน็ตโดยเลือกเส้นทางให้อัตโนมัติ",
      description:"ติดตั้ง APK บนอุปกรณ์ Android เพื่อให้เครื่องอื่นสแกน QR เปิดเบราว์เซอร์แล้วรับ–ส่งไฟล์ได้ รองรับหลายอุปกรณ์พร้อมกัน ไฟล์ที่ได้รับยังอยู่ในเครื่อง Android โดยไม่ต้องพึ่ง Cloud สำหรับการรับ–ส่งผ่าน LAN ส่วนการเชื่อมต่อ Internet ใช้ WebRTC แบบทดลองและอาจไม่สำเร็จในบางเครือข่าย",
      features:["Android เป็นเครื่องหลัก: รับไฟล์เป็นค่าเริ่มต้น หรือเปลี่ยนเป็นส่งไฟล์","QR เปิดหน้าเบราว์เซอร์สำหรับผู้ร่วมใช้โดยไม่ต้องติดตั้งแอป","ใช้งานใน LAN ได้โดยไม่ต้องมีอินเทอร์เน็ต และหลายเครื่องเชื่อมต่อได้","Internet P2P (Preview): เชื่อมต่อข้ามเครือข่ายเมื่อสภาพแวดล้อมรองรับ; ยังไม่มี TURN relay","แสดงประวัติและเปิดไฟล์ที่ยังอยู่ใน Android ด้วยแอปที่ติดตั้งไว้"],
      hero:"ส่งไฟล์ถึงกัน ไม่ว่าจะอยู่ใกล้หรือไกล",blurb:"หนึ่งแอป Android หลายเบราว์เซอร์ เชื่อมต่อด้วย QR",preview:"FILE SHARE · LAN & INTERNET",
      type:"manifest",manifest:"./downloads/file-share-latest.json",secondary:{label:"เปิดหน้าเชื่อมต่อผ่าน Internet (Preview)",url:"./file-share/"},
      note:"APK นี้เป็นรุ่น Preview สำหรับติดตั้งเอง ยังต้องทดสอบกับอุปกรณ์จริง โดย Internet P2P อาจล้มเหลวบนเครือข่ายที่ต้องพึ่ง TURN; หน้าเว็บ Internet ไม่ใช่เซิร์ฟเวอร์เก็บไฟล์ การรับ–ส่งผ่าน LAN ใช้งานได้โดยไม่ต้องเชื่อมอินเทอร์เน็ต",
      fallback:"ยังไม่มีไฟล์ APK X-Stage File Share ที่ตรวจสอบได้"
    },
    "mirror-pc":{
      title:"X-Stage Mirror PC",category:"WINDOWS · DISPLAY",
      subtitle:"รับภาพจาก iPhone/iPad และ Android บน Windows 10/11",
      description:"แอปควบคุมตัวรับภาพบน Windows ที่รวมทางเข้า AirPlay จาก iOS และ Wireless Display/Miracast จาก Android ในหน้าต่างเดียวกัน ตัวรับ AirPlay ใช้ UxPlay แบบพกพาที่แพ็กมาพร้อมรุ่นติดตั้ง ส่วน Android ใช้คุณสมบัติรับภาพของ Windows และต้องรองรับ Miracast ไม่ใช่ Google Cast อย่างเดียว",
      features:["iOS ไม่ต้องติดตั้งแอปบนโทรศัพท์ ใช้ Screen Mirroring ผ่าน AirPlay","Android ใช้การแคสต์ผ่าน Miracast บนเครื่องและไดรเวอร์ที่รองรับ","ตั้งชื่อ AirPlay และควบคุมเริ่ม/หยุดตัวรับจากหน้าเดียว","Windows 10/11 x64; ตัวรับภาพจริงใช้หน้าต่างของ AirPlay/Windows","โหมด LAN ไม่ต้องใช้อินเทอร์เน็ต; ไม่มี cloud relay"],
      hero:"รับทุกหน้าจอในห้องเดียวกัน",blurb:"สะท้อนจากมือถือสู่ Windows ได้อย่างเหมาะสม",preview:"MIRROR PC · IOS & ANDROID",
      type:"manifest",manifest:"./downloads/mirror-pc-latest.json",previewManifest:"./downloads/mirror-pc-preview-latest.json",
      candidate:{label:"ดูซอร์สและผล Build รุ่นพัฒนา",url:"https://github.com/webbase-x/xstage/actions/workflows/build-xstage-mirror-pc.yml"},
      note:"Setup EXE แบบออฟไลน์รวมโปรแกรม .NET, AirPlay Engine, DLL และ Bonjour Service ไว้ครบในชุดเดียว ไม่ต้องดาวน์โหลดส่วนประกอบเพิ่มหลังติดตั้ง (Windows อาจขอสิทธิ์ Administrator สำหรับ Bonjour) รุ่น Preview ยังไม่ได้ทดสอบบนอุปกรณ์จริง และการรับ Android ยังต้องอาศัย Miracast ที่รองรับใน Windows/อุปกรณ์ส่ง",
      fallback:"ยังไม่มี Windows Mirror PC ที่ทดสอบแล้ว"
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
      if(data.channel==="preview"){
        const valid=data.available===true&&SHA256.test(data.sha256||"")&&/^X-Stage-Karaoke-PC-Windows-v\d+\.\d+\.\d+-build\d+\.exe$/.test(data.installer_file||"");
        const sourceOk=data.download_url==="https://webbase-x.github.io/xstage/downloads/"+data.installer_file;
        const url=valid&&sourceOk?sameOriginFile(data.installer_file,"downloads",/^X-Stage-Karaoke-PC-Windows-v\d+\.\d+\.\d+-build\d+\.exe$/):"";
        return url?{available:true,url,status:"EXE v"+String(data.version||"ล่าสุด")+" · รุ่นทดลอง (ยังไม่ลงนาม)",kind:"download",version:String(data.version||""),preview:true}:
          {available:false,url:"",status:"ยังไม่มี EXE รุ่นทดลองที่ตรวจสอบได้",kind:"pending"};
      }
      const remote=data.installer_published===true||data.available===true;
      const verified=remote && SHA256.test(data.sha256||"");
      const url=verified?verifiedReleaseUrl(data.download_url||data.installer_url,".exe"):"";
      return url?{available:true,url:url,status:"Windows v"+String(data.version||"ล่าสุด"),kind:"download",version:String(data.version||"")}:
        {available:false,url:"",status:"ยังไม่มีตัวติดตั้ง Windows ที่ยืนยัน",kind:"pending"};
    }
    if(id==="mirror-pc"){
      const version=String(data.version||"");
      const build=data.build;
      const preview=data.channel==="preview";
      const prefix="X-Stage-Mirror-PC-v"+version+"-build"+build+"-win-x64-";
      const installer=data.file===prefix+"Setup.exe";
      const portable=data.file===prefix+"CANDIDATE.zip";
      const valid=data.available===true&&/^\d+\.\d+\.\d+$/.test(version)&&
        Number.isSafeInteger(build)&&build>0&&SHA256.test(data.sha256||"")&&
        (installer||portable);
      const expectedUrl=preview?
        "https://github.com/webbase-x/xstage/releases/download/xstage-mirror-pc-v"+
        version+"-build"+build+"-preview/"+data.file:null;
      const url=valid&&(!preview||data.download_url===expectedUrl)?
        verifiedReleaseUrl(data.download_url,installer?".exe":".zip"):"";
      return url?{
        available:true,url,
        status:(installer?"Setup EXE":"Portable ZIP")+" v"+version+" · Build "+build+
          (preview?" · รุ่นทดสอบ":" · รุ่นล่าสุด"),
        kind:"download",version,build,preview,installer
      }:{available:false,url:"",status:"ยังไม่มีตัวติดตั้ง Mirror PC ที่ตรวจสอบแล้ว",kind:"pending"};
    }
    if(id==="file-share"){
      const version=String(data.version||"");
      const expectedFile="X-Stage-File-Share-v"+version+".apk";
      const validVersion=/^\d+\.\d+\.\d+(?:-preview\.\d+)?$/.test(version);
      const file=String(data.file||"");
      const valid=data.available===true&&validVersion&&file===expectedFile&&SHA256.test(data.sha256||"");
      const expectedUrl="https://github.com/webbase-x/xstage/releases/download/xstage-file-share-v"+version+"/"+file;
      const url=valid&&data.download_url===expectedUrl?verifiedReleaseUrl(expectedUrl,".apk"):"";
      return url?{available:true,url,status:"APK v"+version+" · "+(data.channel==="preview"?"รุ่น Preview":"เผยแพร่แล้ว"),kind:"download",version}:
        {available:false,url:"",status:"ยังไม่มี APK File Share ที่ตรวจสอบได้",kind:"pending"};
    }
    if(id==="mirror-tv"){
      const verified=data.available===true && SHA256.test(data.sha256||"");
      if(verified && data.channel==="test-preview"){
        // TrueID / Android TV browsers may block GitHub's redirect or target=_blank.
        // Prefer the exact same-origin binary ONLY after its SHA-256-backed feed is published.
        const directValid=data.direct_download_available===true &&
          data.direct_download_file===data.file &&
          data.direct_download_sha256===data.sha256 &&
          data.direct_download_url==="https://webbase-x.github.io/xstage/downloads/"+data.file;
        const direct=directValid?sameOriginFile(data.file,"downloads",/^X-Stage-Mirror-TV-test-v\d+\.\d+\.\d+-build\d+\.apk$/):"";
        const release=verifiedReleaseUrl(data.download_url,".apk");
        const url=direct||release;
        return url?{available:true,url,status:"APK v"+String(data.version||"ล่าสุด")+
          (direct?" · ดาวน์โหลดตรงสำหรับ Android TV":" · ดาวน์โหลดจาก GitHub")+
          " · รุ่นทดสอบ",kind:"download",version:String(data.version||""),test:true,direct:!!direct,
          releaseUrl:release}:
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
    const state=states[id];
    const release=(state.version&&Number.isSafeInteger(state.build))
      ?' · v'+state.version+' · Build '+state.build : '';
    el.textContent=state.status+release;
    el.classList.toggle("ready",states[id].available);
    el.classList.toggle("pending",!states[id].available);
    const quick=document.querySelector('[data-download-app="'+id+'"]');
    if(quick){
      const available=states[id].available&&!!states[id].url;
      quick.hidden=!available;
      if(available){
        quick.href=states[id].url;
        quick.textContent=id==="mirror-pc"?
          ("⬇ ดาวน์โหลด "+(states[id].installer?"Setup EXE":"ZIP")+" v"+states[id].version+" (Build "+states[id].build+")") :
          (id==="mirror-tv"&&states[id].direct?"⬇ ดาวน์โหลด APK สำหรับ TV":"⬇ ดาวน์โหลด APK รุ่นทดสอบ");
        if(states[id].url.startsWith("./")){
          quick.setAttribute("download",states[id].url.split("/").at(-1));
          quick.removeAttribute("target");
        }else{
          quick.removeAttribute("download");
          quick.target="_blank";
          quick.rel="noopener noreferrer";
        }
      }
    }
    if(new URLSearchParams(location.search).get("app")===id)renderDetail(id);
  }
  async function loadLatest(id,manifest){
    try{
      const response=await fetch(manifest,{cache:"no-store",credentials:"omit"});
      if(!response.ok)throw Error("HTTP "+response.status);
      const data=await response.json();
      states[id]=getRelease(id,data);
      states[id].build=Number.isSafeInteger(data.build)?data.build:
        (Number.isSafeInteger(data.build_code)?data.build_code:null);
      if(id==="karaoke-pc"&&!states[id].available&&appInfo[id].previewManifest){
        try{
          const candidateResponse=await fetch(appInfo[id].previewManifest,{cache:"no-store",credentials:"omit"});
          if(candidateResponse.ok){
            const candidate=await candidateResponse.json();
            states[id]=getRelease(id,candidate);
            states[id].build=Number.isSafeInteger(candidate.build)?candidate.build:null;
          }
        }catch{} // Stable release metadata remains authoritative.
      }
      if(id==="mirror-pc"&&!states[id].available&&appInfo[id].previewManifest){
        try{
          const previewResponse=await fetch(appInfo[id].previewManifest,{cache:"no-store",credentials:"omit"});
          if(previewResponse.ok)states[id]=getRelease(id,await previewResponse.json());
        }catch{} // Never offer a broken or unverified release URL.
      }
      if(id==="mirror-tv"&&!states[id].available&&appInfo[id].testManifest){
        try{
          const previewResponse=await fetch(appInfo[id].testManifest,{cache:"no-store",credentials:"omit"});
          if(previewResponse.ok){
            const preview=await previewResponse.json();
            states[id]=getRelease(id,preview);
            states[id].build=Number.isSafeInteger(preview.build)?preview.build:null;
          }
        }catch{} // The production signing feed remains authoritative.
      }
    }catch{
      // A missing production feed must never hide a verified TEST channel.
      if(id==="mirror-tv"&&appInfo[id].testManifest){
        try{
          const fallback=await fetch(appInfo[id].testManifest,{cache:"no-store",credentials:"omit"});
          if(fallback.ok){
            const preview=await fallback.json();
            states[id]=getRelease(id,preview);
            states[id].build=Number.isSafeInteger(preview.build)?preview.build:null;
          }
          else states[id]={available:false,url:"",status:"ตรวจสอบ APK Mirror TV ไม่ได้",kind:"pending"};
        }catch{
          states[id]={available:false,url:"",status:"ตรวจสอบ APK Mirror TV ไม่ได้",kind:"pending"};
        }
      }else{
        states[id]={available:false,url:"",status:"ตรวจสอบรุ่นล่าสุดไม่ได้",kind:"pending",version:""};
      }
    }
    updateCardStatus(id);
  }
  function createAction(label,url,kind,external){
    const a=document.createElement("a");
    a.className="detail-action "+kind;
    a.textContent=label;
    a.href=url;
    if(external){a.target="_blank";a.rel="noopener noreferrer";}
    if(!external&&/\.apk$/i.test(url))a.setAttribute("download",url.split("/").at(-1));
    return a;
  }
  function renderActions(id){
    const info=appInfo[id],state=states[id],container=detailElements.actions;
    container.replaceChildren();
    if(info.type==="web"){
      container.appendChild(createAction("เข้าสู่เว็บไซต์ ↗",info.url,"primary",false));
    }else if(state.available && state.url){
      const label=id==="studio-pc"?"ดาวน์โหลด ZIP สำหรับ Windows ↗":
        id==="mirror-pc"?(state.installer?"ดาวน์โหลด Setup EXE พร้อมใช้ ↗":"ดาวน์โหลด ZIP รุ่นทดสอบ ↗"):
        id==="karaoke-pc"?"ดาวน์โหลดตัวติดตั้ง Windows EXE ↗":
        id==="karaoke-android"||id==="file-share"?"ดาวน์โหลด APK รุ่นทดสอบ ↗":"ดาวน์โหลด APK ↗";
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
    if(id==="mirror-tv"&&state.test){
      if(state.direct&&state.releaseUrl){
        container.appendChild(createAction("สำรอง: ดาวน์โหลดจาก GitHub ↗",state.releaseUrl,"secondary",true));
      }
      container.appendChild(createAction("ซอร์ส GPLv3 ของตัวรับภาพ ↗",
        "https://github.com/webbase-x/xstage/releases/download/xstage-mirror-tv-test-v0.2.3-build105-6e12e392/X-Stage-Mirror-TV-GPLv3-source.tar.gz","secondary",true));
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
    detailElements.status.textContent=state.status+
      (state.version&&Number.isSafeInteger(state.build)?' · v'+state.version+' · Build '+state.build:'');
    detailElements.description.textContent=info.description;
    detailElements.showcaseTitle.textContent=info.hero;
    detailElements.showcaseCopy.textContent=info.blurb;
    detailElements.note.textContent=info.note+(state.kind==="pending"?" · "+state.status:"")+
      (state.test?" · Mirror TV รุ่นทดสอบลงนามด้วยกุญแจ Debug ของ CI; การติดตั้งทับรุ่นก่อนหรือการอัปเดตอัตโนมัติอาจใช้ไม่ได้ ต้องถอนการติดตั้งก่อนหากลายเซ็นไม่ตรงกัน":"")+
      (state.preview?" · Karaoke PC EXE เป็นรุ่นทดลองที่ผ่าน CI แต่ยังไม่มีลายเซ็นผู้เผยแพร่ที่เชื่อถือได้ และยังไม่ได้ทดสอบติดตั้งด้วยตนเองครบทุกเครื่อง Windows SmartScreen อาจเตือน และไม่ควรใช้เป็นการอัปเดตอัตโนมัติของรุ่นทางการ":"");
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
    else if(id==="mirror-tv"||id==="mirror-pc")preview.classList.add("is-mirror");
    if(id==="mirror-tv"&&cardArt){
      preview.appendChild(cardArt.firstElementChild.cloneNode(true));
    }else{
      const img=document.createElement("img");
      img.src=({ "karaoke-web":"./assets/xstage-app-icon.svg","karaoke-pc":"./assets/app-icons/karaoke-pc.svg","studio-pc":"./studio/app-icon.svg","studio-web":"./studio/web-app-icon.svg","karaoke-android":"./assets/app-icons/karaoke-android.svg","mirror-tv":"./assets/app-icons/mirror-tv.svg","mirror-pc":"./assets/app-icons/mirror-pc.svg","file-share":"./assets/app-icons/file-share.svg" })[id]||"./assets/xstage-stage-logo.png";
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
  for(const [id,url] of Object.entries({
    'karaoke-web':'./version.json',
    'studio-web':'./studio/web-version.json'
  })){
    fetch(url,{cache:'no-store',credentials:'omit'})
      .then(response=>response.ok?response.json():null)
      .then(data=>{
        if(!data||typeof data.version!=='string'||!Number.isSafeInteger(data.build))return;
        states[id].version=data.version;
        states[id].build=data.build;
        updateCardStatus(id);
      }).catch(()=>{});
  }
})();
