using System.Diagnostics;
using System.Runtime.InteropServices;

namespace XStageMirrorAndroidPC;

/// <summary>
/// Launch the Microsoft Miracast receiver directly. Never pass an unknown
/// shell:AppsFolder string to explorer.exe: on Windows without that app this
/// can open an unrelated File Explorer window instead of the receiver.
/// </summary>
internal static class MiracastAppLauncher
{
    // Windows 11 22H2+ Wireless Display and Windows 10 legacy Connect identities.
    // These are receiver packages, not arbitrary user-supplied app identifiers.
    private static readonly string[] KnownReceiverApps =
    [
        "Microsoft.WirelessDisplay.Connect_cw5n1h2txyewy!App",
        "Microsoft.PPIProjection_cw5n1h2txyewy!Microsoft.PPIProjection",
        "Microsoft.PPIProjection_cw5n1h2txyewy!App"
    ];

    [ComImport]
    [Guid("2E941141-7F97-4756-BA1D-9DECDE894A3D")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IApplicationActivationManager
    {
        [PreserveSig]
        int ActivateApplication(
            [MarshalAs(UnmanagedType.LPWStr)] string appUserModelId,
            [MarshalAs(UnmanagedType.LPWStr)] string? arguments,
            uint options,
            out uint processId);
    }

    [ComImport]
    [Guid("45BA127D-10A8-46EA-8AB7-56EA9078943C")]
    private class ApplicationActivationManager { }

    internal static bool TryStart(out string error)
    {
        // Windows 10 Connect.exe is a real executable and may be launched
        // directly. Do not launch Explorer even if it is missing.
        var connect = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.Windows),
            "System32", "Connect.exe");
        if (File.Exists(connect))
        {
            try
            {
                using var process = Process.Start(new ProcessStartInfo(connect)
                {
                    UseShellExecute = true
                });
                if (process is not null)
                {
                    error = "";
                    return true;
                }
            }
            catch (Exception ex)
            {
                // The packaged Windows receiver can still be present; try it.
                error = "Connect.exe: " + ex.Message;
            }
        }

        object? instance = null;
        try
        {
            instance = new ApplicationActivationManager();
            var manager = (IApplicationActivationManager)instance;
            var lastHresult = 0;
            foreach (var appId in KnownReceiverApps)
            {
                // AO_NOERRORUI prevents extra Windows error popups. A returned
                // process ID only means activation succeeded, not that casting works.
                var hr = manager.ActivateApplication(appId, null, 0x00000002, out _);
                if (hr == 0)
                {
                    error = "";
                    return true;
                }
                lastHresult = hr;
            }
            error = "ไม่พบแอป Wireless Display/Connect ที่ลงทะเบียนใน Windows " +
                "(HRESULT 0x" + lastHresult.ToString("X8") + "). " +
                "โปรดติดตั้ง Wireless Display ผ่านการเตรียมระบบใน X-Stage";
            return false;
        }
        catch (Exception ex)
        {
            error = "Windows เปิดตัวรับ Wireless Display ไม่ได้: " + ex.Message;
            return false;
        }
        finally
        {
            if (instance is not null && Marshal.IsComObject(instance))
                Marshal.ReleaseComObject(instance);
        }
    }
}
