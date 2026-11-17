using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Windows.Forms;
using Microsoft.Win32;

namespace XStageMirrorIOSPC;

/// <summary>
/// Full-screen receiver shell. The actual video remains in UxPlay's native
/// D3D11/GStreamer surface; never copies decoded frames or re-parents it.
/// This prevents the UI shell from adding work to the video pipeline.
/// </summary>
public sealed class MainForm : Form
{
    private const string VersionText = "v1.0.7 · Build 1008";
    private const string UpdateFeed =
        "https://webbase-x.github.io/xstage/downloads/mirror-ios-pc-preview-latest.json";
    private static readonly Color Night = Color.FromArgb(8, 15, 28);
    private static readonly Color Deep = Color.FromArgb(18, 40, 69);
    private static readonly Color Frost = Color.FromArgb(235, 247, 255);
    private static readonly Color Turquoise = Color.FromArgb(105, 228, 237);
    private static readonly Color Soft = Color.FromArgb(163, 190, 212);

    // Logo uses the same source artwork as the EXE icon; PNG is built into the
    // app's managed assembly, so no external runtime file or network is needed.
    private readonly PictureBox _logo = new()
    {
        AccessibleName = "โลโก้ X-Stage Mirror PC",
        SizeMode = PictureBoxSizeMode.Zoom,
        BackColor = Color.Transparent,
        TabStop = false
    };
    private readonly Label _title = MakeLabel("", 55, true, Frost);
    private readonly Label _number = MakeLabel("", 92, true, Turquoise);
    private readonly Label _version = MakeLabel("", 15, false, Soft);
    private readonly Label _status = MakeLabel("", 20, false, Frost);
    private readonly Label _network = MakeLabel("", 16, false, Soft);
    private readonly Button _minimize = new()
    {
        Text = "—", AccessibleName = "ย่อหน้าต่าง",
        BackColor = Color.FromArgb(30, 54, 79), ForeColor = Color.White,
        FlatStyle = FlatStyle.Flat, TabStop = false,
        Font = new Font("Segoe UI", 17, FontStyle.Bold)
    };
    private readonly Button _closeButton = new()
    {
        Text = "×", AccessibleName = "ปิดแอป",
        BackColor = Color.FromArgb(57, 39, 55), ForeColor = Color.White,
        FlatStyle = FlatStyle.Flat, TabStop = false,
        Font = new Font("Segoe UI", 18, FontStyle.Bold)
    };
    private readonly System.Windows.Forms.Timer _clock = new() { Interval = 1300 };
    private readonly VideoWindowPresentation _video = new();
    private readonly string _name = ReceiverIdentity.DisplayName;
    private readonly string _configFolder = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "X-Stage", "Mirror iOS PC");

    private Process? _engine;
    private string? _engineExe;
    private bool _closing;
    private bool _manualStop;
    private bool _starting;
    private bool _checkingPeers;
    private readonly MirrorAutoUpdateManager _autoUpdates;
    private string? _updateNotice;
    private DateTime _updateNoticeUntil = DateTime.MinValue;
    private int _restarts;
    private DateTime _lastLaunch = DateTime.MinValue;
    private DateTime _lastPeerCheck = DateTime.MinValue;
    private DateTime _lastNetworkCheck = DateTime.MinValue;
    private string _networkText = "กำลังตรวจสอบเครือข่าย";
    private string _receiverIssue = "";
    private string _lastPeerText = "ยังไม่มีอุปกรณ์เชื่อมต่อ";
    private string _renderer = "d3d11";
    private bool _lowLatency;
    // Controlled by X-Stage only; preserve the user’s other UxPlay arguments.
    private const string FastPreviewArguments = " -vsync no -s 1280x720 -fps 30";
    private readonly Dictionary<string, (object? value, RegistryValueKind kind, bool existed)> _originalQtSettings = new();

    public MainForm()
    {
        Text = "X-Stage Mirror iOS PC | " + _name;
        FormBorderStyle = FormBorderStyle.None;
        WindowState = FormWindowState.Maximized;
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Night;
        ForeColor = Frost;
        AutoScaleMode = AutoScaleMode.Dpi;
        KeyPreview = true;
        DoubleBuffered = true;
        ResizeRedraw = true;
        ShowInTaskbar = true;
        try
        {
            var embedded = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            if (embedded is not null) Icon = embedded;
        }
        catch { /* The EXE still works if Windows cannot load its embedded icon. */ }
        _logo.Image = LoadBrandLogo();

        _minimize.FlatAppearance.BorderSize = 0;
        _closeButton.FlatAppearance.BorderSize = 0;
        _minimize.Click += (_, _) => WindowState = FormWindowState.Minimized;
        _closeButton.Click += (_, _) =>
        {
            if (MessageBox.Show(this, "ปิด X-Stage Mirror iOS PC หรือไม่?",
                    "ปิดแอป", MessageBoxButtons.YesNo,
                    MessageBoxIcon.Question) == DialogResult.Yes)
                Close();
        };

        _title.Text = "X-Stage Mirror PC";
        _number.Text = "No." + ReceiverIdentity.Number.ToString("D4");
        _version.Text = "MIRROR iOS PC     " + VersionText;
        _status.Text = "กำลังเตรียมตัวรับ AirPlay";
        _network.Text = "ตรวจสอบเครือข่าย…";
        Controls.AddRange([_logo, _title, _number, _version, _status, _network,
            _minimize, _closeButton]);
        _autoUpdates = new MirrorAutoUpdateManager(
            message =>
            {
                if (_closing || IsDisposed || !IsHandleCreated) return;
                try
                {
                    BeginInvoke(new Action(() =>
                    {
                        if (_closing || IsDisposed) return;
                        _updateNotice = message;
                        _updateNoticeUntil = DateTime.UtcNow.AddSeconds(12);
                        _status.Text = message;
                    }));
                }
                catch (InvalidOperationException) { /* The window is closing. */ }
            },
            () =>
            {
                if (_closing || IsDisposed || !IsHandleCreated) return;
                try
                {
                    BeginInvoke(new Action(() =>
                    {
                        if (!_closing && !IsDisposed) Close();
                    }));
                }
                catch (InvalidOperationException) { /* The window is closing. */ }
            });
        Resize += (_, _) => LayoutWelcome();
        KeyDown += OnReceiverKeyDown;
        Shown += async (_, _) =>
        {
            LayoutWelcome();
            _engineExe = FindEngine();
            _renderer = LoadRendererPreference();
            _lowLatency = LoadLatencyPreference();
            UpdateNetworkStatus();
            await StartAirPlayAsync();
            _ = _autoUpdates.CheckAsync();
        };
        FormClosing += (_, _) =>
        {
            _closing = true;
            _clock.Stop();
            StopOwnEngine();
            RestoreQtSettings();
        };
        FormClosed += (_, _) =>
        {
            var image = _logo.Image;
            _logo.Image = null;
            image?.Dispose();
        };

        _clock.Tick += (_, _) => TickReceiver();
        _clock.Start();
        LayoutWelcome();
    }

    private static Image? LoadBrandLogo()
    {
        // EmbeddedResource is generated from assets/app-icons/mirror-ios-pc.svg
        // during CI, and survives single-file .NET publishing.
        using var stream = typeof(MainForm).Assembly
            .GetManifestResourceStream("XStageMirrorIOSPC.logo.png");
        if (stream is not null)
        {
            using var source = Image.FromStream(stream);
            return new Bitmap(source);
        }
        // Keep a useful logo if a developer compiled outside the official pipeline.
        try { return Icon.ExtractAssociatedIcon(Application.ExecutablePath)?.ToBitmap(); }
        catch { return null; }
    }

    private static Label MakeLabel(string text, float size, bool bold, Color color) => new()
    {
        Text = text,
        ForeColor = color,
        BackColor = Color.Transparent,
        TextAlign = ContentAlignment.MiddleCenter,
        AutoEllipsis = false,
        Font = new Font("Segoe UI", size, bold ? FontStyle.Bold : FontStyle.Regular),
        UseCompatibleTextRendering = true
    };

    private void LayoutWelcome()
    {
        if (IsDisposed) return;
        var w = Math.Max(640, ClientSize.Width);
        var h = Math.Max(480, ClientSize.Height);
        const int buttonWidth = 52;
        const int buttonGap = 10;
        _closeButton.SetBounds(ClientSize.Width - buttonWidth - 24, 22, buttonWidth, 44);
        _minimize.SetBounds(ClientSize.Width - (buttonWidth * 2) - buttonGap - 24, 22,
            buttonWidth, 44);
        // Place the brand icon clearly above the title and preserve separation
        // from the two window buttons, receiver number and status text.
        var logoSize = Math.Clamp((int)Math.Min(w * 0.19, h * 0.185), 72, 168);
        var logoTop = Math.Max(76, (int)(h * 0.12));
        _logo.SetBounds(Math.Max(0, (ClientSize.Width - logoSize) / 2),
            logoTop, logoSize, logoSize);
        var titleTop = Math.Max(logoTop + logoSize + 7, h * 0.35);
        var titleHeight = h * 0.105;
        var numberTop = Math.Max(titleTop + titleHeight + 8, h * 0.48);
        var numberHeight = h * 0.19;
        var versionTop = Math.Max(numberTop + numberHeight + 9, h * 0.70);
        var versionHeight = Math.Max(23, h * 0.048);
        var statusTop = Math.Max(versionTop + versionHeight + 12, h * 0.79);
        var networkTop = Math.Max(statusTop + h * 0.058 + 8, h * 0.865);
        var largeTitle = Math.Clamp(w / 29f, 27, 62);
        var bigNumber = Math.Clamp(Math.Min(w / 13f, h / 5.6f), 44, 112);
        SetLabel(_title, largeTitle, titleTop, titleHeight);
        SetLabel(_number, bigNumber, numberTop, numberHeight);
        SetLabel(_version, Math.Clamp(w / 96f, 11, 17), versionTop, versionHeight);
        SetLabel(_status, Math.Clamp(w / 71f, 12, 21), statusTop, h * 0.058);
        SetLabel(_network, Math.Clamp(w / 90f, 11, 17), networkTop, h * 0.052);
        void SetLabel(Label label, float points, double top, double height)
        {
            if (Math.Abs(label.Font.Size - points) > 1)
                label.Font = new Font("Segoe UI", points,
                    label == _title || label == _number ? FontStyle.Bold : FontStyle.Regular);
            label.SetBounds(10, (int)top, Math.Max(0, ClientSize.Width - 20), (int)height);
        }
    }

    protected override void OnPaintBackground(PaintEventArgs e)
    {
        var rect = ClientRectangle;
        if (rect.Width <= 0 || rect.Height <= 0) return;
        using (var shade = new LinearGradientBrush(rect, Deep, Night, LinearGradientMode.ForwardDiagonal))
            e.Graphics.FillRectangle(shade, rect);
        e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
        var side = Math.Max(rect.Width, rect.Height);
        using var ring1 = new Pen(Color.FromArgb(14, Turquoise), 2);
        using var ring2 = new Pen(Color.FromArgb(12, 183, 226, 255), 1);
        e.Graphics.DrawEllipse(ring1, rect.Width / 2f - side * 0.33f, rect.Height / 2f - side * 0.33f,
            side * 0.66f, side * 0.66f);
        e.Graphics.DrawEllipse(ring2, rect.Width / 2f - side * 0.4f, rect.Height / 2f - side * 0.4f,
            side * 0.8f, side * 0.8f);
    }

    private void TickReceiver()
    {
        if (_closing || IsDisposed) return;
        var alive = _engine is { HasExited: false };
        if (alive)
        {
            // A native fullscreen video window automatically obscures this
            // welcome page. When the window closes, the welcome page remains.
            if (_video.Present(_engine!.Id, Screen.FromControl(this)))
            {
                _status.Text = "กำลังรับภาพ AirPlay";
                _receiverIssue = "";
            }
            else if (!string.IsNullOrWhiteSpace(_receiverIssue))
                _status.Text = _receiverIssue;
            else
                _status.Text = "พร้อมรับภาพจาก iPhone / iPad";
        }
        else
        {
            _video.Reset();
            _status.Text = _engineExe is null ? "ไม่พบชุด AirPlay Engine" :
                !string.IsNullOrWhiteSpace(_receiverIssue) ? _receiverIssue :
                "กำลังเริ่มรับ AirPlay";
            if (!_manualStop && !_starting && _engineExe is not null && _lastLaunch != DateTime.MinValue &&
                DateTime.UtcNow - _lastLaunch > TimeSpan.FromSeconds(8) && _restarts < 3)
            {
                _restarts++;
                _ = StartAirPlayAsync(recovery: true);
            }
        }
        if (DateTime.UtcNow - _lastNetworkCheck > TimeSpan.FromSeconds(8))
            UpdateNetworkStatus();
        if (alive && !_checkingPeers && DateTime.UtcNow - _lastPeerCheck > TimeSpan.FromSeconds(9))
            _ = CheckPeersAsync();
        if (_updateNotice is not null && DateTime.UtcNow < _updateNoticeUntil)
            _status.Text = _updateNotice;
        _ = _autoUpdates.CheckAsync();
    }

    private void UpdateNetworkStatus()
    {
        _lastNetworkCheck = DateTime.UtcNow;
        try
        {
            var interfaces = NetworkInterface.GetAllNetworkInterfaces()
                .Where(n => n.OperationalStatus == OperationalStatus.Up &&
                    n.NetworkInterfaceType != NetworkInterfaceType.Loopback)
                .ToArray();
            var matches = interfaces.SelectMany(n => n.GetIPProperties().UnicastAddresses
                .Where(ip => ip.Address.AddressFamily == AddressFamily.InterNetwork &&
                    !IPAddress.IsLoopback(ip.Address))
                .Select(ip => (name: n.NetworkInterfaceType == NetworkInterfaceType.Wireless80211
                    ? "Wi-Fi" : "LAN", addr: ip.Address.ToString()))).ToArray();
            _networkText = matches.Length > 0 ?
                matches[0].name + "  ·  " + matches[0].addr : "ไม่มีการเชื่อมต่อ LAN / Wi-Fi";
        }
        catch { _networkText = "ตรวจสอบเครือข่ายไม่ได้"; }
        _network.Text = "●  " + _networkText + "    •    " +
            (_engine is { HasExited: false } ? "AirPlay พร้อมรับ" : "AirPlay ยังไม่พร้อม");
        _network.ForeColor = _networkText.StartsWith("ไม่มี") ? Color.FromArgb(255, 166, 111) : Soft;
    }

    private async Task CheckPeersAsync()
    {
        if (_checkingPeers || _engine is not { HasExited: false }) return;
        _checkingPeers = true;
        _lastPeerCheck = DateTime.UtcNow;
        try
        {
            int pid = _engine.Id;
            var probe = await Task.Run(() => AirPlaySessionMonitor.Probe(pid));
            if (_closing || IsDisposed) return;
            _lastPeerText = probe.PeerAddresses.Length > 0
                ? string.Join(", ", probe.PeerAddresses)
                : probe.VideoWindow ? "วิดีโอกำลังแสดง (ไม่มีชื่อผู้ส่ง)" : "ยังไม่พบการเชื่อมต่อ TCP";
        }
        catch { _lastPeerText = "ตรวจสอบเซสชันไม่ได้"; }
        finally { _checkingPeers = false; }
    }

    private static string? FindEngine()
    {
        string folder = Path.Combine(AppContext.BaseDirectory, "engine", "uxplay-windows");
        string[] required =
        [
            "uxplay-windows.exe", "mDNSResponder.exe", "Qt6Core.dll",
            "Qt6Gui.dll", "libgstreamer-1.0-0.dll",
            Path.Combine("platforms", "qwindows.dll"),
            Path.Combine("lib", "gstreamer-1.0", "libgstcoreelements.dll")
        ];
        return required.All(file => File.Exists(Path.Combine(folder, file))) ?
            Path.Combine(folder, "uxplay-windows.exe") : null;
    }

    private static bool BonjourIsRunning()
    {
        try
        {
            using var p = Process.Start(new ProcessStartInfo
            {
                FileName = "sc.exe",
                Arguments = "query \"Bonjour Service\"",
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true
            });
            if (p is null) return false;
            string output = p.StandardOutput.ReadToEnd();
            return p.WaitForExit(3000) && p.ExitCode == 0 &&
                Regex.IsMatch(output, @"STATE\s*:\s*4\s+RUNNING", RegexOptions.IgnoreCase);
        }
        catch { return false; }
    }

    private bool EnsureBonjour()
    {
        if (BonjourIsRunning()) return true;
        if (_engineExe is null) return false;
        var question = "Bonjour Service ยังไม่ทำงานและจำเป็นสำหรับ AirPlay" +
            Environment.NewLine + "อนุญาตให้ Windows เริ่มบริการที่ติดตั้งพร้อมแอปหรือไม่?";
        if (MessageBox.Show(this, question, "AirPlay", MessageBoxButtons.YesNo,
                MessageBoxIcon.Question) != DialogResult.Yes) return false;
        var installed = IsBonjourInstalled();
        try
        {
            using var process = Process.Start(new ProcessStartInfo
            {
                FileName = installed ? "sc.exe" :
                    Path.Combine(Path.GetDirectoryName(_engineExe)!, "mDNSResponder.exe"),
                Arguments = installed ? "start \"Bonjour Service\"" : "-install",
                Verb = "runas",
                UseShellExecute = true
            });
            if (process is null || !process.WaitForExit(30000)) return false;
            for (int i = 0; i < 5; i++)
            {
                if (BonjourIsRunning()) return true;
                System.Threading.Thread.Sleep(350);
            }
        }
        catch (Exception ex) { _receiverIssue = "Bonjour: " + ex.Message; }
        return false;
    }

    private static bool IsBonjourInstalled()
    {
        try
        {
            using var p = Process.Start(new ProcessStartInfo
            {
                FileName = "sc.exe", Arguments = "query \"Bonjour Service\"",
                UseShellExecute = false, CreateNoWindow = true
            });
            return p is not null && p.WaitForExit(3000) && p.ExitCode == 0;
        }
        catch { return false; }
    }

    private void ConfigureAirPlayName()
    {
        // UxPlay Windows reads whitespace-split arguments.txt. NBSP characters
        // retain human-readable separation while remaining a single -n value.
        var name = Regex.Replace(_name, @"\s+", "\u00A0");
        var cfg = Path.Combine(Environment.GetFolderPath(
            Environment.SpecialFolder.ApplicationData), "leapbtw", "uxplay-windows", "arguments.txt");
        Directory.CreateDirectory(Path.GetDirectoryName(cfg)!);
        var target = "-n " + name + " -nh";
        if (!File.Exists(cfg))
        {
            File.WriteAllText(cfg, target + Environment.NewLine);
            return;
        }
        var old = File.ReadAllText(cfg).Trim();
        // Keep unrelated advanced UxPlay options; only replace advertised -n.
        if (Regex.IsMatch(old, @"(?:^|\s)-n\s+\S+"))
            old = Regex.Replace(old, @"(?:^|\s)-n\s+\S+", " -n " + name);
        else old += " -n " + name;
        if (!Regex.IsMatch(old, @"(?:^|\s)-nh(?:\s|$)"))
            old += " -nh";
        // Only remove the exact options the previous X-Stage fast-mode run added.
        // Smooth mode remains the existing UxPlay/GStreamer behavior.
        old = old.Replace(FastPreviewArguments, "", StringComparison.Ordinal);
        if (_lowLatency) old += FastPreviewArguments;
        var desired = old.Trim() + Environment.NewLine;
        if (File.ReadAllText(cfg) != desired)
            File.WriteAllText(cfg, desired);
    }

    private string LoadRendererPreference()
    {
        Directory.CreateDirectory(_configFolder);
        var config = Path.Combine(_configFolder, "renderer.txt");
        try
        {
            var saved = File.Exists(config) ? File.ReadAllText(config).Trim() : "d3d11";
            return saved == "auto" ? "auto" : "d3d11";
        }
        catch { return "d3d11"; }
    }

    private void SaveRendererPreference()
    {
        Directory.CreateDirectory(_configFolder);
        File.WriteAllText(Path.Combine(_configFolder, "renderer.txt"), _renderer);
    }

    private bool LoadLatencyPreference()
    {
        try
        {
            var preference = Path.Combine(_configFolder, "latency-mode.txt");
            return File.Exists(preference) &&
                File.ReadAllText(preference).Trim() == "fast";
        }
        catch { return false; }
    }

    private void SaveLatencyPreference()
    {
        Directory.CreateDirectory(_configFolder);
        File.WriteAllText(Path.Combine(_configFolder, "latency-mode.txt"),
            _lowLatency ? "fast" : "smooth");
    }

    private void ApplyNativeRendererSettings()
    {
        // The pinned Qt UxPlay launcher picks -vs and -fs from QSettings.
        // Restore original values on a normal exit to avoid leaving other
        // independently installed UxPlay installations reconfigured.
        using var key = Registry.CurrentUser.CreateSubKey(@"Software\leapbtw\uxplay-windows");
        if (key is null) throw new InvalidOperationException("เขียนค่าตัวเรนเดอร์ UxPlay ไม่ได้");
        StoreAndSet("renderer_mode", _renderer, RegistryValueKind.String);
        StoreAndSet("force_fs_enabled", 1, RegistryValueKind.DWord);
        StoreAndSet("ble_enabled", 0, RegistryValueKind.DWord);
        void StoreAndSet(string name, object desired, RegistryValueKind kind)
        {
            if (!_originalQtSettings.ContainsKey(name))
            {
                var existed = key.GetValueNames().Contains(name);
                var value = existed ? key.GetValue(name) : null;
                var oldKind = existed ? key.GetValueKind(name) : kind;
                _originalQtSettings[name] = (value, oldKind, existed);
            }
            key.SetValue(name, desired, kind);
        }
    }

    private void RestoreQtSettings()
    {
        try
        {
            using var key = Registry.CurrentUser.CreateSubKey(@"Software\leapbtw\uxplay-windows");
            if (key is null) return;
            foreach (var (name, old) in _originalQtSettings)
            {
                if (!old.existed) key.DeleteValue(name, false);
                else if (old.value is not null) key.SetValue(name, old.value, old.kind);
            }
        }
        catch { /* Preserve any operating system restrictions on registry writing. */ }
    }

    private async Task StartAirPlayAsync(bool recovery = false)
    {
        if (_starting || _closing || _engine is { HasExited: false }) return;
        _starting = true;
        try
        {
            _engineExe = FindEngine();
            if (_engineExe is null) throw new FileNotFoundException(
                "ไม่พบ UxPlay/GStreamer โปรดติดตั้งด้วย Setup EXE รุ่นเต็ม");
            if (!recovery) _restarts = 0;
            if (!BonjourIsRunning() && !EnsureBonjour())
                throw new InvalidOperationException("Bonjour ยังไม่พร้อมสำหรับประกาศ AirPlay");
            // Do not kill or hijack a receiver launched by another application.
            if (Process.GetProcessesByName("uxplay-windows")
                .Any(p => { using (p) return !p.HasExited; }))
                throw new InvalidOperationException(
                    "มี UxPlay อีกตัวเปิดอยู่ กรุณาปิดแอปรับภาพรุ่นเก่าเพื่อไม่ให้แย่งพอร์ต");
            ConfigureAirPlayName();
            ApplyNativeRendererSettings();
            _lastLaunch = DateTime.UtcNow;
            _manualStop = false;
            _video.Reset();
            _engine?.Dispose();
            _engine = Process.Start(new ProcessStartInfo
            {
                FileName = _engineExe,
                WorkingDirectory = Path.GetDirectoryName(_engineExe)!,
                UseShellExecute = true
            });
            if (_engine is null) throw new InvalidOperationException("เปิดตัวรับ AirPlay ไม่สำเร็จ");
            _receiverIssue = "";
            UpdateNetworkStatus();
            // A queued continuation avoids blocking fullscreen drawing.
            await Task.Yield();
        }
        catch (Exception ex)
        {
            _receiverIssue = ex.Message;
            _status.Text = ex.Message;
            WriteDiagnostic("Startup: " + ex.Message);
        }
        finally { _starting = false; }
    }

    private void StopOwnEngine()
    {
        _video.Reset();
        try
        {
            if (_engine is { HasExited: false })
            {
                _engine.CloseMainWindow();
                if (!_engine.WaitForExit(1100))
                    _engine.Kill(entireProcessTree: true);
            }
        }
        catch { /* The engine may have exited while disconnecting. */ }
        finally { _engine?.Dispose(); _engine = null; }
    }

    private void WriteDiagnostic(string message)
    {
        try
        {
            Directory.CreateDirectory(_configFolder);
            File.AppendAllText(Path.Combine(_configFolder, "receiver.log"),
                DateTimeOffset.Now.ToString("O") + "  " + message + Environment.NewLine);
        }
        catch { }
    }

    private void OnReceiverKeyDown(object? sender, KeyEventArgs e)
    {
        if (e.KeyCode == Keys.F1)
        {
            var message = _name + Environment.NewLine +
                VersionText + Environment.NewLine + Environment.NewLine +
                "เครือข่าย: " + _networkText + Environment.NewLine +
                "ตัวรับ: " + (_engine is { HasExited: false } ? "ทำงาน" : "ยังไม่พร้อม") +
                Environment.NewLine + "เรนเดอร์: " + _renderer +
                Environment.NewLine + "ผู้ส่ง: " + _lastPeerText + Environment.NewLine +
                "วิดีโอเต็มจอ: " + (_video.IsShowing ? "ใช่" : "ยังไม่เปิด") +
                Environment.NewLine + Environment.NewLine +
                "โหมด: " + (_lowLatency ? "ตอบสนองเร็ว 720p30 (ทดลอง)" : "ลื่นไหลเดิม") +
                Environment.NewLine +
                "F5 เริ่ม AirPlay ใหม่ · F8 สลับ D3D11/Auto · F9 เปลี่ยนโหมดหน่วง" +
                Environment.NewLine + "Esc ออก";
            MessageBox.Show(this, message, "สถานะ X-Stage Mirror iOS PC",
                MessageBoxButtons.OK, MessageBoxIcon.Information);
            e.Handled = true;
        }
        else if (e.KeyCode == Keys.F5)
        {
            e.Handled = true;
            if (MessageBox.Show(this, "เริ่มตัวรับ AirPlay ใหม่หรือไม่? การเชื่อมต่อปัจจุบันจะถูกตัด",
                "รีสตาร์ต AirPlay", MessageBoxButtons.YesNo,
                MessageBoxIcon.Question) == DialogResult.Yes)
            {
                StopOwnEngine();
                _receiverIssue = "";
                _restarts = 0;
                _ = StartAirPlayAsync();
            }
        }
        else if (e.KeyCode == Keys.F8)
        {
            e.Handled = true;
            var next = _renderer == "d3d11" ? "auto" : "d3d11";
            if (MessageBox.Show(this, "เปลี่ยนตัวเรนเดอร์เป็น " + next +
                    " และเริ่มตัวรับใหม่หรือไม่? การเชื่อมต่อปัจจุบันจะถูกตัด",
                "เลือกตัวเรนเดอร์", MessageBoxButtons.YesNo,
                MessageBoxIcon.Question) == DialogResult.Yes)
            {
                _renderer = next;
                SaveRendererPreference();
                StopOwnEngine();
                _restarts = 0;
                _ = StartAirPlayAsync();
            }
        }
        else if (e.KeyCode == Keys.F9)
        {
            e.Handled = true;
            var next = !_lowLatency;
            var description = next
                ? "ทดลองลดความหน่วง: 720p/30 FPS และวิธีซิงก์แบบตอบสนองเร็ว อาจทำให้เสียงไม่ตรงภาพ"
                : "กลับสู่โหมดลื่นไหลเดิมและรักษาการซิงก์เสียงกับภาพ";
            if (MessageBox.Show(this, description + Environment.NewLine +
                    "การเปลี่ยนจะตัดการเชื่อมต่อปัจจุบัน ยืนยันหรือไม่?",
                    "X-Stage Mirror PC · โหมดการแสดงผล",
                    MessageBoxButtons.YesNo, MessageBoxIcon.Question) == DialogResult.Yes)
            {
                _lowLatency = next;
                SaveLatencyPreference();
                StopOwnEngine();
                _restarts = 0;
                _ = StartAirPlayAsync();
            }
        }
        else if (e.KeyCode == Keys.Escape)
        {
            e.Handled = true;
            if (MessageBox.Show(this, "ออกจาก X-Stage Mirror iOS PC หรือไม่?",
                "ออกจากแอป", MessageBoxButtons.YesNo,
                MessageBoxIcon.Question) == DialogResult.Yes)
                Close();
        }
    }

}
