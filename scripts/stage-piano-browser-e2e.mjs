/* Browser-level layout smoke for the on-stage piano: no Google account needed. */
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const types={'.html':'text/html;charset=utf-8','.js':'application/javascript;charset=utf-8',
  '.css':'text/css;charset=utf-8','.json':'application/json;charset=utf-8',
  '.svg':'image/svg+xml','.png':'image/png','.jpg':'image/jpeg','.ico':'image/x-icon'};
const server=http.createServer((req,res)=>{
  const name=decodeURIComponent(new URL(req.url,'http://localhost').pathname);
  const target=path.resolve(root,'.'+name);
  if(!target.startsWith(root+path.sep)&&target!==root){res.writeHead(403).end();return;}
  const file=fs.existsSync(target)&&fs.statSync(target).isDirectory()?path.join(target,'index.html'):target;
  if(!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404).end();return;}
  res.writeHead(200,{'Content-Type':types[path.extname(file)]||'application/octet-stream',
    'Cache-Control':'no-store'});
  fs.createReadStream(file).pipe(res);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
try{
  const page=await browser.newPage({viewport:{width:1280,height:720}});
  const exceptions=[];
  page.on('pageerror',error=>exceptions.push(error.message));
  await page.route('https://accounts.google.com/**',route=>route.fulfill({
    status:200,contentType:'application/javascript',body:''}));
  await page.route('https://www.googleapis.com/**',route=>route.fulfill({
    status:200,contentType:'application/json',body:'{}'}));
  await page.goto('http://127.0.0.1:'+server.address().port+'/',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>window.XStagePianoCore?.FIRST===48,{timeout:15000});
  // This isolated layout smoke has no Google account. Dismiss the login gate
  // deliberately; functional account authorization remains tested separately.
  await page.evaluate(()=>{
    const gate=document.getElementById('gate');
    if(gate){gate.hidden=true;gate.style.pointerEvents='none';}
  });
  const open=page.locator('#toggle-piano');
  await open.click();
  assert.equal(await page.locator('#stage-piano').isVisible(),true);
  assert.equal(await page.locator('#stage-piano-keys button').count(),49);
  let geometry=await page.evaluate(()=>{
    const piano=document.querySelector('#stage-piano').getBoundingClientRect();
    const transport=document.querySelector('.transport-panel').getBoundingClientRect();
    return {left:piano.left,right:piano.right,bottom:piano.bottom,
      transportTop:transport.top,height:piano.height};
  });
  assert.ok(geometry.left>=0&&geometry.right<=1280,'Desktop piano must fit stage horizontally');
  assert.ok(geometry.bottom<=geometry.transportTop+2,'Desktop piano must sit above playback bar');
  // Device advisor and 16-channel MIDI mixer are interactive on the real page.
  await page.waitForFunction(()=>window.XStageAudioAdvisor &&
    document.querySelectorAll('#xstage-midi-channels [data-midi-channel]').length===16);
  await page.locator('#toggle-audio-tools').click();
  assert.equal(await page.locator('#xstage-audio-tools').isVisible(),true);
  assert.equal(await page.locator('#xstage-midi-transpose option').count(),25);
  await page.locator('#xstage-midi-settings summary').click();
  await page.locator('#xstage-midi-transpose').selectOption('3');
  await page.locator('[data-midi-channel="0"] [data-action="mute"]').check();
  await page.locator('[data-midi-channel="1"] [data-action="solo"]').check();
  await page.locator('[data-midi-channel="1"] [data-action="gain"]').evaluate(element=>{
    element.value='60';element.dispatchEvent(new Event('input',{bubbles:true}));
  });
  const mix=await page.evaluate(()=>window.XStageAudioAdvisor.getMidiSettings());
  assert.equal(mix.transpose,3);
  assert.equal(mix.channels[0].mute,true);
  assert.equal(mix.channels[1].solo,true);
  assert.equal(mix.channels[1].gain,.6);
  await page.evaluate(()=>window.dispatchEvent(new CustomEvent('xstage:fonts-updated',{
    detail:{files:[{id:'small',name:'Small.sf2',size:24*1048576},
      {id:'oversize',name:'TooLarge.sf3',size:280*1048576}]}
  })));
  assert.equal(await page.locator('#xstage-font-file-list .xstage-font-row').count(),2);
  assert.equal(await page.locator('#xstage-font-file-list .xstage-font-row').last().getAttribute('data-level'),'blocked');
  await page.locator('#xstage-midi-reset').click();
  const reset=await page.evaluate(()=>window.XStageAudioAdvisor.getMidiSettings());
  assert.equal(reset.transpose,0);
  assert.ok(reset.channels.every(c=>c.gain===1&&!c.mute&&!c.solo));
  await page.locator('#xstage-audio-close').click();
  assert.equal(await page.locator('#xstage-audio-tools').isVisible(),false);
  // Change to mobile viewport and use the actual onstage mobile menu control.
  await page.setViewportSize({width:390,height:844});
  await page.locator('#stage-piano-close').click();
  // The no-account smoke intentionally has stage menu controls gated. Invoke
  // its real mobile piano button handler without bypassing production login.
  await page.evaluate(()=>{
    const menu=document.getElementById('mobile-stage-menu');
    if(menu)menu.hidden=false;
    document.getElementById('mobile-piano-toggle').click();
    if(menu)menu.hidden=true;
  });
  assert.equal(await page.locator('#stage-piano').isVisible(),true);
  geometry=await page.evaluate(()=>{
    const piano=document.querySelector('#stage-piano').getBoundingClientRect();
    const transport=document.querySelector('.transport-panel').getBoundingClientRect();
    const viewport=document.querySelector('#stage-piano-viewport');
    return {left:piano.left,right:piano.right,bottom:piano.bottom,
      transportTop:transport.top,scrollWidth:viewport.scrollWidth,width:viewport.clientWidth};
  });
  assert.ok(geometry.left>=0&&geometry.right<=390,'Phone piano must not overflow screen');
  assert.ok(geometry.bottom<=geometry.transportTop+2,'Phone piano must not obscure playback controls');
  assert.ok(geometry.scrollWidth>geometry.width,'Phone must allow horizontally scrolling keys');
  // Android TV remains intentionally a clean display-only stage.
  await page.evaluate(()=>document.body.classList.add('xstage-native-tv'));
  assert.equal(await page.locator('#stage-piano').isVisible(),false);
  assert.ok(!exceptions.some(x=>/stage-piano|XStagePiano/.test(x)),
    'No on-stage piano runtime errors: '+exceptions.join('; '));
  console.log('PASS: Chromium stage piano fits desktop/mobile and stays hidden on native TV');
}finally{
  await browser.close();
  await new Promise(resolve=>server.close(resolve));
}
