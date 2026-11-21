/* Memory-aware X-Stage song queue. Estimates are deliberately conservative:
 * deviceMemory is a coarse hint, and performance.memory is V8 heap only.
 * Never display an invented system-free-RAM figure.
 */
(function(scope){
'use strict';
const MiB=1048576;
const fmt=bytes=>(Math.max(0,Number(bytes)||0)/MiB).toFixed(1)+' MB';
const clamp=(n,low,high)=>Math.max(low,Math.min(high,n));
function deviceHint(){
  const n=Number(scope.navigator?.deviceMemory);
  if(Number.isFinite(n)&&n>=0.25)return {gib:n,source:'browser hint'};
  const mobile=/Android|iPhone|iPad|Mobile/i.test(scope.navigator?.userAgent||'');
  // Fallback is a policy tier, NOT a claim about physical installed RAM.
  return {gib:mobile?2:4,source:'conservative fallback'};
}
function nativeRam(){
  try{
    const raw=scope.XStageAndroid?.memorySnapshot?.();
    if(typeof raw!=='string'||!raw)return null;
    const info=JSON.parse(raw);
    const total=Number(info.total),available=Number(info.available),
      threshold=Number(info.threshold);
    if(!Number.isFinite(total)||!Number.isFinite(available)||total<128*MiB||
       available<0||available>total)return null;
    return {total,available,threshold:Number.isFinite(threshold)?threshold:0,
      lowMemory:info.lowMemory===true,source:'Android system'};
  }catch{return null;}
}
function heap(){
  const m=scope.performance?.memory;
  if(m&&Number.isFinite(m.usedJSHeapSize)&&Number.isFinite(m.jsHeapSizeLimit)&&m.jsHeapSizeLimit>0)
    return {used:m.usedJSHeapSize,limit:m.jsHeapSizeLimit,ratio:m.usedJSHeapSize/m.jsHeapSizeLimit};
  return null;
}
function plan({fontBytes=0,queuedBytes=0,activeBytes=0,extraBytes=0}={}){
  const native=nativeRam(),hint=native?
    {gib:native.total/1024/1024/1024,source:'Android system'}:deviceHint();
  const h=heap();
  const low=hint.gib<=2;
  // Limit speculative queue media independently from the actively playing
  // song and essential SoundFont. The budget protects a large RAM reserve.
  const nominal=clamp(Math.floor(hint.gib*MiB*1024*.025),12*MiB,128*MiB);
  // Native Android's actual available RAM is authoritative; keep at least
  // 94% as a reserve for the system, media codecs and other applications.
  const base=native?Math.max(6*MiB,Math.min(nominal,Math.floor(native.available*.06))):nominal;
  const fontReserve=Math.min(Math.max(0,fontBytes)*1.35,base*.75);
  const activeReserve=Math.min(Math.max(0,activeBytes)*.22,base*.65);
  const budget=Math.max(6*MiB,base-fontReserve-activeReserve);
  const occupied=Math.max(0,queuedBytes)+Math.max(0,extraBytes);
  const ratio=occupied/budget;
  const heapPressure=!!h&&h.ratio>=.78;
  const nativePressure=!!native&&
    (native.lowMemory||native.available<=Math.max(native.threshold,384*MiB));
  const level=heapPressure||nativePressure||ratio>=.83?'high':
    ratio>=.58||!!native&&native.available/native.total<.25?'medium':'low';
  // Preload exactly ONE upcoming song, never a speculative backlog.
  // Low-memory devices may still skip preparation to protect playback.
  const queueLimit=1;
  return {budget,occupied,remaining:Math.max(0,budget-occupied),
    ratio,level,queueLimit,heapPressure, nativePressure,
    hint,heap:h,native,fontBytes,activeBytes};
}
function canHold(bytes,resources){
  const n=Number(bytes);
  if(!Number.isFinite(n)||n<=0)return false;
  const p=plan(resources);
  // Leave a full 15% of speculative budget uncommitted.
  return !p.heapPressure&&!p.nativePressure&&n<=Math.max(0,p.budget*.85-p.occupied);
}
function statusText(resources){
  const p=plan(resources);
  const label=p.level==='high'?'สูง · หยุดเตรียมเพิ่ม':p.level==='medium'?
    'ปานกลาง · จำกัดการโหลด':'ปกติ';
  return {level:p.level,text:'คิว '+fmt(p.occupied)+' / งบเตรียม '+fmt(p.budget)+
    ' · '+label,ratio:p.ratio,queueLimit:p.queueLimit,
    note:'เป็นงบแคชประมาณการ ไม่ใช่ RAM ว่างจริง'};
}
scope.XStageMemory={MiB,fmt,plan,canHold,statusText,heap,deviceHint,nativeRam};
})(typeof window!=='undefined'?window:globalThis);
