# X-Stage Download Manager · Windows PC

Independent X-Stage .NET 8 Windows download manager with original UI, icons and branding. It implements standard transfer features without copying another application's design, code or artwork.

**Latest verified public Setup EXE: v0.2.21 · Build 24** (Windows 10/11 x64). Newer desktop UI changes remain development-only until the Windows CI, Release Setup EXE and public SHA-256 manifest agree.

## Build 23 recovery preview

- Network link loss pauses currently running/queued downloads without deleting partial bytes; link restoration restarts only transfers flagged as network-interrupted, after their canceled workers have released download slots.
- Closing the app records active-transfer recovery intent in SQLite. On the next launch the user is asked whether to resume, while deliberately paused downloads remain paused. A second crash before answering retains the recovery prompt.
- Explicitly pausing an offline job cancels automatic recovery. Network-link availability is not the same as internet or site availability, so server errors still rely on the bounded HTTP retry policy.
- Windows Sleep/resume and offline/online transitions still require physical-device validation. Named queues and priority filters are available; automatic start/stop schedules are not yet implemented.

## Live Background Recorder — development, not yet released

- In **สื่อ → บันทึกไลฟ์สด**, check **เฝ้ารอไลฟ์อัตโนมัติ** (on by default), confirm the user's recording rights, choose a direct public HLS/DASH or supported public-platform live URL and a polling interval of **15/30/60 seconds**. The application checks HLS/DASH manifest state or yt-dlp `live_status` metadata only; it **does not open a browser/player or play a video**. A VOD playlist with `#EXT-X-ENDLIST`, a master playlist alone and an upcoming platform video are not treated as live.
- Once on-air status is detected, the existing Live Capture engine starts recording one session automatically. On stream end or Stop it preserves the original MKV and splits the recording into speech-pause-aligned MP4 clips after capture. This is a **one-session watcher**, not a perpetual channel recorder.
- Minimize the Live Capture window while waiting/recording to keep it running in the **Windows system tray**. Double-click the icon to restore, or use its menu to stop/cancel. The Windows app and PC must remain running; **closing the app, logging out, sleep/shutdown or switching off the PC is not unattended cloud recording**.
- The watcher does not use login cookies, protected playback, DRM or private APIs. Some platforms/channel URLs do not expose usable public live status or muxed audio/video streams, so they may remain in the waiting state or report a limitation. Direct manifests may change or expire. Network faults are reported and retried at the selected bounded cadence; explicit access-denied errors stop monitoring.
- Do not label this version published until a new Windows CI, verified GitHub Release Setup EXE and matching SHA-256 manifest all pass.

## Live Capture — development, not yet released

- Open **สื่อ → บันทึกไลฟ์สด · ตัดคลิปตามช่วงหยุดพูด** or the **บันทึกไลฟ์สด** command-deck button. This opens a separate, non-modal window and leaves normal downloads and their SQLite history unchanged.
- For streams the user is authorized to record, accept direct HTTP(S) HLS `.m3u8` and DASH `.mpd` playlists. Public supported video-platform links are resolved via the bundled yt-dlp and may fail when a single audio+video stream is not exposed. No cookies, restricted/private media, subscriptions, DRM bypass or credentials are handled.
- Choose approximate target clip duration: **1 / 3 / 5 / 10 / 15 / 20 / 30 / 60 minutes**. Capture the live session to a uniquely named `master.recording.mkv`, then **after the user stops or the stream ends**, use FFmpeg audio silence detection (`-35 dB`, minimum (0.6) s) and transcode MP4 pieces at detected quiet intervals. Never force an arbitrary clock-time cut; if no suitable pause exists, keep the remainder as one longer clip.
- Preserve the original MKV, even if splitting fails, is cancelled, or the network interrupts; place generated clips in the unique session directory and never overwrite user files. Clip outputs are not added to the legacy queue/SQLite in this initial phase. App shutdown is blocked while a live recorder is finalizing; the recorder offers safe cancel of post-processing while retaining the original.
- Silence detection is **not automatic speech understanding**. Background noise, music and atypical speech may defeat the heuristic, so a semantic promise that every cut is exactly between sentences is not possible. Continuous on-the-fly splitting and verified field behavior on actual livestream platforms remain future work.
- This code has deterministic planner/URL tests and a synthetic FFmpeg/FFprobe smoke test included in Windows CI, but **Windows build, real-device, real live platform and Release/manifest gates still require verification**. Do not offer it as a new Setup EXE before those gates pass.

## Features
- **Original X-Stage Command Center UI (development)**: custom dark-teal masthead and horizontal command deck; antialiased vector icons drawn in-app, not copied from any competitor; live active/queued/completed/failed counts in navigation; searchable transfer desk (Ctrl+F), real file-type icons, priority queue categories and a multi-column transfer grid; seven grouped menus for jobs, queues/priorities, media, files, settings/diagnostics, views and help. Queue assignment shows the selected named queue; commands remain connected to the existing downloader and its SQLite state. The approved large-icon command bar, branded sidebar, tabbed file details, live speed chart and per-job session diagnostics are implemented in source. The chart uses real elapsed-time bytes instead of mock values and remains blank when there is no traffic. Existing sorting, context-menu actions, progress, speed/ETA, category filtering and download history remain available. The visual mockup also depicts manual media merging and scheduled downloads: those are roadmap items, not implemented buttons. Changes await Windows build and real-screen DPI/regression gates before release.
- **Social video links:** YouTube, YouTube Shorts, TikTok, Facebook Reels/videos, Instagram Reels (publicly accessible posts only).
- Click any finished, failed or paused video row and choose **ดาวน์โหลดวิดีโอใหม่ / เปลี่ยนคุณภาพและรูปแบบไฟล์**. Select quality, output container, segment count and destination folder in the dialog; this creates a separate queued job and a unique output name so the old media and its history are not overwritten, even when downloading the same quality/format again.\n- Choose best video quality or 1080p/720p/480p separately from the output container: **MP4 (default)**, MKV, WEBM or MP3 (audio only). MP4 now uses a preserved source MKV (where available) and a separate FFmpeg remux/transcode to H.264/AAC. Only after FFprobe confirms streams, duration and complete MP4 atoms (including moov) does it appear as Completed; an invalid file is never reported as a green 100%. Conversion may take longer and the source is preserved on failure. Previous malformed completed MP4 downloads are marked Failed on next launch, and backed up rather than deleted if the user retries.
- The installer bundles pinned official yt-dlp, FFmpeg/ffprobe and Deno executables, each checked against a release SHA-256 during Windows CI. No downloads or extra installation of tools are required after installing the one Setup EXE.
- yt-dlp handles platform manifests, muxing separate video/audio with FFmpeg, and resumable fragments; the original HTTP Range engine handles ordinary file links as before.
- For social streams, the 1–32 setting controls the maximum number of concurrent downloadable media fragments. It is **not** a guarantee of that many HTTP byte-range connections.
- File queue with two concurrent files and an editable **1 / 2 / 4 / 8 / 16 / 32 connections per file** setting.
- The selection is saved as the default for subsequent downloads; paused or failed jobs can be reconfigured individually.
- Changing the partition count for an existing job resets that job’s partial pieces with an explicit confirmation; completed user files are preserved.
- The effective number of segments can be lower than the selected maximum for small files or servers without HTTP Range support.
- **Network resilience (Build 20)**: each HTTP Range chunk retries from its own verified physical `.part` byte offset after a connection drop/timeout; requests use 45-second inactivity timeouts and bounded exponential backoff. HTTP 408/425/429/5xx are retried but permanent 403/404/401 errors fail promptly; `Retry-After` is honored up to 2 minutes. If the server changes/ignores Range mid-download, discard only unsafe temporary chunks and restart as HTTP 200 single-stream; single-stream drops retry from zero without appending corrupted bytes. Configure 1–10 attempts from **การดาวน์โหลด → กำหนดจำนวนครั้งลองใหม่...**, saved in SQLite. Transfer status reports retries instead of showing a frozen download.\n- Pause, resume and retry, including recovery after interruption when the server supports stable HTTP Range.
- HTTP Range support is probed and checked for correctness instead of silently corrupting downloads.
- History and resumable job/chunk offsets: `%LOCALAPPDATA%/X-Stage/Download Manager/xstage_downloads.sqlite3` (SQLite WAL, atomic transactions; old `downloads.json` is read once and retained untouched as a migration backup). The default connection count is also persisted in SQLite. The engine checkpoints transfers every 2 seconds, writes status immediately, and reports persistence errors in the UI.
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

## Configurable segmented transfers

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
