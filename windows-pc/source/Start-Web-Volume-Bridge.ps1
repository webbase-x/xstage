# User-initiated Windows master-volume companion for Karaoke Online.
# Never installs a service or modifies system audio during startup.
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $here
try {
  if (Test-Path (Join-Path $here 'XStageWindowsVolumeBridge.exe')) {
    & (Join-Path $here 'XStageWindowsVolumeBridge.exe')
  } elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 -m karaoke.web_volume_bridge
  } elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python -m karaoke.web_volume_bridge
  } else {
    throw 'Python 3 or XStageWindowsVolumeBridge.exe is required. Download the EXE from GitHub Actions.'
  }
} finally { Pop-Location }
