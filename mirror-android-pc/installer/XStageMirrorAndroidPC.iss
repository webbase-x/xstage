#define MyAppName "X-Stage Mirror Android PC"
#define MyAppVersion "1.0.4"
#define MyAppBuild "1005"

[Setup]
SourceDir=..\..
AppId={{7D92CF8B-44A9-4C23-9C14-E46D376A84D1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion} (Build {#MyAppBuild})
AppPublisher=X-Stage
AppPublisherURL=https://webbase-x.github.io/xstage/
DefaultDirName={localappdata}\Programs\X-Stage\Mirror Android PC
DefaultGroupName=X-Stage
UninstallDisplayIcon={app}\XStageMirrorAndroidPC.exe
OutputDir=mirror-android-pc\installer\output
OutputBaseFilename=X-Stage-Mirror-Android-PC-v{#MyAppVersion}-build{#MyAppBuild}-win-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=mirror-android-pc\app.ico
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
SetupLogging=yes
CloseApplications=force
RestartApplications=no
; Bundles .NET 8 self-contained runtime. No dependencies downloaded.
; Windows Wireless Display/Miracast itself remains an OS + driver capability.
; Do not request Administrator access or silently alter Windows features.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "mirror-android-pc\out\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\X-Stage Mirror Android PC"; Filename: "{app}\XStageMirrorAndroidPC.exe"
Name: "{autodesktop}\X-Stage Mirror Android PC"; Filename: "{app}\XStageMirrorAndroidPC.exe"

[Run]
Filename: "{app}\XStageMirrorAndroidPC.exe"; Description: "Launch X-Stage Mirror Android PC"; Flags: nowait postinstall
