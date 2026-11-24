import fs from 'node:fs';
import assert from 'node:assert/strict';
const app=fs.readFileSync(new URL('../app.js',import.meta.url),'utf8');
// Extract only the pure folder browser; the following main-library picker
// registers live DOM listeners and must not be evaluated in this fixture.
const start=app.indexOf('function browseAuthorizedDriveFolders(');
const end=app.indexOf('async function openSharedLibraryPicker(',start);
assert.ok(start>=0&&end>start,'Folder browser source boundaries must exist');
const source=app.slice(start,end);
class Element{
  constructor(tag){this.tag=tag;this.children=[];this.style={};this.handlers={};this.open=false;this.disabled=false;}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  setAttribute(){} focus(){}
  addEventListener(type,fn){this.handlers[type]=fn;}
  showModal(){this.open=true;}
  close(){this.open=false;this.handlers.close?.();}
  remove(){this.removed=true;}
  click(){if(!this.disabled)this.handlers.click?.();}
}
const body=new Element('body'),doc={body,createElement:tag=>new Element(tag)};
const choose=new Function('document','isRetiredDriveRoot',source+';return browseAuthorizedDriveFolders;')(doc,id=>id==='retired123');
const folder=(id,name,parent)=>({id,name,mimeType:'application/vnd.google-apps.folder',parents:parent?[parent]:[]});
const seen=[];let active=true;
const list=async id=>{
  seen.push(id);
  if(id==='active123')return [
    folder('sound123','SoundFont',id),folder('sound123','SoundFont',id),
    folder('retired123','Old',id),folder('db0001','DB',id),
    folder('outside123','Outside','otherRoot'),folder('unknown123','Missing parent'),
    folder('active123','Cycle',id)
  ];
  if(id==='sound123')return [
    folder('nested123','SF2',id),folder('outside123','Outside','otherRoot'),
    folder('active123','Cycle',id),folder('cache123','CACHE',id)
  ];
  return [];
};
const wait=()=>new Promise(resolve=>setImmediate(resolve));
const find=(node,label)=>node.textContent===label?node:node.children.map(x=>find(x,label)).find(Boolean);
const run=()=>choose({rootId:'active123',kind:'soundfont',sameSession:()=>active,list,allowGrant:true});
let pending=run();await wait();let dialog=body.children.at(-1);
assert.equal(find(dialog,'📁 Old'),undefined);
assert.equal(find(dialog,'📁 DB'),undefined);
assert.equal(find(dialog,'📁 Outside'),undefined);
assert.equal(find(dialog,'📁 Missing parent'),undefined);
assert.equal(find(dialog,'📁 Cycle'),undefined);
const count=(node,label)=>(node.textContent===label?1:0)+node.children.reduce((n,x)=>n+count(x,label),0);
assert.equal(count(dialog,'📁 SoundFont'),1,'Duplicate IDs must not render twice');
assert.equal(find(dialog,'ใช้โฟลเดอร์นี้').disabled,true);
find(dialog,'📁 SoundFont').click();await wait();
assert.equal(find(dialog,'📁 Outside'),undefined);
assert.equal(find(dialog,'📁 Cycle'),undefined);
assert.equal(find(dialog,'📁 CACHE'),undefined);
find(dialog,'📁 SF2').click();await wait();
find(dialog,'ใช้โฟลเดอร์นี้').click();
assert.deepEqual(await pending,{id:'nested123',name:'SF2'});
assert.deepEqual(seen,['active123','sound123','nested123']);
assert.equal(dialog.removed,true);
pending=run();await wait();dialog=body.children.at(-1);
find(dialog,'ไม่พบโฟลเดอร์ · ขอสิทธิ์อ่านจาก Google').click();
assert.deepEqual(await pending,{grant:true});
pending=run();await wait();dialog=body.children.at(-1);
find(dialog,'ปิด / ยกเลิก').click();assert.equal(await pending,null);
pending=run();await wait();dialog=body.children.at(-1);
active=false;find(dialog,'📁 SoundFont').click();await wait();
assert.equal(find(dialog,'ใช้โฟลเดอร์นี้').disabled,true);
find(dialog,'ปิด / ยกเลิก').click();assert.equal(await pending,null);
console.log('PASS: OAuth-only folder navigation, direct-parent proof, duplicate/cycle exclusion, retired-root and reserved-folder exclusion, nested selection, explicit permission fallback and account isolation');
