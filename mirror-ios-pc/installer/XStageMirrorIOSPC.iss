#define MyAppName "X-Stage Mirror iOS PC"
#define MyAppVersion "1.0.12"
#define MyAppBuild "1013"

[Setup]
; Relative to this script in mirror-ios-pc/installer. Resolve to repository root.
SourceDir=..\..
AppId={{B18DE272-BA03-44D4-8B1F-381514A9CD03}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion} (Build {#MyAppBuild})
AppPublisher=X-Stage
AppPublisherURL=https://webbase-x.github.io/xstage/
DefaultDirName={autopf}\X-Stage\Mirror iOS PC
DefaultGroupName=X-Stage
UninstallDisplayIcon={app}\XStageMirrorIOSPC.exe
OutputDir=mirror-ios-pc\installer\output
OutputBaseFilename=X-Stage-Mirror-iOS-PC-v{#MyAppVersion}-build{#MyAppBuild}-win-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=mirror-ios-pc\app.ico
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
DisableProgramGroupPage=yes
SetupLogging=yes
CloseApplications=force
RestartApplications=no
; The installer contains all managed and native AirPlay DLLs. Internet is
; not used to install runtimes. This package receives AirPlay from iOS only.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "privateairplay"; Description: "Allow X-Stage AirPlay discovery on trusted Private networks (recommended for iPhone/iPad)"; GroupDescription: "Local network permissions:"; Flags: checkedonce
; Prechecked on the first install; not forcibly re-enabled when the user
; previously declined. Preserve any existing rules on upgrades if unchecked.

[Files]
Source: "mirror-ios-pc\out\*"; Excludes: "mDNSResponder.exe"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Bonjour Service runs from mDNSResponder.exe. Installing the file again during
; an upgrade causes Restart Manager to ask to close the shared Windows service.
; Keep its binary in the same location and install it ONLY when missing. A Check
; is necessary because onlyifdoesntexist alone still lets Restart Manager see
; the locked file before deciding whether to skip it.
; Do not remove this binary on uninstall: the Windows Bonjour Service may be
; shared with other AirPlay applications and its service path may point here.
Source: "mirror-ios-pc\out\engine\uxplay-windows\mDNSResponder.exe"; DestDir: "{app}\engine\uxplay-windows"; Flags: onlyifdoesntexist uninsneveruninstall; Check: not FileExists(ExpandConstant('{app}\engine\uxplay-windows\mDNSResponder.exe'))
; The app still bundles Bonjour for fresh installations and installs the
; service only if it is absent; it never forcibly stops an existing service.

[Icons]
Name: "{group}\X-Stage Mirror iOS PC"; Filename: "{app}\XStageMirrorIOSPC.exe"
Name: "{autodesktop}\X-Stage Mirror iOS PC"; Filename: "{app}\XStageMirrorIOSPC.exe"; Comment: "เปิด X-Stage Mirror iOS PC"; IconFilename: "{app}\XStageMirrorIOSPC.exe"

[Run]
Filename: "{app}\engine\uxplay-windows\mDNSResponder.exe"; Parameters: "-install"; WorkingDir: "{app}\engine\uxplay-windows"; Flags: runhidden waituntilterminated; Check: not BonjourServiceInstalled; StatusMsg: "Preparing bundled AirPlay discovery service..."
; App-specific Windows Defender Firewall permissions. The user explicitly opts in
; during installation. Private profiles only; never open on Public networks.
; IMPORTANT: Only remove/recreate existing rules when the user explicitly
; selects the privateairplay task. checkedonce leaves that task unchecked on an
; upgrade, so an unconditional delete here would silently BREAK working AirPlay.
; Never touch public profiles or third-party firewall rules.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""X-Stage Mirror iOS PC AirPlay Private"""; Flags: runhidden waituntilterminated; Tasks: privateairplay
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""X-Stage Mirror iOS PC Bonjour Private"""; Flags: runhidden; Tasks: privateairplay
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""X-Stage Mirror iOS PC mDNS Private"""; Flags: runhidden waituntilterminated; Tasks: privateairplay
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""X-Stage Mirror iOS PC AirPlay Private"" dir=in action=allow program=""{app}\engine\uxplay-windows\uxplay-windows.exe"" enable=yes profile=private"; Flags: runhidden waituntilterminated; Tasks: privateairplay
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""X-Stage Mirror iOS PC Bonjour Private"" dir=in action=allow program=""{app}\engine\uxplay-windows\mDNSResponder.exe"" enable=yes profile=private"; Flags: runhidden waituntilterminated; Tasks: privateairplay
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""X-Stage Mirror iOS PC mDNS Private"" dir=in action=allow protocol=UDP localport=5353 profile=private"; Flags: runhidden waituntilterminated; Tasks: privateairplay
Filename: "{app}\XStageMirrorIOSPC.exe"; Description: "Launch X-Stage Mirror iOS PC"; Flags: nowait postinstall skipifsilent
; Auto-update installation runs only after the client verifies the downloaded Setup EXE.
; Relaunch without requiring a click after a successful SILENT update.
Filename: "{app}\XStageMirrorIOSPC.exe"; Parameters: "/updated"; Flags: nowait skipifnotsilent

[UninstallRun]
; Remove only our program-specific rules; do not uninstall Bonjour because other
; AirPlay apps may rely on the same Windows-wide discovery service.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""X-Stage Mirror iOS PC AirPlay Private"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""X-Stage Mirror iOS PC Bonjour Private"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""X-Stage Mirror iOS PC mDNS Private"""; Flags: runhidden

[Code]
function BonjourServiceInstalled: Boolean;
var
  Code: Integer;
begin
  Result := Exec(ExpandConstant('{sys}\sc.exe'), 'query "Bonjour Service"',
    '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
end;
