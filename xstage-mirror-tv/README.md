# X-Stage Mirror TV (Android TV / TrueID TV)

An independently branded GPLv3 Android TV AirPlay receiver for iPhone and iPad.
No iOS app, accounts, or internet cloud service required for casting on the local network.

## Scope and behavior

- Runs on compatible Android TV / Google TV / TrueID TV boxes (device-specific validation required).
- v0.2.1 baseline improvements (retained in v0.2.2): H.264 (wider hardware compatibility), AUTO video
  advertising capped at 1080p/30fps even on a 4K TV; manually selected resolutions
  and frame rates still override the default.
- **Auto Performance v0.2.2**: reads the hardware AVC decoder's frame-rate and
  resolution capabilities and chooses the highest practical motion-first profile
  automatically; no user selection needed.
- During mirroring it checks decoded-frame pacing, compressed-input drops and
  sustained load in 2-second windows. When video accumulates a backlog it
  discards only **already decoded** older display images, never H.264/H.265
  reference packets, so a live session stays connected.
- On sustained overload, saves a lower resolution/FPS profile for the **next**
  mirroring session; after three long stable sessions it cautiously upgrades.
  The sender's negotiated stream is not guaranteed to accept mid-session
  quality changes, so the app never forcibly disconnects the iPhone.
- Decoder input backpressure bounded to about 25ms per packet (100ms startup),
  instead of the previous 200ms/1s worst-case waits. This reduces stalling,
  but overload can still cause dropped frames; try 720p30 first if stutters persist.
- Android NSD retries failed AirPlay announcements with bounded backoff.
- Video GL surface prewarmed on receiver start; diagnostics log elapsed receiver
  startup, connection-to-video-size, and connection-to-first-video-packet times.
- iOS Control Center > Screen Mirroring discovers the configurable receiver name.
- Default receiver name: **X-Stage Mirror TV**. The brand prefix is fixed. On the **Overview (first screen)** select **✎ เปลี่ยนชื่ออุปกรณ์**, type an optional suffix such as **ห้องประชุม** or **TrueID ห้องนั่งเล่น**, review the preview, and select **บันทึกชื่อ**. The full name (for example, **X-Stage Mirror TV ห้องประชุม**) appears on the first screen, in iPhone/iPad Screen Mirroring discovery, and in the QR setup guide. Settings offers the same editor.
- Suffix is limited to keep the entire receiver name within 64 characters. An empty suffix restores **X-Stage Mirror TV**. The new name persists across app restarts and a normal restart of AirPlay discovery applies the change. Rename is disabled while a sender is connected to avoid interrupting an active mirroring session. Older free-form receiver names are migrated into the suffix on first launch.
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
- Automatically deletes **only app-private downloaded update APKs** after a
  successfully installed newer or equal build, using Android's
  `MY_PACKAGE_REPLACED` broadcast plus a startup fallback. Future versions
  staged for installation are not deleted early. Public Downloads and the
  original installer APK are never touched.
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
5. On the receiver’s first screen select **✎ เปลี่ยนชื่ออุปกรณ์**, enter only the suffix, then **บันทึกชื่อ**. After the announcement restarts, use the new name from the iOS list. When a sender is active, disconnect before editing.
6. Check audio/video sync, portrait/landscape, reboot autostart, disconnect/reconnect.
7. For timing diagnostics, enable Settings > Developer options > benchmark log
   and capture logcat from the physical TV box. For example:
   `adb logcat -v time -s AirPlayService:I XStageMirrorDiscovery:I VideoRenderer:W BENCHMARK:I`
   (exact service log tag may vary by build).
   Record iPhone selection-to-first-visible-frame, FPS, frame drops and jitter
   while scrolling at each preset. Static CI builds cannot verify physical
   TrueID TV networking or measure end-to-end mirroring latency.

**Security:** PIN-free reception is intended for trusted private networks.
Anyone on the LAN may be able to request mirroring; turn on a PIN in Settings
on shared networks. TrueID's own TV firmware may restrict background startup,
network multicast discovery or unknown-source installs.

The QR on the TV is for onboarding / receiver identification, NOT AirPlay pairing:
iOS does not expose a public API for QR-initiated system-wide Screen Mirroring.

## License

GPL-3.0; upstream copyright and NOTICE preserved. Not affiliated with Apple Inc. or TrueID.


## White TV launcher banner and Home icon

Mirror TV publishes a **white 16:9 Android TV banner** at 320×180 and 640×360,
with the distinct dark receiver-casting icon and high-contrast navy/cyan text.

On the idle screen choose **☆ เพิ่มแอปที่หน้าหลักทีวี**. If the current Android
TV launcher supports pinned shortcuts, confirm the OS prompt. Otherwise the
app opens the Home screen; use the remote to select **Favorite Apps > Add app (+)
> X-Stage Mirror TV**. On some TrueID launchers the Favorites command differs,
or sideloaded apps cannot be added automatically. The app cannot change
Launcher Favorites without user approval. The Home action is disabled while a
sender is connected to avoid interrupting active Screen Mirroring.
