using System.Diagnostics;
using System.Drawing;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Windows.Forms;

namespace XStageMirrorPC;

public sealed class MainForm : Form
{
    private const string VersionText = "v0.1.1 · Build 102";
    private const string FeedUrl = "https://webbase-x.github.io/xstage/downloads/mirror-pc-preview-latest.json";
    private static readonly Color Background = Color.FromArgb(13, 20, 38);
    private static readonly Color Surface = Color.FromArgb(23, 33, 54);
    private static readonly Color Muted = Color.FromArgb(169, 191, 213);
    private static readonly Color Accent = Color.FromArgb(74, 212, 231);
    private readonly TextBox _receiverName = new();
    private readonly Label _iosStatus = new();
    private readonly Label _androidStatus = new();
    private readonly Label _updateStatus = new();
    private readonly Button _startButton = new();
    private readonly Button _stopButton = new();
    private readonly System.Windows.Forms.Timer _timer = new() { Interval = 2500 };
    private Process? _airplayProcess;
    private string? _bundledEngine;
    private bool _closing;

    public MainForm()
    {
        Text = "X-Stage Mirror PC";
        BackColor = Background;
        ForeColor = Color.White;
        Font = new Font("Segoe UI", 10);
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(730, 630);
        Size = new Size(830, 740);
        AutoScaleMode = AutoScaleMode.Dpi;
        BuildLayout();

        _timer.Tick += (_, _) => RefreshAirPlayStatus();
        _timer.Start();
        Shown += async (_, _) =>
        {
            _bundledEngine = FindEngine();
            RefreshAirPlayStatus();
            await CheckUpdatesAsync(quiet: true);
        };
        FormClosing += (_, _) =>
        {
            _closing = true;
            _timer.Stop();
            StopOwnProcess();
        };
    }

    private static Label TextLabel(string text, float size = 11, bool bold = false, Color? color = null)
        => new()
        {
            Text = text,
            Font = new Font("Segoe UI", size, bold ? FontStyle.Bold : FontStyle.Regular),
            ForeColor = color ?? Color.White,
            AutoSize = false,
            TextAlign = ContentAlignment.MiddleLeft,
            Dock = DockStyle.Fill
        };

    private static Button ActionButton(string text, bool primary = false)
        => new()
        {
            Text = text,
            FlatStyle = FlatStyle.Flat,
            Cursor = Cursors.Hand,
            AutoSize = false,
            BackColor = primary ? Accent : Color.FromArgb(48, 67, 94),
            ForeColor = primary ? Background : Color.White,
            Font = new Font("Segoe UI", 10, FontStyle.Bold),
            Height = 42,
            FlatAppearance = { BorderSize = 0 }
        };

    // Explicitly size top-level cards. FlowLayoutPanel + AutoSize previously
    // collapsed the entire dashboard to a narrow left column on wide monitors.
    private int ScalePx(int px) => (int)Math.Round(px * DeviceDpi / 96.0);

    private static TableLayoutPanel CreateCard(params int[] rowHeights)
    {
        var card = new TableLayoutPanel
        {
            ColumnCount = 1,
            RowCount = rowHeights.Length,
            AutoSize = false,
            Dock = DockStyle.None,
            GrowStyle = TableLayoutPanelGrowStyle.FixedSize,
            Margin = Padding.Empty,
            Padding = new Padding(22, 16, 22, 12),
            BackColor = Surface
        };
        card.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        foreach (int height in rowHeights) card.RowStyles.Add(new RowStyle(SizeType.Absolute, height));
        return card;
    }

    private void BuildLayout()
    {
        var viewport = new Panel
        {
            Dock = DockStyle.Fill,
            AutoScroll = true,
            Margin = Padding.Empty,
            BackColor = Background
        };
        Controls.Add(viewport);

        var header = CreateCard(44, 31, 31);
        header.BackColor = Background;
        header.Padding = new Padding(4, 1, 4, 0);
        header.Controls.Add(TextLabel("X-STAGE MIRROR PC", 23, true, Accent), 0, 0);
        header.Controls.Add(TextLabel("รับภาพจาก iPhone / iPad และ Android สู่ Windows 10 / 11", 12), 0, 1);
        header.Controls.Add(TextLabel("AIRPLAY + WINDOWS MIRACAST   |   " + VersionText, 10, false, Muted), 0, 2);

        var ios = CreateCard(39, 53, 30, 42, 45, 37, 42);
        ios.Controls.Add(TextLabel("iPhone / iPad  ·  AirPlay", 16, true), 0, 0);
        _iosStatus.Dock = DockStyle.Fill;
        _iosStatus.Font = new Font("Segoe UI", 10, FontStyle.Bold);
        _iosStatus.TextAlign = ContentAlignment.MiddleLeft;
        ios.Controls.Add(_iosStatus, 0, 1);
        ios.Controls.Add(TextLabel("ชื่อเครื่องรับ AirPlay (เว้นวรรคจะแปลงเป็นเครื่องหมาย -)", 10, false, Muted), 0, 2);
        _receiverName.Dock = DockStyle.Fill;
        _receiverName.BackColor = Color.FromArgb(37, 51, 75);
        _receiverName.ForeColor = Color.White;
        _receiverName.BorderStyle = BorderStyle.FixedSingle;
        _receiverName.Font = new Font("Segoe UI", 12);
        _receiverName.Text = "X-Stage-Mirror-PC";
        _receiverName.MaxLength = 55;
        ios.Controls.Add(_receiverName, 0, 3);

        var iosButtons = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 3, RowCount = 1, Margin = Padding.Empty };
        iosButtons.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 40));
        iosButtons.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 25));
        iosButtons.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 35));
        _startButton.Text = "▶  เปิดรับ AirPlay";
        ApplyButtonStyle(_startButton, true);
        _stopButton.Text = "■  หยุดรับภาพ";
        ApplyButtonStyle(_stopButton, false);
        var verifyButton = ActionButton("↻  ตรวจส่วนประกอบ");
        verifyButton.Dock = DockStyle.Fill;
        verifyButton.Margin = new Padding(3);
        verifyButton.Click += (_, _) =>
        {
            _bundledEngine = FindEngine();
            RefreshAirPlayStatus();
            MessageBox.Show(this, _bundledEngine is null
                ? "ชุดโปรแกรมไม่ครบ กรุณาใช้ไฟล์ติดตั้ง X-Stage Mirror PC แบบเต็มจากเว็บไซต์\n\nไฟล์ EXE เพียงไฟล์เดียวไม่ใช่ชุดตัวรับ AirPlay ที่สมบูรณ์"
                : "พบ AirPlay Engine และไลบรารีที่จำเป็นในชุดโปรแกรมแล้ว",
                "ตรวจสอบส่วนประกอบ", MessageBoxButtons.OK, MessageBoxIcon.Information);
        };
        _startButton.Click += (_, _) => StartAirPlay();
        _stopButton.Click += (_, _) => StopAirPlay();
        iosButtons.Controls.Add(_startButton, 0, 0);
        iosButtons.Controls.Add(_stopButton, 1, 0);
        iosButtons.Controls.Add(verifyButton, 2, 0);
        ios.Controls.Add(iosButtons, 0, 4);
        ios.Controls.Add(TextLabel("บน iPhone: ศูนย์ควบคุม → การสะท้อนหน้าจอ → เลือกชื่อเครื่องรับ", 9, false, Muted), 0, 5);
        ios.Controls.Add(TextLabel("ต้องอยู่ใน LAN ที่อนุญาต mDNS และอนุญาต Windows Firewall เมื่อถูกถาม", 9, false, Muted), 0, 6);

        var android = CreateCard(39, 53, 52, 43, 41);
        android.Controls.Add(TextLabel("Android  ·  Wireless Display / Miracast", 16, true), 0, 0);
        _androidStatus.Dock = DockStyle.Fill;
        _androidStatus.ForeColor = Muted;
        _androidStatus.Text = "ใช้ตัวรับภาพ Wireless Display ของ Windows\nต้องรองรับ Miracast ทั้งสองเครื่องและไดรเวอร์ Wi-Fi";
        android.Controls.Add(_androidStatus, 0, 1);
        var androidButtons = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 1, Margin = Padding.Empty };
        androidButtons.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 55));
        androidButtons.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 45));
        var openDisplay = ActionButton("▶  เปิดรับภาพ Android", true);
        var settings = ActionButton("⚙  ตรวจสอบ Windows");
        openDisplay.Dock = DockStyle.Fill;
        settings.Dock = DockStyle.Fill;
        openDisplay.Margin = new Padding(3);
        settings.Margin = new Padding(3);
        openDisplay.Click += (_, _) => OpenWirelessDisplay();
        settings.Click += (_, _) => OpenUri("ms-settings:project");
        androidButtons.Controls.Add(openDisplay, 0, 0);
        androidButtons.Controls.Add(settings, 1, 0);
        android.Controls.Add(androidButtons, 0, 2);
        android.Controls.Add(TextLabel("Android: Cast / Smart View → เลือกชื่อ PC ที่รองรับ Miracast", 9, false, Muted), 0, 3);
        android.Controls.Add(TextLabel("Google Cast อย่างเดียวไม่ใช่ Miracast • Windows อาจต้องเพิ่ม Wireless Display", 9, false, Muted), 0, 4);

        var footer = CreateCard(33, 43, 47);
        footer.Controls.Add(TextLabel("อัปเดตและข้อมูลระบบ", 13, true), 0, 0);
        _updateStatus.Dock = DockStyle.Fill;
        _updateStatus.ForeColor = Muted;
        _updateStatus.Text = "กำลังตรวจสอบรุ่นล่าสุด…";
        footer.Controls.Add(_updateStatus, 0, 1);
        var updateButton = ActionButton("↻  ตรวจสอบอัปเดต");
        updateButton.Dock = DockStyle.Fill;
        updateButton.Click += async (_, _) => await CheckUpdatesAsync(quiet: false);
        footer.Controls.Add(updateButton, 0, 2);

        viewport.Controls.Add(header);
        viewport.Controls.Add(ios);
        viewport.Controls.Add(android);
        viewport.Controls.Add(footer);

        void ResizeDashboard()
        {
            var available = Math.Max(0, viewport.ClientSize.Width - 40);
            var width = Math.Min(1020, Math.Max(600, available));
            var x = available >= width ? (viewport.ClientSize.Width - width) / 2 : 20;
            int y = 16, gap = 16;
            var cards = new (Control view, int height)[]
            {
                (header, 119), (ios, 341), (android, 246), (footer, 164)
            };
            viewport.SuspendLayout();
            try
            {
                foreach (var (view, height) in cards)
                {
                    view.SetBounds(x, y, width, height);
                    y += height + gap;
                }
                viewport.AutoScrollMinSize = new Size(width + 40, y + 12);
            }
            finally { viewport.ResumeLayout(); }
        }
        viewport.SizeChanged += (_, _) => ResizeDashboard();
        ResizeDashboard();
    }

    private static void ApplyButtonStyle(Button button, bool primary)
    {
        button.FlatStyle = FlatStyle.Flat;
        button.FlatAppearance.BorderSize = 0;
        button.BackColor = primary ? Accent : Color.FromArgb(48, 67, 94);
        button.ForeColor = primary ? Background : Color.White;
        button.Font = new Font("Segoe UI", 10, FontStyle.Bold);
        button.Dock = DockStyle.Fill;
        button.Margin = new Padding(3);
        button.Cursor = Cursors.Hand;
    }

    private static string? FindEngine()
    {
        string folder = Path.Combine(AppContext.BaseDirectory, "engine", "uxplay-windows");
        if (!Directory.Exists(folder)) return null;
        // A complete portable upstream distribution must be unpacked, not only the executable.
        return Directory.EnumerateFiles(folder, "uxplay-windows.exe", SearchOption.AllDirectories).FirstOrDefault();
    }

    private void RefreshAirPlayStatus()
    {
        bool alive = _airplayProcess is { HasExited: false };
        _receiverName.Enabled = !alive;
        _startButton.Enabled = !alive && _bundledEngine is not null;
        _stopButton.Enabled = alive;
        _iosStatus.Text = alive
            ? "● ตัวรับ AirPlay กำลังทำงาน (ไม่ได้ยืนยันว่ามีผู้ส่งเชื่อมต่อ)"
            : _bundledEngine is null
                ? "● ไม่มี UxPlay แบบพกพาในแพ็กเกจ • ไม่พร้อมรับ iOS"
                : "● พร้อมเริ่มตัวรับ AirPlay";
        _iosStatus.ForeColor = alive ? Color.FromArgb(120, 235, 165) : _bundledEngine is null ? Color.Orange : Accent;
    }

    private bool WriteNameSettings(string name)
    {
        var systemFile = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "uxplay-windows", "arguments.txt");
        if (File.Exists(systemFile))
        {
            MessageBox.Show(this, "พบการกำหนดค่า UxPlay ระดับเครื่องไว้แล้ว ซึ่งมีลำดับความสำคัญสูงกว่า\nโปรแกรมจะไม่เขียนทับไฟล์ผู้ดูแลระบบ:\n" + systemFile,
                "ไม่สามารถเปลี่ยนชื่อผ่าน X-Stage ได้", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return true; // Upstream will use its existing machine-wide settings.
        }
        var config = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "leapbtw", "uxplay-windows", "arguments.txt");
        var desired = "-n \"" + name + "\" -nh";
        if (File.Exists(config))
        {
            string previous = File.ReadAllText(config).Trim();
            if (previous != desired)
            {
                var choice = MessageBox.Show(this,
                    "พบการตั้งค่าเดิมของ uxplay-windows\n\nการเปลี่ยนชื่อจะเขียนทับ arguments.txt ของผู้ใช้\nต้องการแทนที่การตั้งค่านี้หรือไม่?",
                    "ยืนยันการเปลี่ยนการตั้งค่า AirPlay", MessageBoxButtons.YesNo, MessageBoxIcon.Question);
                if (choice != DialogResult.Yes) return false;
            }
            else return true;
        }
        Directory.CreateDirectory(Path.GetDirectoryName(config)!);
        File.WriteAllText(config, desired + Environment.NewLine);
        return true;
    }

    private void StartAirPlay()
    {
        try
        {
            if (_airplayProcess is { HasExited: false }) return;
            _bundledEngine = FindEngine();
            if (_bundledEngine is null)
                throw new FileNotFoundException("แพ็กเกจนี้ไม่มีตัวรับ AirPlay แบบ portable กรุณาใช้ไฟล์ ZIP ที่ผ่านการทดสอบและมีโฟลเดอร์ engine ครบถ้วน");
            string name = _receiverName.Text.Trim();
            // Avoid options injection or control characters in arguments.txt.
            if (name.Length is < 1 or > 55 || !Regex.IsMatch(name, @"^[\p{L}\p{N} _().-]+$"))
                throw new InvalidOperationException("ชื่อเครื่องรับต้องยาว 1–55 ตัวอักษร และใช้เฉพาะตัวอักษร ตัวเลข เว้นวรรค _ ( ) . -");
            if (!WriteNameSettings(name)) return;
            _airplayProcess = Process.Start(new ProcessStartInfo
            {
                FileName = _bundledEngine,
                WorkingDirectory = Path.GetDirectoryName(_bundledEngine)!,
                UseShellExecute = true
            });
            RefreshAirPlayStatus();
        }
        catch (Exception ex)
        {
            _iosStatus.Text = "เปิดตัวรับ AirPlay ไม่สำเร็จ";
            MessageBox.Show(this, ex.Message, "AirPlay Error", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            RefreshAirPlayStatus();
        }
    }

    private void StopOwnProcess()
    {
        try
        {
            if (_airplayProcess is { HasExited: false })
            {
                // Stop only the process started by this control app, not other Windows receivers.
                _airplayProcess.CloseMainWindow();
                if (!_airplayProcess.WaitForExit(1200)) _airplayProcess.Kill(entireProcessTree: true);
            }
        }
        catch { /* Process may have exited or may deny termination. */ }
        finally { _airplayProcess?.Dispose(); _airplayProcess = null; }
    }

    private void StopAirPlay()
    {
        StopOwnProcess();
        RefreshAirPlayStatus();
    }

    private static void OpenUri(string uri)
        => Process.Start(new ProcessStartInfo(uri) { UseShellExecute = true });

    private void OpenWirelessDisplay()
    {
        try
        {
            string connect = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "System32", "Connect.exe");
            if (File.Exists(connect))
            {
                Process.Start(new ProcessStartInfo(connect) { UseShellExecute = true });
                _androidStatus.Text = "เรียกตัวรับ Windows Connect แล้ว • ตรวจสถานะในหน้าต่าง Windows";
                return;
            }
            // On Windows 11 22H2+ the optional Wireless Display feature is a packaged app.
            // The app id may be unavailable on some SKUs, so always show Windows Settings fallback.
            Process.Start(new ProcessStartInfo("explorer.exe",
                @"shell:AppsFolder\Microsoft.PPIProjection_cw5n1h2txyewy!App") { UseShellExecute = true });
            _androidStatus.Text = "เรียก Wireless Display แล้ว • หากไม่เปิด ให้ใช้ 'ตั้งค่า Windows'";
        }
        catch
        {
            OpenUri("ms-settings:project");
            _androidStatus.Text = "เปิดการตั้งค่า Windows • ติดตั้ง Wireless Display หากยังไม่มี";
        }
    }

    private async Task CheckUpdatesAsync(bool quiet)
    {
        try
        {
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(7) };
            using var response = await client.GetAsync(FeedUrl);
            response.EnsureSuccessStatusCode();
            using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
            var obj = doc.RootElement;
            bool available = obj.TryGetProperty("available", out var av) && av.ValueKind == JsonValueKind.True;
            string version = obj.TryGetProperty("version", out var v) ? v.GetString() ?? "" : "";
            _updateStatus.Text = available
                ? "มีประกาศรุ่น " + version + " (ตรวจสอบรายละเอียดที่ GitHub Releases)"
                : "ยังไม่มีรุ่นใหม่ที่ผ่านการตรวจสอบเผยแพร่ • " + VersionText;
            if (available && Version.TryParse(version, out var remote) && remote > new Version(0, 1, 0))
            {
                var responseToUser = MessageBox.Show(this,
                    "พบประกาศเวอร์ชัน " + version + "\nต้องการเปิด GitHub Releases เพื่อตรวจสอบไฟล์และ SHA-256 หรือไม่?",
                    "อัปเดต X-Stage Mirror PC", MessageBoxButtons.YesNo, MessageBoxIcon.Information);
                if (responseToUser == DialogResult.Yes)
                    OpenUri("https://github.com/webbase-x/xstage/releases");
            }
            else if (!quiet)
                MessageBox.Show(this, _updateStatus.Text, "X-Stage Mirror PC", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        catch (Exception ex)
        {
            if (_closing || IsDisposed) return;
            _updateStatus.Text = "ตรวจสอบออนไลน์ไม่ได้ • ใช้งานการรับภาพใน LAN ต่อได้";
            if (!quiet)
                MessageBox.Show(this, "ไม่สามารถตรวจสอบอัปเดต: " + ex.Message,
                    "อัปเดต", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
    }
}
