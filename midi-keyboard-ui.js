/* X-Stage Karaoke Online — PC-style MIDI keyboard.
 * Based on the controls and MIDI key geometry of
 * windows-pc/source/karaoke/midi_keyboard.py + keyboard_controls.py.
 * Keeps the search keyboard and lyric transport independent. No MIDI uploads.
 */
(function(scope){
'use strict';
const $=id=>document.getElementById(id);
const panel=$('midi-keyboard-panel'),trigger=$('midi-keyboard-toggle');
const control=$('midi-keyboard-control');
if(!panel||!trigger)return;
const close=$('midi-keyboard-close'),range=$('midi-keyboard-range');
const channel=$('midi-keyboard-channel'),instrument=$('midi-instrument');
const keys=$('midi-piano-keys'),scroll=$('midi-piano-scroll');
const notes=$('midi-keyboard-notes'),info=$('midi-piano-info');
const label=$('midi-instrument-label');
const black=new Set([1,3,6,8,10]),names=['C','C♯','D','D♯','E','F','F♯','G','G♯','A','A♯','B'];
const pianoLetters='awsedftgyhujkolp'; // Same C4–D#5 hotkeys as X-Stage PC.
const noteName=n=>names[n%12]+Math.floor(n/12-1);
let source=null,parsed=null,getTime=()=>0,getPlaying=()=>false,preview=()=>false;
let events=[],position=0,lastTime=-1,active=new Map(),rendered=new Map();
let start=36,raf=0,previousFrame=0,heldPointers=new Map(),heldKeyboard=new Map();
let resizeObserver=null,userDismissed=false;
for(let ch=1;ch<=16;ch++){
  const option=document.createElement('option');
  option.value=String(ch-1);option.textContent='ช่อง '+ch;
  channel.append(option);
}
function release(note){
  try{preview(note,false);}catch(error){scope.console?.warn?.('MIDI preview note off:',error);}
  rendered.get(note)?.classList.remove('preview');
}
function releaseAll(){
  for(const value of heldPointers.values())release(value);
  for(const value of heldKeyboard.values())release(value);
  heldPointers.clear();heldKeyboard.clear();
}
function toggle(open,{focus=false}={}){
  if(!source&&open)return;
  panel.hidden=!open;trigger.setAttribute('aria-expanded',String(open));
  if(open){
    ensureEvents();redraw();
    if(focus)panel.focus({preventScroll:true});
    updateNotes();frame();
  }else{
    if(raf){cancelAnimationFrame(raf);raf=0;}
    releaseAll();
  }
}
function ensureEvents(){
  if(parsed||!source)return;
  try{
    parsed=scope.XStageBrowserMidi?.parseMidi?.(source)||null;
    if(!parsed)throw Error('ไม่พบตัวอ่าน MIDI');
    events=parsed.notes.flatMap(note=>[
      {time:note.start,key:note.channel*128+note.key,delta:1},
      {time:note.end,key:note.channel*128+note.key,delta:-1}
    ]).sort((a,b)=>a.time-b.time||a.delta-b.delta);
    position=0;lastTime=-1;active.clear();
    info.textContent='แสดงโน้ตที่กำลังเล่น · เลือกเครื่องดนตรีได้โดยไม่เริ่มเพลงใหม่ · แตะคีย์เพื่อทดลองเสียง SoundFont';
  }catch(error){
    info.textContent='อ่านโน้ต MIDI ไม่สำเร็จ: '+error.message;
    parsed={notes:[]};events=[];
  }
}
function count(){
  const mode=range.value;
  return mode==='128'?128:mode==='61'?61:scroll.clientWidth>=1200?128:61;
}
function drawKeys(){
  rendered.clear();keys.replaceChildren();
  const total=count(),first=total===128?0:start;
  const whiteCount=Array.from({length:total},(_,i)=>first+i)
    .filter(note=>!black.has(note%12)).length;
  const cell=Math.max(total===128?13:24,Math.min(37,scroll.clientWidth/whiteCount));
  const width=whiteCount*cell;
  keys.style.width=width+'px';keys.style.height='128px';
  const fragment=document.createDocumentFragment();
  let whites=0;
  const create=(n,left,isBlack)=>{
    const button=document.createElement('button');
    button.type='button';button.dataset.note=String(n);
    button.className='midi-piano-key '+(isBlack?'is-black':'is-white');
    button.style.left=left+'px';
    button.style.width=(isBlack?cell*.59:cell)+'px';
    button.setAttribute('aria-label',noteName(n)+' ทดลองเสียง MIDI');
    button.title=noteName(n);
    if(!isBlack&&n%12===0){
      const name=document.createElement('span');
      name.textContent=noteName(n);button.append(name);
    }
    rendered.set(n,button);
    fragment.append(button);
  };
  for(let n=first;n<first+total;n++){
    if(black.has(n%12))continue;
    create(n,whites*cell,false);whites++;
  }
  let whiteBefore=0;
  for(let n=first;n<first+total;n++){
    if(!black.has(n%12)){whiteBefore++;continue;}
    create(n,whiteBefore*cell-cell*.295,true);
  }
  keys.append(fragment);
  $('midi-keyboard-oct-down').disabled=total===128||start<=0;
  $('midi-keyboard-oct-up').disabled=total===128||start>=60;
  if(total===128)scroll.scrollLeft=0;
  else{
    const desired=(60-first)/12*7*cell;
    scroll.scrollLeft=Math.max(0,Math.min(width-scroll.clientWidth,desired));
  }
  updateNotes();
}
function redraw(){if(!panel.hidden)drawKeys();}
function advance(now){
  if(!Number.isFinite(now))return;
  if(now<lastTime-.1){position=0;active.clear();}
  while(position<events.length&&events[position].time<=now+.015){
    const event=events[position++];
    const number=(active.get(event.key)||0)+event.delta;
    if(number<=0)active.delete(event.key);else active.set(event.key,number);
  }
  lastTime=now;
}
function updateNotes(){
  const ch=channel.value;
  const visible=new Set();
  if(getPlaying()){
    advance(Number(getTime()));
    for(const [key,number] of active){
      if(number>0&&(ch==='all'||Math.floor(key/128)===Number(ch)))
        visible.add(key%128);
    }
  }
  for(const [pitch,key] of rendered)key.classList.toggle('sounding',visible.has(pitch));
  const displayed=[...visible].sort((a,b)=>a-b);
  notes.textContent=displayed.length?
    displayed.slice(0,6).map(noteName).join(' ') +(displayed.length>6?' +'+(displayed.length-6):''):'—';
}
function frame(){
  if(panel.hidden){raf=0;return;}
  const now=performance.now();
  if(now-previousFrame>=50){previousFrame=now;updateNotes();}
  raf=requestAnimationFrame(frame);
}
function down(note,owner,sourceMap){
  if(!Number.isInteger(note)||note<0||note>127||sourceMap.has(owner))return;
  sourceMap.set(owner,note);
  let played=false;
  try{played=!!preview(note,true);}catch(error){
    info.textContent='ทดลองเสียงไม่ได้: '+error.message;
  }
  rendered.get(note)?.classList.add('preview');
  if(!played)info.textContent='คีย์บอร์ดแสดงโน้ตได้แล้ว · ทดลองเสียงแยกใช้ SpessaSynth และ SoundFont ที่พร้อมเล่น';
}
function up(owner,sourceMap){
  const note=sourceMap.get(owner);
  if(note===undefined)return;
  sourceMap.delete(owner);
  release(note);
}
trigger.addEventListener('click',()=>{
  const open=panel.hidden;
  userDismissed=!open;
  toggle(open,{focus:open});
});
close.addEventListener('click',()=>{
  userDismissed=true;toggle(false);trigger.focus({preventScroll:true});
});
range.addEventListener('change',redraw);
channel.addEventListener('change',updateNotes);
$('midi-keyboard-oct-down').addEventListener('click',()=>{
  start=Math.max(0,start-12);redraw();
});
$('midi-keyboard-oct-up').addEventListener('click',()=>{
  start=Math.min(60,start+12);redraw();
});
instrument.addEventListener('change',()=>{
  label.textContent=instrument.selectedOptions[0]?.textContent||'ตามเพลง MIDI';
  // The existing app listener applies the selected program to live MIDI.
});
keys.addEventListener('pointerdown',event=>{
  const target=event.target.closest?.('[data-note]');
  if(!target||event.button>0)return;
  const note=Number(target.dataset.note);
  down(note,event.pointerId,heldPointers);
  try{target.setPointerCapture?.(event.pointerId);}catch{}
});
for(const type of ['pointerup','pointercancel','lostpointercapture']){
  keys.addEventListener(type,event=>up(event.pointerId,heldPointers));
}
scope.addEventListener('pointerup',event=>up(event.pointerId,heldPointers));
scope.addEventListener('pointercancel',event=>up(event.pointerId,heldPointers));
const canType=target=>target&&/INPUT|SELECT|TEXTAREA/.test(target.tagName||'');
panel.addEventListener('keydown',event=>{
  if(event.key==='Escape'){toggle(false);trigger.focus();return;}
  if(canType(event.target)||event.altKey||event.ctrlKey||event.metaKey)return;
  const offset=pianoLetters.indexOf(String(event.key).toLowerCase());
  if(offset<0)return;
  event.preventDefault();
  if(!event.repeat)down(60+offset,event.code||event.key,heldKeyboard);
});
panel.addEventListener('keyup',event=>{
  const offset=pianoLetters.indexOf(String(event.key).toLowerCase());
  if(offset>=0)up(event.code||event.key,heldKeyboard);
});
panel.addEventListener('focusout',event=>{
  if(!panel.contains(event.relatedTarget))releaseAll();
});
scope.addEventListener('blur',releaseAll);
if(typeof ResizeObserver==='function'){
  resizeObserver=new ResizeObserver(()=>{if(!panel.hidden)redraw();});
  resizeObserver.observe(scroll);
}
function setSong({bytes=null,getCurrentTime=null,isPlaying=null,previewNote=null}={}){
  releaseAll();parsed=null;source=bytes;events=[];position=0;lastTime=-1;
  active.clear();
  getTime=typeof getCurrentTime==='function'?getCurrentTime:()=>0;
  getPlaying=typeof isPlaying==='function'?isPlaying:()=>false;
  preview=typeof previewNote==='function'?previewNote:()=>false;
  if(!bytes){
    toggle(false);
    if(control)control.hidden=true;
    label.textContent='ตามเพลง MIDI';
    return;
  }
  if(control)control.hidden=false;
  label.textContent=instrument.selectedOptions[0]?.textContent||'ตามเพลง MIDI';
  // A newly loaded MIDI opens the top PC-style piano automatically unless
  // the listener explicitly closed it; changing songs preserves that choice.
  if(!userDismissed)toggle(true);
  else if(!panel.hidden){ensureEvents();drawKeys();}
}
scope.XStageMIDIPiano={setSong,close:()=>toggle(false)};
})(typeof window!=='undefined'?window:globalThis);
