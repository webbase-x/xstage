import fs from 'node:fs';
import assert from 'node:assert/strict';
import vm from 'node:vm';

const read = (name) => fs.readFileSync(new URL('../' + name, import.meta.url), 'utf8');
const html = read('studio/web.html');
const js = read('studio/web.js');
const css = read('studio/web.css');
const entry = read('studio/entry.js');
const index = read('studio/index.html');

for (const [name, script] of [['web.js', js], ['entry.js', entry]]) {
  assert.doesNotThrow(() => new Function(script), name + ' must parse as JavaScript');
}
assert.ok(html.includes('id="file-input"') && html.includes('id="folder-input"'),
  'local file picker and folder fallback must be present');
assert.ok(html.includes('id="player"') && html.includes('id="lyrics-text"'),
  'Web studio must support local preview and LRC editing');
assert.ok(html.includes("'wasm-unsafe-eval'"), 'WASM must be allowed under page CSP');
assert.ok(html.includes('worker-src') && html.includes('https://cdn.jsdelivr.net'),
  'module FFmpeg worker dependencies must be permitted under page CSP');
assert.ok(js.includes("dist/esm/ffmpeg-core.js"),
  'ESM module worker must use ESM FFmpeg core rather than UMD');
assert.ok(js.includes("URL.createObjectURL(new Blob(['import"),
  'CDN module worker must use a same-origin blob wrapper that preserves relative imports');
assert.ok(!js.includes('FormData(') && !js.includes('XMLHttpRequest('),
  'Web studio must not use upload-based file processing');
assert.ok(js.includes('await makeZIP(zipAssets)') && js.includes('await renderAudio(song, number)'),
  'both browser-side batch export and conversion must be implemented');
assert.ok(css.includes('@media(max-width:650px)'), 'Web UI must be responsive');
assert.ok(index.includes('<script src="./entry.js"></script>'),
  'public studio must include an entry router');

const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]));
const used = [...js.matchAll(/\$\('([^']+)'\)/g)].map((m) => m[1]);
for (const id of used) assert.ok(ids.has(id), 'Missing HTML element used by Web app: #' + id);

function simulate({hostname, pathname, search = '', hash = ''}) {
  let destination = null;
  const location = {hostname, pathname, search, hash,
    href: 'https://' + hostname + pathname + search + hash,
    replace(url) { destination = url; }};
  vm.runInNewContext(entry, {location, URL, URLSearchParams});
  return destination;
}
assert.equal(simulate({hostname:'webbase-x.github.io',pathname:'/xstage/studio/'}),
  'https://webbase-x.github.io/xstage/studio/web.html');
assert.equal(simulate({hostname:'webbase-x.github.io',pathname:'/xstage/studio/',
  hash:'#auth=secret&engine=http%3A%2F%2F127.0.0.1%3A8765%2F'}), null,
  'PC launcher pairing link must preserve existing PC Web Control');
assert.equal(simulate({hostname:'webbase-x.github.io',pathname:'/xstage/studio/',search:'?mode=pc'}), null,
  'mode=pc must preserve manual engine connection page');
assert.equal(simulate({hostname:'localhost',pathname:'/studio/'}), null,
  'Windows bundled UI must not redirect to Web-only mode');

const start = js.indexOf('  function dosTimeDate()');
const end = js.indexOf('  async function saveUniqueToDirectory(', start);
assert.ok(start >= 0 && end > start, 'ZIP implementation must be present');
const zipFunctions = js.slice(start, end);
const makeZIP = new Function('TextEncoder', 'Blob',
  'const encoder = new TextEncoder();\n' + zipFunctions + '\nreturn makeZIP;')(TextEncoder, Blob);
const zip = await makeZIP([
  {name: 'เพลงทดสอบ.m4a', blob: new Blob([new Uint8Array([1,2,3,4])])},
  {name: 'เพลงทดสอบ.lrc', blob: new Blob(['[00:01.50]สวัสดี'], {type:'text/plain'})}
]);
const buffer = new Uint8Array(await zip.arrayBuffer());
const dv = new DataView(buffer.buffer);
assert.equal(dv.getUint32(0, true), 0x04034b50, 'ZIP must start with local file header');
const endRecord = buffer.length - 22;
assert.equal(dv.getUint32(endRecord, true), 0x06054b50, 'ZIP must have end-of-central-directory');
assert.equal(dv.getUint16(endRecord + 10, true), 2, 'ZIP must contain two output files');

console.log('Song Studio Web smoke tests passed: JavaScript, DOM IDs, pairing, privacy, ZIP structure.');