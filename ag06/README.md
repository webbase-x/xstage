# X-Stage Audio Studio

Independent audio-capture, software-FX, metering and recording for Windows, Android and secure browsers. Supports OS-recognized USB audio devices including first-generation Yamaha AG06. Not affiliated with Yamaha or Steinberg. Brand names appear only to describe device compatibility.

## Studio Workspace (independent implementation)

- Import up to 12 locally held audio files/takes (80 MiB per file, up to 10 minutes each); mix with per-track volume, mute/solo, trim in/out, offset, playback and offline stereo 44.1 kHz/16-bit WAV export.
- Tracks are a local in-memory session: save/export finished mixes before closing the app. Importing individual recordings does not grant multichannel AG06 hardware access. Browsers and mobile devices may have insufficient memory for large sessions.
- This is not Cubase AI, Cubasis LE, WaveLab Cast, or Yamaha AG Controller, and does not incorporate their proprietary code, licenses, DSP protocol, or assets.

## Supported behavior

- Browser/Web: open /ag06/ over HTTPS, grant microphone access, choose the OS-recognized AG06 input, view live stereo USB digital input levels, and record software-processed audio.
- Windows: Electron wrapper for the same local offline HTML/JS (no network required for core audio). Portable EXE builds via GitHub Actions.
- Android: separate Android WebView APK with the same frontend bundled offline via WebViewAssetLoader and a trusted local HTTPS-style origin. Android USB audio/OTG support varies. The APK does not add a Yamaha driver or direct USB DSP protocol. Native recording export uses Android MediaStore (Music/XStageAudio) and is limited to 24 MiB per recording.
- All platforms: HPF, low/mid/high EQ, compression threshold, reverb, guitar saturation and output gain affect **captured stereo USB mix** via Web Audio. Monitor playback is disabled by default to reduce feedback risk. Browser recording uses a supported MediaRecorder format (WebM/Opus, Ogg/Opus or MP4/AAC depending on platform).

## Does not control the physical mixer

The original AG06's internal DSP presets, compressor, SPX reverb, amp simulator and physical GAIN/PAD/+48V/TO PC/LOOPBACK/MONITOR MUTE controls remain on the hardware/Yamaha controller. The Yamaha USB DSP command protocol has not been verified for an independent third-party implementation, so the UI must not advertise hardware changes. USB 2-IN/2-OUT does **not** expose six independently controllable recording channels.

To adjust the device's internal DSP use Yamaha AG Controller / AG DSP Controller on officially supported platforms. The first-generation AG06 is not the AG06MK2.

## Local development

- Web: serve the repository root on http://localhost (a potentially trustworthy secure context), then open /ag06/. Other insecure origins cannot request microphones.
- Windows: cd ag06/desktop && npm install && npm start. For Windows portable EXE: npm run dist (on Windows).
- Android: cd ag06/android && gradle :app:assembleDebug with Gradle 8.11.1, Android SDK 35 and JDK 17; installation requires allowing sideloading. Preview debug APK uses the repository's stable *public X-Stage test key* for repeatable sideload updates (debug package suffix), never a production signing identity.
- Contract/unit tests: node --test ag06/tests/*.test.mjs.

### Audio setup

1. Connect first-generation AG06 via USB; on Windows install the **Yamaha Steinberg USB Driver** from Yamaha.
2. Choose the AG06/03 input if offered; otherwise check OS audio input selection.
3. Press Start Audio and grant microphone permission. The actual Web Audio sample rate is displayed and is not necessarily the AG06 hardware's 192 kHz maximum.
4. Use headphones if enabling local monitoring. When AG06's physical TO PC switch is in LOOPBACK, beware of creating an acoustic or digital feedback loop.
5. Record, stop, then explicitly save/download the file; audio stays local and is not uploaded to X-Stage.

### Security and limits

- Input audio is never uploaded. Only software settings are stored locally in browser localStorage.
- Android MediaStore writes a user-triggered recording using a limited MIME allowlist, size limit and fixed filename. No server is required for the audio engine after installation.
- EXE and APK produced in CI are **preview artifacts** until the builds, devices, signing and download-channel integrity are validated. A successful GitHub Actions compile alone does not prove AG06/Android OTG functionality or hardware DSP access.
- Background audio capture depends on platform media lifecycle; browsers and Android may suspend or disconnect microphone input when backgrounded.
- No claimed Yamaha reverse-engineered proprietary control, DAW bundling, or third-party licensed software redistribution.

Official Yamaha information:
- https://usa.yamaha.com/audio/streaming-gaming/products/mixers/ag-series/specs.html
- https://usa.yamaha.com/audio/streaming-gaming/products/mixers/ag-series/support.html
- https://usa.yamaha.com/audio/streaming-gaming/explore/guides/ag-controller.html
