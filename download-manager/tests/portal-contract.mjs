import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const read = path => fs.readFileSync(new URL('../../'+path, import.meta.url), 'utf8');
const html = read('index.html');
const storefront = read('storefront.js');
const deviceSrc = read('storefront-device.js');
assert.doesNotThrow(() => new vm.Script(storefront));
assert.doesNotThrow(() => new vm.Script(deviceSrc));
assert.ok(html.includes('data-app="download-manager"'));
assert.ok(html.includes('data-device-app="download-manager"'));
assert.ok(html.includes('data-download-app="download-manager"'));
assert.ok(html.includes('data-platform="windows"'));
assert.ok(html.includes('assets/app-icons/download-manager.svg'));
assert.ok(storefront.includes('"download-manager":{'));
assert.ok(storefront.includes('Facebook Reels') && storefront.includes('TikTok'));
assert.ok(html.includes('youtube tiktok facebook reels'));
assert.ok(storefront.includes('downloads/download-manager-preview-latest.json'));
const feed = JSON.parse(read('downloads/download-manager-preview-latest.json'));
assert.equal(feed.name, 'X-Stage Download Manager');
if (feed.available === true) {
  assert.match(feed.sha256, /^[a-f0-9]{64}$/i, 'published EXE needs a SHA-256');
  assert.match(feed.file, /^X-Stage-Download-Manager-v\d+\.\d+\.\d+-build\d+-win-x64-Setup\.exe$/);
  assert.equal(feed.download_url, 'https://github.com/webbase-x/xstage/releases/download/xstage-download-manager-v'+feed.version+'-build'+feed.build+'-preview/'+feed.file);
} else {
  assert.equal(feed.available, false, 'an unpublished build must remain unavailable');
}
assert.equal(feed.channel, 'preview');
const module = { exports: {} };
new Function('module',deviceSrc)(module);
const guide = module.exports;
assert.equal(guide.forApp({kind:'windows',label:'Windows'},'download-manager').level,'supported');
assert.equal(guide.forApp({kind:'ios',label:'iOS'},'download-manager').level,'other');
const cards=(html.match(/<article class="app-card[^>]* data-app=/g)||[]).length;
assert.equal((html.match(/data-device-app=/g)||[]).length,cards,'all app cards must have compatibility guidance');
console.log('PASS: Download Manager portal routing, metadata, platform, icon and safe preview status.');
