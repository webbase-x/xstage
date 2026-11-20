# X-Stage Karaoke Online — professional MIDI engine

## Choice

The optional high-quality engine is **SpessaSynth (spessasynth_lib 4.4.8,
spessasynth_core 4.4.10)**, licensed under Apache-2.0. It is intended to
replace the old hand-written oscillator/sample scheduling for SF2/SF3 MIDI,
KAR, NCN, and Song Studio Pro XMID playback.

Documentation: https://spessasus.github.io/spessasynth_lib/
Upstream: https://github.com/spessasus/spessasynth_lib

The engine runs in an **AudioWorklet**, keeps MIDI events as MIDI, and does not
convert a whole song to WAV. The existing player remains responsible for
Google Drive access, lyrics timing, seek, tempo, queue, and transport controls.

## Deployment

The repository contains source integration in `midi-pro-engine.js` and a
pinning/build workflow in `.github/workflows/vendor-spessasynth.yml`.
The workflow installs specific versions, bundles the ESM for browsers and
copies the matching worklet under `vendor/spessasynth/`. It commits those
assets only if the build checks pass. No upstream third-party script is
loaded from a CDN during playback.

**The professional engine is NOT enabled merely by merging the adapter.**
`vendor/spessasynth/engine.mjs` and
`vendor/spessasynth/spessasynth_processor.min.js` must both exist on
GitHub Pages before production uses it. If either is absent, unsupported,
or cannot initialize, the existing Web Audio MIDI engine is retained.
Never claim that audio quality has improved until an actual browser
playback test has passed.

## Audio

- User-selected SF2/SF3 SoundFonts remain private to their Google account.
- The engine honors MIDI channel program, bank, velocity and percussion
  channel 10 (zero-based channel 9).
- The limiter protects against output peaks but cannot fix poor SoundFont
  samples or turn a 6 MB lightweight GM bank into a studio-grade library.
- A quality GM/GS SoundFont should be chosen for a full arrangement;
  individual-instrument SF2 banks may lack required patches.
- Web Audio is unlocked on the play gesture before asynchronous downloads.
- Changing transpose, program, speed or position reinitializes active
  voices; released tracks must destroy their worklet resources.
- Only test assets with verified redistribution licenses are committed.
  Users' own SoundFonts are never committed.

## Regression and acceptance

Run `npm test` for the professional adapter contract, including note
on/off, instrument/key change and cleanup. A browser listening test is
required for audible distortion, song timing, drum patches, long tracks,
phone/Safari playback and changing SoundFont mid-song.

The original MIDI engine is kept as an explicit compatibility fallback.
