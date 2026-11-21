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
            Volatile.Write(ref _limitKib, limitKib);
        }
    }

    public Task WaitForBytesAsync(int bytes, CancellationToken cancellation)
    {
        if (bytes <= 0 || LimitKibPerSecond == 0)
            return Task.CompletedTask;
        double delay;
        lock (_mutex)
        {
            var limit = _limitKib;
            if (limit == 0) return Task.CompletedTask;
            var now = Environment.TickCount64;
            var start = Math.Max(now, _nextDueMs);
            _nextDueMs = start + bytes * 1000.0 / (limit * 1024.0);
            delay = Math.Max(0, _nextDueMs - now);
        }
        return WaitReservedAsync(delay, _nextDueMs, cancellation);
    }

    private async Task WaitReservedAsync(double delay, double reservedUntil, CancellationToken cancellation)
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
                if (_nextDueMs == reservedUntil)
                    _nextDueMs = Environment.TickCount64;
            }
            throw;
        }
    }
}

public static class TransferRateMath
{
    public static double Smooth(double previous, double measured, bool activelyDownloading)
    {
        if (!activelyDownloading) return 0;
        if (!double.IsFinite(measured) || measured < 0) measured = 0;
        if (previous <= 0) return measured;
        return Math.Max(0, previous * 0.72 + measured * 0.28);
    }
}
