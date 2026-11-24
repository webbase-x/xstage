using Microsoft.Data.Sqlite;
using XStageDownloadManager;

internal static class SmartSyncTransferTests
{
    public static async Task RunAsync()
    {
        var folder = Path.Combine(Path.GetTempPath(), "xstage-sync-transfer-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(folder);
        try
        {
            var source = Path.Combine(folder, "songs.sqlite3");
            var snapshot = Path.Combine(folder, "snapshot.sqlite3");
            using var db = new SqliteConnection(new SqliteConnectionStringBuilder
                { DataSource = source, Pooling = false }.ToString());
            db.Open();
            using var cmd = db.CreateCommand();
            cmd.CommandText = """
                PRAGMA journal_mode=WAL;
                PRAGMA user_version=7;
                CREATE TABLE songs(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
                CREATE INDEX ix_name ON songs(name);
                CREATE VIEW song_view AS SELECT name FROM songs;
                CREATE TRIGGER song_trigger AFTER INSERT ON songs BEGIN SELECT 1; END;
                INSERT INTO songs VALUES(1,'original');
                """;
            cmd.ExecuteNonQuery();
            SmartSyncTransfer.CreateDatabaseSnapshot(source, snapshot);
            using (var copy = new SqliteConnection(new SqliteConnectionStringBuilder
                { DataSource = snapshot, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString()))
            {
                copy.Open();
                using var q = copy.CreateCommand();
                q.CommandText = "SELECT name FROM song_view";
                if ((string?)q.ExecuteScalar() != "original") throw new Exception("WAL data lost");
                q.CommandText = "SELECT COUNT(*) FROM sqlite_master WHERE name IN ('songs','ix_name','song_view','song_trigger')";
                if (Convert.ToInt64(q.ExecuteScalar()) != 4) throw new Exception("SQLite schema lost");
                q.CommandText = "PRAGMA user_version";
                if (Convert.ToInt64(q.ExecuteScalar()) != 7) throw new Exception("SQLite version lost");
            }
            var before = File.ReadAllBytes(snapshot);
            try { SmartSyncTransfer.CreateDatabaseSnapshot(source, snapshot); throw new Exception("Existing DB overwritten"); }
            catch (IOException) { }
            if (!before.SequenceEqual(File.ReadAllBytes(snapshot))) throw new Exception("Existing DB changed");
            var a = new SyncFingerprint(1, new string('a',32));
            var plan = SmartSyncPlanner.Plan(Array.Empty<SyncEntry>(),
                new[] { new SyncEntry("songs.sqlite3-wal", a), new SyncEntry("songs.sqlite3-shm", a) },
                Array.Empty<SyncEntry>());
            if (plan.Any(d => d.Action != SyncAction.Conflict)) throw new Exception("Sidecar planned as independent transfer");
        }
        finally { Directory.Delete(folder, true); }

        var jobs = Enumerable.Range(0, 100).Select(i => new SyncDecision($"MIDI/{i}.mid", SyncAction.DownloadNew))
            .Append(new SyncDecision("DB/songs.sqlite3", SyncAction.UploadNew)).ToArray();
        int active = 0, max = 0, finished = 0, databases = 0;
        var gate = new object();
        await SmartSyncTransfer.ExecuteAsync(jobs, 8, async (_, ct) =>
        {
            lock (gate) { active++; max = Math.Max(max, active); }
            try { await Task.Delay(5, ct); Interlocked.Increment(ref finished); }
            finally { lock (gate) active--; }
        }, (_, ct) =>
        {
            if (finished != 100 || active != 0) throw new Exception("DB lane overlapped files");
            databases++;
            return Task.CompletedTask;
        }, CancellationToken.None);
        if (max < 2 || max > 8 || databases != 1) throw new Exception("Parallel file scheduling failed");
        Console.WriteLine("PASS: Smart Sync parallel file lane and standalone WAL-aware SQLite snapshot");
    }
}
