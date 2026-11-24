import fs from 'node:fs';
import assert from 'node:assert/strict';
const app=fs.readFileSync(new URL('../app.js',import.meta.url),'utf8');
const source=app.slice(app.indexOf('function browseAuthorizedDriveFolders('),app.indexOf('async function chooseUserDriveSource('));
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
const folder=(id,name)=>({id,name,mimeType:'application/vnd.google-apps.folder'});
const seen=[];let active=true;
const list=async id=>{seen.push(id);return id==='active123'?[folder('sound123','SoundFont'),folder('retired123','Old'),folder('db0001','DB')]:[folder('nested123','SF2')];};
const wait=()=>new Promise(resolve=>setImmediate(resolve));
const find=(node,label)=>node.textContent===label?node:node.children.map(x=>find(x,label)).find(Boolean);
const run=()=>choose({rootId:'active123',kind:'soundfont',sameSession:()=>active,list,allowGrant:true});
let pending=run();await wait();let dialog=body.children.at(-1);
assert.equal(find(dialog,'📁 Old'),undefined);
assert.equal(find(dialog,'📁 DB'),undefined);
assert.equal(find(dialog,'ใช้โฟลเดอร์นี้').disabled,true);
find(dialog,'📁 SoundFont').click();await wait();
find(dialog,'📁 SF2').click();await wait();
find(dialog,'ใช้โฟลเดอร์นี้').click();
assert.deepEqual(await pending,{id:'nested123',name:'SF2'});
assert.deepEqual(seen,['active123','sound123','nested123']);
assert.equal(dialog.removed,true);
pending=run();await wait();dialog=body.children.at(-1);
find(dialog,'ไม่พบโฟลเดอร์ · ขอสิทธิ์เพิ่มเติมผ่าน Google Picker').click();
assert.deepEqual(await pending,{grant:true});
pending=run();await wait();dialog=body.children.at(-1);
find(dialog,'ปิด / ยกเลิก').click();assert.equal(await pending,null);
pending=run();await wait();dialog=body.children.at(-1);
active=false;find(dialog,'📁 SoundFont').click();await wait();
assert.equal(find(dialog,'ใช้โฟลเดอร์นี้').disabled,true);
find(dialog,'ปิด / ยกเลิก').click();assert.equal(await pending,null);
console.log('PASS: OAuth-only folder navigation, retired-root exclusion, nested selection, explicit permission fallback and account isolation');
