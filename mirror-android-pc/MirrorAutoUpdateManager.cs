using System.Diagnostics;
using System.Net;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Windows.Forms;

namespace XStageMirrorAndroidPC;

/// <summary>
/// Checks X-Stage's published Windows preview feed on startup and every 30 minutes.
/// Downloads the complete Inno Setup installer, checks the exact release URL and SHA-256,
/// then starts an in-place upgrade. Windows elevation remains under OS control.
/// Never executes an unverified download or an arbitrary URL from the manifest.
/// </summary>
internal sealed class MirrorAutoUpdateManager
{
    private const string Feed =
        "https://webbase-x.github.io/xstage/downloads/mirror-android-pc-preview-latest.json";
    private const string ReleaseRoot =
        "https://github.com/webbase-x/xstage/releases/download/";
    private static readonly TimeSpan Interval = TimeSpan.FromMinutes(30);
    private const long MinimumInstallerBytes = 5_000_000;
    private const long MaximumInstallerBytes = 1_000_000_000;

    private readonly string _directory = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "X-Stage", "Mirror Android PC", "updates");
    private readonly Func<bool> _canUpgrade;
    private readonly Action<string> _status;
    private readonly Action _closeForInstall;
    private int _busy;
    private DateTimeOffset _nextCheck = DateTimeOffset.MinValue;

    internal MirrorAutoUpdateManager(Func<bool> canUpgrade, Action<string> status, Action closeForInstall)
    {
        _canUpgrade = canUpgrade;
        _status = status;
        _closeForInstall = closeForInstall;
    }

    internal async Task CheckAsync()
    {
        if (!_canUpgrade() || DateTimeOffset.UtcNow < _nextCheck ||
            Interlocked.CompareExchange(ref _busy, 1, 0) != 0)
            return;
        _nextCheck = DateTimeOffset.UtcNow.Add(Interval);
        string? partial = null;
        try
        {
            using var client = new HttpClient
            {
                Timeout = TimeSpan.FromMinutes(6)
            };
            using var feedTimeout = new CancellationTokenSource(TimeSpan.FromSeconds(8));
            using var reply = await client.GetAsync(Feed, feedTimeout.Token);
            reply.EnsureSuccessStatusCode();
            using var document = JsonDocument.Parse(await reply.Content.ReadAsStringAsync());
            var root = document.RootElement;
            if (!TryReadUpdate(root, out var item)) return;

            _status($"พบ X-Stage Mirror PC v{item.Version} Build {item.Build} · กำลังดาวน์โหลด");
            Directory.CreateDirectory(_directory);
            partial = Path.Combine(_directory, item.FileName + ".partial-" + Guid.NewGuid().ToString("N"));
            var verified = Path.Combine(_directory, item.FileName);
            // Revalidate even an already-staged file, rather than trusting its name.
            if (!await MatchesHashAsync(verified, item.Sha256))
            {
                await DownloadVerifiedAsync(client, item, partial, (percent, bytes) =>
                    _status(percent is int p
                        ? $"ดาวน์โหลดอัปเดต v{item.Version} Build {item.Build} · {p}%"
                        : $"ดาวน์โหลดอัปเดต · {bytes / (1024 * 1024)} MB"));
                File.Move(partial, verified, overwrite: true);
                partial = null;
            }
            if (!_canUpgrade())
            {
                _nextCheck = DateTimeOffset.MinValue;
                _status("ดาวน์โหลดอัปเดตแล้ว · รอ Windows ติดตั้งส่วนประกอบให้เสร็จ");
                return;
            }
            _status("ตรวจสอบ SHA-256 ผ่านแล้ว · ติดตั้งรุ่นใหม่อัตโนมัติ");

            // The installer upgrades the same AppId and install folder. Windows
            // may display UAC. Never bypass OS permission or pretend it was granted.
            using var installer = Process.Start(new ProcessStartInfo
            {
                FileName = verified,
                Arguments = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART " +
                            "/CLOSEAPPLICATIONS /FORCECLOSEAPPLICATIONS /NORESTARTAPPLICATIONS",
                UseShellExecute = true,
                Verb = "open",
                WorkingDirectory = _directory
            }) ?? throw new InvalidOperationException("ไม่สามารถเปิดตัวติดตั้งที่ตรวจสอบแล้ว");
            _closeForInstall(); // Inno Setup will relaunch the new app after success.
        }
        catch (System.ComponentModel.Win32Exception ex) when (ex.NativeErrorCode == 1223)
        {
            _status("Windows ไม่อนุญาตการติดตั้งอัปเดต · แอปเดิมยังทำงาน");
        }
        catch (Exception ex)
        {
            _status("อัปเดตอัตโนมัติไม่สำเร็จ · ใช้แอปรุ่นเดิมได้");
            try
            {
                var log = Path.Combine(Path.GetDirectoryName(_directory)!, "receiver.log");
                Directory.CreateDirectory(Path.GetDirectoryName(log)!);
                File.AppendAllText(log, $"{DateTimeOffset.Now:O}  Update: {ex.GetType().Name}: {ex.Message}{Environment.NewLine}");
            }
            catch { /* Logging must not block the local Miracast receiver. */ }
        }
        finally
        {
            if (partial is not null)
            {
                try { File.Delete(partial); } catch { }
            }
            Interlocked.Exchange(ref _busy, 0);
        }
    }

    private static bool TryReadUpdate(JsonElement root, out Update item)
    {
        item = default!;
        try
        {
            if (root.GetProperty("available").ValueKind != JsonValueKind.True ||
                root.GetProperty("channel").GetString() != "preview" ||
                root.GetProperty("app").GetString() != "X-Stage Mirror Android PC" ||
                root.GetProperty("platform").GetString() != "Windows 10/11 x64 · Miracast")
                return false;
            int build = root.GetProperty("build").GetInt32();
            if (build <= InstalledBuild()) return false;
            var version = root.GetProperty("version").GetString() ?? "";
            var filename = root.GetProperty("file").GetString() ?? "";
            var hash = root.GetProperty("sha256").GetString() ?? "";
            if (!Regex.IsMatch(version, @"^\d+\.\d+\.\d+$", RegexOptions.CultureInvariant) ||
                !Regex.IsMatch(hash, @"\A[0-9a-fA-F]{64}\z", RegexOptions.CultureInvariant))
                return false;
            var expectedFile = $"X-Stage-Mirror-Android-PC-v{version}-build{build}-win-x64-Setup.exe";
            if (!string.Equals(filename, expectedFile, StringComparison.Ordinal)) return false;
            var expectedUrl = ReleaseRoot +
                $"xstage-mirror-android-pc-v{version}-build{build}-preview/" + expectedFile;
            var actualUrl = root.GetProperty("download_url").GetString();
            if (!string.Equals(actualUrl, expectedUrl, StringComparison.Ordinal)) return false;

            // A higher build must not disguise a lower semantic version.
            var currentVersion = FileVersionInfo.GetVersionInfo(Application.ExecutablePath).FileVersion ?? "";
            var currentParts = currentVersion.Split('.');
            if (currentParts.Length != 4 || !Version.TryParse(string.Join(".", currentParts.Take(3)), out var installed) ||
                !Version.TryParse(version, out var proposed) || proposed < installed)
                return false;
            item = new Update(version, build, expectedFile, expectedUrl, hash.ToLowerInvariant());
            return true;
        }
        catch (Exception ex) when (ex is KeyNotFoundException or FormatException or InvalidOperationException or ArgumentException)
        {
            return false;
        }
    }

    private static int InstalledBuild()
    {
        var parts = (FileVersionInfo.GetVersionInfo(Application.ExecutablePath).FileVersion ?? "").Split('.');
        if (parts.Length != 4 || !int.TryParse(parts[3], out var build))
            throw new InvalidOperationException("ไม่พบเลข Build ของ EXE จึงไม่ติดตั้งอัตโนมัติ");
        return build;
    }

    private static async Task<bool> MatchesHashAsync(string path, string expected)
    {
        if (!File.Exists(path)) return false;
        var file = new FileInfo(path);
        if (file.Length is < MinimumInstallerBytes or > MaximumInstallerBytes) return false;
        await using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read,
            128 * 1024, FileOptions.Asynchronous | FileOptions.SequentialScan);
        if (stream.ReadByte() != 'M' || stream.ReadByte() != 'Z') return false;
        stream.Position = 0;
        var actual = Convert.ToHexString(await SHA256.HashDataAsync(stream));
        return actual.Equals(expected, StringComparison.OrdinalIgnoreCase);
    }

    private static async Task DownloadVerifiedAsync(HttpClient client, Update update, string destination, Action<int?, long> onProgress)
    {
        using var response = await client.GetAsync(
            update.Url, HttpCompletionOption.ResponseHeadersRead);
        response.EnsureSuccessStatusCode();
        if (response.Content.Headers.ContentLength is long size &&
            (size < MinimumInstallerBytes || size > MaximumInstallerBytes))
            throw new InvalidDataException("ขนาดตัวติดตั้งผิดปกติ");

        await using var network = await response.Content.ReadAsStreamAsync();
        // Finish writing and RELEASE the exclusive FileShare.None handle before
        // reopening this file for the PE header check. Keeping the writer alive
        // used to throw IOException on every update, even on a healthy Windows PC.
        await using (var output = new FileStream(destination, FileMode.CreateNew, FileAccess.Write,
            FileShare.None, 128 * 1024, FileOptions.Asynchronous))
        {
            using var digest = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            var buffer = new byte[128 * 1024];
            long transferred = 0;
            int bytesRead;
            int lastPercent = -5;
            long lastReportedBytes = 0;
            while ((bytesRead = await network.ReadAsync(buffer.AsMemory())) > 0)
            {
                transferred += bytesRead;
                if (transferred > MaximumInstallerBytes)
                    throw new InvalidDataException("ไฟล์อัปเดตใหญ่เกินขีดจำกัด");
                digest.AppendData(buffer, 0, bytesRead);
                await output.WriteAsync(buffer.AsMemory(0, bytesRead));
                if (response.Content.Headers.ContentLength is long total && total > 0)
                {
                    var percent = (int)Math.Clamp(transferred * 100L / total, 0L, 100L);
                    if (percent >= lastPercent + 5 || percent == 100)
                    {
                        lastPercent = percent;
                        onProgress(percent, transferred);
                    }
                }
                else if (transferred - lastReportedBytes >= 5L * 1024 * 1024)
                {
                    lastReportedBytes = transferred;
                    onProgress(null, transferred);
                }
            }
            await output.FlushAsync();
            if (transferred < MinimumInstallerBytes)
                throw new InvalidDataException("ดาวน์โหลดตัวติดตั้งไม่ครบ");
            var calculated = Convert.ToHexString(digest.GetHashAndReset());
            if (!calculated.Equals(update.Sha256, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("SHA-256 ไม่ตรงกับ GitHub Release ที่ประกาศ");
        }

        // The exact known asset is a PE installer, not an HTML error page.
        await using var check = new FileStream(destination, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (check.ReadByte() != 'M' || check.ReadByte() != 'Z')
            throw new InvalidDataException("ไฟล์ที่ดาวน์โหลดไม่ใช่ตัวติดตั้ง Windows");
    }

    private sealed record Update(string Version, int Build, string FileName, string Url, string Sha256);
}
