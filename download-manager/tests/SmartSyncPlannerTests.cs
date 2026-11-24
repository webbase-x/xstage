using XStageDownloadManager;

internal static class SmartSyncPlannerTests
{
    public static void Run()
    {
        SyncFingerprint a = new(10, new string('a', 32)), b = new(10, new string('b', 32)),
            c = new(10, new string('c', 32));
        SyncEntry[] E(SyncFingerprint f) => new[] { new SyncEntry("MIDI/song.mid", f) };
        var empty = Array.Empty<SyncEntry>();
        void Check(SyncEntry[] l, SyncEntry[] r, SyncEntry[] baseline, SyncAction expected)
        {
            var actual = SmartSyncPlanner.Plan(l, r, baseline).Single().Action;
            if (actual != expected) throw new Exception($"Smart Sync: expected {expected}, got {actual}");
        }
        Check(E(a), empty, empty, SyncAction.UploadNew);
        Check(empty, E(a), empty, SyncAction.DownloadNew);
        Check(E(a), E(a), empty, SyncAction.Unchanged);
        Check(E(a), E(b), empty, SyncAction.Conflict);
        Check(E(a), E(b), E(a), SyncAction.DownloadUpdate);
        Check(E(b), E(a), E(a), SyncAction.UploadUpdate);
        Check(E(b), E(c), E(a), SyncAction.Conflict);
        Check(empty, E(a), E(a), SyncAction.ReviewDeletion);
        Check(E(b), empty, E(a), SyncAction.ReviewDeletion);
        Check(empty, empty, E(a), SyncAction.Unchanged);
        Check(E(new SyncFingerprint(10, "")), empty, empty, SyncAction.Conflict);
        Check(new[] { new SyncEntry("../outside.mid", a) }, empty, empty, SyncAction.Conflict);
        Check(new[] { new SyncEntry("CON.mid", a) }, empty, empty, SyncAction.Conflict);
        Check(E(a), E(a).Concat(new[] { new SyncEntry("midi/SONG.mid", a) }).ToArray(), empty, SyncAction.Conflict);
        if (SmartSyncPlanner.Plan(new[] { new SyncEntry("MIDI", a) }, E(a), empty)
            .Any(x => x.Action != SyncAction.Conflict)) throw new Exception("File/folder collision missed");
        var many = Enumerable.Range(0, 50000).Select(i => new SyncEntry($"MIDI/{i:D5}.mid", a)).ToArray();
        if (SmartSyncPlanner.Plan(many, many, many).Count != many.Length ||
            SmartSyncPlanner.Plan(many, many, many).Any(x => x.Action != SyncAction.Unchanged))
            throw new Exception("Large library plan incorrect");
        Console.WriteLine("PASS: Smart Sync two-way planning, conflicts, deletion review and 50k files");
    }
}
