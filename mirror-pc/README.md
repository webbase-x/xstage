# X-Stage Mirror PC — Windows 10 / 11

**Version 0.1.0 · Build 101 · development candidate, NOT a verified release**

A single Windows control application for two distinct receiver technologies:

- **iPhone/iPad:** starts a locally bundled, GPL-3.0 UxPlay Windows AirPlay receiver from `engine/uxplay-windows/`. The iOS sender needs no app; use Control Center > Screen Mirroring. No cloud or Internet is used for casting on the same LAN. The actual video is displayed by the UxPlay receiver window, not embedded in the X-Stage control surface.
- **Android:** opens the **Windows Wireless Display / Connect** receiver (Miracast), if present. Miracast is an OS and Wi-Fi driver feature. On Windows 11 it may require the Optional Feature "Wireless Display". Android devices without Miracast support cannot mirror using this route. The X-Stage app cannot bypass that restriction, silently install Windows features, or show the native receiving session inside its own window.

Both routes are started from the **same** X-Stage Mirror PC window, but use separate protocol engines under the hood. They must not be described as one universal cross-platform receiving protocol.

## Build from source

```powershell
dotnet publish mirror-pc/XStageMirrorPC.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:EnableCompressionInSingleFile=true -o mirror-pc/out
```

.NET 8 Windows Desktop SDK required only to **build**. Published XStageMirrorPC.exe is self-contained. Receiver runtime binaries are separate files under `engine/uxplay-windows/` in the released ZIP; do **not** distribute a GUI-only build as a functional AirPlay receiver.

`.github/workflows/build-xstage-mirror-pc.yml` performs Windows compilation and attempts to package a pinned upstream portable receiver (leapbtw/uxplay-windows 2.0.0.1736). It fails closed if the expected portable x64 zip or a SHA-256 digest cannot be verified; no stale or unverified package is silently used. Successful workflow artifact remains a **candidate** until actual Windows/iOS/Android compatibility testing. No public update manifest is set to available automatically.

## Operation

1. Extract the whole candidate ZIP (do not run the exe alone).
2. Open `XStageMirrorPC.exe`; the app checks the bundled AirPlay engine locally and reports its status. Start/stop AirPlay using the in-app controls. The sender and Windows PC should share a LAN that allows mDNS and direct traffic. Windows Firewall may ask for consent.
3. On iPhone/iPad: Control Center > Screen Mirroring > select the advertised receiver name. Third-party DRM-protected content may display black/blank video.
4. On Android: press "Open Windows Wireless Display"; install/configure the optional Windows feature if the OS requests it. Open Cast / Smart View on an Android device that supports Miracast and select the PC. Google Cast-only Android devices are not automatically compatible.
5. To change the AirPlay receiver name, use the app's name field, then restart AirPlay. This app writes `%APPDATA%\leapbtw\uxplay-windows\arguments.txt` **only with explicit user confirmation if an existing non-X-Stage config is detected**. A machine-wide `%ProgramData%\uxplay-windows\arguments.txt` overrides per-user settings and is never overwritten. The native Windows Miracast name comes from Windows PC settings, not the AirPlay name.
6. Use the Windows sound and projection controls for native session management. Closing this control application stops only the UxPlay process that *it launched*, not unrelated receivers.

## Scope and security

- The status "AirPlay server running" means the **process is alive**, not that a sender is connected. Native Windows Miracast session and connected-device status are managed by Windows.
- No fake QR-based system pairing: Apple does not offer a public QR-to-Screen-Mirroring handshake.
- No accounts or cloud relays. Internet is only relevant to checking the release manifest.
- No hidden firewall modification, OS optional-feature installation, or automatic trust of unknown incoming clients. Use a trusted LAN and configure AirPlay PIN through the underlying receiver if required.
- This prototype does not claim sub-100ms latency, device support without physical tests, a signed installer, seamless updates, or video recording.
- Windows 10 reached end of support in October 2025; it may work but Microsoft no longer provides general free security updates.
- UxPlay / uxplay-windows are GPL-3.0 projects; release a complete corresponding source and license notices with any redistributed binary. Upstream: https://github.com/leapbtw/uxplay-windows and https://github.com/FDH2/UxPlay. X-Stage is not affiliated with Apple or Microsoft.

## Release/update feed

`downloads/mirror-pc-latest.json` starts with `available: false`. Do not publish a download link until a verified, complete package and GPLv3 compliance artifacts exist. This build provides manual release checking; self-updating is deliberately not advertised until a verified updater is added.
