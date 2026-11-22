using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

namespace XStageDownloadManager;

// Presentation-only workspace: charts, details and diagnostics read live
// DownloadJob state. This component never creates or mutates download jobs,
// the output directory, or the user's existing SQLite history.
public sealed partial class MainForm
{
    private readonly Label _previewTitle = new();
    private readonly Label _previewMeta = new();
    private readonly Label _previewState = new();
    private readonly Label _previewPath = new();
    private readonly Label _previewUrl = new();
    private readonly Label _previewPercent = new();
    private readonly Label _chartRate = new();
    private readonly Panel _previewProgressTrack = new();
    private readonly Panel _speedChart = new();
    private readonly TextBox _diagnosticText = new();
    private readonly List<double> _speedSamples = new();
    private readonly Dictionary<string, string> _lastObservedStatus = new();
    private readonly Dictionary<string, List<string>> _sessionEvents = new();
    private double _previewProgressFraction;
    private double _latestTransferRate;
    private TabControl? _previewTabs;

    private Control CreateLivePreview()
    {
        var tabs = new TabControl
        {
            Dock = DockStyle.Fill, Margin = Padding.Empty,
            Font = new Font("Segoe UI", 9, FontStyle.Bold),
            SizeMode = TabSizeMode.Fixed, ItemSize = new Size(168, 33),
            DrawMode = TabDrawMode.OwnerDrawFixed,
            BackColor = DarkGrid, ForeColor = Color.White,
            AccessibleName = "รายละเอียดงาน กราฟความเร็ว และบันทึกเหตุการณ์"
        };
        tabs.DrawItem += (_, e) =>
        {
            // Windows may request an owner-draw tab while its handle/size is
            // changing (startup, minimize, DPI scaling). Never pass a zero or
            // stale rectangle to native GDI+.
            if (e.Index < 0 || e.Index >= tabs.TabPages.Count) return;
            var area = tabs.GetTabRect(e.Index);
            if (area.Width <= 0 || area.Height <= 0) return;
            var selected = e.Index == tabs.SelectedIndex;
            using var background = new SolidBrush(selected
                ? Color.FromArgb(21, 89, 155) : DarkPanel);
            e.Graphics.FillRectangle(background, area);
            var color = selected ? Color.White : MutedText;
            TextRenderer.DrawText(e.Graphics, tabs.TabPages[e.Index].Text,
                tabs.Font, area, color,
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
        };
        _previewTabs = tabs;

        var summary = new TabPage("รายละเอียดงาน")
        {
            BackColor = DarkGrid, ForeColor = Color.White,
            Padding = new Padding(11, 6, 8, 5)
        };
        var content = new TableLayoutPanel
        {
            Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 1,
            BackColor = DarkGrid, Padding = Padding.Empty
        };
        content.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 56));
        content.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 44));
        content.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        content.Controls.Add(CreateFileDetailsCard(), 0, 0);
        content.Controls.Add(CreateSpeedChartCard(), 1, 0);
        summary.Controls.Add(content);

        var speed = new TabPage("กราฟความเร็ว")
        {
            BackColor = DarkGrid, ForeColor = Color.White,
            Padding = new Padding(12, 5, 12, 5)
        };
        // Show the same live chart on the first tab and full view, without
        // duplicating timers, fake data or independent speed calculations.
        var largerChart = new Panel { Dock = DockStyle.Fill, BackColor = DarkGrid };
        largerChart.Paint += (_, e) => PaintSpeedGraph(e.Graphics, largerChart.ClientRectangle);
        _speedChart.Invalidate();
        _fullSpeedChart = largerChart;
        speed.Controls.Add(largerChart);

        var diagnostics = new TabPage("บันทึกเหตุการณ์")
        {
            BackColor = DarkGrid, ForeColor = Color.White,
            Padding = new Padding(12, 6, 12, 8)
        };
        var diagnosticsArea = new TableLayoutPanel
        {
            Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2,
            BackColor = DarkGrid
        };
        diagnosticsArea.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        diagnosticsArea.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        diagnosticsArea.RowStyles.Add(new RowStyle(SizeType.Absolute, 35));
        _diagnosticText.Dock = DockStyle.Fill;
        _diagnosticText.Multiline = true;
        _diagnosticText.ReadOnly = true;
        _diagnosticText.ScrollBars = ScrollBars.Vertical;
        _diagnosticText.BackColor = DarkPanel;
        _diagnosticText.ForeColor = Color.FromArgb(225, 237, 245);
        _diagnosticText.BorderStyle = BorderStyle.None;
        _diagnosticText.Font = new Font("Consolas", 9);
        _diagnosticText.AccessibleName = "สถานะและข้อมูลวินิจฉัยของงานที่เลือก";
        diagnosticsArea.Controls.Add(_diagnosticText, 0, 0);
        var openLog = new Button
        {
            Text = "เปิดบันทึกวิดีโอของรายการที่เลือก",
            Dock = DockStyle.Right, Width = 285,
            FlatStyle = FlatStyle.Flat,
            BackColor = DarkPanel, ForeColor = Color.White,
            Cursor = Cursors.Hand
        };
        openLog.FlatAppearance.BorderColor = Accent;
        openLog.Click += (_, _) => WithSelectedJob(job =>
        {
            if (job.Kind == "Video") OpenVideoLog(job);
            else MessageBox.Show(this, "รายการนี้ไม่มีบันทึก yt-dlp",
                "X-Stage", MessageBoxButtons.OK, MessageBoxIcon.Information);
        });
        diagnosticsArea.Controls.Add(openLog, 0, 1);
        diagnostics.Controls.Add(diagnosticsArea);
        tabs.TabPages.Add(summary);
        tabs.TabPages.Add(speed);
        tabs.TabPages.Add(diagnostics);
        return tabs;
    }

    private Panel? _fullSpeedChart;

    private Control CreateFileDetailsCard()
    {
        var content = new TableLayoutPanel
        {
            Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 7,
            BackColor = DarkGrid, Padding = new Padding(7, 0, 13, 0),
            Margin = Padding.Empty
        };
        content.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        content.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));
        content.RowStyles.Add(new RowStyle(SizeType.Absolute, 25));
        content.RowStyles.Add(new RowStyle(SizeType.Absolute, 25));
        content.RowStyles.Add(new RowStyle(SizeType.Absolute, 28));
        content.RowStyles.Add(new RowStyle(SizeType.Absolute, 25));
        content.RowStyles.Add(new RowStyle(SizeType.Absolute, 24));
        content.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        ConfigurePreviewLabel(_previewTitle, 12, FontStyle.Bold, Color.White);
        ConfigurePreviewLabel(_previewMeta, 9, FontStyle.Regular, MutedText);
        ConfigurePreviewLabel(_previewState, 9, FontStyle.Bold, Accent);
        ConfigurePreviewLabel(_previewPercent, 9, FontStyle.Bold, Color.FromArgb(152, 230, 193));
        ConfigurePreviewLabel(_previewPath, 9, FontStyle.Regular, Color.FromArgb(185, 205, 227));
        ConfigurePreviewLabel(_previewUrl, 9, FontStyle.Regular, Color.FromArgb(126, 192, 247));
        _previewProgressTrack.Dock = DockStyle.Fill;
        _previewProgressTrack.Height = 20;
        _previewProgressTrack.Margin = new Padding(0, 4, 18, 4);
        _previewProgressTrack.BackColor = DarkPanel;
        _previewProgressTrack.Paint += (_, e) =>
        {
            var bounds = _previewProgressTrack.ClientRectangle;
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using var background = new SolidBrush(Color.FromArgb(35, 57, 70));
            using var fill = new SolidBrush(Color.FromArgb(54, 216, 127));
            e.Graphics.FillRectangle(background, bounds);
            var width = (int)Math.Round(bounds.Width * Math.Clamp(_previewProgressFraction, 0, 1));
            if (width > 0) e.Graphics.FillRectangle(fill, 0, 0, width, bounds.Height);
        };
        content.Controls.Add(_previewTitle, 0, 0);
        content.Controls.Add(_previewMeta, 0, 1);
        content.Controls.Add(_previewState, 0, 2);
        content.Controls.Add(_previewProgressTrack, 0, 3);
        content.Controls.Add(_previewPercent, 0, 4);
        content.Controls.Add(_previewPath, 0, 5);
        content.Controls.Add(_previewUrl, 0, 6);
        return content;
    }

    private Control CreateSpeedChartCard()
    {
        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2,
            BackColor = Color.FromArgb(12, 33, 47),
            Margin = new Padding(8, 0, 0, 0),
            Padding = new Padding(12, 4, 12, 7)
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 30));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        _chartRate.Dock = DockStyle.Fill;
        _chartRate.Text = "ความเร็วการดาวน์โหลด  ·  0 B/s";
        _chartRate.ForeColor = Color.FromArgb(221, 238, 246);
        _chartRate.Font = new Font("Segoe UI", 9, FontStyle.Bold);
        _chartRate.TextAlign = ContentAlignment.MiddleLeft;
        _chartRate.AutoEllipsis = true;
        layout.Controls.Add(_chartRate, 0, 0);
        _speedChart.Dock = DockStyle.Fill;
        _speedChart.BackColor = Color.FromArgb(12, 33, 47);
        _speedChart.Paint += (_, e) => PaintSpeedGraph(e.Graphics, _speedChart.ClientRectangle);
        layout.Controls.Add(_speedChart, 0, 1);
        return layout;
    }

    private static void ConfigurePreviewLabel(Label target, float size,
        FontStyle style, Color color)
    {
        target.Dock = DockStyle.Fill;
        target.Font = new Font("Segoe UI", size, style);
        target.ForeColor = color;
        target.TextAlign = ContentAlignment.MiddleLeft;
        target.AutoEllipsis = true;
        target.UseMnemonic = false;
    }

    private void RecordTransferSpeed(double rate)
    {
        _latestTransferRate = double.IsFinite(rate) ? Math.Max(0, rate) : 0;
        _speedSamples.Add(_latestTransferRate);
        if (_speedSamples.Count > 90) _speedSamples.RemoveAt(0);
        _chartRate.Text = "ความเร็วการดาวน์โหลด  ·  " +
            FormatBytes((long)Math.Min(long.MaxValue, _latestTransferRate)) + "/s";
        _speedChart.Invalidate();
        _fullSpeedChart?.Invalidate();
    }

    // Actual status transitions observed during this application session.
    // We neither synthesize past events nor persist new log records in
    // the user's downloaded-media database.
    private void TrackLiveEvents(DownloadJob[] jobs)
    {
        var activeIds = new HashSet<string>(jobs.Select(job => job.Id));
        foreach (var id in _lastObservedStatus.Keys.Where(id => !activeIds.Contains(id)).ToArray())
        {
            _lastObservedStatus.Remove(id);
            _sessionEvents.Remove(id);
        }
        foreach (var job in jobs)
        {
            if (_lastObservedStatus.TryGetValue(job.Id, out var before) &&
                string.Equals(before, job.Status, StringComparison.Ordinal))
                continue;
            _lastObservedStatus[job.Id] = job.Status;
            if (!_sessionEvents.TryGetValue(job.Id, out var history))
            {
                history = new List<string>();
                _sessionEvents.Add(job.Id, history);
            }
            history.Add(DateTimeOffset.Now.ToString("HH:mm:ss") +
                (history.Count == 0 ? "  เริ่มติดตาม: " : "  เปลี่ยนสถานะ: ") + job.Status);
            if (history.Count > 40) history.RemoveAt(0);
        }
    }

    private void UpdateLivePreview(DownloadJob? job)
    {
        if (job is null)
        {
            _previewTitle.Text = "เลือกงานดาวน์โหลดเพื่อดูรายละเอียด";
            _previewMeta.Text = "รายละเอียดไฟล์และความคืบหน้าจริงจะแสดงที่นี่";
            _previewState.Text = "พร้อมใช้งาน";
            _previewPath.Text = "ปลายทาง: —";
            _previewUrl.Text = "ลิงก์: —";
            _previewPercent.Text = "—";
            _previewProgressFraction = 0;
            _diagnosticText.Text = "ไม่มีงานที่เลือก";
        }
        else
        {
            _previewTitle.Text = job.Name;
            _previewMeta.Text = "ชนิดไฟล์: " + DownloadTableSort.FileType(job) +
                "    ·    ขนาด: " + (job.TotalBytes >= 0 ? FormatBytes(job.TotalBytes) : "ไม่ทราบ");
            _previewState.Text = "สถานะ: " + job.Status +
                (job.Kind == "Video" && !string.IsNullOrWhiteSpace(job.VideoPhase)
                    ? " · " + job.VideoPhase : "");
            _previewState.ForeColor = job.Status == "Failed"
                ? Color.FromArgb(250, 147, 147) : Accent;
            _previewPath.Text = "บันทึกที่: " + job.Folder;
            _previewUrl.Text = "URL: " + job.Url;
            _previewProgressFraction = ProgressPresentation.FillFraction(job);
            _previewPercent.Text = ProgressPresentation.PercentLabel(job) +
                "    ·    ได้รับ " + FormatBytes(Interlocked.Read(ref job.DownloadedBytes)) +
                (job.Status == "Running"
                    ? "    ·    " + FormatBytes((long)job.SmoothedSpeedBytesPerSecond) + "/s"
                    : "");
            var sessionLog = _sessionEvents.TryGetValue(job.Id, out var events)
                ? string.Join(Environment.NewLine, events) : "ยังไม่มีเหตุการณ์ที่บันทึกในรอบนี้";
            var info = "สถานะปัจจุบัน + เหตุการณ์จริงเฉพาะการเปิดโปรแกรมครั้งนี้" +
                Environment.NewLine + "บันทึกสถานะ:" + Environment.NewLine +
                sessionLog + Environment.NewLine + Environment.NewLine +
                "ชื่อ: " + job.Name +
                Environment.NewLine + "สถานะ: " + job.Status +
                Environment.NewLine + "วันที่เพิ่ม: " + job.CreatedAt.ToLocalTime().ToString("dd/MM/yyyy HH:mm:ss") +
                Environment.NewLine + "คิว: " + job.QueueName +
                Environment.NewLine + "จำนวนส่วน: " + job.Parts +
                Environment.NewLine + "โฟลเดอร์: " + job.Folder +
                Environment.NewLine + "รายละเอียดข้อผิดพลาด: " +
                (string.IsNullOrWhiteSpace(job.Error) ? "ไม่มี" : job.Error);
            if (!string.Equals(_diagnosticText.Text, info, StringComparison.Ordinal))
                _diagnosticText.Text = info;
        }
        _previewProgressTrack.Invalidate();
    }

    private void PaintSpeedGraph(Graphics graphics, Rectangle area)
    {
        // A collapsed/minimized panel can momentarily have zero client
        // dimensions. Do not manufacture an off-screen chart rectangle:
        // GDI+ can report "Parameter is not valid" while layout is settling.
        if (area.Width <= 0 || area.Height <= 0) return;
        graphics.Clear(Color.FromArgb(12, 33, 47));
        if (area.Width < 130 || area.Height < 85) return;
        var rect = new Rectangle(area.Left + 63, area.Top + 12,
            area.Width - 78, area.Height - 38);
        if (rect.Width < 25 || rect.Height < 30) return;
        graphics.SmoothingMode = SmoothingMode.AntiAlias;
        var max = Math.Max(1024, _speedSamples.Count == 0 ? 0 : _speedSamples.Max() * 1.12);
        using var gridPen = new Pen(Color.FromArgb(42, 69, 83), 1);
        using var textBrush = new SolidBrush(Color.FromArgb(176, 198, 218));
        using var smallFont = new Font("Segoe UI", 8);
        for (var tick = 0; tick <= 4; tick++)
        {
            var y = rect.Bottom - tick * rect.Height / 4;
            graphics.DrawLine(gridPen, rect.Left, y, rect.Right, y);
            graphics.DrawString(FormatBytes((long)(max * tick / 4)) + "/s",
                smallFont, textBrush, area.Left + 2, y - 8);
        }
        for (var tick = 0; tick <= 6; tick++)
        {
            var x = rect.Left + tick * rect.Width / 6;
            graphics.DrawLine(gridPen, x, rect.Top, x, rect.Bottom);
        }
        if (_speedSamples.Count < 2 || !_speedSamples.Any(rate => rate > 0))
        {
            var message = _speedSamples.Count < 2
                ? "กำลังเก็บข้อมูลความเร็วจริง..." : "ยังไม่มีการถ่ายโอนข้อมูล";
            TextRenderer.DrawText(graphics, message, smallFont, rect,
                Color.FromArgb(143, 163, 183),
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
            return;
        }
        // Use fixed time slots (90 x UI refresh period) to keep the curve
        // steady without implying that samples were gathered earlier.
        var points = _speedSamples.Select((value, index) =>
            new PointF(rect.Right - (_speedSamples.Count - 1 - index) *
                rect.Width / 89f,
                rect.Bottom - (float)Math.Clamp(value / max, 0, 1) * rect.Height)).ToArray();
        using var fillPath = new GraphicsPath();
        fillPath.AddLines(points);
        fillPath.AddLine(points[^1], new PointF(points[^1].X, rect.Bottom));
        fillPath.AddLine(new PointF(points[^1].X, rect.Bottom),
            new PointF(points[0].X, rect.Bottom));
        fillPath.CloseFigure();
        using var fill = new LinearGradientBrush(
            new Point(rect.Left, rect.Top), new Point(rect.Left, rect.Bottom),
            Color.FromArgb(110, 42, 207, 116), Color.FromArgb(4, 42, 207, 116));
        using var line = new Pen(Color.FromArgb(111, 239, 113), 2.4f);
        graphics.FillPath(fill, fillPath);
        graphics.DrawLines(line, points);
        graphics.DrawString("ล่าสุด", smallFont, textBrush,
            rect.Right - 42, rect.Bottom + 4);
    }
}
