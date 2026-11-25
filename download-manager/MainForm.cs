using System.Diagnostics;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

namespace XStageDownloadManager;

public sealed partial class MainForm : Form
{
    private readonly DownloadEngine _engine = new();
    private readonly TextBox _url = new();
    private readonly TextBox _folder = new();
    private readonly ComboBox _parts = new();
    private readonly ComboBox _videoQuality = new();
    private readonly ComboBox _outputFormat = new();
    private TableLayoutPanel? _inputLayout;
    private Control[] _videoOptionControls = Array.Empty<Control>();
    private readonly DataGridView _grid = new();
    private readonly ContextMenuStrip _completedMenu = new();
    private readonly Label _summary = new();
    private readonly Label _details = new();
    private readonly Label _updateStatus = new();
    private bool _checkingUpdates;
    private bool _updateHandoffInProgress;
    private readonly Font _finishedFileFont = new("Segoe UI", 10, FontStyle.Bold | FontStyle.Underline);
    private readonly Font _normalFileFont = new("Segoe UI", 10, FontStyle.Regular);
    private readonly CancellationTokenSource _browserStop = new();
    private readonly System.Windows.Forms.Timer _timer = new() { Interval = 800 };
    private bool _networkAvailable = System.Net.NetworkInformation.NetworkInterface.GetIsNetworkAvailable();
    private volatile bool _sleeping;
    private long _lastSpeedMeasurementTick;
    private bool _uiSmokeMode;
    private readonly System.Windows.Forms.Timer _syncAnimation = new() { Interval = 90 };
    private Image? _syncIdleIcon;
    private readonly List<Image> _syncFrames = new();
    private int _syncFrame;

    public MainForm(string[] args)
    {
        _uiSmokeMode = args.Contains("--ui-smoke", StringComparer.Ordinal);
        Text = "X-Stage Download Manager · v" + UpdateChecker.CurrentVersion + " Build " + UpdateChecker.CurrentBuild;
        MinimumSize = new Size(880, 590);
        Size = new Size(1250, 780);
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(23, 26, 34);
        ForeColor = Color.FromArgb(23, 34, 55);
        Font = new Font("Segoe UI", 10);
        // A Windows host process or installation without a valid embedded
        // icon can make GDI+ throw "Parameter is not valid" at startup.
        // Keep the brand UI usable with a known-good system fallback.
        try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath) ?? SystemIcons.Application; }
        catch (ArgumentException) { Icon = SystemIcons.Application; }
        catch (System.ComponentModel.Win32Exception) { Icon = SystemIcons.Application; }
        CreateXStageWorkspace();
        _syncAnimation.Tick += (_, _) => AnimateSmartSync();
        FormClosed += (_, _) => _completedMenu.Dispose();
        _parts.Items.AddRange(new object[] { "1", "2", "4", "8", "16", "32" });
        _parts.SelectedItem = _engine.DefaultParts.ToString();
        _parts.SelectedIndexChanged += (_, _) =>
        {
            if (_parts.SelectedItem is string value && int.TryParse(value, out var count))
            {
                try { _engine.SetDefaultParts(count); }
                catch (IOException ex) { MessageBox.Show(this, ex.Message, "บันทึกการตั้งค่าไม่ได้"); }
                catch (UnauthorizedAccessException ex) { MessageBox.Show(this, ex.Message, "บันทึกการตั้งค่าไม่ได้"); }
            }
        };
        _videoQuality.Items.AddRange(new object[]
        {
            "ดีที่สุด (ภาพและเสียง)", "1080p", "720p", "480p"
        });
        _videoQuality.SelectedIndex = 0;
        _outputFormat.Items.AddRange(new object[] { "MP4 (แนะนำ)", "MKV", "WEBM", "MP3 (เฉพาะเสียง)" });
        _outputFormat.SelectedIndex = 0;
        _outputFormat.SelectedIndexChanged += (_, _) => _videoQuality.Enabled = _outputFormat.SelectedIndex != 3;
        _folder.Text = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads");
        _url.TextChanged += (_, _) => UpdateVideoOptionVisibility();
        _url.Text = args.FirstOrDefault(a => DownloadEngine.TryParseUrl(a, out _)) ?? "";
        UpdateVideoOptionVisibility();
        if (_url.Text.Length > 0) ShowInputPanel(true);
        _timer.Tick += (_, _) =>
        {
            CheckNetworkRecovery();
            RefreshRows();
        };
        if (!_uiSmokeMode)
        {
            Microsoft.Win32.SystemEvents.PowerModeChanged += OnPowerModeChanged;
            _timer.Start();
        }
        FormClosing += (_, e) =>
        {
            if (_updateHandoffInProgress && e.CloseReason == CloseReason.UserClosing)
            {
                e.Cancel = true;
                return;
            }
            // Keep the UI process alive until separately recorded livestreams
            // have closed MKV headers or safely cancelled clip generation.
            // Never pause normal downloads for a close attempt we reject.
            if (_smartSyncWindow?.IsBusy == true)
            {
                e.Cancel = true;
                _smartSyncWindow.RequestStop();
                ShowSmartSyncPanel(true);
                return;
            }
            var openLive = Application.OpenForms.OfType<LiveStreamCaptureForm>()
                .Where(window => window.IsBusy).ToArray();
            if (openLive.Length > 0)
            {
                e.Cancel = true;
                foreach (var window in openLive) window.StopOrCancel();
                MessageBox.Show(this,
                    "กำลังปิดไฟล์ไลฟ์ให้ปลอดภัย กรุณาปิดหน้าต่างหลักหลังบันทึกเสร็จ",
                    "X-Stage Live Capture", MessageBoxButtons.OK,
                    MessageBoxIcon.Information);
                return;
            }
            _smartSyncWindow?.CloseForShutdown();
            Microsoft.Win32.SystemEvents.PowerModeChanged -= OnPowerModeChanged;
            _browserStop.Cancel();
            _timer.Stop();
            _engine.PauseAllForShutdown();
            _engine.Save();
        };
        FormClosed += (_, _) =>
        {
            _syncAnimation.Stop();
            _syncAnimation.Dispose();
            RestoreSyncIcon();
            foreach (var frame in _syncFrames) frame.Dispose();
            _syncFrames.Clear();
            _finishedFileFont.Dispose();
            _normalFileFont.Dispose();
            foreach (var image in _rowIcons.Values) image.Dispose();
            _categoryIcons.Dispose();
            foreach (var image in _categoryIconSources) image.Dispose();
            _categoryIconSources.Clear();
        };
        Shown += async (_, _) =>
        {
            // CI smoke renders the actual WinForms controls, but must not
            // start browser IPC, recovery or update calls against an account.
            if (_uiSmokeMode) return;
            if (_engine.InterruptedJobCount > 0)
            {
                var count = _engine.InterruptedJobCount;
                var answer = MessageBox.Show(this,
                    $"พบงานดาวน์โหลดที่ถูกขัดจังหวะ {count} รายการ\n" +
                    "ต้องการดาวน์โหลดต่อจากข้อมูลที่บันทึกไว้หรือไม่?\n" +
                    "เลือก ไม่ เพื่อเก็บรายการไว้ในสถานะหยุดชั่วคราว",
                    "กู้คืนงานดาวน์โหลด", MessageBoxButtons.YesNo, MessageBoxIcon.Question);
                _engine.RecoverInterruptedJobs(answer == DialogResult.Yes);
                RefreshRows();
            }
            StartBrowserHandoff();
            if (args.Length >= 2 && args[0] == "--enqueue" &&
                DownloadEngine.TryParseUrl(args[1], out _))
            {
                try
                {
                    _engine.Add(args[1], _folder.Text, _engine.DefaultParts, SelectedQuality(), SelectedOutputFormat());
                    _url.Clear();
                    RefreshRows();
                }
                catch (Exception ex) { MessageBox.Show(this, ex.Message, "รับงานจากเบราว์เซอร์ไม่สำเร็จ"); }
            }
            await CheckForUpdatesAsync(false);
        };
        RefreshRows();
    }

    // Windows may retain an apparently connected network adapter through
    // sleep. Mark active work interrupted before suspend; resume on the
    // UI timer only after networking is reported available again.
    private void OnPowerModeChanged(object? sender, Microsoft.Win32.PowerModeChangedEventArgs e)
    {
        if (e.Mode == Microsoft.Win32.PowerModes.Suspend)
        {
            _sleeping = true;
            _engine.PauseForNetworkOutage();
        }
        else if (e.Mode == Microsoft.Win32.PowerModes.Resume)
        {
            _sleeping = false;
        }
    }

    private void CheckNetworkRecovery()
    {
        var available = System.Net.NetworkInformation.NetworkInterface.GetIsNetworkAvailable();
        if (_networkAvailable && !available)
            _engine.PauseForNetworkOutage();
        _networkAvailable = available;
        if (available && !_sleeping) _engine.TryResumeNetworkInterrupted();
    }

    private void UpdateVideoOptionVisibility()
    {
        var entry = _inputLayout;
        if (entry is null) return;
        bool showVideo = _videoEntryRequested || SocialVideoDownloader.InputContainsVideo(_url.Text);
        entry.SuspendLayout();
        foreach (var control in _videoOptionControls) control.Visible = showVideo;
        for (int row = 0; row < 5; row++)
        {
            var style = entry.RowStyles[row];
            style.SizeType = row < 3 || showVideo ? SizeType.Percent : SizeType.Absolute;
            style.Height = row >= 3 && !showVideo ? 0 : showVideo ? 20 : 100f / 3f;
        }
        // Shrink the entire panel: no empty video-property rows for ZIP,
        // documents, ordinary HTTP links, or direct-file video links.
        entry.Height = showVideo ? 268 : 166;
        if (_workspaceRoot is not null && !_syncPanelOpen)
            _workspaceRoot.RowStyles[2].Height = _inputVisible ? entry.Height : 0;
        entry.ResumeLayout(true);
    }

    private static Label MakeLabel(string value) => new()
    {
        Text = value, Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft,
        ForeColor = Color.FromArgb(54, 76, 111), Font = new Font("Segoe UI", 10, FontStyle.Bold)
    };

    private static void SetupText(TextBox box, string accessibleName)
    {
        box.Dock = DockStyle.Fill;
        box.Margin = new Padding(3, 9, 6, 9);
        box.BorderStyle = BorderStyle.FixedSingle;
        box.Font = new Font("Segoe UI", 11);
        box.AccessibleName = accessibleName;
    }

    private static Button MakeButton(string text, bool primary, EventHandler handler)
    {
        var button = new Button
        {
            Text = text, Dock = DockStyle.Fill, Margin = new Padding(3, 7, 3, 7),
            Font = new Font("Segoe UI", 9, FontStyle.Bold), FlatStyle = FlatStyle.Flat,
            BackColor = primary ? Color.FromArgb(0, 111, 221) : Color.FromArgb(231, 239, 250),
            ForeColor = primary ? Color.White : Color.FromArgb(36, 77, 139),
            Cursor = Cursors.Hand
        };
        button.FlatAppearance.BorderSize = 0;
        button.Click += handler;
        return button;
    }

    private void AddUrls()
    {
        var urls = _url.Text.Split(new[] { '\r', '\n', ' ', '\t' },
            StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).Take(200).ToArray();
        if (urls.Length == 0) { _url.Focus(); return; }
        if (string.IsNullOrWhiteSpace(_folder.Text))
        {
            MessageBox.Show(this, "กรุณาเลือกโฟลเดอร์จัดเก็บไฟล์", "X-Stage",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        var invalid = new List<string>();
        foreach (var url in urls)
        {
            try { _engine.Add(url, _folder.Text.Trim(), int.Parse((string)_parts.SelectedItem!), SelectedQuality(), SelectedOutputFormat()); }
            catch (Exception ex) { invalid.Add(url + ": " + ex.Message); }
        }
        _url.Clear();
        RefreshRows();
        if (invalid.Count > 0)
            MessageBox.Show(this, "ลิงก์ที่ไม่สามารถเพิ่มได้:\n" +
                string.Join("\n", invalid.Take(5)), "ตรวจสอบ URL",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
    }

    private string SelectedQuality() => _videoQuality.SelectedIndex switch
    {
        1 => "1080", 2 => "720", 3 => "480", _ => "Best"
    };

    private string SelectedOutputFormat() => _outputFormat.SelectedIndex switch
    {
        1 => "mkv", 2 => "webm", 3 => "mp3", _ => "mp4"
    };

    private void ApplyPartsToSelected()
    {
        var job = Selected();
        if (job is null)
        {
            MessageBox.Show(this, "เลือกไฟล์ที่ต้องการเปลี่ยนจำนวนส่วนก่อน", "จำนวนส่วน");
            return;
        }
        if (job.Status is "Running" or "Queued")
        {
            MessageBox.Show(this, "กดหยุดชั่วคราวและรอให้รายการหยุดสนิทก่อนเปลี่ยนจำนวนส่วน", "กำลังดาวน์โหลด");
            return;
        }
        if (job.Status == "Completed")
        {
            MessageBox.Show(this, "ไฟล์ดาวน์โหลดเสร็จแล้ว เลือกจำนวนส่วนสำหรับไฟล์ใหม่ได้", "ดาวน์โหลดสำเร็จ");
            return;
        }
        var parts = int.Parse((string)_parts.SelectedItem!);
        if (job.Parts == parts) return;
        if (Interlocked.Read(ref job.DownloadedBytes) > 0 &&
            MessageBox.Show(this,
                "การเปลี่ยนจำนวนส่วนจะลบเฉพาะชิ้นส่วนชั่วคราวของไฟล์นี้และเริ่มดาวน์โหลดใหม่จาก 0%\nไฟล์ที่ดาวน์โหลดเสร็จจะไม่ถูกลบ\nดำเนินการต่อหรือไม่?",
                "ยืนยันการเปลี่ยนจำนวนส่วน", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes) return;
        try
        {
            if (!_engine.SetJobParts(job, parts))
                MessageBox.Show(this, "รายการยังทำงานอยู่หรือไม่สามารถเปลี่ยนจำนวนส่วนได้", "ไม่สามารถเปลี่ยน");
            RefreshRows();
        }
        catch (IOException ex) { MessageBox.Show(this, ex.Message, "เปลี่ยนจำนวนส่วนไม่สำเร็จ"); }
        catch (UnauthorizedAccessException ex) { MessageBox.Show(this, ex.Message, "เปลี่ยนจำนวนส่วนไม่สำเร็จ"); }
    }

    private DownloadJob? Selected()
    {
        if (_grid.SelectedRows.Count == 0) return null;
        var id = _grid.SelectedRows[0].Tag as string;
        return _engine.Jobs.FirstOrDefault(j => j.Id == id);
    }

    private DownloadJob[] SelectedDownloadJobs()
    {
        var ids = _grid.SelectedRows.Cast<DataGridViewRow>()
            .Select(row => row.Tag as string).OfType<string>().ToHashSet(StringComparer.Ordinal);
        return _engine.Jobs.Where(j => ids.Contains(j.Id)).ToArray();
    }

    private void SelectedAction(Action<DownloadJob> action)
    {
        var job = Selected();
        if (job is null) return;
        action(job);
        RefreshRows();
    }

    private void StartBrowserHandoff()
    {
        _ = Task.Run(async () =>
        {
            try
            {
                await NativeMessagingBridge.ListenAsync(url =>
                {
                    var completion = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
                    try
                    {
                        BeginInvoke(new Action(() =>
                        {
                            try
                            {
                                _engine.Add(url, _folder.Text, _engine.DefaultParts, SelectedQuality(), SelectedOutputFormat());
                                RefreshRows();
                                completion.TrySetResult(true);
                            }
                            catch (Exception)
                            {
                                completion.TrySetResult(false);
                            }
                        }));
                    }
                    catch (InvalidOperationException) { completion.TrySetResult(false); }
                    return completion.Task;
                }, _browserStop.Token);
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                if (!IsDisposed && IsHandleCreated)
                    BeginInvoke(new Action(() => _details.Text = "เชื่อมต่อเบราว์เซอร์ในเครื่องไม่ได้: " + ex.Message));
            }
        });
    }

    private void SetupBrowserIntegration()
    {
        var extensionFolder = BrowserIntegration.ExtensionFolder;
        if (!Directory.Exists(extensionFolder))
        {
            MessageBox.Show(this, "ไม่พบชุดส่วนขยายเบราว์เซอร์ กรุณาติดตั้ง X-Stage Download Manager รุ่นเต็ม",
                "ดาวน์โหลดอัตโนมัติ", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        // Let the content determine each row's height instead of relying on
        // fixed Top/Height coordinates. Thai instructions wrap at larger DPI
        // and must never overlap the folder or save buttons.
        using var dialog = new Form
        {
            Text = "ตั้งค่าดาวน์โหลดอัตโนมัติจาก Chrome / Edge",
            ClientSize = new Size(680, 390),
            MinimumSize = new Size(540, 390),
            StartPosition = FormStartPosition.CenterParent,
            FormBorderStyle = FormBorderStyle.Sizable,
            MaximizeBox = false, MinimizeBox = false,
            ShowInTaskbar = false,
            AutoScaleMode = AutoScaleMode.Font,
            Font = new Font("Segoe UI", 10),
            BackColor = Color.White
        };
        var content = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoScroll = true,
            ColumnCount = 1, RowCount = 4,
            Padding = new Padding(20, 18, 20, 18),
            BackColor = Color.White
        };
        content.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        for (var row = 0; row < content.RowCount; row++)
            content.RowStyles.Add(new RowStyle(SizeType.AutoSize));

        var instructions = new Label
        {
            AutoSize = true,
            Margin = new Padding(0, 0, 0, 18),
            Text = "ตั้งค่าดาวน์โหลดอัตโนมัติ: ส่งลิงก์จาก Chrome / Edge เข้า X-Stage\n" +
                   "1. เปิด chrome://extensions หรือ edge://extensions\n" +
                   "2. เปิดโหมดผู้พัฒนา (Developer mode) แล้วกด Load unpacked\n" +
                   "3. เลือกโฟลเดอร์ส่วนขยายของ X-Stage ด้านล่าง\n" +
                   "4. คัดลอก Extension ID (อักษร a–p 32 ตัว) มาวาง แล้วกดบันทึก",
            ForeColor = Color.FromArgb(35, 55, 83)
        };

        var folderActions = new TableLayoutPanel
        {
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            Dock = DockStyle.Top,
            ColumnCount = 2, RowCount = 1,
            Margin = new Padding(0, 0, 0, 18)
        };
        folderActions.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        folderActions.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        var openFolder = new Button
        {
            Dock = DockStyle.Fill, MinimumSize = new Size(0, 40),
            Margin = new Padding(0, 0, 6, 0),
            Text = "เปิดโฟลเดอร์ส่วนขยาย", BackColor = Color.FromArgb(231, 239, 250)
        };
        openFolder.Click += (_, _) =>
            Process.Start(new ProcessStartInfo(extensionFolder) { UseShellExecute = true });
        var copyFolder = new Button
        {
            Dock = DockStyle.Fill, MinimumSize = new Size(0, 40),
            Margin = new Padding(6, 0, 0, 0),
            Text = "คัดลอกตำแหน่งโฟลเดอร์", BackColor = Color.FromArgb(231, 239, 250)
        };
        copyFolder.Click += (_, _) => Clipboard.SetText(extensionFolder);
        folderActions.Controls.Add(openFolder, 0, 0);
        folderActions.Controls.Add(copyFolder, 1, 0);

        var idCaption = new Label
        {
            AutoSize = true, Text = "Extension ID จาก Chrome / Edge",
            Margin = new Padding(0, 0, 0, 6),
            ForeColor = Color.FromArgb(35, 55, 83)
        };
        var idActions = new TableLayoutPanel
        {
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            Dock = DockStyle.Top,
            ColumnCount = 2, RowCount = 1,
            Margin = Padding.Empty
        };
        idActions.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 70));
        idActions.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 30));
        var id = new TextBox
        {
            Dock = DockStyle.Fill, Margin = new Padding(0, 4, 8, 4),
            Font = new Font("Segoe UI", 11),
            PlaceholderText = "วาง Extension ID จากหน้าเบราว์เซอร์"
        };
        var register = new Button
        {
            Dock = DockStyle.Fill, MinimumSize = new Size(0, 40),
            Margin = Padding.Empty,
            Text = "บันทึกการเชื่อมต่อ", DialogResult = DialogResult.OK,
            BackColor = Color.FromArgb(0, 111, 221), ForeColor = Color.White
        };
        idActions.Controls.Add(id, 0, 0);
        idActions.Controls.Add(register, 1, 0);

        content.Controls.Add(instructions, 0, 0);
        content.Controls.Add(folderActions, 0, 1);
        content.Controls.Add(idCaption, 0, 2);
        content.Controls.Add(idActions, 0, 3);
        dialog.Controls.Add(content);

        // Label.AutoSize + MaximumSize wraps reliably in WinForms. Keep the
        // available width in sync when a user resizes the dialog or changes DPI;
        // AutoScroll keeps every action reachable on small displays.
        void UpdateInstructionWidth()
        {
            var available = Math.Max(220, content.ClientSize.Width -
                content.Padding.Horizontal - SystemInformation.VerticalScrollBarWidth - 6);
            if (instructions.MaximumSize.Width != available)
                instructions.MaximumSize = new Size(available, 0);
        }
        content.ClientSizeChanged += (_, _) => UpdateInstructionWidth();
        UpdateInstructionWidth();
        dialog.AcceptButton = register;
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        try
        {
            BrowserIntegration.Register(id.Text);
            MessageBox.Show(this,
                "ตั้งค่ารับดาวน์โหลดอัตโนมัติจาก Chrome / Edge สำเร็จ\n" +
                "ในส่วนขยาย ให้เปิดการรับดาวน์โหลดอัตโนมัติเฉพาะเมื่อต้องการใช้งาน\n" +
                "ส่วนขยายจะไม่ยกเลิกงานในเบราว์เซอร์หากแอปไม่รับงาน",
                "พร้อมใช้งาน", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        catch (Exception ex) when (ex is ArgumentException or IOException or UnauthorizedAccessException or InvalidOperationException)
        {
            MessageBox.Show(this, ex.Message, "ตั้งค่าดาวน์โหลดอัตโนมัติไม่สำเร็จ", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private async Task CheckForUpdatesAsync(bool manual)
    {
        if (_checkingUpdates || IsDisposed) return;
        _checkingUpdates = true;
        DownloadManagerRelease? candidate = null;
        string? verifiedInstaller = null;
        _updateStatus.Text = "กำลังตรวจสอบอัปเดต...";
        try
        {
            var release = await UpdateChecker.CheckAsync();
            if (IsDisposed) return;
            if (release is null)
            {
                _updateStatus.Text = "ไม่พบไฟล์อัปเดตที่ผ่านการตรวจสอบบนช่องทาง Preview";
                if (manual) MessageBox.Show(this, "ยังไม่พบรุ่นอัปเดตที่เผยแพร่และตรวจสอบแล้ว",
                    "ตรวจสอบอัปเดต", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
            candidate = release;
            if (!UpdateChecker.IsNewer(release.Version, release.Build))
            {
                _updateStatus.Text = $"รุ่นที่ติดตั้ง v{UpdateChecker.CurrentVersion} · Build {UpdateChecker.CurrentBuild} — ไม่มีรุ่นใหม่กว่า";
                if (manual) MessageBox.Show(this,
                    $"รุ่นที่ติดตั้ง: v{UpdateChecker.CurrentVersion} · Build {UpdateChecker.CurrentBuild}\n" +
                    $"รุ่นล่าสุดที่ตรวจสอบได้: v{release.Version} · Build {release.Build}\n\n" +
                    "ยังไม่มีตัวติดตั้งรุ่นใหม่กว่าที่ผ่านการตรวจสอบและเผยแพร่แล้ว",
                    "ตรวจสอบอัปเดต", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }

            _updateStatus.Text = $"พบอัปเดต v{release.Version} · Build {release.Build}";
            var activeCount = _engine.Jobs.Count(j => j.Status is "Running" or "Queued");
            var activeNote = activeCount > 0
                ? $"มีงานดาวน์โหลด {activeCount} รายการ ซึ่งจะหยุดชั่วคราวและเก็บไว้ให้เริ่มต่อหลังอัปเดต\n"
                : "";
            string installer;
            Point handoffCenter;
            // Stage one owns confirmation and download. Dispose its window
            // before starting the detached installer, never show both together.
            using (var download = new UpdateDownloadForm(release, activeNote))
            {
                if (download.ShowDialog(this) != DialogResult.OK)
                {
                    if (download.Error is not null) throw download.Error;
                    _updateStatus.Text = $"มีอัปเดต v{release.Version} · Build {release.Build} — กดตรวจสอบอัปเดตอีกครั้ง";
                    return;
                }
                installer = download.VerifiedSetup!;
                verifiedInstaller = installer;
                handoffCenter = download.HandoffCenter;
            }
            if (IsDisposed) return;
            // Do not start the helper if closing would be vetoed by an active
            // live recording. Keep the verified setup for the next attempt.
            if (_smartSyncWindow?.IsBusy == true ||
                Application.OpenForms.OfType<LiveStreamCaptureForm>().Any(window => window.IsBusy))
            {
                _updateStatus.Text = "ไฟล์อัปเดตพร้อมแล้ว · กรุณาหยุด Smart Sync/บันทึกไลฟ์ก่อนติดตั้ง แล้วกดตรวจสอบอัปเดตอีกครั้ง";
                return;
            }
            _updateStatus.Text = "ตรวจสอบ SHA-256 ผ่าน · กำลังส่งต่อไปยังหน้าต่างอัปเดต";
            // The detached helper is the sole progress window. Do not open
            // another countdown dialog over it. Close only after its readiness
            // handshake; FormClosing still saves interrupted download intent.
            _updateHandoffInProgress = true;
            var disabledWindows = OwnedForms.Where(window => window.Enabled).ToArray();
            Enabled = false;
            foreach (var window in disabledWindows) window.Enabled = false;
            try
            {
                // Keep the UI message loop alive while the copied EXE starts.
                await Task.Run(() => SelfUpdater.LaunchInstallerHelper(
                    installer, release, handoffCenter.X, handoffCenter.Y));
            }
            finally
            {
                _updateHandoffInProgress = false;
                if (!IsDisposed) Enabled = true;
                foreach (var window in disabledWindows)
                    if (!window.IsDisposed) window.Enabled = true;
            }
            if (!IsDisposed) Close();
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or
                                     System.Text.Json.JsonException or IOException or
                                     UnauthorizedAccessException or System.ComponentModel.Win32Exception or
                                     InvalidOperationException)
        {
            if (IsDisposed) return;
            _updateStatus.Text = "อัปเดตไม่สำเร็จ: " + ex.Message.Split('\n')[0];
            var message = ex.Message +
                "\n\nแอปเดิมยังใช้งานได้ ไม่ติดตั้งไฟล์ที่ตรวจสอบไม่ผ่าน" +
                "\nไฟล์บันทึก: " + SelfUpdater.DownloadLogPath;
            if (verifiedInstaller is not null)
            {
                // A helper failure is not a checksum failure. Keep verified
                // bytes and offer their location only when no helper remains.
                if (ex is UpdateHandoffException { CanInstallManually: true } &&
                    File.Exists(verifiedInstaller))
                {
                    if (MessageBox.Show(this, ex.Message +
                        "\n\nต้องการเปิดโฟลเดอร์ไฟล์ติดตั้งที่ตรวจสอบแล้วหรือไม่? ปิดโปรแกรมเดิมก่อนเปิด Setup EXE" +
                        "\nไฟล์บันทึก: " + SelfUpdater.DownloadLogPath,
                        "เปิดตัวช่วยติดตั้งไม่สำเร็จ · SHA-256 ผ่านแล้ว", MessageBoxButtons.YesNo,
                        MessageBoxIcon.Warning) == DialogResult.Yes)
                    {
                        try
                        {
                            var explorer = new ProcessStartInfo("explorer.exe") { UseShellExecute = true };
                            explorer.ArgumentList.Add("/select," + verifiedInstaller);
                            Process.Start(explorer);
                        }
                        catch (Exception openError)
                        {
                            _updateStatus.Text = "เปิดโฟลเดอร์ไม่ได้: " + openError.Message;
                        }
                    }
                }
                else MessageBox.Show(this, message, "ส่งต่อการติดตั้งไม่สำเร็จ",
                    MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
            else if (candidate is not null)
            {
                if (MessageBox.Show(this,
                    message + "\n\nต้องการเปิดหน้าดาวน์โหลด EXE อย่างเป็นทางการผ่านเบราว์เซอร์หรือไม่?",
                    "ดาวน์โหลดและตรวจ SHA-256 ไม่สำเร็จ", MessageBoxButtons.YesNo,
                    MessageBoxIcon.Warning) == DialogResult.Yes)
                    Process.Start(new ProcessStartInfo(candidate.Url) { UseShellExecute = true });
            }
            else
                MessageBox.Show(this, message, "ตรวจสอบอัปเดตไม่สำเร็จ",
                    MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
        finally { _checkingUpdates = false; }
    }

    private void PrepareCompletedMenu(DownloadJob job)
    {
        // Reuse the menu for the lifetime of the form. Disposing it from its
        // Closed event caused the System.Windows.Forms.ContextMenuStrip crash.
        if (_completedMenu.Visible) _completedMenu.Close();
        _completedMenu.Items.Clear();
        _completedMenu.Items.Add("เปิดไฟล์", null, (_, _) => OpenCompletedFile(job)).Enabled =
            job.Status == "Completed" && File.Exists(job.CompletedPath);
        _completedMenu.Items.Add("เปิดโฟลเดอร์ที่บันทึก", null, (_, _) => OpenCompletedFolder(job));
        var priority = new ToolStripMenuItem("ลำดับความสำคัญ");
        foreach (var (title, value) in new[] {
            ("สูง", 0), ("ปกติ", 1), ("ต่ำ", 2)
        })
        {
            var choice = new ToolStripMenuItem(title)
            {
                Checked = job.Priority == value
            };
            choice.Click += (_, _) => SetPriority(job, value);
            priority.DropDownItems.Add(choice);
        }
        _completedMenu.Items.Add(priority);
        var queues = new ToolStripMenuItem("จัดเข้าคิว");
        foreach (var name in _engine.GetQueueNames())
        {
            var queueName = name;
            var choice = new ToolStripMenuItem(queueName)
            {
                Checked = string.Equals(
                    string.IsNullOrWhiteSpace(job.QueueName) ? "ทั่วไป" : job.QueueName.Trim(),
                    queueName, StringComparison.OrdinalIgnoreCase)
            };
            choice.Click += (_, _) => AssignJobQueue(job, queueName);
            queues.DropDownItems.Add(choice);
        }
        queues.DropDownItems.Add(new ToolStripSeparator());
        queues.DropDownItems.Add("สร้างคิวใหม่...", null, (_, _) => CreateJobQueue(job));
        queues.DropDownItems.Add("เปลี่ยนชื่อคิวปัจจุบัน...", null,
            (_, _) => RenameJobQueue(job));
        _completedMenu.Items.Add(queues);
        _completedMenu.Items.Add("จำกัดความเร็ว HTTP รายไฟล์...", null,
            (_, _) => ConfigureFileSpeed(job));

        _completedMenu.Items.Add("เปลี่ยนชื่อไฟล์ (F2)", null, (_, _) => RenameCompletedJob(job))
            .Enabled = job.Status == "Completed" && File.Exists(job.CompletedPath);
        if (job.Kind == "Video")
        {
            var downloadAgain = new ToolStripMenuItem(
                "ดาวน์โหลดวิดีโอใหม่ / เปลี่ยนคุณภาพและรูปแบบไฟล์",
                null, (_, _) => RedownloadVideo(job));
            downloadAgain.Enabled = job.Status is not ("Running" or "Queued");
            _completedMenu.Items.Insert(0, downloadAgain);
        }
        if (job.Status is "Failed" or "Missing")
        {
            _completedMenu.Items.Insert(0, new ToolStripMenuItem(
                "ดูสาเหตุข้อผิดพลาด", null, (_, _) => ShowJobError(job)));
            if (job.Kind == "Video")
                _completedMenu.Items.Add("เปิดบันทึกข้อผิดพลาดวิดีโอ", null, (_, _) => OpenVideoLog(job));
        }
        _completedMenu.AutoClose = true;
    }

    private void ShowCompletedMenu(DownloadJob job, Rectangle cellBounds)
    {
        PrepareCompletedMenu(job);
        _completedMenu.Show(_grid, new Point(cellBounds.Left + 12, cellBounds.Bottom));
    }

    private void RedownloadVideo(DownloadJob source)
    {
        if (source.Kind != "Video") return;
        if (source.Status is "Running" or "Queued")
        {
            MessageBox.Show(this, "กรุณาหยุดงานเดิมก่อนดาวน์โหลดใหม่",
                "ดาวน์โหลดวิดีโอใหม่", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }

        using var dialog = new Form
        {
            Text = "ดาวน์โหลดวิดีโอใหม่ · เลือกคุณสมบัติ",
            Width = 680, Height = 440,
            MinimumSize = new Size(600, 410),
            StartPosition = FormStartPosition.CenterParent,
            FormBorderStyle = FormBorderStyle.FixedDialog,
            MaximizeBox = false, MinimizeBox = false,
            BackColor = Color.White,
            Font = new Font("Segoe UI", 10)
        };
        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill, ColumnCount = 3, RowCount = 7,
            Padding = new Padding(20, 15, 20, 14)
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 150));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 112));
        foreach (var height in new[] { 55, 49, 49, 49, 49, 62, 55 })
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, height));
        var heading = new Label
        {
            Text = "ดาวน์โหลดใหม่: " + source.Name,
            Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft,
            AutoEllipsis = true, Font = new Font("Segoe UI", 11, FontStyle.Bold)
        };
        layout.Controls.Add(heading, 0, 0);
        layout.SetColumnSpan(heading, 3);

        static Label Caption(string label) => new()
        {
            Text = label, Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleLeft,
            ForeColor = Color.FromArgb(55, 75, 100)
        };
        static ComboBox Choice(params string[] options)
        {
            var box = new ComboBox
            {
                Dock = DockStyle.Fill,
                DropDownStyle = ComboBoxStyle.DropDownList,
                Margin = new Padding(3, 7, 8, 8)
            };
            box.Items.AddRange(options);
            return box;
        }
        var quality = Choice("ดีที่สุด (ภาพและเสียง)", "1080p", "720p", "480p");
        quality.SelectedIndex = source.VideoQuality switch
        {
            "1080" => 1, "720" => 2, "480" => 3, _ => 0
        };
        layout.Controls.Add(Caption("คุณภาพวิดีโอ"), 0, 1);
        layout.Controls.Add(quality, 1, 1);
        layout.SetColumnSpan(quality, 2);

        var format = Choice("MP4 (แนะนำ)", "MKV", "WEBM", "MP3 (เสียงอย่างเดียว)");
        format.SelectedIndex = source.OutputFormat switch
        {
            "mkv" => 1, "webm" => 2, "mp3" => 3, _ => 0
        };
        format.SelectedIndexChanged += (_, _) => quality.Enabled = format.SelectedIndex != 3;
        quality.Enabled = format.SelectedIndex != 3;
        layout.Controls.Add(Caption("รูปแบบไฟล์"), 0, 2);
        layout.Controls.Add(format, 1, 2);
        layout.SetColumnSpan(format, 2);

        var parts = Choice("1", "2", "4", "8", "16", "32");
        parts.SelectedItem = source.Parts.ToString();
        if (parts.SelectedIndex < 0) parts.SelectedItem = "4";
        layout.Controls.Add(Caption("จำนวนส่วน"), 0, 3);
        layout.Controls.Add(parts, 1, 3);
        layout.SetColumnSpan(parts, 2);

        var folder = new TextBox
        {
            Text = source.Folder, Dock = DockStyle.Fill,
            Margin = new Padding(3, 9, 6, 9)
        };
        var browse = new Button
        {
            Text = "เลือก...", Dock = DockStyle.Fill,
            Margin = new Padding(2, 6, 2, 6)
        };
        browse.Click += (_, _) =>
        {
            using var picker = new FolderBrowserDialog
            {
                Description = "เลือกโฟลเดอร์สำหรับวิดีโอที่ดาวน์โหลดใหม่",
                SelectedPath = Directory.Exists(folder.Text) ? folder.Text : source.Folder
            };
            if (picker.ShowDialog(dialog) == DialogResult.OK)
                folder.Text = picker.SelectedPath;
        };
        layout.Controls.Add(Caption("บันทึกที่"), 0, 4);
        layout.Controls.Add(folder, 1, 4);
        layout.Controls.Add(browse, 2, 4);

        var note = new Label
        {
            Text = "สร้างรายการดาวน์โหลดใหม่ โดยไม่ลบไฟล์หรือเปลี่ยนประวัติรายการเดิม\nแม้เลือกคุณภาพและชนิดไฟล์เดิม ก็จะบันทึกเป็นไฟล์อีกชุด",
            Dock = DockStyle.Fill, ForeColor = Color.FromArgb(70, 98, 127),
            TextAlign = ContentAlignment.MiddleLeft
        };
        layout.Controls.Add(note, 0, 5);
        layout.SetColumnSpan(note, 3);

        var actions = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill, FlowDirection = FlowDirection.RightToLeft,
            WrapContents = false
        };
        var ok = new Button { Text = "เริ่มดาวน์โหลดใหม่", Width = 160,
            Height = 38, DialogResult = DialogResult.OK };
        var cancel = new Button { Text = "ยกเลิก", Width = 92, Height = 38,
            DialogResult = DialogResult.Cancel };
        actions.Controls.Add(ok);
        actions.Controls.Add(cancel);
        layout.Controls.Add(actions, 0, 6);
        layout.SetColumnSpan(actions, 3);
        dialog.Controls.Add(layout);
        dialog.AcceptButton = ok;
        dialog.CancelButton = cancel;

        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        var selectedQuality = quality.SelectedIndex switch
        {
            1 => "1080", 2 => "720", 3 => "480", _ => "Best"
        };
        var selectedFormat = format.SelectedIndex switch
        {
            1 => "mkv", 2 => "webm", 3 => "mp3", _ => "mp4"
        };
        try
        {
            var newJob = _engine.AddVideoAgain(source, selectedQuality, selectedFormat,
                folder.Text, int.Parse((string)parts.SelectedItem!));
            RefreshRows();
            _details.Text = "เพิ่มงานดาวน์โหลดใหม่แล้ว: " + newJob.Url +
                            " · " + newJob.OutputFormat.ToUpperInvariant();
        }
        catch (Exception ex) when (ex is ArgumentException or IOException or
                                   UnauthorizedAccessException or InvalidOperationException)
        {
            MessageBox.Show(this, ex.Message, "ดาวน์โหลดวิดีโอใหม่ไม่สำเร็จ",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private static string VideoLogPath(DownloadJob job) => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "X-Stage", "Download Manager", "logs", "video-" + job.Id + ".log");

    private void ShowJobError(DownloadJob job)
    {
        var message = string.IsNullOrWhiteSpace(job.Error)
            ? "ไม่มีรายละเอียดเพิ่มเติมจากเว็บไซต์ต้นทาง" : job.Error;
        if (job.Kind == "Video")
            message += "\n\nบันทึกสำหรับตรวจสอบ:\n" + VideoLogPath(job);
        MessageBox.Show(this, message, "สาเหตุที่ดาวน์โหลดไม่สำเร็จ",
            MessageBoxButtons.OK, MessageBoxIcon.Warning);
    }

    private void OpenVideoLog(DownloadJob job)
    {
        try
        {
            var path = VideoLogPath(job);
            if (!File.Exists(path))
            {
                MessageBox.Show(this, "ยังไม่พบบันทึกข้อผิดพลาดของรายการนี้",
                    "บันทึกการดาวน์โหลด", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
            var info = new ProcessStartInfo("notepad.exe") { UseShellExecute = true };
            info.ArgumentList.Add(path);
            Process.Start(info);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or
                                   System.ComponentModel.Win32Exception)
        {
            MessageBox.Show(this, ex.Message, "เปิดบันทึกไม่สำเร็จ");
        }
    }

    private void RenameCompletedJob(DownloadJob job)
    {
        if (job.Status != "Completed" || !File.Exists(job.CompletedPath)) return;
        using var dialog = new Form
        {
            Text = "เปลี่ยนชื่อไฟล์ที่ดาวน์โหลดแล้ว",
            Width = 565, Height = 216, MinimumSize = new Size(500, 216),
            FormBorderStyle = FormBorderStyle.FixedDialog,
            StartPosition = FormStartPosition.CenterParent,
            MaximizeBox = false, MinimizeBox = false, BackColor = Color.White,
            Font = new Font("Segoe UI", 10)
        };
        var label = new Label
        {
            Text = "ชื่อไฟล์ (คงนามสกุลเดิมเพื่อให้เปิดไฟล์ได้ถูกต้อง)",
            Left = 20, Top = 17, Width = 510, Height = 27
        };
        var input = new TextBox
        {
            Text = job.Name, Left = 20, Top = 54, Width = 510, Height = 30
        };
        input.SelectionStart = 0;
        input.SelectionLength = Math.Max(0,
            job.Name.Length - Path.GetExtension(job.Name).Length);
        var hint = new Label
        {
            Text = "ระบบเปลี่ยนชื่อไฟล์ในโฟลเดอร์จริง และบันทึกประวัติให้ตรงกัน\nหากมีชื่อซ้ำจะเพิ่ม (1), (2) โดยไม่เขียนทับไฟล์เดิม",
            Left = 20, Top = 91, Width = 510, Height = 41,
            ForeColor = Color.FromArgb(76, 101, 128)
        };
        var cancel = new Button
        {
            Text = "ยกเลิก", Left = 314, Top = 137, Width = 96, Height = 32,
            DialogResult = DialogResult.Cancel
        };
        var ok = new Button
        {
            Text = "บันทึกชื่อใหม่", Left = 417, Top = 137, Width = 113, Height = 32,
            DialogResult = DialogResult.OK
        };
        dialog.Controls.AddRange(new Control[] { label, input, hint, cancel, ok });
        dialog.AcceptButton = ok;
        dialog.CancelButton = cancel;
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        try
        {
            var path = _engine.RenameCompletedFile(job, input.Text);
            RefreshRows();
            _details.Text = "เปลี่ยนชื่อไฟล์สำเร็จ: " + Path.GetFileName(path);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or
                                   ArgumentException or InvalidOperationException)
        {
            MessageBox.Show(this, ex.Message, "เปลี่ยนชื่อไฟล์ไม่สำเร็จ",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private void OpenCompletedFile(DownloadJob job)
    {
        try
        {
            if (File.Exists(job.CompletedPath))
                Process.Start(new ProcessStartInfo(job.CompletedPath) { UseShellExecute = true });
            else MessageBox.Show(this, "ไม่พบไฟล์ที่ดาวน์โหลดเสร็จแล้ว", "เปิดไฟล์");
        }
        catch (Exception ex) { MessageBox.Show(this, ex.Message, "เปิดไฟล์ไม่สำเร็จ"); }
    }

    private void OpenCompletedFolder(DownloadJob job)
    {
        try
        {
            if (File.Exists(job.CompletedPath))
            {
                var info = new ProcessStartInfo("explorer.exe") { UseShellExecute = true };
                info.ArgumentList.Add("/select,");
                info.ArgumentList.Add(job.CompletedPath);
                Process.Start(info);
            }
            else if (Directory.Exists(job.Folder))
                Process.Start(new ProcessStartInfo(job.Folder) { UseShellExecute = true });
            else MessageBox.Show(this, "ไม่พบโฟลเดอร์ปลายทาง", "เปิดโฟลเดอร์");
        }
        catch (Exception ex) { MessageBox.Show(this, ex.Message, "เปิดโฟลเดอร์ไม่สำเร็จ"); }
    }

    private void OpenSelected()
    {
        var job = Selected();
        if (job is null)
        {
            try
            {
                if (Directory.Exists(_folder.Text))
                    Process.Start(new ProcessStartInfo(_folder.Text) { UseShellExecute = true });
                else MessageBox.Show(this, "กรุณาเลือกโฟลเดอร์ปลายทางก่อน", "X-Stage");
            }
            catch (Exception ex) { MessageBox.Show(this, ex.Message, "เปิดโฟลเดอร์ไม่สำเร็จ"); }
            return;
        }
        // Do not silently launch a completed file: let the user choose.
        // A failed/incomplete download can still open its destination folder.
        PrepareCompletedMenu(job);
        _completedMenu.Show(Cursor.Position);
    }

    private long _lastDestinationCheck;

    private void RefreshRows()
    {
        if (IsDisposed || _grid.IsDisposed) return;
        var now = Environment.TickCount64;
        if (_lastDestinationCheck == 0 || now - _lastDestinationCheck >= 5000)
        {
            _lastDestinationCheck = now;
            _engine.RefreshCompletedFiles();
        }
        var jobs = _engine.Jobs.ToArray();

        // UI selection/search may refresh rows between timer ticks.
        // Only measure throughput on a real elapsed-time interval; otherwise
        // those extra refreshes would create fake zeros/spikes in the chart.
        var tick = Environment.TickCount64;
        var elapsedMs = _lastSpeedMeasurementTick == 0
            ? _timer.Interval : Math.Max(0, tick - _lastSpeedMeasurementTick);
        var measureRate = _lastSpeedMeasurementTick == 0 ||
            elapsedMs >= Math.Max(400, _timer.Interval * 3 / 4);
        if (measureRate) _lastSpeedMeasurementTick = tick;
        double speedTotal = 0;
        foreach (var job in jobs)
        {
            if (measureRate)
            {
                var current = Interlocked.Read(ref job.DownloadedBytes);
                var diff = Math.Max(0L, current - job.PreviousBytes);
                job.SpeedBytesPerSecond = job.Status == "Running"
                    ? diff / (Math.Max(1, elapsedMs) / 1000.0) : 0;
                job.SmoothedSpeedBytesPerSecond = TransferRateMath.Smooth(
                    job.SmoothedSpeedBytesPerSecond, job.SpeedBytesPerSecond,
                    job.Status == "Running");
                job.PreviousBytes = current;
            }
            speedTotal += job.Status == "Running" ? job.SpeedBytesPerSecond : 0;
        }

        TrackLiveEvents(jobs);
        var selectedIds = _grid.SelectedRows.Cast<DataGridViewRow>()
            .Select(row => row.Tag as string).OfType<string>().ToHashSet(StringComparer.Ordinal);
        var visible = DownloadTableSort.Sort(jobs.Where(job => InSelectedCategory(job) && MatchesSearch(job)),
            _sortColumn, _sortDescending, jobs);
        var syncLanes = VisibleSyncLanes();
        var tags = visible.Select(j => j.Id).Concat(syncLanes.Select(l => l.Upload ? SyncUploadTag : SyncDownloadTag)).ToArray();
        var listChanged = _grid.Rows.Count != tags.Length ||
            tags.Where((tag, index) => index < _grid.Rows.Count &&
                !Equals(_grid.Rows[index].Tag, tag)).Any();
        _visibleJobs = visible;
        UpdateCategoryCounts(jobs);
        UpdateOverviewCounts(jobs);
        if (listChanged)
        {
            _grid.SuspendLayout();
            try
            {
                _grid.Rows.Clear();
                foreach (var tag in tags)
                {
                    var index = _grid.Rows.Add();
                    _grid.Rows[index].Tag = tag;
                }
                _grid.ClearSelection();
                foreach (DataGridViewRow row in _grid.Rows)
                    if (row.Tag is string id && selectedIds.Contains(id))
                        row.Selected = true;
            }
            finally { _grid.ResumeLayout(true); }
        }

        foreach (var (job, index) in visible.Select((job, index) => (job, index)))
        {
            var row = _grid.Rows[index];
            var current = Interlocked.Read(ref job.DownloadedBytes);
            row.Cells["No"].Value = (index + 1).ToString("00");
            row.Cells["KindIcon"].Value = GetRowIcon(job);
            row.Cells["QueueName"].Value =
                string.IsNullOrWhiteSpace(job.QueueName) ? "ทั่วไป" : job.QueueName;
            row.Cells["QueueName"].ToolTipText = job.Priority switch
            {
                0 => "คิว: " + job.QueueName + " · ความสำคัญสูง",
                2 => "คิว: " + job.QueueName + " · ความสำคัญต่ำ",
                _ => "คิว: " + job.QueueName + " · ความสำคัญปกติ"
            };
            row.Cells["File"].Value = job.Status == "Completed" ? "✓  " + job.Name : job.Name;
            row.Cells["File"].Style.ForeColor = job.Status == "Completed"
                ? Color.FromArgb(119, 229, 169) : Color.FromArgb(229, 236, 246);
            row.Cells["File"].Style.SelectionForeColor = Color.White;
            row.Cells["File"].Style.Font = job.Status == "Completed"
                ? _finishedFileFont : _normalFileFont;
            row.Cells["FileType"].Value = DownloadTableSort.FileType(job);
            row.Cells["FileType"].ToolTipText = "ชนิดไฟล์: " + DownloadTableSort.FileType(job);
            row.Cells["Queue"].Value = (Array.IndexOf(jobs, job) + 1).ToString("00");
            row.Cells["Size"].Value = job.TotalBytes < 0 ? "ไม่ทราบ" : FormatBytes(job.TotalBytes);
            row.Cells["Progress"].Value = ProgressPresentation.IsComplete(job) ||
                job.Kind == "Video" || job.TotalBytes > 0
                    ? ProgressPresentation.PercentLabel(job)
                    : (current > 0 ? FormatBytes(current) : "—");
            row.Cells["Speed"].Value = job.Status == "Running"
                ? FormatBytes((long)job.SmoothedSpeedBytesPerSecond) + "/s" : "—";
            row.Cells["ETA"].Value = EtaLabel(job);
            row.Cells["Added"].Value = job.CreatedAt.ToLocalTime().ToString("dd/MM/yy HH:mm");
            row.Cells["Status"].ToolTipText = job.Status is "Failed" or "Missing" ? job.Error :
                job.Kind == "Video" && job.Status == "Running" ? job.VideoPhase : "";
            row.Cells["File"].ToolTipText = job.Status is "Failed" or "Missing"
                ? "คลิกเพื่อดูสาเหตุข้อผิดพลาด: " + job.Error
                : job.Name + "\n" + job.Url;
            row.Cells["Status"].Value = job.Status switch
            {
                "Running" => job.Kind == "Video" && job.VideoPhase.Length > 0
                    ? job.VideoPhase : job.TransferPhase.Length > 0
                    ? job.TransferPhase : "กำลังดาวน์โหลด",
                "Queued" => "รอคิว",
                "Paused" => "หยุดชั่วคราว",
                "Completed" => "สำเร็จ",
                "Missing" => "ไม่พบไฟล์ปลายทาง",
                "Failed" => "เกิดข้อผิดพลาด",
                _ => job.Status
            };
            row.Cells["Status"].Style.ForeColor = job.Status switch
            {
                "Completed" => Color.FromArgb(124, 235, 173),
                "Failed" or "Missing" => Color.FromArgb(255, 166, 166),
                "Running" => Color.FromArgb(146, 205, 254),
                _ => Color.FromArgb(215, 225, 238)
            };
            row.Cells["Parts"].Value = job.Kind == "Video"
                ? "สูงสุด " + Math.Min(job.Parts, 4) + " สตรีม"
                : job.SegmentsUsed > 0
                    ? job.SegmentsUsed + " / " + job.Parts + " ส่วน"
                    : "ตั้งไว้ " + job.Parts + " ส่วน";
            row.Cells["Queue"].ToolTipText = job.Priority switch
            {
                0 => "ความสำคัญสูง", 2 => "ความสำคัญต่ำ", _ => "ความสำคัญปกติ"
            };
            row.Cells["Description"].Value = job.Kind == "Video"
                ? SocialVideoDownloader.Platform(job.Url) + " · " +
                  job.OutputFormat.ToUpperInvariant() + " · " + job.VideoQuality
                : CategoryOf(job) switch
                {
                    "music" => "เพลง / เสียง",
                    "document" => "เอกสาร",
                    "program" => "โปรแกรมติดตั้ง",
                    "archive" => "ไฟล์บีบอัด",
                    "video" => "ไฟล์วิดีโอ",
                    _ => "ไฟล์ทั่วไป"
                };
        }
        for (int i = 0; i < syncLanes.Length; i++)
            RenderSyncRow(_grid.Rows[visible.Count + i], syncLanes[i], visible.Count + i);
        var active = jobs.Count(j => j.Status == "Running");
        var completed = jobs.Count(j => j.Status == "Completed");
        var queued = jobs.Count(j => j.Status == "Queued");
        var failed = jobs.Count(j => j.Status is "Failed" or "Missing");
        _transferHeading.Text = "▣  รายการงาน (" + tags.Length.ToString("N0") + ")";
        if (_smartSyncWindow?.IsBusy == true) _transferHeading.Text += " · Smart Sync";
        UpdateSyncAnimation();
        _summary.Text = $"พร้อมทำงาน  ·  ทั้งหมด {jobs.Length:N0} งาน  ·  กำลังดาวน์โหลด {active:N0}  ·  เสร็จแล้ว {completed:N0}";
        _details.Text = $"ความเร็วดาวน์โหลด {FormatBytes((long)speedTotal)}/s  ·  รอคิว {queued:N0}  ·  ผิดพลาด {failed:N0}" +
            (_smartSyncWindow?.IsBusy == true
                ? " · " + (syncLanes.Any(l => l.IsScanning) ? "Sync ตรวจสอบ" :
                    syncLanes.Any(l => l.State == "กำลังรับส่ง") ? "Sync รับส่งไฟล์" : "Sync รอตรวจใหม่")
                : "");
        if (measureRate) RecordTransferSpeed(speedTotal);
        UpdateDetails();
        _engine.SaveProgressIfDue();
        if (_engine.LastStorageError.Length > 0)
            _updateStatus.Text = _engine.LastStorageError;
    }

    private void UpdateDetails()
    {
        var lane = SelectedSyncLane();
        if (lane is not null) { UpdateSyncPreview(lane); return; }
        var job = Selected();
        UpdateLivePreview(job);
        // The full job URL, location, progress and diagnostics now live in
        // the lower dock. The thin footer stays reserved for live totals,
        // rather than getting overwritten when the selected row changes.
    }

    private void PaintProgress(object? sender, DataGridViewCellPaintingEventArgs e)
    {
        if (e.RowIndex < 0 || e.ColumnIndex != _grid.Columns["Progress"].Index) return;
        var graphics = e.Graphics;
        if (graphics is null) return;
        e.PaintBackground(e.CellBounds, true);
        var lane = SyncLaneAt(e.RowIndex);
        if (lane is not null)
        {
            var rect = new Rectangle(e.CellBounds.X + 9, e.CellBounds.Y + 10, Math.Max(1, e.CellBounds.Width - 18), 20);
            using var background = new SolidBrush(Color.FromArgb(229, 236, 245));
            using var green = new SolidBrush(Color.FromArgb(17, 157, 104));
            graphics.FillRectangle(background, rect);
            if (lane.IsScanning)
            {
                var band = SmartSyncScanAnimation.Band(rect.Width, Environment.TickCount64);
                graphics.FillRectangle(green, rect.X + band.Offset, rect.Y, band.Width, rect.Height);
            }
            else graphics.FillRectangle(green, rect.X, rect.Y, (int)Math.Round(rect.Width * lane.Fraction), rect.Height);
            using var font = new Font("Segoe UI", 8, FontStyle.Bold);
            TextRenderer.DrawText(graphics, lane.ProgressText, font, rect,
                lane.Fraction > .52 ? Color.White : Color.FromArgb(25, 70, 117),
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
            e.Handled = true;
            return;
        }
        var job = VisibleJobAt(e.RowIndex);
        if (job is not null && (job.TotalBytes > 0 || job.Kind == "Video" ||
                                ProgressPresentation.IsComplete(job)))
        {
            var completeJob = ProgressPresentation.IsComplete(job);
            var progress = ProgressPresentation.FillFraction(job);
            var rectangle = new Rectangle(e.CellBounds.X + 9, e.CellBounds.Y + 10,
                Math.Max(1, e.CellBounds.Width - 18), 20);
            using var bg = new SolidBrush(Color.FromArgb(229, 236, 245));
            using var fg = new SolidBrush(Color.FromArgb(32, 133, 222));
            using var complete = new SolidBrush(Color.FromArgb(17, 157, 104));
            graphics.FillRectangle(bg, rectangle);
            // Completed always has one continuous green bar, even when
            // temporary HTTP segment counters still contain gaps/old values.
            if (completeJob)
            {
                graphics.FillRectangle(complete, rectangle);
            }
            else
            {
                var segments = job.SegmentDownloadedBytes;
                var segmentCount = job.SegmentsUsed;
                if (job.Kind != "Video" && segmentCount > 1 && job.TotalBytes > 0 &&
                    segments.Length == segmentCount && segmentCount <= 32)
                {
                    for (int i = 0; i < segmentCount; i++)
                    {
                        long segmentSize = job.TotalBytes * (i + 1) / segmentCount -
                                           job.TotalBytes * i / segmentCount;
                        var partProgress = segmentSize <= 0 ? 0 :
                            Math.Clamp(Interlocked.Read(ref segments[i]) / (double)segmentSize, 0, 1);
                        var startX = rectangle.X + i * rectangle.Width / segmentCount;
                        var endX = rectangle.X + (i + 1) * rectangle.Width / segmentCount;
                        var width = Math.Max(1, endX - startX - (segmentCount > 1 ? 1 : 0));
                        graphics.FillRectangle(partProgress >= 1 ? complete : fg,
                            startX, rectangle.Y, (int)Math.Round(width * partProgress), rectangle.Height);
                    }
                }
                else
                    graphics.FillRectangle(fg, rectangle.X, rectangle.Y,
                        (int)Math.Round(rectangle.Width * progress), rectangle.Height);
            }
            using var progressFont = new Font("Segoe UI", 8, FontStyle.Bold);
            TextRenderer.DrawText(graphics, ProgressPresentation.PercentLabel(job),
                progressFont, rectangle,
                completeJob || progress > .52 ? Color.White : Color.FromArgb(25, 70, 117),
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
        }
        else
            TextRenderer.DrawText(graphics, e.FormattedValue?.ToString() ?? "—",
                _grid.Font, e.CellBounds, Color.FromArgb(188, 198, 214),
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
        e.Handled = true;
    }

    private static string SyncName(bool upload) => upload ? "Smart Sync · อัปโหลด PC → Drive" : "Smart Sync · ดาวน์โหลด Drive → PC";

    private SmartSyncLaneSnapshot[] VisibleSyncLanes()
    {
        if (_smartSyncWindow is null) return Array.Empty<SmartSyncLaneSnapshot>();
        var (up, down) = _smartSyncWindow.Lanes.Snapshot();
        return new[] { up, down }.Where(lane =>
            (_categoryFilter switch
            {
                "all" or "sync" => true,
                "active" => lane.State is "กำลังรับส่ง" or "กำลังตรวจสอบ",
                "queued" => lane.State == "พร้อมรับส่ง",
                "completed" => lane.IsComplete,
                "failed" => lane.State == "เกิดข้อผิดพลาด",
                "incomplete" => lane.State is "กำลังรับส่ง" or "กำลังตรวจสอบ" or "พร้อมรับส่ง" or "หยุดชั่วคราว" or "เกิดข้อผิดพลาด",
                _ => false
            }) && (string.IsNullOrWhiteSpace(_jobSearch.Text) ||
                SyncName(lane.Upload).Contains(_jobSearch.Text.Trim(), StringComparison.OrdinalIgnoreCase))).ToArray();
    }

    private SmartSyncLaneSnapshot? SyncLaneAt(int row)
    {
        if (_smartSyncWindow is null || row < 0 || row >= _grid.Rows.Count) return null;
        var (up, down) = _smartSyncWindow.Lanes.Snapshot();
        return (_grid.Rows[row].Tag as string) switch
        {
            SyncUploadTag => up, SyncDownloadTag => down, _ => null
        };
    }
    private SmartSyncLaneSnapshot? SelectedSyncLane() => _grid.SelectedRows.Count == 0 ? null : SyncLaneAt(_grid.SelectedRows[0].Index);
    private static string SyncEta(SmartSyncLaneSnapshot lane)
    {
        if (lane.Rate <= 0 || lane.Bytes <= lane.DoneBytes) return "—";
        var seconds = Math.Min(8640000, (lane.Bytes - lane.DoneBytes) / lane.Rate);
        var eta = TimeSpan.FromSeconds(seconds);
        return $"{(int)eta.TotalHours:00}:{eta.Minutes:00}:{eta.Seconds:00}";
    }
    private void RenderSyncRow(DataGridViewRow row, SmartSyncLaneSnapshot lane, int index)
    {
        row.Cells["No"].Value = (index + 1).ToString("00");
        row.Cells["KindIcon"].Value = _categoryIcons.Images["sync"];
        row.Cells["File"].Value = SyncName(lane.Upload);
        row.Cells["File"].Style.ForeColor = Color.FromArgb(229, 236, 246);
        row.Cells["File"].Style.Font = _normalFileFont;
        row.Cells["File"].ToolTipText = lane.LastFile;
        row.Cells["Size"].Value = lane.Total > 0 ? FormatBytes(lane.Bytes) : "—";
        row.Cells["Progress"].Value = lane.ProgressText;
        row.Cells["Progress"].ToolTipText = $"{lane.Done:N0}/{lane.Total:N0} ไฟล์";
        row.Cells["Speed"].Value = lane.Rate > 0 ? FormatBytes((long)lane.Rate) + "/s" : "—";
        row.Cells["ETA"].Value = SyncEta(lane);
        row.Cells["Status"].Value = lane.State;
        row.Cells["Status"].Style.ForeColor = lane.IsComplete ? Color.FromArgb(124, 235, 173) :
            lane.State == "เกิดข้อผิดพลาด" ? Color.FromArgb(255, 166, 166) : Color.FromArgb(215, 225, 238);
        row.Cells["FileType"].Value = "SYNC";
        row.Cells["QueueName"].Value = "Smart Sync";
        row.Cells["Description"].Value = $"{lane.Done:N0}/{lane.Total:N0} ไฟล์";
    }

    private void UpdateSyncPreview(SmartSyncLaneSnapshot lane)
    {
        _previewTitle.Text = SyncName(lane.Upload);
        var statusLines = (_smartSyncWindow?.StatusText ?? "").Split('\n');
        _previewMeta.Text = lane.IsScanning ? statusLines[0] :
            $"ไฟล์สำเร็จ {lane.Done:N0}/{lane.Total:N0} · {FormatBytes(lane.DoneBytes)} / {FormatBytes(lane.Bytes)}";
        _previewState.Text = lane.IsScanning && statusLines.Length > 1 ? statusLines[1] : lane.State;
        _previewState.ForeColor = Accent;
        _previewPath.Text = "ปลายทาง: " + (lane.Upload ? _smartSyncWindow?.DrivePath : _smartSyncWindow?.PcPath);
        _previewUrl.Text = "ล่าสุด: " + (lane.IsScanning && statusLines.Length > 2 ? statusLines[2] : lane.LastFile);
        _previewProgressFraction = lane.Fraction;
        _previewPercent.Text = lane.IsScanning ? "กำลังตรวจสอบ · ยังไม่ทราบจำนวนทั้งหมด" :
            lane.IsComplete && lane.Total == 0 ? "100.0% · ไม่มีไฟล์ใหม่" :
            lane.Total == 0 ? lane.State : $"{lane.Fraction * 100:0.0}% · {lane.Done:N0}/{lane.Total:N0} ไฟล์";
        var diagnostic = _smartSyncWindow?.StatusText + Environment.NewLine + _smartSyncWindow?.ReviewText;
        if (_diagnosticText.Text != diagnostic) _diagnosticText.Text = diagnostic;
        _previewProgressTrack.Invalidate();
    }
    private ToolStripButton? SmartSyncToolbarButton() => _toolbar?.Items.OfType<ToolStripButton>().FirstOrDefault(x => x.Text == "Smart Sync");
    private void RestoreSyncIcon()
    {
        var button = SmartSyncToolbarButton();
        if (button is not null && _syncIdleIcon is not null) button.Image = _syncIdleIcon;
    }
    private void UpdateSyncAnimation()
    {
        if (_smartSyncWindow is null) return;
        var (up, down) = _smartSyncWindow.Lanes.Snapshot();
        bool active = up.IsScanning || down.IsScanning || up.State == "กำลังรับส่ง" || down.State == "กำลังรับส่ง";
        if (active && !_syncAnimation.Enabled)
        {
            _syncAnimation.Start();
            AnimateSmartSync();
        }
        else if (!active && _syncAnimation.Enabled)
        {
            _syncAnimation.Stop();
            RestoreSyncIcon();
        }
    }
    private void AnimateSmartSync()
    {
        if (IsDisposed || _grid.IsDisposed) return;
        var button = SmartSyncToolbarButton();
        if (button is not null && button.Image is not null)
        {
            _syncIdleIcon ??= button.Image;
            if (_syncFrames.Count == 0)
            {
                for (int i = 0; i < 16; i++)
                {
                    var frame = new Bitmap(40, 40);
                    using var g = Graphics.FromImage(frame);
                    g.Clear(Color.Transparent);
                    g.InterpolationMode = InterpolationMode.HighQualityBicubic;
                    g.TranslateTransform(20, 20);
                    g.RotateTransform(i * 22.5f);
                    g.DrawImage(_syncIdleIcon, -20, -20, 40, 40);
                    _syncFrames.Add(frame);
                }
            }
            button.Image = _syncFrames[_syncFrame++ % _syncFrames.Count];
        }
        foreach (DataGridViewRow row in _grid.Rows)
            if (SyncLaneAt(row.Index)?.IsScanning == true)
                _grid.InvalidateCell(_grid.Columns["Progress"].Index, row.Index);
        if (SelectedSyncLane()?.IsScanning == true) _previewProgressTrack.Invalidate();
    }

    private async Task StartSelectedWorkspaceAsync()
    {
        if (SelectedSyncLane() is not null && _smartSyncWindow is not null)
            await _smartSyncWindow.StartFromWorkspaceAsync();
        else SelectedAction(_engine.Start);
    }
    private void PauseSelectedWorkspace()
    {
        if (SelectedSyncLane() is not null) _smartSyncWindow?.RequestStop();
        else SelectedAction(_engine.Pause);
    }
    private void PauseWorkspaceAll()
    {
        _smartSyncWindow?.RequestStop();
        _engine.PauseAll();
    }

    private static string FormatBytes(long count)
    {
        if (count < 0) return "—";
        var units = new[] { "B", "KB", "MB", "GB", "TB" };
        double size = count;
        int unit = 0;
        while (size >= 1024 && unit < units.Length - 1) { size /= 1024; unit++; }
        return size.ToString(unit == 0 ? "0" : "0.0") + " " + units[unit];
    }
}
