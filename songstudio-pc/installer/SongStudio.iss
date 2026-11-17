#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef AppBuild
  #error AppBuild is required
#endif
#ifndef BundleDir
  #error BundleDir is required
#endif
#ifndef OutputPath
  #error OutputPath is required
#endif

[Setup]
AppId=XStage.SongStudio.PC
AppName=X-Stage Song Studio PC
AppVersion={#AppVersion}
AppVerName=X-Stage Song Studio PC v{#AppVersion} (Build {#AppBuild})
AppPublisher=X-Stage
DefaultDirName={localappdata}\Programs\X-Stage\Song Studio PC
DefaultGroupName=X-Stage
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
SetupIconFile={#BundleDir}\studio\app-icon.ico
UninstallDisplayIcon={app}\X-Stage Song Studio.exe
OutputDir={#OutputPath}
OutputBaseFilename=X-Stage-Song-Studio-PC-v{#AppVersion}-build{#AppBuild}-win-x64-Setup
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
SetupLogging=yes
CloseApplications=yes
RestartApplications=no

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\X-Stage Song Studio PC"; Filename: "{app}\X-Stage Song Studio.exe"; WorkingDir: "{app}"; IconFilename: "{app}\studio\app-icon.ico"; AppUserModelID: "XStage.SongStudio.PC"
Name: "{userdesktop}\X-Stage Song Studio PC"; Filename: "{app}\X-Stage Song Studio.exe"; WorkingDir: "{app}"; IconFilename: "{app}\studio\app-icon.ico"; AppUserModelID: "XStage.SongStudio.PC"

[Run]
Filename: "{app}\X-Stage Song Studio.exe"; Description: "Launch X-Stage Song Studio PC"; Flags: nowait postinstall skipifsilent
