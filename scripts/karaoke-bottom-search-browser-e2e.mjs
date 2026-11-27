/* Real Chromium geometry checks for mobile bottom search and upward results.
 * No Google credentials; all HTML/CSS/JS are loaded from the repository. */
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const mime={'.html':'text/html;charset=utf-8','.js':'text/javascript;charset=utf-8',
  '.css':'text/css;charset=utf-8','.svg':'image/svg+xml','.json':'application/json;charset=utf-8',
  '.png':'image/png','.jpg':'image/jpeg','.webp':'image/webp'};
const server=http.createServer((request,response)=>{
  const pathname=decodeURIComponent(new URL(request.url,'http://127.0.0.1').pathname);
  const file=path.resolve(root,'.'+pathname);
  if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){
    response.writeHead(404).end();return;
  }
  response.writeHead(200,{'Content-Type':mime[path.extname(file)]||'application/octet-stream',
    'Cache-Control':'no-store'});
  fs.createReadStream(file).pipe(response);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const url='http://127.0.0.1:'+server.address().port+'/karaoke.html';
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
async function geometry(page){
  return page.evaluate(()=>{
    const stage=document.getElementById('stage');
    const slot=document.querySelector('.stage-search-slot');
    const dock=document.getElementById('pc-search');
    const box=slot.querySelector('.search-box');
    const results=document.getElementById('songs');
    const transport=document.querySelector('.transport-panel');
    const r=node=>{const {top,bottom,left,right,width,height}=node.getBoundingClientRect();
      return {top,bottom,left,right,width,height};};
    return {slot:r(slot),dock:r(dock),box:r(box),results:r(results),transport:r(transport),
      viewport:{width:window.innerWidth,height:window.innerHeight},
      bottomMode:document.body.classList.contains('xstage-mobile-search-bottom'),
      isDirectStageChild:slot.parentElement===stage,
      isToolbarChild:slot.parentElement?.classList.contains('stage-toolbar'),
      isExpanded:dock.classList.contains('pc-expanded'),
      style:getComputedStyle(slot).position,
      dockStyle:getComputedStyle(dock).position,
      direction:getComputedStyle(dock).flexDirection,
      searchCount:document.querySelectorAll('#search').length,
      voiceCount:document.querySelectorAll('#voice-search').length};
  });
}
try{
  for(const [width,height] of [[320,640],[375,667],[390,680],[430,932],[600,800],
                                  [667,375],[844,390],[932,430]]){
    const ctx=await browser.newContext({viewport:{width,height},isMobile:true,hasTouch:true,deviceScaleFactor:1});
    const page=await ctx.newPage();
    await page.goto(url,{waitUntil:'domcontentloaded'});
    await page.waitForFunction(()=>document.body.classList.contains('xstage-mobile-search-bottom'));
    let g=await geometry(page);
    assert.equal(g.searchCount,1,'Keep one canonical search input: '+width);
    assert.equal(g.voiceCount,0,'Voice search must be removed: '+width);
    assert.equal(g.style,'fixed','Mobile dock must attach to viewport bottom: '+JSON.stringify(g));
    assert.equal(g.isDirectStageChild,true,'Search moved out of toolbar: '+width);
    assert.ok(g.slot.width>width*.80&&g.slot.left>=0&&g.slot.right<=width+2,
      'Search must fit phone and landscape notches: '+JSON.stringify(g));
    assert.ok(g.slot.bottom<=height+2&&g.slot.bottom>=height-55,
      'Search must hug safe viewport bottom: '+JSON.stringify(g));
    assert.ok(g.transport.bottom<=g.slot.top+3,
      'Player buttons must sit above bottom search: '+JSON.stringify(g));
    await page.evaluate(()=>{
      const dock=document.getElementById('pc-search');
      const results=document.getElementById('songs');
      dock.classList.add('pc-expanded');
      for(let i=0;i<16;i++){
        const item=document.createElement('div');
        item.className='song-item';
        item.textContent='เพลงทดสอบ '+i;
        item.style.minHeight='43px';
        results.append(item);
      }
    });
    g=await geometry(page);
    assert.equal(g.isExpanded,true);
    assert.equal(g.direction,'column-reverse',
      'Search results must grow upward on mobile: '+width);
    assert.ok(g.dock.top<g.box.top-30&&g.results.height>30,
      'Expanded results must be visible ABOVE the input: '+JSON.stringify(g));
    assert.ok(g.dock.bottom<=height+2&&g.dock.left>=0&&g.dock.right<=width+2,
      'Expanded dropdown must not overflow the screen: '+JSON.stringify(g));
    if(width===390){
      // Exercise production rendering with synthetic private catalog only.
      await page.evaluate(()=>{
        state.token='simulated-token';
        state.songs=Array.from({length:17},(_,i)=>({code:'T'+String(i).padStart(3,'0'),title:'เพลงจำลอง '+i,artist:'ศิลปิน'}));
        const search=document.getElementById('search');
        search.value='เพลงจำลอง';search.dispatchEvent(new Event('input',{bubbles:true}));
      });
      const count=()=>page.locator('#songs .song-item').count();
      assert.equal(await count(),5,'Exactly five initial DOM rows');
      assert.equal(await page.locator('#songs').evaluate(el=>getComputedStyle(el).scrollbarWidth),'none');
      const original=await page.locator('#songs .song-item').first().evaluate(el=>{el.dataset.original='1';return el.id;});
      await page.locator('#songs').evaluate(el=>{
        el.scrollTop=el.scrollHeight;el.dispatchEvent(new Event('scroll'));
      });
      await page.waitForFunction(()=>document.querySelectorAll('#songs .song-item').length>=10);
      assert.equal(await page.locator('#songs .song-item[data-original="1"]').count(),1,'Existing rows must not be rebuilt');
      assert.equal(await page.locator('#songs .song-item').first().getAttribute('id'),original);
      for(let attempt=0;attempt<4&&(await count())<17;attempt++){
        await page.locator('#songs').evaluate(el=>{
          el.scrollTop=el.scrollHeight;el.dispatchEvent(new Event('scroll'));
        });
      }
      assert.equal(await count(),17,'Every match must be reachable, without duplicates');
      await page.locator('#songs').evaluate(el=>el.dispatchEvent(new WheelEvent('wheel',{deltaY:100})));
      assert.equal(await count(),17,'No duplicate page after reaching the end');
      await page.evaluate(()=>{
        const search=document.getElementById('search');
        search.value='T016';search.dispatchEvent(new Event('input',{bubbles:true}));
      });
      assert.equal(await count(),1,'Changing query discards old pages');
      assert.match(await page.locator('#songs .song-item').first().textContent(),/T016/);
      await page.evaluate(()=>{state.token='';state.songs=[];document.getElementById('search').value='';renderSongs();});
      await page.evaluate(()=>{
        document.getElementById('pc-search').classList.remove('pc-expanded');
        document.documentElement.style.setProperty('--xs-search-keyboard-inset','220px');
      });
      const raised=await geometry(page);
      assert.ok(raised.slot.bottom<height-190,
        'Bottom search must lift above the soft keyboard: '+JSON.stringify(raised));
      await page.setViewportSize({width:1024,height:768});
      await page.waitForFunction(()=>!document.body.classList.contains('xstage-mobile-search-bottom'));
      const desktop=await geometry(page);
      assert.equal(desktop.isToolbarChild,true,'Desktop must restore original top search DOM');
      assert.equal(desktop.searchCount,1,'Desktop must retain one search handler');
      assert.ok(desktop.slot.top<180,'Desktop search must return to top: '+JSON.stringify(desktop));
    }
    await ctx.close();
    console.log('PASS: bottom mobile search '+width+'x'+height+' · results rise above input');
  }
}finally{
  await browser.close();
  await new Promise(resolve=>server.close(resolve));
}
console.log('PASS: voice search removed, responsive bottom search, no transport overlap and keyboard safe-area');
