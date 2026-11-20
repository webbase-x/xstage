"use strict";
(() => {
  console.info("[XSTAGE] app.js loaded");
  window.addEventListener("error",event=>{
    console.error("[XSTAGE] window.error",event.message||"unknown",
      event.filename||"",event.lineno||0,event.colno||0);
  });
  window.addEventListener("unhandledrejection",event=>{
    const reason=event.reason instanceof Error?
      (event.reason.stack||event.reason.message):String(event.reason||"unknown");
    console.error("[XSTAGE] unhandledrejection",reason);
  });
  const $ = id => document.getElementById(id);
  const state = {token:null,ready:false,view:"import",groups:[],selectedGroups:new Set(),
                 songs:[],selectedSongs:new Set(),allReadySelected:false,excludedSongs:new Set(),
                 readyTotal:0,latestEdit:null,lyricsEditJob:null,
                 lyricsEditActive:false,activeJob:null,
                 jobSignature:"",toastTimer:null,riskFilter:"structural",
                 riskOffset:0,riskLimit:5,riskTotal:0,riskRows:[],
                 riskHistory:[],riskSelected:null,riskEvidenceIndex:0,
                 songOffset:0,songHasNext:false,groupOffset:0,groupHasNext:false,
                 selectedGroupInfo:new Map(),issueRows:[],issueOffset:0,
                 lyricSearchRun:0,groupSearchRunning:false,lyricContextHits:0,
                 lyricContextFailed:false,
                 lyricTimed:[],lyricDraft:[],lyricOffset:0,lyricShowDraft:false,
                 previewOffset:0,previewSongs:[],previewHasNext:false,
                 previewSelected:null,previewPlaying:false,previewHeard:false,
                 previewTime:0,previewDuration:0,previewRaf:null,
                 previewLastPaint:0,previewMidiSample:0,previewMidiAt:0,
                 previewPolling:false,previewMidiPoll:null,previewSeeking:false,
                 manualOffset:0,manualTotal:0,manualRows:[],manualSelected:null,
                 manualLines:[],manualDuration:0,manualTime:0,manualPlaying:false,
                 manualHeard:false,manualPoll:null,manualClockTimer:null,manualMidiSample:0,
                 manualMidiAt:0,manualCueUndo:new Map(),manualDirty:false,manualFindings:[],manualOnlyIssues:false,
                 manualLayout:{menu:false,queue:false,stage:false,focus:false},
                 updateTarget:null,updateInstallIntent:false,updateBusy:false,updateNoticeDismissed:false,updateNoticeShown:false,jobsRefreshing:false,lastJobRevision:-1,lastJobPaint:0};
  let manualTimeline=null;
  const labels={import:"นำเข้าเพลง",lyrics:"แก้ไขเนื้อร้อง",media:"เสียงและวิดีโอ",
                preview:"ทดสอบก่อนสร้าง .x...",manual:"ตรวจและปาดเนื้อร้อง",build:"สร้างไฟล์ X-Stage",
                library:"คลังเพลง",risks:"ประวัติเสี่ยงปาดเนื้อ"};
  const number = v => Number(v||0).toLocaleString("en-US");
  function text(id,value){
    const node=$(id);
    const next=String(value??"");
    if(node&&node.textContent!==next)node.textContent=next;
  }
  function toast(message,error=false){
    const node=$("toast");
    node.textContent=String(message||"");
    node.classList.toggle("error",error);
    node.classList.add("show");
    clearTimeout(state.toastTimer);
    state.toastTimer=setTimeout(()=>node.classList.remove("show"),4600);
  }
  async function api(path,payload,timeoutMs=12000){
    const options={cache:"no-store",headers:{}};
    let timer=null;
    if(timeoutMs>0){
      const controller=new AbortController();
      options.signal=controller.signal;
      timer=setTimeout(()=>controller.abort(),timeoutMs);
    }
    if(payload!==undefined){
      options.method="POST";
      options.headers={"Content-Type":"application/json","X-XStage-Token":state.token};
      options.body=JSON.stringify(payload);
    }
    try{
      const response=await fetch(path,options);
      let result;
      try{result=await response.json();}catch{throw new Error("บริการภายในเครื่องไม่ตอบกลับ");}
      if(!response.ok)throw new Error(result.error||"คำสั่งไม่สำเร็จ");
      return result;
    }catch(error){
      if(error?.name==="AbortError")throw new Error("หมดเวลารอ Local Engine");
      throw error;
    }finally{
      if(timer)clearTimeout(timer);
    }
  }
  async function diagnostic(event,detail={}){
    if(!state.token)return;
    try{await api("/api/diagnostic",{event,detail});}catch{/* diagnostics must never block UI */}
  }
  function view(name){
    if(!labels[name])return;
    // Re-clicking the active navigation item should never tear down and
    // repaint its page, losing focus and appearing to flash.
    if(state.view===name&&$("view-"+name)?.classList.contains("is-visible"))return;
    if(state.view==="manual"&&name!=="manual")void manualStop();
    if(state.view==="preview"&&name!=="preview"){
      void stopPreviewPlayback();
      state.previewSelected=null;
      state.previewPlaying=false;
    }
    state.view=name;
    for(const element of document.querySelectorAll(".view"))
      element.classList.toggle("is-visible",element.id==="view-"+name);
    for(const button of document.querySelectorAll("[data-view]"))
      button.classList.toggle("active",button.dataset.view===name);
    text("breadcrumb",labels[name]);
    if(name==="library"||name==="build"||name==="media"){
      state.songOffset=0;
      void refreshSongs();
    }
    if(name==="import")void refreshStatus();
    if(name==="preview")void loadPreviewSongs();
    if(name==="manual")void loadManualQueue();
    manualApplyLayout();
    if(name==="risks")void loadRisks();
    if(name==="lyrics"&&$("lyrics-search").value.trim())void searchGroups();
    document.title=labels[name]+" · X-Stage Song Studio Pro";
    history.replaceState(null,"","#"+name);
  }
  function setReady(enabled){
    state.ready=enabled;
    text("engine-name",enabled?"Local Engine พร้อมใช้":"ยังไม่เชื่อมต่อ PC Engine");
    text("engine-subtitle",enabled?"SQLite · 127.0.0.1":"เปิดผ่าน Song Studio Pro บน PC");
    const dot=document.querySelector(".live-dot");
    if(dot)dot.style.background=enabled?"#5edfad":"#e9a465";
    for(const id of ["import-start","recover-lyrics","risk-scan","lyrics-find","media-attach","build-start","source-browse","source-open","workspace-open","lrc-browse","manual-find","db-health-check","db-detail-audit"]){
      const control=$(id);
      if(control)control.disabled=!enabled;
    }
  }
  const gb = n => (Number(n||0)/(1024**3)).toFixed(2)+" GB";
  function renderDatabaseAudit(result){
    if(!result)return;
    const bytes=n=>(Number(n||0)/(1024**2)).toFixed(2)+" MB";
    const rows=(result.table_space||[]).map((item,i)=>
      (i+1)+". "+item.table+" · "+bytes(item.bytes)+
      " (ตาราง "+bytes(item.table_bytes)+" + ดัชนี "+bytes(item.index_bytes)+") "+
      " · "+(item.category==="keep"?"ต้องเก็บ":
      item.category==="temporary"?"ชั่วคราว":
      item.category==="derived"?"ผลตรวจที่สร้างใหม่ได้":
      item.category==="cache"?"แคชช่วยความเร็ว":"ยังไม่จัดประเภท"));
    text("db-audit-detail",
      "ผลตรวจโครงสร้าง: "+String(result.quick_check)+
      " · วัดพื้นที่ด้วย dbstat: "+(result.dbstat_available?"ได้":"ไม่ได้ใน SQLite รุ่นนี้")+
      "\nSQLite "+bytes(result.database_bytes)+
      " · WAL "+bytes(result.wal_bytes)+
      " · พื้นที่ในฐานที่นำกลับมาใช้ได้ "+bytes(result.reusable_bytes)+
      "\n\n"+(rows.length?rows.join("\n"):"ไม่พบข้อมูลพื้นที่รายตาราง")+
      (result.unknown_tables?.length?
       "\n\nไม่ลบตารางที่ยังไม่ทราบหน้าที่: "+result.unknown_tables.join(", "):""));
  }
  async function checkDatabaseHealth(){
    try{
      const r=await api("/api/db/health",undefined,30000);
      text("db-health-summary",
        "SQLite "+gb(r.database_bytes)+" · WAL "+gb(r.wal_bytes)+
        " · พื้นที่นำกลับมาใช้ในฐานได้ "+gb(r.reusable_bytes)+
        " · เพลง "+number(r.counts.songs)+
        " · ต้นทาง "+number(r.counts.sources)+
        " · เนื้อร้อง "+number(r.counts.lyrics_versions)+
        " · ประวัตินำเข้า "+number(r.counts.import_items)+
        " · Checkpoint "+number(r.counts.checkpoints)+
        " · งานเสร็จ "+number(r.completed_batches)+
        " · งานทำต่อได้ "+number(r.resumable_batches)+
        " · ปัญหาคงค้าง "+number(r.issue_rows));
      $("db-detail-audit").disabled=Boolean(state.activeJob)||!state.ready;
      $("db-history-clean").disabled=Boolean(state.activeJob)||!state.ready;
      $("db-compact").disabled=Boolean(state.activeJob)||!state.ready;
    }catch(e){
      text("db-health-summary","ตรวจ SQLite ไม่สำเร็จ: "+e.message);
      toast(e.message,true);
    }
  }
  async function refreshStatus(){
    if(!state.ready)return;
    const result=await api("/api/status");
    for(const key of ["songs","media","lyrics","exports"])
      text("stat-"+key,number(result[key]));
    text("stat-with-text",number(result.songs_with_text));
    text("stat-ready",number(result.songs_with_lyrics));
    text("stat-pending",number(result.songs_without_lyrics));
    const estimated=number(result.songs_estimated_timing);
    text("issues-summary",number(result.songs_without_lyrics)+
      " เพลงยังไม่พร้อมส่งออก · มี CUR ไม่ครบ "+number(result.songs_partial_lyrics)+
      " เพลง · เก็บเนื้อร้องรอ Timing "+number(result.songs_draft_lyrics)+
      " เพลง · เวลาประมาณ "+estimated+" เพลง · ตรวจรายการตามสาเหตุได้ด้านล่าง");
  }
  const visibleRows=()=>window.innerHeight<=680?4:window.innerHeight<=850?5:6;
  async function refreshSongs(){
    if(!state.ready)return;
    const q=state.view==="library"?$("library-search").value.trim():"";
    const pageSize=visibleRows();
    const inMedia=state.view==="media";
    const data=await api("/api/songs?q="+encodeURIComponent(q)+
      "&limit="+(inMedia?80:pageSize+1)+
      "&offset="+(inMedia?0:state.songOffset));
    state.songHasNext=!inMedia&&(data.rows||[]).length>pageSize;
    state.songs=inMedia?(data.rows||[]):(data.rows||[]).slice(0,pageSize);
    renderSongs();
  }
  function renderSongs(){
    const list=$("library-rows");
    list.replaceChildren();
    const build=$("build-list");
    build.replaceChildren();
    const select=$("media-song");
    const previous=select.value;
    select.replaceChildren(new Option("เลือกเพลง",""));
    if(!state.songs.length){
      const row=document.createElement("tr");
      const cell=document.createElement("td");
      cell.colSpan=6;cell.className="empty-cell";cell.textContent="ไม่พบเพลงตามคำค้น";
      row.append(cell);list.append(row);
      const small=document.createElement("p");
      small.className="empty-small";small.textContent="ยังไม่มีเพลงที่แสดง";
      build.append(small);
    }
    for(const song of state.songs){
      const row=document.createElement("tr");
      const format=song.extension.toUpperCase();
      const ready=song.manual_status==="ready";
      const available=Boolean(song.version_id||song.draft_reason);
      const timingLabel=song.manual_status==="review"?"รอการยืนยัน / แก้ไข":
        ready? song.timing_status:
        song.timing_status==="incomplete"?"เนื้อร้องบางส่วน · CUR ไม่ครบ":
        song.draft_reason?"เก็บเนื้อร้องแล้ว · รอ Timing":"ยังไม่พบเนื้อร้องพร้อมเวลา";
      const columns=[String(song.code).padStart(8,"0"),song.title||song.original_code,
          format,timingLabel,
          song.output_path?"สร้างแล้ว":"—"];
      columns.forEach((value,index)=>{
        const cell=document.createElement("td");
        if(index===1){
          const heading=document.createElement("strong");heading.textContent=value;
          const artist=document.createElement("small");artist.textContent=song.artist||"ไม่ระบุศิลปิน";
          cell.append(heading,artist);
        }else if(index===3){
          const badge=document.createElement("span");badge.className="badge "+(ready?"good":"warn");
          badge.textContent=value;cell.append(badge);
        }else{cell.textContent=value;}
        row.append(cell);
      });
      const action=document.createElement("td");
      if(available){
        const button=document.createElement("button");
        button.type="button";button.className="view-link";
        button.textContent="ดูเนื้อร้อง";
        button.addEventListener("click",()=>void openLyrics(song));
        action.append(button);
      }else action.textContent="—";
      row.append(action);list.append(row);
      const option=new Option(String(song.code).padStart(8,"0")+" · "+song.title,song.id);
      select.append(option);
      const label=document.createElement("label");
      label.className="build-row";
      const check=document.createElement("input");check.type="checkbox";
      check.checked=ready&&(state.allReadySelected?
        !state.excludedSongs.has(song.id):state.selectedSongs.has(song.id));
      check.disabled=!ready;
      check.addEventListener("change",()=>{
        if(state.allReadySelected){
          if(check.checked)state.excludedSongs.delete(song.id);
          else state.excludedSongs.add(song.id);
        }else{
          if(check.checked)state.selectedSongs.add(song.id);
          else state.selectedSongs.delete(song.id);
        }
        updateBuildSelection();
      });
      const div=document.createElement("div");div.className="song-text";
      div.textContent=song.title||song.original_code;
      const small=document.createElement("small");
      small.textContent=String(song.code).padStart(8,"0")+" · "+
        format+" · "+timingLabel;
      div.append(small);label.append(check,div);build.append(label);
    }
    if(previous)select.value=previous;
    updateBuildSelection();
    const pageSize=visibleRows();
    const label="หน้า "+number(Math.floor(state.songOffset/pageSize)+1)+
       " · "+(state.songs.length?number(state.songOffset+1)+"–"+
       number(state.songOffset+state.songs.length):"ไม่มีรายการ");
    text("library-page-info",label);
    text("build-page-info",label);
    $("library-prev").disabled=state.songOffset===0;
    $("build-prev").disabled=state.songOffset===0;
    $("library-next").disabled=!state.songHasNext;
    $("build-next").disabled=!state.songHasNext;
  }
  function updateBuildSelection(){
    // Preserve selected song IDs when moving between pages.
    const count=state.allReadySelected?
      Math.max(0,state.readyTotal-state.excludedSongs.size):state.selectedSongs.size;
    text("build-count",number(count)+" เพลง"+
      (state.allReadySelected?" (ทั้งคลัง)":""));
    $("build-start").disabled=!state.ready||count===0||Boolean(state.activeJob);
  }
  function renderLyricPage(){
    const entries=state.lyricShowDraft?state.lyricDraft:state.lyricTimed;
    const target=$("lyrics-modal-lines");
    target.replaceChildren();
    const size=visibleRows();
    const slice=entries.slice(state.lyricOffset,state.lyricOffset+size);
    for(const line of slice){
      const item=document.createElement("div");
      item.className="lyric-line";
      const time=document.createElement("code");
      time.textContent=line.start===null||line.end===null?
        "รอ Timing":Number(line.start).toFixed(2)+"–"+Number(line.end).toFixed(2)+"s";
      const detail=document.createElement("div");
      const words=document.createElement("p");
      words.textContent=line.text;
      words.title=line.text;
      const label=document.createElement("small");
      label.textContent="บรรทัด "+(line.position+1)+" · "+line.timing+
        " · จุดปาดสี "+(line.cues||[]).length+" จุด";
      detail.append(words,label);item.append(time,detail);target.append(item);
    }
    if(!slice.length)target.append(riskElement("p","empty-small","ไม่มีเนื้อร้องในส่วนนี้"));
    text("lyrics-page-info",number(state.lyricOffset+(slice.length?1:0))+"–"+
      number(state.lyricOffset+slice.length)+" / "+number(entries.length)+" บรรทัด");
    $("lyrics-prev").disabled=state.lyricOffset<=0;
    $("lyrics-next").disabled=state.lyricOffset+size>=entries.length;
    const hasDraft=state.lyricDraft.length>0&&state.lyricTimed.length>0;
    $("lyrics-show-draft").hidden=!hasDraft;
    if(hasDraft)$("lyrics-show-draft").textContent=state.lyricShowDraft?
      "ดูบรรทัดพร้อมเวลา":"ดูข้อความ LYR ทั้งหมด";
  }
  async function openLyrics(song){
    try{
      const data=await api("/api/lyrics?song_id="+encodeURIComponent(song.id));
      text("lyrics-modal-title",song.title+" · "+data.version.timing_status);
      state.lyricTimed=data.lines||[];
      state.lyricDraft=data.draft?data.draft.text.split(/\r?\n/).map((value,index)=>({
        position:index,text:value,start:null,end:null,timing:"untimed",cues:[]
      })):[];
      state.lyricShowDraft=state.lyricTimed.length===0;
      state.lyricOffset=0;
      renderLyricPage();
      $("lyrics-dialog").showModal();
    }catch(error){toast(error.message,true);}
  }
  function renderLyricContext(result){
    const results=$("lyrics-search-context-results");
    const box=$("lyrics-search-context");
    results.replaceChildren();
    const rows=new Map();
    for(const item of result.songs||[]){
      rows.set(item.id,{...item,source:["ชื่อเพลง / ศิลปิน / รหัส"]});
    }
    for(const item of result.drafts||[]){
      const current=rows.get(item.id);
      if(current){
        current.source.push("ข้อความ LYR รอเวลา");
        current.has_draft=true;
      }else{
        rows.set(item.id,{...item,has_draft:true,source:["ข้อความ LYR รอเวลา"]});
      }
    }
    state.lyricContextHits=rows.size;
    box.hidden=!rows.size;
    text("lyrics-search-context-title",
      "พบในชื่อเพลง/ศิลปิน "+number((result.songs||[]).length)+
      " · พบใน LYR รอเวลา "+number((result.drafts||[]).length)+
      ((result.more_songs||result.more_drafts)?" · มีผลเพิ่มเติม":""));
    for(const item of rows.values()){
      const canOpen=Boolean(item.has_current_lyrics||item.has_draft);
      const line=document.createElement(canOpen?"button":"div");
      line.className="lyric-search-hit";
      if(canOpen){
        line.type="button";
        line.addEventListener("click",()=>void openLyrics({id:item.id,title:item.title||String(item.code)}));
      }
      const title=document.createElement("strong");
      title.textContent=String(item.code).padStart(8,"0")+" · "+(item.title||"ไม่ระบุชื่อเพลง");
      const note=document.createElement("small");
      note.textContent=(item.artist||"ไม่ระบุศิลปิน")+" · "+item.source.join(" + ")+
        (canOpen?" · กดดูเนื้อร้อง":" · ยังไม่มีเนื้อร้อง");
      line.append(title,note);results.append(line);
    }
  }
  async function searchGroups(reset=true){
    if(!state.ready)return;
    const q=$("lyrics-search").value.trim();
    const requestId=++state.lyricSearchRun;
    if(reset){
      state.groupOffset=0;
      state.selectedGroups.clear();
      state.selectedGroupInfo.clear();
      state.lyricContextHits=0;
      state.lyricContextFailed=false;
      $("lyrics-search-context").hidden=true;
    }
    state.groups=[];
    state.groupHasNext=false;
    state.groupSearchRunning=Boolean(q);
    renderGroups();
    if(!q){
      text("lyrics-search-feedback","พิมพ์คำค้นแล้วกดค้นหา · ระบบแยกเนื้อร้องที่แก้ไขได้กับข้อมูลชื่อเพลง/LYR");
      return;
    }
    if(q.length>100){
      state.groupSearchRunning=false;renderGroups();
      text("lyrics-search-feedback","คำค้นยาวเกิน 100 ตัวอักษร กรุณาย่อให้สั้นลง");
      return;
    }
    text("lyrics-search-feedback","กำลังค้นหา “"+q+
      "” ในเนื้อร้องปัจจุบันและตรวจชื่อเพลง/LYR · คลังขนาดใหญ่อาจใช้เวลาสักครู่");
    $("lyrics-find").disabled=true;
    const contextTask=reset?
      api("/api/lyrics/search-context?q="+encodeURIComponent(q)+"&limit=12",undefined,45000)
        .then(data=>{
          if(requestId!==state.lyricSearchRun)return;
          renderLyricContext(data);
        })
        .catch(error=>{
          if(requestId!==state.lyricSearchRun)return;
          state.lyricContextFailed=true;
          $("lyrics-search-context-results").replaceChildren();
          text("lyrics-search-context-title","ค้นชื่อเพลงและข้อความ LYR ไม่สำเร็จ: "+error.message);
          $("lyrics-search-context").hidden=false;
        }):Promise.resolve();
    let failed=null;
    try{
      const limit=visibleRows();
      // A multi-gigabyte SQLite registry may need more than the generic 12s
      // UI request limit for an exact substring across all current lyrics.
      const data=await api("/api/groups?q="+encodeURIComponent(q)+
        "&limit="+(limit+1)+"&offset="+state.groupOffset,undefined,90000);
      if(requestId!==state.lyricSearchRun)return;
      state.groupHasNext=(data.rows||[]).length>limit;
      state.groups=(data.rows||[]).slice(0,limit);
    }catch(error){
      if(requestId!==state.lyricSearchRun)return;
      failed=error;
      toast("ค้นเนื้อร้องไม่สำเร็จ: "+error.message,true);
    }finally{
      await contextTask;
      if(requestId===state.lyricSearchRun){
        state.groupSearchRunning=false;
        $("lyrics-find").disabled=false;
        renderGroups();
        if(failed){
          text("lyrics-search-feedback","การค้นบรรทัดเนื้อร้องไม่สำเร็จ: "+failed.message+
            " · ไม่ใช่ผลยืนยันว่าไม่มีข้อความใน SQLite");
        }else{
          const count=state.groups.length;
          text("lyrics-search-feedback",
            count?"พบบรรทัดเนื้อร้องที่ตรงคำค้น "+number(count)+
              " กลุ่มในหน้านี้ · เลือกกลุ่มเพื่อแทนที่ได้":
            state.lyricContextHits?
              "ไม่พบ “"+q+"” ในบรรทัดเนื้อร้องปัจจุบัน แต่พบในชื่อเพลง/ศิลปินหรือ LYR รอเวลา · เลือกดูรายละเอียดด้านบน":
            state.lyricContextFailed?
              "ไม่พบในเนื้อร้องปัจจุบัน แต่ยังตรวจชื่อเพลง/LYR ไม่สำเร็จ · โปรดลองค้นอีกครั้ง":
              "ไม่พบ “"+q+"” ในเนื้อร้องเวอร์ชันปัจจุบันหรือชื่อเพลง/LYR ที่ค้น · ลองใช้คำบางส่วนหรือค้นในเมนูคลังเพลง");
        }
      }
    }
  }
  function renderGroups(){
    text("groups-count",number(state.groups.length)+" กลุ่มในหน้านี้");
    text("groups-page-info","หน้า "+number(Math.floor(state.groupOffset/visibleRows())+1));
    $("groups-prev").disabled=state.groupOffset<=0;
    $("groups-next").disabled=!state.groupHasNext;
    const panel=$("group-list");panel.replaceChildren();
    if(!state.groups.length){
      const empty=document.createElement("p");empty.className="empty-small";
      empty.textContent=state.groupSearchRunning?
        "กำลังค้นใน SQLite · ยังไม่สรุปว่าไม่พบคำค้น":
        $("lyrics-search").value.trim()?
        "ไม่พบบรรทัดเนื้อร้องปัจจุบันที่ตรงคำค้น · ตรวจผลชื่อเพลง/LYR ด้านบน":
        "ค้นคำเพื่อแสดงกลุ่มบรรทัด";
      panel.append(empty);
    }
    for(const entry of state.groups){
      const label=document.createElement("label");label.className="group-row";
      const checkbox=document.createElement("input");checkbox.type="checkbox";
      checkbox.checked=state.selectedGroups.has(entry.group_key);
      checkbox.addEventListener("change",()=>{
        if(checkbox.checked){
          state.selectedGroups.add(entry.group_key);
          state.selectedGroupInfo.set(entry.group_key,entry);
        }else{
          state.selectedGroups.delete(entry.group_key);
          state.selectedGroupInfo.delete(entry.group_key);
        }
        updateSelectedGroups();
      });
      const middle=document.createElement("div");middle.className="group-text";
      const full=document.createElement("strong");full.textContent=entry.text;
      const small=document.createElement("small");
      small.textContent=number(entry.songs)+" เพลง · "+number(entry.lines)+" บรรทัด";
      middle.append(full,small);
      const count=document.createElement("span");count.className="amount";
      count.textContent=number(entry.lines)+" บรรทัด";
      label.append(checkbox,middle,count);panel.append(label);
    }
    updateSelectedGroups();
  }
  function updateSelectedGroups(){
    const chosen=Array.from(state.selectedGroupInfo.values());
    const lines=chosen.reduce((acc,x)=>acc+Number(x.lines),0);
    text("selected-summary",chosen.length?
      "เลือก "+number(chosen.length)+" กลุ่ม · "+number(lines)+" บรรทัด"+
      " · แทนที่ข้อความทั้งบรรทัด (ไม่ใช่แทนเฉพาะคำค้น)":
      "ยังไม่ได้เลือกกลุ่มข้อความ");
    $("lyrics-apply").disabled=!state.ready||state.lyricsEditActive||
      !chosen.length||!$("lyrics-replacement").value.trim();
    $("lyrics-undo").disabled=state.lyricsEditActive||!state.latestEdit;
  }
  async function confirmTask(title,message){
    const modal=$("confirm-dialog");text("confirm-title",title);text("confirm-text",message);
    modal.showModal();
    return await new Promise(resolve=>{
      const callback=()=>{modal.removeEventListener("close",callback);resolve(modal.returnValue==="yes");};
      modal.addEventListener("close",callback);
    });
  }
  async function applyLyrics(){
    if(state.lyricsEditActive)return;
    const q=$("lyrics-search").value.trim();
    const replacement=$("lyrics-replacement").value.trim();
    const keys=Array.from(state.selectedGroups);
    if(!keys.length||!q||!replacement){
      toast("กรุณาค้นคำ เลือกกลุ่ม และใส่ข้อความใหม่",true);return;
    }
    $("lyrics-apply").disabled=true;
    text("edit-feedback","กำลังตรวจจำนวนเพลงและบรรทัดที่เลือก...");
    try{
      const plan=await api("/api/edit/plan",{q,keys});
      if(!plan.lines){
        text("edit-feedback","ไม่พบบรรทัดที่ต้องแก้ไข");return;
      }
      const approved=await confirmTask("ยืนยันแทนที่เนื้อร้อง",
        "กลุ่มที่เลือก: "+number(plan.groups)+"\n"+
        "บรรทัดที่จะเปลี่ยน: "+number(plan.lines)+"\n"+
        "เพลงที่เกี่ยวข้อง: "+number(plan.songs)+"\n\n"+
        "ข้อความใหม่ทั้งบรรทัด:\n"+replacement+"\n\n"+
        "ข้อความสั้นกว่าจุดปาดเดิม จะเติม > ในช่อง CUR ภายใน"+
        " · ข้อความยาวกว่า CUR จะปาดควบหลายอักขระ"+
        " · คงเวลา CUR เดิมและให้เมนู 05 ฟังตรวจ"+
        " · หากยกเลิกระหว่างทำงาน ระบบจะคืนค่า SQLite ทั้งชุด");
      if(!approved){
        text("edit-feedback","ยกเลิกก่อนเริ่มแก้ไข · ยังไม่มีข้อมูลเปลี่ยน");return;
      }
      const result=await api("/api/edit/apply",{
        q,keys,replacement,expected_lines:plan.lines
      });
      state.lyricsEditActive=true;
      state.lyricsEditJob=result.job;
      $("lyrics-cancel").hidden=false;
      text("edit-feedback","เริ่มแทนที่ "+number(plan.lines)+" บรรทัดใน "+
        number(plan.songs)+" เพลง · บันทึกสำเร็จเมื่อจบทั้งชุดเท่านั้น");
      await refreshJobs();
    }catch(error){
      text("edit-feedback","แทนที่ไม่สำเร็จ: "+error.message);
      toast(error.message,true);
    }finally{updateSelectedGroups();}
  }
  async function undoLyrics(){
    if(state.lyricsEditActive)return;
    if(!state.latestEdit)return;
    if(!await confirmTask("ย้อนคืนการแก้ไข","คืนค่าเนื้อร้องทั้งชุดล่าสุด โดยไม่เปลี่ยนไฟล์ต้นฉบับ?"))return;
    try{
      const answer=await api("/api/edit/undo",{batch:state.latestEdit});
      state.latestEdit=null;$("lyrics-undo").disabled=true;
      toast("ย้อนคืน "+number(answer.restored_songs)+" เพลงเรียบร้อย");
      await searchGroups();
    }catch(error){toast(error.message,true);}
  }
  async function attachLrc(){
    const song_id=$("media-song").value;
    const path=$("media-lrc").value.trim();
    if(!song_id||!path){toast("กรุณาเลือกเพลงและไฟล์ LRC",true);return;}
    if(!await confirmTask("แนบเนื้อร้องพร้อมเวลา",
      "ข้อมูล LRC จะถูกเก็บเป็นเวอร์ชันใหม่ใน SQLite\n"+
      "การปาดสีรายตัวอักษรจาก LRC แบบบรรทัดจะมีสถานะ Estimated"))return;
    try{
      const result=await api("/api/attach-lrc",{song_id,path});
      text("media-feedback",result.created?
        "บันทึก Lyrics Version ใหม่แล้ว · Timing สถานะ Estimated":
        "พบข้อมูลเนื้อร้องเวอร์ชันเดียวกันอยู่แล้ว");
      toast("ดำเนินการข้อมูล LRC เรียบร้อย");
      await refreshStatus();await refreshSongs();
    }catch(error){toast(error.message,true);}
  }

  async function refreshSummary(){
    if(!state.ready)return;
    const button=$("refresh-summary");
    button.disabled=true;
    try{
      await refreshStatus();
      await refreshJobs();
      text("summary-refreshed","รีเฟรชข้อมูลจาก SQLite แล้ว · "+new Date().toLocaleTimeString("th-TH"));
      toast("รีเฟรชยอดสรุปสำเร็จ");
    }catch(error){
      text("summary-refreshed","รีเฟรชไม่สำเร็จ: "+error.message);
      toast(error.message,true);
    }finally{button.disabled=false;}
  }
  function syncSettingsUpdate(){
    text("settings-update-version",
      "เวอร์ชันที่ใช้ "+(state.updateTarget?.current_version||
      $("pro-update-version")?.textContent||"กำลังตรวจสอบ")+
      (state.updateTarget?.newer?" · รุ่นล่าสุด "+state.updateTarget.version:
       state.updateTarget?" · เป็นรุ่นล่าสุดแล้ว":""));
    text("settings-update-status",
      $("pro-update-status")?.textContent||"ตรวจสอบรุ่นล่าสุดจาก GitHub Releases");
    $("settings-update-check").disabled=!state.ready||state.updateBusy;
    $("settings-update-install").disabled=!state.ready||
      state.updateBusy||!state.updateTarget?.newer;
  }
  function openLatestExe(){
    const latest=state.updateTarget?.url;
    location.href=latest&&latest.startsWith(
      "https://github.com/webbase-x/xstage/releases/download/")?
      latest:"https://github.com/webbase-x/xstage/releases";
  }
  function renderProUpdateNotice(result,ready={}){
    const available=Boolean(result?.newer);
    const quick=$("pro-update-quick");
    const notice=$("pro-update-notice");
    const install=$("pro-update-notice-install");
    quick.hidden=!available;
    if(!available){
      notice.hidden=true;
      install.disabled=true;
      return;
    }
    quick.textContent="↑ อัปเดต v"+result.version;
    install.disabled=state.updateBusy;
    text("pro-update-notice-title","มี X-Stage Song Studio Pro v"+result.version);
    text("pro-update-notice-text",
      ready.ready&&ready.version===result.version?
        "ดาวน์โหลดและตรวจ SHA-256 แล้ว · พร้อมติดตั้งและเปิดใหม่":
        "มีรุ่นใหม่กว่าที่ใช้อยู่ · กดอัปเดตเพื่อดาวน์โหลด ตรวจ SHA-256 ติดตั้ง และเปิดใหม่");
    if(!state.updateNoticeDismissed)notice.hidden=false;
    if(!state.updateNoticeShown){
      state.updateNoticeShown=true;
      toast("พบ X-Stage Song Studio Pro v"+result.version+" · พร้อมอัปเดต");
    }
  }
  async function checkProUpdate(silent=false){
    if(!state.ready)return;
    const button=$("pro-update-check");
    button.disabled=true;
    $("settings-update-check").disabled=true;
    if(!silent)text("pro-update-status","กำลังตรวจอัปเดตที่เผยแพร่และยืนยัน SHA-256...");
    try{
      const result=await api("/api/update/check");
      state.updateTarget=result;
      text("pro-update-version","v"+result.current_version);
      const ready=await api("/api/update/ready");
      const available=Boolean(result.newer);
      text("pro-update-status",available?
        "พบ v"+result.version+" · ตรวจสอบจาก Release ทางการแล้ว · "+
        (ready.ready&&ready.version===result.version?
          "ดาวน์โหลดไว้แล้ว พร้อมติดตั้ง":"กดปุ่มเดียวเพื่อดาวน์โหลดและติดตั้ง"):
        "ใช้งาน v"+result.current_version+" · ยังไม่มีรุ่นใหม่ที่เผยแพร่");
      $("pro-update-install").disabled=!available||state.updateBusy;
      renderProUpdateNotice(result,ready);
    }catch(error){
      state.updateTarget=null;
      $("pro-update-install").disabled=true;
      $("pro-update-quick").hidden=true;
      $("pro-update-notice").hidden=true;
      text("pro-update-status","ยังตรวจอัปเดตไม่ได้: "+error.message+
        " · โปรแกรมปัจจุบันยังใช้งานได้");
      if(!silent)toast(error.message,true);
    }finally{
      button.disabled=false;
      syncSettingsUpdate();
    }
  }
  async function beginProUpdate(){
    if(state.updateBusy||!state.updateTarget?.newer)return;
    if(!await confirmTask("ติดตั้ง Song Studio Pro รุ่นใหม่",
      "ดาวน์โหลด EXE จาก GitHub ตรวจ SHA-256 แล้วเปลี่ยนโปรแกรมทันที\n"+
      "ถ้านำเข้าเพลงอยู่ จะหยุดหลังไฟล์ปัจจุบัน บันทึก Checkpoint แล้วเปิดรุ่นใหม่มาทำต่อ\n"+
      "ยืนยันให้ดาวน์โหลดและติดตั้งหรือไม่?"))return;
    state.updateBusy=true;
    syncSettingsUpdate();
    text("settings-update-progress","กำลังเตรียมดาวน์โหลดและตรวจ SHA-256 ของรุ่นล่าสุด");
    $("pro-update-install").disabled=true;
    $("pro-update-notice-install").disabled=true;
    $("pro-update-quick").disabled=true;
    $("pro-update-notice").hidden=false;
    text("pro-update-notice-text","กำลังเตรียมอัปเดต · โปรแกรมจะตรวจ SHA-256 ก่อนติดตั้ง");
    try{
      // A release may have been published since startup. Re-check when
      // clicked and jump directly to the newest verified version.
      const latest=await api("/api/update/check",undefined,30000);
      state.updateTarget=latest;
      if(!latest.newer){
        state.updateBusy=false;
        text("pro-update-status","ใช้งานรุ่นล่าสุด v"+latest.current_version+" อยู่แล้ว");
        $("pro-update-install").disabled=true;
        $("pro-update-notice-install").disabled=true;
        $("pro-update-quick").disabled=true;
        $("pro-update-quick").hidden=true;
        $("pro-update-notice").hidden=true;
        syncSettingsUpdate();
        return;
      }
      text("pro-update-status","ตรวจพบรุ่นล่าสุด v"+latest.version+" · อัปเดตข้ามรุ่นได้ทันที");
      const ready=await api("/api/update/ready");
      if(ready.ready&&ready.version===state.updateTarget.version){
        await api("/api/update/install",{});
        text("pro-update-status","กำลังปิดโปรแกรมเก่า ติดตั้ง EXE และเปิดกลับมาทำต่อ...");
        toast("ระบบกำลังเปิดโปรแกรมรุ่นใหม่");
      }else{
        state.updateInstallIntent=true;
        text("pro-update-status","กำลังดาวน์โหลด v"+state.updateTarget.version+
          " · โปรแกรมจะติดตั้งและเปิดใหม่หลัง SHA-256 ผ่าน");
        const job=await api("/api/update/download",{});
        state.activeJob=job.job;
        await refreshJobs();
      }
    }catch(error){
      state.updateInstallIntent=false;state.updateBusy=false;
      $("pro-update-install").disabled=false;
      $("pro-update-notice-install").disabled=false;
      $("pro-update-quick").disabled=false;
      text("pro-update-status","อัปเดตไม่สำเร็จ · "+error.message);
      text("pro-update-notice-text","อัปเดตไม่สำเร็จ · "+error.message);
      toast(error.message,true);
    }finally{
      syncSettingsUpdate();
    }
  }
  async function startJob(kind,payload){
    try{
      const endpoint=kind==="import"?"/api/import":kind==="recover"?"/api/recover-lyrics":
        kind==="swipe-audit"?"/api/swipe/scan":kind==="db-audit"?"/api/db/audit":
        kind==="db-clean"?"/api/db/cleanup":
        kind==="db-compact"?"/api/db/compact":"/api/build";
      const result=await api(endpoint,payload);
      state.activeJob=result.job;
      toast("เริ่มงานแล้ว ระบบประมวลผลต่อเนื่อง");
      await refreshJobs();
    }catch(error){toast(error.message,true);}
  }
  async function refreshJobs(){
    if(!state.ready||state.jobsRefreshing)return;
    state.jobsRefreshing=true;
    try{
      const result=await api("/api/jobs",undefined,4000);
      const jobs=result.jobs||[];
      const job=jobs.find(x=>x.status==="running")||jobs[0];
      state.activeJob=jobs.find(x=>x.status==="running")?.id||null;
      const paintKey=job?
        job.id+":"+job.status+":"+String(job.revision??0)+":"+String(state.activeJob):
        "no-jobs";
      if(state.jobPaintKey===paintKey)return;
      state.jobPaintKey=paintKey;
      if(job){
        state.lastJobPaint=Date.now();
        state.lastJobRevision=Number(job.revision??state.lastJobRevision);
      }
      $("cancel-job").hidden=!state.activeJob;
      updateBuildSelection();
      $("import-start").disabled=!state.ready||Boolean(state.activeJob);
      $("recover-lyrics").disabled=!state.ready||Boolean(state.activeJob);
      $("risk-scan").disabled=!state.ready||Boolean(state.activeJob);
      $("db-health-check").disabled=!state.ready||Boolean(state.activeJob);
      $("db-detail-audit").disabled=!state.ready||Boolean(state.activeJob);
      $("db-history-clean").disabled=!state.ready||Boolean(state.activeJob);
      $("db-compact").disabled=!state.ready||Boolean(state.activeJob);
      if(!job)return;
      text("activity-status",job.status==="running"?"กำลังทำงาน":
          job.status==="completed"?"เสร็จเรียบร้อย":job.status==="failed"?"ข้อผิดพลาด":"หยุดแล้ว");
      text("activity-title",job.kind==="lyrics-edit"?"แทนที่เนื้อร้องเป็นชุด":
          job.kind==="update"?"ดาวน์โหลดและตรวจ SHA-256 โปรแกรมใหม่":
          job.kind==="import"?"นำเข้าและตรวจ SHA-256":
          job.kind==="db-audit"?"ตรวจพื้นที่และความสมบูรณ์ของ SQLite":
          job.kind==="db-clean"?"ล้างประวัติงาน SQLite ที่เสร็จแล้ว":
          job.kind==="db-compact"?"คืนพื้นที่ไฟล์ฐานข้อมูล SQLite":
          job.kind==="recover"?"ตรวจซ่อมเนื้อร้องจาก SQLite":
           job.kind==="swipe-audit"?"ตรวจหลักฐานปาดเนื้อจาก SQLite":"สร้างไฟล์ X-Stage Pro");
      text("activity-subtitle",job.status==="failed"?
        (job.error||job.message||"ดำเนินการไม่สำเร็จ"):
        (job.message||""));
      const p=job.progress||{};
      if(job.kind==="update"){
        text("settings-update-progress",job.status==="running"?
          "ดาวน์โหลดแล้ว "+number(Math.floor(Number(p.downloaded_bytes||0)/1048576))+
          " MB"+(p.total?" / "+number(Math.floor(Number(p.total)/1048576))+" MB":"")+
          " · กำลังตรวจ SHA-256 ก่อนติดตั้ง":
          job.status==="failed"?"อัปเดตไม่สำเร็จ: "+(job.error||job.message):
          job.status==="completed"?"ดาวน์โหลดและตรวจไฟล์ผ่าน · กำลังติดตั้ง":
          "สถานะ: "+job.status);
      }
      if(job.kind==="lyrics-edit"){
        state.lyricsEditJob=job.id;
        state.lyricsEditActive=job.status==="running";
        $("lyrics-cancel").hidden=job.status!=="running";
        $("lyrics-cancel").disabled=job.status!=="running";
        updateSelectedGroups();
        if(job.status==="running"){
          text("edit-feedback","กำลังแทนที่ "+number(p.done)+" / "+
            number(p.total)+" เพลง · เติม > "+number(p.silent_slots)+
            " จุด · ปาดควบ "+number(p.combined_lines)+
            " บรรทัด · ต้องจับเวลาต่อ "+number(p.needs_review_lines)+
            " บรรทัด · ยังไม่บันทึกจนกว่าจะเสร็จทั้งชุด");
        }else if(job.status==="completed"){
          const output=job.result||{};
          if(output.batch){
            state.latestEdit=output.batch;
            state.selectedGroups.clear();
            state.selectedGroupInfo.clear();
            $("lyrics-undo").disabled=false;
          }
          text("edit-feedback","บันทึกสำเร็จ "+number(output.changed_lines)+
            " บรรทัดใน "+number(output.changed_songs)+
            " เพลง · เติม > ใน CUR "+number(output.silent_slots)+
            " จุด ("+number(output.padded_lines)+" บรรทัด)"+
            " · ปาดควบ "+number(output.combined_lines)+
            " บรรทัด · รอแก้เวลาในเมนู 05 "+
            number(output.needs_review_lines)+" บรรทัด"+
            " · เวลาเดิมที่จับคู่ใหม่ต้องฟังยืนยัน"+
            (output.batch?" · กดย้อนคืนได้":""));
        }else{
          text("edit-feedback",job.status==="cancelled"?
            "ยกเลิกแล้ว · ฐานข้อมูลคืนค่าเดิมทั้งชุด":
            "แทนที่ไม่สำเร็จ ฐานข้อมูลยังไม่เปลี่ยน: "+(job.error||job.message));
        }
      }
      text("progress-detail",job.kind==="lyrics-edit"?
          "แทนที่เนื้อร้อง "+number(p.done)+" / "+number(p.total)+
          " เพลง · เติม > "+number(p.silent_slots)+" จุด"+
          " · ปาดควบ "+number(p.combined_lines)+" บรรทัด"+
          " · ไม่มี CUR "+number(p.needs_review_lines)+" บรรทัด"+
          " · รอฟังตรวจ "+number(p.estimated_lines)+" บรรทัด":
          job.kind==="update"?
          "ดาวน์โหลด "+number((p.downloaded_bytes||0)/1048576>>0)+" MB"+
          (p.total?" / "+number((p.total/1048576)>>0)+" MB":"")+
          " · ตรวจ SHA-256 ก่อนติดตั้ง":
          job.kind==="import"?
          "ไฟล์ใหม่ "+number(p.files_new)+" · ไฟล์ซ้ำ "+number(p.media_duplicates)+
          " · เนื้อร้องพร้อมเวลา "+number(p.lyrics_new)+
          " · CUR ไม่ครบ "+number(p.partial_lyrics)+
          " · เก็บเนื้อร้องรอเวลา "+number(p.draft_lyrics)+
          " · ผิดพลาดจริง "+number(p.failures)+
          " · Hash เดิม "+number(p.hash_cache_hits)+
          " · จุดเดิมที่ข้าม "+number(p.resumed_files)+
          " · "+number(p.files_per_second)+" ไฟล์/วินาที":
          job.kind==="db-audit"?
          "ตรวจฐานและดัชนี "+number(p.processed)+" / "+number(p.total)+
          " ขั้นตอน":
          job.kind==="db-clean"?
          "ตรวจแล้ว "+number(p.processed)+" / "+number(p.total)+
          " งาน · ลบ Checkpoint "+number(p.checkpoints_removed)+
          " · ลบประวัติซ้ำ "+number(p.success_logs_removed)+
          " · ลบชุดเก่า "+number(p.old_batches_removed):
          job.kind==="db-compact"?
          "กำลังจัดระเบียบข้อมูลและคืนพื้นที่ที่ว่างใน SQLite":
          job.kind==="recover"?
          "กู้คืนพร้อมใช้ "+number(p.recovered_ready)+" · CUR ไม่ครบ "+number(p.partial_lyrics)+
          " · LYR รอเวลา "+number(p.draft_lyrics)+" · ไม่พบต้นฉบับ "+number(p.missing_sources)+
          " · ต้นฉบับเปลี่ยน "+number(p.changed_sources)+" · อ่านผิดพลาด "+number(p.failures):
          job.kind==="swipe-audit"?
          "ตรวจแล้ว "+number(p.processed)+" / "+number(p.total)+
          " · ผิดปกติจากข้อมูล "+number(p.structural_songs)+
          " · เวลาประมาณ "+number(p.estimated_songs)+
          " · CUR ไม่ครบ "+number(p.blocked_songs):
          "สร้าง "+number(p.built)+" · ข้าม "+number(p.skipped)+" · ไม่สำเร็จ "+number(p.failed));
      text("progress-count",job.kind==="lyrics-edit"?
        number(p.done)+" / "+number(p.total)+" เพลง":
        job.kind==="update"?
        number(p.downloaded_bytes||0)+" ไบต์":
        number(p.processed||p.files_seen||p.done||0)+
        (job.kind==="recover"||job.kind==="swipe-audit"?" / "+number(p.total):"")+" รายการ");
      if(job.kind==="import"){
        text("import-resume-status",(p.resume?"ทำต่อจาก Checkpoint เดิม":
          "นำเข้าใหม่")+
          " · บันทึกเป็นช่วงทุก 16 ไฟล์ · ข้ามไฟล์เดิมที่ไม่เปลี่ยน "+
          number(p.resumed_files)+" เพลง");
      }
      const progressBar=$("progress-fill");
      const downloaded=(job.kind==="update"||job.kind==="lyrics-edit")&&p.total>0;
      progressBar.classList.toggle("indeterminate",job.status==="running"&&!downloaded);
      progressBar.style.width=job.status==="completed"?"100%":
        downloaded?Math.min(100,100*(p.done||p.downloaded_bytes||0)/p.total).toFixed(1)+"%":
        (job.status==="running"&&job.kind!=="update")?"35%":"0%";
      const signature=job.id+":"+job.status;
      if(state.jobSignature!==signature){
        state.jobSignature=signature;
        if(job.status==="completed"||job.status==="failed"||job.status==="cancelled"){
          try{
            await refreshStatus();
            if(state.view==="risks")await loadRisks();
            else if(state.view!=="import")await refreshSongs();
          }catch(error){
            console.error("[XSTAGE] post-job refresh failed",
              error?.stack||error?.message||String(error));
            void diagnostic("ui.post_job_refresh.error",{
              kind:job.kind,status:job.status,error:error?.message||String(error)
            });
          }
          if((job.kind==="db-clean"||job.kind==="db-compact")&&job.status==="completed")
            await checkDatabaseHealth();
          if(job.kind==="db-audit"&&job.status==="completed")
            renderDatabaseAudit(job.result);
          if(job.kind==="lyrics-edit"&&job.status==="completed"&&state.view==="lyrics")
            await searchGroups();
          toast(job.status==="completed"?"งาน "+(job.kind==="lyrics-edit"?"แทนที่เนื้อร้อง":job.kind==="import"?"นำเข้า":job.kind==="update"?"ดาวน์โหลดอัปเดต":job.kind==="db-audit"?"ตรวจ SQLite":job.kind==="db-clean"?"ล้างประวัติ SQLite":job.kind==="db-compact"?"ย่อ SQLite":job.kind==="recover"?"ตรวจซ่อมเนื้อร้อง":job.kind==="swipe-audit"?"ตรวจหลักฐานปาดเนื้อ":"สร้างไฟล์")+" เสร็จแล้ว":
            job.error||"งานล้มเหลว",job.status==="failed");
          if(job.kind==="update"){
            if(job.status==="completed"&&state.updateInstallIntent){
              state.updateInstallIntent=false;
              try{
                await api("/api/update/install",{});
                text("pro-update-status","ตรวจ SHA-256 ผ่าน · กำลังปิดและเปิด Pro รุ่นใหม่");
                toast("กำลังติดตั้งอัปเดตและเปิดทำงานต่อ");
              }catch(error){
                state.updateBusy=false;
                const reason=error?.message||String(error);
                text("pro-update-status","ติดตั้งไม่สำเร็จ: "+reason);
                text("pro-update-notice-text","ติดตั้งไม่สำเร็จ: "+reason+
                  " · สามารถลองใหม่ได้ หรือใช้ดาวน์โหลด EXE โดยตรง");
                const retry=Boolean(state.updateTarget?.newer);
                $("pro-update-install").disabled=!retry;
                $("pro-update-notice-install").disabled=!retry;
                $("pro-update-quick").disabled=!retry;
                toast(reason,true);
              }
            }else if(job.status==="failed"||job.status==="cancelled"){
              state.updateInstallIntent=false;state.updateBusy=false;
              const problem=job.error||job.message||"ไม่ทราบสาเหตุ";
              text("pro-update-status","ดาวน์โหลดอัปเดตไม่สำเร็จ · "+problem);
              text("pro-update-notice-text","ดาวน์โหลดไม่สำเร็จ: "+problem+
                " · กดอัปเดตอีกครั้ง หรือใช้ปุ่มดาวน์โหลด EXE โดยตรง");
              // Restore ALL update buttons: the old UI left the top banner
              // disabled forever after a failed background update job.
              const retry=Boolean(state.updateTarget?.newer);
              $("pro-update-install").disabled=!retry;
              $("pro-update-notice-install").disabled=!retry;
              $("pro-update-quick").disabled=!retry;
              $("pro-update-quick").hidden=!retry;
            }
            syncSettingsUpdate();
          }
        }
      }
    }catch(error){
      console.error("[XSTAGE] refreshJobs failed",
        error?.stack||error?.message||String(error));
      void diagnostic("ui.jobs.refresh.error",{error:error?.message||String(error)});
      if(state.activeJob){
        text("activity-status","กำลังทำงาน · รออัปเดตหน้าจอ");
        text("activity-subtitle","Backend ยังทำงานอยู่ แต่รอบอ่านสถานะล่าสุดไม่ตอบกลับ · ระบบจะลองใหม่อัตโนมัติ");
      }
      // A jobs/status refresh failure is not proof that the Local Engine died.
      // Keep controls usable; the next poll retries automatically.
    }finally{
      state.jobsRefreshing=false;
    }
  }
  async function openPicker(kind,target){
    const button=$(kind==="folder"?"source-browse":"lrc-browse");
    void diagnostic("ui.picker.click",{kind,current:$(target).value.trim()});
    button.disabled=true;
    if(kind==="folder")text("folder-picker-status","กำลังเปิดหน้าต่างเลือกโฟลเดอร์ของ Windows...");
    try{
      const result=await api("/api/pick",{kind,current:$(target).value.trim()},0);
      if(result.path){
        $(target).value=result.path;
        $(target).dispatchEvent(new Event("input",{bubbles:true}));
        if(kind==="folder"){
          text("folder-picker-status","เลือกโฟลเดอร์แล้ว: "+result.path);
          void diagnostic("ui.picker.selected",{kind,path:result.path});
          toast("เลือกโฟลเดอร์สำเร็จ");
        }else{
          text("media-feedback","เลือกไฟล์ LRC แล้ว: "+result.path);
        }
      }else if(kind==="folder"){
        void diagnostic("ui.picker.cancelled",{kind});
        text("folder-picker-status","ยกเลิกการเลือก · โฟลเดอร์เดิมยังอยู่");
      }
    }catch(error){
      const label=kind==="folder"?"โฟลเดอร์":"ไฟล์ LRC";
      const msg="เลือก"+label+"ไม่สำเร็จ: "+error.message;
      void diagnostic("ui.picker.error",{kind,error:error.message});
      if(kind==="folder")text("folder-picker-status",msg);
      else text("media-feedback",msg);
      toast(msg,true);
    }finally{
      button.disabled=!state.ready;
    }
  }
  async function openLocalFolder(scope){
    const button=$(scope==="workspace"?"workspace-open":"source-open");
    button.disabled=true;
    try{
      const result=await api("/api/open-folder",{
        scope,path:scope==="source"?$("source-folder").value.trim():undefined
      });
      if(result.opened){
        if(scope==="source")text("folder-picker-status","เปิด Explorer: "+result.folder);
        toast("เปิดโฟลเดอร์ใน Windows Explorer แล้ว");
      }
    }catch(error){
      if(scope==="source")text("folder-picker-status",error.message);
      toast("เปิดโฟลเดอร์ไม่ได้: "+error.message,true);
    }finally{button.disabled=!state.ready;}
  }
  function renderIssuePage(){
    const list=$("issues-list");
    list.replaceChildren();
    const size=visibleRows();
    const offset=state.issueOffset;
    const rows=state.issueRows.slice(offset,offset+size);
    if(!rows.length){
      const empty=document.createElement("p");
      empty.className="empty-small";
      empty.textContent="ไม่มีรายการผิดพลาดที่บันทึกไว้";
      list.append(empty);
    }
    for(const item of rows){
      const line=document.createElement("div");line.className="issue-item";
      const header=document.createElement("strong");
      header.textContent=item.source_name+" · "+(
        item.outcome==="error"?"ตรวจไฟล์ผิดพลาด":
        item.outcome==="timing-incomplete"?"Timing ไม่ครบ":
        item.outcome==="partial-lyrics"?"บันทึกเนื้อร้องบางส่วน":
        item.outcome==="untimed-lyrics"?"บันทึกข้อความแล้ว รอ CUR":
        item.outcome==="missing-lyr"?"ไม่พบไฟล์ LYR":"อ่านเนื้อร้องผิดพลาด");
      const detail=document.createElement("p");
      detail.textContent=item.message||"ไม่พบรายละเอียดข้อผิดพลาด";
      line.append(header,detail);list.append(line);
    }
    text("issues-page-info",number(offset+(rows.length?1:0))+"–"+
      number(offset+rows.length)+" / "+number(state.issueRows.length)+" รายการล่าสุด");
    $("issues-prev").disabled=offset<=0;
    $("issues-next").disabled=offset+size>=state.issueRows.length;
  }
  async function loadImportIssues(){
    try{
      const result=await api("/api/import-issues");
      state.issueRows=result.rows||[];
      state.issueOffset=0;
      renderIssuePage();
      $("issues-dialog").showModal();
    }catch(error){toast(error.message,true);}
  }
  const riskCategories={
    structural:"พบหลักฐานผิดปกติ",unverified:"เวลาโดยประมาณ",
    blocked:"ข้อมูล CUR ไม่ครบ",history:"ประวัติการตรวจ"
  };
  const riskRules={
    INVALID_LINE_RANGE:"เวลาเริ่ม–จบบรรทัดไม่ถูกต้อง",
    NO_SWEEP_CUES:"เนื้อร้องไม่มีจุดปาดสี",
    CUE_TEXT_DIFFERS:"ข้อความจุดปาดสีไม่ตรงกับเนื้อร้อง",
    CUE_TIME_REVERSES:"จุดปาดสีเรียงเวลาย้อนกลับ",
    CUE_OUTSIDE_LINE:"จุดปาดสีอยู่นอกช่วงบรรทัด",
    CUE_OVERLAP:"เวลาปาดสีทับตำแหน่งถัดไป",
    ESTIMATED_SWEEP:"จุดปาดสีใช้เวลาประมาณ ยังไม่ยืนยันผิด",
    INCOMPLETE_CUR:"CUR ไม่ครบ ยังปาดสีไม่ได้",
    EMPTY_TIMED_VERSION:"เวอร์ชันนี้ไม่มีบรรทัดพร้อมเวลา"
  };
  const reviewNames={
    opened:"เปิดต้นฉบับ",confirmed:"ฟังแล้วยืนยันว่าผิด",
    passed:"ทดลองแล้วตรง", "needs-review":"ยังต้องตรวจ"
  };
  function riskElement(tag,klass,content){
    const e=document.createElement(tag);
    if(klass)e.className=klass;
    if(content!==undefined)e.textContent=String(content);
    return e;
  }
  async function loadRisks(){
    if(!state.ready)return;
    try{
      const filter=state.riskFilter,offset=state.riskOffset;
      const latest=await api("/api/swipe-risks?category="+
           encodeURIComponent(filter==="history"?"all":filter)+"&limit=5&offset="+
           encodeURIComponent(filter==="history"?0:offset));
      const run=latest.run;
      text("risk-structural",run?number(run.structural_songs):"—");
      text("risk-unverified",run?number(run.estimated_songs):"—");
      text("risk-blocked",run?number(run.blocked_songs):"—");
      text("risk-audit-status",run?
        "ตรวจรอบล่าสุด "+run.finished_at+" · "+number(run.songs_checked)+
        " เพลงที่มี Lyrics Version ปัจจุบัน · ไม่สุ่มตัวอย่าง":
        "ยังไม่มีผลตรวจ กดตรวจเพลงทั้งคลังเพื่อบันทึกหลักฐานจริง");
      for(const b of document.querySelectorAll("[data-risk-filter]"))
        b.classList.toggle("selected",b.dataset.riskFilter===filter);
      if(filter==="history"){
        const log=await api("/api/swipe-history");
        state.riskHistory=[
          ...(log.runs||[]).map(x=>({when:x.started_at,kind:"run",data:x})),
          ...(log.reviews||[]).map(x=>({when:x.created_at,kind:"review",data:x}))
        ].sort((a,b)=>b.when.localeCompare(a.when));
        state.riskTotal=state.riskHistory.length;
        renderRiskHistory();
      }else{
        state.riskTotal=latest.total||0;
        state.riskRows=latest.rows||[];
        renderRiskList();
      }
      updateRiskPagination();
    }catch(error){toast(error.message,true);}
  }
  function updateRiskPagination(){
    const beginning=state.riskTotal?state.riskOffset+1:0;
    const end=Math.min(state.riskOffset+state.riskLimit,state.riskTotal);
    text("risk-page-info",number(beginning)+"–"+number(end)+
      " / "+number(state.riskTotal)+" รายการ");
    $("risk-prev").disabled=state.riskOffset<=0;
    $("risk-next").disabled=state.riskOffset+state.riskLimit>=state.riskTotal;
  }
  function renderRiskList(){
    const target=$("risk-rows");target.replaceChildren();
    text("risk-list-title",riskCategories[state.riskFilter]);
    if(!state.riskRows.length){
      target.append(riskElement("p","risk-empty",
        state.riskTotal?"ไม่มีรายการในหน้านี้":
        "ยังไม่มีรายการที่พบหลักฐานตามตัวกรองนี้ · ไม่แสดงเพลงที่ไม่มีหลักฐาน"));
      return;
    }
    for(const entry of state.riskRows){
      const card=riskElement("article","risk-record");
      const main=riskElement("div","risk-record-main");
      const identity=riskElement("strong","risk-song-name",
        String(entry.code).padStart(8,"0")+" · "+entry.title);
      const desc=riskElement("p","risk-song-meta",
        (entry.artist||"ไม่ระบุศิลปิน")+" · "+entry.extension.toUpperCase()+
        " · "+(reviewNames[entry.review_status]||"ยังไม่ได้ทดลองฟัง"));
      const proof=riskElement("p","risk-proof",
        (riskRules[entry.rule]||entry.rule)+" · "+
        (entry.line_position>=0?"บรรทัด "+(entry.line_position+1)+" · ":"")+
        entry.evidence);
      main.append(identity,desc,proof);
      const action=riskElement("button","quiet-btn risk-detail-button","ดูหลักฐาน / ทดลองเปิด");
      action.type="button";
      action.addEventListener("click",()=>openRiskDialog(entry));
      card.append(main,action);target.append(card);
    }
  }
  function renderRiskHistory(){
    const target=$("risk-rows");target.replaceChildren();
    text("risk-list-title","ประวัติการตรวจและทดลองฟัง");
    const rows=state.riskHistory.slice(state.riskOffset,state.riskOffset+state.riskLimit);
    if(!rows.length){
      target.append(riskElement("p","risk-empty","ยังไม่มีประวัติการตรวจหรือทดลองฟัง"));return;
    }
    for(const entry of rows){
      const line=riskElement("article","risk-record");
      if(entry.kind==="run"){
        const run=entry.data;
        const box=riskElement("div","risk-record-main");
        box.append(
          riskElement("strong","risk-song-name","รอบตรวจ · "+entry.when),
          riskElement("p","risk-song-meta",
            "ตรวจ "+number(run.songs_checked)+" เพลง · ผิดปกติ "+number(run.structural_songs)+
            " · ประมาณ "+number(run.estimated_songs)+" · CUR ไม่ครบ "+number(run.blocked_songs)+
            " · "+run.status)
        );
        line.append(box);
      }else{
        const review=entry.data;
        const box=riskElement("div","risk-record-main");
        box.append(
          riskElement("strong","risk-song-name",
            String(review.code).padStart(8,"0")+" · "+review.title),
          riskElement("p","risk-song-meta",
            (reviewNames[review.action]||review.action)+" · "+entry.when),
          riskElement("p","risk-proof",review.note||"ไม่ได้ระบุหมายเหตุ")
        );
        line.append(box);
      }
      target.append(line);
    }
  }
  function openRiskDialog(item){
    state.riskSelected=item;state.riskEvidenceIndex=0;
    text("risk-modal-title",String(item.code).padStart(8,"0")+" · "+item.title);
    text("risk-modal-description",
      "Lyrics Version "+item.version_id+" · "+riskCategories[item.category]+
      " · ผลการฟัง: "+(reviewNames[item.review_status]||"ยังไม่ได้ทดลองฟัง"));
    $("risk-review-note").value="";
    renderRiskEvidence();
    $("risk-dialog").showModal();
  }
  function renderRiskEvidence(){
    const item=state.riskSelected;
    if(!item)return;
    const findings=item.findings||[];
    const evidence=findings[state.riskEvidenceIndex];
    const target=$("risk-evidence-content");target.replaceChildren();
    if(evidence){
      const title=riskElement("strong","risk-evidence-title",riskRules[evidence.rule]||evidence.rule);
      const line=riskElement("p","risk-evidence-meta",
        evidence.line_position<0?"ทั้งเวอร์ชัน":
        "บรรทัด "+(evidence.line_position+1)+" · "+Number(evidence.line_start).toFixed(2)+
        "–"+Number(evidence.line_end).toFixed(2)+" วินาที");
      const words=riskElement("p","risk-evidence-lyrics",evidence.excerpt||"");
      const description=riskElement("p","risk-evidence-description",evidence.evidence);
      target.append(title,line,words,description);
    }
    text("risk-evidence-page",number(state.riskEvidenceIndex+1)+
       " / "+number(findings.length)+" หลักฐาน");
    $("risk-evidence-prev").disabled=state.riskEvidenceIndex<=0;
    $("risk-evidence-next").disabled=state.riskEvidenceIndex+1>=findings.length;
  }
  async function saveRiskReview(action){
    const item=state.riskSelected;
    if(!item)return;
    const note=$("risk-review-note").value.trim();
    try{
      await api("/api/swipe/review",{
        song_id:item.song_id,version_id:item.version_id,action,note
      });
      $("risk-dialog").close();
      toast("บันทึกผลการทดลองลงประวัติ SQLite แล้ว");
      await loadRisks();
    }catch(error){toast(error.message,true);}
  }
  async function openRiskSource(){
    if(!state.riskSelected)return;
    const item=state.riskSelected;
    try{
      const answer=await api("/api/swipe/open-source",{
        song_id:item.song_id,version_id:item.version_id
      });
      toast(answer.note||"เปิดต้นฉบับแล้ว · ยังไม่ได้ยืนยันปาดสี");
      await loadRisks();
    }catch(error){toast(error.message,true);}
  }
  function riskFilterChanged(filter){
    state.riskFilter=filter;state.riskOffset=0;
    void loadRisks();
  }
  function previewFormatSeconds(seconds){
    if(!Number.isFinite(seconds))return "00:00";
    const whole=Math.max(0,Math.floor(seconds));
    return String(Math.floor(whole/60)).padStart(2,"0")+":"+
      String(whole%60).padStart(2,"0");
  }
  async function loadPreviewSongs(){
    if(!state.ready)return;
    try{
      const pageSize=visibleRows();
      const found=await api("/api/songs?q="+encodeURIComponent($("preview-search").value.trim())+
        "&limit="+(pageSize+1)+"&offset="+state.previewOffset);
      state.previewHasNext=(found.rows||[]).length>pageSize;
      state.previewSongs=(found.rows||[]).slice(0,pageSize);
      renderPreviewSongs();
    }catch(error){toast(error.message,true);}
  }
  function renderPreviewSongs(){
    const box=$("preview-songs");box.replaceChildren();
    if(!state.previewSongs.length){
      const empty=document.createElement("p");
      empty.className="empty-small";empty.textContent="ไม่พบเพลงที่ตรงคำค้น";
      box.append(empty);
    }
    for(const song of state.previewSongs){
      const button=document.createElement("button");
      button.type="button";button.className="preview-track";
      button.classList.toggle("chosen",state.previewSelected?.song_id===song.id);
      const title=document.createElement("strong");
      title.textContent=String(song.code).padStart(8,"0")+" · "+song.title;
      const small=document.createElement("small");
      small.textContent=(song.artist||"ไม่ระบุศิลปิน")+
        " · "+song.extension.toUpperCase()+" · "+
        (song.version_id?(song.timing_status==="incomplete"?"CUR ไม่ครบ":song.timing_status):
          "ยังไม่มีเวลาปาด");
      button.append(title,small);
      button.addEventListener("click",()=>void selectPreviewSong(song));
      box.append(button);
    }
    text("preview-page","หน้า "+number(Math.floor(state.previewOffset/visibleRows())+1));
    $("preview-prev").disabled=state.previewOffset<=0;
    $("preview-next").disabled=!state.previewHasNext;
  }
  function currentPreviewMedia(){
    return state.previewSelected?.mode==="video"?$("preview-video"):$("preview-audio");
  }
  async function stopPreviewPlayback(){
    const old=state.previewSelected;
    state.previewPlaying=false;
    for(const e of [$("preview-audio"),$("preview-video")]){e.pause();e.removeAttribute("src");e.load();}
    if(old?.mode==="midi"&&state.token){
      try{await api("/api/preview/midi/stop",{});}catch{/* engine may be shutting down */}
    }
    if(state.previewMidiPoll){clearInterval(state.previewMidiPoll);state.previewMidiPoll=null;}
  }
  async function selectPreviewSong(song){
    await stopPreviewPlayback();
    state.previewSelected=null;
    state.previewTime=0;state.previewDuration=0;state.previewHeard=false;
    updatePreviewControls();
    try{
      const details=await api("/api/preview?song_id="+encodeURIComponent(song.id));
      state.previewSelected=details;
      state.previewDuration=details.duration||0;
      state.previewTime=0;
      state.previewMidiSample=0;
      state.previewMidiAt=performance.now();
      text("preview-song-title",String(details.code).padStart(8,"0")+" · "+details.title);
      text("preview-song-artist",details.artist||"ไม่ระบุศิลปิน");
      text("preview-media-mode",details.mode==="midi"?"MIDI / Windows Synth":
        details.mode==="video"?"VIDEO / Original":"AUDIO / Original");
      text("preview-warning",details.warning);
      text("preview-review-status",
        details.version_id?"ยังไม่มีผลตรวจจากการฟังเพลงนี้ในหน้านี้":
        "ยังไม่มีเนื้อร้องพร้อมเวลา · ทดสอบเสียงต้นฉบับได้ แต่ยังสร้าง .x... ไม่ได้");
      $("preview-video").hidden=details.mode!=="video";
      $("preview-cover").hidden=details.mode==="video";
      if(details.mode!=="midi"){
        const media=currentPreviewMedia();
        media.src="/api/preview/media?song_id="+encodeURIComponent(song.id)+
          "&token="+encodeURIComponent(state.token);
        media.load();
      }
      renderPreviewSongs();
      updatePreviewControls();
      updatePreviewLyrics();
    }catch(error){
      text("preview-warning",error.message);
      toast(error.message,true);
    }
  }
  function updatePreviewControls(){
    const detail=state.previewSelected;
    const selected=Boolean(detail);
    const canReview=selected&&Boolean(detail.version_id)&&state.previewHeard;
    $("preview-play").disabled=!selected;
    $("preview-pause").disabled=!selected||!state.previewPlaying;
    $("preview-seek").disabled=!selected||state.previewDuration<=0;
    $("preview-seek").max=String(Math.max(0,state.previewDuration));
    if(!state.previewSeeking)
      $("preview-seek").value=String(Math.min(state.previewDuration,state.previewTime));
    $("preview-pass").disabled=!canReview;
    $("preview-fail").disabled=!canReview;
    $("preview-needs").disabled=!selected||!detail.version_id;
    $("preview-note").disabled=!selected||!detail.version_id;
    $("preview-to-build").disabled=!selected||!detail.version_id||
      detail.timing_status==="incomplete";
    text("preview-clock",previewFormatSeconds(state.previewTime)+
      " / "+previewFormatSeconds(state.previewDuration));
  }
  async function playPreview(){
    const track=state.previewSelected;
    if(!track)return;
    try{
      if(track.mode==="midi"){
        const status=await api("/api/preview/midi/play",{
          song_id:track.song_id,seek:Math.min(state.previewTime,
            Math.max(0,state.previewDuration-0.05))
        });
        if(status.status==="error")throw new Error(status.error||"MIDI Synthesizer ไม่พร้อม");
        state.previewMidiSample=status.position||0;
        state.previewMidiAt=performance.now();
        state.previewPlaying=true;
        state.previewHeard=true;
        if(!state.previewMidiPoll)
          state.previewMidiPoll=setInterval(()=>void pollPreviewMidi(),250);
      }else{
        const media=currentPreviewMedia();
        await media.play();
        state.previewPlaying=true;
        state.previewHeard=true;
      }
      text("preview-warning",track.warning);
      updatePreviewControls();
      requestPreviewFrame();
    }catch(error){
      state.previewPlaying=false;
      text("preview-warning","เล่นเสียงไม่ได้: "+error.message+
        " · ไม่บันทึกว่าตรวจการปาดสีผ่าน");
      toast(error.message,true);
      updatePreviewControls();
    }
  }
  async function pausePreview(){
    const track=state.previewSelected;
    if(!track)return;
    if(track.mode==="midi"){
      try{
        const status=await api("/api/preview/midi/pause",{});
        state.previewTime=status.position;
      }catch(error){toast(error.message,true);}
    }else{
      currentPreviewMedia().pause();
      state.previewTime=currentPreviewMedia().currentTime||0;
    }
    state.previewPlaying=false;
    updatePreviewControls();
    updatePreviewLyrics();
  }
  async function seekPreview(seconds){
    const track=state.previewSelected;if(!track)return;
    state.previewTime=Math.max(0,Math.min(state.previewDuration,Number(seconds)||0));
    if(track.mode==="midi"){
      if(state.previewPlaying)await playPreview();
    }else{
      const player=currentPreviewMedia();
      if(Number.isFinite(player.duration))player.currentTime=state.previewTime;
    }
    updatePreviewControls();updatePreviewLyrics();
  }
  async function pollPreviewMidi(){
    if(!state.previewSelected||state.previewSelected.mode!=="midi"||
       !state.previewPlaying||state.previewPolling)return;
    state.previewPolling=true;
    try{
      const result=await api("/api/preview/midi/status");
      if(result.song_id!==state.previewSelected.song_id)return;
      state.previewMidiSample=result.position||0;
      state.previewMidiAt=performance.now();
      if(result.status!=="playing"){
        state.previewPlaying=false;
        state.previewTime=result.position||0;
        if(result.status==="error")text("preview-warning",
          "Windows MIDI Synthesizer ไม่สามารถเล่นเพลงนี้ได้ · ไม่ยืนยันเวลาปาดสี");
        updatePreviewControls();updatePreviewLyrics();
      }
    }catch(error){toast(error.message,true);}
    finally{state.previewPolling=false;}
  }
  function requestPreviewFrame(){
    if(state.previewRaf!==null)return;
    const loop=time=>{
      state.previewRaf=null;
      if(state.view!=="preview"||!state.previewSelected)return;
      if(state.previewPlaying){
        if(state.previewSelected.mode==="midi"){
          state.previewTime=Math.min(state.previewDuration,
            state.previewMidiSample+(performance.now()-state.previewMidiAt)/1000);
        }else{
          const player=currentPreviewMedia();
          state.previewTime=player.currentTime||0;
        }
        if(time-state.previewLastPaint>45){
          state.previewLastPaint=time;
          updatePreviewControls();updatePreviewLyrics();
        }
        state.previewRaf=requestAnimationFrame(loop);
      }
    };
    state.previewRaf=requestAnimationFrame(loop);
  }
  function updatePreviewLyrics(){
    const details=state.previewSelected;
    const present=$("preview-current-line");
    const next=$("preview-next-line");
    present.replaceChildren();
    if(!details){present.textContent="♪  เนื้อร้องและเวลาปาดสีจากฐาน SQLite";next.textContent="เลือกเพลง";return;}
    const lines=details.lines||[];
    if(!lines.length){
      present.textContent=details.draft?"พบเนื้อร้อง LYR แต่ไม่มี Timing":"ยังไม่มีเนื้อร้องพร้อมเวลา";
      next.textContent=details.draft?.raw_text?.split("\n").find(x=>x.trim())||
        "ไม่สร้างเวลา CUR ที่ไม่มีอยู่จริง";
      return;
    }
    const current=state.previewTime;
    let index=lines.findIndex((line,i)=>
      current>=line.start&&current<(line.end||line.start+.5));
    if(index===-1){
      index=lines.findIndex(line=>line.start>current);
      if(index===-1)index=lines.length-1;
    }
    const line=lines[index];
    const cues=line.cues||[];
    if(cues.length){
      for(const cue of cues){
        const elem=document.createElement("span");
        elem.textContent=cue.text;
        elem.className="preview-glyph";
        const progress=cue.duration<=0?(current>=cue.start?100:0):
          Math.max(0,Math.min(100,(current-cue.start)/cue.duration*100));
        elem.style.setProperty("--sweep",progress.toFixed(1)+"%");
        present.append(elem);
      }
    }else{
      present.textContent=line.text||"—";
    }
    next.textContent=lines[index+1]?.text||(
      line.timing==="incomplete"?"CUR ยังไม่ครบ · ไม่จำลองเวลาที่ขาด":
      "♪");
  }
  async function recordPreviewOutcome(action){
    const track=state.previewSelected;
    if(!track?.version_id)return;
    const note=$("preview-note").value.trim();
    try{
      await api("/api/preview/review",{
        song_id:track.song_id,version_id:track.version_id,
        action,note
      });
      const label={passed:"ฟังแล้วตรง",confirmed:"พบปาดผิดจริง",
                   "needs-review":"ยังต้องตรวจต่อ"}[action];
      text("preview-review-status","บันทึกแล้ว: "+label+" · เวอร์ชัน "+track.version_id);
      toast("บันทึกประวัติการฟังจริงใน SQLite แล้ว");
    }catch(error){toast(error.message,true);}
  }
  function previewToBuild(){
    const track=state.previewSelected;
    if(!track?.version_id||track.timing_status==="incomplete")return;
    state.selectedSongs.add(track.song_id);
    void stopPreviewPlayback();
    view("build");
    updateBuildSelection();
    toast("เลือก "+track.title+" เข้ารายการสร้าง .x... แล้ว");
  }


  // UI layout modes never modify source lyrics, playback position, or selection.
  function manualApplyLayout(){
    const active=state.view==="manual",layout=state.manualLayout;
    const focused=active&&layout.focus;
    const app=document.querySelector(".app");
    const manual=$("view-manual");
    app.classList.toggle("manual-editor-menu-hidden",
      active&&(focused||layout.menu));
    manual.classList.toggle("manual-editor-queue-hidden",
      active&&(focused||layout.queue));
    manual.classList.toggle("manual-editor-stage-expanded",
      active&&!focused&&layout.stage);
    manual.classList.toggle("manual-editor-focused",focused);
    for(const [id,pressed,yes,no] of [
      ["manual-toggle-menu",focused||layout.menu,"☰ แสดงเมนูหลัก","☰ ซ่อนเมนูหลัก"],
      ["manual-toggle-queue",focused||layout.queue,"▣ แสดงรายการเพลง","▣ ซ่อนรายการเพลง"],
      ["manual-toggle-stage",layout.stage,"▤ ย่อจอคาราโอเกะ","⛶ ขยายจอคาราโอเกะ"],
      ["manual-focus",focused,"↙ กลับมุมมองปกติ","↗ โหมดแก้ไขเต็มพื้นที่"]
    ]){
      const node=$(id);if(!node)continue;
      node.setAttribute("aria-pressed",String(Boolean(pressed)));
      node.textContent=pressed?yes:no;
    }
    text("manual-layout-state",focused?
      "โหมดแก้ไขเต็มพื้นที่ · คลิกอีกครั้งเพื่อกลับ":"ปรับพื้นที่ได้โดยไม่ลบข้อมูลหรือหยุดเพลง");
  }
  const manualIssueRank={structural:0,missing:1,unverified:2};
  const manualIssueText={structural:"พบผิดโครงสร้าง",missing:"ข้อมูลขาด",
    unverified:"รอฟังยืนยัน"};
  function manualCheckDraft(lines){
    const findings=[];
    const add=(category,rule,line_position,found,suggestion)=>findings.push({
      category,rule,line_position,found,suggestion
    });
    if(!lines.length){
      add("missing","NO_LYRICS",-1,"ไม่มีเนื้อร้องในรายการนี้",
        "เพิ่มบรรทัดหรือวางเนื้อร้องก่อน แล้วค่อยจับเวลาจากเพลงต้นฉบับ");
      return findings;
    }
    lines.forEach((line,index)=>{
      const raw=String(line.text||"");
      if(!raw.trim())return;
      if(line.start===null||line.start===undefined||line.start===""||
         line.end===null||line.end===undefined||line.end===""){
        add("missing","LINE_UNTIMED",index,
          "บรรทัดนี้ไม่มีเวลาเริ่มหรือจบครบ",
          "ฟังเพลงต้นฉบับแล้วจับเวลาเริ่มและจบบรรทัด");
        return;
      }
      const start=Number(line.start),end=Number(line.end);
      if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<=start){
        add("structural","LINE_RANGE_INVALID",index,
          "เวลาจบบรรทัดไม่มากกว่าเวลาเริ่ม หรือค่าเวลาไม่ถูกต้อง",
          "ตรวจและแก้เวลาเริ่ม–จบให้ตรงจากเพลงต้นฉบับ");
        return;
      }
      const segments=manualSegments(line),times=manualStartTimes(line);
      if(!segments.length||!times.length){
        add("missing","CUES_MISSING",index,
          "มีบรรทัดพร้อมเวลา แต่ยังไม่มีจุดปาดคำ",
          "แบ่งคำด้วยเครื่องหมาย | แล้วจับเวลาเริ่มปาดแต่ละคำขณะเล่นจริง");
        return;
      }
      if(segments.length!==times.length||
         times.some(v=>v===null||v===undefined||v==="")){
        add("missing","CUES_PARTIAL",index,
          "จุดปาดคำยังไม่ครบทุกช่วงข้อความ",
          "เลือกคำที่ยังขาดเวลาแล้วจับเวลาปาดจากเสียงจริง");
        return;
      }
      if(segments.join("")!==raw)
        add("structural","CUES_TEXT_MISMATCH",index,
          "ข้อความจากจุดปาดไม่ตรงกับเนื้อร้องทั้งบรรทัด",
          "แบ่งคำใหม่ให้รวมแล้วตรงข้อความเดิม รวมช่องว่างและสระวรรณยุกต์");
      const values=times.map(Number);
      if(values.some(v=>!Number.isFinite(v))||values[0]<start-0.001||
         values[values.length-1]>=end||
         values.some((v,k)=>k>0&&v<values[k-1]))
        add("structural","CUES_TIME_OUT_OF_RANGE",index,
          "เวลาปาดอยู่นอกช่วงของบรรทัดหรือย้อนลำดับ",
          "เลื่อนกลับไปฟังและจับเวลาปาดแต่ละคำใหม่");
      if(line.timing==="estimated")
        add("unverified","ESTIMATED_TIMING",index,
          "เวลาบรรทัดนี้เป็นค่าประมาณ ยังไม่ยืนยันว่าผิดจริง",
          "ทดลองฟังกับเพลงแล้วตรวจตำแหน่งปาด ก่อนกดยืนยัน");
    });
    return findings;
  }
  function manualGetFindings(){
    if(!state.manualSelected)return [];
    return state.manualFindings||[];
  }
  function manualFocusLine(index){
    if(!state.manualSelected||index<0||index>=state.manualLines.length)return;
    if(state.manualOnlyIssues){
      state.manualOnlyIssues=false;
      $("manual-only-issues").setAttribute("aria-pressed","false");
      $("manual-only-issues").textContent="แสดงเฉพาะบรรทัดที่ต้องตรวจ";
    }
    $("manual-line-index").value=String(index);
    manualRenderLines();
    const card=$("manual-line-list").querySelector('[data-manual-line="'+index+'"]');
    if(card){
      card.scrollIntoView({block:"nearest",behavior:"smooth"});
      const edit=card.querySelector('input[type="text"]');
      if(edit)edit.focus({preventScroll:true});
    }
    const line=state.manualLines[index];
    if(line?.start!==null&&line?.start!==""&&Number.isFinite(Number(line.start))){
      void manualSeek(Number(line.start));
    }
  }
  function manualRenderFindings(){
    const findings=manualGetFindings().slice().sort((a,b)=>
      (manualIssueRank[a.category]??3)-(manualIssueRank[b.category]??3)||
      a.line_position-b.line_position);
    const summary={structural:0,missing:0,unverified:0};
    findings.forEach(f=>{if(f.category in summary)summary[f.category]++;});
    text("manual-diagnostic-summary",
      "พบผิดโครงสร้าง "+number(summary.structural)+
      " · ข้อมูลขาด "+number(summary.missing)+
      " · ต้องฟังยืนยัน "+number(summary.unverified));
    const select=$("manual-diagnostic-filter"),target=$("manual-diagnostic-list");
    const selected=select?.value||"all";
    const view=selected==="all"?findings:findings.filter(f=>f.category===selected);
    target.replaceChildren();
    if(!view.length){
      const node=document.createElement("p");node.className="empty-small";
      node.textContent=state.manualSelected?
        (findings.length?"ไม่มีจุดที่ตรงกับตัวกรองนี้":
          "ไม่พบข้อมูลผิดโครงสร้างจากตัวตรวจ · ยังต้องฟังจริงเพื่อยืนยัน"):
        "เลือกเพลงเพื่อดูผลการตรวจ";
      target.append(node);
    }
    for(const issue of view.slice(0,36)){
      const button=document.createElement("button");
      button.type="button";button.className="manual-finding is-"+issue.category;
      const tag=document.createElement("span");
      tag.className="manual-finding-tag";
      tag.textContent=manualIssueText[issue.category]||"ตรวจสอบ";
      const message=document.createElement("span");
      message.className="manual-finding-message";
      const title=document.createElement("strong");
      const prefix=issue.line_position>=0?"บรรทัด "+(issue.line_position+1)+" · ":"ทั้งเพลง · ";
      title.textContent=prefix+issue.found;
      const excerpt=state.manualLines[issue.line_position]?.text;
      if(excerpt){
        const quote=document.createElement("small");
        quote.className="manual-finding-excerpt";
        quote.textContent="ข้อความที่ตรวจ: “"+String(excerpt).slice(0,110)+"”";
        message.append(title,quote);
      }else message.append(title);
      const recommend=document.createElement("small");
      recommend.textContent="แนะนำ: "+issue.suggestion;
      message.append(recommend);
      button.append(tag,message);
      if(issue.line_position>=0){
        const jump=document.createElement("span");
        jump.className="manual-finding-jump";jump.textContent="เปิดแก้ ›";
        button.append(jump);
        button.addEventListener("click",()=>manualFocusLine(issue.line_position));
      }else button.addEventListener("click",()=>{
        if(state.manualLines.length)manualFocusLine(0);
        else $("manual-add-line").focus();
      });
      target.append(button);
    }
    if(view.length>36){
      const more=document.createElement("p");more.className="field-hint";
      more.textContent="แสดง 36 จุดแรกจาก "+number(view.length)+
        " จุด · ใช้ตัวกรองหรือเลือกบรรทัดเพื่อดูส่วนที่เหลือ";
      target.append(more);
    }
    const severityByLine=new Map();
    for(const issue of findings){
      if(issue.line_position<0)continue;
      const old=severityByLine.get(issue.line_position);
      if(!old||(manualIssueRank[issue.category]??3)<(manualIssueRank[old]??3))
        severityByLine.set(issue.line_position,issue.category);
    }
    for(const card of $("manual-line-list").children){
      if(!card.dataset?.manualLine)continue;
      const severity=severityByLine.get(Number(card.dataset.manualLine));
      for(const level of ["structural","missing","unverified"])
        card.classList.toggle("manual-suspect-"+level,severity===level);
      const marker=card.querySelector(".manual-line-issue");
      if(marker)marker.textContent=severity?manualIssueText[severity]:"";
    }
  }
  function manualRefreshLiveFindings(){
    if(!state.manualSelected)return;
    state.manualFindings=manualCheckDraft(state.manualLines);
    manualRenderFindings();
  }

  // Menu 05 uses measured or manually captured timestamps only.
  function manualLineNumber(value){
    return Number.isFinite(Number(value))&&value!==""&&value!==null?
      Number(value).toFixed(3):"";
  }
  function manualSelectedLine(){
    return state.manualLines[Number($("manual-line-index").value)||0]||null;
  }
  function manualSegments(line){
    return Array.isArray(line.segments)?line.segments:[];
  }
  function manualStartTimes(line){
    return Array.isArray(line.starts)?line.starts:[];
  }
  function manualControls(){
    const selected=Boolean(state.manualSelected);
    for(const id of ["manual-play","manual-add-line","manual-save","manual-skip",
                     "manual-paste-add","manual-mark-start","manual-mark-cue","manual-mark-end"]){
      $(id).disabled=!selected||(id==="manual-play"&&!state.manualPreview);
    }
    $("manual-pause").disabled=!selected||!state.manualPlaying;
    $("manual-seek").disabled=!selected||!state.manualPreview||
      state.manualDuration<=0;
    $("manual-seek").max=String(Math.max(0,state.manualDuration));
    $("manual-seek").value=String(Math.max(0,Math.min(state.manualDuration,state.manualTime)));
    text("manual-clock",previewFormatSeconds(state.manualTime)+" / "+
      previewFormatSeconds(state.manualDuration));
    manualTimeline?.tick();
    $("manual-approve").disabled=!selected||!state.manualHeard||state.manualDirty||
      !state.manualSelected?.song?.version_id||
      state.manualSelected?.song?.timing_status==="incomplete";
  }
  async function loadManualQueue(){
    if(!state.ready)return;
    try{
      const params=new URLSearchParams({
        q:$("manual-search").value.trim(),filter:$("manual-filter").value,
        offset:String(state.manualOffset),limit:String(visibleRows())
      });
      const result=await api("/api/manual/queue?"+params.toString());
      state.manualRows=result.rows||[];
      state.manualTotal=result.total||0;
      const list=$("manual-song-list");list.replaceChildren();
      for(const song of state.manualRows){
        const button=document.createElement("button");
        button.type="button";button.className="preview-track";
        button.classList.toggle("chosen",state.manualSelected?.song?.id===song.id);
        const title=document.createElement("strong");
        title.textContent=String(song.code).padStart(8,"0")+" · "+song.title;
        const label=document.createElement("small");
        const statuses={missing:"ยังไม่มีเนื้อร้อง",untimed:"มีข้อความ / ไม่มีเวลา",
          incomplete:"เนื้อร้องหรือเวลาปาดไม่ครบ",review:"รอการยืนยัน",
          ready:"พร้อมสร้าง .X"};
        label.textContent=(song.artist||"ไม่ระบุศิลปิน")+" · "+
          (statuses[song.review_status]||song.review_status)+
          (song.decision==="skip"?" · ข้ามไว้":"");
        button.append(title,label);
        button.addEventListener("click",()=>void manualOpenSong(song.id));
        list.append(button);
      }
      if(!state.manualRows.length){
        const item=document.createElement("p");item.className="empty-small";
        item.textContent="ไม่มีเพลงในกลุ่มนี้";list.append(item);
      }
      text("manual-total",number(state.manualTotal)+" เพลง");
      text("manual-page-label","หน้า "+number(Math.floor(state.manualOffset/visibleRows())+1));
      $("manual-prev").disabled=state.manualOffset===0;
      $("manual-next").disabled=state.manualOffset+visibleRows()>=state.manualTotal;
    }catch(error){toast(error.message,true);}
  }
  async function manualStop(){
    if(state.manualPoll){clearInterval(state.manualPoll);state.manualPoll=null;}
    if(state.manualClockTimer){clearInterval(state.manualClockTimer);state.manualClockTimer=null;}
    const wasMidi=state.manualPreview?.mode==="midi";
    state.manualPlaying=false;
    for(const id of ["manual-audio","manual-video"]){
      const media=$(id);media.pause();media.removeAttribute("src");media.load();
    }
    if(wasMidi&&state.token){
      try{await api("/api/preview/midi/stop",{});}catch{/* engine closing */}
    }
  }
  function manualRefreshSelectors(){
    const select=$("manual-line-index");
    const previous=Number(select.value)||0;
    select.replaceChildren();
    state.manualLines.forEach((line,index)=>{
      const title=(index+1)+" · "+(line.text||"ยังไม่มีข้อความ");
      select.append(new Option(title.slice(0,66),String(index)));
    });
    if(state.manualLines.length){
      select.value=String(Math.min(previous,state.manualLines.length-1));
    }
    manualRefreshCues();
  }
  function manualRefreshCues(){
    const line=manualSelectedLine(),select=$("manual-cue-index");
    const previous=Number(select.value)||0;
    select.replaceChildren();
    if(!line)return;
    manualSegments(line).forEach((word,index)=>{
      select.append(new Option((index+1)+" · "+word.slice(0,40),String(index)));
    });
    if(select.options.length)
      select.value=String(Math.min(previous,select.options.length-1));
    manualSetSelectedCueVisual();
    manualTimeline?.render();
  }
  function manualSetSelectedCueVisual(){
    const lineIndex=Number($("manual-line-index").value)||0;
    const cueIndex=Number($("manual-cue-index").value)||0;
    for(const chip of $("manual-line-list").querySelectorAll(".manual-cue-token")){
      const card=chip.closest("[data-manual-line]");
      chip.classList.toggle("is-selected",Number(card?.dataset.manualLine)===lineIndex&&
        Number(chip.dataset.cue)===cueIndex);
    }
    manualTimeline?.selection();
  }
  function manualDraftState(){
    state.manualDirty=true;
    state.manualHeard=false;
    $("manual-approve").disabled=true;
    text("manual-edit-status","ยังไม่บันทึกการแก้ไข");
    manualRefreshLiveFindings();
  }
  function manualRenderLines(){
    const list=$("manual-line-list");list.replaceChildren();
    const activeIndex=Number($("manual-line-index").value)||0;
    const issueLines=new Set(manualGetFindings().filter(f=>
      f.line_position>=0).map(f=>f.line_position));
    state.manualLines.forEach((line,index)=>{
      if(state.manualOnlyIssues&&!issueLines.has(index))return;
      const card=document.createElement("div");card.className="manual-line-card";
      card.dataset.manualLine=String(index);
      card.classList.toggle("is-expanded",index===activeIndex);
      card.classList.toggle("manual-line-active",index===activeIndex);
      const top=document.createElement("div");top.className="manual-line-top";
      const num=document.createElement("strong");num.textContent="บรรทัด "+(index+1);
      const excerpt=document.createElement("span");excerpt.className="manual-line-preview";
      excerpt.textContent=line.text||"ยังไม่มีข้อความ";
      excerpt.title=line.text||"";
      const issueTag=document.createElement("span");issueTag.className="manual-line-issue";
      const choose=document.createElement("button");
      choose.type="button";choose.className="quiet-btn";choose.textContent="เลือกบรรทัด";
      choose.addEventListener("click",()=>manualFocusLine(index));
      top.append(num,excerpt,issueTag,choose);
      const words=document.createElement("input");words.type="text";
      words.value=line.text||"";words.maxLength=400;
      words.placeholder="เนื้อร้องบรรทัดนี้";
      words.setAttribute("aria-label","เนื้อร้องบรรทัด "+(index+1));
      words.addEventListener("input",()=>{
        line.text=words.value;manualDraftState();manualTimeline?.render();
        const option=$("manual-line-index").options[index];
        if(option)option.textContent=(index+1)+" · "+(line.text||"ยังไม่มีข้อความ").slice(0,60);
      });
      const times=document.createElement("div");times.className="manual-times";
      for(const [property,label] of [["start","เริ่ม (วินาที)"],["end","จบ (วินาที)"]]){
        const input=document.createElement("input");input.inputMode="decimal";
        input.type="number";input.min="0";input.step="0.001";
        input.placeholder=label;
        input.value=manualLineNumber(line[property]);
        input.addEventListener("input",()=>{line[property]=input.value;manualDraftState();manualTimeline?.render();});
        times.append(input);
      }
      const cueStrip=document.createElement("div");
      cueStrip.className="manual-cue-strip";
      cueStrip.setAttribute("role","group");
      cueStrip.setAttribute("aria-label","เลือกช่วงข้อความเพื่อปาด");
      const cueLabel=document.createElement("small");
      cueLabel.textContent="เลือกช่วงข้อความ แล้วกดจับเวลา:";
      cueStrip.append(cueLabel);
      for(const [cueIndex,segment] of manualSegments(line).entries()){
        const item=document.createElement("button");
        item.type="button";item.className="manual-cue-token";
        const measured=manualStartTimes(line)[cueIndex];
        item.textContent=segment+" · "+(measured===""||measured==null?
          "ยังไม่จับเวลา":Number(measured).toFixed(2)+" วิ.");
        item.dataset.cue=String(cueIndex);
        item.setAttribute("aria-label","ช่วง "+(cueIndex+1)+" "+segment+" เวลา "+
          (measured===""||measured==null?"ยังไม่มี":measured+" วินาที"));
        item.addEventListener("click",()=>{
          $("manual-line-index").value=String(index);
          manualRefreshCues();
          $("manual-cue-index").value=String(cueIndex);
          manualSetSelectedCueVisual();
          manualDrawKaraoke();
        });
        cueStrip.append(item);
      }
      const rollback=document.createElement("button");
      rollback.type="button";rollback.className="quiet-btn manual-cue-undo";
      rollback.textContent="↶ คืนเวลาก่อนแก้";
      rollback.disabled=!state.manualCueUndo.has(index);
      rollback.addEventListener("click",()=>{
        const previous=state.manualCueUndo.get(index);
        if(!previous)return;
        line.starts=previous.slice();
        state.manualCueUndo.delete(index);
        manualDraftState();manualRenderLines();
      });
      cueStrip.append(rollback);
      const segments=document.createElement("input");
      segments.type="text";segments.placeholder="แบ่งคำ เช่น รัก|เธอ|เสมอ";
      segments.value=manualSegments(line).join("|");
      segments.addEventListener("change",()=>{
        const old=manualSegments(line).join("|");
        line.segments=segments.value?segments.value.split("|"):[];
        if(old!==segments.value)line.starts=[];
        state.manualCueUndo.delete(index);
        manualRefreshCues();manualDraftState();manualRenderLines();
      });
      const starts=document.createElement("input");
      starts.type="text";starts.placeholder="เวลาปาดแต่ละคำ เช่น 2.1,2.5,3.4";
      starts.value=manualStartTimes(line).join(",");
      starts.addEventListener("change",()=>{
        line.starts=starts.value?starts.value.split(",").map(s=>s.trim()):[];
        manualDraftState();manualDrawKaraoke();manualTimeline?.render();
      });
      const details=document.createElement("details");
      details.className="manual-advanced-times";
      const summary=document.createElement("summary");
      summary.textContent="ข้อมูลเวลาขั้นสูง · แบ่งช่วงด้วย | และระบุเวลาเป็นวินาที";
      const footer=document.createElement("small");
      footer.textContent="ข้อมูลตัวเลขใช้แก้เฉพาะกรณีจำเป็น · เวลาที่ไม่ทราบปล่อยว่างได้";
      details.append(summary,segments,starts,footer);
      card.append(top,words,times,cueStrip,details);
      list.append(card);
    });
    if(state.manualOnlyIssues&&!list.children.length){
      const hint=document.createElement("p");
      hint.className="manual-no-issues empty-small";
      hint.textContent="ไม่พบบรรทัดที่ต้องตรวจจากข้อมูลขณะนี้ · กดแสดงทุกบรรทัดได้";
      list.append(hint);
    }
    manualRefreshSelectors();manualControls();manualDrawKaraoke();
    manualRenderFindings();
  }
  async function manualOpenSong(id){
    if(state.manualDirty&&state.manualSelected?.song?.id!==id){
      if(!await confirmTask("ยังไม่ได้บันทึกการแก้ไข",
        "หากเปลี่ยนเพลงตอนนี้ การแก้ไขที่ยังไม่บันทึกจะหายไป · ต้องการเปลี่ยนเพลงหรือไม่?"))return;
    }
    await manualStop();
    state.manualSelected=null;state.manualPreview=null;state.manualTime=0;
    state.manualDuration=0;state.manualHeard=false;state.manualDirty=false;
    state.manualCueUndo.clear();
    manualTimeline?.reset();
    try{
      const details=await api("/api/manual/detail?song_id="+encodeURIComponent(id));
      state.manualSelected=details;
      state.manualDirty=false;
      state.manualLines=details.lines||[];
      state.manualFindings=details.findings||manualCheckDraft(state.manualLines);
      state.manualOnlyIssues=false;
      $("manual-only-issues").setAttribute("aria-pressed","false");
      $("manual-only-issues").textContent="แสดงเฉพาะบรรทัดที่ต้องตรวจ";
      $("manual-line-index").value="0";
      text("manual-song-title",String(details.song.code).padStart(8,"0")+
        " · "+details.song.title);
      text("manual-edit-status",details.song.timing_status||"ยังไม่มีเวลา");
      text("manual-feedback",details.draft_reason||"พร้อมตรวจและแก้ไข");
      try{
        const source=await api("/api/preview?song_id="+encodeURIComponent(id));
        state.manualPreview=source;
        state.manualDuration=source.duration||0;
        $("manual-video").hidden=source.mode!=="video";
        if(source.mode!=="midi"){
          const media=source.mode==="video"?$("manual-video"):$("manual-audio");
          media.src="/api/preview/media?song_id="+encodeURIComponent(id)+
            "&token="+encodeURIComponent(state.token);media.load();
        }
        text("manual-warning",source.warning);
      }catch(error){
        state.manualPreview=null;
        text("manual-warning","เปิดเสียงต้นฉบับไม่ได้: "+error.message+
          " · ยังแก้ไขข้อความและเวลาได้ แต่ไม่ยืนยันการปาดสี");
      }
      manualRenderLines();
      $("manual-edit-scroll").scrollTop=0;
      await loadManualQueue();
    }catch(error){toast(error.message,true);}
  }
  function manualCurrentMedia(){
    return state.manualPreview?.mode==="video"?$("manual-video"):$("manual-audio");
  }
  function manualDrawKaraoke(){
    const main=$("manual-current-line"),next=$("manual-next-line");
    main.replaceChildren();
    const lines=state.manualLines;
    if(!lines.length){
      main.textContent="ยังไม่มีเนื้อร้อง";next.textContent="ใช้เพิ่มบรรทัดหรือวางข้อความ";return;
    }
    const timed=lines.map((line,i)=>({line,i})).filter(o=>
      o.line.start!==null&&o.line.start!==""&&o.line.end!==null&&
      o.line.end!==""&&Number.isFinite(Number(o.line.start))&&
      Number.isFinite(Number(o.line.end))&&Number(o.line.end)>Number(o.line.start));
    let index=Number($("manual-line-index").value)||0;
    // While manually editing (paused), keep the selected line on screen;
    // during actual playback follow the audible line instead.
    if(timed.length&&state.manualPlaying){
      const playing=timed.find(o=>state.manualTime>=Number(o.line.start)&&
        state.manualTime<Number(o.line.end));
      const upcoming=timed.find(o=>Number(o.line.start)>state.manualTime);
      if(playing||upcoming)index=(playing||upcoming).i;
    }
    const line=lines[index]||lines[0];
    const segments=manualSegments(line),starts=manualStartTimes(line);
    const valid=segments.length>0&&segments.length===starts.length&&
      segments.join("")===line.text&&starts.every(x=>x!==""&&Number.isFinite(Number(x)));
    if(valid){
      segments.forEach((piece,i)=>{
        const token=document.createElement("span");token.textContent=piece;
        token.className="preview-glyph";
        const at=Number(starts[i]);
        const end=i+1<starts.length?Number(starts[i+1]):Number(line.end);
        const progress=Number.isFinite(end)&&end>at?
          Math.min(100,Math.max(0,(state.manualTime-at)/(end-at)*100)):
          (state.manualTime>=at?100:0);
        token.style.setProperty("--sweep",progress.toFixed(1)+"%");
        main.append(token);
      });
    }else main.textContent=line.text||"ยังไม่มีข้อความ";
    next.textContent=lines[index+1]?.text||"♪";
  }
  function manualTick(){
    if(!state.manualPlaying||!state.manualPreview)return;
    if(state.manualPreview.mode==="midi"){
      state.manualTime=Math.min(state.manualDuration,
        state.manualMidiSample+(performance.now()-state.manualMidiAt)/1000);
    }else state.manualTime=manualCurrentMedia().currentTime||0;
    manualControls();manualDrawKaraoke();manualTimeline?.tick();
  }
  async function manualPlay(){
    if(!state.manualPreview)return;
    try{
      if(state.manualPreview.mode==="midi"){
        const result=await api("/api/preview/midi/play",{
          song_id:state.manualSelected.song.id,seek:state.manualTime});
        if(result.status==="error")throw new Error(result.error||"MIDI Engine ไม่พร้อม");
        state.manualMidiSample=result.position||0;
        state.manualMidiAt=performance.now();
        if(!state.manualPoll)state.manualPoll=setInterval(async()=>{
          if(!state.manualPlaying)return;
          try{
            const current=await api("/api/preview/midi/status");
            if(current.song_id!==state.manualSelected?.song?.id)return;
            state.manualMidiSample=current.position||0;
            state.manualMidiAt=performance.now();
            if(current.status!=="playing"){
              state.manualPlaying=false;
              manualControls();manualDrawKaraoke();
            }
          }catch{/* disconnected engine */}
        },300);
      }else await manualCurrentMedia().play();
      state.manualPlaying=true;state.manualHeard=true;
      if(!state.manualClockTimer)
        state.manualClockTimer=setInterval(manualTick,75);
      manualControls();
    }catch(error){toast("เล่นต้นฉบับไม่ได้: "+error.message,true);}
  }
  async function manualPause(){
    if(!state.manualPreview)return;
    try{
      if(state.manualPreview.mode==="midi"){
        const paused=await api("/api/preview/midi/pause",{});
        state.manualTime=paused.position||state.manualTime;
      }else{
        const media=manualCurrentMedia();media.pause();
        state.manualTime=media.currentTime||state.manualTime;
      }
    }catch(error){toast(error.message,true);}
    state.manualPlaying=false;manualControls();manualDrawKaraoke();
  }
  async function manualSeek(value){
    const time=Math.max(0,Math.min(state.manualDuration,Number(value)||0));
    state.manualTime=time;
    if(state.manualPreview?.mode==="midi"&&state.manualPlaying)
      await manualPlay();
    else if(state.manualPreview?.mode!=="midi"&&state.manualPreview)
      manualCurrentMedia().currentTime=time;
    manualControls();manualDrawKaraoke();
  }
  function manualMark(kind){
    const line=manualSelectedLine();
    if(!line)return;
    if(kind==="start")line.start=Number(state.manualTime.toFixed(3));
    if(kind==="end")line.end=Number(state.manualTime.toFixed(3));
    if(kind==="cue"){
      const pos=Number($("manual-cue-index").value)||0;
      if(pos>=manualSegments(line).length)
        return toast("ต้องแบ่งคำสำหรับปาดสีของบรรทัดนี้ก่อน",true);
      const lineIndex=Number($("manual-line-index").value)||0;
      if(!Array.isArray(line.starts))line.starts=[];
      if(!state.manualCueUndo.has(lineIndex))
        state.manualCueUndo.set(lineIndex,line.starts.slice());
      while(line.starts.length<manualSegments(line).length)line.starts.push("");
      line.starts[pos]=Number(state.manualTime.toFixed(3));
      manualDraftState();manualRenderLines();
      $("manual-cue-index").value=String(Math.min(pos+1,manualSegments(line).length-1));
      manualSetSelectedCueVisual();
      return;
    }
    manualDraftState();manualRenderLines();
  }
  async function manualSave(){
    const details=state.manualSelected;
    if(!details)return;
    try{
      const result=await api("/api/manual/save",{
        song_id:details.song.id,version_id:details.song.version_id,
        lines:state.manualLines.map(line=>({
          text:line.text,start:line.start,end:line.end,
          segments:manualSegments(line),starts:manualStartTimes(line)
        }))
      });
      toast(result.message);
      text("manual-feedback",result.message);
      await manualOpenSong(details.song.id);
      state.manualHeard=false;manualControls();
      await refreshStatus();
    }catch(error){toast(error.message,true);}
  }
  async function manualSkip(){
    const details=state.manualSelected;
    if(!details)return;
    if(state.manualDirty&&!await confirmTask("ข้ามโดยไม่บันทึก",
        "มีการแก้เนื้อร้องที่ยังไม่บันทึก · หากข้าม เพลงนี้จะเก็บฉบับเดิมเท่านั้น"))return;
    try{
      await api("/api/manual/skip",{
        song_id:details.song.id,version_id:details.song.version_id
      });
      await manualStop();
      state.manualSelected=null;state.manualPreview=null;
      state.manualLines=[];state.manualDirty=false;state.manualFindings=[];manualRenderLines();
      text("manual-song-title","เลือกเพลงด้านซ้าย");
      text("manual-edit-status","ข้ามแล้ว");
      await loadManualQueue();toast("ข้ามรายการแล้ว ข้อมูลต้นฉบับยังอยู่");
    }catch(error){toast(error.message,true);}
  }
  async function manualApprove(){
    const details=state.manualSelected;
    if(!details||!state.manualHeard)return;
    try{
      await api("/api/manual/approve",{
        song_id:details.song.id,version_id:details.song.version_id
      });
      toast("ยืนยันเวอร์ชันนี้พร้อมสร้าง .X แล้ว");
      const id=details.song.id;
      await manualOpenSong(id);
      await loadManualQueue();
    }catch(error){toast(error.message,true);}
  }

  function bind(){
    $("source-browse").addEventListener("click",()=>void openPicker("folder","source-folder"));
    // Windows Explorer's "Copy as path" wraps paths in quotes; accept those too.
    const sourceField=$("source-folder");
    const normalizeSource=()=>{
      const raw=sourceField.value.trim();
      const clean=raw.replace(/^[\x22\x27]+|[\x22\x27]+$/g,"").trim();
      if(clean!==raw)sourceField.value=clean;
      if(clean)text("folder-picker-status","พาธที่ระบุ: "+clean+" · กดเริ่มนำเข้าเพื่อตรวจไฟล์");
      return clean;
    };
    sourceField.addEventListener("change",normalizeSource);
    sourceField.addEventListener("paste",()=>setTimeout(normalizeSource,0));
    sourceField.addEventListener("keydown",event=>{
      if(event.key==="Enter"){
        event.preventDefault();
        const folder=normalizeSource();
        if(!folder)return toast("กรุณาระบุโฟลเดอร์ต้นทาง",true);
        if(!state.ready)return toast("PC Engine ไม่เชื่อมต่อ · เปิดผ่านไฟล์ EXE บน Windows",true);
        if(state.activeJob)return toast("มีงานกำลังประมวลผลอยู่",true);
        void startJob("import",{folder});
      }
    });
    $("source-open").addEventListener("click",()=>void openLocalFolder("source"));
    $("settings-open").addEventListener("click",()=>{
      syncSettingsUpdate();
      $("settings-dialog").showModal();
      void diagnostic("ui.settings.open");
    });
    $("settings-update-check").addEventListener("click",()=>void checkProUpdate());
    $("settings-update-install").addEventListener("click",()=>void beginProUpdate());
    $("settings-update-direct").addEventListener("click",openLatestExe);
    $("settings-close").addEventListener("click",()=>$("settings-dialog").close());
    $("settings-dialog").addEventListener("cancel",event=>{
      event.preventDefault();$("settings-dialog").close();
    });
    $("diagnostic-open-log").addEventListener("click",async()=>{
      try{
        await api("/api/open-log",{});
        toast("เปิด Log วิเคราะห์แล้ว");
      }catch(error){toast("เปิด Log ไม่สำเร็จ: "+error.message,true);}
    });
    $("workspace-open").addEventListener("click",()=>void openLocalFolder("workspace"));
    $("lrc-browse").addEventListener("click",()=>void openPicker("lrc","media-lrc"));
    for(const button of document.querySelectorAll("[data-view]"))
      button.addEventListener("click",async()=>{
        if(state.view==="manual"&&state.manualDirty&&button.dataset.view!=="manual"){
          if(!await confirmTask("มีการแก้ไขที่ยังไม่บันทึก",
            "ออกจากเมนู 05 โดยไม่บันทึกหรือไม่?"))return;
          state.manualDirty=false;
        }
        view(button.dataset.view);
      });

    for(const [id,key] of [
      ["manual-toggle-menu","menu"],["manual-toggle-queue","queue"],
      ["manual-toggle-stage","stage"],["manual-focus","focus"]
    ]){
      $(id).addEventListener("click",()=>{
        if(key==="menu"&&state.manualLayout.focus){
          state.manualLayout.focus=false;state.manualLayout.menu=false;
        }else if(key==="queue"&&state.manualLayout.focus){
          state.manualLayout.focus=false;state.manualLayout.queue=false;
        }else state.manualLayout[key]=!state.manualLayout[key];
        manualApplyLayout();
      });
    }
    $("manual-diagnostic-filter").addEventListener("change",manualRenderFindings);
    $("manual-only-issues").addEventListener("click",()=>{
      state.manualOnlyIssues=!state.manualOnlyIssues;
      $("manual-only-issues").setAttribute("aria-pressed",String(state.manualOnlyIssues));
      $("manual-only-issues").textContent=state.manualOnlyIssues?
        "แสดงทุกบรรทัด":"แสดงเฉพาะบรรทัดที่ต้องตรวจ";
      manualRenderLines();
    });
    document.addEventListener("keydown",event=>{
      if(state.view!=="manual")return;
      if(event.key==="Escape"&&state.manualLayout.focus){
        state.manualLayout.focus=false;manualApplyLayout();return;
      }
      if(event.code==="Space"&&!event.repeat&&!event.altKey&&!event.ctrlKey&&
        !event.metaKey&&state.manualPlaying&&state.manualSelected&&![
          "INPUT","TEXTAREA","SELECT","BUTTON"].includes(document.activeElement?.tagName)){
        event.preventDefault();manualMark("cue");return;
      }
      if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="s"&&
          !$("manual-save").disabled){
        event.preventDefault();void manualSave();
      }
    });

    $("manual-find").addEventListener("click",()=>{
      state.manualOffset=0;void loadManualQueue();
    });
    $("manual-search").addEventListener("keydown",event=>{
      if(event.key==="Enter"){state.manualOffset=0;void loadManualQueue();}
    });
    $("manual-filter").addEventListener("change",()=>{
      state.manualOffset=0;void loadManualQueue();
    });
    $("manual-prev").addEventListener("click",()=>{
      state.manualOffset=Math.max(0,state.manualOffset-visibleRows());
      void loadManualQueue();
    });
    $("manual-next").addEventListener("click",()=>{
      state.manualOffset+=visibleRows();void loadManualQueue();
    });
    $("manual-add-line").addEventListener("click",()=>{
      state.manualLines.push({text:"",start:null,end:null,segments:[],starts:[],timing:"untimed"});
      manualDraftState();manualRenderLines();
      $("manual-line-index").value=String(state.manualLines.length-1);
      manualRefreshCues();
    });
    $("manual-paste-add").addEventListener("click",()=>{
      const items=$("manual-paste").value.split(/\r?\n/).filter(s=>s.trim());
      if(!items.length)return toast("ยังไม่ได้วางเนื้อร้อง",true);
      if(state.manualLines.length+items.length>400)
        return toast("จำนวนบรรทัดเกิน 400",true);
      for(const s of items)
        state.manualLines.push({text:s,start:null,end:null,segments:[],starts:[],timing:"untimed"});
      $("manual-paste").value="";manualDraftState();manualRenderLines();
    });
    $("manual-line-index").addEventListener("change",()=>{
      manualRefreshCues();manualDrawKaraoke();manualTimeline?.render();
    });
    $("manual-cue-index").addEventListener("change",()=>{
      manualSetSelectedCueVisual();manualDrawKaraoke();manualTimeline?.selection();
    });
    $("manual-play").addEventListener("click",()=>void manualPlay());
    $("manual-pause").addEventListener("click",()=>void manualPause());
    $("manual-seek").addEventListener("change",e=>void manualSeek(e.target.value));
    $("manual-mark-start").addEventListener("click",()=>manualMark("start"));
    $("manual-mark-cue").addEventListener("click",()=>manualMark("cue"));
    $("manual-mark-end").addEventListener("click",()=>manualMark("end"));
    $("manual-save").addEventListener("click",()=>void manualSave());
    $("manual-skip").addEventListener("click",()=>void manualSkip());
    $("manual-approve").addEventListener("click",()=>void manualApprove());
    for(const mode of ["audio","video"]){
      const player=$("manual-"+mode);
      player.addEventListener("loadedmetadata",()=>{
        if(state.manualPreview?.mode!==mode)return;
        state.manualDuration=Number.isFinite(player.duration)?player.duration:0;
        manualControls();manualTimeline?.render();
      });
      player.addEventListener("ended",()=>{
        state.manualPlaying=false;state.manualTime=state.manualDuration;
        manualControls();manualDrawKaraoke();
      });
      player.addEventListener("error",()=>{
        if(state.manualPreview?.mode!==mode)return;
        state.manualPlaying=false;
        text("manual-warning","ตัวเล่นไม่รองรับรูปแบบต้นฉบับ · ไม่ยืนยันการปาดสี");
        manualControls();
      });
    }

    $("preview-find").addEventListener("click",()=>{
      state.previewOffset=0;void loadPreviewSongs();
    });
    $("preview-search").addEventListener("keydown",event=>{
      if(event.key==="Enter"){state.previewOffset=0;void loadPreviewSongs();}
    });
    $("preview-prev").addEventListener("click",()=>{
      state.previewOffset=Math.max(0,state.previewOffset-visibleRows());
      void loadPreviewSongs();
    });
    $("preview-next").addEventListener("click",()=>{
      state.previewOffset+=visibleRows();void loadPreviewSongs();
    });
    $("preview-play").addEventListener("click",()=>void playPreview());
    $("preview-pause").addEventListener("click",()=>void pausePreview());
    $("preview-seek").addEventListener("pointerdown",()=>{state.previewSeeking=true;});
    $("preview-seek").addEventListener("input",event=>{
      if(state.previewSeeking)
        text("preview-clock",previewFormatSeconds(Number(event.target.value))+
          " / "+previewFormatSeconds(state.previewDuration));
    });
    $("preview-seek").addEventListener("change",event=>{
      state.previewSeeking=false;void seekPreview(event.target.value);
    });
    $("preview-seek").addEventListener("pointerup",()=>{state.previewSeeking=false;});
    for(const type of ["audio","video"]){
      const media=$("preview-"+type);
      media.addEventListener("loadedmetadata",()=>{
        if(state.previewSelected?.mode!==type)return;
        state.previewDuration=Number.isFinite(media.duration)?media.duration:0;
        updatePreviewControls();
      });
      media.addEventListener("ended",()=>{
        if(state.previewSelected?.mode!==type)return;
        state.previewPlaying=false;state.previewTime=state.previewDuration;
        updatePreviewControls();updatePreviewLyrics();
      });
      media.addEventListener("error",()=>{
        if(state.previewSelected?.mode!==type)return;
        state.previewPlaying=false;
        text("preview-warning","ตัวเล่นนี้ไม่รองรับรูปแบบ/Codec ของไฟล์ต้นฉบับ"+
          " · ไม่สรุปผลการปาดสี ต้องใช้ตัวเล่นที่รองรับจริง");
        updatePreviewControls();
      });
    }
    $("preview-pass").addEventListener("click",()=>void recordPreviewOutcome("passed"));
    $("preview-fail").addEventListener("click",()=>void recordPreviewOutcome("confirmed"));
    $("preview-needs").addEventListener("click",()=>void recordPreviewOutcome("needs-review"));
    $("preview-to-build").addEventListener("click",previewToBuild);
    $("issues-load").addEventListener("click",()=>void loadImportIssues());
    $("db-health-check").addEventListener("click",()=>void checkDatabaseHealth());
    $("db-detail-audit").addEventListener("click",()=>void startJob("db-audit",{}));
    $("db-history-clean").addEventListener("click",async()=>{
      if(state.activeJob)return toast("กรุณารองานปัจจุบันให้เสร็จก่อน",true);
      if(!await confirmTask("ล้างประวัติ SQLite ที่ไม่จำเป็น",
        "เก็บปัญหาใน 4 งานล่าสุดและผลตรวจปาดสีละเอียด 2 รอบล่าสุด\n"+
        "ล้าง Checkpoint งานเสร็จ ประวัติเก่า แคชไม่มีเจ้าของ และดัชนีที่ไม่ใช้\n"+
        "ไม่ลบเพลง ต้นฉบับ เนื้อร้อง เวอร์ชันที่แก้ไข หรือสถานะงานค้าง\n"+
        "การล้างข้อมูลยังไม่ลดขนาดไฟล์จนกว่าจะสั่งคืนพื้นที่"))return;
      void startJob("db-clean",{});
    });
    $("db-compact").addEventListener("click",async()=>{
      if(state.activeJob)return toast("กรุณารองานปัจจุบันให้เสร็จก่อน",true);
      if(!await confirmTask("คืนพื้นที่ไฟล์ SQLite",
        "ระบบจะใช้ VACUUM ย่อ SQLite โดยต้องมีพื้นที่ว่างอย่างน้อย 2 เท่าของขนาดฐาน\n"+
        "ควรสำรองฐานข้อมูลขณะปิดแอปก่อนดำเนินการ\n"+
        "ห้ามปิดเครื่องระหว่างดำเนินการ และไม่แก้ไฟล์ต้นฉบับ"))return;
      void startJob("db-compact",{});
    });
    $("issues-close").addEventListener("click",()=>$("issues-dialog").close());
    $("issues-prev").addEventListener("click",()=>{
      state.issueOffset=Math.max(0,state.issueOffset-visibleRows());renderIssuePage();
    });
    $("issues-next").addEventListener("click",()=>{
      state.issueOffset+=visibleRows();renderIssuePage();
    });
    $("risk-scan").addEventListener("click",()=>void startJob("swipe-audit",{}));
    for(const button of document.querySelectorAll("[data-risk-filter]"))
      button.addEventListener("click",()=>riskFilterChanged(button.dataset.riskFilter));
    $("risk-prev").addEventListener("click",()=>{
      state.riskOffset=Math.max(0,state.riskOffset-state.riskLimit);
      void loadRisks();
    });
    $("risk-next").addEventListener("click",()=>{
      state.riskOffset+=state.riskLimit;void loadRisks();
    });
    $("risk-close").addEventListener("click",()=>$("risk-dialog").close());
    $("risk-evidence-prev").addEventListener("click",()=>{
      state.riskEvidenceIndex=Math.max(0,state.riskEvidenceIndex-1);renderRiskEvidence();
    });
    $("risk-evidence-next").addEventListener("click",()=>{
      state.riskEvidenceIndex+=1;renderRiskEvidence();
    });
    $("risk-confirmed").addEventListener("click",()=>void saveRiskReview("confirmed"));
    $("risk-passed").addEventListener("click",()=>void saveRiskReview("passed"));
    $("risk-needs-review").addEventListener("click",()=>void saveRiskReview("needs-review"));
    $("risk-open-source").addEventListener("click",()=>void openRiskSource());
    $("risk-open-preview").addEventListener("click",()=>{
      const item=state.riskSelected;
      if(!item)return;
      $("risk-dialog").close();
      view("preview");
      void selectPreviewSong({id:item.song_id});
    });
    $("risk-open-lyrics").addEventListener("click",()=>{
      const song=state.riskSelected;
      if(!song)return;
      $("risk-dialog").close();
      void openLyrics({id:song.song_id,title:song.title});
    });
    $("refresh-summary").addEventListener("click",()=>void refreshSummary());
    $("pro-update-check").addEventListener("click",()=>void checkProUpdate());
    $("pro-update-direct").addEventListener("click",openLatestExe);
    $("pro-update-install").addEventListener("click",()=>void beginProUpdate());
    $("pro-update-quick").addEventListener("click",()=>void beginProUpdate());
    $("pro-update-notice-install").addEventListener("click",()=>void beginProUpdate());
    $("pro-update-notice-dismiss").addEventListener("click",()=>{
      state.updateNoticeDismissed=true;
      $("pro-update-notice").hidden=true;
    });
    $("import-start").addEventListener("click",()=>{
      $("source-folder").dispatchEvent(new Event("change"));
      const folder=$("source-folder").value.trim();
      if(!folder)return toast("กรุณาระบุโฟลเดอร์ต้นทาง",true);
      if(!state.ready)return toast("PC Engine ไม่เชื่อมต่อ · เปิดผ่านไฟล์ EXE บน Windows",true);
      if(state.activeJob)return toast("มีงานกำลังประมวลผลอยู่",true);
      void diagnostic("ui.import.click",{folder});
      void startJob("import",{folder});
    });
    $("recover-lyrics").addEventListener("click",async()=>{
      if(!await confirmTask("ตรวจซ่อมเนื้อร้องที่ลงทะเบียนไว้",
        "ตรวจเฉพาะเพลงที่ยังขาดเวลาปาดสีใน SQLite จากพาธต้นฉบับเดิม\n"+
        "ไม่คำนวณ SHA-256 เพลงใหม่ ไม่ลบหรือคัดลอกไฟล์ต้นฉบับ\n"+
        "รักษาเนื้อร้องสมบูรณ์และเวอร์ชันที่คุณแก้ไขเองไว้"))return;
      void startJob("recover",{});
    });
    $("lyrics-find").addEventListener("click",()=>void searchGroups());
    $("lyrics-search").addEventListener("keydown",event=>{
      if(event.key==="Enter")void searchGroups();
    });
    $("lyrics-search").addEventListener("input",()=>{
      ++state.lyricSearchRun;
      state.groupSearchRunning=false;
      state.groups=[];state.groupHasNext=false;state.selectedGroups.clear();
      state.selectedGroupInfo.clear();state.lyricContextHits=0;
      state.lyricContextFailed=false;
      $("lyrics-search-context").hidden=true;
      $("lyrics-find").disabled=!state.ready;
      text("lyrics-search-feedback","คำค้นเปลี่ยนแล้ว · กดค้นหาเพื่ออ่านผลใหม่จาก SQLite");
      renderGroups();
    });
    $("lyrics-replacement").addEventListener("input",updateSelectedGroups);
    $("groups-all").addEventListener("click",()=>{
      for(const group of state.groups){
        state.selectedGroups.add(group.group_key);
        state.selectedGroupInfo.set(group.group_key,group);
      }
      renderGroups();
    });
    $("groups-clear").addEventListener("click",()=>{
      state.selectedGroups.clear();state.selectedGroupInfo.clear();renderGroups();
    });
    $("lyrics-apply").addEventListener("click",()=>void applyLyrics());
    $("lyrics-cancel").addEventListener("click",async()=>{
      if(!state.lyricsEditJob||!state.lyricsEditActive)return;
      if(!await confirmTask("ยกเลิกการแทนที่ทั้งชุด",
        "ยกเลิกการแทนที่ขณะนี้และคืนข้อมูลใน SQLite ทั้งชุดหรือไม่?"))return;
      try{
        await api("/api/job/cancel",{job:state.lyricsEditJob});
        $("lyrics-cancel").disabled=true;
        text("edit-feedback","กำลังยกเลิกและคืนค่าทั้งชุด...");
      }catch(error){toast(error.message,true);}
    });
    $("lyrics-undo").addEventListener("click",()=>void undoLyrics());
    $("media-attach").addEventListener("click",()=>void attachLrc());
    $("build-all").addEventListener("click",async()=>{
      try{
        const result=await api("/api/build/eligible");
        state.allReadySelected=true;state.readyTotal=result.ready_total||0;
        state.excludedSongs.clear();state.selectedSongs.clear();
        renderSongs();toast("เลือกเพลงที่พร้อมสร้างจากทุกหน้าแล้ว");
      }catch(error){toast(error.message,true);}
    });
    $("build-page-all").addEventListener("click",()=>{
      for(const song of state.songs)if(song.manual_status==="ready"){
        if(state.allReadySelected)state.excludedSongs.delete(song.id);
        else state.selectedSongs.add(song.id);
      }
      renderSongs();
    });
    $("build-clear").addEventListener("click",()=>{
      state.allReadySelected=false;state.readyTotal=0;
      state.excludedSongs.clear();state.selectedSongs.clear();renderSongs();
    });
    $("build-page-clear").addEventListener("click",()=>{
      for(const song of state.songs){
        if(state.allReadySelected&&song.manual_status==="ready")
          state.excludedSongs.add(song.id);
        else state.selectedSongs.delete(song.id);
      }
      renderSongs();
    });
    $("build-start").addEventListener("click",()=>{
      const count=state.allReadySelected?
        state.readyTotal-state.excludedSongs.size:state.selectedSongs.size;
      if(count<=0)return;
      void startJob("build",state.allReadySelected?
        {all_ready:true,excluded:[...state.excludedSongs]}:
        {song_ids:[...state.selectedSongs]});
    });
    $("library-prev").addEventListener("click",()=>{
      state.songOffset=Math.max(0,state.songOffset-visibleRows());
      void refreshSongs();
    });
    $("library-next").addEventListener("click",()=>{
      state.songOffset+=visibleRows();void refreshSongs();
    });
    $("build-prev").addEventListener("click",()=>{
      state.songOffset=Math.max(0,state.songOffset-visibleRows());
      void refreshSongs();
    });
    $("build-next").addEventListener("click",()=>{
      state.songOffset+=visibleRows();void refreshSongs();
    });
    $("groups-prev").addEventListener("click",()=>{
      state.groupOffset=Math.max(0,state.groupOffset-visibleRows());
      void searchGroups(false);
    });
    $("groups-next").addEventListener("click",()=>{
      state.groupOffset+=visibleRows();void searchGroups(false);
    });
    $("library-find").addEventListener("click",()=>{
      state.songOffset=0;void refreshSongs();
    });
    $("library-search").addEventListener("keydown",event=>{
      if(event.key==="Enter"){
        state.songOffset=0;void refreshSongs();
      }
    });
    $("cancel-job").addEventListener("click",async()=>{
      if(!state.activeJob)return;
      if(!await confirmTask("หยุดงาน","หยุดหลังประมวลผลไฟล์ปัจจุบันเสร็จ?"))return;
      try{await api("/api/job/cancel",{job:state.activeJob});toast("ส่งคำสั่งหยุดแล้ว");}
      catch(error){toast(error.message,true);}
    });
    $("lyrics-close").addEventListener("click",()=>$("lyrics-dialog").close());
    $("lyrics-prev").addEventListener("click",()=>{
      state.lyricOffset=Math.max(0,state.lyricOffset-visibleRows());renderLyricPage();
    });
    $("lyrics-next").addEventListener("click",()=>{
      state.lyricOffset+=visibleRows();renderLyricPage();
    });
    $("lyrics-show-draft").addEventListener("click",()=>{
      state.lyricShowDraft=!state.lyricShowDraft;
      state.lyricOffset=0;renderLyricPage();
    });
  }
  function startJobPolling(){
    if(globalThis.__XSTAGE_JOB_POLL_TIMER__)clearTimeout(globalThis.__XSTAGE_JOB_POLL_TIMER__);
    const tick=async()=>{
      await refreshJobs();
      globalThis.__XSTAGE_JOB_POLL_TIMER__=setTimeout(tick,1200);
    };
    globalThis.__XSTAGE_FORCE_JOB_REFRESH__=()=>void refreshJobs();
    globalThis.__XSTAGE_JOB_POLL_TIMER__=setTimeout(tick,800);
  }
  async function init(){
    console.info("[XSTAGE] init.begin");
    // Core navigation and buttons must be usable even if an optional module
    // such as the cue timeline fails to initialize.
    bind();
    view(location.hash.slice(1) in labels?location.hash.slice(1):"import");
    globalThis.__XSTAGE_CORE_BOUND__=true;
    console.info("[XSTAGE] core.bind.ready");

    try{
      if(typeof globalThis.XStageCueTimelineUI!=="function")
        throw new Error("XStageCueTimelineUI is unavailable");
      manualTimeline=new globalThis.XStageCueTimelineUI({
        el:$,text,selected:()=>state.manualSelected,
        line:()=>manualSelectedLine(),
        lineIndex:()=>Number($("manual-line-index").value)||0,
        cueIndex:()=>Number($("manual-cue-index").value)||0,
        segments:manualSegments,starts:manualStartTimes,
        time:()=>state.manualTime,duration:()=>state.manualDuration,
        playing:()=>state.manualPlaying,canPlay:()=>Boolean(state.manualPreview),
        selectCue:index=>{
          $("manual-cue-index").value=String(index);
          manualSetSelectedCueVisual();
        },
        seek:time=>void manualSeek(time),
        previewTime:time=>{state.manualTime=time;},
        preview:manualDrawKaraoke,
        capture:()=>manualMark("cue"),
        changed:before=>{
          const index=Number($("manual-line-index").value)||0;
          if(!state.manualCueUndo.has(index))state.manualCueUndo.set(index,before);
          manualDraftState();manualRenderLines();
        }
      });
      console.info("[XSTAGE] timeline.ready");
    }catch(error){
      manualTimeline=null;
      console.error("[XSTAGE] timeline.init.failed",
        error?.stack||error?.message||String(error));
    }
    try{
      const session=await api("/api/session");
      state.token=session.token;
      setReady(true);
      text("workspace-chip","คลัง: "+session.workspace.split(/[\\/]/).pop());
      void diagnostic("ui.session.ready",{version:session.version});
      // Update check is independent from SQLite summary work. Start it early
      // so a new release is visible immediately after the desktop connects.
      void checkProUpdate(true);
      if(state.view==="preview")await loadPreviewSongs();
      if(state.view==="manual")await loadManualQueue();
      if(state.view==="risks")await loadRisks();
      await refreshStatus();
      await refreshJobs();
      try{
        const resume=await api("/api/import/resume");
        if(resume.resume){
          $("source-folder").value=resume.resume.source_root;
          text("import-resume-status",resume.resume.status==="interrupted"?
            "พบงานนำเข้าที่หยุดกะทันหัน · เปิดกลับมาแล้วระบบจะทำต่อจาก Checkpoint โดยอัตโนมัติ":
            "มีรายการหยุดไว้ก่อนหน้า · กดนำเข้าโฟลเดอร์เดิมเพื่อทำต่อ");
        }
      }catch{/* status optional if older engine */}
      startJobPolling();
    }catch(error){
      console.error("[XSTAGE] session.init.failed",
        error?.stack||error?.message||String(error));
      setReady(false);
      text("activity-title","ยังไม่เชื่อมต่อ PC Engine");
      text("activity-subtitle","หากเปิดจากเว็บสาธารณะ ให้เปิดไฟล์ EXE บน Windows · ระบบจะลองเชื่อมต่อใหม่อัตโนมัติ");
      // A transient localhost startup failure must not leave every command disabled forever.
      const reconnect=setInterval(async()=>{
        if(state.ready){clearInterval(reconnect);return;}
        try{
          const session=await api("/api/session");
          if(!session?.token)return;
          state.token=session.token;
          setReady(true);
          text("workspace-chip","คลัง: "+session.workspace.split(/[\\/]/).pop());
          void checkProUpdate(true);
          await refreshStatus();
          await refreshJobs();
          startJobPolling();
          clearInterval(reconnect);
        }catch{/* PC engine not yet available */}
      },3000);
    }
  }
  void init();
})();
