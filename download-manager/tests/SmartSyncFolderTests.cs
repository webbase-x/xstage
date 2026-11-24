using XStageDownloadManager;

internal static class SmartSyncFolderTests
{
    private sealed class InlineProgress(System.Collections.Concurrent.ConcurrentBag<int> values) : IProgress<int>
    {
        public void Report(int value) => values.Add(value);
    }

    private sealed class ScanProgress(List<SmartSyncScanProgress> values) : IProgress<SmartSyncScanProgress>
    {
        public void Report(SmartSyncScanProgress value) => values.Add(value);
    }

    public static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "xstage-sync-test-" + Guid.NewGuid().ToString("N"));
        var pc = Path.Combine(root, "pc"); var drive = Path.Combine(root, "drive");
        Directory.CreateDirectory(pc); Directory.CreateDirectory(drive);
        try
        {
            Directory.CreateDirectory(Path.Combine(pc, "nested"));
            File.WriteAllText(Path.Combine(pc, "nested", "new.txt"), "new PC");
            File.WriteAllText(Path.Combine(drive, "remote.txt"), "new Drive");
            File.WriteAllText(Path.Combine(pc, "conflict.txt"), "pc");
            File.WriteAllText(Path.Combine(drive, "conflict.txt"), "drive");
            File.WriteAllText(Path.Combine(pc, "same.txt"), "identical");
            File.WriteAllText(Path.Combine(drive, "same.txt"), "identical");
            File.WriteAllText(Path.Combine(pc, "songs.sqlite3"), "not copied");
            var scanEvents = new List<SmartSyncScanProgress>();
            var plan = SmartSyncFolders.Scan(pc, drive, SmartSyncDirection.Both, default, new ScanProgress(scanEvents));
            var final = scanEvents.Last();
            if (scanEvents.First().Phase != "ตรวจสอบโฟลเดอร์" ||
                !scanEvents.Any(x => x.Phase == "PC" && x.RelativePath == "nested/new.txt") ||
                !scanEvents.Any(x => x.Phase == "Google Drive" && x.RelativePath == "remote.txt") ||
                final.Phase != "ตรวจสอบเสร็จ" || final.PcFiles != 3 || final.DriveFiles != 3 ||
                final.Review != 1 || final.BytesHashed <= 0 ||
                scanEvents.Zip(scanEvents.Skip(1)).Any(x => x.First.BytesHashed > x.Second.BytesHashed))
                throw new Exception("Smart Sync scan telemetry is missing or incorrect.");
            using (var cancelled = new CancellationTokenSource())
            {
                cancelled.Cancel();
                try { SmartSyncFolders.Scan(pc, drive, SmartSyncDirection.Both, cancelled.Token); throw new Exception("Cancelled scan accepted"); }
                catch (OperationCanceledException) { }
            }
            var result = await SmartSyncFolders.ExecuteAsync(plan, 4, null, default);
            if (result.Copied != 2 || result.Identical != 1 || result.Review != 2 ||
                File.ReadAllText(Path.Combine(drive, "nested", "new.txt")) != "new PC" ||
                File.ReadAllText(Path.Combine(pc, "remote.txt")) != "new Drive" ||
                File.ReadAllText(Path.Combine(drive, "conflict.txt")) != "drive" ||
                File.Exists(Path.Combine(drive, "songs.sqlite3")))
                throw new Exception($"Smart Sync new-only mirror or conflict guard failed: copied={result.Copied}, identical={result.Identical}, review={result.Review}");
            var second = await SmartSyncFolders.ExecuteAsync(
                SmartSyncFolders.Scan(pc, drive, SmartSyncDirection.Both, default), 4, null, default);
            if (second.Copied != 0 || second.Identical != 3)
                throw new Exception("Smart Sync repeated pass must not copy identical files");
            File.WriteAllText(Path.Combine(pc, "upload.txt"), "upload");
            File.WriteAllText(Path.Combine(drive, "stay.txt"), "not downloaded");
            var upload = await SmartSyncFolders.ExecuteAsync(
                SmartSyncFolders.Scan(pc, drive, SmartSyncDirection.ToDrive, default), 2, null, default);
            if (upload.Copied != 1 || upload.SkippedDirection != 1 || File.Exists(Path.Combine(pc, "stay.txt")))
                throw new Exception("Smart Sync direction ignored");
            var observed = new System.Collections.Concurrent.ConcurrentBag<int>();
            File.WriteAllText(Path.Combine(drive, "progress.txt"), "progress");
            var withProgress = await SmartSyncFolders.ExecuteAsync(
                SmartSyncFolders.Scan(pc, drive, SmartSyncDirection.ToPc, default), 2,
                new InlineProgress(observed), default);
            if (withProgress.Copied != 2 || !observed.OrderBy(x => x).SequenceEqual(new[] { 1, 2 }))
                throw new Exception("Copy count must be independent of optional progress observer");
            File.WriteAllText(Path.Combine(pc, "race.txt"), "original");
            var stale = SmartSyncFolders.Scan(pc, drive, SmartSyncDirection.ToDrive, default);
            File.WriteAllText(Path.Combine(drive, "race.txt"), "new destination");
            try { await SmartSyncFolders.ExecuteAsync(stale, 1, null, default); throw new Exception("Overwriting destination was accepted"); }
            catch (IOException) { }
            if (File.ReadAllText(Path.Combine(drive, "race.txt")) != "new destination")
                throw new Exception("Concurrent destination was overwritten");
            try { SmartSyncFolders.Scan(pc, Path.Combine(pc, "nested"), SmartSyncDirection.Both, default); throw new Exception("Nested roots accepted"); }
            catch (InvalidDataException) { }
            Console.WriteLine("PASS: mirrored-folder Smart Sync copies only new files, verifies SHA-256, skips duplicates/conflicts/SQLite and rejects overlap");
        }
        finally { Directory.Delete(root, true); }
    }
}
