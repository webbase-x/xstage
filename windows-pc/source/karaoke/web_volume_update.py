"""Startup-only update of the official standalone Windows helper."""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

try:
    from karaoke.web_volume_build import BUILD
except ImportError:
    BUILD = 0

API = "https://api.github.com/repos/webbase-x/xstage/releases/tags/windows-volume-bridge"
EXE = "XStageWindowsVolumeBridge.exe"
DOWNLOAD = "https://github.com/webbase-x/xstage/releases/download/windows-volume-bridge/" + EXE

# Static script; all path values are passed in environment variables, not interpolated.
SWAP = r"""
$ErrorActionPreference = 'Stop'
$target = $env:XSTAGE_TARGET
$new = $env:XSTAGE_NEW
$backup = $target + '.previous'
try {
  Wait-Process -Id ([int]$env:XSTAGE_PARENT) -Timeout 45 -ErrorAction SilentlyContinue
  if (Get-Process -Id ([int]$env:XSTAGE_PARENT) -ErrorAction SilentlyContinue) { throw 'Old process still running' }
  [System.IO.File]::Replace($new, $target, $backup, $true)
  try {
    Start-Process -FilePath $target -ArgumentList '--no-update' -ErrorAction Stop
  } catch {
    [System.IO.File]::Replace($backup, $target, $null, $true)
    throw
  }
} catch {
  Write-Host ('X-Stage update failed: ' + $_)
  if (Test-Path -LiteralPath $target) { Start-Process -FilePath $target -ArgumentList '--no-update' }
} finally {
  Remove-Item -LiteralPath $new -Force -ErrorAction SilentlyContinue
}
"""

def asset_for_update(release, current):
    for asset in release.get("assets", []):
        if asset.get("name") != EXE or asset.get("browser_download_url") != DOWNLOAD:
            continue
        match = re.fullmatch(r"build-(\d+)", asset.get("label") or "")
        digest = re.fullmatch(r"sha256:([a-fA-F0-9]{64})", asset.get("digest") or "")
        size = asset.get("size")
        if match and digest and int(match[1]) > current and isinstance(size, int) and 0 < size <= 100_000_000:
            return int(match[1]), digest[1].lower(), size
    return None

def check_and_install():
    if sys.platform != "win32" or not getattr(sys, "frozen", False) or BUILD <= 0:
        return False
    staged = None
    try:
        print("Checking for X-Stage Windows Volume Bridge updates...", flush=True)
        with urlopen(Request(API, headers={"User-Agent": "XStageWindowsVolumeBridge", "Accept": "application/vnd.github+json"}), timeout=5) as response:
            release = json.loads(response.read(1_000_000))
        update = asset_for_update(release, BUILD)
        if not update:
            return False
        version, expected, size = update
        target = Path(sys.executable).resolve()
        fd, path = tempfile.mkstemp(prefix=".xstage-update-", suffix=".exe", dir=target.parent)
        staged = Path(path)
        digest = hashlib.sha256()
        count = 0
        with os.fdopen(fd, "wb") as out, urlopen(Request(DOWNLOAD, headers={"User-Agent": "XStageWindowsVolumeBridge"}), timeout=10) as response:
            while chunk := response.read(256 * 1024):
                count += len(chunk)
                if count > size:
                    raise ValueError("Update exceeds expected size")
                digest.update(chunk)
                out.write(chunk)
        if count != size or digest.hexdigest() != expected:
            raise ValueError("Update SHA-256 or size mismatch")
        print("Installing verified build", version, flush=True)
        env = dict(os.environ, XSTAGE_TARGET=str(target), XSTAGE_NEW=str(staged), XSTAGE_PARENT=str(os.getpid()))
        # Use system PowerShell rather than a PATH-resolved executable.
        shell = Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        subprocess.Popen([str(shell), "-NoProfile", "-NonInteractive", "-Command", SWAP], env=env, close_fds=True)
        staged = None
        return True
    except Exception as error:
        print("Update unavailable; continuing current build:", error, flush=True)
        return False
    finally:
        if staged:
            try:
                staged.unlink(missing_ok=True)
            except OSError:
                pass
