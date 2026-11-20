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
        string host = new Uri(url).IdnHost.ToLowerInvariant();
        if (Matches(host, "youtube.com") || Matches(host, "youtu.be") || Matches(host, "youtube-nocookie.com")) return "YouTube";
        if (Matches(host, "tiktok.com")) return "TikTok";
        if (Matches(host, "instagram.com")) return "Instagram Reels";
        return "Facebook Reels";
    }

    public static IReadOnlyList<string> BuildArguments(DownloadJob job, string work, string tools)
    {
        if (!IsVideoUrl(job.Url)) throw new ArgumentException("ลิงก์นี้ไม่ใช่แพลตฟอร์มวิดีโอที่รองรับ");
        if (!AllowedQualities.Contains(job.VideoQuality)) throw new ArgumentException("รูปแบบวิดีโอไม่ถูกต้อง");
        if (!AllowedOutputFormats.Contains(job.OutputFormat)) throw new ArgumentException("นามสกุลปลายทางไม่ถูกต้อง");
        if (!DownloadEngine.AllowedParts.Contains(job.Parts)) throw new ArgumentException("จำนวนส่วนไม่ถูกต้อง");
        var args = new List<string>
        {
            "--ignore-config", "--no-plugin-dirs", "--no-playlist", "--no-simulate", "--no-mtime", "--newline", "--no-colors",
            "--continue", "--windows-filenames", "--encoding", "utf-8",
            "--paths", "home:" + job.Folder,
            "--paths", "temp:" + work,
            "-o", "%(title).150B [%(id)s].%(ext)s",
            "--print", "before_dl:xstage-title:%(title)s",
            "--print", "after_move:xstage-path:%(filepath)s",
            // Keep an independent final-path receipt. Console output on Thai
            // Windows can otherwise replace Unicode filename bytes.
            "--print-to-file", "after_move:%(filepath)s", Path.Combine(work, "xstage-completed-path.txt"),
            "--progress-template", "download:xstage-progress:%(progress._percent_str)s|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|%(progress.total_bytes_estimate)s",
            "--ffmpeg-location", tools,
            "--js-runtimes", "deno:" + Path.Combine(tools, "deno.exe"),
            "-N", job.Parts.ToString(CultureInfo.InvariantCulture),
        };
        if (job.OutputFormat == "mp3" || job.VideoQuality == "AudioMP3")
        {
            args.AddRange(new[] { "-f", "ba/b", "-x", "--audio-format", "mp3", "--audio-quality", "0" });
        }
        else
        {
            string format = job.VideoQuality == "Best" ? "bv*+ba/b" :
                $"bv*[height<={job.VideoQuality}]+ba/b[height<={job.VideoQuality}]";
            // Merge into a flexible intermediate and use FFmpeg to convert
            // to the requested container. Merely renaming the extension is unsafe.
            args.AddRange(new[] { "-f", format, "--merge-output-format", "mkv",
                                  "--recode-video", job.OutputFormat });
        }
        args.Add(job.Url);
        return args;
    }

    public static async Task DownloadAsync(DownloadJob job, string work, CancellationToken ct)
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
        job.VideoPhase = "กำลังอ่านข้อมูลวิดีโอ";
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
        foreach (var arg in BuildArguments(job, work, tools)) info.ArgumentList.Add(arg);

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
            if (line.StartsWith("xstage-title:", StringComparison.Ordinal))
            {
                var title = line["xstage-title:".Length..].Trim();
                if (title.Length > 0) job.Name = title.Length > 160 ? title[..160] : title;
                job.VideoPhase = "กำลังดาวน์โหลดวิดีโอ";
            }
            else if (line.StartsWith("xstage-path:", StringComparison.Ordinal))
                finalPath = line["xstage-path:".Length..].TrimEnd('\r', '\n');
            else if (line.StartsWith("xstage-progress:", StringComparison.Ordinal))
            {
                var progress = line["xstage-progress:".Length..].Split('|');
                if (progress.Length > 0 &&
                    double.TryParse(progress[0].Trim().TrimEnd('%'), NumberStyles.Float,
                        CultureInfo.InvariantCulture, out var percent))
                    job.VideoPercent = Math.Clamp(percent, 0, 100);
                if (progress.Length > 1 && long.TryParse(progress[1], out var bytes))
                    Interlocked.Exchange(ref job.DownloadedBytes, Math.Max(0, bytes));
                if (progress.Length > 2 && long.TryParse(progress[2], out var total))
                    job.TotalBytes = total;
                else if (progress.Length > 3 && long.TryParse(progress[3], out var estimate))
                    job.TotalBytes = estimate;
            }
            else if (line.Contains("[Merger]", StringComparison.Ordinal) ||
                     line.Contains("[ExtractAudio]", StringComparison.Ordinal) ||
                     line.Contains("[VideoRemuxer]", StringComparison.Ordinal))
                job.VideoPhase = "กำลังรวมภาพและเสียง";
        }
        void OnStderr(string line)
        {
            if (string.IsNullOrWhiteSpace(line)) return;
            errors.Enqueue(line.Trim());
            while (errors.Count > 12) errors.Dequeue();
        }

        await Task.WhenAll(ReadLinesAsync(process.StandardOutput, OnStdout),
                           ReadLinesAsync(process.StandardError, OnStderr),
                           process.WaitForExitAsync());
        ct.ThrowIfCancellationRequested();
        if (process.ExitCode != 0)
        {
            var tail = string.Join(" | ", errors);
            throw new IOException("ดาวน์โหลดวิดีโอไม่สำเร็จ" +
                (tail.Length > 0 ? ": " + (tail.Length > 320 ? tail[^320..] : tail) : " (รหัส " + process.ExitCode + ")"));
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
        var expectedExtension = job.VideoQuality == "AudioMP3" ? ".mp3" : "." + job.OutputFormat;
        if (!Path.GetExtension(fullPath).Equals(expectedExtension, StringComparison.OrdinalIgnoreCase))
            throw new IOException("ไฟล์ปลายทางไม่ตรงรูปแบบที่เลือก (" + expectedExtension + ")");
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
