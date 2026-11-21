using System.Buffers.Binary;
using System.Net.Http.Headers;
using System.Text;

namespace XStageDownloadManager;

/// <summary>
/// Resolves the final filename from server metadata instead of treating the
/// opaque UUID in a redirected CDN URL as the original name. Never guesses
/// an executable extension solely from a generic application/octet-stream.
/// </summary>
public static class DownloadFileNaming
{
    private static readonly Dictionary<string, string> MimeExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ["application/pdf"] = ".pdf",
        ["application/zip"] = ".zip",
        ["application/x-zip-compressed"] = ".zip",
        ["application/x-7z-compressed"] = ".7z",
        ["application/x-rar-compressed"] = ".rar",
        ["application/gzip"] = ".gz",
        ["application/x-gzip"] = ".gz",
        ["application/x-tar"] = ".tar",
        ["application/json"] = ".json",
        ["text/plain"] = ".txt",
        ["text/csv"] = ".csv",
        ["image/png"] = ".png",
        ["image/jpeg"] = ".jpg",
        ["image/gif"] = ".gif",
        ["image/webp"] = ".webp",
        ["image/svg+xml"] = ".svg",
        ["audio/mpeg"] = ".mp3",
        ["audio/wav"] = ".wav",
        ["audio/x-wav"] = ".wav",
        ["audio/flac"] = ".flac",
        ["video/mp4"] = ".mp4",
        ["video/webm"] = ".webm",
        ["video/x-matroska"] = ".mkv",
        ["application/x-msdownload"] = ".exe",
        ["application/x-dosexec"] = ".exe",
        ["application/vnd.microsoft.portable-executable"] = ".exe",
        ["application/vnd.microsoft.portable-executable-image"] = ".exe",
        ["application/x-msi"] = ".msi",
        ["application/vnd.ms-cab-compressed"] = ".cab",
        ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"] = ".docx",
        ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"] = ".xlsx",
        ["application/vnd.openxmlformats-officedocument.presentationml.presentation"] = ".pptx"
    };

    public static string CleanName(string input)
    {
        var name = (input ?? "").Trim().Trim('"').Replace('\\', '/').Split('/').Last().Trim();
        foreach (var ch in Path.GetInvalidFileNameChars()) name = name.Replace(ch, '_');
        foreach (var ch in "<>:\"/\\|?*") name = name.Replace(ch, '_');
        name = new string(name.Select(c => char.IsControl(c) ? '_' : c).ToArray());
        name = name.Trim().TrimEnd('.', ' ');
        if (name is "" or "." or "..") return "download";
        // Retain the extension when truncating long filenames.
        if (name.Length > 160)
        {
            var ext = Path.GetExtension(name);
            if (ext.Length > 0 && ext.Length <= 16)
                name = name[..(160 - ext.Length)].TrimEnd('.', ' ') + ext;
            else
                name = name[..160].TrimEnd('.', ' ');
        }
        var stem = Path.GetFileNameWithoutExtension(name).ToUpperInvariant();
        if ((stem is "CON" or "PRN" or "AUX" or "NUL" or "CONIN$" or "CONOUT$" ||
            (stem.Length == 4 && (stem.StartsWith("COM", StringComparison.Ordinal) ||
                                  stem.StartsWith("LPT", StringComparison.Ordinal)) &&
             stem[3] is >= '1' and <= '9')))
            name = "_" + name;
        return name;
    }

    // Signed CDN links frequently have random storage keys instead of real
    // user-facing names. Never present those keys as if they were the
    // original artifact title. Real, readable server metadata always wins.
    public static bool IsOpaqueName(string fileName)
    {
        var value = CleanName(fileName);
        var stem = Path.GetFileNameWithoutExtension(value);
        if (Guid.TryParse(stem, out _)) return true;
        return (stem.Length >= 20 && stem.All(Uri.IsHexDigit)) ||
            (stem.Length >= 10 && stem.All(char.IsAsciiDigit));
    }

    public static bool IsGitHubActionsStorage(string? url)
    {
        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri)) return false;
        var host = uri.Host;
        return (host.StartsWith("productionresults", StringComparison.OrdinalIgnoreCase) ||
                host.StartsWith("pipelinesactions", StringComparison.OrdinalIgnoreCase)) &&
            host.EndsWith(".blob.core.windows.net", StringComparison.OrdinalIgnoreCase) &&
            uri.AbsolutePath.Contains("/actions-results/", StringComparison.OrdinalIgnoreCase);
    }

    public static string FriendlyOpaqueName(string sourceUrl, string fileName)
    {
        var clean = CleanName(fileName);
        if (!IsOpaqueName(clean) || !IsGitHubActionsStorage(sourceUrl))
            return clean;
        var original = Path.GetFileNameWithoutExtension(clean);
        var shortId = original.Replace("-", "", StringComparison.Ordinal);
        if (shortId.Length > 8) shortId = shortId[..8];
        return CleanName("GitHub-Actions-Artifact-" + shortId + Path.GetExtension(clean));
    }

    /// <summary>
    /// Content-Disposition (RFC 5987 filename* before filename) wins over
    /// both requested and redirected URL paths. The origin's named path wins
    /// over a CDN redirect UUID. MIME only supplies a missing extension.
    /// </summary>
    public static string Resolve(string sourceUrl, HttpResponseMessage response)
    {
        var disposition = response.Content.Headers.ContentDisposition;
        var rawName = disposition?.FileNameStar ?? disposition?.FileName ?? "";
        var dispositionName = CleanName(rawName);
        var sourceName = UrlFileName(sourceUrl);
        var finalUrl = response.RequestMessage?.RequestUri?.ToString() ?? sourceUrl;
        var redirectName = UrlFileName(finalUrl);

        // Prefer an explicit meaningful Content-Disposition filename, then a
        // human-readable original URL, then the redirected URL. A generated
        // storage UUID should never supersede a known real filename.
        string selected;
        if (dispositionName != "download" && !IsOpaqueName(dispositionName))
            selected = dispositionName;
        else if (sourceName != "download" && !IsOpaqueName(sourceName))
            selected = sourceName;
        else if (redirectName != "download" && !IsOpaqueName(redirectName))
            selected = redirectName;
        else if (dispositionName != "download")
            selected = dispositionName;
        else if (sourceName != "download")
            selected = sourceName;
        else
            selected = redirectName;

        var type = response.Content.Headers.ContentType?.MediaType;
        var named = WithKnownExtension(selected, type);
        if (!Path.HasExtension(named))
        {
            // Preserve a legitimate source file's suffix when an otherwise
            // authoritative filename is extensionless (e.g. report + .pdf).
            var sourceExtension = Path.GetExtension(sourceName);
            if (sourceExtension.Length is > 1 and <= 16)
                named = CleanName(named + sourceExtension);
        }

        // Raw GitHub Actions CDN URLs do not contain the artifact's original
        // title. Use a clear, deterministic label, not a false guessed title.
        if (IsGitHubActionsStorage(sourceUrl) || IsGitHubActionsStorage(finalUrl))
            return FriendlyOpaqueName(IsGitHubActionsStorage(sourceUrl) ? sourceUrl : finalUrl, named);
        return named;
    }

    public static string UrlFileName(string url)
    {
        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri) ||
            uri.Scheme is not ("http" or "https"))
            return "download";

        // The path, not query parameters (which often contain signed CDN
        // tokens), is the first source for a conventional filename.
        var raw = uri.AbsolutePath.TrimEnd('/').Split('/').LastOrDefault() ?? "";
        string decoded;
        try { decoded = Uri.UnescapeDataString(raw); }
        catch (UriFormatException) { decoded = raw; }
        return CleanName(decoded);
    }

    public static string WithKnownExtension(string name, string? mediaType)
    {
        var clean = CleanName(name);
        if (Path.HasExtension(clean) || string.IsNullOrWhiteSpace(mediaType))
            return clean;
        return MimeExtensions.TryGetValue(mediaType.Split(';')[0].Trim(), out var ext)
            ? CleanName(clean + ext) : clean;
    }

    /// <summary>
    /// Last resort when the response is application/octet-stream without a
    /// filename. Only known byte signatures are accepted. No speculative
    /// extension is attached to opaque or unrecognized content.
    /// </summary>
    public static string? DetectExtension(string path)
    {
        if (!File.Exists(path)) return null;
        var b = new byte[4096];
        int n;
        using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read,
                   FileShare.Read, b.Length))
            n = stream.Read(b);
        var header = b.AsSpan(0, n);
        if (n >= 64 && header[0] == 'M' && header[1] == 'Z')
        {
            var peOffset = BinaryPrimitives.ReadInt32LittleEndian(header.Slice(0x3c, 4));
            if (peOffset >= 64 && peOffset <= n - 4 &&
                header[peOffset] == 'P' && header[peOffset + 1] == 'E' &&
                header[peOffset + 2] == 0 && header[peOffset + 3] == 0)
                return ".exe";
        }
        if (n >= 5 && header.Slice(0, 5).SequenceEqual("%PDF-"u8)) return ".pdf";
        if (n >= 8 && header.Slice(0, 8).SequenceEqual(new byte[] { 137,80,78,71,13,10,26,10 })) return ".png";
        if (n >= 3 && header[0] == 0xff && header[1] == 0xd8 && header[2] == 0xff) return ".jpg";
        if (n >= 6 && (header.Slice(0, 6).SequenceEqual("GIF87a"u8) ||
                       header.Slice(0, 6).SequenceEqual("GIF89a"u8))) return ".gif";
        if (n >= 12 && header.Slice(0, 4).SequenceEqual("RIFF"u8))
        {
            if (header.Slice(8, 4).SequenceEqual("WEBP"u8)) return ".webp";
            if (header.Slice(8, 4).SequenceEqual("WAVE"u8)) return ".wav";
            if (header.Slice(8, 4).SequenceEqual("AVI "u8)) return ".avi";
        }
        if (n >= 4 && header.Slice(0, 4).SequenceEqual("PK\x03\x04"u8)) return ".zip";
        if (n >= 6 && header.Slice(0, 6).SequenceEqual(new byte[] { 0x37,0x7a,0xbc,0xaf,0x27,0x1c })) return ".7z";
        if (n >= 7 && header.Slice(0, 7).SequenceEqual("Rar!\x1a\x07\x00"u8)) return ".rar";
        if (n >= 3 && header.Slice(0, 3).SequenceEqual("ID3"u8)) return ".mp3";
        if (n >= 4 && header.Slice(0, 4).SequenceEqual("fLaC"u8)) return ".flac";
        if (n >= 4 && header.Slice(0, 4).SequenceEqual("OggS"u8)) return ".ogg";
        if (n >= 12 && header.Slice(4, 4).SequenceEqual("ftyp"u8))
        {
            if (header.Slice(8, 4).SequenceEqual("qt  "u8)) return ".mov";
            return ".mp4";
        }
        if (n >= 4 && header.Slice(0, 4).SequenceEqual(new byte[] { 0x1a,0x45,0xdf,0xa3 }))
        {
            var docType = Encoding.ASCII.GetString(b, 0, n).ToLowerInvariant();
            return docType.Contains("webm", StringComparison.Ordinal) ? ".webm"
                : docType.Contains("matroska", StringComparison.Ordinal) ? ".mkv" : null;
        }
        return null;
    }

    public static string EnsureExtension(string suggested, string downloadedPath)
    {
        var clean = CleanName(suggested);
        if (Path.HasExtension(clean)) return clean;
        return CleanName(clean + (DetectExtension(downloadedPath) ?? ""));
    }

    public static string UniqueOutput(string directory, string file)
    {
        var clean = CleanName(file);
        var stem = Path.GetFileNameWithoutExtension(clean);
        var extension = Path.GetExtension(clean);
        var result = Path.Combine(directory, clean);
        for (int n = 1; File.Exists(result) || Directory.Exists(result); n++)
            result = Path.Combine(directory, stem + " (" + n + ")" + extension);
        return result;
    }

    /// <summary>Repair only known, completed, extensionless files. Never
    /// rewrite unknown content, unfinished jobs, or paths outside the user's
    /// selected download directory.</summary>
    public static bool TryRepairCompletedFile(DownloadJob job)
    {
        if (job.Kind != "File" || job.Status != "Completed" ||
            string.IsNullOrWhiteSpace(job.CompletedPath) ||
            Path.HasExtension(job.CompletedPath) || !File.Exists(job.CompletedPath))
            return false;
        try
        {
            var path = Path.GetFullPath(job.CompletedPath);
            var folder = Path.GetFullPath(job.Folder).TrimEnd(Path.DirectorySeparatorChar);
            if (!string.Equals(Path.GetDirectoryName(path)?.TrimEnd(Path.DirectorySeparatorChar),
                               folder, StringComparison.OrdinalIgnoreCase))
                return false;
            var detected = DetectExtension(path);
            if (detected is null) return false;
            var newPath = UniqueOutput(folder, CleanName(Path.GetFileName(path) + detected));
            File.Move(path, newPath);
            job.Name = Path.GetFileName(newPath);
            job.CompletedPath = newPath;
            return true;
        }
        catch (IOException) { return false; }
        catch (UnauthorizedAccessException) { return false; }
        catch (ArgumentException) { return false; }
    }
}
