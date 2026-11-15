$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'Dependency-Common.ps1')
function Test-XStageBuildPython([string]$Executable) {
    try {
        if (-not $Executable -or -not (Test-Path -LiteralPath $Executable -PathType Leaf)) { return $false }
        & $Executable -c "import os,struct,sys,tkinter,venv,ssl; assert os.name=='nt' and struct.calcsize('P')==8 and sys.version_info[:2]==(3,13)" 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}
function Select-XStageBuildPython([string[]]$Candidates) {
    foreach ($candidate in @($Candidates | Select-Object -Unique)) {
        if (Test-XStageBuildPython $candidate) { return $candidate }
    }
    throw 'Locked build requires CPython 3.13 x64. Install it or pass Build-Source.ps1 -PythonExe <path-to-python.exe>. No Python installer was launched.'
}
function Get-XStageBuildPython([string]$PythonExe='') {
    Assert-XStagePlatform
    if ($PythonExe) { return Select-XStageBuildPython -Candidates @($PythonExe) }
    $candidates=@()
    $launcher=Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        try {
            $found=& $launcher.Source -3.13 -c 'import sys;print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $found) { $candidates += [string]($found | Select-Object -Last 1) }
        } catch { }
    }
    $command=Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command -and $command.Source -notmatch 'WindowsApps') { $candidates += $command.Source }
    if ($env:LOCALAPPDATA) { $candidates += Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe' }
    return Select-XStageBuildPython -Candidates $candidates
}
