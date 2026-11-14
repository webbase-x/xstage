/* X-Stage Video Karaoke import review — private client-side metadata editor.
 * Keeps source file bytes in the selected browser folder, never localStorage.
 * The owner must confirm embedded lyrics or supply genuine LRC timing.
 */
(function(scope){
'use strict';
const core=scope.XStageImportCore,$=id=>document.getElementById('cloud-import-video-'+id);
class Editor{
  constructor(importer){
    this.importer=importer;this.videos=[];this.edits=new Map();
    this.selectedKey='';this.previewUrl='';this.previewAbort=null;this.previewConverted=null;
    this.dom={};
    for(const id of ['editor','filter','select','code','title','artist','album','composer',
      'genre','language','year','mode','lrc','lrc-wrap','preview-btn','preview',
      'stamp','save','hint'])this.dom[id]=$(id);
    this.dom.select?.addEventListener('change',()=>this.selectSong(this.dom.select.value));
    this.dom.filter?.addEventListener('input',()=>this.renderOptions());
    this.dom.mode?.addEventListener('change',()=>this.updateMode());
    this.dom.save?.addEventListener('click',()=>{void this.saveCurrent();});
    this.dom['preview-btn']?.addEventListener('click',()=>{void this.previewCurrent();});
    this.dom.stamp?.addEventListener('click',()=>this.insertStamp());
  }
  fingerprint(item){return core.videoFingerprint(item);}
  get(item){
    const found=this.edits.get(item?.key);
    if(!found||found.fingerprint!==this.fingerprint(item))return null;
    try{return core.validateVideoDetails(item,found.metadata);}
    catch{return null;}
  }
  eligibleCount(){return this.videos.filter(item=>!!this.get(item)).length;}
  pendingCount(){return this.videos.length-this.eligibleCount();}
  exportEdits(){
    const eligible=new Set(this.videos.map(item=>item.key));
    return [...this.edits].filter(([key])=>eligible.has(key)).map(([key,value])=>[key,value]);
  }
  setPlan(plan,savedEdits){
    const prior=this.edits;
    this.videos=(plan?.songs||[]).filter(item=>!!item.video);
    this.edits=new Map();
    const restoring=Array.isArray(savedEdits)?new Map(savedEdits):prior;
    for(const item of this.videos){
      const found=restoring.get(item.key)||prior.get(item.key);
      if(found?.fingerprint===this.fingerprint(item))this.edits.set(item.key,found);
    }
    this.dom.editor.hidden=!this.videos.length;
    if(!this.videos.length){this.releasePreview();this.selectedKey='';return;}
    this.renderOptions();
    this.selectSong(this.videos.some(item=>item.key===this.selectedKey)
      ?this.selectedKey:this.videos[0].key);
  }
  renderOptions(){
    const needle=String(this.dom.filter.value||'').trim().toLocaleLowerCase('th-TH');
    const selected=this.selectedKey;
    const items=this.videos.filter(item=>!needle||
      (item.key+' '+item.video.file.name).toLocaleLowerCase('th-TH').includes(needle));
    const fragment=document.createDocumentFragment();
    for(const item of items.slice(0,250)){
      const option=document.createElement('option');option.value=item.key;
      option.textContent=(this.get(item)?'✓ ':'○ ')+item.video.file.name;
      fragment.appendChild(option);
    }
    this.dom.select.replaceChildren(fragment);
    if(items.some(item=>item.key===selected)&&[...this.dom.select.options].some(o=>o.value===selected))
      this.dom.select.value=selected;
    else if(this.dom.select.options.length){
      this.dom.select.selectedIndex=0;
      this.selectedKey=this.dom.select.value;
    }else this.selectedKey='';
    this.dom.select.disabled=!this.dom.select.options.length;
  }
  current(){return this.videos.find(item=>item.key===this.selectedKey)||null;}
  selectSong(key){
    this.releasePreview();
    this.selectedKey=key;
    const item=this.current();
    if(!item){this.dom.hint.textContent='ไม่พบวิดีโอตามคำค้น';return;}
    const saved=this.get(item);
    const meta=saved||{
      code:item.code,title:item.code,artist:'',album:'',composer:'',genre:'',
      language:'',year:'',mode:item.lrc||item.json?'timed':'review',lrc:''
    };
    for(const field of ['code','title','artist','album','composer','genre','language','year'])
      this.dom[field].value=meta[field]??'';
    this.dom.mode.value=meta.mode;
    this.dom.lrc.value=meta.lrc||'';
    this.updateMode();
    this.dom.hint.textContent=(saved?'✓ บันทึกข้อมูลแล้ว · ':'ยังไม่ได้บันทึกข้อมูล · ')+
      (item.lrc||item.json?'พบเนื้อร้องคู่ไฟล์แล้ว':
        'ต้องเลือกว่ามีเนื้อร้องฝังภาพ หรือสร้าง LRC พร้อมเวลาให้ครบ')+
      ' · ไม่ลบไฟล์ต้นฉบับ';
  }
  updateMode(){
    const mode=this.dom.mode.value;
    this.dom['lrc-wrap'].hidden=mode!=='timed';
    this.dom.stamp.hidden=mode!=='timed'||this.dom.preview.hidden;
  }
  async saveCurrent(){
    const item=this.current();if(!item)return;
    const metadata={};
    for(const key of ['code','title','artist','album','composer','genre','language','year'])
      metadata[key]=this.dom[key].value;
    metadata.mode=this.dom.mode.value;metadata.lrc=this.dom.lrc.value;
    try{
      const approved=core.validateVideoDetails(item,metadata);
      this.edits.set(item.key,{fingerprint:this.fingerprint(item),metadata:approved});
      this.renderOptions();
      this.importer.updateVideoStats();
      await this.importer.save({status:'selected'});
      this.dom.hint.textContent='✓ บันทึกข้อมูล '+approved.title+' / '+approved.artist+
        ' แล้ว · คลิกเริ่มตรวจและอัปโหลดเมื่อพร้อม';
    }catch(error){this.dom.hint.textContent=error.message;}
  }
  releasePreview(){
    this.previewAbort?.abort();this.previewAbort=null;
    const player=this.dom.preview;
    if(player){player.pause();player.hidden=true;player.removeAttribute('src');player.load();}
    if(this.previewUrl){URL.revokeObjectURL(this.previewUrl);this.previewUrl='';}
    this.dom.stamp&&(this.dom.stamp.hidden=true);
    this.previewConverted=null;
  }
  async previewCurrent(){
    const item=this.current();if(!item)return;
    this.releasePreview();
    const signal=new AbortController();this.previewAbort=signal;
    try{
      const file=item.video.file;
      if(!await core.validVideo(file))throw Error('วิดีโอ: หัวไฟล์ต้นฉบับไม่ถูกต้อง');
      let playable=file;
      const mime=core.videoMime(file.name);
      const canNative=!!(mime&&this.dom.preview.canPlayType(mime));
      if(core.needsVideoConversion(file.name)&&!canNative){
        const converter=scope.XStageVideoTranscode;
        if(!converter)throw Error('วิดีโอ: ไม่พบตัวแปลงวิดีโอ');
        playable=await converter.convert(file,{
          signal:signal.signal,requireAudio:item.audio.file===file,
          onStatus:message=>{this.dom.hint.textContent=message;}
        });
        this.previewConverted={fingerprint:this.fingerprint(item),file:playable};
      }
      if(signal.signal.aborted||this.current()!==item)return;
      this.previewUrl=URL.createObjectURL(playable);
      this.dom.preview.src=this.previewUrl;
      this.dom.preview.hidden=false;this.dom.preview.load();
      this.updateMode();
      this.dom.hint.textContent=playable===file
        ?'ทดลองเล่นจากต้นฉบับ · ถ้า Codec ไม่รองรับให้ใช้ Song Studio PC หรือเวอร์ชัน MP4'
        :'กำลังทดลองจาก MP4 ที่แปลงบนเครื่อง · ต้นฉบับยังอยู่ครบ';
    }catch(error){
      if(error?.name!=='AbortError')this.dom.hint.textContent=error.message;
    }finally{if(this.previewAbort===signal)this.previewAbort=null;}
  }
  insertStamp(){
    const p=this.dom.preview;
    if(p.hidden||!Number.isFinite(p.currentTime))return;
    const time=Math.max(0,p.currentTime);
    const minute=String(Math.floor(time/60)).padStart(2,'0');
    const second=(time%60).toFixed(2).padStart(5,'0');
    const stamp='['+minute+':'+second+']';
    this.dom.lrc.value+=(this.dom.lrc.value.trimEnd()?'\n':'')+stamp;
    this.dom.lrc.focus();
    this.dom.hint.textContent='แทรกเวลา '+stamp+' แล้ว · เติมข้อความเนื้อร้องหลังวงเล็บและบันทึก';
  }
}
scope.XStageVideoEditor={init:importer=>new Editor(importer)};
})(typeof window!=='undefined'?window:globalThis);
