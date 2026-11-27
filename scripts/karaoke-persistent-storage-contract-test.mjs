import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const app=readFileSync(new URL('../app.js',import.meta.url),'utf8');
const font=readFileSync(new URL('../browser-midi.js',import.meta.url),'utf8');
const bank=font.slice(font.indexOf('async function saveDiskFont('),font.indexOf('function fontStatus('));
assert.match(bank,/store\.clear\(\);\s*return store\.put\(bytes,key\)/,'only one persisted bank; clear and put in same transaction');
const switcher=font.slice(font.indexOf('const generation=++switchGeneration;'),font.indexOf('const generation=++switchGeneration;')+1400);
assert.doesNotMatch(switcher,/store\.clear\(/,'do not delete existing bank before new download');
assert.match(font,/if\(removeLocal\)try\{await fontDisk/,'automatic recovery preserves bank');
assert.match(app,/code:'CATALOG_TOO_LARGE'/);
assert.match(app,/if\(androidTvCatalogRetryPending && state\.token && state\.accountSub\)/);
assert.match(app,/if \(androidTvCatalogRetryPending\) reuseExistingSession=false;/);
console.log('One-bank persistence and catalog retry source contracts passed');

assert.match(app,/function savePersistentQueue\(\)/);
assert.match(app,/function restorePersistentQueue\(\)/);
assert.match(app,/next===state\.queuePreload\.song/);
assert.match(app,/state\.queuePreloadSkipped\.clear\(\);\s*state\.medleyPreloadRetryAt=0/);

assert.match(app,/if\(nativeCatalogBridgeAvailable\(\)\)\{\s*showCatalogLoading/);
assert.match(app,/state\.nativeCatalog&&songs===state\.songs\)return nativeCatalogPager/);
assert.match(app,/nativeCatalogQuery\('catalogSearch',term,offset\)/);
assert.match(app,/state\.nativeCatalog\?null:new Map/);
const nativeStore=readFileSync(new URL('../android-tv/app/src/main/java/com/webbasex/xstage/NativeCatalogStore.java',import.meta.url),'utf8');
assert.match(nativeStore,/setRequestProperty\("Range", "bytes=" \+ existing \+ "-"\)/);
assert.match(nativeStore,/status == 206/);
assert.match(nativeStore,/getHeaderField\("Content-Range"\)/);
assert.match(nativeStore,/new FileOutputStream\(target, existing > 0\)/);
