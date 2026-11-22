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
    private readonly Dictionary<string, TreeNode> _categoryNodes = new();
    private TableLayoutPanel? _workspaceRoot;
    private Panel? _entryShell;
    private bool _inputVisible;
    private string _categoryFilter = "all";
    private List<DownloadJob> _visibleJobs = new();
    private string? _sortColumn;
    private bool _sortDescending;
    private ToolStrip? _toolbar;
    private readonly TextBox _jobSearch = new();
    private readonly Dictionary<string, Label> _overviewCounts = new();

    private static readonly Color DarkTop = Color.FromArgb(13, 29, 43);
    private static readonly Color DarkPanel = Color.FromArgb(17, 45, 59);
    private static readonly Color DarkGrid = Color.FromArgb(18, 38, 49);
    private static readonly Color MutedText = Color.FromArgb(178, 191, 211);
    private static readonly Color Accent = Color.FromArgb(47, 204, 179);

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
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 72)); // X-Stage branded masthead
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 60)); // Compact command deck
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 0));  // URL input, expandable
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); // Sidebar + main list
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 84)); // Status and details
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
        header.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 265));
        header.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        header.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        var identity = new TableLayoutPanel
        {
            Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2,
            Padding = new Padding(17, 6, 2, 5), BackColor = DarkTop
        };
        identity.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        identity.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));
        identity.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        identity.Controls.Add(new Label
        {
            Text = "X-STAGE",
            Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft,
            Font = new Font("Segoe UI", 20, FontStyle.Bold),
            ForeColor = Accent, AutoEllipsis = true
        }, 0, 0);
        identity.Controls.Add(new Label
        {
            Text = "DOWNLOAD  /  COMMAND CENTER",
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
            Dock = DockStyle.Fill, AutoSize = false, Height = 72,
            Padding = new Padding(2, 20, 5, 10),
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

        var addUrl = Action("เพิ่มลิงก์ (Ctrl+N)", (_, _) => ShowAddUrlFromClipboard());
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
            foreach (var name in _engine.GetQueueNames())
            {
                var queueName = name;
                selectQueue.DropDownItems.Add(Action(queueName,
                    (_, _) => WithSelectedJob(j => AssignJobQueue(j, queueName))));
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

        menu.Items.Add(Menu("สื่อ",
            Action("เพิ่มลิงก์วิดีโอ...", (_, _) => ShowAddUrlFromClipboard()),
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
            Action("ดูข้อผิดพลาดของรายการ...",
                (_, _) => WithSelectedJob(ShowJobError)),
            Action("เปิดบันทึกข้อผิดพลาดวิดีโอ...",
                (_, _) => WithSelectedJob(job =>
                {
                    if (job.Kind == "Video") OpenVideoLog(job);
                })),
            new ToolStripSeparator(),
            Action("แสดงเฉพาะวิดีโอ", (_, _) => SelectCategory("video"))));

        menu.Items.Add(Menu("ไฟล์",
            Action("เปิดไฟล์ / โฟลเดอร์", (_, _) => OpenSelected()),
            renameFile,
            new ToolStripSeparator(),
            Action("ลบรายการจากประวัติ", (_, _) => RemoveSelectedJob()),
            Action("ลบเฉพาะประวัติที่เสร็จแล้ว", (_, _) => ClearCompletedHistory())));
        menu.Items.Add(Menu("ตั้งค่า",
            Action("ประสิทธิภาพ / การเชื่อมต่อ...", (_, _) => ConfigurePerformance()),
            Action("จำนวนครั้งลองใหม่...", (_, _) => ConfigureNetworkRetry()),
            Action("รับดาวน์โหลดจาก Chrome / Edge...", (_, _) => SetupBrowserIntegration()),
            new ToolStripSeparator(),
            Action("ตรวจสอบอัปเดต", async (_, _) => await CheckForUpdatesAsync(true))));
        menu.Items.Add(Menu("มุมมอง",
            Action("งานทั้งหมด", (_, _) => SelectCategory("all")),
            Action("กำลังดาวน์โหลด", (_, _) => SelectCategory("active")),
            Action("รอคิว", (_, _) => SelectCategory("queued")),
            Action("ข้อผิดพลาด", (_, _) => SelectCategory("failed")),
            Action("ดาวน์โหลดเสร็จแล้ว", (_, _) => SelectCategory("completed")),
            new ToolStripSeparator(),
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
            Dock = DockStyle.Fill, AutoSize = false, Height = 60,
            GripStyle = ToolStripGripStyle.Hidden,
            LayoutStyle = ToolStripLayoutStyle.HorizontalStackWithOverflow,
            BackColor = DarkPanel, ForeColor = Color.White,
            RenderMode = ToolStripRenderMode.System,
            ImageScalingSize = new Size(22, 22),
            Padding = new Padding(15, 6, 10, 6),
            Font = new Font("Segoe UI", 9, FontStyle.Bold)
        };
        void Button(string label, string symbol, Color color, EventHandler callback, string tooltip)
        {
            var item = new ToolStripButton
            {
                Text = label, Image = DrawToolbarGlyph(symbol, color),
                DisplayStyle = ToolStripItemDisplayStyle.ImageAndText,
                TextImageRelation = TextImageRelation.ImageBeforeText,
                ImageAlign = ContentAlignment.MiddleLeft,
                TextAlign = ContentAlignment.MiddleLeft,
                AutoSize = false, Size = new Size(label.Length > 12 ? 150 : 118, 44),
                Margin = new Padding(0, 0, 5, 0), Padding = new Padding(8, 3, 7, 3),
                ToolTipText = tooltip, ForeColor = Color.White, BackColor = DarkTop
            };
            item.Click += callback;
            bar.Items.Add(item);
        }
        Button("＋ เพิ่มงาน", "add", Accent,
            (_, _) => ShowAddUrlFromClipboard(), "เพิ่ม URL หรือวิดีโอ โดยไม่เริ่มอัตโนมัติจากคลิปบอร์ด");
        Button("▶ เริ่ม / ต่อ", "play", Color.FromArgb(140, 193, 255),
            (_, _) => SelectedAction(_engine.Start), "เริ่มงานที่เลือก");
        Button("Ⅱ พัก", "pause", Color.FromArgb(245, 185, 125),
            (_, _) => SelectedAction(_engine.Pause), "พักงานที่เลือก");
        Button("◷ คิว", "queue", Color.FromArgb(228, 204, 153),
            (_, _) => SelectCategory("queued"), "ดูรายการที่กำลังรอคิว");
        Button("⚙ ความเร็ว", "gauge", Color.FromArgb(165, 186, 244),
            (_, _) => ConfigurePerformance(), "ตั้งค่าความเร็วและจำนวนงานพร้อมกัน");
        Button("↧ เบราว์เซอร์", "browser", Color.FromArgb(137, 216, 255),
            (_, _) => SetupBrowserIntegration(), "ตั้งค่าการรับดาวน์โหลดจาก Chrome / Edge");
        _toolbar = bar;
        return bar;
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

    private SplitContainer CreateDownloadWorkspace()
    {
        var split = new SplitContainer
        {
            Dock = DockStyle.Fill, Orientation = Orientation.Vertical,
            Size = new Size(1000, 600), // ensure min-panel sizes before assigning splitter
            FixedPanel = FixedPanel.Panel1, SplitterWidth = 5,
            Panel1MinSize = 150, Panel2MinSize = 360,
            SplitterDistance = 212, BackColor = Color.FromArgb(62, 73, 90)
        };
        var side = split.Panel1;
        side.BackColor = DarkPanel;
        var section = new Label
        {
            Text = "  X-STAGE  /  คลังงาน", Dock = DockStyle.Top, Height = 41,
            TextAlign = ContentAlignment.MiddleLeft,
            Font = new Font("Segoe UI", 10, FontStyle.Bold),
            ForeColor = Color.White, BackColor = Color.FromArgb(42, 48, 63)
        };
        side.Controls.Add(_categories);
        side.Controls.Add(section);
        _categories.Dock = DockStyle.Fill;
        _categories.BorderStyle = BorderStyle.None;
        _categories.ImageList = _categoryIcons;
        foreach (var (key, glyph) in new (string Key, string Glyph)[]
        {
            ("all", "folder"), ("active", "play"), ("queued", "queue"),
            ("incomplete", "pause"), ("failed", "alert"),
            ("completed", "check"), ("type", "folder"), ("video", "video"),
            ("music", "file"), ("document", "file"), ("program", "settings"),
            ("archive", "folder"), ("other", "file")
        })
        {
            using var icon = DrawToolbarGlyph(glyph, GlyphColor(glyph));
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
            Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 3,
            BackColor = DarkGrid, Padding = Padding.Empty, Margin = Padding.Empty
        };
        desk.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        desk.RowStyles.Add(new RowStyle(SizeType.Absolute, 82));
        desk.RowStyles.Add(new RowStyle(SizeType.Absolute, 48));
        desk.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        desk.Controls.Add(CreateOverviewTiles(), 0, 0);

        var filterBar = new TableLayoutPanel
        {
            Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 1,
            BackColor = DarkGrid, Padding = Padding.Empty
        };
        filterBar.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        filterBar.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 250));
        filterBar.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        filterBar.Controls.Add(new Label
        {
            Text = "  TRANSFER ACTIVITY  /  รายการดาวน์โหลด",
            Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft,
            ForeColor = Color.FromArgb(227, 238, 246),
            Font = new Font("Segoe UI", 10, FontStyle.Bold),
            AutoEllipsis = true
        }, 0, 0);
        _jobSearch.Dock = DockStyle.Fill;
        _jobSearch.Margin = new Padding(0, 9, 13, 9);
        _jobSearch.BorderStyle = BorderStyle.FixedSingle;
        _jobSearch.BackColor = Color.FromArgb(235, 244, 249);
        _jobSearch.ForeColor = Color.FromArgb(23, 43, 56);
        _jobSearch.PlaceholderText = "ค้นหาชื่อไฟล์ ลิงก์ หรือคิว";
        _jobSearch.AccessibleName = "ค้นหารายการดาวน์โหลด";
        _jobSearch.TextChanged += (_, _) => RefreshRows();
        filterBar.Controls.Add(_jobSearch, 1, 0);
        desk.Controls.Add(filterBar, 0, 1);
        desk.Controls.Add(_grid, 0, 2);
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

    private void CreateDownloadGrid()
    {
        _grid.Dock = DockStyle.Fill;
        _grid.Margin = Padding.Empty;
        _grid.BackgroundColor = DarkGrid;
        _grid.BorderStyle = BorderStyle.None;
        _grid.GridColor = Color.FromArgb(68, 75, 89);
        _grid.ColumnHeadersHeight = 40;
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
        _grid.RowTemplate.Height = 38;
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
        Column("File", "ชื่อไฟล์", 345, 210);
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
            BackColor = Color.FromArgb(39, 47, 61),
            Padding = new Padding(16, 6, 16, 6),
            ColumnCount = 1, RowCount = 3
        };
        footer.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        footer.RowStyles.Add(new RowStyle(SizeType.Absolute, 25));
        footer.RowStyles.Add(new RowStyle(SizeType.Absolute, 22));
        footer.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        _summary.Dock = DockStyle.Fill;
        _summary.Font = new Font("Segoe UI", 9, FontStyle.Bold);
        _summary.ForeColor = Color.FromArgb(223, 236, 250);
        _details.Dock = DockStyle.Fill;
        _details.ForeColor = MutedText;
        _details.Font = new Font("Segoe UI", 9);
        _details.AutoEllipsis = true;
        _updateStatus.Dock = DockStyle.Fill;
        _updateStatus.ForeColor = Color.FromArgb(126, 194, 248);
        _updateStatus.Font = new Font("Segoe UI", 8, FontStyle.Bold);
        _updateStatus.Text = "รุ่นที่ติดตั้ง v" + UpdateChecker.CurrentVersion +
                             " · Build " + UpdateChecker.CurrentBuild;
        footer.Controls.Add(_summary, 0, 0);
        footer.Controls.Add(_details, 0, 1);
        footer.Controls.Add(_updateStatus, 0, 2);
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
