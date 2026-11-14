# Starts the existing X-Stage Windows PC app and checks for a verified
# installer update without blocking startup. This launcher must be used as the
# desktop shortcut target to cover old EXEs that lack a built-in updater.
param(
    [string]$AppPath = '',
    [string]$CurrentVersion = '0.0.0',
    [int]$CurrentBuild = 0
)
$ErrorActionPreference = 'Stop'
$updater = Join-Path $PSScriptRoot 'Check-Update.ps1'
if (-not (Test-Path $updater -PathType Leaf)) {
    throw "Update helper missing: $updater"
}

# Resolve relative to the launcher and common install folders. Never require D: on other PCs.
# A caller-provided -AppPath always wins; no full-disk scans or changes to music folders.
if ([string]::IsNullOrWhiteSpace($AppPath)) {
    $parent = Split-Path -Parent $PSScriptRoot
    $candidates = @(
        (Join-Path $PSScriptRoot 'XStageKaraoke.exe'),
        (Join-Path $PSScriptRoot 'Karaoke\XStageKaraoke.exe'),
        (Join-Path $parent 'XStageKaraoke.exe'),
        (Join-Path $parent 'Karaoke\XStageKaraoke.exe')
    )
    if ($env:LOCALAPPDATA) {
        $candidates += Join-Path $env:LOCALAPPDATA 'Programs\X-Stage Karaoke\XStageKaraoke.exe'
    }
    if ($env:ProgramFiles) {
        $candidates += Join-Path $env:ProgramFiles 'X-Stage Karaoke\XStageKaraoke.exe'
    }
    # Legacy installations still work, but the developer's drive is not the default.
    $candidates += 'D:\newKaraoke\Karaoke\XStageKaraoke.exe'
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { $AppPath = $candidate; break }
    }
}
if ([string]::IsNullOrWhiteSpace($AppPath) -or -not (Test-Path -LiteralPath $AppPath -PathType Leaf)) {
    throw "Cannot find X-Stage executable near launcher or known install locations. Specify -AppPath."
}
$executable = (Resolve-Path -LiteralPath $AppPath).Path
if ($CurrentVersion -eq '0.0.0') {
    $versionInfo = (Get-Item $executable).VersionInfo
    $candidate = [string]$versionInfo.ProductVersion
    if ($candidate -match '^\d+\.\d+(?:\.\d+){0,2}$') {
        $CurrentVersion = $candidate
    }
}
# Read a local release manifest only when it matches the installed executable version.
# An unknown Build must never be silently treated as already up to date.
if ($CurrentBuild -le 0 -and $CurrentVersion -ne '0.0.0') {
    foreach ($manifestPath in @((Join-Path (Split-Path $executable -Parent) 'manifest.json'),
                                (Join-Path $PSScriptRoot 'manifest.json'))) {
        try {
            if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { continue }
            $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
            if ([string]$manifest.version -eq $CurrentVersion -and [int]$manifest.build -gt 0) {
                $CurrentBuild = [int]$manifest.build
                break
            }
        } catch { Write-Warning "Local build metadata unavailable: $manifestPath" }
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
