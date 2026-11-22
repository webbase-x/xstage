import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {StudioSession,encodeWav,clamp,safeName} from "../studio-session.js";
import {reduceSpectralNoise} from "../noise-reduction.js";
import {waveformPeaks,noteSequence,encodeProject,decodeProject,midiFrequency,encodeMidi,decodeMidi} from "../studio-advanced.js";
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

test("Standard MIDI writer and reader roundtrip notes and tempo",()=>{
 const notes=[{pitch:60,beat:0,length:1,velocity:.8},{pitch:64,beat:1,length:2,velocity:.7}];
 const bytes=encodeMidi(notes,120),parsed=decodeMidi(bytes);
 assert.equal(String.fromCharCode(...bytes.slice(0,4)),"MThd");
 assert.equal(parsed.bpm,120);assert.equal(parsed.notes.length,2);
 assert.equal(parsed.notes[1].pitch,64);assert.equal(parsed.notes[1].beat,1);
 assert.throws(()=>decodeMidi(new Uint8Array([1,2,3,4])));
});
test("Android bridge and MIDI UI expose real file import/export actions",()=>{
 const native=read("android/app/src/main/java/com/webbasex/ag06studio/MainActivity.java");
 const ui=read("index.html");
 assert.match(native,/onShowFileChooser/);assert.match(native,/saveProjectFile/);assert.match(native,/saveMidiFile/);
 for(const id of ["midi-import","midi-export","midi-instrument"])assert.match(ui,new RegExp('id="'+id+'"'));
 assert.match(read("app.js"),/decodeMidi/);assert.match(read("app.js"),/encodeMidi/);
});

test("spectral reduction refuses to derive noise profile from continuous foreground speech",()=>{
 const rate=8000,samples=new Float32Array(rate);
 for(let i=0;i<samples.length;i++)samples[i]=.2*Math.sin(2*Math.PI*440*i/rate);
 const output=reduceSpectralNoise(samples,rate);
 assert.equal(output.length,samples.length);
 assert.ok(Math.abs(output[100]-samples[100])<1e-7);
});
test("spectral reduction with quiet sections produces finite samples",()=>{
 const rate=8000,samples=new Float32Array(rate);
 for(let i=0;i<samples.length;i++)samples[i]=.003*Math.sin(2*Math.PI*1800*i/rate)+(i>2000?.15*Math.sin(2*Math.PI*300*i/rate):0);
 const output=reduceSpectralNoise(samples,rate);
 assert.equal(output.length,samples.length);
 assert.ok(output.every(Number.isFinite));
 assert.match(read("desktop/package.json"),/noise-reduction\\.js/);
 assert.match(read("android/app/build.gradle"),/noise-reduction\\.js/);
 assert.match(read("index.html"),/id="studio-spectral"/);
});
