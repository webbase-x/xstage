
/* X-Stage web feature parity — keeps Google Drive and playback state in app.js */
'use strict';
(function(){
const $pc=id=>document.getElementById(id);
const dock=$pc('pc-search'),toggle=$pc('pc-hide-search'),dialog=$pc('pc-dialog'),body=$pc('pc-dialog-body');
const favorites=new Set();
const savedUiPrefs=window.XStageUiPrefs?.read?.()||{};
let abA=null,abB=null,
    lyricScale=Number.isFinite(Number(savedUiPrefs.lyricScale))?Math.max(.7,Math.min(1.5,Number(savedUiPrefs.lyricScale))):1,
    lyricColor=/^#[0-9a-f]{6}$/i.test(String(savedUiPrefs.lyricColor||''))?savedUiPrefs.lyricColor:'#ecf7ff';
const audio=ui.player;
function expand(open){dock.classList.toggle('pc-expanded',!!open);toggle.textContent=open?'▴':'▾';ui.search.setAttribute('aria-expanded',String(!!open));}
function focusSearch(){if(!state.token)return;expand(Boolean(ui.search.value.trim()));ui.search.focus();ui.search.select();}
$pc('pc-find').onclick=focusSearch;
toggle.onclick=()=>expand(!dock.classList.contains('pc-expanded'));
ui.search.addEventListener('focus',()=>{if(state.token)expand(Boolean(ui.search.value.trim()))});
ui.search.addEventListener('input',()=>{if(state.token){expand(Boolean(ui.search.value.trim()));if(state.shown.length)selectSong(0,false);}});
ui.search.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();expand(false);ui.search.blur();}if(e.key==='Enter')queueMicrotask(()=>expand(false));},true);
ui.songs.addEventListener('dblclick',()=>queueMicrotask(()=>expand(false)));
document.addEventListener('keydown',e=>{
 if(e.key==='F3'&&state.token){e.preventDefault();focusSearch();return;}
 if(e.key==='Escape'&&dock.classList.contains('pc-expanded')){e.preventDefault();expand(false);return;}
 if(e.key==='F7'){e.preventDefault();if(state.queue.length)playNext();else{stopSong();audio.pause();audio.removeAttribute('src');audio.load();state.current=null;state.lyrics=null;ui.nowPlaying.textContent='ยังไม่ได้เลือกเพลง';ui.nowArtist.textContent='X-Stage Karaoke Online';ui.stageCode.textContent='—';ui.stage.classList.remove('playing');ui.stageIdle.hidden=false;updateTransport();}}
 if(!state.token||e.ctrlKey||e.altKey||e.metaKey||e.key.length!==1||!/[\p{L}\p{N}]/u.test(e.key))return;
 if(['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName))return;
 e.preventDefault();expand(true);ui.search.focus();ui.search.value+=e.key;ui.search.dispatchEvent(new Event('input'));
},true);
const baseRender=renderSongs;
renderSongs=function(){
 if(!state.token){baseRender();return;}
 const saved=state.songs,filtered=$pc('pc-favorites-only').checked;
 if(filtered)state.songs=saved.filter(s=>favorites.has(songIdentity(s)));
 try{baseRender();}finally{state.songs=saved;}
 [...ui.songs.querySelectorAll('.song-item')].forEach((row,i)=>{
  const song=state.shown[i];if(!song)return;
  const star=document.createElement('button');star.type='button';star.className='pc-star';star.style.cssText='border:0;background:transparent;color:#ffd46a;font-size:20px;padding:3px 7px';star.textContent=favorites.has(songIdentity(song))?'★':'☆';star.title='เพลงโปรด (เฉพาะในแท็บนี้)';
  star.onclick=e=>{e.stopPropagation();const id=songIdentity(song);if(favorites.has(id))favorites.delete(id);else favorites.add(id);renderSongs();};
  row.insertBefore(star,row.lastElementChild);
  row.addEventListener('contextmenu',e=>{e.preventDefault();showSong(song);});
 });
};
$pc('pc-favorites-only').onchange=()=>{state.selectedIndex=0;renderSongs();};
const loginObserver=new MutationObserver(()=>{
 if(state.token&&!dock.dataset.logged){dock.dataset.logged='yes';expand(Boolean(ui.search.value.trim()));}
 if(!state.token&&dock.dataset.logged){delete dock.dataset.logged;favorites.clear();expand(false);}
});
loginObserver.observe(ui.logout,{attributes:true,attributeFilter:['hidden']});
function openDialog(title){$pc('pc-dialog-title').textContent=title;body.replaceChildren();if(!dialog.open)dialog.showModal();return body;}
$pc('pc-dialog-close').onclick=()=>dialog.close();
function confirmClearCache(){
 const d=openDialog('ล้างแคช X-Stage');
 d.append(para('ล้างฐานเพลงที่ดาวน์โหลดไว้ในเครื่องและแคชไฟล์เว็บ โดยไม่ลบการลงชื่อเข้าใช้ Google หรือสิทธิ์รีโมท การเปิดเว็บครั้งถัดไปจะตรวจรุ่นฐานเพลงและดาวน์โหลดใหม่'));
 const result=para('');d.append(result);
 d.append(button('ยืนยันล้างแคช',async()=>{
   result.textContent='กำลังล้างแคช…';
   try{await window.XStageClearCache();result.textContent='ล้างแคชสำเร็จ · ยังเข้าสู่ระบบ Google อยู่';}
   catch(e){result.textContent=e?.message||'ล้างแคชไม่สำเร็จ';}
 }));
}
$pc('pc-clear-cache')?.addEventListener('click',confirmClearCache);
$pc('mobile-clear-cache')?.addEventListener('click',confirmClearCache);

function button(label,handler){const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=handler;return b;}
function para(text){const p=document.createElement('p');p.textContent=text;return p;}
function showSong(song){const d=openDialog('รายละเอียดเพลง');d.append(para([song.code,song.title,song.artist,song.type,'ระยะเวลา '+(song.duration||0)+' วินาที'].filter(Boolean).join(' · ')),button('เล่นทันที',()=>{dialog.close();playSong(song);expand(false);}),button('แทรกเป็นเพลงถัดไป',()=>{state.queue.unshift(song);renderQueue();dialog.close();}));}
$pc('pc-history').onclick=()=>{const d=openDialog('ประวัติการเล่น (เซสชันนี้)');const songs=[...state.history];if(state.current)songs.push(state.current);if(!songs.length)d.append(para('ยังไม่มีประวัติการเล่น'));for(const s of songs.slice().reverse().slice(0,100)){const row=document.createElement('div');row.className='pc-history-row';const title=document.createElement('span');title.textContent=(s.code||'')+' · '+(s.title||'');row.append(title,button('เล่น',()=>{dialog.close();playSong(s);}));d.append(row);}};
$pc('pc-random').onclick=()=>{
  if(!state.token){setPlayStatus('กรุณาเข้าสู่ระบบก่อนสุ่มเพลง');return;}
  // Random and medley both run shuffled tracks continuously until stopped.
  if(state.medley){
    const song=randomMedleySong();
    if(song){state.medleyUpcoming=null;playSong(song);}
  }else setMedleyMode(true);
};
function updateAB(){ $pc('pc-loop-a').classList.toggle('pc-active',abA!==null);$pc('pc-loop-b').classList.toggle('pc-active',abB!==null); }
$pc('pc-loop-a').onclick=()=>{if(!state.current)return;abA=audio.currentTime;abB=null;updateAB();setPlayStatus('ตั้งจุด A '+timeLabel(abA));};
$pc('pc-loop-b').onclick=()=>{if(abA===null||audio.currentTime<=abA+.15){setPlayStatus('ตั้งจุด A ก่อน และให้ B อยู่หลัง A');return;}abB=audio.currentTime;audio.loop=false;ui.repeat.checked=false;updateAB();setPlayStatus('กำลังวน A–B');};
$pc('pc-loop-clear').onclick=()=>{abA=null;abB=null;updateAB();setPlayStatus('ยกเลิกการวน A–B');};
audio.addEventListener('timeupdate',()=>{if(abA!==null&&abB!==null&&audio.currentTime>=abB)audio.currentTime=abA;});
audio.addEventListener('loadedmetadata',()=>{abA=null;abB=null;updateAB();});
const originalDrawLine=drawLine;
drawLine=function(text,y,maxWidth,fontSize,fill,progress,centerX){return originalDrawLine(text,y,maxWidth,fontSize*lyricScale,fill==='#ecf7ff'?lyricColor:fill,progress,centerX);};
// Both bundled stage artworks are selectable independently for each display.
const stageArtworks=[
  ['neon','แบบที่ 1 · เวทีนีออน'],
  ['photo','แบบที่ 2 · ภาพเวที'],
  ['deep-blue','แบบที่ 3 · สีน้ำเงินเข้ม']
];
const backgroundPrefs={
  main:['neon','photo','deep-blue'].includes(savedUiPrefs.mainBackground)?savedUiPrefs.mainBackground:'neon',
  singer:['neon','photo','deep-blue'].includes(savedUiPrefs.singerBackground)?savedUiPrefs.singerBackground:'photo'
};
function setMainBackground(value){
  const mode=stageArtworks.some(([v])=>v===value)?value:'neon';
  backgroundPrefs.main=mode;
  window.XStageUiPrefs?.save?.({mainBackground:mode});
  ui.stage.dataset.stageBackground=mode;
  ui.stage.classList.toggle('stage-hero-hidden',mode==='photo');
}
function setSingerBackground(value){
  const mode=stageArtworks.some(([v])=>v===value)?value:'photo';
  backgroundPrefs.singer=mode;
  window.XStageUiPrefs?.save?.({singerBackground:mode});
  sendBackgroundToSecondScreen();
}
function sendBackgroundToSecondScreen(){
  if(screen&&!screen.closed)try{
    screen.postMessage({type:'xstage-background',value:backgroundPrefs.singer},location.origin);
  }catch{}
}
setMainBackground(backgroundPrefs.main);
$pc('pc-lyrics-settings').onclick=()=>{
 const d=openDialog('เนื้อร้อง / พื้นหลัง');
 const scale=document.createElement('input');scale.type='range';scale.min='.7';scale.max='1.5';scale.step='.05';scale.value=String(lyricScale);scale.oninput=()=>{lyricScale=+scale.value;window.XStageUiPrefs?.save?.({lyricScale});};
 const sl=document.createElement('label');sl.textContent='ขนาดตัวอักษร';sl.append(scale);d.append(sl);
 const col=document.createElement('input');col.type='color';col.value=lyricColor;col.oninput=()=>{lyricColor=col.value;window.XStageUiPrefs?.save?.({lyricColor});};
 const cl=document.createElement('label');cl.textContent='สีเนื้อร้อง';cl.append(col);d.append(cl);
 const offset=document.createElement('input');offset.type='range';offset.min='-3000';offset.max='3000';offset.step='50';offset.value='0';
 offset.oninput=()=>{if(state.lyrics){state.lyrics.audioOffsetMs=(Number(state.lyrics.audioOffsetMs)||0)+(+offset.value-(+offset.dataset.before||0));offset.dataset.before=offset.value;}};
 const ol=document.createElement('label');ol.textContent='ชดเชยเวลาเนื้อร้อง (ms)';ol.append(offset);d.append(ol);
 for(const [target,label,current,setValue] of [
   ['main','พื้นหลังจอหลัก',backgroundPrefs.main,setMainBackground],
   ['singer','พื้นหลังจอร้องแยก',backgroundPrefs.singer,setSingerBackground]
 ]){
   const select=document.createElement('select');
   for(const [value,name] of stageArtworks){
     const item=document.createElement('option');item.value=value;item.textContent=name;select.append(item);
   }
   select.value=current;
   select.onchange=()=>setValue(select.value);
   const row=document.createElement('label');row.textContent=label;row.append(select);d.append(row);
 }
 d.append(para('การตั้งค่านี้ไม่แก้ไขเพลงหรือฐานข้อมูลใน Google Drive'));
};
const EQ_FREQS=[20,25,31.5,40,50,63,80,100,125,160,200,250,315,400,500,630,800,1000,1250,1600,2000,2500,3150,4000,5000,6300,8000,10000,12500,16000,20000];
const EQ_PRESETS={
 flat:Array(31).fill(0),
 pop:[1.5,1.5,1.5,2,2.5,3,3,2.5,2,1,.5,0,-.5,-1,-1,-.5,0,1,2,2.5,2.5,2,1.5,1,1,1.5,2,2.5,2.5,2,1],
 rock:[3,3,3.5,4,4,3.5,3,2,1,0,-1,-1.5,-1.5,-1,0,1,2,2.5,3,3,2.5,2,2,2.5,3,3.5,4,4,3.5,3,2],
 jazz:[2,2,2,1.5,1.5,1,0.5,0,0,0.5,1,1.5,1.5,1,0.5,0,0.5,1,1.5,2,2,1.5,1,0.5,1,1.5,2,2.5,3,3,2.5],
 vocal:[-2,-2,-2,-1.5,-1.5,-1,-1,-.5,0,.5,1,1.5,2,2.5,3,3.5,4,4,4,3.5,3,2.5,2,1.5,1,.5,0,-.5,-1,-1.5,-2],
 edm:[4,4,4.5,5,5,4.5,4,3,2,1,0,-1,-1.5,-1.5,-1,0,1,2,2.5,2.5,2,1,0,0.5,1.5,2.5,3.5,4,4.5,4,3],
 acoustic:[1,1,1,1,1.5,1.5,1.5,1,0.5,0,0,0.5,1,1.5,2,2.5,3,3,2.5,2,1.5,1,1,1.5,2,2,2,1.5,1,0.5,0],
 classical:[2,2,2,1.5,1,0.5,0,0,-0.5,-1,-1,-.5,0,.5,1,1.5,2,2.5,2.5,2,1.5,1,.5,.5,1,1.5,2,2.5,3,3,2.5]
};
let eqContext=null,eqNodes=[],eqAnalyser=null,eqLeft=null,eqRight=null,eqSource=null;
let eqBandInputs=[],eqBandLights=[],eqBypassed=false,eqPreset='auto',eqLastSong='',eqFrame=0;
const eqPanel=$pc('xstage-eq-panel'),eqBands=$pc('xstage-eq-bands'),eqPresetSelect=$pc('xstage-eq-preset');
const eqPrefs=window.XStageUiPrefs?.read?.()||{};
if(typeof eqPrefs.eqPreset==='string')eqPreset=eqPrefs.eqPreset;
if(typeof eqPrefs.eqBypassed==='boolean')eqBypassed=eqPrefs.eqBypassed;
function eqFreqLabel(f){return f>=1000?(f/1000).toFixed(f%1000?2:0).replace(/0$/,'')+'k':String(f);}
function eqBandColor(f){return f<80?'#ff3b30':f<250?'#ff8a00':f<630?'#ffd400':f<1600?'#62e33c':f<4000?'#22d3a7':f<10000?'#18b7ff':'#755bff';}
function ensureEqAudio(){
 if(eqContext)return true;
 const C=window.AudioContext||window.webkitAudioContext;if(!C){setPlayStatus('Web Audio API ไม่รองรับ EQ 31 Band');return false;}
 eqContext=new C();eqSource=eqContext.createMediaElementSource(audio);
 eqNodes=EQ_FREQS.map(freq=>{const n=eqContext.createBiquadFilter();n.type='peaking';n.frequency.value=freq;n.Q.value=4.318;return n;});
 eqAnalyser=eqContext.createAnalyser();eqAnalyser.fftSize=4096;eqAnalyser.smoothingTimeConstant=.72;
 eqLeft=eqContext.createAnalyser();eqRight=eqContext.createAnalyser();eqLeft.fftSize=512;eqRight.fftSize=512;
 const splitter=eqContext.createChannelSplitter(2);
 let node=eqSource;for(const filter of eqNodes){node.connect(filter);node=filter;}node.connect(eqAnalyser);eqAnalyser.connect(eqContext.destination);eqAnalyser.connect(splitter);splitter.connect(eqLeft,0);splitter.connect(eqRight,1);
 applyEqGains(false);return true;
}
function savedEqGains(){
 const v=(window.XStageUiPrefs?.read?.()||{}).eqGains;
 return Array.isArray(v)&&v.length===31?v.map(x=>Math.max(-12,Math.min(12,Number(x)||0))):null;
}
function currentEqGains(){return eqBandInputs.length?eqBandInputs.map(i=>Number(i.value)):savedEqGains()||EQ_PRESETS.flat.slice();}
function applyEqGains(save=true){
 const values=currentEqGains();
 eqNodes.forEach((n,i)=>n.gain.value=eqBypassed?0:values[i]);
 eqBandInputs.forEach((input,i)=>input.value=String(values[i]));
 $pc('xstage-eq-bypass')?.setAttribute('aria-pressed',String(eqBypassed));
 if(save)window.XStageUiPrefs?.save?.({eqGains:values,eqPreset,eqBypassed});
 sendEqState();
}
function autoPresetForSong(song){
 const text=[song?.genre,song?.style,song?.type,song?.category].filter(Boolean).join(' ').toLowerCase();
 if(/edm|dance|electro|house|techno|ดนตรีเต้น|แดนซ์/.test(text))return 'edm';
 if(/rock|metal|alternative|ร็อก|ร็อค/.test(text))return 'rock';
 if(/jazz|swing|blues|แจ๊ส/.test(text))return 'jazz';
 if(/classic|orchestra|symph|คลาสสิก|ออร์เคสตรา/.test(text))return 'classical';
 if(/acoustic|folk|country|อะคูสติก|โฟล์ค|ลูกทุ่ง/.test(text))return 'acoustic';
 if(/vocal|ballad|ร้อง|เพลงช้า/.test(text))return 'vocal';
 if(/pop|ป๊อป/.test(text))return 'pop';
 return 'flat';
}
function setEqPreset(name,{save=true}={}){
 eqPreset=EQ_PRESETS[name]?name:name==='auto'?'auto':'flat';
 const actual=eqPreset==='auto'?autoPresetForSong(state.current):eqPreset;
 const gains=EQ_PRESETS[actual]||EQ_PRESETS.flat;
 eqBandInputs.forEach((input,i)=>input.value=String(gains[i]));
 eqNodes.forEach((node,i)=>node.gain.value=eqBypassed?0:gains[i]);
 if(eqPresetSelect)eqPresetSelect.value=eqPreset;
 const label=$pc('xstage-eq-song-style');if(label)label.textContent=eqPreset==='auto'?'AUTO: '+actual.toUpperCase():'PRESET: '+eqPreset.toUpperCase();
 if(save)window.XStageUiPrefs?.save?.({eqPreset,eqGains:gains,eqBypassed});
 sendEqState();
}
function buildEqBands(){
 if(!eqBands||eqBands.children.length)return;
 const saved=savedEqGains()||EQ_PRESETS.flat;
 EQ_FREQS.forEach((freq,i)=>{
  const band=document.createElement('label');band.className='xstage-eq-band';band.style.setProperty('--band-color',eqBandColor(freq));
  const gain=document.createElement('span');gain.className='xstage-eq-gain';gain.textContent=(saved[i]>0?'+':'')+saved[i].toFixed(1);
  const light=document.createElement('i');light.className='xstage-eq-band-light';light.style.setProperty('--level','0');
  const input=document.createElement('input');input.type='range';input.min='-12';input.max='12';input.step='.5';input.value=String(saved[i]);input.setAttribute('aria-label',eqFreqLabel(freq)+'Hz');
  input.addEventListener('input',()=>{eqPreset='custom';if(eqPresetSelect)eqPresetSelect.value='flat';gain.textContent=(+input.value>0?'+':'')+(+input.value).toFixed(1);if(eqNodes[i])eqNodes[i].gain.value=eqBypassed?0:+input.value;window.XStageUiPrefs?.save?.({eqPreset:'custom',eqGains:currentEqGains(),eqBypassed});sendEqState();});
  const hz=document.createElement('span');hz.className='xstage-eq-hz';hz.textContent=eqFreqLabel(freq);
  band.append(gain,light,input,hz);eqBands.append(band);eqBandInputs.push(input);eqBandLights.push(light);
 });
}
function rms(analyser){
 if(!analyser)return 0;const data=new Float32Array(analyser.fftSize);analyser.getFloatTimeDomainData(data);let sum=0;for(const x of data)sum+=x*x;return Math.min(1,Math.sqrt(sum/data.length)*2.8);
}
function drawEqRta(){
 if(!eqPanel||eqPanel.hidden||!eqAnalyser){eqFrame=requestAnimationFrame(drawEqRta);return;}
 const canvas=$pc('xstage-eq-rta'),ctx=canvas?.getContext('2d');if(!ctx){eqFrame=requestAnimationFrame(drawEqRta);return;}
 const bins=new Uint8Array(eqAnalyser.frequencyBinCount);eqAnalyser.getByteFrequencyData(bins);
 ctx.clearRect(0,0,canvas.width,canvas.height);ctx.fillStyle='#02070d';ctx.fillRect(0,0,canvas.width,canvas.height);
 const sr=eqContext.sampleRate,ny=sr/2;const levels=[];
 EQ_FREQS.forEach((freq,i)=>{const bin=Math.max(0,Math.min(bins.length-1,Math.round(freq/ny*bins.length)));const level=bins[bin]/255;levels.push(level);eqBandLights[i]?.style.setProperty('--level',String(level));const x=i*canvas.width/EQ_FREQS.length,w=canvas.width/EQ_FREQS.length-2,h=level*(canvas.height-8);ctx.fillStyle=eqBandColor(freq);ctx.globalAlpha=.38+.62*level;ctx.fillRect(x,canvas.height-h,w,h);});
 ctx.globalAlpha=1;const l=rms(eqLeft),r=rms(eqRight);$pc('xstage-eq-meter-l').value=l;$pc('xstage-eq-meter-r').value=r;
 if(screen&&!screen.closed)try{screen.postMessage({type:'xstage-eq-meter',levels,left:l,right:r},location.origin);}catch{}
 eqFrame=requestAnimationFrame(drawEqRta);
}
function sendEqState(){
 if(!screen||screen.closed)return;try{screen.postMessage({type:'xstage-eq-state',open:!eqPanel.hidden,minimized:eqPanel.classList.contains('is-minimized'),expanded:eqPanel.classList.contains('is-expanded'),preset:eqPreset,bypassed:eqBypassed,gains:currentEqGains()},location.origin);}catch{}
}
function openEq(){
 buildEqBands();if(!ensureEqAudio())return;eqContext.resume().catch(()=>{});
 eqPanel.hidden=false;eqPanel.classList.remove('is-minimized');
 if(eqPresetSelect)eqPresetSelect.value=EQ_PRESETS[eqPreset]||eqPreset==='auto'?eqPreset:'flat';
 if(eqPreset==='auto')setEqPreset('auto',{save:false});else applyEqGains(false);
 sendEqState();
}
$pc('pc-eq').onclick=openEq;
$pc('xstage-eq-close')?.addEventListener('click',()=>{eqPanel.hidden=true;sendEqState();});
$pc('xstage-eq-minimize')?.addEventListener('click',()=>{eqPanel.classList.toggle('is-minimized');sendEqState();});
$pc('xstage-eq-expand')?.addEventListener('click',()=>{eqPanel.classList.toggle('is-expanded');sendEqState();});
$pc('xstage-eq-bypass')?.addEventListener('click',()=>{eqBypassed=!eqBypassed;applyEqGains();});
$pc('xstage-eq-reset')?.addEventListener('click',()=>setEqPreset('flat'));
eqPresetSelect?.addEventListener('change',()=>setEqPreset(eqPresetSelect.value));
(function makeEqDraggable(){
 const handle=eqPanel?.querySelector('[data-eq-drag]');if(!handle)return;let drag=null;
 handle.addEventListener('pointerdown',e=>{if(e.target.closest('button,select'))return;const r=eqPanel.getBoundingClientRect();drag={x:e.clientX-r.left,y:e.clientY-r.top};handle.setPointerCapture(e.pointerId);});
 handle.addEventListener('pointermove',e=>{if(!drag||eqPanel.classList.contains('is-expanded'))return;const left=Math.max(0,Math.min(innerWidth-eqPanel.offsetWidth,e.clientX-drag.x)),top=Math.max(0,Math.min(innerHeight-eqPanel.offsetHeight,e.clientY-drag.y));eqPanel.style.left=left+'px';eqPanel.style.top=top+'px';eqPanel.style.right='auto';eqPanel.style.bottom='auto';});
 handle.addEventListener('pointerup',()=>{if(!drag)return;window.XStageUiPrefs?.save?.({eqPosition:{left:eqPanel.style.left,top:eqPanel.style.top}});drag=null;});
 const pos=eqPrefs.eqPosition;if(pos?.left&&pos?.top){eqPanel.style.left=pos.left;eqPanel.style.top=pos.top;eqPanel.style.right='auto';eqPanel.style.bottom='auto';}
})();
audio.addEventListener('play',()=>{if(eqPreset==='auto'&&state.current){const id=songIdentity(state.current);if(id!==eqLastSong){eqLastSong=id;setEqPreset('auto',{save:false});}}});
window.addEventListener('message',e=>{if(e.origin!==location.origin||e.source!==screen||e.data?.type!=='xstage-eq-command')return;const d=e.data;if(d.action==='open')openEq();else if(d.action==='close'){eqPanel.hidden=true;sendEqState();}else if(d.action==='preset')setEqPreset(String(d.value||'flat'));else if(d.action==='bypass'){eqBypassed=!!d.value;applyEqGains();}else if(d.action==='gain'&&Number.isInteger(d.index)&&eqBandInputs[d.index]){eqBandInputs[d.index].value=String(Math.max(-12,Math.min(12,Number(d.value)||0)));eqBandInputs[d.index].dispatchEvent(new Event('input',{bubbles:true}));}});
buildEqBands();if(eqPresetSelect)eqPresetSelect.value=EQ_PRESETS[eqPreset]||eqPreset==='auto'?eqPreset:'flat';requestAnimationFrame(drawEqRta);
function downloadQueue(){
 const data={schemaVersion:1,source:'XStageWebQueue',songs:state.queue.map(songIdentity)};
 const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
 const a=document.createElement('a');a.href=url;a.download='xstage-web-queue.json';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
}
$pc('pc-export').onclick=downloadQueue;
$pc('pc-import').onclick=()=>$pc('pc-queue-file').click();
$pc('pc-queue-file').onchange=async e=>{
 const f=e.target.files[0];if(!f||!state.token)return;
 try{if(f.size>1e6)throw Error('ไฟล์ใหญ่เกินไป');const d=JSON.parse(await f.text());if(d.source!=='XStageWebQueue'||!Array.isArray(d.songs)||d.songs.length>10000)throw Error('รูปแบบไม่ถูกต้อง');
 const map=new Map(state.songs.filter(playable).map(s=>[songIdentity(s),s]));let count=0;for(const id of d.songs){const s=map.get(String(id));if(s){state.queue.push(s);count++;}}renderQueue();setPlayStatus('นำเข้าคิว '+count+' เพลง');}catch(e){setPlayStatus('นำเข้าคิวไม่สำเร็จ: '+e.message);}e.target.value='';
};
let screen=null;
$pc('pc-stage-pop').onclick=()=>{
 if(screen&&!screen.closed){screen.focus();return;}screen=window.open('./stage.html','xstage-second-stage','width=1100,height=640');
 if(!screen)setPlayStatus('กรุณาอนุญาตให้เปิดหน้าต่างจอร้องแยก');
  else screen.addEventListener('load',sendBackgroundToSecondScreen,{once:true});
};
setInterval(()=>{if(!screen||screen.closed)return;try{screen.postMessage({type:'xstage-stage',title:state.current?.title||'',artist:state.current?.artist||'',lines:state.lyrics?.lines||[],offset:Number(state.lyrics?.audioOffsetMs)||0,time:audio.currentTime},location.origin);}catch{}},200);
$pc('pc-other-tools').onclick=()=>{const d=openDialog('ความสามารถ X-Stage Web');d.append(para('เว็บ: ค้นหาแบบเรียลไทม์, คิวเพลง, ประวัติ, เพลงโปรดในเซสชัน, สุ่มเพลง, A–B, EQ, ตั้งค่าเนื้อร้องและพื้นหลัง, จอร้องแยก, ส่งออก/นำเข้าคิว'));
 d.append(para('เฉพาะ Windows: MIDI Mixer / SoundFont แยกชิ้นดนตรี, GM Keyboard, ปิด Guide Melody, ASIO, ปรับคีย์ดนตรีอิสระจาก M4A และจัดการฐานเพลงในเครื่อง'));
};
ui.logout.addEventListener('click',()=>{favorites.clear();expand(false);abA=null;abB=null;updateAB();if(screen&&!screen.closed)screen.close();screen=null;});
expand(false);
})();

/* Optional PC-style utilities: queue performer, LRC editor, stage effects and microphone recording. */
(function(){
const el=id=>document.getElementById(id),d=el('pc-dialog'),title=el('pc-dialog-title'),body=el('pc-dialog-body');
function b(label,fn){const n=document.createElement('button');n.type='button';n.textContent=label;n.onclick=fn;return n;}
function paragraph(text){const n=document.createElement('p');n.textContent=text;return n;}
function show(titleText){title.textContent=titleText;body.replaceChildren();if(!d.open)d.showModal();}
function saveFile(name,text,type='text/plain;charset=utf-8'){const url=URL.createObjectURL(new Blob([text],{type}));const link=document.createElement('a');link.href=url;link.download=name;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);}
const qRender=renderQueue;
renderQueue=function(){qRender();[...ui.queue.querySelectorAll('.queue-item')].forEach((row,i)=>{
 const song=state.queue[i],controls=row.querySelector('.queue-controls');if(!song||!controls)return;
 const edit=b('✎',()=>queueEditor(i));edit.title='แก้ชื่อผู้ร้อง / ความเร็วเพลงนี้';controls.prepend(edit);
 const small=row.querySelector('.queue-info small');if(small&&song.queueSinger)small.textContent+=(small.textContent?' · ':'')+'ผู้ร้อง '+song.queueSinger;
 if(small&&song.queueSpeed&&song.queueSpeed!==1)small.textContent+=' · '+song.queueSpeed+'×';
});};
const originalPlay=playSong;
playSong=function(song,opts){if(song?.queueSpeed&&[.75,.9,1,1.1,1.25,1.5].includes(Number(song.queueSpeed)))ui.speed.value=String(song.queueSpeed);return originalPlay(song,opts);};
function queueEditor(index){const song=state.queue[index];if(!song)return;show('แก้ไขเพลงในคิว');
 const singer=document.createElement('input');singer.type='text';singer.maxLength=80;singer.value=song.queueSinger||'';singer.placeholder='ชื่อผู้ร้อง';singer.style.cssText='color:white;background:#092d42;border:1px solid #3685a2;padding:8px;border-radius:7px';
 const speed=document.createElement('select');for(const v of [.75,.9,1,1.1,1.25,1.5]){const o=document.createElement('option');o.value=String(v);o.textContent=v.toFixed(2)+'×';speed.append(o);}speed.value=String(song.queueSpeed||1);
 const l=document.createElement('label');l.textContent='ผู้ร้อง';l.append(singer);const l2=document.createElement('label');l2.textContent='ความเร็ว';l2.append(speed);body.append(l,l2);
 body.append(b('บันทึก',()=>{if(state.queue[index]===song){state.queue[index]={...song,queueSinger:singer.value.trim(),queueSpeed:Number(speed.value)};renderQueue();}d.close();}));
}
el('pc-export').onclick=()=>saveFile('xstage-web-queue.json',JSON.stringify({schemaVersion:1,source:'XStageWebQueue',songs:state.queue.map(song=>({id:songIdentity(song),singer:song.queueSinger||'',speed:Number(song.queueSpeed)||1}))},null,2),'application/json');
el('pc-queue-file').onchange=async e=>{const f=e.target.files[0];if(!f||!state.token)return;try{if(f.size>1000000)throw Error('ไฟล์ใหญ่เกินไป');const data=JSON.parse(await f.text());if(data.source!=='XStageWebQueue'||!Array.isArray(data.songs)||data.songs.length>10000)throw Error('รูปแบบคิวไม่รองรับ');
 const index=new Map(state.songs.filter(playable).map(song=>[songIdentity(song),song]));let count=0;for(const item of data.songs){const id=typeof item==='string'?item:String(item?.id||'');const song=index.get(id);if(song){state.queue.push({...song,queueSinger:typeof item?.singer==='string'?item.singer.slice(0,80):'',queueSpeed:[.75,.9,1,1.1,1.25,1.5].includes(Number(item?.speed))?Number(item.speed):1});count++;}}renderQueue();setPlayStatus('นำเข้าคิว '+count+' รายการ');}catch(e){setPlayStatus(e.message);}e.target.value='';};
function stamp(seconds){const n=Math.max(0,Number(seconds)||0);return '['+String(Math.floor(n/60)).padStart(2,'0')+':'+(n%60).toFixed(2).padStart(5,'0')+']';}
function lrcText(){return (state.lyrics?.lines||[]).map(line=>stamp(line.startTime)+String(line.text||'')).join('\n');}
function parseLRC(text){
 const entries=[];for(const line of text.split(/\r?\n/)){const marks=[...line.matchAll(/\[(\d{1,3}):(\d{2}(?:\.\d{1,3})?)\]/g)];const value=line.replace(/\[\d{1,3}:\d{2}(?:\.\d{1,3})?\]/g,'').trim();if(!value)continue;for(const m of marks)entries.push({start:Number(m[1])*60+Number(m[2]),text:value});}
 entries.sort((a,b)=>a.start-b.start);if(!entries.length)throw Error('ไม่พบเวลา LRC ที่ถูกต้อง');
 return {schemaVersion:1,audioOffsetMs:0,lines:entries.map((entry,i)=>{const end=Math.max(entry.start+.1,entries[i+1]?.start??entry.start+6);return {lineIndex:i,startTime:entry.start,endTime:end,text:entry.text,syllables:[{text:entry.text,start:entry.start,duration:end-entry.start}]};})};
}
function lyricEditor(){show('แก้ไข / นำเข้า LRC');if(!state.current){body.append(paragraph('กรุณาเลือกเพลงก่อน'));return;}body.append(paragraph('แก้ไขเฉพาะการเล่นครั้งนี้ ไม่เปลี่ยน JSON บน Drive; การนำเข้า LRC จะใช้เวลาระดับบรรทัด'));
 const area=document.createElement('textarea');area.value=lrcText();area.rows=9;area.style.cssText='background:#051b2c;color:#fff;border:1px solid #366f85;border-radius:8px;padding:10px;width:100%;font:13px/1.6 monospace';body.append(area);
 const uploader=document.createElement('input');uploader.type='file';uploader.accept='.lrc,text/plain';uploader.onchange=async()=>{const file=uploader.files[0];if(!file)return;if(file.size>250000){setPlayStatus('LRC ใหญ่เกินไป');return;}const bytes=await file.arrayBuffer();const decoded=new TextDecoder('utf-8').decode(bytes);area.value=decoded.includes('�')?new TextDecoder('windows-874').decode(bytes):decoded;};body.append(uploader);
 body.append(b('ใช้เนื้อร้องฉบับนี้',()=>{try{state.lyrics=parseLRC(area.value);d.close();setPlayStatus('อัปเดตเนื้อร้อง LRC ในแท็บแล้ว');}catch(e){body.append(paragraph(e.message));}}),b('ดาวน์โหลด LRC',()=>saveFile((state.current.code||'song')+'.lrc',area.value)));
}
let rec=null;async function micRecording(){if(rec){const r=rec;rec=null;r.stop();setPlayStatus('หยุดบันทึกไมโครโฟนแล้ว');return;}try{if(!navigator.mediaDevices?.getUserMedia||typeof MediaRecorder==='undefined')throw Error('เบราว์เซอร์ไม่รองรับบันทึกไมโครโฟน');
 const stream=await navigator.mediaDevices.getUserMedia({audio:true});const recorder=new MediaRecorder(stream),parts=[];recorder.ondataavailable=e=>{if(e.data.size)parts.push(e.data);};
 recorder.onstop=()=>{stream.getTracks().forEach(t=>t.stop());if(parts.length){const url=URL.createObjectURL(new Blob(parts,{type:recorder.mimeType}));const link=document.createElement('a');link.href=url;link.download='xstage-mic.'+(recorder.mimeType.includes('ogg')?'ogg':'webm');link.click();setTimeout(()=>URL.revokeObjectURL(url),30000);}};
 recorder.start();rec=recorder;setPlayStatus('กำลังบันทึกไมโครโฟน…');}catch(e){setPlayStatus(e.message);}
}
const effects=new Map();function stageEffects(){show('เสียงเอฟเฟกต์หน้าเวที (จากเครื่องนี้)');body.append(paragraph('เลือก WAV/MP3 ได้สูงสุด 10 ไฟล์เพื่อเล่นเฉพาะแท็บ ไม่อัปโหลดไป Drive'));
 const input=document.createElement('input');input.type='file';input.accept='.mp3,.wav,audio/*';input.multiple=true;
 const list=document.createElement('div');input.onchange=()=>{for(const url of effects.values())URL.revokeObjectURL(url);effects.clear();for(const [i,f] of [...input.files].slice(0,10).entries())effects.set(i,URL.createObjectURL(f));renderFx();};
 function renderFx(){list.replaceChildren();for(const [i,url] of effects)list.append(b('เอฟเฟกต์ '+(i+1),()=>new Audio(url).play().catch(()=>{})));}body.append(input,list);renderFx();}
const previousTools=el('pc-other-tools').onclick;
el('pc-other-tools').onclick=()=>{previousTools?.();body.append(b('แก้ไข / นำเข้าเนื้อร้อง LRC',lyricEditor),b(rec?'หยุดบันทึกไมโครโฟน':'บันทึกไมโครโฟน',micRecording),b('เสียงเอฟเฟกต์หน้าเวที',stageEffects),b('สุ่มเพิ่มเพลง 5 รายการ',()=>{const pool=state.songs.filter(playable).slice().sort(()=>Math.random()-.5);for(const song of pool.slice(0,5))state.queue.push(song);renderQueue();d.close();}));};
ui.logout.addEventListener('click',()=>{if(rec){const r=rec;rec=null;r.stop();}for(const url of effects.values())URL.revokeObjectURL(url);effects.clear();});
})();
