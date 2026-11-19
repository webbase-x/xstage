using System.Windows.Forms;

namespace XStageDownloadManager;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        // Chromium invokes the registered native host with its origin as an
        // argument and communicates only via binary-framed JSON on stdin/out.
        if (args.Contains("--native-host") ||
            args.Any(x => x.StartsWith("chrome-extension://", StringComparison.Ordinal)))
        {
            NativeMessagingBridge.RunNativeHost(args);
            return;
        }

        ApplicationConfiguration.Initialize();
        var commandUrl = args.Length > 1 && args[0] == "--enqueue" ? args[1] : null;
        using var mutex = new Mutex(true, @"Local\XStageDownloadManagerDesktop", out var firstInstance);
        if (!firstInstance)
        {
            if (commandUrl is not null)
            {
                // The GUI may still be starting: retry the private pipe, never
                // silently queue the same item in multiple Windows processes.
                for (int attempt = 0; attempt < 12; attempt++)
                {
                    if (NativeMessagingBridge.SendToRunningAppAsync(commandUrl, 500)
                        .GetAwaiter().GetResult()) return;
                    Thread.Sleep(200);
                }
            }
            return;
        }

        try { Application.Run(new MainForm(args)); }
        finally { mutex.ReleaseMutex(); }
    }
}
