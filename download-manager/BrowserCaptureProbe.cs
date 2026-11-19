using System.Net;
using System.Net.Http.Headers;

namespace XStageDownloadManager;

internal static class BrowserCaptureProbe
{
    private static readonly HttpClient Client = new(new SocketsHttpHandler
    {
        AutomaticDecompression = DecompressionMethods.None,
        AllowAutoRedirect = true
    }) { Timeout = TimeSpan.FromSeconds(7) };

    // Do not cancel the browser's own download for sign-in pages, inaccessible
    // files, or site HTML. Probe without browser cookies or credentials.
    internal static async Task<bool> IsUnauthenticatedFileAsync(string url)
    {
        if (!DownloadEngine.TryParseUrl(url, out _) || SocialVideoDownloader.IsVideoUrl(url)) return false;
        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Get, url);
            request.Headers.AcceptEncoding.ParseAdd("identity");
            request.Headers.Range = new RangeHeaderValue(0, 0);
            using var result = await Client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead);
            if (!result.IsSuccessStatusCode) return false;
            var type = result.Content.Headers.ContentType?.MediaType?.ToLowerInvariant() ?? "";
            if (type is "text/html" or "application/json" or "text/xml" or "application/xml") return false;
            if (result.StatusCode == HttpStatusCode.PartialContent)
                return result.Content.Headers.ContentRange?.From == 0;
            if (result.StatusCode != HttpStatusCode.OK) return false;
            return result.Content.Headers.ContentLength is > 0 ||
                   result.Content.Headers.ContentDisposition != null;
        }
        catch (Exception ex) when (ex is HttpRequestException or OperationCanceledException or IOException)
        {
            return false;
        }
    }
}
