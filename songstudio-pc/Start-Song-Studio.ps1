#requires -Version 5.1
# X-Stage Song Studio PC Source Launcher
# Performs a one-time download of official Python and Windows FFmpeg builds.
# The program itself runs against the user's local files, without uploading songs.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'Continue'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runtime = Join-Path $Root '.runtime'
$Tools = Join-Path $Runtime 'tools'
$PyDir = Join-Path $Runtime 'python'
$LogFile = Join-Path $Root 'setup.log'
$PythonURL = 'https://www.python.org/ftp/python/3.13.10/python-3.13.10-embeddable-amd64.zip'
# Published by Python.org in windows-3.13.10.json (pythonembed-3.13-64).
$PythonSHA256 = '42a6995f5badcde341d8cf28b1479dc62d97c6cb153aee694eeeef09b56b9f70'
$FFMPEGURL = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
$FFMPEGHashURL = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip.sha256'

function Status([string]$Message) {
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $line = "[$stamp] $Message"
    Write-Host $line -ForegroundColor Cyan
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
}
function Download-Verified([string]$URL, [string]$Output) {
    if ($URL -notmatch '^https://') { throw 'Only secure HTTPS downloads are allowed.' }
    Status "Downloading: $URL"
    # Use TLS 1.2 explicitly in older PowerShell 5.1 environments.
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $URL -OutFile $Output -UseBasicParsing -MaximumRedirection 4
    if (-not (Test-Path -LiteralPath $Output) -or (Get-Item -LiteralPath $Output).Length -lt 1000) {
        throw "Download is empty: $URL"
    }
}
try {
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw 'This source launcher currently supports 64-bit Windows only.'
    }
    if (-not (Test-Path -LiteralPath $Runtime)) { New-Item -ItemType Directory -Path $Runtime | Out-Null }
    if (-not (Test-Path -LiteralPath $Tools)) { New-Item -ItemType Directory -Path $Tools | Out-Null }
    if (-not (Test-Path -LiteralPath $PyDir)) { New-Item -ItemType Directory -Path $PyDir | Out-Null }

    Status '[1/3] Checking Python runtime'
    $Python = Join-Path $PyDir 'python.exe'
    $PythonW = Join-Path $PyDir 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $Python)) {
        $Zip = Join-Path $Runtime 'python-download.zip'
        Download-Verified -URL $PythonURL -Output $Zip
        Status 'Verifying official Python 3.13.10 SHA-256 before extraction...'
        $PythonActualSHA = (Get-FileHash -LiteralPath $Zip -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($PythonActualSHA -ne $PythonSHA256) {
            Remove-Item -LiteralPath $Zip -Force -ErrorAction SilentlyContinue
            throw 'Python 3.13.10 SHA-256 mismatch: download rejected; no runtime extracted.'
        }
        Status 'Extracting official Python 3.13.10 embedded runtime...'
        Expand-Archive -LiteralPath $Zip -DestinationPath $PyDir -Force
        Remove-Item -LiteralPath $Zip -ErrorAction SilentlyContinue
        if (-not (Test-Path -LiteralPath $Python)) { throw 'Official Python archive did not contain python.exe.' }
    }
    & $Python -c "import http.server, json, pathlib, subprocess, secrets; print('Python standard library ready')"
    if ($LASTEXITCODE -ne 0) { throw 'Python runtime self-test failed.' }

    Status '[2/3] Checking FFmpeg audio tools'
    $FFMPEG = Join-Path $Tools 'ffmpeg.exe'
    $FFProbe = Join-Path $Tools 'ffprobe.exe'
    if (-not (Test-Path -LiteralPath $FFMPEG) -or -not (Test-Path -LiteralPath $FFProbe)) {
        $Zip = Join-Path $Runtime 'ffmpeg-download.zip'
        $SHAFile = Join-Path $Runtime 'ffmpeg-download.sha256'
        Download-Verified -URL $FFMPEGURL -Output $Zip
        # Download trusted vendor's independently published SHA-256 digest.
        Status 'Verifying downloaded FFmpeg archive SHA-256...'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $FFMPEGHashURL -OutFile $SHAFile -UseBasicParsing -MaximumRedirection 4
        $SHA = [IO.File]::ReadAllText($SHAFile)
        if ($SHA -notmatch '(?i)\b[a-f0-9]{64}\b') { throw 'Vendor SHA-256 manifest is invalid.' }
        $Expected = $Matches[0].ToUpperInvariant()
        $Actual = (Get-FileHash -LiteralPath $Zip -Algorithm SHA256).Hash.ToUpperInvariant()
        if ($Expected -ne $Actual) { throw "FFmpeg checksum mismatch. Expected $Expected, got $Actual" }

        $Extract = Join-Path $Runtime 'ffmpeg-unpacked'
        if (Test-Path -LiteralPath $Extract) { Remove-Item -LiteralPath $Extract -Force -Recurse }
        Status 'Extracting FFmpeg...'
        Expand-Archive -LiteralPath $Zip -DestinationPath $Extract -Force
        $FFExe = Get-ChildItem -LiteralPath $Extract -Recurse -Filter 'ffmpeg.exe' -File | Select-Object -First 1
        $FPExe = Get-ChildItem -LiteralPath $Extract -Recurse -Filter 'ffprobe.exe' -File | Select-Object -First 1
        if (-not $FFExe -or -not $FPExe) { throw 'Downloaded FFmpeg package did not contain expected executables.' }
        Copy-Item -LiteralPath $FFExe.FullName -Destination $FFMPEG -Force
        Copy-Item -LiteralPath $FPExe.FullName -Destination $FFProbe -Force
        Remove-Item -LiteralPath $Extract -Force -Recurse -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $Zip -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $SHAFile -Force -ErrorAction SilentlyContinue
    }
    & $FFMPEG -hide_banner -version | Select-Object -First 1
    if ($LASTEXITCODE -ne 0) { throw 'FFmpeg runtime self-test failed.' }

    Status '[3/3] Launching Song Studio PC quietly'
    $Engine = Join-Path $Root 'engine.py'
    if (-not (Test-Path -LiteralPath $Engine)) { throw 'Missing engine.py; extract full source archive first.' }
    if (-not (Test-Path -LiteralPath (Join-Path $Root 'studio/index.html'))) {
        throw 'Missing studio UI; extract full source archive first.'
    }
    $Executable = if (Test-Path -LiteralPath $PythonW) { $PythonW } else { $Python }
    $ProcessInfo = New-Object System.Diagnostics.ProcessStartInfo
    $ProcessInfo.FileName = $Executable
    $ProcessInfo.Arguments = '"' + $Engine + '"'
    $ProcessInfo.WorkingDirectory = $Root
    $ProcessInfo.UseShellExecute = $false
    $ProcessInfo.CreateNoWindow = $true
    $Process = [System.Diagnostics.Process]::Start($ProcessInfo)
    if (-not $Process) { throw 'Cannot start local engine process.' }
    Start-Sleep -Milliseconds 1000
    if ($Process.HasExited) { throw "Engine process terminated during startup (code $($Process.ExitCode))." }
    Status "Local Engine started (PID $($Process.Id)). The PC window opens in Microsoft Edge if installed."
    Status 'During use no CMD is needed; sources and M4A outputs stay on this machine.'
    exit 0
}
catch {
    $Message = $_.Exception.Message
    Status "ERROR: $Message"
    Write-Host ''
    Write-Host 'Setup cannot complete. Do not claim the engine is ready.' -ForegroundColor Red
    exit 1
}
