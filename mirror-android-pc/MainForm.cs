using System.Diagnostics;
using System.Drawing;
using System.Net.NetworkInformation;
using System.Text;
using System.Text.Json;
using System.Windows.Forms;

namespace XStageMirrorAndroidPC;

public sealed class MainForm : Form
{
    private const string AppVersion = "v1.0.0 · Build 1001";
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

    public MainForm()
    {
        Text = "X-Stage Mirror Android PC • " + ReceiverIdentity.DisplayName;
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(720, 600);
        Size = new Size(960, 780);
        AutoScaleMode = AutoScaleMode.Dpi;
        BackColor = Base;
        ForeColor = Color.White;
        Font = new Font("Segoe UI", 10);
        MakeInterface();
        Shown += async (_, _) =>
        {
            CheckLocalEnvironment();
            CheckWindowsReceiverSession();
            _receiverPoll.Start();
            await CheckUpdatesAsync();
        };
        _receiverPoll.Tick += (_, _) => CheckWindowsReceiverSession();
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
        var view = new Panel { Dock = DockStyle.Fill, BackColor = Base, AutoScroll = true };
        Controls.Add(view);
        var top = PanelCard(42, 52, 32);
        top.BackColor = Base;
        top.Padding = new Padding(Px(4), 0, Px(4), 0);
        top.Controls.Add(Label("X-STAGE  /  MIRROR ANDROID PC", 14, true, Muted), 0, 0);
        top.Controls.Add(Label(ReceiverIdentity.DisplayName, 26, true, Accent), 0, 1);
        top.Controls.Add(Label("สำหรับ Android / Miracast  •  Windows 10/11 x64  •  " + AppVersion, 10, false, Muted), 0, 2);

        var receiver = PanelCard(45, 54, 42, 60, 52, 48, 52);
        receiver.Controls.Add(Label("ตัวรับภาพ Android ผ่าน Windows", 16, true), 0, 0);
        _computer.TextAlign = ContentAlignment.MiddleLeft;
        _computer.Dock = DockStyle.Fill;
        _computer.ForeColor = Accent;
        _computer.Font = new Font("Segoe UI", 12, FontStyle.Bold);
        receiver.Controls.Add(_computer, 0, 1);
        _status.Dock = DockStyle.Fill;
        _status.ForeColor = Muted;
        _status.Font = new Font("Segoe UI", 11, FontStyle.Bold);
        receiver.Controls.Add(_status, 0, 2);
        _details.Dock = DockStyle.Fill;
        _details.Font = new Font("Segoe UI", 10);
        _details.ForeColor = Muted;
        receiver.Controls.Add(_details, 0, 3);
        var actions = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 1 };
        actions.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 55));
        actions.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 45));
        _openReceiver.Text = "▶  เปิด Windows Wireless Display";
        _openReceiver.FlatStyle = FlatStyle.Flat;
        _openReceiver.FlatAppearance.BorderSize = 0;
        _openReceiver.Dock = DockStyle.Fill;
        _openReceiver.Margin = new Padding(4);
        _openReceiver.BackColor = Accent;
        _openReceiver.ForeColor = Base;
        _openReceiver.Font = new Font("Segoe UI", 11, FontStyle.Bold);
        _openReceiver.Click += (_, _) => OpenReceiver();
        var projection = Button("⚙  ตั้งค่ารับภาพ Windows", false);
        projection.Click += (_, _) => OpenSettings("ms-settings:project");
        actions.Controls.Add(_openReceiver, 0, 0);
        actions.Controls.Add(projection, 1, 0);
        receiver.Controls.Add(actions, 0, 4);
        var other = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2 };
        other.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        other.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        var optional = Button("ติดตั้ง/ตรวจ Wireless Display", false);
        optional.Click += (_, _) => OpenSettings("ms-settings:optionalfeatures");
        var diagnosis = Button("ตรวจสอบความพร้อม", false);
        diagnosis.Click += (_, _) => ShowDiagnostics();
        other.Controls.Add(optional, 0, 0);
        other.Controls.Add(diagnosis, 1, 0);
        receiver.Controls.Add(other, 0, 5);
        receiver.Controls.Add(Label("Android ต้องค้นหาชื่อ Windows ด้านบน · เลข No. ใช้ระบุ X-Stage บน PC (ไม่ใช่ชื่อ Miracast)", 10, false, Muted), 0, 6);

        var sessions = PanelCard(46, 53, 78, 46);
        sessions.Controls.Add(Label("อุปกรณ์เชื่อมต่อ / Connected devices", 16, true), 0, 0);
        _nativeSession.Dock = DockStyle.Fill;
        _nativeSession.ForeColor = Accent;
        _nativeSession.Font = new Font("Segoe UI", 11, FontStyle.Bold);
        sessions.Controls.Add(_nativeSession, 0, 1);
        _connectedDevices.Dock = DockStyle.Fill;
        _connectedDevices.ForeColor = Muted;
        _connectedDevices.Font = new Font("Segoe UI", 11);
        sessions.Controls.Add(_connectedDevices, 0, 2);
        sessions.Controls.Add(Label("Windows ควบคุมรายชื่อผู้ส่งจริงในหน้าต่าง Wireless Display · X-Stage ไม่เดาชื่ออุปกรณ์", 10, false, Muted), 0, 3);

        var steps = PanelCard(37, 53, 53, 54);
        steps.Controls.Add(Label("วิธีเชื่อมต่อที่ถูกต้อง", 15, true), 0, 0);
        steps.Controls.Add(Label("1. เปิด Windows Wireless Display และอนุญาตการฉายภาพบนเครื่องนี้", 11), 0, 1);
        steps.Controls.Add(Label("2. เปิด Smart View / Screen Cast / Miracast บน Android ที่รองรับ", 11), 0, 2);
        steps.Controls.Add(Label("3. เลือกชื่อ PC แล้วอนุญาตบน Windows เมื่อระบบถาม", 11), 0, 3);

        var bottom = PanelCard(34, 48, 48);
        bottom.Controls.Add(Label("รุ่นและอัปเดต", 14, true), 0, 0);
        _update.Dock = DockStyle.Fill; _update.ForeColor = Muted;
        _update.Text = "ตรวจสอบรุ่นล่าสุดเมื่อมีอินเทอร์เน็ต";
        bottom.Controls.Add(_update, 0, 1);
        var checkUpdate = Button("↻  ตรวจสอบรุ่นใหม่", false);
        checkUpdate.Click += async (_, _) => await CheckUpdatesAsync(showMessage: true);
        bottom.Controls.Add(checkUpdate, 0, 2);

        var cards = new (Control view, int height)[] {
            (top, 140), (receiver, 400), (sessions, 265), (steps, 237), (bottom, 174)
        };
        foreach (var (card, _) in cards) view.Controls.Add(card);
        void ResizeCards()
        {
            var vw = view.ClientSize.Width;
            var width = Math.Min(Px(1020), Math.Max(Px(610), vw - Px(40)));
            var left = vw >= width ? (vw - width) / 2 : Px(20);
            var y = Px(16);
            view.SuspendLayout();
            try
            {
                foreach (var (card, height) in cards)
                {
                    card.SetBounds(left, y, width, Px(height));
                    y += Px(height) + Px(16);
                }
                view.AutoScrollMinSize = new Size(width + Px(40), y + Px(12));
            }
            finally { view.ResumeLayout(); }
        }
        view.Resize += (_, _) => ResizeCards();
        ResizeCards();
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
            _status.Text = "ส่งคำสั่งเปิดตัวรับแล้ว • ตรวจในหน้าต่าง Wireless Display ของ Windows";
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

    private async Task CheckUpdatesAsync(bool showMessage = false)
    {
        try
        {
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(8) };
            using var response = await client.GetAsync(PreviewFeed);
            response.EnsureSuccessStatusCode();
            using var manifest = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
            var obj = manifest.RootElement;
            var version = obj.TryGetProperty("version", out var v) ? v.GetString() : null;
            int build = obj.TryGetProperty("build", out var b) && b.TryGetInt32(out var x) ? x : 0;
            bool available = obj.TryGetProperty("available", out var av) && av.ValueKind == JsonValueKind.True;
            var newer = available && (Version.TryParse(version, out var remote)
                && (remote > new Version(1, 0, 0) || (remote == new Version(1, 0, 0) && build > 1001)));
            _update.Text = newer ? "มีรุ่นใหม่: v" + version + " Build " + build :
                "กำลังใช้ " + AppVersion + " · ไม่พบรุ่นใหม่";
            if (!newer && !showMessage) return;
            if (MessageBox.Show(this, newer ? "พบรุ่นใหม่บน X-Stage Apps\nเปิดเว็บไซต์ดาวน์โหลดหรือไม่?" : _update.Text,
                "ตรวจสอบอัปเดต", newer ? MessageBoxButtons.YesNo : MessageBoxButtons.OK,
                MessageBoxIcon.Information) == DialogResult.Yes && newer)
                Process.Start(new ProcessStartInfo(
                    "https://webbase-x.github.io/xstage/?app=mirror-android-pc") { UseShellExecute = true });
        }
        catch
        {
            if (!_closing && !IsDisposed) _update.Text = "ตรวจสอบออนไลน์ไม่ได้ · รับภาพผ่าน Windows แบบออฟไลน์ได้";
        }
    }
}
