// These values describe LOCAL software effects, never the AG06's internal DSP.
export const DEFAULT_PRESET = "voice";
export const LIMITS = Object.freeze({
  hpf:[20,250], low:[-12,12], mid:[-12,12], high:[-12,12],
  comp:[-36,-6], reverb:[0,60], drive:[0,40], gain:[-18,6]
});
export const PRESETS = Object.freeze({
  voice: Object.freeze({hpf:100,low:-2,mid:2,high:3,comp:-22,reverb:7,drive:0,gain:0}),
  vocal: Object.freeze({hpf:80,low:1,mid:1,high:2,comp:-18,reverb:21,drive:0,gain:0}),
  guitar: Object.freeze({hpf:65,low:2,mid:0,high:2,comp:-16,reverb:12,drive:17,gain:-3}),
  flat: Object.freeze({hpf:20,low:0,mid:0,high:0,comp:-6,reverb:0,drive:0,gain:0})
});
export function sanitizeParams(values={}){
  const base=PRESETS[DEFAULT_PRESET];
  return Object.fromEntries(Object.entries(LIMITS).map(([key,[min,max]])=>{
    const supplied=Number(values[key]);
    const value=Number.isFinite(supplied)&&values[key]!==undefined&&values[key]!==null?supplied:base[key];
    return [key,Math.max(min,Math.min(max,Math.round(value)))];
  }));
}
export const formatParam=(key,value)=>{
  if(key==="hpf")return value+" Hz";
  if(key==="comp")return value+" dB";
  if(key==="reverb"||key==="drive")return value+"%";
  return (value>0?"+":"")+value+" dB";
};
