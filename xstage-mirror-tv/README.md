# X-Stage Mirror TV (Android TV / TrueID TV)

An independently branded GPLv3 Android TV AirPlay receiver for iPhone and iPad.
No iOS app, accounts, or internet cloud service required for casting on the local network.

## Scope and behavior

- Runs on compatible Android TV / Google TV / TrueID TV boxes (device-specific validation required).
- iOS Control Center > Screen Mirroring discovers the configurable receiver name.
- Default receiver name: **X-Stage Mirror TV**; change it in the receiver's Settings.
- Automatically starts receiving on launch/boot (subject to Android background restrictions).
- No receiver PIN by default; existing iOS consent to start screen sharing still applies.
- One sender at a time by default: incoming senders cannot silently preempt a session.
- H.264/H.265 and audio decode use the existing upstream Android UxPlay/MediaCodec path.
- Displays a **QR setup guide** on the receiver's idle screen. Scanning opens
  /mirror-tv/ with the receiver name; QR cannot automatically trigger iOS mirroring.
- Mirroring of DRM-protected apps is not supported.

## Build and release

Source is built from a **pinned upstream commit**:
[AirShow a0eeef2](https://github.com/omerekelly/airshow/commit/a0eeef208a60f69a56faadbd39eb1e1de001208c),
which is itself based on jqssun/android-airplay-server and UxPlay.
See prepare_upstream.py for all brand, preference and QR UI changes.

GitHub Actions: [Build X-Stage Mirror TV](../../actions/workflows/build-xstage-mirror-tv.yml).
The successful workflow uploads **X-Stage-Mirror-TV-AndroidTV** containing:
an APK for ARMv7/ARM64, SHA256 checksums, and full corresponding source (including
the upstream LICENSE and NOTICE, patches and submodule sources). APK is debug-signed
for device testing; a production release requires a private signing key and
verification with the physical TrueID box.

Building manually: run the steps in .github/workflows/build-xstage-mirror-tv.yml.
Keep the GPLv3 and upstream attribution when redistributing modified binaries.

## Install and test

1. On the TV box, enable installation from a trusted source and install the generated APK.
2. Open **X-Stage Mirror TV**; allow Local Network access if requested.
3. Connect iPhone and TV to the same LAN (no guest network / AP isolation).
4. On iPhone: Control Center > Screen Mirroring > select the receiver's displayed name.
5. Use Settings on TV to rename the receiver; wait for its AirPlay advertisement to restart.
6. Check audio/video sync, portrait/landscape, reboot autostart, disconnect/reconnect.

**Security:** PIN-free reception is intended for trusted private networks.
Anyone on the LAN may be able to request mirroring; turn on a PIN in Settings
on shared networks. TrueID's own TV firmware may restrict background startup,
network multicast discovery or unknown-source installs.

The QR on the TV is for onboarding / receiver identification, NOT AirPlay pairing:
iOS does not expose a public API for QR-initiated system-wide Screen Mirroring.

## License

GPL-3.0; upstream copyright and NOTICE preserved. Not affiliated with Apple Inc. or TrueID.
