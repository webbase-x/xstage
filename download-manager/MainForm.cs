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
    private readonly DataGridView _grid = new();
    private readonly Label _summary = new();
    private readonly Label _details = new();
    private readonly Label _updateStatus = new();
    private bool _checkingUpdates;
    private readonly System.Windows.Forms.Timer _timer = new() { Interval = 800 };

    public MainForm(string[] args)
    {
        Text = "X-Stage Download Manager · v0.2.1 Build 4";
        MinimumSize = new Size(930, 650);
        Size = new Size(1220, 735);
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(244, 246, 250);
        ForeColor = Color.FromArgb(23, 34, 55);
        Font = new Font("Segoe UI", 10);
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        CreateLayout();
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
            "ดีที่สุด (ภาพและเสียง)", "1080p", "720p", "480p", "MP3 (เสียงอย่างเดียว)"
        });
        _videoQuality.SelectedIndex = 0;
        _folder.Text = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads");
        _url.Text = args.FirstOrDefault(a => DownloadEngine.TryParseUrl(a, out _)) ?? "";
        _timer.Tick += (_, _) => RefreshRows();
        _timer.Start();
        FormClosing += (_, _) => { _timer.Stop(); _engine.PauseAll(); _engine.Save(); };
        Shown += async (_, _) => await CheckForUpdatesAsync(false);
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
            Text = "VIDEO • DOWNLOAD • RESUME • QUEUE     |     Windows PC · v0.2.1 · Build 4",
            AutoSize = true, ForeColor = Color.FromArgb(212, 230, 252),
            Font = new Font("Segoe UI", 9, FontStyle.Regular),
            Location = new Point(28, 65), BackColor = Color.Transparent
        });
        Controls.Add(header);

        var entry = new TableLayoutPanel
        {
            Dock = DockStyle.Top, Height = 214, Padding = new Padding(20, 11, 20, 9),
            BackColor = Color.White, ColumnCount = 4, RowCount = 4
        };
        entry.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 92));
        entry.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        entry.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 112));
        entry.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 133));
        for (int i = 0; i < 4; i++) entry.RowStyles.Add(new RowStyle(SizeType.Percent, 25));
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
        _videoQuality.AccessibleName = "เลือกระดับคุณภาพวิดีโอหรือเสียง MP3";
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
        Controls.Add(entry);

        var toolbar = new FlowLayoutPanel
        {
            Dock = DockStyle.Top, Height = 61, Padding = new Padding(18, 10, 0, 8),
            WrapContents = false, BackColor = Color.FromArgb(250, 251, 253),
            AutoScroll = true
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
            if (job is not null && job.Status == "Completed")
                ShowCompletedMenu(job, _grid.GetCellDisplayRectangle(e.ColumnIndex, e.RowIndex, false));
        };
        _grid.CellMouseEnter += (_, e) =>
        {
            if (e.RowIndex < 0 || e.ColumnIndex != _grid.Columns["File"].Index) return;
            var job = e.RowIndex < _engine.Jobs.Count ? _engine.Jobs[e.RowIndex] : null;
            _grid.Cursor = job?.Status == "Completed" ? Cursors.Hand : Cursors.Default;
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
        _updateStatus.Text = "รุ่นที่ติดตั้ง v0.2.1 · Build 4";
        footer.Controls.Add(_updateStatus, 0, 2);
        Controls.Add(footer);
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
            try { _engine.Add(url, _folder.Text.Trim(), int.Parse((string)_parts.SelectedItem!), SelectedQuality()); }
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
        1 => "1080", 2 => "720", 3 => "480", 4 => "AudioMP3", _ => "Best"
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
                _updateStatus.Text = "รุ่นที่ติดตั้ง v0.2.1 · Build 4 — ไม่มีรุ่นใหม่กว่า";
                if (manual) MessageBox.Show(this, "โปรแกรมเป็นรุ่นล่าสุด หรือใหม่กว่ารุ่นที่เผยแพร่แล้ว",
                    "ตรวจสอบอัปเดต", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
            _updateStatus.Text = $"มีอัปเดต v{release.Version} · Build {release.Build} — กดตรวจสอบอัปเดตเพื่อดาวน์โหลด";
            if (MessageBox.Show(this,
                $"พบ X-Stage Download Manager v{release.Version} Build {release.Build}\\n" +
                $"ขนาดไฟล์ประมาณ {release.Size / 1024.0 / 1024.0:0.0} MB\\n" +
                "เปิดลิงก์ติดตั้ง EXE จาก GitHub Releases หรือไม่?\\n" +
                "โปรแกรมจะไม่ติดตั้งทับหรือปิดงานดาวน์โหลดโดยอัตโนมัติ",
                "พบอัปเดตใหม่", MessageBoxButtons.YesNo, MessageBoxIcon.Information) == DialogResult.Yes)
                Process.Start(new ProcessStartInfo(release.Url) { UseShellExecute = true });
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or
                                     System.Text.Json.JsonException or IOException)
        {
            if (IsDisposed) return;
            _updateStatus.Text = "ตรวจสอบอัปเดตไม่ได้ (สามารถดาวน์โหลดไฟล์ต่อได้ตามปกติ)";
            if (manual) MessageBox.Show(this, ex.Message, "ตรวจสอบอัปเดตไม่สำเร็จ",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
        finally { _checkingUpdates = false; }
    }

    private void ShowCompletedMenu(DownloadJob job, Rectangle cellBounds)
    {
        using var menu = new ContextMenuStrip();
        menu.Items.Add("เปิดไฟล์", null, (_, _) => OpenCompletedFile(job));
        menu.Items.Add("เปิดโฟลเดอร์ที่บันทึก", null, (_, _) => OpenCompletedFolder(job));
        menu.Show(_grid, new Point(cellBounds.Left + 12, cellBounds.Bottom));
        // Menu lifetime is managed by its owner once the popup closes.
        menu.AutoClose = true;
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
        if (job is null) return;
        var path = job.Status == "Completed" && File.Exists(job.CompletedPath)
            ? job.CompletedPath : job.Folder;
        try
        {
            if (File.Exists(path) || Directory.Exists(path))
                Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });
            else MessageBox.Show(this, "ยังไม่พบไฟล์หรือโฟลเดอร์ปลายทาง", "X-Stage");
        }
        catch (Exception ex) { MessageBox.Show(this, ex.Message, "เปิดไฟล์ไม่ได้"); }
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
            row.Cells["File"].Style.Font = new Font("Segoe UI", 10,
                job.Status == "Completed" ? FontStyle.Bold | FontStyle.Underline : FontStyle.Regular);
            row.Cells["Status"].Style.ForeColor = job.Status == "Completed"
                ? Color.FromArgb(16, 132, 81) : Color.FromArgb(31, 42, 60);
            row.Cells["Size"].Value = job.TotalBytes < 0 ? "ไม่ทราบ" : FormatBytes(job.TotalBytes);
            row.Cells["Progress"].Value = job.Kind == "Video"
                ? job.VideoPercent.ToString("0.0") + "%"
                : job.TotalBytes > 0
                    ? (100.0 * current / job.TotalBytes).ToString("0.0") + "%"
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
            _details.Text = "วางลิงก์ YouTube / TikTok / Facebook Reels · เลือกคุณภาพหรือ MP3 · รองรับไฟล์ทั่วไปเช่นเดิม";
            return;
        }
        _details.Text = job.Status == "Failed"
            ? $"ข้อผิดพลาด: {job.Error}   ·   กด เริ่ม / ต่อ เพื่อลองอีกครั้ง"
            : job.Kind == "Video"
                ? $"{SocialVideoDownloader.Platform(job.Url)} · คุณภาพ {job.VideoQuality} · {job.Url} · บันทึกที่ {job.Folder}"
                : $"{job.Url}   ·   บันทึกที่ {job.Folder}";
    }

    private void PaintProgress(object? sender, DataGridViewCellPaintingEventArgs e)
    {
        if (e.RowIndex < 0 || e.ColumnIndex != _grid.Columns["Progress"].Index) return;
        e.PaintBackground(e.CellBounds, true);
        var job = e.RowIndex < _engine.Jobs.Count ? _engine.Jobs[e.RowIndex] : null;
        if (job is not null && (job.TotalBytes > 0 || job.Kind == "Video"))
        {
            var progress = job.Kind == "Video"
                ? Math.Clamp(job.VideoPercent / 100.0, 0, 1)
                : Math.Clamp(Interlocked.Read(ref job.DownloadedBytes) /
                    (double)job.TotalBytes, 0, 1);
            var rectangle = new Rectangle(e.CellBounds.X + 9, e.CellBounds.Y + 10,
                Math.Max(1, e.CellBounds.Width - 18), 20);
            using var bg = new SolidBrush(Color.FromArgb(229, 236, 245));
            using var fg = new SolidBrush(Color.FromArgb(32, 133, 222));
            e.Graphics.FillRectangle(bg, rectangle);
            e.Graphics.FillRectangle(fg, rectangle.X, rectangle.Y,
                (int)Math.Round(rectangle.Width * progress), rectangle.Height);
            TextRenderer.DrawText(e.Graphics, (progress * 100).ToString("0.0") + "%",
                new Font("Segoe UI", 8, FontStyle.Bold), rectangle,
                progress > .52 ? Color.White : Color.FromArgb(25, 70, 117),
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
