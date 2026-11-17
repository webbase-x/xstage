#define MyAppName "X-Stage Mirror iOS PC"
#define MyAppVersion "1.0.1"
#define MyAppBuild "1002"

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
Name: "desktopicon"; Description: "Create desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "privateairplay"; Description: "Allow X-Stage AirPlay discovery on trusted Private networks (recommended for iPhone/iPad)"; GroupDescription: "Local network permissions:"; Flags: checkedonce

[Files]
Source: "mirror-ios-pc\out\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Ensure Bonjour Service registration uses only bundled mDNSResponder.exe.
; This action needs Windows administrator permission but NO extra download.

[Icons]
Name: "{group}\X-Stage Mirror iOS PC"; Filename: "{app}\XStageMirrorIOSPC.exe"
Name: "{autodesktop}\X-Stage Mirror iOS PC"; Filename: "{app}\XStageMirrorIOSPC.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\engine\uxplay-windows\mDNSResponder.exe"; Parameters: "-install"; WorkingDir: "{app}\engine\uxplay-windows"; Flags: runhidden waituntilterminated; Check: not BonjourServiceInstalled; StatusMsg: "Preparing bundled AirPlay discovery service..."
; App-specific Windows Defender Firewall permissions. The user explicitly opts in
; during installation. Private profiles only; never open on Public networks.
; Clear only our own rule names on upgrade; leave unrelated firewall rules intact.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""X-Stage Mirror iOS PC AirPlay Private"""; Flags: runhidden waituntilterminated
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""X-Stage Mirror iOS PC Bonjour Private"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""X-Stage Mirror iOS PC mDNS Private"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""X-Stage Mirror iOS PC mDNS Private"""; Flags: runhidden waituntilterminated
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""X-Stage Mirror iOS PC AirPlay Private"" dir=in action=allow program=""{app}\engine\uxplay-windows\uxplay-windows.exe"" enable=yes profile=private"; Flags: runhidden waituntilterminated; Tasks: privateairplay
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""X-Stage Mirror iOS PC Bonjour Private"" dir=in action=allow program=""{app}\engine\uxplay-windows\mDNSResponder.exe"" enable=yes profile=private"; Flags: runhidden waituntilterminated; Tasks: privateairplay
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""X-Stage Mirror iOS PC mDNS Private"" dir=in action=allow protocol=UDP localport=5353 profile=private"; Flags: runhidden waituntilterminated; Tasks: privateairplay
Filename: "{app}\XStageMirrorIOSPC.exe"; Description: "Launch X-Stage Mirror iOS PC"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Remove only our program-specific rules; do not uninstall Bonjour because other
; AirPlay apps may rely on the same Windows-wide discovery service.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""X-Stage Mirror iOS PC AirPlay Private"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""X-Stage Mirror iOS PC Bonjour Private"""; Flags: runhidden

[Code]
function BonjourServiceInstalled: Boolean;
var
  Code: Integer;
begin
  Result := Exec(ExpandConstant('{sys}\sc.exe'), 'query "Bonjour Service"',
    '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
end;
