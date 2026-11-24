using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

namespace XStageDownloadManager;

// Original X-Stage workspace: branded command deck, distinct visual language.
// Commands are wired to the existing engine and updater, not dummy controls.
public sealed partial class MainForm
{
    private readonly TreeView _categories = new();
    private readonly ImageList _categoryIcons = new() { ImageSize = new Size(20, 20), ColorDepth = ColorDepth.Depth32Bit };
    // WinForms ImageList can defer materializing source images until its
    // native handle exists. Keep originals alive until the whole form closes.
    private readonly List<Image> _categoryIconSources = new();
    private readonly Dictionary<string, TreeNode> _categoryNodes = new();
    private TableLayoutPanel? _workspaceRoot;
    private Panel? _entryShell;
    private bool _inputVisible;
    private SmartSyncForm? _smartSyncWindow;
    private bool _videoEntryRequested;
    private string _categoryFilter = "all";
    private List<DownloadJob> _visibleJobs = new();
    private string? _sortColumn;
    private bool _sortDescending;
    private ToolStrip? _toolbar;
    private readonly TextBox _jobSearch = new();
    private readonly Dictionary<string, Label> _overviewCounts = new();
    private readonly Dictionary<string, Image> _rowIcons = new();

    private static readonly Color DarkTop = Color.FromArgb(4, 19, 43);
    private static readonly Color DarkPanel = Color.FromArgb(6, 29, 60);
    private static readonly Color DarkGrid = Color.FromArgb(5, 24, 49);
    private static readonly Color MutedText = Color.FromArgb(176, 203, 233);
    private static readonly Color Accent = Color.FromArgb(0, 189, 255);

    private void CreateXStageWorkspace()
    {
        SuspendLayout();
        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            RowCount = 5, ColumnCount = 1,
            Margin = Padding.Empty, Padding = Padding.Empty,
            BackColor = DarkTop
        };
        root.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 48)); // branded menu
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 90)); // large-icon command deck
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 0));  // URL input, expandable
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); // Sidebar + main list
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 38)); // live status strip
        _workspaceRoot = root;

        root.Controls.Add(CreateBrandHeader(), 0, 0);
        root.Controls.Add(CreateIconToolbar(), 0, 1);
        root.Controls.Add(CreateQuickEntry(), 0, 2);
        root.Controls.Add(CreateDownloadWorkspace(), 0, 3);
        root.Controls.Add(CreateStatusBar(), 0, 4);
        Controls.Add(root);
        ResumeLayout(true);
    }

    // A branded masthead, with compact command menus to the right.
    // Unlike a classic download-manager menu/toolbar stack, the identity
    // and navigation are integrated into one workspace header.
    private Control CreateBrandHeader()
    {
        var header = new TableLayoutPanel
        {
            Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 1,
            BackColor = DarkTop, Margin = Padding.Empty, Padding = Padding.Empty
        };
        header.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 215));
        header.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        header.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        var identity = new TableLayoutPanel
        {
            Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2,
            Padding = new Padding(17, 6, 2, 5), BackColor = DarkTop
        };
        identity.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        identity.RowStyles.Add(new RowStyle(SizeType.Absolute, 30));
        identity.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        identity.Controls.Add(new Label
        {
            Text = "X-STAGE  /  DM",
            Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft,
            Font = new Font("Segoe UI", 15, FontStyle.Bold),
            ForeColor = Accent, AutoEllipsis = true
        }, 0, 0);
        identity.Controls.Add(new Label
        {
            Text = "DOWNLOAD MANAGER",
            Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft,
            Font = new Font("Segoe UI", 8, FontStyle.Bold),
            ForeColor = MutedText, AutoEllipsis = true
        }, 0, 1);
        header.Controls.Add(identity, 0, 0);
        header.Controls.Add(CreateMenuBar(), 1, 0);
        return header;
    }

    private MenuStrip CreateMenuBar()
    {
        var menu = new MenuStrip
        {
            Dock = DockStyle.Fill, AutoSize = false, Height = 48,
            Padding = new Padding(2, 7, 5, 3),
            BackColor = DarkTop, ForeColor = Color.White,
            Font = new Font("Segoe UI", 9, FontStyle.Regular),
            GripStyle = ToolStripGripStyle.Hidden,
            ImageScalingSize = new Size(18, 18),
            Renderer = new ToolStripProfessionalRenderer(new XStageMenuColors()),
            LayoutStyle = ToolStripLayoutStyle.HorizontalStackWithOverflow
        };
        ToolStripMenuItem Action(string name, EventHandler handler)
        {
            var glyph = MenuGlyph(name);
            var item = new ToolStripMenuItem(name)
            {
                Image = DrawToolbarGlyph(glyph, GlyphColor(glyph)),
                ForeColor = Color.FromArgb(236, 246, 251),
                BackColor = DarkPanel,
                ToolTipText = name
            };
            item.Click += handler;
            return item;
        }
        ToolStripMenuItem Menu(string title, params ToolStripItem[] children)
        {
            var glyph = MenuGlyph(title);
            var item = new ToolStripMenuItem(title)
            {
                Image = DrawToolbarGlyph(glyph, GlyphColor(glyph)),
                ForeColor = Color.White,
                BackColor = DarkTop
            };
            item.DropDownItems.AddRange(children);
            return item;
        }

        var addUrl = Action("เพิ่มลิงก์ (Ctrl+N)", (_, _) => ToggleQuickEntry(false));
        addUrl.ShortcutKeys = Keys.Control | Keys.N;
        var renameFile = Action("เปลี่ยนชื่อไฟล์ที่เสร็จแล้ว (F2)",
            (_, _) => WithSelectedJob(RenameCompletedJob));
        menu.Items.Add(Menu("งาน",
            addUrl,
            new ToolStripSeparator(),
            Action("เริ่ม / ต่อรายการที่เลือก", (_, _) => SelectedAction(_engine.Start)),
            Action("พักรายการที่เลือก", (_, _) => SelectedAction(_engine.Pause)),
            Action("ทำต่อทุกงานที่ยังไม่เสร็จ", (_, _) => StartIncomplete()),
            Action("พักทั้งหมด", (_, _) => _engine.PauseAll())));

        var priority = Menu("ลำดับความสำคัญ",
            Action("สูง", (_, _) => WithSelectedJob(j => SetPriority(j, 0))),
            Action("ปกติ", (_, _) => WithSelectedJob(j => SetPriority(j, 1))),
            Action("ต่ำ", (_, _) => WithSelectedJob(j => SetPriority(j, 2))));
        var selectQueue = new ToolStripMenuItem("ย้ายไปคิว...");
        selectQueue.DropDownOpening += (_, _) =>
        {
            selectQueue.DropDownItems.Clear();
            var selectedQueue = Selected()?.QueueName;
            foreach (var name in _engine.GetQueueNames())
            {
                var queueName = name;
                var choice = new ToolStripMenuItem(queueName)
                {
                    Checked = string.Equals(
                        string.IsNullOrWhiteSpace(selectedQueue) ? "ทั่วไป" : selectedQueue.Trim(),
                        queueName, StringComparison.OrdinalIgnoreCase),
                    ForeColor = Color.FromArgb(236, 246, 251),
                    BackColor = DarkPanel
                };
                choice.Click += (_, _) => WithSelectedJob(j => AssignJobQueue(j, queueName));
                selectQueue.DropDownItems.Add(choice);
            }
        };
        menu.Items.Add(Menu("คิว",
            priority,
            new ToolStripSeparator(),
            selectQueue,
            Action("สร้างคิวสำหรับรายการที่เลือก...",
                (_, _) => WithSelectedJob(CreateJobQueue)),
            Action("เปลี่ยนชื่อคิวปัจจุบัน...",
                (_, _) => WithSelectedJob(RenameJobQueue)),
            new ToolStripSeparator(),
            Action("จำกัดความเร็ว HTTP รายไฟล์...",
                (_, _) => WithSelectedJob(ConfigureFileSpeed)),
            Action("ตั้งค่าความเร็วรวมและจำนวนงาน...",
                (_, _) => ConfigurePerformance())));

        // Subscription services use their official protected players. Never pass
        // DRM playback URLs to yt-dlp, FFmpeg, or the download queue.
        var streamingServices = Menu("รับชมสตรีมมิง (เว็บไซต์ทางการ)",
            Action("Netflix", (_, _) => OpenOfficialStreamingSite("https://www.netflix.com/")),
            Action("Disney+", (_, _) => OpenOfficialStreamingSite("https://www.disneyplus.com/")),
            Action("Prime Video", (_, _) => OpenOfficialStreamingSite("https://www.primevideo.com/")),
            Action("YouTube", (_, _) => OpenOfficialStreamingSite("https://www.youtube.com/")),
            Action("Twitch", (_, _) => OpenOfficialStreamingSite("https://www.twitch.tv/")));
        menu.Items.Add(Menu("สื่อ",
            streamingServices,
            new ToolStripSeparator(),
            Action("บันทึกไลฟ์สด · ตัดคลิปตามช่วงหยุดพูด...",
                (_, _) => OpenLiveCapture()),
            new ToolStripSeparator(),
            Action("เพิ่มลิงก์วิดีโอ...", (_, _) => ToggleQuickEntry(true)),
            Action("ดาวน์โหลดวิดีโอใหม่ / เปลี่ยนคุณภาพ...",
                (_, _) => WithSelectedJob(job =>
                {
                    if (job.Kind == "Video" && job.Status is not ("Running" or "Queued"))
                        RedownloadVideo(job);
                    else
                        MessageBox.Show(this,
                            "เลือกรายการวิดีโอที่ไม่ได้กำลังทำงานหรือรอคิว",
                            "X-Stage", MessageBoxButtons.OK, MessageBoxIcon.Information);
                })),
            new ToolStripSeparator(),
            Action("แสดงเฉพาะวิดีโอ", (_, _) => SelectCategory("video"))));

        menu.Items.Add(Menu("ไฟล์",
            Action("เปิดไฟล์ / โฟลเดอร์", (_, _) => OpenSelected()),
            renameFile,
            new ToolStripSeparator(),
            Action("ลบรายการจากประวัติ", (_, _) => RemoveSelectedJob()),
            Action("ลบเฉพาะประวัติที่เสร็จแล้ว", (_, _) => ClearCompletedHistory())));
        var diagnostics = Menu("ตรวจสอบปัญหา",
            Action("ดูสาเหตุข้อผิดพลาดของงานที่เลือก...",
                (_, _) => WithSelectedJob(ShowJobError)),
            Action("เปิดบันทึกการดาวน์โหลดวิดีโอ...",
                (_, _) => WithSelectedJob(job =>
                {
                    if (job.Kind == "Video") OpenVideoLog(job);
                    else MessageBox.Show(this, "เลือกรายการวิดีโอก่อน",
                        "X-Stage", MessageBoxButtons.OK, MessageBoxIcon.Information);
                })));
        menu.Items.Add(Menu("ตั้งค่า",
            Action("ประสิทธิภาพ / การเชื่อมต่อ...", (_, _) => ConfigurePerformance()),
            Action("จำนวนครั้งลองใหม่...", (_, _) => ConfigureNetworkRetry()),
            Action("Smart Sync — Google Drive...", (_, _) => ToggleSmartSync()),
            Action("Smart Sync — เมื่อเปิดโปรแกรม...", (_, _) => ConfigureSmartSyncStartup()),
            Action("รับดาวน์โหลดจาก Chrome / Edge...", (_, _) => SetupBrowserIntegration()),
            new ToolStripSeparator(),
            diagnostics,
            Action("ตรวจสอบอัปเดต", async (_, _) => await CheckForUpdatesAsync(true))));
        var findJob = Action("ค้นหารายการ (Ctrl+F)", (_, _) => _jobSearch.Focus());
        findJob.ShortcutKeys = Keys.Control | Keys.F;
        var fileTypes = Menu("แสดงตามประเภทไฟล์",
            Action("วิดีโอ", (_, _) => SelectCategory("video")),
            Action("เพลงและเสียง", (_, _) => SelectCategory("music")),
            Action("เอกสาร", (_, _) => SelectCategory("document")),
            Action("โปรแกรม", (_, _) => SelectCategory("program")),
            Action("ไฟล์บีบอัด", (_, _) => SelectCategory("archive")),
            Action("อื่น ๆ", (_, _) => SelectCategory("other")));
        menu.Items.Add(Menu("มุมมอง",
            Action("งานทั้งหมด", (_, _) => SelectCategory("all")),
            Action("กำลังดาวน์โหลด", (_, _) => SelectCategory("active")),
            Action("รอคิว", (_, _) => SelectCategory("queued")),
            Action("ข้อผิดพลาด", (_, _) => SelectCategory("failed")),
            Action("ดาวน์โหลดเสร็จแล้ว", (_, _) => SelectCategory("completed")),
            new ToolStripSeparator(),
            fileTypes,
            findJob,
            Action("แสดง/ซ่อนช่องเพิ่ม URL", (_, _) => ShowInputPanel(!_inputVisible))));
        menu.Items.Add(Menu("ช่วยเหลือ",
            Action("เกี่ยวกับ X-Stage Download Manager", (_, _) =>
                MessageBox.Show(this,
                    "X-Stage Download Manager v" + UpdateChecker.CurrentVersion +
                    " Build " + UpdateChecker.CurrentBuild +
                    "\nเครื่องมือดาวน์โหลด พร้อมระบบจัดคิว สื่อ และอัปเดต",
                    "เกี่ยวกับโปรแกรม", MessageBoxButtons.OK, MessageBoxIcon.Information))));
        return menu;
    }

    private void WithSelectedJob(Action<DownloadJob> action)
    {
        var job = Selected();
        if (job is null)
        {
            MessageBox.Show(this, "กรุณาเลือกรายการดาวน์โหลดจากตารางก่อน",
                "X-Stage", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }
        action(job);
    }

    private ToolStrip CreateIconToolbar()
    {
        var bar = new ToolStrip
        {
            Dock = DockStyle.Fill, AutoSize = false, Height = 94,
            GripStyle = ToolStripGripStyle.Hidden,
            LayoutStyle = ToolStripLayoutStyle.HorizontalStackWithOverflow,
            Renderer = new ToolStripProfessionalRenderer(new XStageMenuColors()),
            BackColor = DarkPanel, ForeColor = Color.White,
            ImageScalingSize = new Size(33, 33),
            Padding = new Padding(12, 5, 10, 5),
            Font = new Font("Segoe UI", 9, FontStyle.Bold)
        };
        void Button(string name, string glyph, Color color,
            EventHandler action, string help, int width = 104)
        {
            var item = new ToolStripButton
            {
                Text = name, Image = DrawToolbarGlyph(glyph, color),
                DisplayStyle = ToolStripItemDisplayStyle.ImageAndText,
                TextImageRelation = TextImageRelation.ImageAboveText,
                ImageAlign = ContentAlignment.MiddleCenter,
                TextAlign = ContentAlignment.MiddleCenter,
                AutoSize = false, Size = new Size(width, 77),
                Margin = new Padding(0, 0, 3, 0), Padding = new Padding(4, 2, 4, 2),
                BackColor = DarkTop, ForeColor = Color.White,
                ToolTipText = help, AccessibleName = name,
                Overflow = name == "Smart Sync" ? ToolStripItemOverflow.Never : ToolStripItemOverflow.AsNeeded
            };
            item.Click += action;
            bar.Items.Add(item);
        }
        Button("เพิ่มงาน", "add", Color.FromArgb(59, 228, 137),
            (_, _) => ToggleQuickEntry(false), "คลิกเปิด/ซ่อนช่องเพิ่ม URL (Ctrl+N)");
        Button("Smart Sync", "sync", Color.FromArgb(59, 228, 137),
            (_, _) => ToggleSmartSync(), "เปิด/ซ่อน Smart Sync Google Drive", 116);
        Button("เริ่ม", "play", Color.FromArgb(98, 166, 255),
            (_, _) => SelectedAction(_engine.Start), "เริ่ม / ต่อรายการที่เลือก");
        Button("พัก", "pause", Color.FromArgb(142, 187, 255),
            (_, _) => SelectedAction(_engine.Pause), "พักรายการที่เลือก");
        Button("หยุดทั้งหมด", "pause", Color.FromArgb(250, 142, 158),
            (_, _) => _engine.PauseAll(), "พักทุกงาน ไม่ลบข้อมูล");
        Button("ลบ", "trash", Color.FromArgb(252, 110, 131),
            (_, _) => RemoveSelectedJob(), "ลบประวัติของรายการที่เลือก");
        Button("จัดคิว", "queue", Color.FromArgb(97, 205, 248),
            (_, _) => WithSelectedJob(CreateJobQueue), "สร้างคิวและย้ายงานที่เลือก");
        Button("จำกัดความเร็ว", "gauge", Color.FromArgb(94, 222, 126),
            (_, _) => ConfigurePerformance(), "ตั้งค่าความเร็วและจำนวนงาน", 125);
        Button("ดาวน์โหลดวิดีโอ", "video", Color.FromArgb(175, 130, 246),
            (_, _) => ToggleQuickEntry(true), "คลิกเปิด/ซ่อนช่องดาวน์โหลดวิดีโอ", 129);
        Button("บันทึกไลฟ์สด", "video", Color.FromArgb(236, 130, 207),
            (_, _) => OpenLiveCapture(), "เปิดโหมดบันทึกไลฟ์และตัดคลิปตามช่วงเงียบ", 118);
        Button("วิเคราะห์ปัญหา", "alert", Color.FromArgb(148, 176, 252),
            (_, _) => ShowDiagnosticsPanel(), "รายละเอียดข้อผิดพลาดจริง", 124);
        Button("ตั้งค่า", "settings", Color.FromArgb(178, 201, 255),
            (_, _) => ShowInputPanel(true, true), "โฟลเดอร์และจำนวนส่วน");
        _toolbar = bar;
        return bar;
    }

    private void OpenOfficialStreamingSite(string url)
    {
        // Only hard-coded HTTPS home pages are accepted; user-supplied
        // playback URLs and account tokens never enter the download engine.
        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri) ||
            uri.Scheme != Uri.UriSchemeHttps ||
            uri.UserInfo.Length != 0 ||
            !new[] { "www.netflix.com", "www.disneyplus.com",
                     "www.primevideo.com", "www.youtube.com", "www.twitch.tv" }
                .Contains(uri.IdnHost, StringComparer.OrdinalIgnoreCase) ||
            uri.AbsolutePath != "/" || uri.Query.Length != 0 || uri.Fragment.Length != 0)
            throw new ArgumentException("Unsupported streaming site.", nameof(url));
        try
        {
            Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute = true });
        }
        catch (Exception ex) when (ex is System.ComponentModel.Win32Exception
                                   or InvalidOperationException)
        {
            MessageBox.Show(this, "ไม่สามารถเปิดเบราว์เซอร์ได้: " + ex.Message,
                "X-Stage Streaming", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private void OpenLiveCapture()
    {
        // Non-modal so the existing DownloadEngine, SQLite checkpoints and
        // running file jobs remain responsive while a live session records.
        var window = new LiveStreamCaptureForm(_folder.Text);
        window.Show(this);
    }

    private void ShowDiagnosticsPanel()
    {
        if (_transferSplit is not null && _transferSplit.Panel2Collapsed &&
            _transferSplit.Height >= 335)
            _transferSplit.Panel2Collapsed = false;
        if (_previewTabs is not null && !_previewTabs.IsDisposed)
            _previewTabs.SelectedIndex = 2;
    }

    private static string MenuGlyph(string label)
    {
        if (label.Contains("เพิ่ม") || label.Contains("สร้างคิว")) return "add";
        if (label.Contains("เริ่ม") || label.Contains("ต่อรายการ") || label.Contains("ทำต่อ")) return "play";
        if (label.Contains("พัก") || label.Contains("หยุด")) return "pause";
        if (label.Contains("คิว") || label.Contains("ลำดับ")) return "queue";
        if (label.Contains("ความเร็ว") || label.Contains("ประสิทธิภาพ")) return "gauge";
        if (label.Contains("เบราว์เซอร์") || label.Contains("Chrome")) return "browser";
        if (label.Contains("ข้อผิดพลาด") || label.Contains("บันทึกข้อผิดพลาด")) return "alert";
        if (label.Contains("วิดีโอ") || label.Contains("สื่อ")) return "video";
        if (label.Contains("อัปเดต") || label.Contains("ลองใหม่")) return "refresh";
        if (label.Contains("ลบ")) return "trash";
        if (label.Contains("เปิดไฟล์") || label.Contains("โฟลเดอร์")) return "folder";
        if (label.Contains("เสร็จ")) return "check";
        if (label.Contains("ไฟล์")) return "file";
        if (label.Contains("มุมมอง") || label.Contains("แสดง")) return "eye";
        if (label.Contains("ตั้งค่า")) return "settings";
        if (label.Contains("ช่วยเหลือ") || label.Contains("เกี่ยวกับ")) return "info";
        if (label.Contains("สูง") || label.Contains("ต่ำ") || label.Contains("ปกติ")) return "queue";
        return "file";
    }

    private static Color GlyphColor(string glyph) => glyph switch
    {
        "pause" or "queue" => Color.FromArgb(240, 195, 127),
        "trash" or "alert" => Color.FromArgb(248, 152, 152),
        "play" => Color.FromArgb(145, 198, 250),
        "check" => Color.FromArgb(140, 227, 172),
        "video" or "browser" => Color.FromArgb(143, 202, 254),
        _ => Accent
    };

    // These symbols are original antialiased vector drawings, not icons
    // copied from any third-party download manager. They scale consistently
    // even when Windows does not have a particular symbol font installed.
    private static Image DrawToolbarGlyph(string glyph, Color color)
    {
        var image = new Bitmap(40, 40);
        using var graphics = Graphics.FromImage(image);
        graphics.Clear(Color.Transparent);
        graphics.SmoothingMode = SmoothingMode.AntiAlias;
        graphics.PixelOffsetMode = PixelOffsetMode.HighQuality;
        using var pen = new Pen(color, 2.8f)
        {
            StartCap = LineCap.Round, EndCap = LineCap.Round, LineJoin = LineJoin.Round
        };
        using var brush = new SolidBrush(color);

        switch (glyph)
        {
            case "add":
                graphics.DrawEllipse(pen, 6, 6, 28, 28);
                graphics.DrawLine(pen, 20, 12, 20, 28);
                graphics.DrawLine(pen, 12, 20, 28, 20);
                break;
            case "play":
                graphics.FillPolygon(brush, new[]
                {
                    new Point(13, 9), new Point(31, 20), new Point(13, 31)
                });
                break;
            case "pause":
                graphics.FillRectangle(brush, 11, 10, 6, 20);
                graphics.FillRectangle(brush, 23, 10, 6, 20);
                break;
            case "queue":
                for (var i = 0; i < 3; i++)
                {
                    var y = 12 + i * 8;
                    graphics.FillEllipse(brush, 7, y - 2, 4, 4);
                    graphics.DrawLine(pen, 16, y, 33, y);
                }
                break;
            case "gauge":
                graphics.DrawArc(pen, 7, 8, 26, 26, 180, 180);
                graphics.DrawLine(pen, 20, 25, 28, 15);
                graphics.FillEllipse(brush, 17, 22, 6, 6);
                break;
            case "browser":
                graphics.DrawRectangle(pen, 7, 8, 26, 24);
                graphics.DrawLine(pen, 7, 15, 33, 15);
                graphics.FillEllipse(brush, 10, 11, 2.5f, 2.5f);
                graphics.FillEllipse(brush, 15, 11, 2.5f, 2.5f);
                break;
            case "video":
                graphics.DrawRectangle(pen, 7, 9, 26, 22);
                graphics.FillPolygon(brush, new[]
                {
                    new Point(17, 15), new Point(27, 20), new Point(17, 25)
                });
                break;
            case "folder":
                graphics.DrawLines(pen, new[]
                {
                    new Point(6, 14), new Point(6, 10), new Point(17, 10),
                    new Point(21, 14), new Point(34, 14), new Point(34, 30),
                    new Point(6, 30), new Point(6, 14)
                });
                break;
            case "sync":
                graphics.DrawArc(pen, 6, 6, 28, 28, 195, 145);
                graphics.DrawLines(pen, new[] { new Point(27, 6), new Point(34, 13), new Point(25, 14) });
                graphics.DrawArc(pen, 6, 6, 28, 28, 15, 145);
                graphics.DrawLines(pen, new[] { new Point(13, 34), new Point(6, 27), new Point(15, 26) });
                break;
            case "refresh":
                graphics.DrawArc(pen, 9, 9, 22, 22, 35, 280);
                graphics.DrawLine(pen, 29, 12, 32, 20);
                graphics.DrawLine(pen, 32, 20, 24, 18);
                break;
            case "trash":
                graphics.DrawRectangle(pen, 12, 14, 16, 20);
                graphics.DrawLine(pen, 9, 11, 31, 11);
                graphics.DrawLine(pen, 17, 7, 23, 7);
                graphics.DrawLine(pen, 17, 19, 17, 28);
                graphics.DrawLine(pen, 23, 19, 23, 28);
                break;
            case "check":
                graphics.DrawEllipse(pen, 6, 6, 28, 28);
                graphics.DrawLines(pen, new[]
                {
                    new Point(12, 21), new Point(18, 27), new Point(29, 14)
                });
                break;
            case "alert":
                graphics.DrawEllipse(pen, 6, 6, 28, 28);
                graphics.DrawLine(pen, 20, 12, 20, 23);
                graphics.FillEllipse(brush, 18, 28, 4, 4);
                break;
            case "eye":
                graphics.DrawArc(pen, 6, 13, 28, 15, 195, 150);
                graphics.DrawArc(pen, 6, 13, 28, 15, 15, 150);
                graphics.FillEllipse(brush, 17, 17, 6, 6);
                break;
            case "settings":
                graphics.DrawEllipse(pen, 12, 12, 16, 16);
                graphics.DrawEllipse(pen, 17, 17, 6, 6);
                for (var i = 0; i < 8; i++)
                {
                    var angle = i * Math.PI / 4;
                    var x1 = 20 + (int)Math.Round(Math.Cos(angle) * 11);
                    var y1 = 20 + (int)Math.Round(Math.Sin(angle) * 11);
                    var x2 = 20 + (int)Math.Round(Math.Cos(angle) * 16);
                    var y2 = 20 + (int)Math.Round(Math.Sin(angle) * 16);
                    graphics.DrawLine(pen, x1, y1, x2, y2);
                }
                break;
            case "info":
                graphics.DrawEllipse(pen, 6, 6, 28, 28);
                graphics.DrawLine(pen, 20, 18, 20, 28);
                graphics.FillEllipse(brush, 18, 11, 4, 4);
                break;
            default:
                graphics.DrawRectangle(pen, 10, 6, 20, 28);
                graphics.DrawLine(pen, 14, 15, 26, 15);
                graphics.DrawLine(pen, 14, 21, 26, 21);
                break;
        }
        return image;
    }

    private sealed class XStageMenuColors : ProfessionalColorTable
    {
        public override Color ToolStripDropDownBackground => DarkPanel;
        public override Color ImageMarginGradientBegin => DarkPanel;
        public override Color ImageMarginGradientMiddle => DarkPanel;
        public override Color ImageMarginGradientEnd => DarkPanel;
        public override Color MenuItemSelected => Color.FromArgb(31, 79, 91);
        public override Color MenuItemSelectedGradientBegin => Color.FromArgb(31, 79, 91);
        public override Color MenuItemSelectedGradientEnd => Color.FromArgb(31, 79, 91);
        public override Color MenuItemBorder => Accent;
        public override Color MenuItemPressedGradientBegin => DarkPanel;
        public override Color MenuItemPressedGradientEnd => DarkPanel;
    }

    private Panel CreateQuickEntry()
    {
        var shell = new Panel
        {
            Dock = DockStyle.Fill, BackColor = Color.FromArgb(241, 246, 251),
            Padding = Padding.Empty, Visible = false, AutoScroll = true
        };
        _entryShell = shell;
        var entry = new TableLayoutPanel
        {
            Dock = DockStyle.Top, Height = 166,
            BackColor = Color.FromArgb(242, 247, 252),
            Padding = new Padding(16, 8, 16, 5),
            ColumnCount = 4, RowCount = 5
        };
        entry.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 92));
        entry.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        entry.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 118));
        entry.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 135));
        for (int row = 0; row < 5; row++)
            entry.RowStyles.Add(new RowStyle(SizeType.Percent, 20));
        entry.Controls.Add(MakeLabel("ลิงก์ / วิดีโอ"), 0, 0);
        entry.Controls.Add(MakeLabel("บันทึกที่"), 0, 1);
        SetupText(_url, "URL สำหรับดาวน์โหลดไฟล์หรือวิดีโอ");
        SetupText(_folder, "ตำแหน่งโฟลเดอร์สำหรับบันทึกไฟล์");
        _url.KeyDown += (_, e) =>
        {
            if (e.KeyCode == Keys.Enter) { e.SuppressKeyPress = true; AddUrls(); }
        };
        entry.Controls.Add(_url, 1, 0);
        entry.Controls.Add(_folder, 1, 1);
        entry.Controls.Add(MakeButton("วางลิงก์", false, (_, _) =>
        {
            try { if (Clipboard.ContainsText()) _url.Text = Clipboard.GetText(); }
            catch (System.Runtime.InteropServices.ExternalException)
            {
                MessageBox.Show(this, "อ่านคลิปบอร์ดไม่ได้", "X-Stage");
            }
        }), 2, 0);
        entry.Controls.Add(MakeButton("＋ ดาวน์โหลด", true, (_, _) =>
        {
            AddUrls();
            if (string.IsNullOrWhiteSpace(_url.Text)) ShowInputPanel(false);
        }), 3, 0);
        entry.Controls.Add(MakeButton("เลือกโฟลเดอร์", false, (_, _) =>
        {
            using var picker = new FolderBrowserDialog
            {
                Description = "เลือกโฟลเดอร์ปลายทาง",
                SelectedPath = Directory.Exists(_folder.Text) ? _folder.Text :
                    Environment.GetFolderPath(Environment.SpecialFolder.UserProfile)
            };
            if (picker.ShowDialog(this) == DialogResult.OK) _folder.Text = picker.SelectedPath;
        }), 3, 1);
        entry.Controls.Add(new Label
        {
            Text = "HTTPS / HTTP", Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleCenter,
            ForeColor = Color.FromArgb(105, 123, 150)
        }, 2, 1);
        entry.Controls.Add(MakeLabel("จำนวนส่วน"), 0, 2);
        _parts.Dock = DockStyle.Fill;
        _parts.DropDownStyle = ComboBoxStyle.DropDownList;
        _parts.Margin = new Padding(3, 7, 6, 7);
        entry.Controls.Add(_parts, 1, 2);
        entry.Controls.Add(new Label
        {
            Text = "1–32 ส่วน", Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleCenter,
            ForeColor = Color.FromArgb(96, 113, 139)
        }, 2, 2);
        entry.Controls.Add(MakeButton("ใช้กับรายการ", false, (_, _) => ApplyPartsToSelected()), 3, 2);
        entry.Controls.Add(MakeLabel("คุณภาพวิดีโอ"), 0, 3);
        _videoQuality.Dock = DockStyle.Fill;
        _videoQuality.DropDownStyle = ComboBoxStyle.DropDownList;
        _videoQuality.Margin = new Padding(3, 7, 6, 7);
        entry.Controls.Add(_videoQuality, 1, 3);
        entry.Controls.Add(new Label
        {
            Text = "YT · TikTok · FB", Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleCenter,
            ForeColor = Color.FromArgb(80, 102, 131)
        }, 2, 3);
        entry.Controls.Add(MakeLabel("รูปแบบไฟล์"), 0, 4);
        _outputFormat.Dock = DockStyle.Fill;
        _outputFormat.DropDownStyle = ComboBoxStyle.DropDownList;
        _outputFormat.Margin = new Padding(3, 7, 6, 7);
        entry.Controls.Add(_outputFormat, 1, 4);
        entry.Controls.Add(new Label
        {
            Text = "MP4 เริ่มต้น", Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleCenter,
            ForeColor = Color.FromArgb(13, 117, 84)
        }, 2, 4);
        _inputLayout = entry;
        _videoOptionControls = entry.Controls.Cast<Control>()
            .Where(c => entry.GetPositionFromControl(c).Row >= 3).ToArray();
        shell.Controls.Add(entry);
        return shell;
    }

    private SplitContainer? _transferSplit;
    private readonly Label _transferHeading = new();

    private SplitContainer CreateDownloadWorkspace()
    {
        var split = new SplitContainer
        {
            Dock = DockStyle.Fill, Orientation = Orientation.Vertical,
            Size = new Size(1000, 600), // ensure min-panel sizes before assigning splitter
            FixedPanel = FixedPanel.Panel1, SplitterWidth = 5,
            Panel1MinSize = 185, Panel2MinSize = 360,
            SplitterDistance = 250, BackColor = Color.FromArgb(27, 70, 96)
        };
        var side = split.Panel1;
        side.BackColor = DarkPanel;
        var section = new Label
        {
            Text = "  คลังดาวน์โหลด", Dock = DockStyle.Top, Height = 37,
            TextAlign = ContentAlignment.MiddleLeft,
            Font = new Font("Segoe UI", 10, FontStyle.Bold),
            ForeColor = Color.White, BackColor = DarkPanel
        };
        var brand = new Panel
        {
            Dock = DockStyle.Top, Height = 80,
            BackColor = Color.FromArgb(8, 33, 56)
        };
        brand.Paint += (_, e) =>
        {
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using var xFont = new Font("Segoe UI", 30, FontStyle.Bold);
            using var titleFont = new Font("Segoe UI", 12, FontStyle.Bold);
            using var captionFont = new Font("Segoe UI", 8, FontStyle.Italic);
            using var xBrush = new SolidBrush(Color.FromArgb(30, 225, 240));
            using var titleBrush = new SolidBrush(Color.White);
            using var captionBrush = new SolidBrush(Accent);
            e.Graphics.DrawString("X", xFont, xBrush, 10, 8);
            e.Graphics.DrawString("X-Stage", titleFont, titleBrush, 67, 16);
            e.Graphics.DrawString("Download Manager", captionFont, captionBrush, 67, 42);
        };
        var usageSummary = new Button
        {
            Dock = DockStyle.Bottom, Height = 43,
            Text = "▥  สรุปการใช้งาน",
            TextAlign = ContentAlignment.MiddleLeft,
            Font = new Font("Segoe UI", 10, FontStyle.Bold),
            ForeColor = Color.White, BackColor = Color.FromArgb(13, 50, 78),
            FlatStyle = FlatStyle.Flat, Cursor = Cursors.Hand,
            AccessibleName = "สรุปจำนวนรายการดาวน์โหลดทั้งหมด"
        };
        usageSummary.FlatAppearance.BorderColor = Color.FromArgb(31, 95, 138);
        usageSummary.Click += (_, _) =>
        {
            var jobs = _engine.Jobs.ToArray();
            var active = jobs.Count(job => job.Status == "Running");
            var queued = jobs.Count(job => job.Status == "Queued");
            var completed = jobs.Count(job => job.Status == "Completed");
            var failed = jobs.Count(job => job.Status == "Failed");
            MessageBox.Show(this,
                $"รายการทั้งหมด: {jobs.Length:N0}\n" +
                $"กำลังดาวน์โหลด: {active:N0}\n" +
                $"รอคิว: {queued:N0}\n" +
                $"สำเร็จ: {completed:N0}\n" +
                $"ข้อผิดพลาด: {failed:N0}",
                "สรุปการใช้งาน · X-Stage", MessageBoxButtons.OK,
                MessageBoxIcon.Information);
        };
        side.Controls.Add(_categories);
        side.Controls.Add(section);
        side.Controls.Add(brand);
        side.Controls.Add(usageSummary);

        _categories.Dock = DockStyle.Fill;
        _categories.BorderStyle = BorderStyle.None;
        _categories.ImageList = _categoryIcons;
        foreach (var (key, glyph) in new (string Key, string Glyph)[]
        {
            ("all", "folder"), ("active", "play"), ("queued", "queue"),
            ("incomplete", "pause"), ("failed", "alert"),
            ("priority-high", "queue"), ("priority-normal", "queue"),
            ("priority-low", "queue"),
            ("completed", "check"), ("type", "folder"), ("video", "video"),
            ("music", "file"), ("document", "file"), ("program", "settings"),
            ("archive", "folder"), ("other", "file")
        })
        {
            var icon = DrawToolbarGlyph(glyph, GlyphColor(glyph));
            _categoryIconSources.Add(icon);
            _categoryIcons.Images.Add(key, icon);
        }
        _categories.ShowLines = false;
        _categories.ShowRootLines = false;
        _categories.HideSelection = false;
        _categories.FullRowSelect = true;
        _categories.BackColor = DarkPanel;
        _categories.ForeColor = Color.FromArgb(230, 239, 249);
        _categories.Font = new Font("Segoe UI", 10);
        _categories.ItemHeight = 33;
        _categories.Indent = 17;
        _categories.AfterSelect += (_, e) =>
        {
            if (e.Node?.Tag is string filter)
            {
                _categoryFilter = filter;
                RefreshRows();
            }
        };
        var all = AddCategory(null, "all", "ดาวน์โหลดทั้งหมด");
        AddCategory(all, "active", "กำลังดาวน์โหลด");
        AddCategory(all, "queued", "รอคิว");
        AddCategory(all, "incomplete", "ยังไม่เสร็จ");
        AddCategory(all, "failed", "ข้อผิดพลาด");
        AddCategory(null, "completed", "เสร็จแล้ว");
        var priorityGroups = new TreeNode("คิวดาวน์โหลด")
        {
            ForeColor = MutedText, NodeFont = new Font("Segoe UI", 10, FontStyle.Bold),
            ImageKey = "queue", SelectedImageKey = "queue"
        };
        _categories.Nodes.Add(priorityGroups);
        AddCategory(priorityGroups, "priority-normal", "คิวปกติ");
        var urgent = AddCategory(priorityGroups, "priority-high", "ความสำคัญสูง");
        urgent.ForeColor = Color.FromArgb(251, 152, 159);
        AddCategory(priorityGroups, "priority-low", "ความสำคัญต่ำ");
        var type = new TreeNode("ประเภทไฟล์")
        {
            ForeColor = MutedText, NodeFont = new Font("Segoe UI", 10, FontStyle.Bold),
            ImageKey = "type", SelectedImageKey = "type"
        };
        _categories.Nodes.Add(type);
        AddCategory(type, "video", "วิดีโอ");
        AddCategory(type, "music", "เพลงและเสียง");
        AddCategory(type, "document", "เอกสาร");
        AddCategory(type, "program", "โปรแกรม");
        AddCategory(type, "archive", "ไฟล์บีบอัด");
        AddCategory(type, "other", "อื่น ๆ");
        all.Expand();
        priorityGroups.Expand();
        type.Expand();

        CreateDownloadGrid();
        split.Panel2.Controls.Add(CreateTransferDesk());
        _categories.SelectedNode = all;
        return split;
    }

    private Control CreateTransferDesk()
    {
        var desk = new TableLayoutPanel
        {
            Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2,
            BackColor = DarkGrid, Padding = Padding.Empty, Margin = Padding.Empty
        };
        desk.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        desk.RowStyles.Add(new RowStyle(SizeType.Absolute, 48));
        desk.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        var heading = new TableLayoutPanel
        {
            Dock = DockStyle.Fill, ColumnCount = 4, RowCount = 1,
            BackColor = Color.FromArgb(12, 45, 80),
            Padding = new Padding(7, 4, 8, 3)
        };
        heading.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        heading.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 240));
        heading.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 42));
        heading.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 42));
        heading.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        _transferHeading.Text = "▣  รายการดาวน์โหลด";
        _transferHeading.Dock = DockStyle.Fill;
        _transferHeading.TextAlign = ContentAlignment.MiddleLeft;
        _transferHeading.Font = new Font("Segoe UI", 11, FontStyle.Bold);
        _transferHeading.ForeColor = Color.White;
        _transferHeading.AutoEllipsis = true;
        heading.Controls.Add(_transferHeading, 0, 0);

        _jobSearch.Dock = DockStyle.Fill;
        _jobSearch.Margin = new Padding(0, 7, 6, 7);
        _jobSearch.BorderStyle = BorderStyle.FixedSingle;
        _jobSearch.BackColor = Color.FromArgb(18, 40, 67);
        _jobSearch.ForeColor = Color.White;
        _jobSearch.PlaceholderText = "ค้นหางาน... (Ctrl+F)";
        _jobSearch.AccessibleName = "ค้นหารายการดาวน์โหลด";
        _jobSearch.TextChanged += (_, _) => RefreshRows();
        heading.Controls.Add(_jobSearch, 1, 0);

        Button SmallAction(string name, string help, EventHandler? action)
        {
            var button = new Button
            {
                Text = name, Dock = DockStyle.Fill,
                Margin = new Padding(2, 5, 2, 4),
                BackColor = DarkPanel, ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat,
                Cursor = Cursors.Hand, Font = new Font("Segoe UI", 12, FontStyle.Bold),
                AccessibleName = help
            };
            button.FlatAppearance.BorderColor = Accent;
            if (action is not null) button.Click += action;
            return button;
        }
        var filter = SmallAction("▼", "กรองรายการดาวน์โหลด", null);
        filter.Click += (_, _) =>
        {
            var choices = new ContextMenuStrip();
            choices.Closed += (_, _) => choices.Dispose();
            foreach (var (caption, key) in new (string Caption, string Key)[]
            {
                ("ทั้งหมด", "all"), ("กำลังดาวน์โหลด", "active"),
                ("รอคิว", "queued"), ("ผิดพลาด", "failed"),
                ("เสร็จสิ้น", "completed"), ("วิดีโอ", "video"),
                ("เสียง", "music"), ("เอกสาร", "document"),
                ("โปรแกรม", "program"), ("ไฟล์บีบอัด", "archive")
            })
            {
                var value = key;
                choices.Items.Add(caption, null, (_, _) => SelectCategory(value));
            }
            choices.Show(filter, new Point(0, filter.Height));
        };
        heading.Controls.Add(filter, 2, 0);
        heading.Controls.Add(SmallAction("☷", "แสดงหรือซ่อนคอลัมน์ขั้นสูง", (_, _) =>
        {
            var show = !_grid.Columns["FileType"].Visible;
            foreach (var key in new[] { "FileType", "Added", "Parts", "Description" })
                _grid.Columns[key].Visible = show;
        }), 3, 0);
        desk.Controls.Add(heading, 0, 0);

        var split = new SplitContainer
        {
            Dock = DockStyle.Fill, Orientation = Orientation.Horizontal,
            Size = new Size(1000, 540), SplitterWidth = 5,
            Panel1MinSize = 95, Panel2MinSize = 105,
            SplitterDistance = 305, BackColor = Color.FromArgb(22, 83, 127)
        };
        _transferSplit = split;
        split.Panel1.Controls.Add(_grid);
        split.Panel2.Controls.Add(CreateLivePreview());
        split.SizeChanged += (_, _) =>
        {
            // The window can pass through tiny/zero client sizes when
            // minimized, changing DPI, or opening the URL panel. Calculate
            // from the CLIENT area and respect both panel minima before
            // writing SplitterDistance; invalid transient dimensions must
            // never reach native WinForms layout.
            if (split.IsDisposed || split.Disposing) return;
            var height = split.ClientSize.Height;
            var minimum = split.Panel1MinSize + split.Panel2MinSize + split.SplitterWidth;
            if (height < Math.Max(335, minimum + 10))
            {
                if (!split.Panel2Collapsed) split.Panel2Collapsed = true;
                return;
            }
            if (split.Panel2Collapsed) split.Panel2Collapsed = false;
            var maximum = height - split.Panel2MinSize - split.SplitterWidth;
            if (maximum <= split.Panel1MinSize) return;
            var wanted = Math.Clamp((int)(height * .58),
                split.Panel1MinSize, maximum);
            if (wanted != split.SplitterDistance)
                split.SplitterDistance = wanted;
        };
        desk.Controls.Add(split, 0, 1);
        return desk;
    }

    private Control CreateOverviewTiles()
    {
        var overview = new TableLayoutPanel
        {
            Dock = DockStyle.Fill, ColumnCount = 4, RowCount = 1,
            BackColor = DarkGrid, Padding = new Padding(9, 7, 9, 6)
        };
        for (var i = 0; i < 4; i++)
            overview.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 25));
        overview.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        var items = new (string Key, string Caption, Color Color)[]
        {
            ("active", "กำลังถ่ายโอน", Accent),
            ("queued", "รอคิว", Color.FromArgb(243, 202, 139)),
            ("completed", "เสร็จสมบูรณ์", Color.FromArgb(141, 224, 168)),
            ("failed", "ต้องตรวจสอบ", Color.FromArgb(255, 158, 158))
        };
        for (var i = 0; i < items.Length; i++)
        {
            var (key, caption, color) = items[i];
            var card = new TableLayoutPanel
            {
                Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2,
                Margin = new Padding(4, 0, 4, 0), Padding = new Padding(12, 3, 8, 3),
                BackColor = DarkPanel, Cursor = Cursors.Hand,
                AccessibleName = caption + " — แสดงรายการ"
            };
            card.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            card.RowStyles.Add(new RowStyle(SizeType.Percent, 58));
            card.RowStyles.Add(new RowStyle(SizeType.Percent, 42));
            var count = new Label
            {
                Dock = DockStyle.Fill, Text = "0",
                ForeColor = color, Font = new Font("Segoe UI", 17, FontStyle.Bold),
                TextAlign = ContentAlignment.MiddleLeft, Cursor = Cursors.Hand
            };
            var name = new Label
            {
                Dock = DockStyle.Fill, Text = caption,
                ForeColor = MutedText, Font = new Font("Segoe UI", 9),
                TextAlign = ContentAlignment.MiddleLeft, AutoEllipsis = true,
                Cursor = Cursors.Hand
            };
            card.Click += (_, _) => SelectCategory(key);
            count.Click += (_, _) => SelectCategory(key);
            name.Click += (_, _) => SelectCategory(key);
            card.Controls.Add(count, 0, 0);
            card.Controls.Add(name, 0, 1);
            overview.Controls.Add(card, i, 0);
            _overviewCounts[key] = count;
        }
        return overview;
    }

    private void UpdateOverviewCounts(DownloadJob[] jobs)
    {
        foreach (var (key, count) in _overviewCounts)
        {
            var value = jobs.Count(job => key switch
            {
                "active" => job.Status == "Running",
                "queued" => job.Status == "Queued",
                "completed" => job.Status == "Completed",
                "failed" => job.Status == "Failed",
                _ => false
            });
            var next = value.ToString("N0");
            if (count.Text != next) count.Text = next;
        }
    }

    private bool MatchesSearch(DownloadJob job)
    {
        var term = _jobSearch.Text.Trim();
        return term.Length == 0 ||
            job.Name.Contains(term, StringComparison.OrdinalIgnoreCase) ||
            job.Url.Contains(term, StringComparison.OrdinalIgnoreCase) ||
            (job.QueueName?.Contains(term, StringComparison.OrdinalIgnoreCase) ?? false);
    }

    private TreeNode AddCategory(TreeNode? parent, string key, string title)
    {
        var node = new TreeNode(title)
        {
            Tag = key, ImageKey = key, SelectedImageKey = key
        };
        if (parent is null) _categories.Nodes.Add(node);
        else parent.Nodes.Add(node);
        _categoryNodes[key] = node;
        return node;
    }

    private Image GetRowIcon(DownloadJob job)
    {
        var kind = CategoryOf(job);
        if (_rowIcons.TryGetValue(kind, out var image)) return image;
        var glyph = kind switch
        {
            "video" => "video", "music" => "file", "document" => "file",
            "program" => "settings", "archive" => "folder", _ => "file"
        };
        image = DrawToolbarGlyph(glyph, GlyphColor(glyph));
        _rowIcons.Add(kind, image);
        return image;
    }

    private void CreateDownloadGrid()
    {
        _grid.Dock = DockStyle.Fill;
        _grid.Margin = Padding.Empty;
        _grid.BackgroundColor = DarkGrid;
        _grid.BorderStyle = BorderStyle.None;
        _grid.GridColor = Color.FromArgb(68, 75, 89);
        _grid.ColumnHeadersHeight = 42;
        _grid.ColumnHeadersHeightSizeMode = DataGridViewColumnHeadersHeightSizeMode.DisableResizing;
        _grid.EnableHeadersVisualStyles = false;
        _grid.ColumnHeadersDefaultCellStyle.BackColor = Color.FromArgb(43, 48, 62);
        _grid.ColumnHeadersDefaultCellStyle.ForeColor = Color.White;
        _grid.ColumnHeadersDefaultCellStyle.SelectionBackColor = Color.FromArgb(43, 48, 62);
        _grid.ColumnHeadersDefaultCellStyle.Font = new Font("Segoe UI", 9, FontStyle.Bold);
        _grid.DefaultCellStyle.BackColor = DarkGrid;
        _grid.DefaultCellStyle.ForeColor = Color.FromArgb(228, 235, 246);
        _grid.DefaultCellStyle.SelectionBackColor = Color.FromArgb(48, 91, 141);
        _grid.DefaultCellStyle.SelectionForeColor = Color.White;
        _grid.AlternatingRowsDefaultCellStyle.BackColor = Color.FromArgb(35, 40, 51);
        _grid.RowTemplate.Height = 39;
        _grid.RowHeadersVisible = false;
        _grid.SelectionMode = DataGridViewSelectionMode.FullRowSelect;
        _grid.MultiSelect = false;
        _grid.ReadOnly = true;
        _grid.AllowUserToAddRows = false;
        _grid.AllowUserToDeleteRows = false;
        _grid.AllowUserToResizeRows = false;
        _grid.AllowUserToOrderColumns = true;
        _grid.AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.None;
        _grid.ScrollBars = ScrollBars.Both;

        void Column(string key, string title, int width, int minimum = 65)
        {
            _grid.Columns.Add(new DataGridViewTextBoxColumn
            {
                Name = key, HeaderText = title, Width = width, MinimumWidth = minimum,
                SortMode = DataGridViewColumnSortMode.Programmatic,
                DefaultCellStyle = new DataGridViewCellStyle { Padding = new Padding(5, 0, 4, 0) }
            });
        }
        Column("No", "#", 44, 40);
        _grid.Columns.Add(new DataGridViewImageColumn
        {
            Name = "KindIcon", HeaderText = "", Width = 34, MinimumWidth = 31,
            ImageLayout = DataGridViewImageCellLayout.Zoom,
            SortMode = DataGridViewColumnSortMode.NotSortable
        });
        Column("File", "ชื่อไฟล์", 300, 210);
        Column("FileType", "ชนิดไฟล์", 104, 85);
        Column("Queue", "คิว", 57, 47);
        Column("Size", "ขนาด", 112);
        Column("Progress", "ความคืบหน้า", 154, 115);
        Column("Status", "สถานะ", 202, 120);
        Column("ETA", "เวลาที่เหลือ", 117, 92);
        Column("Speed", "อัตราการถ่ายโอน", 124, 105);
        Column("Added", "วันที่ดาวน์โหลด", 137, 112);
        Column("Parts", "จำนวนส่วน", 115, 90);
        Column("Description", "คำอธิบาย", 157, 115);
        Column("QueueName", "คิว", 130, 90);
        var order = new[]
        {
            "No", "KindIcon", "File", "Size", "Progress", "Speed",
            "ETA", "Status", "QueueName", "FileType", "Queue",
            "Added", "Parts", "Description"
        };
        for (var index = 0; index < order.Length; index++)
            _grid.Columns[order[index]].DisplayIndex = index;
        foreach (var key in new[] { "FileType", "Queue", "Added", "Parts", "Description" })
            _grid.Columns[key].Visible = false;
        _grid.ColumnHeaderMouseClick += (_, e) =>
        {
            if (e.ColumnIndex < 0) return;
            var key = _grid.Columns[e.ColumnIndex].Name;
            if (_sortColumn == key)
                _sortDescending = !_sortDescending;
            else
            {
                _sortColumn = key;
                _sortDescending = false;
            }

            // Native WinForms sort arrow; no change to the persisted queue.
            foreach (DataGridViewColumn column in _grid.Columns)
                column.HeaderCell.SortGlyphDirection = SortOrder.None;
            _grid.Columns[e.ColumnIndex].HeaderCell.SortGlyphDirection =
                _sortDescending ? SortOrder.Descending : SortOrder.Ascending;
            RefreshRows();
        };
        _grid.KeyDown += (_, e) =>
        {
            if (e.KeyCode != Keys.F2) return;
            e.Handled = true;
            e.SuppressKeyPress = true;
            var job = Selected();
            if (job is not null) RenameCompletedJob(job);
        };
        _grid.CellPainting += PaintProgress;
        _grid.SelectionChanged += (_, _) => UpdateDetails();
        _grid.CellClick += (_, e) =>
        {
            if (e.RowIndex < 0 || e.ColumnIndex != _grid.Columns["File"].Index) return;
            var job = VisibleJobAt(e.RowIndex);
            if (job is not null)
                ShowCompletedMenu(job,
                    _grid.GetCellDisplayRectangle(e.ColumnIndex, e.RowIndex, false));
        };
        _grid.CellMouseEnter += (_, e) =>
        {
            _grid.Cursor = e.RowIndex >= 0 &&
                e.ColumnIndex == _grid.Columns["File"].Index
                ? Cursors.Hand : Cursors.Default;
        };
        _grid.CellMouseLeave += (_, _) => _grid.Cursor = Cursors.Default;
        _grid.CellDoubleClick += (_, e) =>
        {
            if (e.RowIndex >= 0 && e.ColumnIndex != _grid.Columns["File"].Index)
                OpenSelected();
        };
    }

    private Control CreateStatusBar()
    {
        var footer = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 3, RowCount = 1,
            BackColor = Color.FromArgb(9, 28, 48),
            Padding = new Padding(14, 4, 12, 4)
        };
        footer.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 48));
        footer.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 35));
        footer.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 17));
        footer.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        _summary.Dock = DockStyle.Fill;
        _summary.ForeColor = Color.FromArgb(222, 238, 248);
        _summary.Font = new Font("Segoe UI", 9, FontStyle.Bold);
        _summary.TextAlign = ContentAlignment.MiddleLeft;
        _summary.AutoEllipsis = true;
        _details.Dock = DockStyle.Fill;
        _details.ForeColor = Color.FromArgb(132, 220, 235);
        _details.Font = new Font("Segoe UI", 9);
        _details.TextAlign = ContentAlignment.MiddleRight;
        _details.AutoEllipsis = true;
        _updateStatus.Dock = DockStyle.Fill;
        _updateStatus.ForeColor = Accent;
        _updateStatus.Font = new Font("Segoe UI", 8, FontStyle.Bold);
        _updateStatus.TextAlign = ContentAlignment.MiddleRight;
        _updateStatus.AutoEllipsis = true;
        _updateStatus.Text = "v" + UpdateChecker.CurrentVersion +
                             " · Build " + UpdateChecker.CurrentBuild;
        footer.Controls.Add(_summary, 0, 0);
        footer.Controls.Add(_details, 1, 0);
        footer.Controls.Add(_updateStatus, 2, 0);
        return footer;
    }

    // Accept only standalone valid HTTP/HTTPS download URLs. Never paste
    // arbitrary clipboard text (passwords, file paths, or unrelated notes).
    // Supports multiple copied links; does not trigger the download itself.
    internal static string ExtractClipboardUrls(string? clipboard)
    {
        if (string.IsNullOrWhiteSpace(clipboard)) return "";
        var parts = clipboard.Split(
            new[] { '\r', '\n', ' ', '\t' },
            StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (parts.Length == 0 || parts.Length > 200 ||
            parts.Any(part => !DownloadEngine.TryParseUrl(part, out _)))
            return "";
        return string.Join(Environment.NewLine, parts);
    }

    private void ConfigureSmartSyncStartup()
    {
        try
        {
            using var dialog = new Form
            {
                Text = "Smart Sync — เมื่อเปิดโปรแกรม",
                StartPosition = FormStartPosition.CenterParent,
                FormBorderStyle = FormBorderStyle.FixedDialog,
                MaximizeBox = false, MinimizeBox = false,
                ClientSize = new Size(460, 205)
            };
            var layout = new TableLayoutPanel
            {
                Dock = DockStyle.Fill, Padding = new Padding(14), ColumnCount = 1,
                RowCount = 4
            };
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 28));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 38));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));
            var choices = new ComboBox { Dock = DockStyle.Fill, DropDownStyle = ComboBoxStyle.DropDownList };
            choices.Items.AddRange(new object[] { "เริ่มด้วยตนเอง", "ถามก่อนทำงานต่อ", "ทำงานต่ออัตโนมัติ" });
            choices.SelectedIndex = (int)_engine.SmartSyncStartup;
            layout.Controls.Add(new Label { Text = "เมื่อเปิด X-Stage Download Manager", AutoSize = true }, 0, 0);
            layout.Controls.Add(choices, 0, 1);
            layout.Controls.Add(new Label { Dock = DockStyle.Fill,
                Text = "บันทึกตัวเลือกไว้สำหรับ Smart Sync เท่านั้น ระบบรับส่งไฟล์ Drive และการกู้คืนงานกำลังพัฒนา งานที่หยุดเองหรือรอตรวจสอบจะไม่เริ่มอัตโนมัติ" }, 0, 2);
            var buttons = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.RightToLeft };
            var save = new Button { Text = "บันทึก", DialogResult = DialogResult.OK, AutoSize = true };
            var cancel = new Button { Text = "ยกเลิก", DialogResult = DialogResult.Cancel, AutoSize = true };
            buttons.Controls.Add(save); buttons.Controls.Add(cancel);
            layout.Controls.Add(buttons, 0, 3);
            dialog.Controls.Add(layout); dialog.AcceptButton = save; dialog.CancelButton = cancel;
            if (dialog.ShowDialog(this) == DialogResult.OK && choices.SelectedIndex >= 0)
                _engine.SetSmartSyncStartup((SmartSyncStartupMode)choices.SelectedIndex);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or Microsoft.Data.Sqlite.SqliteException)
        {
            MessageBox.Show(this, "ไม่สามารถบันทึกตัวเลือก Smart Sync ได้", "X-Stage",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private void ConfigureNetworkRetry()
    {
        using var dialog = new Form
        {
            Text = "ตั้งค่าความเสถียรเครือข่าย",
            Width = 430, Height = 225,
            FormBorderStyle = FormBorderStyle.FixedDialog,
            StartPosition = FormStartPosition.CenterParent,
            MaximizeBox = false, MinimizeBox = false,
            BackColor = Color.White
        };
        var caption = new Label
        {
            Text = "จำนวนครั้งที่ลองใหม่อัตโนมัติต่อ Chunk / ไฟล์ (1–10)",
            Left = 22, Top = 19, Width = 365, Height = 31
        };
        var spinner = new NumericUpDown
        {
            Left = 22, Top = 54, Width = 365, Minimum = 1, Maximum = 10,
            Value = _engine.MaxRetryCount
        };
        var note = new Label
        {
            Text = "เน็ตหลุดหรือเซิร์ฟเวอร์ตอบ 429/503 จะลองใหม่แบบหน่วงเวลา\nChunk ที่ได้รับครบแล้วจะไม่ถูกดาวน์โหลดซ้ำ",
            Left = 22, Top = 91, Width = 372, Height = 47,
            ForeColor = Color.FromArgb(81, 102, 125)
        };
        var save = new Button
        {
            Text = "บันทึก", Left = 283, Top = 145, Width = 106, Height = 33,
            DialogResult = DialogResult.OK
        };
        dialog.Controls.AddRange(new Control[] { caption, spinner, note, save });
        dialog.AcceptButton = save;
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        try
        {
            _engine.SetRetryLimit((int)spinner.Value);
        }
        catch (Exception ex) when (ex is IOException or ArgumentOutOfRangeException or
                                   Microsoft.Data.Sqlite.SqliteException)
        {
            MessageBox.Show(this, ex.Message, "บันทึกค่าลองใหม่ไม่สำเร็จ",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private void ToggleSmartSync()
    {
        if (_smartSyncWindow is null || _smartSyncWindow.IsDisposed)
            _smartSyncWindow = new SmartSyncForm();
        if (_smartSyncWindow.Visible) _smartSyncWindow.Hide();
        else { _smartSyncWindow.Show(this); _smartSyncWindow.Activate(); }
    }

    private void ToggleQuickEntry(bool video)
    {
        if (_inputVisible && _videoEntryRequested == video)
        {
            ShowInputPanel(false);
            return;
        }
        _videoEntryRequested = video;
        ShowAddUrlFromClipboard();
    }

    private void ShowAddUrlFromClipboard()
    {
        ShowInputPanel(true);
        // Preserve a link already typed/pasted by the user.
        if (!string.IsNullOrWhiteSpace(_url.Text)) return;
        try
        {
            if (Clipboard.ContainsText())
            {
                var copiedLinks = ExtractClipboardUrls(Clipboard.GetText());
                if (copiedLinks.Length > 0)
                {
                    _url.Text = copiedLinks;
                    _url.SelectionStart = _url.TextLength;
                    _url.SelectionLength = 0;
                }
            }
        }
        catch (System.Runtime.InteropServices.ExternalException)
        {
            // Another app may temporarily lock the Windows clipboard.
            // Leave the editable URL field open for manual paste.
        }
        _url.Focus();
    }

    private void ShowInputPanel(bool visible, bool focusFolder = false)
    {
        if (_workspaceRoot is null || _entryShell is null) return;
        _inputVisible = visible;
        if (visible)
        {
            _entryShell.Visible = true;
            UpdateVideoOptionVisibility();
        }
        else
        {
            _workspaceRoot.RowStyles[2].Height = 0;
            _entryShell.Visible = false;
        }
        if (_toolbar is not null)
        {
            foreach (var item in _toolbar.Items.OfType<ToolStripButton>())
            {
                if (item.Text == "เพิ่มงาน") item.Checked = visible && !_videoEntryRequested;
                if (item.Text == "ดาวน์โหลดวิดีโอ") item.Checked = visible && _videoEntryRequested;
            }
        }
        _workspaceRoot.PerformLayout();
        if (visible)
        {
            if (focusFolder) _folder.Focus();
            else _url.Focus();
        }
    }

    private DownloadJob? VisibleJobAt(int row) =>
        row >= 0 && row < _visibleJobs.Count ? _visibleJobs[row] : null;

    private void SelectCategory(string key)
    {
        if (_categoryNodes.TryGetValue(key, out var node))
        {
            if (_categories.SelectedNode == node)
            {
                _categoryFilter = key;
                RefreshRows();
            }
            else _categories.SelectedNode = node;
            node.EnsureVisible();
        }
    }

    private static string CategoryOf(DownloadJob job)
    {
        var ext = Path.GetExtension(job.Name).ToLowerInvariant();
        if (job.Kind == "Video" && (job.OutputFormat == "mp3" ||
            job.VideoQuality == "AudioMP3")) return "music";
        if (job.Kind == "Video" || ext is ".mp4" or ".mkv" or ".webm" or ".avi" or ".mov" or ".flv")
            return "video";
        if (ext is ".mp3" or ".wav" or ".flac" or ".aac" or ".ogg" or ".m4a")
            return "music";
        if (ext is ".pdf" or ".doc" or ".docx" or ".xlsx" or ".xls" or
                    ".pptx" or ".ppt" or ".txt" or ".csv")
            return "document";
        if (ext is ".exe" or ".msi" or ".msix" or ".apk" or ".deb")
            return "program";
        if (ext is ".zip" or ".rar" or ".7z" or ".tar" or ".gz")
            return "archive";
        return "other";
    }

    private bool InSelectedCategory(DownloadJob job) => _categoryFilter switch
    {
        "all" => true,
        "active" => job.Status == "Running",
        "queued" => job.Status == "Queued",
        "failed" => job.Status == "Failed",
        "priority-high" => job.Priority == 0 && job.Status != "Completed",
        "priority-normal" => job.Priority == 1 && job.Status != "Completed",
        "priority-low" => job.Priority == 2 && job.Status != "Completed",
        "incomplete" => job.Status is "Paused" or "Failed" or "Queued" or "Running",
        "completed" => job.Status == "Completed",
        _ => CategoryOf(job) == _categoryFilter
    };

    private void UpdateCategoryCounts(DownloadJob[] jobs)
    {
        foreach (var (key, node) in _categoryNodes)
        {
            var count = jobs.Count(job => key switch
            {
                "all" => true,
                "active" => job.Status == "Running",
                "queued" => job.Status == "Queued",
                "failed" => job.Status == "Failed",
                "priority-high" => job.Priority == 0 && job.Status != "Completed",
                "priority-normal" => job.Priority == 1 && job.Status != "Completed",
                "priority-low" => job.Priority == 2 && job.Status != "Completed",
                "incomplete" => job.Status is "Paused" or "Failed" or "Queued" or "Running",
                "completed" => job.Status == "Completed",
                _ => CategoryOf(job) == key
            });
            var beforeCount = node.Text.LastIndexOf(" (", StringComparison.Ordinal);
            var prefix = beforeCount >= 0 ? node.Text[..beforeCount] : node.Text;
            var newText = prefix + " (" + count + ")";
            if (node.Text != newText) node.Text = newText;
        }
    }

    private void StartIncomplete()
    {
        foreach (var job in _engine.Jobs.ToArray())
            if (job.Status is "Paused" or "Failed")
                _engine.Start(job);
        RefreshRows();
    }

    private void RemoveSelectedJob()
    {
        var job = Selected();
        if (job is null) return;
        if (MessageBox.Show(this,
            "ลบรายการนี้จากประวัติหรือไม่?\nไฟล์ที่ดาวน์โหลดเสร็จจะยังคงอยู่",
            "ยืนยันการลบ", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes)
            return;
        if (!_engine.Remove(job))
            MessageBox.Show(this,
                "หยุดงานแล้ว กรุณารอให้หยุดสนิทและลบอีกครั้ง",
                "กำลังหยุด", MessageBoxButtons.OK, MessageBoxIcon.Information);
        RefreshRows();
    }

    private void ClearCompletedHistory()
    {
        var finished = _engine.Jobs.Where(j => j.Status == "Completed").ToArray();
        if (finished.Length == 0) return;
        if (MessageBox.Show(this,
            "ลบประวัติที่เสร็จแล้ว " + finished.Length +
            " รายการ?\nไฟล์จริงในโฟลเดอร์ดาวน์โหลดจะไม่ถูกลบ",
            "ยืนยันการลบประวัติ", MessageBoxButtons.YesNo,
            MessageBoxIcon.Question) != DialogResult.Yes) return;
        foreach (var job in finished) _engine.Remove(job);
        RefreshRows();
    }

    private static string EtaLabel(DownloadJob job)
    {
        if (job.Status != "Running" || job.TotalBytes <= 0 ||
            job.SmoothedSpeedBytesPerSecond < 1024) return "—";
        var remain = Math.Max(0, job.TotalBytes - Interlocked.Read(ref job.DownloadedBytes));
        var seconds = remain / job.SmoothedSpeedBytesPerSecond;
        if (seconds > 24 * 3600 * 100) return "—";
        var time = TimeSpan.FromSeconds(seconds);
        return time.TotalHours >= 1 ? $"{(int)time.TotalHours:0}:{time.Minutes:00}:{time.Seconds:00}"
                                    : $"{time.Minutes:00}:{time.Seconds:00}";
    }
}
