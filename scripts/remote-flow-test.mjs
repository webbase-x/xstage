import fs from 'node:fs';
import assert from 'node:assert/strict';

// Behavioral regression of the host/mobile song-request contract.
// No browser, PeerJS service, Google token or private Drive access is needed.
const source=fs.readFileSync(new URL('../stage-controls.js',import.meta.url),'utf8');
const first=source.indexOf('  function acceptRequest(conn,msg,limits){');
const last=source.indexOf('\n  function handleControl(',first);
assert.ok(first>=0&&last>first,'host request handler must exist');
const implementation=source.slice(first,last);

function harness({active=false,token=true,queueSize=0,playableSong=true}={}){
  const messages=[],activity=[],limits=[];
  const state={
    token:token?'test-token':null,
    songs:[{code:'001',title:'ทดสอบคำขอเพลง',artist:'ทดสอบ'}],
    queue:Array.from({length:queueSize},()=>({title:'queued'})),
    loading:false,
    current:active?{title:'currently playing'}:null
  };
  const ui={player:{src:active?'blob:active':'',ended:false,paused:!active,currentTime:0}};
  let playCount=0,queueAdds=0;
  const accept=new Function('state','ui','send','playable','addToQueue','playNext','activity','redrawActivity','broadcastStatus',
    'let sequence=0;'+implementation+';return acceptRequest')(
      state,ui,(_conn,message)=>messages.push(message),
      ()=>playableSong,
      song=>{state.queue.push(song);queueAdds++;},
      ()=>{state.queue.shift();playCount++;},
      activity,()=>{},()=>{}
    );
  return {
    request:(message={})=>accept({}, {requestId:42,index:0,singer:'Guest',...message},limits),
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
  assert.equal(test.messages[0].result,'playing');
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

console.log('X-Stage mobile remote request contract: 7 behavioral cases passed');
