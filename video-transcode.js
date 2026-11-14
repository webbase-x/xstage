/* Local-only legacy video normalization for the private X-Stage WEB importer.
 * FFmpeg.wasm is fetched on demand; no Google credentials, Drive URLs, or
 * source media are sent to the engine provider. Unsupported/memory-heavy
 * files are rejected, never catalogued as playable.
 */
(function(scope){
'use strict';
const core=scope.XStageImportCore;
const urls=[
  'https://cdn.jsdelivr.net/npm/@ffmpeg/ffmpeg@0.12.15/dist/esm/index.js',
  'https://cdn.jsdelivr.net/npm/@ffmpeg/ffmpeg@0.12.15/dist/esm/worker.js',
  'https://cdn.jsdelivr.net/npm/@ffmpeg/core@0.12.10/dist/esm/ffmpeg-core.js',
  'https://cdn.jsdelivr.net/npm/@ffmpeg/core@0.12.10/dist/esm/ffmpeg-core.wasm'
];
const LIMIT=192*1024*1024;
let engine=null,pending=null,active=false,objectUrls=[];
const message=error=>String(error?.message||error||'ไม่ทราบสาเหตุ');
function check(signal){
  if(signal?.aborted)throw new DOMException('หยุดงาน','AbortError');
}
async function fetchObjectUrl(url,type){
  const response=await fetch(url,{credentials:'omit',mode:'cors'});
  if(!response.ok)throw Error('โหลด FFmpeg Web Engine ไม่สำเร็จ (HTTP '+response.status+')');
  const data=await response.blob();
  return URL.createObjectURL(new Blob([data],{type}));
}
function dispose(){
  try{engine?.terminate();}catch{}
  engine=null;pending=null;active=false;
  for(const url of objectUrls)URL.revokeObjectURL(url);
  objectUrls=[];
}
async function load(signal,onStatus){
  if(engine)return engine;
  if(!pending){
    pending=(async()=>{
      let instance=null;const temporary=[];
      try{
        onStatus?.('กำลังเตรียม FFmpeg Web Engine สำหรับวิดีโอเก่า…');
        const module=await import(urls[0]);
        instance=new module.FFmpeg();
        const worker=URL.createObjectURL(new Blob(['import "'+urls[1]+'";'],
          {type:'text/javascript'}));
        temporary.push(worker);
        const coreUrl=await fetchObjectUrl(urls[2],'text/javascript');
        temporary.push(coreUrl);
        const wasmUrl=await fetchObjectUrl(urls[3],'application/wasm');
        temporary.push(wasmUrl);
        await instance.load({classWorkerURL:worker,coreURL:coreUrl,wasmURL:wasmUrl});
        engine=instance;objectUrls=temporary;
        return instance;
      }catch(error){
        try{instance?.terminate();}catch{}
        for(const url of temporary)URL.revokeObjectURL(url);
        throw Error('วิดีโอ: เปิด FFmpeg.wasm ไม่สำเร็จ ('+message(error)+') · ลองแปลงด้วย X-Stage Song Studio PC');
      }finally{pending=null;}
    })();
  }
  const instance=await pending;
  check(signal);
  return instance;
}
async function convert(file,{signal,onStatus=()=>{},requireAudio=true}={}){
  if(!core?.needsVideoConversion(file?.name))
    throw Error('วิดีโอ: ชนิดไฟล์นี้ไม่ต้องแปลงด้วยระบบวิดีโอรุ่นเก่า');
  if(!await core.validVideo(file))throw Error('วิดีโอ: หัวไฟล์ไม่ตรงกับนามสกุลหรือไฟล์ไม่สมบูรณ์');
  if(file.size>LIMIT)throw Error('วิดีโอ: ไฟล์เกิน 192 MB สำหรับการแปลงบนเว็บ · ใช้ X-Stage Song Studio PC (FFmpeg ที่รวมมาแล้ว)');
  check(signal);
  if(active)throw Error('วิดีโอ: มีการแปลงอื่นกำลังทำงาน');
  active=true;
  const extension=core.ext(file.name),input='input.'+extension,output='output.mp4';
  let instance=null,progress=null;
  const abort=()=>dispose();
  signal?.addEventListener('abort',abort,{once:true});
  try{
    instance=await load(signal,onStatus);
    check(signal);
    progress=({progress:fraction})=>{
      if(signal?.aborted)return;
      const percent=Math.round(Math.max(0,Math.min(1,Number(fraction)||0))*100);
      onStatus('กำลังแปลงวิดีโอ '+file.name+' · '+percent+'% (ทำงานบนเครื่อง)');
    };
    instance.on('progress',progress);
    onStatus('กำลังอ่าน '+file.name+' เพื่อแปลงเป็น H.264/AAC MP4…');
    await instance.writeFile(input,new Uint8Array(await file.arrayBuffer()));
    check(signal);
    const args=['-hide_banner','-loglevel','error','-y','-i',input,
      '-map','0:v:0',...(requireAudio?['-map','0:a:0']:['-an']),
      '-c:v','libx264','-preset','ultrafast','-crf','25','-pix_fmt','yuv420p',
      ...(requireAudio?['-c:a','aac','-b:a','160k']:[]),
      '-movflags','+faststart',output];
    const rc=await instance.exec(args);
    check(signal);
    if(rc!==0)throw Error('FFmpeg แปลงไม่สำเร็จ (code '+rc+')');
    const bytes=await instance.readFile(output);
    check(signal);
    if(!bytes?.length||bytes.length<1024)throw Error('ผลลัพธ์ MP4 ว่างหรือไม่สมบูรณ์');
    const name=file.name.replace(/\.[^.]+$/,'')+'.mp4';
    return new File([bytes],name,{type:'video/mp4',lastModified:file.lastModified||Date.now()});
  }catch(error){
    if(signal?.aborted)throw new DOMException('หยุดงาน','AbortError');
    if(String(error?.message||'').startsWith('วิดีโอ:'))throw error;
    throw Error('วิดีโอ: แปลง '+file.name+' ไม่สำเร็จ ('+message(error)+') · ลองใช้ Song Studio PC');
  }finally{
    try{if(progress)instance?.off('progress',progress);}catch{}
    try{await instance?.deleteFile(input);}catch{}
    try{await instance?.deleteFile(output);}catch{}
    signal?.removeEventListener('abort',abort);
    active=false;
  }
}
scope.XStageVideoTranscode={convert,dispose,
  needsConversion:name=>!!core?.needsVideoConversion(name),MAX_BYTES:LIMIT};
})(typeof window!=='undefined'?window:globalThis);
