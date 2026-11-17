#define MyAppName "X-Stage Mirror PC"
#define MyAppVersion "0.1.1"
#define MyAppBuild "102"

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

[Files]
Source: "mirror-pc\out\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Ensure Bonjour Service registration uses only bundled mDNSResponder.exe.
; This action needs Windows administrator permission but NO extra download.

[Icons]
Name: "{group}\X-Stage Mirror PC"; Filename: "{app}\XStageMirrorPC.exe"
Name: "{autodesktop}\X-Stage Mirror PC"; Filename: "{app}\XStageMirrorPC.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\engine\uxplay-windows\mDNSResponder.exe"; Parameters: "-install"; WorkingDir: "{app}\engine\uxplay-windows"; Flags: runhidden waituntilterminated; Check: not BonjourServiceInstalled; StatusMsg: "Preparing bundled AirPlay discovery service..."
Filename: "{app}\XStageMirrorPC.exe"; Description: "Launch X-Stage Mirror PC"; Flags: nowait postinstall skipifsilent

[Code]
function BonjourServiceInstalled: Boolean;
var
  Code: Integer;
begin
  Result := Exec(ExpandConstant('{sys}\sc.exe'), 'query "Bonjour Service"',
    '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
end;
