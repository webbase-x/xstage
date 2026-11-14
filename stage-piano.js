/* X-Stage on-stage GM piano: interactive keys and MIDI-note visualization.
 * Notes come from the exact SMF clock used for the rendered audio; no Drive writes. */
(function(scope){
'use strict';
const FIRST=48,LAST=96,WHITE_WIDTH=24,BLACK_WIDTH=16;
const natural=new Set([0,2,4,5,7,9,11]);
const $=id=>document.getElementById(id);
const label=note=>['C','C♯','D','D♯','E','F','F♯','G','G♯','A','A♯','B'][note%12]+(Math.floor(note/12)-1);
function timelineEvents(notes){
  if(!Array.isArray(notes))return [];
  const events=[];
  for(const n of notes.slice(0,300000)){
    if(!n||!Number.isFinite(n.start)||!Number.isFinite(n.end)||!Number.isInteger(n.key)||
       !Number.isInteger(n.channel)||n.key<FIRST||n.key>LAST||
       n.channel<0||n.channel>15||n.end<=n.start)continue;
    events.push({time:Math.max(0,n.start),key:n.key,channel:n.channel,delta:1},
                {time:n.end,key:n.key,channel:n.channel,delta:-1});
  }
  events.sort((a,b)=>a.time-b.time||a.delta-b.delta);
  return events;
}
function activeKeysAt(events,time,channel=-1){
  const counts=new Map();
  if(!Number.isFinite(time)||time<0)return [];
  for(const e of events){
    if(e.time>time)break;
    if(channel!==-1&&e.channel!==channel)continue;
    const next=(counts.get(e.key)||0)+e.delta;
    if(next>0)counts.set(e.key,next);else counts.delete(e.key);
  }
  return [...counts.keys()].sort((a,b)=>a-b);
}
scope.XStagePianoCore={timelineEvents,activeKeysAt,label,FIRST,LAST};
const panel=$('stage-piano'),keysRoot=$('stage-piano-keys'),player=$('player');
const topToggle=$('toggle-piano'),mobileToggle=$('mobile-piano-toggle'),close=$('stage-piano-close');
const status=$('stage-piano-state'),channelSelect=$('stage-piano-channel');
if(!panel||!keysRoot||!player||!topToggle)return;
const keyNodes=new Map();
const whiteTotal=Array.from({length:LAST-FIRST+1},(_,i)=>FIRST+i)
  .filter(note=>natural.has(note%12)).length;
keysRoot.style.width=(whiteTotal*WHITE_WIDTH)+'px';
let whiteIndex=0;
for(let note=FIRST;note<=LAST;note++){
  const isWhite=natural.has(note%12);
  const key=document.createElement('button');
  key.type='button';key.className='stage-piano-key '+(isWhite?'white':'black');
  key.dataset.note=String(note);
  key.setAttribute('aria-label','เล่นโน้ต '+label(note));
  key.setAttribute('aria-pressed','false');
  key.title=label(note);
  if(isWhite){
    key.style.left=(whiteIndex*WHITE_WIDTH)+'px';
    if(note%12===0){const c=document.createElement('span');c.textContent=label(note);key.append(c);}
    whiteIndex++;
  }else key.style.left=(whiteIndex*WHITE_WIDTH-BLACK_WIDTH/2)+'px';
  keysRoot.append(key);keyNodes.set(note,key);
}
if(channelSelect){
  channelSelect.replaceChildren(new Option('ทุกแชนเนล','-1'));
  for(let i=0;i<16;i++)channelSelect.add(new Option('Ch '+(i+1)+(i===9?' · กลอง':''),String(i)));
}
const clock={events:[],cursor:0,at:-1,counts:new Map(),channel:-1,raf:0};
const manual=new Map();
let preference=null,audioContext=null,visible=false;
const now=()=>Number(player.currentTime)||0;
function updateKeys(){
  for(const [note,key] of keyNodes){
    const active=(clock.counts.get(note)||0)>0;
    key.classList.toggle('midi-active',active);
    key.classList.toggle('manual-active',manual.has(note));
    key.setAttribute('aria-pressed',String(active||manual.has(note)));
  }
}
function sync(time){
  if(!Number.isFinite(time))return;
  if(time<clock.at-.06||time>clock.at+1.5||clock.at<0){
    clock.cursor=0;clock.counts.clear();
  }
  while(clock.cursor<clock.events.length&&clock.events[clock.cursor].time<=time){
    const event=clock.events[clock.cursor++];
    if(clock.channel!==-1&&event.channel!==clock.channel)continue;
    const next=(clock.counts.get(event.key)||0)+event.delta;
    if(next>0)clock.counts.set(event.key,next);else clock.counts.delete(event.key);
  }
  clock.at=time;
  updateKeys();
}
function tick(){
  clock.raf=0;
  if(!visible)return;
  sync(now());
  clock.raf=scope.requestAnimationFrame?.(tick)||0;
}
function show(open,remember=true){
  visible=!!open;
  panel.hidden=!visible;
  topToggle.setAttribute('aria-expanded',String(visible));
  mobileToggle?.setAttribute('aria-expanded',String(visible));
  if(remember)preference=visible;
  if(clock.raf){scope.cancelAnimationFrame?.(clock.raf);clock.raf=0;}
  if(visible){
    if(!$('virtual-keyboard')?.hidden)$('virtual-close')?.click();
    sync(now());tick();
  }else releaseAllManual();
  scope.dispatchEvent?.(new Event('xstage:piano-visibility'));
}
function release(note){
  const voice=manual.get(note);
  if(!voice)return;
  manual.delete(note);
  try{
    voice.gain.gain.cancelScheduledValues(voice.ctx.currentTime);
    voice.gain.gain.setTargetAtTime(.00001,voice.ctx.currentTime,.018);
    voice.osc.stop(voice.ctx.currentTime+.11);
  }catch{}
  updateKeys();
}
function releaseAllManual(){for(const note of [...manual.keys()])release(note);}
function press(note){
  if(manual.has(note))return;
  try{
    const Audio=scope.AudioContext||scope.webkitAudioContext;
    if(!Audio){status.textContent='เครื่องนี้ไม่รองรับ Web Audio';return;}
    if(!audioContext)audioContext=new Audio();
    if(audioContext.state==='suspended')void audioContext.resume();
    const oscillator=audioContext.createOscillator(),gain=audioContext.createGain();
    oscillator.type='sine';oscillator.frequency.value=440*Math.pow(2,(note-69)/12);
    gain.gain.setValueAtTime(.00001,audioContext.currentTime);
    gain.gain.exponentialRampToValueAtTime(.085,audioContext.currentTime+.016);
    oscillator.connect(gain);gain.connect(audioContext.destination);oscillator.start();
    manual.set(note,{osc:oscillator,gain,ctx:audioContext});
    updateKeys();
  }catch(error){status.textContent='ทดลองเสียงไม่ได้: '+String(error.message||error).slice(0,65);}
}
for(const [note,key] of keyNodes){
  key.addEventListener('pointerdown',event=>{
    if(event.button!==0&&event.pointerType!=='touch')return;
    event.preventDefault();
    try{key.setPointerCapture(event.pointerId);}catch{}
    press(note);
  });
  for(const name of ['pointerup','pointercancel','lostpointercapture'])
    key.addEventListener(name,()=>release(note));
  key.addEventListener('keydown',event=>{
    if((event.key===' '||event.key==='Enter')&&!event.repeat){event.preventDefault();press(note);}
  });
  key.addEventListener('keyup',event=>{
    if(event.key===' '||event.key==='Enter'){event.preventDefault();release(note);}
  });
  key.addEventListener('blur',()=>release(note));
}
topToggle.addEventListener('click',()=>show(!visible));
mobileToggle?.addEventListener('click',()=>show(!visible));
close?.addEventListener('click',()=>show(false));
channelSelect?.addEventListener('change',()=>{
  clock.channel=Number(channelSelect.value);
  clock.at=-1;sync(now());
});
scope.addEventListener('xstage:midi-ready',event=>{
  clock.events=timelineEvents(event.detail?.notes);
  clock.cursor=0;clock.at=-1;clock.counts.clear();
  status.textContent=clock.events.length?
    'โน้ต MIDI จริง · ไฮไลต์ตามเพลง':'ไม่มีโน้ตในช่วง C3–C7';
  if(preference===null)show((scope.innerWidth||0)>=760,false);
  else if(visible)sync(now());
});
function clear(){
  clock.events=[];clock.cursor=0;clock.at=-1;clock.counts.clear();
  status.textContent='กดคีย์เพื่อทดลองเสียงเปียโนพื้นฐาน';
  updateKeys();
  if(preference===null)show(false,false);
}
scope.addEventListener('xstage:piano-clear',clear);
scope.addEventListener('xstage:auth-cleared',clear);
scope.addEventListener('xstage:piano-collapse',()=>{if(visible)show(false,false);});
scope.addEventListener('blur',releaseAllManual);
document.addEventListener('visibilitychange',()=>{if(document.hidden)releaseAllManual();});
player.addEventListener('seeked',()=>{clock.at=-1;if(visible)sync(now());});
panel.hidden=true;status.textContent='กดคีย์เพื่อทดลองเสียงเปียโนพื้นฐาน';
})(typeof window!=='undefined'?window:globalThis);
