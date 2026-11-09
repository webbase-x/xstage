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
    qrPanel.hidden = true;
    keyboard.hidden = false;
    stage.classList.add('keyboard-open');
    kbToggle.setAttribute('aria-expanded','true');
    kbToggle.classList.add('active');
    // Prevent a second native mobile keyboard from opening on top of the built-in one.
    search.readOnly = true;
    search.focus({preventScroll:true});
    search.dispatchEvent(new Event('input',{bubbles:true}));
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
      keyButton('⌫',()=>editSearch('', 'backspace'),''),
      keyButton('ล้าง',()=>editSearch('', 'clear'),''),
      keyButton('Enter',()=>{
        if(!state.token)return;
        search.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));
        hideKeyboard();
      },'wide key-enter')
    );
    kbKeys.append(row);
  }
  drawKeyboard();
  kbToggle.addEventListener('click',()=>keyboard.hidden?showKeyboard():hideKeyboard());
  kbClose.addEventListener('click',hideKeyboard);
  document.addEventListener('keydown',e=>{
    if(e.key==='Escape'&&!keyboard.hidden)hideKeyboard();
  });

  let session=null;
  function status(text){qrStatus.textContent=text;}
  function showApproval(show){
    qrApprove.hidden=!show;
    qrReject.hidden=!show;
  }
  function send(conn,msg){
    if(conn && conn.open){try{conn.send(msg);}catch{}}
  }
  function snapshot(){
    return {
      type:'status',now:state.current ? String(state.current.title||'') : '',
      artist:state.current ? String(state.current.artist||'') : '',
      paused:ui.player.paused,volume:Math.round(ui.player.volume*100),
      queue:state.queue.length,ready:!!state.token
    };
  }
  function randomSecret(){
    const bytes=new Uint8Array(24);crypto.getRandomValues(bytes);
    return Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
  }
  function destroySession(){
    if(!session)return;
    const old=session;session=null;
    try{old.pending?.close();}catch{}
    try{old.conn?.close();}catch{}
    try{old.peer?.destroy();}catch{}
    showApproval(false);
    qrLink.textContent='';
    qrLink.removeAttribute('href');
    qrCanvas.hidden=true;
    status('ยุติการเชื่อมต่อแล้ว');
    qrEnd.textContent='สร้าง QR ใหม่';
  }
  async function createSession(){
    destroySession();
    if(!state.token){status('เข้าสู่ระบบ Google บนจอหลักก่อน');return;}
    if(typeof Peer!=='function'){status('โหลดระบบรีโมทไม่สำเร็จ กรุณาตรวจอินเทอร์เน็ต');return;}
    if(!window.crypto?.getRandomValues){status('เบราว์เซอร์นี้ไม่รองรับการสร้างรหัสเชื่อมต่อที่ปลอดภัย');return;}
    const active={peer:null,secret:randomSecret(),conn:null,pending:null,approved:false};
    session=active;
    qrEnd.textContent='เปลี่ยน QR';
    status('กำลังเตรียมการเชื่อมต่อมือถือ…');
    const peer=new Peer();
    active.peer=peer;
    peer.on('open',async id=>{
      if(session!==active)return;
      const url=new URL('remote.html',location.href);
      url.search='';url.hash='p='+encodeURIComponent(id)+'&k='+encodeURIComponent(active.secret);
      qrLink.textContent='เปิดลิงก์รีโมทบนมือถือ';
      qrLink.href=url.href;
      if(typeof QRCode==='undefined'){
        status('ไม่สามารถสร้าง QR ได้ ใช้ลิงก์รีโมทแทน');return;
      }
      try{
        await QRCode.toCanvas(qrCanvas,url.href,{width:232,margin:2,errorCorrectionLevel:'M'});
        if(session!==active)return;
        qrCanvas.hidden=false;
        status('ใช้มือถือสแกน QR แล้วอนุญาตการเชื่อมต่อที่จอหลัก');
      }catch{status('สร้าง QR ไม่สำเร็จ ใช้ลิงก์รีโมทแทน');}
    });
    peer.on('connection',conn=>{
      if(session!==active){conn.close();return;}
      if(active.conn?.open || active.pending){conn.close();return;}
      active.pending=conn;
      conn.on('data',message=>{
        if(session!==active)return;
        if(!active.approved){
          if(message?.type!=='hello'||message.key!==active.secret){conn.close();return;}
          status('มือถือกำลังขอเชื่อมต่อ กด “อนุญาต” บนจอหลัก');
          showApproval(true);
          return;
        }
        if(active.conn!==conn)return;
        handleRemote(conn,message);
      });
      conn.on('close',()=>{
        if(session!==active)return;
        if(active.conn===conn){active.conn=null;active.approved=false;status('มือถือหลุดการเชื่อมต่อ สแกน QR เพื่อเชื่อมต่อใหม่');}
        if(active.pending===conn){active.pending=null;showApproval(false);}
      });
      conn.on('error',()=>{if(active.pending===conn){active.pending=null;showApproval(false);}});
    });
    peer.on('error',err=>{if(session===active)status('เชื่อมต่อรีโมทไม่ได้: '+(err?.type||'เครือข่ายไม่พร้อม'));});
    peer.on('disconnected',()=>{if(session===active&&!active.conn)status('การเชื่อมต่อเซิร์ฟเวอร์จับคู่หลุด กรุณาลองสร้าง QR ใหม่');});
  }
  qrApprove.addEventListener('click',()=>{
    if(!session?.pending)return;
    const active=session;
    const conn=active.pending;
    active.conn=conn;active.pending=null;active.approved=true;
    showApproval(false);
    send(conn,{type:'ready'});
    send(conn,snapshot());
    status('มือถือเชื่อมต่อแล้ว สามารถควบคุมเพลงได้');
  });
  qrReject.addEventListener('click',()=>{
    session?.pending?.close();
    if(session)session.pending=null;
    showApproval(false);
    status('ปฏิเสธการเชื่อมต่อแล้ว');
  });
  qrEnd.addEventListener('click',createSession);
  qrToggle.addEventListener('click',()=>{
    hideKeyboard();
    qrPanel.hidden=!qrPanel.hidden;
    if(!qrPanel.hidden && !session)createSession();
  });
  qrClose.addEventListener('click',()=>{qrPanel.hidden=true;});
  function handleRemote(conn,msg){
    if(!msg||typeof msg!=='object'||!state.token)return;
    const type=msg.type;
    if(type==='search'){
      const term=String(msg.query||'').slice(0,70).trim().toLocaleLowerCase('th');
      const items=[];
      if(term){
        for(let i=0;i<state.songs.length && items.length<30;i++){
          const song=state.songs[i];
          if([song.code,song.title,song.artist].some(v=>String(v||'').toLocaleLowerCase('th').includes(term)))
            items.push({index:i,code:String(song.code||''),title:String(song.title||''),artist:String(song.artist||'')});
        }
      }
      send(conn,{type:'results',items});
    }else if(type==='song'){
      if(!Number.isSafeInteger(msg.index)||msg.index<0||msg.index>=state.songs.length)return;
      const song=state.songs[msg.index];
      if(!playable(song))return;
      if(msg.mode==='now')playSong(song);
      else if(msg.mode==='queue')addToQueue(song);
      else if(state.current||state.loading)addToQueue(song);else playSong(song);
    }else if(type==='control'){
      switch(msg.action){
        case 'play':togglePlayback();break;
        case 'stop':stopSong();break;
        case 'next':playNext();break;
        case 'previous':ui.previous.click();break;
        case 'volume':{
          const level=Number(msg.value);
          if(!Number.isFinite(level))return;
          ui.volume.value=String(Math.max(0,Math.min(100,Math.round(level))));
          ui.volume.dispatchEvent(new Event('input',{bubbles:true}));
          break;
        }
        default:return;
      }
    }else return;
    send(conn,snapshot());
  }
  setInterval(()=>{if(session?.approved && session.conn?.open)send(session.conn,snapshot());},1200);
  window.addEventListener('beforeunload',destroySession);
  ui.logout.addEventListener('click',destroySession);
})();