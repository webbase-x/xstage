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
  await page.locator('#song-list tr').first().click();
  await page.fill('#lyrics-text', '[00:00.10]ทดสอบเนื้อร้อง\n[00:00.40]บรรทัดถัดไป');
  await page.click('#save-lyrics');
  await page.click('#load-engine');
  await page.waitForFunction(() => /พร้อมประมวลผล|โหลด Engine ไม่สำเร็จ/.test(document.querySelector('#engine-caption').textContent), null, {timeout:45000});
  assert.match(await page.locator('#engine-caption').innerText(), /พร้อมประมวลผล/, 'Web Engine must finish loading successfully');
  const downloadPromise = page.waitForEvent('download', {timeout:120000});
  await page.click('#build');
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
  const pc = await browser.newPage();
  const pcErrors = [];
  pc.on('pageerror', (error) => pcErrors.push(error.message));
  const settings = {
    source: 'C:\\XStage\\Songs', workspace: 'C:\\XStage\\Created',
    soundfont: 'C:\\XStage\\GeneralUser-GS.sf2', midi_preset: 'balanced',
    mode: 'original', download: 'C:\\XStage\\Downloads', oauth: ''
  };
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
        google:{connected:false,email:''},
        job:{id:'',kind:'',state:'idle',stage:'พร้อม',detail:'',completed:0,total:0,logs:[]},
        update:{status:'unavailable'}
      };
    } else if (url.pathname === '/api/songs') {
      response = {rows:list,total:list.length};
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
    } else if (url.pathname === '/api/environment') {
      response = {'Bundled FFmpeg':true, 'Bundled SoundFont':true};
    } else if (url.pathname === '/api/jobs') {
      response = {id:'pc-wizard-smoke-job'};
    }
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(response)});
  });
  pc.on('dialog', async (dialog) => dialog.accept());
  await pc.goto('http://127.0.0.1:' + port + '/studio/index.html#auth=test-session-token', {waitUntil:'load'});
  await pc.waitForFunction(() => document.getElementById('catalog-total')?.textContent.includes('2'));
  assert.equal(await pc.locator('.brand-mark img').isVisible(), true, 'PC brand icon must render');
  await pc.waitForFunction(() => {
    const icon = document.querySelector('.brand-mark img');
    return Boolean(icon && icon.complete && icon.naturalWidth > 0);
  });
  assert.equal(await pc.locator('link[rel="icon"]').getAttribute('href'), './app-icon.svg');
  assert.equal(await pc.locator('#create-stage-1').isVisible(), true, 'step 1 should be visible initially');
  assert.equal(await pc.locator('#create-stage-2').isVisible(), false, 'step 2 should be hidden initially');
  await pc.click('#create-step-next');
  assert.equal(await pc.locator('#create-stage-2').isVisible(), true, 'step 2 should open');
  await pc.locator('#song-rows tr[data-id="1"]').click();
  await pc.click('#create-step-next');
  assert.equal(await pc.locator('#create-stage-3').isVisible(), true, 'step 3 should open');
  assert.equal(await pc.locator('#create-stage-3 #create-soundfont').isVisible(), true, 'SoundFont must be within step 3');
  assert.equal(await pc.locator('#create-stage-3 #preview-audio').isVisible(), true, 'Preview player must be in the same SoundFont step');
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
  const buildRequest = pc.waitForRequest((req) => {
    try { return new URL(req.url()).pathname === '/api/jobs' && req.postDataJSON()?.action === 'build'; }
    catch { return false; }
  });
  await pc.click('#build-button');
  await pc.locator('#studio-confirm-dialog[open]').waitFor();
  assert.equal(await pc.locator('#studio-confirm-title').innerText(), 'เริ่มสร้างเพลง');
  await pc.click('#studio-confirm-ok');
  await buildRequest;
  assert.deepEqual(pcErrors, [], 'PC wizard should not produce JavaScript errors');
  console.log('PASS: Chromium verified karaoke song search, live preview ticket/stop, borderless in-app modal, PC wizard and build.');

} finally {
  await browser?.close();
  await new Promise((resolve) => server.close(resolve));
}