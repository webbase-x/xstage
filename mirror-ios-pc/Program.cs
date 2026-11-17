using System;
using System.Threading;
using System.Windows.Forms;

namespace XStageMirrorIOSPC;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        // Two independent X-Stage receivers must never fight for AirPlay ports.
        using var instance = new Mutex(true, @"Local\XStageMirrorIOSPC-Receiver", out bool first);
        if (!first)
        {
            MessageBox.Show("X-Stage Mirror iOS PC กำลังทำงานอยู่แล้ว\nกรุณาเปิดหน้าต่างเดิมแทน",
                "X-Stage Mirror iOS PC", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }
        ApplicationConfiguration.Initialize();
        Application.Run(new MainForm());
    }
}
