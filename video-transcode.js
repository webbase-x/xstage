/* Web VDO converter: an isolated worker handles untrusted codec libraries.
 * The worker cannot read sessionStorage or the Google Drive OAuth token.
 * Files remain local until a verified MP4 is uploaded by the normal importer.
 */
(function(scope){
'use strict';
const core=scope.XStageImportCore,MAX_BYTES=192*1024*1024;
let activeWorker=null;
function check(signal){if(signal?.aborted)throw new DOMException('หยุดงาน','AbortError');}
function dispose(){
  if(activeWorker){try{activeWorker.terminate();}catch{}activeWorker=null;}
}
async function convert(file,{signal,onStatus=()=>{},requireAudio=true}={}){
  if(!core?.needsVideoConversion(file?.name))
    throw Error('วิดีโอ: ชนิดไฟล์นี้ไม่ต้องแปลงด้วยระบบวิดีโอรุ่นเก่า');
  if(!await core.validVideo(file))throw Error('วิดีโอ: หัวไฟล์ไม่ตรงกับนามสกุลหรือไฟล์ไม่สมบูรณ์');
  if(file.size>MAX_BYTES)throw Error('วิดีโอ: ไฟล์เกิน 192 MB สำหรับการแปลงบนเว็บ · ใช้ X-Stage Song Studio PC (FFmpeg ที่รวมมาแล้ว)');
  check(signal);
  if(activeWorker)throw Error('วิดีโอ: มีการแปลงอื่นกำลังทำงาน');
  if(typeof Worker==='undefined')throw Error('วิดีโอ: เบราว์เซอร์ไม่รองรับ Worker · ใช้ Song Studio PC');
  let worker;
  try{worker=new Worker('./video-transcode-worker.js?v=1101',{type:'module'});}
  catch(error){throw Error('วิดีโอ: เปิด Worker สำหรับแปลงไฟล์ไม่ได้ ('+(error?.message||error)+')');}
  activeWorker=worker;
  try{
    onStatus('กำลังเตรียมไฟล์ '+file.name+' เพื่อแปลงในเครื่อง…');
    const bytes=await file.arrayBuffer();
    check(signal);
    return await new Promise((resolve,reject)=>{
      let done=false;
      const finish=(error,result)=>{
        if(done)return;done=true;
        signal?.removeEventListener('abort',stop);
        worker.terminate();
        if(activeWorker===worker)activeWorker=null;
        if(error)reject(error);else resolve(result);
      };
      const stop=()=>finish(new DOMException('หยุดงาน','AbortError'));
      signal?.addEventListener('abort',stop,{once:true});
      worker.onerror=event=>finish(Error('วิดีโอ: Worker ไม่พร้อม ('+(event.message||'ไม่ทราบสาเหตุ')+')'));
      worker.onmessage=event=>{
        const data=event.data||{};
        if(data.type==='progress'){onStatus(String(data.message||'กำลังแปลงวิดีโอ'));return;}
        if(data.type==='error'){finish(Error('วิดีโอ: '+String(data.message||'แปลงไฟล์ไม่สำเร็จ')));return;}
        if(data.type!=='done')return;
        if(!(data.buffer instanceof ArrayBuffer)||data.buffer.byteLength<1024){
          finish(Error('วิดีโอ: ผลลัพธ์ MP4 ไม่สมบูรณ์'));return;
        }
        const name=file.name.replace(/\.[^.]+$/,'')+'.mp4';
        finish(null,new File([data.buffer],name,{type:'video/mp4',lastModified:file.lastModified||Date.now()}));
      };
      worker.postMessage({type:'convert',buffer:bytes,name:file.name,requireAudio},[bytes]);
    });
  }catch(error){
    dispose();
    if(signal?.aborted||error?.name==='AbortError')throw new DOMException('หยุดงาน','AbortError');
    if(String(error?.message||'').startsWith('วิดีโอ:'))throw error;
    throw Error('วิดีโอ: '+String(error?.message||error)+' · ลองแปลงด้วย Song Studio PC');
  }
}
scope.XStageVideoTranscode={convert,dispose,needsConversion:name=>!!core?.needsVideoConversion(name),MAX_BYTES};
})(typeof window!=='undefined'?window:globalThis);
