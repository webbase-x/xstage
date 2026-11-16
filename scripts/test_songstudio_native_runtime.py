"""Runtime smoke test for a fully packaged Windows Song Studio Qt desktop.

Requires the complete Ready directory. Offscreen mode is restricted to CI,
so normal application behavior remains unchanged.
"""
from __future__ import annotations
import os
import pathlib
import subprocess
import sys
import time

root = pathlib.Path(sys.argv[1]).resolve()
python = root / ".runtime" / "python" / "python.exe"
bootstrap = root / "desktop_bootstrap.py"
assert python.is_file() and bootstrap.is_file(), "Complete PC Ready bundle required"
env = os.environ.copy()
env.update({
    "QT_QPA_PLATFORM": "offscreen",
    "QTWEBENGINE_DISABLE_SANDBOX": "1",
    "QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu --no-sandbox --disable-software-rasterizer",
    "PYTHONUNBUFFERED": "1",
})
process = subprocess.Popen(
    [str(python), str(bootstrap)],
    cwd=str(root), env=env, stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
try:
    for n in range(24):
        time.sleep(0.5)
        if process.poll() is not None:
            error = root / "engine-startup-error.log"
            diagnostic = error.read_text(encoding="utf-8", errors="replace") if error.exists() else ""
            raise AssertionError(
                f"Embedded desktop exited with {process.returncode}: {diagnostic[-5000:]}")
    print("PASS: real bundled Qt engine stayed alive for 12 seconds")
finally:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
