# X-Stage XSK2 cross-platform compatibility contract

Updated 2026-11-16. This document supersedes the encrypted XSK1 plan.

## Format and privacy

- **XSK2** is a **non-encrypted** package: four ASCII bytes `XSK2` followed by an ordinary two-file ZIP (`ZIP_DEFLATED` or `ZIP_STORED`).
- Exactly one MIDI/KAR source (`.mid`, `.midi`, `.kar`) and one UTF-8 timed Lyrics JSON document are included. No sibling `.lrc`, `.cur` or `.lyr` file is required by the player.
- The JSON is `schemaVersion:2`, `format:"XSK"`, `formatVersion:2`, with `songCode`, `title`, `artist`, `audio.file`, `audio.size`, `audio.sha256`, `lines` and optional timing offset. `createdBy` and `publisher` are **X-Stage Song Studio**.
- **No password, DPAPI key, creator's Windows username, or computer name** is written by the XSK2 producer. Nevertheless, the file is **not confidential**: anyone receiving the file can inspect the song title, performer, lyrics, and original MIDI source. SHA-256 detects accidental corruption, **not authenticity** against a malicious file replacement.
- Do not overwrite XSK1, source MIDI, LYR, CUR, or existing catalogs. Explicit regeneration is required to replace encryption; creating XSK2 must not be interpreted as migration of all XSK1 archives.

## Read/write support

| Component | XSK2 | XSK1 |
| --- | --- | --- |
| Song Studio PC | Creates XSK2, never creates new encryption keys | Preserves old files; may read legacy with a supplied existing key |
| Karaoke PC | Opens and indexes direct XSK2 without a key; reads title and artist from internal JSON | Read-only when the original Windows DPAPI key is available |
| Karaoke Web | Imports a single original XSK2 to private Drive `AUDIO` after inspecting timed JSON metadata, and stores an `xsk.fileId` in the existing v4 Catalog; when queued/played, downloads XSK2 and validates ZIP/MIDI SHA-256 before synthesizing audio in memory | Must regenerate XSK2 from the original source; Web does not decrypt XSK1 |
| Android APK / TV | Uses the same hosted WebView stage, `xsk.fileId` Catalog entries and bounded prefetch/on-demand XSK2 processing as Web | Same limitation as Web |

The Web importer stores the **original single XSK2** (no persistent extracted MIDI or JSON). It inspects the enclosed song JSON to populate the Catalog. At playback, the Web stage or Android WebView fetches XSK2 by `fileId`, unpacks it **in memory**, verifies MIDI SHA-256 and renders MIDI to temporary audio with the selected SoundFont. The first XSK2 waiting in the queue is prepared ahead of time and consumed directly when its turn arrives; preparation proceeds **one song at a time**, with a device-memory ceiling and cancellation if the queue/account changes. If an XSK2 is too large, pre-rendering fails or the song is selected before preparation finishes, playback falls back to on-demand processing. Pre-render is deferred while the current song is still loading to avoid overlapping heavy synthesis. Plain audio/video and MIDI+JSON catalog entries remain untouched. There is no permanent browser-side extraction cache or XSK2 offline mode; Google Drive access and a compatible browser/WebView are required.

## Metadata and timed lyrics

- Prefer real song `title` and `artist` read from NCN `LYR` header, KAR metadata, timed LRC or an edited JSON. Never substitute source filename, song code or the application publisher for a missing singer; skip with a reported reason instead.
- Same-stem files in one directory (e.g. `00001(1).mid` + `.lyr` + `.cur`) and mirrored NCN Song/Lyrics/Cursor layouts are supported.
- Web/APK's catalog title/artist is taken from the document's root and nested `metadata`; preserve an existing valid identity when the new document omits it.
- Keep actual `characters[].startTime` timings from NCN CUR and `syllables[].start` timings from JSON. Neither player should invent per-character timing when it is missing.
- PC SQLite respects `user_edited` entries during reindexing.

## Legacy and testing

- Old `XSK1` is `XSK1` + AES-256-GCM nonce + ciphertext of a ZIP, bound to the issuing Windows account's DPAPI key. PC retains optional reading, but Web/APK deliberately do **not** embed a decrypting key.
- A user who needs a Web/APK version should regenerate XSK2 from original MIDI + complete timed lyrics. Preserve XSK1 alongside the newly allocated XSK2 code; do not silently overwrite.
- Tests: `scripts/test_songstudio_xsk.py`, `scripts/test_songstudio_xsk_stream.py`, `windows-pc/source/tests/test_xsk_playback.py`, `scripts/xsk-browser-test.mjs`, and the existing importer and Android WebView integration regressions.
- Release **only** after producer, PC and Web/App import regressions and Windows/Chromium builds pass on the desired release commit. Do not claim device-wide codec parity merely because all apps can ingest XSK2.
