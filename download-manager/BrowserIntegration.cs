using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.Win32;

namespace XStageDownloadManager;

// Native messaging is only activated after the user loads the optional
// unpacked extension and explicitly registers its Chrome/Edge extension ID.
internal static class BrowserIntegration
{
    internal static string ExtensionFolder => Path.Combine(AppContext.BaseDirectory, "browser-extension");
    private static string DataFolder => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "X-Stage", "Download Manager");
    private static string ManifestPath => Path.Combine(DataFolder, "browser-native-host.json");

    internal static bool IsValidExtensionId(string value) =>
        Regex.IsMatch(value.Trim(), "^[a-p]{32}$", RegexOptions.CultureInvariant);

    internal static string BuildNativeHostManifest(string exePath, IEnumerable<string> extensionIds)
    {
        var origins = extensionIds.Where(IsValidExtensionId)
            .Select(x => "chrome-extension://" + x.Trim() + "/")
            .Distinct(StringComparer.Ordinal).OrderBy(x => x).ToArray();
        if (origins.Length == 0) throw new ArgumentException("ต้องมี Extension ID ที่ถูกต้อง");
        return JsonSerializer.Serialize(new
        {
            name = NativeMessagingBridge.HostName,
            description = "X-Stage Download Manager Windows desktop integration",
            path = Path.GetFullPath(exePath),
            type = "stdio",
            allowed_origins = origins
        }, new JsonSerializerOptions { WriteIndented = true });
    }

    internal static bool IsAllowedOrigin(string origin)
    {
        try
        {
            using var json = JsonDocument.Parse(File.ReadAllText(ManifestPath));
            return json.RootElement.GetProperty("allowed_origins")
                .EnumerateArray().Any(x => x.ValueKind == JsonValueKind.String &&
                                           x.GetString() == origin);
        }
        catch (Exception ex) when (ex is IOException or JsonException or InvalidOperationException or KeyNotFoundException)
        {
            return false;
        }
    }

    internal static void Register(string extensionId)
    {
        extensionId = extensionId.Trim();
        if (!IsValidExtensionId(extensionId))
            throw new ArgumentException("Extension ID ต้องมีอักษร a ถึง p จำนวน 32 ตัว");
        if (!Directory.Exists(ExtensionFolder))
            throw new DirectoryNotFoundException("ไม่พบโฟลเดอร์ส่วนขยาย Chrome/Edge ในตัวติดตั้ง");

        Directory.CreateDirectory(DataFolder);
        var ids = new HashSet<string>(StringComparer.Ordinal) { extensionId };
        try
        {
            using var current = JsonDocument.Parse(File.ReadAllText(ManifestPath));
            foreach (var origin in current.RootElement.GetProperty("allowed_origins").EnumerateArray())
            {
                var value = origin.GetString() ?? "";
                if (value.StartsWith("chrome-extension://", StringComparison.Ordinal) && value.EndsWith("/", StringComparison.Ordinal))
                {
                    var id = value["chrome-extension://".Length..^1];
                    if (IsValidExtensionId(id)) ids.Add(id);
                }
            }
        }
        catch (Exception ex) when (ex is IOException or JsonException or InvalidOperationException or KeyNotFoundException)
        {
            // First pairing has no manifest. Invalid legacy manifests are replaced.
        }
        if (ids.Count > 12) throw new InvalidOperationException("ลงทะเบียนส่วนขยายมากเกินไป กรุณาลบการเชื่อมต่อเดิม");
        var exe = Environment.ProcessPath ?? Application.ExecutablePath;
        File.WriteAllText(ManifestPath, BuildNativeHostManifest(exe, ids));

        foreach (var path in new[]
        {
            @"Software\Google\Chrome\NativeMessagingHosts\" + NativeMessagingBridge.HostName,
            @"Software\Microsoft\Edge\NativeMessagingHosts\" + NativeMessagingBridge.HostName
        })
        {
            using var key = Registry.CurrentUser.CreateSubKey(path, writable: true);
            if (key == null) throw new IOException("ไม่สามารถลงทะเบียน Native Messaging ใน Windows ได้");
            key.SetValue("", ManifestPath, RegistryValueKind.String);
        }
    }
}
