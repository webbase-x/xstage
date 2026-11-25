using System.Security.Cryptography;
using System.Diagnostics;
using System.Text.Json;
using Microsoft.Data.Sqlite;
using System.Text.RegularExpressions;

namespace XStageDownloadManager;

public enum SmartSyncDirection { Both, ToDrive, ToPc }
public enum SmartSyncMode { Fast, Smart, FullVerify }
public enum XmidConflictPolicy { Skip, Overwrite, KeepHash }
public sealed record SmartSyncFolderPlan(string Pc, string Drive, SmartSyncDirection Direction,
    IReadOnlyList<SyncDecision> Decisions, IReadOnlyDictionary<string, SyncFingerprint> PcFiles,
    IReadOnlyDictionary<string, SyncFingerprint> DriveFiles, int DatabaseReviewCount,
    SmartSyncMode Mode = SmartSyncMode.FullVerify, XmidConflictPolicy ConflictPolicy = XmidConflictPolicy.Skip,
    XmidDuplicateCleanup? DuplicateCleanup = null, string CatalogStatus = "");
public sealed record SmartSyncFolderResult(int Copied, int Identical, int Review, int SkippedDirection);
public sealed record XmidDuplicateCleanup(int PcArchived, int DriveArchived, int Preserved, IReadOnlyList<string> Samples);
public sealed record SmartSyncScanProgress(string Phase, string RelativePath, int PcFiles, int DriveFiles,
    long BytesHashed, int Review, int Folders, TimeSpan Elapsed);

// Phase 1: operate only on explicitly selected mirrored local folders.
// Google Drive for desktop owns account authentication and cloud transport.
// No implicit overwrite, deletion, token access, or cloud-completion claim.
public static class SmartSyncFolders
{
    private static readonly StringComparer Paths = StringComparer.OrdinalIgnoreCase;
    public const string DuplicateBackupFolder = ".xstage-sync-duplicates";

    private static string Root(string path)
    {
        if (string.IsNullOrWhiteSpace(path)) throw new ArgumentException("กรุณาเลือกโฟลเดอร์ทั้งสองฝั่ง");
        var root = Path.TrimEndingDirectorySeparator(Path.GetFullPath(path));
        // Validate root and all ancestors; reject streamed/reparse locations.
        SmartSyncTransfer.ResolveLocalPath(root, "xstage-sync-root-validation-" + Guid.NewGuid().ToString("N"));
        return root;
    }

    private static bool ContainsPath(string parent, string child)
    {
        var prefix = Path.EndsInDirectorySeparator(parent) ? parent : parent + Path.DirectorySeparatorChar;
        return Paths.Equals(parent, child) || child.StartsWith(prefix, StringComparison.OrdinalIgnoreCase);
    }

    public static (string Pc, string Drive) ValidateRoots(string pc, string drive)
    {
        pc = Root(pc); drive = Root(drive);
        if (ContainsPath(pc, drive) || ContainsPath(drive, pc))
            throw new InvalidDataException("โฟลเดอร์ทั้งสองต้องไม่ซ้อนกันหรือเป็นตำแหน่งเดียวกัน");
        return (pc, drive);
    }

    private sealed class ScanReporter(IProgress<SmartSyncScanProgress>? progress)
    {
        private readonly Stopwatch _watch = Stopwatch.StartNew();
        private int _pc, _drive, _review, _folders;
        private long _bytes;
        private readonly object _gate = new();
        public void Publish(string phase, string relative, bool pc, int files = 0, long bytes = 0,
            int review = 0, int folders = 0)
        {
            lock (_gate)
            {
                if (pc) _pc += files; else _drive += files;
                _bytes += bytes; _review += review; _folders += folders;
                progress?.Report(new SmartSyncScanProgress(phase, relative, _pc, _drive,
                    _bytes, _review, _folders, _watch.Elapsed));
            }
        }
    }

    private static (List<SyncEntry> Entries, int Review) Inventory(string root, CancellationToken ct,
        ScanReporter reporter, bool pc, SmartSyncMode mode)
    {
        var pending = new Stack<string>();
        var entries = new List<SyncEntry>();
        int review = 0;
        pending.Push(root);
        var phase = pc ? "PC" : "Google Drive";
        reporter.Publish(phase, ".", pc);
        while (pending.Count > 0)
        {
            ct.ThrowIfCancellationRequested();
            var directory = pending.Pop();
            reporter.Publish(phase, Path.GetRelativePath(root, directory), pc, folders: 1);
            if ((File.GetAttributes(directory) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("พบโฟลเดอร์ลิงก์หรือไฟล์แบบสตรีม กรุณาใช้ Drive แบบ Mirror");
            foreach (var path in Directory.EnumerateFileSystemEntries(directory))
            {
                ct.ThrowIfCancellationRequested();
                var attributes = File.GetAttributes(path);
                if ((attributes & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidDataException("พบไฟล์หรือโฟลเดอร์ลิงก์ กรุณาใช้โฟลเดอร์ Mirror ที่ดาวน์โหลดครบแล้ว");
                if ((attributes & FileAttributes.Directory) != 0)
                {
                    // Catalog control folders are not ordinary transferable media.
                    // Never mirror leases, publisher candidates, backup or logs.
                    var dirRelative = Path.GetRelativePath(root, path).Replace(Path.DirectorySeparatorChar, '/');
                    if (!IsCatalogControlPath(dirRelative) &&
                        !Paths.Equals(path, Path.Combine(root, DuplicateBackupFolder))) pending.Push(path);
                    continue;
                }
                var relative = Path.GetRelativePath(root, path).Replace(Path.DirectorySeparatorChar, '/');
                reporter.Publish(phase, relative, pc);
                if (IsCatalogControlPath(relative) || SmartSyncTransfer.IsDatabaseSidecar(relative) || SmartSyncTransfer.IsDatabaseCandidate(relative))
                { review++; reporter.Publish(phase, relative, pc, review: 1); continue; }
                // A crash may have left an unpublished staging file.
                if (Path.GetFileName(path).StartsWith(".xstage-sync-", StringComparison.OrdinalIgnoreCase))
                { review++; reporter.Publish(phase, relative, pc, review: 1); continue; }
                if (!SmartSyncPlanner.SafeRelativePath(relative))
                    throw new InvalidDataException("พบชื่อไฟล์ที่ไม่ปลอดภัยสำหรับ Windows");
                var info = new FileInfo(path);
                var fingerprint = new SyncFingerprint(info.Length, "", info.LastWriteTimeUtc.Ticks);
                if (mode == SmartSyncMode.FullVerify)
                    fingerprint = HashExisting(root, relative, fingerprint, ct);
                entries.Add(new SyncEntry(relative, fingerprint));
                reporter.Publish(phase, relative, pc, files: 1,
                    bytes: mode == SmartSyncMode.FullVerify ? fingerprint.Size : 0);
            }
        }
        return (entries, review);
    }

    public static bool IsCatalogControlPath(string relative)
    {
        var parts = relative.Split('/');
        // Do not copy root-level control trees or any publisher lock.
        return parts.Length > 0 && (new[] { "DB", "CACHE", "BACKUP", "LOGS" }
            .Contains(parts[0], StringComparer.OrdinalIgnoreCase) ||
            parts.Any(part => part.StartsWith(".xstage-import-lock-", StringComparison.OrdinalIgnoreCase) ||
                part.StartsWith(".xstage-catalog-", StringComparison.OrdinalIgnoreCase)));
    }

    // Diagnostic only: these are two LOCAL snapshots; Drive Desktop owns
    // cloud synchronization. Never select a winner or copy a live database.
    public static string CompareCanonicalCatalogs(string pc, string drive, CancellationToken ct)
    {
        const string relative = "DB/songs.sqlite3";
        var left = SmartSyncTransfer.ResolveLocalPath(pc, relative);
        var right = SmartSyncTransfer.ResolveLocalPath(drive, relative);
        if (!File.Exists(left) && !File.Exists(right)) return "";
        if (!File.Exists(left) || !File.Exists(right))
            return "ฐานร่วมยังไม่ครบสองฝั่ง · รอ Drive ซิงก์/เผยแพร่ผ่าน Karaoke Online";
        if (new[] { left, right }.Any(p => new[] { "-wal", "-shm", "-journal" }.Any(s => File.Exists(p + s))))
            return "ฐานร่วมมี SQLite journal ค้าง · ไม่เปรียบเทียบหรือส่งฐาน";
        try
        {
            (string Hash, string Generation) Read(string path)
            {
                ct.ThrowIfCancellationRequested();
                var before = new FileInfo(path);
                long size = before.Length, stamp = before.LastWriteTimeUtc.Ticks;
                string hash;
                using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
                    hash = Convert.ToHexString(SHA256.HashDataAsync(stream, ct).GetAwaiter().GetResult());
                using var db = new SqliteConnection(new SqliteConnectionStringBuilder
                { DataSource = path, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString());
                db.Open();
                using var cmd = db.CreateCommand();
                cmd.CommandText = "PRAGMA quick_check(1)";
                if (!string.Equals(cmd.ExecuteScalar()?.ToString(), "ok", StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("SQLite quick_check");
                cmd.CommandText = "SELECT value FROM catalog_meta WHERE key='format'";
                if (cmd.ExecuteScalar()?.ToString() != "xstage-sqlite3-v1")
                    throw new InvalidDataException("catalog format");
                cmd.CommandText = "SELECT value FROM catalog_meta WHERE key='generation'";
                var generation = cmd.ExecuteScalar()?.ToString() ?? "";
                var after = new FileInfo(path);
                if (after.Length != size || after.LastWriteTimeUtc.Ticks != stamp || generation.Length == 0)
                    throw new InvalidDataException("catalog changed");
                return (hash, generation);
            }
            var a = Read(left); var b = Read(right);
            return a == b ? "ฐานร่วมในเครื่องตรงกัน (SHA-256) · ยังไม่ยืนยัน Cloud"
                : "ฐานร่วมต่างรุ่นหรือ SHA-256 ต่างกัน · ไม่เขียนทับ · ตรวจการเผยแพร่/Drive ซิงก์";
        }
        catch (OperationCanceledException) { throw; }
        catch (Exception) { return "ยังยืนยันความสมบูรณ์ฐานร่วมไม่ได้ · ไม่ส่งหรือเขียนทับ"; }
    }

    private static SyncFingerprint HashExisting(string root, string relative, SyncFingerprint expected, CancellationToken ct)
    {
        var path = SmartSyncTransfer.ResolveLocalPath(root, relative);
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (stream.Length != expected.Size || File.GetLastWriteTimeUtc(path).Ticks != expected.ModifiedUtcTicks)
            throw new IOException("ไฟล์เปลี่ยนระหว่างตรวจสอบ · กรุณาตรวจใหม่");
        var md5 = Convert.ToHexString(MD5.HashDataAsync(stream, ct).GetAwaiter().GetResult());
        if (stream.Length != expected.Size || File.GetLastWriteTimeUtc(path).Ticks != expected.ModifiedUtcTicks)
            throw new IOException("ไฟล์เปลี่ยนระหว่างตรวจสอบ · กรุณาตรวจใหม่");
        return expected with { Md5 = md5 };
    }

    private static IReadOnlyDictionary<string, SyncFingerprint> Unique(IEnumerable<SyncEntry> entries) =>
        entries.GroupBy(x => x.RelativePath, Paths).Where(g => g.Count() == 1)
            .ToDictionary(g => g.Key, g => g.Single().Fingerprint, Paths);

    public static SmartSyncFolderPlan Scan(string pc, string drive, SmartSyncDirection direction, CancellationToken ct,
        IProgress<SmartSyncScanProgress>? progress = null, SmartSyncMode mode = SmartSyncMode.FullVerify,
        XmidConflictPolicy policy = XmidConflictPolicy.Skip, bool quarantineCopies = false,
        Func<int, int, bool>? chooseDuplicateCleanup = null)
    {
        if (!Enum.IsDefined(direction)) throw new ArgumentOutOfRangeException(nameof(direction));
        if (!Enum.IsDefined(mode)) throw new ArgumentOutOfRangeException(nameof(mode));
        if (!Enum.IsDefined(policy)) throw new ArgumentOutOfRangeException(nameof(policy));
        var reporter = new ScanReporter(progress);
        reporter.Publish("ตรวจสอบโฟลเดอร์", "", true);
        ct.ThrowIfCancellationRequested();
        (pc, drive) = ValidateRoots(pc, drive);
        (List<SyncEntry> Entries, int Review) l = (new(), 0), r = (new(), 0);
        Parallel.Invoke(new ParallelOptions { MaxDegreeOfParallelism = 2, CancellationToken = ct },
            () => l = Inventory(pc, ct, reporter, true, mode),
            () => r = Inventory(drive, ct, reporter, false, mode));
        XmidDuplicateCleanup? cleanup = null;
        // Ask once after inventory, before reading candidate content or moving
        // any files. Counts are candidates, not verified duplicates.
        if (chooseDuplicateCleanup is not null)
        {
            int pcCopies = l.Entries.Count(e => CopySuffix.IsMatch(Path.GetFileName(e.RelativePath)));
            int driveCopies = r.Entries.Count(e => CopySuffix.IsMatch(Path.GetFileName(e.RelativePath)));
            if (pcCopies + driveCopies > 0)
            {
                reporter.Publish("พบชื่อสำเนา · รอเลือกวิธีจัดการ", "", false);
                ct.ThrowIfCancellationRequested();
                quarantineCopies = chooseDuplicateCleanup(pcCopies, driveCopies);
                ct.ThrowIfCancellationRequested();
            }
        }
        if (quarantineCopies)
        {
            var batch = DateTime.UtcNow.ToString("yyyyMMdd-HHmmss") + "-" + Guid.NewGuid().ToString("N");
            var samples = new List<string>();
            var pcCleanup = ArchiveCopies(pc, l.Entries, true, batch, reporter, samples, ct);
            var driveCleanup = ArchiveCopies(drive, r.Entries, false, batch, reporter, samples, ct);
            cleanup = new(pcCleanup.Archived, driveCleanup.Archived, pcCleanup.Preserved + driveCleanup.Preserved, samples.AsReadOnly());
        }
        reporter.Publish("เปรียบเทียบรายการ", "", false);
        ct.ThrowIfCancellationRequested();
        // No verified historical baseline yet: differing existing files are
        // always conflicts. Identical files and new files are safe to handle.
        var decisions = SmartSyncPlanner.Plan(l.Entries.Where(e => XmidCode(e.RelativePath) is null),
            r.Entries.Where(e => XmidCode(e.RelativePath) is null), Array.Empty<SyncEntry>(), mode != SmartSyncMode.FullVerify);
        if (mode == SmartSyncMode.Smart)
        {
            // Only equal-size shared paths require content verification.
            // New files are verified during transfer; different sizes are conflicts.
            var left = Unique(l.Entries);
            var right = Unique(r.Entries);
            decisions = decisions.Select(d =>
            {
                ct.ThrowIfCancellationRequested();
                if (d.Action != SyncAction.Unchanged) return d;
                reporter.Publish("ตรวจแฮชคู่ไฟล์", d.RelativePath, true);
                var a = HashExisting(pc, d.RelativePath, left[d.RelativePath], ct);
                reporter.Publish("ตรวจแฮชคู่ไฟล์", d.RelativePath, true, bytes: a.Size);
                var b = HashExisting(drive, d.RelativePath, right[d.RelativePath], ct);
                reporter.Publish("ตรวจแฮชคู่ไฟล์", d.RelativePath, false, bytes: b.Size);
                return a.Md5 == b.Md5 ? d : d with { Action = SyncAction.Conflict };
            }).ToArray();
        }
        ct.ThrowIfCancellationRequested();
        decisions = decisions.Concat(PlanXmid(pc, drive, l.Entries, r.Entries, direction, mode, policy, reporter, ct)).ToArray();
        // Avoid duplicate output paths across all planned publications.
        var duplicate = decisions.Where(d => Allowed(d.Action, direction)).GroupBy(d => d.RelativePath, Paths)
            .Where(g => g.Count() > 1).Select(g => g.Key).ToHashSet(Paths);
        decisions = decisions.Select(d => Allowed(d.Action, direction) && duplicate.Contains(d.RelativePath)
            ? d with { Action = SyncAction.Conflict, Note = "ปลายทางซ้ำ · ตรวจสอบเอง" } : d).ToArray();
        ct.ThrowIfCancellationRequested();
        reporter.Publish("ตรวจสอบเสร็จ", "", false);
        return new SmartSyncFolderPlan(pc, drive, direction, decisions, Unique(l.Entries), Unique(r.Entries), l.Review + r.Review, mode, policy, cleanup,
            CompareCanonicalCatalogs(pc, drive, ct));
    }

    // Numeric or letter-prefixed IDs, including Google copy suffixes and our
    // full SHA-256 variant names. Never normalize non-XMID filenames.
    private static readonly Regex SongName = new(@"\A(?<id>[a-zA-Z]{0,4}[0-9]{1,16})(?:_[a-fA-F0-9]{64})?(?: ?\([0-9]+\))*\.xmid\z",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Compiled);
    public static string? XmidCode(string relative)
    {
        var match = SongName.Match(Path.GetFileName(relative));
        return match.Success ? match.Groups["id"].Value : null;
    }
    private static string InFolder(string path, string name)
    {
        int slash = path.LastIndexOf('/');
        return (slash < 0 ? "" : path[..(slash + 1)]) + name;
    }

    // Cleanup is explicitly opted in per session. Only an ordinary numbered
    // copy beside an existing canonical filename is eligible. Hash variants,
    // different bytes, and copies without a canonical file are preserved.
    private static readonly Regex CopySuffix = new(@"\A(?<id>[A-Za-z]{0,4}[0-9]{1,16})(?: ?\([0-9]+\))+\.xmid\z",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Compiled);

    private static (int Archived, int Preserved) ArchiveCopies(string root, List<SyncEntry> entries,
        bool pc, string batch, ScanReporter reporter, List<string> samples, CancellationToken ct)
    {
        int archived = 0, preserved = 0;
        var remove = new HashSet<string>(StringComparer.Ordinal);
        var byPath = entries.ToLookup(e => e.RelativePath, Paths);
        var groups = entries.Where(e => CopySuffix.IsMatch(Path.GetFileName(e.RelativePath)))
            .GroupBy(e => InFolder(e.RelativePath, CopySuffix.Match(Path.GetFileName(e.RelativePath)).Groups["id"].Value + ".xmid"), Paths);
        void Note(string text)
        {
            if (samples.Count < 200) samples.Add((pc ? "PC · " : "Drive · ") + text);
        }
        foreach (var group in groups)
        {
            ct.ThrowIfCancellationRequested();
            var originals = byPath[group.Key].ToArray();
            if (originals.Length != 1)
            {
                foreach (var copy in group)
                {
                    preserved++;
                    Note("เก็บไว้ · ไม่มีต้นฉบับที่ชัดเจน · " + copy.RelativePath);
                }
                continue;
            }
            var original = originals[0];
            var originalPath = SmartSyncTransfer.ResolveLocalPath(root, original.RelativePath);
            var candidates = group.ToArray();
            // Skip different sizes without hydrating these files. They remain
            // in the normal conflict planner, never archived by this routine.
            if (!candidates.Any(e => e.Fingerprint.Size == original.Fingerprint.Size))
            {
                foreach (var copy in candidates) { preserved++; Note("เก็บไว้ · ขนาดต่างกัน · " + copy.RelativePath); }
                continue;
            }
            using var keeper = new FileStream(originalPath, FileMode.Open, FileAccess.Read, FileShare.Read);
            Check(keeper, originalPath, original.Fingerprint);
            reporter.Publish("ตรวจ SHA-256 สำเนา", original.RelativePath, pc);
            var originalSha = SHA256.HashDataAsync(keeper, ct).GetAwaiter().GetResult();
            Check(keeper, originalPath, original.Fingerprint);
            reporter.Publish("ตรวจ SHA-256 สำเนา", original.RelativePath, pc, bytes: keeper.Length);
            foreach (var copy in candidates)
            {
                ct.ThrowIfCancellationRequested();
                if (copy.Fingerprint.Size != original.Fingerprint.Size || byPath[copy.RelativePath].Count() != 1)
                {
                    preserved++;
                    Note("เก็บไว้ · ขนาดต่างกันหรือชื่อกำกวม · " + copy.RelativePath);
                    continue;
                }
                var source = SmartSyncTransfer.ResolveLocalPath(root, copy.RelativePath);
                reporter.Publish("ตรวจ SHA-256 สำเนา", copy.RelativePath, pc);
                // Share-delete permits same-volume rename while keeping the
                // scanned bytes open and protected from ordinary writers.
                using var stream = new FileStream(source, FileMode.Open, FileAccess.Read, FileShare.Read | FileShare.Delete);
                Check(stream, source, copy.Fingerprint);
                var sha = SHA256.HashDataAsync(stream, ct).GetAwaiter().GetResult();
                Check(stream, source, copy.Fingerprint);
                reporter.Publish("ตรวจ SHA-256 สำเนา", copy.RelativePath, pc, bytes: stream.Length);
                if (!CryptographicOperations.FixedTimeEquals(originalSha, sha))
                {
                    preserved++;
                    Note("เก็บไว้ · SHA-256 ต่างกัน · " + copy.RelativePath);
                    continue;
                }
                ct.ThrowIfCancellationRequested();
                var relativeBackup = DuplicateBackupFolder + "/" + batch + "/" + copy.RelativePath + ".bak";
                var destination = SmartSyncTransfer.ResolveLocalPath(root, relativeBackup);
                Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
                SmartSyncTransfer.ResolveLocalPath(root, relativeBackup);
                SmartSyncTransfer.ResolveLocalPath(root, copy.RelativePath);
                Check(keeper, originalPath, original.Fingerprint);
                Check(stream, source, copy.Fingerprint);
                ct.ThrowIfCancellationRequested();
                // No copy+delete fallback and no overwrite. The full relative
                // original path is retained inside the batch for manual restore.
                File.Move(source, destination, overwrite: false);
                remove.Add(copy.RelativePath);
                archived++;
                Note("สำรองสำเนา SHA-256 ตรงกัน · " + copy.RelativePath + " → " + relativeBackup);
                reporter.Publish("สำรองสำเนาซ้ำ", copy.RelativePath, pc);
            }
        }
        entries.RemoveAll(e => remove.Contains(e.RelativePath));
        return (archived, preserved);

        static void Check(FileStream stream, string path, SyncFingerprint expected)
        {
            if (stream.Length != expected.Size || File.GetLastWriteTimeUtc(path).Ticks != expected.ModifiedUtcTicks)
                throw new IOException("ไฟล์เปลี่ยนระหว่างตรวจสำเนา · หยุดอย่างปลอดภัย");
        }
    }

    private static IReadOnlyList<SyncDecision> PlanXmid(string pc, string drive,
        IEnumerable<SyncEntry> left, IEnumerable<SyncEntry> right, SmartSyncDirection direction,
        SmartSyncMode mode, XmidConflictPolicy policy, ScanReporter reporter, CancellationToken ct)
    {
        var l = left.Where(e => XmidCode(e.RelativePath) is not null).ToLookup(e => XmidCode(e.RelativePath)!, Paths);
        var r = right.Where(e => XmidCode(e.RelativePath) is not null).ToLookup(e => XmidCode(e.RelativePath)!, Paths);
        var result = new List<SyncDecision>();
        var leftPaths = left.Select(e => e.RelativePath).ToHashSet(Paths);
        var rightPaths = right.Select(e => e.RelativePath).ToHashSet(Paths);
        var cache = new Dictionary<(bool, string), (SyncFingerprint Fp, string Sha)>();
        (SyncFingerprint Fp, string Sha) Verify(bool local, SyncEntry e)
        {
            var key = (local, e.RelativePath);
            if (cache.TryGetValue(key, out var found)) return found;
            ct.ThrowIfCancellationRequested();
            reporter.Publish("ตรวจแฮชรหัสเพลง", e.RelativePath, local);
            var path = SmartSyncTransfer.ResolveLocalPath(local ? pc : drive, e.RelativePath);
            using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
            var fp = e.Fingerprint;
            if (stream.Length != fp.Size || File.GetLastWriteTimeUtc(path).Ticks != fp.ModifiedUtcTicks)
                throw new IOException("ไฟล์เพลงเปลี่ยนระหว่างตรวจสอบ");
            var sha = Convert.ToHexString(SHA256.HashDataAsync(stream, ct).GetAwaiter().GetResult()).ToLowerInvariant();
            stream.Position = 0;
            var md5 = Convert.ToHexString(MD5.HashDataAsync(stream, ct).GetAwaiter().GetResult());
            if (stream.Length != fp.Size || File.GetLastWriteTimeUtc(path).Ticks != fp.ModifiedUtcTicks ||
                (fp.Md5.Length != 0 && !Paths.Equals(fp.Md5, md5)))
                throw new IOException("ไฟล์เพลงเปลี่ยนระหว่างตรวจสอบ");
            reporter.Publish("ตรวจแฮชรหัสเพลง", e.RelativePath, local, bytes: fp.Size * 2);
            return cache[key] = (fp with { Md5 = md5 }, sha);
        }
        foreach (var code in l.Select(g => g.Key).Concat(r.Select(g => g.Key)).Distinct(Paths).OrderBy(x => x, Paths))
        {
            ct.ThrowIfCancellationRequested();
            SyncEntry[] Sort(IEnumerable<SyncEntry> entries) => entries
                .OrderBy(e => !Paths.Equals(Path.GetFileName(e.RelativePath), code + ".xmid"))
                .ThenBy(e => e.RelativePath, Paths).ToArray();
            var a = Sort(l[code]); var b = Sort(r[code]);
            if (a.Select(e => e.RelativePath).Distinct(Paths).Count() != a.Length ||
                b.Select(e => e.RelativePath).Distinct(Paths).Count() != b.Length)
            {
                result.Add(new SyncDecision((a.FirstOrDefault() ?? b[0]).RelativePath, SyncAction.Conflict,
                    Note: "รหัสซ้ำแบบตัวพิมพ์ · ตรวจสอบเอง"));
                continue;
            }
            void Pass(bool local, SyncEntry[] sources, SyncEntry[] targets)
            {
                var occupied = local ? rightPaths : leftPaths;
                var planned = new List<SyncEntry>();
                foreach (var source in sources)
                {
                    ct.ThrowIfCancellationRequested();
                    var candidates = targets.Select(e => (Local: !local, Entry: e))
                        .Concat(planned.Select(e => (Local: local, Entry: e))).ToArray();
                    void Review(string note) => result.Add(new SyncDecision(source.RelativePath, SyncAction.Conflict, Note: note));
                    void New(string destination, SyncFingerprint fingerprint, string? note)
                    {
                        if (!occupied.Add(destination)) { Review("ชื่อปลายทางชนกัน · ตรวจสอบเอง"); return; }
                        result.Add(new SyncDecision(destination, local ? SyncAction.UploadNew : SyncAction.DownloadNew,
                            source.RelativePath, fingerprint, null, note));
                        planned.Add(source);
                    }
                    if (candidates.Length == 0)
                    {
                        var name = Regex.Replace(Path.GetFileName(source.RelativePath), @"(?: ?\([0-9]+\))+(?=\.xmid$)", "", RegexOptions.IgnoreCase);
                        var destination = InFolder(source.RelativePath, name);
                        New(destination, source.Fingerprint,
                            string.Equals(source.RelativePath, destination, StringComparison.Ordinal)
                                ? null : "ปรับชื่อสำเนา");
                        continue;
                    }
                    var sameSize = candidates.Where(t => t.Entry.Fingerprint.Size == source.Fingerprint.Size).ToArray();
                    // Fast skips equal-size original names, but explicitly hashed
                    // variants are content identities and must be verified.
                    bool hashedName = Path.GetFileName(source.RelativePath).Contains('_') ||
                        sameSize.Any(t => Path.GetFileName(t.Entry.RelativePath).Contains('_'));
                    if (mode == SmartSyncMode.Fast && !hashedName && sameSize.Length > 0)
                    {
                        result.Add(new SyncDecision(source.RelativePath, SyncAction.Unchanged, Note: "รหัส/ขนาดตรงกัน · ข้าม"));
                        continue;
                    }
                    var incoming = Verify(local, source);
                    var existing = candidates.Select(t => Verify(t.Local, t.Entry)).ToArray();
                    if (existing.Any(t => t.Sha == incoming.Sha))
                    {
                        result.Add(new SyncDecision(source.RelativePath, SyncAction.Unchanged, Note: "SHA-256 ตรงกัน · ข้าม"));
                        continue;
                    }
                    var note = $"รหัส {code} · SHA-256 {incoming.Sha[..12]} / {existing[0].Sha[..12]}";
                    if (policy == XmidConflictPolicy.KeepHash)
                    {
                        New(InFolder(source.RelativePath, code + "_" + incoming.Sha + ".xmid"), incoming.Fp,
                            note + " · เก็บทั้งสองฉบับ");
                    }
                    else if (policy == XmidConflictPolicy.Overwrite && sources.Length == 1 &&
                        targets.Length == 1 && planned.Count == 0)
                    {
                        result.Add(new SyncDecision(targets[0].RelativePath,
                            local ? SyncAction.UploadUpdate : SyncAction.DownloadUpdate,
                            source.RelativePath, incoming.Fp, existing[0].Fp, note + " · ทับพร้อมสำรอง"));
                    }
                    else Review(note + (policy == XmidConflictPolicy.Overwrite
                        ? " · หลายฉบับ กำกวม ไม่ทับ" : " · ข้ามตามนโยบาย"));
                }
            }
            if (direction != SmartSyncDirection.ToPc) Pass(true, a, b);
            // A single matched pair needs only one decision in Skip mode.
            // In both-way overwrite mode PC is explicitly authoritative.
            if (direction != SmartSyncDirection.ToDrive &&
                !(direction == SmartSyncDirection.Both && a.Length > 0 && b.Length > 0 &&
                  (policy == XmidConflictPolicy.Overwrite || (policy == XmidConflictPolicy.Skip && a.Length == 1 && b.Length == 1))))
                Pass(false, b, a);
        }
        return result;
    }

    private static bool Allowed(SyncAction action, SmartSyncDirection direction) =>
        ((action is SyncAction.UploadNew or SyncAction.UploadUpdate) && direction != SmartSyncDirection.ToPc) ||
        ((action is SyncAction.DownloadNew or SyncAction.DownloadUpdate) && direction != SmartSyncDirection.ToDrive);

    public static SmartSyncFolderResult Summarize(SmartSyncFolderPlan plan, int copied = 0) => new(copied,
        plan.Decisions.Count(x => x.Action == SyncAction.Unchanged),
        plan.DatabaseReviewCount + plan.Decisions.Count(x => x.Action is SyncAction.Conflict or SyncAction.ReviewDeletion or SyncAction.UploadUpdate or SyncAction.DownloadUpdate),
        plan.Decisions.Count(x => (x.Action is SyncAction.UploadNew or SyncAction.DownloadNew) && !Allowed(x.Action, plan.Direction)));

    public static async Task<SmartSyncFolderResult> ExecuteAsync(SmartSyncFolderPlan plan,
        int parallelFiles, IProgress<int>? progress, CancellationToken ct, string? checkpointPath = null,
        Action<SyncDecision, long>? fileCompleted = null)
    {
        ValidateRoots(plan.Pc, plan.Drive);
        using var journal = checkpointPath is null ? null : new SmartSyncReceiptStore(checkpointPath, plan.Pc, plan.Drive);
        int copied = 0;
        var work = plan.Decisions.Where(x => Allowed(x.Action, plan.Direction)).ToArray();
        await SmartSyncTransfer.ExecuteAsync(work, parallelFiles, async (d, token) =>
        {
            var upload = d.Action is SyncAction.UploadNew or SyncAction.UploadUpdate;
            var sourceRoot = upload ? plan.Pc : plan.Drive;
            var destinationRoot = upload ? plan.Drive : plan.Pc;
            var sourceMap = upload ? plan.PcFiles : plan.DriveFiles;
            var sourcePath = d.SourcePath ?? d.RelativePath;
            if (IsCatalogControlPath(sourcePath) || IsCatalogControlPath(d.RelativePath))
                throw new InvalidDataException("ไฟล์ควบคุมฐานเพลงต้องใช้ตัวเผยแพร่ฐานโดยเฉพาะ");
            if (!sourceMap.TryGetValue(sourcePath, out var observed))
                throw new InvalidDataException("ข้อมูลไฟล์ต้นทางเปลี่ยน กรุณาตรวจสอบใหม่");
            var expected = d.SourceFingerprint ?? observed;
            bool overwrite = d.Action is SyncAction.UploadUpdate or SyncAction.DownloadUpdate;
            if (overwrite && (plan.ConflictPolicy != XmidConflictPolicy.Overwrite ||
                XmidCode(sourcePath) is null || !Paths.Equals(XmidCode(sourcePath), XmidCode(d.RelativePath)) ||
                d.DestinationFingerprint is null))
                throw new InvalidDataException("ไม่อนุญาตให้เขียนทับรายการนี้");
            var sha = await CopyNewAsync(sourceRoot, destinationRoot, sourcePath, d.RelativePath,
                expected, overwrite ? d.DestinationFingerprint : null, token).ConfigureAwait(false);
            journal?.Record(d, expected.Size, sha);
            fileCompleted?.Invoke(d, expected.Size);
            var completed = Interlocked.Increment(ref copied);
            progress?.Report(completed);
        }, (_, _) => throw new InvalidDataException("SQLite ต้องตรวจสอบก่อนส่ง"), ct).ConfigureAwait(false);
        return Summarize(plan, copied);
    }

    private static async Task<string> CopyNewAsync(string sourceRoot, string destinationRoot, string sourceRelative, string relative,
        SyncFingerprint expected, SyncFingerprint? replaceExpected, CancellationToken ct)
    {
        if (SmartSyncTransfer.IsDatabaseCandidate(sourceRelative) || SmartSyncTransfer.IsDatabaseSidecar(sourceRelative))
            throw new InvalidDataException("SQLite ต้องตรวจสอบก่อนส่ง");
        var source = SmartSyncTransfer.ResolveLocalPath(sourceRoot, sourceRelative);
        var destination = SmartSyncTransfer.ResolveLocalPath(destinationRoot, relative);
        if (replaceExpected is null && File.Exists(destination)) throw new IOException("ปลายทางมีไฟล์ใหม่แล้ว กรุณาตรวจสอบอีกครั้ง");
        var parent = Path.GetDirectoryName(destination)!;
        Directory.CreateDirectory(parent);
        SmartSyncTransfer.ResolveLocalPath(destinationRoot, relative);
        var staging = Path.Combine(parent, ".xstage-sync-" + Guid.NewGuid().ToString("N") + ".partial");
        bool created = false;
        try
        {
            using var input = new FileStream(source, FileMode.Open, FileAccess.Read, FileShare.Read, 131072, true);
            if (input.Length != expected.Size ||
                (expected.ModifiedUtcTicks != 0 && File.GetLastWriteTimeUtc(source).Ticks != expected.ModifiedUtcTicks) ||
                (expected.Md5.Length != 0 && !string.Equals(Convert.ToHexString(await MD5.HashDataAsync(input, ct)), expected.Md5, StringComparison.OrdinalIgnoreCase)))
                throw new IOException("ต้นทางเปลี่ยนระหว่างตรวจสอบ กรุณาตรวจสอบใหม่");
            input.Position = 0;
            using var sha = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            await using (var output = new FileStream(staging, FileMode.CreateNew, FileAccess.Write, FileShare.None, 131072, true))
            {
                created = true;
                var buffer = new byte[131072];
                int read;
                while ((read = await input.ReadAsync(buffer.AsMemory(), ct)) > 0)
                {
                    sha.AppendData(buffer, 0, read);
                    await output.WriteAsync(buffer.AsMemory(0, read), ct);
                }
                await output.FlushAsync(ct);
                output.Flush(true);
            }
            var hash = sha.GetHashAndReset();
            if (input.Length != expected.Size ||
                (expected.ModifiedUtcTicks != 0 && File.GetLastWriteTimeUtc(source).Ticks != expected.ModifiedUtcTicks))
                throw new IOException("ต้นทางเปลี่ยนระหว่างรับส่ง");
            using (var check = new FileStream(staging, FileMode.Open, FileAccess.Read, FileShare.Read, 131072, true))
            {
                var copiedHash = await SHA256.HashDataAsync(check, ct);
                if (check.Length != expected.Size ||
                    !CryptographicOperations.FixedTimeEquals(hash, copiedHash))
                    throw new IOException("ตรวจ SHA-256 ไม่ตรง");
            }
            ct.ThrowIfCancellationRequested();
            SmartSyncTransfer.ResolveLocalPath(destinationRoot, relative);
            if (replaceExpected is null)
                File.Move(staging, destination, overwrite: false);
            else
            {
                var actual = HashExisting(destinationRoot, relative, replaceExpected, ct);
                if (!Paths.Equals(actual.Md5, replaceExpected.Md5))
                    throw new IOException("ปลายทางเปลี่ยนหลังตรวจสอบ · ไม่ทับ");
                ct.ThrowIfCancellationRequested();
                var backup = Path.Combine(parent, ".xstage-sync-backup-" + Guid.NewGuid().ToString("N") + ".bak");
                File.Replace(staging, destination, backup, ignoreMetadataErrors: false);
            }
            created = false;
            return Convert.ToHexString(hash);
        }
        finally
        {
            if (created) try { File.Delete(staging); } catch (IOException) { } catch (UnauthorizedAccessException) { }
        }
    }
}

 
// Per-Windows-user preferences only. No access tokens, file inventory or
// authorization to start a transfer is persisted here.
public sealed record SmartSyncPreferences(string Pc = "", string Drive = "",
    SmartSyncDirection Direction = SmartSyncDirection.Both, bool Background = false,
    SmartSyncMode Mode = SmartSyncMode.Fast, int ParallelFiles = 8,
    XmidConflictPolicy ConflictPolicy = XmidConflictPolicy.Skip);

public static class SmartSyncPreferencesStore
{
    public static string DefaultPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "X-Stage", "Download Manager", "smart-sync-preferences.json");

    private static SmartSyncPreferences Validate(SmartSyncPreferences? preferences)
    {
        if (preferences is null || preferences.Pc is null || preferences.Drive is null ||
            preferences.Pc.Length > 32767 || preferences.Drive.Length > 32767 ||
            !Enum.IsDefined(preferences.Direction) || !Enum.IsDefined(preferences.Mode) ||
            preferences.ParallelFiles is < 1 or > 32 || !Enum.IsDefined(preferences.ConflictPolicy))
            throw new InvalidDataException("ตัวเลือก Smart Sync ไม่ถูกต้อง");
        foreach (var path in new[] { preferences.Pc, preferences.Drive })
            if (path.Length > 0 && (!Path.IsPathFullyQualified(path) || path.Contains('\0')))
                throw new InvalidDataException("ตำแหน่งโฟลเดอร์ Smart Sync ไม่ถูกต้อง");
        // Do not probe the network or a disconnected volume during restore.
        // Scan and transfer still perform their original root/safety validation.
        return preferences;
    }

    public static SmartSyncPreferences Load(string file)
    {
        try
        {
            using var stream = new FileStream(file, FileMode.Open, FileAccess.Read, FileShare.Read);
            if (stream.Length > 1024 * 1024)
                throw new InvalidDataException("ไฟล์ตัวเลือก Smart Sync ใหญ่เกินกำหนด");
            using var document = JsonDocument.Parse(stream);
            var saved = document.RootElement.Deserialize<SmartSyncPreferences>();
            if (saved is not null && !document.RootElement.TryGetProperty("ParallelFiles", out _))
                saved = saved with { ParallelFiles = 8 };
            return Validate(saved);
        }
        catch (FileNotFoundException) { return new(); }
        catch (DirectoryNotFoundException) { return new(); }
    }

    public static void Save(string file, SmartSyncPreferences preferences)
    {
        Validate(preferences);
        file = Path.GetFullPath(file);
        Directory.CreateDirectory(Path.GetDirectoryName(file)!);
        var temporary = file + "." + Guid.NewGuid().ToString("N") + ".tmp";
        bool created = false;
        try
        {
            using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                created = true;
                JsonSerializer.Serialize(stream, preferences);
                stream.Flush(true);
            }
            File.Move(temporary, file, overwrite: true);
            created = false;
        }
        finally
        {
            if (created) try { File.Delete(temporary); } catch (IOException) { } catch (UnauthorizedAccessException) { }
        }
    }
}

// A local audit receipt, not authority to skip a missing destination.
// A completed file is recorded only after its verified no-overwrite publication.
public sealed class SmartSyncReceiptStore : IDisposable
{
    private readonly SqliteConnection _connection;
    private readonly object _gate = new();
    private readonly string _pc, _drive;
    public static string DefaultPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "X-Stage", "Download Manager", "smart-sync-receipts.sqlite3");
    public SmartSyncReceiptStore(string file, string pc, string drive)
    {
        file = Path.GetFullPath(file);
        foreach (var root in new[] { pc, drive })
        {
            var prefix = Path.TrimEndingDirectorySeparator(Path.GetFullPath(root)) + Path.DirectorySeparatorChar;
            if (file.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("ฐานประวัติ Sync ต้องอยู่นอกโฟลเดอร์ที่ซิงค์");
        }
        _pc = pc; _drive = drive;
        Directory.CreateDirectory(Path.GetDirectoryName(file)!);
        _connection = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = file, Pooling = false }.ToString());
        try
        {
            _connection.Open();
            using var command = _connection.CreateCommand();
            command.CommandText = "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; CREATE TABLE IF NOT EXISTS receipts(pc TEXT NOT NULL, drive TEXT NOT NULL, relative TEXT NOT NULL COLLATE NOCASE, direction TEXT NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL, completed TEXT NOT NULL, PRIMARY KEY(pc,drive,relative,direction));";
            command.ExecuteNonQuery();
        }
        catch { _connection.Dispose(); throw; }
    }
    public void Record(SyncDecision decision, long size, string sha)
    {
        lock (_gate)
        {
            using var command = _connection.CreateCommand();
            command.CommandText = "INSERT OR REPLACE INTO receipts VALUES($pc,$drive,$relative,$direction,$size,$sha,$completed)";
            command.Parameters.AddWithValue("$pc", _pc);
            command.Parameters.AddWithValue("$drive", _drive);
            command.Parameters.AddWithValue("$relative", decision.RelativePath);
            command.Parameters.AddWithValue("$direction", decision.Action.ToString());
            command.Parameters.AddWithValue("$size", size);
            command.Parameters.AddWithValue("$sha", sha);
            command.Parameters.AddWithValue("$completed", DateTimeOffset.UtcNow.ToString("O"));
            command.ExecuteNonQuery();
        }
    }
    public void Dispose() => _connection.Dispose();
}


// Thread-safe directional totals for the two aggregate workspace rows.
// A completed count is recorded only after verified publication and receipt.
public sealed record SmartSyncLaneSnapshot(bool Upload, int Total, int Done, long Bytes, long DoneBytes,
    string State, double ElapsedSeconds, string LastFile)
{
    // Zero work after a successful scan is complete, unlike an unscanned,
    // canceled, failed or direction-disabled row.
    public bool IsComplete => State is "สำเร็จ" or "ไม่มีไฟล์ใหม่";
    public double Fraction => Total == 0 ? (IsComplete ? 1 : 0) : Math.Clamp(Done / (double)Total, 0, 1);
    public string ProgressText => IsScanning ? "กำลังตรวจสอบ" :
        Total > 0 || IsComplete ? $"{Fraction * 100:0.0}%" : "—";
    public bool IsScanning => State == "กำลังตรวจสอบ";
    public double Rate => State == "กำลังรับส่ง" && ElapsedSeconds > 0 ? DoneBytes / ElapsedSeconds : 0;
}
public sealed class SmartSyncLaneTracker
{
    private readonly object _gate = new();
    private readonly Stopwatch _watch = new();
    private SmartSyncLaneSnapshot _up = new(true, 0, 0, 0, 0, "ยังไม่ตรวจสอบ", 0, "");
    private SmartSyncLaneSnapshot _down = new(false, 0, 0, 0, 0, "ยังไม่ตรวจสอบ", 0, "");
    public (SmartSyncLaneSnapshot Upload, SmartSyncLaneSnapshot Download) Snapshot()
    {
        lock (_gate)
        {
            var elapsed = _watch.Elapsed.TotalSeconds;
            return (_up with { ElapsedSeconds = elapsed }, _down with { ElapsedSeconds = elapsed });
        }
    }
    public void Reset(string state)
    {
        lock (_gate)
        {
            _watch.Reset();
            _up = new(true, 0, 0, 0, 0, state, 0, "");
            _down = new(false, 0, 0, 0, 0, state, 0, "");
        }
    }
    public void Plan(SmartSyncFolderPlan plan)
    {
        lock (_gate)
        {
            _watch.Reset();
            SmartSyncLaneSnapshot Lane(bool upload)
            {
                bool allowed = upload ? plan.Direction != SmartSyncDirection.ToPc : plan.Direction != SmartSyncDirection.ToDrive;
                var work = allowed ? plan.Decisions.Where(d => upload
                    ? d.Action is SyncAction.UploadNew or SyncAction.UploadUpdate
                    : d.Action is SyncAction.DownloadNew or SyncAction.DownloadUpdate).ToArray() : Array.Empty<SyncDecision>();
                var source = upload ? plan.PcFiles : plan.DriveFiles;
                return new(upload, work.Length, 0, work.Sum(d => d.SourceFingerprint?.Size ??
                    (source.TryGetValue(d.SourcePath ?? d.RelativePath, out var fp) ? fp.Size : 0)), 0,
                    !allowed ? "ไม่อยู่ในทิศทาง" : work.Length == 0 ? "ไม่มีไฟล์ใหม่" : "พร้อมรับส่ง", 0, "");
            }
            _up = Lane(true); _down = Lane(false);
        }
    }
    public void Start()
    {
        lock (_gate)
        {
            _watch.Restart();
            if (_up.Total > 0) _up = _up with { State = "กำลังรับส่ง" };
            if (_down.Total > 0) _down = _down with { State = "กำลังรับส่ง" };
        }
    }
    public void Complete(SyncDecision decision, long bytes)
    {
        lock (_gate)
        {
            bool upload = decision.Action is SyncAction.UploadNew or SyncAction.UploadUpdate;
            var lane = upload ? _up : _down;
            lane = lane with { Done = lane.Done + 1, DoneBytes = lane.DoneBytes + bytes,
                LastFile = decision.RelativePath, State = lane.Done + 1 == lane.Total ? "สำเร็จ" : "กำลังรับส่ง" };
            if (upload) _up = lane; else _down = lane;
        }
    }
    public void Finish(string state)
    {
        lock (_gate)
        {
            _watch.Stop();
            if (_up.State is "กำลังรับส่ง" or "กำลังตรวจสอบ") _up = _up with { State = state };
            if (_down.State is "กำลังรับส่ง" or "กำลังตรวจสอบ") _down = _down with { State = state };
        }
    }
}


// Indeterminate scan is a bouncing segment, never a guessed percentage.
public static class SmartSyncScanAnimation
{
    public static (int Offset, int Width) Band(int width, long ticks)
    {
        if (width <= 0) return (0, 0);
        int segment = Math.Max(1, width / 4);
        int travel = width - segment;
        if (travel == 0) return (0, segment);
        long period = 2L * travel;
        long step = ((ticks / 12) % period + period) % period;
        return ((int)(step <= travel ? step : period - step), segment);
    }
}
