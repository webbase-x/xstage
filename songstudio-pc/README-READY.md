# X-Stage Song Studio PC Ready v0.3.9 Build 309

**Windows 10/11 x64 · portable · no installers / no download-on-first-run**

This is the new bundled distribution of the existing `songstudio-pc` preview engine. It is **not** a recovered copy of the original v0.2.5 Build 205. We keep both in the same repository but explicitly differentiate the available features.

## Open from Windows

1. Download **X-Stage-Song-Studio-PC-Ready-v0.3.9-build309.zip** from the GitHub Releases page.
2. Extract the **entire ZIP archive** into a folder. Do not launch the CMD directly inside the ZIP preview.
3. Double-click **Start-Song-Studio.cmd**.
4. The Windows folder picker and SoundFont file picker open visibly in the foreground, including Thai-language folder names. No external tools are required.
5. The launcher checks that the bundled Python, FFmpeg, FluidSynth, SoundFont and HTDemucs AI libraries/model are intact, using SHA-256 checksums, without downloading anything.
6. The local engine opens the PC app interface in Edge app-style mode (or in your default browser if Edge isn't present). Work with files on this computer.
7. You may change input/output folders. The chosen paths are remembered inside `data/preferences.json`.
8. For a custom X-Stage Song Studio **Windows desktop shortcut icon**, run `Create-Desktop-Shortcut.cmd` in the extracted folder (optional).

### Included components

- Python 3.13.10 **embedded**, runs from `.runtime/python` (no system Python or pip installation)
- FFmpeg and ffprobe **executables**, `.runtime/tools`
- FluidSynth and the DLLs it requires, `.runtime/fluidsynth/bin`
- Default GeneralUser GS `.sf2` SoundFont, NumPy, ONNX Runtime CPU and HTDemucs ONNX model (~166 MB), `.runtime/soundfonts`
- PC engine `engine.py`, existing Song Studio PC/Web control UI, runtime manifest and third-party notices
- New X-Stage Song Studio `studio/app-icon.svg` favicon, pre-rendered `studio/app-icon-512.png` and Windows `studio/app-icon.ico` with all icon sizes, included in Ready ZIP

All listed components are predownloaded and tested during **GitHub Actions build** (on a Windows runner), not on the user's Windows PC. `Start-Song-Studio.cmd` never calls `Invoke-WebRequest` or installs software.

### Functions implemented in this source engine

- Scan source folders, search/select songs, persist source/output preferences
- Convert supported audio formats to M4A (AAC 192 kbps) using FFmpeg; preserve existing M4A audio
- Render MIDI/KAR to WAV using bundled FluidSynth and default SF2, then convert to M4A
- **Offline AI Separation:** HTDemucs ONNX model and NumPy/ONNX Runtime are included in the Ready ZIP. Choose “แยกเสียงร้อง AI (Full Offline)” in create-step 3; create-step 4 exports the instrumental M4A plus a separate vocals M4A. Preview uses the same local AI model. No additional downloads on the user's PC.
- **Live listening:** Step 3 now searches songs independently, plays as a real MP3 stream without generating preview files, and mixes matching same-stem backing audio and MIDI via the chosen SF2/SF3 using FluidSynth. Volume levels apply when starting a new stream. Audio-only files play normally; there is no manufactured MIDI accompaniment. Edit LRC and save as companion lyrics file.
- Local work status, progress, cancellation, and non-overwriting output names

### AI separation limitations

- CPU-only in this edition; a reasonably fast 64-bit PC and sufficient memory are required. Processing takes longer than standard conversion.
- The chosen AI model uses four-stem Demucs separation; output quality varies by recording. It is not a perfect vocal remover.
- The GitHub source folder contains `ai_separate.py` and `ai-model.lock.json`, while the large model binary is shipped in the GitHub Release ZIP, not committed to the Git history.

### Dialog UX

Native browser confirmation windows have been replaced with styled in-app borderless dialogs and toast notifications; the Windows folder/file chooser remains a native OS dialog.

### Preventing duplicate songs across separate sessions

- The first successful build stores the original source's canonical path and SHA-256 in the durable local catalog.
- A second build, even after exiting and restarting Song Studio, **skips** that exact source and never allocates a second audio/lyric file.
- A copied or renamed source with identical audio bytes is also skipped by SHA-256.
- Completed songs are fsynced to `songs/.build-journal.jsonl` before processing the next song. After interruption the next run checks both catalogs and this journal; `current.json` is published atomically.
- Brand-new output uses `songs/audio/<first-digit>/`, companion lyrics `songs/lyrics/<first-digit>/`, grouped immutable `songs/catalogs/`, and `songs/current.json`.
- Legacy outputs created by older versions without source fingerprints cannot always be matched automatically; the engine blocks ambiguous unindexed filename collisions and reports the reason rather than silently making duplicate numbered files.
- Two genuinely different originals with the same filename can coexist with a collision-safe suffix, while existing media is never overwritten.

### Google Drive sign-in (requires user configuration)

Select a Google Cloud **Desktop app** OAuth Client JSON, enable the Google Drive API in that project, and configure OAuth consent/testing access as required by Google. Click **Google Login**; approval happens in the user's browser via a short-lived loopback callback with PKCE. Refresh tokens are encrypted under the Windows user's DPAPI key and never committed to GitHub. The narrow `drive.file` scope permits this app's files, not unrestricted access to older files created by other apps. Upload/download operates on the app's private Drive folder and does not publish file permissions. A real Google account must authorize the login on the target PC; simulated CI tests cannot grant that consent.

### Live SoundFont and PC window fixes

- On MIDI-only tracks, the original melody is rendered through the bundled default SoundFont while the chosen SoundFont is independently mixed. Muting the chosen SoundFont does not mute the original track.
- Both volume sliders, the selected SoundFont and the MIDI preset are processed on the running stream; no preview file is created and the playback time is preserved.
- The Edge PC app launches maximized with desktop-scale responsive layout. If Edge is unavailable, your default browser opens and its window size remains under browser control.
- "M4A only" and "M4A + lyrics" are both tested with real files. A later full build adds missing Lyrics without rewriting an existing M4A.

### Limitations

- **NCN** music handling, **Google Drive access to files owned by a different OAuth application** remain unimplemented in the source engine. The UI still shows legacy controls for PC/Web parity; these actions will display a clear unsupported error rather than silently claiming success.
- Users may choose their own compatible SoundFont; the default bundled SF2 works out of the box.
- Actual music performance depends on CPU speed, RAM and file codec.
- The app does not have a signed native Windows installer/executable. It is a portable ZIP with a double-click CMD launcher, not a signed EXE.
- Windows SmartScreen/Defender may scrutinize this unsigned bundle. Review checksums and project source. Do not disable security protections merely to run it.
- GitHub Actions validates the build and basic local conversion, but device-specific behavior still needs local testing on the target Windows computer.

### Privacy

Songs, soundfonts and output files are handled locally. The local server binds to `127.0.0.1` and uses an in-memory session token for its API. The PC interface can optionally link to the separately hosted web control with an explicit pairing token. The application does not upload song contents by default.

### Developer workflow

- Runtime package generator: `scripts/build_songstudio_ready.ps1`
- GitHub workflow: `.github/workflows/build-songstudio-pc-ready.yml`
- Source (without runtime binaries): `songstudio-pc/`
- Distributed ZIP: GitHub Release `song-studio-pc-ready-v0.3.9-build309`
- Third-party redistribution notes: `THIRD_PARTY_NOTICES.md`

**If the SHA-256 integrity check fails**, the app does not run: download and extract a fresh verified ZIP. Do not download missing components separately.
