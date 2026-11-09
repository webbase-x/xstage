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

  // The mobile page is a song-request terminal, never a playback remote.
  // No mobile Google login, Drive token, file ID or media URL is sent over WebRTC.
  const requestPanel=byId('remote-request-panel');
  const requestList=byId('remote-request-list');
  const requestCount=byId('remote-request-count');
  const requestToggle=byId('remote-request-toggle');
  const requestClose=byId('remote-request-close');
  const requests=[];
  let nextRequestId=0;
  let session=null;
  function status(value){qrStatus.textContent=value;}
  function send(conn,data){if(conn?.open)try{conn.send(data);}catch{}}
  function snapshot(){return {type:'status',ready:!!state.token,requests:requests.length};}
  function randomSecret(){
    const bytes=new Uint8Array(24);crypto.getRandomValues(bytes);
    return Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
  }
  function clearPeerSession(){
    if(!session)return;
    const active=session;session=null;
    for(const conn of active.connections){try{conn.close();}catch{}}
    try{active.peer?.destroy();}catch{}
    qrLink.textContent='';qrLink.removeAttribute('href');qrCanvas.hidden=true;
    qrEnd.textContent='สร้าง QR ใหม่';
    status('ปิดการเชื่อมต่อเดิมแล้ว');
  }
  function requestButton(text,action,variant){
    const btn=document.createElement('button');
    btn.type='button';btn.textContent=text;btn.className='request-action '+variant;
    btn.addEventListener('click',action);return btn;
  }
  function redrawRequests(){
    requestCount.textContent=String(requests.length);
    requestList.replaceChildren();
    if(!requests.length){
      const p=document.createElement('p');
      p.textContent='ยังไม่มีคำขอเพลงจากมือถือ';
      requestList.append(p);return;
    }
    for(const req of requests){
      const item=document.createElement('div');item.className='request-item';
      const info=document.createElement('div');info.className='request-info';
      const title=document.createElement('strong');
      title.textContent=String(req.song.code||'')+' · '+String(req.song.title||'');
      const secondary=document.createElement('small');
      secondary.textContent='ผู้ขอ: '+req.singer+(req.note?' · '+req.note:'');
      info.append(title,secondary);
      const actions=document.createElement('div');actions.className='request-actions';
      const finish=(accepted)=>{
        const index=requests.findIndex(entry=>entry.id===req.id);
        if(index<0)return;
        requests.splice(index,1);
        if(accepted){
          if(!state.token){status('เจ้าของคลังต้องเชื่อมต่อ Google Drive บนจอหลักก่อนเพิ่มคิว');redrawRequests();return;}
          addToQueue(req.song);
        }
        send(req.conn,{type:'request-result',id:req.id,accepted});
        redrawRequests();
      };
      actions.append(
        requestButton('✓ เพิ่มคิว',()=>finish(true),'accept'),
        requestButton('✕ ปฏิเสธ',()=>finish(false),'reject'));
      item.append(info,actions);
      requestList.append(item);
    }
  }
  function showRequests(open){
    requestPanel.hidden=!open;
    requestToggle.setAttribute('aria-expanded',String(open));
  }
  requestToggle.addEventListener('click',()=>showRequests(requestPanel.hidden));
  requestClose.addEventListener('click',()=>showRequests(false));
  redrawRequests();
  async function createSession(){
    clearPeerSession();
    if(typeof Peer!=='function'){status('ไม่สามารถโหลดระบบเชื่อมต่อมือถือได้ กรุณาตรวจอินเทอร์เน็ต');return;}
    if(!window.crypto?.getRandomValues){status('เบราว์เซอร์ไม่รองรับ QR ที่ปลอดภัย');return;}
    const active={peer:null,secret:randomSecret(),connections:new Set()};
    session=active;qrEnd.textContent='เปลี่ยน QR';
    status('กำลังเชื่อมต่อระบบรับคำขอเพลง…');
    const peer=new Peer();active.peer=peer;
    peer.on('open',async id=>{
      if(session!==active)return;
      const url=new URL('remote.html',location.href);
      url.search='';url.hash='p='+encodeURIComponent(id)+'&k='+encodeURIComponent(active.secret);
      qrLink.textContent='เปิดหน้ารีโมทขอเพลง';qrLink.href=url.href;
      if(typeof QRCode==='undefined'){status('ไม่สามารถสร้าง QR ได้ ใช้ลิงก์แทน');return;}
      try{
        await QRCode.toCanvas(qrCanvas,url.href,{width:232,margin:2,errorCorrectionLevel:'M'});
        if(session!==active)return;
        qrCanvas.hidden=false;
        status('พร้อมรับคำขอเพลง · มือถือสแกน QR ได้โดยไม่ต้องล็อกอิน');
      }catch{status('ไม่สามารถสร้าง QR ได้ ใช้ลิงก์แทน');}
    });
    peer.on('connection',conn=>{
      if(session!==active){conn.close();return;}
      if(active.connections.size>=15){conn.close();return;}
      active.connections.add(conn);
      let authenticated=false,lastQueryAt=0;
      const requestTimes=[];
      conn.on('data',message=>{
        if(session!==active||!message||typeof message!=='object')return;
        if(!authenticated){
          if(message.type!=='hello'||message.key!==active.secret){conn.close();return;}
          authenticated=true;
          send(conn,{type:'ready'});
          send(conn,snapshot());
          return;
        }
        if(message.type==='search'){
          const now=Date.now();if(now-lastQueryAt<120)return;lastQueryAt=now;
          if(!state.token){send(conn,{type:'results',items:[],notReady:true});return;}
          const term=String(message.query||'').slice(0,70).trim().toLocaleLowerCase('th');
          const items=[];
          if(term){
            for(let i=0;i<state.songs.length&&items.length<25;i++){
              const song=state.songs[i];
              if([song.code,song.title,song.artist].some(v=>
                String(v||'').toLocaleLowerCase('th').includes(term))){
                items.push({index:i,code:String(song.code||''),title:String(song.title||''),artist:String(song.artist||'')});
              }
            }
          }
          send(conn,{type:'results',items});
        }else if(message.type==='request'){
          if(!state.token){send(conn,{type:'request-error',message:'จอหลักยังไม่พร้อมรับคำขอเพลง'});return;}
          const i=message.index;
          if(!Number.isSafeInteger(i)||i<0||i>=state.songs.length)return;
          const song=state.songs[i];
          if(!playable(song))return;
          const singer=String(message.singer||'ไม่ระบุชื่อ').trim().slice(0,45)||'ไม่ระบุชื่อ';
          const note=String(message.note||'').trim().slice(0,90);
          const now=Date.now();
          while(requestTimes.length&&now-requestTimes[0]>60_000)requestTimes.shift();
          if(requestTimes.length>=5||requests.length>=40){
            send(conn,{type:'request-error',message:'คำขอมากเกินไป กรุณารอสักครู่'});return;
          }
          if(requests.some(r=>r.conn===conn&&r.song===song&&r.singer===singer)){
            send(conn,{type:'request-error',message:'เพลงนี้อยู่ระหว่างรอการอนุมัติแล้ว'});return;
          }
          requestTimes.push(now);
          const id=++nextRequestId;
          requests.push({id,song,singer,note,conn});
          redrawRequests();
          send(conn,{type:'request-received',id,title:String(song.title||'')});
          status('มีคำขอเพลงใหม่ '+requests.length+' รายการ · เปิดเมนู “คำขอเพลง” เพื่อจัดคิว');
        }
        // No remote control/play/stop/volume commands are accepted.
      });
      const cleanup=()=>active.connections.delete(conn);
      conn.on('close',cleanup);conn.on('error',cleanup);
    });
    peer.on('error',err=>{if(session===active)status('ไม่สามารถเชื่อมต่อรีโมท: '+(err?.type||'เครือข่ายไม่พร้อม'));});
    peer.on('disconnected',()=>{if(session===active)status('ระบบจับคู่ขาดการเชื่อมต่อ · กด “เปลี่ยน QR” เพื่อเชื่อมต่อใหม่');});
  }
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
  // Pairing approval buttons are no longer needed: knowing the time-limited
  // QR secret grants permission to submit a request, but not control playback.
  qrApprove.hidden=true;qrReject.hidden=true;
  setInterval(()=>{
    if(session)for(const conn of session.connections)send(conn,snapshot());
  },1400);
  window.addEventListener('beforeunload',clearPeerSession);
  ui.logout.addEventListener('click',()=>{
    clearPeerSession();
    requests.splice(0,requests.length);
    redrawRequests();
  });
})();