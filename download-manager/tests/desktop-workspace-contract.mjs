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

const contracts = [
  ['branded header', /CreateBrandHeader\(\)/, workspace],
  ['compact command deck', /CreateIconToolbar\(\)/, workspace],
  ['live overview tiles', /CreateOverviewTiles\(\)/, workspace],
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
];
for (const [title, pattern, source] of contracts)
  assert.match(source, pattern, title);
assert.doesNotMatch(workspace, /CreateIdmLayout\(|IDM-inspired/, 'new workspace must not use legacy IDM layout');
assert.ok(!workspace.includes('DownloadJob {'), 'workspace must not create or replace user download records');
console.log(`PASS: ${contracts.length} X-Stage desktop workspace, menu and state-preservation contracts`);
