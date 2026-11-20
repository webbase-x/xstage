using System;
using System.Windows.Forms;

namespace XStageMirrorAndroidPC;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        if (args.Length == 2 && args[0] == "--prepare-windows")
        {
            Environment.ExitCode = WindowsPreparation.ExecuteAsync(args[1]).GetAwaiter().GetResult();
            return;
        }
        ApplicationConfiguration.Initialize();
        Application.Run(new MainForm());
    }
}
