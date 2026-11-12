# X-Stage Song Studio — Windows PC Source Launcher (Preview)

This is a **new, independently reconstructed PC source launcher** prepared from the existing X-Stage Song Studio Web Control UI. It is **not** the missing, original and fully verified X-Stage Song Studio v0.2.5 Build 205 engine or an installer (.exe).

## How to open on Windows

1. Download and extract the **entire ZIP** first. Do not run a CMD directly inside the ZIP preview.
2. Double-click `Start-Song-Studio.cmd`.
3. On first run, the setup downloads a Microsoft Windows 64-bit compatible Python 3.13.10 embeddable runtime **from python.org**, plus FFmpeg Windows Release Essentials **from gyan.dev**.
4. Setup checks the published FFmpeg ZIP SHA-256 hash and tests both runtimes. The runtime is stored in the local `.runtime` folder, not installed system-wide.
5. A local server runs at `127.0.0.1` and opens a PC app-style browser window in Edge if installed, otherwise your default browser. No CMD window is needed while the local engine is running.
6. Choose the source and output folders, select songs, preview (up to 60 seconds) or convert to AAC/M4A. LRC can be edited and saved alongside songs.
7. First launch requires an internet connection to download the runtimes; following launches should reuse them.

**Permissions and privacy:** Music sources and conversions remain on the local PC; no songs or Google OAuth credentials are uploaded. Local API is bound only to loopback and uses a newly generated session token. The separately hosted Web Control `https://webbase-x.github.io/xstage/studio/?mode=pc` can be opened via the PC's **เปิด Web Control** button; the pairing token is kept in the browser URL fragment, not transmitted to GitHub Pages.

## Supported in this source preview

- Local song-folder scanning and search; multiple selections; persisted source/work/output preferences.
- MP3, WAV, FLAC and other FFmpeg-supported audio inputs to M4A/AAC 192 kbps; M4A sources are copied without transcoding.
- Single-song preview, LRC read/write, output naming that does not overwrite existing M4A.
- Job progress, log messages, error indication, cancellation and source preservation.
- Optional use of *externally available* FluidSynth with a user-supplied SoundFont for MIDI/KAR; **not installed automatically or verified here**.

## Not yet supported or not equivalent to original Build 205

- The original PC Engine/source bundle is **not available in the repository**. The code in this ZIP is newly created and not confirmed to match that release.
- Google Drive OAuth, private upload/download and AI vocal separation are **not implemented** in this source preview.
- NCN multi-file processing and FluidSynth/SoundFont provisioning are not implemented as a turnkey experience.
- Windows startup and system-specific behavior need confirmation on a real Windows machine; automated CI is Linux-based.
- Windows Defender/SmartScreen may alert because this is unsigned source, not a signed installer. The CMD and PowerShell contents can be inspected before running.
- Setup uses network access to fetch trusted runtime binaries and checks FFmpeg's vendor-published SHA-256. It does not independently verify a pinned hash for Python 3.13.10.

## File layout

```
X-Stage-Song-Studio-PC-Source-Preview/
  Start-Song-Studio.cmd           # Double click this after extraction
  Start-Song-Studio.ps1           # Runtime bootstrap
  engine.py                      # Auditable local engine; Python stdlib only
  studio/
    index.html                   # Same control UI as the existing PC/Web UI
    app.js
    style.css
    entry.js
  README.md
```

Setup creates `.runtime/` and `data/` adjacent to these files.

**Download path in repository:** `downloads/X-Stage-Song-Studio-PC-Source-Launcher-v0.2.5-Build205-Preview.zip`

> The release string in the ZIP filename denotes the requested *target* PC interface/build lineage, not proof that the original Build 205's full source has been recovered.
