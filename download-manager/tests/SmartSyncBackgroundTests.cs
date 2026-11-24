using XStageDownloadManager;

internal static class SmartSyncBackgroundTests
{
    public static async Task RunAsync()
    {
        var entered = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        var exited = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        int calls = 0;
        await using (var worker = new SmartSyncBackgroundWorker(async ct =>
        {
            Interlocked.Increment(ref calls);
            entered.TrySetResult(true);
            try { await Task.Delay(Timeout.InfiniteTimeSpan, ct); }
            finally { exited.TrySetResult(true); }
        }, TimeSpan.FromSeconds(1)))
        {
            if (!worker.Start()) throw new Exception("Smart Sync start rejected");
            await entered.Task.WaitAsync(TimeSpan.FromSeconds(10));
            if (worker.Start() || !worker.IsRunning) throw new Exception("Overlapping sync accepted");
            await worker.StopAsync().WaitAsync(TimeSpan.FromSeconds(10));
            if (!exited.Task.IsCompleted || worker.IsRunning || calls != 1)
                throw new Exception("Sync shutdown did not drain active pass");
            if (!worker.Start()) throw new Exception("Smart Sync restart rejected");
            await worker.StopAsync().WaitAsync(TimeSpan.FromSeconds(10));
        }
        var second = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        int passes = 0;
        await using (var worker = new SmartSyncBackgroundWorker(ct =>
        {
            if (Interlocked.Increment(ref passes) == 2) second.TrySetResult(true);
            return Task.CompletedTask;
        }, TimeSpan.FromSeconds(1)))
        {
            worker.Start();
            await second.Task.WaitAsync(TimeSpan.FromSeconds(10));
            await worker.StopAsync();
            if (worker.CompletedPasses < 2) throw new Exception("Periodic sync did not repeat");
        }
        await using (var worker = new SmartSyncBackgroundWorker(
            _ => Task.FromException(new IOException("sensitive provider URL")), TimeSpan.FromSeconds(1)))
        {
            worker.Start();
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10));
            while (worker.IsRunning) await Task.Delay(10, timeout.Token);
            if (worker.LastError != nameof(IOException) || worker.CompletedPasses != 0)
                throw new Exception("Failed sync not reported safely");
        }
        Console.WriteLine("PASS: Smart Sync background single-flight, cancellation, restart and periodic passes");
    }
}
