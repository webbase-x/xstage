"""X-Stage Song Studio PC Source Launcher — local-only Python engine.
Standard-library-only HTTP server. Source and output remain on this computer.
This is a source preview, not the unrecovered original v0.2.5 Build 205 engine.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import importlib.util
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
if not UI_ROOT.is_dir() and (ROOT.parent / "studio").is_dir():
    UI_ROOT = ROOT.parent / "studio"  # Repo test layout; packaged ZIP uses ROOT/studio.
DATA = ROOT / "data"
RUNTIME = ROOT / ".runtime"
READY_BUNDLE = (ROOT / ".engine-ready-manifest.json").is_file()
STATUS_VERSION = "0.3.4" if READY_BUNDLE else "0.2.5-Source-Preview"
STATUS_BUILD = "304" if READY_BUNDLE else "205-SRC"
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
LIVE_TICKETS = {}
LIVE_LIMIT = threading.BoundedSemaphore(2)
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
DEFAULT_SOUNDFONT = RUNTIME / "soundfonts" / "GeneralUser-GS.sf2"
if DEFAULT_SOUNDFONT.is_file() and not Path(PREFS.get("soundfont", "")).is_file():
    PREFS["soundfont"] = str(DEFAULT_SOUNDFONT)


def ffmpeg_binary():
    names = [RUNTIME / "tools" / "ffmpeg.exe", RUNTIME / "tools" / "ffmpeg", Path("ffmpeg.exe")]
    for file in names:
        if file.exists():
            return str(file.resolve())
    return shutil.which("ffmpeg")

def fluidsynth_binary():
    base = RUNTIME / "fluidsynth"
    preferred = base / "bin" / "fluidsynth.exe"
    if preferred.is_file():
        return str(preferred)
    if base.is_dir():
        for entry in base.rglob("fluidsynth.exe"):
            if entry.is_file():
                return str(entry)
    return shutil.which("fluidsynth")

def ai_available():
    """Ready if all built artifacts exist; fail safely when missing."""
    model = RUNTIME / "models" / "htdemucs_fp16weights.onnx"
    script = ROOT / "ai_separate.py"
    libs = RUNTIME / "ai-site"
    return (model.is_file() and model.stat().st_size > 100_000_000
            and script.is_file() and (libs / "numpy").is_dir()
            and (libs / "onnxruntime").is_dir()
            and (RUNTIME / "python" / "python.exe").is_file())


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
    fonts = [choice] if choice and Path(choice).is_file() else []
    if DEFAULT_SOUNDFONT.is_file() and str(DEFAULT_SOUNDFONT) not in fonts:
        fonts.append(str(DEFAULT_SOUNDFONT))
    return fonts

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
        raise RuntimeError("ไม่พบ FFmpeg ในโฟลเดอร์โปรแกรม กรุณาแตกไฟล์ Ready ZIP ทั้งชุดใหม่")
    opts = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
            "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        opts["creationflags"] = subprocess.CREATE_NO_WINDOW
        exe = Path(str(args[0]))
        if exe.name.lower() == "fluidsynth.exe":
            env = os.environ.copy()
            env["PATH"] = str(exe.parent) + os.pathsep + env.get("PATH", "")
            opts["env"] = env
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
        raise RuntimeError("ไม่พบ FluidSynth ในโฟลเดอร์โปรแกรม กรุณาใช้ Ready ZIP ที่รวมไลบรารีครบ")
    tmp = PREVIEW_FOLDER / (secrets.token_hex(10) + ".wav")
    # FluidSynth CLI expects flags before positional SoundFont/MIDI arguments.
    params = [fluid, "-ni", "-F", str(tmp), "-r", "44100", PREFS["soundfont"], str(path)]
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

def separate_ai(row, target, preview=False):
    """Split a song offline; output karaoke M4A and optional vocals M4A.

    Uses locally bundled FFmpeg + ONNX Runtime + HTDemucs model. Progress
    and cancellation are supplied by the subprocess; no song data leaves PC.
    Returns path to the separate vocals M4A (or None for preview).
    """
    global PROCESS
    if not ai_available():
        raise RuntimeError(
            "AI Separation ไม่พร้อม: ไม่พบโมเดล HTDemucs หรือไลบรารีใน ZIP "
            "กรุณาใช้ PC Ready Build 303 ที่รวม AI ทั้งชุด"
        )
    source = Path(row["path"])
    if source.suffix.lower() in EXT_UNSUPPORTED:
        raise RuntimeError("ยังไม่รองรับ NCN สำหรับ AI separation")
    with tempfile.TemporaryDirectory(prefix="xstage-ai-", dir=str(PREVIEW_FOLDER)) as temp:
        folder = Path(temp)
        prepared = folder / "input.wav"
        instrumental = folder / "instrumental.wav"
        vocals = folder / "vocals.wav"
        midi_wav = None
        try:
            if source.suffix.lower() in EXT_MIDI:
                update("FluidSynth: กำลังสังเคราะห์ MIDI ก่อนแยกเสียง")
                midi_wav = ensure_midi_wav(source)
            update("AI ขั้น 1/4 · เตรียมเสียง PCM 44.1 kHz stereo")
            ffargs = [ffmpeg_binary(), "-hide_banner", "-loglevel", "error", "-y",
                      "-nostdin", "-i", str(midi_wav or source)]
            if preview:
                ffargs += ["-t", "60"]
            ffargs += ["-vn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(prepared)]
            run_process(ffargs)
        finally:
            if midi_wav is not None:
                midi_wav.unlink(missing_ok=True)
        if CANCEL.is_set():
            raise RuntimeError("ผู้ใช้ยกเลิกงาน")

        python = RUNTIME / "python" / "python.exe"
        cmd = [str(python), "-u", str(ROOT / "ai_separate.py"),
               str(prepared), str(instrumental), str(vocals)]
        opts = dict(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                    errors="replace", bufsize=1)
        if os.name == "nt":
            opts["creationflags"] = subprocess.CREATE_NO_WINDOW
        update("AI ขั้น 2/4 · กำลังโหลดโมเดล HTDemucs")
        output_lines = []
        with subprocess.Popen(cmd, **opts) as proc:
            with LOCK:
                PROCESS = proc
            try:
                for line in proc.stdout:
                    item = line.strip()
                    if not item:
                        continue
                    output_lines.append(item)
                    output_lines[:] = output_lines[-30:]
                    if item.startswith("AI_PROGRESS "):
                        fraction = item.split(" ", 2)[1]
                        update("AI ขั้น 2/4 · แยกเสียง " + fraction + " ช่วง")
                        with LOCK:
                            JOB["detail"] = "ประมวลผลบน CPU · " + fraction + " ช่วง"
                            JOB["updated"] = time.monotonic()
                    elif item.startswith("AI_STAGE "):
                        update("AI ขั้น 2/4 · " + item.removeprefix("AI_STAGE "))
                    elif item.startswith("AI_ERROR "):
                        log(item)
                returncode = proc.wait()
                if CANCEL.is_set():
                    raise RuntimeError("ผู้ใช้ยกเลิกงาน")
                if returncode:
                    raise RuntimeError(
                        "AI separation ไม่สำเร็จ (code " + str(returncode) + "): " +
                        " | ".join(output_lines[-5:])
                    )
            finally:
                with LOCK:
                    PROCESS = None
        if not instrumental.is_file() or not vocals.is_file():
            raise RuntimeError("AI separation ไม่คืนไฟล์เสียงทั้งสองส่วน")
        update("AI ขั้น 3/4 · เข้ารหัส M4A ดนตรี")
        run_process([ffmpeg_binary(), "-hide_banner", "-loglevel", "error", "-nostdin",
                     "-y", "-i", str(instrumental), "-c:a", "aac", "-b:a", "192k",
                     "-movflags", "+faststart", str(target)])
        if not target.is_file() or target.stat().st_size < 1000:
            raise RuntimeError("ไฟล์ AI Instrumental M4A ไม่สมบูรณ์")
        if preview:
            return None
        update("AI ขั้น 4/4 · เข้ารหัส M4A เสียงร้องแยก")
        stem = target.with_name(target.stem + " - vocals.m4a")
        if stem.exists():
            stem = unique_target(target.parent, target.stem + " - vocals", ".m4a")
        try:
            run_process([ffmpeg_binary(), "-hide_banner", "-loglevel", "error", "-nostdin",
                         "-y", "-i", str(vocals), "-c:a", "aac", "-b:a", "192k",
                         "-movflags", "+faststart", str(stem)])
        except Exception:
            stem.unlink(missing_ok=True)
            raise
        if not stem.is_file() or stem.stat().st_size < 1000:
            stem.unlink(missing_ok=True)
            raise RuntimeError("ไฟล์ AI Vocals M4A ไม่สมบูรณ์")
        return stem


def execute_job(action, options, started):
    try:
        if action == "scan":
            update("กำลังสแกนไฟล์เพลง")
            amount = scan_source()
            log(f"ตรวจพบ {amount:,} เพลง")
            result = {"message": f"สแกนเสร็จแล้ว {amount:,} เพลง"}
        elif action in ("build", "preview"):
            # Snapshot mode for the entire job, so UI changes cannot alter
            # individual songs in the middle of a batch.
            mode = PREFS.get("mode", "original")
            if mode not in ("original", "instrumental"):
                raise ValueError("ประเภทเสียงไม่ถูกต้อง")
            if mode == "instrumental" and not ai_available():
                raise RuntimeError(
                    "AI Separation ไม่พร้อม: โมเดลหรือไลบรารีไม่ครบ "
                    "กรุณาใช้ PC Ready Build 303"
                )
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
                    if mode == "instrumental":
                        vocal_path = separate_ai(row, dest, preview=action == "preview")
                        if vocal_path is not None:
                            log("บันทึกเสียงร้องแยก: " + vocal_path.name)
                    elif not (action == "preview") and source.suffix.lower() == ".m4a":
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
                 "ฟังก์ชัน Google Drive ยังไม่มีในชุด PC Source Launcher นี้ "
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
    """Show an actual Windows foreground picker; preserve Unicode/Thai paths.

    A hidden PowerShell host alone can leave FolderBrowserDialog behind
    Microsoft Edge. The bundled PS script supplies a top-most dialog owner,
    and base64-encoded UTF-8 stdout avoids Windows console encoding damage.
    """
    if kind not in ("source", "workspace", "download", "soundfont", "oauth"):
        raise ValueError("ประเภทหน้าต่างเลือกโฟลเดอร์/ไฟล์ไม่ถูกต้อง")
    if os.name != "nt":
        raise RuntimeError("หน้าต่างเลือกโฟลเดอร์แบบ PC รองรับเฉพาะ Windows")
    picker = ROOT / "pick_path.ps1"
    if not picker.is_file():
        raise RuntimeError("ไม่พบ pick_path.ps1 กรุณาแตกไฟล์ ZIP รุ่นใหม่ให้ครบก่อน")
    initial = str(PREFS.get(kind) or "")
    args = [
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-STA", "-File", str(picker), "-Kind", kind,
        "-InitialPath", initial
    ]
    try:
        result = subprocess.run(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL, timeout=180,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "หน้าต่างเลือกโฟลเดอร์ไม่ตอบสนองเกิน 3 นาที "
            "โปรดลองเปิดใหม่ หรือพิมพ์พาธในช่องได้โดยตรง"
        ) from exc
    except OSError as exc:
        raise RuntimeError("ไม่สามารถเปิดตัวเลือกโฟลเดอร์ Windows: " + str(exc)) from exc
    stdout = result.stdout.decode("ascii", errors="replace").strip().splitlines()
    line = next((item.strip() for item in reversed(stdout)
                 if item.strip() == "CANCELLED" or item.startswith("PICKED:")), "")
    if result.returncode:
        err = result.stderr.decode("utf-8", errors="replace").strip()[-700:]
        raise RuntimeError("หน้าต่างเลือกโฟลเดอร์เปิดไม่สำเร็จ: " +
                           (err or f"PowerShell exited with code {result.returncode}"))
    if line == "CANCELLED":
        return ""
    if not line.startswith("PICKED:"):
        raise RuntimeError("หน้าต่างเลือกโฟลเดอร์ไม่ส่งผลลัพธ์กลับมา กรุณาลองอีกครั้ง")
    try:
        path = base64.b64decode(line.removeprefix("PICKED:"), validate=True).decode("utf-8")
    except (UnicodeDecodeError, ValueError, binascii.Error) as exc:
        raise RuntimeError("ไม่สามารถอ่านชื่อโฟลเดอร์ภาษาไทยจาก Windows") from exc
    if not path.strip():
        raise RuntimeError("หน้าต่างเลือกโฟลเดอร์ส่งค่าพาธว่างเปล่า")
    return path

def prepare_live_preview(song_id, music_volume=0.8, synth_volume=0.8):
    """Issue one-use ticket for streamed preview; no output audio files."""
    if type(song_id) is not int:
        raise ValueError("กรุณาเลือกเพลงสำหรับทดลองฟัง")
    if JOB.get("state") == "running":
        raise ValueError("มีงานสร้างเพลงกำลังทำงานอยู่ กรุณารอให้เสร็จก่อน")
    with LOCK:
        row = FILE_BY_ID.get(song_id)
        catalog = list(FILES)
    if row is None:
        raise ValueError("ไม่พบเพลงที่เลือกในรายการที่สแกน")
    spec = importlib.util.spec_from_file_location("xstage_live_preview", ROOT / "live_preview.py")
    if not spec or not spec.loader:
        raise RuntimeError("แพ็กเกจไม่มี Live Preview Engine")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    audio, midi = mod.matching_sources(row, catalog)
    if midi and not sf_available():
        raise ValueError("กรุณาเลือก SoundFont (.sf2/.sf3) ก่อนเปิดเพลง MIDI/KAR")
    if not ffmpeg_binary():
        raise RuntimeError("ไม่มี FFmpeg ในแพ็กเกจ PC")
    try:
        backing = float(music_volume)
        sound = float(synth_volume)
        if not (0 <= backing <= 1 and 0 <= sound <= 1):
            raise ValueError()
    except (TypeError, ValueError, OverflowError):
        raise ValueError("ค่าระดับเสียงต้องอยู่ระหว่าง 0 ถึง 100%")
    ticket = secrets.token_urlsafe(30)
    with LOCK:
        # Live preview links expire quickly and are consumed only once.
        for key, value in list(LIVE_TICKETS.items()):
            if value["expires"] <= time.monotonic():
                LIVE_TICKETS.pop(key, None)
        LIVE_TICKETS[ticket] = dict(audio=audio, midi=midi,
                                    soundfont=Path(PREFS["soundfont"]) if midi else None,
                                    music_volume=backing, synth_volume=sound,
                                    expires=time.monotonic() + 90)
    return {
        "ticket": ticket, "title": row.get("title", ""),
        "has_backing": bool(audio), "has_midi": bool(midi),
        "mixed": bool(audio and midi),
        "message": ("กำลังเล่นดนตรีกับ SoundFont ผสมกันแบบสตรีมสด" if audio and midi
                    else "เล่น SoundFont MIDI/KAR แบบสตรีมสด" if midi
                    else "เล่นเสียงดนตรีต้นฉบับ (ไม่มี MIDI สำหรับ SoundFont)")
    }


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
            if path == "/api/live-stream":
                ticket = query.get("ticket", [""])[0]
                with LOCK:
                    request = LIVE_TICKETS.pop(ticket, None)
                if not request or request["expires"] < time.monotonic():
                    self._deny("ลิงก์ทดลองฟังหมดอายุ กรุณากดเล่นใหม่", 404)
                    return
                if not LIVE_LIMIT.acquire(blocking=False):
                    self._deny("กำลังเล่นเพลงทดลองฟังมากเกินไป กรุณาหยุดเพลงเดิม", 429)
                    return
                generator = None
                try:
                    spec = importlib.util.spec_from_file_location("xstage_live_preview", ROOT / "live_preview.py")
                    if not spec or not spec.loader:
                        raise RuntimeError("ไม่พบ Live Preview Engine")
                    live = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(live)
                    generator = live.stream_mp3(
                        audio=request["audio"], midi=request["midi"],
                        soundfont=request["soundfont"], ffmpeg=ffmpeg_binary(),
                        runtime=RUNTIME, music_volume=request["music_volume"],
                        synth_volume=request["synth_volume"]
                    )
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/mpeg")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("Connection", "close")
                    if self._origin() == ALLOWED_ORIGIN:
                        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
                        self.send_header("Vary", "Origin")
                    self.end_headers()
                    self.close_connection = True
                    for data in generator:
                        self.wfile.write(data)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass  # User pressed Stop or chose a different preview song.
                except Exception as exc:
                    if generator is None:
                        try:
                            self._deny("ทดลองฟังไม่สำเร็จ: " + str(exc), 500)
                        except OSError:
                            pass
                    else:
                        print("Live preview stream stopped:", repr(exc), file=sys.stderr)
                finally:
                    if generator is not None:
                        generator.close()
                    LIVE_LIMIT.release()
                return
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
                self._json({"version": STATUS_VERSION, "build": STATUS_BUILD,
                    "job": job_snapshot(), "preferences": dict(PREFS),
                    "soundfonts": font_list(), "presets": formats(),
                    "google": {"connected": False, "email": ""},
                    "update": {"status": "unavailable"}})
            elif path == "/api/environment":
                self._json({"Python Runtime": True, "FFmpeg": bool(ffmpeg_binary()),
                    "SoundFont": sf_available(), "FluidSynth": bool(fluidsynth_binary()),
                    "Local file mode": True,
                    "Google Drive connector": False,
                    "AI separation": ai_available()})
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
        if path not in ("/index.html", "/app.js", "/style.css", "/entry.js", "/app-icon.svg", "/app-icon-512.png", "/app-icon.ico", "/site.webmanifest"):
            self._response(404, b"Not found", "text/plain")
            return
        target = UI_ROOT / path[1:]
        if not target.is_file():
            self._response(404, b"UI bundle missing", "text/plain")
            return
        mimetype = {".html": "text/html; charset=utf-8",
                    ".js": "text/javascript; charset=utf-8",
                    ".css": "text/css; charset=utf-8",
                    ".svg": "image/svg+xml",
                    ".png": "image/png",
                    ".ico": "image/x-icon",
                    ".webmanifest": "application/manifest+json"}[target.suffix]
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
            elif path == "/api/live-preview":
                self._json(prepare_live_preview(
                    payload.get("id"), payload.get("music_volume", .8),
                    payload.get("synth_volume", .8)))
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
