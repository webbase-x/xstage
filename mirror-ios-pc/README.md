# X-Stage Mirror iOS PC

**v1.0.11 · Build 1012 · Windows 10/11 x64 · Preview**

The Windows iOS AirPlay receiver is now a **full-screen kiosk-style screen receiver**. It starts automatically when opened, without a start button or navigation through settings.

## Auto-update file locking fix (Build 1010)

The previous updater downloaded an installer to a .partial file with exclusive
FileShare.None access, then tried to reopen that same file for PE header
verification *before* the writer was disposed. This reliably caused
`IOException: The process cannot access the file ... because it is being used
by another process` even without any third-party process locking the file.

Build 1010 disposes the writer before reopening for PE header validation,
while preserving SHA-256, size, URL and Windows PE safety checks. A Windows
regression test exercises the real private downloader with a local in-memory
HTTP response and proves the verified file can be reopened with exclusive access.
Build 1006/1009 cannot repair themselves until the new version is installed;
once the fixed version is installed, subsequent updates use the corrected path.

## Stop Mirroring recovery (Build 1011)

The native receiver now uses -nc no to close video on Stop Mirroring.
If the iPhone video TCP connection disappears while its AirPlay control
connection persists, two consecutive process-owned TCP observations trigger
hiding the stale video window and returning to the waiting screen.
A surviving old control TCP connection cannot restore the stale frame.
UxPlay and Bonjour stay alive. This does not detect every case of a sender
that stops video but keeps all sockets open; test on real Windows and iOS.

## Stale frame fallback after client goes offline (Build 1012)

A real iPhone-to-Windows report confirmed Build 1011 still left the last
Control Center frame on display after Stop Mirroring. Inspecting the pinned
libuxplay source showed that loss of client feedback deliberately sets
`close_window = false` unless the `-nofreeze` flag is enabled.
Build 1011 enabled `-nc no` (explicit RTSP Stop Mirroring), but it did not
cover this independent network-reset path.

Build 1012 writes these UxPlay arguments at every receiver startup:

`-nc no -nofreeze -reset 6`

`-nc no` requests closing the native renderer on an explicit stop;
`-nofreeze` prevents retained final frames on disconnected/offline reset;
`-reset 6` reduces UxPlay's feedback-silence reset from the 15-second
default to 6 seconds. It does NOT imply a guaranteed zero-delay shutdown
or detect a sender that continues sending valid heartbeats after stopping
video. The existing PID-owned socket monitor remains a backup. No
per-frame pixel comparison or forced restarts are used.

The unit/CI contract asserts the exact full startup flags, but success on
the user's real Windows+iPhone setup still needs post-install verification.

## Full-screen interface

The waiting screen shows a centered **X-Stage Mirror iOS PC brand logo** above
the main title. The logo is rendered from the same SVG as the installed Windows
app icon at 512×512, then embedded as a named resource inside the single-file
EXE. It never makes an external network request and is scaled with Zoom to
retain its aspect ratio and transparency. On resize, the logo, receiver title,
number, version, connection status and network status are laid out in separate
non-overlapping bands; the upper-right minimize/close buttons stay in place.

The waiting screen displays only:
- large **X-Stage Mirror PC / No.XXXX**, using the stable receiver identity persisted under `%LOCALAPPDATA%\X-Stage\Mirror\receiver-number.txt`;
- small app/version/build metadata;
- minimal AirPlay readiness / local Wi-Fi or Ethernet IPv4 status.

The four-digit number remains stable after app restarts and upgrades. The iOS AirPlay receiver advertises the equivalent name with non-breaking spaces, because the pinned upstream launcher splits `arguments.txt` on ASCII spaces.

Once an iPhone/iPad starts mirroring, the **native UxPlay/GStreamer video window** takes over the full physical display. X-Stage requests full-screen D3D11 output through upstream Qt settings and applies a one-time native HWND fullscreen fallback when necessary. The waiting window stays behind the video so that on normal disconnect it becomes visible again. **No screen capture, frame copies, or SetParent** are used; those approaches add latency and can destabilize hardware video sinks.

The renderer window is owned by the packaged UxPlay engine, not WinForms. Source-protected DRM content may remain blocked.

## One AirPlay name and immediate return to welcome (Build 1009)

The receiver advertises **X-Stage Mirror PC No.XXXX** once and only once.
The Windows UxPlay wrapper splits its settings file on literal ASCII spaces,
so ordinary spaces in the `-n` value would be interpreted as separate UxPlay
arguments. Previous releases used NBSP but the app's `.NET Regex` treated it
as whitespace and replaced only part of the old device name; the remaining
tokens accumulated and iPhone displayed duplicated names. NBSP also prevented
natural line wrapping, forcing a line break after `X-`.

Build 1009 writes a **fresh canonical `-n` argument** on every start, and
uses U+2002 en-spaces between name words: UxPlay receives one Unicode name,
while iOS may wrap the label between words instead of after the initial `X-`.
It retains the persisted receiver number, replaces all previously accumulated
name fragments, and saves the old file only once to
`%LOCALAPPDATA%\\X-Stage\\Mirror iOS PC\\uxplay-arguments-before-xstage.txt`.
This receiver deliberately owns its UxPlay settings file; third-party custom
arguments from that file are preserved in the backup, not merged into the
live X-Stage receiver, to avoid duplicating name/option tokens.

When a previously connected sender's TCP session disappears, X-Stage checks
for the transition about twice a second and hides the native video window.
The waiting UI becomes visible immediately on detection. UxPlay, Bonjour,
and the app remain alive for the next AirPlay session; if UxPlay reuses the
same window it is restored when another sender reconnects. If the native
rendering window itself closes first, the waiting screen is already beneath
it. This is network/session-driven, not an unsupported claim of zero latency;
a device that keeps TCP connected after stopping video may retain its native
window until UxPlay itself closes it. Validate on real iOS and Windows hardware.

## Addressing stream freezes

On some Windows GPUs, GStreamer D3D12 video rendering or resolution changes can fail; D3D11 is the default. The application also disables optional UxPlay Bluetooth discovery for LAN use to avoid an unnecessary helper process. These settings are applied to the pinned upstream UxPlay Qt registry configuration at startup and original values are restored after **normal** shutdown. The user's renderer preference (D3D11 or Auto) persists in `%LOCALAPPDATA%\X-Stage\Mirror iOS PC\renderer.txt`.

A frozen image **cannot be diagnosed reliably by checking whether the receiving process is alive**; the UI does not falsely claim to measure active frame delivery. The app therefore does not forcibly interrupt an apparently active stream. After a drop, it waits for UxPlay to recover normally. If the receiver process exits unexpectedly, X-Stage attempts a limited restart. Repeated freezes still require a hardware/network test and upstream logs.

### Keyboard support (hidden while waiting)

- **F1** — connection and network diagnostics
- **F5** — restart the receiver after confirmation (disconnects the current sender)
- **F8** — change between D3D11 and Auto renderer and restart, with confirmation
- **F9** — toggle experimental fast-response 720p30 mode; confirmation restarts the receiver
- **Esc** — exit X-Stage after confirmation
- **Alt+F4** — exit using Windows

When video fills the display, the native renderer may receive the keystrokes instead of X-Stage. Use Alt+Tab to switch to the receiver shell before pressing F1/F5/F8. Do not assume these keys work within GStreamer.

## Windows Firewall consent persistence (Build 1009)

The optional **Allow X-Stage AirPlay discovery on trusted Private networks**
checkbox is preselected on a first installation, but `checkedonce` makes it
unchecked during manual upgrades. This is intentional: we must not silently
override a user's previous network consent. Previous installers nonetheless
removed X-Stage's existing private firewall rules on every upgrade even when
this task was unchecked. Build 1008 scopes all three rule deletions and adds
to the `privateairplay` task; when unchecked, the existing rules are preserved
unchanged. When the user checks it, the app-specific Private-profile rules
are refreshed. Uninstall removes the three X-Stage rules but never unrelated
Windows or third-party network permissions. Automated `/VERYSILENT`
upgrades retain the existing private-network configuration.

## Bonjour service upgrade compatibility (Build 1009)

In Build 1006, the all-in-one Windows installer re-copied
`engine/uxplay-windows/mDNSResponder.exe` into the application directory
every time. If that binary was running as the Windows **Bonjour Service**,
Inno Setup's Restart Manager displayed an "Automatically close the
applications" prompt or stopped the service. Build 1007 excludes the
binary from the recursively replaced application files and installs it as
a separate **missing-file-only** entry, with an early `Check` so Restart
Manager does not consider the already present and in-use binary. The binary
is retained during uninstall while an existing Windows service may still
refer to it. The actual Bonjour Service registration happens only if the
service is not installed. Do not forcibly stop a shared Bonjour service
during ordinary X-Stage upgrades.

Fresh installations still include the verified bundled mDNSResponder and
AirPlay runtime, and do not require an extra download. The installer and
X-Stage source change do not modify an existing non-X-Stage Bonjour service
binary installed elsewhere. A real Windows upgrade with Bonjour running
should still be checked before treating the issue as fully confirmed.

## Packaging and privacy

The Setup EXE embeds the self-contained .NET runtime, UxPlay, GStreamer plugins and Bonjour service. No extra application runtime downloads are required. On trusted **Private** LANs the installer offers consented firewall rules. A first-time Bonjour service registration may ask Windows for administrator permission. There are no remote relay accounts.

The app presents the actual detected local network IP. Connected sender IPs can be inspected using F1 when netstat detects established UxPlay connections; it does not invent an iPhone name or frame rate.

The Windows receiver is separated from **X-Stage Mirror Android PC**; the latter uses Windows-native Miracast and is not changed by this release.


## Desktop icon (Build 1009)

The Windows installer always creates a **X-Stage Mirror iOS PC** desktop shortcut, including during /VERYSILENT automatic upgrades. The shortcut points to the installed executable, uses the embedded branded ICO, and is removed by the installer uninstall process. The Start menu shortcut continues to be created. No manual shortcut option is required.

## Automatic upgrades (Build 1009)

- The running PC receiver checks the exact X-Stage iOS PC preview feed at launch and every 30 minutes, with a short network timeout for the feed.
- When a newer matching Windows build is published, the client automatically downloads the **complete Setup EXE** from the specifically named GitHub Release. It checks platform, app, monotonic build, semantic version, exact asset URL/file name, executable header, size limits and SHA-256. Only that checked file may launch.
- It starts the new installer **immediately without another app dialog**, using Inno Setup silent mode. Windows still controls any required UAC elevation; denying elevation leaves the old app intact.
- **An active mirroring session is interrupted** during installation. The installer uses the same application identity and keeps existing settings; its silent install run step reopens the new receiver after success.
- If the network or hash verification fails, the installed receiver continues running and retries at the next check. A failed download is not executed. The application does not claim an upgrade succeeded merely because the installer started.
- Updates are scoped to the X-Stage iOS PC Windows installer, never an untrusted URL, an Android APK, a raw control EXE, or an unrelated product. Updater files are staged in the user's LocalAppData.
- Source SVG is converted to an ICO inside GitHub Actions and embedded in both the Windows app EXE and installer. Shortcuts inherit the application icon.

## Build and release

`dotnet publish mirror-ios-pc/XStageMirrorIOSPC.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -o mirror-ios-pc/out`

CI workflow `.github/workflows/build-xstage-mirror-ios-pc.yml` compiles the desktop application, validates the pinned upstream runtime's SHA-256, creates a complete Windows Setup EXE plus Portable ZIP, and verifies checksums. A separate release workflow publishes a preview and updates `downloads/mirror-ios-pc-preview-latest.json` **only after** packaging succeeds.

**Preview means packaging verified, not physical iOS/Windows hardware validated.** Before claiming the freeze is fully resolved, test on actual iPhone/iPad (different rotations and 5–10 minute continuous streaming sessions) and check Wi-Fi isolation, decoder compatibility, and stream logs.
