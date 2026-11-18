"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const state = {token:null,ready:false,view:"import",groups:[],selectedGroups:new Set(),
                 songs:[],selectedSongs:new Set(),latestEdit:null,activeJob:null,
                 jobSignature:"",toastTimer:null};
  const labels={import:"นำเข้าเพลง",lyrics:"แก้ไขเนื้อร้อง",media:"เสียงและวิดีโอ",
                build:"สร้างไฟล์ X-Stage",library:"คลังเพลง"};
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
    if(name==="library"||name==="build"||name==="media")void refreshSongs();
    if(name==="import")void refreshStatus();
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
    for(const id of ["import-start","lyrics-find","media-attach","build-start","source-browse","lrc-browse"]){
      $(id).disabled=!enabled;
    }
  }
  async function refreshStatus(){
    if(!state.ready)return;
    const result=await api("/api/status");
    for(const key of ["songs","media","lyrics","exports"])
      text("stat-"+key,number(result[key]));
  }
  async function refreshSongs(){
    if(!state.ready)return;
    const q=state.view==="library"?$("library-search").value.trim():"";
    const data=await api("/api/songs?q="+encodeURIComponent(q)+"&limit=80");
    state.songs=data.rows||[];
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
      const ready=Boolean(song.version_id);
      const columns=[String(song.code).padStart(8,"0"),song.title||song.original_code,
          format,ready? song.timing_status:"ไม่มีข้อมูลเวลา",
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
      if(ready){
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
        format+" · "+(ready?(song.timing_status||"มีเนื้อร้อง"):"ยังไม่มี Lyrics/Timing");
      div.append(small);label.append(check,div);build.append(label);
    }
    if(previous)select.value=previous;
    updateBuildSelection();
  }
  function updateBuildSelection(){
    const present=new Set(state.songs.map(song=>song.id));
    for(const id of state.selectedSongs){
      if(!present.has(id))state.selectedSongs.delete(id);
    }
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
        timing.textContent=Number(line.start).toFixed(2)+" – "+Number(line.end).toFixed(2)+"s";
        const details=document.createElement("div");
        const words=document.createElement("p");words.textContent=line.text;
        const note=document.createElement("small");
        note.textContent="บรรทัด "+(line.position+1)+" · "+line.timing+
                         " · จุดปาดสี "+line.cues.length+" จุด";
        details.append(words,note);element.append(timing,details);list.append(element);
      }
      $("lyrics-dialog").showModal();
    }catch(error){toast(error.message,true);}
  }
  async function searchGroups(){
    if(!state.ready)return;
    const q=$("lyrics-search").value.trim();
    state.selectedGroups.clear();
    state.groups=[];
    if(!q){text("groups-count","0 กลุ่ม");renderGroups();return;}
    try{
      const data=await api("/api/groups?q="+encodeURIComponent(q)+"&limit=100");
      state.groups=data.rows||[];
      renderGroups();
    }catch(error){toast(error.message,true);}
  }
  function renderGroups(){
    text("groups-count",number(state.groups.length)+" กลุ่ม");
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
        if(checkbox.checked)state.selectedGroups.add(entry.group_key);
        else state.selectedGroups.delete(entry.group_key);
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
    const chosen=state.groups.filter(g=>state.selectedGroups.has(g.group_key));
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
      const result=await api(kind==="import"?"/api/import":"/api/build",payload);
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
      if(!job)return;
      text("activity-status",job.status==="running"?"กำลังทำงาน":
          job.status==="completed"?"เสร็จเรียบร้อย":job.status==="failed"?"ข้อผิดพลาด":"หยุดแล้ว");
      text("activity-title",job.kind==="import"?"นำเข้าและตรวจ SHA-256":
          "สร้างไฟล์ X-Stage Plus");
      text("activity-subtitle",job.message||"");
      const p=job.progress||{};
      text("progress-detail",job.kind==="import"?
          "ไฟล์ใหม่ "+number(p.files_new)+" · ไฟล์ซ้ำ "+number(p.media_duplicates)+
          " · เนื้อร้องใหม่ "+number(p.lyrics_new)+" · ผิดพลาด "+number(p.failures):
          "สร้าง "+number(p.built)+" · ข้าม "+number(p.skipped)+" · ไม่สำเร็จ "+number(p.failed));
      text("progress-count",number(p.files_seen||p.done||0)+" รายการ");
      const progress=job.status==="running"?37:job.status==="completed"?100:0;
      $("progress-fill").style.width=progress+"%";
      const signature=job.id+":"+job.status;
      if(state.jobSignature!==signature){
        state.jobSignature=signature;
        if(job.status==="completed"||job.status==="failed"){
          await refreshStatus();
          if(state.view!=="import")await refreshSongs();
          toast(job.status==="completed"?"งาน "+(job.kind==="import"?"นำเข้า":"สร้างไฟล์")+" เสร็จแล้ว":
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
  function bind(){
    $("source-browse").addEventListener("click",()=>void openPicker("folder","source-folder"));
    $("lrc-browse").addEventListener("click",()=>void openPicker("lrc","media-lrc"));
    for(const button of document.querySelectorAll("[data-view]"))
      button.addEventListener("click",()=>view(button.dataset.view));
    $("import-start").addEventListener("click",()=>{
      const folder=$("source-folder").value.trim();
      if(!folder)return toast("กรุณาระบุโฟลเดอร์ต้นทาง",true);
      void startJob("import",{folder});
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
      for(const group of state.groups)state.selectedGroups.add(group.group_key);
      renderGroups();
    });
    $("groups-clear").addEventListener("click",()=>{
      state.selectedGroups.clear();renderGroups();
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
    $("library-find").addEventListener("click",()=>void refreshSongs());
    $("library-search").addEventListener("keydown",event=>{
      if(event.key==="Enter")void refreshSongs();
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
