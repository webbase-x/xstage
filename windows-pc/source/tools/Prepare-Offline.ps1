param(
    [Parameter(Mandatory=$true)][string]$InstallerPath,
    [Parameter(Mandatory=$true)][string]$CorrespondingSource,
    [Parameter(Mandatory=$true)][string]$LicensePath
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Installer-Safety.ps1')
$folder = Join-Path (Split-Path -Parent $PSScriptRoot) 'offline\EqualizerAPO'
if ((Split-Path -Leaf $InstallerPath) -ne 'EqualizerAPO-x64-1.4.2.exe' -or
    (Split-Path -Leaf $CorrespondingSource) -ne 'EqualizerAPO-src-1.4.2.zip') { throw 'Supply the original matching 1.4.2 x64 installer and source archive.' }
foreach ($path in @($InstallerPath,$CorrespondingSource,$LicensePath)) {
    if (!(Test-Path -LiteralPath $path -PathType Leaf)) { throw ('Missing file: '+$path) }
}
if ((Get-Content -LiteralPath $LicensePath -Raw) -notmatch 'GNU GENERAL PUBLIC LICENSE') { throw 'Supply the Equalizer APO GPL license text.' }
if (Test-Path -LiteralPath $folder) { throw 'Offline component folder already exists; preserve it and choose a clean release folder.' }
New-Item -ItemType Directory -Path $folder -Force | Out-Null
Copy-Item -LiteralPath $InstallerPath -Destination (Join-Path $folder 'EqualizerAPO-x64-1.4.2.exe')
Copy-Item -LiteralPath $CorrespondingSource -Destination (Join-Path $folder 'EqualizerAPO-src-1.4.2.zip')
Copy-Item -LiteralPath $LicensePath -Destination (Join-Path $folder 'COPYING.txt')
$hashes = @{}
Get-ChildItem -LiteralPath $folder -File | ForEach-Object { $hashes[$_.Name] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
@{name='Equalizer APO';version='1.4.2';architecture='x64';sha256=$hashes;source_url='https://sourceforge.net/projects/equalizerapo/files/1.4.2/'} |
    ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $folder 'component.json') -Encoding UTF8
Write-Host 'Offline component prepared. Include the whole offline folder in the Windows release.'
