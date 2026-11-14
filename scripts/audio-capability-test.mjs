import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const src=fs.readFileSync(new URL('../audio-capability.js',import.meta.url),'utf8');
const context={console,Number,Map,Set,Object,Array,Math,Date,Promise,
  setTimeout,clearTimeout};
context.window=context;
context.document={getElementById:()=>null,createElement:()=>({canPlayType:()=>''})};
vm.runInNewContext(src,context,{filename:'audio-capability.js'});
const a=context.XStageAudioAdvisor;
assert.ok(a,'Audio advisory module must be bundled');
assert.equal(a.classifySong({sourceFormat:'NCN',midi:{fileId:'m'}}),'NCN');
assert.equal(a.classifySong({sourceFormat:'KAR',midi:{fileId:'m'}}),'KAR');
assert.equal(a.classifySong({sourceFormat:'MP3',audio:{fileId:'a'}}),'MP3');
assert.equal(a.classifySong({sourceFormat:'M4A',audio:{fileId:'a'}}),'M4A');
assert.equal(a.classifySong({sourceFormat:'FLAC',audio:{fileId:'a'}}),'FLAC');
assert.equal(a.classifySong({sourceFormat:'AVI',audio:{fileId:'a'}}),'VIDEO');
assert.equal(a.classifySong({video:{fileId:'v'},audio:{fileId:'a'}}),'VIDEO');
assert.equal(a.classifySong({midi:{fileId:'m'}}),'MIDI');
assert.equal(a.classifySong({audio:{fileId:'a',path:'audio/0001.ogg'}}),'OGG');
assert.equal(a.classifySong({audio:{fileId:'a'}}),'OTHER');
const rows=[{sourceFormat:'NCN'},{sourceFormat:'MIDI'},{sourceFormat:'MP3'},
  {sourceFormat:'M4A'},{sourceFormat:'MP3'},{sourceFormat:'MP4'}];
const counts=a.countSongs(rows);
assert.equal(counts.NCN,1);assert.equal(counts.MIDI,1);assert.equal(counts.MP3,2);
assert.equal(counts.M4A,1);assert.equal(counts.VIDEO,1);
assert.equal(Object.values(counts).reduce((x,y)=>x+y,0),rows.length,
  'Source categories should count each song exactly once');

const strong={ramGB:8,cores:8,quota:6*1024**3,usage:1*1024**3,
  offlineAudio:true,video:true};
const weak={ramGB:1,cores:2,quota:1*1024**3,usage:.3*1024**3,
  offlineAudio:true,video:false};
const font=a.assessFont(32*a.MB,strong);
assert.equal(font.level,'safe');
assert.equal(font.downloadBytes,32*a.MB);
assert.ok(font.estimatedRamBytes>font.downloadBytes);
assert.equal(a.assessFont(280*a.MB,strong).level,'blocked','Web SF hard cap');
assert.equal(a.assessFont(192*a.MB,weak).level,'blocked','Memory cap prevents dangerous download');
assert.equal(a.assessFont(32*a.MB,{cores:4,offlineAudio:true}).level,'caution',
  'No RAM report must not be interpreted as safe');
assert.equal(a.assessFont(32*a.MB,{ramGB:8,cores:8,offlineAudio:false}).level,'blocked');

const audio={sourceFormat:'M4A',audio:{fileId:'audio'}},
  midi={sourceFormat:'MIDI',midi:{fileId:'midi'}},
  both={sourceFormat:'NCN',audio:{fileId:'audio'},midi:{fileId:'midi'}},
  video={sourceFormat:'VIDEO',audio:{fileId:'audio'},video:{fileId:'video'}};
assert.equal(a.recommend(audio,strong).mode,'audio');
assert.equal(a.recommend(video,strong).mode,'video');
assert.equal(a.recommend(video,weak).mode,'audio');
assert.equal(a.recommend(midi,strong).mode,'midi');
assert.equal(a.recommend(midi,strong,'soundfont',{id:'sf',size:32*a.MB}).mode,'soundfont');
assert.equal(a.recommend(midi,weak,'soundfont',{id:'sf',size:192*a.MB}).mode,'midi');
assert.equal(a.recommend(both,strong,'audio').mode,'audio');
assert.equal(a.recommend(both,strong,'midi').mode,'midi');
assert.equal(a.recommend(both,strong,'auto').mode,'audio');
assert.equal(a.recommend({midi:{fileId:'m'}},strong,'video').mode,'midi');
assert.equal(a.recommend({},strong,'auto').mode,'none');
const html=fs.readFileSync(new URL('../index.html',import.meta.url),'utf8');
const app=fs.readFileSync(new URL('../app.js',import.meta.url),'utf8');
for(const id of ['toggle-audio-tools','mobile-audio-tools-toggle','xstage-audio-tools',
  'xstage-device-profile','xstage-font-file-list','xstage-soundfont-status',
  'xstage-play-mode','xstage-mode-apply','xstage-midi-transpose','xstage-midi-channels',
  'xstage-midi-apply','xstage-midi-reset','xstage-format-counts','xstage-format-guide'])
  assert.ok(html.includes('id="'+id+'"'),'Audio UI missing '+id);
assert.ok(app.includes('advisor?.resolve(song)'),'Playback must use device/media advisor');
assert.ok(app.includes('transpose:midiSettings.transpose,channels:midiSettings.channels'),
  'Mixer settings must reach actual renderer');
assert.ok(app.includes('state.midiSourceCache'),'MIDI source should be reused for fast remix');
console.log('PASS: format counts, SoundFont size/RAM status, media recommendations and integration');
