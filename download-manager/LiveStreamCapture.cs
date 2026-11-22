using System.Diagnostics;
using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace XStageDownloadManager;

/// <summary>
/// Opt-in capture of authorized public HLS/DASH streams. Source recordings
/// always remain on disk, including after cancellation or failed splitting.
/// Nothing here touches the legacy download jobs or SQLite schema.
/// </summary>
public sealed class LiveStreamCapture
{
    private readonly object _gate = new();
    private Process? _running;
    private volatile bool _stopRequested;

    public string SessionDirectory { get; private set; } = "";
    public string RecordingPath { get; private set; } = "";
    public string Status { get; private set; } = "พร้อมบันทึก";
    public bool IsRunning { get; private set; }

    public static readonly int[] AllowedClipMinutes = { 1, 3, 5, 10, 15, 20, 30, 60 };

    public static bool IsSupportedSource(string url)
    {
        if (!DownloadEngine.TryParseUrl(url, out var parsed) || parsed is null)
            return false;
        return parsed.AbsolutePath.EndsWith(".m3u8", StringComparison.OrdinalIgnoreCase) ||
               parsed.AbsolutePath.EndsWith(".mpd", StringComparison.OrdinalIgnoreCase) ||
               SocialVideoDownloader.IsVideoUrl(url);
    }

    public static IReadOnlyList<string> BuildCaptureArguments(string url, string recordingPath)
    {
        if (!IsSupportedSource(url))
            throw new ArgumentException("รองรับลิงก์ HLS (.m3u8), DASH (.mpd) หรือวิดีโอบนแพลตฟอร์มสาธารณะที่รองรับ");
        return BuildResolvedCaptureArguments(url, recordingPath);
    }

    // Extractor URLs sometimes omit .m3u8 and carry expiring CDN signatures.
    // This is private and only reached after validating a supported public
    // platform URL through yt-dlp; never expose it as an arbitrary URL input.
    private static IReadOnlyList<string> BuildResolvedCaptureArguments(
        string url, string recordingPath)
    {
        if (!DownloadEngine.TryParseUrl(url, out _) ||
            string.IsNullOrWhiteSpace(recordingPath))
            throw new ArgumentException("ลิงก์หรือปลายทางบันทึกไม่ถูกต้อง");
        return new[]
        {
            "-hide_banner", "-nostats", "-loglevel", "warning",
            "-rw_timeout", "15000000",
            "-i", url,
            "-map", "0:v:0?", "-map", "0:a:0?",
            "-c", "copy", "-f", "matroska", "-y", recordingPath
        };
    }

    public async Task<LiveCaptureResult> RecordAsync(
        string url, string outputFolder, int clipMinutes, Action<string>? status,
        CancellationToken cancellationToken = default)
    {
        if (!IsSupportedSource(url))
            throw new ArgumentException("ระบุลิงก์ไลฟ์ HLS/DASH หรือคลิปสาธารณะที่รองรับเท่านั้น");
        if (!AllowedClipMinutes.Contains(clipMinutes))
            throw new ArgumentOutOfRangeException(nameof(clipMinutes));
        if (string.IsNullOrWhiteSpace(outputFolder))
            throw new ArgumentException("กรุณาเลือกโฟลเดอร์ปลายทาง");
        var ffmpeg = Path.Combine(AppContext.BaseDirectory, "tools", "ffmpeg.exe");
        var ffprobe = Path.Combine(AppContext.BaseDirectory, "tools", "ffprobe.exe");
        if (!File.Exists(ffmpeg) || !File.Exists(ffprobe))
            throw new FileNotFoundException("ไม่พบ FFmpeg/FFprobe ที่รวมมากับ Setup EXE");
        if (IsRunning) throw new InvalidOperationException("กำลังบันทึกไลฟ์อยู่แล้ว");
        _stopRequested = false;
        var name = "XStageLive_" + DateTimeOffset.Now.ToString("yyyyMMdd_HHmmss",
            CultureInfo.InvariantCulture) + "_" + Guid.NewGuid().ToString("N")[..8];
        var session = Path.Combine(Path.GetFullPath(outputFolder), name);
        Directory.CreateDirectory(session);
        SessionDirectory = session;
        RecordingPath = Path.Combine(session, "master.recording.mkv");
        IsRunning = true;
        try
        {
            Status = "กำลังเตรียมแหล่งสตรีม";
            status?.Invoke(Status);
            var resolved = SocialVideoDownloader.IsVideoUrl(url)
                ? await ResolvePublicPlatformStreamAsync(url, cancellationToken)
                : url;
            if (_stopRequested)
                throw new OperationCanceledException("ยกเลิกก่อนเริ่มบันทึก");
            Status = "กำลังบันทึกสด (เก็บไฟล์ต้นฉบับ)";
            status?.Invoke(Status);
            var info = new ProcessStartInfo(ffmpeg)
            {
                WorkingDirectory = session,
                UseShellExecute = false,
                RedirectStandardInput = true,
                RedirectStandardError = true,
                RedirectStandardOutput = true,
                CreateNoWindow = true,
                StandardErrorEncoding = Encoding.UTF8
            };
            foreach (var arg in BuildResolvedCaptureArguments(
                resolved, RecordingPath)) info.ArgumentList.Add(arg);
            var exit = await RunCaptureProcessAsync(info, cancellationToken);
            if (exit != 0 || !File.Exists(RecordingPath) ||
                new FileInfo(RecordingPath).Length <= 0)
                throw new IOException("สตรีมหยุดผิดปกติหรือไม่มีข้อมูล ไฟล์ต้นฉบับที่มีอยู่ยังคงถูกเก็บไว้");
            Status = "กำลังวิเคราะห์ช่วงหยุดพูด";
            status?.Invoke(Status);
            var duration = await ProbeDurationAsync(ffprobe, RecordingPath, cancellationToken);
            var hasAudio = await ProbeAudioAsync(ffprobe, RecordingPath, cancellationToken);
            if (!hasAudio)
            {
                Status = "ไม่มีแทร็กเสียง: เก็บไฟล์ต้นฉบับ ไม่ตัดแบบคาดเดา";
                status?.Invoke(Status);
                return new LiveCaptureResult(session, RecordingPath,
                    Array.Empty<string>(), Status);
            }
            var silences = await DetectSilencesAsync(ffmpeg, RecordingPath, cancellationToken);
            var cuts = LiveSpeechSegmentPlanner.Plan(duration, clipMinutes * 60, silences);
            Status = cuts.Count == 1
                ? "ไม่พบจังหวะเงียบสำหรับตัดต่อ จึงเก็บเป็นคลิปเดียว"
                : $"พบจุดตัดตามจังหวะเงียบ {cuts.Count - 1} จุด";
            status?.Invoke(Status);
            var outputs = new List<string>();
            for (var index = 0; index < cuts.Count; index++)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var (start, end) = cuts[index];
                var filename = $"clip_{index + 1:D3}.mp4";
                var partial = Path.Combine(session, filename + ".partial.mp4");
                var destination = Path.Combine(session, filename);
                if (File.Exists(destination) || File.Exists(partial))
                    throw new IOException("ชื่อไฟล์ปลายทางซ้ำ ระบบจะไม่เขียนทับคลิปเดิม");
                Status = $"กำลังสร้างคลิป {index + 1} / {cuts.Count}";
                status?.Invoke(Status);
                var encode = new ProcessStartInfo(ffmpeg)
                {
                    UseShellExecute = false, CreateNoWindow = true,
                    RedirectStandardError = true, RedirectStandardOutput = true
                };
                foreach (var arg in new[]
                {
                    "-hide_banner", "-nostdin", "-loglevel", "error",
                    "-ss", start.ToString("0.###", CultureInfo.InvariantCulture),
                    "-i", RecordingPath,
                    "-t", (end - start).ToString("0.###", CultureInfo.InvariantCulture),
                    "-map", "0:v:0?", "-map", "0:a:0?",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                    "-c:a", "aac", "-b:a", "160k",
                    "-movflags", "+faststart", "-y", partial
                }) encode.ArgumentList.Add(arg);
                if (await RunToolAsync(encode, cancellationToken) != 0 ||
                    !File.Exists(partial) || !MediaIntegrity.HasCompleteMp4Boxes(partial))
                    throw new IOException("สร้างหรือยืนยันคลิป MP4 ไม่สำเร็จ: " + filename +
                        " · ไฟล์ต้นฉบับยังอยู่ และไฟล์ไม่สมบูรณ์จะไม่ถูกประกาศว่าเสร็จ");
                File.Move(partial, destination); // no overwrite
                outputs.Add(destination);
            }
            Status = cuts.Count == 1
                ? "สร้างคลิปเดียวเสร็จแล้ว (ไม่พบช่วงหยุดพูดเพียงพอ)"
                : $"สร้างคลิปตามช่วงเงียบสำเร็จ {outputs.Count} คลิป";
            status?.Invoke(Status);
            return new LiveCaptureResult(session, RecordingPath, outputs, Status);
        }
        finally
        {
            IsRunning = false;
        }
    }

    public void RequestStop()
    {
        _stopRequested = true;
        lock (_gate)
        {
            try
            {
                if (_running is { HasExited: false } process)
                {
                    process.StandardInput.WriteLine("q");
                    process.StandardInput.Flush();
                }
            }
            catch (InvalidOperationException) { }
            catch (IOException) { }
            catch (ObjectDisposedException) { }
        }
    }

    private async Task<int> RunCaptureProcessAsync(ProcessStartInfo info, CancellationToken ct)
    {
        using var process = new Process { StartInfo = info };
        lock (_gate)
        {
            if (!process.Start()) throw new IOException("เปิด FFmpeg ไม่สำเร็จ");
            _running = process;
        }
        // Drain both pipes to avoid a deadlock if FFmpeg emits warnings.
        var stderr = process.StandardError.ReadToEndAsync();
        var stdout = process.StandardOutput.ReadToEndAsync();
        using var cancel = ct.Register(() =>
        {
            try { if (!process.HasExited) process.Kill(entireProcessTree: true); }
            catch (InvalidOperationException) { }
        });
        if (_stopRequested) RequestStop();
        try
        {
            var exited = process.WaitForExitAsync();
            while (!exited.IsCompleted)
            {
                if (_stopRequested)
                {
                    var winner = await Task.WhenAny(exited, Task.Delay(8000, ct));
                    if (winner != exited && !process.HasExited)
                        process.Kill(entireProcessTree: true);
                }
                await Task.WhenAny(exited, Task.Delay(250, ct));
                ct.ThrowIfCancellationRequested();
            }
            await exited;
            await Task.WhenAll(stderr, stdout);
            return process.ExitCode;
        }
        finally
        {
            lock (_gate) { if (ReferenceEquals(_running, process)) _running = null; }
        }
    }

    private static async Task<string> ResolvePublicPlatformStreamAsync(
        string url, CancellationToken ct)
    {
        var tools = Path.Combine(AppContext.BaseDirectory, "tools");
        var ytDlp = Path.Combine(tools, "yt-dlp.exe");
        if (!File.Exists(ytDlp))
            throw new FileNotFoundException("ไม่พบ yt-dlp ที่รวมมากับ Setup EXE");
        var info = new ProcessStartInfo(ytDlp)
        {
            UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true
        };
        foreach (var arg in new[]
        {
            "--ignore-config", "--no-plugin-dirs", "--no-playlist",
            "--no-warnings", "--socket-timeout", "20",
            "--js-runtimes", "deno:" + Path.Combine(tools, "deno.exe"),
            "--get-url", "-f", "b[protocol*=m3u8]/b", url
        }) info.ArgumentList.Add(arg);
        using var process = Process.Start(info) ??
            throw new IOException("เปิดเครื่องมือค้นหาลิงก์ไลฟ์ไม่สำเร็จ");
        using var registration = ct.Register(() =>
        {
            try { if (!process.HasExited) process.Kill(entireProcessTree: true); }
            catch (InvalidOperationException) { }
        });
        var output = process.StandardOutput.ReadToEndAsync();
        var error = process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync(ct);
        var resolved = (await output).Trim();
        await error; // Never surface signed URLs, cookies or tokens from tool logs.
        var lines = resolved.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
        if (process.ExitCode != 0 || lines.Length != 1 ||
            !DownloadEngine.TryParseUrl(lines[0], out var parsed) || parsed is null)
            throw new IOException("ไม่พบสตรีมสาธารณะที่มีภาพและเสียงรวมกัน หรือแพลตฟอร์มไม่รองรับ");
        return parsed.AbsoluteUri;
    }

    private static async Task<int> RunToolAsync(ProcessStartInfo info, CancellationToken ct)
    {
        using var process = Process.Start(info) ??
            throw new IOException("เปิดเครื่องมือวิเคราะห์สื่อไม่สำเร็จ");
        using var cancel = ct.Register(() =>
        {
            try { if (!process.HasExited) process.Kill(entireProcessTree: true); }
            catch (InvalidOperationException) { }
        });
        var stderr = process.StandardError.ReadToEndAsync();
        var stdout = process.StandardOutput.ReadToEndAsync();
        await process.WaitForExitAsync(ct);
        await Task.WhenAll(stderr, stdout);
        return process.ExitCode;
    }

    private static async Task<double> ProbeDurationAsync(string ffprobe,
        string file, CancellationToken ct)
    {
        var info = new ProcessStartInfo(ffprobe)
        {
            UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true
        };
        foreach (var arg in new[]
        {
            "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", file
        }) info.ArgumentList.Add(arg);
        using var process = Process.Start(info) ??
            throw new IOException("ตรวจความยาวสื่อไม่สำเร็จ");
        var stdout = process.StandardOutput.ReadToEndAsync();
        var stderr = process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync(ct);
        var raw = (await stdout).Trim();
        await stderr;
        if (process.ExitCode != 0 ||
            !double.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture,
                out var duration) || !double.IsFinite(duration) || duration <= 0)
            throw new InvalidDataException("ไฟล์บันทึกยังไม่สมบูรณ์หรืออ่านระยะเวลาไม่ได้");
        return duration;
    }

    private static async Task<bool> ProbeAudioAsync(string ffprobe,
        string file, CancellationToken ct)
    {
        var info = new ProcessStartInfo(ffprobe)
        {
            UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true
        };
        foreach (var arg in new[]
        {
            "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=index", "-of", "csv=p=0", file
        }) info.ArgumentList.Add(arg);
        using var process = Process.Start(info) ??
            throw new IOException("ตรวจแทร็กเสียงไม่สำเร็จ");
        var stdout = process.StandardOutput.ReadToEndAsync();
        var stderr = process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync(ct);
        var result = (await stdout).Trim();
        await stderr;
        if (process.ExitCode != 0) throw new InvalidDataException("ตรวจแทร็กเสียงล้มเหลว");
        return result.Length > 0;
    }

    private static async Task<IReadOnlyList<LiveSilence>> DetectSilencesAsync(
        string ffmpeg, string file, CancellationToken ct)
    {
        var info = new ProcessStartInfo(ffmpeg)
        {
            UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true
        };
        foreach (var arg in new[]
        {
            "-hide_banner", "-nostdin", "-i", file,
            "-map", "0:a:0", "-vn",
            "-af", "silencedetect=noise=-35dB:d=0.6",
            "-f", "null", "-"
        }) info.ArgumentList.Add(arg);
        using var process = Process.Start(info) ??
            throw new IOException("เปิดตัววิเคราะห์ช่วงเงียบไม่สำเร็จ");
        using var cancel = ct.Register(() =>
        {
            try { if (!process.HasExited) process.Kill(entireProcessTree: true); }
            catch (InvalidOperationException) { }
        });
        var stderr = process.StandardError.ReadToEndAsync();
        var stdout = process.StandardOutput.ReadToEndAsync();
        await process.WaitForExitAsync(ct);
        var log = await stderr;
        await stdout;
        if (process.ExitCode != 0)
            throw new IOException("ตรวจจับจุดหยุดพูดไม่สำเร็จ · เก็บต้นฉบับไว้แล้ว");
        return LiveSpeechSegmentPlanner.ParseSilenceLog(log);
    }
}

public sealed record LiveCaptureResult(
    string SessionDirectory, string RecordingPath,
    IReadOnlyList<string> Clips, string Message);

public readonly record struct LiveSilence(double Start, double End);

public static class LiveSpeechSegmentPlanner
{
    private static readonly Regex SilenceStart = new(
        @"silence_start:\s*(?<time>\d+(?:\.\d+)?)", RegexOptions.Compiled);
    private static readonly Regex SilenceEnd = new(
        @"silence_end:\s*(?<time>\d+(?:\.\d+)?)", RegexOptions.Compiled);

    public static IReadOnlyList<LiveSilence> ParseSilenceLog(string log)
    {
        var output = new List<LiveSilence>();
        double? start = null;
        foreach (var line in log.Split('\n'))
        {
            var first = SilenceStart.Match(line);
            if (first.Success && double.TryParse(first.Groups["time"].Value,
                NumberStyles.Float, CultureInfo.InvariantCulture, out var value))
                start = value;
            var last = SilenceEnd.Match(line);
            if (!last.Success || start is null ||
                !double.TryParse(last.Groups["time"].Value,
                    NumberStyles.Float, CultureInfo.InvariantCulture, out var end))
                continue;
            if (end > start.Value + .4)
                output.Add(new LiveSilence(start.Value, end));
            start = null;
        }
        return output;
    }

    /// <summary>
    /// Never insert a clock-only cut: choose a detected quiet interval after
    /// the clip's minimum acceptable duration. If no pause follows, the
    /// remaining recording stays as one longer continuous clip.
    /// Silence is a heuristic, not semantic speech recognition.
    /// </summary>
    public static IReadOnlyList<(double Start, double End)> Plan(
        double durationSeconds, int targetSeconds, IReadOnlyList<LiveSilence> silences)
    {
        if (!double.IsFinite(durationSeconds) || durationSeconds <= 0)
            throw new ArgumentOutOfRangeException(nameof(durationSeconds));
        if (targetSeconds < 60 || targetSeconds > 3600)
            throw new ArgumentOutOfRangeException(nameof(targetSeconds));
        var ranges = new List<(double Start, double End)>();
        double from = 0;
        var allowed = silences.Where(s => double.IsFinite(s.Start) &&
            double.IsFinite(s.End) && s.End - s.Start >= .55 &&
            s.Start > 0 && s.End < durationSeconds).OrderBy(s => s.Start).ToArray();
        for (var i = 0; i < 2048 && from + targetSeconds < durationSeconds; i++)
        {
            var nominal = from + targetSeconds;
            var earliest = from + targetSeconds * .7;
            // Prefer a quiet boundary close to the requested clip duration;
            // if none exists, extend to the next verified pause.
            var nearby = allowed.Where(s => (s.Start + s.End) / 2 >= earliest)
                .Select(s => (Time: (s.Start + s.End) / 2,
                    Distance: Math.Abs((s.Start + s.End) / 2 - nominal)))
                .Where(s => s.Time > from + 1 && s.Time < durationSeconds - 1)
                .ToArray();
            if (nearby.Length == 0) break;
            var cutoff = nearby.Where(s => s.Time <= nominal + targetSeconds * .35)
                .OrderBy(s => s.Distance).Select(s => s.Time).FirstOrDefault();
            if (cutoff <= 0)
                cutoff = nearby.Where(s => s.Time >= nominal)
                    .OrderBy(s => s.Time).Select(s => s.Time).FirstOrDefault();
            if (cutoff <= from + 1) break;
            ranges.Add((from, cutoff));
            from = cutoff;
        }
        ranges.Add((from, durationSeconds));
        return ranges;
    }
}
