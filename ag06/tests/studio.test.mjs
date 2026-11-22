import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {StudioSession,encodeWav,clamp,safeName} from "../studio-session.js";
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
 assert.match(read("android/app/src/main/java/com/webbasex/ag06studio/MainActivity.java"),/data:audio\\/wav/);
});
