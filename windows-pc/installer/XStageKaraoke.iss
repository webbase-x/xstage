; X-Stage Karaoke PC — runtime-only Windows installer.
; Build/testing/source files stay in CI and are never distributed to end users.
#define AppVersion "1.0.79"
#define BuildNumber "1079"
#define AppExe "XStageKaraoke.exe"

[Setup]
AppId={{7E9EA7F6-09A9-47E1-A580-AFA1B260D08A}
AppName=X-Stage Karaoke PC
AppVersion={#AppVersion}
AppVerName=X-Stage Karaoke PC v{#AppVersion} (Build {#BuildNumber})
AppPublisher=X-Stage
DefaultDirName={autopf}\X-Stage\Karaoke PC
UsePreviousAppDir=no
DisableDirPage=yes
DefaultGroupName=X-Stage
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Uninstallable=yes
OutputDir=output
OutputBaseFilename=X-Stage-Karaoke-PC-Windows-v{#AppVersion}-build{#BuildNumber}
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
Name: "{localappdata}\X-Stage\Karaoke PC\Data"

[Files]
Source: "..\source\dist\XStageKaraoke\XStageKaraoke.exe"; DestDir: "{app}\App"; Flags: ignoreversion
Source: "..\source\dist\XStageKaraoke\_internal\*"; DestDir: "{app}\App\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
; Keep only the launcher icon for shortcut branding, not the source asset tree.
Source: "..\source\assets\xstage.ico"; DestDir: "{app}\App"; Flags: ignoreversion

[Icons]
Name: "{group}\X-Stage Karaoke PC"; Filename: "{app}\App\{#AppExe}"; Parameters: "--data-dir ""{localappdata}\X-Stage\Karaoke PC\Data"""; WorkingDir: "{app}\App"; IconFilename: "{app}\App\xstage.ico"
Name: "{autodesktop}\X-Stage Karaoke PC"; Filename: "{app}\App\{#AppExe}"; Parameters: "--data-dir ""{localappdata}\X-Stage\Karaoke PC\Data"""; WorkingDir: "{app}\App"; IconFilename: "{app}\App\xstage.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "สร้างทางลัดบน Desktop"; GroupDescription: "ทางลัดเพิ่มเติม:"

[Run]
Filename: "{app}\App\{#AppExe}"; Parameters: "--data-dir ""{localappdata}\X-Stage\Karaoke PC\Data"""; Description: "เปิด X-Stage Karaoke PC"; Flags: nowait postinstall skipifsilent
