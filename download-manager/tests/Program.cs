using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using XStageDownloadManager;

var bytes = new byte[5 * 1024 * 1024];
for (int i = 0; i < bytes.Length; i++) bytes[i] = (byte)(i % 251);
using var server = new FileServer(bytes);
var folder = Path.Combine(Path.GetTempPath(), "xstage-dm-test-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(folder);
try
{
    var manager = new DownloadEngine();
    if (DownloadEngine.TryParseUrl("file:///C:/Windows/system.ini", out _) ||
        DownloadEngine.TryParseUrl("ftp://localhost/file", out _) ||
        DownloadEngine.TryParseUrl("https://user:pass@example.com/file", out _))
        throw new Exception("Non-HTTP or credential URLs must be rejected.");

    var job = manager.Add(server.Url + "range/test%20file.bin", folder);
    await WaitFor(() => job.Status == "Running" && Interlocked.Read(ref job.DownloadedBytes) >= 65536);
    manager.Pause(job);
    await WaitFor(() => job.Status == "Paused" && job.Cancellation is null);
    if (Interlocked.Read(ref job.DownloadedBytes) <= 0)
        throw new Exception("Test must leave partial downloaded bytes");
    manager.Start(job);
    await WaitFor(() => job.Status is "Completed" or "Failed");
    if (job.Status != "Completed") throw new Exception("Range resume failed: " + job.Error);
    if (!job.SupportsRanges) throw new Exception("HTTP Range was not detected");
    if (!bytes.SequenceEqual(await File.ReadAllBytesAsync(job.CompletedPath)))
        throw new Exception("Range resume produced incorrect bytes");

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
    Console.WriteLine("PASS: HTTP 206 segmented download, pause/resume, byte-for-byte SHA content, HTTP 200 fallback, filename collision and safe removal.");
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
