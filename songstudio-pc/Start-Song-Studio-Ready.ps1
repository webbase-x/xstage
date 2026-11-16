#requires -Version 5.1
<#
X-Stage Song Studio PC Ready — offline-only launcher.
The ZIP must already contain Python, FFmpeg, FluidSynth and a SoundFont.
No software, package, runtime or model is downloaded during startup.
#>
param([switch]$NoLaunch, [string]$ReadySignal = '')
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runtime = Join-Path $Root '.runtime'
$Log = Join-Path $Root 'start-ready.log'
function Write-Status([string]$Text) {
    $line = ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Text)
    Write-Host $line
    Add-Content -LiteralPath $Log -Encoding UTF8 -Value $line
}
function Check-File([string]$RelPath) {
    $path = Join-Path $Root $RelPath
    if (!(Test-Path -LiteralPath $path -PathType Leaf)) {
        throw ("Missing bundled file: {0}. Extract the complete READY ZIP (not Source Preview)." -f $RelPath)
    }
    return $path
}
try {
    Write-Status 'X-Stage Song Studio PC Ready — verifying local offline environment'
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'Only 64-bit Windows is supported.' }
    $ManifestPath = Check-File '.engine-ready-manifest.json'
    $Manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($Manifest.bundle_type -ne 'ready-offline' -or $Manifest.platform -ne 'windows-x64') {
        throw 'Invalid Ready bundle manifest. Source Preview is not a Ready package.'
    }
    $py = Check-File '.runtime\python\python.exe'
    $pyw = Check-File '.runtime\python\pythonw.exe'
    $ffmpeg = Check-File '.runtime\tools\ffmpeg.exe'
    $ffprobe = Check-File '.runtime\tools\ffprobe.exe'
    $sfont = Check-File '.runtime\soundfonts\GeneralUser-GS.sf2'
    $engine = Check-File 'engine.py'
    [void](Check-File 'desktop_window.py')
    [void](Check-File '.runtime\qt-site\PySide6\QtWebEngineWidgets.pyd')
    [void](Check-File 'ncn_lyrics.py')
    [void](Check-File 'ai_lyrics.py')
    [void](Check-File '.runtime\\whisper\\whisper-cli.exe')
    [void](Check-File '.runtime\\models\\ggml-base.bin')
    [void](Check-File 'google_drive.py')
    $qtProcess = Get-ChildItem -LiteralPath (Join-Path $Runtime 'qt-site\PySide6') -Filter 'QtWebEngineProcess.exe' -Recurse -File | Select-Object -First 1
    if (!$qtProcess) { throw 'Bundled Qt WebEngine runtime is missing.' }
    $livePreview = Check-File 'live_preview.py'
    $aiScript = Check-File 'ai_separate.py'
    $aiModel = Check-File '.runtime\models\htdemucs_fp16weights.onnx'
    [void](Check-File '.runtime\ai-site\numpy\__init__.py')
    [void](Check-File '.runtime\ai-site\onnxruntime\__init__.py')
    $picker = Check-File 'pick_path.ps1'
    $ui = Check-File 'studio\index.html'
    [void](Check-File 'studio\app.js')
    [void](Check-File 'studio\style.css')
    [void](Check-File 'studio\pro-design.css')
    [void](Check-File 'created_xsk_export.py')
    [void](Check-File 'created_json_manager.py')
    [void](Check-File 'xsk_package.py')
    [void](Check-File 'xsk_keys.py')
    [void](Check-File 'pro_license.py')
    [void](Check-File 'pc_ready_updates.py')
    [void](Check-File '.runtime\fluidsynth\bin\fluidsynth.exe')
    [void](Check-File '.runtime\tools\ffprobe.exe')
    [void](Check-File 'studio\app-icon.svg')
    [void](Check-File 'studio\app-icon.ico')
    [void](Check-File 'studio\app-icon-512.png')
    [void](Check-File 'studio\site.webmanifest')
    [void](Check-File 'Create-Desktop-Shortcut.cmd')
    [void](Check-File 'Create-Desktop-Shortcut.ps1')
    [void](Check-File 'studio\entry.js')
    if ($null -eq $Manifest.files -or $Manifest.files.Count -lt 6) {
        throw 'Ready bundle integrity manifest is incomplete.'
    }
    $num = 0
    foreach ($item in $Manifest.files) {
        if ($item.path -notmatch '^[a-zA-Z0-9._/ +()-]+$' -or $item.path.Contains('..')) {
            throw 'Unsafe manifest path.'
        }
        $file = Check-File ($item.path.Replace('/', '\'))
        if (-not ($item.sha256 -match '^[a-fA-F0-9]{64}$')) { throw "Invalid checksum for $($item.path)" }
        $actual = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
        if ($actual -ne $item.sha256.ToUpperInvariant()) {
            throw "Bundled component integrity failure: $($item.path). Extract ZIP again."
        }
        $num++
    }
    Write-Status ("Verified {0} bundled component files and SHA-256 checksums." -f $num)
    $versionOutput = & $py -c "import json,subprocess,pathlib,http.server; print('PYTHON_OK')" 2>&1
    if ($LASTEXITCODE -ne 0 -or ($versionOutput -notcontains 'PYTHON_OK')) { throw 'Bundled Python runtime check failed.' }
    # Collect all output before testing exit code. Select-Object -First 1 can close
    # the native process stdout pipe early and cause a false failure on Windows.
    $ffText = (& $ffmpeg -hide_banner -version 2>&1 | Out-String)
    $ffExit = $LASTEXITCODE
    $ffVersion = (($ffText -split "\r?\n") | Where-Object { $_ -match 'ffmpeg version' } | Select-Object -First 1)
    if ($ffExit -ne 0 -or !$ffVersion) { throw ("Bundled FFmpeg runtime check failed (exit {0}): {1}" -f $ffExit, $ffText) }
    Write-Status ("FFmpeg: {0}" -f $ffVersion)
    # SoundFont RIFF header includes 'sfbk' at byte offset 8.
    $stream = [IO.File]::OpenRead($sfont)
    try {
        $header = New-Object byte[] 12
        if ($stream.Read($header,0,12) -ne 12 -or
            [Text.Encoding]::ASCII.GetString($header,0,4) -ne 'RIFF' -or
            [Text.Encoding]::ASCII.GetString($header,8,4) -ne 'sfbk') {
            throw 'Bundled SoundFont file is invalid.'
        }
    } finally { $stream.Dispose() }
    if ((Get-Item $aiModel).Length -lt 100MB) { throw 'AI Separation model is incomplete.' }
    $qtTest = & $py -c "from PySide6.QtWebEngineWidgets import QWebEngineView; print('QT_OK')" 2>&1
    if ($LASTEXITCODE -ne 0 -or ($qtTest -notcontains 'QT_OK')) { throw 'Bundled Qt Desktop runtime check failed.' }
    Write-Status 'SoundFont, AI and native Qt WebEngine runtime verified. Nothing to install or download.'
    if ($NoLaunch) {
        Write-Status 'Offline readiness check passed (NoLaunch mode).'
        exit 0
    }
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $pyw
    $start.Arguments = '"' + $engine + '"'
    $start.WorkingDirectory = $Root
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $proc = [System.Diagnostics.Process]::Start($start)
    if ($null -eq $proc) { throw 'Could not launch the local Song Studio Engine.' }
    Start-Sleep -Milliseconds 900
    if ($proc.HasExited) { throw ('Local Engine failed at launch (exit {0}).' -f $proc.ExitCode) }
    if ($ReadySignal) {
        $allowedParent = (Resolve-Path -LiteralPath (Split-Path -Parent $Root)).Path
        $signalParent = (Resolve-Path -LiteralPath (Split-Path -Parent $ReadySignal)).Path
        if (![string]::Equals($signalParent, $allowedParent, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Unsafe update startup signal path.'
        }
        [IO.File]::WriteAllText($ReadySignal, ("READY:{0}" -f $proc.Id), (New-Object Text.UTF8Encoding($false)))
    }
    Write-Status ("Ready: Engine PID {0}, native Qt Desktop UI opens without Edge/browser." -f $proc.Id)
    Write-Status 'All audio processing and files remain on this PC.'
    exit 0
}
catch {
    Write-Status ('ERROR: ' + $_.Exception.Message)
    exit 1
}
