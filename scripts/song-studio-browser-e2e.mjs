import http from 'node:http';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const root = process.cwd();
const contentTypes = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8' };
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
} finally {
  await browser?.close();
  await new Promise((resolve) => server.close(resolve));
}