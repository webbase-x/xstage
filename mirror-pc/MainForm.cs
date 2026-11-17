using System.Diagnostics;
using System.Drawing;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Windows.Forms;

namespace XStageMirrorPC;

public sealed class MainForm : Form
{
    private const string VersionText = "v0.1.2 · Build 103";
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
    private bool _manualAirPlayStop;
    private int _recoveryAttempts;
    private DateTime _lastReceiverLaunchUtc = DateTime.MinValue;
    private string _receiverIssue = "";

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

        _timer.Tick += (_, _) =>
        {
            // Avoid leaving an empty discovery list after a transient native exit.
            if (!_closing && !_manualAirPlayStop && _bundledEngine is not null &&
                _lastReceiverLaunchUtc != DateTime.MinValue &&
                (_airplayProcess is null || _airplayProcess.HasExited) &&
                _recoveryAttempts < 3 &&
                DateTime.UtcNow - _lastReceiverLaunchUtc >= TimeSpan.FromSeconds(8))
            {
                _recoveryAttempts++;
                StartAirPlay(autoStart: true);
            }
            RefreshAirPlayStatus();
        };
        _timer.Start();
        Shown += async (_, _) =>
        {
            _bundledEngine = FindEngine();
            LoadConfiguredAirPlayName();
            RefreshAirPlayStatus();
            // Users expect the PC receiver to appear as soon as the app opens.
            // Continue to run the Windows Miracast receiver only if the OS supports it.
            if (_bundledEngine is not null) StartAirPlay(autoStart: true);
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

    private TableLayoutPanel CreateCard(params int[] rowHeights)
    {
        var card = new TableLayoutPanel
        {
            ColumnCount = 1,
            RowCount = rowHeights.Length,
            AutoSize = false,
            Dock = DockStyle.None,
            GrowStyle = TableLayoutPanelGrowStyle.FixedSize,
            Margin = Padding.Empty,
            Padding = new Padding(ScalePx(22), ScalePx(16), ScalePx(22), ScalePx(12)),
            BackColor = Surface
        };
        card.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        foreach (int height in rowHeights) card.RowStyles.Add(new RowStyle(SizeType.Absolute, ScalePx(height)));
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
        verifyButton.Text = "ตรวจการค้นพบ";
        verifyButton.Click += (_, _) => ShowDiscoveryDiagnostics();
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
            var available = Math.Max(0, viewport.ClientSize.Width - ScalePx(40));
            var width = Math.Min(ScalePx(1020), Math.Max(ScalePx(600), available));
            var x = available >= width ? (viewport.ClientSize.Width - width) / 2 : ScalePx(20);
            int y = ScalePx(16), gap = ScalePx(16);
            var cards = new (Control view, int height)[]
            {
                (header, 119), (ios, 341), (android, 282), (footer, 164)
            };
            viewport.SuspendLayout();
            try
            {
                foreach (var (view, height) in cards)
                {
                    view.SetBounds(x, y, width, ScalePx(height));
                    y += ScalePx(height) + gap;
                }
                viewport.AutoScrollMinSize = new Size(width + ScalePx(40), y + ScalePx(12));
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
        // A complete AirPlay receiver has native DLLs and GStreamer plugins;
        // a bare XStageMirrorPC.exe is intentionally NOT reported as ready.
        var folder = Path.Combine(AppContext.BaseDirectory, "engine", "uxplay-windows");
        if (!Directory.Exists(folder)) return null;
        var required = new[]
        {
            "uxplay-windows.exe", "mDNSResponder.exe", "Qt6Core.dll",
            "libgstreamer-1.0-0.dll", "dnssd.dll",
            Path.Combine("lib", "gstreamer-1.0", "libgstcoreelements.dll"),
            Path.Combine("platforms", "qwindows.dll")
        };
        return required.All(file => File.Exists(Path.Combine(folder, file)))
            ? Path.Combine(folder, "uxplay-windows.exe") : null;
    }

    private static (bool installed, bool running) QueryBonjourService()
    {
        try
        {
            using var check = Process.Start(new ProcessStartInfo
            {
                FileName = "sc.exe",
                Arguments = "query \"Bonjour Service\"",
                RedirectStandardOutput = true,
                UseShellExecute = false,
                CreateNoWindow = true
            });
            if (check is null) return (false, false);
            var output = check.StandardOutput.ReadToEnd();
            if (!check.WaitForExit(3000) || check.ExitCode != 0) return (false, false);
            return (true, Regex.IsMatch(output, @"STATE\s*:\s*4\s+RUNNING",
                RegexOptions.IgnoreCase | RegexOptions.CultureInvariant));
        }
        catch { return (false, false); }
    }

    private bool EnsureBonjourService(bool autoStart = false)
    {
        var state = QueryBonjourService();
        if (state.running) return true;
        if (autoStart && _recoveryAttempts > 0)
        {
            _receiverIssue = "Bonjour Service หยุดทำงาน • เลือกเปิดรับ AirPlay อีกครั้ง";
            return false; // Never repeatedly prompt for elevation from the recovery timer.
        }
        if (_bundledEngine is null) return false;
        var message = state.installed
            ? "พบ Bonjour Service แต่ยังไม่ทำงาน\n\nต้องการเริ่มบริการเพื่อให้อุปกรณ์ค้นหาเครื่องรับ AirPlay ได้หรือไม่?\nWindows อาจขออนุญาต Administrator"
            : "ยังไม่มี Bonjour Service สำหรับประกาศเครื่องรับ AirPlay\nชุด X-Stage มี mDNSResponder อยู่แล้ว ไม่ต้องดาวน์โหลดเพิ่ม\n\nอนุญาตให้ลงทะเบียนบริการนี้โดย Windows Administrator หรือไม่?";
        if (MessageBox.Show(this, message, "เตรียมการค้นหา AirPlay",
            MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes)
        {
            _receiverIssue = "ยังไม่ได้เปิด Bonjour Service • อุปกรณ์ iOS อาจค้นหาไม่พบ";
            return false;
        }
        try
        {
            var engineFolder = Path.GetDirectoryName(_bundledEngine)!;
            var command = state.installed ? "sc.exe" : Path.Combine(engineFolder, "mDNSResponder.exe");
            var arguments = state.installed ? "start \"Bonjour Service\"" : "-install";
            using var setup = Process.Start(new ProcessStartInfo
            {
                FileName = command,
                Arguments = arguments,
                WorkingDirectory = engineFolder,
                UseShellExecute = true,
                Verb = "runas"
            });
            if (setup is null || !setup.WaitForExit(30000))
                throw new InvalidOperationException("บริการยังไม่ตอบกลับ");
            // A service is ready only if running, not merely present in sc.exe.
            for (var retry = 0; retry < 5; retry++)
            {
                if (QueryBonjourService().running) return true;
                System.Threading.Thread.Sleep(300);
            }
            throw new InvalidOperationException("Bonjour Service ยังไม่ได้เริ่มทำงาน");
        }
        catch (Exception ex)
        {
            _receiverIssue = "Bonjour Service ไม่พร้อม: " + ex.Message;
            MessageBox.Show(this, _receiverIssue, "AirPlay Discovery",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return false;
        }
    }

    private void LoadConfiguredAirPlayName()
    {
        var paths = new[]
        {
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
                "uxplay-windows", "arguments.txt"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                "leapbtw", "uxplay-windows", "arguments.txt")
        };
        foreach (var file in paths)
        {
            try
            {
                if (!File.Exists(file)) continue;
                var match = Regex.Match(File.ReadAllText(file), @"(?:^|\s)-n\s+([^\s]+)");
                if (match.Success) _receiverName.Text = Environment.ExpandEnvironmentVariables(match.Groups[1].Value);
                return; // Respect a system-wide configuration even without a -n option.
            }
            catch (Exception ex) { _receiverIssue = "ไม่สามารถอ่านการตั้งค่า AirPlay: " + ex.Message; }
        }
    }

    private void ShowDiscoveryDiagnostics()
    {
        _bundledEngine = FindEngine();
        var service = QueryBonjourService();
        var receiverAlive = _airplayProcess is { HasExited: false };
        var report = new System.Text.StringBuilder()
            .AppendLine("X-Stage Mirror PC " + VersionText)
            .AppendLine()
            .AppendLine("AirPlay Engine: " + (_bundledEngine is null ? "ไม่ครบ" : "พบไฟล์ครบ"))
            .AppendLine("Bonjour Service: " + (service.running ? "กำลังทำงาน" :
                service.installed ? "ติดตั้งแล้วแต่หยุดทำงาน" : "ไม่พบ"))
            .AppendLine("ตัวรับ AirPlay: " + (receiverAlive ? "เปิดอยู่ (ยังไม่ยืนยัน mDNS)" : "ยังไม่ได้เปิด"))
            .AppendLine("ชื่อเครื่องรับ: " + _receiverName.Text.Trim());
        try
        {
            var addresses = System.Net.NetworkInformation.NetworkInterface.GetAllNetworkInterfaces()
                .Where(n => n.OperationalStatus == System.Net.NetworkInformation.OperationalStatus.Up &&
                    n.NetworkInterfaceType != System.Net.NetworkInformation.NetworkInterfaceType.Loopback)
                .SelectMany(n => n.GetIPProperties().UnicastAddresses)
                .Where(a => a.Address.AddressFamily == System.Net.Sockets.AddressFamily.InterNetwork)
                .Take(5).Select(a => a.Address.ToString()).ToArray();
            report.AppendLine("IPv4 ของ PC: " + (addresses.Length > 0 ?
                string.Join(", ", addresses) : "ไม่พบการเชื่อมต่อเครือข่าย"));
        }
        catch { report.AppendLine("ตรวจสอบ IPv4 ไม่สำเร็จ"); }
        report.AppendLine()
            .AppendLine("iOS: ให้ iPhone/iPad และ PC อยู่ LAN เดียวกัน ไม่ใช้ Guest Wi-Fi ที่แยกอุปกรณ์")
            .AppendLine("หากใช้เครือข่ายที่เชื่อถือได้ ให้ตรวจว่า Windows Firewall อนุญาต AirPlay บน Private")
            .AppendLine("Android: ต้องรองรับ Miracast และเปิด Wireless Display ของ Windows")
            .AppendLine("สถานะเปิดโปรเซสไม่ใช่การยืนยันว่าโทรศัพท์มองเห็นเครื่องรับแล้ว");
        MessageBox.Show(this, report.ToString(), "ตรวจการค้นพบอุปกรณ์",
            MessageBoxButtons.OK, MessageBoxIcon.Information);
        RefreshAirPlayStatus();
    }

    private void RefreshAirPlayStatus()
    {
        bool alive = _airplayProcess is { HasExited: false };
        _receiverName.Enabled = !alive;
        _startButton.Enabled = !alive && _bundledEngine is not null;
        _stopButton.Enabled = alive;
        _iosStatus.Text = alive
            ? "● ตัวรับ AirPlay เปิดอยู่ • ให้ iPhone/iPad ค้นหาชื่อเครื่องรับใน LAN เดียวกัน"
            : _bundledEngine is null
                ? "● ชุด AirPlay Engine ไม่ครบ • ใช้ Setup EXE รุ่นเต็ม"
                : !string.IsNullOrEmpty(_receiverIssue)
                    ? "● " + _receiverIssue
                    : "● ยังไม่ได้เปิด AirPlay • กดเปิดรับ AirPlay";
        _iosStatus.ForeColor = alive ? Color.FromArgb(120, 235, 165)
            : _bundledEngine is null || !string.IsNullOrEmpty(_receiverIssue) ? Color.Orange : Accent;
    }

    private bool WriteNameSettings(string name, bool autoStart)
    {
        var systemFile = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
            "uxplay-windows", "arguments.txt");
        if (File.Exists(systemFile))
        {
            if (autoStart) return true; // Never modify administrator-managed configuration.
            var configured = Regex.Match(File.ReadAllText(systemFile), @"(?:^|\s)-n\s+([^\s]+)");
            if (configured.Success &&
                string.Equals(configured.Groups[1].Value, name, StringComparison.OrdinalIgnoreCase))
                return true;
            MessageBox.Show(this, "พบไฟล์กำหนดค่า AirPlay ระดับเครื่อง ชื่อเครื่องรับถูกควบคุมโดยผู้ดูแลระบบ\n" +
                systemFile, "ชื่อเครื่องรับ AirPlay", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return false;
        }
        var config = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "leapbtw", "uxplay-windows", "arguments.txt");
        var advertised = Regex.Replace(name.Trim(), @"\s+", "-");
        var desired = "-n " + advertised + " -nh";
        if (File.Exists(config))
        {
            var previous = File.ReadAllText(config).Trim();
            if (previous == desired || autoStart) return true; // Preserve existing advanced options.
            if (MessageBox.Show(this,
                "การเปลี่ยนชื่อเครื่องรับจะเขียนทับ arguments.txt เดิมของ UxPlay\n" +
                "ต้องการแทนที่การตั้งค่าเดิมหรือไม่?", "ยืนยันการเปลี่ยนชื่อ",
                MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes)
                return false;
        }
        Directory.CreateDirectory(Path.GetDirectoryName(config)!);
        File.WriteAllText(config, desired + Environment.NewLine);
        return true;
    }

    private void StartAirPlay(bool autoStart = false)
    {
        try
        {
            if (_airplayProcess is { HasExited: false }) return;
            if (!autoStart) { _manualAirPlayStop = false; _recoveryAttempts = 0; }
            _bundledEngine = FindEngine();
            if (_bundledEngine is null)
                throw new FileNotFoundException("AirPlay Engine ไม่ครบ กรุณาติดตั้งด้วย Setup EXE รุ่นเต็ม");
            var name = _receiverName.Text.Trim();
            if (name.Length is < 1 or > 55 ||
                !Regex.IsMatch(name, @"^[\p{L}\p{N} _().-]+$"))
                throw new InvalidOperationException("ชื่อเครื่องรับต้องเป็นตัวอักษร/ตัวเลข ความยาว 1–55 ตัว");
            if (!WriteNameSettings(name, autoStart)) return;
            if (!EnsureBonjourService(autoStart)) { RefreshAirPlayStatus(); return; }
            _receiverName.Text = Regex.Replace(name, @"\s+", "-");
            _lastReceiverLaunchUtc = DateTime.UtcNow;
            _airplayProcess?.Dispose();
            _airplayProcess = Process.Start(new ProcessStartInfo
            {
                FileName = _bundledEngine,
                WorkingDirectory = Path.GetDirectoryName(_bundledEngine)!,
                UseShellExecute = true
            });
            _receiverIssue = _airplayProcess is null ? "ไม่สามารถเริ่ม AirPlay Engine" : "";
            RefreshAirPlayStatus();
        }
        catch (Exception ex)
        {
            _receiverIssue = "เปิดตัวรับ AirPlay ไม่สำเร็จ: " + ex.Message;
            if (!autoStart) MessageBox.Show(this, ex.Message, "AirPlay Error",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
            RefreshAirPlayStatus();
        }
    }

    private void StopOwnProcess()
    {
        try
        {
            if (_airplayProcess is { HasExited: false })
            {
                _airplayProcess.CloseMainWindow();
                if (!_airplayProcess.WaitForExit(1200)) _airplayProcess.Kill(entireProcessTree: true);
            }
        }
        catch { /* Native process may already have exited. */ }
        finally { _airplayProcess?.Dispose(); _airplayProcess = null; }
    }

    private void StopAirPlay()
    {
        _manualAirPlayStop = true;
        _lastReceiverLaunchUtc = DateTime.MinValue;
        StopOwnProcess();
        _receiverIssue = "";
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
            if (available && Version.TryParse(version, out var remote) && remote > new Version(0, 1, 1))
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
