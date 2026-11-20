using System.Diagnostics;
using System.Net.NetworkInformation;
using System.Text;

namespace XStageMirrorAndroidPC;

internal static class WindowsPreparation
{
    private const string Capability = "App.WirelessDisplay.Connect~~~~0.0.1.0";
    internal static string ProgressFile => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "X-Stage", "Mirror Android PC", "setup", "state.txt");

    internal static bool HasWirelessAdapter()
    {
        try { return NetworkInterface.GetAllNetworkInterfaces().Any(n =>
            n.NetworkInterfaceType == NetworkInterfaceType.Wireless80211); }
        catch { return false; }
    }

    internal static string? ReadState()
    {
        try { return File.Exists(ProgressFile) ? File.ReadAllText(ProgressFile, Encoding.UTF8) : null; }
        catch (IOException) { return null; }
        catch (UnauthorizedAccessException) { return null; }
    }

    internal static async Task<int> ExecuteAsync(string file)
    {
        void Report(string step, string text)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(file)!);
            var pending = file + ".new";
            File.WriteAllText(pending, step + "|" + text, Encoding.UTF8);
            File.Move(pending, file, overwrite: true);
        }
        try
        {
            Report("1/4", "ตรวจสอบ Windows และอุปกรณ์รับภาพ");
            Report("2/4", "กำลังตรวจสอบฟีเจอร์ Wireless Display");
            var installed = await CheckCapabilityAsync();
            var needsRestart = false;
            if (!installed)
            {
                Report("3/4", "กำลังดาวน์โหลดและติดตั้ง Wireless Display จาก Windows Update · อาจใช้เวลาหลายนาที");
                var exitCode = await RunAsync(Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.System), "dism.exe"),
                    "/Online /Add-Capability /CapabilityName:" + Capability + " /NoRestart");
                if (exitCode is not (0 or 3010))
                    throw new InvalidOperationException("Windows ติดตั้ง Wireless Display ไม่สำเร็จ (" + exitCode + ")");
                needsRestart = exitCode == 3010;
                Report("3/4", "ติดตั้งส่วนประกอบแล้ว · กำลังตรวจสอบอีกครั้ง");
                if (!needsRestart && !await CheckCapabilityAsync())
                    throw new InvalidOperationException("Windows ยังไม่ยืนยันว่าติดตั้ง Wireless Display แล้ว");
            }
            else Report("3/4", "Wireless Display ติดตั้งอยู่แล้ว · ไม่ต้องดาวน์โหลดซ้ำ");

            if (!HasWirelessAdapter())
            {
                Report("4/4", "กำลังค้นหาไดรเวอร์เครือข่ายที่ตรงรุ่นจาก Windows Update");
                needsRestart |= await Task.Run(() => InstallNetworkDrivers(Report));
            }
            else Report("4/4", "ตรวจพบอะแดปเตอร์ Wi-Fi · ไม่ติดตั้งไดรเวอร์โดยไม่จำเป็น");

            if (needsRestart)
            {
                Report("RESTART", "ต้องรีสตาร์ต Windows เพื่อใช้ฟีเจอร์หรือไดรเวอร์ที่เพิ่งติดตั้ง");
                return 3010;
            }
            // A completed DISM or driver transaction is not enough to claim
            // hardware readiness. Miracast still needs a usable Wi-Fi adapter.
            if (!HasWirelessAdapter())
                throw new InvalidOperationException(
                    "ไม่พบอะแดปเตอร์ Wi-Fi หลังค้นหาไดรเวอร์ Windows Update แล้ว " +
                    "เครื่องอาจไม่มีฮาร์ดแวร์ Wi-Fi Direct หรือไม่มีไดรเวอร์ตรงรุ่น");
            Report("DONE", "ติดตั้งส่วนประกอบสำเร็จ · กำลังตรวจหน้าต่างตัวรับ Miracast");
            return 0;
        }
        catch (Exception ex)
        {
            try { Report("ERROR", ex.Message); }
            catch { }
            return 1;
        }
    }

    private static async Task<bool> CheckCapabilityAsync()
    {
        var powershell = Path.Combine(Environment.GetFolderPath(
            Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe");
        var start = new ProcessStartInfo(powershell)
        {
            UseShellExecute = false, RedirectStandardOutput = true,
            RedirectStandardError = true, CreateNoWindow = true
        };
        start.ArgumentList.Add("-NoProfile");
        start.ArgumentList.Add("-NonInteractive");
        start.ArgumentList.Add("-Command");
        start.ArgumentList.Add("$ErrorActionPreference='Stop'; (Get-WindowsCapability -Online -Name '" +
                               Capability + "').State.ToString()");
        using var proc = Process.Start(start)
            ?? throw new InvalidOperationException("Windows PowerShell ไม่เริ่มทำงาน");
        var output = proc.StandardOutput.ReadToEndAsync();
        var errors = proc.StandardError.ReadToEndAsync();
        await proc.WaitForExitAsync();
        var text = (await output).Trim();
        var error = (await errors).Trim();
        if (proc.ExitCode != 0)
            throw new InvalidOperationException("ตรวจ Windows Capability ไม่สำเร็จ: " + error);
        // Compare the exact state: "Uninstalled" must NEVER be accepted as Installed.
        return text.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries)
            .Any(line => line.Trim().Equals("Installed", StringComparison.OrdinalIgnoreCase));
    }

    private static async Task<int> RunAsync(string program, string arguments)
    {
        var start = new ProcessStartInfo(program, arguments)
        {
            UseShellExecute = false, RedirectStandardOutput = true,
            RedirectStandardError = true, CreateNoWindow = true
        };
        using var proc = Process.Start(start)
            ?? throw new InvalidOperationException("Windows ไม่สามารถเริ่มตัวติดตั้ง");
        var outTask = proc.StandardOutput.ReadToEndAsync();
        var errTask = proc.StandardError.ReadToEndAsync();
        await proc.WaitForExitAsync();
        _ = await outTask;
        _ = await errTask;
        return proc.ExitCode;
    }

    private static bool InstallNetworkDrivers(Action<string, string> report)
    {
        // Windows Update selects updates applicable to THIS PC. Only install
        // network-class drivers; never fetch unknown vendor EXEs or replace
        // a working display adapter simply because the receiver is not visible.
        var type = Type.GetTypeFromProgID("Microsoft.Update.Session");
        var collectionType = Type.GetTypeFromProgID("Microsoft.Update.UpdateColl");
        if (type is null || collectionType is null)
            throw new InvalidOperationException("Windows Update Agent ไม่พร้อมใช้งาน");
        dynamic session = Activator.CreateInstance(type)!;
        dynamic available = session.CreateUpdateSearcher().Search(
            "IsInstalled=0 and IsHidden=0 and Type='Driver'");
        dynamic selected = Activator.CreateInstance(collectionType)!;
        for (var i = 0; i < (int)available.Updates.Count; i++)
        {
            dynamic update = available.Updates.Item(i);
            string driverClass;
            try { driverClass = (string)update.DriverClass; }
            catch { continue; }
            if (!string.Equals(driverClass, "Net", StringComparison.OrdinalIgnoreCase))
                continue;
            if (!(bool)update.EulaAccepted) update.AcceptEula();
            selected.Add(update);
        }
        var count = (int)selected.Count;
        if (count == 0)
        {
            report("4/4", "Windows Update ไม่พบไดรเวอร์เครือข่ายที่ตรงกับอุปกรณ์");
            return false;
        }
        report("4/4", "กำลังดาวน์โหลดไดรเวอร์เครือข่าย " + count + " รายการ");
        dynamic downloader = session.CreateUpdateDownloader();
        downloader.Updates = selected;
        dynamic download = downloader.Download();
        if ((int)download.ResultCode is not (2 or 3))
            throw new InvalidOperationException("Windows Update ดาวน์โหลดไดรเวอร์ไม่สำเร็จ");
        report("4/4", "กำลังติดตั้งไดรเวอร์ที่ Windows ตรวจสอบว่าตรงกับอุปกรณ์");
        dynamic installer = session.CreateUpdateInstaller();
        installer.Updates = selected;
        dynamic installed = installer.Install();
        if ((int)installed.ResultCode is not (2 or 3))
            throw new InvalidOperationException("Windows Update ติดตั้งไดรเวอร์ไม่สำเร็จ");
        return (bool)installed.RebootRequired;
    }
}
