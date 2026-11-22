using System.ComponentModel;
using System.Diagnostics;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;

namespace XStageDownloadManager;

/// <summary>
/// Checks publicly accessible live manifests or public platform metadata
/// without opening a browser/player or downloading media. One waiting session
/// is owned by a LiveStreamCaptureForm; no background Windows service or
/// persistent unattended execution is implied.
/// </summary>
public sealed class LiveBackgroundMonitor
{
    private static readonly HttpClient ManifestHttp = new(new SocketsHttpHandler
    {
        AutomaticDecompression = DecompressionMethods.None,
        AllowAutoRedirect = true,
        MaxAutomaticRedirections = 3
    }) { Timeout = Timeout.InfiniteTimeSpan };

    public static readonly int[] AllowedPollSeconds = { 15, 30, 60 };

    public static bool IsActivePlatformStatus(string? status) =>
        string.Equals(status?.Trim(), "is_live", StringComparison.OrdinalIgnoreCase);

    public static bool IsActiveHlsManifest(string? content)
    {
        if (string.IsNullOrEmpty(content) ||
            !content.TrimStart('\uFEFF', ' ', '\t', '\r', '\n')
                .StartsWith("#EXTM3U", StringComparison.Ordinal))
            return false;
        // A master manifest alone does not demonstrate that a broadcast
        // is currently on air; require a live media playlist.
        return content.Contains("#EXT-X-MEDIA-SEQUENCE:", StringComparison.Ordinal) &&
               (content.Contains("#EXTINF:", StringComparison.Ordinal) ||
                content.Contains("#EXT-X-PART:", StringComparison.Ordinal)) &&
               !content.Contains("#EXT-X-ENDLIST", StringComparison.Ordinal);
    }

    public static bool IsActiveDashManifest(string? content) =>
        !string.IsNullOrWhiteSpace(content) &&
        Regex.IsMatch(content,
            @"<MPD\b[^>]*\btype\s*=\s*[""']dynamic[""']",
            RegexOptions.IgnoreCase | RegexOptions.CultureInvariant,
            TimeSpan.FromSeconds(1));

    public static IReadOnlyList<string> BuildPlatformStatusArguments(string url, string tools)
    {
        if (!SocialVideoDownloader.IsVideoUrl(url))
            throw new ArgumentException("ลิงก์นี้ไม่ใช่แพลตฟอร์มวิดีโอสาธารณะที่รองรับ", nameof(url));
        return new[]
        {
            "--ignore-config", "--no-plugin-dirs", "--no-playlist",
            "--no-warnings", "--skip-download",
            "--socket-timeout", "12", "--retries", "1",
            "--extractor-retries", "1",
            "--js-runtimes", "deno:" + Path.Combine(tools, "deno.exe"),
            "--print", "xstage-live-status:%(live_status)s", url
        };
    }

    public async Task WaitForLiveAsync(string url, int pollSeconds,
        Action<string>? onStatus, CancellationToken cancellationToken = default)
    {
        if (!LiveStreamCapture.IsSupportedSource(url))
            throw new ArgumentException("ต้องระบุลิงก์ไลฟ์สาธารณะ HLS, DASH หรือแพลตฟอร์มที่รองรับ");
        if (!AllowedPollSeconds.Contains(pollSeconds))
            throw new ArgumentOutOfRangeException(nameof(pollSeconds));
        var attempts = 0;
        while (true)
        {
            cancellationToken.ThrowIfCancellationRequested();
            attempts++;
            onStatus?.Invoke($"กำลังตรวจสอบไลฟ์ · รอบที่ {attempts:N0} (ทุก {pollSeconds} วินาที)");
            bool active;
            try
            {
                active = SocialVideoDownloader.IsVideoUrl(url)
                    ? await ProbePublicPlatformAsync(url, cancellationToken)
                    : await ProbeManifestAsync(url, cancellationToken);
            }
            catch (Exception exception) when (
                exception is HttpRequestException or IOException or
                Win32Exception or OperationCanceledException &&
                !cancellationToken.IsCancellationRequested)
            {
                // Offline/upcoming streams can fail extraction or networking.
                // Never guess "live" from a failed request. Bound the polling
                // cadence and surface the error instead of silently stalling.
                onStatus?.Invoke("ยังตรวจไม่พบไลฟ์ · เครือข่าย/แพลตฟอร์มไม่พร้อม จะลองใหม่");
                active = false;
            }
            if (active)
            {
                onStatus?.Invoke("ตรวจพบไลฟ์ที่กำลังออกอากาศ · เริ่มบันทึกโดยไม่เปิดหน้าวิดีโอ");
                return;
            }
            onStatus?.Invoke($"ยังไม่เริ่มไลฟ์ · ตรวจซ้ำใน {pollSeconds} วินาที");
            await Task.Delay(TimeSpan.FromSeconds(pollSeconds), cancellationToken);
        }
    }

    private static async Task<bool> ProbeManifestAsync(string url, CancellationToken ct)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
        timeout.CancelAfter(TimeSpan.FromSeconds(12));
        using var response = await ManifestHttp.GetAsync(url,
            HttpCompletionOption.ResponseHeadersRead, timeout.Token);
        if (response.StatusCode is HttpStatusCode.Forbidden or HttpStatusCode.Unauthorized)
            throw new UnauthorizedAccessException(
                "แหล่งสตรีมต้องได้รับอนุญาตให้เข้าถึง ไม่รองรับการข้ามสิทธิ์");
        if (!response.IsSuccessStatusCode) return false;
        await using var stream = await response.Content.ReadAsStreamAsync(timeout.Token);
        using var reader = new StreamReader(stream, Encoding.UTF8, true, 1024, leaveOpen: false);
        // Bound memory and network traffic, even if a hostile URL returns a
        // large file rather than a text manifest.
        var buffer = new char[64 * 1024];
        var count = 0;
        while (count < buffer.Length)
        {
            var read = await reader.ReadAsync(buffer.AsMemory(count, buffer.Length - count),
                timeout.Token);
            if (read == 0) break;
            count += read;
        }
        var manifest = new string(buffer, 0, count);
        return url.Contains(".m3u8", StringComparison.OrdinalIgnoreCase)
            ? IsActiveHlsManifest(manifest) : IsActiveDashManifest(manifest);
    }

    private static async Task<bool> ProbePublicPlatformAsync(string url, CancellationToken ct)
    {
        var tools = Path.Combine(AppContext.BaseDirectory, "tools");
        var ytDlp = Path.Combine(tools, "yt-dlp.exe");
        if (!File.Exists(ytDlp))
            throw new FileNotFoundException(
                "ไม่พบ yt-dlp ที่รวมในตัวติดตั้ง ไม่สามารถเฝ้ารอสตรีมสาธารณะ");
        using var info = new Process { StartInfo = new ProcessStartInfo(ytDlp)
        {
            UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8
        }};
        foreach (var arg in BuildPlatformStatusArguments(url, tools))
            info.StartInfo.ArgumentList.Add(arg);
        if (!info.Start()) throw new IOException("เปิดตัวตรวจสถานะไลฟ์ไม่สำเร็จ");
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
        timeout.CancelAfter(TimeSpan.FromSeconds(35));
        using var abort = timeout.Token.Register(() =>
        {
            try { if (!info.HasExited) info.Kill(entireProcessTree: true); }
            catch (InvalidOperationException) { }
            catch (Win32Exception) { }
        });
        var output = info.StandardOutput.ReadToEndAsync(timeout.Token);
        // Drain errors; never surface private signed media URLs or tokens.
        var error = info.StandardError.ReadToEndAsync(timeout.Token);
        await info.WaitForExitAsync(timeout.Token);
        var stdout = await output;
        await error;
        if (info.ExitCode != 0) return false;
        return stdout.Split(new[] { '\n', '\r' }, StringSplitOptions.RemoveEmptyEntries)
            .Any(line => line.Trim().Equals(
                "xstage-live-status:is_live", StringComparison.OrdinalIgnoreCase));
    }
}
