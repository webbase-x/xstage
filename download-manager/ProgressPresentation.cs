namespace XStageDownloadManager;

/// <summary>
/// One source of truth for the displayed transfer percentage and full-green
/// state. yt-dlp may report 100% before FFmpeg finishes; HTTP fragments may
/// likewise reach their expected byte counts before final file validation.
/// </summary>
public static class ProgressPresentation
{
    public static bool IsComplete(DownloadJob job) => job.Status == "Completed";

    public static double FillFraction(DownloadJob job)
    {
        if (IsComplete(job)) return 1.0;
        if (job.Status == "Missing") return 0.0;
        var downloaded = Interlocked.Read(ref job.DownloadedBytes);
        double value = job.Kind == "Video" ? job.VideoPercent / 100.0 :
            job.TotalBytes > 0 ? downloaded / (double)job.TotalBytes : 0.0;
        if (!double.IsFinite(value)) return 0.0;
        // Do not paint or label 100% until the final file is verified.
        return Math.Clamp(value, 0.0, 0.999);
    }

    public static string PercentLabel(DownloadJob job) =>
        IsComplete(job) ? "100.0%" :
        (FillFraction(job) * 100.0).ToString("0.0", System.Globalization.CultureInfo.InvariantCulture) + "%";
}
