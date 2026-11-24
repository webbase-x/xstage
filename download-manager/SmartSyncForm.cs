using System.Diagnostics;
using System.Drawing;
using System.Windows.Forms;

namespace XStageDownloadManager;

public sealed class SmartSyncForm : Form
{
    private readonly TextBox _pc = new() { ReadOnly = true, Dock = DockStyle.Fill };
    private readonly TextBox _drive = new() { ReadOnly = true, Dock = DockStyle.Fill };
    private readonly ComboBox _direction = new() { DropDownStyle = ComboBoxStyle.DropDownList, Dock = DockStyle.Fill };
    private readonly CheckBox _background = new() { Text = "ตรวจไฟล์ใหม่ทุก 60 วินาที (ขณะโปรแกรมเปิด)", AutoSize = true };
    private readonly Button _scan = new() { Text = "ตรวจสอบไฟล์", AutoSize = true };
    private readonly Button _start = new() { Text = "เริ่ม Sync", AutoSize = true, Enabled = false };
    private readonly Button _stop = new() { Text = "หยุด", AutoSize = true, Enabled = false };
    private readonly Label _status = new() { Dock = DockStyle.Fill, AutoSize = false };
    private readonly TextBox _review = new() { Dock = DockStyle.Fill, Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical };
    private readonly List<Control> _choices = new();
    private CancellationTokenSource? _cancel;
    private SmartSyncFolderPlan? _plan;
    private bool _shutdown;
    public bool IsBusy => _cancel is not null;

    public SmartSyncForm()
    {
        Text = "Smart Sync · Google Drive for desktop";
        StartPosition = FormStartPosition.CenterParent;
        Size = new Size(780, 620);
        MinimumSize = new Size(640, 510);
        Font = new Font("Segoe UI", 10);
        ShowInTaskbar = false;
        var grid = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(12), ColumnCount = 3, RowCount = 9 };
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 125));
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 116));
        foreach (int height in new[] { 72, 36, 36, 36, 36, 72, 58 })
            grid.RowStyles.Add(new RowStyle(SizeType.Absolute, height));
        grid.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        grid.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));
        void Full(Control control, int row) { grid.Controls.Add(control, 0, row); grid.SetColumnSpan(control, 3); }
        Full(new Label { Dock = DockStyle.Fill, Text = "ใช้บัญชี Google ที่เข้าสู่ระบบใน Google Drive for desktop แล้ว เลือกโฟลเดอร์แบบ Mirror ที่เก็บไฟล์จริงในเครื่องทั้งสองฝั่ง · ไม่ใช่ลิงก์ Drive หรือ Stream files" }, 0);
        var login = new Button { Text = "เปิดหน้า Google Drive for desktop", AutoSize = true };
        login.Click += (_, _) =>
        {
            try { Process.Start(new ProcessStartInfo("https://www.google.com/drive/download/") { UseShellExecute = true }); }
            catch (Exception ex) { _status.Text = ex.Message; }
        };
        Full(login, 1);
        void Folder(string name, TextBox field, int row)
        {
            grid.Controls.Add(new Label { Text = name, Dock = DockStyle.Fill }, 0, row);
            grid.Controls.Add(field, 1, row);
            var button = new Button { Text = "เลือกโฟลเดอร์", Dock = DockStyle.Fill };
            button.Click += (_, _) =>
            {
                using var picker = new FolderBrowserDialog { SelectedPath = field.Text, Description = name };
                if (picker.ShowDialog(this) == DialogResult.OK)
                { field.Text = picker.SelectedPath; InvalidatePlan(); }
            };
            grid.Controls.Add(button, 2, row);
            _choices.Add(button);
        }
        Folder("Google Drive", _drive, 2);
        Folder("เครื่อง PC", _pc, 3);
        grid.Controls.Add(new Label { Text = "ทิศทาง", Dock = DockStyle.Fill }, 0, 4);
        _direction.Items.AddRange(new object[] { "สองทาง PC ↔ Drive", "PC → Drive", "Drive → PC" });
        _direction.SelectedIndex = 0;
        _direction.SelectedIndexChanged += (_, _) => InvalidatePlan();
        grid.Controls.Add(_direction, 1, 4);
        _choices.Add(_direction);
        var actions = new FlowLayoutPanel { Dock = DockStyle.Fill, WrapContents = true };
        actions.Controls.AddRange(new Control[] { _scan, _start, _stop, _background });
        Full(actions, 5);
        _scan.Click += async (_, _) => await RunAsync(false);
        _start.Click += async (_, _) => await RunAsync(true);
        _stop.Click += (_, _) => RequestStop();
        Full(_status, 6);
        _status.Text = "เลือกสองโฟลเดอร์แล้วกดตรวจสอบไฟล์";
        Full(_review, 7);
        Full(new Label { Text = "ไม่ลบหรือเขียนทับไฟล์เดิม · SQLite/ไฟล์ขัดแย้งต้องตรวจสอบแยก · Drive เป็นผู้ส่งขึ้นคลาวด์", Dock = DockStyle.Fill }, 8);
        Controls.Add(grid);
        FormClosing += (_, e) =>
        {
            if (!_shutdown && e.CloseReason == CloseReason.UserClosing)
            { e.Cancel = true; Hide(); }
        };
    }

    private void InvalidatePlan()
    { _plan = null; _start.Enabled = false; _status.Text = "กรุณาตรวจสอบไฟล์ใหม่"; }

    public void RequestStop()
    { if (_cancel is not null) { _status.Text = "กำลังหยุดอย่างปลอดภัย"; _cancel.Cancel(); } }

    public void CloseForShutdown()
    { _shutdown = true; Close(); }

    private void DisplayPlan(SmartSyncFolderPlan plan, int copied = 0)
    {
        var s = SmartSyncFolders.Summarize(plan, copied);
        var up = plan.Decisions.Count(d => d.Action == SyncAction.UploadNew);
        var down = plan.Decisions.Count(d => d.Action == SyncAction.DownloadNew);
        _status.Text = $"ไฟล์เหมือนกัน {s.Identical:N0} · ใหม่ PC→Drive {up:N0} · Drive→PC {down:N0} · ต้องตรวจสอบ {s.Review:N0} · ส่งแล้ว {copied:N0}";
        _review.Lines = plan.Decisions.Where(d => d.Action != SyncAction.Unchanged).Take(500)
            .Select(d => d.Action + "   " + d.RelativePath)
            .Prepend("รายการตัวอย่างสูงสุด 500 ไฟล์ · SQLite/sidecar ที่ข้าม: " + plan.DatabaseReviewCount).ToArray();
    }

    private async Task RunAsync(bool transfer)
    {
        if (IsBusy || (transfer && _plan is null)) return;
        var pc = _pc.Text; var drive = _drive.Text;
        var direction = (SmartSyncDirection)_direction.SelectedIndex;
        var repeat = transfer && _background.Checked;
        using var cancellation = new CancellationTokenSource();
        _cancel = cancellation;
        var token = cancellation.Token;
        foreach (var control in _choices) control.Enabled = false;
        _scan.Enabled = _start.Enabled = _background.Enabled = false;
        _stop.Enabled = true;
        try
        {
            do
            {
                _status.Text = "กำลังตรวจสอบไฟล์และแฮช...";
                var plan = transfer && _plan is not null ? _plan :
                    await Task.Run(() => SmartSyncFolders.Scan(pc, drive, direction, token), token);
                _plan = plan;
                DisplayPlan(plan);
                if (!transfer) break;
                var progress = new Progress<int>(n => { if (!IsDisposed && IsBusy) _status.Text = $"กำลังซิงค์ไฟล์ · สำเร็จ {n:N0} รายการ"; });
                var result = await Task.Run(() => SmartSyncFolders.ExecuteAsync(plan, 4, progress, token), token);
                DisplayPlan(plan, result.Copied);
                _plan = null;
                if (repeat)
                {
                    _status.Text += " · ตรวจใหม่ใน 60 วินาที";
                    await Task.Delay(TimeSpan.FromSeconds(60), token);
                }
            } while (repeat);
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested)
        { _plan = null; _status.Text = "หยุดแล้ว · ไฟล์ที่ตรวจสอบและบันทึกสำเร็จยังคงอยู่"; }
        catch (Exception ex)
        { _plan = null; _status.Text = "หยุด: " + ex.Message; }
        finally
        {
            _cancel = null;
            if (!IsDisposed)
            {
                foreach (var control in _choices) control.Enabled = true;
                _scan.Enabled = _background.Enabled = true;
                _start.Enabled = _plan is not null;
                _stop.Enabled = false;
            }
        }
    }
}
