#requires -Version 5.1
<#
Build X-Stage Song Studio PC Ready portable ZIP on Windows GitHub Actions.
Downloads happen ON THE BUILD RUNNER ONLY. Users receive all runtimes prebundled.
The AI inference script, pinned ONNX model and wheel dependencies are included at build time.
#>
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Repo = Split-Path -Parent $PSScriptRoot
$Version = 'v0.3.25-build325'
if ($Version -match '^v(\d+\.\d+\.\d+)-build(\d+)$') {
    $AppVersion = $Matches[1]
    $AppBuild = [int]$Matches[2]
} else {
    throw 'Invalid Song Studio release version'
}
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
    # GitHub runner dependencies are externally hosted. A temporary 429/503
    # must not abort an otherwise successful PC Ready build immediately.
    # Retry only the same HTTPS source, then validate its existing SHA check.
    for ($Attempt = 1; $Attempt -le 4; $Attempt++) {
        try {
            Step "Downloading $Url (attempt $Attempt/4)"
            Invoke-WebRequest -Uri $Url -OutFile $Target -UseBasicParsing -MaximumRedirection 8 -TimeoutSec 240
            if (!(Test-Path $Target) -or (Get-Item $Target).Length -lt 64) { throw "Empty dependency: $Url" }
            return
        } catch {
            if (Test-Path -LiteralPath $Target) { Remove-Item -LiteralPath $Target -Force -ErrorAction SilentlyContinue }
            if ($Attempt -eq 4) { throw }
            $Pause = [int][Math]::Min(20, [Math]::Pow(2, $Attempt + 1))
            Step "Dependency temporarily unavailable: $Url · retry in $Pause s"
            Start-Sleep -Seconds $Pause
        }
    }
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
  'songstudio-pc/history_store.py' = 'history_store.py'
 'songstudio-pc/ncn_lyrics.py' = 'ncn_lyrics.py'
 'songstudio-pc/song_index.py' = 'song_index.py'
 'songstudio-pc/ai_lyrics.py' = 'ai_lyrics.py'
 'songstudio-pc/lyric_alignment.py' = 'lyric_alignment.py'
 'songstudio-pc/lyric_text_groups.py' = 'lyric_text_groups.py'
 'songstudio-pc/google_drive.py' = 'google_drive.py'
 'songstudio-pc/online_publish.py' = 'online_publish.py'
 'songstudio-pc/folder_upload.py' = 'folder_upload.py'
 'songstudio-pc/code_registry.py' = 'code_registry.py'
 'songstudio-pc/song_export.py' = 'song_export.py'
 'songstudio-pc/live_preview.py' = 'live_preview.py'
 'songstudio-pc/ai_separate.py' = 'ai_separate.py'
 'songstudio-pc/ai-model.lock.json' = 'ai-model.lock.json'
 'songstudio-pc/pick_path.ps1' = 'pick_path.ps1'
 'songstudio-pc/README-READY.md' = 'README.md'
 'songstudio-pc/Create-Desktop-Shortcut.cmd' = 'Create-Desktop-Shortcut.cmd'
 'songstudio-pc/Create-Desktop-Shortcut.ps1' = 'Create-Desktop-Shortcut.ps1'
 'studio/app-icon.svg' = 'studio/app-icon.svg'
 'studio/site.webmanifest' = 'studio/site.webmanifest'
 'studio/index.html' = 'studio/index.html'
 'studio/app.js' = 'studio/app.js'
 'studio/style.css' = 'studio/style.css'
 'studio/entry.js' = 'studio/entry.js'
}
foreach ($item in $map.GetEnumerator()) { CopyFromRepo $item.Key $item.Value }

# Google Desktop clients are PUBLIC OAuth clients. The Google token endpoint
# can nevertheless require BOTH client_id and client_secret (HTTP 400 when
# missing) even with PKCE. Supply the pair from the SAME Google Desktop JSON.
# GitHub Actions Secret keeps the secret OUT of Git history/build logs, but
# it necessarily becomes visible to users who inspect the distributed ZIP.
# NEVER bundle user refresh/access tokens or Google login passwords.
$DesktopClientId = [string]$env:XSTAGE_GOOGLE_DESKTOP_CLIENT_ID
$DesktopClientSecret = [string]$env:XSTAGE_GOOGLE_DESKTOP_CLIENT_SECRET
if (![string]::IsNullOrWhiteSpace($DesktopClientId) -and
    ![string]::IsNullOrWhiteSpace($DesktopClientSecret)) {
    if ($DesktopClientId -notmatch '^[0-9]+-[A-Za-z0-9_-]+\.apps\.googleusercontent\.com$') {
        throw 'Invalid XSTAGE_GOOGLE_DESKTOP_CLIENT_ID: expected Google Desktop OAuth client ID'
    }
    if ($DesktopClientSecret.Length -lt 8 -or $DesktopClientSecret -match '[\r\n]') {
        throw 'Invalid XSTAGE_GOOGLE_DESKTOP_CLIENT_SECRET: check Desktop OAuth JSON'
    }
    $publicClient = [ordered]@{
        installed = [ordered]@{
            client_id = $DesktopClientId
            client_secret = $DesktopClientSecret
            auth_uri = 'https://accounts.google.com/o/oauth2/v2/auth'
            token_uri = 'https://oauth2.googleapis.com/token'
            redirect_uris = @('http://127.0.0.1')
        }
    }
    $clientDir = Join-Path $Stage 'config'
    New-Item -ItemType Directory -Force -Path $clientDir | Out-Null
    $clientFile = Join-Path $clientDir 'google-oauth-client.json'
    ConvertTo-Json -InputObject $publicClient -Depth 6 | Set-Content -LiteralPath $clientFile -Encoding UTF8
    Step 'Included complete public Google Desktop OAuth client pair (no user tokens)'
} else {
    # Never distribute a broken ID-only OAuth client: that causes Google 400.
    Write-Warning 'Google Desktop OAuth ID+Secret pair missing from GitHub Actions config. Bundled OAuth is disabled; users may import the original Desktop Client JSON once in Advanced Settings.'
}
Step 'Rendering X-Stage Song Studio PC native ICO and 512px icon for Windows'
& python (Join-Path $Repo 'scripts/build_songstudio_app_icon.py') (Join-Path $Stage 'studio')
if ($LASTEXITCODE -ne 0) { throw 'Rendering Song Studio app icon failed' }
foreach ($asset in @('studio/app-icon.svg','studio/app-icon.ico','studio/app-icon-512.png','studio/site.webmanifest')) {
    if (!(Test-Path -LiteralPath (Join-Path $Stage $asset))) { throw "Missing app artwork: $asset" }
}


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

# 4b. Include OFFLINE HTDemucs AI model and pinned Windows x64 inference dependencies.
# These downloads happen on GitHub Actions ONLY. No requests on users' PCs.
$ModelDir = Join-Path $Runtime 'models'
$AiSite = Join-Path $Runtime 'ai-site'
New-Item -ItemType Directory -Force -Path $ModelDir, $AiSite | Out-Null
$ModelLock = Get-Content -LiteralPath (Join-Path $Stage 'ai-model.lock.json') -Raw | ConvertFrom-Json
$ModelURL = [string]$ModelLock.model_url
$ModelHash = [string]$ModelLock.model_sha256
$ModelFile = Join-Path $ModelDir ([string]$ModelLock.filename)
if ($ModelURL -notmatch '^https://huggingface\.co/StemSplitio/htdemucs-onnx/resolve/') {
    throw 'Model lockfile points to an unexpected origin'
}
if ($ModelLock.filename -ne 'htdemucs_fp16weights.onnx') {
    throw 'Unexpected model filename in lockfile'
}
Step "Downloading pinned HTDemucs ONNX model on CI (~166 MB)..."
try {
    Download $ModelURL $ModelFile
} catch {
    Step "Trying resumable curl mirror request for Hugging Face model: $_"
    & curl.exe -fL --retry 3 --retry-delay 3 --connect-timeout 30 --max-time 720 -o $ModelFile $ModelURL
    if ($LASTEXITCODE -ne 0) { throw 'HTDemucs ONNX model download failed on Windows builder' }
}
if ((Get-Item $ModelFile).Length -lt 100MB) { throw 'AI ONNX file unexpectedly small' }
CheckSHA $ModelFile $ModelHash
Step 'Bundling pinned NumPy + ONNX Runtime CPU wheels on Windows build runner'
# actions/setup-python supplies Python 3.13 plus pip on GitHub Windows runner.
& python -m pip install --disable-pip-version-check --no-compile --only-binary=:all: --target $AiSite "numpy==2.2.6" "onnxruntime==1.23.2"
if ($LASTEXITCODE -ne 0) { throw 'Failed to install pinned Windows AI wheels in the bundle' }
$Pth = Join-Path $PyDir 'python313._pth'
if (!(Test-Path -LiteralPath $Pth)) { throw 'Embedded Python path configuration missing' }
# Python's embeddable distribution ignores global site-packages and the system
# registry. The bundled AI dependencies live only within this ZIP.
Add-Content -LiteralPath $Pth -Value '..\ai-site' -Encoding ASCII
& $py -c "import numpy,onnxruntime; print('OFFLINE_AI_READY',numpy.__version__,onnxruntime.__version__)"
if ($LASTEXITCODE -ne 0) { throw 'Bundled Python cannot import local ONNX Runtime/NumPy' }
Step 'All AI libraries and model included, no downloads required by user'

Step 'Downloading verified offline multilingual Whisper base model and native CLI on CI'
$WhisperZip = Join-Path $Downloads 'whisper-bin-x64.zip'
$WhisperURL = 'https://github.com/ggml-org/whisper.cpp/releases/download/b5454/whisper-bin-x64.zip'
$WhisperZipSHA = '6ba69e3482d7826214f90a6a9c84ca07782aec1e1d0c6a7c30c994fd5d816ccb'
Download $WhisperURL $WhisperZip
CheckSHA $WhisperZip $WhisperZipSHA
$WhisperExtract = Join-Path $Downloads 'whisper-unpacked'
Expand-Archive -LiteralPath $WhisperZip -DestinationPath $WhisperExtract -Force
$WhisperExe = Get-ChildItem -LiteralPath $WhisperExtract -Recurse -Filter 'whisper-cli.exe' -File | Select-Object -First 1
if (!$WhisperExe) { throw 'Verified whisper.cpp Windows bundle has no whisper-cli.exe' }
$WhisperFolder = Join-Path $Runtime 'whisper'
New-Item -ItemType Directory -Force -Path $WhisperFolder | Out-Null
Copy-Item -Path (Join-Path $WhisperExe.Directory.FullName '*') -Destination $WhisperFolder -Recurse -Force
if (!(Test-Path (Join-Path $WhisperFolder 'whisper-cli.exe'))) { throw 'Missing offline Whisper CLI' }

# Multilingual base (not base.en) supports Thai; hash is from upstream model.
$WhisperModelURL = 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin'
$WhisperModelSHA = '60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe'
$WhisperModel = Join-Path $ModelDir 'ggml-base.bin'
try {
    Download $WhisperModelURL $WhisperModel
} catch {
    Write-Warning "Retrying Whisper model download with curl: $_"
    & curl.exe -fL --retry 3 --retry-delay 4 --connect-timeout 30 --max-time 900 -o $WhisperModel $WhisperModelURL
    if ($LASTEXITCODE -ne 0) { throw 'Failed to download Whisper multilingual model on CI' }
}
if ((Get-Item $WhisperModel).Length -lt 100MB) { throw 'Whisper model file too small' }
CheckSHA $WhisperModel $WhisperModelSHA
Step 'Verified offline Whisper multilingual ASR included, no runtime downloads'


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
 'ncn_lyrics.py',
 'song_index.py',
 'ai_lyrics.py',
 'lyric_alignment.py',
 'lyric_text_groups.py',
 'google_drive.py',
 'song_export.py',
 'code_registry.py',
 'online_publish.py',
 'folder_upload.py',
 'history_store.py',
 'live_preview.py',
 'ai_separate.py',
 'ai-model.lock.json',
 '.runtime/models/htdemucs_fp16weights.onnx',
 '.runtime/models/ggml-base.bin',
 '.runtime/whisper/whisper-cli.exe',
 '.runtime/python/python313._pth',
 '.runtime/ai-site/numpy/__init__.py',
 '.runtime/ai-site/onnxruntime/__init__.py',
 'pick_path.ps1',
 'Create-Desktop-Shortcut.cmd',
 'Create-Desktop-Shortcut.ps1',
 'studio/app-icon.svg',
 'studio/app-icon.ico',
 'studio/app-icon-512.png',
 'studio/site.webmanifest',
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
    version = $AppVersion
    build = $AppBuild
    created_utc = [DateTime]::UtcNow.ToString('o')
    contents = @('Python 3.13.10 embeddable', 'FFmpeg 9.x essentials', 'FluidSynth 2.6.2 win64', 'GeneralUser GS 2.0.3 SoundFont', 'HTDemucs ONNX model (MIT)', 'NumPy 2.2.6', 'ONNX Runtime 1.23.2')
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
                      ".runtime/models/htdemucs_fp16weights.onnx",
                      "ai_separate.py",
                      "live_preview.py",
                      "song_export.py",
                      "song_index.py",
                      "lyric_alignment.py",
                      "lyric_text_groups.py",
                      "code_registry.py",
                      "google_drive.py",
                      "studio/app-icon.svg",
                      "studio/app-icon.ico",
                      "studio/app-icon-512.png",
                      "Create-Desktop-Shortcut.cmd",
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
