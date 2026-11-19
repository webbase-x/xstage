using System.Collections.Concurrent;
using System.Net;
using System.Net.Http.Headers;
using System.Text.Json;

namespace XStageDownloadManager;

// Independent HTTP/HTTPS download engine. No IDM binaries, libraries or reverse-engineered code.
public sealed class DownloadEngine
{
    private static readonly HttpClient Http = new(new SocketsHttpHandler
    {
        AutomaticDecompression = DecompressionMethods.None,
        MaxConnectionsPerServer = 16,
        PooledConnectionLifetime = TimeSpan.FromMinutes(10)
    }) { Timeout = Timeout.InfiniteTimeSpan };

    private readonly object _saveLock = new();
    private readonly SemaphoreSlim _downloads = new(2, 2);
    private readonly ConcurrentDictionary<string, byte> _active = new();
    private static readonly JsonSerializerOptions Json = new() { WriteIndented = true, IncludeFields = true };
    private readonly string _index;
    public List<DownloadJob> Jobs { get; }

    public DownloadEngine()
    {
        var data = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "X-Stage", "Download Manager");
        Directory.CreateDirectory(data);
        _index = Path.Combine(data, "downloads.json");
        Jobs = Load();
        foreach (var job in Jobs)
        {
            if (job.Status is "Running" or "Queued") job.Status = "Paused";
            job.Cancellation = null;
            job.PreviousBytes = job.DownloadedBytes;
        }
        Save();
    }

    private List<DownloadJob> Load()
    {
        try
        {
            return File.Exists(_index)
                ? JsonSerializer.Deserialize<List<DownloadJob>>(File.ReadAllText(_index), Json) ?? new()
                : new();
        }
        catch
        {
            // Keep the broken original for recovery instead of deleting the user's download history.
            try { File.Copy(_index, _index + ".damaged-" + DateTime.UtcNow.ToString("yyyyMMddHHmmss"), true); }
            catch { /* Best effort only. */ }
            return new();
        }
    }

    public void Save()
    {
        lock (_saveLock)
        {
            try
            {
                var tmp = _index + ".tmp";
                File.WriteAllText(tmp, JsonSerializer.Serialize(Jobs, Json));
                File.Move(tmp, _index, true);
            }
            catch (IOException) { /* Retry on next timer tick; downloads must keep running. */ }
            catch (UnauthorizedAccessException) { }
        }
    }

    public static bool TryParseUrl(string text, out Uri? url)
    {
        if (Uri.TryCreate(text.Trim(), UriKind.Absolute, out url) &&
            (url.Scheme == Uri.UriSchemeHttps || url.Scheme == Uri.UriSchemeHttp) &&
            string.IsNullOrEmpty(url.UserInfo)) return true;
        url = null;
        return false;
    }

    public DownloadJob Add(string url, string folder)
    {
        if (!TryParseUrl(url, out var uri) || uri is null)
            throw new ArgumentException("รองรับลิงก์ HTTP/HTTPS ที่ถูกต้องเท่านั้น");
        var name = CleanName(Uri.UnescapeDataString(uri.AbsolutePath.Split('/').LastOrDefault() ?? ""));
        var job = new DownloadJob { Url = uri.ToString(), Name = name, Folder = folder };
        Jobs.Insert(0, job);
        Save();
        Start(job);
        return job;
    }

    public void Start(DownloadJob job)
    {
        if (job.Status == "Completed" || !_active.TryAdd(job.Id, 0)) return;
        job.Status = "Queued";
        job.Error = "";
        var cts = new CancellationTokenSource();
        job.Cancellation = cts;
        Save();
        _ = Task.Run(async () =>
        {
            var entered = false;
            try
            {
                await _downloads.WaitAsync(cts.Token);
                entered = true;
                cts.Token.ThrowIfCancellationRequested();
                job.Status = "Running";
                await DownloadAsync(job, cts.Token);
                cts.Token.ThrowIfCancellationRequested();
                job.Status = "Completed";
                job.Error = "";
            }
            catch (OperationCanceledException)
            {
                job.Status = "Paused";
            }
            catch (Exception ex)
            {
                job.Status = "Failed";
                job.Error = ex.Message.Length > 350 ? ex.Message[..350] : ex.Message;
            }
            finally
            {
                if (entered) _downloads.Release();
                _active.TryRemove(job.Id, out _);
                if (ReferenceEquals(job.Cancellation, cts)) job.Cancellation = null;
                cts.Dispose();
                Save();
            }
        });
    }

    public void Pause(DownloadJob job)
    {
        if (job.Status is not ("Running" or "Queued")) return;
        job.Status = "Paused";
        try { job.Cancellation?.Cancel(); } catch (ObjectDisposedException) { }
        Save();
    }

    public void PauseAll()
    {
        foreach (var job in Jobs.ToArray()) Pause(job);
    }

    public bool Remove(DownloadJob job)
    {
        if (_active.ContainsKey(job.Id)) { Pause(job); return false; }
        Jobs.Remove(job);
        // Remove only this application's temporary segments, never a completed user file.
        try
        {
            var work = WorkDir(job);
            if (Directory.Exists(work)) Directory.Delete(work, true);
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
        Save();
        return true;
    }

    private static string WorkDir(DownloadJob job) =>
        Path.Combine(job.Folder, ".xstage-downloads", job.Id);

    private sealed record ProbeInfo(bool Ranges, long Total, string ETag,
        DateTimeOffset? LastModified, string SuggestedName);

    private static HttpRequestMessage Request(HttpMethod method, string url)
    {
        var request = new HttpRequestMessage(method, url);
        request.Headers.AcceptEncoding.ParseAdd("identity");
        request.Headers.UserAgent.ParseAdd("XStageDownloadManager/0.1");
        return request;
    }

    private static async Task<ProbeInfo> ProbeAsync(DownloadJob job, CancellationToken ct)
    {
        using var req = Request(HttpMethod.Get, job.Url);
        req.Headers.Range = new RangeHeaderValue(0, 0);
        using var response = await Http.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, ct);
        response.EnsureSuccessStatusCode();
        var range = response.Content.Headers.ContentRange;
        var supported = response.StatusCode == HttpStatusCode.PartialContent &&
            range?.HasLength == true && range.From == 0 && range.To == 0;
        var length = supported ? range!.Length!.Value : response.Content.Headers.ContentLength ?? -1;
        var rawName = response.Content.Headers.ContentDisposition?.FileNameStar ??
            response.Content.Headers.ContentDisposition?.FileName ?? "";
        return new ProbeInfo(supported, length, response.Headers.ETag?.ToString() ?? "",
            response.Content.Headers.LastModified, CleanName(rawName));
    }

    private static async Task DownloadAsync(DownloadJob job, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        Directory.CreateDirectory(job.Folder);
        var probe = await ProbeAsync(job, ct);
        var work = WorkDir(job);
        if (job.Name.Equals("download", StringComparison.OrdinalIgnoreCase) &&
            probe.SuggestedName != "download") job.Name = probe.SuggestedName;
        var partialExists = job.SupportsRanges && Directory.Exists(work) &&
            Directory.EnumerateFiles(work, "*.part").Any();
        var strongTagMatches = !string.IsNullOrEmpty(job.ETag) &&
            !job.ETag.StartsWith("W/", StringComparison.OrdinalIgnoreCase) &&
            job.ETag == probe.ETag;
        var dateMatches = job.LastModified.HasValue && job.LastModified == probe.LastModified;
        // Resuming unvalidated bytes may silently mix content from different file versions.
        var sourceChanged = (job.TotalBytes > -1 && probe.Total > -1 && job.TotalBytes != probe.Total)
            || (!string.IsNullOrEmpty(job.ETag) && !string.IsNullOrEmpty(probe.ETag) && job.ETag != probe.ETag)
            || (job.LastModified.HasValue && probe.LastModified.HasValue && job.LastModified != probe.LastModified)
            || (job.SupportsRanges && !probe.Ranges)
            || (partialExists && !(strongTagMatches || dateMatches));
        if (sourceChanged && Directory.Exists(work)) Directory.Delete(work, true);
        Directory.CreateDirectory(work);
        job.TotalBytes = probe.Total;
        job.SupportsRanges = probe.Ranges;
        job.ETag = probe.ETag;
        job.LastModified = probe.LastModified;
        if (probe.Ranges && probe.Total > 0)
            await ParallelDownloadAsync(job, work, ct);
        else
            await SingleDownloadAsync(job, work, ct);
        ct.ThrowIfCancellationRequested();

        var destination = UniqueOutput(job.Folder, job.Name);
        var merged = Path.Combine(work, "ready.tmp");
        if (File.Exists(merged)) File.Delete(merged);
        await using (var output = new FileStream(merged, FileMode.CreateNew, FileAccess.Write,
                         FileShare.None, 131072, FileOptions.Asynchronous))
        {
            if (job.SupportsRanges && job.TotalBytes > 0)
            {
                int count = SegmentCount(job.TotalBytes, job.Parts);
                for (int i = 0; i < count; i++)
                {
                    ct.ThrowIfCancellationRequested();
                    await using var input = new FileStream(PartPath(work, i), FileMode.Open,
                        FileAccess.Read, FileShare.Read, 131072, FileOptions.Asynchronous);
                    await input.CopyToAsync(output, ct);
                }
            }
            else
            {
                await using var input = new FileStream(Path.Combine(work, "whole.part"),
                    FileMode.Open, FileAccess.Read, FileShare.Read, 131072, FileOptions.Asynchronous);
                await input.CopyToAsync(output, ct);
            }
        }
        if (job.TotalBytes >= 0 && new FileInfo(merged).Length != job.TotalBytes)
            throw new IOException("ขนาดไฟล์ที่ประกอบไม่ตรงกับข้อมูลจากเซิร์ฟเวอร์");
        ct.ThrowIfCancellationRequested();
        File.Move(merged, destination);
        job.CompletedPath = destination;
        if (job.TotalBytes < 0) job.TotalBytes = new FileInfo(destination).Length;
        Interlocked.Exchange(ref job.DownloadedBytes, job.TotalBytes);
        try { Directory.Delete(work, true); } catch (IOException) { }
    }

    private static int SegmentCount(long size, int parts)
    {
        if (size < 1024 * 1024) return 1;
        return (int)Math.Clamp(Math.Min(parts, size / (1024 * 1024)), 1, 8);
    }

    private static string PartPath(string work, int index) => Path.Combine(work, index.ToString("D2") + ".part");

    private static async Task ParallelDownloadAsync(DownloadJob job, string work, CancellationToken ct)
    {
        var count = SegmentCount(job.TotalBytes, job.Parts);
        long existingTotal = 0;
        for (int i = 0; i < count; i++)
        {
            var begin = job.TotalBytes * i / count;
            var end = job.TotalBytes * (i + 1) / count - 1;
            var path = PartPath(work, i);
            if (File.Exists(path) && new FileInfo(path).Length > end - begin + 1)
                File.Delete(path);
            if (File.Exists(path)) existingTotal += new FileInfo(path).Length;
        }
        // If the parallelism setting changed, remove stale parts to avoid corrupt merges.
        if (Directory.GetFiles(work, "*.part").Any(f =>
            Path.GetFileNameWithoutExtension(f) != "whole" &&
            (!int.TryParse(Path.GetFileNameWithoutExtension(f), out var n) || n >= count)))
        {
            foreach (var file in Directory.GetFiles(work, "*.part")) File.Delete(file);
            existingTotal = 0;
        }
        Interlocked.Exchange(ref job.DownloadedBytes, existingTotal);
        await Task.WhenAll(Enumerable.Range(0, count).Select(i =>
        {
            var begin = job.TotalBytes * i / count;
            var end = job.TotalBytes * (i + 1) / count - 1;
            return DownloadPartAsync(job, PartPath(work, i), begin, end, ct);
        }));
    }

    private static async Task DownloadPartAsync(DownloadJob job, string file,
        long begin, long end, CancellationToken ct)
    {
        var saved = File.Exists(file) ? new FileInfo(file).Length : 0;
        var expected = end - begin + 1;
        if (saved == expected) return;
        using var req = Request(HttpMethod.Get, job.Url);
        req.Headers.Range = new RangeHeaderValue(begin + saved, end);
        if (!string.IsNullOrEmpty(job.ETag) && !job.ETag.StartsWith("W/", StringComparison.OrdinalIgnoreCase))
            req.Headers.TryAddWithoutValidation("If-Range", job.ETag);
        else if (job.LastModified.HasValue)
            req.Headers.TryAddWithoutValidation("If-Range", job.LastModified.Value.ToString("R"));
        using var res = await Http.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, ct);
        var r = res.Content.Headers.ContentRange;
        if (res.StatusCode != HttpStatusCode.PartialContent || r?.From != begin + saved || r.To != end || r.Length != job.TotalBytes)
            throw new IOException("เซิร์ฟเวอร์ไม่รองรับช่วงข้อมูลเดิมอย่างถูกต้อง โปรดลองใหม่");
        await using var output = new FileStream(file, FileMode.Append, FileAccess.Write,
            FileShare.Read, 131072, FileOptions.Asynchronous);
        await using var input = await res.Content.ReadAsStreamAsync(ct);
        var buffer = new byte[131072];
        var remaining = expected - saved;
        while (remaining > 0)
        {
            var got = await input.ReadAsync(buffer.AsMemory(0, (int)Math.Min(buffer.Length, remaining)), ct);
            if (got == 0) throw new EndOfStreamException("การรับข้อมูลจากเซิร์ฟเวอร์หยุดก่อนครบไฟล์");
            await output.WriteAsync(buffer.AsMemory(0, got), ct);
            Interlocked.Add(ref job.DownloadedBytes, got);
            remaining -= got;
        }
    }

    private static async Task SingleDownloadAsync(DownloadJob job, string work, CancellationToken ct)
    {
        // A server without HTTP Range cannot be safely resumed from the middle.
        var path = Path.Combine(work, "whole.part");
        Interlocked.Exchange(ref job.DownloadedBytes, 0);
        using var req = Request(HttpMethod.Get, job.Url);
        using var res = await Http.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, ct);
        res.EnsureSuccessStatusCode();
        if (res.StatusCode != HttpStatusCode.OK)
            throw new IOException("การดาวน์โหลดแบบไฟล์เดียวต้องได้รับ HTTP 200");
        if (job.TotalBytes < 0) job.TotalBytes = res.Content.Headers.ContentLength ?? -1;
        await using var output = new FileStream(path, FileMode.Create, FileAccess.Write,
            FileShare.Read, 131072, FileOptions.Asynchronous);
        await using var input = await res.Content.ReadAsStreamAsync(ct);
        var buffer = new byte[131072];
        int got;
        while ((got = await input.ReadAsync(buffer, ct)) > 0)
        {
            await output.WriteAsync(buffer.AsMemory(0, got), ct);
            Interlocked.Add(ref job.DownloadedBytes, got);
        }
    }

    private static string CleanName(string input)
    {
        var name = input.Trim().Trim('"').Replace('\\', '/').Split('/').Last().Trim();
        foreach (var ch in Path.GetInvalidFileNameChars()) name = name.Replace(ch, '_');
        foreach (var ch in "<>:\"/\\|?*") name = name.Replace(ch, '_'); // Windows filename rules
        name = name.Trim().TrimEnd('.');
        if (name is "" or "." or "..") name = "download";
        if (name.Length > 160) name = name[..160];
        var reserved = Path.GetFileNameWithoutExtension(name).ToUpperInvariant();
        if (new[] { "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "LPT1", "LPT2" }.Contains(reserved))
            name = "_" + name;
        return name;
    }

    private static string UniqueOutput(string directory, string file)
    {
        var clean = CleanName(file);
        var baseName = Path.GetFileNameWithoutExtension(clean);
        var ext = Path.GetExtension(clean);
        var result = Path.Combine(directory, clean);
        for (int n = 1; File.Exists(result); n++)
            result = Path.Combine(directory, baseName + " (" + n + ")" + ext);
        return result;
    }
}
