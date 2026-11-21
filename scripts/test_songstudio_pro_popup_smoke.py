"""Smoke-test actual HTML dialogs in Windows Qt WebEngine with no physical monitor.

Retains a strict fail result for: page load failures, absent core bindings,
unresponsive JS context, dialog races, disappearing dialogs, bad backdrops.
A GitHub runner cannot replace a physical GPU/desktop focus test.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

if os.name != "nt":
    raise SystemExit("Windows Qt WebEngine runner required")

# Headless Windows runner may not expose an accelerated GLES context. Choose
# Chromium's software ANGLE renderer instead of relying on GPU virtualization.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_OPENGL"] = "software"
os.environ["QT_QUICK_BACKEND"] = "software"
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    + " --use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader"
    + " --disable-gpu-sandbox --no-sandbox"
).strip()

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

root = Path(__file__).resolve().parents[1]
page_file = root / "songstudio-plus" / "web" / "index.html"
app = QApplication([])
view = QWebEngineView()
view.resize(1280, 760)
errors = []
finished = False
deadline = time.monotonic() + 24
console_errors = []


class DiagnosticPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, lineno, source_id):
        msg = str(message)
        if "ERR" in str(level).upper() or "Error" in msg or "error" in msg:
            console_errors.append(f"{source_id}:{lineno}: {msg}"[:320])
        if "XSTAGE" in msg or "Uncaught" in msg:
            print("Qt console: " + msg[:300], flush=True)


page = DiagnosticPage(view)
view.setPage(page)


def finish(ok, detail):
    global finished
    if finished:
        return
    finished = True
    display = json.dumps(detail, ensure_ascii=False, default=str)
    print(("PASS" if ok else "FAIL") + ": Qt dialog smoke " + display,
          flush=True)
    if not ok:
        errors.append(display)
        if console_errors:
            print("Qt browser console: " + repr(console_errors[-8:]),
                  flush=True)
    # Terminate without triggering a fresh JS evaluation during shutdown.
    view.close()
    app.quit()


def run_js(script, callback, stage):
    """Use explicit JSON serialization for unambiguous Qt QVariant transport."""
    def receive(value):
        if finished:
            return
        try:
            if not isinstance(value, str) or not value:
                raise ValueError(f"empty/non-string JS result: {value!r}")
            result = json.loads(value)
        except (TypeError, ValueError) as exc:
            callback({"ok": False, "phase": stage,
                      "reason": str(exc), "url": page.url().toString()})
            return
        callback(result)
    page.runJavaScript(script, receive)


JS_READY = r"""(() => JSON.stringify({
    ok: document.readyState === "complete" &&
        Boolean(globalThis.__XSTAGE_CORE_BOUND__) &&
        Boolean(document.getElementById("settings-open")),
    phase: "core-ready",
    readyState: document.readyState,
    bound: Boolean(globalThis.__XSTAGE_CORE_BOUND__),
    url: location.href
}))()"""

JS_OPEN = r"""(() => {
    const button = document.getElementById("settings-open");
    button.click();
    button.click();
    const modal = document.getElementById("settings-dialog");
    return JSON.stringify({ok: modal.open &&
      document.querySelectorAll("dialog[open]").length === 1,
      phase: "double-click",
      open: modal.open,
      openCount: document.querySelectorAll("dialog[open]").length});
})()"""

JS_PERSIST = r"""(() => {
    const modal = document.getElementById("settings-dialog");
    return JSON.stringify({ok: modal.open &&
      document.querySelectorAll("dialog[open]").length === 1,
      phase: "persist-across-frame",
      open: modal.open,
      openCount: document.querySelectorAll("dialog[open]").length});
})()"""

JS_LIFECYCLE = r"""(() => {
    const settings = document.getElementById("settings-dialog");
    if (!settings.open)
      return JSON.stringify({ok: false, phase: "settings-disappeared"});
    settings.close();
    const states = [];
    for (const name of ["issues-dialog", "risk-dialog", "lyrics-dialog"]) {
      const dialog = document.getElementById(name);
      dialog.showModal();
      if (!dialog.open)
        return JSON.stringify({ok: false, phase: "open-" + name});
      for (let i=0; i<16; i++)
        document.getElementById("activity-subtitle").textContent="Refresh " + i;
      states.push({name, openCount: document.querySelectorAll("dialog[open]").length});
      dialog.close();
      if (dialog.open)
        return JSON.stringify({ok: false, phase: "close-" + name});
    }
    const backdropFilters =
      ["confirm-dialog", "settings-dialog", "issues-dialog",
       "risk-dialog", "lyrics-dialog"].map(id => ({
        id, value: getComputedStyle(document.getElementById(id),
                                   "::backdrop").backdropFilter
      }));
    return JSON.stringify({
      ok: states.every(item=>item.openCount === 1) &&
          backdropFilters.every(item=>item.value === "none") &&
          document.querySelectorAll("dialog[open]").length === 0,
      phase: "multiple-dialogs-and-backdrops",
      states, backdropFilters
    });
})()"""


def check_ready(attempt=1):
    if finished:
        return
    if time.monotonic() > deadline:
        finish(False, {"phase": "core-not-ready", "attempts": attempt})
        return
    def checked(result):
        if result.get("ok"):
            print("PASS: Qt page and core JS ready", flush=True)
            run_js(JS_OPEN, opened, "open")
        else:
            if attempt % 7 == 1:
                print("Qt startup probe: " + repr(result), flush=True)
            QTimer.singleShot(350, lambda: check_ready(attempt + 1))
    run_js(JS_READY, checked, "ready")


def opened(result):
    if not result.get("ok"):
        finish(False, result)
        return
    print("PASS: double-click opens one modal", flush=True)
    QTimer.singleShot(800, lambda: run_js(JS_PERSIST, persisted, "persist"))


def persisted(result):
    if not result.get("ok"):
        finish(False, result)
        return
    print("PASS: modal persisted across Qt paint frames", flush=True)
    run_js(JS_LIFECYCLE, lifecycle, "lifecycle")


def lifecycle(result):
    finish(bool(result.get("ok")), result)


def loaded(ok):
    print("Qt loadFinished: " + repr(ok) + " url=" +
          page.url().toString(), flush=True)
    if not ok:
        finish(False, {"phase": "webview-load", "error": "packaged page failed"})
        return
    QTimer.singleShot(300, check_ready)


page.loadFinished.connect(loaded)
QTimer.singleShot(26000, lambda: finish(False, {
    "phase": "timeout", "url": page.url().toString()
}))
view.load(QUrl.fromLocalFile(str(page_file)))
view.show()
app.exec()
if errors:
    raise SystemExit("Qt WebEngine popup smoke failed: " + "; ".join(errors))
