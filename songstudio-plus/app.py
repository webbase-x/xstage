"""Local-only HTTP host for X-Stage Song Studio Pro.

Runs on loopback, never exposes filesystem or SQLite over LAN.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sqlite3
import subprocess
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
import db_maintenance as dbmaint
import risk_audit as risks
import preview_player as preview
import manual_editor as manual
import pro_updater as updater
import song_download as songdl
import drive_library as drivelib

class State:
    def __init__(self,workspace):
        self.workspace=Path(workspace).expanduser().resolve()
        core.init(self.workspace)
        risks.init(self.workspace)
        manual.init(self.workspace)
        self.midi_preview=preview.MidiPreview()
        self.jobs={}
        self.lock=threading.RLock()
        self.token=secrets.token_urlsafe(30)
        self.native_picker=None
        # A successful update check must be the single verified snapshot used
        # by the subsequent download. Do not query CDN/Pages a SECOND time
        # inside the worker; a transient "available=false" would abort at 0 B.
        self._verified_update=None
        self._log_lock=threading.RLock()
        self.log_path=self.workspace/"LOGS"/"song-studio-pro.log"
        self.log_path.parent.mkdir(parents=True,exist_ok=True)
        self.diagnostic("state.ready",version=updater.VERSION,
                        platform=sys.platform,frozen=bool(getattr(sys,"frozen",False)),
                        workspace=str(self.workspace))
        self.exit_requested=threading.Event()
        self._restart_prepared=False
        self.resume_info=core.interrupted_import(self.workspace)
        if self.resume_info and self.resume_info["status"]=="interrupted":
            folder=Path(self.resume_info["source_root"])
            if folder.is_dir():
                self.start_job("import",lambda progress,cancel:
                    core.import_folder(self.workspace,str(folder),progress,cancel))

    def diagnostic(self,event,**details):
        """Append a compact UTF-8 diagnostic line for startup/import analysis."""
        try:
            payload={"time":time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                     "event":str(event),**details}
            line=json.dumps(payload,ensure_ascii=False,default=str)
            with self._log_lock:
                if self.log_path.is_file() and self.log_path.stat().st_size>5*1024*1024:
                    old=self.log_path.with_suffix(".previous.log")
                    old.unlink(missing_ok=True)
                    self.log_path.replace(old)
                with self.log_path.open("a",encoding="utf-8") as stream:
                    stream.write(line+"\n")
        except Exception:
            pass

    def check_latest_update(self):
        try:
            verified=updater.check()
        except (OSError,ValueError,KeyError,TypeError) as exc:
            with self.lock:
                cached=dict(self._verified_update) if self._verified_update else None
            if cached and cached.get("newer"):
                self.diagnostic("update.check.cached",version=cached["version"],
                                cause=str(exc)[:250])
                return {**cached,"used_previous_verification":True}
            raise
        with self.lock:
            cached=self._verified_update
            if (cached and cached.get("newer") and
                    updater.version_tuple(cached["version"])>
                    updater.version_tuple(verified["version"])):
                selected=dict(cached)
            else:
                self._verified_update=dict(verified)
                selected=dict(verified)
        self.diagnostic("update.check.verified",version=selected["version"],
                        source=selected.get("feed","official-release"))
        return selected

    def download_target(self):
        with self.lock:
            target=dict(self._verified_update) if self._verified_update else None
        if not target:
            target=self.check_latest_update()
        if not target.get("newer"):
            raise ValueError("ใช้งาน Song Studio Pro รุ่นล่าสุดอยู่แล้ว")
        return target

    def start_job(self,kind,operation):
        job_id=secrets.token_hex(10)
        self.diagnostic("job.start",kind=kind,job=job_id)
        job={"id":job_id,"kind":kind,"status":"running","progress":{},
             "message":"กำลังเตรียมงาน","error":None,"result":None,
             "cancel":threading.Event(),"started_at":time.monotonic(),
             "updated_at":time.time(),"revision":0}
        with self.lock:
            running=[x for x in self.jobs.values() if x["status"]=="running"]
            if running and kind=="update" and all(x["kind"]!="update" for x in running):
                # Update downloads touch UPDATES, not SQLite. Installation
                # requests a checkpoint before closing the old program.
                pass
            elif running:
                raise ValueError("มีงานกำลังทำอยู่ กรุณารอให้เสร็จก่อนเริ่มงานถัดไป")
            # Keep active work and only the latest finished jobs. A studio
            # that stays open for weeks must not retain unbounded job/results
            # (including large error summaries) in memory.
            finished=[key for key,item in self.jobs.items()
                      if item["status"]!="running"]
            for key in finished[:-40]:
                del self.jobs[key]
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
                    job["updated_at"]=time.time()
                    job["revision"]=int(job.get("revision",0))+1
                self.diagnostic("job.finish",kind=kind,job=job_id,status=job["status"])
            except Exception as e:
                with self.lock:
                    job["status"]="cancelled" if job["cancel"].is_set() else "failed"
                    job["error"]=str(e)[:1200]
                    job["message"]=("ยกเลิกและคืนค่าแล้ว" if job["cancel"].is_set()
                       else ("ดาวน์โหลด/ตรวจ SHA-256 ไม่สำเร็จ: "+str(e)[:320]
                             if kind=="update" else "ดำเนินการไม่สำเร็จ: "+str(e)[:320]))
                    job["updated_at"]=time.time()
                    job["revision"]=int(job.get("revision",0))+1
                self.diagnostic("job.error",kind=kind,job=job_id,
                                status=job["status"],error=str(e)[:1200])
        threading.Thread(target=runner,daemon=True,name="Plus-"+kind).start()
        return {"job":job_id}

    def update(self,job,summary,message):
        with self.lock:
            summary=dict(summary)
            # Resumed imports already contain counters from earlier sessions.
            # Subtract the first reported counter so throughput reflects only
            # work done in THIS process, never a fictitious 80k files/second.
            moment=time.monotonic()
            items=summary.get("files_seen",summary.get("done",0))
            if not isinstance(items,(int,float)):
                items=0
            if "_rate_first_count" not in job:
                job["_rate_first_count"]=items
                job["_rate_first_at"]=moment
            elapsed=max(moment-job["_rate_first_at"],0.001)
            summary["files_per_second"]=round(
                max(0,items-job["_rate_first_count"])/elapsed,1)
            job["progress"]=summary
            job["message"]=str(message)[:240]
            job["updated_at"]=time.time()
            job["revision"]=int(job.get("revision",0))+1
            # Persist occasional factual import progress to the local log,
            # but never write on every source file or SQLite transaction.
            log_progress=(job.get("kind")=="import" and
                          moment-job.get("_progress_logged_at",-1e9)>=20)
            if log_progress:
                job["_progress_logged_at"]=moment
        if log_progress:
            self.diagnostic("job.progress",kind="import",job=job.get("id"),
                            files_seen=summary.get("files_seen",0),
                            files_new=summary.get("files_new",0),
                            media_duplicates=summary.get("media_duplicates",0),
                            resumed_files=summary.get("resumed_files",0),
                            failures=summary.get("failures",0),
                            source=str(message)[:180])

    def jobs_snapshot(self):
        now_epoch=time.time()
        with self.lock:
            rows=[]
            for job in list(self.jobs.values())[-10:][::-1]:
                item={k:v for k,v in job.items() if k not in (
                    "cancel","started_at","_rate_first_count","_rate_first_at","_progress_logged_at")}
                item["progress_age"]=round(max(0.0,now_epoch-float(job.get("updated_at",now_epoch))),3)
                rows.append(item)
            return rows
    def request_restart(self):
        with self.lock:
            for job in self.jobs.values():
                if job["status"]=="running": job["cancel"].set()
            self.exit_requested.set()
    def ready_to_exit(self):
        with self.lock:
            ready=self.exit_requested.is_set() and not any(
                j["status"]=="running" for j in self.jobs.values())
            if not ready or self._restart_prepared:
                return ready
            self._restart_prepared=True
            interrupted=[j for j in self.jobs.values()
                         if j["kind"]=="import" and j["status"]=="cancelled"
                         and isinstance(j.get("result"),dict) and
                         j["result"].get("batch")]
        # A deliberate updater restart may resume this exact import. This
        # executes only after the import runner has committed all checkpoints.
        try:
            for job in interrupted:
                core.prepare_import_for_restart(
                    self.workspace,job["result"]["batch"])
        except (OSError,sqlite3.DatabaseError):
            # Keep the old process alive until its resume state is durable.
            with self.lock:self._restart_prepared=False
            return False
        return True

class Handler(BaseHTTPRequestHandler):
    state=None
    server_version="XStageSongStudioPro/0.1"
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
            self.send_json(200,{"token":self.state.token,"version":updater.VERSION,
                                "workspace":str(self.state.workspace)})
            return
        if path=="/api/status":
            self.send_json(200,core.stats(self.state.workspace));return
        if path=="/api/db/health":
            self.send_json(200,dbmaint.snapshot(self.state.workspace));return
        if path=="/api/import/resume":
            self.send_json(200,{"resume":self.state.resume_info});return
        if path=="/api/update/check":
            self.send_json(200,self.state.check_latest_update());return
        if path=="/api/update/ready":
            ready=updater.ready_file(self.state.workspace)
            self.send_json(200,{"ready":bool(ready),
                                "version":ready["version"] if ready else None});return
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
        if path=="/api/manual/queue":
            self.send_json(200,manual.queue(self.state.workspace,
                q.get("q",[""])[0],q.get("filter",["pending"])[0],
                q.get("offset",[0])[0],q.get("limit",[6])[0]));return
        if path=="/api/manual/detail":
            self.send_json(200,manual.detail(
                self.state.workspace,q.get("song_id",[""])[0]));return
        if path=="/api/build/catalog":
            self.send_json(200,manual.build_catalog(self.state.workspace,
                q.get("status",["ready"])[0],
                q.get("offset",[0])[0],q.get("limit",[40])[0],
                q.get("q",[""])[0]));return
        if path=="/api/build/catalog-count":
            # The count covers every song in persistent SQLite, regardless
            # of approval, lyric completeness or prior conversion.
            self.send_json(200,{"total":core.catalog_song_count(
                self.state.workspace)});return
        if path=="/api/build/eligible":
            self.send_json(200,{"ready_total":manual.ready_count(
                self.state.workspace)});return
        if path=="/api/songs":
            rows=core.songs(self.state.workspace,
                q.get("q",[""])[0],q.get("limit",[80])[0],q.get("offset",[0])[0])
            self.send_json(200,{"rows":manual.annotate_rows(
                self.state.workspace,rows)});return
        if path=="/api/lyrics/search-context":
            self.send_json(200,core.search_context(
                self.state.workspace,q.get("q",[""])[0],
                int(q.get("limit",[12])[0])));return
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
                               "timing":line["timing_status"],
                               "cues":core.display_cues(line["text"],cues)}
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
        if name not in ("index.html","app.js","style.css","icon.svg",
                        "timeline-core.js","timeline-ui.js"):
            self.send_json(404,{"error":"ไม่พบไฟล์"});return
        bundle=Path(getattr(sys,"_MEIPASS",Path(__file__).parent))
        folder=bundle/"web"
        if not folder.is_dir():
            folder=Path(__file__).parent/"web"
        try:
            payload=(folder/name).read_bytes()
            if name in ("index.html","app.js","timeline-core.js","timeline-ui.js"):
                self.state.diagnostic("asset.served",name=name,bytes=len(payload))
        except OSError as exc:
            self.state.diagnostic("asset.error",name=name,error=str(exc)[:1000])
            raise
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
            if path=="/api/drive/check":
                result=drivelib.describe(body.get("folder",""))
            elif path=="/api/import":
                source=body.get("folder","")
                self.state.diagnostic("import.request",folder=source,
                                      exists=Path(source).is_dir() if isinstance(source,str) else False)
                result=self.state.start_job("import",lambda progress,cancel:
                    core.import_folder(self.state.workspace,source,progress,cancel))
            elif path=="/api/import/google-drive":
                root=drivelib.resolve_root(body.get("folder",""))
                self.state.diagnostic("import.google-drive.request",root=str(root))
                result=self.state.start_job("drive-import",lambda progress,cancel:
                    drivelib.download_and_import(self.state.workspace,root,progress,cancel))
            elif path=="/api/import/file":
                raw=body.get("file","")
                if not isinstance(raw,str) or not raw.strip():
                    raise ValueError("กรุณาเลือกไฟล์เพลงบนเครื่อง")
                target=Path(raw.strip()).expanduser().resolve(strict=True)
                self.state.diagnostic("import.single.request",
                                      extension=target.suffix.lower())
                result=self.state.start_job("import",lambda progress,cancel:
                    core.import_folder(self.state.workspace,str(target.parent),
                                       progress,cancel,selected_file=str(target)))
            elif path=="/api/import/download":
                url=body.get("url","")
                if not isinstance(url,str):
                    raise ValueError("กรุณาระบุลิงก์ไฟล์เพลง HTTPS")
                # Reject private or non-HTTPS destinations BEFORE starting a
                # job; redirects are validated again in the download worker.
                songdl.validate_remote_url(url)
                self.state.diagnostic("import.direct.download.request")
                result=self.state.start_job("song-download",
                    lambda progress,cancel:songdl.download_and_import(
                        self.state.workspace,url,progress,cancel))
            elif path=="/api/update/download":
                # Freeze the same release that /api/update/check verified;
                # NEVER refetch a changing manifest after the user clicks.
                target=self.state.download_target()
                self.state.diagnostic("update.download.selected",
                                      version=target["version"],
                                      source=target.get("feed","verified"),
                                      sha256=target["sha256"][:16])
                result=self.state.start_job("update",lambda progress,cancel:
                    updater.download(self.state.workspace,target,progress,cancel))
            elif path=="/api/update/install":
                result=updater.install_and_restart(self.state.workspace)
                self.state.request_restart()
            elif path=="/api/db/audit":
                result=self.state.start_job("db-audit",lambda progress,cancel:
                    dbmaint.detailed_audit(self.state.workspace,progress,cancel))
            elif path=="/api/db/cleanup":
                result=self.state.start_job("db-clean",lambda progress,cancel:
                    dbmaint.cleanup_history(self.state.workspace,progress,cancel))
            elif path=="/api/db/compact":
                result=self.state.start_job("db-compact",lambda progress,cancel:
                    dbmaint.compact_database(self.state.workspace,progress,cancel))
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
                query=body.get("q","")
                keys=body.get("keys",[])
                replacement=body.get("replacement","")
                expected=body.get("expected_lines",-1)
                if (not isinstance(keys,list) or not 1<=len(keys)<=1000 or
                        any(not isinstance(k,str) for k in keys)):
                    raise ValueError("กรุณาเลือกกลุ่มข้อความที่ต้องการแก้")
                result=self.state.start_job("lyrics-edit",lambda progress,cancel:
                    core.replace_groups(self.state.workspace,query,keys,
                                        replacement,expected,progress,cancel))
            elif path=="/api/edit/undo":
                result=core.undo_edit(self.state.workspace,body.get("batch",""))
            elif path=="/api/pick":
                kind=body.get("kind")
                if kind not in ("folder","lrc","media"):
                    raise ValueError("ประเภทการเลือกไม่ถูกต้อง")
                if not self.state.native_picker:
                    self.state.diagnostic("picker.unavailable",kind=kind)
                    raise ValueError("Windows Picker ยังไม่พร้อม กรุณาเปิด Log วิเคราะห์")
                self.state.diagnostic("picker.request",kind=kind,
                                      current=body.get("current",""))
                try:
                    result=self.state.native_picker(kind,body.get("current",""))
                except Exception as exc:
                    self.state.diagnostic("picker.exception",kind=kind,error=str(exc)[:1000])
                    raise
            elif path=="/api/diagnostic":
                event=str(body.get("event","ui.event"))[:80]
                detail=body.get("detail",{})
                if not isinstance(detail,dict): detail={"value":str(detail)[:500]}
                safe={str(k)[:80]:str(v)[:800] for k,v in list(detail.items())[:20]}
                self.state.diagnostic(event,**safe)
                result={"logged":True}
            elif path=="/api/open-log":
                self.state.log_path.touch(exist_ok=True)
                if sys.platform!="win32":
                    raise ValueError("เปิด Log อัตโนมัติได้เฉพาะ Windows")
                subprocess.Popen(["notepad.exe",str(self.state.log_path)],
                    creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0),
                    close_fds=True)
                self.state.diagnostic("log.opened",source="api")
                result={"opened":True,"path":str(self.state.log_path)}
            elif path=="/api/songs/remove":
                if any(job.get("status") in ("running","queued")
                       for job in self.state.jobs_snapshot()):
                    raise ValueError("มีงานกำลังประมวลผล ไม่สามารถลบรายการขณะนี้")
                result=core.hide_song(self.state.workspace,body.get("song_id",""))
                self.state.diagnostic("library.song.hidden",
                                      song_id=result["song_id"],code=result["code"])
            elif path=="/api/workspace/select":
                if any(job.get("status") in ("running", "queued") for job in self.state.jobs_snapshot()):
                    raise ValueError("มีงานกำลังทำงานอยู่ กรุณารอให้เสร็จก่อนเปลี่ยนคลัง")
                supplied=body.get("folder")
                if not isinstance(supplied,str) or not supplied.strip():
                    raise ValueError("กรุณาเลือกโฟลเดอร์คลังเพลง")
                target=save_workspace_preference(supplied.strip())
                self.state.diagnostic("workspace.preference.saved",
                                      new_workspace=str(target))
                result={"workspace":str(target),"restart_required":True,
                        "has_database":(target/"DB"/"xstage_plus.sqlite3").is_file()}
            elif path=="/api/open-folder":
                scope=body.get("scope")
                if scope=="workspace":
                    folder=self.state.workspace
                elif scope=="source":
                    supplied=body.get("path")
                    if not isinstance(supplied,str) or not supplied.strip():
                        raise ValueError("กรุณาเลือกหรือพิมพ์โฟลเดอร์ก่อน")
                    folder=Path(supplied.strip()).expanduser()
                else:
                    raise ValueError("ประเภทโฟลเดอร์ไม่ถูกต้อง")
                if not folder.is_dir():
                    raise ValueError("ไม่พบโฟลเดอร์นี้ กรุณาตรวจสอบพาธหรือไดรฟ์")
                if sys.platform!="win32":
                    raise ValueError("เปิด Explorer ได้เฉพาะ Windows")
                os.startfile(str(folder.resolve()))
                result={"opened":True,"folder":str(folder.resolve())}
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
            elif path=="/api/manual/save":
                result=manual.save(self.state.workspace,
                    body.get("song_id",""),body.get("version_id"),
                    body.get("lines"))
            elif path=="/api/manual/skip":
                result=manual.skip(self.state.workspace,
                    body.get("song_id",""),body.get("version_id"))
            elif path=="/api/manual/approve":
                result=manual.approve(self.state.workspace,
                    body.get("song_id",""),body.get("version_id"))
            elif path=="/api/build":
                all_catalog=body.get("all_catalog") is True
                all_ready=body.get("all_ready") is True
                if all_catalog and all_ready:
                    raise ValueError("เลือกได้เพียงโหมดสร้างทั้งฐานหรือเฉพาะที่พร้อม")
                excluded=body.get("excluded",[])
                ids=body.get("song_ids",[])
                if all_catalog:
                    if "song_ids" in body or "excluded" in body:
                        raise ValueError("โหมดสร้างทั้งหมดต้องอ่านรายการจากฐานข้อมูลโดยตรง")
                    total_songs=core.catalog_song_count(self.state.workspace)
                    if not total_songs:
                        raise ValueError("ยังไม่มีเพลงในฐานข้อมูล SQLite")
                elif all_ready:
                    if not isinstance(excluded,list) or len(excluded)>500000 or any(
                            not isinstance(x,str) for x in excluded):
                        raise ValueError("รายการยกเว้นไม่ถูกต้อง")
                    ids=manual.approved_build_ids(self.state.workspace,excluded)
                else:
                    if (not isinstance(ids,list) or not 1<=len(ids)<=5000 or
                            any(not isinstance(x,str) for x in ids)):
                        raise ValueError("เลือกเพลง 1–5,000 เพลงต่อชุด")
                    # Do not materialize the whole ready catalog for a handful
                    # of selected songs. All-ready IDs are already SQL-approved.
                    eligible=manual.approved_selected_ids(self.state.workspace,ids)
                    if any(song_id not in eligible for song_id in ids):
                        raise ValueError("มีเพลงที่ยังไม่พร้อมสร้างหรือยังรอการยืนยัน กรุณาตรวจและปาดเนื้อร้องก่อน")
                # Explicit selections are de-duplicated. Whole-database mode
                # iterates the registry in bounded SQLite batches and attempts
                # every track, not just reviewed/timed ones.
                if not all_catalog:
                    ids=list(dict.fromkeys(ids))
                def run_build(progress,cancel):
                    expected=total_songs if all_catalog else len(ids)
                    total={"done":0,"total":expected,"built":0,"skipped":0,
                           "duplicate_mid":0,"blocked":0,"failed":0,"errors":[]}
                    progress(dict(total),f"เริ่มตรวจและสร้างไฟล์ 0/{expected:,} เพลง")
                    catalog=(core.catalog_song_ids(self.state.workspace)
                             if all_catalog else iter(ids))
                    for song_id in catalog:
                        if cancel.is_set():break
                        try:
                            info=core.build_song(self.state.workspace,song_id)
                            total["skipped" if info["skipped"] else "built"]+=1
                            if info.get("duplicate_mid"):
                                total["duplicate_mid"]+=1
                        except ValueError as e:
                            reason=str(e)
                            if ("ยังไม่มีเนื้อร้องพร้อมเวลา" in reason or
                                "CUR ยังไม่ครบ" in reason):
                                total["blocked"]+=1
                            else:
                                total["failed"]+=1
                            if len(total["errors"])<50:
                                total["errors"].append(song_id[:20]+" · "+reason[:200])
                        except (OSError,TypeError) as e:
                            total["failed"]+=1
                            if len(total["errors"])<50:
                                total["errors"].append(song_id[:20]+" · "+str(e)[:200])
                        total["done"]+=1
                        progress(dict(total),
                            f"ตรวจทั้งฐาน {total['done']:,}/{expected:,} · "
                            f"สร้าง {total['built']:,} · ข้ามซ้ำ {total['skipped']:,} "
                            f"(MID ซ้ำ {total['duplicate_mid']:,}) · "
                            f"ข้อมูลไม่ครบ {total['blocked']:,} · ผิดพลาด {total['failed']:,}")
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
        except PermissionError as e:
            self.send_json(403,{"error":str(e)})
        except (ValueError,TypeError,KeyError,OSError,TimeoutError,
                RuntimeError,json.JSONDecodeError) as e:
            self.send_json(400,{"error":str(e)})
        except Exception:
            self.send_json(500,{"error":"คำสั่งล้มเหลว โปรดตรวจสอบรายงานโปรแกรม"})

def _registered_windows_documents():
    """Use the Windows Documents known location, including OneDrive redirection.

    The folder can have a Thai (or any Unicode) name. Do not encode it with
    an ANSI code page or assume it is \\Users\\name\\Documents.
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg
        key = (r"Software\Microsoft\Windows\CurrentVersion\Explorer"
               r"\User Shell Folders")
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as entry:
            location, _ = winreg.QueryValueEx(entry, "Personal")
        return Path(os.path.expandvars(location)).expanduser()
    except (OSError, ValueError, ImportError, TypeError):
        return None


def _registered_windows_music():
    """Resolve the Windows Music known folder, including OneDrive redirection."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
        key = (r"Software\\Microsoft\\Windows\\CurrentVersion\\Explorer"
               r"\\User Shell Folders")
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as entry:
            location, _ = winreg.QueryValueEx(entry, "My Music")
        return Path(os.path.expandvars(location)).expanduser()
    except (OSError, ValueError, ImportError, TypeError):
        return None


def workspace_candidates(*, home=None, env=None, platform=None, documents=None,
                         music=None):
    """Use Music/XStageSongPlus for new Windows libraries, retaining old DBs.

    The user can override this default with --workspace. Existing SQLite
    libraries take priority over a fresh Music directory so no songs vanish
    after upgrading. Never move or delete the old workspace automatically.
    """
    home = Path.home() if home is None else Path(home)
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    if documents is None and platform == "win32":
        documents = _registered_windows_documents()
    if music is None and platform == "win32":
        music = _registered_windows_music()
    candidates = []
    def add(path):
        if path is None:
            return
        path = Path(path).expanduser()
        if path not in candidates:
            candidates.append(path)

    legacy = []
    for parent in (documents, home / "Documents"):
        if parent is not None:
            legacy.append(Path(parent) / "XStageSongPlus")
    if platform == "win32":
        for key in ("LOCALAPPDATA", "APPDATA"):
            base = env.get(key)
            if base and Path(base).is_dir():
                legacy.append(Path(base) / "XStageSongPlus")
        if home.is_dir():
            legacy.append(home / "XStageSongPlus")
    else:
        legacy.append(home / "Documents" / "XStageSongPlus")

    # Respect an existing catalog wherever it was previously created.
    for old in legacy:
        if (old / "DB" / "xstage_plus.sqlite3").is_file():
            add(old)

    if platform == "win32":
        music_folder = Path(music) if music is not None else home / "Music"
        add(music_folder / "XStageSongPlus")
    else:
        add(home / "Music" / "XStageSongPlus")

    # A legacy non-database directory is only a last-resort fallback.
    for old in legacy:
        if old.parent.is_dir():
            add(old)
    return candidates


def workspace_preference_path(*, home=None, env=None):
    """User-specific launcher setting, independent of song workspace."""
    home = Path.home() if home is None else Path(home)
    env = os.environ if env is None else env
    root = Path(env.get("LOCALAPPDATA") or home / ".config")
    return root / "XStageSongStudioPro" / "settings.json"


def chosen_workspace(*, home=None, env=None):
    path = workspace_preference_path(home=home, env=env)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = data.get("workspace")
        if isinstance(value, str) and value.strip():
            return Path(value).expanduser()
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None


def save_workspace_preference(folder):
    target = Path(folder).expanduser().resolve(strict=True)
    if not target.is_dir():
        raise ValueError("กรุณาเลือกโฟลเดอร์ที่มีอยู่จริง")
    # Do not create an empty database now. Changing workspace takes effect
    # after restart, when the engine opens the selected existing/new catalog.
    pref = workspace_preference_path()
    pref.parent.mkdir(parents=True, exist_ok=True)
    temp = pref.with_suffix(".tmp")
    try:
        temp.write_text(json.dumps({"workspace": str(target)},
                                   ensure_ascii=False), encoding="utf-8")
        temp.replace(pref)
    finally:
        temp.unlink(missing_ok=True)
    return target


def _startup_failure(message):
    """A GUI error instead of a PyInstaller 'Unhandled exception in script'."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None, str(message), "X-Stage Song Studio Pro", 0x10)
            return
        except (OSError, AttributeError):
            pass
    print(message, file=sys.stderr)


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--workspace",default=None,
                        help="explicit SQLite workspace; do not relocate it")

    parser.add_argument("--port",type=int,default=0)
    parser.add_argument("--no-browser",action="store_true",
                        help="headless local API for automated checks")
    parser.add_argument("--browser",action="store_true",
                        help="troubleshooting only: open UI in the Windows default browser")
    options=parser.parse_args(argv)
    choices = ([Path(options.workspace)] if options.workspace is not None
               else ([chosen_workspace()] if chosen_workspace() is not None
                     else workspace_candidates()))
    state = None
    failures = []
    for choice in choices:
        try:
            state = State(choice)
            break
        except (OSError, sqlite3.Error) as exc:
            failures.append(f"{choice}: {exc}")
            # If this workspace already holds a database, never silently
            # switch to a fresh empty library on another path.
            if options.workspace is not None or (choice/"DB"/"xstage_plus.sqlite3").is_file():
                break
    if state is None:
        details = "\n".join(failures[-3:]) or "No usable local user-data folder"
        _startup_failure(
            "ไม่สามารถเปิดฐานข้อมูล X-Stage Song Studio Pro ได้\n"
            "โปรดตรวจสอบตำแหน่งโฟลเดอร์และสิทธิ์การเขียน\n"
            "สามารถระบุพาธอื่นด้วย --workspace\n\n" + details)
        return 1
    if sys.platform=="win32":
        try:
            import windows_picker
            state.native_picker=lambda kind,current="":windows_picker.pick(
                kind,current,state.diagnostic)
            state.diagnostic("picker.backend.ready",backend="WindowsForms-PowerShell-STA")
        except Exception as exc:
            state.diagnostic("picker.backend.error",error=str(exc)[:1000])
    handler=type("PlusHandler",(Handler,),{"state":state})
    with ThreadingHTTPServer(("127.0.0.1",options.port),handler) as server:
        url=f"http://127.0.0.1:{server.server_port}/"
        print("X-Stage Song Studio Pro",url,flush=True)
        if sys.platform=="win32" and not options.no_browser:
            bundle=Path(getattr(sys,"_MEIPASS",Path(__file__).parent))
            icon=bundle/"app-plus.ico"
            if options.browser:
                from desktop_ui import run_browser_host
                state.diagnostic("ui.mode",mode="windows-default-browser-troubleshooting")
                return run_browser_host(server,url,state.workspace,icon,state)
            from desktop_ui import run_desktop
            state.diagnostic("ui.mode",mode="desktop-standalone-qtwebengine")
            return run_desktop(server,url,state.workspace,icon,state)
        if not options.no_browser:
            state.diagnostic("ui.mode",mode="system-browser")
            webbrowser.open(url)
        def quit_when_installed():
            while not state.exit_requested.wait(0.3):pass
            while not state.ready_to_exit():
                time.sleep(.2)
            server.shutdown()
        threading.Thread(target=quit_when_installed,daemon=True,
                         name="studio-pro-update-shutdown").start()
        try:server.serve_forever(poll_interval=0.3)
        except KeyboardInterrupt:pass

if __name__=="__main__":
    main()
