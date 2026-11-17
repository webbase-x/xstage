using System.Runtime.InteropServices;
using System.Text;

namespace XStageMirrorIOSPC;

/// <summary>
/// Displays the native GStreamer/UxPlay video surface FULL SCREEN without
/// SetParent, bitmap copying, capture, or continuous window manipulation.
/// The UxPlay decoder remains responsible for frames/audio timing.
/// </summary>
internal sealed class VideoWindowPresentation
{
    private IntPtr _current;
    private IntPtr _hidden;
    internal bool IsShowing => _current != IntPtr.Zero &&
        IsWindow(_current) && IsWindowVisible(_current);

    // Called only after the process-owned AirPlay TCP session is observed to
    // disconnect. Hiding rather than closing the renderer avoids tearing down
    // the decoding engine, native audio playback and the AirPlay listener.
    internal void HideAfterDisconnect()
    {
        if (_current != IntPtr.Zero && IsWindow(_current))
        {
            _hidden = _current;
            ShowWindow(_hidden, 0); // SW_HIDE
        }
        _current = IntPtr.Zero;
    }

    internal void RestoreAfterReconnect()
    {
        // UxPlay may reuse the same native video HWND for a new stream.
        if (_hidden != IntPtr.Zero && IsWindow(_hidden))
            ShowWindow(_hidden, 8); // SW_SHOWNA, does not steal focus
        _hidden = IntPtr.Zero;
    }

    internal bool HasFreshRenderWindow(int pid)
    {
        var hwnd = FindRenderWindow(pid);
        return hwnd != IntPtr.Zero && hwnd != _hidden;
    }

    internal bool Present(int uxplayPid, System.Windows.Forms.Screen target)
    {
        if (_current != IntPtr.Zero && !IsWindow(_current))
            _current = IntPtr.Zero;
        var hwnd = FindRenderWindow(uxplayPid);
        if (hwnd == IntPtr.Zero) return false;
        if (hwnd == _current) return true; // Never churn GStreamer window geometry per frame.
        _current = hwnd;

        // Native full screen is also requested via UxPlay's -fs + D3D11 sink.
        // This is a defensive fallback when the sink launches border/windowed.
        var style = GetWindowLongPtr(hwnd, -16).ToInt64();
        const long WS_CAPTION = 0x00C00000L;
        const long WS_THICKFRAME = 0x00040000L;
        const long WS_POPUP = unchecked((long)0x80000000L);
        SetWindowLongPtr(hwnd, -16, new IntPtr((style & ~(WS_CAPTION | WS_THICKFRAME)) | WS_POPUP));
        var bounds = target.Bounds;
        SetWindowPos(hwnd, new IntPtr(-1), bounds.X, bounds.Y, bounds.Width,
            bounds.Height, 0x0020 | 0x0040); // FRAMECHANGED | SHOWWINDOW
        return true;
    }

    internal void Reset()
    {
        _current = IntPtr.Zero;
        _hidden = IntPtr.Zero;
    }

    private static IntPtr FindRenderWindow(int pid)
    {
        IntPtr found = IntPtr.Zero;
        EnumWindows((h, _) =>
        {
            if (!IsWindowVisible(h)) return true;
            GetWindowThreadProcessId(h, out uint owner);
            if (owner != (uint)pid) return true;
            int len = GetWindowTextLength(h);
            if (len < 3) return true;
            var sb = new StringBuilder(len + 1);
            GetWindowText(h, sb, sb.Capacity);
            string title = sb.ToString();
            bool render = title.Contains("AirPlay Video Stream", StringComparison.OrdinalIgnoreCase)
                || title.Contains("Direct3D", StringComparison.OrdinalIgnoreCase) &&
                    title.Contains("renderer", StringComparison.OrdinalIgnoreCase);
            if (!render) return true;
            found = h;
            return false;
        }, IntPtr.Zero);
        return found;
    }

    private delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr user);
    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr user);
    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool IsWindow(IntPtr hwnd);
    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool ShowWindow(IntPtr hwnd, int command);
    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowTextLength(IntPtr hwnd);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowText(IntPtr hwnd, StringBuilder text, int maxCount);
    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")]
    private static extern IntPtr GetWindowLongPtr(IntPtr hwnd, int index);
    [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW")]
    private static extern IntPtr SetWindowLongPtr(IntPtr hwnd, int index, IntPtr value);
    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetWindowPos(IntPtr hwnd, IntPtr after,
        int x, int y, int width, int height, uint flags);
}
