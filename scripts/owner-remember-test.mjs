import fs from 'node:fs';
import assert from 'node:assert/strict';
const read=name=>fs.readFileSync(new URL('../'+name,import.meta.url),'utf8');
const mobile=read('remote.js'),markup=read('remote.html'),host=read('stage-controls.js');

assert.ok(markup.includes('id="owner-logout-mobile"'),'mobile Owner logout must have a visible action');
assert.ok(markup.includes('กลับเป็น Guest'),'logout must clearly distinguish mobile Owner from TV Google logout');
assert.ok(markup.includes('data-admin="logout"'),'existing explicit TV Google logout must remain separate');
assert.ok(mobile.includes('const OWNER_PREF_KEY=')&&mobile.includes('const OWNER_PAIR_KEY='),
  'Owner intent and ephemeral stage pairing are remembered separately');
assert.ok(mobile.includes('if(!validPair(hostId,secret)&&rememberedOwner)'),
  'the mobile remote must restore a valid remembered TV pairing without rescanning');
assert.ok(mobile.includes('client.requestAccessToken({prompt:automatic?'),
  'remembered Owner must attempt Google consent again, not grant itself privileges');
assert.ok(mobile.includes('rememberWrite(OWNER_PREF_KEY,{email:String(data.email||\'\')})'),
  'remember Owner only after receiving a TV-verified Owner role');
assert.ok(mobile.includes("send({type:'owner-signout'})")&&
  mobile.includes('clearRememberedOwner()'),
  'mobile logout removes saved state and instructs TV to revoke Owner');
assert.ok(mobile.includes('function discardOwnerToken()')&&
  mobile.includes("ownerAccessToken='';"),
  'mobile must not persist Google OAuth tokens');
assert.ok(!mobile.includes('localStorage.setItem(OWNER_PREF_KEY,ownerAccessToken)'),
  'Google OAuth tokens must never be saved in localStorage');

const first=host.indexOf('  async function verifyOwner(entry,accessToken){');
const last=host.indexOf('\n  function approveEntry(entry){',first);
assert.ok(first>=0&&last>first,'owner verifier must exist');
const impl=host.slice(first,last);
function harness({account='google-user-1',token='test',responseOk=true,remoteSub='google-user-1',pause=false}={}){
  const messages=[],stages=[],stageSession={};
  const entry={approved:true,conn:{open:true},role:'guest',ownerAuthGeneration:0};
  let resolveFetch;
  const fetch=()=>pause
    ? new Promise(resolve=>{resolveFetch=resolve;})
    : Promise.resolve({ok:responseOk,json:async()=>({sub:remoteSub,email:'owner@example.com'})});
  const verify=new Function('state','ui','send','snapshot','status','fetch','session',
    impl+'\nreturn verifyOwner;')(
      {accountSub:account},{account:{textContent:'owner@example.com'}},
      (conn,message)=>messages.push(message),()=>({type:'status',role:entry.role}),
      text=>stages.push(text),fetch,stageSession);
  return {verify:()=>verify(entry,token),entry,messages,stages,
    signOut:()=>{entry.ownerAuthGeneration++;entry.role='guest';},
    resolve:()=>resolveFetch?.({ok:true,json:async()=>({sub:remoteSub,email:'owner@example.com'})})};
}
{
  const x=harness();
  await x.verify();
  assert.equal(x.entry.role,'owner','only matching Google sub gets Owner permissions');
  assert.equal(x.messages[0].role,'owner');
}
{
  const x=harness({remoteSub:'different-user'});
  await x.verify();
  assert.equal(x.entry.role,'guest','wrong Google account must remain Guest');
  assert.equal(x.messages[0].role,'guest');
}
{
  const x=harness({responseOk:false});
  await x.verify();
  assert.equal(x.entry.role,'guest','rejected/expired OAuth token must remain Guest');
}
{
  const x=harness({pause:true});
  const pending=x.verify();
  x.signOut();
  x.resolve();
  await pending;
  assert.equal(x.entry.role,'guest','pending Google response cannot re-enable Owner after logout');
  assert.equal(x.messages.length,0,'cancelled verification cannot emit a late Owner message');
}
const logoutStart=host.indexOf("if(msg.type==='owner-signout'){");
const logoutEnd=host.indexOf("if(msg.type==='search'){",logoutStart);
assert.ok(logoutStart>=0&&logoutEnd>logoutStart,'TV must handle separate mobile-only logout');
const logout=host.slice(logoutStart,logoutEnd);
const entry={role:'owner',ownerAuthGeneration:4};
const messages=[],channel={open:true};
const demote=new Function('msg','entry','send','conn','snapshot',logout+'\nreturn entry.role;');
const role=demote({type:'owner-signout'},entry,(_conn,m)=>messages.push(m),channel,()=>({type:'status',role:entry.role}));
assert.equal(role,undefined,'Owner sign-out must finish handling without invoking later commands');
assert.equal(entry.role,'guest','TV must demote to Guest immediately');
assert.equal(entry.ownerAuthGeneration,5,'TV must invalidate any in-flight Owner verification');
assert.equal(messages[0].signedOut,true,'TV must acknowledge mobile sign-out');
assert.equal(messages[1].role,'guest','TV must advertise reduced permissions');
console.log('Mobile Owner remember/logout: verified role, wrong account, rejected token, logout race and host revocation passed');
