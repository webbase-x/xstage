import {validateSuggestion,makePrompt} from './smart-lyrics-ai-core.mjs';
const $=id=>document.getElementById(id);
const button=$('lyric-group-ai-suggest'),status=$('lyric-group-ai-status');
if(button&&status){
  let pending=false,request=0;
  function show(value){status.textContent=value;}
  button.addEventListener('click',async()=>{
    if(pending)return;
    const chosen=[...document.querySelectorAll('#lyric-group-results [data-lyric-group]:checked')];
    if(chosen.length!==1){show('กรุณาเลือกเพียง 1 กลุ่มข้อความที่มีคำผิด (ระบบจะแก้ทุกเพลงในกลุ่มนั้นหลังยืนยัน)');return;}
    const row=chosen[0].closest('.lyric-group-row');
    const source=row?.querySelector('.lyric-group-row-text')?.textContent||'';
    if(!source||source.length>400){show('ข้อความที่เลือกไม่รองรับการตรวจ AI');return;}
    const modelApi=globalThis.LanguageModel;
    if(!modelApi||typeof modelApi.create!=='function'){
      show('เบราว์เซอร์นี้ไม่มีโมเดล AI ภายในเครื่องที่รองรับ · ยังแก้ด้วยตนเองได้ตามปกติ');return;
    }
    const originalId=chosen[0].dataset.lyricGroup,seq=++request;
    let session;
    pending=true;button.disabled=true;show('กำลังตรวจความพร้อมของ AI ภายในเครื่อง...');
    try{
      if(typeof modelApi.availability==='function'){
        const availability=await modelApi.availability();
        if(availability==='unavailable')throw Error('โมเดล AI ใช้งานไม่ได้บนเครื่องหรือเบราว์เซอร์นี้');
        if(availability==='downloadable'||availability==='downloading')
          show('กำลังเตรียมโมเดล AI ภายในเครื่อง (อาจต้องดาวน์โหลดโมเดลของเบราว์เซอร์)');
      }
      session=await modelApi.create();
      const response=await session.prompt(makePrompt(source));
      if(seq!==request)return;
      const stillSelected=[...document.querySelectorAll('#lyric-group-results [data-lyric-group]:checked')];
      if(stillSelected.length!==1||stillSelected[0].dataset.lyricGroup!==originalId)throw Error('รายการที่เลือกเปลี่ยนระหว่างตรวจ');
      const result=validateSuggestion(response,source);
      if(result.status==='unchanged'){show('AI ไม่พบข้อผิดพลาดที่มั่นใจ · คงข้อความเดิม');return;}
      if(result.confidence!=='high'){show('AI เสนอคำแก้แต่ความมั่นใจไม่สูง ('+result.confidence+') · ไม่ใส่ให้อัตโนมัติ: '+result.corrected);return;}
      $('lyric-group-replacement-mode').value='custom';
      $('lyric-group-replacement').value=result.corrected;
      $('lyric-group-replacement').dispatchEvent(new Event('input',{bubbles:true}));
      show('AI เสนอ: '+result.corrected+' · '+result.reason+' · ตรวจตัวอย่างและกด “ตรวจแล้ว แทนที่” เพื่อสำรองและแก้ทั้งกลุ่ม (AI ไม่บันทึกเอง)');
    }catch(error){show('ตรวจ AI ไม่สำเร็จ: '+String(error?.message||error));}
    finally{try{session?.destroy?.();}catch{} pending=false;button.disabled=false;}
  });
}
