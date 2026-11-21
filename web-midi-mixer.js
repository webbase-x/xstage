/* X-Stage Karaoke Online: Web Audio / SpessaSynth MIDI channel mixer.
 * Changes remain in this tab and are reset for each new MIDI song.
 * No system audio device, native DLL or private Drive access is required.
 */
(function(scope){
'use strict';
const rows=Array.from({length:16},()=>({level:100,mute:false,solo:false}));
const valid=channel=>Number.isInteger(channel)&&channel>=0&&channel<16;
let paint=()=>{};
function notify(){
  scope.dispatchEvent?.(new (scope.Event||Event)('xstage-midi-mixerchange'));
  paint();
}
function resetForSong(){
  for(const row of rows){row.level=100;row.mute=false;row.solo=false;}
  notify();
}
function getGain(channel){return valid(channel)?rows[channel].level/100:1;}
function isMuted(channel){
  if(!valid(channel))return false;
  return rows[channel].mute||(rows.some(row=>row.solo)&&!rows[channel].solo);
}
function setLevel(channel,level){
  if(!valid(channel)||!Number.isFinite(Number(level)))return;
  rows[channel].level=Math.max(0,Math.min(150,Math.round(Number(level))));
  notify();
}
function setMute(channel,muted){
  if(!valid(channel))return;
  rows[channel].mute=!!muted;notify();
}
function setSolo(channel,solo){
  if(!valid(channel))return;
  rows[channel].solo=!!solo;notify();
}
scope.XStageWebMidiMixer={isMuted,getGain,setLevel,setMute,setSolo,resetForSong,
  getChannel:channel=>valid(channel)?{...rows[channel]}:null};
const doc=scope.document;
if(!doc?.createElement)return;
function init(){
  if(doc.getElementById('web-midi-mixer-dialog'))return;
  const dialog=doc.createElement('dialog');
  dialog.id='web-midi-mixer-dialog';dialog.className='web-midi-mixer-dialog';
  const header=doc.createElement('header');
  const heading=doc.createElement('strong');heading.textContent='MIDI MIXER · 16 CHANNELS';
  const reset=doc.createElement('button');reset.type='button';reset.textContent='คืนค่า';
  reset.title='คืนเสียงทุกช่องเป็น 100% และยกเลิก Mute / Solo';
  reset.addEventListener('click',resetForSong);
  const close=doc.createElement('button');close.type='button';close.textContent='✕';
  close.setAttribute('aria-label','ปิด MIDI Mixer');
  close.addEventListener('click',()=>dialog.close());
  header.append(heading,reset,close);
  const help=doc.createElement('p');
  help.textContent='M = ปิดเสียงช่อง · S = ฟังเฉพาะช่องที่ Solo · ระดับเสียง 0–150% · ช่อง 10 เป็นกลอง (GM) การปรับใช้กับ MIDI ในแท็บนี้เท่านั้น';
  const content=doc.createElement('div');content.className='web-midi-mixer-channels';
  const controls=[];
  for(let ch=0;ch<16;ch++){
    const line=doc.createElement('div');line.className='web-midi-mixer-channel';
    const name=doc.createElement('span');name.className='web-midi-channel-name';
    name.textContent='ช่อง '+String(ch+1).padStart(2,'0')+(ch===9?' · กลอง':'');
    const mute=doc.createElement('button');mute.type='button';mute.textContent='M';
    mute.setAttribute('aria-label','ปิดเสียง MIDI ช่อง '+(ch+1));
    mute.addEventListener('click',()=>setMute(ch,!rows[ch].mute));
    const solo=doc.createElement('button');solo.type='button';solo.textContent='S';
    solo.setAttribute('aria-label','Solo MIDI ช่อง '+(ch+1));
    solo.addEventListener('click',()=>setSolo(ch,!rows[ch].solo));
    const slider=doc.createElement('input');slider.type='range';slider.min='0';
    slider.max='150';slider.step='1';slider.value='100';
    slider.setAttribute('aria-label','ระดับเสียง MIDI ช่อง '+(ch+1));
    slider.addEventListener('input',()=>setLevel(ch,slider.value));
    const amount=doc.createElement('output');amount.textContent='100%';
    line.append(name,mute,solo,slider,amount);content.append(line);
    controls.push({mute,solo,slider,amount});
  }
  paint=()=>{
    for(let ch=0;ch<16;ch++){
      const row=rows[ch],view=controls[ch];
      view.mute.setAttribute('aria-pressed',String(row.mute));
      view.solo.setAttribute('aria-pressed',String(row.solo));
      view.slider.value=String(row.level);
      view.amount.textContent=row.level+'%';
      view.mute.classList.toggle('active',row.mute);
      view.solo.classList.toggle('active',row.solo);
    }
  };
  dialog.append(header,help,content);doc.body.append(dialog);
  const open=()=>{
    paint();
    if(typeof dialog.showModal==='function')dialog.showModal();
    else dialog.setAttribute('open','');
  };
  const buttons=[
    {anchor:'pc-eq',label:'MIDI Mixer',id:'pc-midi-mixer'},
    {anchor:'mobile-eq',label:'🎚 MIDI Mixer 16 ช่อง',id:'mobile-midi-mixer'}
  ];
  for(const config of buttons){
    const anchor=doc.getElementById(config.anchor);
    if(!anchor||doc.getElementById(config.id))continue;
    const button=doc.createElement('button');
    button.type='button';button.id=config.id;button.textContent=config.label;
    button.addEventListener('click',open);anchor.after(button);
  }
  paint();
}
if(doc.readyState==='loading')doc.addEventListener('DOMContentLoaded',init,{once:true});
else init();
})(typeof window!=='undefined'?window:globalThis);
