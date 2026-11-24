using System.Text.RegularExpressions;

namespace XStageDownloadManager;

// Pure, side-effect-free plan. A provider must revalidate both versions before
// executing a transfer and checkpoint only after verified completion.
public enum SyncAction { Unchanged, DownloadNew, UploadNew, DownloadUpdate, UploadUpdate, Conflict, ReviewDeletion }
public sealed record SyncFingerprint(long Size, string Md5);
public sealed record SyncEntry(string RelativePath, SyncFingerprint Fingerprint);
public sealed record SyncDecision(string RelativePath, SyncAction Action);

public static class SmartSyncPlanner
{
    private static readonly StringComparer Paths = StringComparer.OrdinalIgnoreCase;

    private static bool ValidFingerprint(SyncFingerprint f) =>
        f.Size >= 0 && f.Md5 is not null && Regex.IsMatch(f.Md5, @"\A[0-9a-fA-F]{32}\z");

    private static bool Same(SyncFingerprint a, SyncFingerprint b) =>
        ValidFingerprint(a) && ValidFingerprint(b) && a.Size == b.Size &&
        string.Equals(a.Md5, b.Md5, StringComparison.OrdinalIgnoreCase);

    public static bool SafeRelativePath(string path)
    {
        if (string.IsNullOrWhiteSpace(path) || path.Contains('\\')) return false;
        foreach (var segment in path.Split('/'))
        {
            if (segment.Length == 0 || segment is "." or ".." ||
                segment.EndsWith('.') || segment.EndsWith(' ') ||
                segment.Any(c => c < 32 || "<>:\"|?*".Contains(c))) return false;
            var stem = segment.Split('.')[0].TrimEnd(' ');
            if (Regex.IsMatch(stem, @"\A(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])\z",
                    RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)) return false;
        }
        return true;
    }

    public static IReadOnlyList<SyncDecision> Plan(IEnumerable<SyncEntry> local,
        IEnumerable<SyncEntry> remote, IEnumerable<SyncEntry> baseline)
    {
        var l = local.ToLookup(x => x.RelativePath, Paths);
        var r = remote.ToLookup(x => x.RelativePath, Paths);
        var b = baseline.ToLookup(x => x.RelativePath, Paths);
        var keys = l.Select(g => g.Key).Concat(r.Select(g => g.Key)).Concat(b.Select(g => g.Key))
            .Distinct(Paths).OrderBy(x => x, Paths).ToArray();
        // A file at "a" cannot coexist with a file at "a/b" on Windows.
        var all = new HashSet<string>(keys, Paths);
        var collisions = new HashSet<string>(Paths);
        foreach (var path in keys)
        {
            for (var i = path.IndexOf('/'); i >= 0; i = path.IndexOf('/', i + 1))
                if (all.Contains(path[..i])) { collisions.Add(path[..i]); collisions.Add(path); }
        }
        var result = new List<SyncDecision>(keys.Length);
        foreach (var path in keys)
        {
            var ls = l[path].ToArray(); var rs = r[path].ToArray(); var bs = b[path].ToArray();
            var action = SyncAction.Conflict;
            if (SafeRelativePath(path) && !SmartSyncTransfer.IsDatabaseSidecar(path) && !collisions.Contains(path) &&
                ls.Length <= 1 && rs.Length <= 1 && bs.Length <= 1 &&
                ls.Concat(rs).Concat(bs).All(x => ValidFingerprint(x.Fingerprint)))
            {
                var lf = ls.SingleOrDefault()?.Fingerprint;
                var rf = rs.SingleOrDefault()?.Fingerprint;
                var bf = bs.SingleOrDefault()?.Fingerprint;
                if (lf is null && rf is null) action = SyncAction.Unchanged;
                else if (lf is null || rf is null)
                    action = bf is not null ? SyncAction.ReviewDeletion :
                        lf is null ? SyncAction.DownloadNew : SyncAction.UploadNew;
                else if (Same(lf, rf)) action = SyncAction.Unchanged;
                else if (bf is not null && Same(lf, bf)) action = SyncAction.DownloadUpdate;
                else if (bf is not null && Same(rf, bf)) action = SyncAction.UploadUpdate;
            }
            result.Add(new SyncDecision(path, action));
        }
        return result;
    }
}
