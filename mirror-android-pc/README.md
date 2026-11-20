# X-Stage Mirror Android PC

Version 1.0.4 · Build 1005 · Windows 10/11 x64 · Preview

## Build 1005

The welcome-screen version/build is taken from the compiled assembly.
Windows Wireless Display launch is shown only as a requested action, not
as a verified Miracast video connection. Hardware verification remains required.

Miracast receiver launcher with the same full-screen welcome UX as X-Stage Mirror iOS PC: matching centered branding, large No.XXXX, gradient/ring background and window controls. F1 shows diagnostics; F5 reopens the Windows receiver; F6/F7 open Windows settings. A right-click menu provides these recovery actions without cluttering the welcome screen. The storefront icon, Windows EXE icon and welcome logo all use a distinctive green Android robot. A persistent X-Stage No.XXXX is shared with Mirror iOS PC; the real Windows hostname is displayed so Android senders can find the correct Miracast receiver.

The app opens Windows Wireless Display automatically at startup. The native Windows receiver owns video and permissions. A running Connect process is not proof of a connected sender. The interface intentionally does not invent connected device names.

The Windows EXE is self-contained and includes the .NET 8 desktop runtime. The app does not require separate application dependencies, but Windows must have compatible Wi-Fi Direct/Miracast drivers and the Wireless Display optional feature. Google Cast-only senders cannot connect with Miracast.

On startup and at most every 30 minutes, the app reads the published preview manifest. A newer build is downloaded only from the expected GitHub release URL and checked against its exact filename, semantic version, SHA-256 digest, size and PE executable header before an in-place per-user installer launch. Failed network or denied installer permissions leave the existing application usable.

Build: dotnet publish mirror-android-pc/XStageMirrorAndroidPC.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -o mirror-android-pc/out

CI: .github/workflows/build-xstage-mirror-android-pc.yml followed by .github/workflows/publish-xstage-mirror-android-pc-preview.yml.

Physical Android/Windows Miracast casting is not yet hardware-certified.

Preview publication uses the repository's configured release publishing identity,
then verifies Setup and portable SHA-256 before activating the update feed.
