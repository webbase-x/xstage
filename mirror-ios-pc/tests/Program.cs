using System.Net;
using System.Net.Http;
using System.Reflection;
using System.Security.Cryptography;

internal static class Program
{
    public static async Task Main()
    {
        // Exercise the real production download method. The fake HTTP handler
        // eliminates network/GitHub dependencies; only Windows FileStream locking
        // is under test. The old implementation always failed its PE re-open.
        byte[] payload = new byte[10_000_064];
        payload[0] = (byte)'M';
        payload[1] = (byte)'Z';
        string expectedSha = Convert.ToHexString(SHA256.HashData(payload));
        string destination = Path.Combine(
            Path.GetTempPath(), "xstage-mirror-updater-regression-" +
            Guid.NewGuid().ToString("N") + ".partial");
        try
        {
            var assembly = Assembly.Load("XStageMirrorIOSPC");
            var manager = assembly.GetType(
                "XStageMirrorIOSPC.MirrorAutoUpdateManager", throwOnError: true)!;
            var updateType = manager.GetNestedType("Update", BindingFlags.NonPublic)
                ?? throw new InvalidOperationException("Update record missing");
            var update = Activator.CreateInstance(
                updateType, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
                binder: null,
                args: new object[] { "1.0.9", 1010, "test-Setup.exe", "https://example.invalid/test", expectedSha },
                culture: null) ?? throw new InvalidOperationException("Update record creation failed");
            var method = manager.GetMethod(
                "DownloadVerifiedAsync", BindingFlags.NonPublic | BindingFlags.Static)
                ?? throw new InvalidOperationException("Download method missing");
            using var client = new HttpClient(new StaticHandler(payload));
            var task = method.Invoke(null, new object[] { client, update, destination }) as Task
                ?? throw new InvalidOperationException("Download did not produce a Task");
            await task;
            using (var reopened = new FileStream(destination, FileMode.Open, FileAccess.ReadWrite,
                       FileShare.None))
            {
                if (reopened.ReadByte() != 'M' || reopened.ReadByte() != 'Z')
                    throw new InvalidDataException("PE header was not verified");
                if (reopened.Length != payload.Length)
                    throw new InvalidDataException("Downloaded payload size mismatch");
            }
            Console.WriteLine("PASS: updater closed the exclusive writer before PE re-open");
            TestStopMirroring(assembly);
        }
        finally
        {
            if (File.Exists(destination)) File.Delete(destination);
        }
    }

    private static void TestStopMirroring(Assembly assembly)
    {
        Type type = assembly.GetType("XStageMirrorIOSPC.AirPlaySessionTransitions", true)!;
        object state = Activator.CreateInstance(type, true)!;
        var observe = type.GetMethod("ShouldHide", BindingFlags.NonPublic | BindingFlags.Instance)!;
        var hide = type.GetMethod("MarkHidden", BindingFlags.NonPublic | BindingFlags.Instance)!;
        var hasNew = type.GetMethod("HasNewSession", BindingFlags.NonPublic | BindingFlags.Instance)!;
        bool ShouldHide(bool visible, params string[] sockets) =>
            (bool)observe.Invoke(state, new object[] { sockets, visible })!;
        bool HasNew(params string[] sockets) =>
            (bool)hasNew.Invoke(state, new object[] { sockets })!;
        const string control = "192.168.1.2:7000 -> 192.168.1.3:55551";
        const string video = "192.168.1.2:7001 -> 192.168.1.3:55552";
        const string newVideo = "192.168.1.2:7001 -> 192.168.1.3:55553";
        if (ShouldHide(false, control) ||
            ShouldHide(true, control, video) ||
            ShouldHide(true, control) ||
            !ShouldHide(true, control))
            throw new InvalidOperationException("Video socket loss must be confirmed");
        hide.Invoke(state, new object[] { new[] { control } });
        if (HasNew(control) || !HasNew(control, newVideo))
            throw new InvalidOperationException("Old control socket is not a new video session");
        var confirm = type.GetMethod("ConfirmNoPeers", BindingFlags.NonPublic | BindingFlags.Instance)!;
        bool Confirm(bool seen, bool showing, int peers) =>
            (bool)confirm.Invoke(state, new object[] { seen, showing, peers })!;
        if (Confirm(true, true, 0) || !Confirm(true, true, 0))
            throw new InvalidOperationException("Empty peer samples need confirmation");
        if (Confirm(true, true, 1) || Confirm(true, true, 0) || !Confirm(true, true, 0))
            throw new InvalidOperationException("Returning peers must reset empty-peer samples");
        Console.WriteLine("PASS: socket transitions and intermittent peer observation");
    }

    private sealed class StaticHandler(byte[] payload) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new ByteArrayContent(payload)
            });
        }
    }
}
