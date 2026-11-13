import http from 'node:http';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const root = process.cwd();
const contentTypes = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8', '.svg':'image/svg+xml',
  '.webmanifest':'application/manifest+json' };
const server = http.createServer(async (req, res) => {
  const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
  const absolute = path.resolve(root, '.' + pathname);
  if (!absolute.startsWith(root + path.sep)) {
    res.writeHead(403); res.end(); return;
  }
  try {
    const data = await fsp.readFile(absolute);
    res.writeHead(200, {'Content-Type':contentTypes[path.extname(absolute)] || 'application/octet-stream'});
    res.end(data);
  } catch {
    res.writeHead(404); res.end('Not found');
  }
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const port = server.address().port;

function sineWaveWAV() {
  const samples = 22050, sampleRate = 22050, bytes = 44 + samples * 2;
  const buffer = Buffer.alloc(bytes);
  buffer.write('RIFF', 0); buffer.writeUInt32LE(bytes - 8, 4); buffer.write('WAVE', 8);
  buffer.write('fmt ', 12); buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20); buffer.writeUInt16LE(1, 22);
  buffer.writeUInt32LE(sampleRate, 24); buffer.writeUInt32LE(sampleRate * 2, 28);
  buffer.writeUInt16LE(2, 32); buffer.writeUInt16LE(16, 34);
  buffer.write('data', 36); buffer.writeUInt32LE(samples * 2, 40);
  for (let i = 0; i < samples; i++) {
    const amplitude = Math.sin(2 * Math.PI * 440 * i / sampleRate) * 9000;
    buffer.writeInt16LE(Math.round(amplitude), 44 + i * 2);
  }
  return buffer;
}
let browser;
try {
  browser = await chromium.launch({headless:true, args:['--no-sandbox']});
  const page = await browser.newPage({acceptDownloads:true});
  page.on('pageerror', (error) => console.error('BROWSER PAGE ERROR:', error.message));
  page.on('console', (m) => { if (m.type() === 'error') console.error('BROWSER CONSOLE:', m.text()); });
  page.on('requestfailed', (request) => console.error('NETWORK FAIL:', request.url(), request.failure()?.errorText));
  await page.goto('http://127.0.0.1:' + port + '/studio/web.html', {waitUntil:'load'});
  await page.setInputFiles('#file-input', [{
    name:'demo.wav', mimeType:'audio/wav', buffer:sineWaveWAV()
  }]);
  await page.waitForFunction(() => document.querySelector('#file-count').textContent.includes('1'));
  // Songs often contain multiple audio source formats. Both must remain
  // selectable instead of silently replacing the previous format.
  await page.setInputFiles('#file-input', [{
    name:'demo.mp3', mimeType:'audio/mpeg', buffer:Buffer.from('ID3dummy-alternate-source')
  }]);
  await page.locator('#song-list select[data-audio-select]').waitFor();
  assert.equal(await page.locator('#song-list select[data-audio-select]').inputValue(), 'wav');
  await page.locator('#song-list select[data-audio-select]').selectOption('mp3');
  assert.equal(await page.locator('#song-list select[data-audio-select]').inputValue(), 'mp3');
  await page.locator('#song-list select[data-audio-select]').selectOption('wav');
  await page.locator('#song-list tr').first().click();
  await page.fill('#lyrics-text', '[00:00.10]ทดสอบเนื้อร้อง\n[00:00.40]บรรทัดถัดไป');
  await page.click('#save-lyrics');
  await page.click('#load-engine');
  await page.waitForFunction(() => /พร้อมประมวลผล|โหลด Engine ไม่สำเร็จ/.test(document.querySelector('#engine-caption').textContent), null, {timeout:45000});
  assert.match(await page.locator('#engine-caption').innerText(), /พร้อมประมวลผล/, 'Web Engine must finish loading successfully');
  await page.click('#build');
  // Browser conversions are asynchronous. A later automatic download may be
  // blocked as lacking user activation, so production retains the ZIP and
  // exposes a real click to download it.
  await page.locator('#download-result:visible').waitFor({timeout:120000});
  await assert.equal(await page.locator('#download-result').isEnabled(), true,
    'successful Web conversion must leave an actionable download button');
  const downloadPromise = page.waitForEvent('download', {timeout:30000});
  await page.click('#download-result');
  const download = await downloadPromise;
  const savedFile = await download.path();
  assert.ok(savedFile, 'a browser ZIP download must have a local path');
  const archive = await fsp.readFile(savedFile);
  assert.ok(archive.includes(Buffer.from('demo.m4a')), 'archive must contain M4A');
  assert.ok(archive.includes(Buffer.from('demo.lrc')), 'archive must contain companion LRC');
  assert.ok(archive.includes(Buffer.from('ftyp')), 'M4A must contain ISO BMFF file type signature');
  assert.ok(archive.includes(Buffer.from('ทดสอบเนื้อร้อง')), 'LRC must contain editable timed lyric');
  console.log('PASS: Chromium loaded WebAssembly Engine and converted demo.wav to M4A + LRC locally.');

  // The PC Ready package and authenticated PC Web Control share this UI.
  // Simulate its local API; exercise all four visible steps in Chromium.
  const pc = await browser.newPage({acceptDownloads:true});
  const pcErrors = [];
  pc.on('pageerror', (error) => pcErrors.push(error.message));
  const settings = {
    source: 'C:\\XStage\\Songs', workspace: 'C:\\XStage\\Created',
    soundfont: 'C:\\XStage\\GeneralUser-GS.sf2', midi_preset: 'balanced',
    mode: 'original', download: 'C:\\XStage\\Downloads', oauth: ''
  };
  let fakeGoogleConnected = false;
  const importedAI = new Map();
  let removedAIRequests=0;
  let simulatedJob = {id:'',kind:'',state:'idle',stage:'พร้อม',detail:'',
                      completed:0,total:0,logs:[]};
  const uploadRequests = [];
  let lyricBulkReady=false,bulkBackup=null;
  const bulkGroup={id:'intro-verified-1234',position:'first',
    label:'บรรทัดแรก',text:'[X-Stage Karaoke]',count:3,
    examples:[{code:'001',title:'เพลงหนึ่ง',artist:'XStage'},
              {code:'002',title:'เพลงสอง',artist:'XStage'}]};
  const list = [
    {id: 1, title: 'เสียงทดสอบ 1', artist: 'XStage', code: 'TEST001', kind: 'MID', size: 12000, status: 'ready'},
    {id: 2, title: 'เสียงทดสอบ 2', artist: 'XStage', code: 'TEST002', kind: 'MP3', size: 32000, status: 'ready'}
  ];
  await pc.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === '/api/live-stream') {
      await route.fulfill({status:200,contentType:'audio/mpeg',body:Buffer.from('ID3')});
      return;
    }
    let response = {};
    if (url.pathname === '/api/status') {
      response = {
        version:'0.3.5', build:305,
        preferences:settings, soundfonts:[settings.soundfont],
        presets:[{value:'balanced',label:'สมดุล'}],
        google:{configured:true,connected:fakeGoogleConnected,
                email:fakeGoogleConnected?'test@example.invalid':'',
                config_source:'bundled'},
        job:simulatedJob,
        update:{status:'unavailable'}
      };
    } else if (url.pathname === '/api/songs') {
      response = {rows:list,total:list.length};
    } else if (url.pathname === '/api/preview-lyrics') {
      const id = Number(url.searchParams.get('id'));
      response = id === 1 ? {
        id, status:'found', source:'NCN',
        message:'พบเนื้อร้องจากต้นฉบับ NCN 2 บรรทัด',
        lines:[{startTime:0,endTime:2,text:'เสียงทดสอบต้นฉบับ'},
               {startTime:2,endTime:5,text:'บรรทัดที่สอง'}],
        requiresReview:false,aiAvailable:false
      } : {
        id,status:'missing',source:'ไม่พบเนื้อร้อง',
        message:'ยังไม่มี LRC หรือไฟล์เนื้อร้อง MIDI',lines:[],
        aiEligible:true,aiAvailable:true,requiresReview:false
      };
    } else if (url.pathname === '/api/preview-sources') {
      response = {
        id:Number(url.searchParams.get('id')),
        options:[{value:'auto',kind:'play',label:'ทดสอบเสียงต้นฉบับ'},
                 {value:'midi:1',kind:'play',label:'ทดลองฟัง MID'}],
        components:[{type:'Song · MIDI',name:'TEST001.mid',found:true,required:true},
                    {type:'Lyrics · LYR',name:'TEST001.lyr',found:true,required:true},
                    {type:'Cursor · CUR',name:'TEST001.cur',found:true,required:true}],
        timedLyricsReady:true, proofMessage:'พบต้นฉบับครบสามส่วน'
      };
    } else if (url.pathname === '/api/lyric-groups') {
      const position=url.searchParams.get('position')||'first';
      const groups=lyricBulkReady&&position==='first'?[bulkGroup]:[];
      response={rows:groups.map(({id,position,text,count})=>({id,position,text,count})),
                total:groups.length,songs:3,inspected:3,withoutLyrics:0,skippedInvalid:0};
    } else if (url.pathname === '/api/lyric-groups-preview') {
      response=bulkGroup;
    } else if (url.pathname === '/api/lyric-groups-backup') {
      response={latest:bulkBackup};
    } else if (url.pathname === '/api/vocal-songs') {
      const rows=[...importedAI.values()];
      response = {rows,total:rows.length};
    } else if (url.pathname === '/api/vocal-import') {
      const song={id:-1,title:'เพลง AI นำเข้า',artist:'นักร้องทดลอง',
                  code:'AINEW',kind:'MP3',size:10000,status:'ai-import'};
      importedAI.set(song.id,song);
      response = {added:1,skipped:0,total:importedAI.size,errors:[],song,
                  message:'นำเข้าเพลงใหม่ 1 เพลง'};
    } else if (url.pathname === '/api/vocal-remove') {
      const id=request.postDataJSON()?.id;
      if(importedAI.delete(id)){
        removedAIRequests++;
        response={ok:true,message:'นำเพลงออกจากรายการ AI แล้ว · ไม่ลบไฟล์ต้นฉบับหรือร่างเนื้อร้อง'};
      } else {
        await route.fulfill({status:400,contentType:'application/json',
          body:JSON.stringify({error:'ไม่พบรายการเพลงที่นำเข้าในเมนู AI'})});
        return;
      }
    } else if (url.pathname === '/api/ai-lyrics-draft') {
      response = {id:-1,title:'เพลง AI นำเข้า',artist:'นักร้องทดลอง',code:'AINEW',
                  available:true,hasDraft:true,approvedLrc:'',
                  draft:{source:'AI_DRAFT_UNVERIFIED',
                         rawLrc:'[00:00.10]ท่อนแรก AI\n[00:00.50]ท่อนที่สอง AI',
                         lines:[{startTime:0.1,endTime:0.5,text:'ท่อนแรก AI'},
                                {startTime:0.5,endTime:1,text:'ท่อนที่สอง AI'}]}};
    } else if (url.pathname === '/api/ai-lyrics-approve') {
      response = {ok:true,lines:2,message:'บันทึก LRC ที่ผู้ใช้ตรวจแก้แล้ว'};
    } else if (url.pathname === '/api/songs/ids') {
      response = {ids:list.map((song) => song.id)};
    } else if (url.pathname === '/api/config') {
      Object.assign(settings, request.postDataJSON() || {});
      response = {preferences:settings,soundfonts:[settings.soundfont]};
    } else if (url.pathname === '/api/live-preview') {
      response = {ticket:'one-time-demo-ticket', stream_id:'demo-stream-id', title:'เสียงทดสอบ 2',
        has_backing:true, has_midi:true, mixed:true,
        message:'กำลังเล่นดนตรีกับ SoundFont ผสมกันแบบสตรีมสด'};
    } else if (url.pathname === '/api/estimate') {
      response = {songs:1,bytes:12000,enoughDisk:true,warning:false};
    } else if (url.pathname === '/api/code-registry') {
      response = {pcSongs:2,driveSongs:1,onlineVerified:true,localCodeConflicts:1,
        message:'ตรวจครบ PC 2 และ Google Drive 1 เพลง · ต้องปรับรหัสในคลัง PC 1 รายการ',
        sampleRemaps:[{oldCode:'TEST001',newCode:'000001',title:'เพลงใหม่'}]};
    } else if (url.pathname === '/api/environment') {
      response = {'Bundled FFmpeg':true, 'Bundled SoundFont':true};
    } else if (url.pathname === '/api/jobs') {
      const action=request.postDataJSON()?.action;
      if(action==='lyric-groups-scan')lyricBulkReady=true;
      if(action==='lyric-groups-replace'){
        bulkBackup={id:'20261113T153000000000Z-a1b2c3d4',position:'first',
          oldText:bulkGroup.text,newText:'[X-Stage Karaoke Online]',
          songs:3,createdAt:'2026-11-13T15:30:00+07:00'};
        lyricBulkReady=false;
      }
      if(action==='lyric-groups-undo')bulkBackup=null;
      if (request.postDataJSON()?.action === 'login') fakeGoogleConnected = true;
      if (request.postDataJSON()?.action === 'upload') uploadRequests.push(request.postDataJSON());
      response = {id:'pc-wizard-smoke-job'};
    }
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(response)});
  });
  pc.on('dialog', async (dialog) => dialog.accept());
  await pc.goto('http://127.0.0.1:' + port + '/studio/index.html#auth=test-session-token', {waitUntil:'load'});
  await pc.waitForFunction(() => document.getElementById('catalog-total')?.textContent.includes('2'));
  assert.match(await pc.locator('#google-config-state').innerText(), /ตั้งค่าแล้ว/,
    'Bundled public OAuth Client must show ready for login, not Not Ready');
  assert.match(await pc.locator('#google-badge').innerText(), /พร้อมให้ลงชื่อเข้าใช้/,
    'Not signed in must not be confused with missing OAuth config');
  assert.equal(await pc.locator('.brand-mark img').isVisible(), true, 'PC brand icon must render');
  await pc.waitForFunction(() => {
    const icon = document.querySelector('.brand-mark img');
    return Boolean(icon && icon.complete && icon.naturalWidth > 0);
  });
  assert.equal(await pc.locator('link[rel="icon"]').getAttribute('href'), './app-icon.svg');
  assert.equal(await pc.locator('#create-stage-1').isVisible(), true, 'step 1 should be visible initially');
  await pc.click('#verify-code-registry');
  await pc.waitForFunction(() => document.querySelector('#code-registry-state')?.textContent.includes('TEST001'));
  assert.match(await pc.locator('#code-registry-state').innerText(), /000001/,
    'Two-source code-registry preview must show the proposed non-colliding code');
  assert.equal(await pc.locator('#create-stage-2').isVisible(), false, 'step 2 should be hidden initially');
  await pc.click('#create-step-next');
  assert.equal(await pc.locator('#create-stage-2').isVisible(), true, 'step 2 should open');
  await pc.locator('#song-rows tr[data-id="1"]').click();
  await pc.click('#create-step-next');
  assert.equal(await pc.locator('#create-stage-3').isVisible(), true, 'step 3 should open');
  assert.equal(await pc.locator('#create-stage-3 #create-soundfont').isVisible(), true, 'SoundFont must be within step 3');
  assert.equal(await pc.locator('#create-stage-3 #preview-audio').isVisible(), true, 'Preview player must be in the same SoundFont step');
  await pc.waitForFunction(() => document.getElementById('preview-lyrics-source')?.textContent.includes('NCN'));
  assert.match(await pc.locator('#preview-lyrics-lines').innerText(), /เสียงทดสอบต้นฉบับ/,
    'Preview must prove source NCN has real karaoke lyrics');
  assert.equal(await pc.locator('#preview-song-search').isVisible(), true, 'Preview search must be visible in step 3');
  await pc.locator('#preview-song-search').fill('เสียงทดสอบ');
  await pc.locator('#preview-search-results [data-preview-id="2"]').waitFor();
  const previewRequest = pc.waitForRequest((req) => {
    try { return new URL(req.url()).pathname === '/api/live-preview' &&
      req.postDataJSON()?.id === 2; } catch { return false; }
  });
  await pc.locator('#preview-search-results [data-preview-id="2"]').click();
  await previewRequest;
  await pc.waitForFunction(() => document.getElementById('preview-audio')?.src.includes('/api/live-stream'));
  await pc.waitForFunction(() => document.getElementById('preview-lyrics-source')?.textContent.includes('ไม่พบเนื้อร้อง'));
  assert.match(await pc.locator('#preview-lyrics-lines').innerText(), /ไม่พบเนื้อร้อง/);
  assert.equal(await pc.locator('#preview-ai-transcribe').isEnabled(), true,
    'When vocals exist and offline ASR is available show optional AI draft action');
  assert.match(await pc.locator('#preview-selected').innerText(), /เสียงทดสอบ 2/);
  const liveChange = pc.waitForRequest((req) => {
    try { return new URL(req.url()).pathname === '/api/live-control' &&
      req.postDataJSON()?.synth_volume === 0 &&
      req.postDataJSON()?.music_volume === 0.8; }
    catch { return false; }
  });
  await pc.locator('#preview-sf-volume').evaluate(el => {
    el.value = '0';
    el.dispatchEvent(new Event('input',{bubbles:true}));
  });
  await liveChange;
  assert.equal(await pc.locator('#preview-sf-volume-label').innerText(), '0%');
  assert.equal(await pc.locator('#preview-audio').getAttribute('src'),
    'http://127.0.0.1:' + port + '/api/live-stream?ticket=one-time-demo-ticket',
    'Realtime mixer changes must not start a new stream or reset play position');
  await pc.click('#preview-stop-button');
  assert.equal(await pc.locator('#preview-audio').getAttribute('src'), null, 'Stop must release live stream');
  await pc.waitForFunction(() => !document.getElementById('create-step-next').disabled);
  await pc.click('#create-step-next');
  assert.equal(await pc.locator('#create-stage-4').isVisible(), true, 'step 4 should open');
  assert.match(await pc.locator('#review-song-count').innerText(), /1/, 'review must reflect selected song count');
  assert.match(await pc.locator('#review-soundfont').innerText(), /GeneralUser-GS/, 'review must reflect selected SoundFont');
  await pc.click('#build-button');
  await pc.locator('#studio-confirm-dialog[open]').waitFor();
  assert.equal(await pc.locator('#studio-confirm-title').innerText(), 'ยืนยันเริ่มสร้างเพลง');
  const fullBuild = pc.waitForRequest((req) => {
    try { return new URL(req.url()).pathname === '/api/jobs' &&
      req.postDataJSON()?.action === 'build' && req.postDataJSON()?.audio_only === false; }
    catch { return false; }
  });
  await pc.click('#studio-confirm-ok');
  await fullBuild;
  await pc.waitForFunction(() => document.getElementById('create-build-feedback-title')?.textContent.includes('รับคำสั่ง'));
  assert.match(await pc.locator('#create-build-feedback-detail').innerText(), /pc-wizard-smoke-job/);

  await pc.click('#build-audio-button');
  await pc.locator('#studio-confirm-dialog[open]').waitFor();
  assert.match(await pc.locator('#studio-confirm-message').innerText(), /M4A อย่างเดียว/);
  const audioBuild = pc.waitForRequest((req) => {
    try { return new URL(req.url()).pathname === '/api/jobs' &&
      req.postDataJSON()?.action === 'build' && req.postDataJSON()?.audio_only === true; }
    catch { return false; }
  });
  await pc.click('#studio-confirm-ok');
  await audioBuild;
  // Grouped opening/closing text editor operates independently per line
  // position and never sends any upload request without the owner's action.
  await pc.click('.nav-button[data-tab="lyric-head-tail"]');
  assert.equal(await pc.locator('#tab-lyric-head-tail').isVisible(),true);
  const scanJob=pc.waitForRequest(req=>{
    try{return new URL(req.url()).pathname==='/api/jobs'&&
      req.postDataJSON()?.action==='lyric-groups-scan';}catch{return false;}
  });
  await pc.click('#lyric-group-scan');
  await scanJob;
  simulatedJob={id:'lyric-scan-complete',kind:'lyric-groups-scan',state:'success',
    stage:'เสร็จสิ้น',detail:'วิเคราะห์แล้ว',completed:3,total:3,
    result:{message:'จัดกลุ่มข้อความแล้ว',songs:3,groups:1},logs:[]};
  await pc.locator('#lyric-group-results [data-lyric-group="intro-verified-1234"]')
    .waitFor({timeout:10000});
  assert.match(await pc.locator('#lyric-group-results').innerText(),/3 เพลง/);
  await pc.click('#lyric-group-results [data-lyric-group="intro-verified-1234"]');
  await pc.waitForFunction(()=>document.querySelector('#lyric-group-selection')?.textContent.includes('บรรทัดแรก'));
  assert.match(await pc.locator('#lyric-group-examples').innerText(),/เพลงหนึ่ง/);
  await pc.locator('#lyric-group-replacement').fill('[X-Stage Karaoke Online]');
  await pc.click('#lyric-group-apply');
  await pc.locator('#studio-confirm-dialog[open]').waitFor();
  assert.match(await pc.locator('#studio-confirm-message').innerText(),/3 เพลง/);
  assert.match(await pc.locator('#studio-confirm-message').innerText(),/ไม่เปลี่ยน/);
  await pc.click('#studio-confirm-cancel');
  await pc.click('#lyric-group-apply');
  await pc.locator('#studio-confirm-dialog[open]').waitFor();
  const replaceRequest=pc.waitForRequest(req=>{
    try{const d=req.postDataJSON();return new URL(req.url()).pathname==='/api/jobs'&&
      d?.action==='lyric-groups-replace'&&d?.expectedCount===3&&
      d?.group==='intro-verified-1234'&&d?.replacement==='[X-Stage Karaoke Online]';}catch{return false;}
  });
  await pc.click('#studio-confirm-ok');
  await replaceRequest;
  simulatedJob={id:'lyric-bulk-complete',kind:'lyric-groups-replace',state:'success',
    stage:'เสร็จสิ้น',detail:'แทนที่แล้ว',completed:3,total:3,
    result:{changedSongs:3,message:'แก้ข้อความบรรทัดแรกสำเร็จ 3 เพลง'},logs:[]};
  await pc.waitForFunction(()=>document.querySelector('#lyric-group-undo')?.disabled===false);
  assert.match(await pc.locator('#lyric-group-results').innerText(),/วิเคราะห์/);
  await pc.click('#lyric-group-undo');
  await pc.locator('#studio-confirm-dialog[open]').waitFor();
  const undoRequest=pc.waitForRequest(req=>{
    try{const d=req.postDataJSON();return new URL(req.url()).pathname==='/api/jobs'&&
      d?.action==='lyric-groups-undo'&&d?.backupId===bulkBackup.id;}catch{return false;}
  });
  await pc.click('#studio-confirm-ok');
  await undoRequest;
  simulatedJob={id:'lyric-undo-complete',kind:'lyric-groups-undo',state:'success',
    stage:'เสร็จสิ้น',detail:'คืนข้อมูลแล้ว',completed:3,total:3,
    result:{restoredSongs:3,message:'คืนค่าเดิม 3 เพลง'},logs:[]};
  await pc.waitForFunction(()=>document.querySelector('#lyric-group-undo')?.disabled===true);
  assert.deepEqual(pcErrors,[], 'Bulk lyric group UI must not produce JavaScript errors');
  simulatedJob={id:'',kind:'',state:'idle',stage:'พร้อม',detail:'',
    completed:0,total:0,logs:[]};
  // Independent AI lyrics menu: import -> select -> proof playback -> review.
  await pc.click('.nav-button[data-tab="ai-lyrics"]');
  assert.equal(await pc.locator('#tab-ai-lyrics').isVisible(),true,
    'AI Lyrics must be a separate left menu');
  assert.equal(await pc.locator('#ai-lyrics-import').isVisible(),true);
  await pc.click('#ai-lyrics-import');
  await pc.waitForFunction(()=>document.querySelector('#ai-lyrics-selected')?.textContent.includes('เพลง AI นำเข้า'));
  assert.equal(await pc.locator('#ai-lyrics-start').isEnabled(),true,
    'Independent imported file can use Whisper when a model is available');
  assert.match(await pc.locator('#ai-lyrics-editor').inputValue(),/ท่อนแรก AI/);
  assert.equal(await pc.locator('#ai-lyrics-save').isEnabled(),true);
  const aiLive = pc.waitForRequest((req)=>{
    try {return new URL(req.url()).pathname === '/api/live-preview' &&
      req.postDataJSON()?.id===-1;}catch{return false;}
  });
  await pc.click('#ai-lyrics-play');
  await aiLive;
  await pc.waitForFunction(()=>document.querySelector('#ai-lyrics-audio')?.src.includes('/api/live-stream'));
  assert.match(await pc.locator('#ai-lyrics-karaoke').innerText(),/ท่อนแรก AI/);
  await pc.click('#ai-lyrics-stop');
  await pc.click('#ai-lyrics-save');
  await pc.locator('#studio-confirm-dialog[open]').waitFor();
  const approvedLrc = pc.waitForRequest((req)=>{
    try{return new URL(req.url()).pathname === '/api/ai-lyrics-approve' &&
      req.postDataJSON()?.id === -1;}catch{return false;}
  });
  await pc.click('#studio-confirm-ok');
  await approvedLrc;
  const exportedLrc = pc.waitForEvent('download');
  await pc.click('#ai-lyrics-download');
  assert.match((await exportedLrc).suggestedFilename(),/\.lrc$/);
  // Removing an imported song must ask first, preserve the row on Cancel,
  // then clear the selected editor and list only after an accepted API call.
  // Owners can paste correct lyrics with no timestamps, keep every word,
  // and choose AI-assisted approximate timing without overwriting on cancel.
  const ownerLyrics='ฉันเดินทางไกล\nยังคงคิดถึงเธอ\nแม้เวลาผ่านไป';
  await pc.locator('#ai-lyrics-paste').fill(ownerLyrics);
  assert.equal(await pc.locator('#ai-lyrics-align').isEnabled(),true);
  await pc.locator('#ai-lyrics-align').click();
  await pc.locator('#studio-confirm-dialog[open]').waitFor();
  assert.match(await pc.locator('#studio-confirm-title').innerText(),/AI จัดเวลา/);
  await pc.click('#studio-confirm-cancel');
  assert.equal(await pc.locator('#ai-lyrics-paste').inputValue(), ownerLyrics);
  await pc.locator('#ai-lyrics-align').click();
  await pc.locator('#studio-confirm-dialog[open]').waitFor();
  const alignRequest=pc.waitForRequest(req=>{
    try{return new URL(req.url()).pathname==='/api/jobs' &&
      req.postDataJSON()?.action==='ai-align' &&
      req.postDataJSON()?.lyrics===ownerLyrics &&
      req.postDataJSON()?.id===-1;}catch{return false;}
  });
  await pc.click('#studio-confirm-ok');
  await alignRequest;
  simulatedJob={id:'finished-ai-align-test',kind:'ai-align',state:'success',
    stage:'จัดเวลาแล้ว',detail:'พร้อมตรวจแก้',total:1,completed:1,
    result:{songId:-1,rawLrc:'[00:05.00]ฉันเดินทางไกล\n[00:08.00]ยังคงคิดถึงเธอ\n[00:12.00]แม้เวลาผ่านไป\n',
      uncertain:1,issues:['บรรทัด 2: พบคำตรงกันเพียงบางส่วน'],
      message:'จัดเวลาเบื้องต้น 3 บรรทัด'},logs:[]};
  await pc.waitForFunction(()=>document.querySelector('#ai-lyrics-editor')?.value.includes('[00:08.00]ยังคงคิดถึงเธอ'),
    null,{timeout:10000});
  assert.deepEqual((await pc.locator('#ai-lyrics-editor').inputValue()).split('\n').filter(Boolean)
    .map(s=>s.slice(s.indexOf(']')+1)),ownerLyrics.split('\n'),
    'Whisper timestamps may be approximate but must never replace supplied words');
  assert.match(await pc.locator('#ai-lyrics-align-review').innerText(),/บรรทัด 2/);
  assert.equal(await pc.locator('#ai-lyrics-paste').inputValue(),ownerLyrics);
  // Reset mocked engine to idle before exercising independent AI removal.
  simulatedJob={id:'',kind:'',state:'idle',stage:'พร้อม',detail:'',
    completed:0,total:0,logs:[]};

  const removeButton=pc.locator('#ai-lyrics-results [data-ai-remove="-1"]');
  await removeButton.waitFor();
  await removeButton.click();
  await pc.locator('#studio-confirm-dialog[open]').waitFor();
  assert.match(await pc.locator('#studio-confirm-title').innerText(),/นำเพลงออก/);
  assert.match(await pc.locator('#studio-confirm-message').innerText(),/ไม่ลบไฟล์เพลงต้นฉบับ/);
  assert.equal(await pc.locator('#studio-confirm-ok').innerText(),'นำออกจากรายการ');
  await pc.click('#studio-confirm-cancel');
  assert.equal(removedAIRequests,0,'Cancel must not invoke /api/vocal-remove');
  assert.equal(await removeButton.count(),1,'Cancel must preserve the imported row');
  await removeButton.click();
  await pc.locator('#studio-confirm-dialog[open]').waitFor();
  await pc.click('#studio-confirm-ok');
  await pc.waitForFunction(()=>document.querySelector('#ai-lyrics-count')?.textContent.includes('ยังไม่มีเพลงที่นำเข้า'));
  assert.equal(removedAIRequests,1,'Confirm must remove only the selected import');
  assert.equal(await pc.locator('#ai-lyrics-selected').innerText(),'ยังไม่ได้เลือกเพลง');
  assert.equal(await pc.locator('#ai-lyrics-editor').inputValue(),'');
  assert.equal(await pc.locator('#ai-lyrics-start').isDisabled(),true);
  // Importing the same local audio again must remain possible.
  await pc.click('#ai-lyrics-import');
  await pc.locator('#ai-lyrics-results [data-ai-remove="-1"]').waitFor();
  assert.equal(await pc.locator('#ai-lyrics-count').innerText(),'1–1 จาก 1 ไฟล์');
  assert.deepEqual(pcErrors,[], 'AI import/remove must not cause browser errors');
  // Cloud UI smoke uses mocked API only; network/account integration is
  // independently covered by the Drive round-trip Python tests.
  await pc.click('.nav-button[data-tab="settings"]');
  await pc.click('#settings-login');
  await pc.waitForFunction(()=>document.querySelector('#google-badge')?.textContent.includes('test@example.invalid'));
  assert.match(await pc.locator('#google-login-state').innerText(), /test@example.invalid/,
    'After Google Login, the settings status must show the actual signed-in account');
  assert.match(await pc.locator('#google-config-state').innerText(), /ตั้งค่าแล้ว/,
    'OAuth client readiness must remain visible after Google Login');
  await pc.click('.nav-button[data-tab="upload"]');
  assert.equal(await pc.locator('#upload-button').isEnabled(),true);
  await pc.click('#upload-button');
  await pc.locator('#studio-confirm-dialog[open]').waitFor();
  const uploadJob=pc.waitForRequest(req=>{
    try{return new URL(req.url()).pathname==='/api/jobs' &&
      req.postDataJSON()?.action==='upload';}catch{return false;}
  });
  await pc.click('#studio-confirm-ok');
  await uploadJob;
  await pc.click('.nav-button[data-tab="download"]');
  const downloadButton=pc.locator('.download-action[data-kind="songs"]');
  assert.equal(await downloadButton.isEnabled(),true);
  await downloadButton.click();
  await pc.locator('#studio-confirm-dialog[open]').waitFor();
  const downloadJob=pc.waitForRequest(req=>{
    try{return new URL(req.url()).pathname==='/api/jobs' &&
      req.postDataJSON()?.action==='download' &&
      req.postDataJSON()?.kind==='songs';}catch{return false;}
  });
  await pc.click('#studio-confirm-ok');
  await downloadJob;
  assert.deepEqual(pcErrors,[], 'Cloud UI actions should not produce JavaScript errors');

  // Post-build consent: a completed build must ASK instead of uploading.
  const manualUploadCount = uploadRequests.length;
  simulatedJob = {id:'finished-build-1',kind:'build',state:'success',
    stage:'เสร็จสิ้น',detail:'สร้างเพลงสำเร็จ',completed:1,total:1,
    created:1,skipped:0,errors:0,result:{created:1,skipped:0,errors:0},logs:[]};
  await pc.locator('#studio-confirm-dialog[open]').waitFor({timeout:10000});
  assert.match(await pc.locator('#studio-confirm-title').innerText(),/X-Stage Song Karaoke Online/);
  assert.equal(await pc.locator('#studio-confirm-ok').innerText(),'อัปโหลดตอนนี้');
  assert.equal(await pc.locator('#studio-confirm-cancel').innerText(),'ไว้ภายหลัง');
  assert.equal(uploadRequests.length,manualUploadCount,'No upload without post-build consent');
  await pc.locator('#upload-create-library').evaluate(el=>el.checked=true);
  const automaticFollowup = pc.waitForResponse(res=>{
    try {
      const req=res.request(),data=req.postDataJSON();
      return new URL(req.url()).pathname==='/api/jobs' &&
        data?.action==='upload' && data?.create_new_library===false;
    } catch {return false;}
  });
  await pc.click('#studio-confirm-ok');
  await automaticFollowup;
  assert.equal(uploadRequests.length,manualUploadCount+1);
  assert.equal(uploadRequests.at(-1).create_new_library,false,
    'Post-build upload MUST NOT inherit create-new-library flag');
  assert.equal(await pc.locator('#tab-upload').isVisible(),true);

  simulatedJob = {id:'finished-build-2',kind:'build',state:'success',
    stage:'เสร็จสิ้น',detail:'สร้างเพลงสำเร็จ',completed:1,total:1,
    created:1,skipped:0,errors:0,result:{created:1,skipped:0,errors:0},logs:[]};
  await pc.locator('#studio-confirm-dialog[open]').waitFor({timeout:10000});
  await pc.click('#studio-confirm-cancel');
  await pc.waitForTimeout(1800);
  assert.equal(uploadRequests.length,manualUploadCount+1,
    'Choosing Later must not upload anything');
  assert.equal(await pc.locator('#studio-confirm-dialog').isVisible(),false,
    'Build completion prompt must not reopen on repeated polling');

  fakeGoogleConnected=false;
  simulatedJob = {id:'finished-build-3',kind:'build',state:'success',
    stage:'เสร็จสิ้น',detail:'สร้างเพลงสำเร็จ',completed:1,total:1,
    created:1,skipped:0,errors:0,result:{created:1,skipped:0,errors:0},logs:[]};
  await pc.locator('#studio-confirm-dialog[open]').waitFor({timeout:10000});
  await pc.click('#studio-confirm-ok');
  await pc.waitForFunction(()=>document.querySelector('#global-message')?.textContent.includes('ยังไม่ได้เชื่อม Google Drive'));
  assert.equal(uploadRequests.length,manualUploadCount+1,
    'Offline Google login must NOT start an unauthorized upload');
  assert.equal(await pc.locator('#tab-upload').isVisible(),true);

  simulatedJob = {id:'finished-build-4',kind:'build',state:'error',
    stage:'สร้างบางรายการไม่สำเร็จ',detail:'มี ERR',completed:2,total:2,
    created:1,skipped:0,errors:1,result:{created:1,skipped:0,errors:1},logs:[]};
  await pc.locator('#studio-confirm-dialog[open]').waitFor({timeout:10000});
  assert.match(await pc.locator('#studio-confirm-message').innerText(),/บางเพลงสร้างไม่สำเร็จ/);
  await pc.click('#studio-confirm-cancel');

  simulatedJob = {id:'finished-build-5',kind:'build',state:'error',
    stage:'ไม่สำเร็จ',detail:'ไม่มีไฟล์สำเร็จ',completed:1,total:1,
    created:0,skipped:0,errors:1,result:{created:0,skipped:0,errors:1},logs:[]};
  await pc.waitForTimeout(1500);
  assert.equal(await pc.locator('#studio-confirm-dialog').isVisible(),false,
    'No upload prompt when build has no successful or verified output');

  assert.deepEqual(pcErrors, [], 'Post-build consent must not cause browser errors');
  assert.deepEqual(pcErrors, [], 'PC wizard should not produce JavaScript errors');
  console.log('PASS: Both Create buttons submit real build jobs after ONE confirmation; acknowledgment stays visible.');

} finally {
  await browser?.close();
  await new Promise((resolve) => server.close(resolve));
}