import fs from 'node:fs';
import assert from 'node:assert/strict';

// Behavioral regression of the host/mobile song-request contract.
// No browser, PeerJS service, Google token or private Drive access is needed.
const source=fs.readFileSync(new URL('../stage-controls.js',import.meta.url),'utf8');
const first=source.indexOf('  function acceptRequest(conn,msg,limits){');
const last=source.indexOf('\n  function handleControl(',first);
assert.ok(first>=0&&last>first,'host request handler must exist');
const implementation=source.slice(first,last);

function harness({active=false,token=true,queueSize=0,playableSong=true,native=false}={}){
  const messages=[],activity=[],limits=[];
  const state={
    token:token?'test-token':null,
    songs:[{code:'001',title:'ทดสอบคำขอเพลง',artist:'ทดสอบ'}],
    queue:Array.from({length:queueSize},()=>({title:'queued'})),
    nativeCatalog:native?{capability:'native-active'}:null,
    loading:false,
    current:active?{title:'currently playing'}:null
  };
  const ui={player:{src:active?'blob:active':'',ended:false,paused:!active,currentTime:0}};
  let playCount=0,queueAdds=0;
  const accept=new Function('state','ui','send','playable','addToQueue','playNext','activity','redrawActivity','broadcastStatus','catalogSongById',
    'let sequence=0;'+implementation+';return acceptRequest')(
      state,ui,(_conn,message)=>messages.push(message),
      ()=>playableSong,
      song=>{state.queue.push(song);queueAdds++;},
      ()=>{state.queue.shift();playCount++;},
      activity,()=>{},()=>{},id=>id==='stable-42'?{webSongId:id,title:'Native song'}:null
    );
  return {
    request:(message={},conn={})=>accept(conn, {requestId:42,index:0,singer:'Guest',...message},limits),
    get messages(){return messages;},
    get queueAdds(){return queueAdds;},
    get playCount(){return playCount;},
    get activity(){return activity;}
  };
}

{
  const test=harness();
  test.request();
  assert.equal(test.playCount,1,'empty queue starts playback');
  assert.equal(test.messages[0].type,'request-received');
  assert.equal(test.messages[0].result,'starting','request is not acknowledged as playing before media starts');
  assert.equal(test.messages[0].requestId,42,'receipt must match the phone request');
}
{
  const test=harness({active:true});
  test.request();
  assert.equal(test.playCount,0,'active track must not be interrupted');
  assert.equal(test.messages[0].result,'queued');
}
{
  const test=harness();
  test.request({index:200,requestId:43});
  assert.equal(test.messages[0].type,'request-error');
  assert.equal(test.messages[0].requestId,43,'invalid song must receive an error ACK');
}
{
  const test=harness({token:false});
  test.request();
  assert.equal(test.messages[0].type,'request-error','not-ready library must answer');
  assert.equal(test.playCount,0);
}
{
  const test=harness({queueSize:150});
  test.request();
  assert.equal(test.messages[0].type,'request-error','queue capacity guard');
}
{
  const test=harness({playableSong:false});
  test.request();
  assert.equal(test.messages[0].type,'request-error','missing audio guard');
}
{
  const test=harness({active:true});
  for(let n=0;n<9;n++)test.request({requestId:n});
  assert.equal(test.messages[8].type,'request-error','ninth request in one minute must be rate-limited');
  assert.equal(test.messages[8].requestId,8,'rate limit must identify the request');
}

{
  const test=harness({queueSize:1,active:false});
  test.request();
  assert.equal(test.playCount,0,'a second request only joins the existing queue, even when stage is idle');
  assert.equal(test.messages[0].result,'queued','queued requests are not claimed to be playing');
}
{
  const test=harness({queueSize:1,active:true});
  test.request();
  assert.equal(test.playCount,0,'incoming request must never interrupt a playing song');
  assert.equal(test.queueAdds,1);
}
const player=fs.readFileSync(new URL('../app.js',import.meta.url),'utf8');
const remote=fs.readFileSync(new URL('../remote.js',import.meta.url),'utf8');
assert.ok(player.includes('publishPlaybackStatus(\'loading\'')&&player.includes('publishPlaybackStatus(\'playing\'')&&player.includes('publishPlaybackStatus(\'error\''),
  'host playback must report loading, actual playing, and Drive/media failures');
assert.ok(source.includes("type:'playback-status'")&&remote.includes("data.type==='playback-status'"),
  'mobile remote must receive actual TV playback feedback');

 // Host reconnect: never create a second retry timer, preserve session, and stop on replacement.
 const start=source.indexOf('  function scheduleHostReconnect(active){');
 const end=source.indexOf("  window.addEventListener('online'",start);
 assert.ok(start>=0&&end>start);
 const timers=[],messages=[],net={onLine:true};
 let reconnects=0;
 const active={peer:{disconnected:true,destroyed:false,reconnect(){reconnects++;}},reconnectAttempts:0,reconnectTimer:0};
 const hostRetry=new Function('session','navigator','status','setTimeout',
   source.slice(start,end)+';return {scheduleHostReconnect,replace:()=>{session=null;}}')(
   active,net,message=>messages.push(message),(fn,delay)=>{timers.push({fn,delay});return timers.length;});
 hostRetry.scheduleHostReconnect(active);hostRetry.scheduleHostReconnect(active);
 assert.equal(timers.length,1,'duplicate disconnect events must share one timer');
 assert.equal(timers[0].delay,1000);
 timers[0].fn();assert.equal(reconnects,1);
 net.onLine=false;hostRetry.scheduleHostReconnect(active);
 assert.equal(timers.length,1,'offline state must not start a peer reconnect');
 net.onLine=true;hostRetry.scheduleHostReconnect(active);
 assert.equal(timers[1].delay,2000);
 hostRetry.replace();timers[1].fn();assert.equal(reconnects,1,'old session timer must not reconnect after replacement');
 assert.ok(source.includes('if(generation!==sessionGeneration)return;'),'stale QR initialization must stop');
 assert.ok(remote.includes('if(connecting&&!force)return;')&&remote.includes('peer=null;conn=null;'),
   'mobile remote must suppress overlapping connect attempts and ignore retired peer callbacks');

console.log('X-Stage mobile remote request and reconnect contract passed');

{
  const t=harness({native:true,active:true});
  t.request({index:123},{xstageNativeResults:{capability:'native-active',items:new Map([[123,'stable-42']])}});
  assert.equal(t.messages[0].type,'request-received');
  assert.equal(t.messages[0].title,'Native song');
  t.request({index:123},{xstageNativeResults:{capability:'stale',items:new Map([[123,'stable-42']])}});
  assert.equal(t.messages[1].type,'request-error');
  t.request({index:999},{xstageNativeResults:{capability:'native-active',items:new Map([[123,'stable-42']])}});
  assert.equal(t.messages[2].type,'request-error');
}
