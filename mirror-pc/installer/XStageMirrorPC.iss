#define MyAppName "X-Stage Mirror PC"
#define MyAppVersion "0.1.2"
#define MyAppBuild "103"

[Setup]
; Relative to this script in mirror-pc/installer. Resolve to repository root.
SourceDir=..\..
AppId={{D54A387F-447A-483A-946D-2BBFC4CA1F8A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion} (Build {#MyAppBuild})
AppPublisher=X-Stage
AppPublisherURL=https://webbase-x.github.io/xstage/
DefaultDirName={autopf}\X-Stage\Mirror PC
DefaultGroupName=X-Stage
UninstallDisplayIcon={app}\XStageMirrorPC.exe
OutputDir=mirror-pc\installer\output
OutputBaseFilename=X-Stage-Mirror-PC-v{#MyAppVersion}-build{#MyAppBuild}-win-x64-Setup
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
; not used to install runtimes. Miracast remains an OS/hardware requirement.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "privateairplay"; Description: "Allow X-Stage AirPlay discovery on trusted Private networks (recommended for iPhone/iPad)"; GroupDescription: "Local network permissions:"; Flags: checkedonce

[Files]
Source: "mirror-pc\out\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Ensure Bonjour Service registration uses only bundled mDNSResponder.exe.
; This action needs Windows administrator permission but NO extra download.

[Icons]
Name: "{group}\X-Stage Mirror PC"; Filename: "{app}\XStageMirrorPC.exe"
Name: "{autodesktop}\X-Stage Mirror PC"; Filename: "{app}\XStageMirrorPC.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\engine\uxplay-windows\mDNSResponder.exe"; Parameters: "-install"; WorkingDir: "{app}\engine\uxplay-windows"; Flags: runhidden waituntilterminated; Check: not BonjourServiceInstalled; StatusMsg: "Preparing bundled AirPlay discovery service..."
; App-specific Windows Defender Firewall permissions. The user explicitly opts in
; during installation. Private profiles only; never open on Public networks.
; Clear only our own rule names on upgrade; leave unrelated firewall rules intact.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""X-Stage Mirror PC AirPlay Private"""; Flags: runhidden waituntilterminated
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""X-Stage Mirror PC Bonjour Private"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""X-Stage Mirror PC mDNS Private"""; Flags: runhidden waituntilterminated
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""X-Stage Mirror PC mDNS Private"""; Flags: runhidden waituntilterminated
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""X-Stage Mirror PC AirPlay Private"" dir=in action=allow program=""{app}\engine\uxplay-windows\uxplay-windows.exe"" enable=yes profile=private"; Flags: runhidden waituntilterminated; Tasks: privateairplay
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""X-Stage Mirror PC Bonjour Private"" dir=in action=allow program=""{app}\engine\uxplay-windows\mDNSResponder.exe"" enable=yes profile=private"; Flags: runhidden waituntilterminated; Tasks: privateairplay
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""X-Stage Mirror PC mDNS Private"" dir=in action=allow protocol=UDP localport=5353 profile=private"; Flags: runhidden waituntilterminated; Tasks: privateairplay
Filename: "{app}\XStageMirrorPC.exe"; Description: "Launch X-Stage Mirror PC"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Remove only our program-specific rules; do not uninstall Bonjour because other
; AirPlay apps may rely on the same Windows-wide discovery service.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""X-Stage Mirror PC AirPlay Private"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""X-Stage Mirror PC Bonjour Private"""; Flags: runhidden

[Code]
function BonjourServiceInstalled: Boolean;
var
  Code: Integer;
begin
  Result := Exec(ExpandConstant('{sys}\sc.exe'), 'query "Bonjour Service"',
    '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
end;
