# Web MIDI SoundFont laboratory (isolated beta)
This branch adds an **opt-in standalone MIDI laboratory**, not a production player replacement. Open `midi-lab.html` on the branch's preview deployment or serve via static HTTP. Main `index.html`, `app.js`, M4A playback, OAuth, catalog, queue and TV interfaces are unchanged.

## Defaults
- Mode `auto` (MIDI files routed to MIDI in this lab; existing M4A main player untouched)
- Quality `balanced` (48kHz AudioContext request)
- Cache on (one user-selected SoundFont up to 64MiB in IndexedDB, never sent to Drive)
- SF2/SF3 local upload, MID/MIDI/KAR local upload. No NCN or lyric karaoke alignment yet.
- Pinned spessasynth_lib v4.4.8 via esm.sh, matching worklet via jsDelivr. Production should **self-host a tested and license-compliant pinned bundle and worklet**. CDN availability, Android TV/browser support and sample rate require real-device tests.

## Security & failure isolation
- No OAuth tokens or Drive access; no media uploaded.
- File extension and header checks; size ceilings. Do not treat these checks as comprehensive validation.
- SoundFont persistent cache is opt-in, stored on this device; Clear Cache button.
- User gesture initiates AudioContext. HTTP failures and AudioWorklet restrictions appear as status errors.
- Only one soundfont per page instance; reload to swap. Enabling M4A mode points users back to main stage.
- Not wired into the main queue: playback works locally only when browser and CDN libraries load.

## Test checklist (manual; not claimed passed)
1. With Chrome/Edge desktop: load a licensed SF2, then valid MIDI, hear instruments, pause/resume, seek, speed, stop; repeat with KAR.
2. Reload; choose cached SF and MIDI; clear cache and verify font is no longer remembered.
3. Check SF3 on Chromium, especially low-powered Android 10 TrueID TV. Measure glitches, latency, memory, and resume after page/background/TV sleep.
4. Invalid MIDI, invalid SoundFont, zero byte, oversized file, blocked CDN, offline, IndexedDB denied, no AudioWorklet must fail visibly; M4A main stage must remain unaffected.
5. Audit third-party license, pin and self-host dependency assets before production.
6. Separately implement Catalog MIDI associations, private Drive streaming, timed lyrics / NCN, MIDI channel mixing, karaoke key controls, keyboard and remote integration; regression-test existing M4A path.
