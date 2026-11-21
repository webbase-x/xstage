import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {PRESETS,LIMITS,sanitizeParams,formatParam} from "../presets.js";

const root=new URL("../",import.meta.url);
const read=path=>readFileSync(new URL(path,root),"utf8");

test("every AG06 preset has all bounded parameters",()=>{
  for(const [name,preset] of Object.entries(PRESETS)){
    assert.deepEqual(sanitizeParams(preset),preset,name);
    assert.deepEqual(Object.keys(preset).sort(),Object.keys(LIMITS).sort());
  }
});
test("out-of-range and malformed values never reach Web Audio nodes",()=>{
  const value=sanitizeParams({hpf:-1,low:999,reverb:NaN,drive:"not a number",gain:100});
  assert.equal(value.hpf,20);
  assert.equal(value.low,12);
  assert.equal(value.reverb,PRESETS.voice.reverb);
  assert.equal(value.drive,PRESETS.voice.drive);
  assert.equal(value.gain,6);
  assert.equal(formatParam("hpf",100),"100 Hz");
});
test("app captures actual microphone signal, not simulated meters",()=>{
  const source=read("audio-engine.js");
  assert.match(source,/mediaDevices\.getUserMedia/);
  assert.match(source,/getFloatTimeDomainData/);
  assert.match(source,/createMediaStreamDestination/);
  assert.match(source,/new MediaRecorder/);
  assert.match(source,/setMonitor\(false\)/);
  assert.match(source,/createBiquadFilter/);
  assert.match(source,/createDynamicsCompressor/);
});
test("UI must not promise control over the AG06 hardware DSP",()=>{
  const html=read("index.html");
  assert.match(html,/ไม่ใช่ Yamaha hardware DSP/);
  assert.match(html,/AG06 รุ่นแรก/);
  assert.match(html,/id="source-select"/);
  assert.match(html,/id="record-button"/);
  assert.match(html,/id="monitor-toggle"/);
  assert.match(html,/id="meter-left"/);
});
test("desktop isolates Electron rendering and restricts microphone permissions",()=>{
  const native=read("desktop/main.cjs");
  assert.match(native,/nodeIntegration:false/);
  assert.match(native,/contextIsolation:true/);
  assert.match(native,/sandbox:true/);
  assert.match(native,/permission==="media"/);
  assert.match(native,/mediaTypes\?\.includes\("audio"\)/);
});
test("Android bridge grants audio only to trusted web origin and bounds saved audio",()=>{
  const native=read("android/app/src/main/java/com/webbasex/ag06studio/MainActivity.java");
  assert.match(native,/RESOURCE_AUDIO_CAPTURE/);
  assert.match(native,/TRUSTED_ORIGIN/);
  assert.match(native,/MAX_DATA_URL_CHARS/);
  assert.match(native,/Music|DIRECTORY_MUSIC/);
  assert.doesNotMatch(native,/READ_EXTERNAL_STORAGE|WRITE_EXTERNAL_STORAGE/);
});
