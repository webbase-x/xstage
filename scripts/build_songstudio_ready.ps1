#requires -Version 5.1
<#
Build X-Stage Song Studio PC Ready portable ZIP on Windows GitHub Actions.
Downloads happen ON THE BUILD RUNNER ONLY. Users receive all runtimes prebundled.
No AI model or Google Drive implementation is claimed by this packaging script.
#>
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Repo = Split-Path -Parent $PSScriptRoot
$Version = 'v0.3.0-build300'
$DirName = 'X-Stage-Song-Studio-PC-Ready-' + $Version
$OutputRoot = Join-Path $Repo 'dist'
$Stage = Join-Path $OutputRoot $DirName
$Downloads = Join-Path $OutputRoot 'dependency-cache'
$Runtime = Join-Path $Stage '.runtime'
$PythonURL = 'https://www.python.org/ftp/python/3.13.10/python-3.13.10-embeddable-amd64.zip'
$FfmpegURL = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
$FfmpegShaURL = $FfmpegURL + '.sha256'
$FluidURL = 'https://github.com/FluidSynth/fluidsynth/releases/download/v2.6.2/fluidsynth-v2.6.2-win10-x64-cpp11.zip'
$FluidSha256 = '808295345D43C9C428F3FA87D29FBF97A9926F356DF95559FF2689F3BD4072D7'
$SoundFontRef = '684543d5e5efaef08d02be50dcda8d552478fa60'
$SoundFontURL = "https://raw.githubusercontent.com/mrbumpy409/GeneralUser-GS/$SoundFontRef/GeneralUser-GS.sf2"
$SoundFontLicenseURL = "https://raw.githubusercontent.com/mrbumpy409/GeneralUser-GS/$SoundFontRef/documentation/LICENSE.txt"

function Step([string]$Text) {
    Write-Host ('[' + (Get-Date -Format 'HH:mm:ss') + '] ' + $Text) -ForegroundColor Cyan
}
function Download([string]$Url, [string]$Target) {
    if (!$Url.StartsWith('https://')) { throw "Refusing insecure dependency URL: $Url" }
    Step "Downloading $Url"
    Invoke-WebRequest -Uri $Url -OutFile $Target -UseBasicParsing -MaximumRedirection 8 -TimeoutSec 240
    if (!(Test-Path $Target) -or (Get-Item $Target).Length -lt 64) { throw "Empty dependency: $Url" }
}
function CheckSHA([string]$File, [string]$Expected) {
    if ($Expected -notmatch '^[a-fA-F0-9]{64}$') { throw "Invalid pinned SHA for $File" }
    $Actual = (Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($Actual -ne $Expected.ToUpperInvariant()) { throw "Checksum mismatch for $File" }
    Step "SHA256 matched: $File"
}
function CopyFromRepo([string]$SourceRel, [string]$DestRel) {
    $From = Join-Path $Repo $SourceRel
    $To = Join-Path $Stage $DestRel
    if (!(Test-Path -LiteralPath $From -PathType Leaf)) { throw "Source file missing: $SourceRel" }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $To) | Out-Null
    Copy-Item -LiteralPath $From -Destination $To -Force
}
Step "Building offline Ready package: $Version"
if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force -Path $Downloads, $Stage, $Runtime | Out-Null
$map = @{
 'songstudio-pc/Start-Song-Studio-Ready.cmd' = 'Start-Song-Studio.cmd'
 'songstudio-pc/Start-Song-Studio-Ready.ps1' = 'Start-Song-Studio-Ready.ps1'
 'songstudio-pc/engine.py' = 'engine.py'
 'songstudio-pc/README-READY.md' = 'README.md'
 'studio/index.html' = 'studio/index.html'
 'studio/app.js' = 'studio/app.js'
 'studio/style.css' = 'studio/style.css'
 'studio/entry.js' = 'studio/entry.js'
}
foreach ($item in $map.GetEnumerator()) { CopyFromRepo $item.Key $item.Value }

# 1. Python embeddable runtime: no Python installation or pip necessary
$PyZip = Join-Path $Downloads 'python-embedded.zip'
Download $PythonURL $PyZip
$PyDir = Join-Path $Runtime 'python'
New-Item -ItemType Directory -Force -Path $PyDir | Out-Null
Expand-Archive -LiteralPath $PyZip -DestinationPath $PyDir -Force
if (!(Test-Path (Join-Path $PyDir 'pythonw.exe'))) { throw 'Bundled Python lacks pythonw.exe' }
$py = Join-Path $PyDir 'python.exe'
& $py -c "import http.server,json,pathlib,subprocess,threading; print('PYTHON_EMBED_OK')"
if ($LASTEXITCODE -ne 0) { throw 'Bundled Python failed self-test' }
Step 'Bundled Python embedded runtime ready'

# 2. Trusted Gyan Windows FFmpeg; check vendor-provided archive digest
$FfmpegZip = Join-Path $Downloads 'ffmpeg-essentials.zip'
$FFSHA = Join-Path $Downloads 'ffmpeg-essentials.sha256'
Download $FfmpegURL $FfmpegZip
Download $FfmpegShaURL $FFSHA
$hashFile = Get-Content -LiteralPath $FFSHA -Raw
if ($hashFile -notmatch '(?i)\b[a-f0-9]{64}\b') { throw 'FFmpeg vendor checksum file invalid' }
CheckSHA $FfmpegZip $Matches[0]
$FFTemp = Join-Path $Downloads 'ffmpeg-unpacked'
Expand-Archive -LiteralPath $FfmpegZip -DestinationPath $FFTemp -Force
$Tools = Join-Path $Runtime 'tools'
New-Item -ItemType Directory -Force -Path $Tools | Out-Null
foreach ($file in @('ffmpeg.exe', 'ffprobe.exe')) {
    $found = Get-ChildItem -LiteralPath $FFTemp -Recurse -Filter $file -File | Select-Object -First 1
    if (!$found) { throw "FFmpeg archive missing $file" }
    Copy-Item -LiteralPath $found.FullName -Destination (Join-Path $Tools $file)
}
& (Join-Path $Tools 'ffmpeg.exe') -hide_banner -version | Select-Object -First 1
if ($LASTEXITCODE -ne 0) { throw 'Bundled FFmpeg failed self-test' }
Step 'Bundled FFmpeg and ffprobe ready'

# 3. Official Windows FluidSynth binary (pinned upstream GitHub checksum)
$FluidZip = Join-Path $Downloads 'fluidsynth-win64.zip'
Download $FluidURL $FluidZip
CheckSHA $FluidZip $FluidSha256
$FluidTemp = Join-Path $Downloads 'fluidsynth-unpacked'
Expand-Archive -LiteralPath $FluidZip -DestinationPath $FluidTemp -Force
$FluidExe = Get-ChildItem -LiteralPath $FluidTemp -Recurse -File -Filter 'fluidsynth.exe' | Select-Object -First 1
if (!$FluidExe) { throw 'Official FluidSynth Windows archive does not contain fluidsynth.exe' }
$FluidBin = Join-Path $Runtime 'fluidsynth/bin'
New-Item -ItemType Directory -Force -Path $FluidBin | Out-Null
# Include all native DLLs beside the executable so no machine-level installation is needed.
Copy-Item -Path (Join-Path $FluidExe.Directory.FullName '*') -Destination $FluidBin -Recurse -Force
$FluidPath = Join-Path $FluidBin 'fluidsynth.exe'
if (!(Test-Path $FluidPath)) { throw 'Bundled FluidSynth executable missing' }
$env:PATH = "$FluidBin;$env:PATH"
& $FluidPath --version
if ($LASTEXITCODE -ne 0) { throw 'Bundled FluidSynth failed self-test' }
Step 'Bundled FluidSynth and its native libraries ready'

# 4. GM SoundFont, pinned to a specific upstream commit, with publisher license
$SFDir = Join-Path $Runtime 'soundfonts'
$Licenses = Join-Path $Runtime 'licenses'
New-Item -ItemType Directory -Force -Path $SFDir, $Licenses | Out-Null
$SFPath = Join-Path $SFDir 'GeneralUser-GS.sf2'
Download $SoundFontURL $SFPath
Download $SoundFontLicenseURL (Join-Path $Licenses 'GeneralUser-GS-LICENSE.txt')
if ((Get-Item $SFPath).Length -lt 1000000) { throw 'Bundled SoundFont is suspiciously small' }
$SF = [IO.File]::OpenRead($SFPath)
try {
    $header = New-Object byte[] 12
    if ($SF.Read($header, 0, 12) -ne 12 -or
        [Text.Encoding]::ASCII.GetString($header,0,4) -ne 'RIFF' -or
        [Text.Encoding]::ASCII.GetString($header,8,4) -ne 'sfbk') {
        throw 'Invalid SoundFont header'
    }
} finally { $SF.Dispose() }
Step 'Bundled GeneralUser-GS SoundFont and license ready'

# 5. Preserve bundled runtime license files and source links in the ZIP
$PythonLicense = Join-Path $PyDir 'LICENSE.txt'
if (Test-Path $PythonLicense) {
    Copy-Item $PythonLicense (Join-Path $Licenses 'Python-LICENSE.txt') -Force
}
$FFLicense = Get-ChildItem -LiteralPath $FFTemp -Filter 'LICENSE*' -File -Recurse | Select-Object -First 1
if ($FFLicense) { Copy-Item $FFLicense.FullName (Join-Path $Licenses 'FFmpeg-LICENSE.txt') -Force }
$FluidLicense = Get-ChildItem -LiteralPath $FluidTemp -Filter 'LICENSE*' -File -Recurse | Select-Object -First 1
if ($FluidLicense) { Copy-Item $FluidLicense.FullName (Join-Path $Licenses 'FluidSynth-LICENSE.txt') -Force }
CopyFromRepo 'songstudio-pc/THIRD_PARTY_NOTICES.md' '.runtime/licenses/THIRD_PARTY_NOTICES.md'

# 6. Runtime integrity manifest, packaged with the app
$paths = @(
 'engine.py',
 'studio/index.html',
 'studio/app.js',
 'studio/style.css',
 'studio/entry.js',
 '.runtime/python/python.exe',
 '.runtime/python/pythonw.exe',
 '.runtime/tools/ffmpeg.exe',
 '.runtime/tools/ffprobe.exe',
 '.runtime/fluidsynth/bin/fluidsynth.exe',
 '.runtime/soundfonts/GeneralUser-GS.sf2'
)
$files = foreach ($relative in $paths) {
    $p = Join-Path $Stage ($relative.Replace('/', '\'))
    if (!(Test-Path -LiteralPath $p -PathType Leaf)) { throw "Manifest file missing: $relative" }
    [ordered]@{
        path = $relative
        sha256 = (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant()
        bytes = (Get-Item $p).Length
    }
}
$manifest = [ordered]@{
    product = 'X-Stage Song Studio PC'
    bundle_type = 'ready-offline'
    platform = 'windows-x64'
    version = '0.3.0'
    build = 300
    created_utc = [DateTime]::UtcNow.ToString('o')
    contents = @('Python 3.13.10 embeddable', 'FFmpeg 9.x essentials', 'FluidSynth 2.6.2 win64', 'GeneralUser GS 2.0.3 SoundFont')
    files = @($files)
}
$ManifestFile = Join-Path $Stage '.engine-ready-manifest.json'
ConvertTo-Json -InputObject $manifest -Depth 8 | Set-Content -LiteralPath $ManifestFile -Encoding UTF8

# Offline check, no network calls, run the exact release launcher in CI
$Check = Join-Path $Stage 'Start-Song-Studio-Ready.ps1'
& $Check -NoLaunch
if ($LASTEXITCODE -ne 0) { throw 'Offline Readiness check FAILED' }
Step 'Offline readiness verified successfully'

# 7. Package a complete ZIP, include checksum alongside it
$Zip = Join-Path $OutputRoot ($DirName + '.zip')
if (Test-Path $Zip) { Remove-Item $Zip -Force }
# Python zipfile creates portable POSIX-style archive paths and includes
# dot-prefixed .runtime and .engine-ready-manifest.json on Windows.
$PackScript = Join-Path $Downloads 'write-archive.py'
$PythonPack = @'
import sys
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
base = Path(sys.argv[1]).resolve()
dest = Path(sys.argv[2]).resolve()
with ZipFile(dest, "w", ZIP_DEFLATED, compresslevel=8, allowZip64=True) as archive:
    for path in sorted(base.rglob("*")):
        if path.is_file():
            name = "/".join((base.name,) + path.relative_to(base).parts)
            archive.write(path, arcname=name)
with ZipFile(dest) as archive:
    names = set(archive.namelist())
    for mandatory in [".runtime/python/python.exe",
                      ".runtime/tools/ffmpeg.exe",
                      ".runtime/fluidsynth/bin/fluidsynth.exe",
                      ".runtime/soundfonts/GeneralUser-GS.sf2",
                      ".engine-ready-manifest.json",
                      "Start-Song-Studio.cmd"]:
        assert base.name + "/" + mandatory in names, mandatory
    assert archive.testzip() is None, "corrupt ZIP entry"
print("Portable Ready ZIP verified:", len(names), "files")
'@
[IO.File]::WriteAllText($PackScript, $PythonPack, (New-Object Text.UTF8Encoding($false)))
& $py $PackScript $Stage $Zip
if ($LASTEXITCODE -ne 0) { throw 'Portable offline Ready ZIP verification failed' }
$Hash = (Get-FileHash -LiteralPath $Zip -Algorithm SHA256).Hash.ToLowerInvariant()
$SHAFile = $Zip + '.sha256'
"$Hash  $($DirName).zip" | Set-Content -LiteralPath $SHAFile -Encoding ascii
Step ("Published candidate: $Zip")
Step ("ZIP size: {0:N2} MB" -f ((Get-Item $Zip).Length / 1MB))
Step ("SHA256: $Hash")
