using System.Text.Json;
using Microsoft.Data.Sqlite;

namespace XStageDownloadManager;

/// <summary>
/// Durable SQLite state store (WAL + FULL synchronous). The legacy JSON is
/// read exactly once; it remains as a read-only migration backup. Each
/// checkpoint replaces jobs and chunk offsets in ONE transaction so a power
/// loss cannot leave a half-written job table.
/// </summary>
public sealed class DownloadStateStore
{
    private readonly string _directory;
    private readonly string _database;
    private readonly object _gate = new();
    private static readonly JsonSerializerOptions Json = new()
    {
        IncludeFields = true,
        WriteIndented = false
    };

    public string DatabasePath => _database;

    public DownloadStateStore(string directory)
    {
        _directory = Path.GetFullPath(directory);
        Directory.CreateDirectory(_directory);
        _database = Path.Combine(_directory, "xstage_downloads.sqlite3");
        lock (_gate)
        {
            using var db = Open();
            using var statement = db.CreateCommand();
            statement.CommandText = """
                CREATE TABLE IF NOT EXISTS xstage_download_jobs (
                    id TEXT PRIMARY KEY,
                    sort_position INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    url TEXT NOT NULL,
                    target_folder TEXT NOT NULL,
                    total_bytes INTEGER NOT NULL,
                    downloaded_bytes INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_utc TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_xstage_jobs_position
                  ON xstage_download_jobs(sort_position);
                CREATE TABLE IF NOT EXISTS xstage_download_chunks (
                    job_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    from_byte INTEGER NOT NULL,
                    to_byte INTEGER NOT NULL,
                    downloaded_bytes INTEGER NOT NULL CHECK(downloaded_bytes >= 0),
                    updated_utc TEXT NOT NULL,
                    PRIMARY KEY(job_id, chunk_index),
                    FOREIGN KEY(job_id) REFERENCES xstage_download_jobs(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS xstage_download_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                PRAGMA user_version=1;
                """;
            statement.ExecuteNonQuery();
        }
    }

    private SqliteConnection Open()
    {
        var connection = new SqliteConnection(new SqliteConnectionStringBuilder
        {
            DataSource = _database,
            Mode = SqliteOpenMode.ReadWriteCreate,
            Cache = SqliteCacheMode.Shared,
            Pooling = true,
            DefaultTimeout = 10
        }.ToString());
        connection.Open();
        using var setup = connection.CreateCommand();
        setup.CommandText = """
            PRAGMA busy_timeout=10000;
            PRAGMA foreign_keys=ON;
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            PRAGMA wal_autocheckpoint=128;
            """;
        setup.ExecuteNonQuery();
        return connection;
    }

    public List<DownloadJob> LoadOrMigrate(string legacyJsonPath)
    {
        lock (_gate)
        {
            using var db = Open();
            using var marker = db.CreateCommand();
            marker.CommandText =
                "SELECT value FROM xstage_download_settings WHERE key='legacy_migration_complete';";
            var migrated = marker.ExecuteScalar() is not null;
            if (!migrated)
            {
                List<DownloadJob> older = new();
                if (File.Exists(legacyJsonPath))
                {
                    try
                    {
                        older = JsonSerializer.Deserialize<List<DownloadJob>>(
                            File.ReadAllText(legacyJsonPath), Json) ?? new();
                    }
                    catch (Exception ex) when (ex is JsonException or IOException)
                    {
                        // Do not silently turn a corrupt user's history into an
                        // empty database. The source JSON is never modified.
                        throw new IOException(
                            "ย้ายประวัติเดิมไป SQLite ไม่สำเร็จ เก็บ downloads.json เดิมไว้แล้ว: " +
                            ex.Message, ex);
                    }
                }
                using var tx = db.BeginTransaction();
                using (var existing = db.CreateCommand())
                {
                    existing.Transaction = tx;
                    existing.CommandText = "SELECT COUNT(*) FROM xstage_download_jobs";
                    if (Convert.ToInt64(existing.ExecuteScalar()) == 0L)
                        InsertSnapshot(db, tx, older);
                }
                using (var complete = db.CreateCommand())
                {
                    complete.Transaction = tx;
                    complete.CommandText = """
                        INSERT INTO xstage_download_settings(key,value)
                        VALUES('legacy_migration_complete','1')
                        ON CONFLICT(key) DO UPDATE SET value='1'
                        """;
                    complete.ExecuteNonQuery();
                }
                tx.Commit();
            }
            var jobs = new List<DownloadJob>();
            using var load = db.CreateCommand();
            load.CommandText = """
                SELECT payload_json FROM xstage_download_jobs
                ORDER BY sort_position ASC
                """;
            using var reader = load.ExecuteReader();
            while (reader.Read())
            {
                var job = JsonSerializer.Deserialize<DownloadJob>(reader.GetString(0), Json);
                if (job is null || string.IsNullOrWhiteSpace(job.Id))
                    throw new InvalidDataException(
                        "พบข้อมูลรายการดาวน์โหลดใน SQLite ไม่สมบูรณ์ ไม่ลบประวัติเดิม");
                jobs.Add(job);
            }
            return jobs;
        }
    }

    public void SaveSnapshot(IReadOnlyList<DownloadJob> jobs)
    {
        lock (_gate)
        {
            using var db = Open();
            using var tx = db.BeginTransaction();
            InsertSnapshot(db, tx, jobs);
            tx.Commit();
        }
    }

    private static void InsertSnapshot(
        SqliteConnection db, SqliteTransaction tx, IReadOnlyList<DownloadJob> jobs)
    {
        // Existing rows remain recoverable if any statement fails: the whole
        // transaction is rolled back, including old segment checkpoints.
        using (var clean = db.CreateCommand())
        {
            clean.Transaction = tx;
            clean.CommandText = "DELETE FROM xstage_download_chunks; DELETE FROM xstage_download_jobs;";
            clean.ExecuteNonQuery();
        }
        using var insert = db.CreateCommand();
        insert.Transaction = tx;
        insert.CommandText = """
            INSERT INTO xstage_download_jobs
                (id,sort_position,kind,status,url,target_folder,total_bytes,downloaded_bytes,payload_json,updated_utc)
            VALUES($id,$position,$kind,$status,$url,$folder,$total,$downloaded,$json,$updated)
            """;
        var id = insert.Parameters.Add("$id", SqliteType.Text);
        var position = insert.Parameters.Add("$position", SqliteType.Integer);
        var kind = insert.Parameters.Add("$kind", SqliteType.Text);
        var status = insert.Parameters.Add("$status", SqliteType.Text);
        var url = insert.Parameters.Add("$url", SqliteType.Text);
        var folder = insert.Parameters.Add("$folder", SqliteType.Text);
        var total = insert.Parameters.Add("$total", SqliteType.Integer);
        var downloaded = insert.Parameters.Add("$downloaded", SqliteType.Integer);
        var json = insert.Parameters.Add("$json", SqliteType.Text);
        var updated = insert.Parameters.Add("$updated", SqliteType.Text);

        using var chunk = db.CreateCommand();
        chunk.Transaction = tx;
        chunk.CommandText = """
            INSERT INTO xstage_download_chunks
                (job_id,chunk_index,from_byte,to_byte,downloaded_bytes,updated_utc)
            VALUES($job,$index,$from,$to,$bytes,$updated)
            """;
        var chunkJob = chunk.Parameters.Add("$job", SqliteType.Text);
        var chunkIndex = chunk.Parameters.Add("$index", SqliteType.Integer);
        var from = chunk.Parameters.Add("$from", SqliteType.Integer);
        var to = chunk.Parameters.Add("$to", SqliteType.Integer);
        var chunkBytes = chunk.Parameters.Add("$bytes", SqliteType.Integer);
        var chunkUpdated = chunk.Parameters.Add("$updated", SqliteType.Text);
        var now = DateTimeOffset.UtcNow.ToString("O");
        for (var i = 0; i < jobs.Count; i++)
        {
            var job = jobs[i];
            if (string.IsNullOrWhiteSpace(job.Id)) throw new InvalidDataException("Job ID is empty");
            id.Value = job.Id;
            position.Value = i;
            kind.Value = job.Kind;
            status.Value = job.Status;
            url.Value = job.Url;
            folder.Value = job.Folder;
            total.Value = job.TotalBytes;
            downloaded.Value = Interlocked.Read(ref job.DownloadedBytes);
            json.Value = JsonSerializer.Serialize(job, Json);
            updated.Value = now;
            insert.ExecuteNonQuery();

            if (job.Kind != "File" || !job.SupportsRanges ||
                job.TotalBytes <= 0 || job.SegmentsUsed is < 1 or > 32)
                continue;
            var baseDir = Path.Combine(job.Folder, ".xstage-downloads", job.Id);
            var count = job.SegmentsUsed;
            for (var index = 0; index < count; index++)
            {
                var startByte = job.TotalBytes * index / count;
                var endByte = job.TotalBytes * (index + 1) / count - 1;
                var max = endByte - startByte + 1;
                var part = Path.Combine(baseDir, index.ToString("D2") + ".part");
                var actual = File.Exists(part) ? new FileInfo(part).Length :
                    job.SegmentDownloadedBytes.Length > index
                        ? Interlocked.Read(ref job.SegmentDownloadedBytes[index]) : 0;
                // Physical .part bytes are authoritative for resume, not
                // potentially stale UI snapshots stored in SQLite.
                actual = Math.Clamp(actual, 0, max);
                chunkJob.Value = job.Id;
                chunkIndex.Value = index;
                from.Value = startByte;
                to.Value = endByte;
                chunkBytes.Value = actual;
                chunkUpdated.Value = now;
                chunk.ExecuteNonQuery();
            }
        }
    }

    public int ReadDefaultParts(int fallback)
    {
        lock (_gate)
        {
            using var db = Open();
            using var cmd = db.CreateCommand();
            cmd.CommandText =
                "SELECT value FROM xstage_download_settings WHERE key='default_parts';";
            var raw = cmd.ExecuteScalar()?.ToString();
            return int.TryParse(raw, out var parts) &&
                DownloadEngine.AllowedParts.Contains(parts) ? parts : fallback;
        }
    }

    public void SaveDefaultParts(int parts)
    {
        if (!DownloadEngine.AllowedParts.Contains(parts))
            throw new ArgumentOutOfRangeException(nameof(parts));
        lock (_gate)
        {
            using var db = Open();
            using var cmd = db.CreateCommand();
            cmd.CommandText = """
                INSERT INTO xstage_download_settings(key,value)
                VALUES('default_parts',$value)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """;
            cmd.Parameters.AddWithValue("$value", parts.ToString());
            cmd.ExecuteNonQuery();
        }
    }

    public int ReadRetryLimit(int fallback = DownloadRetryPolicy.DefaultAttempts)
    {
        lock (_gate)
        {
            using var db = Open();
            using var cmd = db.CreateCommand();
            cmd.CommandText =
                "SELECT value FROM xstage_download_settings WHERE key='retry_limit';";
            var text = cmd.ExecuteScalar()?.ToString();
            return int.TryParse(text, out var count) &&
                count >= DownloadRetryPolicy.MinAttempts &&
                count <= DownloadRetryPolicy.MaxAttempts ? count : fallback;
        }
    }

    public void SaveRetryLimit(int limit)
    {
        if (limit < DownloadRetryPolicy.MinAttempts ||
            limit > DownloadRetryPolicy.MaxAttempts)
            throw new ArgumentOutOfRangeException(nameof(limit));
        lock (_gate)
        {
            using var db = Open();
            using var cmd = db.CreateCommand();
            cmd.CommandText = """
                INSERT INTO xstage_download_settings(key,value)
                VALUES('retry_limit',$limit)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """;
            cmd.Parameters.AddWithValue("$limit", limit.ToString());
            cmd.ExecuteNonQuery();
        }
    }

    // Only validated numeric performance settings reach the orchestrator.
    public int ReadPerformanceSetting(string key, int fallback, int min, int max)
    {
        if (!new[] { "global_jobs", "host_jobs", "global_limit_kib" }.Contains(key))
            throw new ArgumentException("Unknown performance setting", nameof(key));
        lock (_gate)
        {
            using var db = Open();
            using var cmd = db.CreateCommand();
            cmd.CommandText =
                "SELECT value FROM xstage_download_settings WHERE key=$key";
            cmd.Parameters.AddWithValue("$key", key);
            var value = cmd.ExecuteScalar()?.ToString();
            return int.TryParse(value, out var result) && result >= min && result <= max
                ? result : fallback;
        }
    }

    public void SavePerformanceSetting(string key, int value, int min, int max)
    {
        if (!new[] { "global_jobs", "host_jobs", "global_limit_kib" }.Contains(key))
            throw new ArgumentException("Unknown performance setting", nameof(key));
        if (value < min || value > max)
            throw new ArgumentOutOfRangeException(nameof(value));
        lock (_gate)
        {
            using var db = Open();
            using var cmd = db.CreateCommand();
            cmd.CommandText = """
                INSERT INTO xstage_download_settings(key,value)
                VALUES($key,$value)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value;
                """;
            cmd.Parameters.AddWithValue("$key", key);
            cmd.Parameters.AddWithValue("$value", value.ToString());
            cmd.ExecuteNonQuery();
        }
    }

    public (string Mode, long Jobs, long Chunks) Inspect()
    {
        lock (_gate)
        {
            using var db = Open();
            using var cmd = db.CreateCommand();
            cmd.CommandText = """
                SELECT
                  (SELECT COUNT(*) FROM xstage_download_jobs),
                  (SELECT COUNT(*) FROM xstage_download_chunks),
                  (SELECT journal_mode FROM pragma_journal_mode)
                """;
            using var reader = cmd.ExecuteReader();
            reader.Read();
            return (reader.GetString(2), reader.GetInt64(0), reader.GetInt64(1));
        }
    }
}
