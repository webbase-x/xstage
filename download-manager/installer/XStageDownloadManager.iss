#define MyAppName "X-Stage Download Manager"
#define MyAppVersion "0.2.17"
#define MyAppBuild "20"

[Setup]
SourceDir=..\..
AppId={{7B45D389-0C25-46A5-9B65-14D74CE67B40}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion} (Build {#MyAppBuild})
AppPublisher=X-Stage
AppPublisherURL=https://webbase-x.github.io/xstage/
DefaultDirName={autopf}\X-Stage\Download Manager
DefaultGroupName=X-Stage
PrivilegesRequired=admin
UsePreviousAppDir=no
DisableDirPage=yes
UninstallDisplayIcon={app}\XStageDownloadManager.exe
OutputDir=download-manager\installer\output
OutputBaseFilename=X-Stage-Download-Manager-v{#MyAppVersion}-build{#MyAppBuild}-win-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=download-manager\app.ico
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
DisableProgramGroupPage=yes
CloseApplications=force

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "download-manager\out\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\X-Stage Download Manager"; Filename: "{app}\XStageDownloadManager.exe"
Name: "{autodesktop}\X-Stage Download Manager"; Filename: "{app}\XStageDownloadManager.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\XStageDownloadManager.exe"; Description: "Launch X-Stage Download Manager"; Flags: nowait postinstall skipifsilent

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
