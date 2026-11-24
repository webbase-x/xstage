import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const code=fs.readFileSync(new URL('../browser-midi.js',import.meta.url),'utf8');
const sizes=[230569982,172456754,255310812,99663650,45605786,15873406,38651222];
const files=sizes.map((size,i)=>({id:'bank-'+i,name:'Bank '+i+(i%2?'.sf2':'.SF2'),size:String(size),mimeType:'application/octet-stream'}));
let full=false,pages=[],privateDownloads=0,folderParent='activeRoot',incomplete=false;
const verified=[];
const select={options:[],value:'',replaceChildren(...items){this.options=items;this.value=items[0]?.value||'';},append(...items){this.options.push(...items);},get selectedOptions(){return this.options.filter(x=>x.value===this.value);}};
const permission={hidden:true,style:{}},status={textContent:''};
class Option{constructor(text,value){this.text=text;this.value=value;this.dataset={};}}
const ctx={navigator:{deviceMemory:2},document:{getElementById:id=>({'xstage-soundfont-select':select,'xstage-soundfont-authorize':permission,'xstage-drive-font-permission-status':status})[id]},
 XStageDriveReadAccess:()=>full,
 XStageCloudImport:{Drive:class{
   constructor(token){this.token=token;}
   async folderMetadata(id){
     assert.equal(this.token(),'test-token');
     verified.push(id);
     if(id==='selectedFolder')return {id,name:'SoundFont',mimeType:'application/vnd.google-apps.folder',parents:[folderParent],trashed:false};
     assert.equal(id,'otherRoot');
     return {id,name:'Other',mimeType:'application/vnd.google-apps.folder',parents:['root'],trashed:false};
   }
 }},
 localStorage:{getItem:key=>key==='xstage-drive-source-folders-v1'?JSON.stringify({'account:activeRoot':{soundfont:{id:'selectedFolder',name:'SoundFont'}}}):null,setItem(){}},
 Option,CustomEvent:class{},URLSearchParams,Uint8Array,ArrayBuffer,DataView,TextEncoder,TextDecoder,Blob,DOMException,setTimeout,clearTimeout,console,dispatchEvent(){},addEventListener(){},
 fetch:async(url,opts)=>{
   if(String(url).includes('raw.githubusercontent.com'))return {ok:false,status:503};
   if(String(url).includes('alt=media')){privateDownloads++;throw Error('inventory must not download private banks');}
   const params=new URL(String(url)).searchParams;
   assert.equal(opts.headers.Authorization,'Bearer test-token');
   assert.match(params.get('q'),/'selectedFolder' in parents/);
   pages.push(params.get('pageToken')||'first');
   return {ok:true,json:async()=>incomplete?{files:[files[0]],incompleteSearch:true}:!full?{files:[files[0]]}:params.get('pageToken')?{files:[...files.slice(3),files[0]]}:{files:files.slice(0,3),nextPageToken:'next'}};
 }};
ctx.window=ctx;
// Exercise production folder ancestry validation, not a permissive stub.
vm.runInNewContext(fs.readFileSync(new URL('../cloud-drive-folders.js',import.meta.url),'utf8'),ctx);
vm.runInNewContext(code,ctx);
const auth={token:'test-token',sub:'account',rootId:'activeRoot'};
await ctx.XStageBrowserMidi.refreshFonts(auth);
assert.equal(select.options.length,2);
assert.equal(permission.hidden,false);
assert.match(status.textContent,/อาจยังไม่ครบ/);
full=true;pages=[];
await ctx.XStageBrowserMidi.refreshFonts(auth);
assert.equal(select.options.length,8,'Seven banks plus builtin, even on 2GB device');
assert.equal(new Set(select.options.map(x=>x.value)).size,8);
assert.deepEqual(pages,['first','next']);
assert.equal(permission.hidden,true);
assert.match(status.textContent,/พบ SoundFont 7 ไฟล์/);
assert.deepEqual(verified,['selectedFolder','selectedFolder']);
folderParent='otherRoot';pages=[];
await ctx.XStageBrowserMidi.refreshFonts(auth);
assert.equal(pages.length,0,'Unrelated source must not be listed');
assert.match(status.textContent,/อ่านรายการไม่ได้/);
assert.ok(select.options.some(x=>x.disabled),'Error option must be shown');
folderParent='activeRoot';incomplete=true;pages=[];
await ctx.XStageBrowserMidi.refreshFonts(auth);
assert.deepEqual(pages,['first']);
assert.match(status.textContent,/ค้นหาไม่ครบ/);
assert.ok(select.options.some(x=>x.disabled));
assert.equal(privateDownloads,0);
console.log('PASS: all seven paginated SoundFonts remain listed independently of RAM; limited scope remains visible');
