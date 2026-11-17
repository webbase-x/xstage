# X-Stage Mirror Android PC

**Version 1.0.0 · Build 1001 · Windows 10/11 x64 · Preview**

Dedicated launcher and diagnostic tool for Windows **Wireless Display / Miracast** receiver sessions from compatible Android devices. Independent from AirPlay receiver.

## Identity and actual cast destination

Shows **X-Stage Mirror PC No.XXXX**, a random four-digit number created once under `%LOCALAPPDATA%\X-Stage\Mirror\receiver-number.txt`. The number is shared with X-Stage Mirror iOS PC on the same Windows user account. This is a convenient local identification label only.

**Important:** Miracast is advertised by the Windows Wireless Display receiver, which generally uses the Windows **computer/device name**, not this X-Stage application label. The app prominently displays the actual `Environment.MachineName` for the Android sender to select. It cannot safely rename a Windows host or make it appear as an arbitrary advertised Miracast name without OS changes.

## Connected devices

Windows native Wireless Display manages session approvals and sender identity. This app detects the Windows Connect process and, if available, displays the actual Windows receiver window title; the sender/device list is still shown **in the Windows receiver window**, not fabricated in X-Stage. Seeing a Connect process is not proof that a sender connected.

## Ready-to-use scope and limitations

The one-file Windows Setup EXE embeds the desktop .NET runtime. No extra **application** downloads are required. Miracast still requires compatible Windows Wi-Fi/Wi-Fi Direct driver and the native Wireless Display optional feature installed by Windows. Some Android devices implement Google Cast but not Miracast; the protocols are not interchangeable. Where the Windows optional feature is missing, it may require Windows Update. No installer can bundle arbitrary hardware drivers or bypass receiver feature support.

## Build

`dotnet publish mirror-android-pc/XStageMirrorAndroidPC.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -o mirror-android-pc/out`

CI: `.github/workflows/build-xstage-mirror-android-pc.yml` → `.github/workflows/publish-xstage-mirror-android-pc-preview.yml` with independent ZIP/Setup SHA-256 verification. Physical Windows/Android casting has not been certified.
