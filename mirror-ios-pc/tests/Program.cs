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
        }
        finally
        {
            if (File.Exists(destination)) File.Delete(destination);
        }
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
