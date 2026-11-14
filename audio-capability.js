/* X-Stage V4 audio capability and playback advisor. No device fingerprinting,
 * remote service, persistent SoundFont download, or Drive write. */
(function(scope){
'use strict';
const MB=1048576, MAX_FONT=256*MB;
const $=id=>document.getElementById(id);
const fmt=bytes=>Number.isFinite(bytes)&&bytes>=0
  ?(bytes>=1073741824?(bytes/1073741824).toFixed(2)+' GB':
    bytes>=MB?(bytes/MB).toFixed(1)+' MB':(bytes/1024).toFixed(0)+' KB'):'ไม่ทราบ';
const types=['MIDI','KAR','NCN','M4A','MP3','WAV','AAC','FLAC','OGG','VIDEO','OTHER'];
const guide=[
  ['MIDI / KAR','คำสั่งโน้ต ไม่ใช่ไฟล์เสียง ความสมจริงขึ้นกับตัวสังเคราะห์และ SoundFont · ปรับคีย์/แชนเนลได้'],
  ['NCN','ใช้ MID + LYR + CUR · เล่นด้วย MIDI และเวลาคำร้องที่ตรวจสอบแล้ว · ห้ามแก้ CUR ต้นฉบับ'],
  ['MIDI + SF2/SF3','คุณภาพขึ้นกับชุดตัวอย่างเสียงและ Engine · ใช้ RAM มากกว่า MIDI พื้นฐาน ไม่มีการรับประกันเสียงเท่า FluidSynth'],
  ['M4A','ภาชนะไฟล์เสียง อาจเป็น AAC (บีบอัดสูญเสีย) หรือ ALAC (ไม่สูญเสีย) · ฟังเสียงตามต้นฉบับ'],
  ['MP3 / AAC / OGG','โดยทั่วไปบีบอัดแบบสูญเสียคุณภาพ ขึ้นกับบิตเรต · ใช้ทรัพยากรน้อยกว่าเรนเดอร์ MIDI'],
  ['WAV / FLAC','WAV PCM และ FLAC ส่วนใหญ่ไม่สูญเสียคุณภาพ · ไฟล์อาจใหญ่กว่าแต่ไม่ได้แปลว่าเสียงต้นฉบับดีกว่า'],
  ['วิดีโอ','คุณภาพภาพ/เสียงขึ้นกับ Codec ความละเอียดและบิตเรต · ตรวจความเข้ากันได้กับเบราว์เซอร์/ทีวี'],
];
const validId=media=>typeof media?.fileId==='string'&&!!media.fileId;
function classifySong(song){
  if(!song||typeof song!=='object')return 'OTHER';
  const source=String(song.sourceFormat||song.source_format||'').trim().toUpperCase();
  if(source==='NCN')return 'NCN';
  if(source==='KAR')return 'KAR';
  if(['VIDEO','VDO','MP4','WEBM','AVI','MPEG','MPG','DAT','VOB','MKV','MOV','WMV','FLV'].includes(source))return 'VIDEO';
  if(['MID','MIDI'].includes(source))return 'MIDI';
  if(['M4A','MP3','WAV','AAC','FLAC','OGG','OGA'].includes(source))
    return source==='OGA'?'OGG':source;
  if(validId(song.video))return 'VIDEO';
  if(validId(song.midi))return 'MIDI';
  const name=String(song.audio?.path||song.audio?.name||'').split(/[?#]/)[0];
  const ext=name.match(/\.([a-z\d]+)$/i)?.[1]?.toUpperCase();
  return types.includes(ext)?ext:'OTHER';
}
function countSongs(songs){
  const counts=Object.fromEntries(types.map(key=>[key,0]));
  for(const song of (Array.isArray(songs)?songs:[]))counts[classifySong(song)]++;
  return counts;
}
function normalizeProfile(profile={}){
  const cores=Number.isFinite(profile.cores)&&profile.cores>=1?Math.floor(profile.cores):null;
  const ramGB=Number.isFinite(profile.ramGB)&&profile.ramGB>0?profile.ramGB:null;
  const quota=Number.isFinite(profile.quota)&&profile.quota>0?profile.quota:null;
  const usage=Number.isFinite(profile.usage)&&profile.usage>=0?profile.usage:null;
  return {cores,ramGB,quota,usage,
    freeQuota:quota!==null&&usage!==null?Math.max(0,quota-usage):null,
    offlineAudio:profile.offlineAudio!==false,webAudio:profile.webAudio!==false,
    video:profile.video!==false,source:profile.source||'browser'};
}
async function probeDevice(){
  const nav=typeof navigator==='object'?navigator:{};
  let quota=null,usage=null;
  try{
    if(typeof nav.storage?.estimate==='function'){
      const e=await Promise.race([nav.storage.estimate(),
        new Promise(resolve=>setTimeout(()=>resolve(null),1800))]);
      if(e&&Number.isFinite(e.quota)&&Number.isFinite(e.usage)){
        quota=e.quota;usage=e.usage;
      }
    }
  }catch{}
  const video=document.createElement?.('video');
  const codecSupport=!!video?.canPlayType?.('video/mp4; codecs="avc1.42E01E, mp4a.40.2"');
  return normalizeProfile({
    cores:Number(nav.hardwareConcurrency)||null,
    ramGB:Number(nav.deviceMemory)||null,
    quota,usage,video:codecSupport,
    offlineAudio:typeof scope.OfflineAudioContext==='function',
    webAudio:!!(scope.AudioContext||scope.webkitAudioContext),
    source:'browser'
  });
}
function assessFont(bytes,device){
  const p=normalizeProfile(device);
  const size=Number(bytes);
  if(!Number.isFinite(size)||size<0)return {
    level:'caution',downloadBytes:null,estimatedRamBytes:null,
    text:'ไม่มีข้อมูลขนาด SoundFont · ต้องตรวจไฟล์ก่อนโหลด',freeQuota:p.freeQuota
  };
  const estimatedRamBytes=Math.ceil(size*3+96*MB);
  let level='safe',notes=[];
  if(size>MAX_FONT){level='blocked';notes.push('เกินขีดจำกัด Web 256 MB');}
  if(p.ramGB===null){
    if(level!=='blocked')level='caution';
    notes.push('เบราว์เซอร์ไม่แจ้ง RAM');
  }else if(estimatedRamBytes>p.ramGB*1073741824*.48){
    level='blocked';notes.push('RAM ประมาณการไม่เพียงพอ');
  }else if(estimatedRamBytes>p.ramGB*1073741824*.24&&level!=='blocked'){
    level='caution';notes.push('ใช้ RAM ค่อนข้างสูง');
  }
  if(p.cores!==null&&p.cores<4&&level==='safe'){level='caution';notes.push('CPU มีคอร์น้อย');}
  if(p.freeQuota!==null&&p.freeQuota<size*1.1&&level==='safe'){
    // This is only a browser-storage quota advisory. SoundFonts are kept in RAM.
    level='caution';notes.push('โควตาพื้นที่แคชเบราว์เซอร์ต่ำ (ไม่ได้บันทึก SoundFont ถาวร)');
  }
  if(!p.offlineAudio){level='blocked';notes.push('ไม่มี OfflineAudioContext');}
  if(!notes.length)notes.push('เหมาะกับความพร้อมที่เบราว์เซอร์รายงาน');
  return {level,downloadBytes:size,estimatedRamBytes,freeQuota:p.freeQuota,
    text:notes.join(' · ')};
}
function recommend(song,profile={},preference='auto',font=null){
  const p=normalizeProfile(profile);
  const midi=validId(song?.midi),audio=validId(song?.audio),video=validId(song?.video);
  const fontResult=font&&Number.isFinite(font.size)?assessFont(font.size,p):null;
  const fontReady=!!(font?.id&&fontResult&&fontResult.level!=='blocked');
  const output=(mode,explanation)=>({
    mode,useMidi:mode==='midi'||mode==='soundfont',
    useFont:mode==='soundfont',useVideo:mode==='video',
    explanation,available:{midi,audio,video,font:fontReady}
  });
  if(!midi&&!audio)return output('none','เพลงนี้ไม่มีไฟล์เสียงหรือ MIDI ที่พร้อมเล่น');
  if(preference==='midi'&&midi)return output('midi','เลือก MIDI พื้นฐาน ไม่ดาวน์โหลด SoundFont');
  if(preference==='soundfont'&&midi&&fontReady)return output('soundfont',
    'เลือก MIDI + SoundFont · หน่วยความจำที่ต้องใช้เป็นการประมาณ');
  if(preference==='audio'&&audio)return output('audio','เลือกใช้เสียงจากไฟล์จริง (ไม่มีการปรับคีย์แบบ MIDI)');
  if(preference==='video'&&video&&audio&&p.video)return output('video',
    'เล่นเสียงที่ตรวจสอบพร้อมภาพวิดีโอ ถ้า Codec ไม่รองรับจะใช้เสียงอย่างเดียว');
  if(audio){
    if(preference==='auto'&&video&&p.video&&(p.cores===null||p.cores>=4)&&
      (p.ramGB===null||p.ramGB>=2))return output('video','แนะนำภาพวิดีโอพร้อมเสียงต้นฉบับ');
    return output('audio','แนะนำไฟล์เสียงต้นฉบับ ประหยัด CPU/RAM กว่าการเรนเดอร์ MIDI');
  }
  if(fontReady&&(p.cores===null||p.cores>=4)&&
     (fontResult.level==='safe'||preference==='soundfont'))
    return output('soundfont','ใช้ MIDI + SoundFont ตามที่เลือกไว้');
  return output('midi','ใช้ MIDI พื้นฐานเพื่อลดการใช้ RAM/การโหลด SoundFont');
}
function formatSummary(counts){
  return types.filter(key=>counts[key]).map(key=>key+' '+counts[key].toLocaleString('th-TH')).join(' · ')||'ยังไม่มีเพลง';
}
const state={profile:null,songs:[],fontFiles:[],mixer:null,activeSong:null};
function profileSync(){
  if(!state.profile)state.profile=normalizeProfile({
    cores:Number(navigator?.hardwareConcurrency)||null,
    ramGB:Number(navigator?.deviceMemory)||null,
    video:true,offlineAudio:typeof scope.OfflineAudioContext==='function'
  });
  return state.profile;
}
function showProfile(){
  const el=$('xstage-device-profile');if(!el)return;
  const p=profileSync();
  const ram=p.ramGB===null?'ไม่เปิดเผย RAM':p.ramGB+' GB (เบราว์เซอร์รายงาน)';
  const cpu=p.cores===null?'ไม่เปิดเผย CPU':'CPU logical '+p.cores+' คอร์';
  const space=p.freeQuota===null?'พื้นที่โควตาเบราว์เซอร์: ไม่ทราบ':
    'โควตาเบราว์เซอร์ที่เหลือ '+fmt(p.freeQuota);
  el.textContent=cpu+' · '+ram+' · '+space+
    ' · ไม่ใช่พื้นที่ว่างจริงของทั้งเครื่อง';
}
function renderStats(songs){
  state.songs=Array.isArray(songs)?songs:[];
  const counts=countSongs(state.songs);
  const el=$('xstage-format-counts');if(el)el.textContent=formatSummary(counts);
  return counts;
}
function getSettings(){
  const transpose=Math.max(-12,Math.min(12,Math.trunc(Number($('xstage-midi-transpose')?.value)||0)));
  const rows=[...($('xstage-midi-channels')?.querySelectorAll?.('[data-midi-channel]')||[])];
  const channels=Array.from({length:16},(_,i)=>({gain:1,mute:false,solo:false}));
  for(const row of rows){
    const i=Number(row.dataset.midiChannel);
    if(!Number.isInteger(i)||i<0||i>15)continue;
    const mute=row.querySelector('[data-action="mute"]');
    const solo=row.querySelector('[data-action="solo"]');
    const gain=row.querySelector('[data-action="gain"]');
    channels[i]={mute:!!mute?.checked,solo:!!solo?.checked,
      gain:Math.max(0,Math.min(1,Number(gain?.value||0)/100))};
  }
  return {transpose,channels};
}
function populateChannelMixer(){
  const container=$('xstage-midi-channels');if(!container)return;
  for(let i=0;i<16;i++){
    const row=document.createElement('div');row.className='xstage-channel';row.dataset.midiChannel=String(i);
    const label=document.createElement('strong');label.textContent='Ch '+(i+1)+(i===9?' กลอง':'');
    const makeCheck=(action,text)=>{
      const wrap=document.createElement('label');
      const input=document.createElement('input');input.type='checkbox';input.dataset.action=action;
      wrap.append(input,document.createTextNode(text));return wrap;
    };
    const gain=document.createElement('input');gain.type='range';gain.min='0';gain.max='100';gain.value='100';gain.step='1';
    gain.dataset.action='gain';gain.setAttribute('aria-label','ระดับเสียง Ch '+(i+1));
    const output=document.createElement('output');output.textContent='100%';
    gain.addEventListener('input',()=>{output.textContent=gain.value+'%';});
    row.append(label,makeCheck('mute','Mute'),makeCheck('solo','Solo'),gain,output);
    container.append(row);
  }
}
function updateAdvice(){
  const el=$('xstage-mode-advice');if(!el)return;
  const choice=$('xstage-play-mode')?.value||'auto';
  const font=scope.XStageBrowserMidi?.selectedFontInfo?.()||null;
  const rec=recommend(state.activeSong,profileSync(),choice,font);
  el.textContent=rec.explanation;
  el.dataset.level=rec.mode==='none'?'blocked':'safe';
}
function renderFontList(files){
  state.fontFiles=Array.isArray(files)?files:[];
  const el=$('xstage-font-file-list');if(!el)return;
  el.replaceChildren();
  if(!state.fontFiles.length){el.textContent='ยังไม่มี SoundFont ใน XStageWeb/AUDIO';return;}
  for(const f of state.fontFiles){
    const report=assessFont(Number(f.size),profileSync());
    const line=document.createElement('div');line.className='xstage-font-row';
    line.dataset.level=report.level;
    const name=document.createElement('strong');name.textContent=f.name;
    const detail=document.createElement('span');detail.textContent=
      'ไฟล์ '+fmt(report.downloadBytes)+' · RAM เพิ่มโดยประมาณ '+fmt(report.estimatedRamBytes)+
      ' · ถ้าเก็บออฟไลน์จะใช้ '+fmt(report.downloadBytes)+' · '+report.text;
    line.append(name,detail);el.append(line);
  }
}
async function updateProfile(){
  state.profile=await probeDevice();
  showProfile();renderFontList(state.fontFiles);updateAdvice();
  return state.profile;
}
function onSong(song){
  state.activeSong=song||null;
  const label=$('xstage-song-format');
  if(label)label.textContent=song?'ประเภทต้นฉบับ: '+classifySong(song):'ยังไม่ได้เลือกเพลง';
  updateAdvice();
}
scope.XStageAudioAdvisor={MB,MAX_FONT,types,guide,fmt,classifySong,countSongs,
  normalizeProfile,probeDevice,assessFont,recommend,
  get profile(){return profileSync();},
  refreshProfile:updateProfile,renderStats,renderFontList,onSong,
  getMidiSettings:getSettings,
  resolve(song,preference=null,font=null){return recommend(song,profileSync(),
    preference||$('xstage-play-mode')?.value||'auto',font??scope.XStageBrowserMidi?.selectedFontInfo?.());},
  clear(){renderStats([]);onSong(null);renderFontList([]);}
};
function initialize(){
  const guideEl=$('xstage-format-guide');
  if(guideEl){
    for(const [name,description] of guide){
      const row=document.createElement('p');
      const title=document.createElement('strong');title.textContent=name+' — ';
      row.append(title,document.createTextNode(description));guideEl.append(row);
    }
  }
  populateChannelMixer();
  const panel=$('xstage-audio-tools'),open=$('toggle-audio-tools'),mobile=$('mobile-audio-tools-toggle');
  const show=value=>{
    if(!panel)return;
    panel.hidden=!value;
    open?.setAttribute('aria-expanded',String(value));
    mobile?.setAttribute('aria-expanded',String(value));
    if(value)void updateProfile();
  };
  open?.addEventListener('click',()=>show(panel?.hidden));
  mobile?.addEventListener('click',()=>show(panel?.hidden));
  $('xstage-audio-close')?.addEventListener('click',()=>show(false));
  $('xstage-profile-refresh')?.addEventListener('click',()=>{void updateProfile();});
  $('xstage-play-mode')?.addEventListener('change',updateAdvice);
  $('xstage-midi-apply')?.addEventListener('click',()=>{
    scope.dispatchEvent(new CustomEvent('xstage:midi-settings-apply',
      {detail:getSettings()}));
  });
  $('xstage-midi-reset')?.addEventListener('click',()=>{
    if($('xstage-midi-transpose'))$('xstage-midi-transpose').value='0';
    for(const row of $('xstage-midi-channels')?.querySelectorAll('[data-midi-channel]')||[]){
      row.querySelector('[data-action="mute"]').checked=false;
      row.querySelector('[data-action="solo"]').checked=false;
      const input=row.querySelector('[data-action="gain"]');input.value='100';
      row.querySelector('output').textContent='100%';
    }
    scope.dispatchEvent(new CustomEvent('xstage:midi-settings-apply',
      {detail:getSettings()}));
  });
  scope.addEventListener('xstage:catalog-updated',e=>renderStats(e.detail?.songs));
  scope.addEventListener('xstage:song-selected',e=>onSong(e.detail?.song));
  scope.addEventListener('xstage:fonts-updated',e=>renderFontList(e.detail?.files));
  scope.addEventListener('xstage:auth-cleared',()=>scope.XStageAudioAdvisor.clear());
  showProfile();updateAdvice();void updateProfile();
}
if(typeof document==='object'&&document.getElementById('xstage-audio-tools'))initialize();
})(typeof window!=='undefined'?window:globalThis);
