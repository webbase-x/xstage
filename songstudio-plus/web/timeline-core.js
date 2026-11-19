/* Exact, testable time-axis math for manual karaoke cues.
 * Displays measured/manual positions only; never synthesizes missing cues.
 * Compatible with Windows QtWebEngine and Node's test runner.
 */
(function(root){
  "use strict";
  const number=value=>(value===null||value===undefined||value==="")?
    null:(Number.isFinite(Number(value))?Number(value):null);
  const clamp=(x,lo,hi)=>Math.max(lo,Math.min(hi,x));
  function range(line,anchor,duration,zoom=1){
    const start=number(line?.start),end=number(line?.end);
    const timed=start!==null&&end!==null&&end>start;
    const original=timed?Math.max(8,end-start+3):14;
    const scale=clamp(Number(zoom)||1,.25,8);
    const full=Math.max(4,Number(duration)||0,original);
    const width=Math.min(full,Math.max(4,original*scale));
    const middle=timed?(start+end)/2:(number(anchor)??0);
    const from=clamp(middle-width/2,0,Math.max(0,full-width));
    return {from,to:from+width,width,timed};
  }
  function position(at,window){
    const value=number(at);
    return value===null?null:clamp(100*(value-window.from)/window.width,0,100);
  }
  function sampleTime(clientX,left,width,window){
    if(!Number.isFinite(width)||width<=0)return null;
    return Math.round((window.from+clamp((clientX-left)/width,0,1)*window.width)*1000)/1000;
  }
  function bounds(line,index,duration){
    const values=Array.isArray(line?.starts)?line.starts:[];
    if(!Number.isInteger(index)||index<0||index>=values.length)return null;
    const start=number(line.start),end=number(line.end);
    const previous=index>0?number(values[index-1]):null;
    const next=index+1<values.length?number(values[index+1]):null;
    let low=Math.max(0,start??0,previous??0);
    let high=end!==null?end-.001:Number.POSITIVE_INFINITY;
    if(next!==null)high=Math.min(high,next);
    const trackEnd=number(duration);
    if(trackEnd!==null&&trackEnd>0)high=Math.min(high,trackEnd);
    if(!Number.isFinite(high))return null; // need measured line end or duration
    if(high<low)return null;
    return {min:low,max:high};
  }
  const atTime=(value,limits)=>limits?
    Math.round(clamp(value,limits.min,limits.max)*1000)/1000:null;
  const format=t=>{
    const value=number(t);
    if(value===null)return "--:--.---";
    const m=Math.floor(Math.max(0,value)/60);
    return String(m).padStart(2,"0")+":"+
      (Math.max(0,value)-60*m).toFixed(3).padStart(6,"0");
  };
  const api={number,clamp,range,position,sampleTime,bounds,atTime,format};
  if(typeof module!=="undefined"&&module.exports)module.exports=api;
  root.XStageCueTimeline=api;
})(typeof globalThis!=="undefined"?globalThis:this);
