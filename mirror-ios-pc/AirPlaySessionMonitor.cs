using System.Diagnostics;
using System.Net;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;

namespace XStageMirrorIOSPC;

/// <summary>
/// Observes ONLY the bundled UxPlay process. A TCP peer is a network session,
/// not proof of video mirroring; a render window is evidence of active video.
/// No user identity is fabricated when UxPlay does not expose one.
/// </summary>
internal static class AirPlaySessionMonitor
{
    internal sealed record Snapshot(bool VideoWindow, string[] PeerAddresses, string[] Connections, string? Problem);

    internal static Snapshot Probe(int receiverPid)
    {
        try
        {
            var addresses = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var connections = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var psi = new ProcessStartInfo
            {
                FileName = "netstat.exe",
                Arguments = "-ano -p tcp",
                RedirectStandardOutput = true,
                UseShellExecute = false,
                CreateNoWindow = true
            };
            using var process = Process.Start(psi);
            if (process is null) return new Snapshot(false, [], [], "Windows netstat ไม่ตอบกลับ");
            // Reading stdout first prevents pipe buffer deadlocks on busy machines.
            string output = process.StandardOutput.ReadToEnd();
            if (!process.WaitForExit(3500))
            {
                try { process.Kill(); } catch { }
                return new Snapshot(false, [], [], "การตรวจ TCP ใช้เวลานานเกินไป");
            }
            foreach (var line in output.Split('\n'))
            {
                var fields = Regex.Split(line.Trim(), @"\s+");
                if (fields.Length < 5 || fields[0] != "TCP" ||
                    !fields[3].Equals("ESTABLISHED", StringComparison.OrdinalIgnoreCase) ||
                    !int.TryParse(fields[4], out var pid) || pid != receiverPid)
                    continue;
                var remote = fields[2];
                int colon = remote.LastIndexOf(':');
                if (colon < 1) continue;
                var host = remote[..colon].Trim('[', ']');
                int scopeIndex = host.IndexOf('%');
                if (scopeIndex >= 0) host = host[..scopeIndex];
                if (!IPAddress.TryParse(host, out var ip) || IPAddress.IsLoopback(ip) ||
                    ip.Equals(IPAddress.Any) || ip.Equals(IPAddress.IPv6Any))
                    continue;
                addresses.Add(ip.ToString());
                connections.Add(fields[1] + " -> " + remote);
            }
            return new Snapshot(HasVideoWindow(receiverPid),
                addresses.OrderBy(x => x, StringComparer.OrdinalIgnoreCase).Take(8).ToArray(),
                connections.OrderBy(x => x, StringComparer.OrdinalIgnoreCase).ToArray(), null);
        }
        catch (Exception ex)
        {
            return new Snapshot(false, [], [], "ตรวจสอบเซสชันไม่ได้: " + ex.Message);
        }
    }

    private static bool HasVideoWindow(int targetPid)
    {
        bool found = false;
        EnumWindows((handle, _) =>
        {
            if (!IsWindowVisible(handle)) return true;
            GetWindowThreadProcessId(handle, out var owner);
            if (owner != (uint)targetPid) return true;
            var length = GetWindowTextLength(handle);
            if (length < 3) return true;
            var title = new StringBuilder(length + 1);
            GetWindowText(handle, title, title.Capacity);
            var name = title.ToString();
            // Bundled UxPlay renames its rendering window "AirPlay Video Stream".
            // In other renderers, a GStreamer renderer window may retain its title.
            if (name.Contains("AirPlay Video Stream", StringComparison.OrdinalIgnoreCase) ||
                name.Contains("renderer", StringComparison.OrdinalIgnoreCase))
            {
                found = true;
                return false;
            }
            return true;
        }, IntPtr.Zero);
        return found;
    }

    private delegate bool EnumWindowsProc(IntPtr handle, IntPtr parameter);
    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr parameter);
    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool IsWindowVisible(IntPtr handle);
    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr handle, out uint processId);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowText(IntPtr handle, StringBuilder text, int maxCount);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowTextLength(IntPtr handle);
}
