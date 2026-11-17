# X-Stage Mirror iOS PC

**Version 1.0.0 · Build 1001 · Windows 10/11 x64 · Preview**

Dedicated AirPlay receiver from iPhone/iPad to Windows. Independent from X-Stage Mirror Android PC.

## Display identity

Shows **X-Stage Mirror PC No.XXXX** at the top of its window. A cryptographically random four-digit number (1000–9999) is generated once per Windows user and saved under `%LOCALAPPDATA%\X-Stage\Mirror\receiver-number.txt`. This same number is shared by the iOS and Android companion apps installed for that Windows user, and remains stable across app restarts and upgrades. It is not an authentication PIN or a pairing code.

When possible, the AirPlay receiver advertises this name via UxPlay. Because the pinned UxPlay Windows launcher parses arguments by ASCII spaces rather than shell quoting, it uses non-breaking spaces internally so the displayed name still looks like **X-Stage Mirror PC No.XXXX** in the AirPlay picker. Check physical iOS device discovery before claiming compatibility. If another globally managed UxPlay configuration overrides X-Stage, the app must not silently overwrite it.

## Ready-to-use environment

The Setup EXE embeds .NET runtime, UxPlay, GStreamer multimedia libraries and bundled Bonjour discovery service. It asks for Windows administrator consent to register Bonjour, and for optional firewall rules **only on Private network profiles**. It does not add firewall exceptions on Public networks.

A complete portable ZIP is also available; the GUI executable alone does not contain the native receiver runtime. The user may need to uninstall/close an older combined X-Stage Mirror PC before starting this AirPlay receiver, so they do not compete for local ports.

## Connected device panel

Uses the UxPlay process ID and its established TCP connections to display verifiable remote IP addresses. A UxPlay-owned video-render window additionally indicates an active rendering session. The application does **not** claim that every TCP peer is casting or guess the iPhone's model/name: UxPlay does not expose a dependable device identity API in this package.

## Build

`dotnet publish mirror-ios-pc/XStageMirrorIOSPC.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -o mirror-ios-pc/out`

CI: `.github/workflows/build-xstage-mirror-ios-pc.yml` → `.github/workflows/publish-xstage-mirror-ios-pc-preview.yml`, SHA-256 validation and corresponding GPLv3 source included. Preview builds are not certified on hardware. iPhone/iPad Screen Mirroring requires local LAN allowing Bonjour/mDNS; DRM video may remain protected.
