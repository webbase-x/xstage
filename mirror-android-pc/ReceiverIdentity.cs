using System.Globalization;
using System.Security.Cryptography;

namespace XStageMirrorAndroidPC;

internal static class ReceiverIdentity
{
    // Both standalone apps on the same Windows account deliberately share
    // a stable randomized number. It is never regenerated during normal startup.
    private static readonly Lazy<int> DeviceNumber = new(ReadOrCreate);
    internal static int Number => DeviceNumber.Value;
    internal static string DisplayName => "X-Stage Mirror PC No." +
        Number.ToString("D4", CultureInfo.InvariantCulture);

    private static int ReadOrCreate()
    {
        var path = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "X-Stage", "Mirror", "receiver-number.txt");
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        for (int attempt = 0; attempt < 4; attempt++)
        {
            try
            {
                if (File.Exists(path) &&
                    int.TryParse(File.ReadAllText(path).Trim(), NumberStyles.None,
                        CultureInfo.InvariantCulture, out int number) &&
                    number is >= 1000 and <= 9999)
                    return number;
                using var stream = new FileStream(path, FileMode.CreateNew,
                    FileAccess.Write, FileShare.None);
                int fresh = RandomNumberGenerator.GetInt32(1000, 10000);
                using var writer = new StreamWriter(stream);
                writer.Write(fresh.ToString("D4", CultureInfo.InvariantCulture));
                return fresh;
            }
            catch (IOException) when (attempt < 3)
            {
                System.Threading.Thread.Sleep(70);
            }
        }
        // Do not silently change a previously assigned number if persistence fails.
        throw new IOException("ไม่สามารถอ่านหรือบันทึกหมายเลขเครื่องรับใน AppData ได้");
    }
}
