using System.Diagnostics;
using System.Drawing;
using System.Windows.Forms;

namespace XStageDownloadManager;

// Retain type name for the existing preference/UI tests; this is now an embedded view.
public sealed class SmartSyncForm : UserControl
{
    private readonly TextBox _pc = new() { ReadOnly = true, Dock = DockStyle.Fill };
    private readonly TextBox _drive = new() { ReadOnly = true, Dock = DockStyle.Fill };
    private readonly ComboBox _conflict = new() { DropDownStyle = ComboBoxStyle.DropDownList, Dock = DockStyle.Fill };
    private readonly ComboBox _mode = new() { DropDownStyle = ComboBoxStyle.DropDownList, Dock = DockStyle.Fill };
    private readonly NumericUpDown _parallel = new() { Minimum = 1, Maximum = 32, Value = 8, Width = 72 };
    private readonly ComboBox _direction = new() { DropDownStyle = ComboBoxStyle.DropDownList, Dock = DockStyle.Fill };
    private readonly CheckBox _background = new() { Text = "ตรวจไฟล์ใหม่ทุก 60 วินาที (ขณะโปรแกรมเปิด)", AutoSize = true };
    private readonly CheckBox _cleanupCopies = new() { Text = "สำรองสำเนา (1), (2) ที่ SHA-256 ตรงกันทั้งสองฝั่ง", AutoSize = true };
    private readonly Button _sync = new() { Text = "Sync", AutoSize = true, MinimumSize = new Size(112, 32) };
    private readonly Label _status = new() { Dock = DockStyle.Fill, AutoSize = false };
    private readonly TextBox _review = new() { Dock = DockStyle.Fill, Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical };
    private readonly List<Control> _choices = new();
    private readonly System.Windows.Forms.Timer _scanTicker = new() { Interval = 350 };
    private readonly Stopwatch _scanWatch = new();
    private SmartSyncScanProgress? _latestScan;
    private long _lastAdvance;
    private int _lastCount;
    // Latest-value mailbox: no queued UI callback for each of 50,000 files.
    private sealed class ScanMailbox(Action<SmartSyncScanProgress> report) : IProgress<SmartSyncScanProgress>
    {
        public void Report(SmartSyncScanProgress value) => report(value);
    }
    private CancellationTokenSource? _cancel;
    public SmartSyncLaneTracker Lanes { get; } = new();
    public string StatusText
    {
        get
        {
            var (up, down) = Lanes.Snapshot();
            return up.State == "กำลังรับส่ง" || down.State == "กำลังรับส่ง"
                ? $"กำลัง Sync · สำเร็จ {up.Done + down.Done:N0}/{up.Total + down.Total:N0} ไฟล์"
                : _status.Text;
        }
    }
    public string ReviewText => _review.Text;
    public string PcPath => _pc.Text;
    public string DrivePath => _drive.Text;
    public event Action? WorkspaceChanged;
    public event Action? WorkspaceStarted;
    private readonly string _preferencesPath;
    private readonly string _receiptPath;
    public bool IsBusy => _cancel is not null;

    public SmartSyncForm(string? preferencesPath = null, string? receiptPath = null)
    {
        _preferencesPath = preferencesPath ?? SmartSyncPreferencesStore.DefaultPath;
        _receiptPath = receiptPath ?? SmartSyncReceiptStore.DefaultPath;
        AccessibleName = "Smart Sync · Google Drive";
        Dock = DockStyle.Fill;
        AutoScroll = true;
        Size = new Size(860, 320);
        BackColor = MainForm.DarkTop;
        ForeColor = Color.White;
        Font = new Font("Segoe UI", 10);
        var grid = new TableLayoutPanel { Dock = DockStyle.Top, Height = 250, Padding = new Padding(8), ColumnCount = 3, RowCount = 7 };
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 125));
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 145));
        foreach (int height in new[] { 32, 32, 32, 32, 32, 32, 42 })
            grid.RowStyles.Add(new RowStyle(SizeType.Absolute, height));
        void Full(Control control, int row) { grid.Controls.Add(control, 0, row); grid.SetColumnSpan(control, 3); }
        void Folder(string name, TextBox field, int row)
        {
            grid.Controls.Add(new Label { Text = name, Dock = DockStyle.Fill }, 0, row);
            grid.Controls.Add(field, 1, row);
            var button = new Button { Text = "เลือกโฟลเดอร์", Dock = DockStyle.Fill };
            button.Click += (_, _) =>
            {
                using var picker = new FolderBrowserDialog { SelectedPath = field.Text, Description = name };
                if (picker.ShowDialog(this) == DialogResult.OK)
                {
                    field.Text = picker.SelectedPath;
                    InvalidatePlan();
                    SavePreferences();
                }
            };
            grid.Controls.Add(button, 2, row);
            _choices.Add(button);
        }
        Folder("Google Drive", _drive, 0);
        Folder("เครื่อง PC", _pc, 1);
        grid.Controls.Add(new Label { Text = "ทิศทาง", Dock = DockStyle.Fill }, 0, 2);
        _direction.Items.AddRange(new object[] { "สองทาง PC ↔ Drive", "PC → Drive", "Drive → PC" });
        _direction.SelectedIndex = 0;
        // Subscribe after restoring saved controls, not during initialization.
        grid.Controls.Add(_direction, 1, 2);
        _choices.Add(_direction);
        grid.Controls.Add(new Label { Text = "โหมด Sync", Dock = DockStyle.Fill }, 0, 3);
        _mode.Items.AddRange(new object[] { "Fast · ข้ามไฟล์ชื่อ/ขนาดตรงกัน", "Smart · ตรวจแฮชคู่ไฟล์", "Full Verify · ตรวจทุกไฟล์" });
        _mode.SelectedIndex = 0;
        grid.Controls.Add(_mode, 1, 3);
        var lanes = new FlowLayoutPanel { Dock = DockStyle.Fill, WrapContents = false };
        lanes.Controls.Add(new Label { Text = "พร้อมกัน", AutoSize = true });
        lanes.Controls.Add(_parallel);
        grid.Controls.Add(lanes, 2, 3);
        _choices.Add(_mode); _choices.Add(_parallel);
        grid.Controls.Add(new Label { Text = "รหัสเพลงชนกัน", Dock = DockStyle.Fill }, 0, 4);
        _conflict.Items.AddRange(new object[] { "ข้าม · ไม่เปลี่ยนไฟล์", "ทับ · สำรองเดิม (สองทางยึด PC)", "เก็บทั้งคู่ · รหัส_SHA-256" });
        _conflict.SelectedIndex = 0;
        grid.Controls.Add(_conflict, 1, 4);
        grid.SetColumnSpan(_conflict, 2);
        _choices.Add(_conflict);
        Full(_cleanupCopies, 5);
        _choices.Add(_cleanupCopies);
        var actions = new FlowLayoutPanel { Dock = DockStyle.Fill, WrapContents = true };
        actions.Controls.AddRange(new Control[] { _sync, _background });
        Full(actions, 6);
        _sync.Click += async (_, _) =>
        {
            if (IsBusy) RequestStop();
            else await StartFromWorkspaceAsync();
        };
        _scanTicker.Tick += (_, _) => RenderScanProgress();
        _status.Text = "เลือกคู่โฟลเดอร์ Mirror แล้วตรวจสอบไฟล์ · SQLite ไม่รับส่ง";
        Controls.Add(grid);
        ApplyWorkspaceTheme(grid);
        RestorePreferences();
        _direction.SelectedIndexChanged += (_, _) =>
        {
            InvalidatePlan();
            SavePreferences();
        };
        _background.CheckedChanged += (_, _) => SavePreferences();
        _mode.SelectedIndexChanged += (_, _) => { InvalidatePlan(); SavePreferences(); };
        _parallel.ValueChanged += (_, _) => SavePreferences();
        _conflict.SelectedIndexChanged += (_, _) => { InvalidatePlan(); SavePreferences(); };
        Disposed += (_, _) => { _scanTicker.Dispose(); _review.Dispose(); _status.Dispose(); };
    }

    private void ApplyWorkspaceTheme(Control parent)
    {
        parent.BackColor = MainForm.DarkPanel;
        parent.ForeColor = Color.White;
        foreach (Control control in parent.Controls)
        {
            control.ForeColor = Color.White;
            switch (control)
            {
                case TextBox text:
                    text.BackColor = MainForm.DarkGrid;
                    text.ForeColor = Color.FromArgb(228, 235, 246);
                    text.BorderStyle = BorderStyle.FixedSingle;
                    break;
                case ComboBox combo:
                    combo.BackColor = MainForm.DarkGrid;
                    combo.ForeColor = Color.White;
                    combo.FlatStyle = FlatStyle.Flat;
                    break;
                case NumericUpDown number:
                    number.BackColor = MainForm.DarkGrid;
                    number.ForeColor = Color.White;
                    break;
                case Button button:
                    button.FlatStyle = FlatStyle.Flat;
                    button.UseVisualStyleBackColor = false;
                    button.BackColor = MainForm.DarkGrid;
                    button.FlatAppearance.BorderColor = button == _sync ? Color.FromArgb(59, 228, 137) : MainForm.Accent;
                    button.FlatAppearance.MouseOverBackColor = Color.FromArgb(31, 79, 91);
                    button.ForeColor = button == _sync ? Color.FromArgb(59, 228, 137) : Color.White;
                    button.MinimumSize = new Size(0, 30);
                    break;
                case Label label:
                    label.ForeColor = MainForm.MutedText;
                    break;
                case CheckBox check:
                    check.FlatStyle = FlatStyle.Flat;
                    break;
                case TableLayoutPanel or FlowLayoutPanel:
                    ApplyWorkspaceTheme(control);
                    break;
            }
        }
        _status.ForeColor = Color.FromArgb(132, 220, 235);
    }

    private void RestorePreferences()
    {
        try
        {
            var saved = SmartSyncPreferencesStore.Load(_preferencesPath);
            _pc.Text = saved.Pc;
            _drive.Text = saved.Drive;
            _direction.SelectedIndex = (int)saved.Direction;
            _background.Checked = saved.Background;
            _mode.SelectedIndex = (int)saved.Mode;
            _parallel.Value = saved.ParallelFiles;
            _conflict.SelectedIndex = (int)saved.ConflictPolicy;
            if (saved.Pc.Length > 0 || saved.Drive.Length > 0)
                _status.Text = "เรียกคืนค่าที่เลือกครั้งล่าสุดแล้ว · กด Sync เพื่อตรวจสอบและรับส่ง";
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Text.Json.JsonException or InvalidDataException)
        {
            _status.Text = "อ่านค่าที่บันทึกไม่ได้ · กรุณาเลือกใหม่: " + ex.Message;
        }
    }

    private void SavePreferences()
    {
        try
        {
            SmartSyncPreferencesStore.Save(_preferencesPath, new SmartSyncPreferences(
                _pc.Text, _drive.Text, (SmartSyncDirection)_direction.SelectedIndex, _background.Checked,
                (SmartSyncMode)_mode.SelectedIndex, (int)_parallel.Value, (XmidConflictPolicy)_conflict.SelectedIndex));
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or InvalidDataException)
        {
            _status.Text = "บันทึกค่าที่เลือกไม่ได้: " + ex.Message;
        }
    }

    private void InvalidatePlan()
    { _review.Clear(); _status.Text = "กด Sync เพื่อตรวจสอบและรับส่ง"; Lanes.Reset("ยังไม่ตรวจสอบ"); WorkspaceChanged?.Invoke(); }

    public void RequestStop()
    {
        if (_cancel is not null)
        {
            _status.Text = "กำลังหยุดอย่างปลอดภัย";
            _sync.Enabled = false;
            _cancel.Cancel();
            WorkspaceChanged?.Invoke();
        }
    }

    public void CloseForShutdown() => Dispose();

    // Shared toolbar controls the whole paired session; direction-specific
    // cancellation would otherwise leave half of a two-way plan running.
    public async Task StartFromWorkspaceAsync()
    {
        if (IsBusy) return;
        await RunAsync();
    }
    public void ClearPreview()
    {
        if (!IsBusy) InvalidatePlan();
    }

    private void RenderScanProgress()
    {
        if (!IsBusy || _cancel?.IsCancellationRequested == true) return;
        var current = Volatile.Read(ref _latestScan);
        var elapsed = _scanWatch.Elapsed;
        if (current is null)
        {
            _status.Text = $"กำลังเปิดโฟลเดอร์… · {elapsed:hh\\:mm\\:ss}";
            return;
        }
        var count = current.PcFiles + current.DriveFiles;
        if (count != _lastCount) { _lastCount = count; _lastAdvance = elapsed.Ticks; }
        var rate = count / Math.Max(1, elapsed.TotalSeconds);
        var stalled = TimeSpan.FromTicks(elapsed.Ticks - _lastAdvance);
        _status.Text = $"ตรวจ {current.Phase} · PC {current.PcFiles:N0} · Drive {current.DriveFiles:N0} ไฟล์ · ข้าม {current.Review:N0}\n" +
            $"{rate:N1} ไฟล์/วินาที · อ่าน {current.BytesHashed / 1048576d:N1} MB · {elapsed:hh\\:mm\\:ss}" +
            (stalled.TotalSeconds >= 10 ? $" · ยังไม่มีไฟล์เสร็จ {stalled.TotalSeconds:N0} วินาที" : "") +
            "\n" + current.RelativePath;
    }

    private async Task<SmartSyncFolderPlan> ScanWithProgressAsync(string pc, string drive,
        SmartSyncDirection direction, SmartSyncMode mode, XmidConflictPolicy policy, CancellationToken token, bool quarantineCopies = false)
    {
        Volatile.Write(ref _latestScan, null);
        _lastAdvance = 0; _lastCount = 0;
        _scanWatch.Restart();
        Lanes.Reset("กำลังตรวจสอบ");
        _review.Clear();
        WorkspaceChanged?.Invoke();
        _scanTicker.Start();
        RenderScanProgress();
        try
        {
            var progress = new ScanMailbox(value => Volatile.Write(ref _latestScan, value));
            return await Task.Run(() => SmartSyncFolders.Scan(pc, drive, direction, token, progress, mode, policy, quarantineCopies), token);
        }
        finally
        {
            _scanTicker.Stop();
            _scanWatch.Stop();
        }
    }

    private void DisplayPlan(SmartSyncFolderPlan plan, int copied = 0)
    {
        var s = SmartSyncFolders.Summarize(plan, copied);
        var up = plan.Decisions.Count(d => d.Action is SyncAction.UploadNew or SyncAction.UploadUpdate);
        var down = plan.Decisions.Count(d => d.Action is SyncAction.DownloadNew or SyncAction.DownloadUpdate);
        var replacements = plan.Decisions.Count(d => d.Action is SyncAction.UploadUpdate or SyncAction.DownloadUpdate);
        var matchLabel = plan.Mode == SmartSyncMode.Fast ? "ชื่อ/ขนาดตรงกัน (ยังไม่ตรวจเนื้อหา)" : "ไฟล์เหมือนกัน";
        _status.Text = $"{matchLabel} {s.Identical:N0} · แผน PC→Drive {up:N0} · Drive→PC {down:N0} · ทับ {replacements:N0} · ตรวจสอบ {s.Review:N0} · ส่งแล้ว {copied:N0}";
        // Show conflicts and planned replacements before regular transfers;
        // keep skipped entries available in the preview when space remains.
        var cleanup = plan.DuplicateCleanup;
        var cleanupLines = cleanup is null ? Array.Empty<string>() :
            new[] { $"สำรองสำเนา PC {cleanup.PcArchived:N0} · Drive {cleanup.DriveArchived:N0} · เก็บไว้ {cleanup.Preserved:N0} · {SmartSyncFolders.DuplicateBackupFolder}" }
                .Concat(cleanup.Samples).ToArray();
        if (cleanup is not null) _status.Text += $" · สำรองซ้ำ {cleanup.PcArchived + cleanup.DriveArchived:N0} · เก็บไว้ {cleanup.Preserved:N0}";
        _review.Lines = plan.Decisions.OrderBy(d => d.Action switch
            {
                SyncAction.Conflict or SyncAction.ReviewDeletion => 0,
                SyncAction.UploadUpdate or SyncAction.DownloadUpdate => 1,
                SyncAction.Unchanged => 3,
                _ => 2
            }).Take(500)
            .Select(SmartSyncPresentation.Describe)
            .Prepend("แผนรับส่ง (ไม่ใช่ผลสำเร็จรายไฟล์) · ตัวอย่างสูงสุด 500 รายการ · SQLite/sidecar ที่ข้าม: " +
                plan.DatabaseReviewCount).Concat(cleanupLines).ToArray();
        if (cleanupLines.Length > 0) _review.Lines = cleanupLines.Concat(_review.Lines.Take(_review.Lines.Length - cleanupLines.Length)).ToArray();
    }

    private async Task RunAsync()
    {
        if (IsBusy) return;
        if (string.IsNullOrWhiteSpace(_pc.Text) || string.IsNullOrWhiteSpace(_drive.Text))
        {
            _status.Text = "กรุณาเลือกโฟลเดอร์ PC และ Google Drive";
            WorkspaceChanged?.Invoke();
            MessageBox.Show(FindForm() ?? (IWin32Window)this, _status.Text, "Smart Sync", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }
        var pc = _pc.Text; var drive = _drive.Text;
        var direction = (SmartSyncDirection)_direction.SelectedIndex;
        var mode = (SmartSyncMode)_mode.SelectedIndex;
        var parallel = (int)_parallel.Value;
        var policy = (XmidConflictPolicy)_conflict.SelectedIndex;
        if (policy == XmidConflictPolicy.Overwrite &&
            MessageBox.Show(this, "ใช้การเขียนทับกับ XMID ที่รหัสชนกันทุกไฟล์ในงานนี้หรือไม่? ระบบสำรองไฟล์เดิมไว้ · สองทางยึด PC · หลายฉบับที่กำกวมจะข้าม",
                "ยืนยันการเขียนทับทั้งงาน", MessageBoxButtons.YesNo, MessageBoxIcon.Warning,
                MessageBoxDefaultButton.Button2) != DialogResult.Yes) return;
        var quarantineCopies = _cleanupCopies.Checked;
        if (quarantineCopies && MessageBox.Show(this,
            "สำรองสำเนา XMID ที่ SHA-256 ตรงกับต้นฉบับในโฟลเดอร์เดียวกันทั้ง PC และ Drive ก่อน Sync หรือไม่?\n" +
            "ไม่ลบถาวร · เก็บชื่อเดิมและตำแหน่งไว้ใน " + SmartSyncFolders.DuplicateBackupFolder +
            " · การย้ายบน Drive อาจซิงค์การเปลี่ยนแปลงขึ้นคลาวด์",
            "ยืนยันการจัดการสำเนาทั้งสองฝั่ง", MessageBoxButtons.YesNo, MessageBoxIcon.Warning,
            MessageBoxDefaultButton.Button2) != DialogResult.Yes) return;
        var repeat = _background.Checked;
        using var cancellation = new CancellationTokenSource();
        _cancel = cancellation;
        var token = cancellation.Token;
        foreach (var control in _choices) control.Enabled = false;
        _background.Enabled = false;
        _sync.Text = "หยุด Sync";
        _sync.ForeColor = Color.FromArgb(250, 142, 158);
        Lanes.Reset("กำลังตรวจสอบ");
        _status.Text = "เริ่มตรวจสอบไฟล์";
        WorkspaceStarted?.Invoke();
        try
        {
            do
            {
                _status.Text = mode == SmartSyncMode.Fast ? "กำลังตรวจรายชื่อไฟล์ (ไม่อ่านเนื้อหาเดิม)..." : "กำลังตรวจสอบไฟล์และแฮช...";
                var plan = await ScanWithProgressAsync(pc, drive, direction, mode, policy, token, quarantineCopies);
                quarantineCopies = false; // No unattended cleanup on periodic passes.
                token.ThrowIfCancellationRequested();
                Lanes.Plan(plan);
                DisplayPlan(plan);
                WorkspaceChanged?.Invoke();
                Lanes.Start();
                _status.Text = "ตรวจสอบเสร็จ · เริ่ม Sync";
                WorkspaceChanged?.Invoke();
                // Directional counters are updated on the worker, UI polls them.
                // No queued callback per file when syncing tens of thousands.
                var result = await Task.Run(() => SmartSyncFolders.ExecuteAsync(plan, parallel, null, token, _receiptPath, Lanes.Complete), token);
                Lanes.Finish("สำเร็จ");
                DisplayPlan(plan, result.Copied);
                WorkspaceChanged?.Invoke();
                if (repeat)
                {
                    _status.Text += " · ตรวจใหม่ใน 60 วินาที";
                    await Task.Delay(TimeSpan.FromSeconds(60), token);
                }
            } while (repeat);
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested)
        { Lanes.Finish("หยุดชั่วคราว"); _status.Text = "หยุดแล้ว · ไฟล์ที่รับส่งสำเร็จและสำเนาที่สำรองไว้ยังคงอยู่"; }
        catch (Exception ex)
        { Lanes.Finish("เกิดข้อผิดพลาด"); _status.Text = "หยุด: " + ex.Message + " · สำเนาที่สำรองแล้วอยู่ใน " + SmartSyncFolders.DuplicateBackupFolder; }
        finally
        {
            _cancel = null;
            if (!IsDisposed)
            {
                foreach (var control in _choices) control.Enabled = true;
                _background.Enabled = true;
                _cleanupCopies.Checked = false;
                _sync.Enabled = true;
                _sync.Text = "Sync";
                _sync.ForeColor = Color.FromArgb(59, 228, 137);
                WorkspaceChanged?.Invoke();
            }
        }
    }
}
