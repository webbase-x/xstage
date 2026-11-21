using System.Collections.Generic;
using System.Diagnostics;

namespace XStageDownloadManager;

/// <summary>
/// Fair, cancellation-safe download slot scheduler. It never changes the
/// durable queue position and it limits active jobs per originating host.
/// High-priority items are preferred, but an older low priority job is aged
/// every 20s so it cannot starve indefinitely.
/// </summary>
public sealed class TransferSlotQueue
{
    private sealed class Waiter
    {
        public required string Id;
        public required string Host;
        public required int Priority;
        public required long Sequence;
        public required long EnqueuedAt;
        public required TaskCompletionSource<IDisposable> Completion;
    }

    private sealed class Slot : IDisposable
    {
        private TransferSlotQueue? _owner;
        private readonly string _host;
        public Slot(TransferSlotQueue owner, string host)
        {
            _owner = owner;
            _host = host;
        }
        public void Dispose() =>
            Interlocked.Exchange(ref _owner, null)?.Exit(_host);
    }

    private readonly object _mutex = new();
    private readonly Dictionary<string, int> _hostCounts =
        new(StringComparer.OrdinalIgnoreCase);
    private readonly List<Waiter> _waiting = new();
    private long _sequence;
    private int _active;
    private int _globalMax;
    private int _perHostMax;

    public TransferSlotQueue(int maxConcurrent = 2, int maxPerHost = 2)
    {
        Configure(maxConcurrent, maxPerHost);
    }

    public int ActiveCount { get { lock (_mutex) return _active; } }
    public int WaitingCount { get { lock (_mutex) return _waiting.Count; } }
    public int MaxConcurrent { get { lock (_mutex) return _globalMax; } }
    public int MaxPerHost { get { lock (_mutex) return _perHostMax; } }

    public void Configure(int maxConcurrent, int maxPerHost)
    {
        if (maxConcurrent is < 1 or > 8 || maxPerHost is < 1 or > 8)
            throw new ArgumentOutOfRangeException(nameof(maxConcurrent),
                "จำนวนงานพร้อมกันต้องอยู่ระหว่าง 1 ถึง 8");
        lock (_mutex)
        {
            _globalMax = maxConcurrent;
            _perHostMax = maxPerHost;
            Dispatch();
        }
    }

    public async Task<IDisposable> EnterAsync(string id, string host, int priority, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        if (string.IsNullOrWhiteSpace(host))
            throw new ArgumentException("Host is required", nameof(host));
        // Treat equivalent host spellings as the same per-host capacity bucket.
        host = host.Trim();
        if (priority is < 0 or > 2)
            throw new ArgumentOutOfRangeException(nameof(priority));
        var waiter = new Waiter
        {
            Id = id, Host = host, Priority = priority,
            Sequence = Interlocked.Increment(ref _sequence),
            EnqueuedAt = Environment.TickCount64,
            Completion = new TaskCompletionSource<IDisposable>(
                TaskCreationOptions.RunContinuationsAsynchronously)
        };
        lock (_mutex)
        {
            _waiting.Add(waiter);
            Dispatch();
        }
        using var registration = token.Register(() => Cancel(waiter, token));
        var lease = await waiter.Completion.Task.ConfigureAwait(false);
        if (token.IsCancellationRequested)
        {
            lease.Dispose();
            token.ThrowIfCancellationRequested();
        }
        return lease;
    }

    public void Reprioritize(string id, int priority)
    {
        if (priority is < 0 or > 2)
            throw new ArgumentOutOfRangeException(nameof(priority));
        lock (_mutex)
        {
            foreach (var waiter in _waiting.Where(w => w.Id == id))
                waiter.Priority = priority;
            Dispatch();
        }
    }

    private void Cancel(Waiter waiter, CancellationToken token)
    {
        lock (_mutex)
        {
            if (_waiting.Remove(waiter))
            {
                waiter.Completion.TrySetCanceled(token);
                Dispatch();
            }
        }
    }

    private void Dispatch()
    {
        while (_active < _globalMax && _waiting.Count > 0)
        {
            var now = Environment.TickCount64;
            var next = _waiting
                .Where(w => !_hostCounts.TryGetValue(w.Host, out var running) ||
                            running < _perHostMax)
                .OrderBy(w => Math.Max(0, w.Priority -
                    (int)Math.Min(2, (now - w.EnqueuedAt) / 20_000)))
                .ThenBy(w => w.Sequence)
                .FirstOrDefault();
            if (next is null) return;
            _waiting.Remove(next);
            _active++;
            _hostCounts[next.Host] =
                (_hostCounts.TryGetValue(next.Host, out var count) ? count : 0) + 1;
            if (!next.Completion.TrySetResult(new Slot(this, next.Host)))
            {
                _active--;
                _hostCounts[next.Host]--;
            }
        }
    }

    private void Exit(string host)
    {
        lock (_mutex)
        {
            _active--;
            if (_hostCounts.TryGetValue(host, out var running))
            {
                if (running == 1) _hostCounts.Remove(host);
                else _hostCounts[host] = running - 1;
            }
            Dispatch();
        }
    }
}

/// <summary>
/// Smooth global/per-job HTTP receive bandwidth cap. Permit acquisition
/// occurs before a socket read to avoid downloading unbounded data into RAM.
/// A zero limit means unlimited. Always use tiny 8 KiB reads when limited.
/// </summary>
public sealed class TransferRateGate
{
    private readonly object _mutex = new();
    private double _nextDueMs;
    private int _limitKib;
    private long _configurationVersion;
    public int LimitKibPerSecond => Volatile.Read(ref _limitKib);

    public TransferRateGate(int limitKib = 0) => Configure(limitKib);

    public void Configure(int limitKib)
    {
        if (limitKib != 0 && limitKib is < 64 or > 1_048_576)
            throw new ArgumentOutOfRangeException(nameof(limitKib),
                "ความเร็วต้องเป็น 0 (ไม่จำกัด) หรือ 64–1048576 KiB/s");
        lock (_mutex)
        {
            _nextDueMs = Environment.TickCount64;
            _configurationVersion++;
            Volatile.Write(ref _limitKib, limitKib);
        }
    }

    public Task WaitForBytesAsync(int bytes, CancellationToken cancellation)
    {
        cancellation.ThrowIfCancellationRequested();
        if (bytes <= 0 || LimitKibPerSecond == 0)
            return Task.CompletedTask;
        double delay;
        double reservedUntil;
        double reservedFrom;
        long version;
        lock (_mutex)
        {
            var limit = _limitKib;
            if (limit == 0) return Task.CompletedTask;
            var now = Environment.TickCount64;
            reservedFrom = Math.Max(now, _nextDueMs);
            _nextDueMs = reservedFrom + bytes * 1000.0 / (limit * 1024.0);
            reservedUntil = _nextDueMs;
            version = _configurationVersion;
            delay = Math.Max(0, reservedUntil - now);
        }
        return WaitReservedAsync(delay, reservedFrom, reservedUntil, version, cancellation);
    }

    private async Task WaitReservedAsync(double delay, double reservedFrom, double reservedUntil, long version, CancellationToken cancellation)
    {
        try
        {
            await Task.Delay(TimeSpan.FromMilliseconds(delay), cancellation).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (cancellation.IsCancellationRequested)
        {
            // Refund only the last reservation. Earlier reservations cannot be
            // refunded safely because later readers may already be queued.
            lock (_mutex)
            {
                if (_configurationVersion == version && _nextDueMs == reservedUntil)
                    _nextDueMs = Math.Max(Environment.TickCount64, reservedFrom);
            }
            throw;
        }
    }
}

/// <summary>
/// Apply independent global and per-file bandwidth budgets to the same bytes.
/// Reserve both budgets together: serial waits incorrectly halve throughput
/// when the two configured caps are equal. Cancellation propagates to both
/// reservations and never bypasses either budget.
/// </summary>
public static class TransferRateLimiter
{
    public static Task WaitAsync(TransferRateGate global, TransferRateGate? file,
        int bytes, CancellationToken cancellation)
    {
        cancellation.ThrowIfCancellationRequested();
        if (bytes <= 0) return Task.CompletedTask;
        var globalWait = global.WaitForBytesAsync(bytes, cancellation);
        if (file is null || file.LimitKibPerSecond == 0) return globalWait;
        var fileWait = file.WaitForBytesAsync(bytes, cancellation);
        return Task.WhenAll(globalWait, fileWait);
    }
}

public static class TransferRateMath
{
    public static double Smooth(double previous, double measured, bool activelyDownloading)
    {
        if (!activelyDownloading) return 0;
        if (!double.IsFinite(measured) || measured < 0) measured = 0;
        if (!double.IsFinite(previous) || previous <= 0) return measured;
        var smoothed = previous * 0.72 + measured * 0.28;
        // Corrupted or extreme telemetry must never poison ETA/UI state.
        return double.IsFinite(smoothed) ? Math.Max(0, smoothed) : measured;
    }
}

/// <summary>
/// Overflow-safe byte boundaries for very large ranged downloads. The final
/// segment ends at size - 1 and every byte belongs to exactly one segment.
/// </summary>
public static class TransferSegmentGeometry
{
    public static long Boundary(long size, int index, int count)
    {
        if (size < 0) throw new ArgumentOutOfRangeException(nameof(size));
        if (count < 1 || index < 0 || index > count)
            throw new ArgumentOutOfRangeException(nameof(index));
        // Avoid size * index, which overflows long for multi-terabyte files.
        return (size / count) * index + (size % count) * index / count;
    }
}

/// <summary>
/// Conservative segment recommendation for a *new* HTTP transfer only.
/// Never repartition existing partial files: their persisted byte boundaries
/// must remain stable across resume, even when throughput changes.
/// </summary>
public static class AdaptiveSegmentPlanner
{
    public static int Recommend(int requestedParts, long contentLength,
        double measuredBytesPerSecond, bool hasPersistedSegments)
    {
        if (!DownloadEngine.AllowedParts.Contains(requestedParts))
            throw new ArgumentOutOfRangeException(nameof(requestedParts));
        if (hasPersistedSegments || contentLength <= 0 ||
            !double.IsFinite(measuredBytesPerSecond) || measuredBytesPerSecond <= 0)
            return requestedParts;
        // At least 1 MiB per range; avoid excess requests on small objects.
        var sizeCap = contentLength < 2L * 1024 * 1024 ? 1 :
            contentLength < 8L * 1024 * 1024 ? 2 :
            contentLength < 32L * 1024 * 1024 ? 4 :
            contentLength < 128L * 1024 * 1024 ? 8 :
            contentLength < 512L * 1024 * 1024 ? 16 : 32;
        // Do not increase parallelism on slow links.
        var speedCap = measuredBytesPerSecond < 256 * 1024 ? 1 :
            measuredBytesPerSecond < 1024 * 1024 ? 2 :
            measuredBytesPerSecond < 4 * 1024 * 1024 ? 4 :
            measuredBytesPerSecond < 12 * 1024 * 1024 ? 8 :
            measuredBytesPerSecond < 32 * 1024 * 1024 ? 16 : 32;
        return Math.Min(requestedParts, Math.Min(sizeCap, speedCap));
    }
}
