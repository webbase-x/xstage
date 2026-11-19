using System.Diagnostics;
using System.Drawing;
using System.Net.NetworkInformation;
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Windows.Forms;

namespace XStageMirrorAndroidPC;

public sealed class MainForm : Form
{
    private static readonly string AppVersion = GetVersionText();
    private static string GetVersionText()
    {
        var v = typeof(MainForm).Assembly.GetCustomAttribute<AssemblyFileVersionAttribute>()?.Version;
        var p = v?.Split('.');
        return p is { Length: 4 } ? $"v{p[0]}.{p[1]}.{p[2]} · Build {p[3]}" : "ไม่ทราบเวอร์ชัน EXE";
    }
    private const string PreviewFeed =
        "https://webbase-x.github.io/xstage/downloads/mirror-android-pc-preview-latest.json";
    private static readonly Color Base = Color.FromArgb(12, 19, 36);
    private static readonly Color CardColor = Color.FromArgb(24, 35, 56);
    private static readonly Color Accent = Color.FromArgb(89, 215, 220);
    private static readonly Color Muted = Color.FromArgb(174, 192, 213);
    private readonly Label _status = new();
    private readonly Label _details = new();
    private readonly Label _update = new();
    private readonly Label _computer = new();
    private readonly Button _openReceiver = new();
    private readonly Label _nativeSession = new();
    private readonly Label _connectedDevices = new();
    private readonly System.Windows.Forms.Timer _receiverPoll = new() { Interval = 5000 };
    private bool _closing;
    private readonly MirrorAutoUpdateManager _autoUpdates;

    public MainForm()
    {
        Text = "X-Stage Mirror Android PC • " + ReceiverIdentity.DisplayName;
        StartPosition = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.None;
        WindowState = FormWindowState.Maximized;
        AutoScaleMode = AutoScaleMode.Dpi;
        BackColor = Base;
        ForeColor = Color.White;
        Font = new Font("Segoe UI", 10);
        MakeInterface();
        _autoUpdates = new MirrorAutoUpdateManager(
            message =>
            {
                if (_closing || IsDisposed || !IsHandleCreated) return;
                try { BeginInvoke(new Action(() => { if (!_closing && !IsDisposed) _status.Text = message; })); }
                catch (InvalidOperationException) { }
            },
            () =>
            {
                if (_closing || IsDisposed || !IsHandleCreated) return;
                try { BeginInvoke(new Action(() => { if (!_closing && !IsDisposed) Close(); })); }
                catch (InvalidOperationException) { }
            });
        Shown += (_, _) =>
        {
            CheckLocalEnvironment();
            OpenReceiver();
            CheckWindowsReceiverSession();
            _receiverPoll.Start();
            _ = _autoUpdates.CheckAsync();
        };
        _receiverPoll.Tick += (_, _) =>
        {
            CheckWindowsReceiverSession();
            _ = _autoUpdates.CheckAsync();
        };
        FormClosing += (_, _) => { _closing = true; _receiverPoll.Stop(); };
    }

    private int Px(int n) => (int)Math.Round(n * DeviceDpi / 96.0);

    private static Label Label(string content, float size, bool bold = false, Color? color = null)
        => new()
        {
            Dock = DockStyle.Fill, AutoSize = false, Text = content,
            TextAlign = ContentAlignment.MiddleLeft, ForeColor = color ?? Color.White,
            Font = new Font("Segoe UI", size, bold ? FontStyle.Bold : FontStyle.Regular)
        };

    private static Button Button(string text, bool primary)
    {
        var b = new Button
        {
            Text = text, Dock = DockStyle.Fill, Margin = new Padding(4),
            BackColor = primary ? Accent : Color.FromArgb(52, 72, 100),
            ForeColor = primary ? Base : Color.White,
            FlatStyle = FlatStyle.Flat, Cursor = Cursors.Hand,
            Font = new Font("Segoe UI", 11, FontStyle.Bold)
        };
        b.FlatAppearance.BorderSize = 0;
        return b;
    }

    private TableLayoutPanel PanelCard(params int[] heights)
    {
        var card = new TableLayoutPanel
        {
            ColumnCount = 1, RowCount = heights.Length, GrowStyle = TableLayoutPanelGrowStyle.FixedSize,
            BackColor = CardColor, Padding = new Padding(Px(22), Px(16), Px(22), Px(16)),
            Margin = Padding.Empty, Dock = DockStyle.None, AutoSize = false
        };
        card.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        foreach (var row in heights) card.RowStyles.Add(new RowStyle(SizeType.Absolute, Px(row)));
        return card;
    }

    private void MakeInterface()
    {
        // The same calm, full-screen welcome hierarchy used by Mirror iOS PC.
        // Windows owns the native Miracast renderer; we do not fake a video surface.
        var view = new Panel { Dock = DockStyle.Fill, BackColor = Color.FromArgb(12, 26, 44) };
        Controls.Add(view);
        var logo = new PictureBox
        {
            SizeMode = PictureBoxSizeMode.Zoom,
            BackColor = Color.Transparent,
            AccessibleName = "X-Stage Mirror Android PC"
        };
        using (var stream = typeof(MainForm).Assembly.GetManifestResourceStream("XStageMirrorAndroidPC.logo.png"))
        {
            if (stream is not null)
            {
                using var original = Image.FromStream(stream);
                logo.Image = new Bitmap(original);
            }
        }
        var title = Label("X-Stage Mirror PC", 51, true);
        var number = Label("No." + ReceiverIdentity.Number.ToString("D4"), 90, true, Accent);
        var version = Label("MIRROR ANDROID PC     " + AppVersion, 15, false, Muted);
        var receiverName = Label("ชื่อจอ Windows: " + Environment.MachineName, 22, true);
        var help = Label("Smart View / Screen Cast → " + Environment.MachineName +
            "   ·   No. คือรหัส X-Stage ไม่ใช่ชื่ออุปกรณ์ที่ Android ค้นหา", 11, false, Muted);
        _status.TextAlign = ContentAlignment.MiddleCenter;
        _status.Font = new Font("Segoe UI", 18);
        _status.ForeColor = Color.White;
        _details.TextAlign = ContentAlignment.MiddleCenter;
        _details.Font = new Font("Segoe UI", 12);
        _details.ForeColor = Muted;
        var minimize = Button("—", false);
        minimize.AccessibleName = "ย่อหน้าต่าง";
        minimize.Click += (_, _) => WindowState = FormWindowState.Minimized;
        var close = Button("×", false);
        close.AccessibleName = "ปิดแอป";
        close.BackColor = Color.FromArgb(57, 39, 55);
        close.Click += (_, _) =>
        {
            if (MessageBox.Show(this, "ปิด X-Stage Mirror Android PC หรือไม่?",
                "ปิดแอป", MessageBoxButtons.YesNo,
                MessageBoxIcon.Question) == DialogResult.Yes)
                Close();
        };
        var settings = Button("ตั้งค่า", false);
        settings.Click += (_, _) => OpenSettings("ms-settings:project");
        _openReceiver.Text = "เปิดตัวรับ";
        _openReceiver.BackColor = CardColor;
        _openReceiver.ForeColor = Color.White;
        _openReceiver.FlatStyle = FlatStyle.Flat;
        _openReceiver.FlatAppearance.BorderSize = 0;
        _openReceiver.Font = new Font("Segoe UI", 12, FontStyle.Bold);
        _openReceiver.Click += (_, _) => OpenReceiver();
        foreach (var control in new Control[]
        {
            logo, title, number, version, receiverName, _status, _details,
            help, settings, _openReceiver, minimize, close
        })
        {
            view.Controls.Add(control);
        }
        void Place()
        {
            if (view.IsDisposed) return;
            var w = Math.Max(640, view.ClientSize.Width);
            var h = Math.Max(480, view.ClientSize.Height);
            var logoSize = Math.Clamp((int)Math.Min(w * 0.18, h * 0.17), 70, 160);
            var logoTop = Math.Max(75, (int)(h * 0.11));
            logo.SetBounds(Math.Max(0, (view.ClientSize.Width - logoSize) / 2), logoTop, logoSize, logoSize);
            var titleTop = Math.Max(logoTop + logoSize + 7, (int)(h * 0.34));
            var numberTop = Math.Max(titleTop + (int)(h * 0.10) + 5, (int)(h * 0.48));
            void Center(Control control, int top, int height)
                => control.SetBounds(12, top, Math.Max(0, view.ClientSize.Width - 24), height);
            Center(title, titleTop, (int)(h * 0.10));
            Center(number, numberTop, (int)(h * 0.17));
            Center(version, numberTop + (int)(h * 0.17) + 5, 34);
            Center(receiverName, numberTop + (int)(h * 0.17) + 45, 54);
            Center(_status, numberTop + (int)(h * 0.17) + 105, 48);
            Center(_details, numberTop + (int)(h * 0.17) + 151, 65);
            Center(help, Math.Max(numberTop + (int)(h * 0.17) + 218, h - 64), 38);
            settings.SetBounds(20, 22, 90, 44);
            _openReceiver.SetBounds(118, 22, 130, 44);
            minimize.SetBounds(Math.Max(0, view.ClientSize.Width - 136), 22, 52, 44);
            close.SetBounds(Math.Max(0, view.ClientSize.Width - 76), 22, 52, 44);
            title.Font = new Font("Segoe UI", Math.Clamp(w / 29f, 27, 60), FontStyle.Bold);
            number.Font = new Font("Segoe UI", Math.Clamp(Math.Min(w / 13f, h / 5.5f), 44, 112), FontStyle.Bold);
            receiverName.Font = new Font("Segoe UI", Math.Clamp(w / 65f, 14, 26), FontStyle.Bold);
        }
        view.Resize += (_, _) => Place();
        Place();
    }

    private void CheckLocalEnvironment()
    {
        _computer.Text = "ชื่อจริงที่ Android ต้องค้นหา:  " + Environment.MachineName;
        bool wifi = NetworkInterface.GetAllNetworkInterfaces().Any(n =>
            n.NetworkInterfaceType == NetworkInterfaceType.Wireless80211 &&
            n.OperationalStatus == OperationalStatus.Up);
        bool native = File.Exists(Path.Combine(Environment.GetFolderPath(
            Environment.SpecialFolder.Windows), "System32", "Connect.exe"));
        _status.Text = native ? "พบตัวรับ Windows Connect (ยังไม่ยืนยัน Miracast)" :
            "ต้องตรวจสอบ/ติดตั้ง Windows Wireless Display";
        _status.ForeColor = native ? Accent : Color.Orange;
        _details.Text = (wifi ? "พบอะแดปเตอร์ Wi-Fi เปิดใช้งาน" :
            "ยังไม่พบอะแดปเตอร์ Wi-Fi ที่เปิดใช้งาน") +
            "\nตัวรับนี้ใช้ความสามารถของ Windows และไดรเวอร์ ไม่ใช่ AirPlay หรือ Google Cast\n" +
            "สถานะในแอปไม่ใช่การยืนยันว่ามีอุปกรณ์ส่งเชื่อมต่อแล้ว";
    }

    private static void OpenSettings(string url)
    {
        try { Process.Start(new ProcessStartInfo(url) { UseShellExecute = true }); }
        catch (Exception ex) { MessageBox.Show("เปิดการตั้งค่า Windows ไม่ได้: " + ex.Message); }
    }

    private void OpenReceiver()
    {
        try
        {
            var connect = Path.Combine(Environment.GetFolderPath(
                Environment.SpecialFolder.Windows), "System32", "Connect.exe");
            if (File.Exists(connect))
                Process.Start(new ProcessStartInfo(connect) { UseShellExecute = true });
            else
                Process.Start(new ProcessStartInfo("explorer.exe",
                    @"shell:AppsFolder\Microsoft.PPIProjection_cw5n1h2txyewy!App")
                    { UseShellExecute = true });
            // Launching Windows Connect is not proof of a successful Miracast session.
            _status.Text = "ส่งคำสั่งเปิด Wireless Display แล้ว · ตรวจหน้าต่าง Windows";
        }
        catch (Exception ex)
        {
            _status.Text = "เปิดตัวรับไม่ได้ • โปรดตรวจ Windows Wireless Display";
            MessageBox.Show(this, "Windows ไม่สามารถเปิด Wireless Display ได้:\n" + ex.Message,
                "X-Stage Mirror Android PC", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            OpenSettings("ms-settings:optionalfeatures");
        }
    }

    private void CheckWindowsReceiverSession()
    {
        if (_closing || IsDisposed) return;
        try
        {
            var found = false;
            string? windowTitle = null;
            foreach (var process in Process.GetProcessesByName("Connect"))
            {
                using (process)
                {
                    if (process.HasExited) continue;
                    found = true;
                    if (!string.IsNullOrWhiteSpace(process.MainWindowTitle))
                        windowTitle = process.MainWindowTitle;
                }
            }
            _nativeSession.Text = found
                ? "พบโปรเซส Windows Connect กำลังเปิดอยู่"
                : "ยังตรวจไม่พบโปรเซส Connect (อาจเป็นแอป Wireless Display รุ่นใหม่)";
            _connectedDevices.Text = windowTitle is not null
                ? "หน้าต่าง Windows: " + windowTitle + "\nรายชื่ออุปกรณ์ที่เชื่อมต่อให้ดูในหน้าต่าง Windows โดยตรง"
                : "รายชื่อ/จำนวนผู้ส่ง: Windows Wireless Display เป็นผู้จัดการเซสชัน\nกด เปิด Windows Wireless Display เพื่อดูผู้ส่งที่เชื่อมต่อจริง";
        }
        catch (Exception ex)
        {
            _nativeSession.Text = "ตรวจสอบสถานะตัวรับ Windows ไม่สำเร็จ";
            _connectedDevices.Text = ex.Message;
        }
    }

    private void ShowDiagnostics()
    {
        CheckLocalEnvironment();
        var text = new StringBuilder()
            .AppendLine("X-Stage Mirror Android PC " + AppVersion)
            .AppendLine("PC: " + Environment.MachineName)
            .AppendLine("Windows: " + Environment.OSVersion.VersionString)
            .AppendLine()
            .AppendLine("Miracast ต้องมีตัวรับ Windows Wireless Display + Wi-Fi Direct/driver ที่รองรับ")
            .AppendLine("Android ต้องมี Miracast; Google Cast ไม่เข้ากันได้โดยตรง")
            .AppendLine("การมี Wi-Fi ไม่ยืนยันว่ารองรับ Miracast")
            .AppendLine("เปิด Settings > System > Projecting to this PC เพื่อกำหนดการอนุญาต")
            .AppendLine("ตรวจเพิ่มเติมได้ด้วยคำสั่ง netsh wlan show drivers")
            .AppendLine()
            .AppendLine("ถ้า Windows ไม่มี Wireless Display ให้ติดตั้ง Optional Feature ของ Windows")
            .AppendLine("การเพิ่ม Optional Feature อาจต้องเชื่อมต่อ Windows Update และไม่สามารถบรรจุไดรเวอร์ทดแทนลง Setup EXE");
        MessageBox.Show(this, text.ToString(), "ตรวจสอบอุปกรณ์", MessageBoxButtons.OK, MessageBoxIcon.Information);
    }

}
