using System.Diagnostics;
using System.Drawing;
using System.Windows.Forms;

namespace XStageDownloadManager;

/// <summary>
/// Separate opt-in live capture surface: regular HTTP downloads and their
/// persisted queue keep operating unchanged in the main window.
/// </summary>
public sealed class LiveStreamCaptureForm : Form
{
    private readonly LiveStreamCapture _capture = new();
    private readonly TextBox _source = new();
    private readonly TextBox _destination = new();
    private readonly ComboBox _minutes = new();
    private readonly CheckBox _permission = new();
    private readonly Button _start = new();
    private readonly Button _stop = new();
    private readonly Button _open = new();
    private readonly Label _state = new();
    private readonly Label _bytes = new();
    private readonly System.Windows.Forms.Timer _refresh = new() { Interval = 1000 };
    private bool _working;
    private bool _stopInitiated;
    private bool _postProcessing;
    private CancellationTokenSource? _processingCancellation;

    public bool IsBusy => _working;

    public LiveStreamCaptureForm(string defaultFolder)
    {
        Text = "X-Stage · บันทึกสตรีมสดและตัดตามจังหวะหยุดพูด";
        MinimumSize = new Size(655, 560);
        Size = new Size(800, 620);
        StartPosition = FormStartPosition.CenterParent;
        Font = new Font("Segoe UI", 10);
        BackColor = Color.FromArgb(14, 30, 46);
        ForeColor = Color.White;

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 10,
            Padding = new Padding(22, 16, 22, 15), AutoScroll = true
        };
        root.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        foreach (var height in new[] { 60, 32, 43, 32, 43, 37, 56, 40, 67, 90 })
            root.RowStyles.Add(new RowStyle(SizeType.Absolute, height));

        static Label Label(string title) => new()
        {
            Dock = DockStyle.Fill, Text = title,
            ForeColor = Color.FromArgb(201, 221, 236),
            TextAlign = ContentAlignment.BottomLeft,
            Font = new Font("Segoe UI", 9, FontStyle.Bold)
        };
        root.Controls.Add(new Label
        {
            Text = "LIVE CAPTURE  /  X-STAGE",
            Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft,
            Font = new Font("Segoe UI", 18, FontStyle.Bold),
            ForeColor = Color.FromArgb(54, 217, 188)
        }, 0, 0);
        root.Controls.Add(Label("ลิงก์ไลฟ์ HLS (.m3u8), DASH (.mpd) หรือวิดีโอสาธารณะที่รองรับ"), 0, 1);
        ConfigureInput(_source);
        _source.PlaceholderText = "https://.../live.m3u8";
        root.Controls.Add(_source, 0, 2);
        root.Controls.Add(Label("จัดเก็บในโฟลเดอร์"), 0, 3);

        var folderRow = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 1 };
        folderRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        folderRow.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 145));
        folderRow.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        ConfigureInput(_destination);
        _destination.Text = defaultFolder;
        folderRow.Controls.Add(_destination, 0, 0);
        var browse = new Button { Text = "เลือกโฟลเดอร์", Dock = DockStyle.Fill };
        StyleButton(browse, false);
        browse.Click += (_, _) =>
        {
            using var dialog = new FolderBrowserDialog
            {
                Description = "เลือกโฟลเดอร์บันทึกไลฟ์สด",
                SelectedPath = Directory.Exists(_destination.Text) ?
                    _destination.Text : Environment.GetFolderPath(Environment.SpecialFolder.UserProfile)
            };
            if (dialog.ShowDialog(this) == DialogResult.OK)
                _destination.Text = dialog.SelectedPath;
        };
        folderRow.Controls.Add(browse, 1, 0);
        root.Controls.Add(folderRow, 0, 4);

        var settingsRow = new TableLayoutPanel
        {
            Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 1,
            BackColor = Color.FromArgb(19, 47, 65)
        };
        settingsRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 68));
        settingsRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 32));
        settingsRow.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        settingsRow.Controls.Add(new Label
        {
            Text = "ความยาวคลิปเป้าหมาย (นาที) · ยืดออกจนพบจังหวะเงียบ",
            Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft,
            Padding = new Padding(10, 0, 0, 0), ForeColor = Color.White
        }, 0, 0);
        _minutes.Dock = DockStyle.Fill;
        _minutes.DropDownStyle = ComboBoxStyle.DropDownList;
        _minutes.Margin = new Padding(5, 4, 8, 4);
        foreach (var minutes in LiveStreamCapture.AllowedClipMinutes)
            _minutes.Items.Add(minutes + " นาที");
        _minutes.SelectedItem = "5 นาที";
        settingsRow.Controls.Add(_minutes, 1, 0);
        root.Controls.Add(settingsRow, 0, 5);

        _permission.Dock = DockStyle.Fill;
        _permission.Text = "ฉันมีสิทธิ์บันทึกและจัดเก็บสตรีมนี้";
        _permission.ForeColor = Color.FromArgb(205, 226, 240);
        _permission.Padding = new Padding(6, 0, 0, 0);
        root.Controls.Add(_permission, 0, 6);

        var buttonRow = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 3, RowCount = 1 };
        foreach (var percent in new[] { 37, 28, 35 })
            buttonRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, percent));
        buttonRow.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        _start.Text = "●  เริ่มบันทึกสด";
        _stop.Text = "■  หยุดและสร้างคลิป";
        _open.Text = "เปิดโฟลเดอร์คลิป";
        StyleButton(_start, true);
        StyleButton(_stop, false);
        StyleButton(_open, false);
        _stop.Enabled = false;
        _open.Enabled = false;
        buttonRow.Controls.Add(_start, 0, 0);
        buttonRow.Controls.Add(_stop, 1, 0);
        buttonRow.Controls.Add(_open, 2, 0);
        root.Controls.Add(buttonRow, 0, 7);

        var status = new TableLayoutPanel
        {
            Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2,
            BackColor = Color.FromArgb(17, 44, 64)
        };
        status.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        status.RowStyles.Add(new RowStyle(SizeType.Percent, 50));
        status.RowStyles.Add(new RowStyle(SizeType.Percent, 50));
        _state.Text = "พร้อมบันทึกสตรีม · ไม่มีไฟล์จำลอง";
        _state.ForeColor = Color.FromArgb(93, 229, 177);
        _state.Dock = DockStyle.Fill;
        _state.TextAlign = ContentAlignment.MiddleLeft;
        _state.Padding = new Padding(12, 0, 0, 0);
        _bytes.Dock = DockStyle.Fill;
        _bytes.Text = "บันทึกแล้ว 0 B";
        _bytes.ForeColor = Color.FromArgb(186, 208, 229);
        _bytes.TextAlign = ContentAlignment.MiddleLeft;
        _bytes.Padding = new Padding(12, 0, 0, 0);
        status.Controls.Add(_state, 0, 0);
        status.Controls.Add(_bytes, 0, 1);
        root.Controls.Add(status, 0, 8);

        root.Controls.Add(new Label
        {
            Text = "บันทึกไฟล์ต้นฉบับ MKV ไว้เสมอ แล้วสร้างคลิป MP4 หลังหยุดไลฟ์ " +
                   "โดยใช้ช่วงเงียบอย่างน้อย 0.6 วินาที · หากพูดต่อเนื่องจะไม่ตัดตามเวลาบังคับ " +
                   "· การตรวจช่วงเงียบเป็นการประมาณ ไม่ใช่ระบบเข้าใจจบประโยค",
            Dock = DockStyle.Fill, AutoEllipsis = false,
            ForeColor = Color.FromArgb(172, 199, 218),
            Font = new Font("Segoe UI", 9)
        }, 0, 9);

        Controls.Add(root);
        _start.Click += async (_, _) => await StartCaptureAsync();
        _stop.Click += (_, _) => StopOrCancel();

        _open.Click += (_, _) => OpenSessionFolder();
        _refresh.Tick += (_, _) => RefreshSize();
        FormClosing += (_, e) =>
        {
            if (!_working) return;
            // Closing requests a safe stop, or cancels transcoding while
            // retaining the MKV source and any already finalized MP4 clips.
            e.Cancel = true;
            StopOrCancel();
        };
        FormClosed += (_, _) => _refresh.Dispose();
    }

    private static void ConfigureInput(TextBox box)
    {
        box.Dock = DockStyle.Fill;
        box.Font = new Font("Segoe UI", 11);
        box.Margin = new Padding(4, 5, 7, 5);
        box.BackColor = Color.FromArgb(235, 247, 250);
        box.ForeColor = Color.FromArgb(23, 42, 61);
        box.BorderStyle = BorderStyle.FixedSingle;
    }

    private static void StyleButton(Button button, bool primary)
    {
        button.Dock = DockStyle.Fill;
        button.Margin = new Padding(3);
        button.FlatStyle = FlatStyle.Flat;
        button.FlatAppearance.BorderSize = 1;
        button.FlatAppearance.BorderColor = Color.FromArgb(41, 113, 155);
        button.BackColor = primary ? Color.FromArgb(23, 135, 165) : Color.FromArgb(21, 60, 80);
        button.ForeColor = Color.White;
        button.Font = new Font("Segoe UI", 9, FontStyle.Bold);
        button.Cursor = Cursors.Hand;
    }

    public void StopOrCancel()
    {
        if (!_working) return;
        if (_postProcessing)
        {
            _stop.Enabled = false;
            _stop.Text = "กำลังยกเลิกการแปลง...";
            _state.Text = "กำลังยกเลิกการแปลง · ต้นฉบับจะยังอยู่";
            _processingCancellation?.Cancel();
            return;
        }
        if (_stopInitiated) return;
        _stopInitiated = true;
        _stop.Enabled = false;
        _stop.Text = "กำลังหยุด...";
        _capture.RequestStop();
        if (_capture.Status.Contains("เตรียมแหล่งสตรีม", StringComparison.Ordinal))
        {
            // Cancel a possibly slow public-platform extractor before FFmpeg
            // has started. A stopped recording still gets a graceful "q".
            _processingCancellation?.Cancel();
        }
        _state.Text = "กำลังปิดไฟล์ต้นฉบับอย่างปลอดภัย...";
    }

    private async Task StartCaptureAsync()
    {
        if (_working) return;
        if (!_permission.Checked)
        {
            MessageBox.Show(this, "โปรดยืนยันสิทธิ์ในการบันทึกสตรีมก่อน",
                "การใช้งานสื่อ", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        var url = _source.Text.Trim();
        if (!LiveStreamCapture.IsSupportedSource(url))
        {
            MessageBox.Show(this,
                "รองรับ HLS (.m3u8), DASH (.mpd) หรือวิดีโอสาธารณะจากแพลตฟอร์มที่รองรับ",
                "ตรวจลิงก์สตรีม", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        if (_minutes.SelectedIndex < 0) return;
        var minutes = LiveStreamCapture.AllowedClipMinutes[_minutes.SelectedIndex];
        _working = true;
        _stopInitiated = false;
        _postProcessing = false;
        _processingCancellation = new CancellationTokenSource();
        _start.Enabled = false;
        _stop.Enabled = true;
        _stop.Text = "■  หยุดและสร้างคลิป";
        _open.Enabled = false;
        _source.ReadOnly = true;
        _destination.ReadOnly = true;
        _minutes.Enabled = false;
        _refresh.Start();
        try
        {
            var result = await _capture.RecordAsync(
                url, _destination.Text.Trim(), minutes, ShowPhase,
                _processingCancellation.Token);
            _state.Text = result.Message;
            _bytes.Text = "ไฟล์ต้นฉบับ: " + result.RecordingPath +
                " · คลิปสำเร็จ " + result.Clips.Count + " ไฟล์";
            _open.Enabled = Directory.Exists(result.SessionDirectory);
            MessageBox.Show(this,
                result.Message + Environment.NewLine +
                "โฟลเดอร์: " + result.SessionDirectory +
                Environment.NewLine + "ต้นฉบับ MKV ถูกเก็บไว้เสมอ",
                "บันทึกสตรีมเสร็จแล้ว", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        catch (Exception error)
        {
            // Preserve the raw recording for recovery after a stream/codec,
            // storage or FFmpeg problem. The process never overwrites files.
            _state.Text = "ไม่สำเร็จ: " + error.Message;
            _open.Enabled = Directory.Exists(_capture.SessionDirectory);
            MessageBox.Show(this,
                error.Message + Environment.NewLine +
                "หากมีข้อมูลบันทึกไว้แล้ว จะยังอยู่ใน: " + _capture.SessionDirectory,
                "X-Stage Live Capture", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
        finally
        {
            _refresh.Stop();
            _processingCancellation?.Dispose();
            _processingCancellation = null;
            _postProcessing = false;
            _working = false;
            _start.Enabled = true;
            _stop.Enabled = false;
            _source.ReadOnly = false;
            _destination.ReadOnly = false;
            _minutes.Enabled = true;
            RefreshSize();
        }
    }

    private void ShowPhase(string phase)
    {
        if (IsDisposed || !IsHandleCreated) return;
        if (InvokeRequired)
        {
            BeginInvoke(new Action(() => ShowPhase(phase)));
            return;
        }
        _state.Text = phase;
        if (phase.Contains("วิเคราะห์ช่วงหยุดพูด", StringComparison.Ordinal) ||
            phase.Contains("จุดตัดตามจังหวะเงียบ", StringComparison.Ordinal) ||
            phase.Contains("กำลังสร้างคลิป", StringComparison.Ordinal) ||
            phase.Contains("ไม่พบจังหวะเงียบ", StringComparison.Ordinal))
        {
            _postProcessing = true;
            if (!_processingCancellation?.IsCancellationRequested ?? false)
            {
                _stop.Enabled = true;
                _stop.Text = "ยกเลิกแปลง (เก็บต้นฉบับ)";
            }
        }
    }

    private void RefreshSize()
    {
        var file = _capture.RecordingPath;
        if (string.IsNullOrWhiteSpace(file) || !File.Exists(file)) return;
        try
        {
            var length = new FileInfo(file).Length;
            var units = new[] { "B", "KB", "MB", "GB", "TB" };
            double size = length;
            var level = 0;
            while (size >= 1024 && level < units.Length - 1)
            {
                size /= 1024;
                level++;
            }
            _bytes.Text = $"บันทึกไฟล์จริงแล้ว {size:0.##} {units[level]}";
        }
        catch (IOException) { }
    }

    private void OpenSessionFolder()
    {
        if (!Directory.Exists(_capture.SessionDirectory)) return;
        try
        {
            var info = new ProcessStartInfo("explorer.exe")
            {
                UseShellExecute = false
            };
            info.ArgumentList.Add(_capture.SessionDirectory);
            Process.Start(info);
        }
        catch (System.ComponentModel.Win32Exception error)
        {
            MessageBox.Show(this, error.Message, "เปิดโฟลเดอร์ไม่สำเร็จ");
        }
    }
}
