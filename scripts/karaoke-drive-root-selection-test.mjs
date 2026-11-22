import fs from 'node:fs';
import assert from 'node:assert/strict';

const read=p=>fs.readFileSync(new URL('../'+p,import.meta.url),'utf8');
const app=read('app.js'),imp=read('cloud-import.js'),html=read('karaoke.html');
const version=JSON.parse(read('version.json'));
assert.equal(version.build,1139);
assert.equal(version.version,'1.0.139');
assert.ok(html.includes('app.js?v=1174-auto-migrate-mid'));
assert.ok(html.includes('cloud-import.js?v=1175-mid-bytes-and-md5'));
assert.ok(app.includes('createdTime,modifiedTime,md5Checksum,size,sharedWithMeTime'));
assert.ok(html.includes('id="library-drive-link"'));
assert.ok(app.includes("ui.libraryDriveLink.href='https://drive.google.com/drive/folders/'"));
assert.ok(app.includes('ui.libraryDriveLink.hidden=true'));
assert.ok(app.includes("return (root?.name||driveLayout.root)+' · '+base"));
assert.ok(app.includes('พบ XStageKaraoke ชื่อซ้ำ'));
assert.ok(!app.includes("name='XStageSong'"));
assert.ok(!imp.includes("name='XStageSong'"));

const match=imp.match(/^function chooseImportRoot\(roots,activeRootId\)\{[\s\S]*?^\}/m);
assert.ok(match,'Importer must expose root selection logic for test');
const choose=new Function('fail','isRetiredDriveRoot',match[0]+';return chooseImportRoot;')(
  message=>{throw Error(message);},id=>id==='1RYekUHCC3qs661cUrbxkNauUz_SuqZvy');
const older={id:'existing-empty-root',name:'XStageKaraoke',ownedByMe:true,
 createdTime:'2026-11-21T14:02:52Z'};
const newer={id:'newer-imported-root',name:'XStageKaraoke',ownedByMe:true,
 createdTime:'2026-11-21T14:21:11Z'};
assert.equal(choose([],''),'');
assert.equal(choose([older],''),older.id);
assert.equal(choose([older,newer],newer.id),newer.id);
assert.equal(choose([newer,older],older.id),older.id);
assert.throws(()=>choose([older,newer],''),/ชื่อซ้ำ/);
assert.throws(()=>choose([older,newer],'unrelated-root'),/ชื่อซ้ำ/);
assert.throws(()=>choose([{...older,ownedByMe:false}],older.id),/ไม่ได้เป็นเจ้าของ/);
assert.equal(choose([older],older.id),older.id);

const labelMatch=app.match(/^function libraryLabel\(root\)\{[\s\S]*?^\}/m);
assert.ok(labelMatch,'Duplicate-aware labels must exist');
const label=new Function('state','driveLayout',labelMatch[0]+';return libraryLabel;')(
 {availableLibraries:[older,newer]},{root:'XStageKaraoke'});
const oldLabel=label(older),newLabel=label(newer);
assert.notEqual(oldLabel,newLabel,'Two same-name folders must have distinct labels');
assert.ok(oldLabel.includes('XStageKaraoke')&&newLabel.includes('XStageKaraoke'));
assert.ok(oldLabel.includes('…'+older.id.slice(-5)));
assert.ok(newLabel.includes('…'+newer.id.slice(-5)));
assert.ok(app.includes('String(saved.rootId||\'\')!==String(state.libraryRootId)'),
 'Resume must never cross to a song with an identical code in a different Drive folder');
assert.ok(app.includes('rootId:String(state.libraryRootId||\'\')'),
 'Session resume records must preserve their root identity');
assert.ok(app.includes("saved?.layoutVersion!==6")&&
  app.includes("saved?.format!=='xstage-sqlite3-v1'"),
  'Legacy JSON catalog caches cannot masquerade as new SQLite snapshots');
assert.ok(imp.includes("const activeRootId=String(auth.rootId||'')"),
  'Browser import must honor the selected root, not first search hit');
assert.ok(app.includes('error.driveStatus=status;error.driveSubject=subject;'),
  'Google Drive errors must retain the HTTP status and resource kind');
assert.ok(app.includes("if([403,404].includes(error?.driveStatus)&&error?.driveSubject==='ไฟล์เพลงส่วนตัว')"),
  'An inaccessible app-scoped SQLite file must not be misdiagnosed as expired Google login');
assert.ok(imp.includes('publishSingleCatalog')&&imp.includes('songs.sqlite3')&&
  !imp.includes("pushSqlite('catalog-delta-"),
  'Browser must publish one app-authorized SQLite catalog without legacy delta files');
console.log('PASS: distinct duplicate folders, verified import target, no legacy cache/resume, same-code playback isolation');
