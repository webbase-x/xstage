using System.Diagnostics;
using System.Net;
using System.Security.Cryptography;

namespace XStageDownloadManager;

/// <summary>
/// Downloads a publisher-pinned Setup EXE inside the application, verifies the
/// exact size and SHA-256, then hands installation to a separate copy of this
/// self-contained executable so Windows can replace the original safely.
/// </summary>
public static class SelfUpdater
{
    private static readonly HttpClient Client = new(new HttpClientHandler
    {
        AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate,
        AllowAutoRedirect = true
    }) { Timeout = Timeout.InfiniteTimeSpan };

    // Match the 64-bit Inno Setup {autopf} destination. Do not run the
    // obsolete per-user EXE after migrating to an all-users installation.
    public static string InstalledProgramFilesExe => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
        "X-Stage", "Download Manager", "XStageDownloadManager.exe");

    private static string UpdateFolder => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "X-Stage", "Download Manager", "updates");

    public static async Task<string> DownloadVerifiedAsync(
        DownloadManagerRelease release, IProgress<double>? progress = null,
        CancellationToken cancellation = default)
    {
        if (!UpdateChecker.IsNewer(release.Version, release.Build))
            throw new IOException("ไม่พบอัปเดตรุ่นใหม่กว่าที่ติดตั้ง");
        var expectedName = $"X-Stage-Download-Manager-v{release.Version}-build{release.Build}-win-x64-Setup.exe";
        var expectedUrl = $"https://github.com/webbase-x/xstage/releases/download/xstage-download-manager-v{release.Version}-build{release.Build}-preview/{expectedName}";
        if (release.Filename != expectedName || release.Url != expectedUrl ||
            release.Sha256.Length != 64 || !release.Sha256.All(Uri.IsHexDigit) ||
            release.Size < 1024)
            throw new IOException("ข้อมูลแหล่งอัปเดตไม่ผ่านการตรวจสอบ");

        Directory.CreateDirectory(UpdateFolder);
        var destination = Path.Combine(UpdateFolder, expectedName);
        if (File.Exists(destination))
        {
            if (await VerifyFileAsync(destination, release.Sha256, release.Size, cancellation))
            {
                progress?.Report(100);
                return destination;
            }
            File.Delete(destination);
        }

        var partial = destination + ".partial";
        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Get, expectedUrl);
            request.Headers.UserAgent.ParseAdd("XStageDownloadManager/Updater");
            using var response = await Client.SendAsync(
                request, HttpCompletionOption.ResponseHeadersRead, cancellation);
            response.EnsureSuccessStatusCode();
            if (response.Content.Headers.ContentLength is long reportedSize &&
                reportedSize != release.Size)
                throw new IOException("ขนาดไฟล์ติดตั้งไม่ตรงกับข้อมูลอัปเดต");

            await using (var source = await response.Content.ReadAsStreamAsync(cancellation))
            await using (var output = new FileStream(partial, FileMode.Create, FileAccess.Write,
                             FileShare.None, 131072, FileOptions.Asynchronous))
            using (var digest = IncrementalHash.CreateHash(HashAlgorithmName.SHA256))
            {
                var buffer = new byte[131072];
                long total = 0;
                int read;
                while ((read = await source.ReadAsync(buffer, cancellation)) != 0)
                {
                    total += read;
                    if (total > release.Size)
                        throw new IOException("ไฟล์ติดตั้งใหญ่กว่าที่เผยแพร่ไว้");
                    digest.AppendData(buffer, 0, read);
                    await output.WriteAsync(buffer.AsMemory(0, read), cancellation);
                    progress?.Report(100.0 * total / release.Size);
                }
                await output.FlushAsync(cancellation);
                var actualHash = Convert.ToHexString(digest.GetHashAndReset()).ToLowerInvariant();
                if (total != release.Size ||
                    !string.Equals(actualHash, release.Sha256, StringComparison.OrdinalIgnoreCase))
                    throw new IOException("ตรวจสอบ SHA-256/ขนาดไฟล์อัปเดตไม่ผ่าน — ไม่ติดตั้งไฟล์นี้");
            }
            File.Move(partial, destination, true);
            progress?.Report(100);
            return destination;
        }
        catch
        {
            try { if (File.Exists(partial)) File.Delete(partial); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
            throw;
        }
    }

    private static async Task<bool> VerifyFileAsync(
        string path, string expectedSha, long expectedSize, CancellationToken ct = default)
    {
        if (!File.Exists(path) || new FileInfo(path).Length != expectedSize)
            return false;
        await using var stream = new FileStream(path, FileMode.Open, FileAccess.Read,
            FileShare.Read, 131072, FileOptions.Asynchronous);
        var digest = await SHA256.HashDataAsync(stream, ct);
        return Convert.ToHexString(digest).Equals(expectedSha, StringComparison.OrdinalIgnoreCase);
    }

    public static void LaunchInstallerHelper(string verifiedSetup, DownloadManagerRelease release)
    {
        // Copy the current self-contained EXE to user-local temporary storage.
        // It can run the updater without locking the installed application binary.
        var appExe = Environment.ProcessPath ??
                     throw new IOException("ไม่พบไฟล์แอปสำหรับเปิดใหม่หลังอัปเดต");
        if (!File.Exists(appExe)) throw new FileNotFoundException("ไม่พบไฟล์แอป", appExe);
        if (!File.Exists(verifiedSetup) || new FileInfo(verifiedSetup).Length != release.Size)
            throw new IOException("ไฟล์อัปเดตที่ตรวจสอบแล้วไม่อยู่ในตำแหน่งที่คาดหวัง");

        Directory.CreateDirectory(UpdateFolder);
        var helper = Path.Combine(UpdateFolder, "xstage-update-helper-" + Guid.NewGuid().ToString("N") + ".exe");
        File.Copy(appExe, helper);
        try
        {
            var info = new ProcessStartInfo(helper)
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                WorkingDirectory = UpdateFolder
            };
            foreach (var arg in new[] {
                "--apply-verified-update", Environment.ProcessId.ToString(),
                verifiedSetup, appExe, release.Sha256, release.Size.ToString(),
                release.Version, release.Build.ToString()
            }) info.ArgumentList.Add(arg);
            using var process = Process.Start(info);
            if (process is null) throw new IOException("ไม่สามารถเริ่มกระบวนการติดตั้งอัปเดต");
        }
        catch
        {
            try { File.Delete(helper); } catch (IOException) { }
            throw;
        }
    }

    // Called by Program.Main *before* creating the primary application mutex.
    public static int ApplyUpdateInHelper(string[] args)
    {
        if (args.Length != 8 || !int.TryParse(args[1], out var oldPid) ||
            !long.TryParse(args[5], out var size) || !int.TryParse(args[7], out var build))
            return 2;
        var setup = args[2];
        var previousExe = args[3];
        var installedExe = InstalledProgramFilesExe;
        var sha = args[4];
        var version = args[6];
        var log = Path.Combine(UpdateFolder, "last-update.log");

        void WriteLog(string message)
        {
            try
            {
                Directory.CreateDirectory(UpdateFolder);
                File.AppendAllText(log, DateTimeOffset.Now.ToString("O") + " " + message +
                    Environment.NewLine);
            }
            catch (IOException) { }
        }

        try
        {
            var expectedName = $"X-Stage-Download-Manager-v{version}-build{build}-win-x64-Setup.exe";
            if (Path.GetFileName(setup) != expectedName ||
                Path.GetFullPath(setup) != Path.Combine(UpdateFolder, expectedName) ||
                sha.Length != 64 || !sha.All(Uri.IsHexDigit))
                throw new IOException("ไฟล์ติดตั้งไม่ตรงกับอัปเดตที่อนุญาต");
            if (!VerifyFileAsync(setup, sha, size).GetAwaiter().GetResult())
                throw new IOException("SHA-256 ไม่ตรง: ยกเลิกการติดตั้ง");

            try
            {
                using var previous = Process.GetProcessById(oldPid);
                if (!previous.WaitForExit(90000))
                    throw new IOException("แอปเดิมยังไม่ปิด จึงไม่ติดตั้งทับ");
            }
            catch (ArgumentException) { /* The main process already exited. */ }

            // Program Files requires UAC. Prompt for elevation only after
            // SHA-256 verification and after the previous app has exited.
            // The helper remains at user integrity level and later relaunches
            // the installed app without administrator privileges.
            var install = new ProcessStartInfo(setup)
            {
                UseShellExecute = true,
                Verb = "runas",
                WorkingDirectory = UpdateFolder
            };
            foreach (var arg in new[] { "/VERYSILENT", "/SUPPRESSMSGBOXES",
                                         "/NORESTART", "/CLOSEAPPLICATIONS" })
                install.ArgumentList.Add(arg);
            using var process = Process.Start(install) ??
                                throw new IOException("เริ่มตัวติดตั้งไม่สำเร็จ");
            if (!process.WaitForExit(600000))
            {
                WriteLog("Installer timeout; not claiming success or launching a second installer.");
                return 3;
            }
            if (process.ExitCode != 0)
                throw new IOException("ตัวติดตั้งคืนรหัสข้อผิดพลาด " + process.ExitCode);
            if (!File.Exists(installedExe))
                throw new IOException("ติดตั้งเสร็จ แต่ไม่พบแอปรุ่นใหม่");
            var installedVersion = FileVersionInfo.GetVersionInfo(installedExe).FileVersion;
            if (!string.Equals(installedVersion, version + "." + build, StringComparison.Ordinal))
                throw new IOException("เวอร์ชันไฟล์หลังติดตั้งไม่ตรงกับรุ่นใหม่: " + installedVersion);
            WriteLog("SUCCESS v" + version + " Build " + build);
            Process.Start(new ProcessStartInfo(installedExe) { UseShellExecute = true });
            try { File.Delete(setup); } catch (IOException) { }
            return 0;
        }
        catch (Exception ex)
        {
            WriteLog("FAILED " + ex.Message);
            // Recover from cancellation or installation failure. Always
            // prefer the verified Program Files app; fall back to the old
            // installed EXE only if migration has not completed.
            try
            {
                var reopen = File.Exists(installedExe) ? installedExe : previousExe;
                if (File.Exists(reopen))
                    Process.Start(new ProcessStartInfo(reopen) { UseShellExecute = true });
            }
            catch (Exception) { }
            return 1;
        }
    }
}
