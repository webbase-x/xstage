using System.Diagnostics;
using System.IO.Pipes;
using System.Text;
using System.Text.Json;

namespace XStageDownloadManager;

// The browser extension talks to this installed EXE through Chromium Native
// Messaging. The desktop GUI receives URLs over a current-user named pipe.
// Browser capture is opt-in and never requires a background web server.
internal static class NativeMessagingBridge
{
    internal const string HostName = "com.xstage.download_manager";
    private const string PipeName = "XStageDownloadManager_v021_local";
    private const int MaxMessageBytes = 8192;

    internal static async Task<bool> SendToRunningAppAsync(string url, int timeoutMs = 1500)
    {
        if (!DownloadEngine.TryParseUrl(url, out _)) return false;
        try
        {
            using var client = new NamedPipeClientStream(".", PipeName, PipeDirection.InOut, PipeOptions.Asynchronous);
            using var timeout = new CancellationTokenSource(timeoutMs);
            await client.ConnectAsync(timeout.Token);
            using var writer = new StreamWriter(client, new UTF8Encoding(false), 1024, leaveOpen: true) { AutoFlush = true };
            using var reader = new StreamReader(client, Encoding.UTF8, leaveOpen: true);
            await writer.WriteLineAsync(url.AsMemory(), timeout.Token);
            var result = await reader.ReadLineAsync(timeout.Token);
            return result == "ok";
        }
        catch (Exception ex) when (ex is IOException or OperationCanceledException or TimeoutException)
        {
            return false;
        }
    }

    internal static async Task ListenAsync(Func<string, Task<bool>> onUrl, CancellationToken cancel)
    {
        while (!cancel.IsCancellationRequested)
        {
            using var server = new NamedPipeServerStream(PipeName, PipeDirection.InOut, 1,
                PipeTransmissionMode.Byte, PipeOptions.Asynchronous);
            try
            {
                await server.WaitForConnectionAsync(cancel);
                using var reader = new StreamReader(server, Encoding.UTF8, leaveOpen: true);
                using var writer = new StreamWriter(server, new UTF8Encoding(false), 1024, leaveOpen: true) { AutoFlush = true };
                var url = await reader.ReadLineAsync(cancel);
                var accepted = url is { Length: <= MaxMessageBytes } &&
                               DownloadEngine.TryParseUrl(url, out _) && await onUrl(url);
                await writer.WriteLineAsync(accepted ? "ok" : "error");
            }
            catch (OperationCanceledException) when (cancel.IsCancellationRequested) { return; }
            catch (IOException) { /* Browser host may close while the GUI is shutting down. */ }
            catch (InvalidOperationException) { }
        }
    }

    private static async Task<bool> HandOffAsync(string url)
    {
        if (!DownloadEngine.TryParseUrl(url, out _) || url.Length > MaxMessageBytes) return false;
        if (await SendToRunningAppAsync(url)) return true;
        // Serialize simultaneous native-host launches. ACK is only sent after
        // the actual GUI accepted the URL through its named pipe.
        try
        {
            using var launchGate = new Mutex(false, @"Local\XStageDownloadManagerStartGate");
            if (!launchGate.WaitOne(TimeSpan.FromSeconds(3))) return false;
            try
            {
                if (await SendToRunningAppAsync(url)) return true;
                if (!Mutex.TryOpenExisting(@"Local\XStageDownloadManagerDesktop", out var desktopMutex))
                {
                    var start = new ProcessStartInfo(Environment.ProcessPath ?? Application.ExecutablePath)
                    {
                        UseShellExecute = false
                    };
                    if (Process.Start(start) is null) return false;
                }
                else desktopMutex.Dispose();
            }
            finally { launchGate.ReleaseMutex(); }

            for (int attempt = 0; attempt < 18; attempt++)
            {
                if (await SendToRunningAppAsync(url, 350)) return true;
                await Task.Delay(200);
            }
            return false;
        }
        catch (Exception ex) when (ex is IOException or System.ComponentModel.Win32Exception or
                                   InvalidOperationException or UnauthorizedAccessException)
        {
            return false;
        }
    }

    internal static void RunNativeHost(string[] arguments)
    {
        // Chromium passes the extension origin as the first argument on Windows.
        var origin = arguments.FirstOrDefault(a => a.StartsWith("chrome-extension://", StringComparison.Ordinal));
        if (origin is not null && !BrowserIntegration.IsAllowedOrigin(origin)) return;
        try
        {
            using var input = Console.OpenStandardInput();
            using var output = Console.OpenStandardOutput();
            Span<byte> sizeBytes = stackalloc byte[4];
            input.ReadExactly(sizeBytes);
            int count = System.Buffers.Binary.BinaryPrimitives.ReadInt32LittleEndian(sizeBytes);
            if (count is < 1 or > MaxMessageBytes)
            {
                WriteResponse(output, new { ok = false, error = "Message size invalid" });
                return;
            }
            byte[] bytes = new byte[count];
            input.ReadExactly(bytes);
            using var message = JsonDocument.Parse(bytes);
            var root = message.RootElement;
            var type = root.TryGetProperty("type", out var t) ? t.GetString() : null;
            if (type == "ping")
            {
                WriteResponse(output, new { ok = true, version = UpdateChecker.CurrentVersion });
                return;
            }
            var url = type == "enqueue" && root.TryGetProperty("url", out var u) &&
                u.ValueKind == JsonValueKind.String ? u.GetString() : null;
            var automatic = type == "enqueue" && root.TryGetProperty("source", out var source) &&
                            source.ValueKind == JsonValueKind.String && source.GetString() == "auto";
            bool canCapture = !automatic || url is not null &&
                BrowserCaptureProbe.IsUnauthenticatedFileAsync(url).GetAwaiter().GetResult();
            bool accepted = canCapture && !string.IsNullOrWhiteSpace(url) &&
                            HandOffAsync(url).GetAwaiter().GetResult();
            WriteResponse(output, new { ok = accepted });
        }
        catch (Exception ex) when (ex is IOException or JsonException or EndOfStreamException or InvalidOperationException)
        {
            // Native hosts MUST reserve stdout for the binary-framed JSON response.
        }
    }

    private static void WriteResponse(Stream output, object message)
    {
        var data = JsonSerializer.SerializeToUtf8Bytes(message);
        Span<byte> sizeBytes = stackalloc byte[4];
        System.Buffers.Binary.BinaryPrimitives.WriteInt32LittleEndian(sizeBytes, data.Length);
        output.Write(sizeBytes);
        output.Write(data);
        output.Flush();
    }
}
