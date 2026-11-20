using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Net.NetworkInformation;
using System.Reflection;
using System.Text;
using System.Windows.Forms;

namespace XStageMirrorAndroidPC;

public sealed class MainForm : Form
{
    private static readonly string VersionText = GetVersionText();
    private static readonly Color Night = Color.FromArgb(8, 15, 28);
    private static readonly Color Deep = Color.FromArgb(18, 40, 69);
    private static readonly Color Frost = Color.FromArgb(235, 247, 255);
    private static readonly Color Turquoise = Color.FromArgb(105, 228, 237);
    private static readonly Color Soft = Color.FromArgb(163, 190, 212);
    private static readonly Color Warning = Color.FromArgb(255, 177, 113);

    private readonly PictureBox _logo = new()
    {
        SizeMode = PictureBoxSizeMode.Zoom,
        BackColor = Color.Transparent,
        AccessibleName = "X-Stage Mirror Android PC"
    };
    private readonly Label _title = MakeLabel("X-Stage Mirror PC", 55, true, Frost);
    private readonly Label _number = MakeLabel("No." + ReceiverIdentity.Number.ToString("D4"), 92, true, Turquoise);
    private readonly Label _version = MakeLabel("MIRROR ANDROID PC     " + VersionText, 15, false, Soft);
    private readonly Label _status = MakeLabel("กำลังเตรียมตัวรับ Miracast", 20, false, Frost);
    private readonly Label _network = MakeLabel(
        "Windows PC: " + Environment.MachineName + "   ·   Android: Smart View / Screen Cast", 16, false, Soft);
    private readonly Button _minimize = MakeWindowButton("—", "ย่อหน้าต่าง", Color.FromArgb(30, 54, 79));
    private readonly Button _closeButton = MakeWindowButton("×", "ปิดแอป", Color.FromArgb(57, 39, 55));
    private readonly System.Windows.Forms.Timer _poll = new() { Interval = 1200 };
    private readonly MirrorAutoUpdateManager _autoUpdates;

    private string _receiverStatus = "กำลังเตรียมตัวรับ Miracast";
    private string _receiverWindow = "ยังไม่พบหน้าต่าง Connect";
    private string? _updateNotice;
    private DateTime _updateNoticeUntil = DateTime.MinValue;
    private bool _wifiAvailable;
    private bool _connectExecutableAvailable;
    private bool _connectProcessRunning;
    private bool _launchRequested;
    private bool _closing;
    private bool _nativePresented;
    private int _missedWindows;
    private int _launchRetries;
    private DateTime _lastLaunchUtc = DateTime.MinValue;
    private bool _installingWindowsFeature;
    private bool _autoRepairAttempted;
    private Process? _repairProcess;
    private DateTime _repairStartedUtc;
    private string _repairMessage = "";
    private string _repairFailure = "";
    private const string DefaultDeviceHint = "Windows PC: " + Environment.MachineName +
        "   ·   Android: Smart View / Screen Cast";
    private string _lastLaunchError = "";

    public MainForm()
    {
        Text = "X-Stage Mirror Android PC | " + ReceiverIdentity.DisplayName;
        FormBorderStyle = FormBorderStyle.None;
        WindowState = FormWindowState.Maximized;
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Night;
        ForeColor = Frost;
        Font = new Font("Segoe UI", 10);
        AutoScaleMode = AutoScaleMode.Dpi;
        KeyPreview = true;
        DoubleBuffered = true;
        ResizeRedraw = true;
        ShowInTaskbar = true;
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true);
        try
        {
            var embedded = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            if (embedded is not null) Icon = embedded;
        }
        catch { /* A missing custom icon must never prevent the receiver from starting. */ }

        _logo.Image = LoadBrandLogo();
        _minimize.Click += (_, _) => WindowState = FormWindowState.Minimized;
        _closeButton.Click += (_, _) => ConfirmClose();
        _status.Cursor = Cursors.Hand;
        _status.AccessibleName = "สถานะตัวรับ Miracast กดเพื่อดูการวินิจฉัย";
        _status.Click += async (_, _) => { if (_launchRetries >= 3) await PrepareWindowsFeatureAsync(); else ShowDiagnostics(); };

        Controls.AddRange([_logo, _title, _number, _version, _status, _network,
            _minimize, _closeButton]);
        var menu = BuildContextMenu();
        ContextMenuStrip = menu;
        foreach (Control c in Controls) c.ContextMenuStrip = menu;

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
                        _updateNoticeUntil = DateTime.UtcNow.AddSeconds(20);
                        RenderStatus();
                    }));
                }
                catch (InvalidOperationException) { /* Form is closing. */ }
            },
            () =>
            {
                if (_closing || IsDisposed || !IsHandleCreated) return;
                try { BeginInvoke(new Action(() => { if (!_closing && !IsDisposed) Close(); })); }
                catch (InvalidOperationException) { }
            });

        Resize += (_, _) => LayoutWelcome();
        KeyDown += OnReceiverKeyDown;
        Shown += (_, _) =>
        {
            LayoutWelcome();
            _status.Text = "ขั้นตอน 1/4 · กำลังตรวจสอบ Windows และอุปกรณ์";
            CheckLocalEnvironment();
            _poll.Start();
            if (WindowsPreparation.HasWirelessAdapter()) OpenReceiver();
            else _ = PrepareWindowsFeatureAsync();
            _ = _autoUpdates.CheckAsync();
        };
        _poll.Tick += (_, _) =>
        {
            PollPreparation();
            CheckWindowsReceiverSession();
            _ = _autoUpdates.CheckAsync();
        };
        FormClosing += (_, _) =>
        {
            _closing = true;
            _poll.Stop();
        };
        FormClosed += (_, _) =>
        {
            var image = _logo.Image;
            _logo.Image = null;
            image?.Dispose();
        };
        LayoutWelcome();
    }

    private static string GetVersionText()
    {
        var v = typeof(MainForm).Assembly.GetCustomAttribute<AssemblyFileVersionAttribute>()?.Version;
        var p = v?.Split('.');
        return p is { Length: 4 } ? $"v{p[0]}.{p[1]}.{p[2]} · Build {p[3]}" : "ไม่ทราบเวอร์ชัน EXE";
    }

    private static Image? LoadBrandLogo()
    {
        using var stream = typeof(MainForm).Assembly
            .GetManifestResourceStream("XStageMirrorAndroidPC.logo.png");
        if (stream is not null)
        {
            using var original = Image.FromStream(stream);
            return new Bitmap(original);
        }
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

    private static Button MakeWindowButton(string text, string accessibleName, Color background)
    {
        var button = new Button
        {
            Text = text,
            AccessibleName = accessibleName,
            BackColor = background,
            ForeColor = Color.White,
            FlatStyle = FlatStyle.Flat,
            Cursor = Cursors.Hand,
            Font = new Font("Segoe UI", 15, FontStyle.Regular),
            TabStop = true
        };
        button.FlatAppearance.BorderSize = 0;
        return button;
    }

    private ContextMenuStrip BuildContextMenu()
    {
        var menu = new ContextMenuStrip();
        menu.Items.Add("จัดเตรียมตัวรับ Wireless Display ของ Windows", null,
            async (_, _) => await PrepareWindowsFeatureAsync());
        menu.Items.Add("เปิดตัวรับ Windows Wireless Display  (F5)", null, (_, _) => OpenReceiver());
        menu.Items.Add("ตั้งค่าการฉายภาพไปยังพีซี  (F6)", null,
            (_, _) => OpenSettings("ms-settings:project"));
        menu.Items.Add("ตรวจสอบ/ติดตั้ง Wireless Display  (F7)", null,
            (_, _) => OpenSettings("ms-settings:optionalfeatures"));
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("วิธีเชื่อมต่อและตรวจสอบอุปกรณ์  (F1)", null, (_, _) => ShowDiagnostics());
        return menu;
    }

    private void LayoutWelcome()
    {
        if (IsDisposed || ClientSize.Width <= 0 || ClientSize.Height <= 0) return;
        var w = Math.Max(640, ClientSize.Width);
        var h = Math.Max(480, ClientSize.Height);
        const int buttonWidth = 52;
        const int buttonGap = 10;
        _closeButton.SetBounds(Math.Max(0, ClientSize.Width - buttonWidth - 24), 22,
            buttonWidth, 44);
        _minimize.SetBounds(Math.Max(0, ClientSize.Width - (buttonWidth * 2) - buttonGap - 24),
            22, buttonWidth, 44);

        // Match Mirror iOS PC: centered logo, title, receiver number, build and two status lines.
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
        SetLabel(_title, Math.Clamp(w / 29f, 27, 62), titleTop, titleHeight);
        SetLabel(_number, Math.Clamp(Math.Min(w / 13f, h / 5.6f), 44, 112),
            numberTop, numberHeight);
        SetLabel(_version, Math.Clamp(w / 96f, 11, 17), versionTop, versionHeight);
        SetLabel(_status, Math.Clamp(w / 71f, 12, 21), statusTop, h * 0.058);
        SetLabel(_network, Math.Clamp(w / 90f, 11, 17), networkTop, h * 0.052);

        void SetLabel(Label label, float fontSize, double top, double height)
        {
            if (Math.Abs(label.Font.Size - fontSize) > 1)
            {
                var old = label.Font;
                label.Font = new Font("Segoe UI", fontSize,
                    label == _title || label == _number ? FontStyle.Bold : FontStyle.Regular);
                old.Dispose();
            }
            label.SetBounds(10, (int)top, Math.Max(0, ClientSize.Width - 20),
                Math.Max(24, (int)height));
        }
    }

    protected override void OnPaintBackground(PaintEventArgs e)
    {
        var rect = ClientRectangle;
        if (rect.Width <= 0 || rect.Height <= 0) return;
        using (var shade = new LinearGradientBrush(rect, Deep, Night,
                   LinearGradientMode.ForwardDiagonal))
            e.Graphics.FillRectangle(shade, rect);
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        var side = Math.Max(rect.Width, rect.Height);
        using var ring1 = new Pen(Color.FromArgb(14, Turquoise), 2);
        using var ring2 = new Pen(Color.FromArgb(12, 183, 226, 255), 1);
        e.Graphics.DrawEllipse(ring1, rect.Width / 2f - side * 0.33f,
            rect.Height / 2f - side * 0.33f, side * 0.66f, side * 0.66f);
        e.Graphics.DrawEllipse(ring2, rect.Width / 2f - side * 0.4f,
            rect.Height / 2f - side * 0.4f, side * 0.8f, side * 0.8f);
    }

    private void CheckLocalEnvironment()
    {
        try
        {
            _wifiAvailable = NetworkInterface.GetAllNetworkInterfaces().Any(n =>
                n.NetworkInterfaceType == NetworkInterfaceType.Wireless80211 &&
                n.OperationalStatus == OperationalStatus.Up);
        }
        catch { _wifiAvailable = false; }
        _connectExecutableAvailable = File.Exists(Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.Windows),
            "System32", "Connect.exe"));
        UpdateReceiverStatus();
    }

    private void CheckWindowsReceiverSession()
    {
        if (_closing || IsDisposed || _installingWindowsFeature) return;
        if (NativeMiracastWindow.TryFind(out var handle, out var title))
        {
            _connectProcessRunning = true;
            _receiverWindow = title;
            _missedWindows = 0;
            _launchRetries = 0;
            if (!_nativePresented && NativeMiracastWindow.ShowOnTop(handle))
            {
                _nativePresented = true;
                // Never leave our full-screen splash in front of the Miracast video.
                WindowState = FormWindowState.Minimized;
            }
        }
        else
        {
            _connectProcessRunning = false;
            _receiverWindow = "ไม่พบหน้าต่าง Wireless Display ที่เปิดอยู่";
            // Ignore one missed poll during Windows compositor transitions.
            if (_nativePresented && ++_missedWindows >= 2)
            {
                _nativePresented = false;
                WindowState = FormWindowState.Maximized;
                Activate();
            }
            if (_launchRetries < 3 &&
                DateTime.UtcNow - _lastLaunchUtc > TimeSpan.FromSeconds(12))
                OpenReceiver();
            else if (_launchRetries >= 3 && !_autoRepairAttempted)
                _ = PrepareWindowsFeatureAsync();
        }
        UpdateReceiverStatus();
    }

    private void UpdateReceiverStatus()
    {
        if (_connectProcessRunning)
            _receiverStatus = _wifiAvailable
                ? "พร้อมรับภาพ · เลือก " + Environment.MachineName + " จาก Android"
                : "เปิดตัวรับแล้ว แต่ยังไม่พบ Wi-Fi ที่พร้อมใช้งาน";
        else if (!_wifiAvailable)
            _receiverStatus = "ไม่พบ Wi-Fi ที่เปิดใช้งาน · กด F1 เพื่อตรวจสอบ";
        else if (_launchRetries >= 3)
            _receiverStatus = "เปิดตัวรับ Windows ไม่สำเร็จ · คลิกเพื่อจัดเตรียมระบบ";
        else if (_launchRequested)
            _receiverStatus = "กำลังเปิดตัวรับ Windows Wireless Display…";
        else
            _receiverStatus = "กำลังเตรียมตัวรับ Miracast…";
        RenderStatus();
    }

    private void RenderStatus()
    {
        var updating = _updateNotice is not null && DateTime.UtcNow < _updateNoticeUntil;
        var message = _installingWindowsFeature
            ? "กำลังจัดเตรียมระบบ · " + _repairMessage
            : !string.IsNullOrEmpty(_repairFailure) ? _repairFailure
            : updating ? _updateNotice! : _receiverStatus;
        if (_status.Text != message) _status.Text = message;
        var foreground = _connectProcessRunning || updating || _installingWindowsFeature;
        var color = foreground ? Frost : Warning;
        if (_status.ForeColor != color) _status.ForeColor = color;
    }

    private void OpenReceiver()
    {
        if (_closing || IsDisposed || _installingWindowsFeature) return;
        if (NativeMiracastWindow.TryFind(out var existing, out var existingTitle))
        {
            _connectProcessRunning = true;
            _receiverWindow = existingTitle;
            _launchRetries = 0;
            if (!_nativePresented && NativeMiracastWindow.ShowOnTop(existing))
            {
                _nativePresented = true;
                WindowState = FormWindowState.Minimized;
            }
            UpdateReceiverStatus();
            return;
        }
        if (DateTime.UtcNow - _lastLaunchUtc < TimeSpan.FromSeconds(8))
            return; // No duplicate launches, even when invoked via F5.
        _lastLaunchUtc = DateTime.UtcNow;
        _launchRetries++;
        try
        {
            var connect = Path.Combine(Environment.GetFolderPath(
                Environment.SpecialFolder.Windows), "System32", "Connect.exe");
            using var process = File.Exists(connect)
                ? Process.Start(new ProcessStartInfo(connect) { UseShellExecute = true })
                : Process.Start(new ProcessStartInfo("explorer.exe",
                    @"shell:AppsFolder\Microsoft.PPIProjection_cw5n1h2txyewy!App")
                { UseShellExecute = true });
            _launchRequested = process is not null;
            _lastLaunchError = _launchRequested ? "" : "Windows ไม่รับคำสั่งเปิดตัวรับ";
        }
        catch (Exception ex)
        {
            _launchRequested = false;
            _lastLaunchError = ex.Message;
        }
        UpdateReceiverStatus();
    }

    private Task PrepareWindowsFeatureAsync()
    {
        if (_closing || IsDisposed || _installingWindowsFeature) return Task.CompletedTask;
        _autoRepairAttempted = true;
        _repairFailure = "";
        _repairMessage = "ขั้นตอน 1/4 · รออนุญาตสิทธิ์ Windows";
        _installingWindowsFeature = true;
        _repairStartedUtc = DateTime.UtcNow;
        _network.Text = "Windows อาจขออนุญาต UAC เพื่อดาวน์โหลดส่วนประกอบที่ขาด";
        RenderStatus();
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(WindowsPreparation.ProgressFile)!);
            if (File.Exists(WindowsPreparation.ProgressFile))
                File.Delete(WindowsPreparation.ProgressFile);
            var start = new ProcessStartInfo(Application.ExecutablePath)
            {
                UseShellExecute = true,
                Verb = "runas"
            };
            start.ArgumentList.Add("--prepare-windows");
            start.ArgumentList.Add(WindowsPreparation.ProgressFile);
            _repairProcess = Process.Start(start)
                ?? throw new InvalidOperationException("Windows ไม่เริ่มขั้นตอนติดตั้ง");
        }
        catch (System.ComponentModel.Win32Exception ex) when (ex.NativeErrorCode == 1223)
        {
            FinishPreparation(false, "ต้องอนุญาต UAC เพื่อจัดเตรียม Windows");
        }
        catch (Exception ex)
        {
            FinishPreparation(false, "เตรียมระบบไม่สำเร็จ: " + ex.Message);
        }
        return Task.CompletedTask;
    }

    private void PollPreparation()
    {
        if (!_installingWindowsFeature || IsDisposed || _closing) return;
        var state = WindowsPreparation.ReadState();
        if (!string.IsNullOrWhiteSpace(state))
        {
            var split = state.IndexOf('|');
            if (split > 0)
            {
                var stage = state[..split];
                var detail = state[(split + 1)..].Trim();
                _repairMessage = stage is "RESTART" or "ERROR" or "DONE"
                    ? detail : "ขั้นตอน " + stage + " · " + detail;
                if (stage == "RESTART" || stage == "ERROR")
                {
                    FinishPreparation(false, _repairMessage);
                    return;
                }
            }
        }
        var passed = DateTime.UtcNow - _repairStartedUtc;
        _network.Text = "กำลังดำเนินการ " + ((int)passed.TotalMinutes).ToString("D2") +
            ":" + passed.Seconds.ToString("D2") +
            " · Windows Update อาจต้องใช้อินเทอร์เน็ต";
        RenderStatus();
        if (_repairProcess is null) return;
        try
        {
            if (!_repairProcess.HasExited) return;
            var successful = _repairProcess.ExitCode == 0 &&
                state?.StartsWith("DONE|", StringComparison.Ordinal) == true;
            FinishPreparation(successful, successful
                ? "ตรวจส่วนประกอบสำเร็จ กำลังเปิดตัวรับ"
                : _repairMessage.Length > 0 ? _repairMessage : "Windows เตรียมระบบไม่สำเร็จ");
        }
        catch (InvalidOperationException ex)
        {
            FinishPreparation(false, "ตรวจผลการติดตั้งไม่ได้: " + ex.Message);
        }
    }

    private void FinishPreparation(bool successful, string result)
    {
        _repairProcess?.Dispose();
        _repairProcess = null;
        _installingWindowsFeature = false;
        _network.Text = DefaultDeviceHint;
        if (successful)
        {
            _repairFailure = "";
            _launchRetries = 0;
            _lastLaunchUtc = DateTime.MinValue;
            _launchRequested = false;
            CheckLocalEnvironment();
            OpenReceiver();
        }
        else
        {
            _launchRetries = 3;
            _repairFailure = result + " · คลิกสถานะเพื่อลองใหม่";
            _status.Text = _repairFailure;
            _status.ForeColor = Warning;
        }
    }

    private static void OpenSettings(string url)
    {
        try { Process.Start(new ProcessStartInfo(url) { UseShellExecute = true })?.Dispose(); }
        catch (Exception ex)
        {
            MessageBox.Show("เปิดการตั้งค่า Windows ไม่ได้: " + ex.Message,
                "X-Stage Mirror Android PC", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private void ShowDiagnostics()
    {
        CheckLocalEnvironment();
        CheckWindowsReceiverSession();
        var text = new StringBuilder()
            .AppendLine("X-Stage Mirror Android PC  " + VersionText)
            .AppendLine("หมายเลข X-Stage: No." + ReceiverIdentity.Number.ToString("D4"))
            .AppendLine("ชื่อที่ Android ต้องค้นหา: " + Environment.MachineName)
            .AppendLine("Windows: " + Environment.OSVersion.VersionString)
            .AppendLine("Wi-Fi: " + (_wifiAvailable ? "เปิดใช้งาน" : "ยังไม่พบอะแดปเตอร์ที่เปิดใช้งาน"))
            .AppendLine("Connect.exe: " + (_connectExecutableAvailable ? "พบไฟล์" : "ยังไม่พบ"))
            .AppendLine("โปรเซส Connect: " + (_connectProcessRunning ? "กำลังทำงาน" : "ยังไม่พบ"))
            .AppendLine("หน้าต่างตัวรับ: " + _receiverWindow)
            .AppendLine("คำสั่งเปิดตัวรับ: " + (string.IsNullOrEmpty(_lastLaunchError) ? "ไม่มีข้อผิดพลาดที่บันทึก" : _lastLaunchError))
            .AppendLine("เตรียมระบบ: " + (_installingWindowsFeature ? _repairMessage : _repairFailure))
            .AppendLine("แสดงหน้าต่างรับภาพ: " + (_nativePresented ? "เปิดอยู่" : "ยังไม่ยืนยัน"))
            .AppendLine()
            .AppendLine("บน Android เปิด Smart View / Screen Cast และเลือกชื่อ Windows PC ข้างต้น")
            .AppendLine("No.XXXX เป็นเลขประจำแอป X-Stage ไม่ใช่ชื่อ Miracast ที่โทรศัพท์ค้นหา")
            .AppendLine("Windows Wireless Display เป็นผู้แสดงภาพและจัดการสิทธิ์เชื่อมต่อ")
            .AppendLine("เมื่อฝั่งส่งยกเลิก Windows จะล้างภาพของเซสชันเอง")
            .AppendLine("หากหน้าต่างตัวรับปิด X-Stage จะเรียกเปิดใหม่โดยอัตโนมัติ")
            .AppendLine("การพบโปรเซส Connect ไม่ได้ยืนยันว่ามีอุปกรณ์ส่งเชื่อมต่อแล้ว")
            .AppendLine("Google Cast อย่างเดียวไม่สามารถเชื่อมกับ Miracast ได้โดยตรง")
            .AppendLine()
            .AppendLine("F5 เปิดตัวรับอีกครั้ง · F6 ตั้งค่าการฉายภาพ · F7 Optional Features")
            .AppendLine("อุปกรณ์ต้องรองรับ Wi-Fi Direct/Miracast และมีไดรเวอร์ที่เหมาะสม")
            .AppendLine("ตรวจสอบเพิ่มได้ด้วยคำสั่ง netsh wlan show drivers");
        MessageBox.Show(this, text.ToString(), "สถานะและวิธีเชื่อมต่อ",
            MessageBoxButtons.OK, MessageBoxIcon.Information);
    }

    private void ConfirmClose()
    {
        if (MessageBox.Show(this, "ปิด X-Stage Mirror Android PC หรือไม่?",
                "ปิดแอป", MessageBoxButtons.YesNo,
                MessageBoxIcon.Question) == DialogResult.Yes)
            Close();
    }

    private void OnReceiverKeyDown(object? sender, KeyEventArgs e)
    {
        switch (e.KeyCode)
        {
            case Keys.F1: ShowDiagnostics(); break;
            case Keys.F5: OpenReceiver(); break;
            case Keys.F6: OpenSettings("ms-settings:project"); break;
            case Keys.F7: OpenSettings("ms-settings:optionalfeatures"); break;
            case Keys.Escape: ConfirmClose(); break;
            default: return;
        }
        e.Handled = true;
        e.SuppressKeyPress = true;
    }
}
