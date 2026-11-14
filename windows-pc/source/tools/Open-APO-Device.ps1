param([Parameter(Mandatory=$true)][string]$Program)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Get-ItemProperty 'HKLM:\SOFTWARE\EqualizerAPO').ConfigPath
$root = [IO.Path]::GetFullPath($root)
$programPath = [IO.Path]::GetFullPath($Program)
if ((Split-Path -Parent $programPath) -ine $root -or
    (Split-Path -Leaf $programPath) -notin @('DeviceSelector.exe','Configurator.exe')) {
    throw 'Unexpected Equalizer APO program path.'
}
if (!(Test-Path -LiteralPath $programPath -PathType Leaf)) { throw 'Device Selector is missing.' }
$env:QT_PLUGIN_PATH = Join-Path $root 'qt'
$env:QT_QPA_PLATFORM_PLUGIN_PATH = Join-Path $root 'qt\platforms'
try {
    # The user confirms Windows elevation; no device or APO setting is changed here.
    $process = Start-Process -FilePath $programPath -WorkingDirectory $root -Verb RunAs -PassThru -Wait
    exit $process.ExitCode
} catch { Write-Error $_; exit 1 }
