# Starts the existing X-Stage Windows PC app and checks for a verified
# installer update without blocking startup. This launcher must be used as the
# desktop shortcut target to cover old EXEs that lack a built-in updater.
param(
    [string]$AppPath = 'D:\newKaraoke\Karaoke\XStageKaraoke.exe',
    [string]$CurrentVersion = '0.0.0',
    [int]$CurrentBuild = 0
)
$ErrorActionPreference = 'Stop'
$updater = Join-Path $PSScriptRoot 'Check-Update.ps1'
if (-not (Test-Path $updater -PathType Leaf)) {
    throw "Update helper missing: $updater"
}

# Keep the already-installed karaoke program and its private music/data intact.
if (-not (Test-Path $AppPath -PathType Leaf)) {
    throw "Cannot find X-Stage executable: $AppPath. Specify -AppPath."
}
$executable = (Resolve-Path $AppPath).Path
if ($CurrentVersion -eq '0.0.0') {
    $versionInfo = (Get-Item $executable).VersionInfo
    $candidate = [string]$versionInfo.ProductVersion
    if ($candidate -match '^\d+\.\d+(?:\.\d+){0,2}$') {
        $CurrentVersion = $candidate
    }
}
Start-Process -FilePath $executable -WorkingDirectory (Split-Path $executable -Parent)

# Update validation/download happens separately and will not freeze the player.
# Actual Windows installation may require User Account Control confirmation.
$quoted = @(
    '-NoProfile'
    '-ExecutionPolicy','Bypass'
    '-File', ('"' + $updater + '"')
    '-CurrentVersion', ('"' + $CurrentVersion + '"')
    '-CurrentBuild', [string]$CurrentBuild
    '-Install'
    '-Startup'
)
Start-Process -FilePath 'powershell.exe' -ArgumentList $quoted -WindowStyle Hidden
