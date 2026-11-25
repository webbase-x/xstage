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
            // Catalog control files must never enter ordinary media sync.
            if (!SmartSyncFolders.IsCatalogControlPath("CACHE/.xstage-import-lock-a.json") ||
                !SmartSyncFolders.IsCatalogControlPath("BACKUP/songs-backup-a.sqlite3") ||
                !SmartSyncFolders.IsCatalogControlPath("DB/songs.sqlite3") ||
                SmartSyncFolders.IsCatalogControlPath("SONGS/MIDI/10001.xmid"))
                throw new Exception("Catalog control isolation failed");
            if (SmartSyncFolders.CompareCanonicalCatalogs(pc, drive, default) != "")
                throw new Exception("Missing catalogs must not be reported as synchronized");
            Directory.CreateDirectory(Path.Combine(pc,"DB"));
            File.WriteAllText(Path.Combine(pc,"DB","songs.sqlite3"),"unfinished");
            if (!SmartSyncFolders.CompareCanonicalCatalogs(pc,drive,default).Contains("ยังไม่ครบ"))
                throw new Exception("Missing peer DB must not be copied");
            Directory.Delete(Path.Combine(pc,"DB"),true);
            var preferencesFile = Path.Combine(root, "settings", "smart-sync.json");
            if (SmartSyncPreferencesStore.Load(preferencesFile) != new SmartSyncPreferences())
                throw new Exception("Missing preferences must start with safe defaults");
            // A disconnected drive must be retained without scanning or resolving it.
            var disconnected = Path.Combine(root, "disconnected-drive");
            var saved = new SmartSyncPreferences(pc, disconnected, SmartSyncDirection.ToPc, true);
            SmartSyncPreferencesStore.Save(preferencesFile, saved);
            if (SmartSyncPreferencesStore.Load(preferencesFile) != saved || Directory.Exists(disconnected))
                throw new Exception("Smart Sync preference round trip failed");
            var changed = saved with { Drive = drive, Direction = SmartSyncDirection.ToDrive, Background = false };
            SmartSyncPreferencesStore.Save(preferencesFile, changed);
            if (SmartSyncPreferencesStore.Load(preferencesFile) != changed ||
                Directory.GetFiles(Path.GetDirectoryName(preferencesFile)!).Length != 1)
                throw new Exception("Smart Sync settings replacement failed");
            try
            {
                SmartSyncPreferencesStore.Save(preferencesFile, changed with { Direction = (SmartSyncDirection)99 });
                throw new Exception("Invalid direction accepted");
            }
            catch (InvalidDataException) { }
            if (SmartSyncPreferencesStore.Load(preferencesFile) != changed)
                throw new Exception("Invalid save modified previous settings");
            File.WriteAllText(preferencesFile, "{broken");
            try { SmartSyncPreferencesStore.Load(preferencesFile); throw new Exception("Corrupt preferences accepted"); }
            catch (System.Text.Json.JsonException) { }
            Console.WriteLine("PASS: Smart Sync preferences persist across restarts and reject invalid data");
            var dupPc = Path.Combine(root, "dupPC"); var dupDrive = Path.Combine(root, "dupDrive");
            Directory.CreateDirectory(dupPc); Directory.CreateDirectory(dupDrive);
            foreach (var folder in new[] { dupPc, dupDrive })
            {
                File.WriteAllText(Path.Combine(folder, "00001.XMID"), "AAA");
                File.WriteAllText(Path.Combine(folder, "00001 (1).xmid"), "AAA");
                File.WriteAllText(Path.Combine(folder, "00001 (2).xmid"), "BBB");
                File.WriteAllText(Path.Combine(folder, "00001 (3).xmid"), "longer");
                File.WriteAllText(Path.Combine(folder, "00002 (1).xmid"), "only copy");
                File.WriteAllText(Path.Combine(folder, "00001 (1).txt"), "not a song");
            }
            var readOnly = SmartSyncFolders.Scan(dupPc, dupDrive, SmartSyncDirection.Both, default, null, SmartSyncMode.Fast);
            if (readOnly.DuplicateCleanup is not null || !File.Exists(Path.Combine(dupPc, "00001 (1).xmid")))
                throw new Exception("Default Sync must not move existing copies");
            int prompts = 0;
            var declined = SmartSyncFolders.Scan(dupPc, dupDrive, SmartSyncDirection.Both, default, null, SmartSyncMode.Fast,
                chooseDuplicateCleanup: (pcCount, driveCount) =>
                {
                    prompts++;
                    if (pcCount != 4 || driveCount != 4) throw new Exception("Candidate count incorrect");
                    return false;
                });
            if (prompts != 1 || declined.DuplicateCleanup is not null || !File.Exists(Path.Combine(dupPc, "00001 (1).xmid")))
                throw new Exception("Declining duplicate cleanup must not move anything");
            using (var stopAtPrompt = new CancellationTokenSource())
            {
                try
                {
                    SmartSyncFolders.Scan(dupPc, dupDrive, SmartSyncDirection.Both, stopAtPrompt.Token, null, SmartSyncMode.Fast,
                        chooseDuplicateCleanup: (_, _) => { stopAtPrompt.Cancel(); return true; });
                    throw new Exception("Cancellation at cleanup choice accepted");
                }
                catch (OperationCanceledException) { }
            }
            if (!File.Exists(Path.Combine(dupDrive, "00001 (1).xmid")))
                throw new Exception("Cancellation at prompt must precede moves");
            var cleaned = SmartSyncFolders.Scan(dupPc, dupDrive, SmartSyncDirection.Both, default, null, SmartSyncMode.Fast,
                chooseDuplicateCleanup: (pcCount, driveCount) => { prompts++; return pcCount == 4 && driveCount == 4; });
            if (prompts != 2) throw new Exception("Expected one cleanup choice per explicit scan");
            if (cleaned.DuplicateCleanup is not { PcArchived: 1, DriveArchived: 1, Preserved: 6 })
                throw new Exception("Duplicate quarantine counts incorrect");
            foreach (var folder in new[] { dupPc, dupDrive })
            {
                var backup = Directory.GetFiles(Path.Combine(folder, SmartSyncFolders.DuplicateBackupFolder), "*.bak", SearchOption.AllDirectories);
                if (backup.Length != 1 || File.ReadAllText(backup[0]) != "AAA" ||
                    File.Exists(Path.Combine(folder, "00001 (1).xmid")) ||
                    File.ReadAllText(Path.Combine(folder, "00001.XMID")) != "AAA" ||
                    File.ReadAllText(Path.Combine(folder, "00001 (2).xmid")) != "BBB" ||
                    !File.Exists(Path.Combine(folder, "00001 (3).xmid")) ||
                    !File.Exists(Path.Combine(folder, "00002 (1).xmid")) ||
                    !File.Exists(Path.Combine(folder, "00001 (1).txt")))
                    throw new Exception("Quarantine must keep canonical, different, unique and non-XMID files");
            }
            var again = SmartSyncFolders.Scan(dupPc, dupDrive, SmartSyncDirection.Both, default, null, SmartSyncMode.Fast,
                quarantineCopies: true);
            if (again.DuplicateCleanup is not { PcArchived: 0, DriveArchived: 0 } ||
                again.Decisions.Any(d => d.RelativePath.Contains(SmartSyncFolders.DuplicateBackupFolder)))
                throw new Exception("Quarantine must be repeat-safe and excluded from transfer");
            using (var canceledCleanup = new CancellationTokenSource())
            {
                canceledCleanup.Cancel();
                try { SmartSyncFolders.Scan(dupPc, dupDrive, SmartSyncDirection.Both, canceledCleanup.Token,
                    null, SmartSyncMode.Fast, quarantineCopies: true); throw new Exception("Canceled cleanup accepted"); }
                catch (OperationCanceledException) { }
            }
            Console.WriteLine("PASS: opt-in XMID duplicate quarantine, hash comparison, preservation, backup exclusion and repeat safety");
            var songPc = Path.Combine(root, "songPC"); var songDrive = Path.Combine(root, "songDrive");
            Directory.CreateDirectory(songPc); Directory.CreateDirectory(songDrive);
            File.WriteAllText(Path.Combine(songPc, "00001.xmid"), "A");
            File.WriteAllText(Path.Combine(songDrive, "00001 (1).xmid"), "A");
            File.WriteAllText(Path.Combine(songPc, "a00002.xmid"), "new content");
            File.WriteAllText(Path.Combine(songDrive, "a00002 (2).xmid"), "old");
            File.WriteAllText(Path.Combine(songDrive, "00003 (1).xmid"), "new song");
            File.WriteAllText(Path.Combine(songPc, "00005.xmid"), "new plain");
            var songPlan = SmartSyncFolders.Scan(songPc, songDrive, SmartSyncDirection.Both, default, null, SmartSyncMode.Fast);
            var plain = songPlan.Decisions.Single(d => d.Action == SyncAction.UploadNew && d.RelativePath == "00005.xmid");
            var renamed = songPlan.Decisions.Single(d => d.Action == SyncAction.DownloadNew && d.RelativePath == "00003.xmid");
            if (plain.Note is not null || SmartSyncPresentation.Describe(plain) != "อัปโหลดใหม่ · 00005.xmid" ||
                SmartSyncPresentation.Describe(renamed) != "ดาวน์โหลดใหม่ · 00003 (1).xmid → 00003.xmid")
                throw new Exception("Sync preview must show a path arrow only for an actual name change");
            if (SmartSyncPresentation.Describe(new SyncDecision("0/00001.xmid", SyncAction.Unchanged,
                Note: "รหัส/ขนาดตรงกัน · ข้าม")) != "ข้าม · 0/00001.xmid · รหัส/ขนาดตรงกัน (ยังไม่ยืนยันเนื้อหา)" ||
                !SmartSyncPresentation.Describe(new SyncDecision("00001.xmid", SyncAction.Conflict,
                    Note: "SHA-256 ต่างกัน")).StartsWith("แจ้งเตือน · ") ||
                !SmartSyncPresentation.Describe(new SyncDecision("00001.xmid", SyncAction.UploadUpdate,
                    Note: "ทับพร้อมสำรอง")).StartsWith("เขียนทับ (PC → Drive) · ") ||
                !SmartSyncPresentation.Describe(new SyncDecision("00001_hash.xmid", SyncAction.UploadNew,
                    "00001.xmid", Note: "เก็บทั้งสองฉบับ")).StartsWith("เก็บทั้งสองฉบับ (PC → Drive) · "))
                throw new Exception("Sync preview action labels regressed");
            if (!songPlan.Decisions.Any(d => d.Action == SyncAction.Conflict && d.Note!.Contains("SHA-256")) ||
                songPlan.Decisions.Any(d => d.Action == SyncAction.DownloadNew && d.RelativePath.Contains("00001")) ||
                !songPlan.Decisions.Any(d => d.Action == SyncAction.DownloadNew && d.RelativePath == "00003.xmid"))
                throw new Exception("XMID alias skip/normalization or hash conflict failed");
            await SmartSyncFolders.ExecuteAsync(songPlan, 2, null, default);
            var overwrite = SmartSyncFolders.Scan(songPc, songDrive, SmartSyncDirection.Both, default, null, SmartSyncMode.Fast, XmidConflictPolicy.Overwrite);
            await SmartSyncFolders.ExecuteAsync(overwrite, 2, null, default);
            if (File.ReadAllText(Path.Combine(songDrive, "a00002 (2).xmid")) != "new content" ||
                !Directory.GetFiles(songDrive, ".xstage-sync-backup-*.bak").Any(x => File.ReadAllText(x) == "old"))
                throw new Exception("XMID replacement must preserve backup and PC priority");
            File.WriteAllText(Path.Combine(songPc, "00004.xmid"), "PC");
            File.WriteAllText(Path.Combine(songDrive, "00004.xmid"), "Drive");
            var keep = SmartSyncFolders.Scan(songPc, songDrive, SmartSyncDirection.Both, default, null, SmartSyncMode.Fast, XmidConflictPolicy.KeepHash);
            var copies = await SmartSyncFolders.ExecuteAsync(keep, 2, null, default);
            if (copies.Copied != 2 || Directory.GetFiles(songPc, "00004_*.xmid").Length != 1 ||
                Directory.GetFiles(songDrive, "00004_*.xmid").Length != 1 ||
                File.ReadAllText(Path.Combine(songPc, "00004.xmid")) != "PC" ||
                File.ReadAllText(Path.Combine(songDrive, "00004.xmid")) != "Drive")
                throw new Exception("Hash variants must preserve both originals");
            var repeat = await SmartSyncFolders.ExecuteAsync(
                SmartSyncFolders.Scan(songPc, songDrive, SmartSyncDirection.Both, default, null, SmartSyncMode.Fast, XmidConflictPolicy.KeepHash),
                2, null, default);
            if (repeat.Copied != 0) throw new Exception("Hash variants must not grow on repeated runs");
            SmartSyncPreferencesStore.Save(preferencesFile, changed with { ConflictPolicy = XmidConflictPolicy.KeepHash });
            if (SmartSyncPreferencesStore.Load(preferencesFile).ConflictPolicy != XmidConflictPolicy.KeepHash)
                throw new Exception("XMID conflict choice was not persisted");
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
            // Same size but different content is only a fast-mode skip, never verified equality.
            File.WriteAllText(Path.Combine(pc, "equal-size.txt"), "AA");
            File.WriteAllText(Path.Combine(drive, "equal-size.txt"), "BB");
            var fastEvents = new List<SmartSyncScanProgress>();
            var fast = SmartSyncFolders.Scan(pc, drive, SmartSyncDirection.Both, default, new ScanProgress(fastEvents), SmartSyncMode.Fast);
            if (fastEvents.Last().BytesHashed != 0 || fast.Decisions.Single(x => x.RelativePath == "equal-size.txt").Action != SyncAction.Unchanged ||
                fast.Decisions.Single(x => x.RelativePath == "conflict.txt").Action != SyncAction.Conflict)
                throw new Exception("Fast scan must use metadata only and never plan an overwrite");
            var smart = SmartSyncFolders.Scan(pc, drive, SmartSyncDirection.Both, default, null, SmartSyncMode.Smart);
            if (smart.Decisions.Single(x => x.RelativePath == "equal-size.txt").Action != SyncAction.Conflict)
                throw new Exception("Smart scan missed equal-size changed content");
            File.Delete(Path.Combine(pc, "equal-size.txt")); File.Delete(Path.Combine(drive, "equal-size.txt"));
            var receipt = Path.Combine(root, "receipts.sqlite3");
            var bandStart = SmartSyncScanAnimation.Band(100, 0);
            var bandEnd = SmartSyncScanAnimation.Band(100, 900);
            var bandBack = SmartSyncScanAnimation.Band(100, 1800);
            if (bandStart != (0, 25) || bandEnd != (75, 25) || bandBack != bandStart)
                throw new Exception("Scan animation must bounce within the cell");
            var emptyLanes = new SmartSyncLaneTracker();
            emptyLanes.Reset("กำลังตรวจสอบ");
            if (emptyLanes.Snapshot().Upload.Fraction != 0) throw new Exception("Scan is not complete");
            var emptyPlan = fast with { Decisions = Array.Empty<SyncDecision>() };
            emptyLanes.Plan(emptyPlan);
            emptyLanes.Start();
            emptyLanes.Finish("สำเร็จ");
            var (emptyUp, emptyDown) = emptyLanes.Snapshot();
            if (!emptyUp.IsComplete || !emptyDown.IsComplete || emptyUp.Fraction != 1 || emptyDown.Fraction != 1 ||
                emptyUp.ProgressText != "100.0%" || emptyDown.State != "ไม่มีไฟล์ใหม่")
                throw new Exception("Zero-work sync must show completed 100 percent");
            emptyLanes.Plan(emptyPlan with { Direction = SmartSyncDirection.ToDrive });
            if (emptyLanes.Snapshot().Download.IsComplete || emptyLanes.Snapshot().Download.ProgressText != "—")
                throw new Exception("Disabled direction must not be presented as completed");
            var lanes = new SmartSyncLaneTracker();
            lanes.Reset("กำลังตรวจสอบ");
            if (!lanes.Snapshot().Upload.IsScanning || !lanes.Snapshot().Download.IsScanning)
                throw new Exception("Both scan lanes must be indeterminate");
            lanes.Plan(fast);
            lanes.Start();
            var result = await SmartSyncFolders.ExecuteAsync(fast, 8, null, default, receipt, lanes.Complete);
            var (up, down) = lanes.Snapshot();
            if (up.Total != 1 || down.Total != 1 || up.Done != 1 || down.Done != 1 ||
                up.DoneBytes != up.Bytes || down.DoneBytes != down.Bytes || up.Fraction != 1 || down.Fraction != 1)
                throw new Exception("Directional progress must count verified files independently");
            using (var connection = new Microsoft.Data.Sqlite.SqliteConnection("Data Source=" + receipt + ";Pooling=False"))
            {
                connection.Open();
                using var command = connection.CreateCommand();
                command.CommandText = "SELECT count(*) FROM receipts WHERE length(sha256)=64";
                if (Convert.ToInt32(command.ExecuteScalar()) != 2)
                    throw new Exception("Completed fast transfers were not checkpointed");
            }
            if (result.Identical != 2) throw new Exception("Fast skip count incorrect");
            // Subsequent legacy tests use the count from the original plan.
            result = result with { Identical = SmartSyncFolders.Summarize(plan).Identical };
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
