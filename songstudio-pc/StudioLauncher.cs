// X-Stage Song Studio portable Windows GUI launcher.
// Compiled by the Windows GitHub Actions runner; never downloads dependencies.
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class StudioLauncher {
    [STAThread]
    private static int Main() {
        try {
            string root = AppDomain.CurrentDomain.BaseDirectory;
            string script = Path.Combine(root, "Start-Song-Studio-Ready.ps1");
            string python = Path.Combine(root, ".runtime", "python", "pythonw.exe");
            string manifest = Path.Combine(root, ".engine-ready-manifest.json");
            if (!File.Exists(script) || !File.Exists(python) || !File.Exists(manifest)) {
                MessageBox.Show("กรุณาแตก ZIP ทั้งหมดก่อนเปิดโปรแกรม\n"
                    + "ไม่พบชุด Python Runtime หรือไฟล์ตรวจสอบความสมบูรณ์",
                    "X-Stage Song Studio", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 2;
            }
            var info = new ProcessStartInfo {
                FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),
                    "WindowsPowerShell", "v1.0", "powershell.exe"),
                Arguments = "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File \""
                    + script + "\"",
                WorkingDirectory = root,
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden
            };
            // Existing verified PowerShell launcher checks every manifest checksum,
            // then starts bundled pythonw.exe (no console).
            Process p = Process.Start(info);
            if (p == null) throw new InvalidOperationException("ไม่สามารถเปิดระบบเริ่มต้น");
            return 0;
        } catch (Exception ex) {
            MessageBox.Show(ex.Message, "X-Stage Song Studio",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
