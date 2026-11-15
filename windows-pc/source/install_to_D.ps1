param(
    [string]$Destination = $(if (Test-Path -LiteralPath 'D:\') { 'D:\newKaraoke\Karaoke' } else { Join-Path $env:LOCALAPPDATA 'XStageKaraoke' }),
    [switch]$RunSetup,
    [switch]$CloseRunning,
    [ValidateRange(1,120)][int]$CloseTimeoutSeconds = 20
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'tools\Dependency-Common.ps1')
Assert-XStagePlatform
# Source previews contain no Windows executable. Build before touching the target.
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'XStageKaraoke.exe') -PathType Leaf) -and
    (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'main.py') -PathType Leaf)) {
    Write-Host 'Source preview detected. Building the Windows player first...'
    & (Join-Path $PSScriptRoot 'Build-Source.ps1')
    $builtInstaller = Join-Path $PSScriptRoot 'dist\XStageKaraoke\install_to_D.ps1'
    if (-not (Test-Path -LiteralPath $builtInstaller -PathType Leaf)) {
        throw 'Build did not produce a complete release. Installation has not started.'
    }
    $installArgs = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$builtInstaller,'-Destination',$Destination,'-CloseTimeoutSeconds',"$CloseTimeoutSeconds")
    if ($CloseRunning) { $installArgs += '-CloseRunning' }
    if ($RunSetup) { $installArgs += '-RunSetup' }
    & powershell.exe @installArgs
    exit $LASTEXITCODE
}
$source = [IO.Path]::GetFullPath($PSScriptRoot)
$target = [IO.Path]::GetFullPath($Destination)
if ($target.TrimEnd('\') -ieq [IO.Path]::GetPathRoot($target).TrimEnd('\')) { throw 'Choose a dedicated application folder.' }
if ($source.TrimEnd('\') -ieq $target.TrimEnd('\') -or
    $source.StartsWith($target.TrimEnd('\')+'\', [StringComparison]::OrdinalIgnoreCase) -or
    $target.StartsWith($source.TrimEnd('\')+'\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Extract this package into a separate folder, then install.'
}
$app = Join-Path $target 'App'
$code = Join-Path $target 'Source'
$program = Join-Path $app 'XStageKaraoke.exe'

function Get-InstalledPlayerProcesses {
    foreach ($candidate in @(Get-Process -Name 'XStageKaraoke' -ErrorAction SilentlyContinue)) {
        try {
            if ($candidate.Path -and [IO.Path]::GetFullPath($candidate.Path) -ieq $program) { $candidate }
        } catch {
            # Do not close a process unless its executable path is verified.
            # The file preflight below still detects inaccessible file locks.
        }
    }
}

function Show-BusyInstructions([string]$FilePath) {
    Write-Host ''
    Write-Host ('File is in use: ' + $FilePath) -ForegroundColor Yellow
    Write-Host 'Close all X-Stage Karaoke windows, including the singer display.'
    Write-Host 'If it cannot close, press Ctrl+Shift+Esc, find XStageKaraoke.exe, and end that task.'
    Write-Host 'Then run Install-to-D.cmd again. Existing Data and song files are preserved.'
}

$sourceNames = @('RELEASE_0937_TH.md','QA_RESULTS_0937_TH.md','AUDIT_ALL_FUNCTIONS_0937_TH.md','WINDOWS_BUILD_0937_TH.md','RELEASE_090_TH.md','QUALITY_AND_CLEANUP_TH.md','requirements-build.lock.txt','release-environment.json','Install-to-D.cmd','install_to_D.ps1','start.bat','SYSTEM_EQ_TH.md','native','Setup-Dependencies.ps1','DEPENDENCIES_TH.md','offline','SETUP_0570_TH.md','EQ_0570_TH.md','EQ_0571_TH.md','EQ_0572_TH.md','EQ_0573_TH.md','EQ_0574_TH.md','EQ_0575_TH.md','VERIFY_0576_TH.md','EQ_0578_TH.md','SONG_WORKSPACE_0579_TH.md','SOUNDFONT_0580_TH.md','SOUNDFONT_0581_TH.md','RUNTIME_LOGS_0583_TH.md','karaoke','tools','tests','samples','assets','third_party_licenses','main.py','build.ps1','version_info.txt','README_TH.md','CHANGELOG.md','requirements.txt','THIRD_PARTY.md','LICENSE.txt','FEATURE_STATUS.md','SOUNDFONT_GUIDE_TH.md','UI_GUIDE_TH.md','IMPORT_GUIDE_TH.md','DUPLICATE_GUIDE_TH.md','PROGRESS_GUIDE_TH.md','INDEXER_GUIDE_TH.md','AUDIO_FIX_TH.md','AUTO_AUDIO_TH.md','AUDIO_BENCHMARK_TH.md','AUDIO_TOOLS_TH.md','PERFORMANCE_GUIDE_TH.md','WINDOWS_CHECK_TH.md','BUILD_FIX_TH.md','Build-Windows.cmd','Build-Source.ps1','TEST_RESULTS.md','SEARCH_BENCHMARK.json','Setup-Audio.ps1')
$sourceNames = @('Convert-Web-Assets.cmd','Verify-Windows-0945.cmd') + $sourceNames
$appNames = @('RELEASE_090_TH.md','QUALITY_AND_CLEANUP_TH.md','Setup-Dependencies.ps1','DEPENDENCIES_TH.md','offline','SETUP_0570_TH.md','EQ_0570_TH.md','EQ_0571_TH.md','EQ_0572_TH.md','EQ_0573_TH.md','EQ_0574_TH.md','EQ_0575_TH.md','VERIFY_0576_TH.md','EQ_0578_TH.md','SONG_WORKSPACE_0579_TH.md','SOUNDFONT_0580_TH.md','SOUNDFONT_0581_TH.md','RUNTIME_LOGS_0583_TH.md','XStageKaraoke.exe','_internal','tools','samples','assets','native','Setup-Audio.ps1','README_TH.md','FEATURE_STATUS.md','SOUNDFONT_GUIDE_TH.md','UI_GUIDE_TH.md','IMPORT_GUIDE_TH.md','DUPLICATE_GUIDE_TH.md','PROGRESS_GUIDE_TH.md','INDEXER_GUIDE_TH.md','AUDIO_FIX_TH.md','AUTO_AUDIO_TH.md','AUDIO_BENCHMARK_TH.md','AUDIO_TOOLS_TH.md','PERFORMANCE_GUIDE_TH.md','WINDOWS_CHECK_TH.md','BUILD_FIX_TH.md')
foreach ($required in @('XStageKaraoke.exe','_internal','tools\Repair-XStage-WiFi.ps1','tools\Installer-Safety.ps1','tools\Open-APO-Device.ps1')) {
    if (-not (Test-Path -LiteralPath (Join-Path $source $required))) {
        throw ('Incomplete package: missing ' + $required + '. This release is incomplete; use the full Windows release or the source package with Build-Source.ps1.')
    }
}

$running = @(Get-InstalledPlayerProcesses)
if ($running.Count -gt 0 -and -not $CloseRunning) {
    Show-BusyInstructions $program
    exit 20
}
if ($running.Count -gt 0) {
    Write-Host 'Closing the installed X-Stage Karaoke normally so it can save settings and queue...'
    $deadline = [DateTime]::UtcNow.AddSeconds($CloseTimeoutSeconds)
    while ($running.Count -gt 0 -and [DateTime]::UtcNow -lt $deadline) {
        foreach ($player in $running) {
            try { $null = $player.CloseMainWindow() } catch { }
        }
        Start-Sleep -Milliseconds 250
        $running = @(Get-InstalledPlayerProcesses)
    }
    if ($running.Count -gt 0) {
        Show-BusyInstructions $program
        exit 20
    }
}

# Prepare and verify all native/runtime dependencies BEFORE backing up or changing installed files.
& (Join-Path $source 'Setup-Dependencies.ps1') -TargetDirectory $source

# Probe all existing destination files before changing any program file. A
# running EXE or loaded DLL must be reported before Source and App can diverge.
$copies = @()
foreach ($group in @(@{Names=$sourceNames; Folder=$code}, @{Names=$appNames; Folder=$app})) {
    foreach ($name in $group.Names) {
        $item = Join-Path $source $name
        if (-not (Test-Path -LiteralPath $item)) { continue }
        $destination = Join-Path $group.Folder $name
        $copies += @{Item=$item; Folder=$group.Folder}
        $files = if (Test-Path -LiteralPath $item -PathType Container) {
            @(Get-ChildItem -LiteralPath $item -File -Recurse | ForEach-Object {
                Join-Path $destination $_.FullName.Substring($item.TrimEnd('\').Length+1)
            })
        } else { @($destination) }
        foreach ($file in $files) {
            if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { continue }
            $stream = $null
            try {
                $stream = [IO.File]::Open($file, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
            } catch [IO.IOException] {
                Show-BusyInstructions $file
                exit 20
            } catch [UnauthorizedAccessException] {
                Write-Host ('No write access: ' + $file) -ForegroundColor Red
                Write-Host 'Use a Windows account that can update this application folder.'
                exit 21
            } finally {
                if ($stream) { $stream.Dispose() }
            }
        }
    }
}

. (Join-Path $source 'tools\Installer-Safety.ps1')
$updatePlan = @(Get-XStageUpdatePlan -Target $target -Copies $copies)
$programBackup = Backup-XStageUpdate -Target $target -Plan $updatePlan
Write-Host ('Program backup verified: ' + $programBackup)
try {
foreach ($directory in @($target,$app,$code,(Join-Path $target 'Data'),(Join-Path $target 'Records'),(Join-Path $target 'SoundFx'))) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}
# Merge application files only. Never delete or replace Data or source songs.
foreach ($entry in $updatePlan) {
    if (!$entry.Source) { continue }
    $null = Assert-XStageTarget $target $entry.Destination
    New-Item -ItemType Directory -Path (Split-Path -Parent $entry.Destination) -Force | Out-Null
    Copy-Item -LiteralPath $entry.Source -Destination $entry.Destination -Force -ErrorAction Stop
    if ((Get-FileHash -LiteralPath $entry.Source -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $entry.Destination -Algorithm SHA256).Hash) { throw 'Program copy verification failed.' }
}
if (-not (Test-Path -LiteralPath (Join-Path $app 'tools\Repair-XStage-WiFi.ps1') -PathType Leaf)) {
    throw 'Installation incomplete: Wi-Fi permission helper was not copied to App\tools. Run the full installer again.'
}
& (Join-Path $app 'Setup-Dependencies.ps1') -TargetDirectory $app
$launcher = @'
@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0App\XStageKaraoke.exe" (
  start "" "%~dp0App\XStageKaraoke.exe" --data-dir "%~dp0Data"
  exit /b
)
python "%~dp0Source\main.py" --data-dir "%~dp0Data"
if errorlevel 1 pause
'@
[IO.File]::WriteAllText((Join-Path $target 'Start-Karaoke.cmd'), $launcher, [Text.Encoding]::ASCII)
[IO.File]::WriteAllText((Join-Path $target 'X-Stage Karaoke.cmd'), $launcher, [Text.Encoding]::ASCII)
# Also provide a console-free launcher for Windows users; the legacy CMD
# scripts remain available only for installation and troubleshooting.
$quietLauncher = Join-Path $source 'Start-XStage-Silent.vbs'
if (Test-Path -LiteralPath $quietLauncher -PathType Leaf) {
    Copy-Item -LiteralPath $quietLauncher -Destination (Join-Path $target 'Start-XStage-Silent.vbs') -Force
}

$audioLauncher = @'
@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0App\Setup-Dependencies.ps1"
pause
'@
[IO.File]::WriteAllText((Join-Path $target 'Setup-Audio.cmd'), $audioLauncher, [Text.Encoding]::ASCII)
# A .cmd file cannot carry a custom Explorer icon; provide a real shortcut.
try {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut((Join-Path $target 'X-Stage Karaoke.lnk'))
    $shortcut.TargetPath = Join-Path $app 'XStageKaraoke.exe'
    $shortcut.Arguments = '--data-dir "' + (Join-Path $target 'Data') + '"'
    $shortcut.WorkingDirectory = $target
    $shortcut.IconLocation = (Join-Path $app 'assets\xstage.ico') + ',0'
    $shortcut.Description = 'X-Stage Karaoke'
    $shortcut.Save()
} catch {
    Write-Warning ('Cannot create logo shortcut. Use Start-Karaoke.cmd: ' + $_.Exception.Message)
}
} catch {
    $failure = $_
    try { Restore-XStageUpdate -Target $target -Backup $programBackup }
    catch { throw ('Update failed and automatic restore is incomplete. Backup: '+$programBackup+'; restore error: '+$_) }
    throw $failure
}
Write-Host ('Installed: ' + $target)
if ($RunSetup) { Start-Process -FilePath $program -WorkingDirectory $target -ArgumentList @('--setup','--data-dir',('"'+(Join-Path $target 'Data')+'"')) }
Write-Host 'Open X-Stage Karaoke.lnk. First run imports the existing catalog in the background.'
