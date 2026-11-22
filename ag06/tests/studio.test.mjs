import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {StudioSession,encodeWav,clamp,safeName} from "../studio-session.js";
import {waveformPeaks,noteSequence,encodeProject,decodeProject,midiFrequency} from "../studio-advanced.js";
const read=path=>readFileSync(new URL(path,new URL("../",import.meta.url)),"utf8");
test("WAV encoder writes valid RIFF mono samples",()=>{
 const b={numberOfChannels:1,length:2,sampleRate:44100,getChannelData:()=>new Float32Array([-1,1])};
 const wav=encodeWav(b);assert.equal(wav.type,"audio/wav");assert.equal(wav.size,48);
});
test("studio gains, mute, solo and trims do not require hardware DSP",()=>{
 const s=new StudioSession(),b={duration:8};
 s.tracks=[{id:"1",buffer:b,mute:false,solo:false,offset:1,start:2,end:6},
 {id:"2",buffer:b,mute:false,solo:true,offset:0,start:0,end:5}];
 assert.equal(s.duration(),5);assert.equal(s.active().length,1);
 s.tracks[1].mute=true;assert.equal(s.active().length,0);
 s.remove("2");assert.equal(s.active().length,1);
 assert.equal(clamp(5,0,2),2);assert.equal(safeName("x/y"),"xy");
});
test("workspace UI and packaging include independent module",()=>{
 for(const id of ["studio-files","studio-tracks","studio-add-take","studio-play","studio-stop","studio-export"])
 assert.match(read("index.html"),new RegExp('id="'+id+'"'));
 assert.match(read("app.js"),/new StudioSession/);
 assert.match(read("desktop/package.json"),/studio-session\.js/);
 assert.match(read("android/app/build.gradle"),/studio-session\.js/);
 assert.match(read("studio-session.js"),/new OfflineAudioContext/);
 assert.match(read("studio-session.js"),/voiceLevelAt/);
 assert.match(read("index.html"),/id="studio-ducking"/);
 assert.match(read("index.html"),/id="studio-normalize"/);
 assert.match(read("android/app/src/main/java/com/webbasex/ag06studio/MainActivity.java"),new RegExp("data:audio/wav"));
});

test("waveform extracts peaks without requiring screen or device",()=>{
 const peaks=waveformPeaks({getChannelData:()=>new Float32Array([0,.1,-.6,1,0])},5);
 assert.equal(peaks.length,5);assert.equal(peaks[3],1);
});
test("note editor bounds pitch, beat and tempo",()=>{
 assert.equal(Math.round(midiFrequency(69)),440);
 const notes=noteSequence([{pitch:150,beat:2,length:1,velocity:.8}],120);
 assert.equal(notes[0].pitch,96);assert.equal(notes[0].start,1);
});
test("project format round trip restores metadata and embedded PCM",()=>{
 const session=new StudioSession();session.tracks=[{name:"Voice",volume:1,mute:false,solo:false,role:"voice",start:0,end:.001,offset:0,buffer:{
  sampleRate:8000,numberOfChannels:1,getChannelData:()=>new Float32Array([0,.25,-.25,0])}}];
 const project=decodeProject(encodeProject(session,[{pitch:60,beat:0,length:1,velocity:.8}]));
 assert.equal(project.tracks[0].name,"Voice");assert.equal(project.notes[0].pitch,60);
 assert.throws(()=>decodeProject('{"format":"invalid","version":1,"tracks":[]}'));
});
test("new editor buttons and both desktop/mobile bundles are wired",()=>{
 const html=read("index.html"),app=read("app.js");
 for(const id of ["studio-timeline","studio-zoom","studio-noise-gate","studio-save-project","studio-open-project","midi-notes","midi-add","midi-play","midi-to-track","hardware-dsp"])
  assert.match(html,new RegExp('id="'+id+'"'));
 assert.match(app,/drawWaveform/);assert.match(app,/decodeProject/);assert.match(app,/renderSynth/);
 assert.match(read("desktop/package.json"),/studio-advanced\.js/);
 assert.match(read("android/app/build.gradle"),/studio-advanced\.js/);
});
