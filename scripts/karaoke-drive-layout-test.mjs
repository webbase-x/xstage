import assert from 'node:assert/strict';
import fs from 'node:fs';

const read=path=>fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const app=read('app.js'),importer=read('cloud-import.js'),midi=read('browser-midi.js');
const html=read('karaoke.html'),config=read('config.js');
const version=JSON.parse(read('version.json'));
assert.ok(version.build>=1144,'revision must not regress');
assert.match(version.version,/^\d+\.\d+\.\d+$/);
assert.ok(config.includes("root:'XStageKaraoke'"));
assert.ok(config.includes("songs:'SONGS'"));
assert.ok(config.includes("db:'DB'"));
assert.ok(config.includes("soundfont:'SOUNDFONT'"));
assert.ok(!app.includes("name='XStageSong'"));
assert.ok(!importer.includes("name='XStageSong'"));
assert.ok(!app.includes("or name='LYRICS'"));
assert.ok(app.includes("name='DB' and mimeType="));
assert.ok(importer.includes("await drive.ensurePath(rootId,['DB'])"));
assert.ok(importer.includes("await drive.ensurePath(rootId,['DB'])")&&importer.includes("await drive.ensurePath(rootId,['CACHE'])"),'DB and CACHE folders are created only when publishing');
assert.ok(!midi.includes("name==='AUDIO'"),'No SoundFont fallback to legacy AUDIO');
assert.ok(midi.includes(".toLowerCase()==='soundfont'")&&midi.includes("soundFolders.length>1"),'SoundFont lookup must be case-insensitive and duplicate-safe');
assert.ok(midi.includes("/\\.sf[23]$/i")&&midi.includes('pendingFolders=[sourceId]'),'SoundFont must recurse selected folder and accept SF2/SF3 files');
assert.ok(/cloud-import\.js\?v=/.test(html),'cloud-import.js cache-busted script loads');
assert.ok(/cloud-import\.css\?v=/.test(html),'cloud-import.css cache-busted stylesheet loads');
assert.ok(html.includes('id="cloud-import-action-hint"'));
assert.ok(html.includes('id="cloud-import-start"'));
assert.ok(importer.includes('onVideoApproved(item)'));
assert.ok(importer.includes('this.chosenItems.add(entry.key)'));
assert.ok(/browser-midi\.js\?v=/.test(html),'browser MIDI script is cache-busted');

const first=importer.indexOf('function pathFor(');
const end=importer.indexOf('async function db()',first);
assert.ok(first>=0&&end>first);
const body=importer.slice(first,end);
const pathFor=new Function('core','driveLayout',body+';return pathFor;')(
  {ext:name=>name.slice(name.lastIndexOf('.')+1).toLowerCase()},
  {songs:'SONGS',soundfont:'SOUNDFONT'});
const check=(kind,role,name,expected)=>
  assert.deepEqual(pathFor('74649',kind,role,name),expected);
check('mid','','74649.mid',['SONGS','MIDI','MID','SONG','7','74649.mid']);
check('xmid','','74649.xmid',['SONGS','MIDI','XMID','7','74649.xmid']);
check('kar','','74649.kar',['SONGS','MIDI','KAR','7','74649.kar']);
check('json','NCN','74649.json',['SONGS','MIDI','NCN','LYRICS','7','74649.json']);
check('mp3','','74649.mp3',['SONGS','AUDIO','MP3','SONG','7','74649.mp3']);
check('mp4','','74649.mp4',['SONGS','VIDEO','MP4','SONG','7','74649.mp4']);
check('sf2','','piano.sf2',['SOUNDFONT','SF2','piano.sf2']);
check('sf3','','piano.sf3',['SOUNDFONT','SF3','piano.sf3']);
assert.ok(importer.includes("[driveLayout.songs,'MIDI','NCN',role,bucket]"));
console.log('PASS: XStageKaraoke exclusively, SONGS/MIDI/AUDIO/VIDEO, DB pointer, SOUNDFONT SF2/SF3, no old library scan');
