# X-Stage Download Manager · Windows PC

Independent, original .NET 8 Windows download manager inspired by the *features* (not copied code/assets) of Internet Download Manager.

**Preview v0.2.1 · Build 4** (Windows 10/11 x64).

## Features
- Manual HTTP/HTTPS URL entry, multiline paste, download-folder picker.
- **Social video links:** YouTube, YouTube Shorts, TikTok, Facebook Reels/videos, Instagram Reels (publicly accessible posts only).
- Choose the best available video+audio, 1080p, 720p or 480p, or extract MP3 audio. Available formats depend on the source.
- The installer bundles pinned official yt-dlp, FFmpeg/ffprobe and Deno executables, each checked against a release SHA-256 during Windows CI. No downloads or extra installation of tools are required after installing the one Setup EXE.
- yt-dlp handles platform manifests, muxing separate video/audio with FFmpeg, and resumable fragments; the original HTTP Range engine handles ordinary file links as before.
- For social streams, the 1–32 setting controls the maximum number of concurrent downloadable media fragments. It is **not** a guarantee of that many HTTP byte-range connections.
- File queue with two concurrent files and an editable **1 / 2 / 4 / 8 / 16 / 32 connections per file** setting.
- The selection is saved as the default for subsequent downloads; paused or failed jobs can be reconfigured individually.
- Changing the partition count for an existing job resets that job’s partial pieces with an explicit confirmation; completed user files are preserved.
- The effective number of segments can be lower than the selected maximum for small files or servers without HTTP Range support.
- Pause, resume and retry, including recovery after interruption when the server supports stable HTTP Range.
- HTTP Range support is probed and checked for correctness instead of silently corrupting downloads.
- History: %LOCALAPPDATA%/X-Stage/Download Manager/downloads.json
- Partials: .xstage-downloads/[id]/ in the destination, removed upon completion.
- Thai desktop interface showing progress, speed, size, status and errors.
- Per-segment progress bar shows actual bytes received in each HTTP range, not cosmetic stripes; social video downloads use unified progress.
- Completed entries turn green. Click a finished filename to open its file or containing folder.
- Startup checks and a **ตรวจสอบอัปเดต** button query the verified X-Stage release manifest. A newer version prompts before opening the canonical Setup EXE link; no silent installation.
- Optional Chrome/Edge connector is bundled in the installer, loaded and paired by the user; auto-capture is OFF by default. Context-menu handoff is available.
- Self-contained Windows runtime packaged into **one Setup EXE** published through GitHub Releases; no Portable ZIP is offered.

## Not included yet
- Chrome/Edge interception is available only after users install and enable the optional browser extension.
- DRM/protected streams, login-only or private posts, age-gated/subscriber-only content, paywall bypass, or torrent protocol.
- Live streaming capture and authenticated browser sessions.
- Scheduled downloads and speed limits.
- Browser cookies, login handling or application auto-update.

## Build
1. Install .NET 8 SDK and Python Pillow on Windows.
2. Run: python download-manager/generate_icon.py
3. Run: dotnet publish download-manager/XStageDownloadManager.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true
4. For the only publicly offered download, use the verified Windows Setup EXE from GitHub Releases. The workflow publishes no ZIP asset.

The Preview is not code-signed or fully tested on a real Windows PC. Only show the direct EXE download after GitHub Release publication and SHA-256 verification. Downloads without server Range support restart from zero when interrupted.

## Configurable IDM-style segments

Select **จำนวนส่วน** in the third row (1, 2, 4, 8, 16 or 32). The selected number becomes the default for new jobs. To change an existing job, pause it completely, select it, then choose **ใช้กับรายการ**; the app explains that previous temporary pieces must be restarted because segment boundaries change. The list reports actual / requested segments. A server can limit concurrency, and more connections do not guarantee better throughput.

## Supported video use and limitations

Paste a link to a video you own or are authorized to download. Select **วิดีโอ** quality; the app detects YouTube, TikTok, Facebook/Instagram Reels, while ordinary files still use the original segmented downloader. The app downloads one post at a time (no playlist or channel extraction) and writes the final video or MP3 into the chosen folder. The extractor output name uses the actual title and platform video ID. Pausing terminates yt-dlp and restarting continues saved fragments where the site supports it. Failed extraction may mean the content is private, requires sign-in, is DRM-protected, unavailable in the region, or the site's extractors have changed; no workaround for restricted media is provided.

Platform layouts and extractors change, so the app cannot guarantee access to every public video. The offline CI tests cover URL classification, command security and original file downloads. A separate smoke test checks all bundled tools; end-to-end downloads from live platforms require follow-up testing on the user's PC.

### Third-party notices

Bundled binaries are maintained independently: [yt-dlp 2026.10.26](https://github.com/yt-dlp/yt-dlp/releases/tag/2026.10.26), [Deno 2.9.8](https://github.com/denoland/deno/releases/tag/v2.9.8) and [yt-dlp/FFmpeg-Builds 2026-11-16](https://github.com/yt-dlp/FFmpeg-Builds/releases/tag/autobuild-2026-11-16-23-35). The installer includes a THIRD-PARTY-NOTICES file and corresponding source links. FFmpeg binary is a GPL build; yt-dlp and Deno have separate licenses. No IDM binaries/code are used.

## Browser integration (optional)

1. Open **เชื่อม Chrome / Edge** in X-Stage Download Manager.
2. Open chrome://extensions (Chrome) or edge://extensions (Edge), enable **Developer mode**, and choose **Load unpacked**.
3. Select the directory shown by the app: <installation directory>/browser-extension.
4. Copy the extension ID from the browser extension page into the app and click **เชื่อมต่อ**. The app registers a per-user Windows Native Messaging host for Chrome and Edge; no local HTTP port or remote server is exposed.
5. Open the extension popup to check the connection. Enable automatic capture only when wanted. You can also right-click a link and choose **ดาวน์โหลดด้วย X-Stage**.

For automatic handoff, the app probes anonymous direct-file access before acknowledging the job. The browser's original download is cancelled only after the desktop app accepts the URL. If the host is unavailable, the source requires browser credentials, or the source is HTML, the original browser download remains untouched. Private files, login-only downloads, and DRM media are not intercepted.

## Update notifications

On startup, X-Stage checks release metadata over HTTPS with a short timeout. **ตรวจสอบอัปเดต** repeats the check. A valid update must have a matching version/build, SHA-256, size and canonical GitHub Releases .exe URL. Builds alone do not count as published updates. An unavailable or outdated release feed does not interrupt downloads; installation is always user-confirmed.

**Publication note:** The Windows build publishes an Actions artifact containing only a Setup EXE. Publishing a direct .exe through GitHub Releases depends on repository token write permissions; the portal points only to an already verified release until a newer EXE has actually been published.
