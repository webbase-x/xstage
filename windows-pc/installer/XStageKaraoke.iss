; X-Stage Karaoke v1.0.76 Windows setup wrapper.
; The audited install_to_D.ps1 performs dependency checks, running-app
; shutdown and transactional copies. The Inno wrapper does not install
; directly over song libraries or application data.
#define AppVersion "1.0.76"
#define BuildNumber "1076"

[Setup]
AppId={{7E9EA7F6-09A9-47E1-A580-AFA1B260D08A}
AppName=X-Stage Karaoke
AppVersion={#AppVersion}
AppVerName=X-Stage Karaoke v{#AppVersion} (Build {#BuildNumber})
AppPublisher=X-Stage Karaoke
DefaultDirName={autopf}\X-Stage Karaoke
DisableDirPage=yes
DisableProgramGroupPage=yes
Uninstallable=no
CreateUninstallRegKey=no
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=X-Stage-Karaoke-Windows-v{#AppVersion}-build{#BuildNumber}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupLogging=yes
DisableWelcomePage=no
ShowLanguageDialog=no
; This installer stages the verified release in a temporary directory
; and invokes the existing transactional installer, which owns the
; destination and preserves Data/ user files.
AllowNoIcons=yes

[Languages]
Name: "thai"; MessagesFile: "compiler:Languages\Thai.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\source\dist\XStageKaraoke\*"; DestDir: "{tmp}\xstage-v1076"; Flags: recursesubdirs createallsubdirs ignoreversion deleteafterinstall

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ScriptPath, PowerShell, Params: string;
  ExitCode: Integer;
begin
  if CurStep <> ssPostInstall then
    Exit;
  ScriptPath := ExpandConstant('{tmp}\xstage-v1076\install_to_D.ps1');
  if not FileExists(ScriptPath) then
    RaiseException('Installer package is incomplete: install_to_D.ps1 is missing.');
  PowerShell := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ScriptPath + '" -CloseRunning -RunSetup';
  if not Exec(PowerShell, Params, '', SW_SHOW, ewWaitUntilTerminated, ExitCode) then
    RaiseException('Cannot start the X-Stage installation process.');
  if ExitCode <> 0 then
    RaiseException('X-Stage installation did not complete (exit code ' + IntToStr(ExitCode) + '). Check installation logs in LocalAppData.');
end;
