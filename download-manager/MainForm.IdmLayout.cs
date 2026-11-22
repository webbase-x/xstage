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
    private readonly Dictionary<string, TreeNode> _categoryNodes = new();
    private TableLayoutPanel? _workspaceRoot;
    private Panel? _entryShell;
    private bool _inputVisible;
    private string _categoryFilter = "all";
    private List<DownloadJob> _visibleJobs = new();
    private string? _sortColumn;
    private bool _sortDescending;
    private ToolStrip? _toolbar;

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
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 31)); // Traditional application menu
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 64)); // X-Stage command deck
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 0));  // URL input, expandable
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); // Sidebar + main list
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 84)); // Status and details
        _workspaceRoot = root;

        root.Controls.Add(CreateMenuBar(), 0, 0);
        root.Controls.Add(CreateIconToolbar(), 0, 1);
        root.Controls.Add(CreateQuickEntry(), 0, 2);
        root.Controls.Add(CreateDownloadWorkspace(), 0, 3);
        root.Controls.Add(CreateStatusBar(), 0, 4);
        Controls.Add(root);
        ResumeLayout(true);
    }

    private MenuStrip CreateMenuBar()
    {
        var menu = new MenuStrip
        {
            Dock = DockStyle.Fill, AutoSize = false, Height = 31,
            Padding = new Padding(12, 2, 8, 0),
            BackColor = DarkTop, ForeColor = Color.White,
            Font = new Font("Segoe UI", 10)
        };
        ToolStripMenuItem Action(string name, EventHandler handler)
        {
            var item = new ToolStripMenuItem(name);
            item.Click += handler;
            return item;
        }
        ToolStripMenuItem Menu(string title, params ToolStripItem[] children)
        {
            var item = new ToolStripMenuItem(title) { ForeColor = Color.White };
            item.DropDownItems.AddRange(children);
            return item;
        }
        var newUrl = Action("＋ เพิ่ม URL (Ctrl+N)", (_, _) => ShowAddUrlFromClipboard());
        newUrl.ShortcutKeys = Keys.Control | Keys.N;
        menu.Items.Add(Menu("งาน",
            newUrl,
            Action("▶ เริ่ม / ต่อ", (_, _) => SelectedAction(_engine.Start)),
            Action("Ⅱ หยุดชั่วคราว", (_, _) => SelectedAction(_engine.Pause)),
            Action("↻ เริ่มงานที่ยังไม่เสร็จทั้งหมด", (_, _) => StartIncomplete()),
            Action("Ⅱ หยุดทั้งหมด", (_, _) => _engine.PauseAll())));
        menu.Items.Add(Menu("ไฟล์",
            Action("เปิดไฟล์ / โฟลเดอร์ของรายการ", (_, _) => OpenSelected()),
            Action("ดาวน์โหลดวิดีโอใหม่ / เปลี่ยนคุณภาพ", (_, _) =>
            {
                var job = Selected();
                if (job?.Kind == "Video") RedownloadVideo(job);
            }),
            Action("ลบรายการที่เลือก", (_, _) => RemoveSelectedJob()),
            Action("ลบประวัติที่ดาวน์โหลดสำเร็จ", (_, _) => ClearCompletedHistory())));
        menu.Items.Add(Menu("การดาวน์โหลด",
            Action("ดาวน์โหลดอัตโนมัติ (Chrome / Edge)", (_, _) => SetupBrowserIntegration()),
            Action("กำหนดจำนวนครั้งลองใหม่...", (_, _) => ConfigureNetworkRetry()),
            Action("ประสิทธิภาพและจำนวนงานพร้อมกัน...", (_, _) => ConfigurePerformance()),
            Action("ตรวจสอบอัปเดต", async (_, _) => await CheckForUpdatesAsync(true))));
        menu.Items.Add(Menu("มุมมอง",
            Action("แสดงทั้งหมด", (_, _) => SelectCategory("all")),
            Action("แสดงที่กำลังดาวน์โหลด", (_, _) => SelectCategory("active")),
            Action("แสดงที่เสร็จแล้ว", (_, _) => SelectCategory("completed")),
            Action("แสดงที่ยังไม่เสร็จ", (_, _) => SelectCategory("incomplete")),
            Action("แสดงวิดีโอ", (_, _) => SelectCategory("video")),
            Action("แสดง/ซ่อนช่องเพิ่ม URL", (_, _) => ShowInputPanel(!_inputVisible))));
        menu.Items.Add(Menu("ช่วยเหลือ",
            Action("เกี่ยวกับ X-Stage Download Manager", (_, _) =>
                MessageBox.Show(this,
                    "X-Stage Download Manager v" + UpdateChecker.CurrentVersion +
                    " Build " + UpdateChecker.CurrentBuild +
                    "\nดาวน์โหลดไฟล์และสื่อวิดีโอ พร้อมระบบอัปเดตในแอป",
                    "เกี่ยวกับโปรแกรม", MessageBoxButtons.OK, MessageBoxIcon.Information))));
        return menu;
    }

    private ToolStrip CreateIconToolbar()
    {
        var bar = new ToolStrip
        {
            Dock = DockStyle.Fill, AutoSize = false, Height = 64,
            GripStyle = ToolStripGripStyle.Hidden, LayoutStyle = ToolStripLayoutStyle.HorizontalStackWithOverflow,
            BackColor = DarkTop, ForeColor = Color.White,
            RenderMode = ToolStripRenderMode.System,
            ImageScalingSize = new Size(22, 22),
            Padding = new Padding(14, 6, 8, 6),
            Font = new Font("Segoe UI", 9)
        };
        void Button(string label, string symbol, Color iconColor, EventHandler callback, string tooltip)
        {
            var item = new ToolStripButton
            {
                Text = label, Image = DrawToolbarGlyph(symbol, iconColor),
                DisplayStyle = ToolStripItemDisplayStyle.ImageAndText,
                TextImageRelation = TextImageRelation.ImageBeforeText,
                ImageAlign = ContentAlignment.MiddleCenter,
                TextAlign = ContentAlignment.BottomCenter,
                AutoSize = false, Size = new Size(label.Length > 14 ? 150 : 104, 46),
                Margin = new Padding(0, 0, 3, 0), Padding = new Padding(3),
                ToolTipText = tooltip, ForeColor = Color.White, BackColor = DarkPanel
            };
            item.Click += callback;
            bar.Items.Add(item);
        }
        bar.Items.Add(new ToolStripLabel("X-STAGE  /  TRANSFERS")
        {
            ForeColor = Accent, Font = new Font("Segoe UI", 10, FontStyle.Bold),
            Margin = new Padding(4, 0, 18, 0)
        });
        Button("เพิ่ม URL", "＋", Color.FromArgb(89, 204, 176),
            (_, _) => ShowAddUrlFromClipboard(), "เปิดช่องเพิ่ม URL และเติมลิงก์จากคลิปบอร์ดอัตโนมัติ");
        Button("เริ่ม / ต่อ", "▶", Color.FromArgb(140, 193, 255),
            (_, _) => SelectedAction(_engine.Start), "เริ่มรายการที่เลือกหรือดาวน์โหลดต่อ");
        Button("หยุด", "■", Color.FromArgb(255, 149, 151),
            (_, _) => SelectedAction(_engine.Pause), "หยุดรายการที่เลือกชั่วคราว");
        Button("หยุดทั้งหมด", "Ⅱ", Color.FromArgb(255, 183, 130),
            (_, _) => _engine.PauseAll(), "หยุดการดาวน์โหลดที่กำลังทำงานทั้งหมด");
        Button("ลบ", "✕", Color.FromArgb(255, 150, 163),
            (_, _) => RemoveSelectedJob(), "ลบเฉพาะประวัติรายการ ไม่ลบไฟล์ที่ดาวน์โหลดสำเร็จ");
        Button("ลบที่เสร็จแล้ว", "✓", Color.FromArgb(180, 155, 235),
            (_, _) => ClearCompletedHistory(), "ลบประวัติรายการที่เสร็จแล้วโดยไม่ลบไฟล์");
        Button("ตั้งค่า", "⚙", Color.FromArgb(165, 186, 244),
            (_, _) => ShowInputPanel(true, true), "เลือกโฟลเดอร์ จำนวนส่วน และชนิดไฟล์");
        Button("รอคิว", "◷", Color.FromArgb(241, 202, 123),
            (_, _) => SelectCategory("queued"), "ดูงานที่รอเริ่มดาวน์โหลด");
        Button("ดาวน์โหลดอัตโนมัติ", "↧", Color.FromArgb(137, 216, 255),
            (_, _) => SetupBrowserIntegration(), "ตั้งค่าการรับดาวน์โหลดจาก Chrome / Edge");
        Button("อัปเดต", "⟳", Color.FromArgb(110, 225, 178),
            async (_, _) => await CheckForUpdatesAsync(true), "ตรวจสอบและติดตั้งอัปเดต");
        _toolbar = bar;
        return bar;
    }

    private static Image DrawToolbarGlyph(string glyph, Color color)
    {
        var image = new Bitmap(40, 40);
        using var g = Graphics.FromImage(image);
        g.Clear(Color.Transparent);
        g.SmoothingMode = SmoothingMode.AntiAlias;
        using var font = new Font("Segoe UI Symbol", 27, FontStyle.Regular, GraphicsUnit.Pixel);
        using var brush = new SolidBrush(color);
        using var format = new StringFormat
        {
            Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center
        };
        g.DrawString(glyph, font, brush, new RectangleF(0, -2, 40, 40), format);
        return image;
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
        _categories.ShowLines = false;
        _categories.ShowRootLines = false;
        _categories.HideSelection = false;
        _categories.FullRowSelect = true;
        _categories.BackColor = DarkPanel;
        _categories.ForeColor = Color.FromArgb(230, 239, 249);
        _categories.Font = new Font("Segoe UI", 10);
        _categories.ItemHeight = 31;
        _categories.Indent = 17;
        _categories.AfterSelect += (_, e) =>
        {
            if (e.Node?.Tag is string filter)
            {
                _categoryFilter = filter;
                RefreshRows();
            }
        };
        var all = AddCategory(null, "all", "▣  ดาวน์โหลดทั้งหมด");
        AddCategory(all, "active", "◉  กำลังดาวน์โหลด");
        AddCategory(all, "queued", "◷  รอคิว");
        AddCategory(all, "incomplete", "Ⅱ  ยังไม่เสร็จ");
        AddCategory(null, "completed", "✓  เสร็จแล้ว");
        var type = new TreeNode("▦  ประเภทไฟล์")
        {
            ForeColor = MutedText, NodeFont = new Font("Segoe UI", 10, FontStyle.Bold)
        };
        _categories.Nodes.Add(type);
        AddCategory(type, "video", "▣  วิดีโอ");
        AddCategory(type, "music", "♫  เพลงและเสียง");
        AddCategory(type, "document", "▤  เอกสาร");
        AddCategory(type, "program", "▧  โปรแกรม");
        AddCategory(type, "archive", "▥  ไฟล์บีบอัด");
        AddCategory(type, "other", "◇  อื่น ๆ");
        all.Expand();
        type.Expand();

        CreateDownloadGrid();
        split.Panel2.Controls.Add(_grid);
        _categories.SelectedNode = all;
        return split;
    }

    private TreeNode AddCategory(TreeNode? parent, string key, string title)
    {
        var node = new TreeNode(title) { Tag = key };
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
