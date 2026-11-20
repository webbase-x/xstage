# X-Stage Mirror Android PC

Version 1.0.8 · Build 1009 · Windows 10/11 x64 · Preview

## Build 1009 — reliable setup outcome and readiness

The Windows installer helper now validates the exact `Installed` capability state (never a substring match), checks whether a Wi-Fi adapter is really present **after** Windows Update driver attempts, and reports a meaningful unsupported hardware/driver error when Windows still has none. Setup does not misleadingly report success just because DISM exited.

The welcome screen shows active stages and an elapsed timer; after several minutes it describes Windows Update waiting instead of appearing frozen. The app suspends its own application-upgrade checks during Windows servicing so installer hand-off cannot interrupt prerequisite repair. Only a confirmed native Wireless Display window plus an enabled Wi-Fi adapter yields the "ready to receive" message. If an actual Windows native receiver is found later, stale repair errors are cleared. No File Explorer fallback. A CI regression check covers these invariants.

## Build 1008 — fix File Explorer opened instead of receiver

The Windows 11 fallback previously executed `explorer.exe shell:AppsFolder\Microsoft.PPIProjection_cw5n1h2txyewy!App`. On installations where this identity is missing or renamed it can open File Explorer (e.g. Documents), leaving the X-Stage splash screen behind. Build 1008 removes that fallback. It launches Connect.exe directly only if present or invokes the Windows COM ApplicationActivationManager for the Wireless Display and legacy Connect AppUserModelIDs. It checks HRESULT, does not open any folder, does not claim a session is connected, and triggers the existing Windows prerequisite repair/error flow when the receiver is unavailable. A CI regression test prevents reintroducing Explorer.

## Build 1007 — automatic Windows prerequisites with visible stages

The receiver now starts checking the wireless adapter automatically. Missing network adapter or three failed receiver-window launches automatically starts an elevated copy of the included EXE to check/install the Microsoft Wireless Display Feature on Demand. UAC permission, Windows Update connectivity, possible reboot and Windows policies cannot be bypassed.

If Windows detects no wireless adapter, only device-applicable `Net` class drivers are searched, downloaded and installed through Microsoft Windows Update Agent, never an arbitrary web driver. Existing working adapters and display drivers are left untouched. If hardware is missing, the OEM has not published a compatible driver, wireless is disabled, or Windows policy blocks the action, the UI explains the failure instead of claiming full readiness.

The UI shows stage 1/4 through 4/4, current activity, elapsed time and either explicit error/reboot status or a real native receiver window. Readiness is not evidence of an Android stream connected. Incoming picture cleanup on sender disconnect remains owned by the native Windows receiver.

## Build 1006 — native Windows receiver hand-off

The app starts the Windows Miracast receiver automatically, waits for a verified native window, then raises that window and minimizes the X-Stage welcome so it cannot obstruct video. If Windows closes the receiver, X-Stage restores the welcome and retries a bounded number of times. The source can disconnect and the Windows-owned receiver clears its stream; this is not an X-Stage video decoder or independent session disconnect detector.

A recovery action inside X-Stage can invoke Windows DISM to add the Wireless Display optional feature with administrator approval. Windows Update or a restart can be necessary. Neither Miracast Wi-Fi Direct drivers nor Windows projection permissions are bypassed. The file build does not guarantee compatibility with all Windows/Android hardware, and physical mirroring/disconnect behavior is not yet tested.



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
