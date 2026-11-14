# X-Stage Song Studio — Web-only and PC control

**Browser-only Song Studio:** https://webbase-x.github.io/xstage/studio/

**Direct browser editor:** https://webbase-x.github.io/xstage/studio/web.html

**PC-connected control (optional):** https://webbase-x.github.io/xstage/studio/?mode=pc

Two modes live in this same existing repository. Do **not** confuse their capabilities:

## Web-only — MIDI/KAR/NCN & SoundFont browser editor

Opening the normal public `/studio/` URL without a PC pairing token routes to `web.html`.
No Windows desktop app or local API/engine is required.

- Choose local audio files or a folder (File System Access API in supported Chromium browsers; file/folder input fallback elsewhere).
- Index MP3, M4A, WAV, AAC, OGG, FLAC and associated LRC; identify standalone MIDI/KAR and properly pair NCN `MID + LYR + CUR` in `Song/Lyrics/Cursor` folders by code. A standalone `.ncn` file is not the NCN three-file format and will be rejected.
- Preview browser-playable audio and synthesize MIDI/KAR/NCN to browser WAV, with optional user-selected local SF2/SF3 SoundFonts, transpose ±12, and 16 MIDI channel volumes/mutes (channel 10 drums remains untransposed). Edit timestamped LRC and highlight real KAR/NCN cues. Changing SoundFont/mixer requires rerendering the preview; it is not live FluidSynth streaming.
- Use `@ffmpeg/ffmpeg@0.12.15` + `@ffmpeg/core@0.12.10` (single-thread ESM) in the browser for M4A (AAC 192kbps) conversions. Download library/runtime code from jsDelivr on demand. Files are processed in local browser memory; the app does not upload song contents.
- Keep existing M4A audio unchanged instead of transcoding again.
- For MIDI/KAR/NCN, default export preserves the *original MIDI bytes* and includes verified Lyrics JSON/LRC when real timing exists; NCN also retains original LYR/CUR. A second export mode synthesizes the MIDI to separate M4A with FFmpeg.wasm. Audio-only inputs still export M4A + optional timed LRC; lyrics are **not** embedded inside M4A.
- Write to a user-chosen folder (if supported), with collision-safe names, or download a local ZIP.
- Cancel a conversion and show progress and per-song errors.
- Source files are neither moved nor deleted; no remote backup or cloud upload is performed.

**Known browser-only limitations**
- The bundled Web Audio SoundFont renderer supports a compatibility subset of SF2 and SF3 and is **not** sound-identical to the PC FluidSynth engine. Some SF3 Ogg sample encodings are unsupported by Safari/old Android WebViews; use SF2 or Song Studio PC when decoding fails.
- Browser-only edition does not implement PC Whisper transcription, AI vocal separation, full Smart Batch Lyrics correction, or production-grade multi-hour MIDI rendering. The UI shares the PC four-step workflow/visual language, not all PC engine capabilities.
- NCN with incomplete, impossible or backwards CUR timing is blocked from automatic timed export, even if MIDI audio itself can be previewed. Editing LRC uses explicitly entered line timestamps and does not overwrite or reconstruct original CUR.
- No Google Drive upload/download in Web-only mode, intentionally: audio is kept on-device. Those operations are still available via the PC Engine edition.
- MIDI is limited to 12 MiB/15 minutes; local SF2/SF3 to 256 MiB with device-memory estimates before synth. Large batches may exhaust browser RAM. ZIP export warns above 500 MB of input media; choose a local output folder for larger batches. The resource estimate is conservative, not a physical-device performance guarantee.
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

- `web.html`, `web.js`, `web.css`, `web-midi-core.js`: independent browser-only client and pure NCN safety helpers
- `../browser-midi.js`: shared bundled browser MIDI/NCN/SoundFont renderer (no third-party script download)
- `index.html`, `app.js`, `style.css`: original PC Engine control UI
- `entry.js`: route direct visitors to Web editor while preserving PC pairing
- `scripts/song-studio-web-test.mjs`, `scripts/song-studio-web-midi-test.mjs`: smoke, real CUR timing and byte-for-byte source checks
