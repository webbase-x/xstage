; X-Stage Karaoke PC — runtime-only Windows installer.
; Build/testing/source files stay in CI and are never distributed to end users.
#define AppVersion "1.0.82"
#define BuildNumber "1082"
#define AppExe "X-StageKaraoke.exe"

[Setup]
AppId={{7E9EA7F6-09A9-47E1-A580-AFA1B260D08A}
AppName=X-Stage Karaoke PC
AppVersion={#AppVersion}
AppVerName=X-Stage Karaoke PC v{#AppVersion} (Build {#BuildNumber})
AppPublisher=X-Stage
DefaultDirName={autopf}\X-Stage\Karaoke
UsePreviousAppDir=no
DisableDirPage=yes
DefaultGroupName=X-Stage
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Uninstallable=yes
OutputDir=output
OutputBaseFilename=X-StageKaraoke
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\source\assets\xstage.ico
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
; Only files listed below are shipped. The PyInstaller one-dir runtime
; contains its dependencies in _internal. No developer source or build tools.

[Languages]
Name: "thai"; MessagesFile: "compiler:Languages\Thai.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Dirs]
; User data is not an installer payload and must survive upgrades/uninstalls.
Name: "{app}\data"; Permissions: users-modify; Flags: uninsneveruninstall
Name: "{app}\Songs"; Permissions: users-modify; Flags: uninsneveruninstall
Name: "{app}\Songs\MIDI"; Flags: uninsneveruninstall
Name: "{app}\Songs\MIDI\NCN"; Flags: uninsneveruninstall
Name: "{app}\Songs\MIDI\XMID"; Flags: uninsneveruninstall
Name: "{app}\Songs\MP3"; Flags: uninsneveruninstall
Name: "{app}\Songs\M4A"; Flags: uninsneveruninstall
Name: "{app}\Songs\VIDEO"; Flags: uninsneveruninstall

[Files]
Source: "..\source\dist\XStageKaraoke\XStageKaraoke.exe"; DestDir: "{app}"; DestName: "{#AppExe}"; Flags: ignoreversion
Source: "..\source\dist\XStageKaraoke\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

; The BASS runtime lives beside the app, not inside PyInstaller _internal.
; Ship the verified x64 libraries produced by Setup-Audio.ps1 with the installer.
Source: "..\source\dist\XStageKaraoke\native\x64\*"; DestDir: "{app}\native\x64"; Flags: ignoreversion recursesubdirs createallsubdirs

; Runtime support scripts invoked by existing application menus (not development tools).
Source: "..\source\dist\XStageKaraoke\Setup-Dependencies.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\source\dist\XStageKaraoke\Setup-Audio.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\source\dist\XStageKaraoke\tools\Dependency-Common.ps1"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "..\source\dist\XStageKaraoke\tools\Probe-Native.ps1"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "..\source\dist\XStageKaraoke\tools\Repair-Dependencies.ps1"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "..\source\dist\XStageKaraoke\tools\Repair-XStage-WiFi.ps1"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "..\source\dist\XStageKaraoke\tools\Setup-System-EQ.ps1"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "..\source\dist\XStageKaraoke\tools\Open-APO-Device.ps1"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "..\source\dist\XStageKaraoke\tools\Install-EqualizerAPO.ps1"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "..\source\dist\XStageKaraoke\tools\Installer-Safety.ps1"; DestDir: "{app}\tools"; Flags: ignoreversion

[Icons]
Name: "{group}\X-Stage Karaoke PC"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{autodesktop}\X-Stage Karaoke PC"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "สร้างทางลัดบน Desktop"; GroupDescription: "ทางลัดเพิ่มเติม:"

[Run]
Filename: "{app}\{#AppExe}"; Description: "เปิด X-Stage Karaoke PC"; Flags: nowait postinstall skipifsilent
