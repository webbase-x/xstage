/* X-Stage Online: virtual keyboard and QR-paired mobile remote.
 * Pairing credentials exist only in memory and a URL fragment; no Google tokens are sent. */
'use strict';
(function(){
  const byId = id => document.getElementById(id);
  const stage = byId('stage');
  const search = byId('search');
  const keyboard = byId('virtual-keyboard');
  const kbKeys = byId('virtual-keys');
  const kbToggle = byId('toggle-keyboard');
  const kbClose = byId('virtual-close');
  const kbLang = byId('virtual-language');
  const qrToggle = byId('toggle-remote');
  const qrPanel = byId('remote-pair-panel');
  const qrClose = byId('remote-pair-close');
  const qrCanvas = byId('remote-qr');
  const qrStatus = byId('remote-pair-status');
  const qrLink = byId('remote-link');
  const qrApprove = byId('remote-approve');
  const qrReject = byId('remote-reject');
  const qrEnd = byId('remote-end');
  if(!stage || !search || !keyboard || !kbKeys || !qrPanel) return;

  const layouts = {
    th: [
      ['ๆ','ไ','ำ','พ','ะ','ั','ี','ร','น','ย','บ','ล'],
      ['ฟ','ห','ก','ด','เ','้','่','า','ส','ว','ง'],
      ['ผ','ป','แ','อ','ิ','ื','ท','ม','ใ','ฝ'],
      ['๐','๑','๒','๓','๔','๕','๖','๗','๘','๙']
    ],
    en: [
      ['1','2','3','4','5','6','7','8','9','0'],
      ['q','w','e','r','t','y','u','i','o','p'],
      ['a','s','d','f','g','h','j','k','l'],
      ['z','x','c','v','b','n','m']
    ]
  };
  // Reserve exactly the space occupied by the onscreen keyboard for search results.
  function updateKeyboardHeight(){
    if(!keyboard.hidden)stage.style.setProperty('--virtual-keyboard-height',Math.ceil(keyboard.getBoundingClientRect().height)+'px');
  }
  if(typeof ResizeObserver!=='undefined')new ResizeObserver(updateKeyboardHeight).observe(keyboard);
  let layout = 'th';
  let shift = false;
  function hideKeyboard(){
    keyboard.hidden = true;
    stage.classList.remove('keyboard-open');
    kbToggle.setAttribute('aria-expanded','false');
    kbToggle.classList.remove('active');
    search.readOnly = false;
    search.blur();
  }
  function showKeyboard(){
    keyboard.hidden = false;
    stage.classList.add('keyboard-open');
    kbToggle.setAttribute('aria-expanded','true');
    kbToggle.classList.add('active');
    // Prevent a second native mobile keyboard from opening on top of the built-in one.
    search.readOnly = true;
    search.focus({preventScroll:true});
    search.dispatchEvent(new Event('input',{bubbles:true}));
    updateKeyboardHeight();
  }
  function editSearch(value,action){
    if(!state.token) { hideKeyboard(); return; }
    const start = Number.isInteger(search.selectionStart) ? search.selectionStart : search.value.length;
    const end = Number.isInteger(search.selectionEnd) ? search.selectionEnd : search.value.length;
    let next = search.value;
    let pos = start;
    if(action === 'clear') { next=''; pos=0; }
    else if(action === 'backspace') {
      if(end>start){ next=next.slice(0,start)+next.slice(end); }
      else if(start>0){ next=next.slice(0,start-1)+next.slice(end); pos=start-1; }
    }else{
      next=next.slice(0,start)+value+next.slice(end);
      pos=start+value.length;
    }
    search.value=next;
    search.dispatchEvent(new Event('input',{bubbles:true}));
    search.focus({preventScroll:true});
    try {search.setSelectionRange(pos,pos);}catch{}
  }
  function keyButton(text,action,cls){
    const b=document.createElement('button');
    b.type='button';b.textContent=text;b.className='virtual-key'+(cls?' '+cls:'');
    b.setAttribute('aria-label',text);
    b.addEventListener('pointerdown',e=>e.preventDefault());
    b.addEventListener('click',action);
    return b;
  }
  function drawKeyboard(){
    kbKeys.replaceChildren();
    kbLang.textContent=layout==='th'?'ภาษาไทย':'English';
    for(const letters of layouts[layout]){
      const row=document.createElement('div');row.className='virtual-key-row';
      for(const ch of letters){
        const val=layout==='en' && shift ? ch.toUpperCase() : ch;
        row.append(keyButton(val,()=>editSearch(val),'')); 
      }
      kbKeys.append(row);
    }
    const row=document.createElement('div');row.className='virtual-key-row virtual-key-actions';
    row.append(
      keyButton('TH / EN',()=>{layout=layout==='th'?'en':'th';drawKeyboard();},'wide'),
      keyButton('⇧',()=>{shift=!shift;drawKeyboard();},''),
      keyButton('เว้นวรรค',()=>editSearch(' '),'wide'),
      keyButton('↑',()=>search.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowUp',bubbles:true,cancelable:true})),''),
      keyButton('↓',()=>search.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true,cancelable:true})),''),
      keyButton('⌫',()=>editSearch('', 'backspace'),''),
      keyButton('ล้าง',()=>editSearch('', 'clear'),''),
      keyButton('Enter',()=>{
        if(!state.token)return;
        search.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));
        hideKeyboard();
      },'wide key-enter')
    );
    kbKeys.append(row);
    updateKeyboardHeight();
  }
  drawKeyboard();
  kbToggle.addEventListener('click',()=>keyboard.hidden?showKeyboard():hideKeyboard());
  kbClose.addEventListener('click',hideKeyboard);
  document.addEventListener('keydown',e=>{
    if(e.key==='Escape'&&!keyboard.hidden)hideKeyboard();
  });

  // Guests approve connection once on the host, then can search, enqueue,
  // and use a restricted player controller. No Google token or file URLs leave the host.
  const requestPanel=byId('remote-request-panel');
  const requestList=byId('remote-request-list');
  const requestCount=byId('remote-request-count');
  const requestToggle=byId('remote-request-toggle');
  const requestClose=byId('remote-request-close');
  const activity=[];
  let session=null, sequence=0;
  function status(value){qrStatus.textContent=value;}
  function send(conn,data){if(conn?.open)try{conn.send(data);}catch{}}
  function randomSecret(){
    const bytes=new Uint8Array(24);crypto.getRandomValues(bytes);
    return Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
  }
  function songSummary(song){
    return {title:String(song?.title||''),artist:String(song?.artist||''),code:String(song?.code||''),
      singer:String(song?.queueSinger||'')};
  }
  function snapshot(){
    return {type:'status',ready:!!state.token,playing:!!ui.player.src&&!ui.player.paused,
      now:songSummary(state.current),queue:state.queue.slice(0,50).map(songSummary),
      queueCount:state.queue.length,volume:Math.round(Number(ui.volume.value)||0),
      muted:ui.player.muted,medley:!!state.medley,scale:state.visualScale||1};
  }
  function broadcast(msg){
    if(!session)return;
    for(const entry of session.connections.values())if(entry.approved)send(entry.conn,msg);
  }
  function broadcastStatus(){broadcast(snapshot());}
  function clearPeerSession(){
    if(!session)return;
    const active=session;session=null;
    for(const entry of active.connections.values())try{entry.conn.close();}catch{}
    try{active.peer?.destroy();}catch{}
    qrApprove.hidden=true;qrReject.hidden=true;
    qrLink.textContent='';qrLink.removeAttribute('href');qrCanvas.hidden=true;
    qrEnd.textContent='สร้าง QR ใหม่';status('ปิดการเชื่อมต่อรีโมทแล้ว');
  }
  function redrawActivity(){
    requestCount.textContent=String(activity.length);
    requestList.replaceChildren();
    if(!activity.length){
      const p=document.createElement('p');p.textContent='ยังไม่มีรายการขอเพลง';
      requestList.append(p);return;
    }
    for(const item of activity.slice().reverse()){
      const row=document.createElement('div');row.className='request-item';
      const info=document.createElement('div');info.className='request-info';
      const title=document.createElement('strong');title.textContent=item.title;
      const by=document.createElement('small');by.textContent=item.singer+' · '+item.result+(item.note?' · '+item.note:'');
      info.append(title,by);row.append(info);requestList.append(row);
    }
  }
  requestToggle?.addEventListener('click',()=>{
    requestPanel.hidden=!requestPanel.hidden;
    requestToggle.setAttribute('aria-expanded',String(!requestPanel.hidden));
  });
  requestClose?.addEventListener('click',()=>{
    requestPanel.hidden=true;requestToggle.setAttribute('aria-expanded','false');
  });
  redrawActivity();
  function acceptRequest(conn,msg,limits){
    if(!state.token){send(conn,{type:'request-error',message:'เจ้าของเวทียังไม่เปิดคลังเพลง'});return;}
    if(state.queue.length>=150){send(conn,{type:'request-error',message:'คิวเต็มแล้ว กรุณารอ'});return;}
    if(!Number.isSafeInteger(msg.index)||msg.index<0||msg.index>=state.songs.length)return;
    const song=state.songs[msg.index];
    if(!playable(song)){send(conn,{type:'request-error',message:'เพลงนี้ยังเล่นไม่ได้'});return;}
    const now=Date.now();
    while(limits.length&&now-limits[0]>60_000)limits.shift();
    if(limits.length>=8){send(conn,{type:'request-error',message:'ขอเพลงบ่อยเกินไป กรุณารอสักครู่'});return;}
    limits.push(now);
    const singer=String(msg.singer||'ไม่ระบุชื่อ').trim().slice(0,45)||'ไม่ระบุชื่อ';
    const note=String(msg.note||'').trim().slice(0,90);
    const queued={...song,queueSinger:singer};
    const wasEmpty=state.queue.length===0;
    const inactive=!state.loading&&(!state.current||!ui.player.src||ui.player.ended||
      (ui.player.paused&&ui.player.currentTime<.5));
    addToQueue(queued);
    const playImmediately=wasEmpty&&inactive;
    if(playImmediately)playNext(); // Uses the original queue playback path.
    activity.push({title:song.title||song.code,singer,note,result:playImmediately?'เล่นทันที':'เพิ่มเข้าคิว'});
    if(activity.length>30)activity.shift();
    redrawActivity();
    send(conn,{type:'request-received',id:++sequence,title:String(song.title||''),
      result:playImmediately?'playing':'queued'});
    broadcastStatus();
  }
  function handleControl(conn,msg,entry){
    const now=Date.now();
    if(now-entry.lastControl<120)return;entry.lastControl=now;
    const action=String(msg.action||'');
    const audio=ui.player;
    if(action==='playpause')togglePlayback();
    else if(action==='stop')stopSong();
    else if(action==='next')playNext();
    else if(action==='volume-up'||action==='volume-down'){
      const next=Math.max(0,Math.min(100,Math.round(Number(ui.volume.value)||
        0)+(action==='volume-up'?5:-5)));
      ui.volume.value=String(next);ui.volume.dispatchEvent(new Event('input',{bubbles:true}));
      audio.muted=false;
    }else if(action==='mute'){
      audio.muted=!audio.muted;
    }else if(action==='view-bigger'||action==='view-smaller'){
      setStageVisualScale((state.visualScale||1)+(action==='view-bigger'?.1:-.1));
    }else if(action==='medley'){
      setMedleyMode(!state.medley);
    }else return;
    broadcastStatus();
  }
  async function createSession(){
    clearPeerSession();
    if(typeof Peer!=='function'){status('โหลดระบบเชื่อมต่อมือถือไม่ได้ กรุณาตรวจอินเทอร์เน็ต');return;}
    if(!window.crypto?.getRandomValues){status('เบราว์เซอร์ไม่รองรับการเชื่อมต่ออย่างปลอดภัย');return;}
    const active={peer:null,secret:randomSecret(),connections:new Map(),pending:null};
    session=active;qrEnd.textContent='เปลี่ยน QR';
    status('กำลังสร้าง QR เพื่อจับคู่รีโมท…');
    const peer=new Peer();active.peer=peer;
    peer.on('open',async id=>{
      if(session!==active)return;
      const url=new URL('remote.html',location.href);
      url.search='';url.hash='p='+encodeURIComponent(id)+'&k='+encodeURIComponent(active.secret);
      qrLink.textContent='เปิดรีโมท X-Stage บนมือถือ';qrLink.href=url.href;
      if(typeof QRCode==='undefined'){status('ไม่สามารถสร้าง QR ได้ ใช้ลิงก์รีโมทแทน');return;}
      try{
        await QRCode.toCanvas(qrCanvas,url.href,{width:232,margin:2,errorCorrectionLevel:'M'});
        if(session!==active)return;
        qrCanvas.hidden=false;
        status('สแกน QR แล้วอนุมัติมือถือครั้งแรกบนจอหลัก');
      }catch{status('สร้าง QR ไม่สำเร็จ ใช้ลิงก์รีโมทแทน');}
    });
    peer.on('connection',conn=>{
      if(session!==active){conn.close();return;}
      if(active.connections.size>=12){conn.close();return;}
      const entry={conn,approved:false,lastSearch:0,lastControl:0,requests:[]};
      active.connections.set(conn,entry);
      conn.on('data',msg=>{
        if(session!==active||!msg||typeof msg!=='object')return;
        if(!entry.approved){
          if(msg.type!=='hello'||msg.key!==active.secret){conn.close();return;}
          if(active.pending&&active.pending!==entry){
            send(conn,{type:'error',message:'เจ้าของเวทีกำลังอนุมัติมือถืออีกเครื่อง'});conn.close();return;
          }
          active.pending=entry;
          // Make the approval buttons visible even if the QR panel was closed
          // while the phone was scanning.
          qrPanel.hidden=false;stage.classList.add('remote-visible');
          qrToggle.setAttribute('aria-expanded','true');
          qrApprove.hidden=false;qrReject.hidden=false;
          status('มือถือขอเชื่อมต่อ · กด “อนุญาต” หนึ่งครั้ง');
          send(conn,{type:'pending'});
          return;
        }
        if(msg.type==='search'){
          const now=Date.now();if(now-entry.lastSearch<150)return;entry.lastSearch=now;
          const term=String(msg.query||'').trim().slice(0,70).toLocaleLowerCase('th');
          const items=[];
          if(term&&state.token){
            for(let i=0;i<state.songs.length&&items.length<30;i++){
              const song=state.songs[i];
              if(playable(song)&&[song.code,song.title,song.artist].some(v=>
                String(v||'').toLocaleLowerCase('th').includes(term))){
                items.push({index:i,code:String(song.code||''),title:String(song.title||''),
                  artist:String(song.artist||'')});
              }
            }
          }
          send(conn,{type:'results',items,query:term,notReady:!state.token});
        }else if(msg.type==='request'){
          acceptRequest(conn,msg,entry.requests);
        }else if(msg.type==='control'){
          handleControl(conn,msg,entry);
        }else if(msg.type==='refresh'){
          send(conn,snapshot());
        }
      });
      const cleanup=()=>{
        active.connections.delete(conn);
        if(active.pending===entry){
          active.pending=null;qrApprove.hidden=true;qrReject.hidden=true;
          status('มือถือยกเลิกการเชื่อมต่อ');
        }
      };
      conn.on('close',cleanup);conn.on('error',cleanup);
    });
    peer.on('error',err=>{if(session===active)status('เชื่อมต่อไม่ได้: '+(err?.type||'เครือข่ายไม่พร้อม'));});
    peer.on('disconnected',()=>{
      if(session===active)status('การจับคู่หลุด กรุณากด “เปลี่ยน QR” เมื่อเชื่อมต่อไม่ได้');
    });
  }
  qrApprove.addEventListener('click',()=>{
    const entry=session?.pending;
    if(!entry||!entry.conn.open)return;
    session.pending=null;entry.approved=true;
    qrApprove.hidden=true;qrReject.hidden=true;
    send(entry.conn,{type:'ready'});
    send(entry.conn,snapshot());
    status('อนุมัติแล้ว · มือถือสามารถขอเพลงและควบคุมการเล่นได้');
  });
  qrReject.addEventListener('click',()=>{
    const entry=session?.pending;
    if(entry){session.pending=null;entry.conn.close();}
    qrApprove.hidden=true;qrReject.hidden=true;
    status('ปฏิเสธการเชื่อมต่อมือถือ');
  });
  qrEnd.addEventListener('click',createSession);
  function showQR(open){
    qrPanel.hidden=!open;
    stage.classList.toggle('remote-visible',open);
    qrToggle.setAttribute('aria-expanded',String(open));
    qrToggle.classList.toggle('active',open);
    if(open&&!session)createSession();
  }
  qrToggle.addEventListener('click',()=>showQR(qrPanel.hidden));
  qrClose.addEventListener('click',()=>showQR(false));
  setInterval(broadcastStatus,1200);
  window.addEventListener('beforeunload',clearPeerSession);
  ui.logout.addEventListener('click',clearPeerSession);
})();