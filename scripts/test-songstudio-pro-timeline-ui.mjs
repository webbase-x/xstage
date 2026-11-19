import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
class NodeStub{
  constructor(tag="div"){
    this.tagName=tag.toUpperCase();this.children=[];this.dataset={};
    this.style={};this.events={};this.attributes={};this.hidden=false;
    this.textContent="";this.className="";this.captured=null;
    this.disabled=false;this.classList={toggle:(name,on)=>{
      const parts=new Set(this.className.split(" ").filter(Boolean));
      if(on)parts.add(name);else parts.delete(name);
      this.className=[...parts].join(" ");
    }};
  }
  append(...elements){this.children.push(...elements);}
  replaceChildren(){this.children=[];}
  setAttribute(name,value){this.attributes[name]=value;}
  addEventListener(name,fn){(this.events[name]??=[]).push(fn);}
  fire(name,attrs={}){
    const event={button:0,pointerId:7,clientX:0,key:"",code:"",
      shiftKey:false,preventDefault(){},stopPropagation(){},
      target:this,...attrs};
    for(const fn of this.events[name]||[])fn(event);
  }
  setPointerCapture(id){this.captured=id;}
  hasPointerCapture(id){return this.captured===id;}
  releasePointerCapture(id){if(this.captured===id)this.captured=null;}
  focus(){}
  closest(selector){return selector===".manual-timeline-marker"&&
    this.className.includes("manual-timeline-marker")?this:null;}
  getBoundingClientRect(){return {left:0,width:800};}
  querySelector(selector){
    const match=selector.match(/^\[data-cue="(\d+)"\]$/);
    return match?this.children.find(c=>c.dataset.cue===match[1])||null:null;
  }
}
globalThis.document={createElement:name=>new NodeStub(name)};
require('../songstudio-plus/web/timeline-core.js');
require('../songstudio-plus/web/timeline-ui.js');
const ids=["manual-timeline-zoom-in","manual-timeline-zoom-out",
  "manual-timeline-follow","manual-timeline-track","manual-timeline-ruler",
  "manual-timeline-cues","manual-timeline-highlight","manual-timeline-playhead"];
const elements=Object.fromEntries(ids.map(x=>[x,new NodeStub()]));
let line={text:"ABC",start:1,end:6,segments:["A","B","C"],starts:[1,2,4]};
let playback=2.5,selectedCue=0,changes=0,undo=null,seekTo=null,preview=0;
const text={};
const ctrl=new globalThis.XStageCueTimelineUI({
  el:id=>elements[id],text:(id,value)=>{text[id]=value;},
  selected:()=>({id:"song-1"}),line:()=>line,lineIndex:()=>0,
  cueIndex:()=>selectedCue,segments:l=>l.segments,starts:l=>l.starts,
  time:()=>playback,duration:()=>60,playing:()=>false,canPlay:()=>true,
  selectCue:i=>{selectedCue=i;},seek:at=>{seekTo=at;},
  previewTime:at=>{playback=at;},preview:()=>{preview++;},
  capture:()=>{},changed:before=>{undo=before;changes++;}
});
ctrl.render();
assert.equal(elements["manual-timeline-cues"].children.length,3);
assert.equal(elements["manual-timeline-ruler"].children.length,7);
const marker=elements["manual-timeline-cues"].children[1];
marker.fire("pointerdown",{pointerId:42,clientX:200});
assert.equal(selectedCue,1);
marker.fire("pointermove",{pointerId:42,clientX:300}); // 3s in 8s window
assert.equal(line.starts[1],3);
assert.ok(preview>0,'dragging must immediately redraw lyric sweep');
marker.fire("pointerup",{pointerId:42,clientX:300});
assert.equal(changes,1,'one drag creates one undo checkpoint');
assert.deepEqual(undo,[1,2,4]);
assert.equal(seekTo,3,'preview seeks to the edited timestamp once drag ends');
const newMarker=elements["manual-timeline-cues"].children[1];
newMarker.fire("keydown",{key:"ArrowRight"});
assert.equal(line.starts[1],3.05,'arrow key nudges a cue by 50 ms');
assert.equal(changes,2);
assert.equal(elements["manual-timeline-playhead"].hidden,false);
const oldWidth=ctrl.viewport.width;
elements["manual-timeline-zoom-in"].fire("click");
assert.ok(ctrl.viewport.width<oldWidth);
line={text:"AB",start:1,end:5,segments:["A","B"],starts:[1,""]};
ctrl.render();
assert.equal(elements["manual-timeline-cues"].children.length,1,
 'missing cue must remain absent, not receive a generated position');
assert.match(text["manual-timeline-status"],/ยังไม่มีเวลา/);
const before=changes;
elements["manual-timeline-track"].fire("click",{clientX:400});
assert.notEqual(seekTo,null,'clicking track seeks actual playback');
assert.equal(changes,before,'seeking cannot write lyric timestamps');
console.log('PASS: live timeline cue drag, preview, undo, keyboard nudge, zoom, missing cues and seek');
