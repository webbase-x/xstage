using System.Security.Cryptography;
using System.Diagnostics;

namespace XStageDownloadManager;

public enum SmartSyncDirection { Both, ToDrive, ToPc }
public sealed record SmartSyncFolderPlan(string Pc, string Drive, SmartSyncDirection Direction,
    IReadOnlyList<SyncDecision> Decisions, IReadOnlyDictionary<string, SyncFingerprint> PcFiles,
    IReadOnlyDictionary<string, SyncFingerprint> DriveFiles, int DatabaseReviewCount);
public sealed record SmartSyncFolderResult(int Copied, int Identical, int Review, int SkippedDirection);
public sealed record SmartSyncScanProgress(string Phase, string RelativePath, int PcFiles, int DriveFiles,
    long BytesHashed, int Review, int Folders, TimeSpan Elapsed);

// Phase 1: operate only on explicitly selected mirrored local folders.
// Google Drive for desktop owns account authentication and cloud transport.
// No implicit overwrite, deletion, token access, or cloud-completion claim.
public static class SmartSyncFolders
{
    private static readonly StringComparer Paths = StringComparer.OrdinalIgnoreCase;

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
        public void Publish(string phase, string relative, bool pc, int files = 0, long bytes = 0,
            int review = 0, int folders = 0)
        {
            if (pc) _pc += files; else _drive += files;
            _bytes += bytes; _review += review; _folders += folders;
            progress?.Report(new SmartSyncScanProgress(phase, relative, _pc, _drive,
                _bytes, _review, _folders, _watch.Elapsed));
        }
    }

    private static (List<SyncEntry> Entries, int Review) Inventory(string root, CancellationToken ct,
        ScanReporter reporter, bool pc)
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
                if ((attributes & FileAttributes.Directory) != 0) { pending.Push(path); continue; }
                var relative = Path.GetRelativePath(root, path).Replace(Path.DirectorySeparatorChar, '/');
                reporter.Publish(phase, relative, pc);
                if (SmartSyncTransfer.IsDatabaseSidecar(relative) || SmartSyncTransfer.IsDatabaseCandidate(relative))
                { review++; reporter.Publish(phase, relative, pc, review: 1); continue; }
                // A crash may have left an unpublished staging file.
                if (Path.GetFileName(path).StartsWith(".xstage-sync-", StringComparison.OrdinalIgnoreCase))
                { review++; reporter.Publish(phase, relative, pc, review: 1); continue; }
                if (!SmartSyncPlanner.SafeRelativePath(relative))
                    throw new InvalidDataException("พบชื่อไฟล์ที่ไม่ปลอดภัยสำหรับ Windows");
                SmartSyncTransfer.ResolveLocalPath(root, relative);
                using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
                var md5 = Convert.ToHexString(MD5.HashDataAsync(stream, ct).GetAwaiter().GetResult());
                entries.Add(new SyncEntry(relative, new SyncFingerprint(stream.Length, md5)));
                reporter.Publish(phase, relative, pc, files: 1, bytes: stream.Length);
            }
        }
        return (entries, review);
    }

    private static IReadOnlyDictionary<string, SyncFingerprint> Unique(IEnumerable<SyncEntry> entries) =>
        entries.GroupBy(x => x.RelativePath, Paths).Where(g => g.Count() == 1)
            .ToDictionary(g => g.Key, g => g.Single().Fingerprint, Paths);

    public static SmartSyncFolderPlan Scan(string pc, string drive, SmartSyncDirection direction, CancellationToken ct,
        IProgress<SmartSyncScanProgress>? progress = null)
    {
        if (!Enum.IsDefined(direction)) throw new ArgumentOutOfRangeException(nameof(direction));
        var reporter = new ScanReporter(progress);
        reporter.Publish("ตรวจสอบโฟลเดอร์", "", true);
        ct.ThrowIfCancellationRequested();
        (pc, drive) = ValidateRoots(pc, drive);
        var l = Inventory(pc, ct, reporter, true);
        var r = Inventory(drive, ct, reporter, false);
        reporter.Publish("เปรียบเทียบรายการ", "", false);
        ct.ThrowIfCancellationRequested();
        // No verified historical baseline yet: differing existing files are
        // always conflicts. Identical files and new files are safe to handle.
        var decisions = SmartSyncPlanner.Plan(l.Entries, r.Entries, Array.Empty<SyncEntry>());
        ct.ThrowIfCancellationRequested();
        reporter.Publish("ตรวจสอบเสร็จ", "", false);
        return new SmartSyncFolderPlan(pc, drive, direction, decisions, Unique(l.Entries), Unique(r.Entries), l.Review + r.Review);
    }

    private static bool Allowed(SyncAction action, SmartSyncDirection direction) =>
        (action == SyncAction.UploadNew && direction != SmartSyncDirection.ToPc) ||
        (action == SyncAction.DownloadNew && direction != SmartSyncDirection.ToDrive);

    public static SmartSyncFolderResult Summarize(SmartSyncFolderPlan plan, int copied = 0) => new(copied,
        plan.Decisions.Count(x => x.Action == SyncAction.Unchanged),
        plan.DatabaseReviewCount + plan.Decisions.Count(x => x.Action is SyncAction.Conflict or SyncAction.ReviewDeletion or SyncAction.UploadUpdate or SyncAction.DownloadUpdate),
        plan.Decisions.Count(x => (x.Action is SyncAction.UploadNew or SyncAction.DownloadNew) && !Allowed(x.Action, plan.Direction)));

    public static async Task<SmartSyncFolderResult> ExecuteAsync(SmartSyncFolderPlan plan,
        int parallelFiles, IProgress<int>? progress, CancellationToken ct)
    {
        ValidateRoots(plan.Pc, plan.Drive);
        int copied = 0;
        var work = plan.Decisions.Where(x => Allowed(x.Action, plan.Direction)).ToArray();
        await SmartSyncTransfer.ExecuteAsync(work, parallelFiles, async (d, token) =>
        {
            var upload = d.Action == SyncAction.UploadNew;
            var sourceRoot = upload ? plan.Pc : plan.Drive;
            var destinationRoot = upload ? plan.Drive : plan.Pc;
            var sourceMap = upload ? plan.PcFiles : plan.DriveFiles;
            if (!sourceMap.TryGetValue(d.RelativePath, out var expected))
                throw new InvalidDataException("ข้อมูลไฟล์ต้นทางเปลี่ยน กรุณาตรวจสอบใหม่");
            await CopyNewAsync(sourceRoot, destinationRoot, d.RelativePath, expected, token).ConfigureAwait(false);
            var completed = Interlocked.Increment(ref copied);
            progress?.Report(completed);
        }, (_, _) => throw new InvalidDataException("SQLite ต้องตรวจสอบก่อนส่ง"), ct).ConfigureAwait(false);
        return Summarize(plan, copied);
    }

    private static async Task CopyNewAsync(string sourceRoot, string destinationRoot, string relative,
        SyncFingerprint expected, CancellationToken ct)
    {
        var source = SmartSyncTransfer.ResolveLocalPath(sourceRoot, relative);
        var destination = SmartSyncTransfer.ResolveLocalPath(destinationRoot, relative);
        if (File.Exists(destination)) throw new IOException("ปลายทางมีไฟล์ใหม่แล้ว กรุณาตรวจสอบอีกครั้ง");
        var parent = Path.GetDirectoryName(destination)!;
        Directory.CreateDirectory(parent);
        SmartSyncTransfer.ResolveLocalPath(destinationRoot, relative);
        var staging = Path.Combine(parent, ".xstage-sync-" + Guid.NewGuid().ToString("N") + ".partial");
        bool created = false;
        try
        {
            using var input = new FileStream(source, FileMode.Open, FileAccess.Read, FileShare.Read, 131072, true);
            if (input.Length != expected.Size ||
                !string.Equals(Convert.ToHexString(await MD5.HashDataAsync(input, ct)), expected.Md5, StringComparison.OrdinalIgnoreCase))
                throw new IOException("ต้นทางเปลี่ยนระหว่างตรวจสอบ กรุณาตรวจสอบใหม่");
            input.Position = 0;
            var hash = await SHA256.HashDataAsync(input, ct);
            input.Position = 0;
            await using (var output = new FileStream(staging, FileMode.CreateNew, FileAccess.Write, FileShare.None, 131072, true))
            {
                created = true;
                await input.CopyToAsync(output, ct);
                await output.FlushAsync(ct);
                output.Flush(true);
            }
            using (var check = new FileStream(staging, FileMode.Open, FileAccess.Read, FileShare.Read, 131072, true))
            {
                var copiedHash = await SHA256.HashDataAsync(check, ct);
                if (check.Length != expected.Size ||
                    !CryptographicOperations.FixedTimeEquals(hash, copiedHash))
                    throw new IOException("ตรวจ SHA-256 ไม่ตรง");
            }
            ct.ThrowIfCancellationRequested();
            SmartSyncTransfer.ResolveLocalPath(destinationRoot, relative);
            File.Move(staging, destination, overwrite: false);
            created = false;
        }
        finally
        {
            if (created) try { File.Delete(staging); } catch (IOException) { } catch (UnauthorizedAccessException) { }
        }
    }
}
