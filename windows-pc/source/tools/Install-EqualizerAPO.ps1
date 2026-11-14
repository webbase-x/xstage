param([Parameter(Mandatory=$true)][string]$OfflineRoot)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Installer-Safety.ps1')
try {
    if (![Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64' -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { throw 'This offline component requires Windows x64.' }
    $folder = [IO.Path]::GetFullPath($OfflineRoot)
    $manifest = Get-Content -LiteralPath (Join-Path $folder 'component.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.name -ne 'Equalizer APO' -or $manifest.version -ne '1.4.2' -or $manifest.architecture -ne 'x64') { throw 'Unexpected component package.' }
    foreach ($name in @('EqualizerAPO-x64-1.4.2.exe','EqualizerAPO-src-1.4.2.zip','COPYING.txt')) {
        $path = Join-Path $folder $name
        if (!(Test-Path -LiteralPath $path -PathType Leaf)) { throw ('Incomplete offline package: '+$name) }
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ine $manifest.sha256.$name) { throw ('Component file changed: '+$name) }
    }
    # Run the original vendor installer interactively: the user accepts its license
    # and UAC request. Never reboot or alter device registration silently.
    $process = Start-Process -FilePath (Join-Path $folder 'EqualizerAPO-x64-1.4.2.exe') -WorkingDirectory $folder -Verb RunAs -Wait -PassThru
    exit $process.ExitCode
} catch { Write-Error $_; exit 1 }
