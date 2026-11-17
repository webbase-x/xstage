# X-Stage Mirror iOS PC

**v1.0.4 · Build 1005 · Windows 10/11 x64 · Preview**

The Windows iOS AirPlay receiver is now a **full-screen kiosk-style screen receiver**. It starts automatically when opened, without a start button or navigation through settings.

## Full-screen interface

The waiting screen displays only:
- large **X-Stage Mirror PC / No.XXXX**, using the stable receiver identity persisted under `%LOCALAPPDATA%\X-Stage\Mirror\receiver-number.txt`;
- small app/version/build metadata;
- minimal AirPlay readiness / local Wi-Fi or Ethernet IPv4 status.

The four-digit number remains stable after app restarts and upgrades. The iOS AirPlay receiver advertises the equivalent name with non-breaking spaces, because the pinned upstream launcher splits `arguments.txt` on ASCII spaces.

Once an iPhone/iPad starts mirroring, the **native UxPlay/GStreamer video window** takes over the full physical display. X-Stage requests full-screen D3D11 output through upstream Qt settings and applies a one-time native HWND fullscreen fallback when necessary. The waiting window stays behind the video so that on normal disconnect it becomes visible again. **No screen capture, frame copies, or SetParent** are used; those approaches add latency and can destabilize hardware video sinks.

The renderer window is owned by the packaged UxPlay engine, not WinForms. Source-protected DRM content may remain blocked.

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

## Packaging and privacy

The Setup EXE embeds the self-contained .NET runtime, UxPlay, GStreamer plugins and Bonjour service. No extra application runtime downloads are required. On trusted **Private** LANs the installer offers consented firewall rules. A first-time Bonjour service registration may ask Windows for administrator permission. There are no remote relay accounts.

The app presents the actual detected local network IP. Connected sender IPs can be inspected using F1 when netstat detects established UxPlay connections; it does not invent an iPhone name or frame rate.

The Windows receiver is separated from **X-Stage Mirror Android PC**; the latter uses Windows-native Miracast and is not changed by this release.


## Desktop icon (Build 1005)

The Windows installer always creates a **X-Stage Mirror iOS PC** desktop shortcut, including during /VERYSILENT automatic upgrades. The shortcut points to the installed executable, uses the embedded branded ICO, and is removed by the installer uninstall process. The Start menu shortcut continues to be created. No manual shortcut option is required.

## Automatic upgrades (Build 1005)

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
