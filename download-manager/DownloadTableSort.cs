namespace XStageDownloadManager;

/// <summary>
/// Sorts the displayed download jobs by real typed values, never by their
/// localized/abbreviated cell text ("12 MB", "100%", "dd/MM/yy").
/// Sorting does not change the persisted queue or the selected job identity.
/// </summary>
public static class DownloadTableSort
{
    public static string FileType(DownloadJob job)
    {
        // A completed file's verified path wins over the original URL/name.
        var source = job.Status == "Completed" &&
                     !string.IsNullOrWhiteSpace(job.CompletedPath)
            ? job.CompletedPath : job.Name;
        var extension = Path.GetExtension(source).TrimStart('.');
        if (extension.Length is > 0 and <= 12 &&
            extension.All(c => c is >= 'a' and <= 'z' or >= 'A' and <= 'Z' or >= '0' and <= '9'))
            return extension.ToUpperInvariant();

        // A social video may still be loading metadata, before a file exists.
        if (job.Kind == "Video")
        {
            var configured = job.VideoQuality == "AudioMP3" ? "mp3" : job.OutputFormat;
            if (configured is "mp4" or "mkv" or "webm" or "mp3")
                return configured.ToUpperInvariant();
        }
        return "ไม่ทราบ";
    }

    public static List<DownloadJob> Sort(
        IEnumerable<DownloadJob> displayedJobs,
        string? column, bool descending,
        IReadOnlyList<DownloadJob>? originalQueue = null)
    {
        var jobs = displayedJobs.ToList();
        if (string.IsNullOrWhiteSpace(column))
            return jobs;

        var index = originalQueue is null ? new Dictionary<string, int>() :
            originalQueue.Select((job, position) => (job, position))
                .ToDictionary(entry => entry.job.Id, entry => entry.position);

        return column switch
        {
            "File" => ByText(jobs, j => j.Name, descending),
            "FileType" => ByText(jobs, j => FileType(j), descending, "ไม่ทราบ"),
            "Queue" => ByNumber(jobs, j =>
                index.TryGetValue(j.Id, out var rank) ? rank : null, descending),
            "Size" => ByNumber(jobs, j => j.TotalBytes >= 0 ? j.TotalBytes : null, descending),
            "Progress" => ByNumber(jobs, j => ProgressPresentation.FillFraction(j), descending),
            "Status" => ByNumber(jobs, j => j.Status switch
            {
                "Running" => 0, "Queued" => 1, "Paused" => 2,
                "Failed" => 3, "Completed" => 4, _ => 5
            }, descending),
            "ETA" => ByNumber(jobs, RemainingSeconds, descending),
            "Speed" => ByNumber(jobs, j => j.Status == "Running"
                ? j.SpeedBytesPerSecond : 0, descending),
            "Added" => ByNumber(jobs, j => j.CreatedAt.UtcTicks, descending),
            "Parts" => ByNumber(jobs, j => j.Kind == "Video"
                ? Math.Min(j.Parts, 4) : j.SegmentsUsed > 0 ? j.SegmentsUsed : j.Parts, descending),
            "Description" => ByText(jobs, Category, descending),
            _ => jobs
        };
    }

    private static double? RemainingSeconds(DownloadJob j)
    {
        if (j.Status != "Running" || j.TotalBytes <= 0 ||
            j.SpeedBytesPerSecond < 1024)
            return null;
        var remaining = Math.Max(0, j.TotalBytes - Interlocked.Read(ref j.DownloadedBytes));
        return remaining / j.SpeedBytesPerSecond;
    }

    private static string Category(DownloadJob j)
    {
        var type = FileType(j);
        return type switch
        {
            "MP4" or "MKV" or "WEBM" or "AVI" or "MOV" => "วิดีโอ",
            "MP3" or "WAV" or "FLAC" or "M4A" or "OGG" => "เพลงและเสียง",
            "PDF" or "DOC" or "DOCX" or "XLS" or "XLSX" or "PPTX" or "TXT" => "เอกสาร",
            "EXE" or "MSI" or "APK" => "โปรแกรม",
            "ZIP" or "RAR" or "7Z" or "TAR" or "GZ" => "ไฟล์บีบอัด",
            _ => "อื่น ๆ"
        };
    }

    private static List<DownloadJob> ByText(
        List<DownloadJob> jobs, Func<DownloadJob, string> key,
        bool descending, string? unknown = null)
    {
        // Missing types are last in both directions, even with descending sort.
        return (descending
            ? jobs.OrderBy(j => unknown is not null &&
                string.Equals(key(j), unknown, StringComparison.OrdinalIgnoreCase) ? 1 : 0)
                .ThenByDescending(key, StringComparer.CurrentCultureIgnoreCase)
            : jobs.OrderBy(j => unknown is not null &&
                string.Equals(key(j), unknown, StringComparison.OrdinalIgnoreCase) ? 1 : 0)
                .ThenBy(key, StringComparer.CurrentCultureIgnoreCase)).ToList();
    }

    private static List<DownloadJob> ByNumber(
        List<DownloadJob> jobs, Func<DownloadJob, double?> key, bool descending)
    {
        // Missing sizes/ETAs always appear below known values in both directions.
        return (descending
            ? jobs.OrderBy(j => key(j).HasValue ? 0 : 1)
                .ThenByDescending(j => key(j) ?? 0)
            : jobs.OrderBy(j => key(j).HasValue ? 0 : 1)
                .ThenBy(j => key(j) ?? 0)).ToList();
    }
}
