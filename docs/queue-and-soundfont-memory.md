# X-Stage queue preloading and SoundFont RAM contract

Implemented in `main` 2026-11-16. This is a **bounded working-set policy**,
not a promise that all tracks in an arbitrarily long queue can be resident.

## Web / Android APK / TV

- The Google Drive catalog remains the song index, and the original XSK2
  archive is kept as a single file on Drive. The stage opens it only when
  queued or requested.
- Queue preparation is sequential: start with the first pending song, then
  advance through the following songs **until the safe byte budget or
  device-specific track count is reached**. Types: XSK2 (extract and render),
  standard MIDI/KAR + timed JSON (render), MP3/M4A/other supported audio +
  JSON, and compatible video + JSON.
- Small video/audio assets may be kept transiently in memory. Larger media
  that would exceed the reserve is **not preloaded as a whole**; playback
  downloads on demand. This policy cannot guarantee zero-delay playback for
  files too large to keep in memory.
- At most 2/3/4 prepared tracks for low/medium/higher-RAM devices. Browser
  `navigator.deviceMemory` is only a coarse hint, not free RAM. Chromium
  `performance.memory` reports a JS heap estimate, not the whole process.
- The native Android WebView bridge `XStageAndroid.memorySnapshot()`
  supplies **actual system available RAM and the Android low-memory flag**;
  prefetch is paused under pressure and furthest queued blobs are evicted.
  Standalone Web browsers may not expose these values, so the policy uses
  conservative bounds and labels estimates honestly.
- When playing a cached song, its blob is removed from speculative cache and
  transferred to the player. On skip/end the previous Blob URL and secondary
  video blob URL are revoked and references dropped. Cancel, reorder,
  SoundFont switch, sign-out, and library switch invalidate relevant cache
  entries; no media is persisted to `localStorage`.
- Medley prefetch has the same memory guard and is evicted first under pressure.
- The selected SF2/SF3 file and its parsed structure stay in **app-session
  memory** and are reused for consecutive songs. Decoded AudioBuffers are
  capped (12 MiB low-memory / 48 MiB other devices) and evicted LRU-like.
  Oversized new SoundFonts are refused when Android system RAM is low.
  Change of SoundFont releases the prior parsed file and pre-rendered queue
  waves. Closing the app or changing Google account releases the session font.
- Green/amber/red indicators show font bytes, decoded sample bytes and the
  estimated queued-media budget. Android may display measured free system
  RAM; standalone Web never fabricates physical free RAM.

## Karaoke PC

- Local media is already on disk: retaining an entire MP4/MKV in process RAM
  would waste resources. `QueueWarmup` does a sequential, 64 KiB-per-song
  header warmup for up to six queued files, and automatically drops removed
  songs or all cache on app exit/very low available RAM.
- The PC banner uses measured Windows `GlobalMemoryStatusEx` values, colored
  green/amber/red. Selected SoundFont is shown by **on-disk file size only**;
  it is *not* falsely reported as physical resident RAM.
- Native BASS SoundFont ownership is still managed by each playback engine.
  There is **no new persistent cross-track BASS font-handle pool** in this
  change, because reusing handles across closed native devices without an
  audio-device lifecycle test could destabilize live playback. Existing
  medley-prepared engine handling is retained.

## Safety and validation

No background queue job can modify a song or its catalog. Media preload
requests are abortable and scoped to the active account/queue. Decompressed
and synthesized media are not uploaded. On mobile, the Android native memory
signal is only exported to the trusted X-Stage WebView origin and contains no
user name, installed-app information, or device identifier.

Regression tests: `scripts/memory-queue-test.mjs`,
`scripts/soundfont-memory-test.mjs`, `scripts/xsk-queue-test.mjs`,
`windows-pc/source/tests/test_queue_warm.py` and the existing
Web/Android/PC suites. Real Windows and Android build + playback tests are
still required before calling this a production-verified release.
