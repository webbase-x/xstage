# Song Studio PC vs Web — cross-dimensional compatibility audit

Scope: the independent browser editor at `/studio/web.html` versus the Windows Song Studio PC Engine control at `/studio/index.html`. This is **not** the hosted X-Stage karaoke playback app, though Web MIDI synthesis is shared with it.

| Dimension | Browser implementation in this PR | Remaining difference / acceptance gate |
| --- | --- | --- |
| Navigation and UI | Same four create steps, PC-style dark/nav/cyan controls and SoundFont/preview in step 3; responsive mobile layout | PC has additional AI Lyrics, Head/Tail bulk editor, Google Drive upload/download and Settings tabs; not present in standalone Web |
| Source discovery | Local file/folder picker or drag/drop, 120,000 item cap with yields and cancellation, UI shows top 500 results | Browser File System Access permission and recursive folder picker behavior depend on browser; still needs large real-folder benchmark |
| Source identity | Stable folder/stem key unifies NCN Song/Lyrics/Cursor; protects same-stem collisions and actual bytes (512 KiB chunk comparison) | Cross-folder unrelated stems remain distinct; content hash across globally renamed songs is not implemented |
| MIDI/KAR | Shared SMF parser, built-in oscillator fallback or user-selected local SF2/SF3; metadata/cues from MIDI | Output not bit-identical to PC FluidSynth; only bundled renderer-supported SF presets/codec paths |
| NCN | Requires MID+LYR+CUR, CP874 bytes and original MIDI tempo change timeline, real character syllables | Truncated/backwards/FFFF CUR cannot be safely auto-exported as verified timing; intentionally blocked |
| Source preservation | Export original MIDI/KAR, and NCN LYR/CUR byte-for-byte; separate verified Lyrics JSON and LRC | This is local export; does not publish a shared Google Drive V4 generation automatically |
| MIDI audio output | Optional offline WAV rendering via SoundFont -> local FFmpeg.wasm AAC M4A | Browser FFmpeg code downloads from pinned CDN on first use/cache miss; desktop Ready edition embeds tools |
| Mixer | Transpose ±12 except percussion ch 10; 16 channels with mute and gain; rerender to hear settings | This is **not** live streaming and cannot match PC's FluidSynth/BASS MIDI feature/quality exactly |
| Timed text editor | Editable LRC, timestamp insertion from preview, NCN real CUR visual highlighting if unmodified | Editing LRC replaces precise CUR glyph cues with line-level LRC; original CUR stays unchanged; no automatic transcription |
| Batch | Multi-select, ZIP/individual folder output, validation, per-song errors, cancel; guarded concurrent source scans | ZIP memory cap 500 MiB input; 4 GiB ZIP32 limit and no browser background processing/restart resume |
| Memory and limits | MIDI<=12 MiB, SoundFont<=256 MiB, duration<=900 s; estimated memory preflight | Browser memory estimation is heuristic. Actual SF3 sample Ogg decode depends on Web Audio and OS. Test low-memory TV separately |
| Privacy and security | Local file bytes only, no FormData/XMLHttpRequest uploads; no cloud OAuth in browser-only mode; bounded parser / no arbitrary source execution | FFmpeg source code fetched from CDN; no offline guarantees. Check security policies of third-party code/CDN before production |
| Reliability | Source duplicate bytes verified in bounded slices; reject conflicting CUR; abort controller for MIDI jobs; programmatic source timestamp checks | Unfinished/uncertified source should never be published as a timed catalog; browser session memory not durable |
| Accessibility | Semantic buttons/labels, keyboard focus indicator, aria status, responsive layout | Need human testing with Thai screen readers, actual keyboard on TV/phone, and touch at differing DPIs |
| Test automation | Node smoke, 100k karaoke search & Drive regressions, NCN tempo/byte tests, and Chromium actual NCN SF2 preview and two export modes | No physical Windows PC/Android TV Safari iOS or user's private Google Drive test has been run |

## End-to-end acceptance requirements

1. Run `npm test` plus `scripts/song-studio-web-midi-test.mjs` and actual `scripts/song-studio-browser-e2e.mjs` with a real MIDI/KAR, CP874 NCN and small SF2 test fixture.
2. Verify SF3 in Safari and Android WebView; if Ogg decode unsupported, clearly show SF2 alternative.
3. Import a large real NCN library with filenames split into Song/Lyrics/Cursor; verify no song mixing, unexpected duplicates, wrong credits, unsafe CUR, or silent data mutation.
4. Test browser-only UI at phone widths and desktop widths, including duplicate selection, stop/cancel, and SoundFont switching; check resource warning stays actionable.
5. Verify user-owned XStageWeb V4 separately before claiming Web/PC shared cloud publishing parity. Nothing in this PR deletes or rewrites Drive data.
6. Change Web build/cache keys and require fully green checks prior to releasing shared `browser-midi.js` to hosted Karaoke Web and Android. Test physical devices before claiming hardware compatibility.

**Release truth:** until PR merged and CI passes the latest commit, this document describes a proposed feature branch rather than production; real device validation is still required.