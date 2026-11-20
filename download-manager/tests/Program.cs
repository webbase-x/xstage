using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using XStageDownloadManager;

var bytes = new byte[9 * 1024 * 1024];
for (int i = 0; i < bytes.Length; i++) bytes[i] = (byte)(i % 251);
using var server = new FileServer(bytes);
var folder = Path.Combine(Path.GetTempPath(), "xstage-dm-test-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(folder);
try
{
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

    video.VideoQuality = "AudioMP3";
    var mp3Args = SocialVideoDownloader.BuildArguments(video, folder, folder);
    if (!mp3Args.Contains("--audio-format") || !mp3Args.Contains("mp3"))
        throw new Exception("MP3 extraction args missing.");

    // Update checks must compare semantic versions and ignore unsigned/unverified feeds.
    var filename = "X-Stage-Download-Manager-v0.2.2-build5-win-x64-Setup.exe";
    var json = System.Text.Json.JsonSerializer.Serialize(new
    {
        available = true, channel = "preview", version = "0.2.2", build = 5,
        file = filename, sha256 = new string('a', 64), size_bytes = 250_000_000L,
        download_url = "https://github.com/webbase-x/xstage/releases/download/xstage-download-manager-v0.2.2-build5-preview/" + filename
    });
    if (UpdateChecker.Parse(json) is not { Version: "0.2.2", Build: 5 } ||
        !UpdateChecker.IsNewer("0.2.2", 5) || UpdateChecker.IsNewer("0.1.1", 2) ||
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
    var manager = new DownloadEngine();
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
    if (!await BrowserCaptureProbe.IsUnauthenticatedFileAsync(server.Url + "range/test-file.bin") ||
        !await BrowserCaptureProbe.IsUnauthenticatedFileAsync(server.Url + "plain/test-file.bin") ||
        await BrowserCaptureProbe.IsUnauthenticatedFileAsync("https://www.youtube.com/watch?v=123"))
        throw new Exception("Browser capture must probe accessible direct files without cookies.");
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
    if (new DownloadEngine().DefaultParts != 8)
        throw new Exception("Default segment count must persist across restarts.");
    Console.WriteLine("PASS: configurable 1/8/16/32 segments, paused-job resegmentation, 32-range merge, byte-for-byte equality, HTTP 200 fallback, settings persistence and safe removal.");
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
                var supportsRange = path.StartsWith("/range/");
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
                var response = "HTTP/1.1 " + code + "\r\n" +
                    "Content-Type: application/octet-stream\r\n" +
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
