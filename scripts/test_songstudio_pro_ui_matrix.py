"""Exercise every Song Studio menu at common small/large Qt WebEngine viewports.

Runs in real Windows Qt WebEngine software rendering, without relying on
static HTML screenshots. It checks navigation wiring and per-view horizontal
containment. Physical HDMI, audio, MIDI devices and native file dialogs are
covered separately or require hardware QA.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

if os.name != "nt":
    raise SystemExit("Windows runner required")

os.environ["QT_QPA_PLATFORM"]="offscreen"
os.environ["QT_OPENGL"]="software"
os.environ["QT_QUICK_BACKEND"]="software"
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]=(
    os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS","")
    +" --use-gl=angle --use-angle=swiftshader"
    +" --enable-unsafe-swiftshader --disable-gpu-sandbox --no-sandbox"
).strip()

from PySide6.QtCore import QTimer,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/"dist"/"songstudio-viewport-evidence"
EVIDENCE.mkdir(parents=True,exist_ok=True)
SIZES=[(390,680),(600,800),(768,720),(900,720),
       (1024,768),(1366,768),(1920,1080),(2560,1440)]
MENUS=["import","drive","lyrics","media","preview","manual",
       "build","library","risks"]
app=QApplication([])
web=QWebEngineView()
web.resize(*SIZES[0])
completed=False
results=[]
failures=[]

def finish(message=None):
    global completed
    if completed:
        return
    completed=True
    if message:
        failures.append(str(message))
    EVIDENCE.joinpath("layout-results.json").write_text(
        json.dumps({"viewports":results,"failures":failures},
                   ensure_ascii=False,indent=2),encoding="utf-8")
    for row in results:
        print(("PASS" if row["ok"] else "FAIL")+": Qt viewport "+
              str(row["width"])+"x"+str(row["height"])+
              " menus="+str(row["menus"])+" "+repr(row["issues"][:3]),
              flush=True)
    if failures:
        print("FAILURES: "+repr(failures[-10:]),flush=True)
    else:
        print("PASS: all 9 menus across 8 Qt viewport dimensions",flush=True)
    web.close()
    app.quit()

def probe(idx):
    if completed:
        return
    if idx>=len(SIZES):
        finish()
        return
    width,height=SIZES[idx]
    web.resize(width,height)
    QTimer.singleShot(170,lambda:check(idx,width,height))

def check(idx,width,height):
    js=r"""(() => {
      const menus=["import","drive","lyrics","media","preview","manual",
                   "build","library","risks"];
      const issues=[];
      let visibleCount=0;
      for(const name of menus){
        const nav=document.querySelector('[data-view="'+name+'"]');
        const panel=document.getElementById("view-"+name);
        if(!nav||!panel){issues.push(name+":missing");continue;}
        nav.click();
        const displayed=[...document.querySelectorAll(".view.is-visible")];
        if(!panel.classList.contains("is-visible") ||
            displayed.length!==1 || displayed[0]!==panel){
          issues.push(name+":navigation-not-exclusive");
          continue;
        }
        visibleCount++;
        for(const [tag,node] of [
          ["app",document.querySelector(".app")],
          ["main",document.querySelector(".main")],
          ["content",document.querySelector(".content")],
          ["view-"+name,panel]]){
          if(node && node.clientWidth>0 && node.scrollWidth-node.clientWidth>7)
            issues.push(name+":"+tag+"-horizontal-overflow:"+
                        (node.scrollWidth-node.clientWidth));
        }
      }
      const topbar=document.querySelector(".topbar");
      // The CHOOSE SONGS panel and three status tabs were intentionally
      // retired. Validate the new build action surface rather than
      // expecting old tabs to remain visible.
      const buildPanel=document.getElementById("view-build");
      const legacySelection=buildPanel.querySelector(".build-selection-internal");
      const hasHiddenLegacy=legacySelection &&
        (legacySelection.hidden || getComputedStyle(legacySelection).display==="none");
      if(!hasHiddenLegacy)issues.push("build-legacy-song-selection-visible");
      if([...buildPanel.querySelectorAll(".build-status-tabs button")]
          .some(button=>button.getClientRects().length))
        issues.push("build-retired-status-tabs-visible");
      if([...buildPanel.querySelectorAll("#build-all,#build-page-all,#build-clear,#build-page-clear")]
          .some(button=>button.getClientRects().length))
        issues.push("build-retired-selection-buttons-visible");
      const all=buildPanel.querySelector("#build-everything");
      const ready=buildPanel.querySelector("#build-ready-all");
      const visibleAction=button=>Boolean(button)&&
        button.getClientRects().length>0 &&
        getComputedStyle(button).visibility!=="hidden";
      if(!visibleAction(all)||!visibleAction(ready))
        issues.push("build-main-actions-not-visible");
      const drive=document.getElementById("view-drive");
      if(!drive||!drive.querySelector("#drive-browse")||
         !drive.querySelector("#drive-check")||
         !drive.querySelector("#drive-download"))
        issues.push("drive-missing-import-controls");
      const source=document.getElementById("source-folder");
      const direct=document.getElementById("song-download-url");
      const single=document.getElementById("single-media-file");
      if(!source||!direct||!single)issues.push("missing-import-download-controls");
      document.querySelector('[data-view="import"]').click();
      const viewport={width:innerWidth,height:innerHeight};
      return JSON.stringify({ok:issues.length===0 && visibleCount===menus.length,
        menus:visibleCount,issues,viewport,
        importScrollHeight:document.getElementById("view-import").scrollHeight,
        importClientHeight:document.getElementById("view-import").clientHeight,
        topbarHeight:Math.round(topbar.getBoundingClientRect().height)});
    })()"""
    def got(raw):
        try:
            item=json.loads(raw) if isinstance(raw,str) else None
        except ValueError:
            item=None
        if not item:
            finish("Qt JS returned no viewport results for "+str((width,height)))
            return
        ok=bool(item.get("ok"))
        reported=item.get("viewport",{})
        if abs(reported.get("width",0)-width)>3:
            item.setdefault("issues",[]).append("Qt viewport did not resize")
            ok=False
        entry={"width":width,"height":height,"ok":ok,
               "menus":item.get("menus",0),
               "issues":item.get("issues",[]),
               "importScrollHeight":item.get("importScrollHeight"),
               "importClientHeight":item.get("importClientHeight"),
               "topbarHeight":item.get("topbarHeight")}
        results.append(entry)
        if not ok:
            failures.append(str(width)+"x"+str(height)+" "+repr(entry["issues"]))
        try:
            screenshot=EVIDENCE/(str(width)+"x"+str(height)+".png")
            web.grab().save(str(screenshot),"PNG")
        except Exception as exc:
            print("Qt screenshot warning: "+str(exc),flush=True)
        QTimer.singleShot(90,lambda:probe(idx+1))
    web.page().runJavaScript(js,got)

def check_ready(attempt=0):
    if completed:
        return
    def read(raw):
        if raw is True:
            probe(0)
        elif attempt>=32:
            finish("App JavaScript did not bind on Qt WebEngine")
        else:
            QTimer.singleShot(250,lambda:check_ready(attempt+1))
    web.page().runJavaScript("Boolean(globalThis.__XSTAGE_CORE_BOUND__)",read)

def loaded(ok):
    if not ok:
        finish("HTML failed to load in Qt WebEngine")
    else:
        QTimer.singleShot(250,check_ready)

web.loadFinished.connect(loaded)
QTimer.singleShot(52000,lambda:finish("Qt viewport test timeout"))
web.load(QUrl.fromLocalFile(str(ROOT/"songstudio-plus"/"web"/"index.html")))
web.show()
app.exec()
if failures:
    raise SystemExit("Viewport/navigation regression: "+repr(failures[-8:]))
