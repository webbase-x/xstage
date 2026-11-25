using System.Diagnostics;
using System.Globalization;
using System.Text;

namespace XStageDownloadManager;

// Media extraction uses bundled, independently maintained upstream tools. It does
// not bypass DRM, access controls, subscriptions, login gates or private posts.
public static class SocialVideoDownloader
{
    public static readonly string[] AllowedQualities = { "Best", "1080", "720", "480", "AudioMP3" };
    public static readonly string[] AllowedOutputFormats = { "mp4", "mkv", "webm", "mp3" };

    // Video-only controls are meaningful for supported social streams,
    // not for regular HTTP files (including direct .mp4 links).
    public static bool InputContainsVideo(string input) =>
        input.Split(new[] { '\r', '\n', ' ', '\t' },
            StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
        .Take(200).Any(IsVideoUrl);

    public static bool IsVideoUrl(string url)
    {
        if (!DownloadEngine.TryParseUrl(url, out var parsed) || parsed is null) return false;
        string host = parsed.IdnHost.TrimEnd('.').ToLowerInvariant();
        return Matches(host, "youtube.com") || Matches(host, "youtu.be") ||
               Matches(host, "youtube-nocookie.com") ||
               Matches(host, "tiktok.com") || Matches(host, "facebook.com") ||
               Matches(host, "fb.watch") || Matches(host, "fb.com") ||
               Matches(host, "instagram.com");
    }

    private static bool Matches(string host, string domain) =>
        host == domain || host.EndsWith("." + domain, StringComparison.Ordinal);

    public static string Platform(string url)
    {
        if (!IsVideoUrl(url)) return "";
        string host = new Uri(url).IdnHost.TrimEnd('.').ToLowerInvariant();
        if (Matches(host, "youtube.com") || Matches(host, "youtu.be") || Matches(host, "youtube-nocookie.com")) return "YouTube";
        if (Matches(host, "tiktok.com")) return "TikTok";
        if (Matches(host, "instagram.com")) return "Instagram Reels";
        return "Facebook Reels";
    }

    // HTTP Range segment count is unrelated to yt-dlp fragment parallelism.
    // Very high video concurrency can cause 403/429 and slower transfers.
    public static int VideoFragmentConcurrency(int chosenParts) => Math.Clamp(chosenParts, 1, 4);

    // yt-dlp runs outside the native HTTP byte gate. Apply the strictest
    // configured cap per video process; this is not yet an aggregate global
    // cap when several native/video jobs run simultaneously.
    public static int VideoRateLimitKib(int globalLimitKib, int fileLimitKib, bool sharedAllocation = false)
    {
        // Keep subprocess limits within the same validated range as native
        // HTTP. Corrupt legacy settings must not launch an unbounded process.
        if (globalLimitKib != 0 && (globalLimitKib < (sharedAllocation ? 1 : 64) || globalLimitKib > 1_048_576))
            throw new ArgumentOutOfRangeException(nameof(globalLimitKib),
                "Video speed limits must be 0 or 64–1048576 KiB/s.");
        if (fileLimitKib != 0 && fileLimitKib is < 64 or > 1_048_576)
            throw new ArgumentOutOfRangeException(nameof(fileLimitKib),
                "Video speed limits must be 0 or 64–1048576 KiB/s.");
        if (globalLimitKib == 0) return fileLimitKib;
        if (fileLimitKib == 0) return globalLimitKib;
        return Math.Min(globalLimitKib, fileLimitKib);
    }

    public static bool IsYtDlpError(string line) =>
        line.Contains("ERROR:", StringComparison.OrdinalIgnoreCase) ||
        line.StartsWith("ERROR ", StringComparison.OrdinalIgnoreCase) ||
        line.Contains("HTTP Error 403", StringComparison.OrdinalIgnoreCase) ||
        line.Contains("HTTP Error 429", StringComparison.OrdinalIgnoreCase);

    public static string ExplainFailure(string details, int exitCode)
    {
        // Explain protected playback rather than suggesting retries or
        // unauthorized workarounds for DRM-encrypted subscription media.
        if (details.Contains("DRM protected", StringComparison.OrdinalIgnoreCase) ||
            details.Contains("DRM-protected", StringComparison.OrdinalIgnoreCase) ||
            details.Contains("This video is DRM", StringComparison.OrdinalIgnoreCase) ||
            details.Contains("encrypted with DRM", StringComparison.OrdinalIgnoreCase))
            return "สตรีมนี้มีการป้องกัน DRM โปรดรับชมผ่านเว็บไซต์หรือแอปทางการ";
        if (details.Contains("Requested format is not available", StringComparison.OrdinalIgnoreCase))
            return "ไม่พบรูปแบบหรือความละเอียดที่เลือก โปรดเลือกคุณภาพดีที่สุดหรือต่ำลง";
        if (details.Contains("HTTP Error 429", StringComparison.OrdinalIgnoreCase) ||
            details.Contains("Too Many Requests", StringComparison.OrdinalIgnoreCase))
            return "เว็บไซต์จำกัดจำนวนคำขอชั่วคราว (HTTP 429) ลองใหม่ภายหลัง";
        if (details.Contains("HTTP Error 403", StringComparison.OrdinalIgnoreCase))
            return "เว็บไซต์ปฏิเสธคำขอดาวน์โหลด (HTTP 403) อาจมีข้อจำกัดการเข้าถึง";
        if (details.Contains("Sign in to confirm", StringComparison.OrdinalIgnoreCase) ||
            details.Contains("login required", StringComparison.OrdinalIgnoreCase) ||
            details.Contains("This video is private", StringComparison.OrdinalIgnoreCase))
            return "วิดีโอนี้ต้องยืนยันตัวตนหรือมีข้อจำกัดการเข้าถึง";
        if (details.Contains("Video unavailable", StringComparison.OrdinalIgnoreCase))
            return "วิดีโอนี้ไม่พร้อมให้เข้าถึง";
        if (details.Contains("Unsupported URL", StringComparison.OrdinalIgnoreCase))
            return "รูปแบบลิงก์นี้ยังไม่รองรับ";
        return "ดาวน์โหลดวิดีโอไม่สำเร็จ (รหัส " + exitCode + ")";
    }

    public static IReadOnlyList<string> BuildArguments(DownloadJob job, string work, string tools, int globalLimitKib = 0, bool sharedAllocation = false)
    {
        if (!IsVideoUrl(job.Url)) throw new ArgumentException("ลิงก์นี้ไม่ใช่แพลตฟอร์มวิดีโอที่รองรับ");
        if (!AllowedQualities.Contains(job.VideoQuality)) throw new ArgumentException("รูปแบบวิดีโอไม่ถูกต้อง");
        if (!AllowedOutputFormats.Contains(job.OutputFormat)) throw new ArgumentException("นามสกุลปลายทางไม่ถูกต้อง");
        if (!DownloadEngine.AllowedParts.Contains(job.Parts)) throw new ArgumentException("จำนวนส่วนไม่ถูกต้อง");
        // Keep the YouTube ID immediately before the extension for reliable
        // Unicode-path recovery. A separate-copy job inserts an 8-digit marker
        // before [id], so yt-dlp cannot skip a previously downloaded video.
        // Imported/legacy records can carry IDs shorter than eight characters.
        // Never crash the video worker while constructing a safe output name.
        var copyMarker = job.Id.Length > 8 ? job.Id[..8] : job.Id;
        if (string.IsNullOrWhiteSpace(copyMarker))
            throw new ArgumentException("Video job must have a stable ID.", nameof(job));
        var outputPattern = job.IsRedownload
            ? "%(title).135B (again-" + copyMarker + ") [%(id)s].%(ext)s"
            : "%(title).150B [%(id)s].%(ext)s";
        var args = new List<string>
        {
            // --print implicitly enables yt-dlp's quiet mode. Force live
            // download progress back on or the Windows UI remains at 0.0%.
            "--ignore-config", "--no-plugin-dirs", "--no-playlist", "--no-simulate", "--no-mtime",
            "--progress", "--newline", "--no-colors",
            "--continue", "--windows-filenames", "--encoding", "utf-8",
            // Bound network retry time rather than waiting indefinitely.
            "--socket-timeout", "20", "--retries", "3",
            "--fragment-retries", "3", "--extractor-retries", "2",
            "--retry-sleep", "http:linear=1:4:1",
            "--retry-sleep", "fragment:linear=1:4:1",
            "--paths", "home:" + job.Folder,
            "--paths", "temp:" + work,
            "-o", outputPattern,
            "--print", "before_dl:xstage-title:%(title)s",
            "--print", "after_move:xstage-path:%(filepath)s",
            // Keep an independent final-path receipt. Console output on Thai
            // Windows can otherwise replace Unicode filename bytes.
            "--print-to-file", "after_move:%(filepath)s", Path.Combine(work, "xstage-completed-path.txt"),
            "--progress-template", "download:xstage-progress:%(progress._percent_str)s|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|%(progress.total_bytes_estimate)s",
            "--ffmpeg-location", tools,
            "--js-runtimes", "deno:" + Path.Combine(tools, "deno.exe"),
            "-N", (globalLimitKib > 0 || job.FileSpeedLimitKib > 0 ? 1 : VideoFragmentConcurrency(job.Parts)).ToString(CultureInfo.InvariantCulture),
        };
        var rateLimitKib = VideoRateLimitKib(globalLimitKib, job.FileSpeedLimitKib, sharedAllocation);
        if (rateLimitKib > 0)
        {
            args.Add("--limit-rate");
            args.Add(rateLimitKib.ToString(CultureInfo.InvariantCulture) + "K");
        }
        if (job.OutputFormat == "mp3" || job.VideoQuality == "AudioMP3")
        {
            args.AddRange(new[] { "-f", "ba/b", "-x", "--audio-format", "mp3", "--audio-quality", "0" });
        }
        else
        {
            string format = job.VideoQuality == "Best" ? "bv*+ba/b" :
                $"bv*[height<={job.VideoQuality}]+ba/b[height<={job.VideoQuality}]";
            // The previously used --recode-video mp4 could leave a partial
            // MP4 (ftyp + mdat but no moov) that was wrongly marked complete.
            // Keep a playable source and perform the final MP4 conversion
            // separately with FFprobe verification before exposing the file.
            args.AddRange(new[] { "-f", format, "--merge-output-format", "mkv" });
            if (job.OutputFormat == "webm")
                args.AddRange(new[] { "--recode-video", "webm" });
        }
        args.Add(job.Url);
        return args;
    }

    // Pure parser, shared by stdout/stderr readers and regression tests.
    // For versions where the formatted percent is N/A, fall back to a real
    // downloaded-byte ratio; never fabricate a percentage from elapsed time.
    public static bool TryParseProgress(
        string line, out double percent, out long downloadedBytes, out long totalBytes)
    {
        percent = double.NaN;
        downloadedBytes = -1;
        totalBytes = -1;
        const string prefix = "xstage-progress:";
        var position = line.IndexOf(prefix, StringComparison.Ordinal);
        if (position < 0) return false;
        var fields = line[(position + prefix.Length)..].Split('|');
        if (fields.Length < 2) return false;

        var numericPercent = System.Text.RegularExpressions.Regex.Replace(
            fields[0], @"\x1B\[[0-9;]*[A-Za-z]", "").Trim().TrimEnd('%').Trim();
        if (double.TryParse(numericPercent, NumberStyles.Float,
                CultureInfo.InvariantCulture, out var parsed) && double.IsFinite(parsed))
            percent = Math.Clamp(parsed, 0, 100);

        if (long.TryParse(fields[1].Trim(), NumberStyles.Integer,
                CultureInfo.InvariantCulture, out var bytes))
            downloadedBytes = Math.Max(0, bytes);
        if (fields.Length > 2 &&
            long.TryParse(fields[2].Trim(), NumberStyles.Integer,
                CultureInfo.InvariantCulture, out var total) && total > 0)
            totalBytes = total;
        else if (fields.Length > 3 &&
                 long.TryParse(fields[3].Trim(), NumberStyles.Integer,
                     CultureInfo.InvariantCulture, out var estimate) && estimate > 0)
            totalBytes = estimate;
        if (double.IsNaN(percent) && downloadedBytes >= 0 && totalBytes > 0)
            percent = Math.Clamp(100.0 * downloadedBytes / totalBytes, 0, 100);
        return double.IsFinite(percent) || downloadedBytes >= 0;
    }

    // Describe real yt-dlp work even before the first downloaded byte.
    public static string? DescribeOutputPhase(string line)
    {
        if (line.Contains("[Merger]", StringComparison.Ordinal) ||
            line.Contains("[ExtractAudio]", StringComparison.Ordinal) ||
            line.Contains("[VideoRemuxer]", StringComparison.Ordinal) ||
            line.Contains("[VideoConvertor]", StringComparison.Ordinal) ||
            line.Contains("[Fixup", StringComparison.Ordinal) ||
            line.Contains("[ffmpeg]", StringComparison.OrdinalIgnoreCase))
            return "กำลังรวม/แปลงไฟล์วิดีโอ";
        if (line.Contains("Downloading webpage", StringComparison.OrdinalIgnoreCase) ||
            line.Contains("Extracting URL", StringComparison.OrdinalIgnoreCase) ||
            line.Contains("Downloading player", StringComparison.OrdinalIgnoreCase) ||
            line.Contains("Downloading API", StringComparison.OrdinalIgnoreCase))
            return "กำลังอ่านข้อมูลวิดีโอจากเว็บไซต์";
        if (line.Contains("Downloading m3u8", StringComparison.OrdinalIgnoreCase) ||
            line.Contains("Downloading MPD", StringComparison.OrdinalIgnoreCase) ||
            line.Contains("Downloading format", StringComparison.OrdinalIgnoreCase) ||
            line.Contains("Downloading 1 format", StringComparison.OrdinalIgnoreCase))
            return "กำลังเชื่อมต่อสตรีมวิดีโอ";
        if (line.StartsWith("[download] Destination:", StringComparison.Ordinal) ||
            line.Contains("Total fragments:", StringComparison.OrdinalIgnoreCase))
            return "กำลังรับข้อมูลวิดีโอ";
        return null;
    }

    // Transcoding is more expensive than waiting for a CDN to deliver bytes.
    public static bool IsStalled(TimeSpan noByteProgress, bool postProcessing)
        => postProcessing ? noByteProgress >= TimeSpan.FromMinutes(15)
                          : noByteProgress >= TimeSpan.FromMinutes(2);

    public static async Task DownloadAsync(DownloadJob job, string work, CancellationToken ct, int globalLimitKib = 0, bool sharedAllocation = false)
    {
        var tools = Path.Combine(AppContext.BaseDirectory, "tools");
        var ytDlp = Path.Combine(tools, "yt-dlp.exe");
        foreach (var file in new[] { ytDlp, Path.Combine(tools, "ffmpeg.exe"),
                                     Path.Combine(tools, "ffprobe.exe"),
                                     Path.Combine(tools, "deno.exe") })
            if (!File.Exists(file))
                throw new FileNotFoundException("ไม่พบเครื่องมือวิดีโอที่รวมมากับตัวติดตั้ง กรุณาติดตั้ง X-Stage Download Manager รุ่นเต็มอีกครั้ง", file);

        Directory.CreateDirectory(job.Folder);
        Directory.CreateDirectory(work);
        var receiptPath = Path.Combine(work, "xstage-completed-path.txt");
        // Never treat an earlier attempt's receipt as a successful download.
        if (File.Exists(receiptPath)) File.Delete(receiptPath);
        job.VideoPhase = "กำลังค้นหาข้อมูลวิดีโอ";
        job.VideoPercent = 0;
        job.SegmentsUsed = 0; // -N sets a maximum fragment concurrency, not a guaranteed number of HTTP byte ranges

        var info = new ProcessStartInfo(ytDlp)
        {
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            WorkingDirectory = job.Folder,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8
        };
        info.Environment["YTDLP_NO_PLUGINS"] = "1";
        info.Environment["PYTHONIOENCODING"] = "utf-8";
        info.Environment["PYTHONUTF8"] = "1";
        foreach (var arg in BuildArguments(job, work, tools, globalLimitKib, sharedAllocation)) info.ArgumentList.Add(arg);

        using var process = new Process { StartInfo = info };
        if (!process.Start()) throw new IOException("ไม่สามารถเปิดตัวดาวน์โหลดวิดีโอได้");
        using var cancellation = ct.Register(() =>
        {
            try { if (!process.HasExited) process.Kill(entireProcessTree: true); }
            catch (InvalidOperationException) { }
            catch (System.ComponentModel.Win32Exception) { }
        });

        string? finalPath = null;
        var errors = new Queue<string>();
        var started = Stopwatch.GetTimestamp();
        long lastByteTick = started;
        long lastOutputTick = started;
        long previousReportedBytes = 0;
        int postProcessing = 0;
        string? watchdogError = null;
        var logDir = Path.Combine(Environment.GetFolderPath(
            Environment.SpecialFolder.LocalApplicationData),
            "X-Stage", "Download Manager", "logs");
        Directory.CreateDirectory(logDir);
        var logFile = Path.Combine(logDir, "video-" + job.Id + ".log");
        var recentLines = new Queue<string>();
        void RecordLine(string line)
        {
            Interlocked.Exchange(ref lastOutputTick, Stopwatch.GetTimestamp());
            // Avoid persisting signed CDN URL query tokens in diagnostics.
            var safe = System.Text.RegularExpressions.Regex.Replace(
                line, @"https?://[^\s]+", "[url]",
                System.Text.RegularExpressions.RegexOptions.IgnoreCase);
            lock (recentLines)
            {
                recentLines.Enqueue(safe.Length > 600 ? safe[..600] : safe);
                while (recentLines.Count > 80) recentLines.Dequeue();
            }
        }
        async Task ReadLinesAsync(StreamReader reader, Action<string> processLine)
        {
            try
            {
                string? line;
                while ((line = await reader.ReadLineAsync()) is not null) processLine(line);
            }
            catch (IOException) when (ct.IsCancellationRequested) { }
            catch (ObjectDisposedException) when (ct.IsCancellationRequested) { }
        }
        void OnStdout(string line)
        {
            RecordLine(line);
            if (IsYtDlpError(line))
            {
                lock (errors)
                {
                    errors.Enqueue(line.Trim());
                    while (errors.Count > 12) errors.Dequeue();
                }
            }
            var phase = DescribeOutputPhase(line);
            if (phase is not null)
            {
                job.VideoPhase = phase;
                if (phase == "กำลังรวม/แปลงไฟล์วิดีโอ")
                {
                    Interlocked.Exchange(ref postProcessing, 1);
                    Interlocked.Exchange(ref lastByteTick, Stopwatch.GetTimestamp());
                }
            }
            if (line.StartsWith("xstage-title:", StringComparison.Ordinal))
            {
                var title = line["xstage-title:".Length..].Trim();
                if (title.Length > 0) job.Name = title.Length > 160 ? title[..160] : title;
                job.VideoPhase = "กำลังเตรียมรับวิดีโอ";
            }
            else if (line.StartsWith("xstage-path:", StringComparison.Ordinal))
                finalPath = line["xstage-path:".Length..].TrimEnd('\r', '\n');
            else if (TryParseProgress(line, out var percent, out var bytes, out var total))
            {
                if (double.IsFinite(percent))
                    job.VideoPercent = Math.Clamp(percent, 0, 99.9);
                if (bytes >= 0)
                {
                    if (bytes != Interlocked.Read(ref previousReportedBytes))
                    {
                        Interlocked.Exchange(ref previousReportedBytes, bytes);
                        Interlocked.Exchange(ref lastByteTick, Stopwatch.GetTimestamp());
                    }
                    Interlocked.Exchange(ref job.DownloadedBytes, bytes);
                    if (bytes > 0) job.VideoPhase = "กำลังดาวน์โหลดวิดีโอ";
                }
                if (total > 0) job.TotalBytes = total;
            }

        }
        void OnStderr(string line)
        {
            if (string.IsNullOrWhiteSpace(line)) return;
            // yt-dlp may write progress to either redirected stream depending
            // on its version and output mode. Parse both using one handler.
            OnStdout(line);
            if (!IsYtDlpError(line))
            {
                lock (errors)
                {
                    errors.Enqueue(line.Trim());
                    while (errors.Count > 12) errors.Dequeue();
                }
            }
        }

        using var watchStop = CancellationTokenSource.CreateLinkedTokenSource(ct);
        var watchdog = Task.Run(async () =>
        {
            try
            {
                while (!process.HasExited)
                {
                    await Task.Delay(TimeSpan.FromSeconds(2), watchStop.Token);
                    var now = Stopwatch.GetTimestamp();
                    var idleBytes = Stopwatch.GetElapsedTime(Interlocked.Read(ref lastByteTick), now);
                    if (!IsStalled(idleBytes, Volatile.Read(ref postProcessing) != 0))
                    {
                        if (Interlocked.Read(ref previousReportedBytes) == 0 &&
                            Volatile.Read(ref postProcessing) == 0)
                        {
                            var seconds = (int)Stopwatch.GetElapsedTime(started, now).TotalSeconds;
                            if (seconds >= 8)
                                job.VideoPhase = "กำลังเชื่อมต่อวิดีโอ (" + seconds + " วินาที)";
                        }
                        continue;
                    }
                    var noOutput = Stopwatch.GetElapsedTime(Interlocked.Read(ref lastOutputTick), now);
                    watchdogError = Volatile.Read(ref postProcessing) != 0
                        ? "ขั้นตอนรวม/แปลงวิดีโอไม่มีความคืบหน้านานเกิน 15 นาที"
                        : "ไม่ได้รับข้อมูลวิดีโอใหม่เกิน 2 นาที" +
                          (noOutput.TotalSeconds >= 60 ? " (โปรแกรมวิดีโอไม่มีการตอบกลับ)" : "");
                    job.VideoPhase = "วิดีโอไม่ตอบสนอง — หยุดงานที่ค้าง";
                    try { if (!process.HasExited) process.Kill(entireProcessTree: true); }
                    catch (InvalidOperationException) { }
                    catch (System.ComponentModel.Win32Exception) { }
                    break;
                }
            }
            catch (OperationCanceledException) { }
        });
        try
        {
            await Task.WhenAll(ReadLinesAsync(process.StandardOutput, OnStdout),
                               ReadLinesAsync(process.StandardError, OnStderr),
                               process.WaitForExitAsync());
        }
        finally
        {
            watchStop.Cancel();
            await watchdog;
            try
            {
                string[] recorded;
                lock (recentLines) recorded = recentLines.ToArray();
                File.WriteAllLines(logFile, recorded, Encoding.UTF8);
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
        ct.ThrowIfCancellationRequested();
        if (watchdogError is not null)
            throw new IOException(watchdogError + " · ตรวจสอบบันทึก: " + logFile);
        if (process.ExitCode != 0)
        {
            string tail;
            lock (errors) tail = string.Join(" | ", errors);
            var reason = ExplainFailure(tail, process.ExitCode);
            var safeTail = System.Text.RegularExpressions.Regex.Replace(
                tail, @"https?://[^\s]+", "[URL]",
                System.Text.RegularExpressions.RegexOptions.IgnoreCase);
            throw new IOException(reason +
                (safeTail.Length > 0 ? " · รายละเอียด: " +
                    (safeTail.Length > 220 ? safeTail[^220..] : safeTail) : "") +
                " · บันทึก: " + logFile);
        }
        string fullPath;
        try { fullPath = VerifyCompletedPath(job.Folder, finalPath, receiptPath); }
        catch (IOException)
        {
            // When a UTF-8 path is damaged on Windows stdout, the correct
            // yt-dlp output can still be recognized by its unique video ID.
            // Only do this AFTER yt-dlp exits successfully.
            var recovered = FindCompletedYouTubeOutput(job.Url, job.Folder, job.VideoQuality, job.OutputFormat);
            if (recovered is null) throw;
            fullPath = recovered;
        }
        if (job.OutputFormat == "mp4" && job.VideoQuality != "AudioMP3")
        {
            job.VideoPhase = "กำลังตรวจสอบและสร้างไฟล์ MP4 ที่เล่นได้";
            fullPath = await MediaIntegrity.FinishMp4Async(fullPath, job.Folder, work, tools,
                ct, phase => job.VideoPhase = phase);
        }
        var expectedExtension = job.VideoQuality == "AudioMP3" ? ".mp3" : "." + job.OutputFormat;
        if (!Path.GetExtension(fullPath).Equals(expectedExtension, StringComparison.OrdinalIgnoreCase))
            throw new IOException("ไฟล์ปลายทางไม่ตรงรูปแบบที่เลือก (" + expectedExtension + ")");
        job.VideoPhase = "กำลังตรวจสอบความสมบูรณ์ของไฟล์";
        await MediaIntegrity.VerifyAsync(fullPath, Path.Combine(tools, "ffprobe.exe"),
            expectedExtension == ".mp3", ct);
        job.Name = Path.GetFileName(fullPath);
        job.CompletedPath = fullPath;
        job.TotalBytes = new FileInfo(fullPath).Length;
        Interlocked.Exchange(ref job.DownloadedBytes, job.TotalBytes);
        job.VideoPercent = 100;
        job.VideoPhase = "สำเร็จ";
        try { Directory.Delete(work, true); }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }


    // Recover an already-completed file when old Builds incorrectly recorded a
    // post-download path-check failure. yt-dlp's naming template always places
    // [YouTubeId] immediately before the media extension. Never search loosely
    // by title or choose arbitrarily among multiple matching files.
    public static string? FindCompletedYouTubeOutput(string url, string folder, string quality = "Best", string? outputFormat = null)
    {
        if (!IsVideoUrl(url) || !Directory.Exists(folder)) return null;
        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri)) return null;
        var host = uri.IdnHost.TrimEnd('.').ToLowerInvariant();
        if (!Matches(host, "youtube.com") && !Matches(host, "youtu.be") &&
            !Matches(host, "youtube-nocookie.com")) return null;

        string? id = null;
        if (Matches(host, "youtu.be"))
            id = uri.AbsolutePath.Trim('/').Split('/')[0];
        else if (uri.AbsolutePath.StartsWith("/shorts/", StringComparison.OrdinalIgnoreCase) ||
                 uri.AbsolutePath.StartsWith("/live/", StringComparison.OrdinalIgnoreCase))
            id = uri.AbsolutePath.Trim('/').Split('/').Skip(1).FirstOrDefault();
        else
        {
            foreach (var part in uri.Query.TrimStart('?').Split('&'))
            {
                var pair = part.Split('=', 2);
                if (pair.Length == 2 && pair[0] == "v") { id = Uri.UnescapeDataString(pair[1]); break; }
            }
        }
        if (id is null || id.Length != 11 ||
            id.Any(ch => !char.IsAsciiLetterOrDigit(ch) && ch is not ('_' or '-')))
            return null;

        var allowed = quality == "AudioMP3" ? new[] { ".mp3" }
            : outputFormat is "mp4" or "mkv" or "webm" or "mp3"
                ? new[] { "." + outputFormat } : new[] { ".mkv", ".mp4", ".webm" };
        var files = Directory.EnumerateFiles(folder, "*", SearchOption.TopDirectoryOnly)
            .Where(file =>
                allowed.Contains(Path.GetExtension(file), StringComparer.OrdinalIgnoreCase) &&
                Path.GetFileNameWithoutExtension(file).EndsWith(" [" + id + "]", StringComparison.Ordinal) &&
                new FileInfo(file).Length > 0)
            .Take(2).ToArray();
        return files.Length == 1 ? Path.GetFullPath(files[0]) : null;
    }

    // The exact legacy error was thrown only AFTER yt-dlp finished with exit 0.
    // Repair that historical bookkeeping mistake without downloading again.
    public static bool TryRecoverLegacyCompletedJob(DownloadJob job)
    {
        if (job.Kind != "Video" || job.Status != "Failed" ||
            job.Error != "ไม่พบไฟล์วิดีโอในโฟลเดอร์ปลายทางที่เลือก")
            return false;
        string? recovered;
        try { recovered = FindCompletedYouTubeOutput(job.Url, job.Folder, job.VideoQuality); }
        catch (IOException) { return false; }
        catch (UnauthorizedAccessException) { return false; }
        if (recovered is null) return false;
        job.CompletedPath = recovered;
        job.Name = Path.GetFileName(recovered);
        job.TotalBytes = new FileInfo(recovered).Length;
        Interlocked.Exchange(ref job.DownloadedBytes, job.TotalBytes);
        job.VideoPercent = 100;
        job.VideoPhase = "สำเร็จ";
        job.Error = "";
        job.Status = "Completed";
        return true;
    }

    // Never mark an unrelated pre-existing file as complete. Only trust the
    // exact recorded output path when it belongs to the chosen destination.
    public static string VerifyCompletedPath(string folder, string? stdoutPath, string? receiptPath)
    {
        var candidates = new List<string>();
        if (!string.IsNullOrWhiteSpace(stdoutPath)) candidates.Add(stdoutPath);
        if (!string.IsNullOrWhiteSpace(receiptPath) && File.Exists(receiptPath))
            candidates.AddRange(File.ReadAllLines(receiptPath, Encoding.UTF8)
                .Where(path => !string.IsNullOrWhiteSpace(path)));

        var root = Path.GetFullPath(folder).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
                   + Path.DirectorySeparatorChar;
        foreach (var raw in candidates.AsEnumerable().Reverse())
        {
            try
            {
                var path = raw.TrimEnd('\r', '\n');
                var resolved = Path.GetFullPath(
                    Path.IsPathFullyQualified(path) ? path : Path.Combine(folder, path));
                if (resolved.StartsWith(root, StringComparison.OrdinalIgnoreCase) && File.Exists(resolved))
                    return resolved;
            }
            catch (ArgumentException) { /* Invalid console bytes: try the other receipt. */ }
            catch (NotSupportedException) { }
        }
        throw new IOException(candidates.Count == 0
            ? "โปรแกรมดาวน์โหลดไม่ส่งตำแหน่งไฟล์ที่บันทึกเสร็จ กรุณาตรวจสอบบันทึกข้อผิดพลาด"
            : "ไม่พบไฟล์วิดีโอตามตำแหน่งที่โปรแกรมดาวน์โหลดรายงาน โปรดตรวจสอบโฟลเดอร์ปลายทางและลองอีกครั้ง");
    }
}
