import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const midiText=fs.readFileSync(new URL('../browser-midi.js',import.meta.url),'utf8');
const app=fs.readFileSync(new URL('../app.js',import.meta.url),'utf8');
const html=fs.readFileSync(new URL('../karaoke.html',import.meta.url),'utf8');
const version=JSON.parse(fs.readFileSync(new URL('../version.json',import.meta.url),'utf8'));
assert.ok(version.build>=1144,'revision must not regress');
assert.ok(/browser-midi\.js\?v=\d+/.test(html));
assert.ok(/app\.js\?v=\d+/.test(html));
assert.ok(app.includes('window.XStageBrowserMidi.prefersCompactGm?.()'));
assert.ok(app.includes('setTimeout(()=>resolve({expired:true}),12000)'),
  'Slow chosen SoundFont must have a bounded 12-second startup wait');

const large='large-font-243mb',bank=new Uint8Array(120000);
bank.set([82,73,70,70],0);
new DataView(bank.buffer).setUint32(4,bank.byteLength-8,true);
bank.set([115,102,98,107],8);
const auth={sub:'account',rootId:'root',token:'private-token'};
let publicFetches=0,largeDownloads=0;
const driveParents=[];
class Option{
  constructor(text,value){this.text=text;this.value=value;this.dataset={};}
}
class CustomEvent{
  constructor(type,{detail}={}){this.type=type;this.detail=detail;}
}
const select={
  options:[],value:'',
  replaceChildren(...options){this.options=options;this.value=options[0]?.value||'';},
  get selectedOptions(){return this.options.filter(x=>x.value===this.value);}
};
const permission={hidden:true,style:{display:'none'}},sourceStatus={textContent:''};
let explicitFolder='',fullRead=false,confirmLoad=false,confirmations=0;
const saved=new Map([['xstage-font-pref:account:root',large]]);
const fakeFetch=async(url,options={})=>{
  url=String(url);
  if(url.includes('raw.githubusercontent.com')){
    publicFetches++;
    assert.equal(options.cache,'force-cache');
    assert.equal(options.headers,undefined,'Public GM request never carries Drive auth');
    return {ok:true,headers:{get:()=>String(bank.byteLength)},
      arrayBuffer:async()=>bank.buffer.slice(0)};
  }
  if(url.includes('/drive/v3/files?')){
    assert.equal(options.headers.Authorization,'Bearer '+auth.token);
    const q=new URL(url).searchParams.get('q');
    const parent=q.match(/'([^']+)' in parents/)?.[1]||'';
    driveParents.push({q,parent});
    const folders=parent==='root'
      ?[{id:'font-root',name:'SoundFont',mimeType:'application/vnd.google-apps.folder'}]
      :parent==='font-root'
        ?[{id:'sf2-folder',name:'SF2',mimeType:'application/vnd.google-apps.folder'}]
        :parent==='sf2-folder'
          ?[{id:large,name:'Nong SoundFont SF2 (243 MB).sf2',size:String(243*1048576)},
            {id:'compact-37',name:'CT58MGM_V45.sf2',size:String(37*1048576)}, {id:'nested',name:'Custom banks',mimeType:'application/vnd.google-apps.folder'}]
          :parent==='nested'?[{id:'nested-font',name:'Nested.SF3',size:'12345'}]:[];
    return {ok:true,json:async()=>({files:folders})};
  }
  if(url.includes('alt=media')){
    largeDownloads++;
    return new Promise(()=>{}); // Simulate the user's stalled 243 MB download.
  }
  throw Error('Unexpected network request: '+url);
};
const ctx={
  navigator:{userAgent:'iPhone'},
  confirm:()=>{confirmations++;return confirmLoad;},
  document:{getElementById:id=>id==='xstage-soundfont-select'?select:id==='xstage-soundfont-authorize'?permission:id==='xstage-drive-font-permission-status'?sourceStatus:null},
  XStageDriveReadAccess:()=>fullRead,
  XStageDriveFolders:{readSelections:()=>explicitFolder?{soundfont:{id:explicitFolder,name:'Selected'}}:{}},
  localStorage:{getItem:k=>saved.get(k)||null,setItem:(k,v)=>saved.set(k,v)},
  fetch:fakeFetch,Option,CustomEvent,
  dispatchEvent(){},addEventListener(){},console,
  Blob,TextEncoder,TextDecoder,Uint8Array,ArrayBuffer,DataView,URLSearchParams,
  setTimeout,clearTimeout,DOMException
};
ctx.window=ctx;
vm.runInNewContext(midiText,ctx,{filename:'browser-midi.js'});
const midi=ctx.XStageBrowserMidi;
await midi.refreshFonts(auth);
assert.equal(select.value,'builtin:TimGM6mb',
  'A 243 MB preference must select a sampled 6 MB GM bank for fast startup');
assert.equal(saved.get('xstage-font-pref:account:root'),large,
  'A fast start must not destroy the saved private-bank preference');
assert.equal(largeDownloads,0,'Do not download 243 MB automatically on login');
const first=await midi.selectedFont(auth.token);
assert.equal(first.byteLength,bank.byteLength,'Public GM must have real validated samples');
assert.equal(publicFetches,1);
assert.ok(select.options.some(option=>option.value===large),
  'The SOUNDFONT/SF2 browser picker must expose the 243 MB file: '+
  JSON.stringify({parents:driveParents,options:select.options.map(option=>({value:option.value,size:option.dataset?.size}))}));
assert.ok(select.options.some(option=>option.value==='nested-font'),'Nested SoundFont must appear');
select.value=large;
select.onchange();
assert.equal(select.value,'builtin:TimGM6mb','Cancelling confirmation retains current font');
assert.equal(largeDownloads,0);
assert.equal(confirmations,1);
confirmLoad=true;
select.value=large;
select.onchange(); // Explicit large-bank choice may start a background fetch.
await new Promise(resolve=>setTimeout(resolve,0));
assert.equal(midi.prefersCompactGm(),true,
  'An unloaded user-selected 243 MB bank triggers fast GM for the song');
const quick=await midi.fastGmFont(auth.token);
assert.equal(quick,first,'Reuse the public GM bank after the user selects 243 MB');
assert.equal(publicFetches,1,'No duplicate public-bank fetch');
assert.ok(/GM 6 MB/.test(midi.fontStatus().warning),
  'The player must tell the user why it uses the fast bank');
assert.equal(largeDownloads,1,'The explicit large selection remains possible');
assert.equal(midi.isFastGmBytes(quick),true);
assert.equal(permission.hidden,true,'Already accessible SoundFonts require no extra grant');
explicitFolder='empty-folder';
await midi.refreshFonts(auth);
assert.equal(permission.hidden,false,'An empty explicit source offers permission recovery');
assert.match(sourceStatus.textContent,/พบ SoundFont 0 ไฟล์/);
explicitFolder='font-root';
await midi.refreshFonts(auth);
assert.equal(permission.hidden,false,'A nonempty but limited scan still offers permission recovery');
assert.match(sourceStatus.textContent,/อาจยังไม่ครบ/);
fullRead=true;
await midi.refreshFonts(auth);
assert.equal(permission.hidden,true,'Verified full read hides permission recovery');
assert.ok(select.options.some(option=>option.value==='nested-font'));
console.log('PASS: 243 MB saved SF2 cannot block first MIDI; validated 6 MB GM bank is reused');
