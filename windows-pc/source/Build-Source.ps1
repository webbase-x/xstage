param([string]$PythonExe='')
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'tools\Build-Python.ps1')
Assert-XStagePlatform
$venvFolder=Join-Path $PSScriptRoot '.build-venv'
$venvPython=Join-Path $venvFolder 'Scripts\python.exe'
$basePython=$null
if ($PythonExe) { $basePython=Get-XStageBuildPython -PythonExe $PythonExe }
if (-not (Test-XStageBuildPython $venvPython)) {
    if (-not $basePython) { $basePython=Get-XStageBuildPython }
    # Retain existing environments. Never move/delete one to repair a build.
    if (Test-Path -LiteralPath $venvFolder) {
        $venvFolder=Join-Path $PSScriptRoot ('.build-venv-py313-'+[Guid]::NewGuid().ToString('N'))
        $venvPython=Join-Path $venvFolder 'Scripts\python.exe'
    }
    & $basePython -m venv $venvFolder
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create the CPython 3.13 build environment.' }
}
if (-not (Test-XStageBuildPython $venvPython)) { throw 'Use CPython 3.13 x64 for the locked build.' }
& (Join-Path $PSScriptRoot 'Setup-Dependencies.ps1')
$wheelhouse=Join-Path $PSScriptRoot 'offline\wheels'
New-Item -ItemType Directory -Path $wheelhouse -Force | Out-Null
& $venvPython -m pip install --only-binary=:all: --find-links $wheelhouse -r (Join-Path $PSScriptRoot 'requirements-build.lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check internet/proxy or provide matching CPython 3.13 x64 wheels in offline\wheels.' }
& $venvPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Python dependency conflicts detected. Build stopped.' }
& $venvPython (Join-Path $PSScriptRoot 'tools\check_dependencies.py') --home $PSScriptRoot
if ($LASTEXITCODE -ne 0) { throw 'Dependency verification failed; see dependency-report.json.' }
& (Join-Path $PSScriptRoot 'build.ps1') -PythonExe $venvPython
