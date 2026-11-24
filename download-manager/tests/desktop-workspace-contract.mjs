// Non-visual regression guard for the original X-Stage Windows workspace.
// Real WinForms pixel/DPI validation is still required on a Windows runner/PC.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const workspace = readFileSync(join(root, 'MainForm.IdmLayout.cs'), 'utf8');
const main = readFileSync(join(root, 'MainForm.cs'), 'utf8');
const engine = readFileSync(join(root, 'DownloadEngine.cs'), 'utf8');
const performance = readFileSync(join(root, 'MainForm.Performance.cs'), 'utf8');
const preview = readFileSync(join(root, 'MainForm.XStagePreview.cs'), 'utf8');
const live = readFileSync(join(root, 'LiveStreamCapture.cs'), 'utf8');
const liveUi = readFileSync(join(root, 'LiveStreamCaptureForm.cs'), 'utf8');
const background = readFileSync(join(root, 'LiveBackgroundMonitor.cs'), 'utf8');
const testProject = readFileSync(join(root, 'tests/DownloadEngine.Tests.csproj'), 'utf8');

const updateUi = readFileSync(join(root, 'UpdateTransitionForm.cs'), 'utf8');
const updater = readFileSync(join(root, 'SelfUpdater.cs'), 'utf8');
assert.ok(!main.includes('ShowRestartCountdownAsync'), 'Do not show a second countdown popup');
assert.match(main, /using \(var download = new UpdateDownloadForm[\s\S]*?handoffCenter = download\.HandoffCenter;\s*\}[\s\S]*?await Task\.Run\(\(\) => SelfUpdater\.LaunchInstallerHelper\([\s\S]*?installer, release, handoffCenter\.X, handoffCenter\.Y\)\);[\s\S]*?if \(!IsDisposed\) Close\(\);/);
assert.match(updateUi, /Location = CenterOnWorkingArea\(new Point\(x, y\), Size\)/);
assert.match(updater, /centerX\.ToString[\s\S]*?centerY\.ToString/);
assert.match(main, /OfType<LiveStreamCaptureForm>\(\)\.Any\(window => window\.IsBusy\)[\s\S]*?SelfUpdater\.LaunchInstallerHelper/);
assert.match(updater, /process\.Kill\(\)[\s\S]*?throw new UpdateHandoffException/);
assert.match(updater, /watch\.Elapsed < TimeSpan\.FromSeconds\(90\)/);
assert.match(updater, /if \(process\.HasExited\)[\s\S]*?process\.ExitCode/);
assert.match(main, /UpdateHandoffException \{ CanInstallManually: true \}/);
assert.match(main, /เปิดตัวช่วยติดตั้งไม่สำเร็จ · SHA-256 ผ่านแล้ว/);
assert.match(updateUi, /_probeOnly[\s\S]*?Readiness probe only/);
for (let step = 2; step <= 6; step++) assert.ok(updater.includes('ขั้นที่ '+step+'/6'));
assert.ok(updateUi.includes('ขั้นที่ 1/6') && updateUi.includes('ขั้นที่ 6/6'));
assert.ok(updateUi.includes('_dismiss.Visible = true'));
assert.match(workspace, /Button\("เพิ่มงาน"[\s\S]*?ToggleQuickEntry\(false\)/);
assert.match(workspace, /Button\("ดาวน์โหลดวิดีโอ"[\s\S]*?ToggleQuickEntry\(true\)/);
assert.match(workspace, /if \(_inputVisible && _videoEntryRequested == video\)[\s\S]*?ShowInputPanel\(false\)/);
assert.ok(testProject.includes('../UpdateTransitionForm.cs'));
const smartSyncUi = readFileSync(join(root, 'SmartSyncForm.cs'), 'utf8');
assert.match(workspace, /Button\("Smart Sync", "sync"[\s\S]*?ToggleSmartSync\(\)/);
assert.match(workspace, /Overflow = name == "Smart Sync" \? ToolStripItemOverflow\.Never/);
assert.ok(workspace.indexOf('Button("Smart Sync"') < workspace.indexOf('Button("เริ่ม"'));
assert.match(workspace, /_smartSyncWindow\.Visible\) _smartSyncWindow\.Hide\(\)/);
assert.match(smartSyncUi, /SmartSyncFolders\.ExecuteAsync\(plan, parallel, progress, token, SmartSyncReceiptStore\.DefaultPath\)/);
assert.match(smartSyncUi, /Task\.Delay\(TimeSpan\.FromSeconds\(60\), token\)/);
assert.match(smartSyncUi, /Volatile\.Read\(ref _latestScan\)/);
assert.match(smartSyncUi, /_scanTicker\.Tick/);
assert.match(smartSyncUi, /SmartSyncFolders\.Scan\(pc, drive, direction, token, progress, mode\)/);
assert.match(smartSyncUi, /ApplyWorkspaceTheme\(grid\)/);
assert.match(smartSyncUi, /MainForm\.DarkGrid/);
assert.match(smartSyncUi, /RestorePreferences\(\);[\s\S]*?_direction\.SelectedIndexChanged/);
assert.match(smartSyncUi, /_background\.CheckedChanged \+= \(_, _\) => SavePreferences\(\)/);
assert.match(smartSyncUi, /SmartSyncPreferencesStore\.Load\(_preferencesPath\)/);
assert.ok(testProject.includes('../SmartSyncFolders.cs'));
const contracts = [
  ['changed source clears stale adaptive throughput', /if \(sourceChanged\)[\s\S]*?job\.PreviousBytes = 0;\s*job\.SpeedBytesPerSecond = 0;\s*job\.SmoothedSpeedBytesPerSecond = 0;/, engine],
  ['protected subscription domains rejected before job creation', /host\.EndsWith\("\." \+ domain, StringComparison\.OrdinalIgnoreCase\)/, engine],
  ['protected subscription domains are explicit', /"netflix\.com", "disneyplus\.com", "primevideo\.com"/, engine],
  ['protected streams rejected before queue mutation', /var host = uri\.IdnHost[\s\S]*?throw new ArgumentException\([\s\S]*?var selectedParts = parts \?\? DefaultParts;/, engine],
  ['official streaming services menu', /Menu\("รับชมสตรีมมิง \(เว็บไซต์ทางการ\)"/, workspace],
  ['Netflix official playback link', /OpenOfficialStreamingSite\("https:\/\/www\.netflix\.com\/"\)/, workspace],
  ['Disney official playback link', /OpenOfficialStreamingSite\("https:\/\/www\.disneyplus\.com\/"\)/, workspace],
  ['Prime Video official playback link', /OpenOfficialStreamingSite\("https:\/\/www\.primevideo\.com\/"\)/, workspace],
  ['Twitch official playback link', /OpenOfficialStreamingSite\("https:\/\/www\.twitch\.tv\/"\)/, workspace],
  ['streaming uses external system browser', /Process\.Start\(new ProcessStartInfo\(uri\.AbsoluteUri\) \{ UseShellExecute = true \}\)/, workspace],
  ['streaming requires HTTPS and no credentials', /uri\.Scheme != Uri\.UriSchemeHttps[\s\S]*?uri\.UserInfo\.Length != 0/, workspace],
  ['streaming does not enqueue DRM media', /Never pass[\s\S]*?DRM playback URLs to yt-dlp/, workspace],
  ['global speed save button cannot implicitly close dialog before validation', /Text = "บันทึก", Width = 112, Height = 35,\s*DialogResult = DialogResult\.None/, performance],
  ['file speed save button cannot implicitly close dialog before validation', /Width = 110, Height = 30, DialogResult = DialogResult\.None/, performance],
  ['global speed validation keeps dialog open', /ok\.Click \+= \(_, _\) =>[\s\S]*?dialog\.DialogResult = DialogResult\.None;/, performance],
  ['per-file speed validation keeps dialog open', /save\.Click \+= \(_, _\) =>[\s\S]*?dialog\.DialogResult = DialogResult\.None;/, performance],
  ['branded header', /CreateBrandHeader\(\)/, workspace],
  ['live command bar', /Button\("บันทึกไลฟ์สด", "video"/, workspace],
  ['live media command', /Action\("บันทึกไลฟ์สด · ตัดคลิปตามช่วงหยุดพูด/, workspace],
  ['live dialog is nonmodal', /window\.Show\(this\)/, workspace],
  ['live minute choices', /AllowedClipMinutes = \{ 1, 3, 5, 10, 15, 20, 30, 60 \}/, live],
  ['background live polling choices', /AllowedPollSeconds = \{ 15, 30, 60 \}/, background],
  ['metadata-only public extractor', /"xstage-live-status:%\(live_status\)s"/, background],
  ['live HLS manifest detection', /IsActiveHlsManifest\(string\? content\)/, background],
  ['live DASH manifest detection', /IsActiveDashManifest\(string\? content\)/, background],
  ['finished HLS rejected', /!content\.Contains\("#EXT-X-ENDLIST"/, background],
  ['monitor has bounded request timeout', /timeout\.CancelAfter\(TimeSpan\.FromSeconds\(12\)\)/, background],
  ['monitor supports cancellation', /Task\.Delay\(TimeSpan\.FromSeconds\(pollSeconds\), cancellationToken\)/, background],
  ['auto-start when live', /await _monitor\.WaitForLiveAsync\(url, seconds, ShowPhase,/, liveUi],
  ['monitor never opens video webpage', /ไม่เปิดหน้าเว็บหรือเล่นภาพ\/เสียง/, liveUi],
  ['background tray icon', /private readonly NotifyIcon _trayIcon = new\(\)/, liveUi],
  ['restore window from tray', /private void RestoreFromTray\(\)/, liveUi],
  ['waiting can be cancelled safely', /if \(_waitingForLive\)/, liveUi],
  ['main form protected from active recording exit', /Application\.OpenForms\.OfType<LiveStreamCaptureForm>\(\)/, main],
  ['metadata-only monitor linked in windows test', /LiveBackgroundMonitor\.cs/, testProject],
  ['master preservation', /"master\.recording\.mkv"/, live],
  ['stopped FFmpeg gracefully', /process\.StandardInput\.WriteLine\("q"\)/, live],
  ['silence detector connected', /silencedetect=noise=-35dB:d=0\.6/, live],
  ['no forced cut', /if \(nearby\.Length == 0\) break;/, live],
  ['speech-aware segmentation', /LiveSpeechSegmentPlanner\.Plan\(/, live],
  ['live permission checkbox', /if \(!_permission\.Checked\)/, liveUi],
  ['live dialog retains files on errors', /ต้นฉบับ MKV ถูกเก็บไว้เสมอ/, liveUi],
  ['live UI linked in integration test', /LiveStreamCaptureForm\.cs/, testProject],
  ['live capture linked in integration test', /LiveStreamCapture\.cs/, testProject],
  ['compact command deck', /CreateIconToolbar\(\)/, workspace],
  ['unified vector glyph renderer', /private static Image DrawToolbarGlyph\(string glyph, Color color\)/, workspace],
  ['vector rather than font characters', /graphics\.FillPolygon\(brush/, workspace],
  ['custom X-Stage menu palette', /class XStageMenuColors : ProfessionalColorTable/, workspace],
  ['menu icons', /Image = DrawToolbarGlyph\(glyph, GlyphColor\(glyph\)\)/, workspace],
  ['category image list', /_categories\.ImageList = _categoryIcons/, workspace],
  ['keep category image sources alive for deferred native GDI handle', /_categoryIconSources\.Add\(icon\)/, workspace],
  ['dispose category source images after native ImageList', /_categoryIcons\.Dispose\(\);\s*foreach \(var image in _categoryIconSources\) image\.Dispose\(\)/, main],
  ['valid drawable chart bounds', /if \(area\.Width < 130 \|\| area\.Height < 85\) return;/, preview],
  ['real Windows UI smoke invocation', /_uiSmokeMode = args\.Contains\("--ui-smoke"/, main],
  ['category image keys', /ImageKey = key, SelectedImageKey = key/, workspace],
  ['live menu selected-queue indicator', /Checked = string\.Equals\(/, workspace],
  ['grouped menu separators', /new ToolStripSeparator\(\)/, workspace],
  ['file-type submenu', /var fileTypes = Menu\("แสดงตามประเภทไฟล์"/, workspace],
  ['grouped diagnostics', /var diagnostics = Menu\("ตรวจสอบปัญหา"/, workspace],
  ['Ctrl+F find shortcut', /findJob\.ShortcutKeys = Keys\.Control \| Keys\.F/, workspace],
  ['toolbar avoids duplicate symbol-font icons', /Button\("เพิ่มงาน", "add", Color\.FromArgb/, workspace],
  ['live overview tiles', /CreateOverviewTiles\(\)/, workspace],
  ['new detailed dock', /split\.Panel2\.Controls\.Add\(CreateLivePreview\(\)\)/, workspace],
  ['adaptive collapse on short windows', /height < Math\.Max\(335, minimum \+ 10\)/, workspace],
  ['data grid file icon column', /new DataGridViewImageColumn/, workspace],
  ['data grid displays actual queue', /Column\("QueueName", "คิว"/, workspace],
  ['live priority queue categories', /AddCategory\(priorityGroups, "priority-high"/, workspace],
  ['toolbar uses large vertical icons', /TextImageRelation = TextImageRelation\.ImageAboveText/, workspace],
  ['live speed linked to engine', /RecordTransferSpeed\(speedTotal\)/, main],
  ['selected file details linked to row', /UpdateLivePreview\(job\)/, main],
  ['transfer desk', /CreateTransferDesk\(\)/, workspace],
  ['accessible search', /AccessibleName = "ค้นหารายการดาวน์โหลด"/, workspace],
  ['search wiring', /_jobSearch\.TextChanged \+= \(_, _\) => RefreshRows\(\)/, workspace],
  ['search respects category', /jobs\.Where\(job => InSelectedCategory\(job\) && MatchesSearch\(job\)\)/, main],
  ['search keeps original row IDs', /_grid\.Rows\[index\]\.Tag = job\.Id/, main],
  ['selected action resolves original job', /_engine\.Jobs\.FirstOrDefault\(j => j\.Id == id\)/, main],
  ['dashboard updated from engine', /UpdateOverviewCounts\(jobs\)/, main],
  ['failed category', /AddCategory\(all, "failed"/, workspace],
  ['failed list filtering', /"failed" => job\.Status == "Failed"/, workspace],
  ['queue menu', /Menu\("คิว",/, workspace],
  ['media menu', /Menu\("สื่อ",/, workspace],
  ['settings menu', /Menu\("ตั้งค่า",/, workspace],
  ['queue destinations loaded live', /selectQueue\.DropDownOpening \+=/, workspace],
  ['queue rename available', /WithSelectedJob\(RenameJobQueue\)/, workspace],
  ['per-file bandwidth command', /WithSelectedJob\(ConfigureFileSpeed\)/, workspace],
  ['priority command', /WithSelectedJob\(j => SetPriority\(j, 0\)\)/, workspace],
  ['video re-download', /RedownloadVideo\(job\)/, workspace],
  ['browser handoff', /SetupBrowserIntegration\(\)/, workspace],
  ['download engine entrypoint preserved', /private readonly DownloadEngine _engine = new\(\)/, main],
  ['queue functionality exists', /private void RenameJobQueue\(DownloadJob job\)/, performance],
  ['speed configuration exists', /private void ConfigureFileSpeed\(DownloadJob job\)/, performance],
  ['priority SQLite failures are reported without terminating the UI', /private void SetPriority\(DownloadJob job, int priority\)[\s\S]*?catch \(Exception ex\) when \(ex is ArgumentOutOfRangeException or IOException or\s+Microsoft\.Data\.Sqlite\.SqliteException\)/, performance],
  ['file speed rejects invalid 1–63 KiB/s before changing engine state', /if \(speed\.Value is > 0 and < 64\)/, performance],
  ['file speed dialog has explicit cancellation', /dialog\.CancelButton = cancel;/, performance],
  ['performance dialog keeps input when SQLite save fails', /ok\.Click[\s\S]*?dialog\.DialogResult = DialogResult\.None;[\s\S]*?_engine\.ConfigurePerformance\([\s\S]*?catch \(Exception ex\)[\s\S]*?MessageBox\.Show\(dialog, ex\.Message/, performance],
  ['per-file dialog keeps input when SQLite save fails', /save\.Click[\s\S]*?dialog\.DialogResult = DialogResult\.None;[\s\S]*?_engine\.SetFileSpeedLimit\([\s\S]*?catch \(Exception ex\)[\s\S]*?MessageBox\.Show\(dialog, ex\.Message/, performance],
  ['legacy out-of-range speed does not crash settings dialog', /Value = Math\.Clamp\(job\.FileSpeedLimitKib, 0, 1_048_576\)/, performance],
  ['tabbed details, chart and diagnostics', /new TabControl/, preview],
  ['real speed samples', /_speedSamples\.Add\(_latestTransferRate\)/, preview],
  ['real elapsed-time sampling', /var elapsedMs = _lastSpeedMeasurementTick == 0/, main],
  ['no extra chart point for search refresh', /if \(measureRate\) RecordTransferSpeed\(speedTotal\)/, main],
  ['real session transitions', /private void TrackLiveEvents\(DownloadJob\[\] jobs\)/, preview],
  ['session log capped', /if \(history\.Count > 40\) history\.RemoveAt\(0\)/, preview],
  ['session event updates', /TrackLiveEvents\(jobs\)/, main],
  ['selected job diagnostics', /private void UpdateLivePreview\(DownloadJob\? job\)/, preview],
  ['unknown speed is not fabricated', /กำลังเก็บข้อมูลความเร็วจริง/, preview],
  ['files menu', /menu\.Items\.Add\(Menu\("ไฟล์",/, workspace],
  ['work menu', /menu\.Items\.Add\(Menu\("งาน",/, workspace],
  ['view menu', /menu\.Items\.Add\(Menu\("มุมมอง",/, workspace],
  ['help menu', /menu\.Items\.Add\(Menu\("ช่วยเหลือ",/, workspace],
];
for (const [title, pattern, source] of contracts)
  assert.match(source, pattern, title);
assert.doesNotMatch(workspace,
  /using var icon = DrawToolbarGlyph\(glyph, GlyphColor\(glyph\)\)/,
  'do not dispose deferred native ImageList source bitmaps before handle creation');
assert.doesNotMatch(workspace, /CreateIdmLayout\(|IDM-inspired/, 'new workspace must not use legacy IDM layout');
assert.ok(!workspace.includes('DownloadJob {'), 'workspace must not create or replace user download records');
assert.doesNotMatch(background, /ShellExecute = true|Process\.Start\("https?:|_state\.Save/,
  'background monitoring must not open a web player or mutate SQLite');
assert.doesNotMatch(live, /_state\.Save|Jobs\.Add|File\.Delete\(RecordingPath\)/,
  'live capture must not touch SQLite or delete source recordings');
// CS0160 regression: ObjectDisposedException derives from InvalidOperationException.
// A trailing catch after its base catch is unreachable and breaks Windows builds.
const stopHandler = live.split('public void RequestStop()')[1]
  ?.split('private async Task<int> RunCaptureProcessAsync(')[0] ?? '';
assert.match(stopHandler, /catch \(InvalidOperationException\)/,
  'stop handler must handle process disposal races');
assert.doesNotMatch(stopHandler, /catch \(ObjectDisposedException\)/,
  'CS0160: stop handler must not catch a derived exception after its base');

console.log(`PASS: ${contracts.length} X-Stage desktop workspace, menu and state-preservation contracts`);
