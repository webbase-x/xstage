"""X-Stage Song Studio PC Source Launcher — local-only Python engine.
Standard-library-only HTTP server. Source and output remain on this computer.
This is a source preview, not the unrecovered original v0.2.5 Build 205 engine.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UI_ROOT = ROOT / "studio"
DATA = ROOT / "data"
RUNTIME = ROOT / ".runtime"
DATA.mkdir(exist_ok=True)
EXT_AUDIO = {".mp3", ".m4a", ".mp4", ".aac", ".wav", ".wma", ".flac", ".ogg", ".oga"}
EXT_MIDI = {".mid", ".midi", ".kar"}
EXT_UNSUPPORTED = {".ncn"}
PREFS_FILE = DATA / "preferences.json"
NOTES_FILE = DATA / "song-metadata.json"
LOCK = threading.RLock()
TOKEN = secrets.token_urlsafe(40)
PORT = None
JOB = {
    "id": "", "kind": "", "state": "idle", "stage": "พร้อมใช้งาน",
    "detail": "", "completed": 0, "total": 0, "elapsed": 0,
    "eta": None, "idleFor": 0, "logs": [], "result": {}
}
CANCEL = threading.Event()
PROCESS = None
FILES = []
FILE_BY_ID = {}
PREVIEWS = {}
PREVIEW_FOLDER = Path(tempfile.mkdtemp(prefix="xstage-song-preview-"))
ALLOWED_ORIGIN = "https://webbase-x.github.io"

def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default

def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)

HOME_MUSIC = Path.home() / "Music"
PREFS = {
    "source": str(HOME_MUSIC),
    "workspace": str(HOME_MUSIC / "X-Stage-Song-Studio"),
    "download": str(Path.home() / "Downloads"),
    "soundfont": "", "midi_preset": "balanced", "mode": "original", "oauth": ""
}
PREFS.update({k: v for k, v in load_json(PREFS_FILE, {}).items() if k in PREFS and isinstance(v, str)})
NOTES = load_json(NOTES_FILE, {})

def ffmpeg_binary():
    names = [RUNTIME / "tools" / "ffmpeg.exe", RUNTIME / "tools" / "ffmpeg", Path("ffmpeg.exe")]
    for file in names:
        if file.exists():
            return str(file.resolve())
    return shutil.which("ffmpeg")

def fluidsynth_binary():
    return shutil.which("fluidsynth")

def sf_available():
    return bool(PREFS["soundfont"]) and Path(PREFS["soundfont"]).is_file()

def formats():
    return [
        {"value": "balanced", "label": "สมดุล"},
        {"value": "warm", "label": "อบอุ่น"},
        {"value": "bright", "label": "สว่าง"}
    ]

def font_list():
    choice = PREFS.get("soundfont", "")
    return [choice] if choice and Path(choice).is_file() else []

def scan_source():
    source = Path(PREFS["source"]).expanduser()
    if not source.is_dir():
        raise ValueError("โฟลเดอร์ต้นฉบับไม่มีอยู่ กรุณาเลือกโฟลเดอร์ก่อนสแกน")
    rows = []
    index = 1
    for base, dirs, files in os.walk(source, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(base) / d).is_symlink())
        for name in sorted(files):
            path = Path(base) / name
            ext = path.suffix.lower()
            if ext not in (EXT_AUDIO | EXT_MIDI | EXT_UNSUPPORTED) or path.is_symlink():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            data = NOTES.get(str(path), {})
            rows.append({
                "id": index, "path": str(path), "title": data.get("title") or path.stem,
                "artist": data.get("artist", ""),
                "code": path.stem, "kind": ext[1:].upper(),
                "size": stat.st_size, "status": "ready" if ext not in EXT_UNSUPPORTED else "unsupported",
                "lyrics_edit": data.get("lyrics", "")
            })
            index += 1
            if index > 100000:
                raise ValueError("พบเพลงเกิน 100,000 รายการ กรุณาเลือกโฟลเดอร์ย่อย")
    with LOCK:
        FILES[:] = rows
        FILE_BY_ID.clear()
        FILE_BY_ID.update((x["id"], x) for x in rows)
    return len(rows)

def visible_files(search=""):
    with LOCK:
        rows = list(FILES)
    query = search.casefold()
    if query:
        rows = [row for row in rows if query in
                (row["title"] + " " + row["artist"] + " " + row["code"]).casefold()]
    return rows

def log(line):
    with LOCK:
        JOB["logs"].append(str(line))
        JOB["logs"][:] = JOB["logs"][-100:]
        JOB["detail"] = str(line)
        JOB["updated"] = time.monotonic()

def update(stage, done=None):
    with LOCK:
        JOB["stage"] = stage
        if done is not None:
            JOB["completed"] = done
        JOB["updated"] = time.monotonic()

def run_process(args):
    global PROCESS
    if not ffmpeg_binary():
        raise RuntimeError("ไม่พบ FFmpeg กรุณาเปิด Start-Song-Studio.cmd เพื่อติดตั้งเครื่องมือ")
    opts = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
            "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        opts["creationflags"] = subprocess.CREATE_NO_WINDOW
    with subprocess.Popen(args, **opts) as proc:
        with LOCK:
            PROCESS = proc
        try:
            _, stderr = proc.communicate()
            if CANCEL.is_set():
                raise RuntimeError("ผู้ใช้ยกเลิกงาน")
            if proc.returncode:
                msg = stderr.decode("utf-8", errors="replace")[-800:]
                raise RuntimeError("FFmpeg ไม่สำเร็จ: " + msg)
        finally:
            with LOCK:
                PROCESS = None

def unique_target(folder, base, suffix):
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (base + suffix)
    n = 1
    while target.exists():
        target = folder / (base + f" ({n})" + suffix)
        n += 1
        if n > 1000:
            raise RuntimeError("ชื่อไฟล์ซ้ำเกินขีดจำกัด")
    return target

def safe_stem(name):
    return "".join("_" if c in '<>:"/\\|?*\0' else c for c in name).strip(". ")[:130] or "song"

def lyrics_text(row):
    note = NOTES.get(row["path"], {}).get("lyrics", "")
    if note:
        return note
    source = Path(row["path"])
    try:
        return source.with_suffix(".lrc").read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return ""

def ensure_midi_wav(path):
    if not sf_available():
        raise RuntimeError("การสร้าง MIDI/KAR ต้องเลือก SoundFont SF2/SF3 ก่อน")
    fluid = fluidsynth_binary()
    if not fluid:
        raise RuntimeError("ไม่พบ FluidSynth สำหรับสร้างเสียง MIDI/KAR; ฟังก์ชันนี้ยังไม่พร้อมใช้งานในชุดซอร์ส")
    tmp = PREVIEW_FOLDER / (secrets.token_hex(10) + ".wav")
    params = [fluid, "-ni", PREFS["soundfont"], str(path), "-F", str(tmp), "-r", "44100"]
    run_process(params)
    return tmp

def convert(row, target, preview=False):
    path = Path(row["path"])
    midi = path.suffix.lower() in EXT_MIDI
    temp_wav = None
    try:
        if midi:
            temp_wav = ensure_midi_wav(path)
        inp = temp_wav or path
        cmd = [ffmpeg_binary(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
               "-i", str(inp)]
        if preview:
            cmd += ["-t", "60"]
        cmd += ["-vn", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(target)]
        run_process(cmd)
        if not target.is_file() or target.stat().st_size < 1000:
            raise RuntimeError("ไฟล์เสียงผลลัพธ์ไม่สมบูรณ์")
    finally:
        if temp_wav:
            temp_wav.unlink(missing_ok=True)

def execute_job(action, options, started):
    try:
        if action == "scan":
            update("กำลังสแกนไฟล์เพลง")
            amount = scan_source()
            log(f"ตรวจพบ {amount:,} เพลง")
            result = {"message": f"สแกนเสร็จแล้ว {amount:,} เพลง"}
        elif action in ("build", "preview"):
            ids = options.get("ids", [])
            if not isinstance(ids, list):
                raise ValueError("รายการเพลงไม่ถูกต้อง")
            with LOCK:
                rows = [dict(FILE_BY_ID[i]) for i in ids if isinstance(i, int) and i in FILE_BY_ID]
            if not rows:
                raise ValueError("กรุณาเลือกเพลงก่อนสร้าง")
            if action == "preview" and len(rows) != 1:
                raise ValueError("การทดลองฟังต้องเลือกหนึ่งเพลง")
            with LOCK:
                JOB["total"] = len(rows)
            update("กำลังเตรียมเพลงที่เลือก")
            workspace = Path(PREFS["workspace"]).expanduser() / "song"
            failed = 0
            result = {"message": ""}
            for idx, row in enumerate(rows):
                if CANCEL.is_set():
                    raise RuntimeError("ผู้ใช้ยกเลิกงาน")
                source = Path(row["path"])
                if not source.is_file():
                    failed += 1
                    log(f"ไม่พบต้นฉบับ: {source.name}")
                    update("กำลังดำเนินการ", idx + 1)
                    continue
                update(f"กำลังสร้าง {idx + 1}/{len(rows)}: {row['title']}")
                base = safe_stem(row["title"])
                if action == "preview":
                    dest = PREVIEW_FOLDER / (secrets.token_hex(16) + ".m4a")
                else:
                    dest = unique_target(workspace, base, ".m4a")
                try:
                    if not (action == "preview") and source.suffix.lower() == ".m4a":
                        shutil.copy2(source, dest)
                    else:
                        convert(row, dest, preview=action == "preview")
                    if action == "preview":
                        ticket = secrets.token_urlsafe(24)
                        with LOCK:
                            PREVIEWS[ticket] = (dest, time.time() + 300)
                            result["ticket"] = ticket
                    elif not options.get("audio_only", False):
                        lyrics = lyrics_text(row)
                        if lyrics.strip():
                            dest.with_suffix(".lrc").write_text(lyrics, encoding="utf-8")
                    log(f"เสร็จ: {row['title']}")
                except Exception as exc:
                    failed += 1
                    log(f"ไม่สำเร็จ {row['title']}: {exc}")
                    dest.unlink(missing_ok=True)
                update("กำลังดำเนินการ", idx + 1)
            if failed == len(rows):
                raise RuntimeError("เพลงทั้งหมดดำเนินการไม่สำเร็จ ตรวจรายละเอียดงาน")
            result["message"] = f"สร้างสำเร็จ {len(rows) - failed}/{len(rows)} เพลง ({workspace})"
        elif action == "check-update":
            result = {"message": "ยังไม่มีไฟล์ติดตั้ง Windows ที่ผ่านการตรวจสอบสำหรับ Source Launcher นี้"}
            update("ตรวจเวอร์ชันเสร็จแล้ว", 1)
        else:
            raise RuntimeError(
                "ฟังก์ชัน Google Drive / AI แบบออฟไลน์ยังไม่มีในชุด PC Source Launcher นี้ "
                "และไม่ได้อ้างว่าเทียบเท่า v0.2.5 Build 205"
            )
        with LOCK:
            JOB.update(state="success", result=result, stage="เสร็จสิ้น",
                       detail=result.get("message", "เสร็จแล้ว"))
    except Exception as exc:
        with LOCK:
            JOB["state"] = "cancelled" if CANCEL.is_set() else "error"
            JOB["stage"] = "ยกเลิกงาน" if CANCEL.is_set() else "เกิดข้อผิดพลาด"
        log(str(exc))
    finally:
        with LOCK:
            JOB["elapsed"] = time.monotonic() - started
            JOB["updated"] = time.monotonic()

def start_job(data):
    global JOB
    action = str(data.get("action", ""))
    with LOCK:
        if JOB["state"] == "running":
            raise ValueError("มีงานกำลังดำเนินการอยู่")
        CANCEL.clear()
        JOB = {
            "id": secrets.token_hex(8), "kind": action, "state": "running",
            "stage": "เตรียมงาน", "detail": "กำลังเริ่มต้น",
            "completed": 0, "total": 0, "elapsed": 0, "eta": None,
            "idleFor": 0, "logs": [], "result": {},
            "started": time.monotonic(), "updated": time.monotonic()
        }
        result = JOB["id"]
    thread = threading.Thread(target=execute_job, args=(action, data, time.monotonic()), daemon=True)
    thread.start()
    return {"id": result}

def open_picker(kind):
    if os.name != "nt":
        return ""
    if kind in ("source", "workspace", "download"):
        command = ("Add-Type -AssemblyName System.Windows.Forms; "
                   "$d=New-Object System.Windows.Forms.FolderBrowserDialog; "
                   "if($d.ShowDialog() -eq 'OK'){$d.SelectedPath}")
    else:
        command = ("Add-Type -AssemblyName System.Windows.Forms; "
                   "$d=New-Object System.Windows.Forms.OpenFileDialog; "
                   "$d.Filter='Files|*.sf2;*.sf3;*.json|All files|*.*'; "
                   "if($d.ShowDialog() -eq 'OK'){$d.FileName}")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", command],
                          capture_output=True, text=True, timeout=120, creationflags=flags)
    return proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""

def job_snapshot():
    with LOCK:
        job = dict(JOB)
    if job["state"] == "running":
        elapsed = max(0, time.monotonic() - job["started"])
        job["elapsed"] = elapsed
        job["idleFor"] = round(time.monotonic() - job["updated"])
        if job["completed"] > 0:
            job["eta"] = (elapsed / job["completed"]) * (job["total"] - job["completed"])
    job.pop("updated", None)
    job.pop("started", None)
    return job

class Handler(BaseHTTPRequestHandler):
    server_version = "XStageStudioPCSource/0.1"
    def log_message(self, fmt, *args):
        return

    def _origin(self):
        return self.headers.get("Origin", "")

    def _allowed(self):
        return self._origin() in ("", f"http://127.0.0.1:{PORT}", ALLOWED_ORIGIN)

    def _auth(self):
        return self.headers.get("X-XStage-Token", "") == TOKEN

    def _response(self, code, data=b"", content_type="application/json; charset=utf-8",
                  cors=False):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "cross-origin" if cors else "same-origin")
        if cors and self._origin() == ALLOWED_ORIGIN:
            self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-XStage-Token")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code=200, cors=True):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._response(code, raw, cors=cors)

    def _deny(self, msg="Access denied", code=403):
        self._json({"error": msg}, code)

    def _host_ok(self):
        try:
            host = self.headers.get("Host", "")
            return host in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")
        except ValueError:
            return False

    def do_OPTIONS(self):
        if not self._host_ok() or not self._allowed():
            self._deny()
            return
        self._response(204, b"", cors=True)

    def do_GET(self):
        if not self._host_ok() or not self._allowed():
            self._deny()
            return
        u = urllib.parse.urlsplit(self.path)
        path = u.path
        query = urllib.parse.parse_qs(u.query)
        if path.startswith("/api/"):
            if path == "/api/preview":
                ticket = query.get("ticket", [""])[0]
                with LOCK:
                    v = PREVIEWS.get(ticket)
                if not v or v[1] < time.time() or not v[0].is_file():
                    self._deny("ไม่พบไฟล์ทดลองฟังหรือหมดอายุ", 404)
                    return
                self._response(200, v[0].read_bytes(), "audio/mp4", cors=True)
                return
            if not self._auth():
                self._deny()
                return
            if path == "/api/status":
                self._json({"version": "0.2.5-Source-Preview", "build": "205-SRC",
                    "job": job_snapshot(), "preferences": dict(PREFS),
                    "soundfonts": font_list(), "presets": formats(),
                    "google": {"connected": False, "email": ""},
                    "update": {"status": "unavailable"}})
            elif path == "/api/environment":
                self._json({"Python Runtime": True, "FFmpeg": bool(ffmpeg_binary()),
                    "SoundFont": sf_available(), "FluidSynth": bool(fluidsynth_binary()),
                    "Local file mode": True,
                    "Google Drive connector": False,
                    "AI separation": False})
            elif path == "/api/songs/ids":
                self._json({"ids": [x["id"] for x in visible_files(query.get("search", [""])[0])]})
            elif path == "/api/songs":
                rows = visible_files(query.get("search", [""])[0])
                limit = max(1, min(500, int(query.get("limit", ["100"])[0])))
                offset = max(0, int(query.get("offset", ["0"])[0]))
                self._json({"rows": rows[offset:offset + limit], "total": len(rows)})
            elif path.startswith("/api/song/"):
                row = FILE_BY_ID.get(int(path.rsplit("/", 1)[-1]))
                if row is None:
                    self._deny("ไม่พบเพลง", 404)
                else:
                    self._json({**row, "lyrics_edit": lyrics_text(row)})
            else:
                self._deny("ไม่พบ API", 404)
            return
        if path in ("/", "/index.html"):
            path = "/index.html"
        if path not in ("/index.html", "/app.js", "/style.css", "/entry.js"):
            self._response(404, b"Not found", "text/plain")
            return
        target = UI_ROOT / path[1:]
        if not target.is_file():
            self._response(404, b"UI bundle missing", "text/plain")
            return
        mimetype = {".html": "text/html; charset=utf-8",
                    ".js": "text/javascript; charset=utf-8",
                    ".css": "text/css; charset=utf-8"}[target.suffix]
        self._response(200, target.read_bytes(), mimetype)

    def do_POST(self):
        if not self._host_ok() or not self._allowed() or not self._auth():
            self._deny()
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1048576 or length <= 0:
            self._deny("ขนาดคำสั่งไม่ถูกต้อง", 413)
            return
        try:
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("คำสั่งไม่ถูกต้อง")
            path = urllib.parse.urlsplit(self.path).path
            if path == "/api/config":
                for key, value in payload.items():
                    if key in PREFS and isinstance(value, str):
                        PREFS[key] = value[:2048]
                save_json(PREFS_FILE, PREFS)
                self._json({"preferences": dict(PREFS), "soundfonts": font_list()})
            elif path == "/api/folder-picker":
                kind = payload.get("kind", "")
                if kind not in ("source", "workspace", "download", "soundfont", "oauth"):
                    raise ValueError("ประเภทไฟล์ไม่ถูกต้อง")
                self._json({"path": open_picker(kind)})
            elif path == "/api/estimate":
                ids = payload.get("ids", [])
                if not isinstance(ids, list):
                    raise ValueError("รายการเพลงไม่ถูกต้อง")
                matches = [FILE_BY_ID[i] for i in ids if isinstance(i, int) and i in FILE_BY_ID]
                size = sum(r["size"] for r in matches)
                workspace = Path(PREFS["workspace"]).expanduser()
                workspace.mkdir(parents=True, exist_ok=True)
                free = shutil.disk_usage(workspace).free
                self._json({"songs": len(matches), "bytes": size, "enoughDisk": free > size * 3,
                            "warning": len(matches) > 200 or size > 2 * 1024 ** 3})
            elif path == "/api/jobs":
                self._json(start_job(payload))
            elif path == "/api/jobs/cancel":
                CANCEL.set()
                with LOCK:
                    p = PROCESS
                if p:
                    p.terminate()
                self._json({"ok": True})
            elif path.startswith("/api/song/"):
                row = FILE_BY_ID.get(int(path.rsplit("/", 1)[-1]))
                if not row:
                    raise ValueError("ไม่พบเพลง")
                value = NOTES.setdefault(row["path"], {})
                for key in ("title", "artist", "lyrics"):
                    if isinstance(payload.get(key), str):
                        value[key] = payload[key][:100000]
                row["title"] = value.get("title", row["title"])
                row["artist"] = value.get("artist", row["artist"])
                save_json(NOTES_FILE, NOTES)
                self._json({"ok": True})
            elif path == "/api/open-browser":
                webbrowser.open(f"{ALLOWED_ORIGIN}/xstage/studio/#engine=" +
                    urllib.parse.quote(f"http://127.0.0.1:{PORT}/", safe="") +
                    "&auth=" + urllib.parse.quote(TOKEN, safe=""))
                self._json({"ok": True})
            else:
                self._deny("ไม่พบ API", 404)
        except (ValueError, OSError, TypeError, subprocess.TimeoutExpired) as exc:
            self._json({"error": str(exc)}, 400)
        except Exception as exc:
            self._json({"error": "เกิดข้อผิดพลาด: " + str(exc)}, 500)

def main():
    global PORT
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        PORT = server.server_port
        url = f"http://127.0.0.1:{PORT}/#auth={TOKEN}"
        # Open a standalone application window when Edge is installed;
        # fall back to the system's default browser otherwise.
        edge = Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe"
        if not edge.is_file():
            edge = Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe"
        try:
            if edge.is_file():
                subprocess.Popen([str(edge), "--app=" + url], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            else:
                webbrowser.open(url)
        except Exception:
            webbrowser.open(url)
        server.serve_forever(poll_interval=0.25)

if __name__ == "__main__":
    main()
