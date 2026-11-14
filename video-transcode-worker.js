/* Dedicated worker for legacy karaoke conversion. No auth state and no
 * access to the X-Stage DOM or Google access token. CDN packages are pinned.
 * An offline-ready PC package is used for files too large for WASM.
 */
const urls=[
  'https://cdn.jsdelivr.net/npm/@ffmpeg/ffmpeg@0.12.15/dist/esm/index.js',
  'https://cdn.jsdelivr.net/npm/@ffmpeg/ffmpeg@0.12.15/dist/esm/worker.js',
  'https://cdn.jsdelivr.net/npm/@ffmpeg/core@0.12.10/dist/esm/ffmpeg-core.js',
  'https://cdn.jsdelivr.net/npm/@ffmpeg/core@0.12.10/dist/esm/ffmpeg-core.wasm'
];
function report(message){postMessage({type:'progress',message});}
async function objectUrl(url,type){
  const response=await fetch(url,{credentials:'omit',mode:'cors'});
  if(!response.ok)throw Error('ดาวน์โหลด FFmpeg Web Engine ไม่สำเร็จ (HTTP '+response.status+')');
  const blob=await response.blob();
  return URL.createObjectURL(new Blob([blob],{type}));
}
self.onmessage=async event=>{
  const data=event.data||{};
  if(data.type!=='convert'||!(data.buffer instanceof ArrayBuffer))return;
  let engine=null;
  const temporary=[];
  try{
    report('กำลังเตรียม FFmpeg.wasm สำหรับ VDO · โหลดอัตโนมัติเมื่อจำเป็น');
    const module=await import(urls[0]);
    engine=new module.FFmpeg();
    const worker=URL.createObjectURL(new Blob(['import "'+urls[1]+'";'],{type:'text/javascript'}));
    temporary.push(worker);
    const coreURL=await objectUrl(urls[2],'text/javascript');temporary.push(coreURL);
    const wasmURL=await objectUrl(urls[3],'application/wasm');temporary.push(wasmURL);
    await engine.load({classWorkerURL:worker,coreURL,wasmURL});
    const extension=String(data.name||'').split('.').pop().toLowerCase();
    if(!/^(avi|mpg|mpeg|dat|vob|wmv|mkv|mov|flv)$/.test(extension))
      throw Error('ชนิดวิดีโอไม่รองรับ');
    const input='input.'+extension,output='output.mp4';
    const progress=({progress:fraction})=>{
      const percent=Math.round(Math.max(0,Math.min(1,Number(fraction)||0))*100);
      report('กำลังแปลงวิดีโอ '+String(data.name||'')+' · '+percent+'%');
    };
    engine.on('progress',progress);
    await engine.writeFile(input,new Uint8Array(data.buffer));
    const requireAudio=data.requireAudio!==false;
    const args=['-hide_banner','-loglevel','error','-y','-i',input,'-map','0:v:0',
      ...(requireAudio?['-map','0:a:0']:['-an']),
      '-c:v','libx264','-preset','ultrafast','-crf','25','-pix_fmt','yuv420p',
      ...(requireAudio?['-c:a','aac','-b:a','160k']:[]),
      '-movflags','+faststart',output];
    const rc=await engine.exec(args);
    if(rc!==0)throw Error('FFmpeg ไม่สามารถอ่านหรือเข้ารหัสวิดีโอนี้ได้ (code '+rc+')');
    const bytes=await engine.readFile(output);
    if(!(bytes instanceof Uint8Array)||bytes.length<1024)
      throw Error('ผลลัพธ์ MP4 ว่างเปล่าหรือไม่สมบูรณ์');
    const result=bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength);
    postMessage({type:'done',buffer:result},[result]);
  }catch(error){
    postMessage({type:'error',message:String(error?.message||error)+' · ลองใช้ Song Studio PC หากแปลงไม่ได้'});
  }finally{
    try{engine?.terminate();}catch{}
    for(const url of temporary)URL.revokeObjectURL(url);
  }
};
