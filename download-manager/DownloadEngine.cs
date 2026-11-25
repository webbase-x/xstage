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
    private readonly TransferSlotQueue _slots = new();
    private readonly TransferRateGate _globalSpeed = new();
    private readonly ConcurrentDictionary<string, TransferRateGate> _fileSpeed = new();
    private readonly ConcurrentDictionary<string, byte> _active = new();
    private static readonly JsonSerializerOptions Json = new() { WriteIndented = true, IncludeFields = true };
    private readonly string _index;
    private readonly string _settings;
    private readonly DownloadStateStore _state;
    private long _lastProgressSave;
    public string LastStorageError { get; private set; } = "";
    public string DatabasePath => _state.DatabasePath;
    public static readonly int[] AllowedParts = { 1, 2, 4, 8, 16, 32 };
    public SmartSyncStartupMode SmartSyncStartup => _state.ReadSmartSyncStartupMode();
    public void SetSmartSyncStartup(SmartSyncStartupMode mode) => _state.SaveSmartSyncStartupMode(mode);
    public int DefaultParts { get; private set; } = 4;
    public int MaxRetryCount { get; private set; } = DownloadRetryPolicy.DefaultAttempts;
    public int MaxConcurrentJobs => _slots.MaxConcurrent;
    public int MaxJobsPerHost => _slots.MaxPerHost;
    public int GlobalLimitKib => _globalSpeed.LimitKibPerSecond;
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
        MaxRetryCount = _state.ReadRetryLimit();
        _slots.Configure(_state.ReadPerformanceSetting("global_jobs", 2, 1, 8),
            _state.ReadPerformanceSetting("host_jobs", 2, 1, 8));
        _globalSpeed.Configure(_state.ReadPerformanceSetting("global_limit_kib",
            0, 0, 1_048_576));
        Jobs = _state.LoadOrMigrate(_index);
        _state.SaveDefaultParts(DefaultParts);
        foreach (var job in Jobs)
        {
            job.InterruptedOnStartup = job.Status is "Running" or "Queued" ||
                ((job.ResumeAfterRestart || job.ResumeWhenNetworkReturns) && job.Status == "Paused");
            if (job.Status is "Running" or "Queued") job.Status = "Paused";
            // Preserve intent if the process closes before recovery consent.
            job.ResumeAfterRestart = job.InterruptedOnStartup;
            job.ResumeWhenNetworkReturns = false;
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
    public string Save()
    {
        lock (_saveLock)
        {
            try
            {
                _state.SaveSnapshot(Jobs.ToArray());
                Interlocked.Exchange(ref _lastProgressSave, Environment.TickCount64);
                LastStorageError = "";
                return "";
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or
                                       Microsoft.Data.Sqlite.SqliteException or InvalidDataException)
            {
                var error = "บันทึกสถานะ SQLite ไม่สำเร็จ: " + ex.Message;
                LastStorageError = error;
                try
                {
                    File.AppendAllText(Path.Combine(Path.GetDirectoryName(DatabasePath)!,
                        "state-errors.log"), DateTimeOffset.Now.ToString("O") +
                        " " + error + Environment.NewLine);
                }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
                return error;
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
        if (!string.IsNullOrWhiteSpace(text) &&
            Uri.TryCreate(text.Trim(), UriKind.Absolute, out url) &&
            (url.Scheme == Uri.UriSchemeHttps || url.Scheme == Uri.UriSchemeHttp) &&
            string.IsNullOrEmpty(url.UserInfo)) return true;
        url = null;
        return false;
    }

    // Public Drive file shares can use the existing resumable HTTP engine.
    // Preserve resource keys; never import browser cookies or bypass quotas.
    public static Uri NormalizeDriveFileUrl(Uri uri)
    {
        if (!uri.IdnHost.Equals("drive.google.com", StringComparison.OrdinalIgnoreCase))
            return uri;
        if (uri.Scheme != Uri.UriSchemeHttps)
            throw new ArgumentException("Google Drive ต้องใช้ HTTPS");
        var query = System.Web.HttpUtility.ParseQueryString(uri.Query);
        var match = System.Text.RegularExpressions.Regex.Match(uri.AbsolutePath,
            @"^/file/d/([A-Za-z0-9_-]+)(?:/(?:view|preview|edit))?/?$");
        var id = match.Success ? match.Groups[1].Value :
            uri.AbsolutePath is "/open" or "/uc" ? query["id"] : null;
        if (id is null || !System.Text.RegularExpressions.Regex.IsMatch(id, @"^[A-Za-z0-9_-]{1,256}$"))
            throw new ArgumentException("กรุณาใช้ลิงก์แชร์ไฟล์ Google Drive ไม่ใช่โฟลเดอร์");
        var key = query["resourcekey"];
        return new Uri("https://drive.google.com/uc?export=download&id=" +
            Uri.EscapeDataString(id) + (string.IsNullOrEmpty(key) ? "" :
            "&resourcekey=" + Uri.EscapeDataString(key)));
    }

    public void SetDefaultParts(int parts)
    {
        ValidateParts(parts);
        // Persist first: a failed SQLite write must not silently change the
        // in-memory default for subsequent downloads.
        _state.SaveDefaultParts(parts);
        DefaultParts = parts;
    }

    public void SetRetryLimit(int attempts)
    {
        if (attempts < DownloadRetryPolicy.MinAttempts ||
            attempts > DownloadRetryPolicy.MaxAttempts)
            throw new ArgumentOutOfRangeException(nameof(attempts),
                "จำนวนครั้งลองใหม่ต้องอยู่ระหว่าง 1 ถึง 10");
        _state.SaveRetryLimit(attempts);
        MaxRetryCount = attempts;
    }

    public void ConfigurePerformance(int concurrentJobs, int perHostJobs, int globalLimitKib)
    {
        if (concurrentJobs is < 1 or > 8 || perHostJobs is < 1 or > 8)
            throw new ArgumentOutOfRangeException(nameof(concurrentJobs));
        if (globalLimitKib != 0 && globalLimitKib is < 64 or > 1_048_576)
            throw new ArgumentOutOfRangeException(nameof(globalLimitKib));
        // Save all three before changing live limits; no partially committed
        // performance profile is ever restored after an interrupted write.
        _state.SavePerformanceSettings(concurrentJobs, perHostJobs, globalLimitKib);
        _slots.Configure(concurrentJobs, perHostJobs);
        _globalSpeed.Configure(globalLimitKib);
    }

    public void SetJobQueue(DownloadJob job, string queueName)
    {
        if (!Jobs.Contains(job))
            throw new ArgumentException("Unknown job.", nameof(job));
        var normalized = queueName?.Trim();
        if (string.IsNullOrWhiteSpace(normalized) || normalized.Length > 64 ||
            normalized.Any(char.IsControl))
            throw new ArgumentException("Queue name must be 1–64 printable characters.", nameof(queueName));
        var previous = job.QueueName;
        job.QueueName = normalized;
        var storageError = Save();
        if (storageError.Length > 0)
        {
            job.QueueName = previous;
            throw new IOException(storageError);
        }
    }

    // Rename a logical queue in one durable checkpoint, without touching job bytes
    // or transfer state. Restore every assignment if SQLite persistence fails.
    public int RenameQueue(string oldName, string newName)
    {
        var source = oldName?.Trim();
        var target = newName?.Trim();
        if (string.IsNullOrWhiteSpace(source) || source.Length > 64 ||
            source.Any(char.IsControl) || string.IsNullOrWhiteSpace(target) ||
            target.Length > 64 || target.Any(char.IsControl))
            throw new ArgumentException("Queue names must be 1–64 printable characters.");
        // Treat legacy blank queue names as the default queue shown in the UI.
        static string EffectiveQueue(DownloadJob job) =>
            string.IsNullOrWhiteSpace(job.QueueName) ? "ทั่วไป" : job.QueueName.Trim();
        var affected = Jobs.Where(j => string.Equals(EffectiveQueue(j), source,
            StringComparison.OrdinalIgnoreCase)).ToArray();
        if (affected.Length == 0) return 0;
        if (Jobs.Any(j => !affected.Contains(j) &&
            string.Equals(EffectiveQueue(j), target, StringComparison.OrdinalIgnoreCase)))
            throw new ArgumentException("Destination queue already exists.", nameof(newName));
        var originals = affected.Select(j => j.QueueName).ToArray();
        for (var i = 0; i < affected.Length; i++) affected[i].QueueName = target;
        var storageError = Save();
        if (storageError.Length > 0)
        {
            for (var i = 0; i < affected.Length; i++) affected[i].QueueName = originals[i];
            throw new IOException(storageError);
        }
        return affected.Length;
    }

    public IReadOnlyList<string> GetQueueNames() => Jobs
        .Select(j => string.IsNullOrWhiteSpace(j.QueueName) ? "ทั่วไป" : j.QueueName.Trim())
        .Distinct(StringComparer.OrdinalIgnoreCase)
        .OrderBy(n => n, StringComparer.CurrentCultureIgnoreCase)
        .ToArray();

    public void SetJobPriority(DownloadJob job, int priority)
    {
        if (!Jobs.Contains(job) || priority is < 0 or > 2)
            throw new ArgumentOutOfRangeException(nameof(priority));
        var previous = job.Priority;
        job.Priority = priority;
        _slots.Reprioritize(job.Id, priority);
        var storageError = Save();
        if (storageError.Length > 0)
        {
            job.Priority = previous;
            _slots.Reprioritize(job.Id, previous);
            throw new IOException(storageError);
        }
    }

    public void SetFileSpeedLimit(DownloadJob job, int limitKib)
    {
        if (!Jobs.Contains(job) ||
            (limitKib != 0 && limitKib is < 64 or > 1_048_576))
            throw new ArgumentOutOfRangeException(nameof(limitKib));
        var previous = job.FileSpeedLimitKib;
        job.FileSpeedLimitKib = limitKib;
        var gate = _fileSpeed.GetOrAdd(job.Id, _ => new TransferRateGate());
        gate.Configure(limitKib);
        var storageError = Save();
        if (storageError.Length > 0)
        {
            job.FileSpeedLimitKib = previous;
            gate.Configure(previous);
            throw new IOException(storageError);
        }
    }

    private Task LimitNetworkReadAsync(DownloadJob job, int bytes, CancellationToken ct)
    {
        var fileGate = job.FileSpeedLimitKib > 0
            ? _fileSpeed.GetOrAdd(job.Id, _ => new TransferRateGate(job.FileSpeedLimitKib))
            : null;
        return TransferRateLimiter.WaitAsync(_globalSpeed, fileGate, bytes, ct);
    }

    private static int ReadBufferSize(DownloadJob job, int globalLimitKib) =>
        globalLimitKib > 0 || job.FileSpeedLimitKib > 0 ? 8192 : 131072;

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
        // Refuse to discard resumable chunks when durable state is unavailable.
        // Keep the previous settings and partial files intact on SQLite failure.
        var previousParts = job.Parts;
        var previousSegments = job.SegmentsUsed;
        var previousSegmentBytes = job.SegmentDownloadedBytes;
        var previousTotal = job.TotalBytes;
        var previousRanges = job.SupportsRanges;
        var previousTag = job.ETag;
        var previousModified = job.LastModified;
        var previousDownloaded = job.DownloadedBytes;
        var previousPrevious = job.PreviousBytes;
        var previousError = job.Error;
        var previousStatus = job.Status;
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
        var saveError = Save();
        if (saveError.Length > 0)
        {
            job.Parts = previousParts;
            job.SegmentsUsed = previousSegments;
            job.SegmentDownloadedBytes = previousSegmentBytes;
            job.TotalBytes = previousTotal;
            job.SupportsRanges = previousRanges;
            job.ETag = previousTag;
            job.LastModified = previousModified;
            job.DownloadedBytes = previousDownloaded;
            job.PreviousBytes = previousPrevious;
            job.Error = previousError;
            job.Status = previousStatus;
            throw new IOException(saveError);
        }
        // The new geometry is already durable. If Windows locks an old
        // chunk, report the cleanup failure without reverting SQLite to an
        // incompatible geometry; the next transfer will discard stale parts.
        if (Directory.Exists(work))
        {
            try { Directory.Delete(work, true); }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                job.Error = "เปลี่ยนจำนวนส่วนแล้ว แต่ยังลบไฟล์ชั่วคราวเดิมไม่ได้: " +
                    ex.Message + " กรุณาปิดโปรแกรมที่ใช้งานไฟล์ แล้วลองเริ่มดาวน์โหลดอีกครั้ง";
                Save();
                throw new IOException(job.Error, ex);
            }
        }
        return true;
    }

    public DownloadJob Add(string url, string folder, int? parts = null, string videoQuality = "Best", string outputFormat = "mp4", bool separateCopy = false)
    {
        if (!TryParseUrl(url, out var uri) || uri is null)
            throw new ArgumentException("รองรับลิงก์ HTTP/HTTPS ที่ถูกต้องเท่านั้น");
        // Protected subscription player pages are not downloadable files.
        // Reject before inserting a job or writing SQLite; the Media menu
        // opens the provider's official browser player instead.
        var host = uri.IdnHost.TrimEnd('.');
        if (new[] { "netflix.com", "disneyplus.com", "primevideo.com" }
            .Any(domain => host.Equals(domain, StringComparison.OrdinalIgnoreCase) ||
                           host.EndsWith("." + domain, StringComparison.OrdinalIgnoreCase)))
            throw new ArgumentException(
                "บริการสตรีมมิงนี้ต้องรับชมผ่านเว็บไซต์หรือแอปทางการ ไม่สามารถดาวน์โหลดเนื้อหาที่ป้องกัน DRM ได้");
        uri = NormalizeDriveFileUrl(uri);
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
        // A new transfer must not start unless its record is durable. Otherwise
        // a crash can leave downloaded bytes with no recoverable job history.
        var storageError = Save();
        if (storageError.Length > 0)
        {
            Jobs.Remove(job);
            throw new IOException(storageError);
        }
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
        // Never transfer an arbitrary/untracked job: it has no durable recovery
        // record and could overwrite a file without appearing in history.
        if (!Jobs.Contains(job))
            throw new ArgumentException("Unknown download job.", nameof(job));
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
        var previousStatus = job.Status;
        var previousError = job.Error;
        var previousRestart = job.ResumeAfterRestart;
        var previousNetwork = job.ResumeWhenNetworkReturns;
        var previousInterrupted = job.InterruptedOnStartup;
        job.ResumeAfterRestart = false;
        job.ResumeWhenNetworkReturns = false;
        job.InterruptedOnStartup = false;
        job.Status = "Queued";
        job.Error = "";
        var cts = new CancellationTokenSource();
        job.Cancellation = cts;
        var checkpointError = Save();
        if (checkpointError.Length > 0)
        {
            job.Status = previousStatus;
            job.Error = previousError;
            job.ResumeAfterRestart = previousRestart;
            job.ResumeWhenNetworkReturns = previousNetwork;
            job.InterruptedOnStartup = previousInterrupted;
            job.Cancellation = null;
            _active.TryRemove(job.Id, out _);
            cts.Dispose();
            throw new IOException(checkpointError);
        }
        _ = Task.Run(async () =>
        {
            IDisposable? slot = null;
            try
            {
                var host = new Uri(job.Url).Host;
                slot = await _slots.EnterAsync(job.Id, host, job.Priority, cts.Token);
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
                slot?.Dispose();
                _fileSpeed.TryRemove(job.Id, out _);
                _active.TryRemove(job.Id, out _);
                if (ReferenceEquals(job.Cancellation, cts)) job.Cancellation = null;
                cts.Dispose();
                Save();
            }
        });
    }

    /// <summary>
    /// Rename a verified completed file on disk and in SQLite together.
    /// Keep its real extension, never overwrite a sibling, never escape the
    /// selected folder, and refuse changes to a running/partial transfer.
    /// </summary>
    public string RenameCompletedFile(DownloadJob job, string newName)
    {
        if (!Jobs.Contains(job) || job.Status != "Completed" ||
            _active.ContainsKey(job.Id))
            throw new InvalidOperationException("เปลี่ยนชื่อได้เฉพาะไฟล์ที่ดาวน์โหลดสำเร็จและไม่มีงานค้าง");
        var oldPath = Path.GetFullPath(job.CompletedPath);
        var folder = Path.GetFullPath(job.Folder).TrimEnd(Path.DirectorySeparatorChar);
        if (!string.Equals(Path.GetDirectoryName(oldPath)?.TrimEnd(Path.DirectorySeparatorChar),
                           folder, StringComparison.OrdinalIgnoreCase) || !File.Exists(oldPath))
            throw new IOException("ไม่พบไฟล์ที่ดาวน์โหลดในโฟลเดอร์ปลายทาง");
        if (string.IsNullOrWhiteSpace(newName) ||
            newName.IndexOfAny(new[] { '/', '\\', ':' }) >= 0)
            throw new ArgumentException("กรุณาระบุชื่อไฟล์เท่านั้น ไม่ใส่เส้นทาง");
        var clean = DownloadFileNaming.CleanName(newName);
        var oldExtension = Path.GetExtension(oldPath);
        var requestedExtension = Path.GetExtension(clean);
        if (requestedExtension.Length > 0 &&
            !requestedExtension.Equals(oldExtension, StringComparison.OrdinalIgnoreCase))
            throw new ArgumentException("เปลี่ยนชื่อได้ แต่ไม่สามารถเปลี่ยนนามสกุลไฟล์จริง");
        if (requestedExtension.Length == 0) clean += oldExtension;
        clean = DownloadFileNaming.CleanName(clean);
        var destination = Path.Combine(folder, clean);
        if (string.Equals(oldPath, destination, StringComparison.OrdinalIgnoreCase))
            return oldPath;
        destination = DownloadFileNaming.UniqueOutput(folder, clean);
        var originalName = job.Name;
        File.Move(oldPath, destination);
        job.Name = Path.GetFileName(destination);
        job.CompletedPath = destination;
        var storageError = Save();
        if (storageError.Length > 0)
        {
            job.Name = originalName;
            job.CompletedPath = oldPath;
            try { File.Move(destination, oldPath); }
            catch (IOException) { }
            throw new IOException("บันทึกชื่อไฟล์ในฐานข้อมูลไม่สำเร็จ: " + storageError);
        }
        return destination;
    }

    public void Pause(DownloadJob job)
    {
        if (job.Status == "Paused")
        {
            // Manual Stop while offline explicitly opts out of automatic recovery.
            if (job.ResumeWhenNetworkReturns || job.ResumeAfterRestart ||
                job.InterruptedOnStartup)
            {
                job.ResumeWhenNetworkReturns = false;
                job.ResumeAfterRestart = false;
                job.InterruptedOnStartup = false;
                Save();
            }
            return;
        }
        if (job.Status is not ("Running" or "Queued")) return;
        job.Status = "Paused";
        job.ResumeAfterRestart = false;
        job.ResumeWhenNetworkReturns = false;
        job.InterruptedOnStartup = false;
        try { job.Cancellation?.Cancel(); } catch (ObjectDisposedException) { }
        Save();
    }

    public void PauseAll()
    {
        foreach (var job in Jobs.ToArray()) Pause(job);
    }

    // Only previously active jobs are eligible for consent-based recovery.
    public void PauseAllForShutdown()
    {
        var toRecover = Jobs.Where(job => job.Status is "Running" or "Queued").ToArray();
        foreach (var job in toRecover) Pause(job);
        foreach (var job in toRecover)
            if (job.Status == "Paused") job.ResumeAfterRestart = true;
        Save();
    }

    public int InterruptedJobCount =>
        Jobs.Count(job => job.InterruptedOnStartup && job.Status == "Paused");

    public void RecoverInterruptedJobs(bool resume)
    {
        var interrupted = Jobs.Where(job => job.InterruptedOnStartup &&
            job.Status == "Paused").ToArray();
        foreach (var job in interrupted)
        {
            job.InterruptedOnStartup = false;
            job.ResumeAfterRestart = false;
            job.ResumeWhenNetworkReturns = false;
        }
        Save();
        if (resume)
            foreach (var job in interrupted)
                Start(job);
    }

    // Network recovery never includes items the user explicitly paused.
    // Wait for canceled workers to relinquish their slot before restarting.
    public void PauseForNetworkOutage()
    {
        var interrupted = Jobs.Where(job => job.Status is "Running" or "Queued").ToArray();
        foreach (var job in interrupted) Pause(job);
        foreach (var job in interrupted)
            if (job.Status == "Paused") job.ResumeWhenNetworkReturns = true;
        if (interrupted.Length > 0) Save();
    }

    public void TryResumeNetworkInterrupted()
    {
        var ready = Jobs.Where(job => job.ResumeWhenNetworkReturns &&
            job.Status == "Paused" && !_active.ContainsKey(job.Id)).ToArray();
        foreach (var job in ready)
        {
            job.ResumeWhenNetworkReturns = false;
            Start(job);
        }
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

    private async Task<ProbeInfo> ProbeAsync(DownloadJob job, CancellationToken ct)
    {
        Exception? last = null;
        for (var attempt = 1; attempt <= MaxRetryCount; attempt++)
        {
            ct.ThrowIfCancellationRequested();
            TimeSpan? retryAfter = null;
            using var idle = CancellationTokenSource.CreateLinkedTokenSource(ct);
            idle.CancelAfter(TimeSpan.FromSeconds(DownloadRetryPolicy.InactivitySeconds));
            try
            {
                job.TransferPhase = attempt == 1 ? "กำลังตรวจสอบเซิร์ฟเวอร์"
                    : $"กำลังตรวจสอบใหม่ ({attempt}/{MaxRetryCount})";
                using var req = Request(HttpMethod.Get, job.Url);
                req.Headers.Range = new RangeHeaderValue(0, 0);
                using var response = await Http.SendAsync(req,
                    HttpCompletionOption.ResponseHeadersRead, idle.Token);
                if (!response.IsSuccessStatusCode)
                {
                    retryAfter = DownloadRetryPolicy.RetryAfter(response.Headers);
                    response.EnsureSuccessStatusCode();
                }
                if (new Uri(job.Url).IdnHost.Equals("drive.google.com", StringComparison.OrdinalIgnoreCase) &&
                    response.Content.Headers.ContentType?.MediaType?.Equals("text/html", StringComparison.OrdinalIgnoreCase) == true &&
                    response.Content.Headers.ContentDisposition?.DispositionType?.Equals("attachment", StringComparison.OrdinalIgnoreCase) != true)
                    throw new UnsafeHttpRangeException("Google Drive ส่งหน้าขออนุญาตหรือยืนยันดาวน์โหลดแทนไฟล์ กรุณาตรวจสิทธิ์และดาวน์โหลดผ่านเว็บไซต์ทางการ");
                var range = response.Content.Headers.ContentRange;
                var supported = response.StatusCode == HttpStatusCode.PartialContent &&
                    range?.HasLength == true && range.From == 0 && range.To == 0;
                if (response.StatusCode == HttpStatusCode.PartialContent && !supported)
                    throw new UnsafeHttpRangeException("Probe Range 0-0 ไม่ถูกต้อง");
                var length = supported ? range!.Length!.Value
                    : response.Content.Headers.ContentLength ?? -1;
                job.TransferPhase = "";
                return new ProbeInfo(supported, length,
                    response.Headers.ETag?.ToString() ?? "",
                    response.Content.Headers.LastModified,
                    DownloadFileNaming.Resolve(job.Url, response));
            }
            catch (HttpRequestException ex) when (ex.StatusCode.HasValue &&
                !DownloadRetryPolicy.IsTransientStatus(ex.StatusCode.Value))
            {
                throw new IOException("เซิร์ฟเวอร์ปฏิเสธลิงก์ดาวน์โหลด HTTP " +
                    (int)ex.StatusCode.Value + " (ไม่ลองใหม่)", ex);
            }
            catch (OperationCanceledException) when (!ct.IsCancellationRequested)
            {
                last = new IOException("ตรวจสอบเซิร์ฟเวอร์ไม่ตอบกลับภายใน 45 วินาที");
            }
            catch (Exception ex) when (ex is HttpRequestException or IOException)
            {
                last = ex;
                if (ex is UnsafeHttpRangeException) throw;
            }

            if (attempt == MaxRetryCount) break;
            job.TransferPhase = $"ตรวจสอบไม่สำเร็จ — จะลองใหม่ ({attempt}/{MaxRetryCount})";
            await DownloadRetryPolicy.DelayAsync(attempt, retryAfter, ct);
        }
        throw new IOException("ตรวจสอบลิงก์ดาวน์โหลดไม่สำเร็จหลังลอง " +
            MaxRetryCount + " ครั้ง: " + last?.Message, last);
    }

    private async Task DownloadAsync(DownloadJob job, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        Directory.CreateDirectory(job.Folder);
        if (SocialVideoDownloader.IsVideoUrl(job.Url))
        {
            await SocialVideoDownloader.DownloadAsync(job, WorkDir(job), ct, GlobalLimitKib);
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
        if (sourceChanged)
        {
            if (Directory.Exists(work)) Directory.Delete(work, true);
            // Source identity changed: previously persisted byte boundaries
            // must not constrain the fresh transfer.
            job.SegmentsUsed = 0;
            job.SegmentDownloadedBytes = Array.Empty<long>();
            Interlocked.Exchange(ref job.DownloadedBytes, 0);
            // Do not carry the previous source's speed/ETA baseline into
            // the newly probed file.
            job.PreviousBytes = 0;
            job.SpeedBytesPerSecond = 0;
            job.SmoothedSpeedBytesPerSecond = 0;
        }
        Directory.CreateDirectory(work);
        job.TotalBytes = probe.Total;
        job.SupportsRanges = probe.Ranges;
        job.ETag = probe.ETag;
        job.LastModified = probe.LastModified;
        if (probe.Ranges && probe.Total > 0)
        {
            try
            {
                await ParallelDownloadAsync(job, work, ct);
            }
            catch (UnsafeHttpRangeException)
            {
                // The server changed or ignored Range after the initial probe.
                // Never append 200/incorrect 206 bytes to old partials.
                foreach (var part in Directory.GetFiles(work, "*.part"))
                    File.Delete(part);
                job.SupportsRanges = false;
                job.SegmentsUsed = 1;
                job.SegmentDownloadedBytes = Array.Empty<long>();
                job.TransferPhase = "เซิร์ฟเวอร์ไม่รองรับการแบ่งส่วน — โหลดแบบสตรีมเดียว";
                await SingleDownloadAsync(job, work, ct);
            }
        }
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
                // Merge exactly the persisted byte-boundary geometry used by
                // the Range workers. The configured Parts may differ after a
                // restart; merging by that preference can silently corrupt ZIPs.
                int count = job.SegmentsUsed;
                if (count < 1 || count > 32)
                    throw new InvalidDataException("ไม่พบจำนวนส่วนดาวน์โหลดที่ยืนยันแล้ว");
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
        job.TransferPhase = "";
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

    // Pure policy, exercised by deterministic network telemetry simulations.
    public static int NextRangeConcurrency(int current, int count, int ceiling,
        double previousRate, double rate)
    {
        var maximum = Math.Max(1, Math.Min(count, ceiling));
        current = Math.Clamp(current, 1, maximum);
        if (!double.IsFinite(rate) || rate <= 0)
            return Math.Max(1, current / 2);
        if (double.IsFinite(previousRate) && previousRate > 0 &&
            rate < previousRate * 0.75)
            return Math.Max(1, current / 2);
        return Math.Min(maximum, current * 2);
    }

    private async Task ParallelDownloadAsync(DownloadJob job, string work, CancellationToken ct)
    {
        // Never re-partition an existing resumable transfer. Throughput-driven
        // selection applies only before the first segment is created.
        // Only use a real observed throughput sample. A fresh job has no
        // sample and retains the user's configured part count. Persisted Range
        // geometry is never adapted: changing it would corrupt resume bytes.
        var recommendedParts = AdaptiveSegmentPlanner.RecommendWithLimits(
            job.Parts, job.TotalBytes, job.SmoothedSpeedBytesPerSecond,
            job.SegmentsUsed > 0, GlobalLimitKib, job.FileSpeedLimitKib);
        var count = job.SegmentsUsed > 0
            ? SegmentCount(job.TotalBytes, job.SegmentsUsed)
            : SegmentCount(job.TotalBytes, recommendedParts);
        // Save the actual geometry with the job so resumption never reuses a segment
        // written for different byte boundaries. Older jobs default to zero (unknown).
        // A zero/unknown geometry cannot validate pre-existing chunks. This
        // also recovers safely when a previous repartition persisted its new
        // geometry but Windows refused to delete a locked old chunk.
        if (job.SegmentsUsed != count)
        {
            foreach (var path in Directory.GetFiles(work, "*.part")) File.Delete(path);
        }
        job.SegmentsUsed = count;
        job.SegmentDownloadedBytes = new long[count];
        long existingTotal = 0;
        for (int i = 0; i < count; i++)
        {
            var begin = TransferSegmentGeometry.Boundary(job.TotalBytes, i, count);
            var end = TransferSegmentGeometry.Boundary(job.TotalBytes, i + 1, count) - 1;
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
            // Every segment was discarded: reset the corresponding UI/SQLite
            // progress counters as well, not only the aggregate byte count.
            Array.Clear(job.SegmentDownloadedBytes);
            // Discard the previous EWMA sampling baseline with the rejected
            // chunks; otherwise the first post-recovery ETA can be negative.
            job.PreviousBytes = 0;
        }
        Interlocked.Exchange(ref job.DownloadedBytes, existingTotal);
        // Commit the exact byte-boundary geometry before any Range worker writes
        // a chunk. Otherwise a crash can leave valid-looking partial files
        // alongside an unknown (zero) geometry in SQLite.
        var checkpointError = Save();
        if (checkpointError.Length > 0)
            throw new IOException("ไม่สามารถบันทึกขอบเขตการดาวน์โหลดก่อนเริ่มเขียนไฟล์: " +
                checkpointError);
        // Keep persisted byte geometry immutable; adapt only the number of
        // active range workers. Start conservatively and sample completed bytes.
        var tasks = new List<Task>();
        var pending = new Queue<int>(Enumerable.Range(0, count).Where(i =>
            job.SegmentDownloadedBytes[i] < TransferSegmentGeometry.Boundary(job.TotalBytes, i + 1, count)
                - TransferSegmentGeometry.Boundary(job.TotalBytes, i, count)));
        var active = new List<Task>();
        var target = Math.Min(2, count);
        var previousBytes = Interlocked.Read(ref job.DownloadedBytes);
        var previousTick = Environment.TickCount64;
        double previousRate = 0;
        while (pending.Count > 0 || active.Count > 0)
        {
            while (!ct.IsCancellationRequested && !tasks.Any(t => t.IsFaulted || t.IsCanceled)
                && pending.Count > 0 && active.Count < target)
            {
                var i = pending.Dequeue();
                var begin = TransferSegmentGeometry.Boundary(job.TotalBytes, i, count);
                var end = TransferSegmentGeometry.Boundary(job.TotalBytes, i + 1, count) - 1;
                var task = DownloadPartAsync(job, PartPath(work, i), begin, end, i, ct);
                active.Add(task);
                tasks.Add(task);
            }
            if (active.Count == 0) break;
            await Task.WhenAny(active.Append(Task.Delay(1000))).ConfigureAwait(false);
            active.RemoveAll(t => t.IsCompleted);
            var now = Environment.TickCount64;
            if (now - previousTick >= 1000)
            {
                var bytes = Interlocked.Read(ref job.DownloadedBytes);
                var rate = Math.Max(0, bytes - previousBytes) * 1000d / (now - previousTick);
                var ceiling = AdaptiveSegmentPlanner.RecommendWithLimits(job.Parts,
                    job.TotalBytes, rate, false, GlobalLimitKib, job.FileSpeedLimitKib);
                target = NextRangeConcurrency(target, count, ceiling, previousRate, rate);
                previousRate = rate;
                previousBytes = bytes;
                previousTick = now;
            }
        }
        try { await Task.WhenAll(tasks); ct.ThrowIfCancellationRequested(); }
        catch
        {
            if (tasks.Any(task => task.Exception?.Flatten().InnerExceptions
                    .Any(error => error is UnsafeHttpRangeException) == true))
                throw new UnsafeHttpRangeException(
                    "เซิร์ฟเวอร์ส่งข้อมูล Range ไม่ตรงกับที่ร้องขอ");
            throw;
        }
    }

    private async Task DownloadPartAsync(DownloadJob job, string file,
        long begin, long end, int segmentIndex, CancellationToken ct)
    {
        var expected = end - begin + 1;
        Exception? last = null;
        for (int attempt = 1; attempt <= MaxRetryCount; attempt++)
        {
            ct.ThrowIfCancellationRequested();
            var saved = File.Exists(file) ? new FileInfo(file).Length : 0;
            if (saved == expected) return;
            if (saved > expected)
                throw new IOException("ข้อมูล Chunk ที่บันทึกไว้เกินช่วงที่คาดไว้");
            TimeSpan? retryAfter = null;
            using var idle = CancellationTokenSource.CreateLinkedTokenSource(ct);
            idle.CancelAfter(TimeSpan.FromSeconds(DownloadRetryPolicy.InactivitySeconds));
            try
            {
                using var req = Request(HttpMethod.Get, job.Url);
                req.Headers.Range = new RangeHeaderValue(begin + saved, end);
                if (!string.IsNullOrEmpty(job.ETag) &&
                    !job.ETag.StartsWith("W/", StringComparison.OrdinalIgnoreCase))
                    req.Headers.TryAddWithoutValidation("If-Range", job.ETag);
                else if (job.LastModified.HasValue)
                    req.Headers.TryAddWithoutValidation("If-Range",
                        job.LastModified.Value.ToString("R"));

                using var response = await Http.SendAsync(req,
                    HttpCompletionOption.ResponseHeadersRead, idle.Token);
                if (response.StatusCode != HttpStatusCode.PartialContent)
                {
                    if (DownloadRetryPolicy.IsTransientStatus(response.StatusCode))
                    {
                        retryAfter = DownloadRetryPolicy.RetryAfter(response.Headers);
                        throw new HttpRequestException("HTTP " + (int)response.StatusCode,
                            null, response.StatusCode);
                    }
                    if (response.StatusCode == HttpStatusCode.OK)
                        throw new UnsafeHttpRangeException("เซิร์ฟเวอร์ไม่ยอมรับ Range แล้ว (HTTP 200)");
                    response.EnsureSuccessStatusCode();
                    throw new UnsafeHttpRangeException("เซิร์ฟเวอร์ไม่ตอบกลับ HTTP 206");
                }
                var range = response.Content.Headers.ContentRange;
                if (range?.From != begin + saved || range.To != end ||
                    range.Length != job.TotalBytes)
                    throw new UnsafeHttpRangeException(
                        "ช่วงข้อมูล 206 หรือขนาดไฟล์ไม่ตรงกับที่ร้องขอ");
                var remaining = expected - saved;
                if (response.Content.Headers.ContentLength is long n && n != remaining)
                    throw new UnsafeHttpRangeException("Content-Length ของ Chunk ไม่ตรง");

                await using var output = new FileStream(file, FileMode.Append,
                    FileAccess.Write, FileShare.Read, 131072, FileOptions.Asynchronous);
                await using var input = await response.Content.ReadAsStreamAsync(idle.Token);
                var buffer = new byte[131072];
                while (remaining > 0)
                {
                    var amount = (int)Math.Min(
                        ReadBufferSize(job, GlobalLimitKib), remaining);
                    await LimitNetworkReadAsync(job, amount, ct);
                    idle.CancelAfter(TimeSpan.FromSeconds(DownloadRetryPolicy.InactivitySeconds));
                    var read = await input.ReadAsync(
                        buffer.AsMemory(0, amount), idle.Token);
                    if (read == 0)
                        throw new EndOfStreamException("ข้อมูลช่วงดาวน์โหลดหยุดก่อนครบ");
                    await output.WriteAsync(buffer.AsMemory(0, read), ct);
                    Interlocked.Add(ref job.SegmentDownloadedBytes[segmentIndex], read);
                    Interlocked.Add(ref job.DownloadedBytes, read);
                    remaining -= read;
                    idle.CancelAfter(TimeSpan.FromSeconds(DownloadRetryPolicy.InactivitySeconds));
                }
                await output.FlushAsync(ct);
                job.TransferPhase = "";
                return;
            }
            catch (HttpRequestException ex) when (ex.StatusCode.HasValue &&
                !DownloadRetryPolicy.IsTransientStatus(ex.StatusCode.Value))
            {
                throw new IOException("Chunk ถูกเซิร์ฟเวอร์ปฏิเสธ HTTP " +
                    (int)ex.StatusCode.Value + " (ไม่ลองใหม่)", ex);
            }
            catch (OperationCanceledException) when (!ct.IsCancellationRequested)
            {
                last = new IOException("Chunk ไม่มีข้อมูลใหม่เกิน 45 วินาที");
            }
            catch (Exception ex) when ((ex is IOException or HttpRequestException) &&
                                       ex is not UnsafeHttpRangeException)
            {
                last = ex;
            }

            if (attempt == MaxRetryCount) break;
            job.TransferPhase = $"Chunk {segmentIndex + 1} หลุด — ต่อใหม่ ({attempt}/{MaxRetryCount})";
            await DownloadRetryPolicy.DelayAsync(attempt, retryAfter, ct);
        }
        throw new IOException("Chunk " + (segmentIndex + 1) + " ไม่สำเร็จหลัง " +
            MaxRetryCount + " ครั้ง: " + last?.Message, last);
    }

    private async Task SingleDownloadAsync(DownloadJob job, string work, CancellationToken ct)
    {
        // Non-range servers cannot resume from the middle. Retry creates a
        // fresh temporary stream each time, never appending corrupt bytes.
        var path = Path.Combine(work, "whole.part");
        job.SegmentDownloadedBytes = Array.Empty<long>();
        Exception? last = null;
        for (var attempt = 1; attempt <= MaxRetryCount; attempt++)
        {
            ct.ThrowIfCancellationRequested();
            TimeSpan? retryAfter = null;
            using var idle = CancellationTokenSource.CreateLinkedTokenSource(ct);
            idle.CancelAfter(TimeSpan.FromSeconds(DownloadRetryPolicy.InactivitySeconds));
            try
            {
                // A non-Range retry restarts from byte zero; reset the speed
                // sample baseline too, otherwise ETA can use stale bytes.
                Interlocked.Exchange(ref job.DownloadedBytes, 0);
                job.PreviousBytes = 0;
                using var req = Request(HttpMethod.Get, job.Url);
                using var res = await Http.SendAsync(req,
                    HttpCompletionOption.ResponseHeadersRead, idle.Token);
                if (DownloadRetryPolicy.IsTransientStatus(res.StatusCode))
                {
                    retryAfter = DownloadRetryPolicy.RetryAfter(res.Headers);
                    throw new HttpRequestException("HTTP " + (int)res.StatusCode,
                        null, res.StatusCode);
                }
                res.EnsureSuccessStatusCode();
                if (res.StatusCode != HttpStatusCode.OK)
                    throw new IOException("สตรีมเดียวต้องได้รับ HTTP 200");
                job.Name = DownloadFileNaming.Resolve(job.Url, res);
                if (res.Content.Headers.ContentLength is long announced && announced > 0)
                    job.TotalBytes = announced;

                await using var output = new FileStream(path, FileMode.Create,
                    FileAccess.Write, FileShare.Read, 131072, FileOptions.Asynchronous);
                await using var input = await res.Content.ReadAsStreamAsync(idle.Token);
                var buffer = new byte[131072];
                while (true)
                {
                    var amount = ReadBufferSize(job, GlobalLimitKib);
                    await LimitNetworkReadAsync(job, amount, ct);
                    idle.CancelAfter(TimeSpan.FromSeconds(DownloadRetryPolicy.InactivitySeconds));
                    var read = await input.ReadAsync(buffer.AsMemory(0, amount), idle.Token);
                    if (read == 0) break;
                    await output.WriteAsync(buffer.AsMemory(0, read), ct);
                    Interlocked.Add(ref job.DownloadedBytes, read);
                    idle.CancelAfter(TimeSpan.FromSeconds(DownloadRetryPolicy.InactivitySeconds));
                }
                await output.FlushAsync(ct);
                if (job.TotalBytes >= 0 &&
                    new FileInfo(path).Length != job.TotalBytes)
                    throw new IOException("สตรีมเดียวได้รับข้อมูลไม่ครบตามขนาดจากเซิร์ฟเวอร์");
                job.TransferPhase = "";
                return;
            }
            catch (HttpRequestException ex) when (ex.StatusCode.HasValue &&
                !DownloadRetryPolicy.IsTransientStatus(ex.StatusCode.Value))
            {
                throw new IOException("เว็บไซต์ปฏิเสธดาวน์โหลด HTTP " +
                    (int)ex.StatusCode.Value + " (ไม่ลองใหม่)", ex);
            }
            catch (OperationCanceledException) when (!ct.IsCancellationRequested)
            {
                last = new IOException("ไม่พบข้อมูลใหม่จากเซิร์ฟเวอร์เกิน 45 วินาที");
            }
            catch (Exception ex) when (ex is IOException or HttpRequestException)
            {
                last = ex;
            }

            if (attempt == MaxRetryCount) break;
            job.TransferPhase = $"สตรีมสะดุด — เริ่มใหม่ ({attempt}/{MaxRetryCount})";
            await DownloadRetryPolicy.DelayAsync(attempt, retryAfter, ct);
        }
        throw new IOException("ดาวน์โหลดสตรีมเดียวไม่สำเร็จหลัง " +
            MaxRetryCount + " ครั้ง: " + last?.Message, last);
    }
}
