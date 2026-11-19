import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const timeline=require('../songstudio-plus/web/timeline-core.js');

const phrase={start:10,end:20,starts:[10,12,14.5,17]};
const win=timeline.range(phrase,0,240,1);
assert.ok(win.from<=10&&win.to>=20,'whole selected line initially visible');
assert.equal(timeline.position(12,win)>=0,true);
assert.equal(timeline.sampleTime(win.from,win.from,0,win),null);
const midpoint=timeline.sampleTime(200,0,400,win);
assert.equal(midpoint,Math.round((win.from+win.width/2)*1000)/1000);
assert.deepEqual(timeline.bounds(phrase,1,240),{min:10,max:14.5});
assert.equal(timeline.atTime(16,timeline.bounds(phrase,1,240)),14.5);
assert.deepEqual(timeline.bounds(phrase,0,240),{min:10,max:12});
assert.equal(timeline.atTime(6,timeline.bounds(phrase,0,240)),10);
assert.equal(timeline.bounds({start:null,end:null,starts:['']},0,0),null,
 'no fabricated time bounds without a measured line or player duration');
assert.equal(timeline.number(''),null,'missing onset is not time 0');
assert.equal(timeline.number(0),0,'time zero remains valid');
assert.equal(timeline.format(61.425),'01:01.425');
const next=timeline.range({start:null,end:null},95,260,.5);
assert.ok(next.from<=95&&95<=next.to,'untimed lyrics use playback position only for viewport');
assert.equal(timeline.position(null,next),null,'missing cues remain missing');
assert.ok(timeline.range(phrase,0,240,.5).width<win.width,'zoom in should shrink range');
assert.ok(timeline.range(phrase,0,240,2).width>win.width,'zoom out should widen range');
console.log('PASS: timeline positions, missing onset, zoom, bounds and timestamp preview maths');
