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
        MaxConnectionsPerServer = 64,
        PooledConnectionLifetime = TimeSpan.FromMinutes(10)
    }) { Timeout = Timeout.InfiniteTimeSpan };

    private readonly object _saveLock = new();
    private readonly SemaphoreSlim _downloads = new(2, 2);
    private readonly ConcurrentDictionary<string, byte> _active = new();
    private static readonly JsonSerializerOptions Json = new() { WriteIndented = true, IncludeFields = true };
    private readonly string _index;
    private readonly string _settings;
    private readonly DownloadStateStore _state;
    private long _lastProgressSave;
    public string LastStorageError { get; private set; } = "";
    public string DatabasePath => _state.DatabasePath;
    public static readonly int[] AllowedParts = { 1, 2, 4, 8, 16, 32 };
    public int DefaultParts { get; private set; } = 4;
    public List<DownloadJob> Jobs { get; }

    public DownloadEngine(string? dataDirectory = null)
    {
        var data = dataDirectory ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "X-Stage", "Download Manager");
        Directory.CreateDirectory(data);
        _index = Path.Combine(data, "downloads.json");
        _settings = Path.Combine(data, "settings.json");
        _state = new DownloadStateStore(data);
        // Keep both historical JSON files untouched as migration backups.
        var legacyParts = DefaultParts;
        try
        {
            var configured = JsonSerializer.Deserialize<int>(File.ReadAllText(_settings));
            if (AllowedParts.Contains(configured)) legacyParts = configured;
        }
        catch (IOException) { }
        catch (JsonException) { }
        DefaultParts = _state.ReadDefaultParts(legacyParts);
        Jobs = _state.LoadOrMigrate(_index);
        _state.SaveDefaultParts(DefaultParts);
        foreach (var job in Jobs)
        {
            if (job.Status is "Running" or "Queued") job.Status = "Paused";
            // Build 4 could download the MKV correctly, then falsely report
            // failure because the Thai/Unicode final pathname was corrupted.
            // That specific failure occurred only after yt-dlp returned 0.
            SocialVideoDownloader.TryRecoverLegacyCompletedJob(job);
            // A user-supplied real-world Build 14 MP4 had ftyp/mdat but no
            // moov atom. Do not perpetuate a false Completed state on restart.
            if (job.Kind == "Video" && job.Status == "Completed" &&
                Path.GetExtension(job.CompletedPath).Equals(".mp4", StringComparison.OrdinalIgnoreCase) &&
                File.Exists(job.CompletedPath) &&
                !MediaIntegrity.HasCompleteMp4Boxes(job.CompletedPath))
            {
                job.Status = "Failed";
                job.VideoPercent = 0;
                job.Error = "ไฟล์ MP4 ไม่สมบูรณ์ (ไม่มี moov atom) กด เริ่ม / ต่อ เพื่อดาวน์โหลด/แปลงใหม่";
            }
            // Recover completed extensionless downloads from earlier builds
            // using only known file signatures; never guess for unknown data.
            DownloadFileNaming.TryRepairCompletedFile(job);
            job.Cancellation = null;
            if (!AllowedParts.Contains(job.Parts)) job.Parts = 4;
            job.PreviousBytes = job.DownloadedBytes;
        }
        Save();
    }

    // Persist critical state changes immediately, and keep running transfers
    // checkpointed separately on a bounded cadence. SQLite commits jobs and
    // individual chunk byte positions atomically in WAL mode.
    public void Save()
    {
        lock (_saveLock)
        {
            try
            {
                _state.SaveSnapshot(Jobs.ToArray());
                Interlocked.Exchange(ref _lastProgressSave, Environment.TickCount64);
                LastStorageError = "";
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or
                                       Microsoft.Data.Sqlite.SqliteException or InvalidDataException)
            {
                LastStorageError = "บันทึกสถานะ SQLite ไม่สำเร็จ: " + ex.Message;
                try
                {
                    File.AppendAllText(Path.Combine(Path.GetDirectoryName(DatabasePath)!,
                        "state-errors.log"), DateTimeOffset.Now.ToString("O") +
                        " " + LastStorageError + Environment.NewLine);
                }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            }
        }
    }

    public void SaveProgressIfDue()
    {
        if (Environment.TickCount64 - Interlocked.Read(ref _lastProgressSave) >= 2000)
            Save();
    }

    public static bool TryParseUrl(string text, out Uri? url)
    {
        if (Uri.TryCreate(text.Trim(), UriKind.Absolute, out url) &&
            (url.Scheme == Uri.UriSchemeHttps || url.Scheme == Uri.UriSchemeHttp) &&
            string.IsNullOrEmpty(url.UserInfo)) return true;
        url = null;
        return false;
    }

    public void SetDefaultParts(int parts)
    {
        ValidateParts(parts);
        DefaultParts = parts;
        _state.SaveDefaultParts(parts);
    }

    private static void ValidateParts(int parts)
    {
        if (!AllowedParts.Contains(parts))
            throw new ArgumentOutOfRangeException(nameof(parts), "จำนวนส่วนต้องเป็น 1, 2, 4, 8, 16 หรือ 32");
    }

    // Changing segment geometry requires discarding old partials, never mixing different byte ranges.
    // An active download must first be paused and fully stopped.
    public bool SetJobParts(DownloadJob job, int parts)
    {
        ValidateParts(parts);
        if (job.Status == "Completed" || _active.ContainsKey(job.Id)) return false;
        if (!Jobs.Contains(job)) return false;
        if (job.Parts == parts) return true;
        var work = WorkDir(job);
        if (Directory.Exists(work)) Directory.Delete(work, true);
        job.Parts = parts;
        job.SegmentsUsed = 0;
        job.SegmentDownloadedBytes = Array.Empty<long>();
        job.TotalBytes = -1;
        job.SupportsRanges = false;
        job.ETag = "";
        job.LastModified = null;
        job.DownloadedBytes = 0;
        job.PreviousBytes = 0;
        job.Error = "";
        job.Status = "Paused";
        Save();
        return true;
    }

    public DownloadJob Add(string url, string folder, int? parts = null, string videoQuality = "Best", string outputFormat = "mp4", bool separateCopy = false)
    {
        if (!TryParseUrl(url, out var uri) || uri is null)
            throw new ArgumentException("รองรับลิงก์ HTTP/HTTPS ที่ถูกต้องเท่านั้น");
        var selectedParts = parts ?? DefaultParts;
        ValidateParts(selectedParts);
        var video = SocialVideoDownloader.IsVideoUrl(uri.ToString());
        if (video && !SocialVideoDownloader.AllowedQualities.Contains(videoQuality))
            throw new ArgumentException("กรุณาเลือกคุณภาพวิดีโอที่รองรับ");
        if (video && !SocialVideoDownloader.AllowedOutputFormats.Contains(outputFormat))
            throw new ArgumentException("กรุณาเลือกรูปแบบปลายทาง MP4 / MKV / WEBM / MP3");
        var name = video ? SocialVideoDownloader.Platform(uri.ToString()) + " video" :
            DownloadFileNaming.UrlFileName(uri.ToString());
        var job = new DownloadJob
        {
            Url = uri.ToString(), Name = name, Folder = folder, Parts = selectedParts,
            Kind = video ? "Video" : "File", VideoQuality = video ? videoQuality : "Best",
            OutputFormat = video ? outputFormat : "mp4",
            IsRedownload = video && separateCopy
        };
        Jobs.Insert(0, job);
        Save();
        Start(job);
        return job;
    }

    /// <summary>
    /// Enqueue an independent fresh video download using newly selected
    /// settings. The source record and its original completed file remain
    /// untouched even when quality/format are unchanged.
    /// </summary>
    public DownloadJob AddVideoAgain(DownloadJob source, string quality,
        string format, string folder, int parts)
    {
        if (!Jobs.Contains(source) || source.Kind != "Video" ||
            !SocialVideoDownloader.IsVideoUrl(source.Url))
            throw new ArgumentException("เลือกรายการวิดีโอที่อยู่ในประวัติก่อน");
        if (source.Status is "Running" or "Queued" || _active.ContainsKey(source.Id))
            throw new InvalidOperationException("รายการเดิมกำลังทำงาน กรุณาหยุดให้เสร็จก่อนดาวน์โหลดใหม่");
        if (string.IsNullOrWhiteSpace(folder))
            throw new ArgumentException("กรุณาเลือกโฟลเดอร์สำหรับบันทึก");
        return Add(source.Url, folder.Trim(), parts, quality, format, separateCopy: true);
    }

    public void Start(DownloadJob job)
    {
        if (job.Status == "Completed" || !_active.TryAdd(job.Id, 0)) return;
        // Keep the damaged file as a backup, but remove its original name
        // so yt-dlp cannot mistake it for a valid completed download.
        if (job.Kind == "Video" && job.CompletedPath.Length > 0 &&
            Path.GetExtension(job.CompletedPath).Equals(".mp4", StringComparison.OrdinalIgnoreCase) &&
            File.Exists(job.CompletedPath) &&
            !MediaIntegrity.HasCompleteMp4Boxes(job.CompletedPath))
        {
            try
            {
                var backupFolder = WorkDir(job);
                Directory.CreateDirectory(backupFolder);
                var backup = Path.Combine(backupFolder,
                    "invalid-" + DateTime.UtcNow.ToString("yyyyMMddHHmmss") + "-" +
                    Path.GetFileName(job.CompletedPath) + ".broken");
                File.Move(job.CompletedPath, backup);
                job.CompletedPath = "";
            }
            catch (IOException ex)
            {
                _active.TryRemove(job.Id, out _);
                job.Status = "Failed";
                job.Error = "ไม่สามารถเก็บไฟล์ MP4 ที่เสียไว้ก่อนลองใหม่: " + ex.Message;
                Save();
                return;
            }
            catch (UnauthorizedAccessException ex)
            {
                _active.TryRemove(job.Id, out _);
                job.Status = "Failed";
                job.Error = "ไม่สามารถเก็บไฟล์ MP4 ที่เสียไว้ก่อนลองใหม่: " + ex.Message;
                Save();
                return;
            }
        }
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
        return new ProbeInfo(supported, length, response.Headers.ETag?.ToString() ?? "",
            response.Content.Headers.LastModified,
            DownloadFileNaming.Resolve(job.Url, response));
    }

    private static async Task DownloadAsync(DownloadJob job, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        Directory.CreateDirectory(job.Folder);
        if (SocialVideoDownloader.IsVideoUrl(job.Url))
        {
            await SocialVideoDownloader.DownloadAsync(job, WorkDir(job), ct);
            return;
        }
        var probe = await ProbeAsync(job, ct);
        var work = WorkDir(job);
        // The final HTTP response may have Content-Disposition with the real
        // name even when the requested URL is a CDN UUID without extension.
        job.Name = probe.SuggestedName;
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
        {
            job.SegmentsUsed = 1;
            await SingleDownloadAsync(job, work, ct);
        }
        ct.ThrowIfCancellationRequested();

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
        // Inspect the assembled file only if the server supplied no extension;
        // this is important for GitHub release-assets URLs with opaque UUIDs.
        job.Name = DownloadFileNaming.EnsureExtension(job.Name, merged);
        var destination = DownloadFileNaming.UniqueOutput(job.Folder, job.Name);
        File.Move(merged, destination);
        job.Name = Path.GetFileName(destination);
        job.CompletedPath = destination;
        if (job.TotalBytes < 0) job.TotalBytes = new FileInfo(destination).Length;
        Interlocked.Exchange(ref job.DownloadedBytes, job.TotalBytes);
        try { Directory.Delete(work, true); } catch (IOException) { }
    }

    private static int SegmentCount(long size, int parts)
    {
        // Keep each request at least 256 KiB where possible; tiny files need fewer parts.
        if (size < 256 * 1024) return 1;
        return (int)Math.Clamp(Math.Min(Math.Clamp(parts, 1, 32), size / (256 * 1024)), 1, 32);
    }

    private static string PartPath(string work, int index) => Path.Combine(work, index.ToString("D2") + ".part");

    private static async Task ParallelDownloadAsync(DownloadJob job, string work, CancellationToken ct)
    {
        var count = SegmentCount(job.TotalBytes, job.Parts);
        // Save the actual geometry with the job so resumption never reuses a segment
        // written for different byte boundaries. Older jobs default to zero (unknown).
        if (job.SegmentsUsed > 0 && job.SegmentsUsed != count)
        {
            foreach (var path in Directory.GetFiles(work, "*.part")) File.Delete(path);
        }
        job.SegmentsUsed = count;
        job.SegmentDownloadedBytes = new long[count];
        long existingTotal = 0;
        for (int i = 0; i < count; i++)
        {
            var begin = job.TotalBytes * i / count;
            var end = job.TotalBytes * (i + 1) / count - 1;
            var path = PartPath(work, i);
            if (File.Exists(path) && new FileInfo(path).Length > end - begin + 1)
                File.Delete(path);
            if (File.Exists(path))
            {
                var bytes = new FileInfo(path).Length;
                job.SegmentDownloadedBytes[i] = bytes;
                existingTotal += bytes;
            }
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
            return DownloadPartAsync(job, PartPath(work, i), begin, end, i, ct);
        }));
    }

    private static async Task DownloadPartAsync(DownloadJob job, string file,
        long begin, long end, int segmentIndex, CancellationToken ct)
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
            Interlocked.Add(ref job.SegmentDownloadedBytes[segmentIndex], got);
            Interlocked.Add(ref job.DownloadedBytes, got);
            remaining -= got;
        }
    }

    private static async Task SingleDownloadAsync(DownloadJob job, string work, CancellationToken ct)
    {
        // A server without HTTP Range cannot be safely resumed from the middle.
        var path = Path.Combine(work, "whole.part");
        job.SegmentDownloadedBytes = Array.Empty<long>();
        Interlocked.Exchange(ref job.DownloadedBytes, 0);
        using var req = Request(HttpMethod.Get, job.Url);
        using var res = await Http.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, ct);
        res.EnsureSuccessStatusCode();
        if (res.StatusCode != HttpStatusCode.OK)
            throw new IOException("การดาวน์โหลดแบบไฟล์เดียวต้องได้รับ HTTP 200");
        // A full GET response may add a filename that was absent from the
        // initial one-byte Range probe. Preserve it before final assembly.
        job.Name = DownloadFileNaming.Resolve(job.Url, res);
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

}
