"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const state = {token:null,ready:false,view:"import",groups:[],selectedGroups:new Set(),
                 songs:[],selectedSongs:new Set(),latestEdit:null,activeJob:null,
                 jobSignature:"",toastTimer:null,riskFilter:"structural",
                 riskOffset:0,riskLimit:5,riskTotal:0,riskRows:[],
                 riskHistory:[],riskSelected:null,riskEvidenceIndex:0,
                 songOffset:0,songHasNext:false,groupOffset:0,groupHasNext:false,
                 selectedGroupInfo:new Map(),issueRows:[],issueOffset:0};
  const labels={import:"นำเข้าเพลง",lyrics:"แก้ไขเนื้อร้อง",media:"เสียงและวิดีโอ",
                build:"สร้างไฟล์ X-Stage",library:"คลังเพลง",risks:"ประวัติเสี่ยงปาดเนื้อ"};
  const number = v => Number(v||0).toLocaleString("en-US");
  function text(id,value){const node=$(id);if(node)node.textContent=value;}
  function toast(message,error=false){
    const node=$("toast");
    node.textContent=String(message||"");
    node.classList.toggle("error",error);
    node.classList.add("show");
    clearTimeout(state.toastTimer);
    state.toastTimer=setTimeout(()=>node.classList.remove("show"),4600);
  }
  async function api(path,payload){
    const options={cache:"no-store",headers:{}};
    if(payload!==undefined){
      options.method="POST";
      options.headers={"Content-Type":"application/json","X-XStage-Token":state.token};
      options.body=JSON.stringify(payload);
    }
    const response=await fetch(path,options);
    let result;
    try{result=await response.json();}catch{throw new Error("บริการภายในเครื่องไม่ตอบกลับ");}
    if(!response.ok)throw new Error(result.error||"คำสั่งไม่สำเร็จ");
    return result;
  }
  function view(name){
    if(!labels[name])return;
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
    if(name==="risks")void loadRisks();
    if(name==="lyrics"&&$("lyrics-search").value.trim())void searchGroups();
    document.title=labels[name]+" · X-Stage Song Studio Plus";
    history.replaceState(null,"","#"+name);
  }
  function setReady(enabled){
    state.ready=enabled;
    text("engine-name",enabled?"Local Engine พร้อมใช้":"ยังไม่เชื่อมต่อ PC Engine");
    text("engine-subtitle",enabled?"SQLite · 127.0.0.1":"เปิดผ่าน Song Studio Plus บน PC");
    const dot=document.querySelector(".live-dot");
    if(dot)dot.style.background=enabled?"#5edfad":"#e9a465";
    for(const id of ["import-start","recover-lyrics","risk-scan","lyrics-find","media-attach","build-start","source-browse","lrc-browse"]){
      $(id).disabled=!enabled;
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
      const ready=Boolean(song.version_id&&song.timing_status!=="incomplete");
      const available=Boolean(song.version_id||song.draft_reason);
      const timingLabel=ready? song.timing_status:
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
      check.checked=state.selectedSongs.has(song.id);
      check.disabled=!ready;
      check.addEventListener("change",()=>{
        if(check.checked)state.selectedSongs.add(song.id);
        else state.selectedSongs.delete(song.id);
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
    text("build-count",number(state.selectedSongs.size)+" เพลง");
    $("build-start").disabled=!state.ready||state.selectedSongs.size===0||Boolean(state.activeJob);
  }
  async function openLyrics(song){
    try{
      const data=await api("/api/lyrics?song_id="+encodeURIComponent(song.id));
      text("lyrics-modal-title",song.title+" · "+data.version.timing_status);
      const list=$("lyrics-modal-lines");list.replaceChildren();
      for(const line of data.lines){
        const element=document.createElement("div");element.className="lyric-line";
        const timing=document.createElement("code");
        timing.textContent=line.start===null||line.end===null?
          "รอ Timing":Number(line.start).toFixed(2)+" – "+Number(line.end).toFixed(2)+"s";
        const details=document.createElement("div");
        const words=document.createElement("p");words.textContent=line.text;
        const note=document.createElement("small");
        note.textContent="บรรทัด "+(line.position+1)+" · "+line.timing+
                         " · จุดปาดสี "+line.cues.length+" จุด";
        details.append(words,note);element.append(timing,details);list.append(element);
      }
      if(data.draft&&data.version.timing_status==="incomplete"){
        const section=document.createElement("div");section.className="lyric-draft-summary";
        const title=document.createElement("strong");
        title.textContent="เนื้อร้องทั้งหมดจาก LYR · บางช่วงยังไม่มีเวลาปาดสี";
        const raw=document.createElement("pre");raw.textContent=data.draft.text;
        section.append(title,raw);list.append(section);
      }
      $("lyrics-dialog").showModal();
    }catch(error){toast(error.message,true);}
  }
  async function searchGroups(reset=true){
    if(!state.ready)return;
    const q=$("lyrics-search").value.trim();
    if(reset){
      state.groupOffset=0;
      state.selectedGroups.clear();
      state.selectedGroupInfo.clear();
    }
    state.groups=[];
    if(!q){text("groups-count","0 กลุ่ม");renderGroups();return;}
    try{
      const limit=visibleRows();
      const data=await api("/api/groups?q="+encodeURIComponent(q)+
        "&limit="+(limit+1)+"&offset="+state.groupOffset);
      state.groupHasNext=(data.rows||[]).length>limit;
      state.groups=(data.rows||[]).slice(0,limit);
      renderGroups();
    }catch(error){toast(error.message,true);}
  }
  function renderGroups(){
    text("groups-count",number(state.groups.length)+" กลุ่มในหน้านี้");
    text("groups-page-info","หน้า "+number(Math.floor(state.groupOffset/visibleRows())+1));
    $("groups-prev").disabled=state.groupOffset<=0;
    $("groups-next").disabled=!state.groupHasNext;
    const panel=$("group-list");panel.replaceChildren();
    if(!state.groups.length){
      const empty=document.createElement("p");empty.className="empty-small";
      empty.textContent=$("lyrics-search").value.trim()?
        "ไม่พบกลุ่มข้อความที่ตรงคำค้น":"ค้นคำเพื่อแสดงกลุ่มบรรทัด";
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
    $("lyrics-apply").disabled=!state.ready||!chosen.length||!$("lyrics-replacement").value.trim();
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
    const q=$("lyrics-search").value.trim();
    const replacement=$("lyrics-replacement").value.trim();
    const keys=Array.from(state.selectedGroups);
    if(!keys.length||!q||!replacement){toast("กรุณาค้นคำ เลือกกลุ่ม และใส่ข้อความใหม่",true);return;}
    try{
      const plan=await api("/api/edit/plan",{q,keys});
      if(!plan.lines){toast("ไม่มีรายการที่ต้องเปลี่ยน");return;}
      const approved=await confirmTask("ยืนยันแทนที่เนื้อร้อง",
        "กลุ่มที่เลือก: "+number(plan.groups)+"\n"+
        "บรรทัดที่จะเปลี่ยน: "+number(plan.lines)+"\n"+
        "เพลงที่เกี่ยวข้อง: "+number(plan.songs)+"\n\n"+
        "ข้อความใหม่ทั้งบรรทัด:\n"+replacement+"\n\n"+
        "รักษาเวลาเริ่ม–จบแยกตามเพลง ระบบจะทำเครื่องหมาย Estimated เมื่อปรับจังหวะปาดสี");
      if(!approved)return;
      const output=await api("/api/edit/apply",{q,keys,replacement,expected_lines:plan.lines});
      if(output.batch){state.latestEdit=output.batch;$("lyrics-undo").disabled=false;}
      text("edit-feedback","แก้ไขแล้ว "+number(output.changed_lines)+" บรรทัดใน "+
        number(output.changed_songs)+" เพลง · สามารถ Undo การแก้ไขชุดล่าสุด");
      state.selectedGroups.clear();
      await searchGroups();await refreshStatus();
      toast("บันทึกเนื้อร้องใหม่ลง SQLite สำเร็จ");
    }catch(error){toast(error.message,true);}
  }
  async function undoLyrics(){
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
  async function startJob(kind,payload){
    try{
      const endpoint=kind==="import"?"/api/import":kind==="recover"?"/api/recover-lyrics":kind==="swipe-audit"?"/api/swipe/scan":"/api/build";
      const result=await api(endpoint,payload);
      state.activeJob=result.job;
      toast("เริ่มงานแล้ว ระบบประมวลผลต่อเนื่อง");
      await refreshJobs();
    }catch(error){toast(error.message,true);}
  }
  async function refreshJobs(){
    if(!state.ready)return;
    try{
      const result=await api("/api/jobs");
      const jobs=result.jobs||[];
      const job=jobs.find(x=>x.status==="running")||jobs[0];
      state.activeJob=jobs.find(x=>x.status==="running")?.id||null;
      $("cancel-job").hidden=!state.activeJob;
      $("build-start").disabled=!state.ready||!state.selectedSongs.size||Boolean(state.activeJob);
      $("import-start").disabled=!state.ready||Boolean(state.activeJob);
      $("recover-lyrics").disabled=!state.ready||Boolean(state.activeJob);
      $("risk-scan").disabled=!state.ready||Boolean(state.activeJob);
      if(!job)return;
      text("activity-status",job.status==="running"?"กำลังทำงาน":
          job.status==="completed"?"เสร็จเรียบร้อย":job.status==="failed"?"ข้อผิดพลาด":"หยุดแล้ว");
      text("activity-title",job.kind==="import"?"นำเข้าและตรวจ SHA-256":
          job.kind==="recover"?"ตรวจซ่อมเนื้อร้องจาก SQLite":
           job.kind==="swipe-audit"?"ตรวจหลักฐานปาดเนื้อจาก SQLite":"สร้างไฟล์ X-Stage Plus");
      text("activity-subtitle",job.message||"");
      const p=job.progress||{};
      text("progress-detail",job.kind==="import"?
          "ไฟล์ใหม่ "+number(p.files_new)+" · ไฟล์ซ้ำ "+number(p.media_duplicates)+
          " · เนื้อร้องพร้อมเวลา "+number(p.lyrics_new)+
          " · CUR ไม่ครบ "+number(p.partial_lyrics)+
          " · เก็บเนื้อร้องรอเวลา "+number(p.draft_lyrics)+
          " · ผิดพลาดจริง "+number(p.failures)+
          " · Hash เดิม "+number(p.hash_cache_hits)+" · "+number(p.files_per_second)+" ไฟล์/วินาที":
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
      text("progress-count",number(p.processed||p.files_seen||p.done||0)+
        (job.kind==="recover"||job.kind==="swipe-audit"?" / "+number(p.total):"")+" รายการ");
      const progressBar=$("progress-fill");
      progressBar.classList.toggle("indeterminate",job.status==="running");
      progressBar.style.width=job.status==="completed"?"100%":job.status==="running"?"32%":"0%";
      const signature=job.id+":"+job.status;
      if(state.jobSignature!==signature){
        state.jobSignature=signature;
        if(job.status==="completed"||job.status==="failed"){
          await refreshStatus();
          if(state.view==="risks")await loadRisks();
          else if(state.view!=="import")await refreshSongs();
          toast(job.status==="completed"?"งาน "+(job.kind==="import"?"นำเข้า":job.kind==="recover"?"ตรวจซ่อมเนื้อร้อง":job.kind==="swipe-audit"?"ตรวจหลักฐานปาดเนื้อ":"สร้างไฟล์")+" เสร็จแล้ว":
            job.error||"งานล้มเหลว",job.status==="failed");
        }
      }
    }catch(error){setReady(false);}
  }
  async function openPicker(kind,target){
    try{
      const result=await api("/api/pick",{kind});
      if(result.path)$(target).value=result.path;
    }catch(error){toast("เปิดหน้าต่างเลือกไฟล์ไม่สำเร็จ: "+error.message,true);}
  }
  async function loadImportIssues(){
    const container=$("issues-list");
    container.replaceChildren();
    try{
      const result=await api("/api/import-issues");
      const rows=result.rows||[];
      if(!rows.length){
        const empty=document.createElement("p");
        empty.className="empty-small";
        empty.textContent="ยังไม่พบรายการอ่านเนื้อร้องผิดพลาดที่บันทึกไว้";
        container.append(empty);return;
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
        line.append(header,detail);
        container.append(line);
      }
      toast("พบ "+number(rows.length)+" รายการที่ต้องตรวจสอบ");
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
  function bind(){
    $("source-browse").addEventListener("click",()=>void openPicker("folder","source-folder"));
    $("lrc-browse").addEventListener("click",()=>void openPicker("lrc","media-lrc"));
    for(const button of document.querySelectorAll("[data-view]"))
      button.addEventListener("click",()=>view(button.dataset.view));
    $("issues-load").addEventListener("click",()=>void loadImportIssues());
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
    $("risk-open-lyrics").addEventListener("click",()=>{
      const song=state.riskSelected;
      if(!song)return;
      $("risk-dialog").close();
      void openLyrics({id:song.song_id,title:song.title});
    });
    $("import-start").addEventListener("click",()=>{
      const folder=$("source-folder").value.trim();
      if(!folder)return toast("กรุณาระบุโฟลเดอร์ต้นทาง",true);
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
      state.groups=[];state.selectedGroups.clear();renderGroups();
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
    $("lyrics-undo").addEventListener("click",()=>void undoLyrics());
    $("media-attach").addEventListener("click",()=>void attachLrc());
    $("build-all").addEventListener("click",()=>{
      for(const song of state.songs)if(song.version_id)state.selectedSongs.add(song.id);
      renderSongs();
    });
    $("build-clear").addEventListener("click",()=>{
      state.selectedSongs.clear();renderSongs();
    });
    $("build-start").addEventListener("click",()=>{
      if(!state.selectedSongs.size)return;
      void startJob("build",{song_ids:Array.from(state.selectedSongs)});
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
  }
  async function init(){
    bind();
    view(location.hash.slice(1) in labels?location.hash.slice(1):"import");
    try{
      const session=await api("/api/session");
      state.token=session.token;
      setReady(true);
      text("workspace-chip","คลัง: "+session.workspace.split(/[\\/]/).pop());
      await refreshStatus();
      await refreshJobs();
      setInterval(()=>{void refreshJobs();},1600);
    }catch{
      setReady(false);
      text("activity-title","โปรดเปิดแอปบน Windows");
      text("activity-subtitle","หน้านี้เป็นตัวอย่างหน้าตาโปรแกรม · การใช้งาน SQLite ต้องเปิดผ่านตัวติดตั้ง Song Studio Plus PC");
    }
  }
  void init();
})();
