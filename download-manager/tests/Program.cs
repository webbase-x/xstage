using System.Drawing;
using System.Reflection;
using System.Windows.Forms;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using XStageDownloadManager;

if (args.Length == 0)
{
    SmartSyncPlannerTests.Run();
    await SmartSyncBackgroundTests.RunAsync();
    await SmartSyncTransferTests.RunAsync();
    await SmartSyncFolderTests.RunAsync();
}

// CI smoke: instantiate and paint the exact desktop UI across window sizes.
// Unlike source-only contracts, this reaches WinForms/GDI+ at runtime and
// catches the "Parameter is not valid" failure in icon or panel painting.
// Run on an isolated Windows CI runner; never import or replace user files.
if (args.Contains("--ui-smoke", StringComparer.Ordinal))
{
    Exception? failure = null;
    var thread = new Thread(() =>
    {
        try
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            using var main = new MainForm(new[] { "--ui-smoke" });
            main.Show();
            // Reference UI contract: preserve the navy/cyan visual identity
            // and the compact menu/deck/status proportions at every DPI.
            var rootField = typeof(MainForm).GetField("_workspaceRoot",
                BindingFlags.NonPublic | BindingFlags.Instance) ??
                throw new Exception("Download workspace root not found.");
            var root = (TableLayoutPanel)(rootField.GetValue(main) ??
                throw new Exception("Download workspace root is null."));
            if (root.RowStyles.Count != 5 ||
                root.RowStyles[0].Height != 48 ||
                root.RowStyles[1].Height != 90 ||
                root.RowStyles[4].Height != 38)
                throw new Exception("Reference menu, command deck or status bar proportions regressed.");
            var accentField = typeof(MainForm).GetField("Accent",
                BindingFlags.NonPublic | BindingFlags.Static) ??
                throw new Exception("Download workspace accent not found.");
            if ((Color)(accentField.GetValue(null) ??
                throw new Exception("Download workspace accent is null.")) !=
                Color.FromArgb(0, 189, 255))
                throw new Exception("Reference cyan accent regressed.");
            var pinnedToolbar = (ToolStrip)(typeof(MainForm).GetField("_toolbar",
                BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(main)!);
            var syncButton = pinnedToolbar.Items.OfType<ToolStripButton>().Single(x => x.Text == "Smart Sync");
            foreach (var (width, height) in new[]
            {
                (880, 590), (1024, 768), (1250, 780), (1366, 768),
                (1920, 1080), (880, 590)
            })
            {
                main.Size = new Size(width, height);
                main.PerformLayout();
                for (var i = 0; i < 3; i++) Application.DoEvents();
                using var target = new Bitmap(width, height);
                main.DrawToBitmap(target, new Rectangle(0, 0, width, height));
                Application.DoEvents();
                if (syncButton.Placement != ToolStripItemPlacement.Main || !syncButton.Available || syncButton.Image is null)
                    throw new Exception($"Smart Sync icon hidden at {width}x{height}");
            }
            // Force native ImageList materialization AFTER construction.
            // Disposing bitmaps immediately after Images.Add previously left
            // deferred GDI+ image sources unusable ("Parameter is not valid").
            var imageField = typeof(MainForm).GetField("_categoryIcons",
                BindingFlags.NonPublic | BindingFlags.Instance) ??
                throw new Exception("Category icon ImageList is missing");
            var imageList = (ImageList)(imageField.GetValue(main) ??
                throw new Exception("Category ImageList is null"));
            if (imageList.Images.Count < 10)
                throw new Exception("Category icon list is unexpectedly empty");
            using (var imageTarget = new Bitmap(50, 50))
            using (var imageGraphics = Graphics.FromImage(imageTarget))
            {
                for (var i = 0; i < imageList.Images.Count; i++)
                    imageList.Draw(imageGraphics, 2, 2, i);
            }
            // Test every custom GDI+ glyph using the same code as menus,
            // category image lists and transfer table image cells.
            var draw = typeof(MainForm).GetMethod("DrawToolbarGlyph",
                BindingFlags.Static | BindingFlags.NonPublic) ??
                throw new Exception("X-Stage vector icon renderer not found.");
            foreach (var glyph in new[]
            {
                "add", "play", "pause", "queue", "gauge", "browser",
                "video", "folder", "refresh", "trash", "check", "alert",
                "eye", "settings", "info", "file", "sync"
            })
            {
                using var rendered = (Image)(draw.Invoke(null, new object[]
                {
                    glyph, Color.FromArgb(45, 207, 176)
                }) ?? throw new Exception("Vector glyph renderer returned null."));
                using var target = new Bitmap(40, 40);
                using var graphics = Graphics.FromImage(target);
                graphics.DrawImage(rendered, 0, 0, 40, 40);
            }
            // Exercise the real toolbar clicks without adding any download.
            var toolbar = (ToolStrip)(typeof(MainForm).GetField("_toolbar",
                BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(main)!);
            var urlInput = (TextBox)(typeof(MainForm).GetField("_url",
                BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(main)!);
            var addButton = toolbar.Items.OfType<ToolStripButton>().Single(x => x.Text == "เพิ่มงาน");
            var videoButton = toolbar.Items.OfType<ToolStripButton>().Single(x => x.Text == "ดาวน์โหลดวิดีโอ");
            urlInput.Text = "https://example.test/draft.zip";
            addButton.PerformClick();
            if (root.RowStyles[2].Height <= 0 || !addButton.Checked)
                throw new Exception("Add toolbar did not open quick entry.");
            addButton.PerformClick();
            if (root.RowStyles[2].Height != 0 || addButton.Checked)
                throw new Exception("Add toolbar did not hide quick entry.");
            videoButton.PerformClick();
            if (root.RowStyles[2].Height != 268 || !videoButton.Checked)
                throw new Exception("Video toolbar did not open video settings.");
            videoButton.PerformClick();
            if (root.RowStyles[2].Height != 0 || videoButton.Checked ||
                urlInput.Text != "https://example.test/draft.zip")
                throw new Exception("Video toggle must hide without deleting draft.");
            addButton.PerformClick();
            videoButton.PerformClick();
            if (!videoButton.Checked || addButton.Checked || root.RowStyles[2].Height != 268)
                throw new Exception("Switching mode must reuse the same visible panel.");
            videoButton.PerformClick();
            syncButton.PerformClick();
            Application.DoEvents();
            var embedded = (SmartSyncForm)typeof(MainForm).GetField("_smartSyncWindow",
                BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(main)!;
            var mainGrid = (DataGridView)typeof(MainForm).GetField("_grid",
                BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(main)!;
            if (embedded.FindForm() != main || !embedded.Visible ||
                mainGrid.Rows.Cast<DataGridViewRow>().Count(row => (row.Tag as string)?.StartsWith("workspace:smart-sync:") == true) != 2)
                throw new Exception("Smart Sync must use two aggregate rows and the main window");
            syncButton.PerformClick();
            if (embedded.Visible || root.RowStyles[2].Height != 0)
                throw new Exception("Smart Sync inline settings must hide without disposal");
            addButton.PerformClick();
            if (!addButton.Checked || embedded.Visible)
                throw new Exception("Quick entry must share the inline host");
            addButton.PerformClick();
            // Recreate the actual Smart Sync window, including a path which
            // does not exist; restore must not launch a scan or transfer.
            var syncSettings = Path.Combine(Path.GetTempPath(), "xstage-sync-ui-" + Guid.NewGuid().ToString("N"));
            try
            {
                var file = Path.Combine(syncSettings, "preferences.json");
                var saved = new SmartSyncPreferences(Path.Combine(syncSettings, "PC"),
                    Path.Combine(syncSettings, "Drive"), SmartSyncDirection.ToPc, true);
                SmartSyncPreferencesStore.Save(file, saved);
                using (var sync = new SmartSyncForm(file))
                {
                    T Field<T>(string name) => (T)typeof(SmartSyncForm).GetField(name,
                        BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(sync)!;
                    if (Field<TextBox>("_pc").Text != saved.Pc || Field<TextBox>("_drive").Text != saved.Drive ||
                        Field<ComboBox>("_direction").SelectedIndex != (int)saved.Direction ||
                        !Field<CheckBox>("_background").Checked || sync.IsBusy || !Field<Button>("_sync").Enabled || Field<Button>("_sync").Text != "Sync" ||
                        Field<ComboBox>("_mode").SelectedIndex != (int)SmartSyncMode.Fast ||
                        Field<NumericUpDown>("_parallel").Value != 8 ||
                        Field<TextBox>("_pc").BackColor != MainForm.DarkGrid)
                        throw new Exception("Smart Sync UI failed to restore saved settings safely");
                    Field<ComboBox>("_direction").SelectedIndex = (int)SmartSyncDirection.ToDrive;
                    Field<CheckBox>("_background").Checked = false;
                }
                using (var reopened = new SmartSyncForm(file))
                {
                    var expected = saved with { Direction = SmartSyncDirection.ToDrive, Background = false };
                    if (SmartSyncPreferencesStore.Load(file) != expected || reopened.IsBusy)
                        throw new Exception("Smart Sync UI changes were not persisted");
                }
                // Test the actual one-click session using local temporary
                // directories and an isolated receipt database.
                Directory.CreateDirectory(saved.Pc);
                Directory.CreateDirectory(saved.Drive);
                File.WriteAllText(Path.Combine(saved.Pc, "00001.xmid"), "PC");
                File.WriteAllText(Path.Combine(saved.Drive, "00002.xmid"), "Drive");
                SmartSyncPreferencesStore.Save(file, saved with { Direction = SmartSyncDirection.Both, Background = false });
                using (var oneClick = new SmartSyncForm(file, Path.Combine(syncSettings, "receipts.sqlite3")))
                {
                    int starts = 0;
                    oneClick.WorkspaceStarted += () =>
                    {
                        starts++;
                        if (!oneClick.IsBusy || !oneClick.Lanes.Snapshot().Upload.IsScanning)
                            throw new Exception("Sync must enter scanning before the workspace hides");
                    };
                    var work = oneClick.StartFromWorkspaceAsync();
                    var watch = System.Diagnostics.Stopwatch.StartNew();
                    while (!work.IsCompleted && watch.Elapsed < TimeSpan.FromSeconds(30))
                    { Application.DoEvents(); Thread.Sleep(10); }
                    if (!work.IsCompleted) throw new Exception("One-click Sync timed out");
                    work.GetAwaiter().GetResult();
                    var (up, down) = oneClick.Lanes.Snapshot();
                    if (starts != 1 || oneClick.IsBusy || up.Done != 1 || down.Done != 1 ||
                        !File.Exists(Path.Combine(saved.Drive, "00001.xmid")) ||
                        !File.Exists(Path.Combine(saved.Pc, "00002.xmid")))
                        throw new Exception("One-click Sync must scan and transfer both directions without a second click");
                }
            }
            finally { if (Directory.Exists(syncSettings)) Directory.Delete(syncSettings, true); }
            // Both real update windows render without initiating network or
            // install actions. Test shared center and clamping separately.
            using (var download = new UpdateDownloadForm(
                new DownloadManagerRelease("0.2.26", 29, "setup.exe", "https://example.test", new string('a',64), 1024), ""))
            {
                download.CreateControl();
                using var snapshot = new Bitmap(download.Width, download.Height);
                download.DrawToBitmap(snapshot, new Rectangle(0, 0, snapshot.Width, snapshot.Height));
                if (download.Controls.OfType<ProgressBar>().Count() != 1 ||
                    !download.Controls.OfType<Button>().Any(x => x.Text == "อัปเดต"))
                    throw new Exception("First update window missing download/consent controls.");
                var area = Screen.PrimaryScreen!.WorkingArea;
                var center = new Point(area.Left + area.Width / 2, area.Top + area.Height / 2);
                var position = UpdateTransitionForm.CenterOnWorkingArea(center, download.Size);
                if (position.X != center.X - download.Width / 2 || position.Y != center.Y - download.Height / 2)
                    throw new Exception("Update window center handoff regressed.");
            }
            // Instantiate the actual detached updater UI without showing it:
            // painting must not launch installation or signal a real handshake.
            using (var transition = new UpdateTransitionForm(new[] {
                "--apply-verified-update", "1", "setup.exe", "old.exe",
                new string('a', 64), "1024", "0.2.25", "28", "test-only" }))
            {
                transition.CreateControl();
                transition.PerformLayout();
                using var snapshot = new Bitmap(transition.Width, transition.Height);
                transition.DrawToBitmap(snapshot, new Rectangle(0, 0, snapshot.Width, snapshot.Height));
                var bars = transition.Controls.OfType<ProgressBar>().ToArray();
                if (bars.Length != 1 || !transition.Controls.OfType<Label>().Any(x => x.Text.Contains("ขั้นที่ 1/6")))
                    throw new Exception("Single updater progress window did not render its first stage.");
            }
            main.Close();
        }
        catch (Exception error) { failure = error; }
    }) { IsBackground = true };
    thread.SetApartmentState(ApartmentState.STA);
    thread.Start();
    if (!thread.Join(TimeSpan.FromSeconds(45)))
        throw new Exception("WinForms/GDI+ UI smoke timed out after 45 seconds.");
    if (failure is not null)
        throw new Exception("X-Stage desktop UI render smoke failed: " +
            failure, failure);
    Console.WriteLine("PASS: WinForms desktop, six viewport changes, live ImageList handle and 16 vector glyphs render without GDI+ errors");
    return;
}

// Real FFmpeg/FFprobe integration: invoked after pinned tools are downloaded
// in GitHub Actions. Synthetic video only, never a copyrighted user clip.
if (args.Length >= 3 && args[0] == "--media-smoke")
{
    var input = args[1];
    var tools = args[2];
    var work = Path.Combine(Path.GetTempPath(), "xstage-media-smoke-" + Guid.NewGuid().ToString("N"));
    Directory.CreateDirectory(work);
    try
    {
        var source = await MediaIntegrity.VerifyAsync(input,
            Path.Combine(tools, "ffprobe.exe"), false, CancellationToken.None);
        if (!source.HasVideo || !source.HasAudio)
            throw new Exception("Synthetic media source must have both video and audio.");
        var converted = await MediaIntegrity.FinishMp4Async(input, work, work, tools,
            CancellationToken.None);
        var output = await MediaIntegrity.VerifyAsync(converted,
            Path.Combine(tools, "ffprobe.exe"), false, CancellationToken.None);
        if (!output.HasVideo || !output.HasAudio ||
            output.VideoCodec != "h264" || output.AudioCodec != "aac" ||
            !MediaIntegrity.HasCompleteMp4Boxes(converted))
            throw new Exception("Real-world FFmpeg MP4 conversion/validation failed.");
        Console.WriteLine("PASS: synthetic MKV -> verified H264/AAC MP4 with moov and nonzero duration.");
    }
    finally { Directory.Delete(work, true); }
    return;
}

// Background recorder only recognizes genuinely active public media manifests.
// A master playlist, finished VOD or upcoming platform video is NOT "live".
var hlsActive = "#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXT-X-MEDIA-SEQUENCE:10\n#EXTINF:4.0,\npart10.ts\n";
var hlsFinished = hlsActive + "#EXT-X-ENDLIST\n";
var hlsMaster = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=350000\nvariant.m3u8\n";
var selectedVariant = LiveBackgroundMonitor.SelectHlsVariant(
    new Uri("https://example.net/streams/master.m3u8"), hlsMaster);
if (selectedVariant?.AbsoluteUri != "https://example.net/streams/variant.m3u8" ||
    LiveBackgroundMonitor.SelectHlsVariant(
        new Uri("https://example.net/master.m3u8"), hlsActive) is not null ||
    LiveBackgroundMonitor.SelectHlsVariant(
        new Uri("https://example.net/master.m3u8"),
        "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100000\nfile:///C:/secret.m3u8") is not null)
    throw new Exception("HLS master variant resolution must be safe and preserve relative paths.");

if (!LiveBackgroundMonitor.IsActiveHlsManifest(hlsActive) ||
    LiveBackgroundMonitor.IsActiveHlsManifest(hlsFinished) ||
    LiveBackgroundMonitor.IsActiveHlsManifest(hlsMaster) ||
    LiveBackgroundMonitor.IsActiveHlsManifest("#EXTM3U\n#EXTINF:4,\nvideo.mp4") ||
    !LiveBackgroundMonitor.IsActiveDashManifest(
        "<?xml version=\"1.0\"?><MPD xmlns=\"urn:mpeg:dash:schema:mpd:2011\" type=\"dynamic\"></MPD>") ||
    LiveBackgroundMonitor.IsActiveDashManifest("<MPD type=\"static\"></MPD>") ||
    LiveBackgroundMonitor.IsActiveDashManifest("this is not an MPD") ||
    !LiveBackgroundMonitor.IsActivePlatformStatus("is_live") ||
    LiveBackgroundMonitor.IsActivePlatformStatus("is_upcoming") ||
    LiveBackgroundMonitor.IsActivePlatformStatus("was_live") ||
    LiveBackgroundMonitor.IsActivePlatformStatus(null))
    throw new Exception("Live monitor classified VOD/upcoming/master as actively broadcasting.");

var monitorArgs = LiveBackgroundMonitor.BuildPlatformStatusArguments(
    "https://www.youtube.com/live/demo123", @"C:\tools");
if (!monitorArgs.Contains("--no-plugin-dirs") ||
    !monitorArgs.Contains("--ignore-config") ||
    !monitorArgs.Contains("--skip-download") ||
    !monitorArgs.Contains("xstage-live-status:%(live_status)s") ||
    monitorArgs.Last() != "https://www.youtube.com/live/demo123")
    throw new Exception("Public live-status polling must be metadata-only with safe extractor options.");
var rejectPrivateMonitor = false;
try
{
    LiveBackgroundMonitor.BuildPlatformStatusArguments(
        "https://example.net/file.m3u8", @"C:\tools");
}
catch (ArgumentException) { rejectPrivateMonitor = true; }
if (!rejectPrivateMonitor)
    throw new Exception("Platform-specific monitor must reject arbitrary non-platform endpoints.");

using (var alreadyCancelled = new CancellationTokenSource())
{
    alreadyCancelled.Cancel();
    var cancelled = false;
    try
    {
        await new LiveBackgroundMonitor().WaitForLiveAsync(
            "https://example.net/stream.m3u8", 30, null, alreadyCancelled.Token);
    }
    catch (OperationCanceledException) { cancelled = true; }
    if (!cancelled)
        throw new Exception("Background monitoring must stop before any network traffic on cancel.");
}
var invalidPoll = false;
try
{
    await new LiveBackgroundMonitor().WaitForLiveAsync(
        "https://example.net/stream.m3u8", 1, null);
}
catch (ArgumentOutOfRangeException) { invalidPoll = true; }
if (!invalidPoll)
    throw new Exception("Live monitor polling must prevent excessive network requests.");

Console.WriteLine("PASS: live background metadata, manifest classification, cancellation and bounded polling.");

// Live capture: route only supported public sources into the opt-in recorder.
// A querystring does not change the HLS/DASH pathname classification.
if (!LiveStreamCapture.IsSupportedSource("https://video.example/live/master.m3u8?token=abc") ||
    !LiveStreamCapture.IsSupportedSource("https://cdn.example/dash/live.mpd") ||
    !LiveStreamCapture.IsSupportedSource("https://www.youtube.com/live/test123") ||
    LiveStreamCapture.IsSupportedSource("https://example.org/song.mp3") ||
    LiveStreamCapture.IsSupportedSource("https://example.org/master.m3u8.evil") ||
    LiveStreamCapture.IsSupportedSource("file:///C:/secret/master.m3u8") ||
    LiveStreamCapture.IsSupportedSource("https://user:pass@example.org/live.m3u8"))
    throw new Exception("Live capture URL classifier must accept only authorized-format HTTP(S) inputs.");

var liveArgs = LiveStreamCapture.BuildCaptureArguments(
    "https://video.example/stream.m3u8?token=abc", @"C:\Temp\safe recording.mkv");
if (!liveArgs.SequenceEqual(new[]
{
    "-hide_banner", "-nostats", "-loglevel", "warning",
    "-rw_timeout", "15000000", "-i",
    "https://video.example/stream.m3u8?token=abc",
    "-map", "0:v:0?", "-map", "0:a:0?",
    "-c", "copy", "-f", "matroska", "-y", @"C:\Temp\safe recording.mkv"
}))
    throw new Exception("Live FFmpeg arguments must preserve URL/path as separate argument tokens.");

var rejectedLiveInput = false;
try { LiveStreamCapture.BuildCaptureArguments("https://example.org/installer.exe", "test.mkv"); }
catch (ArgumentException) { rejectedLiveInput = true; }
if (!rejectedLiveInput)
    throw new Exception("Unknown file URLs must not be treated as live streams.");

var pauses = LiveSpeechSegmentPlanner.ParseSilenceLog(
    "[silencedetect] silence_start: 292.0\n" +
    "[silencedetect] silence_end: 293.2 | silence_duration: 1.2\n" +
    "[silencedetect] silence_start: 591.0\n" +
    "[silencedetect] silence_end: 592.0 | silence_duration: 1.0\n" +
    "[silencedetect] silence_start: 610\n" +
    "[silencedetect] silence_end: 610.1 | silence_duration: 0.1\n");
if (pauses.Count != 2 ||
    Math.Abs(pauses[0].Start - 292) > .001 ||
    Math.Abs(pauses[1].End - 592) > .001)
    throw new Exception("Silence parser should read valid FFmpeg silence intervals.");

var clips = LiveSpeechSegmentPlanner.Plan(630, 300, pauses);
if (clips.Count != 3 ||
    Math.Abs(clips[0].End - 292.6) > .05 ||
    Math.Abs(clips[1].Start - clips[0].End) > .000001 ||
    Math.Abs(clips[1].End - 591.5) > .05 ||
    Math.Abs(clips[2].Start - clips[1].End) > .000001 ||
    Math.Abs(clips[2].End - 630) > .000001)
    throw new Exception("Live clip planner must split near requested time ONLY at detected pauses.");

var uninterrupted = LiveSpeechSegmentPlanner.Plan(600, 60,
    Array.Empty<LiveSilence>());
if (uninterrupted.Count != 1 || uninterrupted[0] != (0d, 600d))
    throw new Exception("Speech-safe planner must never force a clock-only cut.");

var earlyPause = LiveSpeechSegmentPlanner.Plan(180, 60,
    new[] { new LiveSilence(6, 8) });
if (earlyPause.Count != 1)
    throw new Exception("An unrelated early silence must not trigger arbitrary cuts.");

var extendedSpeech = LiveSpeechSegmentPlanner.Plan(550, 60,
    new[] { new LiveSilence(440, 442) });
if (extendedSpeech.Count != 2 || extendedSpeech[0].End < 440)
    throw new Exception("The safe clip boundary must extend beyond the target when speech continues.");

var invalidLiveMinutes = false;
try { LiveSpeechSegmentPlanner.Plan(100, 45, pauses); }
catch (ArgumentOutOfRangeException) { invalidLiveMinutes = true; }
if (!invalidLiveMinutes)
    throw new Exception("Clip lengths below one minute are unsupported.");

Console.WriteLine("PASS: live URL/FFmpeg argument contracts, pause detection and no mid-speech clock cuts.");

// Windows device names remain reserved even when an extension is present.
foreach (var device in new[] { "CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
             "COM1", "COM4", "COM9", "LPT1", "LPT4", "LPT9" })
{
    var cleaned = DownloadFileNaming.CleanName(device.ToLowerInvariant() + ".txt");
    if (cleaned != "_" + device.ToLowerInvariant() + ".txt")
        throw new Exception("Reserved Windows filename was not sanitized: " + device);
}
if (DownloadFileNaming.CleanName("company.txt") != "company.txt" ||
    DownloadFileNaming.CleanName("LPT10.txt") != "LPT10.txt")
    throw new Exception("Filename sanitization must not rename ordinary files.");

// A pre-existing directory with the same name is also a collision on Windows.
var collisionRoot = Path.Combine(Path.GetTempPath(), "xstage-dm-name-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(collisionRoot);
try
{
    Directory.CreateDirectory(Path.Combine(collisionRoot, "archive.zip"));
    File.WriteAllText(Path.Combine(collisionRoot, "archive (1).zip"), "existing");
    var unique = DownloadFileNaming.UniqueOutput(collisionRoot, "archive.zip");
    if (Path.GetFileName(unique) != "archive (2).zip")
        throw new Exception("UniqueOutput must skip existing directories and files.");
}
finally { Directory.Delete(collisionRoot, true); }

var bytes = new byte[9 * 1024 * 1024];
for (int i = 0; i < bytes.Length; i++) bytes[i] = (byte)(i % 251);
using var server = new FileServer(bytes);
var folder = Path.Combine(Path.GetTempPath(), "xstage-dm-test-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(folder);
try
{
    // Crash recovery must distinguish interrupted jobs from intentional pauses.
    // Rejecting the consent prompt leaves bytes and user history untouched.
    var recoveryFolder = Path.Combine(folder, "recovery-intent");
    Directory.CreateDirectory(recoveryFolder);
    var recoveryState = new DownloadStateStore(recoveryFolder);
    recoveryState.SaveSnapshot(new[]
    {
        new DownloadJob { Id = "unexpected", Url = server.Url + "range/crash.bin",
            Folder = folder, Status = "Running" },
        new DownloadJob { Id = "shutdown", Url = server.Url + "range/shutdown.bin",
            Folder = folder, Status = "Paused", ResumeAfterRestart = true },
        new DownloadJob { Id = "user-paused", Url = server.Url + "range/user.bin",
            Folder = folder, Status = "Paused" },
        new DownloadJob { Id = "network", Url = server.Url + "range/network.bin",
            Folder = folder, Status = "Paused", ResumeWhenNetworkReturns = true },
        new DownloadJob { Id = "finished", Url = server.Url + "range/finished.bin",
            Folder = folder, Status = "Completed" }
    });
    var recovered = new DownloadEngine(recoveryFolder);
    if (recovered.InterruptedJobCount != 3 ||
        recovered.Jobs.Single(j => j.Id == "user-paused").InterruptedOnStartup ||
        recovered.Jobs.Single(j => j.Id == "finished").InterruptedOnStartup)
        throw new Exception("Startup recovery incorrectly selected user-paused/completed jobs.");
    recovered.RecoverInterruptedJobs(false);
    if (recovered.InterruptedJobCount != 0 ||
        recovered.Jobs.Any(j => j.Status == "Running" || j.Status == "Queued") ||
        recovered.Jobs.Any(j => j.ResumeAfterRestart))
        throw new Exception("Declining recovery must retain jobs paused with no implicit restart.");
    var reopen = new DownloadEngine(recoveryFolder);
    if (reopen.InterruptedJobCount != 0 || reopen.Jobs.Count != 5)
        throw new Exception("Recovery consent and download history must persist across restarts.");

    // The UI must preserve the recovery prompt across repeated crashes before consent.
    recoveryState.SaveSnapshot(new[]
    {
        new DownloadJob { Id = "crash-before-consent", Url = server.Url + "range/retry.bin",
            Folder = folder, Status = "Running" }
    });
    var firstBoot = new DownloadEngine(recoveryFolder);
    if (firstBoot.InterruptedJobCount != 1)
        throw new Exception("First launch must offer recovery for interrupted transfer.");
    var secondBoot = new DownloadEngine(recoveryFolder);
    if (secondBoot.InterruptedJobCount != 1)
        throw new Exception("Restart before recovery consent must not erase recovery intent.");
    secondBoot.RecoverInterruptedJobs(false);
    var pausedFromNetwork = secondBoot.Jobs.Single();
    pausedFromNetwork.ResumeWhenNetworkReturns = true;
    secondBoot.Save();
    secondBoot.Pause(pausedFromNetwork);
    secondBoot.TryResumeNetworkInterrupted();
    if (pausedFromNetwork.Status != "Paused" || pausedFromNetwork.ResumeWhenNetworkReturns)
        throw new Exception("Explicit Pause must cancel network auto-resume.");

    // Persist a 32-range near-long.MaxValue checkpoint: SQLite boundaries
    // must not overflow even when no physical .part files exist yet.
    var hugeStateFolder = Path.Combine(folder, "huge-range-checkpoint");
    var hugeState = new DownloadStateStore(hugeStateFolder);
    hugeState.SaveSnapshot(new[]
    {
        new DownloadJob { Id = "huge", Url = server.Url + "range/huge.bin",
            Folder = folder, Kind = "File", Status = "Paused",
            TotalBytes = long.MaxValue, SupportsRanges = true, SegmentsUsed = 32,
            SegmentDownloadedBytes = new long[32] }
    });
    if (hugeState.Inspect().Chunks != 32)
        throw new Exception("Large-file SQLite checkpoint lost segment rows.");
    using (var db = new Microsoft.Data.Sqlite.SqliteConnection(
        "Data Source=" + hugeState.DatabasePath))
    {
        db.Open();
        using var cmd = db.CreateCommand();
        cmd.CommandText = "SELECT chunk_index,from_byte,to_byte FROM xstage_download_chunks ORDER BY chunk_index";
        using var reader = cmd.ExecuteReader();
        long previousEnd = -1;
        var rows = 0;
        while (reader.Read())
        {
            var index = reader.GetInt32(0);
            var start = reader.GetInt64(1);
            var end = reader.GetInt64(2);
            if (index != rows || start != previousEnd + 1 || end < start ||
                end != TransferSegmentGeometry.Boundary(long.MaxValue, index + 1, 32) - 1)
                throw new Exception("SQLite checkpoint has overflowed or discontinuous Range offsets.");
            previousEnd = end;
            rows++;
        }
        if (rows != 32 || previousEnd != long.MaxValue - 1)
            throw new Exception("SQLite Range checkpoint did not cover the entire large file.");
    }

    // Simulated SQLite write failure: no orphaned transfer may start and no
    // unpersisted job may remain visible in the in-memory queue.
    var rejectedFolder = Path.Combine(folder, "rejected-new-job");
    var rejectedEngine = new DownloadEngine(rejectedFolder);
    using (var db = new Microsoft.Data.Sqlite.SqliteConnection(
        "Data Source=" + rejectedEngine.DatabasePath))
    {
        db.Open();
        using var cmd = db.CreateCommand();
        cmd.CommandText = "CREATE TRIGGER reject_new_job BEFORE INSERT ON xstage_download_jobs BEGIN SELECT RAISE(ABORT, 'simulated disk write failure'); END;";
        cmd.ExecuteNonQuery();
    }
    var originalCount = rejectedEngine.Jobs.Count;
    try
    {
        rejectedEngine.Add(server.Url + "range/must-not-start.bin", folder);
        throw new Exception("An unpersisted download was allowed to start.");
    }
    catch (IOException) { }
    if (rejectedEngine.Jobs.Count != originalCount ||
        rejectedEngine.Jobs.Any(j => j.Url.Contains("must-not-start.bin")))
        throw new Exception("Failed SQLite insert left a phantom download job.");

    // Simulate a full SQLite checkpoint rejection while restarting a known
    // paused job. The worker must not start or alter its recovery intent.
    var restartFolder = Path.Combine(folder, "failed-start-checkpoint");
    var restartState = new DownloadStateStore(restartFolder);
    restartState.SaveSnapshot(new[]
    {
        new DownloadJob { Id = "restart-checkpoint",
            Url = server.Url + "range/restart-checkpoint.bin",
            Folder = folder, Status = "Paused", ResumeAfterRestart = true,
            Error = "previous error" }
    });
    var restartEngine = new DownloadEngine(restartFolder);
    var restartJob = restartEngine.Jobs.Single();
    using (var db = new Microsoft.Data.Sqlite.SqliteConnection(
        "Data Source=" + restartEngine.DatabasePath))
    {
        db.Open();
        using var cmd = db.CreateCommand();
        cmd.CommandText = "CREATE TRIGGER reject_restart BEFORE INSERT ON xstage_download_jobs BEGIN SELECT RAISE(ABORT, 'simulated checkpoint failure'); END;";
        cmd.ExecuteNonQuery();
    }
    try
    {
        restartEngine.Start(restartJob);
        throw new Exception("A restart was allowed despite failed SQLite checkpoint.");
    }
    catch (IOException) { }
    if (restartJob.Status != "Paused" || !restartJob.ResumeAfterRestart ||
        restartJob.Cancellation != null || restartJob.Error != "previous error")
        throw new Exception("Failed restart checkpoint altered existing job or recovery intent.");
    if (File.Exists(Path.Combine(folder, "restart-checkpoint.bin")))
        throw new Exception("Failed restart checkpoint unexpectedly created output.");

    // A detached job object must never bypass SQLite registration and start
    // writing output files. Simulate a caller retaining an obsolete job object.
    var untracked = new DownloadJob { Id = "detached",
        Url = server.Url + "range/untracked.bin", Folder = folder, Status = "Paused" };
    try
    {
        rejectedEngine.Start(untracked);
        throw new Exception("Untracked download was accepted.");
    }
    catch (ArgumentException) { }
    if (untracked.Status != "Paused" || untracked.Cancellation is not null ||
        rejectedEngine.Jobs.Any(j => j.Id == "detached"))
        throw new Exception("Rejected untracked job changed state or history.");

    // Scheduler: high-priority jobs overtake low priority without changing
    // persistence order; live reprioritization and cancellation release slots.
    // Invalid per-host limits must identify the correct settings field and
    // leave the active scheduler configuration untouched.
    var validationQueue = new TransferSlotQueue(2, 2);
    foreach (var invalidHostLimit in new[] { 0, 9 })
    {
        try
        {
            validationQueue.Configure(2, invalidHostLimit);
            throw new Exception("Invalid per-host concurrency was accepted.");
        }
        catch (ArgumentOutOfRangeException error) when (error.ParamName == "maxPerHost") { }
    }
    if (validationQueue.MaxConcurrent != 2 || validationQueue.MaxPerHost != 2)
        throw new Exception("Rejected per-host setting mutated the live scheduler.");
    try
    {
        validationQueue.Configure(0, 2);
        throw new Exception("Invalid global concurrency was accepted.");
    }
    catch (ArgumentOutOfRangeException error) when (error.ParamName == "maxConcurrent") { }

    var scheduler = new TransferSlotQueue(1, 1);
    using (var blocker = await scheduler.EnterAsync("block", "example.test", 1, CancellationToken.None))
    {
        var lowTask = scheduler.EnterAsync("low", "example.test", 2, CancellationToken.None);
        var highTask = scheduler.EnterAsync("high", "example.test", 0, CancellationToken.None);
        if (scheduler.ActiveCount != 1 || scheduler.WaitingCount != 2)
            throw new Exception("Transfer slot queue must enforce global concurrency.");
        blocker.Dispose();
        using var high = await highTask.WaitAsync(TimeSpan.FromSeconds(3));
        if (lowTask.IsCompleted)
            throw new Exception("High-priority job must run before waiting low-priority job.");
        high.Dispose();
        using var low = await lowTask.WaitAsync(TimeSpan.FromSeconds(3));
    }
    // Reprioritizing a waiting transfer must take effect immediately without
    // changing the persisted queue order or preempting an active transfer.
    var priorityQueue = new TransferSlotQueue(1, 1);
    using (var running = await priorityQueue.EnterAsync("running", "priority.test", 1, CancellationToken.None))
    {
        var older = priorityQueue.EnterAsync("older", "priority.test", 1, CancellationToken.None);
        var promoted = priorityQueue.EnterAsync("promoted", "priority.test", 2, CancellationToken.None);
        priorityQueue.Reprioritize("promoted", 0);
        if (older.IsCompleted || promoted.IsCompleted)
            throw new Exception("Reprioritization must not preempt the running transfer.");
        running.Dispose();
        using (var first = await promoted.WaitAsync(TimeSpan.FromSeconds(3)))
        {
            if (older.IsCompleted)
                throw new Exception("Live priority change did not reorder pending dispatch.");
        }
        using var last = await older.WaitAsync(TimeSpan.FromSeconds(3));
    }
    if (priorityQueue.ActiveCount != 0 || priorityQueue.WaitingCount != 0)
        throw new Exception("Reprioritized transfers leaked scheduler slots.");

    scheduler.Configure(2, 1);
    using (var slotA = await scheduler.EnterAsync("one", "first.test", 1, CancellationToken.None))
    {
        var sameHost = scheduler.EnterAsync("two", "first.test", 1, CancellationToken.None);
        using var otherHost =
            await scheduler.EnterAsync("three", "other.test", 1, CancellationToken.None);
        if (sameHost.IsCompleted || scheduler.ActiveCount != 2)
            throw new Exception("Per-host limit must allow another domain without oversubscription.");
        slotA.Dispose();
        using var second = await sameHost.WaitAsync(TimeSpan.FromSeconds(3));
    }
    // Whitespace and casing must not bypass the per-host connection cap.
    var normalizedHosts = new TransferSlotQueue(2, 1);
    using (var firstHost = await normalizedHosts.EnterAsync("host-a", " Example.TEST ", 1, CancellationToken.None))
    {
        var sameHost = normalizedHosts.EnterAsync("host-b", "example.test", 1, CancellationToken.None);
        using var otherHost = await normalizedHosts.EnterAsync("host-c", "different.test", 1, CancellationToken.None);
        if (sameHost.IsCompleted || normalizedHosts.ActiveCount != 2)
            throw new Exception("Equivalent host names bypassed the per-host transfer limit.");
        firstHost.Dispose();
        using var resumed = await sameHost.WaitAsync(TimeSpan.FromSeconds(3));
    }
    if (normalizedHosts.ActiveCount != 0 || normalizedHosts.WaitingCount != 0)
        throw new Exception("Normalized host slots were not released.");

    scheduler.Configure(1, 1);
    using (var slot = await scheduler.EnterAsync("hold", "sample.test", 1, CancellationToken.None))
    {
        using var stopped = new CancellationTokenSource();
        var canceled = scheduler.EnterAsync("cancel-me", "sample.test", 1, stopped.Token);
        stopped.Cancel();
        try
        {
            await canceled;
            throw new Exception("A canceled pending download must not acquire a slot.");
        }
        catch (OperationCanceledException) { }
        if (scheduler.WaitingCount != 0)
            throw new Exception("Canceled queue entries must be removed promptly.");
    }
    // Invalid and pre-canceled requests must never enter the scheduler or
    // consume capacity. This protects recovery paths that retry canceled jobs.
    var admission = new TransferSlotQueue(1, 1);
    using (var preCanceled = new CancellationTokenSource())
    {
        preCanceled.Cancel();
        try
        {
            using var unexpected = await admission.EnterAsync(
                "already-stopped", "safe.test", 1, preCanceled.Token);
            throw new Exception("A pre-canceled transfer acquired a slot.");
        }
        catch (OperationCanceledException) { }
    }
    try
    {
        using var unexpected = await admission.EnterAsync(
            "invalid-priority", "safe.test", 3, CancellationToken.None);
        throw new Exception("Invalid priority entered the scheduler.");
    }
    catch (ArgumentOutOfRangeException) { }
    try
    {
        using var unexpected = await admission.EnterAsync(
            "invalid-host", "  ", 1, CancellationToken.None);
        throw new Exception("A blank host entered the scheduler.");
    }
    catch (ArgumentException) { }
    if (admission.ActiveCount != 0 || admission.WaitingCount != 0)
        throw new Exception("Rejected scheduler admissions leaked slots.");
    using (var accepted = await admission.EnterAsync(
        "valid-after-rejections", "safe.test", 1, CancellationToken.None))
    {
        if (admission.ActiveCount != 1 || admission.WaitingCount != 0)
            throw new Exception("Rejected admissions prevented a valid transfer.");
    }
    if (admission.ActiveCount != 0)
        throw new Exception("Scheduler did not release the post-rejection lease.");

    // Reducing limits must not revoke active leases or dispatch queued work
    // until capacity is genuinely available. Increasing limits should wake it.
    var resizing = new TransferSlotQueue(2, 2);
    using (var first = await resizing.EnterAsync("resize-a", "one.test", 1, CancellationToken.None))
    using (var second = await resizing.EnterAsync("resize-b", "two.test", 1, CancellationToken.None))
    {
        resizing.Configure(1, 1);
        var pending = resizing.EnterAsync("resize-c", "three.test", 1, CancellationToken.None);
        first.Dispose();
        if (pending.IsCompleted || resizing.ActiveCount != 1)
            throw new Exception("Reduced concurrency must not oversubscribe active leases.");
        resizing.Configure(2, 1);
        using var promoted = await pending.WaitAsync(TimeSpan.FromSeconds(3));
        if (resizing.ActiveCount != 2)
            throw new Exception("Increasing concurrency must dispatch a waiting host.");
    }
    if (resizing.ActiveCount != 0 || resizing.WaitingCount != 0)
        throw new Exception("Repeated lease disposal must not leak scheduler slots.");

    // A saturated host must not head-of-line block a different host even
    // when its queued transfer has higher priority. This is important when
    // 32 Range workers contend with independent downloads.
    var independentHosts = new TransferSlotQueue(2, 1);
    using (var first = await independentHosts.EnterAsync(
        "host-one-active", "one.test", 1, CancellationToken.None))
    {
        var blocked = independentHosts.EnterAsync(
            "host-one-blocked", "one.test", 0, CancellationToken.None);
        using (var second = await independentHosts.EnterAsync(
            "host-two-active", "two.test", 2, CancellationToken.None)
            .WaitAsync(TimeSpan.FromSeconds(3)))
        {
            if (blocked.IsCompleted || independentHosts.ActiveCount != 2 ||
                independentHosts.WaitingCount != 1)
                throw new Exception("Saturated host blocked independent host admission.");
        }
        if (blocked.IsCompleted || independentHosts.ActiveCount != 1)
            throw new Exception("Host limit was bypassed after another host exited.");
        first.Dispose();
        using var resumed = await blocked.WaitAsync(TimeSpan.FromSeconds(3));
    }
    if (independentHosts.ActiveCount != 0 || independentHosts.WaitingCount != 0)
        throw new Exception("Cross-host backpressure leaked a transfer slot.");

    // Host buckets are case-insensitive and trim whitespace. A cancelled
    // waiter must not consume a slot or prevent another host from running.
    var cancellableNormalizedHosts = new TransferSlotQueue(2, 1);
    using (var active = await cancellableNormalizedHosts.EnterAsync(
        "normalized-active", " EXAMPLE.test ", 1, CancellationToken.None))
    {
        using var cancellation = new CancellationTokenSource();
        var blocked = cancellableNormalizedHosts.EnterAsync(
            "normalized-waiter", "example.TEST", 0, cancellation.Token);
        if (blocked.IsCompleted || cancellableNormalizedHosts.WaitingCount != 1)
            throw new Exception("Equivalent host spellings bypassed the host limit.");
        cancellation.Cancel();
        try
        {
            using var unexpected = await blocked.WaitAsync(TimeSpan.FromSeconds(3));
            throw new Exception("Cancelled host waiter unexpectedly acquired a slot.");
        }
        catch (OperationCanceledException) { }
        if (cancellableNormalizedHosts.WaitingCount != 0 || cancellableNormalizedHosts.ActiveCount != 1)
            throw new Exception("Cancelled host waiter leaked scheduler capacity.");
        using var other = await cancellableNormalizedHosts.EnterAsync(
            "normalized-other", "independent.test", 1, CancellationToken.None)
            .WaitAsync(TimeSpan.FromSeconds(3));
        if (cancellableNormalizedHosts.ActiveCount != 2)
            throw new Exception("Cancelled waiter blocked another host.");
    }
    if (cancellableNormalizedHosts.ActiveCount != 0 || cancellableNormalizedHosts.WaitingCount != 0)
        throw new Exception("Normalized host test leaked scheduler slots.");

    // DNS fully-qualified names with a trailing dot refer to the same host.
    // They must share the per-host slot rather than bypass the rate scheduler.
    var fqdnHosts = new TransferSlotQueue(2, 1);
    using (var active = await fqdnHosts.EnterAsync(
        "fqdn-active", "Example.Test.", 1, CancellationToken.None))
    {
        using var cancellation = new CancellationTokenSource();
        var blocked = fqdnHosts.EnterAsync(
            "fqdn-blocked", " example.test ", 1, cancellation.Token);
        if (blocked.IsCompleted || fqdnHosts.WaitingCount != 1)
            throw new Exception("Trailing DNS dot bypassed per-host concurrency.");
        cancellation.Cancel();
        try
        {
            using var unexpected = await blocked.WaitAsync(TimeSpan.FromSeconds(3));
            throw new Exception("Cancelled FQDN waiter acquired a slot.");
        }
        catch (OperationCanceledException) { }
    }
    if (fqdnHosts.ActiveCount != 0 || fqdnHosts.WaitingCount != 0)
        throw new Exception("FQDN normalization leaked scheduler slots.");
    var rejectedEmptyHost = false;
    try
    {
        using var unexpected = await fqdnHosts.EnterAsync(
            "invalid-host", " ... ", 1, CancellationToken.None);
    }
    catch (ArgumentException) { rejectedEmptyHost = true; }
    if (!rejectedEmptyHost)
        throw new Exception("Empty normalized hostname was accepted.");

    // A cancelled waiter from a saturated host must not reserve global capacity
    // after that host releases its active lease. A different host can proceed.
    var cancellationIsolation = new TransferSlotQueue(1, 1);
    using (var active = await cancellationIsolation.EnterAsync(
        "isolation-active", "first.test", 1, CancellationToken.None))
    {
        using var cancel = new CancellationTokenSource();
        var waiting = cancellationIsolation.EnterAsync(
            "isolation-cancelled", "first.test", 1, cancel.Token);
        if (waiting.IsCompleted || cancellationIsolation.WaitingCount != 1)
            throw new Exception("Saturated host waiter must remain queued.");
        cancel.Cancel();
        try
        {
            using var unexpected = await waiting.WaitAsync(TimeSpan.FromSeconds(3));
            throw new Exception("Cancelled saturated-host waiter acquired a lease.");
        }
        catch (OperationCanceledException) { }
    }
    using (var next = await cancellationIsolation.EnterAsync(
        "isolation-next", "second.test", 1, CancellationToken.None)
        .WaitAsync(TimeSpan.FromSeconds(3)))
    {
        if (cancellationIsolation.ActiveCount != 1 || cancellationIsolation.WaitingCount != 0)
            throw new Exception("Cancelled host waiter blocked the next independent host.");
    }
    if (cancellationIsolation.ActiveCount != 0 || cancellationIsolation.WaitingCount != 0)
        throw new Exception("Cancellation isolation leaked scheduler capacity.");

    // Very large resumable files must retain contiguous, overflow-safe byte
    // boundaries, including when the file is smaller than the range count.
    foreach (var size in new long[] { 0, 1, 7, 31, 32, 33, 1025, long.MaxValue })
    foreach (var parts in DownloadEngine.AllowedParts)
    {
        long previous = 0;
        for (var index = 0; index <= parts; index++)
        {
            var boundary = TransferSegmentGeometry.Boundary(size, index, parts);
            if (boundary < previous || boundary > size ||
                (index == 0 && boundary != 0) ||
                (index == parts && boundary != size))
                throw new Exception("Segment geometry overflowed or lost contiguous bytes.");
            previous = boundary;
        }
    }

    // Adaptive recommendations are bounded by requested parts, file size and
    // measured throughput; existing checkpoint geometry is immutable.
    foreach (var parts in DownloadEngine.AllowedParts)
    {
        if (AdaptiveSegmentPlanner.Recommend(parts, 1L << 40, 64 * 1024 * 1024, false) != parts ||
            AdaptiveSegmentPlanner.Recommend(parts, 1L << 40, 64 * 1024 * 1024, true) != parts ||
            AdaptiveSegmentPlanner.Recommend(parts, 1L << 40, double.NaN, false) != parts)
            throw new Exception("Adaptive planner changed user cap or persisted geometry.");
    }
    // Boundary-focused throughput and file-size tests: adaptive limits must
    // never exceed the requested connections or create undersized ranges.
    foreach (var (length, speed, expected) in new (long, double, int)[]
    {
        (2L * 1024 * 1024 - 1, 64d * 1024 * 1024, 1),
        (2L * 1024 * 1024, 64d * 1024 * 1024, 2),
        (8L * 1024 * 1024 - 1, 64d * 1024 * 1024, 2),
        (8L * 1024 * 1024, 64d * 1024 * 1024, 4),
        (512L * 1024 * 1024, 64d * 1024 * 1024, 32),
        (1L << 40, 256d * 1024 - 1, 1),
        (1L << 40, 256d * 1024, 2),
        (1L << 40, 1024d * 1024, 4),
        (1L << 40, 4d * 1024 * 1024, 8),
        (1L << 40, 12d * 1024 * 1024, 16),
        (1L << 40, 32d * 1024 * 1024, 32)
    })
    {
        var actual = AdaptiveSegmentPlanner.Recommend(32, length, speed, false);
        if (actual != expected)
            throw new Exception($"Adaptive boundary mismatch: {length} bytes, {speed} B/s: {actual} != {expected}.");
        if (AdaptiveSegmentPlanner.Recommend(8, length, speed, false) != Math.Min(8, expected))
            throw new Exception("Adaptive boundary exceeded requested connection count.");
        if (AdaptiveSegmentPlanner.Recommend(32, length, speed, true) != 32)
            throw new Exception("Adaptive boundary changed persisted resume segments.");
    }
    // Invalid telemetry and unknown content lengths must not repartition a
    // transfer. In particular, an infinite EWMA sample is not high bandwidth.
    foreach (var parts in DownloadEngine.AllowedParts)
    foreach (var rate in new[] { double.NaN, double.PositiveInfinity,
                                  double.NegativeInfinity, -1d, 0d })
    foreach (var length in new[] { -1L, 0L, 1L << 40 })
    {
        if (AdaptiveSegmentPlanner.Recommend(parts, length, rate, false) != parts ||
            AdaptiveSegmentPlanner.Recommend(parts, length, rate, true) != parts)
            throw new Exception("Invalid throughput telemetry changed persisted or requested segments.");
    }
    foreach (var parts in DownloadEngine.AllowedParts)
    {
        if (AdaptiveSegmentPlanner.Recommend(parts, -1, 64 * 1024 * 1024, false) != parts ||
            AdaptiveSegmentPlanner.Recommend(parts, 0, 64 * 1024 * 1024, false) != parts)
            throw new Exception("Unknown Content-Length must not alter segment geometry.");
    }
    // First transfer has no measured rate: do not silently override a user's
    // requested 1/8/32 connections. On resume, even slow throughput must
    // preserve the existing byte-boundary geometry.
    foreach (var parts in new[] { 1, 8, 32 })
    {
        if (AdaptiveSegmentPlanner.Recommend(parts, 1L << 40, 0, false) != parts ||
            AdaptiveSegmentPlanner.Recommend(parts, 1L << 40, 128 * 1024, true) != parts)
            throw new Exception("Unmeasured or resumed transfer must preserve requested Range geometry.");
    }
    if (AdaptiveSegmentPlanner.Recommend(32, 1024, 64 * 1024 * 1024, false) != 1 ||
        AdaptiveSegmentPlanner.Recommend(32, 1L << 40, 128 * 1024, false) != 1 ||
        AdaptiveSegmentPlanner.Recommend(32, 1L << 40, 2 * 1024 * 1024, false) != 4 ||
        AdaptiveSegmentPlanner.Recommend(32, 1L << 40, 64 * 1024 * 1024, false) != 32)
        throw new Exception("Adaptive segment caps do not reflect size and throughput.");
    try
    {
        AdaptiveSegmentPlanner.Recommend(3, 1L << 40, 64 * 1024 * 1024, false);
        throw new Exception("Unsupported part count must be rejected.");
    }
    catch (ArgumentOutOfRangeException) { }

    // Boundary matrix for adaptive segment sizing: a measured rate must
    // never increase user-selected parallelism or repartition saved chunks.
    // Check exact threshold transitions rather than just representative speeds.
    var mib = 1024L * 1024;
    foreach (var (fileBytes, expected) in new (long Bytes, int Parts)[]
    {
        (2 * mib - 1, 1), (2 * mib, 2),
        (8 * mib - 1, 2), (8 * mib, 4),
        (32 * mib - 1, 4), (32 * mib, 8),
        (128 * mib - 1, 8), (128 * mib, 16),
        (512 * mib - 1, 16), (512 * mib, 32)
    })
    {
        var actual = AdaptiveSegmentPlanner.Recommend(32, fileBytes,
            64 * mib, false);
        if (actual != expected)
            throw new Exception($"Adaptive size boundary {fileBytes}: expected {expected}, got {actual}.");
        if (AdaptiveSegmentPlanner.Recommend(8, fileBytes, 64 * mib, false) >
            8 || AdaptiveSegmentPlanner.Recommend(32, fileBytes, 64 * mib, true) != 32)
            throw new Exception("Adaptive size threshold overrode user or checkpoint geometry.");
    }
    foreach (var (speed, expected) in new (double Speed, int Parts)[]
    {
        (256 * 1024 - 1, 1), (256 * 1024, 2),
        (mib - 1, 2), (mib, 4),
        (4 * mib - 1, 4), (4 * mib, 8),
        (12 * mib - 1, 8), (12 * mib, 16),
        (32 * mib - 1, 16), (32 * mib, 32)
    })
    {
        var actual = AdaptiveSegmentPlanner.Recommend(32, 1L << 40,
            speed, false);
        if (actual != expected)
            throw new Exception($"Adaptive speed boundary {speed}: expected {expected}, got {actual}.");
    }
    foreach (var invalidSpeed in new[] { double.NaN,
        double.PositiveInfinity, double.NegativeInfinity, -1d, 0d })
    {
        if (AdaptiveSegmentPlanner.Recommend(8, 1L << 40, invalidSpeed, false) != 8)
            throw new Exception("Unusable throughput telemetry must preserve user Range geometry.");
    }

    // Increasing measured bandwidth must never reduce parallelism. Conversely,
    // a small user cap must never be exceeded, even at extreme rates. Keep this
    // regression deterministic and independent of Windows network conditions.
    foreach (var requested in DownloadEngine.AllowedParts)
    {
        var previous = 0;
        foreach (var measured in new double[]
        {
            128 * 1024, 256 * 1024, 512 * 1024,
            1024 * 1024, 4 * 1024 * 1024,
            12 * 1024 * 1024, 32 * 1024 * 1024,
            64 * 1024 * 1024
        })
        {
            var chosen = AdaptiveSegmentPlanner.Recommend(
                requested, 1L << 40, measured, false);
            if (chosen < previous || chosen > requested ||
                !DownloadEngine.AllowedParts.Contains(chosen))
                throw new Exception("Adaptive throughput changed non-monotonically or exceeded user cap.");
            previous = chosen;
        }
    }

    // Very large files previously overflowed long when computing size * index.
    // Capped fresh jobs must not create needless sockets. Resume keeps the
    // original geometry even if the user lowers the cap after pausing.
    foreach (var requested in new[] { 1, 8, 32 })
    {
        if (AdaptiveSegmentPlanner.RecommendWithLimits(requested, 1L << 30, 0, false, 64, 0) != 1 ||
            AdaptiveSegmentPlanner.RecommendWithLimits(requested, 1L << 30, 0, false, 0, 128) != 1 ||
            AdaptiveSegmentPlanner.RecommendWithLimits(requested, 1L << 30, 0, true, 64, 64) != requested ||
            AdaptiveSegmentPlanner.RecommendWithLimits(requested, 1L << 30, 0, false, 0, 0) != requested)
            throw new Exception("Adaptive capped fresh geometry or persisted resume geometry regressed.");
    }
    if (AdaptiveSegmentPlanner.RecommendWithLimits(32, 1L << 30, 64d * 1024 * 1024, false, 2048, 128) != 1 ||
        AdaptiveSegmentPlanner.RecommendWithLimits(32, 1L << 30, 128d * 1024, false, 65536, 0) != 1)
        throw new Exception("Adaptive cap must use the tighter of the observed rate and both configured limits.");

    // Verify exact coverage and continuity for 1, 8 and 32 segments.
    foreach (var size in new long[] { 1, 256 * 1024, 1L << 40, long.MaxValue })
    foreach (var count in new[] { 1, 8, 32 })
    {
        long last = 0;
        for (var i = 0; i < count; i++)
        {
            var begin = TransferSegmentGeometry.Boundary(size, i, count);
            var next = TransferSegmentGeometry.Boundary(size, i + 1, count);
            if (begin != last || next < begin || next > size)
                throw new Exception("Large-file Range geometry has a gap, overlap or overflow.");
            last = next;
        }
        if (last != size)
            throw new Exception("Large-file Range geometry did not cover the full file.");
    }
    try
    {
        TransferSegmentGeometry.Boundary(long.MaxValue, 33, 32);
        throw new Exception("Out-of-range segment indices must be rejected.");
    }
    catch (ArgumentOutOfRangeException) { }

    // Verify scheduler backpressure at supported job-slot boundaries (1/8).
    // The 32-range case is tested separately as 32 contending transfers with
    // eight active slots; range segment count is not job concurrency.
    // A blocked waiter must not start early; cancellation must not leak capacity.
    foreach (var capacity in new[] { 1, 8 })
    {
        var queue = new TransferSlotQueue(capacity, capacity);
        var active = new List<IDisposable>();
        for (var i = 0; i < capacity; i++)
            active.Add(await queue.EnterAsync("range-" + capacity + "-" + i,
                "range.test", 1, CancellationToken.None));
        using (var cancellation = new CancellationTokenSource())
        {
            var blocked = queue.EnterAsync("blocked-" + capacity,
                "range.test", 1, cancellation.Token);
            if (blocked.IsCompleted || queue.ActiveCount != capacity || queue.WaitingCount != 1)
                throw new Exception("Backpressure failed at " + capacity + " concurrent ranges.");
            cancellation.Cancel();
            try { using var unexpected = await blocked.WaitAsync(TimeSpan.FromSeconds(3));
                throw new Exception("Canceled range waiter acquired a slot."); }
            catch (OperationCanceledException) { }
            if (queue.WaitingCount != 0 || queue.ActiveCount != capacity)
                throw new Exception("Canceled range waiter leaked scheduler capacity.");
        }
        foreach (var lease in active) lease.Dispose();
        if (queue.ActiveCount != 0 || queue.WaitingCount != 0)
            throw new Exception("Range backpressure leaked leases at " + capacity + ".");
    }

    // Backpressure under 32 contending transfers: only eight may run, and
    // canceled waiters must not consume slots when active transfers finish.
    var saturated = new TransferSlotQueue(8, 8);
    var leases = new List<IDisposable>();
    for (var i = 0; i < 8; i++)
        leases.Add(await saturated.EnterAsync("active-" + i, "bulk.test", 1, CancellationToken.None));
    using (var stopWaiting = new CancellationTokenSource())
    {
        var waiting = Enumerable.Range(0, 24)
            .Select(i => saturated.EnterAsync("waiting-" + i, "bulk.test", 1, stopWaiting.Token))
            .ToArray();
        if (saturated.ActiveCount != 8 || saturated.WaitingCount != 24 ||
            waiting.Any(task => task.IsCompleted))
            throw new Exception("32-transfer contention exceeded the configured eight slots.");
        stopWaiting.Cancel();
        foreach (var task in waiting)
        {
            try
            {
                using var unexpected = await task.WaitAsync(TimeSpan.FromSeconds(3));
                throw new Exception("Canceled waiter unexpectedly acquired a slot.");
            }
            catch (OperationCanceledException) { }
        }
        if (saturated.WaitingCount != 0 || saturated.ActiveCount != 8)
            throw new Exception("Canceled backpressure waiters leaked scheduler capacity.");
    }
    foreach (var lease in leases) lease.Dispose();
    if (saturated.ActiveCount != 0 || saturated.WaitingCount != 0)
        throw new Exception("32-transfer backpressure did not release all slots.");

    // Partial cancellation under saturation must preserve the surviving FIFO
    // waiters and reclaim all leases, not just the all-canceled case.
    var partialQueue = new TransferSlotQueue(1, 1);
    var occupied = await partialQueue.EnterAsync("partial-active", "partial.test", 1, CancellationToken.None);
    using (var canceled = new CancellationTokenSource())
    {
        var firstWaiting = partialQueue.EnterAsync("partial-canceled", "partial.test", 1, canceled.Token);
        var surviving = partialQueue.EnterAsync("partial-survivor", "partial.test", 1, CancellationToken.None);
        if (partialQueue.WaitingCount != 2 || surviving.IsCompleted)
            throw new Exception("Partial cancellation test did not saturate the queue.");
        canceled.Cancel();
        try { using var unexpected = await firstWaiting.WaitAsync(TimeSpan.FromSeconds(3));
            throw new Exception("Canceled first waiter acquired capacity."); }
        catch (OperationCanceledException) { }
        if (partialQueue.WaitingCount != 1 || surviving.IsCompleted)
            throw new Exception("Canceling one waiter disturbed the surviving reservation.");
        occupied.Dispose();
        using (var survivorLease = await surviving.WaitAsync(TimeSpan.FromSeconds(3)))
        {
            if (partialQueue.ActiveCount != 1 || partialQueue.WaitingCount != 0)
                throw new Exception("Surviving waiter did not inherit the released slot.");
        }
    }
    occupied.Dispose();
    if (partialQueue.ActiveCount != 0 || partialQueue.WaitingCount != 0)
        throw new Exception("Partial cancellation leaked scheduler capacity.");

    // Reconfiguring capacity while leases are active must not over-allocate,
    // and raising the cap must dispatch queued jobs without requiring a release.
    var resizedQueue = new TransferSlotQueue(2, 2);
    using (var firstLease = await resizedQueue.EnterAsync("resize-1", "resize.test", 1, CancellationToken.None))
    using (var secondLease = await resizedQueue.EnterAsync("resize-2", "resize.test", 1, CancellationToken.None))
    {
        resizedQueue.Configure(1, 1);
        var pendingResize = resizedQueue.EnterAsync("resize-wait", "resize.test", 1, CancellationToken.None);
        if (resizedQueue.ActiveCount != 2 || resizedQueue.WaitingCount != 1 || pendingResize.IsCompleted)
            throw new Exception("Lowering concurrency admitted a waiting transfer.");
        resizedQueue.Configure(3, 3);
        using (var thirdLease = await pendingResize.WaitAsync(TimeSpan.FromSeconds(3)))
        {
            if (resizedQueue.ActiveCount != 3 || resizedQueue.WaitingCount != 0)
                throw new Exception("Raising concurrency did not dispatch the waiting transfer.");
        }
    }
    if (resizedQueue.ActiveCount != 0 || resizedQueue.WaitingCount != 0)
        throw new Exception("Reconfigured scheduler leaked a lease.");

    // Saving an unchanged global speed limit must not reset outstanding
    // bandwidth debt or let concurrent transfers briefly exceed the cap.
    var unchangedGate = new TransferRateGate(64);
    using (var firstStop = new CancellationTokenSource())
    using (var secondStop = new CancellationTokenSource())
    {
        var firstPermit = unchangedGate.WaitForBytesAsync(256 * 1024, firstStop.Token);
        unchangedGate.Configure(64);
        var secondPermit = unchangedGate.WaitForBytesAsync(8 * 1024, secondStop.Token);
        if (await Task.WhenAny(secondPermit, Task.Delay(400)) == secondPermit)
            throw new Exception("Unchanged speed setting erased pending bandwidth debt.");
        secondStop.Cancel();
        firstStop.Cancel();
        try { await secondPermit; } catch (OperationCanceledException) { }
        try { await firstPermit; } catch (OperationCanceledException) { }
    }

    // Canceling the last reservation must preserve the earlier reader's debt.
    var sharedGate = new TransferRateGate(64);
    using (var earlierStop = new CancellationTokenSource())
    using (var tailStop = new CancellationTokenSource())
    using (var nextStop = new CancellationTokenSource())
    {
        var earlier = sharedGate.WaitForBytesAsync(256 * 1024, earlierStop.Token);
        var tail = sharedGate.WaitForBytesAsync(256 * 1024, tailStop.Token);
        tailStop.Cancel();
        try { await tail; throw new Exception("Tail must cancel."); }
        catch (OperationCanceledException) { }
        var next = sharedGate.WaitForBytesAsync(8 * 1024, nextStop.Token);
        var quick = Task.Delay(500);
        if (await Task.WhenAny(next, quick) == next)
            throw new Exception("Tail cancellation erased an earlier bandwidth reservation.");
        nextStop.Cancel();
        earlierStop.Cancel();
        try { await next; } catch (OperationCanceledException) { }
        try { await earlier; } catch (OperationCanceledException) { }
    }
    // A queued job canceled while another host owns all slots must never
    // consume capacity when that host finishes. Check both slot and host counts.
    var cancelledBehindHost = new TransferSlotQueue(1, 1);
    using (var occupiedSlot = await cancelledBehindHost.EnterAsync("busy", "busy.test", 1, CancellationToken.None))
    {
        using var cancelledToken = new CancellationTokenSource();
        var abandoned = cancelledBehindHost.EnterAsync("abandoned", "waiting.test", 0, cancelledToken.Token);
        var survivor = cancelledBehindHost.EnterAsync("survivor", "waiting.test", 2, CancellationToken.None);
        cancelledToken.Cancel();
        try
        {
            await abandoned;
            throw new Exception("Canceled priority waiter unexpectedly acquired a slot.");
        }
        catch (OperationCanceledException) { }
        if (cancelledBehindHost.WaitingCount != 1 || survivor.IsCompleted)
            throw new Exception("Canceling a waiting transfer changed active capacity.");
        occupiedSlot.Dispose();
        using var resumed = await survivor.WaitAsync(TimeSpan.FromSeconds(3));
        if (cancelledBehindHost.ActiveCount != 1)
            throw new Exception("Surviving queued transfer failed to acquire released capacity.");
    }
    if (cancelledBehindHost.ActiveCount != 0 || cancelledBehindHost.WaitingCount != 0)
        throw new Exception("Canceling queued transfers leaked active or waiting slots.");

    // Measured global backpressure at 1/8/32 simultaneous HTTP ranges.
    // A shared gate must constrain the aggregate rather than allowing each
    // segment its own full-speed budget. This uses only synthetic byte permits
    // and never touches user files, the network or persisted checkpoints.
    foreach (var ranges in new[] { 1, 8, 32 })
    {
        var aggregate = new TransferRateGate(64);
        var clock = System.Diagnostics.Stopwatch.StartNew();
        var permits = Enumerable.Range(0, ranges)
            .Select(async _ =>
            {
                // Every segment requests the same total share of 64 KiB.
                // Small read reservations mirror the bounded socket reader.
                for (var chunk = 0; chunk < 64 / ranges; chunk++)
                    await aggregate.WaitForBytesAsync(1024, CancellationToken.None);
            }).ToArray();
        await Task.WhenAll(permits).WaitAsync(TimeSpan.FromSeconds(5));
        if (clock.ElapsedMilliseconds < 750 || clock.ElapsedMilliseconds > 4500)
            throw new Exception($"Global bandwidth backpressure failed with {ranges} ranges: {clock.ElapsedMilliseconds}ms.");
    }
    var limit = new TransferRateGate(128);
    var gateClock = System.Diagnostics.Stopwatch.StartNew();
    await limit.WaitForBytesAsync(64 * 1024, CancellationToken.None);
    if (gateClock.ElapsedMilliseconds < 300)
        throw new Exception("Rate gate failed to enforce a measurable bandwidth limit.");
    // The global and per-file caps are independent constraints, not serial
    // delays. Two equal 128 KiB/s caps must allow a 64 KiB read in roughly
    // 0.5s rather than erroneously delaying it for roughly 1s.
    var combinedGlobal = new TransferRateGate(128);
    var combinedFile = new TransferRateGate(128);
    gateClock.Restart();
    await TransferRateLimiter.WaitAsync(combinedGlobal, combinedFile,
        64 * 1024, CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(3));
    if (gateClock.ElapsedMilliseconds < 300 || gateClock.ElapsedMilliseconds > 850)
        throw new Exception("Combined HTTP caps must use the slower budget, not add both delays.");
    // Cancellation must cancel both concurrent reservations, leaving no
    // stale multi-second tail that would block the next download.
    var combinedCancelGlobal = new TransferRateGate(64);
    var combinedCancelFile = new TransferRateGate(64);
    using (var stopCombined = new CancellationTokenSource())
    {
        var abandoned = TransferRateLimiter.WaitAsync(combinedCancelGlobal,
            combinedCancelFile, 256 * 1024, stopCombined.Token);
        stopCombined.Cancel();
        try { await abandoned; throw new Exception("Combined rate reservation must cancel."); }
        catch (OperationCanceledException) { }
    }
    gateClock.Restart();
    await TransferRateLimiter.WaitAsync(combinedCancelGlobal, combinedCancelFile,
        8 * 1024, CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(2));
    if (gateClock.ElapsedMilliseconds > 1200)
        throw new Exception("Canceled combined bandwidth cap stalled a new transfer.");
    // A canceled final bandwidth reservation must not stall the next job.
    var cancelGate = new TransferRateGate(64);
    using (var stopGate = new CancellationTokenSource())
    {
        var waiting = cancelGate.WaitForBytesAsync(256 * 1024, stopGate.Token);
        stopGate.Cancel();
        try
        {
            await waiting;
            throw new Exception("Canceled rate reservation must throw.");
        }
        catch (OperationCanceledException) { }
    }
    gateClock.Restart();
    await cancelGate.WaitForBytesAsync(8 * 1024, CancellationToken.None);
    if (gateClock.ElapsedMilliseconds > 1200)
        throw new Exception("Canceled bandwidth reservation stalled a subsequent transfer.");
    // Reconfiguration must invalidate an old reservation's cancellation refund.
    var reconfiguredGate = new TransferRateGate(64);
    using (var oldRequest = new CancellationTokenSource())
    {
        var obsolete = reconfiguredGate.WaitForBytesAsync(256 * 1024, oldRequest.Token);
        // A real rate change creates a new generation. Reapplying the
        // same limit intentionally preserves outstanding reservations.
        reconfiguredGate.Configure(128);
        var current = reconfiguredGate.WaitForBytesAsync(64 * 1024, CancellationToken.None);
        oldRequest.Cancel();
        try { await obsolete; throw new Exception("Old reservation must cancel."); }
        catch (OperationCanceledException) { }
        gateClock.Restart();
        await current.WaitAsync(TimeSpan.FromSeconds(3));
        if (gateClock.ElapsedMilliseconds < 300)
            throw new Exception("Old canceled reservation must not refund a new configuration.");
    }
    using (var alreadyCanceled = new CancellationTokenSource())
    {
        alreadyCanceled.Cancel();
        try
        {
            await reconfiguredGate.WaitForBytesAsync(8 * 1024, alreadyCanceled.Token);
            throw new Exception("Pre-canceled request must not reserve bandwidth.");
        }
        catch (OperationCanceledException) { }
    }
    limit.Configure(0);
    gateClock.Restart();
    await limit.WaitForBytesAsync(64 * 1024, CancellationToken.None);
    if (gateClock.ElapsedMilliseconds > 150)
        throw new Exception("Unlimited rate setting must not delay transfers.");
    if (TransferRateMath.Smooth(1000, 0, true) is <= 0 or >= 1000 ||
        TransferRateMath.Smooth(1000, 2000, true) is <= 1000 or >= 2000 ||
        TransferRateMath.Smooth(1000, 0, false) != 0 ||
        TransferRateMath.Smooth(double.NaN, 200, true) != 200 ||
        TransferRateMath.Smooth(double.PositiveInfinity, 200, true) != 200 ||
        TransferRateMath.Smooth(double.NegativeInfinity, 200, true) != 200 ||
        TransferRateMath.Smooth(200, double.NaN, true) is <= 0 or >= 200 ||
        !double.IsFinite(TransferRateMath.Smooth(double.MaxValue, double.MaxValue, true)))
        throw new Exception("Download speed smoothing must decay and reset correctly.");

    // Retry policy is selective. Auth and missing resources must not be
    // retried; rate limits and network failures should have bounded backoff.
    if (!DownloadRetryPolicy.IsTransientStatus(HttpStatusCode.RequestTimeout) ||
        !DownloadRetryPolicy.IsTransientStatus(HttpStatusCode.TooManyRequests) ||
        !DownloadRetryPolicy.IsTransientStatus(HttpStatusCode.ServiceUnavailable) ||
        DownloadRetryPolicy.IsTransientStatus(HttpStatusCode.NotFound) ||
        DownloadRetryPolicy.IsTransientStatus(HttpStatusCode.Forbidden) ||
        DownloadRetryPolicy.Backoff(1) != TimeSpan.FromSeconds(1) ||
        DownloadRetryPolicy.Backoff(4) != TimeSpan.FromSeconds(8) ||
        DownloadRetryPolicy.Backoff(9) != TimeSpan.FromSeconds(30) ||
        DownloadRetryPolicy.Backoff(1, TimeSpan.FromSeconds(20)) != TimeSpan.FromSeconds(20))
        throw new Exception("Transient and permanent HTTP retry behavior must be bounded.");

    // SQLite migration and crash recovery: imported legacy JSON must remain
    // untouched, every job/chunk checkpoint must commit atomically, and a
    // second startup must never re-import deleted history.
    var stateDir = Path.Combine(folder, "sqlite-state");
    Directory.CreateDirectory(stateDir);
    var legacyHistoryPath = Path.Combine(stateDir, "downloads.json");
    var legacyJob = new DownloadJob
    {
        Id = "legacy123", Url = server.Url + "range/legacy.bin",
        Name = "ประวัติไทย.zip", Folder = folder, Kind = "File",
        Status = "Running", TotalBytes = 1048576, DownloadedBytes = 13579,
        SupportsRanges = true, SegmentsUsed = 4, Parts = 4,
        ETag = "\"legacy-strong-tag\"", CreatedAt = DateTimeOffset.UtcNow
    };
    var legacyData = System.Text.Json.JsonSerializer.Serialize(
        new[] { legacyJob }, new System.Text.Json.JsonSerializerOptions { IncludeFields = true });
    File.WriteAllText(legacyHistoryPath, legacyData);
    var store = new DownloadStateStore(stateDir);
    var restored = store.LoadOrMigrate(legacyHistoryPath);
    if (restored.Count != 1 || restored[0].Id != legacyJob.Id ||
        restored[0].Name != legacyJob.Name ||
        restored[0].DownloadedBytes != legacyJob.DownloadedBytes ||
        !File.Exists(legacyHistoryPath) || File.ReadAllText(legacyHistoryPath) != legacyData)
        throw new Exception("Legacy JSON migration lost Thai filenames, offsets or original backup.");
    var segmentDir = Path.Combine(folder, ".xstage-downloads", legacyJob.Id);
    Directory.CreateDirectory(segmentDir);
    File.WriteAllBytes(Path.Combine(segmentDir, "00.part"), new byte[32768]);
    store.SaveSnapshot(restored);
    var info = store.Inspect();
    if (info.Mode != "wal" || info.Jobs != 1 || info.Chunks != 4)
        throw new Exception("SQLite WAL migration must checkpoint every partial segment.");
    using (var db = new Microsoft.Data.Sqlite.SqliteConnection(
               "Data Source=" + store.DatabasePath))
    {
        db.Open();
        using var cmd = db.CreateCommand();
        cmd.CommandText = """
            SELECT downloaded_bytes FROM xstage_download_chunks
            WHERE job_id='legacy123' AND chunk_index=0;
            """;
        if (Convert.ToInt64(cmd.ExecuteScalar()) != 32768L)
            throw new Exception("Chunk offsets must reflect durable physical .part bytes.");
    }
    store.SaveDefaultParts(16);
    var anotherStore = new DownloadStateStore(stateDir);
    if (anotherStore.ReadDefaultParts(4) != 16 ||
        anotherStore.LoadOrMigrate(legacyHistoryPath).Single().Id != legacyJob.Id)
        throw new Exception("SQLite reopening lost job state, settings or checkpoint data.");

    var failedTxn = false;
    try
    {
        anotherStore.SaveSnapshot(new[] { restored[0], restored[0] });
    }
    catch (Microsoft.Data.Sqlite.SqliteException)
    {
        failedTxn = true;
    }
    if (!failedTxn || anotherStore.LoadOrMigrate(legacyHistoryPath).Count != 1)
        throw new Exception("A failed SQLite transaction must preserve the prior committed job list.");
    anotherStore.SaveSnapshot(Array.Empty<DownloadJob>());
    if (new DownloadStateStore(stateDir).LoadOrMigrate(legacyHistoryPath).Count != 0)
        throw new Exception("Migrated JSON must not resurrect a removed history item.");

    store.SavePerformanceSetting("global_jobs", 3, 1, 8);
    store.SavePerformanceSetting("host_jobs", 2, 1, 8);
    store.SavePerformanceSetting("global_limit_kib", 256, 0, 1_048_576);
    if (new DownloadStateStore(stateDir)
        .ReadPerformanceSetting("global_jobs", 2, 1, 8) != 3 ||
        new DownloadStateStore(stateDir)
        .ReadPerformanceSetting("host_jobs", 2, 1, 8) != 2 ||
        new DownloadStateStore(stateDir)
        .ReadPerformanceSetting("global_limit_kib", 0, 0, 1_048_576) != 256)
        throw new Exception("Performance limits must persist in SQLite.");
    // A failed second statement must roll back the first setting too.
    // This simulates a SQLite write failure without touching user data.
    store.SavePerformanceSettings(3, 2, 256);
    using (var db = new Microsoft.Data.Sqlite.SqliteConnection(
        "Data Source=" + store.DatabasePath))
    {
        db.Open();
        using var trigger = db.CreateCommand();
        trigger.CommandText = """
            CREATE TRIGGER xstage_test_reject_host_setting
            BEFORE UPDATE ON xstage_download_settings
            WHEN NEW.key='host_jobs'
            BEGIN SELECT RAISE(ABORT, 'simulated settings write failure'); END;
            """;
        trigger.ExecuteNonQuery();
        try
        {
            store.SavePerformanceSettings(4, 3, 512);
            throw new Exception("Expected atomic performance update to fail.");
        }
        catch (Microsoft.Data.Sqlite.SqliteException) { }
        finally
        {
            using var cleanup = db.CreateCommand();
            cleanup.CommandText = "DROP TRIGGER IF EXISTS xstage_test_reject_host_setting;";
            cleanup.ExecuteNonQuery();
        }
    }
    if (store.ReadPerformanceSetting("global_jobs", 2, 1, 8) != 3 ||
        store.ReadPerformanceSetting("host_jobs", 2, 1, 8) != 2 ||
        store.ReadPerformanceSetting("global_limit_kib", 0, 0, 1_048_576) != 256)
        throw new Exception("Failed performance transaction must retain every old limit.");
    store.SavePerformanceSettings(4, 3, 512);
    if (new DownloadStateStore(stateDir)
        .ReadPerformanceSetting("global_jobs", 2, 1, 8) != 4 ||
        new DownloadStateStore(stateDir)
        .ReadPerformanceSetting("host_jobs", 2, 1, 8) != 3 ||
        new DownloadStateStore(stateDir)
        .ReadPerformanceSetting("global_limit_kib", 0, 0, 1_048_576) != 512)
        throw new Exception("Atomic performance settings must survive SQLite reopen.");
    store.SavePerformanceSettings(3, 2, 256);


    // Regression: a verified completed download must fill every pixel of its
    // progress bar even if its old per-segment data is stale or incomplete.
    var completeFile = new DownloadJob
    {
        Kind = "File", Status = "Completed", TotalBytes = 1024,
        DownloadedBytes = 1024, SegmentsUsed = 32,
        SegmentDownloadedBytes = new long[32]
    };
    if (!ProgressPresentation.IsComplete(completeFile) ||
        ProgressPresentation.FillFraction(completeFile) != 1.0 ||
        ProgressPresentation.PercentLabel(completeFile) != "100.0%")
        throw new Exception("Completed segmented file must be displayed as 100% solid green.");

    var finalizingFile = new DownloadJob
    {
        Kind = "File", Status = "Running", TotalBytes = 1024,
        DownloadedBytes = 1024
    };
    if (ProgressPresentation.IsComplete(finalizingFile) ||
        ProgressPresentation.FillFraction(finalizingFile) >= 1.0 ||
        ProgressPresentation.PercentLabel(finalizingFile) == "100.0%")
        throw new Exception("Finalizing file must not show verified 100% too early.");

    var finalizingVideo = new DownloadJob
    {
        Kind = "Video", Status = "Running", VideoPercent = 100
    };
    if (ProgressPresentation.IsComplete(finalizingVideo) ||
        ProgressPresentation.PercentLabel(finalizingVideo) == "100.0%")
        throw new Exception("Video fragment download at 100% is not a finished FFmpeg merge.");
    finalizingVideo.Status = "Completed";
    finalizingVideo.VideoPercent = 0; // stale yt-dlp reading
    if (ProgressPresentation.FillFraction(finalizingVideo) != 1.0 ||
        ProgressPresentation.PercentLabel(finalizingVideo) != "100.0%")
        throw new Exception("Completed video must always display solid green 100%.");

    // Header sorting must use numeric/date data rather than display labels.
    // The displayed order must not mutate the original queue or row IDs.
    var sortDate = new DateTimeOffset(2026, 11, 20, 8, 0, 0, TimeSpan.Zero);
    var sortJobs = new[]
    {
        new DownloadJob { Id = "s1", Name = "large.zip", TotalBytes = 10_000_000,
            Status = "Completed", CreatedAt = sortDate.AddMinutes(2) },
        new DownloadJob { Id = "s2", Name = "small.exe", TotalBytes = 200,
            Status = "Completed", CreatedAt = sortDate },
        new DownloadJob { Id = "s3", Name = "unnamed", TotalBytes = -1,
            Status = "Queued", CreatedAt = sortDate.AddMinutes(1) },
        new DownloadJob { Id = "s4", Name = "video",
            Kind = "Video", OutputFormat = "mp4", TotalBytes = 500,
            Status = "Running", VideoPercent = 67, CreatedAt = sortDate.AddMinutes(3) }
    };
    static string JoinedIds(IEnumerable<DownloadJob> jobs) =>
        string.Join(",", jobs.Select(job => job.Id));
    if (DownloadTableSort.FileType(sortJobs[0]) != "ZIP" ||
        DownloadTableSort.FileType(sortJobs[1]) != "EXE" ||
        DownloadTableSort.FileType(sortJobs[2]) != "ไม่ทราบ" ||
        DownloadTableSort.FileType(sortJobs[3]) != "MP4")
        throw new Exception("File type column must show real extension or chosen social output.");
    if (JoinedIds(DownloadTableSort.Sort(sortJobs, "Size", false, sortJobs)) != "s2,s4,s1,s3" ||
        JoinedIds(DownloadTableSort.Sort(sortJobs, "Size", true, sortJobs)) != "s1,s4,s2,s3" ||
        JoinedIds(DownloadTableSort.Sort(sortJobs, "FileType", false, sortJobs)) != "s2,s4,s1,s3" ||
        JoinedIds(DownloadTableSort.Sort(sortJobs, "FileType", true, sortJobs)) != "s1,s4,s2,s3" ||
        JoinedIds(DownloadTableSort.Sort(sortJobs, "Added", false, sortJobs)) != "s2,s3,s1,s4" ||
        JoinedIds(DownloadTableSort.Sort(sortJobs, "Added", true, sortJobs)) != "s4,s1,s3,s2")
        throw new Exception("Sort by bytes, file extension, and actual timestamp must handle both directions.");
    var filteredQueue = new[] { sortJobs[3], sortJobs[1] };
    if (JoinedIds(DownloadTableSort.Sort(filteredQueue, "Queue", false, sortJobs)) != "s2,s4" ||
        JoinedIds(DownloadTableSort.Sort(filteredQueue, "Queue", true, sortJobs)) != "s4,s2" ||
        JoinedIds(sortJobs) != "s1,s2,s3,s4")
        throw new Exception("Sorting a filtered list must preserve original queue order and identity.");
    // Approved X-Stage transfer table adds a visible named-queue column.
    // Sorting must use the persisted queue name without reordering the real
    // transfer queue or changing the selected job ID.
    sortJobs[0].QueueName = "C";
    sortJobs[1].QueueName = "A";
    sortJobs[2].QueueName = "D";
    sortJobs[3].QueueName = "B";
    if (JoinedIds(DownloadTableSort.Sort(sortJobs, "QueueName", false, sortJobs)) != "s2,s4,s1,s3" ||
        JoinedIds(DownloadTableSort.Sort(sortJobs, "QueueName", true, sortJobs)) != "s3,s1,s4,s2" ||
        JoinedIds(DownloadTableSort.Sort(sortJobs, "No", false, sortJobs)) != "s1,s2,s3,s4" ||
        JoinedIds(DownloadTableSort.Sort(sortJobs, "No", true, sortJobs)) != "s4,s3,s2,s1" ||
        JoinedIds(sortJobs) != "s1,s2,s3,s4")
        throw new Exception("X-Stage named queue / row number sorting must be stable and read-only.");

    // Ctrl+N and the toolbar use the same parser: clipboard URL is inserted
    // into the editable field, not submitted to the download engine automatically.
    if (MainForm.ExtractClipboardUrls("https://example.com/demo.zip") != "https://example.com/demo.zip" ||
        MainForm.ExtractClipboardUrls("https://example.com/a.zip\nhttps://example.com/b.pdf")
          != "https://example.com/a.zip" + Environment.NewLine + "https://example.com/b.pdf" ||
        MainForm.ExtractClipboardUrls("password123") != "" ||
        MainForm.ExtractClipboardUrls("file:///C:/secret.txt") != "")
        throw new Exception("Add URL clipboard extraction must accept only HTTP/HTTPS URLs.");

    // Verify strict hostname matching; reject lookalike domains and file URLs.
    var videoHosts = new[]
    {
        "https://www.youtube.com/watch?v=test1234", "https://youtu.be/test1234",
        "https://www.tiktok.com/@someone/video/123", "https://vt.tiktok.com/abc",
        "https://www.facebook.com/reel/123", "https://fb.watch/abc",
        "https://www.instagram.com/reel/abc"
    };
    foreach (var uri in videoHosts)
        if (!SocialVideoDownloader.IsVideoUrl(uri))
            throw new Exception("Social video domain not recognized: " + uri);
    // A DNS-equivalent trailing-dot host must keep the correct platform label.
    foreach (var (url, expected) in new[]
    {
        ("https://www.youtube.com./watch?v=abc", "YouTube"),
        ("https://www.tiktok.com./video/123", "TikTok"),
        ("https://www.instagram.com./reel/abc", "Instagram Reels"),
        ("https://www.facebook.com./watch/123", "Facebook Reels")
    })
    {
        if (!SocialVideoDownloader.IsVideoUrl(url) || SocialVideoDownloader.Platform(url) != expected)
            throw new Exception("Trailing-dot video host lost its platform label: " + url);
    }
    // Ordinary download links must NOT expose video-quality/container options.
    if (SocialVideoDownloader.InputContainsVideo("") ||
        SocialVideoDownloader.InputContainsVideo("https://example.com/file.zip") ||
        SocialVideoDownloader.InputContainsVideo("https://example.com/manual.pdf") ||
        SocialVideoDownloader.InputContainsVideo("https://cdn.example.org/video.mp4") ||
        SocialVideoDownloader.InputContainsVideo("https://youtube.com.evil.example/watch?v=123") ||
        !SocialVideoDownloader.InputContainsVideo("https://youtu.be/tF-PEdvMJ_o") ||
        !SocialVideoDownloader.InputContainsVideo("https://example.com/file.zip\nhttps://www.youtube.com/watch?v=tF-PEdvMJ_o"))
        throw new Exception("Video-only controls must follow the input URL category.");

    foreach (var uri in new[] {
        "https://youtube.com.attacker.invalid/video", "https://evil-tiktok.com/video",
        "https://facebook.com.evil.example/reel/1", "https://user:pass@youtube.com/watch?v=1",
        "file:///C:/secret" })
        if (SocialVideoDownloader.IsVideoUrl(uri))
            throw new Exception("Unsafe or deceptive social URL incorrectly accepted: " + uri);
    var video = new DownloadJob { Url = videoHosts[0], Folder = folder, Parts = 16, VideoQuality = "1080" };
    // Video subprocess must honor the stricter persisted per-file/global cap.
    // This is a per-process cap; aggregate cross-engine shaping is still pending.
    video.FileSpeedLimitKib = 128;
    var cappedVideo = SocialVideoDownloader.BuildArguments(video, folder, folder, 256).ToArray();
    var capIndex = Array.IndexOf(cappedVideo, "--limit-rate");
    if (capIndex < 0 || capIndex + 1 >= cappedVideo.Length || cappedVideo[capIndex + 1] != "128K" ||
        SocialVideoDownloader.VideoRateLimitKib(0, 0) != 0 ||
        SocialVideoDownloader.VideoRateLimitKib(256, 0) != 256 ||
        SocialVideoDownloader.VideoRateLimitKib(0, 128) != 128 ||
        SocialVideoDownloader.VideoRateLimitKib(256, 128) != 128)
        throw new Exception("yt-dlp speed caps must honor the strictest configured limit.");
    // Invalid persisted limits must fail before starting yt-dlp. This mirrors
    // TransferRateGate and protects against corrupt or out-of-range settings.
    foreach (var (global, file) in new[] {
        (-1, 0), (0, -1), (63, 0), (0, 63),
        (1_048_577, 0), (0, 1_048_577)
    })
    {
        try
        {
            SocialVideoDownloader.VideoRateLimitKib(global, file);
            throw new Exception("Invalid yt-dlp speed cap accepted: " + global + "/" + file);
        }
        catch (ArgumentOutOfRangeException ex)
        {
            var expectedParameter = global != 0 && (global < 64 || global > 1_048_576)
                ? "globalLimitKib" : "fileLimitKib";
            if (ex.ParamName != expectedParameter)
                throw new Exception("Incorrect yt-dlp speed setting diagnostic: " +
                    ex.ParamName + " instead of " + expectedParameter);
        }
    }
    if (SocialVideoDownloader.VideoRateLimitKib(64, 1_048_576) != 64 ||
        SocialVideoDownloader.VideoRateLimitKib(1_048_576, 64) != 64)
        throw new Exception("yt-dlp speed cap boundary validation regressed.");
    foreach (var diagnostic in new[] {
        "ERROR: This video is DRM protected",
        "ERROR: stream is DRM-protected",
        "ERROR: encrypted with DRM",
        "ERROR: This video is DRM encrypted"
    })
    {
        var explanation = SocialVideoDownloader.ExplainFailure(diagnostic, 1);
        if (!explanation.Contains("DRM", StringComparison.Ordinal) ||
            !explanation.Contains("ทางการ", StringComparison.Ordinal))
            throw new Exception("DRM media must direct users to official playback.");
    }
    if (SocialVideoDownloader.ExplainFailure("HTTP Error 429", 1).Contains("DRM"))
        throw new Exception("Non-DRM network failures must retain their own diagnostics.");
    // Legacy SQLite imports may have short IDs; a separate-copy request
    // must not throw from an unchecked [..8] slice before yt-dlp starts.
    var shortIdCopy = new DownloadJob { Id = "old1", Url = videoHosts[0],
        Folder = folder, Parts = 4, VideoQuality = "Best",
        OutputFormat = "mp4", IsRedownload = true };
    var shortIdArgs = SocialVideoDownloader.BuildArguments(shortIdCopy, folder, folder);
    var outputIndex = shortIdArgs.ToList().IndexOf("-o");
    if (outputIndex < 0 || !shortIdArgs[outputIndex + 1].Contains("(again-old1)"))
        throw new Exception("Short legacy video IDs must preserve stable redownload naming.");
    video.FileSpeedLimitKib = 0;
    var uncappedVideo = SocialVideoDownloader.BuildArguments(video, folder, folder).ToArray();
    if (uncappedVideo.Contains("--limit-rate"))
        throw new Exception("Unlimited video downloads must not receive a rate cap.");
    var videoArgs = SocialVideoDownloader.BuildArguments(video, Path.Combine(folder, ".temp"), Path.Combine(folder, "tools")).ToArray();
    if (!videoArgs.Contains("--no-playlist") || !videoArgs.Contains("--ignore-config") ||
        !videoArgs.Contains("--no-plugin-dirs") ||
        !videoArgs.Contains("--no-simulate") || !videoArgs.Contains("deno:" + Path.Combine(folder, "tools", "deno.exe")) ||
        !videoArgs.Contains("bv*[height<=1080]+ba/b[height<=1080]"))
        throw new Exception("Video arguments must isolate config, enforce video quality and use bundled Deno.");
    // yt-dlp's --print implies --quiet; --progress must explicitly restore
    // live reporting for the embedded UI in both Windows redirected streams.
    if (!videoArgs.Contains("--progress") ||
        !videoArgs.Contains("--newline") ||
        !videoArgs.Contains("--progress-template"))
        throw new Exception("Video progress must be enabled even when --print suppresses default output.");

    if (!SocialVideoDownloader.TryParseProgress(
            "xstage-progress: 25.0%|2048|8192|NA",
            out var firstPercent, out var firstBytes, out var firstTotal) ||
        firstPercent != 25.0 || firstBytes != 2048 || firstTotal != 8192)
        throw new Exception("Video progress template percent, bytes and total not parsed correctly.");

    if (!SocialVideoDownloader.TryParseProgress(
            "xstage-progress:N/A|2048|NA|8192",
            out var fallbackPercent, out _, out _) ||
        fallbackPercent != 25.0)
        throw new Exception("Video percent must fall back to received bytes / estimated total.");

    if (!SocialVideoDownloader.TryParseProgress(
            "[download] xstage-progress: \\x1b[0;94m 37.5%\\x1b[0m|3000|8000|NA".Replace(
                "\\x1b", ((char)27).ToString()),
            out var ansiPercent, out _, out _) ||
        ansiPercent != 37.5)
        throw new Exception("Video progress parser should ignore terminal color codes.");

    if (SocialVideoDownloader.TryParseProgress("[download] Downloading webpage...",
            out _, out _, out _))
        throw new Exception("Video progress parser must not treat non-progress log lines as measurements.");

    // Social downloads should expose a phase instead of staying at fake
    // "0.0% downloading", and network retries must terminate predictably.
    if (!videoArgs.Contains("--socket-timeout") ||
        !videoArgs.Contains("--fragment-retries") ||
        !videoArgs.Contains("--extractor-retries") ||
        !videoArgs.Contains("--retry-sleep"))
        throw new Exception("Bounded yt-dlp network retries and socket timeout missing.");
    // 32 HTTP byte ranges are useful for direct files, but using 32 yt-dlp
    // fragments concurrently risks HTTP 403/429 on social video CDNs.
    var streamOptionIndex = Array.IndexOf(videoArgs, "-N");
    if (streamOptionIndex < 0 || streamOptionIndex + 1 >= videoArgs.Length ||
        videoArgs[streamOptionIndex + 1] != "4" ||
        SocialVideoDownloader.VideoFragmentConcurrency(32) != 4 ||
        SocialVideoDownloader.VideoFragmentConcurrency(2) != 2)
        throw new Exception("Social video concurrency must cap at 4 independent of HTTP segment count.");
    if (!SocialVideoDownloader.IsYtDlpError("ERROR: HTTP Error 403: Forbidden") ||
        !SocialVideoDownloader.IsYtDlpError("ERROR: Requested format is not available") ||
        SocialVideoDownloader.IsYtDlpError("[download] Destination: video.mp4") ||
        !SocialVideoDownloader.ExplainFailure("ERROR: HTTP Error 403", 1).Contains("403") ||
        !SocialVideoDownloader.ExplainFailure("ERROR: HTTP Error 429", 1).Contains("429") ||
        !SocialVideoDownloader.ExplainFailure("ERROR: Requested format is not available", 1)
            .Contains("ความละเอียด") ||
        !SocialVideoDownloader.ExplainFailure("ERROR: Sign in to confirm", 1)
            .Contains("ยืนยันตัวตน"))
        throw new Exception("Video failures from yt-dlp stdout/stderr must explain access and format errors.");

    if (SocialVideoDownloader.DescribeOutputPhase("[youtube] Downloading webpage") !=
            "กำลังอ่านข้อมูลวิดีโอจากเว็บไซต์" ||
        SocialVideoDownloader.DescribeOutputPhase("[download] Destination: song.f137.mp4") !=
            "กำลังรับข้อมูลวิดีโอ" ||
        SocialVideoDownloader.DescribeOutputPhase("[Merger] Merging formats") !=
            "กำลังรวม/แปลงไฟล์วิดีโอ" ||
        SocialVideoDownloader.DescribeOutputPhase("plain unrelated text") is not null)
        throw new Exception("Video phase detector misreported yt-dlp output.");
    if (SocialVideoDownloader.IsStalled(TimeSpan.FromSeconds(30), false) ||
        !SocialVideoDownloader.IsStalled(TimeSpan.FromSeconds(121), false) ||
        SocialVideoDownloader.IsStalled(TimeSpan.FromMinutes(5), true) ||
        !SocialVideoDownloader.IsStalled(TimeSpan.FromMinutes(16), true))
        throw new Exception("Progress watchdog must distinguish network stalls and slow FFmpeg.");

    // Container selection is independent of resolution. MP4 is the default;
    // yt-dlp/FFmpeg must actually convert instead of renaming an MKV extension.
    if (video.OutputFormat != "mp4" || videoArgs.Contains("--recode-video") ||
        !videoArgs.Contains("--merge-output-format") ||
        !videoArgs.Contains("mkv"))
        throw new Exception("MP4 must use verified MKV-first workflow, never direct yt-dlp recode.");
    foreach (var outputFormat in new[] { "mkv", "webm", "mp4" })
    {
        video.OutputFormat = outputFormat;
        var containerArgs = SocialVideoDownloader.BuildArguments(video, folder, folder).ToArray();
        var pos = Array.IndexOf(containerArgs, "--merge-output-format");
        if (pos < 0 || pos + 1 >= containerArgs.Length || containerArgs[pos + 1] != "mkv")
            throw new Exception("Download must retain MKV as intermediate: " + outputFormat);
        if (containerArgs.Contains("--recode-video") != (outputFormat == "webm"))
            throw new Exception("Only WEBM should use yt-dlp recode; MP4 needs verified finalization.");
    }
    video.OutputFormat = "mp3";
    var audioOutputArgs = SocialVideoDownloader.BuildArguments(video, folder, folder);
    if (!audioOutputArgs.Contains("--extract-audio") && !audioOutputArgs.Contains("-x") ||
        !audioOutputArgs.Contains("--audio-format") || !audioOutputArgs.Contains("mp3"))
        throw new Exception("MP3 output must extract audio using FFmpeg.");
    video.OutputFormat = "mp4";
    var unsupportedFormatRejected = false;
    video.OutputFormat = "exe";
    try { SocialVideoDownloader.BuildArguments(video, folder, folder); }
    catch (ArgumentException) { unsupportedFormatRejected = true; }
    if (!unsupportedFormatRejected) throw new Exception("Unknown output extension must be rejected.");
    video.OutputFormat = "mp4";

    // Redownload must allow changing quality/container while preserving the
    // original completed video. The new yt-dlp output name is unique even
    // when the user chooses exactly the same format as the old download.
    var oldCopy = new DownloadJob
    {
        Url = video.Url, Folder = folder, Kind = "Video",
        VideoQuality = "Best", OutputFormat = "mp4", Parts = 32,
        Id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    };
    var newCopy = new DownloadJob
    {
        Url = oldCopy.Url, Folder = oldCopy.Folder, Kind = "Video",
        VideoQuality = "720", OutputFormat = "mkv", Parts = 8,
        IsRedownload = true, Id = "0123456789abcdef0123456789abcdef"
    };
    var originalArgs = SocialVideoDownloader.BuildArguments(oldCopy, folder, folder).ToArray();
    var againArgs = SocialVideoDownloader.BuildArguments(newCopy, folder, folder).ToArray();
    var firstTemplate = originalArgs[Array.IndexOf(originalArgs, "-o") + 1];
    var newTemplate = againArgs[Array.IndexOf(againArgs, "-o") + 1];
    if (firstTemplate.Contains("(again-", StringComparison.Ordinal) ||
        !newTemplate.Contains("(again-01234567)", StringComparison.Ordinal) ||
        newTemplate == firstTemplate ||
        !newTemplate.EndsWith(" [%(id)s].%(ext)s", StringComparison.Ordinal) ||
        !againArgs.Contains("bv*[height<=720]+ba/b[height<=720]"))
        throw new Exception("Video redownload must use selected quality and an independent output filename.");
    newCopy.OutputFormat = "mp3";
    if (!SocialVideoDownloader.BuildArguments(newCopy, folder, folder).Contains("--audio-format"))
        throw new Exception("Redownload must support MP3 audio-only output without affecting the old item.");
    if (oldCopy.OutputFormat != "mp4" || oldCopy.VideoQuality != "Best" ||
        oldCopy.IsRedownload)
        throw new Exception("Redownload must not change original media properties.");

    // Regression for the user's actual 6.1 MB corrupt MP4: ftyp + mdat,
    // moov absent. It MUST never become a green 100% completed download.
    var brokenMp4 = Path.Combine(folder, "regression-incomplete-moov.mp4");
    await File.WriteAllBytesAsync(brokenMp4, new byte[] {
        0,0,0,16, (byte)'f',(byte)'t',(byte)'y',(byte)'p',
        (byte)'i',(byte)'s',(byte)'o',(byte)'m', 0,0,0,0,
        0,0,0,0, (byte)'m',(byte)'d',(byte)'a',(byte)'t',
        1,2,3,4,5,6,7,8
    });
    if (MediaIntegrity.HasCompleteMp4Boxes(brokenMp4))
        throw new Exception("ftyp + mdat without moov must fail validation.");
    var validBoxes = Path.Combine(folder, "regression-valid-boxes.mp4");
    await File.WriteAllBytesAsync(validBoxes, new byte[] {
        0,0,0,16, (byte)'f',(byte)'t',(byte)'y',(byte)'p',
        (byte)'i',(byte)'s',(byte)'o',(byte)'m', 0,0,0,0,
        0,0,0,8, (byte)'m',(byte)'o',(byte)'o',(byte)'v',
        0,0,0,8, (byte)'m',(byte)'d',(byte)'a',(byte)'t'
    });
    if (!MediaIntegrity.HasCompleteMp4Boxes(validBoxes))
        throw new Exception("Complete top-level MP4 box structure should be recognized.");

    // Thai and other Unicode output names must be resolved from the exact
    // post-download yt-dlp receipt instead of guessing from a corrupt console.
    if (!videoArgs.Contains("--encoding") || !videoArgs.Contains("utf-8") ||
        !videoArgs.Contains("--print-to-file"))
        throw new Exception("yt-dlp must emit explicit UTF-8 output and a final-path receipt.");
    var thaiFolder = Path.Combine(folder, "ดาวน์โหลด เพลงไทย");
    Directory.CreateDirectory(thaiFolder);
    var finished = Path.Combine(thaiFolder, "ชื่อเพลงภาษาไทย [tF-PEdvMJ_o].mp4");
    await File.WriteAllBytesAsync(finished, new byte[] { 10, 20, 30 });
    var receipt = Path.Combine(folder, "yt-dlp-final-path.txt");
    await File.WriteAllTextAsync(receipt, finished + Environment.NewLine, new UTF8Encoding(false));
    if (SocialVideoDownloader.VerifyCompletedPath(thaiFolder, "���-broken.mp4", receipt) != finished ||
        SocialVideoDownloader.VerifyCompletedPath(thaiFolder, finished, null) != finished)
        throw new Exception("Unicode output path could not be recovered safely.");
    var outsider = Path.Combine(folder, "other.mp4");
    await File.WriteAllBytesAsync(outsider, new byte[] { 40 });
    await File.WriteAllTextAsync(receipt, outsider + Environment.NewLine, new UTF8Encoding(false));
    var unsafeReceiptRejected = false;
    try { SocialVideoDownloader.VerifyCompletedPath(thaiFolder, null, receipt); }
    catch (IOException) { unsafeReceiptRejected = true; }
    if (!unsafeReceiptRejected) throw new Exception("yt-dlp final path escaped the output folder.");
    File.Delete(receipt);

    // Build 4 can leave a fully downloaded MKV with a false Failed status.
    // A matching 11-character YouTube ID and the exact legacy error are
    // required; no video bytes are downloaded again during reconciliation.
    File.Delete(finished);
    var mkv = Path.Combine(thaiFolder, "เพลงภาษาไทย [tF-PEdvMJ_o].mkv");
    await File.WriteAllBytesAsync(mkv, new byte[] { 1, 2, 3, 4 });
    var oldVideo = new DownloadJob
    {
        Url = "https://youtu.be/tF-PEdvMJ_o?si=yVXyalBQnGlDsmdc",
        Folder = thaiFolder,
        Kind = "Video",
        Status = "Failed",
        Error = "ไม่พบไฟล์วิดีโอในโฟลเดอร์ปลายทางที่เลือก",
        VideoQuality = "Best"
    };
    if (SocialVideoDownloader.FindCompletedYouTubeOutput(oldVideo.Url, thaiFolder) != mkv ||
        !SocialVideoDownloader.TryRecoverLegacyCompletedJob(oldVideo) ||
        oldVideo.Status != "Completed" || oldVideo.Error.Length != 0 ||
        oldVideo.CompletedPath != mkv || oldVideo.VideoPercent != 100 ||
        oldVideo.Name != Path.GetFileName(mkv) || oldVideo.DownloadedBytes != 4)
        throw new Exception("Downloaded MKV must reconcile with exact YouTube ID, no re-download.");
    var unrelated = new DownloadJob
    {
        Url = oldVideo.Url, Folder = thaiFolder, Kind = "Video",
        Status = "Failed", Error = "HTTP 403"
    };
    if (SocialVideoDownloader.TryRecoverLegacyCompletedJob(unrelated))
        throw new Exception("Actual download failure must not be marked completed.");
    var duplicateMkv = Path.Combine(thaiFolder, "ชื่ออีกชุด [tF-PEdvMJ_o].mp4");
    await File.WriteAllBytesAsync(duplicateMkv, new byte[] { 8, 9 });
    if (SocialVideoDownloader.FindCompletedYouTubeOutput(oldVideo.Url, thaiFolder) is not null)
        throw new Exception("Ambiguous matching video IDs must not be auto-reconciled.");
    File.Delete(duplicateMkv);
    if (SocialVideoDownloader.FindCompletedYouTubeOutput(
            "https://youtu.be/AAAAAAAAAAA", thaiFolder) is not null)
        throw new Exception("Unrelated video IDs must not be auto-reconciled.");

    video.VideoQuality = "AudioMP3";
    var mp3Args = SocialVideoDownloader.BuildArguments(video, folder, folder);
    if (!mp3Args.Contains("--audio-format") || !mp3Args.Contains("mp3"))
        throw new Exception("MP3 extraction args missing.");

    // The requested machine-wide installation must not fall back into LocalAppData.
    var expectedProgramFilesExe = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
        "X-Stage", "Download Manager", "XStageDownloadManager.exe");
    if (!string.Equals(SelfUpdater.InstalledProgramFilesExe, expectedProgramFilesExe,
                       StringComparison.OrdinalIgnoreCase))
        throw new Exception("Updater restart path must target the Program Files installation.");
    var installerRecipe = File.ReadAllText(
        Path.Combine("download-manager", "installer", "XStageDownloadManager.iss"));
    if (!installerRecipe.Contains(@"DefaultDirName={autopf}\X-Stage\Download Manager") ||
        !installerRecipe.Contains("PrivilegesRequired=admin") ||
        !installerRecipe.Contains("UsePreviousAppDir=no") ||
        !installerRecipe.Contains("DisableDirPage=yes"))
        throw new Exception("Installer must request UAC and use Program Files, not a previous per-user directory.");

    // Update checks must compare semantic versions and ignore unsigned/unverified feeds.
    var filename = "X-Stage-Download-Manager-v0.2.20-build23-win-x64-Setup.exe";
    var json = System.Text.Json.JsonSerializer.Serialize(new
    {
        available = true, channel = "preview", version = "0.2.20", build = 23,
        file = filename, sha256 = new string('a', 64), size_bytes = 250_000_000L,
        download_url = "https://github.com/webbase-x/xstage/releases/download/xstage-download-manager-v0.2.20-build23-preview/" + filename
    });
    // Compare against the compiled application version, not a former release.
    // A version bump must not break otherwise valid update security tests.
    var installedVersion = Version.Parse(UpdateChecker.CurrentVersion);
    var nextPatch = new Version(installedVersion.Major, installedVersion.Minor,
        checked(installedVersion.Build + 1)).ToString();
    var previousPatch = installedVersion.Build > 0
        ? new Version(installedVersion.Major, installedVersion.Minor,
            installedVersion.Build - 1).ToString()
        : null;
    if (UpdateChecker.Parse(json) is not { Version: "0.2.20", Build: 23 } ||
        UpdateChecker.IsNewer(UpdateChecker.CurrentVersion, UpdateChecker.CurrentBuild) ||
        UpdateChecker.IsNewer(UpdateChecker.CurrentVersion, UpdateChecker.CurrentBuild - 1) ||
        !UpdateChecker.IsNewer(UpdateChecker.CurrentVersion, checked(UpdateChecker.CurrentBuild + 1)) ||
        !UpdateChecker.IsNewer(nextPatch, 1) ||
        (previousPatch is not null && UpdateChecker.IsNewer(previousPatch, int.MaxValue)) ||
        UpdateChecker.IsNewer("0.1.1", 2) ||
        UpdateChecker.IsNewer("0.2.1", 4))
        throw new Exception("EXE-only manifest and version comparison failed.");
    if (UpdateChecker.Parse("{broken") is not null ||
        UpdateChecker.Parse(new string('x', 65537)) is not null ||
        UpdateChecker.Parse("\uFEFF" + json) is null)
        throw new Exception("Update manifest must reject malformed/oversized feeds and accept a UTF-8 BOM.");
    if (UpdateChecker.Parse(json.Replace("github.com", "untrusted.test")) is not null ||
        UpdateChecker.Parse(json.Replace(new string('a', 64), "bad")) is not null)
        throw new Exception("Untrusted update feeds must be rejected.");
    var sampleId = new string('a', 32);
    if (!BrowserIntegration.IsValidExtensionId(sampleId) ||
        BrowserIntegration.IsValidExtensionId(new string('z', 32)) ||
        !BrowserIntegration.BuildNativeHostManifest(@"C:\Test\XStageDownloadManager.exe", new[] { sampleId })
            .Contains("chrome-extension://" + sampleId + "/", StringComparison.Ordinal))
        throw new Exception("Native Chrome/Edge extension IDs and allowed origins failed.");
    var isolatedEngineData = Path.Combine(folder, "isolated-engine");
    var manager = new DownloadEngine(isolatedEngineData);
    var driveShare = DownloadEngine.NormalizeDriveFileUrl(new Uri("https://drive.google.com/file/d/AbC_123/view?resourcekey=0-test"));
    if (driveShare.AbsoluteUri != "https://drive.google.com/uc?export=download&id=AbC_123&resourcekey=0-test")
        throw new Exception("Drive share URL normalization failed");
    if (DownloadEngine.NormalizeDriveFileUrl(new Uri("https://drive.google.com/open?id=AbC_123")).AbsoluteUri !=
        "https://drive.google.com/uc?export=download&id=AbC_123")
        throw new Exception("Drive open URL normalization failed");
    if (DownloadEngine.NormalizeDriveFileUrl(new Uri("https://example.com/file/d/AbC_123/view")).Host != "example.com")
        throw new Exception("Non-Drive URL changed");
    try
    {
        DownloadEngine.NormalizeDriveFileUrl(new Uri("https://drive.google.com/drive/folders/AbC_123"));
        throw new Exception("Drive folder accepted as a file");
    }
    catch (ArgumentException) { }
    if (DownloadEngine.TryParseUrl(null!, out _) ||
        DownloadEngine.TryParseUrl("", out _) ||
        DownloadEngine.TryParseUrl("  ", out _) ||
        !DownloadEngine.TryParseUrl("  https://example.com/file  ", out var trimmedUrl) ||
        trimmedUrl?.AbsoluteUri != "https://example.com/file")
        throw new Exception("Captured URL parser must reject empty input and trim valid URLs.");
    if (DownloadEngine.TryParseUrl("file:///C:/Windows/system.ini", out _) ||
        DownloadEngine.TryParseUrl("ftp://localhost/file", out _) ||
        DownloadEngine.TryParseUrl("https://user:pass@example.com/file", out _))
        throw new Exception("Non-HTTP or credential URLs must be rejected.");

    var queueUi = File.ReadAllText(Path.Combine("download-manager", "MainForm.cs"));
    var queueDialog = File.ReadAllText(Path.Combine("download-manager", "MainForm.Performance.cs"));
    var engineSource = File.ReadAllText(Path.Combine("download-manager", "DownloadEngine.cs"));
    var buildWorkflow = File.ReadAllText(Path.Combine(".github", "workflows",
        "build-xstage-download-manager.yml"));
    if (!queueUi.Contains("CreateJobQueue(job)") ||
        !queueUi.Contains("AssignJobQueue(job, queueName)") ||
        !queueUi.Contains("string.IsNullOrWhiteSpace(job.QueueName) ? \"ทั่วไป\" : job.QueueName.Trim()") ||
        !queueDialog.Contains("_engine.SetJobQueue(job, queueName)") ||
        !queueDialog.Contains("MaxLength = 64"))
        throw new Exception("Named queue context menu and canonical durable assignment UI missing.");
    if (!engineSource.Contains("public string Save()") ||
        engineSource.Contains("Save();\n        if (LastStorageError.Length > 0)") ||
        engineSource.Contains("Save();\r\n        if (LastStorageError.Length > 0)"))
        throw new Exception("Mutable settings must use the result of their exact SQLite save attempt.");
    if (!buildWorkflow.Contains("Report CI-only candidate build") ||
        !buildWorkflow.Contains("startsWith(github.event.head_commit.message, 'release(download-manager):')") ||
        !buildWorkflow.Contains("actions/checkout@v7") ||
        !buildWorkflow.Contains("actions/setup-dotnet@v6") ||
        !buildWorkflow.Contains("actions/setup-python@v7") ||
        !buildWorkflow.Contains("actions/upload-artifact@v7"))
        throw new Exception("Download Manager CI/release gate or current Node 24-compatible Actions regressed.");

    var queueJob = manager.Add(server.Url + "range/queue-test.bin", folder, 1);
    manager.Pause(queueJob);
    manager.SetJobQueue(queueJob, "ไฟล์เร่งด่วน");
    if (!manager.GetQueueNames().Contains("ไฟล์เร่งด่วน") ||
        new DownloadEngine(isolatedEngineData).Jobs.Single(j => j.Id == queueJob.Id).QueueName != "ไฟล์เร่งด่วน")
        throw new Exception("Named queues must persist across SQLite reopen.");
    var rejectedBlankQueue = false;
    try { manager.SetJobQueue(queueJob, "  "); }
    catch (ArgumentException) { rejectedBlankQueue = true; }
    if (!rejectedBlankQueue) throw new Exception("Blank queue name must be rejected.");
    manager.SetJobQueue(queueJob, "  คิวเอกสาร  ");
    if (queueJob.QueueName != "คิวเอกสาร" ||
        new DownloadEngine(isolatedEngineData).Jobs.Single(j => j.Id == queueJob.Id).QueueName != "คิวเอกสาร")
        throw new Exception("Queue names must be trimmed before durable SQLite persistence.");
    var rejectedLongQueue = false;
    try { manager.SetJobQueue(queueJob, new string('ก', 65)); }
    catch (ArgumentException) { rejectedLongQueue = true; }
    if (!rejectedLongQueue || queueJob.QueueName != "คิวเอกสาร")
        throw new Exception("Invalid queue names must not mutate existing assignments.");
    var rejectedControlQueue = false;
    try { manager.SetJobQueue(queueJob, "queue" + (char)10 + "invalid"); }
    catch (ArgumentException) { rejectedControlQueue = true; }
    if (!rejectedControlQueue || queueJob.QueueName != "คิวเอกสาร")
        throw new Exception("Control characters must not mutate queue assignments.");


    // File speed caps must persist without altering the job's queue or priority.
    manager.SetFileSpeedLimit(queueJob, 256);
    var reopenedSpeed = new DownloadEngine(isolatedEngineData).Jobs.Single(j => j.Id == queueJob.Id);
    if (queueJob.FileSpeedLimitKib != 256 || reopenedSpeed.FileSpeedLimitKib != 256 ||
        reopenedSpeed.QueueName != queueJob.QueueName)
        throw new Exception("Per-file speed cap must survive SQLite reopen without changing queue.");
    manager.SetFileSpeedLimit(queueJob, 0);
    if (new DownloadEngine(isolatedEngineData).Jobs.Single(j => j.Id == queueJob.Id).FileSpeedLimitKib != 0)
        throw new Exception("Removing a per-file speed cap must persist.");

    // Priority updates must persist across SQLite reopen without changing queue membership.
    var previousQueueName = queueJob.QueueName;
    manager.SetJobPriority(queueJob, 2);
    var reopenedPriority = new DownloadEngine(isolatedEngineData).Jobs.Single(j => j.Id == queueJob.Id);
    if (queueJob.Priority != 2 || reopenedPriority.Priority != 2 ||
        reopenedPriority.QueueName != previousQueueName)
        throw new Exception("Priority updates must survive SQLite reopen without changing queue assignments.");
    manager.SetJobPriority(queueJob, 1);
    if (new DownloadEngine(isolatedEngineData).Jobs.Single(j => j.Id == queueJob.Id).Priority != 1)
        throw new Exception("Restored job priority must persist after SQLite reopen.");

    // Queue grouping is case-insensitive, but assignments remain per-job and
    // may not be changed through a foreign engine instance.
    var secondQueueJob = manager.Add(server.Url + "range/queue-second.bin", folder, 1);
    manager.Pause(secondQueueJob);
    manager.SetJobQueue(secondQueueJob, "คิวเอกสาร");
    if (manager.GetQueueNames().Count(n => n == "คิวเอกสาร") != 1)
        throw new Exception("Jobs sharing a queue must not create duplicate queue names.");
    manager.SetJobQueue(secondQueueJob, "คิวอื่น");
    if (queueJob.QueueName != "คิวเอกสาร" ||
        new DownloadEngine(isolatedEngineData).Jobs.Single(j => j.Id == queueJob.Id).QueueName != "คิวเอกสาร")
        throw new Exception("Moving a job must not change another queue assignment.");
    var rejectedForeignJob = false;
    try { manager.SetJobQueue(new DownloadJob { Id = queueJob.Id }, "คิวปลอม"); }
    catch (ArgumentException) { rejectedForeignJob = true; }
    if (!rejectedForeignJob)
        throw new Exception("Foreign job objects must not mutate persisted queues.");

    // Renaming a queue changes every member in one persisted checkpoint and
    // must reject accidental merges with a different existing queue.
    manager.SetJobQueue(secondQueueJob, "คิวเอกสาร");
    if (manager.RenameQueue(" คิวเอกสาร ", "คิวเอกสารใหม่") != 2 ||
        queueJob.QueueName != "คิวเอกสารใหม่" ||
        secondQueueJob.QueueName != "คิวเอกสารใหม่")
        throw new Exception("Renaming a queue must update all its members.");
    var reopenedRenamed = new DownloadEngine(isolatedEngineData);
    if (reopenedRenamed.Jobs.Count(j => j.QueueName == "คิวเอกสารใหม่") != 2)
        throw new Exception("Queue rename must survive SQLite reopen.");
    manager.SetJobQueue(secondQueueJob, "คิวอื่น");
    var rejectedMerge = false;
    try { manager.RenameQueue("คิวเอกสารใหม่", "คิวอื่น"); }
    catch (ArgumentException) { rejectedMerge = true; }
    if (!rejectedMerge || queueJob.QueueName != "คิวเอกสารใหม่")
        throw new Exception("Queue rename must not silently merge queues.");
    if (manager.RenameQueue("คิวไม่มี", "คิวใหม่") != 0)
        throw new Exception("Renaming a missing queue must not create one.");
    // Older records can have no queue name. The UI displays these as "ทั่วไป".
    // Renaming that queue must include the legacy records and persist the result.
    var unnamedJob = manager.Add(server.Url + "range/legacy-queue.bin", folder, 1);
    manager.Pause(unnamedJob);
    unnamedJob.QueueName = "";
    manager.Save();
    if (manager.RenameQueue("ทั่วไป", "คิวเริ่มต้นใหม่") < 1 ||
        unnamedJob.QueueName != "คิวเริ่มต้นใหม่" ||
        new DownloadEngine(isolatedEngineData).Jobs.Single(j => j.Id == unnamedJob.Id)
            .QueueName != "คิวเริ่มต้นใหม่")
        throw new Exception("Renaming default queue must migrate unnamed legacy jobs durably.");


    // Legacy records may carry whitespace around queue labels. The queue picker
    // must show one canonical label, matching rename and assignment semantics.
    var spacedQueueJob = manager.Add(server.Url + "range/spaced-queue.bin", folder, 1);
    manager.Pause(spacedQueueJob);
    spacedQueueJob.QueueName = "  คิวเริ่มต้นใหม่  ";
    manager.Save();
    if (manager.GetQueueNames().Count(n => n == "คิวเริ่มต้นใหม่") != 1 ||
        manager.GetQueueNames().Any(n => n != n.Trim()))
        throw new Exception("Queue list must trim and deduplicate legacy labels.");

    manager.SetDefaultParts(8);
    if (manager.DefaultParts != 8) throw new Exception("Default segment preference not saved.");
    var job = manager.Add(server.Url + "range/test%20file.bin", folder);
    if (job.Parts != 8) throw new Exception("New job must inherit default segment count.");
    if (manager.SetJobParts(job, 16)) throw new Exception("Active downloads must not be resegmented.");
    await WaitFor(() => job.Status == "Running" && Interlocked.Read(ref job.DownloadedBytes) >= 65536);
    var activeCheckpoint = new DownloadEngine(isolatedEngineData).Jobs.Single(j => j.Id == job.Id);
    if (activeCheckpoint.SegmentsUsed != 8)
        throw new Exception("Active Range transfer must persist its byte-boundary geometry before writing chunks.");
    manager.Pause(job);
    await WaitFor(() => job.Status == "Paused" && job.Cancellation is null);
    if (Interlocked.Read(ref job.DownloadedBytes) <= 0)
        throw new Exception("Test must leave partial downloaded bytes");
    var oldWorkDir = Path.Combine(job.Folder, ".xstage-downloads", job.Id);
    if (!Directory.Exists(oldWorkDir) ||
        !Directory.EnumerateFiles(oldWorkDir, "*.part").Any())
        throw new Exception("Repartition regression requires existing resumable chunk files.");
    // A previous sampling baseline must not survive a new segment geometry.
    job.PreviousBytes = 12345;
    if (!manager.SetJobParts(job, 16))
        throw new Exception("Paused download must accept a new segment count.");
    if (Directory.Exists(oldWorkDir) &&
        Directory.EnumerateFiles(oldWorkDir, "*.part").Any())
        throw new Exception("Successful repartition retained chunks with obsolete boundaries.");
    var reopenedParts = new DownloadEngine(isolatedEngineData).Jobs.Single(j => j.Id == job.Id);
    if (reopenedParts.Parts != 16 || reopenedParts.DownloadedBytes != 0 ||
        reopenedParts.SegmentsUsed != 0)
        throw new Exception("Repartition must persist new geometry before download resumes.");
    if (reopenedParts.PreviousBytes != 0 || job.PreviousBytes != 0)
        throw new Exception("Repartition must reset the persisted speed sampling baseline.");
    if (reopenedParts.Status != "Paused" ||
        reopenedParts.SegmentDownloadedBytes.Any(value => value != 0))
        throw new Exception("Repartition must persist a paused, zero-progress checkpoint.");
    if (job.Parts != 16 || job.SegmentsUsed != 0 || Interlocked.Read(ref job.DownloadedBytes) != 0)
        throw new Exception("Repartition must reset temporary pieces and progress.");
    // Simulate a locked-file cleanup failure from the prior process: the
    // new geometry is durable, but a stale old-format chunk survives on disk.
    // The worker must discard it rather than append corrupt bytes.
    Directory.CreateDirectory(oldWorkDir);
    await File.WriteAllBytesAsync(Path.Combine(oldWorkDir, "00.part"),
        Enumerable.Repeat((byte)0xEE, 4096).ToArray());
    manager.Start(job);
    await WaitFor(() => job.Status is "Completed" or "Failed");
    if (job.Status != "Completed") throw new Exception("Range resume failed: " + job.Error);
    if (!job.SupportsRanges) throw new Exception("HTTP Range was not detected");
    if (job.SegmentsUsed != 16) throw new Exception("Requested 16 ranges must be used for a sufficiently large file.");
    // The final archive must be assembled from the same persisted Range
    // geometry, not from a changed UI/default preference.
    if (new FileInfo(job.CompletedPath).Length != bytes.Length)
        throw new Exception("Merged Range output has incorrect archive length.");
    if (!bytes.SequenceEqual(await File.ReadAllBytesAsync(job.CompletedPath)))
        throw new Exception("Range resume produced incorrect bytes");

    // A genuine adapter outage uses the same cancel-safe workers as Pause,
    // but only the outage flag authorizes automatic continuation.
    var networkJob = manager.Add(server.Url + "range/network-recovery.bin", folder, 8);
    await WaitFor(() => networkJob.Status == "Running" &&
        Interlocked.Read(ref networkJob.DownloadedBytes) >= 65536);
    manager.PauseForNetworkOutage();
    await WaitFor(() => networkJob.Status == "Paused" && networkJob.Cancellation is null);
    if (!networkJob.ResumeWhenNetworkReturns)
        throw new Exception("Network interruption must preserve automatic recovery intent.");
    manager.TryResumeNetworkInterrupted();
    await WaitFor(() => networkJob.Status is "Completed" or "Failed");
    if (networkJob.Status != "Completed" ||
        !bytes.SequenceEqual(await File.ReadAllBytesAsync(networkJob.CompletedPath)))
        throw new Exception("Network restoration must preserve verified original bytes: " +
            networkJob.Error);

    // One-part Range transfers must remain byte-identical and never be
    // inflated to the default eight-way configuration. Together with the
    // eight-way resume and 32-way test below this covers 1/8/32 settings.
    var singlePart = manager.Add(server.Url + "range/one-connection.bin", folder, 1);
    await WaitFor(() => singlePart.Status is "Completed" or "Failed");
    if (singlePart.Status != "Completed" || singlePart.Parts != 1 ||
        singlePart.SegmentsUsed != 1 ||
        !bytes.SequenceEqual(await File.ReadAllBytesAsync(singlePart.CompletedPath)))
        throw new Exception("One-part HTTP Range download produced incorrect bytes or segment count: " +
                            singlePart.Error);

    // Exercise eight fresh HTTP Range requests independently of the
    // repartition/resume test; verify the merged bytes before completion.
    var eightParts = manager.Add(server.Url + "range/eight-connections.bin", folder, 8);
    await WaitFor(() => eightParts.Status is "Completed" or "Failed");
    if (eightParts.Status != "Completed" || eightParts.Parts != 8 ||
        eightParts.SegmentsUsed != 8 ||
        !bytes.SequenceEqual(await File.ReadAllBytesAsync(eightParts.CompletedPath)))
        throw new Exception("Eight-connection HTTP Range transfer failed byte integrity: " +
                            eightParts.Error);

    var maxParts = manager.Add(server.Url + "range/32-connections.bin", folder, 32);
    await WaitFor(() => maxParts.Status is "Completed" or "Failed");
    if (maxParts.Status != "Completed") throw new Exception("32-connection download failed: " + maxParts.Error);
    if (maxParts.SegmentsUsed != 32)
        throw new Exception("32 HTTP ranges were not used for a sufficiently large file.");
    if (!bytes.SequenceEqual(await File.ReadAllBytesAsync(maxParts.CompletedPath)))
        throw new Exception("32-connection merge corrupted the output.");
    // A raw GitHub Actions CDN URL only reveals an opaque artifact storage key.
    // A readable Content-Disposition must win; otherwise use an explicitly
    // descriptive fallback rather than inventing the artifact's original title.
    const string actionsCdn =
        "https://productionresults19.blob.core.windows.net/actions-results/job-123/" +
        "artifacts/e1fc3003c714e6d6e2fd0bc1e9f6865cf491f3ab";
    using (var noName = new HttpResponseMessage(HttpStatusCode.OK)
    {
        Content = new ByteArrayContent(Array.Empty<byte>()),
        RequestMessage = new HttpRequestMessage(HttpMethod.Get, actionsCdn)
    })
    {
        noName.Content.Headers.ContentType =
            new System.Net.Http.Headers.MediaTypeHeaderValue("application/zip");
        if (DownloadFileNaming.Resolve(actionsCdn, noName) !=
            "GitHub-Actions-Artifact-e1fc3003.zip")
            throw new Exception("Opaque GitHub Actions storage key must have a readable .zip fallback.");

        noName.Content.Headers.ContentDisposition =
            new System.Net.Http.Headers.ContentDispositionHeaderValue("attachment")
            {
                FileName = "งานสร้าง-XStage-รุ่นล่าสุด.zip"
            };
        if (DownloadFileNaming.Resolve(actionsCdn, noName) != "งานสร้าง-XStage-รุ่นล่าสุด.zip")
            throw new Exception("Human-readable Content-Disposition must override Actions CDN UUID.");

        noName.Content.Headers.ContentDisposition.FileName =
            "e1fc3003c714e6d6e2fd0bc1e9f6865cf491f3ab.zip";
        if (DownloadFileNaming.Resolve(actionsCdn, noName) !=
            "GitHub-Actions-Artifact-e1fc3003.zip")
            throw new Exception("Opaque Content-Disposition must not hide readable artifact fallback.");
    }
    using (var namedOrigin = new HttpResponseMessage(HttpStatusCode.OK)
    {
        Content = new ByteArrayContent(Array.Empty<byte>()),
        RequestMessage = new HttpRequestMessage(HttpMethod.Get,
            "https://example.com/media/b816293394e55bcf1b0a10ce78e2a370")
    })
    {
        namedOrigin.Content.Headers.ContentDisposition =
            new System.Net.Http.Headers.ContentDispositionHeaderValue("attachment")
            {
                FileName = "e1fc3003c714e6d6e2fd0bc1e9f6865cf491f3ab.zip"
            };
        if (DownloadFileNaming.Resolve(
            "https://example.com/media/รายงานประจำปี.zip", namedOrigin) !=
            "รายงานประจำปี.zip")
            throw new Exception("Readable original URL must override opaque server disposition name.");
    }

    // CDN redirects often use UUID filenames with no extension. The
    // Content-Disposition filename is authoritative, regardless of URL name.
    const string opaqueId = "5aef5bed-774f-4423-b75d-78e1f2b9a60e";
    var githubAsset = manager.Add(server.Url + "range/" + opaqueId + "?sp=token", folder, 8);
    await WaitFor(() => githubAsset.Status is "Completed" or "Failed");
    if (githubAsset.Status != "Completed" ||
        githubAsset.Name != "X-Stage-Song-Studio-Pro-v0.1.22-preview.exe" ||
        Path.GetFileName(githubAsset.CompletedPath) != githubAsset.Name ||
        !bytes.SequenceEqual(await File.ReadAllBytesAsync(githubAsset.CompletedPath)))
        throw new Exception("Content-Disposition filename must override opaque GitHub UUID URL.");
    var originalGithubPath = githubAsset.CompletedPath;
    var renamedPath = manager.RenameCompletedFile(githubAsset, "ไฟล์ทดสอบที่เปลี่ยนชื่อ");
    if (Path.GetFileName(renamedPath) != "ไฟล์ทดสอบที่เปลี่ยนชื่อ.exe" ||
        !File.Exists(renamedPath) || File.Exists(originalGithubPath) ||
        !bytes.SequenceEqual(await File.ReadAllBytesAsync(renamedPath)))
        throw new Exception("Rename must update the real file and keep the original extension.");
    var invalidExtensionBlocked = false;
    try { manager.RenameCompletedFile(githubAsset, "ไฟล์ใหม่.txt"); }
    catch (ArgumentException) { invalidExtensionBlocked = true; }
    if (!invalidExtensionBlocked || !File.Exists(renamedPath))
        throw new Exception("Rename must reject a changed file type and preserve original data.");
    await File.WriteAllBytesAsync(Path.Combine(folder, "ชื่อไฟล์ซ้ำ.exe"), new byte[] { 11, 22 });
    var uniqueRename = manager.RenameCompletedFile(githubAsset, "ชื่อไฟล์ซ้ำ.exe");
    if (Path.GetFileName(uniqueRename) != "ชื่อไฟล์ซ้ำ (1).exe" ||
        !File.Exists(uniqueRename) ||
        !(await File.ReadAllBytesAsync(Path.Combine(folder, "ชื่อไฟล์ซ้ำ.exe")))
            .SequenceEqual(new byte[] { 11, 22 }))
        throw new Exception("Filename collision during rename must never overwrite another file.");

    // RFC 5987 filename* should preserve Thai characters and a real extension.
    var thaiNameJob = manager.Add(server.Url + "range/thaifileuuid", folder, 8);
    await WaitFor(() => thaiNameJob.Status is "Completed" or "Failed");
    if (thaiNameJob.Status != "Completed" ||
        thaiNameJob.Name != "ทดสอบ.pdf" ||
        !File.Exists(thaiNameJob.CompletedPath))
        throw new Exception("filename*=UTF-8 Thai filename was not decoded.");

    // If no name is provided, an explicit media type can restore the extension.
    var mimeJob = manager.Add(server.Url + "plain/mimeopaqueuuid", folder, 8);
    await WaitFor(() => mimeJob.Status is "Completed" or "Failed");
    if (mimeJob.Status != "Completed" || mimeJob.Name != "mimeopaqueuuid.pdf" ||
        !File.Exists(mimeJob.CompletedPath))
        throw new Exception("Known response MIME should provide a missing extension.");

    // With generic application/octet-stream, use only a strong file signature.
    var legacyPath = Path.Combine(folder, "older-uuid");
    var peBytes = new byte[256];
    peBytes[0] = (byte)'M'; peBytes[1] = (byte)'Z';
    peBytes[0x3c] = 0x80;
    peBytes[0x80] = (byte)'P'; peBytes[0x81] = (byte)'E';
    await File.WriteAllBytesAsync(legacyPath, peBytes);
    var legacy = new DownloadJob
    {
        Name = "older-uuid", CompletedPath = legacyPath,
        Folder = folder, Kind = "File", Status = "Completed"
    };
    if (!DownloadFileNaming.TryRepairCompletedFile(legacy) ||
        !legacy.CompletedPath.EndsWith("older-uuid.exe", StringComparison.Ordinal) ||
        legacy.Name != "older-uuid.exe" ||
        !File.Exists(legacy.CompletedPath) || File.Exists(legacyPath))
        throw new Exception("Completed unsigned legacy PE file must recover EXE extension.");

    var unknownPath = Path.Combine(folder, "unknown-uuid");
    await File.WriteAllBytesAsync(unknownPath, new byte[] { 1, 2, 3, 4 });
    var unknown = new DownloadJob
    {
        Name = "unknown-uuid", CompletedPath = unknownPath,
        Folder = folder, Kind = "File", Status = "Completed"
    };
    if (DownloadFileNaming.TryRepairCompletedFile(unknown) ||
        !File.Exists(unknownPath) || unknown.Name != "unknown-uuid")
        throw new Exception("Unknown file must never get a guessed extension.");

    if (!DownloadFileNaming.CleanName(new string('x', 175) + ".exe").EndsWith(".exe",
            StringComparison.Ordinal))
        throw new Exception("Long file names must retain their extension.");

    // An interrupted EXE transfer must resume from a verified-length partial,
    // rather than discard 200 MB and start from zero on every network drop.
    var updaterSha = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    var updateTarget = Path.Combine(folder, "integration-update-setup.exe");
    await File.WriteAllBytesAsync(updateTarget + ".partial",
        bytes.AsMemory(0, 1024 * 1024).ToArray());
    var updatedFile = await SelfUpdater.DownloadAndVerifyPayloadAsync(
        new Uri(server.Url + "range/update-setup.exe"), updateTarget, updaterSha, bytes.Length);
    if (updatedFile != updateTarget || !File.Exists(updatedFile) ||
        !bytes.SequenceEqual(await File.ReadAllBytesAsync(updatedFile)) ||
        File.Exists(updateTarget + ".partial"))
        throw new Exception("Updater HTTP 206 Range resume and SHA-256 verification failed.");

    // Some CDNs ignore Range. 200 must replace the partial file, not append it.
    var noRangeTarget = Path.Combine(folder, "integration-update-plain.exe");
    await File.WriteAllBytesAsync(noRangeTarget + ".partial", bytes.AsMemory(0, 300000).ToArray());
    await SelfUpdater.DownloadAndVerifyPayloadAsync(
        new Uri(server.Url + "plain/update.exe"), noRangeTarget, updaterSha, bytes.Length);
    if (!bytes.SequenceEqual(await File.ReadAllBytesAsync(noRangeTarget)))
        throw new Exception("Updater must restart from byte zero when server ignores Range.");

    // Simulate a disconnection on the first attempt. The updater should keep
    // .partial and recover using Range on its internal retry.
    var unstableTarget = Path.Combine(folder, "integration-update-retry.exe");
    await SelfUpdater.DownloadAndVerifyPayloadAsync(
        new Uri(server.Url + "unstable/setup.exe"), unstableTarget, updaterSha, bytes.Length);
    if (!bytes.SequenceEqual(await File.ReadAllBytesAsync(unstableTarget)))
        throw new Exception("Updater must survive a dropped CDN stream and retry.");

    if (!await BrowserCaptureProbe.IsUnauthenticatedFileAsync(server.Url + "range/test-file.bin") ||
        !await BrowserCaptureProbe.IsUnauthenticatedFileAsync(server.Url + "plain/test-file.bin") ||
        await BrowserCaptureProbe.IsUnauthenticatedFileAsync("https://www.youtube.com/watch?v=123"))
        throw new Exception("Browser capture must probe accessible direct files without cookies.");
    manager.ConfigurePerformance(3, 2, 256);
    var reloadedPerf = new DownloadEngine(isolatedEngineData);
    if (reloadedPerf.MaxConcurrentJobs != 3 ||
        reloadedPerf.MaxJobsPerHost != 2 ||
        reloadedPerf.GlobalLimitKib != 256)
        throw new Exception("Engine must restore global concurrency and bandwidth settings.");
    manager.ConfigurePerformance(2, 2, 0); // Restore normal high-speed transfer tests.
    manager.SetRetryLimit(7);
    if (new DownloadEngine(isolatedEngineData).MaxRetryCount != 7)
        throw new Exception("User-configured retry limit must persist in SQLite.");
    var flaky = manager.Add(server.Url + "flaky-range/disconnected.bin", folder, 8);
    await WaitFor(() => flaky.Status is "Completed" or "Failed");
    if (flaky.Status != "Completed" ||
        !bytes.SequenceEqual(await File.ReadAllBytesAsync(flaky.CompletedPath)))
        throw new Exception("Interrupted Range chunk did not resume from its saved byte offset: " +
                            flaky.Error);
    var toggle = manager.Add(server.Url + "range-toggle/disabled.bin", folder, 8);
    await WaitFor(() => toggle.Status is "Completed" or "Failed");
    if (toggle.Status != "Completed" || toggle.SupportsRanges ||
        !bytes.SequenceEqual(await File.ReadAllBytesAsync(toggle.CompletedPath)))
        throw new Exception("Server ignoring Range after probe must safely fall back to HTTP 200: " +
                            toggle.Error);
    var busy = manager.Add(server.Url + "busy-once/retry.bin", folder, 4);
    await WaitFor(() => busy.Status is "Completed" or "Failed");
    if (busy.Status != "Completed" ||
        !bytes.SequenceEqual(await File.ReadAllBytesAsync(busy.CompletedPath)))
        throw new Exception("HTTP 503 Retry-After retry failed: " + busy.Error);
    var flakySingle = manager.Add(server.Url + "flaky-single/retry.bin", folder);
    await WaitFor(() => flakySingle.Status is "Completed" or "Failed");
    if (flakySingle.Status != "Completed" ||
        !bytes.SequenceEqual(await File.ReadAllBytesAsync(flakySingle.CompletedPath)))
        throw new Exception("Non-Range transfer must retry safely from byte zero: " +
                            flakySingle.Error);
    var plain = manager.Add(server.Url + "plain/test%20file.bin", folder);
    await WaitFor(() => plain.Status is "Completed" or "Failed");
    if (plain.Status != "Completed") throw new Exception("Single stream failed: " + plain.Error);
    if (plain.SupportsRanges) throw new Exception("Non-Range server was misclassified");
    if (!bytes.SequenceEqual(await File.ReadAllBytesAsync(plain.CompletedPath)))
        throw new Exception("Single stream incorrect bytes");
    if (job.CompletedPath == plain.CompletedPath || !File.Exists(job.CompletedPath))
        throw new Exception("Existing output must not be overwritten");
    if (!manager.Remove(job) || !File.Exists(job.CompletedPath))
        throw new Exception("Removing history must not delete completed files");
    if (new DownloadEngine(isolatedEngineData).DefaultParts != 8)
        throw new Exception("Default segment count must persist across restarts.");
    Console.WriteLine("PASS: HTTP Range segments, verified EXE update resume, dropped-stream retry, SHA-256 verification, HTTP 200 fallback, settings persistence and safe removal.");
}
finally
{
    try { Directory.Delete(folder, true); } catch { }
}

static async Task WaitFor(Func<bool> predicate, int timeoutMs = 30000)
{
    var until = DateTime.UtcNow.AddMilliseconds(timeoutMs);
    while (!predicate())
    {
        if (DateTime.UtcNow > until) throw new TimeoutException("Download test timed out");
        await Task.Delay(25);
    }
}

sealed class FileServer : IDisposable
{
    private readonly byte[] _data;
    private readonly TcpListener _listener;
    private readonly CancellationTokenSource _cts = new();
    private int _interruptedOnce;
    private int _flakyRangeOnce;
    private int _flakySingleOnce;
    private int _busyOnce;
    public string Url { get; }
    public FileServer(byte[] data)
    {
        _data = data;
        _listener = new TcpListener(IPAddress.Loopback, 0);
        _listener.Start();
        Url = "http://127.0.0.1:" + ((IPEndPoint)_listener.LocalEndpoint).Port + "/";
        _ = Serve();
    }
    private async Task Serve()
    {
        while (!_cts.IsCancellationRequested)
        {
            try
            {
                var client = await _listener.AcceptTcpClientAsync(_cts.Token);
                _ = Task.Run(() => Handle(client));
            }
            catch (OperationCanceledException) { return; }
            catch (ObjectDisposedException) { return; }
        }
    }
    private async Task Handle(TcpClient client)
    {
        using (client)
        {
            try
            {
                var stream = client.GetStream();
                using var reader = new StreamReader(stream, Encoding.ASCII, false, 1024, true);
                var first = await reader.ReadLineAsync();
                var path = first?.Split(' ').Skip(1).FirstOrDefault() ?? "";
                var headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                string? line;
                while (!string.IsNullOrEmpty(line = await reader.ReadLineAsync()))
                {
                    var split = line.IndexOf(':');
                    if (split > 0) headers[line[..split].Trim()] = line[(split + 1)..].Trim();
                }
                if (path.StartsWith("/busy-once/") &&
                    Interlocked.Exchange(ref _busyOnce, 1) == 0)
                {
                    await stream.WriteAsync(Encoding.ASCII.GetBytes(
                        "HTTP/1.1 503 Service Unavailable\r\n" +
                        "Retry-After: 1\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"));
                    return;
                }
                var supportsRange = path.StartsWith("/range/") ||
                    path.StartsWith("/unstable/") ||
                    path.StartsWith("/flaky-range/") ||
                    path.StartsWith("/busy-once/");
                if (path.StartsWith("/range-toggle/"))
                    supportsRange = headers.TryGetValue("Range", out var probeRange) &&
                        probeRange == "bytes=0-0";
                var interrupt = path.StartsWith("/unstable/") &&
                    Interlocked.Exchange(ref _interruptedOnce, 1) == 0;
                var flakyRange = path.StartsWith("/flaky-range/") &&
                    headers.TryGetValue("Range", out var rangeValue) &&
                    rangeValue != "bytes=0-0" &&
                    Interlocked.Exchange(ref _flakyRangeOnce, 1) == 0;
                var flakySingle = path.StartsWith("/flaky-single/") &&
                    Interlocked.Exchange(ref _flakySingleOnce, 1) == 0;
                var begin = 0;
                var end = _data.Length - 1;
                var code = "200 OK";
                if (supportsRange && headers.TryGetValue("Range", out var range) && range.StartsWith("bytes="))
                {
                    var pieces = range[6..].Split('-');
                    begin = int.Parse(pieces[0]);
                    end = string.IsNullOrEmpty(pieces[1]) ? end : int.Parse(pieces[1]);
                    code = "206 Partial Content";
                }
                var length = end - begin + 1;
                var contentType = path.StartsWith("/plain/mimeopaqueuuid")
                    ? "application/pdf" : "application/octet-stream";
                var attachment = path.StartsWith("/range/5aef5bed-")
                    ? "Content-Disposition: attachment; filename=\"X-Stage-Song-Studio-Pro-v0.1.22-preview.exe\"\r\n"
                    : path.StartsWith("/range/thaifileuuid")
                        ? "Content-Disposition: attachment; filename*=UTF-8''%E0%B8%97%E0%B8%94%E0%B8%AA%E0%B8%AD%E0%B8%9A.pdf\r\n"
                        : "";
                var response = "HTTP/1.1 " + code + "\r\n" +
                    "Content-Type: " + contentType + "\r\n" +
                    attachment +
                    "Content-Length: " + length + "\r\n" +
                    "ETag: \"xstage-test-v1\"\r\n" +
                    "Last-Modified: Wed, 21 Oct 2015 07:28:00 GMT\r\n" +
                    (code.StartsWith("206") ? "Content-Range: bytes " + begin + "-" + end + "/" + _data.Length + "\r\n" : "") +
                    "Connection: close\r\n\r\n";
                await stream.WriteAsync(Encoding.ASCII.GetBytes(response));
                var offset = begin;
                while (offset <= end)
                {
                    var chunk = Math.Min(8192, end - offset + 1);
                    await stream.WriteAsync(_data.AsMemory(offset, chunk));
                    offset += chunk;
                    if ((interrupt || flakyRange || flakySingle) &&
                        offset - begin >= 160 * 1024) break;
                    await Task.Delay(2);
                }
            }
            catch (IOException) { /* A paused download intentionally closes its socket. */ }
            catch (SocketException) { }
            catch (ObjectDisposedException) { }
        }
    }
    public void Dispose() { _cts.Cancel(); _listener.Stop(); _cts.Dispose(); }
}
