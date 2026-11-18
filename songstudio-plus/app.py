"""Local-only HTTP host for X-Stage Song Studio Plus.

Runs on loopback, never exposes filesystem or SQLite over LAN.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import secrets
import sys
import time
import threading
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import plus_core as core

class State:
    def __init__(self,workspace):
        self.workspace=Path(workspace).expanduser().resolve()
        core.init(self.workspace)
        self.jobs={}
        self.lock=threading.RLock()
        self.token=secrets.token_urlsafe(30)

    def start_job(self,kind,operation):
        job_id=secrets.token_hex(10)
        job={"id":job_id,"kind":kind,"status":"running","progress":{},
             "message":"กำลังเตรียมงาน","error":None,"result":None,
             "cancel":threading.Event(),"started_at":time.monotonic()}
        with self.lock:
            if any(x["status"]=="running" for x in self.jobs.values()):
                raise ValueError("มีงานกำลังทำอยู่ กรุณารอให้เสร็จก่อนเริ่มงานถัดไป")
            self.jobs[job_id]=job
        def runner():
            try:
                result=operation(
                    lambda summary,message:self.update(job,summary,message),
                    job["cancel"])
                with self.lock:
                    job["result"]=result
                    job["status"]="cancelled" if job["cancel"].is_set() else "completed"
                    job["message"]="ยกเลิกงานแล้ว" if job["cancel"].is_set() else "เสร็จเรียบร้อย"
            except Exception as e:
                with self.lock:
                    job["status"]="failed"
                    job["error"]=str(e)[:1200]
                    job["message"]="ดำเนินการไม่สำเร็จ"
        threading.Thread(target=runner,daemon=True,name="Plus-"+kind).start()
        return {"job":job_id}

    def update(self,job,summary,message):
        with self.lock:
            summary=dict(summary)
            elapsed=max(time.monotonic()-job["started_at"],0.001)
            items=summary.get("files_seen",summary.get("done",0))
            summary["files_per_second"]=round(items/elapsed,1)
            job["progress"]=summary
            job["message"]=str(message)[:240]

    def jobs_snapshot(self):
        with self.lock:
            return [{k:v for k,v in job.items() if k not in ("cancel","started_at")}
                    for job in list(self.jobs.values())[-10:]][::-1]

class Handler(BaseHTTPRequestHandler):
    state=None
    server_version="XStageSongStudioPlus/0.1"
    def log_message(self,format,*args):
        # Avoid printing private local paths in access logs.
        return

    def send_json(self,status,data):
        body=json.dumps(data,ensure_ascii=False,default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Security-Policy","default-src 'none'")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        if self.headers.get("Content-Type","").split(";")[0].strip()!="application/json":
            raise ValueError("ต้องส่งข้อมูลชนิด application/json")
        if self.headers.get("X-XStage-Token")!=self.state.token:
            raise PermissionError("คำขอไม่ได้รับอนุญาต")
        origin=self.headers.get("Origin")
        if origin and origin!=f"http://127.0.0.1:{self.server.server_port}":
            raise PermissionError("Origin ไม่ตรงกับโปรแกรมภายในเครื่อง")
        length=int(self.headers.get("Content-Length","0"))
        if not 0<length<=1024*1024:
            raise ValueError("ขนาดคำขอไม่ถูกต้อง")
        payload=json.loads(self.rfile.read(length))
        if not isinstance(payload,dict):
            raise ValueError("ข้อมูลคำขอไม่ถูกต้อง")
        return payload

    def do_GET(self):
        try:
            self.handle_get()
        except (ValueError,OSError,KeyError,TypeError) as e:
            self.send_json(400,{"error":str(e)})
        except Exception:
            self.send_json(500,{"error":"โปรแกรมเกิดข้อผิดพลาดที่ไม่คาดคิด"})

    def handle_get(self):
        url=urllib.parse.urlsplit(self.path)
        path=url.path
        q=urllib.parse.parse_qs(url.query)
        if path=="/api/session":
            self.send_json(200,{"token":self.state.token,"version":"0.1.4",
                                "workspace":str(self.state.workspace)})
            return
        if path=="/api/status":
            self.send_json(200,core.stats(self.state.workspace));return
        if path=="/api/jobs":
            self.send_json(200,{"jobs":self.state.jobs_snapshot()});return
        if path=="/api/import-issues":
            self.send_json(200,{"rows":core.import_issues(self.state.workspace,80)});return
        if path=="/api/songs":
            self.send_json(200,{"rows":core.songs(self.state.workspace,
                q.get("q",[""])[0],q.get("limit",[80])[0],q.get("offset",[0])[0])});return
        if path=="/api/groups":
            self.send_json(200,{"rows":core.groups(self.state.workspace,
                q.get("q",[""])[0],min(int(q.get("limit",[100])[0]),500),
                int(q.get("offset",[0])[0]))});return
        if path=="/api/lyrics":
            song_id=q.get("song_id",[""])[0]
            with core.connect(self.state.workspace) as db:
                version=db.execute("""SELECT v.* FROM xstage_lyric_versions v
                    WHERE v.song_id=? AND v.is_current=1""",(song_id,)).fetchone()
                if not version: raise ValueError("เพลงยังไม่มีเนื้อร้องที่จัดเวลาแล้ว")
                lines=core.get_version_lines(db,version["id"])
                self.send_json(200,{"version":dict(version),
                  "lines":[{"position":line["position"],"text":line["text"],
                            "start":line["start_time"],"end":line["end_time"],
                            "timing":line["timing_status"],"cues":cues}
                           for line,cues in lines]})
                return
        if path=="/api/inspect":
            name=q.get("file",[""])[0]
            output=(self.state.workspace/name).resolve()
            if (not output.is_relative_to(self.state.workspace) or
                    not output.is_file()):
                raise ValueError("ไฟล์อยู่นอกคลัง")
            self.send_json(200,core.inspect_xfile(output,False));return
        if path=="/" or path in ("/app.js","/style.css","/icon.svg") or path.startswith("/web/"):
            self.static_file("index.html" if path=="/" else path.removeprefix("/web/").removeprefix("/"))
            return
        self.send_json(404,{"error":"ไม่พบหน้าที่เรียก"})

    def static_file(self,name):
        if name not in ("index.html","app.js","style.css","icon.svg"):
            self.send_json(404,{"error":"ไม่พบไฟล์"});return
        bundle=Path(getattr(sys,"_MEIPASS",Path(__file__).parent))
        folder=bundle/"web"
        if not folder.is_dir():
            folder=Path(__file__).parent/"web"
        payload=(folder/name).read_bytes()
        kind=mimetypes.guess_type(name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type",kind+("; charset=utf-8" if kind.startswith("text/") or "javascript" in kind else ""))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'")
        self.send_header("Content-Length",str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        try:
            body=self.read_json()
            path=urllib.parse.urlsplit(self.path).path
            if path=="/api/import":
                source=body.get("folder","")
                result=self.state.start_job("import",lambda progress,cancel:
                    core.import_folder(self.state.workspace,source,progress,cancel))
            elif path=="/api/recover-lyrics":
                result=self.state.start_job("recover",lambda progress,cancel:
                    core.recover_existing_lyrics(self.state.workspace,progress,cancel))
            elif path=="/api/edit/plan":
                result=core.plan_edit(self.state.workspace,body.get("q",""),body.get("keys",[]))
            elif path=="/api/edit/apply":
                result=core.replace_groups(self.state.workspace,
                    body.get("q",""),body.get("keys",[]),
                    body.get("replacement",""),body.get("expected_lines",-1))
            elif path=="/api/edit/undo":
                result=core.undo_edit(self.state.workspace,body.get("batch",""))
            elif path=="/api/pick":
                kind=body.get("kind")
                if kind not in ("folder","lrc"):
                    raise ValueError("ประเภทการเลือกไม่ถูกต้อง")
                # A desktop dialog is explicitly invoked only on user click.
                # It cannot be accessed remotely: server binds loopback only.
                import tkinter as tk
                from tkinter import filedialog
                window=tk.Tk()
                window.withdraw()
                try:
                    window.attributes("-topmost",True)
                    if kind=="folder":
                        chosen=filedialog.askdirectory(
                            title="เลือกโฟลเดอร์เพลงต้นฉบับ",parent=window)
                    else:
                        chosen=filedialog.askopenfilename(
                            title="เลือกไฟล์เนื้อร้องที่มีเวลา",
                            filetypes=[("Timed Lyrics","*.lrc"),("ทุกไฟล์","*.*")],
                            parent=window)
                finally:
                    window.destroy()
                result={"path":chosen or ""}
            elif path=="/api/attach-lrc":
                song_id=body.get("song_id","")
                lrc_path=Path(body.get("path","")).expanduser().resolve(strict=True)
                if lrc_path.suffix.lower()!=".lrc" or lrc_path.stat().st_size>2*1024*1024:
                    raise ValueError("โปรดเลือกไฟล์ LRC แบบมีเวลาที่รองรับ")
                document=core.parse_lrc(lrc_path)
                with core.WRITE_LOCK,core.connect(self.state.workspace) as db:
                    song=db.execute("SELECT * FROM xstage_songs WHERE id=?",(song_id,)).fetchone()
                    if not song: raise ValueError("ไม่พบเพลง")
                    vid,created=core.insert_version(db,song,None,document,None,"LRC")
                result={"version":vid,"created":created,"timing_status":"estimated"}
            elif path=="/api/build":
                ids=body.get("song_ids",[])
                if (not isinstance(ids,list) or not 1<=len(ids)<=5000 or
                    any(not isinstance(x,str) for x in ids)):
                    raise ValueError("เลือกเพลง 1–5,000 เพลงต่อชุด")
                def run_build(progress,cancel):
                    total={"done":0,"built":0,"skipped":0,"failed":0,"errors":[]}
                    for song_id in dict.fromkeys(ids):
                        if cancel.is_set():break
                        try:
                            info=core.build_song(self.state.workspace,song_id)
                            total["skipped" if info["skipped"] else "built"]+=1
                        except (OSError,ValueError,TypeError) as e:
                            total["failed"]+=1
                            if len(total["errors"])<20:total["errors"].append(str(e)[:200])
                        total["done"]+=1
                        progress(dict(total),f"สร้างไฟล์ {total['done']:,}/{len(ids):,}")
                    return total
                result=self.state.start_job("build",run_build)
            elif path=="/api/job/cancel":
                job_id=body.get("job","")
                with self.state.lock:
                    job=self.state.jobs.get(job_id)
                    if not job or job["status"]!="running":
                        raise ValueError("ไม่พบงานที่ยกเลิกได้")
                    job["cancel"].set()
                result={"accepted":True}
            else:
                self.send_json(404,{"error":"ไม่พบคำสั่ง"});return
            self.send_json(200,result)
        except (ValueError,TypeError,KeyError,json.JSONDecodeError) as e:
            self.send_json(400,{"error":str(e)})
        except PermissionError as e:
            self.send_json(403,{"error":str(e)})
        except Exception:
            self.send_json(500,{"error":"คำสั่งล้มเหลว โปรดตรวจสอบรายงานโปรแกรม"})

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--workspace",default=str(Path.home()/"Documents"/"XStageSongPlus"))
    parser.add_argument("--port",type=int,default=0)
    parser.add_argument("--no-browser",action="store_true",
                        help="headless local API for automated checks")
    parser.add_argument("--browser",action="store_true",
                        help="explicitly open browser instead of Windows desktop")
    options=parser.parse_args(argv)
    state=State(options.workspace)
    handler=type("PlusHandler",(Handler,),{"state":state})
    with ThreadingHTTPServer(("127.0.0.1",options.port),handler) as server:
        url=f"http://127.0.0.1:{server.server_port}/"
        print("X-Stage Song Studio Plus",url,flush=True)
        if sys.platform=="win32" and not options.browser and not options.no_browser:
            from desktop_ui import run_desktop
            bundle=Path(getattr(sys,"_MEIPASS",Path(__file__).parent))
            icon=bundle/"app-plus.ico"
            return run_desktop(server,url,state.workspace,icon)
        if not options.no_browser:
            webbrowser.open(url)
        try:server.serve_forever(poll_interval=0.3)
        except KeyboardInterrupt:pass

if __name__=="__main__":
    main()
