# X-Stage Download Manager · Windows PC

Independent, original .NET 8 Windows download manager inspired by the *features* (not copied code/assets) of Internet Download Manager.

**Preview v0.2.15 · Build 18** (Windows 10/11 x64).

## Features
- **IDM-inspired desktop UI**: dark menu bar and icon+caption toolbar, compact expandable URL/quality form (Ctrl+N), category tree (active/queued/incomplete/completed and video/music/documents/programs/archive/other), transfer table with queue order, real file type (MP4/MKV/EXE/ZIP/PDF etc.), progress, speed, ETA, date, parts and description. Click any column header to sort by its real value, click again for descending order, with an arrow showing direction. Sort and filters keep row actions attached to the correct original job ID. **+ เพิ่ม URL** and Ctrl+N auto-fill the URL field when valid HTTP(S) links are already in the clipboard without starting the download or overriding existing input. Toolbar actions and per-file menu remain functional; filters map back to original job IDs and never act on an unrelated row. Columns scroll instead of overlapping at small widths.\n- Manual HTTP/HTTPS URL entry, multiline paste, download-folder picker. Resolve the final file name from HTTP Content-Disposition (including UTF-8 filename*), original URL, response MIME type, or a verified file signature when the CDN uses an opaque UUID. Completed extensionless downloads from older builds are safely renamed on next startup only if the existing file type is unambiguous; never overwrite originals. The video quality and MP4/MKV/WEBM/MP3 rows appear only for supported social-media video links, and collapse completely for ordinary file URLs.
- **Social video links:** YouTube, YouTube Shorts, TikTok, Facebook Reels/videos, Instagram Reels (publicly accessible posts only).
- Click any finished, failed or paused video row and choose **ดาวน์โหลดวิดีโอใหม่ / เปลี่ยนคุณภาพและรูปแบบไฟล์**. Select quality, output container, segment count and destination folder in the dialog; this creates a separate queued job and a unique output name so the old media and its history are not overwritten, even when downloading the same quality/format again.\n- Choose best video quality or 1080p/720p/480p separately from the output container: **MP4 (default)**, MKV, WEBM or MP3 (audio only). MP4 now uses a preserved source MKV (where available) and a separate FFmpeg remux/transcode to H.264/AAC. Only after FFprobe confirms streams, duration and complete MP4 atoms (including moov) does it appear as Completed; an invalid file is never reported as a green 100%. Conversion may take longer and the source is preserved on failure. Previous malformed completed MP4 downloads are marked Failed on next launch, and backed up rather than deleted if the user retries.
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
- UTF-8 console decoding and independent post-download path receipt for Thai/Unicode filenames.
- The toolbar opens an explicit Open file / Open folder choice; incomplete/failed entries can still open their destination folder.
- Per-segment progress bar shows actual bytes received in each HTTP range, not cosmetic stripes; social video downloads use unified progress.
- Completed entries show a continuous full-width solid green 100.0% progress bar regardless of stale HTTP segment measurements; non-finalized jobs are capped at displayed 99.9% until final verification/FFmpeg merge finishes. Click a finished filename to open its file or containing folder.
- Startup and manual update checks use the verified X-Stage Release manifest. After user approval, the app downloads the EXE itself and validates size and SHA-256. The old app stays visible until the separate update window is on screen, counts down 3 seconds, and closes for Windows to replace the EXE. The update window remains visible while installing and relaunches the new app immediately after verified success, before optional legacy cleanup. Active transfers are paused and their resumable state is saved.
- Optional **ดาวน์โหลดอัตโนมัติ** Chrome/Edge connector is bundled in the installer, loaded and paired by the user; auto-capture is OFF by default. Context-menu handoff is available.
- Self-contained Windows runtime packaged into **one Setup EXE** published through GitHub Releases; no Portable ZIP is offered. The x64 application now installs in `C:\\Program Files\\X-Stage\\Download Manager` (Inno `{autopf}`), requires Windows administrator permission at install/update, and always relaunches the Program Files executable after successful migration. A legacy per-user installation is uninstalled only after the new executable passes verification. Download history and preferences remain in `%LOCALAPPDATA%` rather than Program Files. The Setup EXE is currently unsigned, so Windows may show an unknown-publisher UAC prompt.

## Not included yet
- Chrome/Edge interception is available only after users install and enable the optional browser extension.
- DRM/protected streams, login-only or private posts, age-gated/subscriber-only content, paywall bypass, or torrent protocol.
- Live streaming capture and authenticated browser sessions.
- Scheduled downloads and speed limits.
- Browser cookies and login handling. Auto-install is user-approved rather than unattended.

## Build
1. Install .NET 8 SDK and Python Pillow on Windows.
2. Run: python download-manager/generate_icon.py
3. Run: dotnet publish download-manager/XStageDownloadManager.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true
4. For the only publicly offered download, use the verified Windows Setup EXE from GitHub Releases. The workflow publishes no ZIP asset.

The Preview is not code-signed or fully tested on a real Windows PC. Only show the direct EXE download after GitHub Release publication and SHA-256 verification. Downloads without server Range support restart from zero when interrupted.

## Configurable IDM-style segments

Select **จำนวนส่วน** in the third row (1, 2, 4, 8, 16 or 32). The selected number becomes the default for new jobs. To change an existing job, pause it completely, select it, then choose **ใช้กับรายการ**; the app explains that previous temporary pieces must be restarted because segment boundaries change. The list reports actual / requested segments. A server can limit concurrency, and more connections do not guarantee better throughput.

## Supported video use and limitations

Paste a link to a video you own or are authorized to download. Select **วิดีโอ** quality and **รูปแบบไฟล์** independently (MP4 is initially selected); the app detects YouTube, TikTok, Facebook/Instagram Reels, while ordinary files still use the original segmented downloader. The app downloads one post at a time (no playlist or channel extraction) and writes the final video or MP3 into the chosen folder. The extractor output name uses the actual title and platform video ID. Pausing terminates yt-dlp and restarting continues saved fragments where the site supports it. Failed extraction may mean the content is private, requires sign-in, is DRM-protected, unavailable in the region, or the site's extractors have changed; no workaround for restricted media is provided.

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

On startup, X-Stage checks release metadata over HTTPS with a short timeout. **ตรวจสอบอัปเดต** repeats the check. A valid update must have a matching version/build, SHA-256, size and canonical GitHub Releases .exe URL. After confirmation the app downloads the Setup EXE with persistent `.partial` resume, bounded retry and transparent HTTP error logging, verifies SHA-256 and byte size, and starts a detached copy of the app to wait for shutdown. That helper installs silently and restarts the installed app only after successful installation and file-version validation. Failed checks leave the existing app running. Failed downloads keep partial bytes for HTTP Range resume and offer the official GitHub Release link, with details recorded in `%LOCALAPPDATA%/X-Stage/Download Manager/updates/update-download.log`. No installer is launched from an unverified download. Existing download jobs are paused and saved before exit.

**Publication note:** The Windows build publishes an Actions artifact containing only a Setup EXE. Publishing a direct .exe through GitHub Releases depends on repository token write permissions; the portal points only to an already verified release until a newer EXE has actually been published.
