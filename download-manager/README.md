# X-Stage Download Manager · Windows PC

Independent, original .NET 8 Windows download manager inspired by the *features* (not copied code/assets) of Internet Download Manager.

**Preview v0.1.1 · Build 2** (Windows 10/11 x64).

## Features
- Manual HTTP/HTTPS URL entry, multiline paste, download-folder picker.
- File queue with two concurrent files and an editable **1 / 2 / 4 / 8 / 16 / 32 connections per file** setting.
- The selection is saved as the default for subsequent downloads; paused or failed jobs can be reconfigured individually.
- Changing the partition count for an existing job resets that job’s partial pieces with an explicit confirmation; completed user files are preserved.
- The effective number of segments can be lower than the selected maximum for small files or servers without HTTP Range support.
- Pause, resume and retry, including recovery after interruption when the server supports stable HTTP Range.
- HTTP Range support is probed and checked for correctness instead of silently corrupting downloads.
- History: %LOCALAPPDATA%/X-Stage/Download Manager/downloads.json
- Partials: .xstage-downloads/[id]/ in the destination, removed upon completion.
- Thai desktop interface showing progress, speed, size, status and errors.
- Self-contained Windows runtime packaged into **one Setup EXE** published through GitHub Releases; no Portable ZIP is offered.

## Not included yet
- Chrome/Edge browser interception extension.
- Streaming video capture, DRM bypass, paywall bypass or torrent protocol.
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
