"""Exercise real Qt WebEngine HTML dialog lifecycle without a physical monitor.

This is a GUI smoke test on the Windows CI runner. It does not confirm
multi-monitor, Windows-focus or graphics-driver behavior on user hardware.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

if os.name != "nt":
    raise SystemExit("Windows Qt WebEngine runner required")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "") + " --disable-gpu --no-sandbox"
).strip()

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView

root = Path(__file__).resolve().parents[1]
html = root / "songstudio-plus" / "web" / "index.html"
app = QApplication([])
view = QWebEngineView()
view.resize(1280, 760)
errors = []
finished = False

def finish(ok, detail):
    global finished
    if finished:
        return
    finished = True
    print(("PASS" if ok else "FAIL") + ": Qt dialog smoke " + str(detail), flush=True)
    if not ok:
        errors.append(str(detail))
    view.close()
    app.quit()

def second(result):
    if not isinstance(result, dict) or not result.get("ok"):
        finish(False, result)
        return
    print("PASS: modal persisted through idle paint", flush=True)
    def final(result2):
        finish(bool(isinstance(result2, dict) and result2.get("ok")), result2)
    view.page().runJavaScript(r"""(() => {
      const settings=document.getElementById("settings-dialog");
      if(!settings.open)return {ok:false,phase:"settings-disappeared"};
      settings.close();
      let modalOpenCounts=[];
      for(const name of ["issues-dialog","risk-dialog","lyrics-dialog"]){
        const dialog=document.getElementById(name);
        dialog.showModal();
        if(!dialog.open)return {ok:false,phase:"open "+name};
        for(let i=0;i<16;i++)
          document.getElementById("activity-subtitle").textContent="Refresh "+i;
        if(!dialog.open)return {ok:false,phase:"repaint "+name};
        modalOpenCounts.push(document.querySelectorAll("dialog[open]").length);
        dialog.close();
        if(dialog.open)return {ok:false,phase:"close "+name};
      }
      const nativeBackdrops=["confirm-dialog","settings-dialog",
        "issues-dialog","risk-dialog","lyrics-dialog"].map(id=>{
          const dialog=document.getElementById(id);
          return getComputedStyle(dialog,"::backdrop").backdropFilter;
        });
      return {ok:modalOpenCounts.every(n=>n===1)&&
            nativeBackdrops.every(x=>x==="none")&&
            document.querySelectorAll("dialog[open]").length===0,
        modalOpenCounts,nativeBackdrops};
    })()""", final)

def first(result):
    if not isinstance(result, dict) or not result.get("ok"):
        finish(False, result)
        return
    # Keep the dialog in the native top layer across asynchronous Chromium
    # paint frames, not just in a single synchronous JS turn.
    QTimer.singleShot(650, lambda:view.page().runJavaScript(
        '({ok:document.getElementById("settings-dialog").open})',second))

def loaded(ok):
    if not ok:
        finish(False, "QWebEngine did not load bundled HTML")
        return
    def begin():
        view.page().runJavaScript(r"""(() => {
          if(!globalThis.__XSTAGE_CORE_BOUND__)
            return {ok:false,phase:"core-not-bound"};
          const button=document.getElementById("settings-open");
          button.click();button.click();
          const modal=document.getElementById("settings-dialog");
          return {ok:modal.open&&
            document.querySelectorAll("dialog[open]").length===1,
            phase:"double-click",open:modal.open};
        })()""",first)
    QTimer.singleShot(750,begin)

view.loadFinished.connect(loaded)
QTimer.singleShot(22000,lambda:finish(False,"timeout"))
view.load(QUrl.fromLocalFile(str(html)))
view.show()
app.exec()
if errors:
    raise SystemExit("Qt WebEngine popup smoke failed: " + "; ".join(errors))
