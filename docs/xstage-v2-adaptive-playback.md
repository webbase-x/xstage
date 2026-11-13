# X-Stage V2 adaptive playback design (implementation in progress)

## Requested storage (new database contract)
```text
XStageWeb/
  AUDIO/MP3/{Songs,Lyrics}/{0-9,A-Z}/
  AUDIO/M4A/{Songs,Lyrics}/{0-9,A-Z}/
  VIDEO/{AVI,MPG,VCD,WMV}/
  MIDI/NCN/{Songs,Lyrics,Cursor}/{0-9,A-Z}/
  MIDI/E-MK/{0-9,A-Z}/
  DB/
```
A true clean break requires a new database pointer **XStageWeb/DB/current.json**, a versioned catalog contract, new Song Studio uploader and a Web/APK catalog reader that all understand the same format. The existing v1 root current.json is still in use by the branch in PR #18; **do not delete the old path on real Drive until the v2 reader and writer are complete and validated.** The user has authorized a clean design, not destructive action on their private data through untested code.

## Engine selection
- Detect actual browser MIME support, WebAssembly, AudioWorklet, native APK low-RAM memory class and network data saver.
- Audio: native HTML media element for supported MP3/AAC M4A.
- Video: separate video element with codec probing. Containers AVI, MPG, VCD, WMV cannot be guaranteed to play in WebView; unsupported files must show an explicit reason or use an explicit conversion job (never silently skip).
- MIDI: pinned, licensed WASM synthesizer and user-selected/licensed SF2/SF3 required; the current `XStageMidiEngine.ready` gate prevents making false playability claims when no synth is installed. NCN triple files require verified same-code MIDI/LYR/CUR synchronization.
- Prefer direct, supported formats; conversion should be a separate desktop/authorized pipeline, not a silent cloud mutation.

## Startup: environment vs song
1. Load app code, UI, audio policy and already-bundled lightweight dependencies. Keep static code in the versioned service worker and WebView HTTP cache where permitted.
2. Select a supported engine based on device features; load its WASM/worklet and verified SoundFont (if MIDI chosen) with progress and failure UI before attempting MIDI playback. Cache SoundFont only when permitted, and enforce a storage quota.
3. After authenticated catalog is verified, download **no private song or lyrics until requested**, except at most one queued song toward the end of active playback.
4. If available memory is low or user has enabled data saver, prioritize active playback over preloading and skip large files. Never prefetch video files or native MIDI trios under the generic M4A policy.
5. On track end/switch: pause and release old audio, revoke its blob URL, release previous lyric objects and clear queue blobs not used. Aborts must guard against stale async completions. On logout: clear all private in-memory references.
6. Do **not** write downloaded song/lyrics into CacheStorage, IndexedDB or external storage. Google Drive API requests use `cache:'no-store'`. Browser/OS transient buffers cannot be securely shredded by an ordinary webpage; the app can release its references and request eviction, not guarantee physical disk erasure.

## Current implementation
- `device-runtime.js`: device capability profile and adaptive queue limits.
- `app.js`: preload only near song end and cap retained prepared audio; existing blob URL revocation still handles primary M4A playback.
- `MainActivity.java`: trusted X-Stage pages receive low-RAM and memoryClass hints; no new file permissions.
- `scripts/device-runtime-test.mjs`: verifies safe format selection and memory caps.
- MIDI, native MP3/video playback, real SoundFont initialization, v2 DB schema, full media lifecycle and native APK end-to-end playback remain **not done**. This draft must not ship as a completed rewrite.

## Acceptance requirements before merge
- Storage: authoritative new DB schema and new song packages, no ambiguous duplicate codes, validated folder membership/file IDs, atomic catalog pointer publish.
- Playback: M4A and MP3; codec-appropriate video and MIDI; NCN synchronized lyrics; remote controls and TV resumption.
- Network: no active-song interruptions due to background download, bounded memory on Android 10, no duplicate preloads, cancel on skip/logout, use latest queued next song.
- Security: private Google Drive remains private, no OAuth token in logs/QR, no cached persistent private songs.
- Test: all web regression suites, Android APK build, manual Android TV/Chrome tests and real Google Drive permission/sync checks.
