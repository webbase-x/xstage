param([string]$TargetDirectory = (Join-Path $PSScriptRoot 'native\x64'))
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'tools\Dependency-Common.ps1')
Assert-XStagePlatform
Add-Type -AssemblyName System.IO.Compression.FileSystem
$target=[IO.Path]::GetFullPath($TargetDirectory)
$probe=Join-Path $PSScriptRoot 'tools\Probe-Native.ps1'
if ((Test-Path -LiteralPath $target) -and (Test-Path -LiteralPath (Join-Path $target 'bass.dll'))) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $probe -Directory $target
    if ($LASTEXITCODE -eq 0) { Write-Host 'BASS x64 dependencies already verified.'; return }
}
$packages=@(
 @{Name='bass24.zip';Url='https://www.un4seen.com/files/bass24.zip';Dll='bass.dll'},
 @{Name='bassmidi24.zip';Url='https://www.un4seen.com/files/bassmidi24.zip';Dll='bassmidi.dll'},
 @{Name='bass_fx24.zip';Url='https://www.un4seen.com/files/z/0/bass_fx24.zip';Dll='bass_fx.dll'}
)
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('XStage-native-'+[Guid]::NewGuid().ToString('N'))
$stage=Join-Path $temporary 'stage';$backup=Join-Path $temporary 'backup'
New-Item -ItemType Directory -Path $stage,$backup -Force | Out-Null
try {
    foreach ($package in $packages) {
        $zip=Get-XStageDownload $package.Url $package.Name (Join-Path $PSScriptRoot 'offline') { param($file) Assert-XStageArchive $file $package.Dll }
        $archive=[IO.Compression.ZipFile]::OpenRead($zip)
        try {
            $entry=$archive.Entries | Where-Object { $_.FullName.Replace('\','/') -ieq ('x64/'+$package.Dll) } | Select-Object -First 1
            if (-not $entry) { throw ('Archive has no x64/'+$package.Dll+': '+$zip) }
            $destination=Join-Path $stage $package.Dll
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry,$destination,$true)
            Assert-XStagePE $destination
            foreach ($notice in $archive.Entries | Where-Object { $_.FullName -match '^[^/\\]+\.txt$' }) {
                [IO.Compression.ZipFileExtensions]::ExtractToFile($notice,(Join-Path $stage ($package.Dll+'-'+$notice.Name)),$true)
            }
        } finally { $archive.Dispose() }
    }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $probe -Directory $stage
    if ($LASTEXITCODE -ne 0) { throw 'Downloaded native libraries failed the load/API check. Existing files were not changed.' }
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    $changed=@()
    try {
        foreach ($file in Get-ChildItem -LiteralPath $stage -File) {
            $destination=Join-Path $target $file.Name
            if (Test-Path -LiteralPath $destination) { Copy-Item -LiteralPath $destination -Destination (Join-Path $backup $file.Name) -Force }
            $changed += $file.Name
            Copy-Item -LiteralPath $file.FullName -Destination $destination -Force
            if ((Get-FileHash -LiteralPath $destination).Hash -ne (Get-FileHash -LiteralPath $file.FullName).Hash) { throw ('Copy verification failed: '+$destination) }
        }
    } catch {
        foreach ($name in $changed) {
            $old=Join-Path $backup $name;$dest=Join-Path $target $name
            if (Test-Path -LiteralPath $old) { Copy-Item -LiteralPath $old -Destination $dest -Force }
            elseif (Test-Path -LiteralPath $dest) { Remove-Item -LiteralPath $dest -Force }
        }
        throw
    }
    Write-Host 'BASS / BASSMIDI / BASS FX x64 installed and verified.'
} finally { Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue }
