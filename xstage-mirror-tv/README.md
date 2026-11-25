# X-Stage Mirror TV (Android TV / TrueID TV)

An independently branded GPLv3 Android TV AirPlay receiver for iPhone and iPad.
No iOS app, accounts, or internet cloud service required for casting on the local network.

## Mirror TV receiver — v0.2.17 (Build 119)

- Stability-first AUTO starts at 720p30 where supported; adaptive quality learns within 30 FPS profiles and can upgrade to 1080p30 after three stable sessions. Manual settings remain available; no forced disconnect to renegotiate.
- Rebase discontinuous video presentation timestamps outside a 250 ms window, and reset after catch-up so old timestamps do not park decoder buffers.
- Retry failed mDNS announcements with capped 30-second backoff until receiver teardown, ignoring stale failure callbacks and cleaning up late registration. This restores discovery after registration failure, not the iOS sender session itself.
- Actual iPhone/TrueID long-duration testing is still required; CI is a build and source-contract check.

### Previous v0.2.16 (Build 118)

- Live AirPlay HLS errors now retry outside the Media3 error callback, avoiding re-entrant stop/prepare calls. Unexpected live-playlist END triggers bounded source recovery at the live edge rather than ending the receiver immediately.
- Normal completed video-on-demand continues to close without retry. The independent screen mirroring pipeline remains unchanged.
- An actual iPhone / TrueID TV live-stream hardware test remains required.

### Previous v0.2.15 (Build 117)


- AirPlay live HLS recovery: distinguish a live stream from on-demand video after the media timeline is known. If the live stream buffers for 12 seconds, restart just its ExoPlayer source and seek to the live edge (never reuse an expired DVR-window position). Limit to 3 consecutive retries; reset the counter only after sustained stable playback. On failure show a message rather than trapping the user in a spinner.
- Video-on-demand retains its 18-second timeout and one bounded retry. Mirrored phone-screen video is decoded by a different pipeline and is not restarted by the HLS recovery mechanism.
- Device validation is required with an actual live stream and the user's TrueID device. YouTube DRM/restricted content or the sender's network/authentication cannot be bypassed by the receiver.

### Previous v0.2.14 (Build 116)


- A stalled AirPlay video/HLS load gets one bounded retry after 18 seconds; on another timeout it closes video playback with a message instead of loading indefinitely. Screen mirroring is independent and remains running.
- Remote Back closes the rename editor or returns from Settings to the home view; Save and Cancel close the rename editor. During video playback Back leaves only the video player. App-exit confirmation is for the home screen.
- Physical iPhone/TrueID validation is still needed.

- On opening the APK, the AirPlay receiver starts automatically when local networking is available. The previous auto-start preference no longer blocks startup.
- The main screen displays the receiver name, a compact **Version / Build** line sourced from Android BuildConfig, readiness/connection status and a concise iPhone/iPad instruction. Debug logs, a QR setup guide and manual start/stop/exit buttons do not clutter the home screen.
- **เปลี่ยนชื่อ** reveals the existing inline name editor only on demand. **ตั้งค่า** opens advanced options.
- While mirroring, the picture fills the entire display without app overlays. Pressing the TV remote **Back** key prompts **ปิด** (stop receiver and finish the app) or **ไม่ปิด** (keep receiving).
- Permissions and errors remain visible when reception cannot begin. Identifiable Android emulators start AUTO video at a conservative 720p30 (or lower on small displays); physical Android TVs retain normal hardware-adaptive selection. Disconnections now log elapsed connection time and whether a video size or first video packet was received. Runtime device validation on TrueID hardware and BlueStacks 5 is still required.

## Scope and behavior

- Runs on compatible Android TV / Google TV / TrueID TV boxes (device-specific validation required).
- v0.2.1 baseline improvements (retained in v0.2.2): H.264 (wider hardware compatibility), AUTO video
  advertising capped at 1080p/30fps even on a 4K TV; manually selected resolutions
  and frame rates still override the default.
- **v0.2.7 (Build 109) TV usability**: receiver room-name editing is now inline rather
  than a modal dialog, so the field remains inside the scrollable overview when
  the TV keyboard appears. The keyboard's Done/Enter or a hardware Enter key
  saves the name; the Save button remains available. The focus path follows the
  visible editor (rename → text field → save/cancel), and left/right switches
  between action buttons. The overview can scroll on smaller TrueID displays.
  Settings choices and the bottom navigation use grouped remote focus, brighter
  labels, and a more prominent selected-state color. Physical TrueID remote and
  keyboard behavior still require on-device validation.
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
- Default receiver name: **X-Stage Mirror TV**. The brand prefix is fixed. On the **first screen** select **เปลี่ยนชื่อ** and then **✎ เปลี่ยนชื่ออุปกรณ์**, type an optional suffix such as **ห้องประชุม** or **TrueID ห้องนั่งเล่น**, review the preview, and select **บันทึกชื่อ**. The full name (for example, **X-Stage Mirror TV ห้องประชุม**) appears on the first screen, in iPhone/iPad Screen Mirroring discovery, and in the QR setup guide. Settings offers the same editor.
- Suffix is limited to keep the entire receiver name within 64 characters. An empty suffix restores **X-Stage Mirror TV**. The new name persists across app restarts and a normal restart of AirPlay discovery applies the change. Rename is disabled while a sender is connected to avoid interrupting an active mirroring session. Older free-form receiver names are migrated into the suffix on first launch.
- Automatically starts receiving on launch/boot (subject to Android background restrictions).
- No receiver PIN by default; existing iOS consent to start screen sharing still applies.
- One sender at a time by default: incoming senders cannot silently preempt a session.
- H.264/H.265 and audio decode use the existing upstream Android UxPlay/MediaCodec path.
- Previously displayed a **QR setup guide** on the receiver's idle screen (now hidden on the minimal home). Scanning opens
  /mirror-tv/ with the receiver name; QR cannot automatically trigger iOS mirroring.
- Mirroring of DRM-protected apps is not supported.
- All AirPlay/UxPlay native libraries and codecs are bundled into **one APK**.
  No separate codec, helper, SoundFont, media server, or iOS app is downloaded.
- **v0.2.8 (Build 110) safe in-place upgrades**: official and preview
  releases must use the same **persistent private Android signing key**.
  The update manifest records the signing certificate SHA-256. At launch the
  receiver compares it to its installed APK's signer, in addition to comparing
  versionCode and validating the downloaded APK SHA-256. Compatible newer APKs
  are handed to Android's system installer, which still requires user approval
  and preserves app data. A signature mismatch is reported **before** downloading
  an APK; the app remains installed and LAN casting remains available.
  Both publishing workflows reject accidental signing-key changes, and the
  preview workflow audits the original public Build 107 APK certificate.
  **Build 107 compatibility cannot be guaranteed:** if it was installed from
  the debug-signed APK and its original private signing key is unavailable,
  Android does not permit an in-place update to a newly signed APK. Changing
  package name, version, or manifest cannot bypass this security rule. Do not
  uninstall until the receiver name and settings have been noted and a safe
  replacement plan is available. Builds 110 and later signed with the same
  persistent key are designed to update in place.
- Starting in **v0.2.5 (Build 107)**, checks both the production-signed
  `mirror-tv/latest.json` and preview `mirror-tv/test-latest.json` on every
  app launch; Settings also has a manual "ตรวจสอบอัปเดต" button.
  A newer **production** release is downloaded, checked with SHA-256 and
  package/version, and handed to Android's standard user-approved installer.
  Starting in **v0.2.6 (Build 108)**, newer previews signed by the SAME
  persistent PRIVATE signing certificate as the installed app are downloaded,
  SHA-256 checked and offered to Android's standard installer with user
  approval, retaining installed app data. The installed certificate is
  inspected on-device; if it differs, a warning and first-party download
  link are shown instead of forcing an unsafe replacement. Legacy debug-signed
  Builds 107 and older cannot be made compatible retrospectively when their
  ephemeral signing keys are no longer available. A ONE-TIME uninstall of
  a legacy preview may be necessary (and may erase its app settings).
- Automatically deletes **only app-private downloaded update APKs** after a
  successfully installed newer or equal build, using Android's
  `MY_PACKAGE_REPLACED` broadcast plus a startup fallback. Future versions
  staged for installation are not deleted early. Public Downloads and the
  original installer APK are never touched.
- **Fail-closed preview signing**: Build 108 and newer cannot publish an APK
  without the same four private `XSTAGE_MIRROR_*` signing secrets used by
  official releases. No debug fallback is allowed. The release APK is built
  non-debuggable and signed by Gradle; CI pins the public SHA-256 fingerprint
  and refuses to rotate it in later releases. All keys and local.properties
  are excluded from GPLv3 source and public artifacts.
  A newer same-signer preview can trigger Android's user-confirmed in-place
  installer flow; it never silently installs updates.

## APK signer audit — Android SDK Build Tools 37

The shared `verify_apk_signer.py` accepts the older `Signer #1 certificate SHA-256 digest`
and newer `V3.0 Signer: certificate SHA-256 digest` output from
`apksigner verify --verbose --print-certs`. Both preview and production jobs
compare the **verified APK certificate SHA-256** with the certificate exported
from the configured **persistent private keystore**. A missing, conflicting or
unexpected identity always fails publication; this is a parsing compatibility
fix, not a signing bypass. The preview workflow runs parser regression tests
before compilation.

## One-time signing fix (GitHub Codespaces)

If [Build X-Stage Mirror TV](../../actions/workflows/build-xstage-mirror-tv.yml)
stops at `Require persistent private signing key`, the four encrypted GitHub
Actions secrets have not been configured. **This is not a Kotlin compile error.**
Never commit a private key, publish one as a CI artifact, or silently fall back
to a rotating debug signing certificate.

For a repository administrator, the setup below can initialize a **new private
persistent certificate once** and publish its four secret values directly via
the GitHub CLI, without putting passwords in the repository:

1. Open the **webbase-x/xstage** repository in a GitHub Codespace (or a trusted
   Linux/macOS terminal containing `gh`, `keytool` from JDK 21, `python3`, and
   `base64`). In the repository terminal, authenticate `gh` with the repository
   owner's privileges if necessary: `gh auth login -h github.com`.
2. Run `bash xstage-mirror-tv/setup-signing.sh` and follow its prompts.
   **The generated password is shown once**: save it in a private password manager.
   The PKCS#12 keystore stays at `~/.config/xstage/mirror-tv-release.p12`,
   outside the repository. Back up that file privately *outside the Codespace*.
3. The script verifies the local key/certificate, refuses accidental key
   rotation, uploads the four encrypted `XSTAGE_MIRROR_*` secrets using
   `gh secret set` via stdin, and requests the signed Build from the `main`
   branch. Monitor its [GitHub Actions workflow](../../actions/workflows/build-xstage-mirror-tv.yml).
   APK publication occurs **only after** Gradle compilation, APK signature
   verification, certificate checks, package/version checks and checksum pass.

The four repository secrets are `XSTAGE_MIRROR_KEYSTORE_BASE64`,
`XSTAGE_MIRROR_STORE_PASSWORD`, `XSTAGE_MIRROR_KEY_ALIAS`, and
`XSTAGE_MIRROR_KEY_PASSWORD`. The GitHub repository administrator must create
them (directly, or via the script); a GitHub App with source-edit access alone
cannot access or create them.

**If a private Mirror TV signing key already exists**, restore the *same
original* keystore instead of generating a new one. The script rejects a newly
generated identity if GitHub already has a Mirror keystore secret or a prior
published certificate fingerprint. If you only have the old Build 107 debug
APK, you cannot derive its private signing key from that APK. A newly signed
Build 110 cannot be installed over Build 107 when the signatures differ;
a one-time reinstall may be necessary **after preserving settings**. From the
first private-key-signed build onward, keep the keystore/password backed up
and reuse them on every update. Do not uninstall an existing app before a
replacement and its signing compatibility are verified.

## Build and release

Source is built from a **pinned upstream commit**:
[AirShow a0eeef2](https://github.com/omerekelly/airshow/commit/a0eeef208a60f69a56faadbd39eb1e1de001208c),
which is itself based on jqssun/android-airplay-server and UxPlay.
See prepare_upstream.py for all brand, preference and QR UI changes.

GitHub Actions: [Build X-Stage Mirror TV](../../actions/workflows/build-xstage-mirror-tv.yml).
The successful workflow uploads **X-Stage-Mirror-TV-AndroidTV** containing:
an APK for ARMv7/ARM64, SHA256 checksums, and full corresponding source (including
the upstream LICENSE and NOTICE, patches and submodule sources). APK is built with a persistent private signing certificate only when the
four encrypted signing secrets are configured; otherwise the signed publication
fails closed. A separate compile-only test never publishes its debug APK.
Real device validation is still required on a physical TrueID box.

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

## BlueStacks 5 emulator limitation

BlueStacks 5 on Windows is **not a validated Android TV receiver target**. Even if the AirPlay service name appears in iOS Screen Mirroring, a connection and usable video are not guaranteed: emulator NAT/virtual networking can prevent Bonjour/mDNS discovery or the inbound TCP media session, and its virtual Android decoder may behave differently from physical TV hardware. Seeing the name alone does not prove that AirPlay setup or video decoding has succeeded. Do not present emulator testing as proof of TrueID compatibility.

When the goal is to display an iPhone/iPad on a Windows computer, use the dedicated native **X-Stage Mirror iOS PC** receiver from the storefront (`?app=mirror-ios-pc`), on the same trusted LAN, rather than trying to route AirPlay through BlueStacks. For TV reception, test the Android APK on a physical Android TV / Google TV / TrueID device. This does not claim BlueStacks can be repaired solely through APK changes.

## Install and test

1. On the TV box, enable installation from a trusted source and install the generated APK.
2. Open **X-Stage Mirror TV**; allow Local Network access if requested.
3. Connect iPhone and TV to the same LAN (no guest network / AP isolation).
4. On iPhone: Control Center > Screen Mirroring > select the receiver's displayed name.
5. On the receiver’s first screen select **เปลี่ยนชื่อ**, then **✎ เปลี่ยนชื่ออุปกรณ์**, enter only the suffix, then **Enter/Done** on the keyboard or **บันทึกชื่อ**. After the announcement restarts, use the new name from the iOS list. When a sender is active, disconnect before editing.
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

Use the Android TV launcher's **Favorite Apps > Add app (+)** menu to put the app on Home. If the current Android
TV launcher supports pinned shortcuts, confirm the OS prompt. Otherwise the
app opens the Home screen; use the remote to select **Favorite Apps > Add app (+)
> X-Stage Mirror TV**. On some TrueID launchers the Favorites command differs,
or sideloaded apps cannot be added automatically. The app cannot change
Launcher Favorites without user approval. The Home action is disabled while a
sender is connected to avoid interrupting active Screen Mirroring.
