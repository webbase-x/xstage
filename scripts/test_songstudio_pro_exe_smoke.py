"""Run the actual packaged EXE and verify its native embedded Qt WebView."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.request import urlopen

def main():
    if os.name != "nt":
        raise SystemExit("Windows runner required")
    root = Path(__file__).resolve().parents[1]
    exe = (root / sys.argv[1]).resolve()
    if not exe.is_file():
        raise SystemExit(f"Built EXE missing: {exe}")
    workspace = root / "dist" / "pro-exe-smoke"
    workspace.mkdir(parents=True, exist_ok=True)
    log = workspace / "LOGS" / "song-studio-pro.log"
    evidence = workspace / "exe-smoke-result.json"
    env = os.environ.copy()
    env.update(QT_QPA_PLATFORM="offscreen", QT_OPENGL="software",
               QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu --no-sandbox")
    checks = dict(exe_launched=False, embedded_webview_loaded=False,
                  javascript_bound=False, latest_dashboard_embedded=False)
    errors = []
    process = subprocess.Popen([str(exe), "--workspace", str(workspace)],
                               cwd=root, env=env)
    try:
        deadline = time.monotonic() + 75
        while time.monotonic() < deadline:
            if log.exists():
                for line in log.read_text(encoding="utf-8",errors="replace").splitlines():
                    try:
                        event = json.loads(line)
                    except (ValueError,TypeError):
                        continue
                    if event.get("event") == "state.ready":
                        checks["exe_launched"] = True
                    if event.get("event") == "web.load.finished" and event.get("ok") is True:
                        checks["embedded_webview_loaded"] = True
                    if event.get("event") == "web.core.check" and event.get("bound") is True:
                        checks["javascript_bound"] = True
                    if event.get("event") == "web.load.request" and not checks["latest_dashboard_embedded"]:
                        url = event.get("url")
                        if url:
                            try:
                                with urlopen(url,timeout=3) as response:
                                    html = response.read().decode("utf-8")
                                with urlopen(url+"style.css",timeout=3) as response:
                                    css = response.read().decode("utf-8")
                                overview=html.split('<div class="stat-grid"',1)[1].split("</div>",1)[0]
                                checks["latest_dashboard_embedded"] = (
                                    len(re.findall(r'<article class="stat(?: stat-attention)?"',overview)) == 4
                                    and 'class="import-disclosure import-advanced"' in html
                                    and 'id="source-browse"' in html
                                    and 'calm import workspace' in css)
                            except (OSError,UnicodeError,IndexError) as exc:
                                errors.append(str(exc)[:200])
            if all(checks.values()):
                break
            if process.poll() is not None:
                errors.append(f"EXE exited early: {process.returncode}")
                break
            time.sleep(1)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    result = {"ok":all(checks.values()),"checks":checks,"errors":errors[-5:]}
    evidence.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    for key,passed in checks.items():
        print(("PASS" if passed else "FAIL") + ": " + key,flush=True)
    if not result["ok"]:
        if log.exists():
            print(log.read_text(encoding="utf-8",errors="replace")[-5000:],flush=True)
        raise SystemExit("Packaged EXE native WebView smoke test failed")

if __name__ == "__main__":
    main()
