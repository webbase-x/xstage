import assert from 'node:assert/strict';
import fs from 'node:fs';
const app=fs.readFileSync(new URL('../app.js',import.meta.url),'utf8');
const begin=app.indexOf('async function resolvePcDriveLink(');
const end=app.indexOf('\nfunction playable(',begin);
assert.ok(begin>0&&end>begin,'Web must expose the on-demand PC Drive ID resolver');
const code=app.slice(begin,end);
const root='xstageRoot12345',token='user-token';
const state={libraryRootId:root,token};
const folder='application/vnd.google-apps.folder';
const files=[
 {id:'songsFolder100',name:'SONGS',parents:[root],mimeType:folder},
 {id:'midiFolder100',name:'MIDI',parents:['songsFolder100'],mimeType:folder},
 {id:'xmidFolder100',name:'XMID',parents:['midiFolder100'],mimeType:folder},
 {id:'bucketFolder100',name:'1',parents:['xmidFolder100'],mimeType:folder},
 {id:'actualDriveSong100',name:'10001.xmid',parents:['bucketFolder100'],
  mimeType:'application/octet-stream',size:'300',md5Checksum:'a'.repeat(32)}
];
let queries=0;
const resolver=new Function('state','driveList','getFileId','DOMException',
  code+';return resolvePcDriveLink;')(state,async q=>{
    queries++;
    const match=q.match(/^'([^']+)' in parents and name='([^']+)' and trashed=false$/);
    assert.ok(match,'resolver must constrain parent and exact filename in Drive query');
    return files.filter(x=>x.parents.includes(match[1])&&x.name===match[2]);
  },media=>media?.fileId||'',DOMException);
const song=()=>({pendingDriveLink:true,xmid:{fileId:'',
  path:'SONGS/MIDI/XMID/1/10001.xmid',size:300,
  md5Checksum:'a'.repeat(32)}});
const expected=song();
await resolver(expected,token);
assert.equal(expected.xmid.fileId,'actualDriveSong100');
assert.equal(expected.pendingDriveLink,false);
assert.equal(queries,5,'Lookup must only walk the selected library hierarchy');
await resolver(expected,token);
assert.equal(queries,5,'Linked songs do not re-query Drive on each play');
const wrongMD5=song();wrongMD5.xmid.md5Checksum='b'.repeat(32);
await assert.rejects(resolver(wrongMD5,token),/MD5/);
assert.equal(wrongMD5.xmid.fileId,'');
const wrongSize=song();wrongSize.xmid.size=299;
await assert.rejects(resolver(wrongSize,token),/ขนาด\/MD5/);
for(const pathname of ['../10001.xmid','SONGS/../secret.xmid',
                        'OTHER/MIDI/XMID/1/10001.xmid','SONGS/C:/fake.xmid']){
 const bad=song();bad.xmid.path=pathname;
 await assert.rejects(resolver(bad,token),/ไม่ปลอดภัย/);
}
// A portable catalog may use the chosen source as SONGS itself.
files.push({id:'flatDriveSong100',name:'flat.xmid',parents:['songsFolder100'],
  mimeType:'application/octet-stream',size:'300',md5Checksum:'a'.repeat(32)});
const flat=song();flat.xmid.path='SONGS/flat.xmid';
await resolver(flat,token);
assert.equal(flat.xmid.fileId,'flatDriveSong100');
assert.equal(flat.pendingDriveLink,false);
const duplicate=song();
files.push({...files.find(x=>x.id==='actualDriveSong100'),id:'otherDriveSong101'});
await assert.rejects(resolver(duplicate,token),/ซ้ำ\/ไม่พบ/);
assert.equal(duplicate.xmid.fileId,'');
console.log('PASS: PC-made DB paths resolve to exactly one Google Drive file by root, package size and MD5');
