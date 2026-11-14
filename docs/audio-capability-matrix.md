# X-Stage V4 audio capability, quality and MIDI mixer contract

Scope: **Song Studio PC + hosted Web + Android APK WebView** on the same private Drive V4 root. This branch depends on #35 (V4) and #36 (on-stage 49-key MIDI piano). It does **not** change songs on Drive or original NCN MID/LYR/CUR timing files.

## SoundFont location and download safety

- **Cloud write/read location:** `XStageWeb/AUDIO/*.sf2` or `*.sf3`. Cloud Lyrics JSON and catalogs remain in `XStageWeb/LYRICS/`. No `SOUNDFONT/` cloud folder.
- **Song Studio PC:** read-only `/api/audio-capabilities` reports logical CPU cores, installed/available physical RAM when OS allows, chosen local SoundFont file size and local download destination's free disk space. The source PC uploader sends the local file directly to private Drive and does **not** need an extra local download copy.
- **Web/Android WebView:** Google Drive file list includes each SF2/SF3 size; show green/yellow/red risk assessment and **download bytes per file** before selection. The Web runtime has a 256 MiB single-font limit, stricter guard when physical RAM is unavailable, and a bounded streaming download; blocked fonts cannot be chosen or loaded. Caution fonts require explicit confirmation.
- **Memory estimate:** roughly `3 × SoundFont size + 96 MiB` for Web, and `3 × size + 256 MiB` for PC; these are conservative forecasts, *not* measured peak RSS or proof of suitability. Browser `navigator.deviceMemory` can be unavailable or rounded.
- **Storage labels:** `navigator.storage.estimate()` gives only **this site's browser-storage quota/usage**. It is *not* device-wide disk free or a guarantee of persistent storage. Browser SoundFont downloads are currently **RAM-only**, not persisted as an offline cached file. PC disk space is from OS filesystem APIs.

## Source classification and sound-quality explanation

The displayed source counts classify **one catalog song once** using its declared `sourceFormat` when known (including NCN, KAR, MIDI, M4A, MP3, WAV, AAC, FLAC, OGG, video), falling back to media metadata when absent; unknown records remain **OTHER**, not guessed. Web counts are for playable catalog rows; PC counts reflect scanned local songs.

| Media mode | Playback | User controls / technical limitations |
| --- | --- | --- |
| MIDI/KAR/NCN basic | Offline browser synthesis from notes, same clock as lyrics | ±12 semitone transpose (excluding drums Ch 10); 16-ch mute, solo, gain; piano note display; tempo control via existing playback-rate control |
| MIDI + SF2/SF3 | Same MIDI synthesis with verified private sample bank | SoundFont chooser and memory guard; sound quality depends on actual SF and browser renderer, **not guaranteed identical to FluidSynth** |
| MP3/AAC/OGG | Decoded original/compressed audio | Original sound, speed/repeat/EQ where supported; **no MIDI channel separation or semitone transpose** |
| M4A | Codec-dependent original stream (AAC or ALAC possible) | Same audio controls; **M4A is a container, not evidence of lossless quality** |
| WAV/FLAC | Usually lossless / PCM | Original stream when browser codec supports it; may require more bandwidth |
| Video | Verified audio plus optional muted video layer | Existing original/fallback video toggle and timed lyrics; actual codec support is browser/device-specific |
| NCN LYR/CUR | Not exposed for editing by Web mixer | Converted Lyrics JSON timeline is authoritative; untouched source timing |

The player initially recommends a mode from reported CPU/RAM, media availability and video codec support. A requested mode that has no usable media falls back to another available mode (it must not invent audio or lyrics). Auto mode prioritizes original audio on uncertain/limited hardware. MIDI-only songs can be synthesized; no promise of performance on all devices.

## Mixer and time consistency

- MIDI key transpose is limited to `-12…+12` semitones. Channel 10 (MIDI index 9) is percussion and not transposed.
- Mute, Solo and channel gain are applied **to the actual notes passed into offline synthesis**, not merely to the graphical piano. If any channel is Solo, all other channels are silent. The piano receives the *post-mixer* note timeline.
- The raw MIDI/NCN files, catalog JSON and existing Lyrics JSON **are never rewritten** by these controls. All timestamps remain fixed; the playback mode/mixer change re-renders the current MIDI in the browser and restores the prior playback position.
- Mixer edits are applied explicitly on the current track. The underlying MIDI bytes are reused from a bounded one-item in-memory cache, rather than redownloaded every time. Lyrics JSON is reused when the current catalog object matches.
- The current browser MIDI renderer produces a seekable WAV in memory; it is not a streaming multi-instrument synthesizer, ASIO engine, 88-key input controller, or professional audio stem separator. Live changes require re-render and may interrupt playback for large songs.

## Release gate

The following must pass on the final commit:

1. `npm test`, including **audio-capability**, browser MIDI transpose/channel and stage piano tests.
2. `drive-v4-contract.yml` on Windows/Linux, including `test_songstudio_audio_capabilities.py`.
3. Chromium E2E for desktop/mobile controls, resource status, device format and SoundFont risk display, plus existing private Drive importer and Web/Android smoke/build.
4. Manual verification with private Google Drive, 2–3 real SF2/SF3 banks of different sizes, MIDI/KAR/NCN timing, M4A/MP3/video codecs, low-RAM Android TV and Windows Song Studio. No claim of actual RAM savings or live hardware playback is made from mocked CI alone.

Source branch is a draft PR until a release decision is made; no automatic publishing or Drive migration occurs.
