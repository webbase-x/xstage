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
    // Download the actual release bytes without decompression; a transformed
    // response would make the published SHA-256 and Content-Length invalid.
    private static readonly HttpClient Client = new(new HttpClientHandler
    {
        AutomaticDecompression = DecompressionMethods.None,
        AllowAutoRedirect = true,
        MaxAutomaticRedirections = 6
    }) { Timeout = Timeout.InfiniteTimeSpan };

    public static string InstalledProgramFilesExe => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
        "X-Stage", "Download Manager", "XStageDownloadManager.exe");

    private static string UpdateFolder => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "X-Stage", "Download Manager", "updates");

    public static string DownloadLogPath => Path.Combine(UpdateFolder, "update-download.log");

    private static void LogDownload(string message)
    {
        try
        {
            Directory.CreateDirectory(UpdateFolder);
            File.AppendAllText(DownloadLogPath,
                DateTimeOffset.Now.ToString("O") + " " + message + Environment.NewLine);
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }

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
        LogDownload($"Starting v{release.Version} Build {release.Build}; expected bytes={release.Size}; file={expectedName}");
        // GitHub Releases is the ONLY source for production update bytes.
        return await DownloadAndVerifyPayloadAsync(new Uri(expectedUrl), destination,
            release.Sha256, release.Size, progress, cancellation);
    }

    // Internal so the integration tests can exercise the same byte-for-byte
    // resume logic with a deterministic local HTTP Range server.
    internal static async Task<string> DownloadAndVerifyPayloadAsync(
        Uri source, string destination, string expectedSha, long expectedSize,
        IProgress<double>? progress = null, CancellationToken cancellation = default)
    {
        if (expectedSize < 1 || expectedSha.Length != 64 ||
            !expectedSha.All(Uri.IsHexDigit))
            throw new IOException("ข้อมูลตรวจสอบไฟล์อัปเดตไม่ถูกต้อง");
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(destination))!);
        if (File.Exists(destination))
        {
            if (await VerifyFileAsync(destination, expectedSha, expectedSize, cancellation))
            {
                progress?.Report(100);
                return destination;
            }
            // Never run an old or corrupted installer merely because it has
            // the right name.
            File.Delete(destination);
        }

        var partial = destination + ".partial";
        Exception? lastError = null;
        for (var attempt = 1; attempt <= 4; attempt++)
        {
            cancellation.ThrowIfCancellationRequested();
            try
            {
                long resumeFrom = File.Exists(partial) ? new FileInfo(partial).Length : 0;
                if (resumeFrom > expectedSize)
                {
                    File.Delete(partial);
                    resumeFrom = 0;
                }
                if (resumeFrom == expectedSize)
                {
                    if (await VerifyFileAsync(partial, expectedSha, expectedSize, cancellation))
                    {
                        File.Move(partial, destination, true);
                        progress?.Report(100);
                        LogDownload("PASS existing complete partial SHA-256");
                        return destination;
                    }
                    File.Delete(partial);
                    resumeFrom = 0;
                }

                LogDownload($"HTTP attempt {attempt}/4; resuming at byte {resumeFrom} of {expectedSize}");
                using var inactivity = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
                inactivity.CancelAfter(TimeSpan.FromSeconds(60));
                using var request = new HttpRequestMessage(HttpMethod.Get, source);
                request.Headers.UserAgent.ParseAdd("XStageDownloadManager/AutoUpdate");
                if (resumeFrom > 0)
                    request.Headers.Range = new System.Net.Http.Headers.RangeHeaderValue(resumeFrom, null);

                using var response = await Client.SendAsync(
                    request, HttpCompletionOption.ResponseHeadersRead, inactivity.Token);

                // Follow only HTTPS and the official GitHub release/CDN hosts.
                // Do not install bytes returned by an unrelated redirect.
                if (source.Host.Equals("github.com", StringComparison.OrdinalIgnoreCase))
                {
                    var final = response.RequestMessage?.RequestUri;
                    if (final is null || final.Scheme != Uri.UriSchemeHttps ||
                        !(final.Host.Equals("github.com", StringComparison.OrdinalIgnoreCase) ||
                          final.Host.EndsWith(".githubusercontent.com", StringComparison.OrdinalIgnoreCase)))
                        throw new IOException("แหล่งดาวน์โหลดเปลี่ยนไปยังเว็บไซต์ที่ไม่ใช่ GitHub");
                }

                if (!response.IsSuccessStatusCode)
                    throw new HttpRequestException(
                        "เซิร์ฟเวอร์ดาวน์โหลดตอบกลับ HTTP " + (int)response.StatusCode +
                        " (" + response.ReasonPhrase + ")",
                        null, response.StatusCode);

                var contentType = response.Content.Headers.ContentType?.MediaType;
                if (contentType is "text/html" or "application/json" or "text/plain")
                    throw new IOException("ได้รับข้อมูลหน้าเว็บแทนไฟล์ติดตั้ง EXE");

                var append = resumeFrom > 0 && response.StatusCode == HttpStatusCode.PartialContent;
                if (response.StatusCode == HttpStatusCode.PartialContent)
                {
                    var cr = response.Content.Headers.ContentRange;
                    var from = append ? resumeFrom : 0;
                    if (cr?.From != from || cr.Length != expectedSize)
                        throw new IOException("เซิร์ฟเวอร์ส่งตำแหน่งข้อมูล Range ไม่ถูกต้อง");
                }
                else if (response.StatusCode != HttpStatusCode.OK)
                    throw new IOException("เซิร์ฟเวอร์ไม่ได้ส่งไฟล์ติดตั้งแบบ HTTP 200 หรือ 206");

                // A server may ignore Range and return 200. Restart from 0
                // instead of appending a complete response to a partial file.
                long start = append ? resumeFrom : 0;
                var remaining = expectedSize - start;
                if (response.Content.Headers.ContentLength is long contentLength &&
                    contentLength != remaining)
                    throw new IOException($"ขนาดข้อมูลที่ได้รับไม่ตรง: {contentLength} แทน {remaining} ไบต์");

                await using (var input = await response.Content.ReadAsStreamAsync(inactivity.Token))
                await using (var output = new FileStream(partial,
                    append ? FileMode.OpenOrCreate : FileMode.Create,
                    FileAccess.Write, FileShare.None, 131072, FileOptions.Asynchronous))
                {
                    if (append) output.Position = resumeFrom;
                    var buffer = new byte[131072];
                    long received = start;
                    int count;
                    while ((count = await input.ReadAsync(buffer, inactivity.Token)) > 0)
                    {
                        received += count;
                        if (received > expectedSize)
                            throw new IOException("ไฟล์อัปเดตที่ได้รับมีขนาดเกินข้อมูลจาก Release");
                        await output.WriteAsync(buffer.AsMemory(0, count), inactivity.Token);
                        progress?.Report(Math.Min(99.9, received * 100.0 / expectedSize));
                        inactivity.CancelAfter(TimeSpan.FromSeconds(60));
                    }
                    await output.FlushAsync(cancellation);
                    if (received != expectedSize)
                        throw new IOException($"ดาวน์โหลดไม่ครบ: {received:N0}/{expectedSize:N0} ไบต์");
                }

                if (!await VerifyFileAsync(partial, expectedSha, expectedSize, cancellation))
                {
                    File.Delete(partial);
                    throw new IOException("SHA-256 ไม่ตรงกับไฟล์ที่ GitHub เผยแพร่ ลบไฟล์ผิดพลาดและลองใหม่");
                }
                File.Move(partial, destination, true);
                progress?.Report(100);
                LogDownload("PASS downloaded size and SHA-256; path=" + destination);
                return destination;
            }
            catch (OperationCanceledException) when (!cancellation.IsCancellationRequested)
            {
                lastError = new IOException("ไม่มีข้อมูลตอบกลับจากเซิร์ฟเวอร์ภายใน 60 วินาที");
            }
            catch (Exception ex) when (ex is IOException or HttpRequestException)
            {
                lastError = ex;
            }

            cancellation.ThrowIfCancellationRequested();
            LogDownload($"FAILED attempt {attempt}/4; partial bytes=" +
                (File.Exists(partial) ? new FileInfo(partial).Length : 0) +
                "; reason=" + lastError?.Message);

            // Permanent HTTP failures should show immediately; do not retry
            // repeatedly on a deleted release, revoked authorization, etc.
            if (lastError is HttpRequestException http &&
                http.StatusCode is HttpStatusCode.Forbidden or HttpStatusCode.Unauthorized
                    or HttpStatusCode.NotFound or HttpStatusCode.Gone)
                break;
            if (attempt < 4)
                await Task.Delay(TimeSpan.FromSeconds(Math.Min(8, 1 << (attempt - 1))), cancellation);
        }
        throw new IOException(
            "ดาวน์โหลดอัปเดตไม่สำเร็จหลังพยายามต่อไฟล์และลองใหม่: " +
            (lastError?.Message ?? "ไม่ทราบสาเหตุ") +
            Environment.NewLine + "บันทึกข้อผิดพลาด: " + DownloadLogPath, lastError);
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

    public static void LaunchInstallerHelper(string verifiedSetup, DownloadManagerRelease release, int centerX, int centerY)
    {
        // Copy the current self-contained EXE to user-local temporary storage.
        // It can run the updater without locking the installed application binary.
        var appExe = Environment.ProcessPath ??
                     throw new IOException("ไม่พบไฟล์แอปสำหรับเปิดใหม่หลังอัปเดต");
        if (!File.Exists(appExe)) throw new FileNotFoundException("ไม่พบไฟล์แอป", appExe);
        if (!File.Exists(verifiedSetup) || new FileInfo(verifiedSetup).Length != release.Size)
            throw new IOException("ไฟล์อัปเดตที่ตรวจสอบแล้วไม่อยู่ในตำแหน่งที่คาดหวัง");

        Directory.CreateDirectory(UpdateFolder);
        // Executables in an application-data updates directory can be held by
        // antivirus scanning or denied by folder policies. A separate,
        // unique temp directory is an alternative, not a security bypass:
        // if Windows blocks both locations, report the real error and do not
        // request users to disable their protection.
        var helperLocations = new[] {
            UpdateFolder,
            Path.Combine(Path.GetTempPath(), "X-Stage", "Download Manager")
        }.Distinct(StringComparer.OrdinalIgnoreCase);
        Exception? lastError = null;
        foreach (var location in helperLocations)
        {
            var helper = Path.Combine(location,
                "xstage-update-helper-" + Guid.NewGuid().ToString("N") + ".exe");
            try
            {
                Directory.CreateDirectory(location);
                // Wait for the helper UI before letting the old app close.
                var readyEventName = "Local\\XStageDownloadReady_" + Guid.NewGuid().ToString("N");
                using var readyEvent = new EventWaitHandle(
                    false, EventResetMode.ManualReset, readyEventName);
                // Transient locks from security scanning often disappear quickly.
                for (var attempt = 0; ; attempt++)
                {
                    try
                    {
                        File.Copy(appExe, helper, overwrite: false);
                        break;
                    }
                    catch (IOException) when (attempt < 2)
                    {
                        Thread.Sleep(350 * (attempt + 1));
                    }
                    catch (UnauthorizedAccessException) when (attempt < 2)
                    {
                        Thread.Sleep(350 * (attempt + 1));
                    }
                }
                var info = new ProcessStartInfo(helper)
                {
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    WorkingDirectory = location
                };
                foreach (var arg in new[] {
                    "--apply-verified-update", Environment.ProcessId.ToString(),
                    verifiedSetup, appExe, release.Sha256, release.Size.ToString(),
                    release.Version, release.Build.ToString(), readyEventName,
                    centerX.ToString(System.Globalization.CultureInfo.InvariantCulture),
                    centerY.ToString(System.Globalization.CultureInfo.InvariantCulture)
                }) info.ArgumentList.Add(arg);
                using var process = Process.Start(info);
                if (process is null)
                    throw new IOException("ไม่สามารถเริ่มกระบวนการติดตั้งอัปเดต");
                if (!readyEvent.WaitOne(TimeSpan.FromSeconds(12)))
                {
                    try
                    {
                        if (!process.HasExited) process.Kill();
                        process.WaitForExit(5000);
                    }
                    catch (Exception ex) when (ex is InvalidOperationException or System.ComponentModel.Win32Exception)
                    {
                        LogDownload("Could not stop unacknowledged helper: " + ex.Message);
                    }
                    // Never try another location after a child process was
                    // launched. It could otherwise produce two updater windows.
                    throw new InvalidOperationException("หน้าต่างอัปเดตไม่พร้อม · โปรแกรมเดิมยังเปิดอยู่ กรุณาตรวจสอบอัปเดตอีกครั้ง");
                }
                return;
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or
                                       System.ComponentModel.Win32Exception)
            {
                lastError = ex;
                LogDownload("Update helper failed in " + location + ": " + ex.Message);
                try { File.Delete(helper); }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            }
        }
        throw new IOException(
            "Windows ไม่อนุญาตให้สร้างหรือเปิดตัวช่วยอัปเดตในโฟลเดอร์ที่ทดสอบ " +
            "โปรดตรวจสอบสิทธิ์และ Windows Security โดยไม่ต้องปิดระบบป้องกัน " +
            "รายละเอียด: " + DownloadLogPath, lastError);
    }


    private static void TryRemoveLegacyPerUserInstall(string previousExe, Action<string> log)
    {
        var oldRoot = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Programs", "X-Stage", "Download Manager");
        var expectedOldExe = Path.Combine(oldRoot, "XStageDownloadManager.exe");
        if (!string.Equals(Path.GetFullPath(previousExe), Path.GetFullPath(expectedOldExe),
                           StringComparison.OrdinalIgnoreCase))
            return;
        var uninstaller = Path.Combine(oldRoot, "unins000.exe");
        if (!File.Exists(uninstaller)) return;
        try
        {
            var start = new ProcessStartInfo(uninstaller)
            {
                UseShellExecute = true,
                WorkingDirectory = oldRoot
            };
            start.ArgumentList.Add("/VERYSILENT");
            start.ArgumentList.Add("/SUPPRESSMSGBOXES");
            start.ArgumentList.Add("/NORESTART");
            using var uninstall = Process.Start(start);
            if (uninstall is null || !uninstall.WaitForExit(60000) || uninstall.ExitCode != 0)
                log("Legacy user installation could not be fully removed; the new Program Files installation is usable.");
            else
                log("Removed legacy per-user application only; user downloads and settings retained.");
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or
                                   System.ComponentModel.Win32Exception or InvalidOperationException)
        {
            log("Legacy per-user cleanup skipped: " + ex.Message);
        }
    }

    // Called by Program.Main *before* creating the primary application mutex.
    public static int ApplyUpdateInHelper(string[] args, Action<string>? reportStatus = null)
    {
        if (args.Length is not (9 or 11) || !int.TryParse(args[1], out var oldPid) ||
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
            reportStatus?.Invoke("ขั้นที่ 2/6 · ตรวจสอบ SHA-256 และขนาดไฟล์");
            var expectedName = $"X-Stage-Download-Manager-v{version}-build{build}-win-x64-Setup.exe";
            if (Path.GetFileName(setup) != expectedName ||
                Path.GetFullPath(setup) != Path.Combine(UpdateFolder, expectedName) ||
                sha.Length != 64 || !sha.All(Uri.IsHexDigit))
                throw new IOException("ไฟล์ติดตั้งไม่ตรงกับอัปเดตที่อนุญาต");
            if (!VerifyFileAsync(setup, sha, size).GetAwaiter().GetResult())
                throw new IOException("SHA-256 ไม่ตรง: ยกเลิกการติดตั้ง");

            reportStatus?.Invoke("ขั้นที่ 3/6 · รอให้แอปรุ่นเก่าปิดและบันทึกคิว");
            try
            {
                using var previous = Process.GetProcessById(oldPid);
                if (!previous.WaitForExit(90000))
                    throw new IOException("แอปเดิมยังไม่ปิด จึงไม่ติดตั้งทับ");
            }
            catch (ArgumentException) { /* The main process already exited. */ }

            reportStatus?.Invoke("ขั้นที่ 4/6 · ขอสิทธิ์ติดตั้งจาก Windows");
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
            reportStatus?.Invoke("ขั้นที่ 4/6 · กำลังติดตั้งรุ่นใหม่");
            if (!process.WaitForExit(600000))
            {
                WriteLog("Installer timeout; not claiming success or launching a second installer.");
                return 3;
            }
            if (process.ExitCode != 0)
                throw new IOException("ตัวติดตั้งคืนรหัสข้อผิดพลาด " + process.ExitCode);
            reportStatus?.Invoke("ขั้นที่ 5/6 · ตรวจสอบเวอร์ชันที่ติดตั้ง");
            if (!File.Exists(installedExe))
                throw new IOException("ติดตั้งเสร็จ แต่ไม่พบแอปรุ่นใหม่");
            var installedVersion = FileVersionInfo.GetVersionInfo(installedExe).FileVersion;
            if (!string.Equals(installedVersion, version + "." + build, StringComparison.Ordinal))
                throw new IOException("เวอร์ชันไฟล์หลังติดตั้งไม่ตรงกับรุ่นใหม่: " + installedVersion);
            // Open the new version immediately after verification. Cleanup of
            // the old per-user install must NEVER block the next UI opening.
            reportStatus?.Invoke("ขั้นที่ 6/6 · กำลังเปิดแอปรุ่นใหม่");
            Process.Start(new ProcessStartInfo(installedExe) { UseShellExecute = true });
            WriteLog("SUCCESS v" + version + " Build " + build +
                     " in " + installedExe);
            TryRemoveLegacyPerUserInstall(previousExe, WriteLog);
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
