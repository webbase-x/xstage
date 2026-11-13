# X-Stage Song Studio PC Ready v0.3.14 Build 316

**Windows 10/11 x64 · portable · no installers / no download-on-first-run**

This is the new bundled distribution of the existing `songstudio-pc` preview engine. It is **not** a recovered copy of the original v0.2.5 Build 205. We keep both in the same repository but explicitly differentiate the available features.

## Open from Windows

1. Download **X-Stage-Song-Studio-PC-Ready-v0.3.17-build317.zip** from the GitHub Releases page.
2. Extract the **entire ZIP archive** into a folder. Do not launch the CMD directly inside the ZIP preview.
3. Double-click **Start-Song-Studio.cmd**.
4. The Windows folder picker and SoundFont file picker open visibly in the foreground, including Thai-language folder names. No external tools are required.
5. The launcher checks that the bundled Python, FFmpeg, FluidSynth, SoundFont and HTDemucs AI libraries/model are intact, using SHA-256 checksums, without downloading anything.
6. The local engine opens the PC app interface in Edge app-style mode (or in your default browser if Edge isn't present). Work with files on this computer.
7. You may change input/output folders. The chosen paths persist across new ZIP releases under Windows `%LOCALAPPDATA%\\X-Stage\\SongStudio\\preferences.json`.
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

### Google Drive OAuth for every PC user (one owner configuration)

**The app developer configures the matching Google Desktop OAuth Client ID + Client Secret ONCE.**
Do **not** distribute any user's refresh/access token, profile, or Google password.

1. In Google Cloud, enable Google Drive API and set up Google Auth Platform.
   For users outside your organization, choose **External** and publish
   the OAuth consent app **In production**. While in **Testing**, only
   allowlisted test users can authenticate and consent usually expires after
   seven days (for non-identity scopes). Follow Google's verification requirements.
2. At **Google Auth Platform → Clients → Create client → Desktop app**, create
   a dedicated **X-Stage Song Studio PC** client. Download the original OAuth
   Desktop JSON containing BOTH `installed.client_id` and `installed.client_secret`.
   Do **NOT** use the Web app Client ID from `config.js`: Web/TV use different
   OAuth client types. Google can reject a Desktop token request with
   `HTTP 400: client_secret is missing` if the secret is omitted, even with PKCE.
3. In the repository **Settings → Secrets and variables → Actions** set:
   - **Variable:** `XSTAGE_GOOGLE_DESKTOP_CLIENT_ID` = Desktop Client ID
   - **Secret:** `XSTAGE_GOOGLE_DESKTOP_CLIENT_SECRET` = matching Desktop Client Secret
   From the **same** downloaded Desktop JSON. The next `PC Ready Offline ZIP`
   build embeds the complete *public Desktop OAuth client configuration*
   (both values) into `config/google-oauth-client.json`. GitHub Actions stores
   the build input Secret outside Git history, but anyone who downloads a
   native application can inspect the resulting Desktop credentials; this
   field is **not** a confidential server secret. **Never include** users'
   access tokens or refresh tokens in a release.
4. Every end user extracts that release and clicks **Google Login**.
   No JSON picker is required. Each user selects **their own** Google account
   and approves **their own** Drive access once. Personal OAuth tokens are
   never included in the downloadable ZIP.

**Persistent Windows user storage:** `%LOCALAPPDATA%\X-Stage\SongStudio\`.
This stores `preferences.json`, a user's optional `oauth-client.json`
override and `google-auth.dpapi` (encrypted refresh token). New application
ZIP releases automatically reuse the same per-Windows-account settings.
Old per-ZIP `data` contents are copied into this folder if not present; they
never overwrite an existing user profile. Separate Windows accounts have
separate authorization, which is required for privacy.

**Fallback and repair for older builds:** If the developer has not configured
BOTH GitHub settings, the ZIP intentionally does not bundle a broken ID-only
OAuth file. Open **Settings → Advanced → Choose Desktop OAuth Client JSON**
and select the **original full JSON from Google Cloud** once. The app now
preserves both `client_id` and `client_secret` under Windows AppData; future
releases do not require choosing again. Older versions (Build 310–312) stripped
`client_secret` on import. Reimport the ORIGINAL JSON once after upgrading.
If the same Desktop client is fully bundled in the new release, the app can
bypass the obsolete ID-only AppData override automatically.

**Important:** this does NOT log users into Google automatically or bypass
Google consent. Desktop clients are public: their `client_secret` cannot be considered
confidential once shipped to users. We still use PKCE and encrypted *per-user*
refresh tokens, and never ship the user's tokens. `drive.file` limits visibility
to files this application created or was explicitly granted access to.
The app owner must publish the Google consent screen appropriately for the
target audience; Google may require brand verification.

**Testing status:** GitHub Windows automated tests can check the bundled
Client ID and mock the OAuth callback, and validate Windows DPAPI roundtrip.
They cannot verify sign-in against a real account without the user's consent.

### Live SoundFont and PC window fixes

- On MIDI-only tracks, the original melody is rendered through the bundled default SoundFont while the chosen SoundFont is independently mixed. Muting the chosen SoundFont does not mute the original track.
- Both volume sliders, the selected SoundFont and the MIDI preset are processed on the running stream; no preview file is created and the playback time is preserved.
- The Edge PC app launches maximized with desktop-scale responsive layout. If Edge is unavailable, your default browser opens and its window size remains under browser control.
- "M4A only" and "M4A + lyrics" are both tested with real files. A later full build adds missing Lyrics without rewriting an existing M4A.

### Build button fix in v0.3.12 Build311

- Both buttons (M4A only / M4A + lyrics) now use one confirmation, then show the actual PC Engine job ID directly on Step 4.
- Preflight checks song IDs, input existence, format support, FFmpeg, SoundFont (for MIDI), AI mode readiness and output write permission **before** acknowledging a job.
- The Step 4 panel shows current progress, skipped existing songs, M4A/Lyrics counts and detailed errors. Failures remain visible until next action.
- Windows CI includes a real authenticated HTTP POST `/api/jobs` + GET `/api/status` smoke test, followed by output validation for both create actions and `songs/current.json`.
- Existing completed songs are skipped without regeneration. Older source formats such as NCN remain unsupported and now produce a clear explanation instead of silent inactivity.

### Verify song lyrics while auditioning, and optional offline AI transcript

In Step 3, find a song by title, singer or code and start the no-file karaoke
preview. The lyrics panel displays lines in sync with the player's playback
position, and labels the genuine source: timed LRC, MIDI/KAR embedded lyric,
or NCN Song + Lyrics + Cursor components. When lyrics cannot be matched or
the NCN trio is incomplete, the app reports the exact reason and never
fabricates a blank or guessed lyric document.

**AI only when original audio has audible singing:** Ready Build 316 includes
the pinned multilingual Whisper.cpp base model and native Windows CLI. On
an MP3/M4A/WAV/etc. with no usable existing lyrics, click
**AI ถอดเสียงร้องเป็นร่างเนื้อร้อง** and select Thai or auto-detect language.
The on-device ASR transcribes to an **unverified** line-timed draft in
`%LOCALAPPDATA%\\X-Stage\\SongStudio\\ai-lyrics-drafts`.
No private audio is sent to a server. A temporary mono WAV is deleted
after inference; no M4A song is created by the audition workflow.
Use **ตรวจและบันทึกร่าง AI** to correct the guessed text and timing before
it is accepted as an editable LRC or used in the final catalog.

Important limitations: Whisper is a speech recognizer, not a reliable song
lyrics recognizer. It can mishear Thai singing, improvise/hallucinate words on
instrumental music, or miss entire verses. Never auto-publish AI transcripts
as verified karaoke lyrics. A pure MIDI/NCN instrumental contains note
events, **not a singer's words**, so transcription is not offered unless
an actual audio recording with vocals exists.

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
- Distributed ZIP: GitHub Release `song-studio-pc-ready-v0.3.17-build317`
- Third-party redistribution notes: `THIRD_PARTY_NOTICES.md`

**If the SHA-256 integrity check fails**, the app does not run: download and extract a fresh verified ZIP. Do not download missing components separately.
