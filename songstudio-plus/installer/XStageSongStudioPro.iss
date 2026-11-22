; X-Stage Song Studio Pro Windows x64 Setup.
; No writable SQLite, logs or song workspaces are installed to Program Files.
#define MyAppName "X-Stage Song Studio Pro"
#define MyAppVersion "0.1.41"
#define MyAppExe "XStageSongStudioPro.exe"

[Setup]
SourceDir=..\..
AppId={{B741E21A-93B6-421D-BB7B-2A53C5E03491}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion} (Preview)
AppPublisher=X-Stage
AppPublisherURL=https://webbase-x.github.io/xstage/
AppSupportURL=https://github.com/webbase-x/xstage/issues
DefaultDirName={autopf}\X-Stage\Song Studio Pro
DefaultGroupName=X-Stage
PrivilegesRequired=admin
UsePreviousAppDir=no
DisableDirPage=yes
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExe}
OutputDir=songstudio-plus\installer\output
OutputBaseFilename=X-Stage-Song-Studio-Pro-v{#MyAppVersion}-win-x64-Setup
SetupIconFile=songstudio-plus\app-plus.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create desktop shortcut"; Flags: unchecked

[Files]
Source: "dist\XStageSongStudioPro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\X-Stage Song Studio Pro"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\X-Stage Song Studio Pro"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Launch X-Stage Song Studio Pro"; Flags: nowait postinstall skipifsilent

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
