"use strict";
/* Public, heuristic device guidance only. No tracking, fingerprinting, or network calls.
 * Detection is intentionally conservative; a user can still view every app/download.
 */
(function(root){
  const NAME={
    windows:"Windows PC",mac:"Mac",ios:"iPhone / iPad",
    android_tv:"Android TV / Google TV",android_tablet:"แท็บเล็ต Android",
    android_phone:"โทรศัพท์ Android",android:"อุปกรณ์ Android",
    linux:"Linux PC",unknown:"อุปกรณ์นี้"
  };
  function detect(nav){
    const n=nav||{};
    const ua=String(n.userAgent||"");
    const platform=String(n.userAgentData?.platform||n.platform||"");
    const touch=Number(n.maxTouchPoints)||0;
    let kind="unknown";
    if(/Android/i.test(ua)||/Android/i.test(platform)){
      if(/Android[ ._-]?TV|Google[ ._-]?TV|AFT[A-Z0-9-]*|BRAVIA|SHIELD.Android.TV|Smart.TV|Leanback|TrueID[ ._-]?(?:TV|Box)|True[ ._-]?ID[ ._-]?TV/i.test(ua))kind="android_tv";
      else if(/\bMobile\b/i.test(ua))kind="android_phone";
      else kind="android_tablet";
    }else if(/iPhone|iPad|iPod/i.test(ua)||/iOS/i.test(platform)||(/MacIntel/i.test(platform)&&touch>1)){
      kind="ios";
    }else if(/Windows|Win32|Win64/i.test(platform+" "+ua))kind="windows";
    else if(/Macintosh|MacIntel|macOS/i.test(platform+" "+ua))kind="mac";
    else if(/Linux|X11/i.test(platform+" "+ua))kind="linux";
    return {kind,label:NAME[kind],certain:kind!=="unknown"};
  }
  const catalog={
    "apps-portal":{target:"มือถือและแท็บเล็ต Android, Android TV / Google TV ที่มี WebView และเบราว์เซอร์",fallback:["karaoke-web"]},
    "karaoke-web":{target:"เว็บเบราว์เซอร์สมัยใหม่บน iPhone, iPad, Android, Windows หรือ Mac",fallback:[]},
    "karaoke-pc":{target:"คอมพิวเตอร์ Windows 10/11 แบบ x64",fallback:["karaoke-web"]},
    "download-manager":{target:"Windows 10/11 x64 สำหรับดาวน์โหลดไฟล์ HTTP/HTTPS",fallback:["karaoke-web"]},
    "ag06-studio":{target:"เว็บสมัยใหม่ที่รองรับไมโครโฟน หรือ Windows 10/11 x64 และ Android 10+ ที่รองรับ USB Audio",fallback:[]},
    "studio-pro":{target:"คอมพิวเตอร์ Windows 10/11 x64 (EXE Pro Preview)",fallback:["karaoke-web"]},
    "karaoke-android":{target:"Android TV, Google TV หรือแท็บเล็ต Android (APK สำหรับติดตั้งเอง)",fallback:["karaoke-web"]},
    "file-share":{target:"โทรศัพท์ แท็บเล็ต Android 6+ หรือ Android TV ที่รองรับสำหรับติดตั้ง APK; เครื่องอื่นใช้เว็บเบราว์เซอร์",fallback:["karaoke-web"]},
    "mirror-pc":{target:"Windows 10/11 x64 โดย iOS ใช้ AirPlay และ Android ต้องรองรับ Miracast พร้อม Windows Wireless Display",fallback:["mirror-tv"]},
    "mirror-ios-pc":{target:"Windows 10/11 x64 · AirPlay สำหรับ iPhone/iPad · ตั้งชื่อ X-Stage Mirror PC No.XXXX",fallback:["mirror-tv"]},
    "mirror-android-pc":{target:"Windows 10/11 x64 · Windows Wireless Display/Miracast ที่มีไดรเวอร์รองรับ",fallback:["mirror-ios-pc"]},
    "mirror-tv":{target:"กล่องหรือทีวี Android TV / Google TV สำหรับติดตั้งแอปตัวรับ; iPhone/iPad เป็นอุปกรณ์ส่งภาพ",fallback:["karaoke-web"]}
  };
  function forApp(profile,id){
    const p=profile||{kind:"unknown",label:NAME.unknown};
    const info=catalog[id];
    if(!info)return {level:"unknown",text:"ยังไม่ทราบแพลตฟอร์มที่รองรับ",target:"",fallback:[]};
    const kind=p.kind,web=id==="karaoke-web";
    if(id==="ag06-studio")return {level:"unknown",text:"เว็บใช้งานได้เมื่ออนุญาตไมโครโฟน ส่วน AG06 ผ่าน USB ต้องให้ระบบรู้จักอุปกรณ์ก่อน และ EXE/APK ยังเป็น Preview",target:info.target,fallback:[]};
    if(web){
      return {level:"supported",text:"เปิดเว็บไซต์บนอุปกรณ์นี้ได้",target:info.target,fallback:info.fallback};
    }
    if(id==="karaoke-pc"||id==="studio-pro"||id==="download-manager"||id==="mirror-pc"||id==="mirror-ios-pc"||id==="mirror-android-pc"){
      return {level:kind==="windows"?"supported":kind==="unknown"?"unknown":"other",
        text:kind==="windows"?"ใช้งานบน Windows นี้ได้ หากเป็นรุ่น x64 และตรงตามข้อกำหนด":kind==="unknown"?"ตรวจสอบว่าเป็น Windows x64 ก่อนติดตั้ง":"รุ่นนี้ติดตั้งได้บน Windows x64 เท่านั้น",
        target:info.target,fallback:info.fallback};
    }
    if(id==="karaoke-android"){
      const yes=kind==="android_tv"||kind==="android_tablet";
      const maybe=kind==="android_phone"||kind==="android"||kind==="unknown";
      return {level:yes?"supported":maybe?"unknown":"other",
        text:yes?"เป็นอุปกรณ์ Android ที่เหมาะกับรุ่นนี้ โปรดตรวจสอบเวอร์ชันระบบก่อนติดตั้ง":maybe?"แนะนำ Android TV / Google TV หรือแท็บเล็ต Android; อุปกรณ์นี้อาจไม่เหมาะกับหน้าจอแอป":"ต้องติดตั้ง APK บน Android TV / Google TV หรือแท็บเล็ต Android ไม่ใช่ iOS/Windows/Mac",
        target:info.target,fallback:info.fallback};
    }
    if(id==="file-share"){
      const android=["android_tv","android_tablet","android_phone","android"].includes(kind);
      return {level:android?"supported":kind==="unknown"?"unknown":"other",
        text:android?"อุปกรณ์ Android นี้อาจติดตั้ง APK ตัวรับ–ส่งได้ โปรดตรวจ Android 6+ และทดสอบบนเครื่องจริง":kind==="unknown"?"ตรวจสอบว่าเครื่องหลักเป็น Android ที่ติดตั้ง APK ได้":"เครื่องนี้เปิดเว็บเพื่อรับ–ส่งไฟล์กับอุปกรณ์ Android ได้ แต่ไม่ใช่เครื่องที่ติดตั้ง APK ตัวหลัก",
        target:info.target,fallback:info.fallback};
    }
    if(id==="mirror-tv"){
      const yes=kind==="android_tv",other=kind==="ios"||kind==="windows"||kind==="mac"||kind==="linux";
      return {level:yes?"supported":other?"other":"unknown",
        text:yes?"อุปกรณ์นี้อาจติดตั้งตัวรับ Mirror TV ได้ เมื่อรองรับ APK และระบบที่กำหนด":
          kind==="ios"?"iPhone/iPad ใช้ส่งภาพได้ แต่ต้องติดตั้งแอปตัวรับบน Android TV / Google TV":
          other?"ต้องติดตั้งตัวรับบน Android TV / Google TV ส่วนเครื่องนี้ใช้เป็นตัวส่งหรือดูคู่มือได้":
          "แอปตัวรับออกแบบสำหรับ Android TV / Google TV; โทรศัพท์ Android ไม่ใช่อุปกรณ์เป้าหมาย",
        target:info.target,fallback:info.fallback};
    }
    return {level:"unknown",text:"ตรวจสอบความเข้ากันได้ก่อนติดตั้ง",target:info.target,fallback:info.fallback};
  }
  function overview(profile){
    const kind=profile.kind;
    if(kind==="ios")return "แนะนำ Karaoke Online บนอุปกรณ์นี้ ส่วน APK ต้องติดตั้งบน Android TV/Google TV และโปรแกรม PC ต้องใช้ Windows x64";
    if(kind==="windows")return "ใช้งานแอปเว็บและโปรแกรม PC บนอุปกรณ์นี้ได้ ส่วน Karaoke Android และ Mirror TV ต้องติดตั้งบน Android TV/Google TV หรือแท็บเล็ตที่รองรับ";
    if(kind==="mac"||kind==="linux")return "แนะนำ Karaoke Online บนเบราว์เซอร์ โปรแกรม PC ต้องใช้ Windows x64 และ APK ต้องใช้อุปกรณ์ Android ที่รองรับ";
    if(kind==="android_phone")return "แนะนำแอป Web สำหรับโทรศัพท์นี้ แอป Karaoke Android เหมาะกับแท็บเล็ตหรือ Android TV มากกว่า และ Mirror TV เป็นตัวรับสำหรับทีวี";
    if(kind==="android_tv")return "แนะนำ Karaoke Android และ Mirror TV บนทีวีนี้ โปรแกรม PC ต้องใช้ Windows x64 ส่วนแอป Web ขึ้นกับความสามารถของเบราว์เซอร์ทีวี";
    if(kind==="android_tablet")return "แนะนำ Karaoke Android หรือแอป Web บนแท็บเล็ตนี้ ส่วน Mirror TV เป็นแอปตัวรับสำหรับ Android TV/Google TV";
    return "ยังระบุอุปกรณ์ไม่ได้แน่ชัด เลือกดูรายละเอียดแต่ละแอปเพื่อทราบระบบที่รองรับก่อนติดตั้ง";
  }
  const api=Object.freeze({detect,forApp,overview,catalog});
  if(typeof module!=="undefined"&&module.exports)module.exports=api;
  if(root)root.XStageDeviceGuide=api;
})(typeof window!=="undefined"?window:null);
