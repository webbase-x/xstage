import assert from 'node:assert/strict';
import fs from 'node:fs';
const root=new URL('../',import.meta.url);
const read=path=>fs.readFileSync(new URL(path,root),'utf8');
const html=read('songstudio-plus/web/index.html');
const stylesheet=read('songstudio-plus/web/style.css');
const js=read('songstudio-plus/web/app.js');
const timeline=read('songstudio-plus/web/timeline-ui.js');
const server=read('songstudio-plus/app.py');
const desktop=read('songstudio-plus/desktop_ui.py');
const picker=read('songstudio-plus/windows_picker.py');
const core=read('songstudio-plus/plus_core.py');
const sources=[js,timeline].join('\n');
const buttons=[...html.matchAll(/<button\b[^>]*\bid="([^"]+)"/g)].map(match=>match[1]);
assert.equal(buttons.length,new Set(buttons).size,'duplicate button id');
assert.ok(buttons.length>=79,'all menus should retain original interactive buttons');
const missing=buttons.filter(id=>!sources.includes('"'+id+'"'));
assert.deepEqual(missing,[],'all named controls must be referenced in the action code');
const htmlIds=new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(match=>match[1]));
const listenerIds=[...js.matchAll(/\$\("([^"]+)"\)\.addEventListener/g)].map(match=>match[1]);
assert.deepEqual([...new Set(listenerIds.filter(id=>!htmlIds.has(id)))],[],
 'every JavaScript event target must exist in the HTML');
for(const page of ['import','lyrics','media','preview','manual','build','library','risks']){
  assert.ok(html.includes('data-view="'+page+'"'),'missing menu '+page);
}
for(const [name,call] of [
  ['source-browse','openPicker("folder","source-folder")'],
  ['lrc-browse','openPicker("lrc","media-lrc")'],
  ['source-open','openLocalFolder("source")'],
  ['diagnostic-open-log','/api/open-log'],
  ['workspace-open','openLocalFolder("workspace")'],
  ['pro-update-check','checkProUpdate()'],
  ['pro-update-install','beginProUpdate()'],
  ['pro-update-quick','beginProUpdate()'],
  ['pro-update-notice-install','beginProUpdate()'],
  ['pro-update-notice-dismiss','updateNoticeDismissed=true'],
  ['import-start','startJob("import"'],
  ['recover-lyrics','startJob("recover"'],
  ['lyrics-apply','applyLyrics()'],
  ['lyrics-undo','undoLyrics()'],
  ['lyrics-cancel','/api/job/cancel'],
  ['media-attach','attachLrc()'],
  ['build-start','startJob("build"'],
  ['manual-save','manualSave()'],
  ['manual-skip','manualSkip()'],
  ['manual-approve','manualApprove()'],
  ['preview-play','playPreview()'],
  ['preview-pause','pausePreview()'],
  ['risk-scan','startJob("swipe-audit"']
]){
  assert.ok(js.includes('"'+name+'"'),'button is missing: '+name);
  assert.ok(js.includes(call),'button action is missing: '+name+' '+call);
}
for(const route of [
  '/api/pick','/api/open-folder','/api/open-log','/api/diagnostic','/api/import','/api/jobs',
  '/api/status','/api/recover-lyrics','/api/edit/apply',
  '/api/edit/undo','/api/preview','/api/attach-lrc',
  '/api/manual/save','/api/manual/approve','/api/manual/skip',
  '/api/build','/api/update/check','/api/update/install',
  '/api/swipe/scan','/api/swipe/open-source'
])assert.ok(server.includes('"'+route+'"'),'API route missing: '+route);
assert.ok(!server.includes('import tkinter as tk'),
 'Native Windows app must never open tkinter in the HTTP worker thread');
assert.ok(server.includes('self.state.native_picker('),
 'Picker API must call the registered Windows picker backend');
assert.ok(server.includes('import windows_picker'),
 'Windows picker backend must be registered by the local engine');
assert.ok(picker.includes('System.Windows.Forms.FolderBrowserDialog'),
 'Folder selection must use Windows Forms directly');
assert.ok(picker.includes('System.Windows.Forms.OpenFileDialog'),
 'LRC selection must use a Windows file dialog directly');
assert.ok(picker.includes('"powershell.exe","-NoProfile","-STA"'),
 'Windows picker must run PowerShell in STA mode');
assert.ok(desktop.includes('def run_desktop('),
 'Windows desktop shell is required');
assert.ok(server.includes('run_desktop(server,url'),
 'Default Windows UI must use the standalone desktop shell');
assert.ok(server.includes('if options.browser:')&&server.includes('run_browser_host(server,url'),
 'System browser must remain troubleshooting-only');
assert.ok(desktop.includes('window.web.load(QUrl(url))'),
 'Standalone desktop must load its localhost UI inside Qt WebEngine');
assert.ok(desktop.indexOf('worker.start()') < desktop.indexOf('window.web.load(QUrl(url))'),
 'Local PC Engine must start before the embedded desktop UI loads');
assert.ok(desktop.includes('javaScriptConsoleMessage'),
 'Desktop shell must capture JavaScript console failures');
assert.ok(desktop.includes('web.load.finished')&&desktop.includes('web.render.terminated'),
 'Desktop shell must log WebView load and renderer failures');
assert.ok(desktop.includes('Ctrl+Shift+L')&&desktop.includes('web.core.check'),
 'Desktop shell must provide a native log shortcut and JS core health check');
assert.ok(js.includes('__XSTAGE_CORE_BOUND__'),
 'Web UI must expose successful core button binding to the desktop wrapper');
assert.ok(html.includes('list="lyrics-replacement-options"')&&
          html.includes('<option value="X-Stage Karaoke">'),
 'Grouped lyric replacement must offer X-Stage Karaoke while retaining custom typing');
assert.ok(!html.includes('id="groups-prev"')&&
          !html.includes('id="groups-next"')&&
          js.includes('async function loadMoreGroups(')&&
          js.includes('function renderGroupWindow(')&&
          html.includes('id="groups-scroll-status"')&&
          js.includes('groupNearBottom()'),
 'Grouped lyric results must scroll continuously with bounded SQLite batches and virtual DOM');
assert.ok(html.includes('id="build-tab-ready"')&&
          html.includes('id="build-tab-attention"')&&
          html.includes('id="build-scroll-status"')&&
          js.includes('async function loadMoreBuildSongs(')&&
          js.includes('function renderBuildRows('),
 'XMID/X-Media build must offer ready/review tabs and bounded scroll fetching');
assert.ok(js.includes('const review=song.manual_status==="review"')&&
          js.includes('check.disabled=!selectable')&&
          js.includes('await api("/api/manual/approve"'),
 'Build rows waiting for review must be selectable through explicit approval, not permanently disabled');
assert.ok(js.includes('"build-page-all").addEventListener("click",async()=>')&&
          js.includes('ยืนยันเพลงที่รอการตรวจในหน้านี้'),
 'Select-page action must handle review-status songs with an explicit approval prompt');
assert.ok(js.includes('CUR/เนื้อร้องยังไม่ครบ')&&
          js.includes('ระบบไม่สร้างเพลงที่ข้อมูลเวลาไม่ครบ'),
 'Build page must explain truly blocked rows instead of silently disabling every selection');
assert.ok(js.includes('jobsRefreshing:false')&&js.includes('if(!state.ready||state.jobsRefreshing)return'),
 'Job polling must not overlap across repeated imports');
assert.ok(js.includes('ui.post_job_refresh.error')&&!js.includes('}catch(error){setReady(false);}'),
 'Post-job refresh failures must not disconnect the Local Engine');
const readyControls=js.match(/for\(const id of \[(.*?)\]\)\{/s)?.[1]||"";
assert.ok(!readyControls.includes('diagnostic-open-log'),
 'Program log control must remain available even when engine-ready controls are disabled');
assert.ok(server.includes('notepad.exe')&&desktop.includes('Ctrl+Shift+L'),
 'Diagnostic log must open independently through Notepad and a native shortcut');
assert.ok(html.includes('id="pro-update-notice"')&&html.includes('id="pro-update-quick"'),
 'Startup update notification and quick action must exist');
assert.ok(js.includes('renderProUpdateNotice(result,ready)')&&
          js.includes('void checkProUpdate(true);'),
 'Verified update check must run automatically after Local Engine connect');
assert.ok(js.includes('async function api(path,payload,timeoutMs=12000)'),
 'Interactive API calls require a default timeout');
assert.ok(js.includes('api("/api/pick",{kind,current:$(target).value.trim()},0)'),
 'Windows picker may wait for explicit user interaction');
const connectBlock=core.slice(core.indexOf('@contextmanager\ndef connect'),core.indexOf('SCHEMA ='));
assert.ok(!connectBlock.includes('journal_mode=WAL'),
 'Normal SQLite connections must not renegotiate WAL during imports');
assert.ok(core.includes('_INITIALIZED = set()')&&core.includes('PRAGMA journal_mode=WAL'),
 'SQLite WAL must be configured once during workspace initialization');
assert.ok(server.includes('song-studio-pro.log')&&server.includes('def diagnostic('),
 'Persistent diagnostic log is required');
assert.ok(js.indexOf('bind();') < js.indexOf('new globalThis.XStageCueTimelineUI'),
 'Core buttons must bind before optional cue timeline initialization');
assert.ok(js.includes('timeline.init.failed'),
 'Optional timeline failure must be logged without killing the core UI');
assert.ok(!js.includes('state.ready=true;'), 'Do not fake engine state');
const importLayout=stylesheet.slice(stylesheet.lastIndexOf(
  '/* Song Studio Pro: responsive, non-overlapping window'));
assert.ok(importLayout.includes('#view-import.is-visible{')&&
          importLayout.includes('overflow-y:auto')&&
          importLayout.includes('scrollbar-width:none'),
 'Import controls must remain reachable when the Windows window is short');
assert.ok(importLayout.includes('#view-import>.two-col{')&&
          importLayout.includes('flex:0 0 auto')&&
          importLayout.includes('height:auto'),
 'Dynamic SQLite/import panels must not be squeezed into fixed-height tracks');
assert.ok(importLayout.includes('.top-actions{')&&
          importLayout.includes('flex-wrap:wrap'),
 'Windows toolbar must wrap instead of overlapping when resized');
assert.ok(html.includes('id="activity-heartbeat"')&&
          html.includes('id="activity-open-log"')&&
          js.includes('const activityAgeBucket=')&&
          js.includes('Number(job.progress_age||0)'),
  'Running imports must visibly report the age of their last real progress');
assert.ok(js.includes('["diagnostic-open-log","activity-open-log"]')&&
          server.includes('"job.progress"')&&
          server.includes('version=updater.VERSION')&&
          server.includes('"version":updater.VERSION'),
  'Import log and active app version must be reliable and directly accessible');
assert.ok(html.includes('id="toast-dismiss"')&&
  html.includes('id="toast-message"')&&
  js.includes('function dismissToast()')&&
  js.includes('if(!error)state.toastTimer=setTimeout(dismissToast,8000)')&&
  js.includes('if(confirmationPending||modal.open)return false;')&&
  js.includes('modal.returnValue="cancel"')&&
  js.includes('function showStableModal(id)'),
 'Popup warnings persist until dismissal and confirmations cannot overlap');
assert.ok(js.includes('const known=Boolean(state.updateTarget?.newer)')&&
  stylesheet.includes('#toast.show{opacity:1;visibility:visible;pointer-events:auto}'),
 'Transient update errors must not flash away existing notices');
assert.ok(!html.includes('id="lyrics-search-context"')&&
  !html.includes('id="lyrics-search-context-results"')&&
  !js.includes('renderLyricContext(')&&
  !js.includes('/api/lyrics/search-context')&&
  !js.includes('lyrics-search-context')&&
  !stylesheet.includes('.lyrics-search-context')&&
  html.includes('id="group-list"')&&
  js.includes('async function loadMoreGroups('),
  'Lyrics editor must not render or fetch song/artist/untimed LYR context; grouped lyric search remains active');
assert.ok(html.includes('id="sidebar-current-version"')&&
          !html.includes('v0.1.35 · Preview')&&
          html.includes('id="pro-update-version">กำลังตรวจสอบเวอร์ชัน')&&
          js.includes('function showRunningVersion(session)')&&
          js.includes('text("sidebar-current-version",version?')&&
          (js.match(/showRunningVersion\(session\);/g)||[]).length===2&&
          server.includes('"version":updater.VERSION'),
  'Sidebar, update page and settings must show running EXE version from /api/session on connect/reconnect');
console.log('PASS: '+buttons.length+' visible action buttons, eight menus, 19 critical actions, APIs, Windows picker, Desktop Standalone and diagnostic log');
