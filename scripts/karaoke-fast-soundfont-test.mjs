import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const midiText=fs.readFileSync(new URL('../browser-midi.js',import.meta.url),'utf8');
const app=fs.readFileSync(new URL('../app.js',import.meta.url),'utf8');
const html=fs.readFileSync(new URL('../karaoke.html',import.meta.url),'utf8');
const version=JSON.parse(fs.readFileSync(new URL('../version.json',import.meta.url),'utf8'));
assert.equal(version.build,1143);
assert.ok(html.includes('browser-midi.js?v=1139-soundfont-extension'));
assert.ok(html.includes('app.js?v=1178-sqlite-only'));
assert.ok(app.includes('window.XStageBrowserMidi.prefersCompactGm?.()'));
assert.ok(app.includes('},12000);'),'Slow chosen SoundFont cannot hold first note for 45 seconds');

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
      ?[{id:'font-root',name:'SOUNDFONT',mimeType:'application/vnd.google-apps.folder'}]
      :parent==='font-root'
        ?[{id:'sf2-folder',name:'SF2',mimeType:'application/vnd.google-apps.folder'}]
        :parent==='sf2-folder'
          ?[{id:large,name:'Nong SoundFont SF2 (243 MB).sf2',size:String(243*1048576)},
            {id:'compact-37',name:'CT58MGM_V45.sf2',size:String(37*1048576)}]
          :[];
    return {ok:true,json:async()=>({files:folders})};
  }
  if(url.includes('alt=media')){
    largeDownloads++;
    return new Promise(()=>{}); // Simulate the user's stalled 243 MB download.
  }
  throw Error('Unexpected network request: '+url);
};
const ctx={
  navigator:{deviceMemory:8},
  document:{getElementById:id=>id==='xstage-soundfont-select'?select:null},
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
select.value=large;
select.onchange(); // Explicit large-bank choice may start a background fetch.
assert.equal(midi.prefersCompactGm(),true,
  'An unloaded user-selected 243 MB bank triggers fast GM for the song');
const quick=await midi.fastGmFont(auth.token);
assert.equal(quick,first,'Reuse the public GM bank after the user selects 243 MB');
assert.equal(publicFetches,1,'No duplicate public-bank fetch');
assert.ok(/GM 6 MB/.test(midi.fontStatus().warning),
  'The player must tell the user why it uses the fast bank');
assert.equal(largeDownloads,1,'The explicit large selection remains possible');
assert.equal(midi.isFastGmBytes(quick),true);
console.log('PASS: 243 MB saved SF2 cannot block first MIDI; validated 6 MB GM bank is reused');
