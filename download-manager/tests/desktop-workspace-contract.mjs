// Non-visual regression guard for the original X-Stage Windows workspace.
// Real WinForms pixel/DPI validation is still required on a Windows runner/PC.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const workspace = readFileSync(join(root, 'MainForm.IdmLayout.cs'), 'utf8');
const main = readFileSync(join(root, 'MainForm.cs'), 'utf8');
const performance = readFileSync(join(root, 'MainForm.Performance.cs'), 'utf8');
const preview = readFileSync(join(root, 'MainForm.XStagePreview.cs'), 'utf8');
const live = readFileSync(join(root, 'LiveStreamCapture.cs'), 'utf8');
const liveUi = readFileSync(join(root, 'LiveStreamCaptureForm.cs'), 'utf8');
const testProject = readFileSync(join(root, 'tests/DownloadEngine.Tests.csproj'), 'utf8');

const contracts = [
  ['branded header', /CreateBrandHeader\(\)/, workspace],
  ['live command bar', /Button\("บันทึกไลฟ์สด", "video"/, workspace],
  ['live media command', /Action\("บันทึกไลฟ์สด · ตัดคลิปตามช่วงหยุดพูด/, workspace],
  ['live dialog is nonmodal', /window\.Show\(this\)/, workspace],
  ['live minute choices', /AllowedClipMinutes = \{ 1, 3, 5, 10, 15, 20, 30, 60 \}/, live],
  ['master preservation', /"master\.recording\.mkv"/, live],
  ['stopped FFmpeg gracefully', /process\.StandardInput\.WriteLine\("q"\)/, live],
  ['silence detector connected', /silencedetect=noise=-35dB:d=0\.6/, live],
  ['no forced cut', /if \(nearby\.Length == 0\) break;/, live],
  ['speech-aware segmentation', /LiveSpeechSegmentPlanner\.Plan\(/, live],
  ['live permission checkbox', /if \(!_permission\.Checked\)/, liveUi],
  ['live dialog retains files on errors', /เก็บไฟล์ต้นฉบับ/, liveUi],
  ['live UI linked in integration test', /LiveStreamCaptureForm\.cs/, testProject],
  ['live capture linked in integration test', /LiveStreamCapture\.cs/, testProject],
  ['compact command deck', /CreateIconToolbar\(\)/, workspace],
  ['unified vector glyph renderer', /private static Image DrawToolbarGlyph\(string glyph, Color color\)/, workspace],
  ['vector rather than font characters', /graphics\.FillPolygon\(brush/, workspace],
  ['custom X-Stage menu palette', /class XStageMenuColors : ProfessionalColorTable/, workspace],
  ['menu icons', /Image = DrawToolbarGlyph\(glyph, GlyphColor\(glyph\)\)/, workspace],
  ['category image list', /_categories\.ImageList = _categoryIcons/, workspace],
  ['category image keys', /ImageKey = key, SelectedImageKey = key/, workspace],
  ['live menu selected-queue indicator', /Checked = string\.Equals\(/, workspace],
  ['grouped menu separators', /new ToolStripSeparator\(\)/, workspace],
  ['file-type submenu', /var fileTypes = Menu\("แสดงตามประเภทไฟล์"/, workspace],
  ['grouped diagnostics', /var diagnostics = Menu\("ตรวจสอบปัญหา"/, workspace],
  ['Ctrl+F find shortcut', /findJob\.ShortcutKeys = Keys\.Control \| Keys\.F/, workspace],
  ['toolbar avoids duplicate symbol-font icons', /Button\("เพิ่มงาน", "add", Color\.FromArgb/, workspace],
  ['live overview tiles', /CreateOverviewTiles\(\)/, workspace],
  ['new detailed dock', /split\.Panel2\.Controls\.Add\(CreateLivePreview\(\)\)/, workspace],
  ['adaptive collapse on short windows', /split\.Height < 335/, workspace],
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
assert.doesNotMatch(workspace, /CreateIdmLayout\(|IDM-inspired/, 'new workspace must not use legacy IDM layout');
assert.ok(!workspace.includes('DownloadJob {'), 'workspace must not create or replace user download records');
assert.doesNotMatch(live, /_state\.Save|Jobs\.Add|File\.Delete\(RecordingPath\)/,
  'live capture must not touch SQLite or delete source recordings');
console.log(`PASS: ${contracts.length} X-Stage desktop workspace, menu and state-preservation contracts`);
