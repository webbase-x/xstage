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
- All AirPlay/UxPlay native libraries and codecs are bundled into **one APK**.
  No separate codec, helper, SoundFont, media server, or iOS app is downloaded.
- Automatically checks for signed APK updates at app startup; Settings also
  includes a manual "ตรวจสอบอัปเดต" control. When a valid newer version exists,
  the app downloads it, checks SHA-256 and package/version, then opens Android's
  standard installer. Android may require permission and approval.
- Updates are **disabled until a release is signed and published** using a
  persistent private signing key. This avoids broken and unsafe update flows.

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

### Publish signed automatic updates

A debug-signed APK from Actions is for first-stage testing only: GitHub-hosted
debug keystores are not persistent across builds, so they cannot provide safe
in-place updates. Do **not** publish them as an automatic update.

The separate [signed release workflow](../../actions/workflows/release-xstage-mirror-tv.yml)
accepts a semantic version and monotonically increasing build number, and needs
four encrypted repository secrets:

- `XSTAGE_MIRROR_KEYSTORE_BASE64`: your dedicated **private** Android release
  keystore, base64 encoded. Do not commit it to source control.
- `XSTAGE_MIRROR_STORE_PASSWORD`: keystore password.
- `XSTAGE_MIRROR_KEY_ALIAS`: signing key alias.
- `XSTAGE_MIRROR_KEY_PASSWORD`: key password.

It produces the **fully bundled and signed** APK plus GPLv3 source archive
in a public GitHub Release, then publishes the verified SHA-256 and release
version to `mirror-tv/latest.json` on GitHub Pages. Old apps check that HTTPS
manifest on startup. Publishing is stopped if signing secrets are missing,
the APK build fails, or the version is not newer.

**Important migration:** the earlier v0.1.0 debug APK and the stable release
will have different signing certificates. If v0.1.0 debug was installed, uninstall
it once to install the stable signed build. After that, all updates use the
same private signing certificate and can be installed in place without
reinstalling dependencies or deleting app settings.

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
