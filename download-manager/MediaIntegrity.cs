using System.Buffers.Binary;
using System.Diagnostics;
using System.Globalization;
using System.Text;
using System.Text.Json;

namespace XStageDownloadManager;

/// <summary>
/// A successful downloader exit is not proof that the resulting media can be
/// opened. Check MP4 box structure and FFprobe's actual streams before marking
/// a download complete. MP4 conversion writes a private temporary output and
/// exposes the final file only after validation.
/// </summary>
public static class MediaIntegrity
{
    public sealed record MediaInfo(string VideoCodec, string AudioCodec, double DurationSeconds)
    {
        public bool HasVideo => VideoCodec.Length > 0;
        public bool HasAudio => AudioCodec.Length > 0;
    }

    // Reject the exact broken MP4 uploaded by a user: ftyp + mdat but no moov.
    // Scan top-level box headers by seeking; never load entire videos into RAM.
    public static bool HasCompleteMp4Boxes(string path)
    {
        if (!File.Exists(path)) return false;
        using var input = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (input.Length < 32) return false;
        bool ftyp = false, moov = false;
        long position = 0;
        Span<byte> header = stackalloc byte[16];
        while (position + 8 <= input.Length)
        {
            input.Position = position;
            input.ReadExactly(header[..8]);
            ulong length = BinaryPrimitives.ReadUInt32BigEndian(header[..4]);
            var type = Encoding.ASCII.GetString(header.Slice(4, 4));
            var headSize = 8;
            if (length == 1)
            {
                if (position + 16 > input.Length) return false;
                input.ReadExactly(header.Slice(8, 8));
                length = BinaryPrimitives.ReadUInt64BigEndian(header.Slice(8, 8));
                headSize = 16;
            }
            else if (length == 0)
                length = (ulong)(input.Length - position);

            if (length < (ulong)headSize || length > (ulong)(input.Length - position))
                return false;
            if (type == "ftyp" && position == 0) ftyp = true;
            if (type == "moov") moov = true;
            position += (long)length;
        }
        return ftyp && moov && position == input.Length;
    }

    public static async Task<MediaInfo> VerifyAsync(
        string path, string ffprobeExe, bool audioOnly, CancellationToken cancellation)
    {
        if (!File.Exists(path) || new FileInfo(path).Length <= 0)
            throw new IOException("ไม่พบไฟล์สื่อที่ดาวน์โหลดเสร็จ หรือไฟล์ว่างเปล่า");
        if (Path.GetExtension(path).Equals(".mp4", StringComparison.OrdinalIgnoreCase) &&
            !HasCompleteMp4Boxes(path))
            throw new IOException("MP4 ไม่สมบูรณ์: ไม่พบกล่อง moov หรือโครงสร้าง MP4 ถูกตัดขาด");

        var info = new ProcessStartInfo(ffprobeExe)
        {
            UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8
        };
        foreach (var argument in new[] { "-v", "error", "-show_entries",
                "format=duration:stream=codec_type,codec_name,width,height", "-of", "json", path })
            info.ArgumentList.Add(argument);
        using var probe = new Process { StartInfo = info };
        if (!probe.Start()) throw new IOException("ไม่สามารถเปิด FFprobe เพื่อตรวจสอบไฟล์สื่อ");
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        timeout.CancelAfter(TimeSpan.FromSeconds(45));
        using var abort = timeout.Token.Register(() =>
        {
            try { if (!probe.HasExited) probe.Kill(entireProcessTree: true); }
            catch (InvalidOperationException) { }
            catch (System.ComponentModel.Win32Exception) { }
        });
        string stdout, stderr;
        try
        {
            var outTask = probe.StandardOutput.ReadToEndAsync(timeout.Token);
            var errTask = probe.StandardError.ReadToEndAsync(timeout.Token);
            await probe.WaitForExitAsync(timeout.Token);
            stdout = await outTask;
            stderr = await errTask;
        }
        catch (OperationCanceledException) when (!cancellation.IsCancellationRequested)
        {
            throw new IOException("FFprobe ตรวจไฟล์นานผิดปกติ (เกิน 45 วินาที)");
        }
        if (probe.ExitCode != 0)
            throw new IOException("ไฟล์สื่อเสียหายหรืออ่านไม่ได้: " +
                                  (stderr.Contains("moov atom not found", StringComparison.OrdinalIgnoreCase)
                                      ? "ไม่พบ moov atom ใน MP4"
                                      : "FFprobe ไม่สามารถอ่านข้อมูลสตรีมได้"));

        try
        {
            using var document = JsonDocument.Parse(stdout);
            var root = document.RootElement;
            var video = "", audio = "";
            if (root.TryGetProperty("streams", out var streams))
                foreach (var stream in streams.EnumerateArray())
                {
                    if (!stream.TryGetProperty("codec_type", out var type) ||
                        !stream.TryGetProperty("codec_name", out var codec)) continue;
                    var kind = type.GetString() ?? "";
                    var name = codec.GetString() ?? "";
                    if (kind == "video")
                    {
                        int width = stream.TryGetProperty("width", out var w) && w.TryGetInt32(out var ww) ? ww : 0;
                        int height = stream.TryGetProperty("height", out var h) && h.TryGetInt32(out var hh) ? hh : 0;
                        if (width > 0 && height > 0) video = name;
                    }
                    else if (kind == "audio") audio = name;
                }

            double duration = 0;
            if (root.TryGetProperty("format", out var format) &&
                format.TryGetProperty("duration", out var value))
                double.TryParse(value.ToString(), NumberStyles.Float, CultureInfo.InvariantCulture, out duration);

            if (!double.IsFinite(duration) || duration <= 0)
                throw new IOException("ไฟล์สื่อไม่มีระยะเวลาที่อ่านได้ (อาจดาวน์โหลดหรือแปลงไม่ครบ)");
            if (audioOnly ? audio.Length == 0 : video.Length == 0)
                throw new IOException(audioOnly ? "ไฟล์เสียงไม่มีสตรีมเสียงที่อ่านได้"
                                                : "ไฟล์วิดีโอไม่มีสตรีมภาพที่อ่านได้");
            return new MediaInfo(video, audio, duration);
        }
        catch (JsonException)
        {
            throw new IOException("FFprobe ส่งข้อมูลตรวจสอบที่ไม่สมบูรณ์");
        }
    }

    /// <summary>
    /// Prefer fast stream copy for H.264/AAC; transcode incompatible codecs
    /// to universally playable H.264/AAC. Never overwrite a user's file.
    /// The MKV/source stays intact if conversion or verification fails.
    /// </summary>
    public static async Task<string> FinishMp4Async(
        string sourcePath, string folder, string work, string tools,
        CancellationToken cancellation, Action<string>? onPhase = null)
    {
        var ffprobe = Path.Combine(tools, "ffprobe.exe");
        var ffmpeg = Path.Combine(tools, "ffmpeg.exe");
        var source = await VerifyAsync(sourcePath, ffprobe, false, cancellation);
        var compatible = source.VideoCodec == "h264" &&
                         (!source.HasAudio || source.AudioCodec == "aac");
        if (Path.GetExtension(sourcePath).Equals(".mp4", StringComparison.OrdinalIgnoreCase) &&
            compatible)
            return sourcePath;

        Directory.CreateDirectory(work);
        var temp = Path.Combine(work, "mp4-output-" + Guid.NewGuid().ToString("N") + ".mp4");
        try
        {
            // Remux without quality loss if already H264/AAC; otherwise
            // transcode to codecs supported on Windows, iOS, Android and TV.
            await TranscodeAsync(sourcePath, temp, ffmpeg, compatible,
                cancellation, onPhase);
            var ready = await VerifyAsync(temp, ffprobe, false, cancellation);
            if (ready.VideoCodec != "h264" ||
                (ready.HasAudio && ready.AudioCodec != "aac"))
                throw new IOException("MP4 ที่แปลงไม่ใช่ H.264/AAC ตามที่ต้องการ");
            var filename = Path.GetFileNameWithoutExtension(sourcePath) + ".mp4";
            var destination = DownloadFileNaming.UniqueOutput(folder, filename);
            File.Move(temp, destination);
            return destination;
        }
        finally
        {
            try { if (File.Exists(temp)) File.Delete(temp); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
    }

    private static async Task TranscodeAsync(
        string source, string destination, string ffmpegExe, bool copy,
        CancellationToken cancellation, Action<string>? onPhase)
    {
        onPhase?.Invoke(copy ? "กำลังรวมไฟล์ MP4 (ไม่ลดคุณภาพ)"
                              : "กำลังแปลง MP4 เป็น H.264/AAC");
        var info = new ProcessStartInfo(ffmpegExe)
        {
            UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
        };
        var args = new List<string> { "-hide_banner", "-nostdin", "-v", "error",
            "-y", "-i", source, "-map", "0:v:0", "-map", "0:a?" };
        if (copy) args.AddRange(new[] { "-c:v", "copy", "-c:a", "copy" });
        else args.AddRange(new[] { "-c:v", "libx264", "-preset", "veryfast",
                                  "-crf", "21", "-pix_fmt", "yuv420p",
                                  "-c:a", "aac", "-b:a", "192k" });
        args.AddRange(new[] { "-movflags", "+faststart",
                              "-progress", "pipe:1", "-nostats", destination });
        foreach (var arg in args) info.ArgumentList.Add(arg);

        using var process = new Process { StartInfo = info };
        if (!process.Start()) throw new IOException("ไม่สามารถเปิด FFmpeg เพื่อแปลง MP4");
        using var abort = cancellation.Register(() =>
        {
            try { if (!process.HasExited) process.Kill(entireProcessTree: true); }
            catch (InvalidOperationException) { }
            catch (System.ComponentModel.Win32Exception) { }
        });
        var progressTask = Task.Run(async () =>
        {
            while (await process.StandardOutput.ReadLineAsync(cancellation) is { } line)
            {
                if (line.StartsWith("out_time=", StringComparison.Ordinal))
                    onPhase?.Invoke(copy ? "กำลังรวม MP4: " + line[9..]
                                          : "กำลังแปลง MP4: " + line[9..]);
            }
        }, cancellation);
        var errorsTask = process.StandardError.ReadToEndAsync(cancellation);
        await process.WaitForExitAsync(cancellation);
        await progressTask;
        var errors = await errorsTask;
        if (process.ExitCode != 0)
            throw new IOException("แปลง MP4 ไม่สำเร็จ (FFmpeg " + process.ExitCode + "): " +
                (errors.Length > 300 ? errors[^300..] : errors));
    }
}
