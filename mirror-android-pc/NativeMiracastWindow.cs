using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;

namespace XStageMirrorAndroidPC;

/// <summary>
/// Identify only Microsoft's Connect or Wireless Display window. Windows owns
/// playback; a launch or window does NOT prove a Miracast peer is connected.
/// </summary>
internal static class NativeMiracastWindow
{
    private delegate bool EnumWindowCallback(IntPtr hwnd, IntPtr data);
    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumWindowCallback callback, IntPtr data);
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr handle);
    [DllImport("user32.dll")] private static extern bool IsWindow(IntPtr handle);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetClassName(IntPtr handle, StringBuilder name, int length);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowText(IntPtr handle, StringBuilder title, int length);
    [DllImport("user32.dll")] private static extern bool ShowWindow(IntPtr handle, int command);
    [DllImport("user32.dll")] private static extern bool SetForegroundWindow(IntPtr handle);

    internal static bool TryFind(out IntPtr handle, out string title)
    {
        try
        {
            foreach (var process in Process.GetProcessesByName("Connect"))
            {
                using (process)
                {
                    if (process.HasExited) continue;
                    var h = process.MainWindowHandle;
                    if (h == IntPtr.Zero || !IsWindowVisible(h)) continue;
                    handle = h;
                    title = string.IsNullOrWhiteSpace(process.MainWindowTitle)
                        ? "Windows Connect" : process.MainWindowTitle;
                    return true;
                }
            }
        }
        catch { /* Windows can restrict enumerating other processes. */ }
        IntPtr found = IntPtr.Zero;
        string caption = "";
        EnumWindows((h, _) =>
        {
            if (!IsWindowVisible(h)) return true;
            var cls = new StringBuilder(128);
            GetClassName(h, cls, cls.Capacity);
            if (!cls.ToString().Equals("ApplicationFrameWindow", StringComparison.Ordinal))
                return true;
            var buffer = new StringBuilder(256);
            GetWindowText(h, buffer, buffer.Capacity);
            var name = buffer.ToString().Trim();
            if (!(name.Equals("Connect", StringComparison.OrdinalIgnoreCase) ||
                  name.Equals("Wireless Display", StringComparison.OrdinalIgnoreCase) ||
                  name.Equals("จอแสดงผลแบบไร้สาย", StringComparison.OrdinalIgnoreCase) ||
                  name.Equals("เชื่อมต่อ", StringComparison.OrdinalIgnoreCase)))
                return true;
            found = h;
            caption = name;
            return false;
        }, IntPtr.Zero);
        handle = found;
        title = caption;
        return found != IntPtr.Zero;
    }

    internal static bool ShowOnTop(IntPtr handle)
    {
        if (handle == IntPtr.Zero || !IsWindow(handle)) return false;
        ShowWindow(handle, 3); // SW_MAXIMIZE
        return SetForegroundWindow(handle) || IsWindowVisible(handle);
    }
}
