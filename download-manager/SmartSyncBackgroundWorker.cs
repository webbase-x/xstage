namespace XStageDownloadManager;

// The UI owns one worker per sync pair. The provider must checkpoint verified
// transfers itself and honor cancellation. No UI context or overlapping passes.
public sealed class SmartSyncBackgroundWorker : IAsyncDisposable
{
    private readonly object _gate = new();
    private readonly Func<CancellationToken, Task> _syncPass;
    private readonly TimeSpan _interval;
    private CancellationTokenSource? _stop;
    private Task? _loop;
    private bool _disposed;
    private int _stopping;
    private string? _lastError;
    private long _completedPasses;

    public SmartSyncBackgroundWorker(Func<CancellationToken, Task> syncPass, TimeSpan interval)
    {
        ArgumentNullException.ThrowIfNull(syncPass);
        if (interval < TimeSpan.FromSeconds(1) || interval > TimeSpan.FromDays(1))
            throw new ArgumentOutOfRangeException(nameof(interval));
        _syncPass = syncPass;
        _interval = interval;
    }

    public bool IsRunning { get { lock (_gate) return _loop is { IsCompleted: false }; } }
    public string? LastError { get { lock (_gate) return _lastError; } }
    public long CompletedPasses => Interlocked.Read(ref _completedPasses);

    public bool Start()
    {
        lock (_gate)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            if (_stopping != 0 || _loop is { IsCompleted: false }) return false;
            _stop?.Dispose();
            var source = new CancellationTokenSource();
            _stop = source;
            _lastError = null;
            _loop = Task.Run(() => RunAsync(source.Token));
            return true;
        }
    }

    private async Task RunAsync(CancellationToken token)
    {
        while (!token.IsCancellationRequested)
        {
            try
            {
                await _syncPass(token).ConfigureAwait(false);
                Interlocked.Increment(ref _completedPasses);
                lock (_gate) _lastError = null;
            }
            catch (OperationCanceledException) when (token.IsCancellationRequested) { return; }
            catch (Exception ex)
            {
                // Stop on failure: the provider might need renewed consent or
                // conflict review. Do not silently repeat a failed mutation.
                lock (_gate) _lastError = ex.GetType().Name;
                return;
            }
            try { await Task.Delay(_interval, token).ConfigureAwait(false); }
            catch (OperationCanceledException) when (token.IsCancellationRequested) { return; }
        }
    }

    public async Task StopAsync()
    {
        Task? loop;
        Task? cancel;
        lock (_gate)
        {
            _stopping++;
            loop = _loop;
            // CancelAsync sets the cancellation flag synchronously but invokes
            // callbacks asynchronously, avoiding re-entry while holding _gate.
            cancel = _stop?.CancelAsync();
        }
        try { if (cancel is not null) await cancel.ConfigureAwait(false); }
        finally
        {
            try { if (loop is not null) await loop.ConfigureAwait(false); }
            finally { lock (_gate) _stopping--; }
        }
    }

    public async ValueTask DisposeAsync()
    {
        lock (_gate) _disposed = true;
        try { await StopAsync().ConfigureAwait(false); }
        finally { lock (_gate) { _stop?.Dispose(); _stop = null; } }
    }
}
