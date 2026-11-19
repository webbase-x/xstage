/* Interactive timestamp editor for Song Studio Pro menu 05.
 * Uses exact stored/measured cue times. No inferred lyric timings or fake waveform.
 */
(function(root){
  "use strict";
  class CueTimeline{
    constructor(options){
      this.o=options;
      this.math=root.XStageCueTimeline;
      this.zoom=1;
      this.anchor=0;
      this.viewport=null;
      this.drag=null;
      for(const [id,fn] of [
        ["manual-timeline-zoom-in",()=>{this.zoom=Math.max(.25,this.zoom/2);this.render();}],
        ["manual-timeline-zoom-out",()=>{this.zoom=Math.min(8,this.zoom*2);this.render();}],
        ["manual-timeline-follow",()=>{this.anchor=this.o.time();this.render();}]
      ])this.o.el(id).addEventListener("click",fn);
      this.o.el("manual-timeline-track").addEventListener("click",event=>{
        if(!this.o.selected()||!this.o.canPlay()||
           event.target.closest(".manual-timeline-marker")||!this.viewport)return;
        const rect=this.o.el("manual-timeline-track").getBoundingClientRect();
        const time=this.math.sampleTime(event.clientX,rect.left,rect.width,this.viewport);
        if(time!==null)this.o.seek(time);
      });
    }
    reset(){
      this.zoom=1;this.anchor=0;this.viewport=null;this.drag=null;
      this.render();
    }
    selection(){
      const active=this.o.cueIndex();
      for(const item of this.o.el("manual-timeline-cues").children)
        item.classList.toggle("is-selected",Number(item.dataset.cue)===active);
    }
    tick(){
      const head=this.o.el("manual-timeline-playhead");
      const now=this.o.time();
      this.o.text("manual-timeline-position","▶ "+this.math.format(now));
      const w=this.viewport;
      if(!w){head.hidden=true;return;}
      const visible=now>=w.from&&now<=w.to;
      head.hidden=!visible;
      if(visible)head.style.left=this.math.position(now,w)+"%";
      this.selection();
    }
    render(){
      const el=this.o.el;
      const ruler=el("manual-timeline-ruler"),cues=el("manual-timeline-cues");
      ruler.replaceChildren();cues.replaceChildren();
      const line=this.o.line();
      const hasSong=Boolean(this.o.selected());
      for(const id of ["manual-timeline-zoom-in","manual-timeline-zoom-out",
                        "manual-timeline-follow"])el(id).disabled=!hasSong;
      if(!line){
        this.viewport=null;
        this.o.text("manual-timeline-line","เลือกบรรทัดก่อนปาดสี");
        this.o.text("manual-timeline-status","ยังไม่มีจุดปาด · เพิ่มเนื้อร้องหรือเลือกบรรทัด");
        this.tick();return;
      }
      this.o.text("manual-timeline-line","บรรทัด "+(this.o.lineIndex()+1)+
        " · "+(line.text||"ยังไม่มีข้อความ").slice(0,75));
      const window=this.math.range(line,this.anchor,this.o.duration(),this.zoom);
      this.viewport=window;
      for(let i=0;i<=6;i++){
        const node=document.createElement("span");
        node.className="manual-timeline-tick";
        node.style.left=(100*i/6)+"%";
        node.textContent=this.math.format(window.from+i*window.width/6);
        ruler.append(node);
      }
      const start=this.math.number(line.start),end=this.math.number(line.end);
      const fill=el("manual-timeline-highlight");
      fill.hidden=start===null||end===null||end<=start;
      if(!fill.hidden){
        fill.style.left=this.math.position(start,window)+"%";
        fill.style.width=Math.max(0,
          this.math.position(end,window)-this.math.position(start,window))+"%";
      }
      let missing=0,outside=0;
      const segments=this.o.segments(line),starts=this.o.starts(line);
      for(let i=0;i<segments.length;i++){
        const at=this.math.number(starts[i]);
        if(at===null){missing++;continue;}
        if(at<window.from||at>window.to){outside++;continue;}
        const marker=document.createElement("button");
        marker.type="button";
        marker.className="manual-timeline-marker";
        marker.dataset.cue=String(i);
        marker.style.left=this.math.position(at,window)+"%";
        const label=document.createElement("span");
        label.className="manual-timeline-marker-text";
        label.textContent=segments[i]||"คำ "+(i+1);
        const timing=document.createElement("small");
        timing.className="manual-timeline-marker-time";
        timing.textContent=this.math.format(at);
        marker.append(label,timing);
        marker.setAttribute("aria-label","ตำแหน่งปาดช่วง "+(i+1)+
          " "+segments[i]+" เวลา "+this.math.format(at));
        marker.title="ลากเพื่อแก้เวลา · ลูกศรปรับทีละ 0.05 วินาที · Shift+ลูกศรปรับ 0.01";
        marker.addEventListener("click",event=>{
          event.stopPropagation();this.o.selectCue(i);this.selection();
        });
        marker.addEventListener("pointerdown",event=>{
          if(event.button!==0)return;
          event.stopPropagation();event.preventDefault();
          this.o.selectCue(i);this.selection();marker.focus();
          const bounds=this.math.bounds(line,i,this.o.duration());
          if(!bounds){
            this.o.text("manual-timeline-status",
              "ยังลากไม่ได้ · ตรวจเวลาเริ่ม/จบบรรทัดและเวลาคำข้างเคียง");
            return;
          }
          this.drag={id:event.pointerId,marker,index:i,bounds,
            firstX:event.clientX,changed:false,before:starts.slice()};
          marker.setPointerCapture(event.pointerId);
        });
        marker.addEventListener("pointermove",event=>{
          const drag=this.drag;
          if(!drag||drag.marker!==marker||drag.id!==event.pointerId)return;
          if(!drag.changed&&Math.abs(event.clientX-drag.firstX)<3)return;
          const rect=el("manual-timeline-track").getBoundingClientRect();
          const sampled=this.math.sampleTime(event.clientX,rect.left,rect.width,window);
          if(sampled===null)return;
          const next=this.math.atTime(sampled,drag.bounds);
          if(next===null)return;
          drag.changed=true;
          line.starts[i]=next;
          marker.style.left=this.math.position(next,window)+"%";
          timing.textContent=this.math.format(next);
          if(!this.o.playing())this.o.previewTime(next);
          this.o.preview();this.tick();
          this.o.text("manual-timeline-status","กำลังเลื่อน “"+segments[i]+
            "” ไปที่ "+this.math.format(next)+" · ยังไม่ได้บันทึก");
        });
        const finish=event=>{
          const drag=this.drag;
          if(!drag||drag.marker!==marker||drag.id!==event.pointerId)return;
          this.drag=null;
          if(marker.hasPointerCapture(event.pointerId))
            marker.releasePointerCapture(event.pointerId);
          if(!drag.changed)return;
          this.o.changed(drag.before);
          const at=Number(line.starts[i]);
          if(!this.o.playing())this.o.seek(at);
          this.render();
          this.o.text("manual-timeline-status",
            "ตำแหน่งปาดเปลี่ยนแล้ว · ผลสีปาดด้านบนเปลี่ยนทันที · กดบันทึกเมื่อถูกต้อง");
        };
        marker.addEventListener("pointerup",finish);
        marker.addEventListener("pointercancel",finish);
        marker.addEventListener("keydown",event=>{
          if(event.code==="Space"&&this.o.playing()){
            event.preventDefault();event.stopPropagation();this.o.capture();return;
          }
          if(event.key!=="ArrowLeft"&&event.key!=="ArrowRight")return;
          event.preventDefault();
          const bounds=this.math.bounds(line,i,this.o.duration());
          if(!bounds)return;
          const old=starts.slice();
          const step=event.shiftKey?.01:.05;
          const next=this.math.atTime(Number(starts[i])+
            (event.key==="ArrowRight"?step:-step),bounds);
          if(next===null||next===Number(starts[i]))return;
          line.starts[i]=next;
          if(!this.o.playing())this.o.previewTime(next);
          this.o.changed(old);this.o.preview();this.render();
          const current=cues.querySelector('[data-cue="'+i+'"]');
          if(current)current.focus({preventScroll:true});
        });
        cues.append(marker);
      }
      this.o.text("manual-timeline-status",missing?
        "มี "+missing+" ช่วงที่ยังไม่มีเวลา · เลือกคำและกดจับเวลาจากเสียงจริง":
        outside?"มี "+outside+" จุดนอกหน้าต่างเวลา · ซูมออกเพื่อดู":
        "ลากหมุดเวลาเพื่อปรับปาดสี · คลิกพื้นที่ว่างเพื่อเลื่อนฟัง");
      this.tick();
    }
  }
  root.XStageCueTimelineUI=CueTimeline;
})(globalThis);
