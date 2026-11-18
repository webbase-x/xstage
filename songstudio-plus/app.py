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
import risk_audit as risks
import preview_player as preview

class State:
    def __init__(self,workspace):
        self.workspace=Path(workspace).expanduser().resolve()
        core.init(self.workspace)
        risks.init(self.workspace)
        self.midi_preview=preview.MidiPreview()
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
        except PermissionError as e:
            self.send_json(403,{"error":str(e)})
        except (ValueError,OSError,KeyError,TypeError) as e:
            self.send_json(400,{"error":str(e)})
        except Exception:
            self.send_json(500,{"error":"โปรแกรมเกิดข้อผิดพลาดที่ไม่คาดคิด"})

    def handle_get(self):
        url=urllib.parse.urlsplit(self.path)
        path=url.path
        q=urllib.parse.parse_qs(url.query)
        if path=="/api/session":
            self.send_json(200,{"token":self.state.token,"version":"0.1.5",
                                "workspace":str(self.state.workspace)})
            return
        if path=="/api/status":
            self.send_json(200,core.stats(self.state.workspace));return
        if path=="/api/jobs":
            self.send_json(200,{"jobs":self.state.jobs_snapshot()});return
        if path=="/api/import-issues":
            self.send_json(200,{"rows":core.import_issues(self.state.workspace,80)});return
        if path=="/api/swipe-risks":
            self.send_json(200,risks.list_findings(
                self.state.workspace,q.get("category",["structural"])[0],
                int(q.get("limit",[100])[0]),int(q.get("offset",[0])[0])));return
        if path=="/api/swipe-history":
            self.send_json(200,risks.history(self.state.workspace));return
        if path=="/api/preview":
            self.send_json(200,preview.preview_details(
                self.state.workspace,q.get("song_id",[""])[0]));return
        if path=="/api/preview/midi/status":
            self.send_json(200,self.state.midi_preview.state());return
        if path=="/api/preview/media":
            if q.get("token",[""])[0]!=self.state.token:
                raise PermissionError("ไม่มีสิทธิ์อ่านไฟล์เพลง")
            self.stream_preview_media(q.get("song_id",[""])[0]);return
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
                draft=db.execute("""SELECT * FROM xstage_lyric_drafts
                    WHERE song_id=?""",(song_id,)).fetchone()
                if not version and not draft:
                    raise ValueError("ไม่พบเนื้อร้องของเพลงนี้ใน SQLite")
                if version:
                    lines=core.get_version_lines(db,version["id"])
                    payload={"version":dict(version),
                     "lines":[{"position":line["position"],"text":line["text"],
                               "start":line["start_time"],"end":line["end_time"],
                               "timing":line["timing_status"],"cues":cues}
                              for line,cues in lines]}
                else:
                    payload={"version":{"timing_status":"untimed","title":draft["title"],
                                        "artist":draft["artist"]},
                     "lines":[{"position":i,"text":line,"start":None,"end":None,
                               "timing":"untimed","cues":[]}
                              for i,line in enumerate(draft["raw_text"].splitlines()) if line.strip()]}
                if draft:
                    payload["draft"]={"text":draft["raw_text"],
                                      "reason":draft["reason"]}
                self.send_json(200,payload)
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

    def stream_preview_media(self,song_id):
        """Protected source-media GET with proper HTTP Range for HTML seek.

        Always resolve from the registered SQLite media ID, never a user-supplied
        filename; the original remains untouched and no media copy is created.
        """
        info,source=preview.source_info(self.state.workspace,song_id)
        ext=source.suffix.lower()
        if ext not in preview.AUDIO_EXT:
            raise ValueError("ไฟล์นี้ต้องใช้ MIDI Synthesizer ไม่ใช่ HTML Media")
        types={
            ".mp3":"audio/mpeg",".m4a":"audio/mp4",".wav":"audio/wav",
            ".flac":"audio/flac",".mp4":"video/mp4",
            ".webm":"video/webm",".mkv":"video/x-matroska",
            ".mov":"video/quicktime"
        }
        size=source.stat().st_size
        if size<=0:raise ValueError("ไฟล์เพลงต้นฉบับว่าง")
        incoming=self.headers.get("Range")
        status=200
        start=0
        stop=size-1
        if incoming:
            import re
            matched=re.fullmatch(r"bytes=(\d*)-(\d*)",incoming.strip())
            if not matched or not any(matched.groups()):
                self.send_response(416)
                self.send_header("Content-Range",f"bytes */{size}")
                self.send_header("Content-Length","0")
                self.end_headers()
                return
            first,last=matched.groups()
            if not first:
                suffix=min(size,int(last))
                start=size-suffix
            else:
                start=int(first)
                if last:stop=min(stop,int(last))
            if start>stop or start>=size:
                self.send_response(416)
                self.send_header("Content-Range",f"bytes */{size}")
                self.send_header("Content-Length","0")
                self.end_headers()
                return
            status=206
        self.send_response(status)
        self.send_header("Content-Type",types[ext])
        self.send_header("Accept-Ranges","bytes")
        self.send_header("Cache-Control","no-store")
        self.send_header("Cross-Origin-Resource-Policy","same-origin")
        self.send_header("X-Content-Type-Options","nosniff")
        if status==206:
            self.send_header("Content-Range",f"bytes {start}-{stop}/{size}")
        self.send_header("Content-Length",str(stop-start+1))
        self.end_headers()
        try:
            with source.open("rb") as media:
                media.seek(start)
                remaining=stop-start+1
                while remaining>0:
                    block=media.read(min(1024*1024,remaining))
                    if not block:break
                    self.wfile.write(block)
                    remaining-=len(block)
        except (BrokenPipeError,ConnectionResetError):
            # HTML media readers cancel older Range requests while seeking.
            return

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
            elif path=="/api/swipe/scan":
                result=self.state.start_job("swipe-audit",lambda progress,cancel:
                    risks.scan(self.state.workspace,progress,cancel))
            elif path=="/api/swipe/review":
                result=risks.review(self.state.workspace,
                    body.get("song_id",""),body.get("version_id",""),
                    body.get("action",""),body.get("note",""))
            elif path=="/api/swipe/open-source":
                result=risks.open_original(self.state.workspace,
                    body.get("song_id",""),body.get("version_id",""))
            elif path=="/api/preview/midi/play":
                result=self.state.midi_preview.play(
                    self.state.workspace,body.get("song_id",""),body.get("seek",0))
            elif path=="/api/preview/midi/pause":
                result=self.state.midi_preview.pause()
            elif path=="/api/preview/midi/stop":
                self.state.midi_preview.stop()
                result={"stopped":True}
            elif path=="/api/preview/review":
                result=risks.review(self.state.workspace,
                    body.get("song_id",""),body.get("version_id",""),
                    body.get("action",""),body.get("note",""))
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
