using System.Diagnostics;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

namespace XStageDownloadManager;

public sealed class MainForm : Form
{
    private readonly DownloadEngine _engine = new();
    private readonly TextBox _url = new();
    private readonly TextBox _folder = new();
    private readonly ComboBox _parts = new();
    private readonly ComboBox _videoQuality = new();
    private readonly ComboBox _outputFormat = new();
    private TableLayoutPanel? _inputLayout;
    private Control[] _videoOptionControls = Array.Empty<Control>();
    private readonly DataGridView _grid = new();
    private readonly ContextMenuStrip _completedMenu = new();
    private readonly Label _summary = new();
    private readonly Label _details = new();
    private readonly Label _updateStatus = new();
    private bool _checkingUpdates;
    private readonly Font _finishedFileFont = new("Segoe UI", 10, FontStyle.Bold | FontStyle.Underline);
    private readonly Font _normalFileFont = new("Segoe UI", 10, FontStyle.Regular);
    private readonly CancellationTokenSource _browserStop = new();
    private readonly System.Windows.Forms.Timer _timer = new() { Interval = 800 };

    public MainForm(string[] args)
    {
        Text = "X-Stage Download Manager · v0.2.6 Build 9";
        MinimumSize = new Size(930, 650);
        Size = new Size(1220, 785);
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(244, 246, 250);
        ForeColor = Color.FromArgb(23, 34, 55);
        Font = new Font("Segoe UI", 10);
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        CreateLayout();
        FormClosed += (_, _) => _completedMenu.Dispose();
        _parts.Items.AddRange(new object[] { "1", "2", "4", "8", "16", "32" });
        _parts.SelectedItem = _engine.DefaultParts.ToString();
        _parts.SelectedIndexChanged += (_, _) =>
        {
            if (_parts.SelectedItem is string value && int.TryParse(value, out var count))
            {
                try { _engine.SetDefaultParts(count); }
                catch (IOException ex) { MessageBox.Show(this, ex.Message, "บันทึกการตั้งค่าไม่ได้"); }
                catch (UnauthorizedAccessException ex) { MessageBox.Show(this, ex.Message, "บันทึกการตั้งค่าไม่ได้"); }
            }
        };
        _videoQuality.Items.AddRange(new object[]
        {
            "ดีที่สุด (ภาพและเสียง)", "1080p", "720p", "480p"
        });
        _videoQuality.SelectedIndex = 0;
        _outputFormat.Items.AddRange(new object[] { "MP4 (แนะนำ)", "MKV", "WEBM", "MP3 (เฉพาะเสียง)" });
        _outputFormat.SelectedIndex = 0;
        _outputFormat.SelectedIndexChanged += (_, _) => _videoQuality.Enabled = _outputFormat.SelectedIndex != 3;
        _folder.Text = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads");
        _url.TextChanged += (_, _) => UpdateVideoOptionVisibility();
        _url.Text = args.FirstOrDefault(a => DownloadEngine.TryParseUrl(a, out _)) ?? "";
        UpdateVideoOptionVisibility();
        _timer.Tick += (_, _) => RefreshRows();
        _timer.Start();
        FormClosing += (_, _) =>
        {
            _browserStop.Cancel();
            _timer.Stop();
            _engine.PauseAll();
            _engine.Save();
        };
        FormClosed += (_, _) => { _finishedFileFont.Dispose(); _normalFileFont.Dispose(); };
        Shown += async (_, _) =>
        {
            StartBrowserHandoff();
            if (args.Length >= 2 && args[0] == "--enqueue" &&
                DownloadEngine.TryParseUrl(args[1], out _))
            {
                try
                {
                    _engine.Add(args[1], _folder.Text, _engine.DefaultParts, SelectedQuality(), SelectedOutputFormat());
                    _url.Clear();
                    RefreshRows();
                }
                catch (Exception ex) { MessageBox.Show(this, ex.Message, "รับงานจากเบราว์เซอร์ไม่สำเร็จ"); }
            }
            await CheckForUpdatesAsync(false);
        };
        RefreshRows();
    }

    private void CreateLayout()
    {
        var header = new Panel { Dock = DockStyle.Top, Height = 101 };
        header.Paint += (_, e) =>
        {
            using var gradient = new LinearGradientBrush(header.ClientRectangle,
                Color.FromArgb(12, 38, 79), Color.FromArgb(28, 105, 184), 0f);
            e.Graphics.FillRectangle(gradient, header.ClientRectangle);
            using var circle = new SolidBrush(Color.FromArgb(58, 178, 234));
            e.Graphics.FillEllipse(circle, header.Width - 132, -90, 235, 235);
            using var circle2 = new SolidBrush(Color.FromArgb(35, 106, 200));
            e.Graphics.FillEllipse(circle2, header.Width - 308, 40, 188, 188);
        };
        header.Controls.Add(new Label
        {
            Text = "X-STAGE   DOWNLOAD MANAGER", AutoSize = true,
            ForeColor = Color.White, Font = new Font("Segoe UI", 20, FontStyle.Bold),
            Location = new Point(25, 17), BackColor = Color.Transparent
        });
        header.Controls.Add(new Label
        {
            Text = "VIDEO • DOWNLOAD • RESUME • QUEUE     |     Windows PC · v0.2.6 · Build 9",
            AutoSize = true, ForeColor = Color.FromArgb(212, 230, 252),
            Font = new Font("Segoe UI", 9, FontStyle.Regular),
            Location = new Point(28, 65), BackColor = Color.Transparent
        });
        Controls.Add(header);

        var entry = new TableLayoutPanel
        {
            Dock = DockStyle.Top, Height = 268, Padding = new Padding(20, 11, 20, 9),
            BackColor = Color.White, ColumnCount = 4, RowCount = 5
        };
        entry.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 92));
        entry.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        entry.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 112));
        entry.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 133));
        for (int i = 0; i < 5; i++) entry.RowStyles.Add(new RowStyle(SizeType.Percent, 20));
        entry.Controls.Add(MakeLabel("ลิงก์ / วิดีโอ"), 0, 0);
        entry.Controls.Add(MakeLabel("บันทึกที่"), 0, 1);
        SetupText(_url, "วางลิงก์ YouTube, TikTok, Facebook Reels หรือ URL ไฟล์ทั่วไป");
        SetupText(_folder, "เลือกโฟลเดอร์สำหรับบันทึกไฟล์");
        _url.KeyDown += (_, e) =>
        {
            if (e.KeyCode == Keys.Enter) { e.SuppressKeyPress = true; AddUrls(); }
        };
        entry.Controls.Add(_url, 1, 0);
        entry.Controls.Add(_folder, 1, 1);
        var paste = MakeButton("วางลิงก์", false, (_, _) =>
        {
            try { if (Clipboard.ContainsText()) _url.Text = Clipboard.GetText(); }
            catch { MessageBox.Show("อ่านคลิปบอร์ดไม่ได้", "X-Stage", MessageBoxButtons.OK, MessageBoxIcon.Information); }
        });
        var add = MakeButton("＋ ดาวน์โหลด", true, (_, _) => AddUrls());
        var browse = MakeButton("เลือกโฟลเดอร์", false, (_, _) =>
        {
            using var dialog = new FolderBrowserDialog
            {
                Description = "เลือกตำแหน่งเก็บไฟล์ที่ดาวน์โหลด",
                SelectedPath = Directory.Exists(_folder.Text) ? _folder.Text :
                    Environment.GetFolderPath(Environment.SpecialFolder.UserProfile)
            };
            if (dialog.ShowDialog(this) == DialogResult.OK) _folder.Text = dialog.SelectedPath;
        });
        entry.Controls.Add(paste, 2, 0);
        entry.Controls.Add(add, 3, 0);
        entry.Controls.Add(browse, 3, 1);
        var hint = new Label
        {
            Text = "HTTPS / HTTP", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleCenter,
            ForeColor = Color.FromArgb(114, 127, 151), Font = new Font("Segoe UI", 8)
        };
        entry.Controls.Add(hint, 2, 1);
        entry.Controls.Add(MakeLabel("จำนวนส่วน"), 0, 2);
        _parts.DropDownStyle = ComboBoxStyle.DropDownList;
        _parts.Dock = DockStyle.Fill;
        _parts.Margin = new Padding(3, 8, 6, 7);
        _parts.Font = new Font("Segoe UI", 11);
        _parts.AccessibleName = "จำนวนการเชื่อมต่อแบ่งโหลดต่อหนึ่งไฟล์";
        entry.Controls.Add(_parts, 1, 2);
        entry.Controls.Add(new Label
        {
            Text = "1–32 ส่วน", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleCenter,
            ForeColor = Color.FromArgb(92, 110, 134), Font = new Font("Segoe UI", 8)
        }, 2, 2);
        entry.Controls.Add(MakeButton("ใช้กับรายการ", false, (_, _) => ApplyPartsToSelected()), 3, 2);
        entry.Controls.Add(MakeLabel("วิดีโอ"), 0, 3);
        _videoQuality.Dock = DockStyle.Fill;
        _videoQuality.DropDownStyle = ComboBoxStyle.DropDownList;
        _videoQuality.Margin = new Padding(3, 8, 6, 7);
        _videoQuality.Font = new Font("Segoe UI", 11);
        _videoQuality.AccessibleName = "เลือกระดับคุณภาพวิดีโอ";
        entry.Controls.Add(_videoQuality, 1, 3);
        entry.Controls.Add(new Label
        {
            Text = "อัตโนมัติ", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleCenter,
            ForeColor = Color.FromArgb(92, 110, 134), Font = new Font("Segoe UI", 8)
        }, 2, 3);
        entry.Controls.Add(new Label
        {
            Text = "YT · TikTok · FB", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleCenter,
            ForeColor = Color.FromArgb(54, 76, 111), Font = new Font("Segoe UI", 8, FontStyle.Bold)
        }, 3, 3);
        entry.Controls.Add(MakeLabel("รูปแบบไฟล์"), 0, 4);
        _outputFormat.Dock = DockStyle.Fill;
        _outputFormat.DropDownStyle = ComboBoxStyle.DropDownList;
        _outputFormat.Margin = new Padding(3, 8, 6, 7);
        _outputFormat.Font = new Font("Segoe UI", 11);
        _outputFormat.AccessibleName = "เลือกรูปแบบไฟล์ปลายทาง ค่าเริ่มต้น MP4";
        entry.Controls.Add(_outputFormat, 1, 4);
        entry.Controls.Add(new Label
        {
            Text = "MP4 แนะนำ", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleCenter,
            ForeColor = Color.FromArgb(17, 128, 90), Font = new Font("Segoe UI", 8, FontStyle.Bold)
        }, 2, 4);
        _inputLayout = entry;
        _videoOptionControls = entry.Controls.Cast<Control>()
            .Where(control => entry.GetPositionFromControl(control).Row >= 3).ToArray();
        Controls.Add(entry);

        var toolbar = new FlowLayoutPanel
        {
            Dock = DockStyle.Top, Height = 104, Padding = new Padding(18, 10, 0, 8),
            WrapContents = true, BackColor = Color.FromArgb(250, 251, 253),
            AutoScroll = false
        };
        toolbar.Controls.Add(MakeTool("▶  เริ่ม / ต่อ", (_, _) => SelectedAction(j => _engine.Start(j))));
        toolbar.Controls.Add(MakeTool("Ⅱ  หยุดชั่วคราว", (_, _) => SelectedAction(_engine.Pause)));
        toolbar.Controls.Add(MakeTool("⟳  เริ่มทั้งหมด", (_, _) =>
        {
            foreach (var j in _engine.Jobs.ToArray())
                if (j.Status is "Paused" or "Failed") _engine.Start(j);
        }));
        toolbar.Controls.Add(MakeTool("Ⅱ  หยุดทั้งหมด", (_, _) => _engine.PauseAll()));
        toolbar.Controls.Add(MakeTool("⌕  เปิดไฟล์ / โฟลเดอร์", (_, _) => OpenSelected()));
        toolbar.Controls.Add(MakeTool("⟳  ตรวจสอบอัปเดต", async (_, _) => await CheckForUpdatesAsync(true)));
        toolbar.Controls.Add(MakeTool("🌐  ดาวน์โหลดอัตโนมัติ", (_, _) => SetupBrowserIntegration()));
        toolbar.Controls.Add(MakeTool("✕  ลบรายการ", (_, _) =>
        {
            var job = Selected();
            if (job is null) return;
            if (MessageBox.Show(this, "ลบรายการนี้จากประวัติหรือไม่?\nไฟล์ที่ดาวน์โหลดเสร็จจะไม่ถูกลบ",
                "ยืนยัน", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;
            if (!_engine.Remove(job))
                MessageBox.Show(this, "หยุดการดาวน์โหลดแล้ว กรุณารอให้หยุดสนิทและกดลบอีกครั้ง",
                    "กำลังหยุด", MessageBoxButtons.OK, MessageBoxIcon.Information);
            RefreshRows();
        }));
        Controls.Add(toolbar);

        _grid.Dock = DockStyle.Fill;
        _grid.Margin = Padding.Empty;
        _grid.BackgroundColor = Color.White;
        _grid.BorderStyle = BorderStyle.None;
        _grid.ColumnHeadersHeight = 44;
        _grid.ColumnHeadersHeightSizeMode = DataGridViewColumnHeadersHeightSizeMode.DisableResizing;
        _grid.EnableHeadersVisualStyles = false;
        _grid.ColumnHeadersDefaultCellStyle.BackColor = Color.FromArgb(236, 243, 250);
        _grid.ColumnHeadersDefaultCellStyle.ForeColor = Color.FromArgb(37, 60, 93);
        _grid.ColumnHeadersDefaultCellStyle.Font = new Font("Segoe UI", 10, FontStyle.Bold);
        _grid.DefaultCellStyle.BackColor = Color.White;
        _grid.DefaultCellStyle.ForeColor = Color.FromArgb(31, 42, 60);
        _grid.DefaultCellStyle.SelectionBackColor = Color.FromArgb(224, 240, 255);
        _grid.DefaultCellStyle.SelectionForeColor = Color.FromArgb(24, 66, 116);
        _grid.AlternatingRowsDefaultCellStyle.BackColor = Color.FromArgb(248, 250, 253);
        _grid.RowTemplate.Height = 41;
        _grid.RowHeadersVisible = false;
        _grid.SelectionMode = DataGridViewSelectionMode.FullRowSelect;
        _grid.MultiSelect = false;
        _grid.ReadOnly = true;
        _grid.AllowUserToAddRows = false;
        _grid.AllowUserToDeleteRows = false;
        _grid.AllowUserToResizeRows = false;
        _grid.AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.None;
        _grid.Columns.Add(new DataGridViewTextBoxColumn { Name = "File", HeaderText = "ชื่อไฟล์", AutoSizeMode = DataGridViewAutoSizeColumnMode.Fill, MinimumWidth = 150 });
        _grid.Columns.Add(new DataGridViewTextBoxColumn { Name = "Size", HeaderText = "ขนาด", Width = 94 });
        _grid.Columns.Add(new DataGridViewTextBoxColumn { Name = "Progress", HeaderText = "ความคืบหน้า", Width = 185 });
        _grid.Columns.Add(new DataGridViewTextBoxColumn { Name = "Speed", HeaderText = "ความเร็ว", Width = 114 });
        _grid.Columns.Add(new DataGridViewTextBoxColumn { Name = "Status", HeaderText = "สถานะ", Width = 130 });
        _grid.Columns.Add(new DataGridViewTextBoxColumn { Name = "Parts", HeaderText = "จำนวนส่วนจริง", Width = 130 });
        _grid.CellPainting += PaintProgress;
        _grid.SelectionChanged += (_, _) => UpdateDetails();
        _grid.CellClick += (_, e) =>
        {
            if (e.RowIndex < 0 || e.ColumnIndex != _grid.Columns["File"].Index) return;
            var job = e.RowIndex < _engine.Jobs.Count ? _engine.Jobs[e.RowIndex] : null;
            if (job is not null)
                ShowCompletedMenu(job, _grid.GetCellDisplayRectangle(e.ColumnIndex, e.RowIndex, false));
        };
        _grid.CellMouseEnter += (_, e) =>
        {
            if (e.RowIndex < 0 || e.ColumnIndex != _grid.Columns["File"].Index) return;
            var job = e.RowIndex < _engine.Jobs.Count ? _engine.Jobs[e.RowIndex] : null;
            _grid.Cursor = job is not null ? Cursors.Hand : Cursors.Default;
        };
        _grid.CellMouseLeave += (_, _) => _grid.Cursor = Cursors.Default;
        _grid.CellDoubleClick += (_, e) =>
        {
            if (e.RowIndex >= 0 && e.ColumnIndex != _grid.Columns["File"].Index) OpenSelected();
        };
        Controls.Add(_grid);
        _grid.BringToFront();

        var footer = new TableLayoutPanel
        {
            Dock = DockStyle.Bottom, Height = 98,
            BackColor = Color.FromArgb(231, 238, 247), Padding = new Padding(22, 7, 22, 9),
            ColumnCount = 1, RowCount = 3
        };
        footer.RowStyles.Add(new RowStyle(SizeType.Absolute, 27));
        footer.RowStyles.Add(new RowStyle(SizeType.Absolute, 27));
        footer.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        _summary.Dock = DockStyle.Fill;
        _summary.Font = new Font("Segoe UI", 10, FontStyle.Bold);
        _summary.ForeColor = Color.FromArgb(24, 63, 113);
        _details.Dock = DockStyle.Fill;
        _details.ForeColor = Color.FromArgb(81, 102, 127);
        _details.Font = new Font("Segoe UI", 9);
        _details.AutoEllipsis = true;
        footer.Controls.Add(_summary, 0, 0);
        footer.Controls.Add(_details, 0, 1);
        _updateStatus.Dock = DockStyle.Fill;
        _updateStatus.ForeColor = Color.FromArgb(41, 92, 156);
        _updateStatus.Font = new Font("Segoe UI", 8, FontStyle.Bold);
        _updateStatus.Text = "รุ่นที่ติดตั้ง v0.2.6 · Build 9";
        footer.Controls.Add(_updateStatus, 0, 2);
        Controls.Add(footer);
    }

    private void UpdateVideoOptionVisibility()
    {
        var entry = _inputLayout;
        if (entry is null) return;
        bool showVideo = SocialVideoDownloader.InputContainsVideo(_url.Text);
        entry.SuspendLayout();
        foreach (var control in _videoOptionControls) control.Visible = showVideo;
        for (int row = 0; row < 5; row++)
        {
            var style = entry.RowStyles[row];
            style.SizeType = row < 3 || showVideo ? SizeType.Percent : SizeType.Absolute;
            style.Height = row >= 3 && !showVideo ? 0 : showVideo ? 20 : 100f / 3f;
        }
        // Shrink the entire panel: no empty video-property rows for ZIP,
        // documents, ordinary HTTP links, or direct-file video links.
        entry.Height = showVideo ? 268 : 166;
        entry.ResumeLayout(true);
    }

    private static Label MakeLabel(string value) => new()
    {
        Text = value, Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft,
        ForeColor = Color.FromArgb(54, 76, 111), Font = new Font("Segoe UI", 10, FontStyle.Bold)
    };

    private static void SetupText(TextBox box, string accessibleName)
    {
        box.Dock = DockStyle.Fill;
        box.Margin = new Padding(3, 9, 6, 9);
        box.BorderStyle = BorderStyle.FixedSingle;
        box.Font = new Font("Segoe UI", 11);
        box.AccessibleName = accessibleName;
    }

    private static Button MakeButton(string text, bool primary, EventHandler handler)
    {
        var button = new Button
        {
            Text = text, Dock = DockStyle.Fill, Margin = new Padding(3, 7, 3, 7),
            Font = new Font("Segoe UI", 9, FontStyle.Bold), FlatStyle = FlatStyle.Flat,
            BackColor = primary ? Color.FromArgb(0, 111, 221) : Color.FromArgb(231, 239, 250),
            ForeColor = primary ? Color.White : Color.FromArgb(36, 77, 139),
            Cursor = Cursors.Hand
        };
        button.FlatAppearance.BorderSize = 0;
        button.Click += handler;
        return button;
    }

    private static Button MakeTool(string text, EventHandler handler)
    {
        var button = new Button
        {
            Text = text, Height = 37, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowOnly,
            Margin = new Padding(3, 0, 7, 0), Padding = new Padding(10, 0, 10, 0),
            FlatStyle = FlatStyle.Flat, Font = new Font("Segoe UI", 9, FontStyle.Bold),
            BackColor = Color.White, ForeColor = Color.FromArgb(39, 66, 100),
            Cursor = Cursors.Hand
        };
        button.FlatAppearance.BorderColor = Color.FromArgb(213, 225, 239);
        button.Click += handler;
        return button;
    }

    private void AddUrls()
    {
        var urls = _url.Text.Split(new[] { '\r', '\n', ' ', '\t' },
            StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).Take(200).ToArray();
        if (urls.Length == 0) { _url.Focus(); return; }
        if (string.IsNullOrWhiteSpace(_folder.Text))
        {
            MessageBox.Show(this, "กรุณาเลือกโฟลเดอร์จัดเก็บไฟล์", "X-Stage",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        var invalid = new List<string>();
        foreach (var url in urls)
        {
            try { _engine.Add(url, _folder.Text.Trim(), int.Parse((string)_parts.SelectedItem!), SelectedQuality(), SelectedOutputFormat()); }
            catch (Exception ex) { invalid.Add(url + ": " + ex.Message); }
        }
        _url.Clear();
        RefreshRows();
        if (invalid.Count > 0)
            MessageBox.Show(this, "ลิงก์ที่ไม่สามารถเพิ่มได้:\n" +
                string.Join("\n", invalid.Take(5)), "ตรวจสอบ URL",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
    }

    private string SelectedQuality() => _videoQuality.SelectedIndex switch
    {
        1 => "1080", 2 => "720", 3 => "480", _ => "Best"
    };

    private string SelectedOutputFormat() => _outputFormat.SelectedIndex switch
    {
        1 => "mkv", 2 => "webm", 3 => "mp3", _ => "mp4"
    };

    private void ApplyPartsToSelected()
    {
        var job = Selected();
        if (job is null)
        {
            MessageBox.Show(this, "เลือกไฟล์ที่ต้องการเปลี่ยนจำนวนส่วนก่อน", "จำนวนส่วน");
            return;
        }
        if (job.Status is "Running" or "Queued")
        {
            MessageBox.Show(this, "กดหยุดชั่วคราวและรอให้รายการหยุดสนิทก่อนเปลี่ยนจำนวนส่วน", "กำลังดาวน์โหลด");
            return;
        }
        if (job.Status == "Completed")
        {
            MessageBox.Show(this, "ไฟล์ดาวน์โหลดเสร็จแล้ว เลือกจำนวนส่วนสำหรับไฟล์ใหม่ได้", "ดาวน์โหลดสำเร็จ");
            return;
        }
        var parts = int.Parse((string)_parts.SelectedItem!);
        if (job.Parts == parts) return;
        if (Interlocked.Read(ref job.DownloadedBytes) > 0 &&
            MessageBox.Show(this,
                "การเปลี่ยนจำนวนส่วนจะลบเฉพาะชิ้นส่วนชั่วคราวของไฟล์นี้และเริ่มดาวน์โหลดใหม่จาก 0%\nไฟล์ที่ดาวน์โหลดเสร็จจะไม่ถูกลบ\nดำเนินการต่อหรือไม่?",
                "ยืนยันการเปลี่ยนจำนวนส่วน", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes) return;
        try
        {
            if (!_engine.SetJobParts(job, parts))
                MessageBox.Show(this, "รายการยังทำงานอยู่หรือไม่สามารถเปลี่ยนจำนวนส่วนได้", "ไม่สามารถเปลี่ยน");
            RefreshRows();
        }
        catch (IOException ex) { MessageBox.Show(this, ex.Message, "เปลี่ยนจำนวนส่วนไม่สำเร็จ"); }
        catch (UnauthorizedAccessException ex) { MessageBox.Show(this, ex.Message, "เปลี่ยนจำนวนส่วนไม่สำเร็จ"); }
    }

    private DownloadJob? Selected()
    {
        if (_grid.SelectedRows.Count == 0) return null;
        var id = _grid.SelectedRows[0].Tag as string;
        return _engine.Jobs.FirstOrDefault(j => j.Id == id);
    }

    private void SelectedAction(Action<DownloadJob> action)
    {
        var job = Selected();
        if (job is null) return;
        action(job);
        RefreshRows();
    }

    private void StartBrowserHandoff()
    {
        _ = Task.Run(async () =>
        {
            try
            {
                await NativeMessagingBridge.ListenAsync(url =>
                {
                    var completion = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
                    try
                    {
                        BeginInvoke(new Action(() =>
                        {
                            try
                            {
                                _engine.Add(url, _folder.Text, _engine.DefaultParts, SelectedQuality());
                                RefreshRows();
                                completion.TrySetResult(true);
                            }
                            catch (Exception)
                            {
                                completion.TrySetResult(false);
                            }
                        }));
                    }
                    catch (InvalidOperationException) { completion.TrySetResult(false); }
                    return completion.Task;
                }, _browserStop.Token);
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                if (!IsDisposed && IsHandleCreated)
                    BeginInvoke(new Action(() => _details.Text = "เชื่อมต่อเบราว์เซอร์ในเครื่องไม่ได้: " + ex.Message));
            }
        });
    }

    private void SetupBrowserIntegration()
    {
        var extensionFolder = BrowserIntegration.ExtensionFolder;
        if (!Directory.Exists(extensionFolder))
        {
            MessageBox.Show(this, "ไม่พบชุดส่วนขยายเบราว์เซอร์ กรุณาติดตั้ง X-Stage Download Manager รุ่นเต็ม",
                "ดาวน์โหลดอัตโนมัติ", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        using var dialog = new Form
        {
            Text = "ตั้งค่าดาวน์โหลดอัตโนมัติจาก Chrome / Edge", Width = 590, Height = 340,
            StartPosition = FormStartPosition.CenterParent, FormBorderStyle = FormBorderStyle.FixedDialog,
            MaximizeBox = false, MinimizeBox = false, BackColor = Color.White
        };
        var instructions = new Label
        {
            Left = 20, Top = 15, Width = 540, Height = 140,
            Text = "ตั้งค่าดาวน์โหลดอัตโนมัติ: ส่งลิงก์จาก Chrome / Edge เข้า X-Stage\n" +
                   "1. เปิด chrome://extensions หรือ edge://extensions\n" +
                   "2. เปิดโหมดผู้พัฒนา (Developer mode) แล้วกด Load unpacked\n" +
                   "3. เลือกโฟลเดอร์ส่วนขยายของ X-Stage ด้านล่าง\n" +
                   "4. คัดลอก Extension ID (อักษร a–p 32 ตัว) มาวาง แล้วกดบันทึก",
            Font = new Font("Segoe UI", 10), ForeColor = Color.FromArgb(35, 55, 83)
        };
        var openFolder = new Button { Left = 20, Top = 155, Width = 260, Height = 36,
            Text = "เปิดโฟลเดอร์ส่วนขยาย", BackColor = Color.FromArgb(231, 239, 250) };
        openFolder.Click += (_, _) =>
            Process.Start(new ProcessStartInfo(extensionFolder) { UseShellExecute = true });
        var copyFolder = new Button { Left = 292, Top = 131, Width = 265, Height = 36,
            Text = "คัดลอกตำแหน่งโฟลเดอร์", BackColor = Color.FromArgb(231, 239, 250) };
        copyFolder.Click += (_, _) => Clipboard.SetText(extensionFolder);
        var id = new TextBox { Left = 20, Top = 214, Width = 385, Font = new Font("Segoe UI", 11),
            PlaceholderText = "วาง Extension ID จากหน้าเบราว์เซอร์" };
        var register = new Button { Left = 417, Top = 211, Width = 140, Height = 35,
            Text = "บันทึกการเชื่อมต่อ", DialogResult = DialogResult.OK,
            BackColor = Color.FromArgb(0, 111, 221), ForeColor = Color.White };
        dialog.Controls.AddRange(new Control[] { instructions, openFolder, copyFolder, id, register });
        dialog.AcceptButton = register;
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        try
        {
            BrowserIntegration.Register(id.Text);
            MessageBox.Show(this,
                "ตั้งค่ารับดาวน์โหลดอัตโนมัติจาก Chrome / Edge สำเร็จ\n" +
                "ในส่วนขยาย ให้เปิดการรับดาวน์โหลดอัตโนมัติเฉพาะเมื่อต้องการใช้งาน\n" +
                "ส่วนขยายจะไม่ยกเลิกงานในเบราว์เซอร์หากแอปไม่รับงาน",
                "พร้อมใช้งาน", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        catch (Exception ex) when (ex is ArgumentException or IOException or UnauthorizedAccessException or InvalidOperationException)
        {
            MessageBox.Show(this, ex.Message, "ตั้งค่าดาวน์โหลดอัตโนมัติไม่สำเร็จ", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private async Task CheckForUpdatesAsync(bool manual)
    {
        if (_checkingUpdates || IsDisposed) return;
        _checkingUpdates = true;
        _updateStatus.Text = "กำลังตรวจสอบอัปเดต...";
        try
        {
            var release = await UpdateChecker.CheckAsync();
            if (IsDisposed) return;
            if (release is null)
            {
                _updateStatus.Text = "ไม่พบไฟล์อัปเดตที่ผ่านการตรวจสอบบนช่องทาง Preview";
                if (manual) MessageBox.Show(this, "ยังไม่พบรุ่นอัปเดตที่เผยแพร่และตรวจสอบแล้ว",
                    "ตรวจสอบอัปเดต", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
            if (!UpdateChecker.IsNewer(release.Version, release.Build))
            {
                _updateStatus.Text = $"รุ่นที่ติดตั้ง v{UpdateChecker.CurrentVersion} · Build {UpdateChecker.CurrentBuild} — ไม่มีรุ่นใหม่กว่า";
                if (manual) MessageBox.Show(this, "โปรแกรมเป็นรุ่นล่าสุด หรือใหม่กว่ารุ่นที่เผยแพร่แล้ว",
                    "ตรวจสอบอัปเดต", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }

            _updateStatus.Text = $"พบอัปเดต v{release.Version} · Build {release.Build}";
            var activeCount = _engine.Jobs.Count(j => j.Status is "Running" or "Queued");
            var activeNote = activeCount > 0
                ? $"มีงานดาวน์โหลด {activeCount} รายการ ซึ่งจะหยุดชั่วคราวและเก็บไว้ให้เริ่มต่อหลังอัปเดต\n"
                : "";
            if (MessageBox.Show(this,
                $"พบ X-Stage Download Manager v{release.Version} Build {release.Build}\n" +
                $"ขนาดไฟล์ประมาณ {release.Size / 1024.0 / 1024.0:0.0} MB\n\n" +
                "ดาวน์โหลดอัปเดตภายในแอป ตรวจสอบ SHA-256 แล้วติดตั้งทันที\n" +
                activeNote +
                "แอปจะปิดและเปิดใหม่อัตโนมัติเมื่อการติดตั้งสำเร็จ ดำเนินการหรือไม่?",
                "อัปเดต X-Stage", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes)
            {
                _updateStatus.Text = $"มีอัปเดต v{release.Version} · Build {release.Build} — กดตรวจสอบอัปเดตอีกครั้ง";
                return;
            }
            var progress = new Progress<double>(percent =>
            {
                if (!IsDisposed)
                    _updateStatus.Text = $"กำลังดาวน์โหลดอัปเดต v{release.Version} · {percent:0.0}%";
            });
            var installer = await SelfUpdater.DownloadVerifiedAsync(release, progress);
            if (IsDisposed) return;
            _updateStatus.Text = "ตรวจสอบไฟล์ผ่านแล้ว กำลังเตรียมหน้าต่างติดตั้ง...";
            // Do not close the existing UI until the independent updater
            // window has actually been shown and acknowledged readiness.
            SelfUpdater.LaunchInstallerHelper(installer, release);
            await ShowRestartCountdownAsync(release);
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or
                                     System.Text.Json.JsonException or IOException or
                                     UnauthorizedAccessException or System.ComponentModel.Win32Exception)
        {
            if (IsDisposed) return;
            _updateStatus.Text = "อัปเดตไม่สำเร็จ — แอปเดิมและงานดาวน์โหลดยังใช้ได้";
            MessageBox.Show(this, ex.Message, "ติดตั้งอัปเดตไม่สำเร็จ",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
        finally { _checkingUpdates = false; }
    }

    private async Task ShowRestartCountdownAsync(DownloadManagerRelease release)
    {
        // The update helper is already visible. Keep the old application's
        // window present and clearly show the seconds before handing off.
        using var notice = new Form
        {
            Text = "พร้อมติดตั้งอัปเดต X-Stage",
            Width = 570, Height = 175,
            StartPosition = FormStartPosition.CenterParent,
            FormBorderStyle = FormBorderStyle.FixedDialog,
            ControlBox = false,
            ShowInTaskbar = false,
            TopMost = true,
            BackColor = Color.White
        };
        var message = new Label
        {
            Left = 18, Top = 20, Width = 530, Height = 82,
            Font = new Font("Segoe UI", 14, FontStyle.Bold),
            ForeColor = Color.FromArgb(20, 71, 135),
            TextAlign = ContentAlignment.MiddleCenter
        };
        notice.Controls.Add(message);
        notice.Show(this);
        for (int seconds = 3; seconds >= 1; seconds--)
        {
            if (IsDisposed) return;
            var status = $"พร้อมติดตั้ง v{release.Version} Build {release.Build} · กำลังจะปิดและเปิดใหม่ใน {seconds} วินาที";
            message.Text = status;
            _updateStatus.Text = status;
            Text = $"X-Stage Download Manager · เปิดรุ่นใหม่ใน {seconds} วินาที";
            await Task.Delay(1000);
        }
        if (IsDisposed) return;
        _updateStatus.Text = "กำลังส่งต่อไปยังหน้าต่างติดตั้งและเปิดรุ่นใหม่...";
        // The detached updater stays on-screen during the short period when
        // Windows must replace the original EXE in Program Files.
        // FormClosing pauses current downloads and saves their state.
        Close();
    }

    private void PrepareCompletedMenu(DownloadJob job)
    {
        // Reuse the menu for the lifetime of the form. Disposing it from its
        // Closed event caused the System.Windows.Forms.ContextMenuStrip crash.
        if (_completedMenu.Visible) _completedMenu.Close();
        _completedMenu.Items.Clear();
        _completedMenu.Items.Add("เปิดไฟล์", null, (_, _) => OpenCompletedFile(job)).Enabled =
            job.Status == "Completed" && File.Exists(job.CompletedPath);
        _completedMenu.Items.Add("เปิดโฟลเดอร์ที่บันทึก", null, (_, _) => OpenCompletedFolder(job));
        _completedMenu.AutoClose = true;
    }

    private void ShowCompletedMenu(DownloadJob job, Rectangle cellBounds)
    {
        PrepareCompletedMenu(job);
        _completedMenu.Show(_grid, new Point(cellBounds.Left + 12, cellBounds.Bottom));
    }

    private void OpenCompletedFile(DownloadJob job)
    {
        try
        {
            if (File.Exists(job.CompletedPath))
                Process.Start(new ProcessStartInfo(job.CompletedPath) { UseShellExecute = true });
            else MessageBox.Show(this, "ไม่พบไฟล์ที่ดาวน์โหลดเสร็จแล้ว", "เปิดไฟล์");
        }
        catch (Exception ex) { MessageBox.Show(this, ex.Message, "เปิดไฟล์ไม่สำเร็จ"); }
    }

    private void OpenCompletedFolder(DownloadJob job)
    {
        try
        {
            if (File.Exists(job.CompletedPath))
            {
                var info = new ProcessStartInfo("explorer.exe") { UseShellExecute = true };
                info.ArgumentList.Add("/select,");
                info.ArgumentList.Add(job.CompletedPath);
                Process.Start(info);
            }
            else if (Directory.Exists(job.Folder))
                Process.Start(new ProcessStartInfo(job.Folder) { UseShellExecute = true });
            else MessageBox.Show(this, "ไม่พบโฟลเดอร์ปลายทาง", "เปิดโฟลเดอร์");
        }
        catch (Exception ex) { MessageBox.Show(this, ex.Message, "เปิดโฟลเดอร์ไม่สำเร็จ"); }
    }

    private void OpenSelected()
    {
        var job = Selected();
        if (job is null)
        {
            try
            {
                if (Directory.Exists(_folder.Text))
                    Process.Start(new ProcessStartInfo(_folder.Text) { UseShellExecute = true });
                else MessageBox.Show(this, "กรุณาเลือกโฟลเดอร์ปลายทางก่อน", "X-Stage");
            }
            catch (Exception ex) { MessageBox.Show(this, ex.Message, "เปิดโฟลเดอร์ไม่สำเร็จ"); }
            return;
        }
        // Do not silently launch a completed file: let the user choose.
        // A failed/incomplete download can still open its destination folder.
        PrepareCompletedMenu(job);
        _completedMenu.Show(Cursor.Position);
    }

    private void RefreshRows()
    {
        if (IsDisposed || _grid.IsDisposed) return;
        var jobs = _engine.Jobs.ToArray();
        var selectedId = Selected()?.Id;
        if (_grid.Rows.Count != jobs.Length ||
            jobs.Where((job, index) => index < _grid.Rows.Count &&
                !Equals(_grid.Rows[index].Tag, job.Id)).Any())
        {
            _grid.Rows.Clear();
            foreach (var job in jobs)
            {
                var index = _grid.Rows.Add();
                _grid.Rows[index].Tag = job.Id;
            }
            _grid.ClearSelection();
            if (selectedId is not null)
                foreach (DataGridViewRow row in _grid.Rows)
                    if (Equals(row.Tag, selectedId)) { row.Selected = true; break; }
        }
        double speedTotal = 0;
        foreach (var (job, index) in jobs.Select((job, index) => (job, index)))
        {
            var row = _grid.Rows[index];
            var current = Interlocked.Read(ref job.DownloadedBytes);
            var diff = Math.Max(0L, current - job.PreviousBytes);
            job.SpeedBytesPerSecond = job.Status == "Running" ? diff / (_timer.Interval / 1000.0) : 0;
            job.PreviousBytes = current;
            speedTotal += job.SpeedBytesPerSecond;
            row.Cells["File"].Value = job.Status == "Completed" ? "✓  " + job.Name : job.Name;
            row.Cells["File"].Style.ForeColor = job.Status == "Completed"
                ? Color.FromArgb(16, 132, 81) : Color.FromArgb(31, 42, 60);
            row.Cells["File"].Style.SelectionForeColor = job.Status == "Completed"
                ? Color.FromArgb(16, 132, 81) : Color.FromArgb(24, 66, 116);
            row.Cells["File"].Style.Font = job.Status == "Completed"
                ? _finishedFileFont : _normalFileFont;
            row.Cells["Status"].Style.ForeColor = job.Status == "Completed"
                ? Color.FromArgb(16, 132, 81) : Color.FromArgb(31, 42, 60);
            row.Cells["Size"].Value = job.TotalBytes < 0 ? "ไม่ทราบ" : FormatBytes(job.TotalBytes);
            row.Cells["Progress"].Value = ProgressPresentation.IsComplete(job) ||
                job.Kind == "Video" || job.TotalBytes > 0
                    ? ProgressPresentation.PercentLabel(job)
                    : (current > 0 ? FormatBytes(current) : "—");
            row.Cells["Speed"].Value = job.Status == "Running"
                ? FormatBytes((long)job.SpeedBytesPerSecond) + "/s" : "—";
            row.Cells["Status"].Value = job.Status switch
            {
                "Running" => job.Kind == "Video" && job.VideoPhase.Length > 0
                    ? job.VideoPhase : "กำลังดาวน์โหลด", "Queued" => "รอคิว",
                "Paused" => "หยุดชั่วคราว", "Completed" => "สำเร็จ",
                "Failed" => "เกิดข้อผิดพลาด", _ => job.Status
            };
            row.Cells["Parts"].Value = job.Kind == "Video"
                ? "สูงสุด " + job.Parts + " ช่วง"
                : job.SegmentsUsed > 0
                    ? job.SegmentsUsed + " / " + job.Parts + " ส่วน"
                    : "ตั้งไว้ " + job.Parts + " ส่วน";
        }
        var active = jobs.Count(j => j.Status == "Running");
        var completed = jobs.Count(j => j.Status == "Completed");
        _summary.Text = $"ดาวน์โหลด {active} รายการ  ·  สำเร็จ {completed} รายการ  ·  รวม {jobs.Length} รายการ  ·  ความเร็ว {FormatBytes((long)speedTotal)}/s";
        UpdateDetails();
        _engine.Save();
    }

    private void UpdateDetails()
    {
        var job = Selected();
        if (job is null)
        {
            _details.Text = "วางลิงก์ YouTube / TikTok / Facebook Reels · เลือกคุณภาพและรูปแบบไฟล์ (MP4 เริ่มต้น)";
            return;
        }
        _details.Text = job.Status == "Failed"
            ? $"ข้อผิดพลาด: {job.Error}   ·   กด เริ่ม / ต่อ เพื่อลองอีกครั้ง"
            : job.Kind == "Video"
                ? $"{SocialVideoDownloader.Platform(job.Url)} · คุณภาพ {job.VideoQuality} · ไฟล์ {job.OutputFormat.ToUpperInvariant()} · {job.Url} · บันทึกที่ {job.Folder}"
                : $"{job.Url}   ·   บันทึกที่ {job.Folder}";
    }

    private void PaintProgress(object? sender, DataGridViewCellPaintingEventArgs e)
    {
        if (e.RowIndex < 0 || e.ColumnIndex != _grid.Columns["Progress"].Index) return;
        e.PaintBackground(e.CellBounds, true);
        var job = e.RowIndex < _engine.Jobs.Count ? _engine.Jobs[e.RowIndex] : null;
        if (job is not null && (job.TotalBytes > 0 || job.Kind == "Video" ||
                                ProgressPresentation.IsComplete(job)))
        {
            var completeJob = ProgressPresentation.IsComplete(job);
            var progress = ProgressPresentation.FillFraction(job);
            var rectangle = new Rectangle(e.CellBounds.X + 9, e.CellBounds.Y + 10,
                Math.Max(1, e.CellBounds.Width - 18), 20);
            using var bg = new SolidBrush(Color.FromArgb(229, 236, 245));
            using var fg = new SolidBrush(Color.FromArgb(32, 133, 222));
            using var complete = new SolidBrush(Color.FromArgb(17, 157, 104));
            e.Graphics.FillRectangle(bg, rectangle);
            // Completed always has one continuous green bar, even when
            // temporary HTTP segment counters still contain gaps/old values.
            if (completeJob)
            {
                e.Graphics.FillRectangle(complete, rectangle);
            }
            else
            {
                var segments = job.SegmentDownloadedBytes;
                var segmentCount = job.SegmentsUsed;
                if (job.Kind != "Video" && segmentCount > 1 && job.TotalBytes > 0 &&
                    segments.Length == segmentCount && segmentCount <= 32)
                {
                    for (int i = 0; i < segmentCount; i++)
                    {
                        long segmentSize = job.TotalBytes * (i + 1) / segmentCount -
                                           job.TotalBytes * i / segmentCount;
                        var partProgress = segmentSize <= 0 ? 0 :
                            Math.Clamp(Interlocked.Read(ref segments[i]) / (double)segmentSize, 0, 1);
                        var startX = rectangle.X + i * rectangle.Width / segmentCount;
                        var endX = rectangle.X + (i + 1) * rectangle.Width / segmentCount;
                        var width = Math.Max(1, endX - startX - (segmentCount > 1 ? 1 : 0));
                        e.Graphics.FillRectangle(partProgress >= 1 ? complete : fg,
                            startX, rectangle.Y, (int)Math.Round(width * partProgress), rectangle.Height);
                    }
                }
                else
                    e.Graphics.FillRectangle(fg, rectangle.X, rectangle.Y,
                        (int)Math.Round(rectangle.Width * progress), rectangle.Height);
            }
            using var progressFont = new Font("Segoe UI", 8, FontStyle.Bold);
            TextRenderer.DrawText(e.Graphics, ProgressPresentation.PercentLabel(job),
                progressFont, rectangle,
                completeJob || progress > .52 ? Color.White : Color.FromArgb(25, 70, 117),
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
        }
        else
            TextRenderer.DrawText(e.Graphics, e.FormattedValue?.ToString() ?? "—",
                _grid.Font, e.CellBounds, Color.FromArgb(91, 111, 135),
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
        e.Handled = true;
    }

    private static string FormatBytes(long count)
    {
        if (count < 0) return "—";
        var units = new[] { "B", "KB", "MB", "GB", "TB" };
        double size = count;
        int unit = 0;
        while (size >= 1024 && unit < units.Length - 1) { size /= 1024; unit++; }
        return size.ToString(unit == 0 ? "0" : "0.0") + " " + units[unit];
    }
}
