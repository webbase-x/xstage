using System.Diagnostics;
using System.Globalization;
using System.Text;

namespace XStageDownloadManager;

// Media extraction uses bundled, independently maintained upstream tools. It does
// not bypass DRM, access controls, subscriptions, login gates or private posts.
public static class SocialVideoDownloader
{
    public static readonly string[] AllowedQualities = { "Best", "1080", "720", "480", "AudioMP3" };

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
        if (!DownloadEngine.AllowedParts.Contains(job.Parts)) throw new ArgumentException("จำนวนส่วนไม่ถูกต้อง");
        var args = new List<string>
        {
            "--ignore-config", "--no-playlist", "--no-mtime", "--newline", "--no-colors",
            "--continue", "--windows-filenames",
            "--paths", "home:" + job.Folder,
            "--paths", "temp:" + work,
            "-o", "%(title).150B [%(id)s].%(ext)s",
            "--print", "before_dl:xstage-title:%(title)s",
            "--print", "after_move:xstage-path:%(filepath)s",
            "--progress-template", "download:xstage-progress:%(progress._percent_str)s|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|%(progress.total_bytes_estimate)s",
            "--ffmpeg-location", tools,
            "--js-runtimes", "deno:" + Path.Combine(tools, "deno.exe"),
            "-N", job.Parts.ToString(CultureInfo.InvariantCulture),
        };
        if (job.VideoQuality == "AudioMP3")
        {
            args.AddRange(new[] { "-f", "ba/b", "-x", "--audio-format", "mp3", "--audio-quality", "0" });
        }
        else
        {
            string format = job.VideoQuality == "Best" ? "bv*+ba/b" :
                $"bv*[height<={job.VideoQuality}]+ba/b[height<={job.VideoQuality}]";
            args.AddRange(new[] { "-f", format, "--merge-output-format", "mp4/mkv" });
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
        job.VideoPhase = "กำลังอ่านข้อมูลวิดีโอ";
        job.VideoPercent = 0;
        job.SegmentsUsed = job.Parts;

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
                finalPath = line["xstage-path:".Length..].Trim();
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
        if (string.IsNullOrWhiteSpace(finalPath)) throw new IOException("โปรแกรมวิดีโอไม่ส่งตำแหน่งไฟล์ที่บันทึกเสร็จ");
        var fullPath = Path.GetFullPath(finalPath);
        var folderPath = Path.GetFullPath(job.Folder).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        if (!fullPath.StartsWith(folderPath, StringComparison.OrdinalIgnoreCase) || !File.Exists(fullPath))
            throw new IOException("ไม่พบไฟล์วิดีโอในโฟลเดอร์ปลายทางที่เลือก");
        job.CompletedPath = fullPath;
        job.TotalBytes = new FileInfo(fullPath).Length;
        Interlocked.Exchange(ref job.DownloadedBytes, job.TotalBytes);
        job.VideoPercent = 100;
        job.VideoPhase = "สำเร็จ";
        try { Directory.Delete(work, true); }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }
}
