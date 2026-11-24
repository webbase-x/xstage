using Microsoft.Data.Sqlite;

namespace XStageDownloadManager;

// Provider-independent transfer preparation. The receiver must still verify
// revision/identity, quiesce database users and atomically publish the snapshot.
public static class SmartSyncTransfer
{
    public static bool IsDatabaseCandidate(string path) =>
        Path.GetExtension(path).ToLowerInvariant() is ".sqlite" or ".sqlite3" or ".db";

    public static bool IsDatabaseSidecar(string path)
    {
        foreach (var suffix in new[] { "-wal", "-shm", "-journal" })
            if (path.EndsWith(suffix, StringComparison.OrdinalIgnoreCase) &&
                IsDatabaseCandidate(path[..^suffix.Length])) return true;
        return false;
    }

    // Resolve a provider path without traversing junctions/symlinks. The
    // caller must still exclude concurrent filesystem changes during publish.
    public static string ResolveLocalPath(string root, string relative)
    {
        if (!SmartSyncPlanner.SafeRelativePath(relative) || IsDatabaseSidecar(relative))
            throw new InvalidDataException("Unsafe sync path");
        root = Path.GetFullPath(root);
        if (!Directory.Exists(root)) throw new DirectoryNotFoundException(root);
        for (DirectoryInfo? ancestor = new DirectoryInfo(root); ancestor != null; ancestor = ancestor.Parent)
            if ((ancestor.Attributes & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("Sync root traverses a reparse point");
        var current = root;
        var parts = relative.Split('/');
        for (int i = 0; i < parts.Length; i++)
        {
            current = Path.Combine(current, parts[i]);
            try
            {
                var attributes = File.GetAttributes(current);
                if ((attributes & FileAttributes.ReparsePoint) != 0 ||
                    (i < parts.Length - 1 && (attributes & FileAttributes.Directory) == 0) ||
                    (i == parts.Length - 1 && (attributes & FileAttributes.Directory) != 0))
                    throw new InvalidDataException("Sync path collision or reparse point");
            }
            catch (FileNotFoundException) { }
            catch (DirectoryNotFoundException) { }
        }
        return current;
    }

    private static bool IsTransfer(SyncDecision d) => d.Action is
        SyncAction.DownloadNew or SyncAction.UploadNew or
        SyncAction.DownloadUpdate or SyncAction.UploadUpdate;

    // One request per small file; bounded concurrency, no task per entire
    // library. The provider owns connection pooling, quota backoff, revision
    // preconditions, integrity and transactional per-file checkpoints.
    // Database transfers use a separate, serial lane after regular files.
    public static async Task ExecuteAsync(IEnumerable<SyncDecision> plan, int parallelFiles,
        Func<SyncDecision, CancellationToken, Task> transferFile,
        Func<SyncDecision, CancellationToken, Task> transferDatabase,
        CancellationToken token)
    {
        if (parallelFiles is < 1 or > 64) throw new ArgumentOutOfRangeException(nameof(parallelFiles));
        ArgumentNullException.ThrowIfNull(transferFile);
        ArgumentNullException.ThrowIfNull(transferDatabase);
        var work = plan.Where(IsTransfer).ToArray();
        if (work.Any(d => !SmartSyncPlanner.SafeRelativePath(d.RelativePath) ||
                          IsDatabaseSidecar(d.RelativePath)) ||
            work.Select(d => d.RelativePath).Distinct(StringComparer.OrdinalIgnoreCase).Count() != work.Length)
            throw new InvalidDataException("Unsafe or duplicate sync transfer plan");
        await Parallel.ForEachAsync(work.Where(d => !IsDatabaseCandidate(d.RelativePath)),
            new ParallelOptions { MaxDegreeOfParallelism = parallelFiles, CancellationToken = token },
            async (d, ct) => await transferFile(d, ct).ConfigureAwait(false)).ConfigureAwait(false);
        foreach (var d in work.Where(d => IsDatabaseCandidate(d.RelativePath)))
        {
            token.ThrowIfCancellationRequested();
            await transferDatabase(d, token).ConfigureAwait(false);
        }
    }

    // Never byte-copy a live SQLite main file: committed data may be in WAL.
    // Stage into an exclusively created new file; no replacement of live DB.
    public static void CreateDatabaseSnapshot(string source, string destination)
    {
        source = Path.GetFullPath(source);
        destination = Path.GetFullPath(destination);
        if (!File.Exists(source)) throw new FileNotFoundException("SQLite source not found");
        if (string.Equals(source, destination, StringComparison.OrdinalIgnoreCase))
            throw new ArgumentException("Snapshot must have a separate destination");
        using (var reservation = new FileStream(destination, FileMode.CreateNew, FileAccess.Write, FileShare.None)) { }
        try
        {
            using var input = new SqliteConnection(new SqliteConnectionStringBuilder
            { DataSource = source, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString());
            using var output = new SqliteConnection(new SqliteConnectionStringBuilder
            { DataSource = destination, Mode = SqliteOpenMode.ReadWrite, Pooling = false }.ToString());
            input.Open();
            output.Open();
            input.BackupDatabase(output);
            using var cmd = output.CreateCommand();
            cmd.CommandText = "PRAGMA journal_mode=DELETE;";
            if (!string.Equals(cmd.ExecuteScalar()?.ToString(), "delete", StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Snapshot is not standalone");
            cmd.CommandText = "PRAGMA integrity_check;";
            using var reader = cmd.ExecuteReader();
            if (!reader.Read() || reader.GetString(0) != "ok" || reader.Read())
                throw new InvalidDataException("SQLite snapshot failed integrity check");
        }
        catch
        {
            // Only our newly reserved staging file, never the source or an
            // existing destination. Leave original database untouched.
            File.Delete(destination);
            throw;
        }
    }
}
