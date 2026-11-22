using System.Windows.Forms;

namespace XStageDownloadManager;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        // Run the copied single-file updater before taking the GUI instance lock.
        // The installed app must exit so Inno Setup can replace its binary safely.
        if (args.Length > 0 && args[0] == "--apply-verified-update")
        {
            ApplicationConfiguration.Initialize();
            Application.Run(new UpdateTransitionForm(args));
            return;
        }

        // Chromium invokes the registered native host with its origin as an
        // argument and communicates only via binary-framed JSON on stdin/out.
        if (args.Contains("--native-host") ||
            args.Any(x => x.StartsWith("chrome-extension://", StringComparison.Ordinal)))
        {
            NativeMessagingBridge.RunNativeHost(args);
            return;
        }

        ApplicationConfiguration.Initialize();
        // Replace the generic .NET "Parameter is not valid" dialog with a
        // useful, redacted stack trace in the application's private log.
        // The log path never lives in a user's download/output directory.
        Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
        Application.ThreadException += (_, eventArgs) =>
        {
            var log = WriteUiError(eventArgs.Exception);
            MessageBox.Show(
                "X-Stage พบข้อผิดพลาดในหน้าจอและจะปิดอย่างปลอดภัย\n" +
                "รายละเอียดสำหรับตรวจสอบ: " + log + "\n" +
                "โปรดแจ้งไฟล์บันทึกนี้เพื่อระบุบรรทัดที่เกิดปัญหา",
                "X-Stage · รายงานข้อผิดพลาด", MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            Application.Exit();
        };
        AppDomain.CurrentDomain.UnhandledException += (_, eventArgs) =>
        {
            if (eventArgs.ExceptionObject is Exception exception)
                WriteUiError(exception);
        };
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

        try
        {
            Application.Run(new MainForm(args));
        }
        catch (Exception exception)
        {
            var log = WriteUiError(exception);
            MessageBox.Show(
                "ไม่สามารถเปิดหน้าต่าง X-Stage ได้\n" +
                "รายละเอียดข้อผิดพลาด: " + log,
                "X-Stage · เปิดโปรแกรมไม่สำเร็จ", MessageBoxButtons.OK,
                MessageBoxIcon.Error);
        }
        finally { mutex.ReleaseMutex(); }
    }

    private static string WriteUiError(Exception exception)
    {
        try
        {
            var folder = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "X-Stage", "Download Manager", "logs");
            Directory.CreateDirectory(folder);
            var file = Path.Combine(folder, "ui-errors.log");
            var backup = Path.Combine(folder, "ui-errors.previous.log");
            // Keep the log bounded and avoid recording signed CDN URL tokens.
            if (File.Exists(file) && new FileInfo(file).Length > 256 * 1024)
                File.Move(file, backup, overwrite: true);
            var trace = System.Text.RegularExpressions.Regex.Replace(
                exception.ToString(), @"https?://[^\s]+", "[redacted-url]",
                System.Text.RegularExpressions.RegexOptions.IgnoreCase);
            if (trace.Length > 12000) trace = trace[..12000];
            File.AppendAllText(file,
                DateTimeOffset.Now.ToString("O") + Environment.NewLine +
                trace + Environment.NewLine + "---" + Environment.NewLine);
            return file;
        }
        catch (Exception)
        {
            return "ไม่สามารถบันทึกไฟล์ได้";
        }
    }
}
