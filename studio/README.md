# X-Stage Song Studio — Web-only and PC control

**Browser-only Song Studio:** https://webbase-x.github.io/xstage/studio/

**Direct browser editor:** https://webbase-x.github.io/xstage/studio/web.html

**PC-connected control (optional):** https://webbase-x.github.io/xstage/studio/?mode=pc

Two modes live in this same existing repository. Do **not** confuse their capabilities:

## Web-only (Beta 0.3.0)

Opening the normal public `/studio/` URL without a PC pairing token routes to `web.html`.
No Windows desktop app or local API/engine is required.

- Choose local audio files or a folder (File System Access API in supported Chromium browsers; file/folder input fallback elsewhere).
- Index MP3, M4A, WAV, AAC, OGG, FLAC, associated LRC files, and recognize MIDI/KAR/NCN items.
- Preview browser-playable audio and edit timed LRC lyrics, with playback time stamp insertion.
- Use `@ffmpeg/ffmpeg@0.12.15` + `@ffmpeg/core@0.12.10` (single-thread ESM) in the browser for M4A (AAC 192kbps) conversions. Download library/runtime code from jsDelivr on demand. Files are processed in local browser memory; the app does not upload song contents.
- Keep existing M4A audio unchanged instead of transcoding again.
- Export M4A plus a separate synchronized `.lrc` companion. Lyrics are **not** promised to be embedded as timed metadata inside M4A.
- Write to a user-chosen folder (if supported), with collision-safe names, or download a local ZIP.
- Cancel a conversion and show progress and per-song errors.
- Source files are neither moved nor deleted; no remote backup or cloud upload is performed.

**Known browser-only limitations**
- SF2/SF3 SoundFont rendering for MIDI/KAR/NCN is **not available** in this Web Beta, despite files being recognized. Do not claim otherwise.
- No offline AI vocal separation in the browser-only edition.
- No Google Drive upload/download in Web-only mode, intentionally: audio is kept on-device. Those operations are still available via the PC Engine edition.
- Large batches may exhaust browser RAM. The default ZIP export warns above 500 MB of selected source audio; choose a local output folder for larger batches.
- File/folder API permissions, codec support, WebAssembly performance and automatic downloads vary across browser/OS. Chrome/Edge on desktop are the preferred test platforms.
- The Web Engine currently fetches its code from jsDelivr and may be cached by the browser; **full offline-first availability of FFmpeg after restarting is not guaranteed**.
- We have smoke tests for JS syntax/DOM/ZIP and routing, but real end-to-end AAC conversion must be validated in supported browsers before calling the Web Beta production-ready.

## Windows/PC Engine Web Control

Opening `/studio/?mode=pc` keeps the prior Web Control user interface. The local Windows app can open it through its authenticated pairing link, which is not redirected to the Web-only editor.

1. Start X-Stage Song Studio v0.2.5+ Local Engine on Windows.
2. Click **เปิด Web Control** in the desktop app or run `Run-Song-Studio-Web.vbs`.
3. The PC opens the URL with an unguessable token in the fragment, never transmitted to GitHub Pages.
4. Allow browser local-network permissions if prompted; press **เชื่อมต่อ Engine**.
5. Local Python engine handles SoundFont, conversion and optional private Drive operations. Local API uses `127.0.0.1`, strong bearer auth and strict origin.

Never forward the local engine port publicly.

### Project files

- `web.html`, `web.js`, `web.css`: independent browser-only client
- `index.html`, `app.js`, `style.css`: original PC Engine control UI
- `entry.js`: route direct visitors to Web editor while preserving PC pairing
- `scripts/song-studio-web-test.mjs`: smoke checks
