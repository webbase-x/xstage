$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'Dependency-Common.ps1')
function Test-XStagePython([string]$Executable) {
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) { return $false }
    try {
        & $Executable -c "import os,struct,sys,tkinter,venv,ssl; assert os.name=='nt' and struct.calcsize('P')==8 and (3,11)<=sys.version_info[:2]<=(3,14)" 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}
function Get-XStagePython {
    Assert-XStagePlatform
    $candidates=@()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($version in @('3.14','3.13','3.12','3.11')) {
            try { $found=& py ("-"+$version) -c 'import sys;print(sys.executable)' 2>$null
            } catch { continue }
            if ($LASTEXITCODE -eq 0 -and $found) { $candidates += [string]($found | Select-Object -Last 1) }
        }
    }
    $known=Join-Path $env:LOCALAPPDATA 'XStageKaraoke\Runtime\Python314\python.exe'
    $candidates += $known
    $command=Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command -and $command.Source -notmatch 'WindowsApps') { $candidates += $command.Source }
    foreach ($candidate in $candidates) { if (Test-XStagePython $candidate) { return $candidate } }
    $expected='92480239264744fe0386a1bd8275786fefa126e3129e56a68e22b52c73329965'
    $installer=Get-XStageDownload 'https://www.python.org/ftp/python/3.14.10/python-3.14.10-amd64.exe' 'python-3.14.10-amd64.exe' (Join-Path (Split-Path -Parent $PSScriptRoot) 'offline') { param($file)
        Assert-XStagePublisher $file 'Python Software Foundation'
        if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ine $expected) { throw 'Python checksum mismatch' }
    }
    Assert-XStagePublisher $installer 'Python Software Foundation'
    if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash -ine $expected) { throw ('Python installer checksum mismatch: '+$installer) }
    $folder=Split-Path -Parent $known
    $process=Start-Process -FilePath $installer -ArgumentList @('/passive','InstallAllUsers=0','Include_launcher=0','Include_pip=1','Include_tcltk=1','Include_test=0','PrependPath=0',('TargetDir="'+$folder+'"')) -Wait -PassThru
    if ($process.ExitCode -notin @(0,3010)) { throw ('Python installation failed/cancelled: '+$process.ExitCode) }
    if (-not (Test-XStagePython $known)) { throw 'Python runtime is not ready. Restart if requested and rerun the installer.' }
    return $known
}
