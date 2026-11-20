using System.Net;
using System.Net.Http.Headers;

namespace XStageDownloadManager;

/// <summary>
/// One policy for probing, ordinary byte ranges and non-range single streams.
/// Never retry authorization, missing assets, invalid byte ranges or TLS
/// certificate failures as if they were transient network interruptions.
/// </summary>
public static class DownloadRetryPolicy
{
    public const int DefaultAttempts = 5;
    public const int MinAttempts = 1;
    public const int MaxAttempts = 10;
    public const int InactivitySeconds = 45;

    public static bool IsTransientStatus(HttpStatusCode status) => (int)status switch
    {
        408 or 425 or 429 or 500 or 502 or 503 or 504 or 520 or 521 or 522 or 523 or 524 => true,
        _ => false
    };

    public static TimeSpan Backoff(int attempt, TimeSpan? retryAfter = null)
    {
        // A maximum of 30s for backoff; respect a server-provided wait up to
        // two minutes, otherwise let the job fail with a visible explanation.
        var seconds = Math.Min(30, Math.Pow(2, Math.Clamp(attempt - 1, 0, 5)));
        var delay = TimeSpan.FromSeconds(seconds);
        return retryAfter.HasValue && retryAfter.Value > delay ? retryAfter.Value : delay;
    }

    public static TimeSpan? RetryAfter(HttpResponseHeaders headers)
    {
        var value = headers.RetryAfter;
        if (value?.Delta is TimeSpan delta && delta > TimeSpan.Zero)
            return delta;
        if (value?.Date is DateTimeOffset date && date > DateTimeOffset.UtcNow)
            return date - DateTimeOffset.UtcNow;
        return null;
    }

    public static bool IsRecoverable(Exception exception) =>
        exception is HttpRequestException or IOException or TimeoutException;

    public static async Task DelayAsync(
        int attempt, HttpResponseHeaders? headers, CancellationToken cancellation)
    {
        var fromServer = headers is null ? null : RetryAfter(headers);
        if (fromServer is TimeSpan wait && wait > TimeSpan.FromMinutes(2))
            throw new IOException("เว็บไซต์กำหนด Retry-After นานกว่า 2 นาที (" +
                Math.Ceiling(wait.TotalMinutes) + " นาที) กรุณาเริ่มใหม่ภายหลัง");
        await Task.Delay(Backoff(attempt, fromServer), cancellation);
    }
}

// A mismatched 206 / ignored Range must never be appended to an existing
// byte-range segment. Only a fresh single-stream transfer is safe.
public sealed class UnsafeHttpRangeException : IOException
{
    public UnsafeHttpRangeException(string message) : base(message) { }
}
