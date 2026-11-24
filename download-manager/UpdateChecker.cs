using System.Net;
using System.Net.Http.Headers;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace XStageDownloadManager;

public sealed record DownloadManagerRelease(string Version, int Build, string Filename, string Url, string Sha256, long Size);

public static class UpdateChecker
{
    public const string CurrentVersion = "0.2.24";
    public const int CurrentBuild = 27;
    public const string FeedUrl = "https://webbase-x.github.io/xstage/downloads/download-manager-preview-latest.json";

    private static readonly HttpClient Client = new(new HttpClientHandler
    {
        AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate,
        AllowAutoRedirect = true
    }) { Timeout = TimeSpan.FromSeconds(12) };

    public static bool IsNewer(string version, int build) =>
        Version.TryParse(version, out var incoming) &&
        Version.TryParse(CurrentVersion, out var current) &&
        (incoming.CompareTo(current) > 0 || incoming == current && build > CurrentBuild);

    // A GitHub Pages manifest is just a notification hint. It never executes an
    // installer and may only link to the exact canonical GitHub EXE release asset.
    public static DownloadManagerRelease? Parse(string json)
    {
        if (string.IsNullOrWhiteSpace(json) || json.Length > 65536) return null;
        // A temporarily stale/malformed feed must not crash update checks.
        JsonDocument document;
        try { document = JsonDocument.Parse(json.TrimStart('\uFEFF')); }
        catch (JsonException) { return null; }
        using var parsed = document;
        var obj = parsed.RootElement;
        if (obj.ValueKind != JsonValueKind.Object) return null;
        string field(string key) =>
            obj.TryGetProperty(key, out var el) && el.ValueKind == JsonValueKind.String
                ? el.GetString() ?? "" : "";
        if (!obj.TryGetProperty("available", out var availability) ||
            availability.ValueKind != JsonValueKind.True ||
            field("channel") != "preview") return null;
        var version = field("version");
        if (!Version.TryParse(version, out _) || !Regex.IsMatch(version, @"^\d+\.\d+\.\d+$")) return null;
        if (!obj.TryGetProperty("build", out var buildElement) ||
            buildElement.ValueKind != JsonValueKind.Number ||
            !buildElement.TryGetInt32(out var build) || build < 1) return null;
        var file = $"X-Stage-Download-Manager-v{version}-build{build}-win-x64-Setup.exe";
        var expected = $"https://github.com/webbase-x/xstage/releases/download/xstage-download-manager-v{version}-build{build}-preview/{file}";
        if (field("file") != file || field("download_url") != expected) return null;
        var hash = field("sha256");
        if (!Regex.IsMatch(hash, @"^[a-fA-F0-9]{64}$")) return null;
        if (!obj.TryGetProperty("size_bytes", out var sizeElement) ||
            sizeElement.ValueKind != JsonValueKind.Number ||
            !sizeElement.TryGetInt64(out var size) || size < 1024) return null;
        return new DownloadManagerRelease(version, build, file, expected, hash.ToLowerInvariant(), size);
    }

    public static async Task<DownloadManagerRelease?> CheckAsync(CancellationToken cancellation = default)
    {
        // GitHub Pages/CDN can retain the previous manifest after publication.
        // A per-check cache key avoids a stale "no newer version" response.
        using var request = new HttpRequestMessage(HttpMethod.Get,
            FeedUrl + "?check=" + DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        request.Headers.CacheControl = new CacheControlHeaderValue { NoCache = true, NoStore = true };
        request.Headers.UserAgent.ParseAdd($"XStageDownloadManager/{CurrentVersion}");
        using var response = await Client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellation);
        response.EnsureSuccessStatusCode();
        await using var stream = await response.Content.ReadAsStreamAsync(cancellation);
        using var reader = new StreamReader(stream);
        var content = await reader.ReadToEndAsync(cancellation);
        return Parse(content);
    }
}
