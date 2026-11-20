using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using XStageDownloadManager;

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

var bytes = new byte[9 * 1024 * 1024];
for (int i = 0; i < bytes.Length; i++) bytes[i] = (byte)(i % 251);
using var server = new FileServer(bytes);
var folder = Path.Combine(Path.GetTempPath(), "xstage-dm-test-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(folder);
try
{
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
    var filename = "X-Stage-Download-Manager-v0.2.17-build20-win-x64-Setup.exe";
    var json = System.Text.Json.JsonSerializer.Serialize(new
    {
        available = true, channel = "preview", version = "0.2.17", build = 20,
        file = filename, sha256 = new string('a', 64), size_bytes = 250_000_000L,
        download_url = "https://github.com/webbase-x/xstage/releases/download/xstage-download-manager-v0.2.17-build20-preview/" + filename
    });
    if (UpdateChecker.Parse(json) is not { Version: "0.2.17", Build: 20 } ||
        !UpdateChecker.IsNewer("0.2.17", 20) || UpdateChecker.IsNewer("0.1.1", 2) ||
        UpdateChecker.IsNewer("0.2.1", 4))
        throw new Exception("EXE-only manifest and version comparison failed.");
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
    if (DownloadEngine.TryParseUrl("file:///C:/Windows/system.ini", out _) ||
        DownloadEngine.TryParseUrl("ftp://localhost/file", out _) ||
        DownloadEngine.TryParseUrl("https://user:pass@example.com/file", out _))
        throw new Exception("Non-HTTP or credential URLs must be rejected.");

    manager.SetDefaultParts(8);
    if (manager.DefaultParts != 8) throw new Exception("Default segment preference not saved.");
    var job = manager.Add(server.Url + "range/test%20file.bin", folder);
    if (job.Parts != 8) throw new Exception("New job must inherit default segment count.");
    if (manager.SetJobParts(job, 16)) throw new Exception("Active downloads must not be resegmented.");
    await WaitFor(() => job.Status == "Running" && Interlocked.Read(ref job.DownloadedBytes) >= 65536);
    manager.Pause(job);
    await WaitFor(() => job.Status == "Paused" && job.Cancellation is null);
    if (Interlocked.Read(ref job.DownloadedBytes) <= 0)
        throw new Exception("Test must leave partial downloaded bytes");
    if (!manager.SetJobParts(job, 16))
        throw new Exception("Paused download must accept a new segment count.");
    if (job.Parts != 16 || job.SegmentsUsed != 0 || Interlocked.Read(ref job.DownloadedBytes) != 0)
        throw new Exception("Repartition must reset temporary pieces and progress.");
    manager.Start(job);
    await WaitFor(() => job.Status is "Completed" or "Failed");
    if (job.Status != "Completed") throw new Exception("Range resume failed: " + job.Error);
    if (!job.SupportsRanges) throw new Exception("HTTP Range was not detected");
    if (job.SegmentsUsed != 16) throw new Exception("Requested 16 ranges must be used for a sufficiently large file.");
    if (!bytes.SequenceEqual(await File.ReadAllBytesAsync(job.CompletedPath)))
        throw new Exception("Range resume produced incorrect bytes");

    var maxParts = manager.Add(server.Url + "range/32-connections.bin", folder, 32);
    await WaitFor(() => maxParts.Status is "Completed" or "Failed");
    if (maxParts.Status != "Completed") throw new Exception("32-connection download failed: " + maxParts.Error);
    if (maxParts.SegmentsUsed != 32)
        throw new Exception("32 HTTP ranges were not used for a sufficiently large file.");
    if (!bytes.SequenceEqual(await File.ReadAllBytesAsync(maxParts.CompletedPath)))
        throw new Exception("32-connection merge corrupted the output.");
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
