using XStageDownloadManager;

internal static class SmartSyncBackgroundTests
{
    public static async Task RunAsync()
    {
        foreach (var mode in Enum.GetValues<SmartSyncStartupMode>())
        foreach (var interrupted in new[] { false, true })
        foreach (var paused in new[] { false, true })
        foreach (var review in new[] { false, true })
        foreach (var confirmed in new[] { false, true })
        {
            var expected = interrupted && !paused && !review &&
                (mode == SmartSyncStartupMode.Automatic || (mode == SmartSyncStartupMode.Ask && confirmed));
            if (SmartSyncStartupPolicy.ShouldResume(mode, interrupted, paused, review, confirmed) != expected)
                throw new Exception("Smart Sync startup consent policy regressed");
        }
        var stateFolder = Path.Combine(Path.GetTempPath(), "xstage-sync-settings-" + Guid.NewGuid().ToString("N"));
        try
        {
            var store = new DownloadStateStore(stateFolder);
            if (store.ReadSmartSyncStartupMode() != SmartSyncStartupMode.Manual)
                throw new Exception("Smart Sync must be opt-in");
            foreach (var mode in Enum.GetValues<SmartSyncStartupMode>())
            {
                store.SaveSmartSyncStartupMode(mode);
                if (new DownloadStateStore(stateFolder).ReadSmartSyncStartupMode() != mode)
                    throw new Exception("Smart Sync preference not restored");
            }
            try
            {
                store.SaveSmartSyncStartupMode((SmartSyncStartupMode)99);
                throw new Exception("Invalid Smart Sync setting accepted");
            }
            catch (ArgumentOutOfRangeException) { }
            if (store.ReadSmartSyncStartupMode() != SmartSyncStartupMode.Automatic)
                throw new Exception("Invalid setting mutated persisted preference");
        }
        finally
        {
            Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
            Directory.Delete(stateFolder, true);
        }
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
