import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const read=p=>fs.readFileSync(new URL('../'+p,import.meta.url),'utf8');
const app=read('app.js'),html=read('karaoke.html'),css=read('xstage-ux.css');
const beginning=app.indexOf('function hasRememberedLogin(){');
const end=app.indexOf('// MIDI owns its own transport clock.',beginning);
assert.ok(beginning>0&&end>beginning,'remembered verified-account functions must exist');
const prefs=new Map(),storage={
  getItem:key=>prefs.get(key)||null,
  setItem:(key,value)=>prefs.set(key,String(value)),
  removeItem:key=>prefs.delete(key)
};
const ctx={localStorage:storage,JSON,String};
vm.runInNewContext(`
 const REMEMBERED_LOGIN_KEY='xstage-remembered-google-login';
 const REMEMBERED_ACCOUNT_KEY='xstage-google-account-hint-v1';
 ${app.slice(beginning,end)}
 globalThis.rememberTest={hasRememberedLogin,rememberedGoogleAccount,rememberVerifiedGoogleAccount,rememberLogin};
`,ctx);
const api=ctx.rememberTest;
assert.equal(api.hasRememberedLogin(),false);
assert.equal(api.rememberedGoogleAccount(),null);
api.rememberVerifiedGoogleAccount({sub:'USER_123',email:'owner@example.com',email_verified:true});
assert.equal(api.hasRememberedLogin(),true);
const remembered=api.rememberedGoogleAccount();
assert.equal(remembered.sub,'USER_123');
assert.equal(remembered.email,'owner@example.com');
const saved=JSON.parse(prefs.get('xstage-google-account-hint-v1'));
assert.deepEqual(Object.keys(saved).sort(),['email','sub'],
  'Long-term storage must contain NO access token, password, or refresh token');
api.rememberVerifiedGoogleAccount({sub:'USER_EVIL',email:'evil@example.com',email_verified:false});
assert.equal(api.rememberedGoogleAccount().sub,'USER_123',
  'Unverified Google account data must not overwrite remembered identity');
api.rememberLogin(false);
assert.equal(api.hasRememberedLogin(),false);
assert.equal(prefs.has('xstage-google-account-hint-v1'),false);
assert.equal(prefs.has('xstage-remembered-google-login'),false);

assert.ok(app.includes('login({remembered:hasRememberedLogin()})'),
  'One-tap explicit reconnect must reuse the remembered account');
assert.ok(app.includes("...(hint?.email?{login_hint:hint.email}:{})"),
  'Remembered reconnect must supply the original verified Google login hint');
assert.ok(app.includes("known?.sub||'',true"),
  'Reconnection must verify immutable Google subject, never switch accounts silently');
assert.ok(app.includes("prompt:'select_account'"),
  'Non-remembered sign-in must still allow the user to choose a Google account');
assert.ok(app.includes("client.requestAccessToken({")&&app.includes("prompt:''"),
  'Token renewal must reuse existing consent when Google permits');
assert.ok(!app.includes('refresh_token:'),
  'Never persist or request a long-lived refresh token from static web JavaScript');
assert.ok(html.includes('id="google-renew"')&&css.includes('.google-renew-button'),
  'Near-expiry renewal must expose a mobile-friendly, explicit button');
const noticeStart=app.indexOf('function updateGoogleRenewNotice(){');
const noticeEnd=app.indexOf("$('google-renew')?.addEventListener",noticeStart);
assert.ok(noticeStart>0&&noticeEnd>noticeStart);
const button={hidden:true,textContent:'',title:''};
const state={token:'temporary-access',tokenExpiresAt:Date.now()+11*60*1000,accountSub:'USER_123'};
const makeNotice=new Function('$','state','androidTvNativeBridgeReady','Date',
 app.slice(noticeStart,noticeEnd)+'\nreturn updateGoogleRenewNotice;');
const update=makeNotice(()=>button,state,()=>false,Date);
update();assert.equal(button.hidden,true,'Do not display renewal action too early');
state.tokenExpiresAt=Date.now()+7*60*1000;update();
assert.equal(button.hidden,false,'Show renewal action before Google access expires');
assert.equal(button.textContent,'ต่ออายุ Google');
state.tokenExpiresAt=Date.now()-10;update();
assert.equal(button.textContent,'เชื่อม Google อีกครั้ง');
state.token='';update();
assert.equal(button.hidden,true,'After reload the sign-in gate, not a stale renew button, is used');
assert.ok(app.includes('if(!document.hidden)updateGoogleRenewNotice();'),
  'Visible tabs must refresh renewal state after sleep/wake');
console.log('PASS: remembered verified Google identity, one-tap reconnect, safe token expiry and renewal without auto OAuth popups');
