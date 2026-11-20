using System.Text.Json.Serialization;

namespace XStageDownloadManager;

public sealed class DownloadJob
{
    public string Id { get; set; } = Guid.NewGuid().ToString("N");
    public string Url { get; set; } = "";
    public string Name { get; set; } = "download";
    public string Kind { get; set; } = "File";
    public string VideoQuality { get; set; } = "Best";
    // Requested output container; independent of video resolution. Defaults to MP4.
    public string OutputFormat { get; set; } = "mp4";
    // Explicit new download from an existing video item. Give it a distinct
    // filename so yt-dlp cannot reuse or overwrite the existing saved video.
    public bool IsRedownload { get; set; }

    public double VideoPercent { get; set; }
    [JsonIgnore] public string VideoPhase = "";
    public string Folder { get; set; } = "";
    public string Status { get; set; } = "Queued";
    public string Error { get; set; } = "";
    public string CompletedPath { get; set; } = "";
    public long TotalBytes { get; set; } = -1;
    public long DownloadedBytes;
    public bool SupportsRanges { get; set; }
    public string ETag { get; set; } = "";
    public DateTimeOffset? LastModified { get; set; }
    public int Parts { get; set; } = 4;
    // Number of actual range slices used for this job, persisted across restarts.
    public int SegmentsUsed { get; set; }
    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.Now;
    // In-memory byte counters updated by each HTTP Range worker; no fake segment progress.
    [JsonIgnore] public long[] SegmentDownloadedBytes = Array.Empty<long>();
    [JsonIgnore] public long PreviousBytes;
    [JsonIgnore] public double SpeedBytesPerSecond;
    [JsonIgnore] public CancellationTokenSource? Cancellation;
}
