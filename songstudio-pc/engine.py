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
# Each Windows account has its own durable preferences and OAuth tokens.
# This location survives replacement/extraction of new PC Ready ZIP releases.
_LOCAL_APP_DATA = os.environ.get("LOCALAPPDATA") if os.name == "nt" else ""
DATA = ((Path(_LOCAL_APP_DATA) if _LOCAL_APP_DATA else
         Path.home() / "AppData" / "Local") / "X-Stage" / "SongStudio"
        if os.name == "nt" else ROOT / "data")
RUNTIME = ROOT / ".runtime"
READY_BUNDLE = (ROOT / ".engine-ready-manifest.json").is_file()
STATUS_VERSION = "0.3.23" if READY_BUNDLE else "0.2.5-Source-Preview"
STATUS_BUILD = "323" if READY_BUNDLE else "205-SRC"
DATA.mkdir(parents=True, exist_ok=True)
# Import the older per-ZIP data folder only once. Never overwrite newer
# preferences, credentials or the DPAPI token already in AppData.
if os.name == "nt" and (ROOT / "data").is_dir():
    for _filename in ("preferences.json", "song-metadata.json",
                      "google-auth.dpapi", "oauth-client.json"):
        _prior = ROOT / "data" / _filename
        _dest = DATA / _filename
        if _prior.is_file() and not _dest.exists():
            try:
                shutil.copy2(_prior, _dest)
            except OSError:
                pass
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
    "eta": None, "idleFor": 0, "logs": [], "result": {},
    "created": 0, "skipped": 0, "errors": 0, "m4aCount": 0, "lyricsCount": 0
}
CANCEL = threading.Event()
PROCESS = None
FILES = []
FILE_BY_ID = {}
PREVIEWS = {}
LIVE_TICKETS = {}
LIVE_SESSIONS = {}
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

# This library belongs ONLY to the independent AI Lyrics menu.
AI_IMPORTS_FILE = DATA / "ai-lyrics-imports.json"
AI_IMPORTED = {}
# Temporary microphone recordings are private and never added to the public
# Karaoke Online catalog. Pending upload tickets are random and in-memory.
AI_RECORDING_INBOX = DATA / "ai-recording-inbox"
AI_RECORDINGS_PENDING = {}
MAX_AI_RECORDING_BYTES = 64 * 1024 * 1024
MAX_AI_RECORDING_SECONDS = 20 * 60
def restore_ai_imports():
    raw = load_json(AI_IMPORTS_FILE, [])
    if not isinstance(raw, list):
        return
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            song_id = entry.get("id")
            path = Path(entry["path"]).expanduser()
            if (type(song_id) is not int or song_id >= 0 or
                    path.suffix.lower() not in EXT_AUDIO or not path.is_file()
                    or path.is_symlink()):
                continue
            row = {"id": song_id, "path": str(path.resolve()), "code": path.stem,
                   "title": str(entry.get("title") or path.stem),
                   "artist": str(entry.get("artist") or ""),
                   "kind": path.suffix[1:].upper(), "size": path.stat().st_size,
                   "status": "ai-import", "source_format": "AI_IMPORT"}
            AI_IMPORTED[song_id] = row
            FILE_BY_ID[song_id] = row
        except (OSError, ValueError, KeyError, TypeError):
            continue

def import_ai_audio(source_path):
    """Register a selected local audio file without scanning the song library."""
    if not isinstance(source_path, str) or not source_path.strip():
        raise ValueError("กรุณาเลือกไฟล์เพลงจากเครื่อง")
    path = Path(source_path).expanduser()
    if path.suffix.lower() not in EXT_AUDIO:
        raise ValueError("รองรับการนำเข้าไฟล์เสียง MP3, M4A, WAV, FLAC, AAC, OGG, WMA และ MP4")
    if not path.is_file() or path.is_symlink():
        raise ValueError("ไม่พบไฟล์เพลงหรือไม่อนุญาตให้ใช้ symbolic link")
    if path.stat().st_size < 1000:
        raise ValueError("ไฟล์เสียงมีขนาดเล็กผิดปกติหรือไม่มีข้อมูล")
    resolved = str(path.resolve())
    with LOCK:
        existing = next((row for row in AI_IMPORTED.values()
                         if row["path"].casefold() == resolved.casefold()), None)
        if existing:
            return {"ok": True, "alreadyImported": True, "song": existing,
                    "message": "ไฟล์นี้มีอยู่แล้วในเมนูสร้างเนื้อร้อง AI"}
        song_id = min([0, *AI_IMPORTED.keys()]) - 1
        row = {"id": song_id, "path": resolved, "code": path.stem,
               "title": path.stem, "artist": "", "kind": path.suffix[1:].upper(),
               "size": path.stat().st_size, "status": "ai-import",
               "source_format": "AI_IMPORT"}
        AI_IMPORTED[song_id] = row
        FILE_BY_ID[song_id] = row
        try:
            save_json(AI_IMPORTS_FILE,
                      [{"id": item["id"], "path": item["path"], "title": item["title"],
                        "artist": item["artist"]} for item in AI_IMPORTED.values()])
        except Exception:
            AI_IMPORTED.pop(song_id, None)
            FILE_BY_ID.pop(song_id, None)
            raise
    return {"ok": True, "alreadyImported": False, "song": row,
            "message": "นำเข้าไฟล์เสียงในเมนูสร้างเนื้อร้อง AI แล้ว (ไม่คัดลอกต้นฉบับ)"}

def stage_microphone_recording(reader, length, content_type):
    """Accept browser MediaRecorder bytes on the authenticated loopback API.

    Stream to private AppData rather than loading long recordings into RAM.
    Never trust a browser file path, name, MIME parameter, or user upload ID.
    No public catalog is changed until a separate explicit Create Song action.
    """
    formats = {"audio/webm": (".webm", b"\x1a\x45\xdf\xa3"),
               "audio/mp4": (".mp4", None),
               "audio/ogg": (".ogg", b"OggS")}
    mime = str(content_type or "").split(";", 1)[0].strip().lower()
    if mime not in formats:
        raise ValueError("ไฟล์บันทึกไมโครโฟนต้องเป็น WebM, MP4 หรือ OGG เท่านั้น")
    if type(length) is not int or not 1000 <= length <= MAX_AI_RECORDING_BYTES:
        raise ValueError("เสียงที่บันทึกมีขนาดไม่ถูกต้องหรือเกิน 64 MB")
    with LOCK:
        if JOB["state"] == "running":
            raise ValueError("มีงานอื่นกำลังทำงาน ไม่สามารถรับไฟล์บันทึกพร้อมกันได้")
        if len(AI_RECORDINGS_PENDING) >= 4:
            raise ValueError("มีเสียงบันทึกที่รอบันทึกมากเกินไป · โปรดบันทึกให้เสร็จก่อน")
    AI_RECORDING_INBOX.mkdir(parents=True, exist_ok=True)
    ticket = secrets.token_urlsafe(24)
    suffix, magic = formats[mime]
    filename = AI_RECORDING_INBOX / (ticket + suffix)
    partial = AI_RECORDING_INBOX / (ticket + ".upload")
    try:
        remaining = length
        with partial.open("xb") as output:
            while remaining:
                chunk = reader.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("ไฟล์เสียงบันทึกส่งมาไม่ครบ · ยังไม่ได้บันทึก")
                output.write(chunk)
                remaining -= len(chunk)
            output.flush()
            os.fsync(output.fileno())
        with partial.open("rb") as check:
            prefix = check.read(16)
        if (magic is not None and not prefix.startswith(magic)) or (
                mime == "audio/mp4" and prefix[4:8] != b"ftyp"):
            raise ValueError("ข้อมูลเสียงบันทึกไม่ตรงกับชนิดไฟล์ที่ระบุ")
        partial.replace(filename)
        with LOCK:
            AI_RECORDINGS_PENDING[ticket] = filename
        return {"recordingId": ticket, "bytes": length,
                "message": "รับไฟล์จากไมโครโฟนแล้ว · พร้อมบันทึกเป็น M4A"}
    finally:
        partial.unlink(missing_ok=True)


def save_microphone_recording(recording_id):
    """Convert an uploaded voice take to AAC M4A and import into AI Lyrics."""
    with LOCK:
        original = AI_RECORDINGS_PENDING.get(recording_id)
    if not original or not original.is_file() or not original.resolve().is_relative_to(
            AI_RECORDING_INBOX.resolve()):
        raise ValueError("ไม่พบเสียงที่บันทึกไว้หรือรายการหมดอายุ · กรุณาอัดใหม่")
    ffmpeg = ffmpeg_binary()
    if not ffmpeg:
        raise RuntimeError("ไม่พบ FFmpeg สำหรับบันทึกเสียง M4A ในแพ็กเกจ PC")
    export = _song_export_module()
    root = export.songs_root(PREFS["workspace"])
    output = root / "audio" / "_" / (
        "Voice-Recording-" + time.strftime("%Y%m%d-%H%M%S") +
        "-" + secrets.token_hex(5) + ".m4a")
    output.parent.mkdir(parents=True, exist_ok=True)
    staged = export.temporary_audio(output)
    try:
        update("บันทึกเสียงขั้น 1/2 · แปลงเสียงไมโครโฟนเป็น AAC/M4A", 0)
        run_process([ffmpeg, "-hide_banner", "-loglevel", "error",
                     "-nostdin", "-y", "-i", str(original),
                     "-vn", "-t", str(MAX_AI_RECORDING_SECONDS),
                     "-c:a", "aac", "-b:a", "160k", "-movflags",
                     "+faststart", str(staged)])
        if CANCEL.is_set():
            raise RuntimeError("ยกเลิกการบันทึกเสียง")
        export.commit_audio(staged, output)
        update("บันทึกเสียงขั้น 2/2 · เพิ่มเสียงที่อัดลงรายการ AI", 1)
        imported = import_ai_audio(str(output))
    finally:
        staged.unlink(missing_ok=True)
    with LOCK:
        AI_RECORDINGS_PENDING.pop(recording_id, None)
    original.unlink(missing_ok=True)
    return {"message": ("บันทึกเสียงใหม่ M4A และนำเข้าเมนู AI สำเร็จ · "
                        "ไม่แก้เพลงต้นฉบับหรืออัปโหลด Google Drive"),
            "song": imported["song"], "path": str(output)}


restore_ai_imports()


def _module(filename, name):
    source = ROOT / filename
    if not source.is_file():
        raise RuntimeError("ไม่พบไฟล์โปรแกรมที่จำเป็น: " + filename)
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def google_client_path():
    """Use a complete Desktop OAuth pair; migrate around broken ID-only clients.

    v0.3.10–312 imported a Desktop client then stripped client_secret.
    When a new release bundles the SAME client's missing secret, prefer
    bundled credentials without deleting the user's private overrides.
    """
    override = DATA / "oauth-client.json"
    bundled = ROOT / "config" / "google-oauth-client.json"
    if override.is_file():
        if bundled.is_file():
            try:
                own = json.loads(override.read_text(encoding="utf-8-sig")).get("installed", {})
                built = json.loads(bundled.read_text(encoding="utf-8-sig")).get("installed", {})
                if (not own.get("client_secret") and built.get("client_secret")
                        and own.get("client_id") == built.get("client_id")):
                    return str(bundled)
            except (OSError, ValueError, AttributeError, TypeError):
                pass
        return str(override)
    if bundled.is_file():
        return str(bundled)
    legacy = PREFS.get("oauth", "")
    return legacy if legacy and Path(legacy).is_file() else ""


GOOGLE = _module("google_drive.py", "xstage_google_drive").GoogleDrive(
    DATA, google_client_path)
NCN = _module("ncn_lyrics.py", "xstage_ncn_lyrics")
SONG_INDEX = _module("song_index.py", "xstage_song_index")
AI_LYRICS = _module("ai_lyrics.py", "xstage_ai_lyrics")
LYRIC_ALIGNMENT = _module("lyric_alignment.py", "xstage_lyric_alignment")
LYRIC_TEXT = _module("lyric_text_groups.py", "xstage_lyric_text_groups")
HISTORY = _module("history_store.py", "xstage_history_store")
HISTORY_FILE = DATA / "edit-history.json"
LYRIC_TEXT_INDEX = None
LYRIC_TEXT_BACKUPS = DATA / "lyric-text-backups"
# Normalize old absolute JSON paths to a stable per-user copy when possible.
if not (DATA / "oauth-client.json").is_file() and not (ROOT / "config" / "google-oauth-client.json").is_file():
    _old_oauth = PREFS.get("oauth", "")
    if _old_oauth and Path(_old_oauth).is_file():
        try:
            GOOGLE.import_client(_old_oauth)
        except (OSError, ValueError, RuntimeError):
            pass
# The UI reflects the stable effective path but never receives client secrets.
PREFS["oauth"] = google_client_path()

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

LAST_SCAN_STATS = {}


def restore_song_catalog():
    """Restore a complete, source-specific SQLite catalog without scanning."""
    rows = SONG_INDEX.restore(
        PREFS["source"], PREFS["workspace"], DATA / "song-index.sqlite3", NOTES)
    with LOCK:
        FILES[:] = rows
        FILE_BY_ID.clear()
        FILE_BY_ID.update((row["id"], row) for row in rows)
        FILE_BY_ID.update(AI_IMPORTED)
    return len(rows)


def scan_source(full=False):
    """Fast incremental scan. Full mode rebuilds metadata without deleting media."""
    global LAST_SCAN_STATS

    def progress(message, completed):
        with LOCK:
            JOB["total"] = 0  # Enumeration count is unknown; never invent a percentage.
            JOB["completed"] = completed
        update(message)

    with LOCK:
        running_scan = JOB.get("state") == "running" and JOB.get("kind") == "scan"
    rows, stats = SONG_INDEX.scan(
        PREFS["source"], PREFS["workspace"], DATA / "song-index.sqlite3",
        NOTES, NCN, full=bool(full),
        cancelled=CANCEL if running_scan else None, on_progress=progress)
    with LOCK:
        FILES[:] = rows
        FILE_BY_ID.clear()
        FILE_BY_ID.update((row["id"], row) for row in rows)
        FILE_BY_ID.update(AI_IMPORTED)
        LAST_SCAN_STATS = stats
        JOB["total"] = len(rows)
        JOB["completed"] = len(rows)
    return len(rows)


def _selected_row(song_id):
    """Find either an ordinary scan row or an independent AI-import row."""
    if type(song_id) is not int:
        return None
    with LOCK:
        return FILE_BY_ID.get(song_id) or AI_IMPORTED.get(song_id)


def import_vocal_sources():
    """Open Windows multi-file picker, register only references in AI workspace."""
    selected = open_picker("vocal")
    if not selected:
        return {"cancelled": True, "added": 0, "message": "ยกเลิกการนำเข้าเพลง"}
    try:
        paths = json.loads(selected)
    except (ValueError, TypeError) as exc:
        raise ValueError("ข้อมูลจากหน้าต่างเลือกเพลงไม่ถูกต้อง") from exc
    if isinstance(paths, str):
        paths = [paths]
    if not isinstance(paths, list) or not 1 <= len(paths) <= 200:
        raise ValueError("กรุณานำเข้าเพลงครั้งละ 1–200 ไฟล์")
    added = skipped = 0
    errors = []
    imported = []
    for raw in paths:
        try:
            result = import_ai_audio(raw)
            imported.append(result["song"])
            if result["alreadyImported"]:
                skipped += 1
            else:
                added += 1
        except (OSError, ValueError, TypeError) as exc:
            errors.append(str(exc))
    if not imported:
        raise ValueError("ไม่สามารถนำเข้าเพลงใดได้: " + "; ".join(errors[:3]))
    return {"cancelled": False, "added": added, "skipped": skipped,
            "total": len(AI_IMPORTED), "errors": errors[:20],
            "song": imported[0],
            "message": f"นำเข้าใหม่ {added} เพลง · ข้ามซ้ำ {skipped} · ผิดพลาด {len(errors)}"}


def remove_vocal_source(song_id):
    """Forget one AI import, retaining music files and private drafts."""
    if type(song_id) is not int:
        raise ValueError("รหัสไฟล์เพลงไม่ถูกต้อง")
    with LOCK:
        if JOB.get("state") == "running":
            raise ValueError("มีงานกำลังดำเนินการ · ไม่สามารถนำเพลงออกระหว่างประมวลผลได้")
        removed = AI_IMPORTED.pop(song_id, None)
        if not removed:
            raise ValueError("ไม่พบรายการเพลงที่นำเข้าในเมนู AI")
        FILE_BY_ID.pop(song_id, None)
        try:
            save_json(AI_IMPORTS_FILE,
                      [{"id": item["id"], "path": item["path"],
                        "title": item["title"], "artist": item["artist"]}
                       for item in AI_IMPORTED.values()])
        except Exception:
            AI_IMPORTED[song_id] = removed
            FILE_BY_ID[song_id] = removed
            raise
    return {"ok": True, "message": "นำเพลงออกจากรายการ AI แล้ว · ไม่ลบไฟล์ต้นฉบับหรือร่างเนื้อร้อง"}


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

def _matching_lrc(source: Path) -> Path | None:
    """A companion must have the SAME original code in SAME directory."""
    candidate = source.with_suffix(".lrc")
    if candidate.is_file():
        return candidate
    # Linux regression tests and Windows both honor case-insensitive .LRC.
    try:
        for item in source.parent.iterdir():
            if (item.is_file() and item.stem.casefold() == source.stem.casefold()
                    and item.suffix.casefold() == ".lrc"):
                return item
    except OSError:
        pass
    return None


def lyrics_package(row):
    """Return (LRC, accurately timed JSON, source fingerprint) or no lyrics.

    Never invent timings. The metadata editor's saved timed LRC has priority.
    NCN requires .MID + .LYR + .CUR with the SAME code and mirrored folder.
    KAR text events are decoded from the MIDI itself.
    """
    export = _song_export_module()
    code = str(row.get("code") or Path(row["path"]).stem)
    note = NOTES.get(row["path"], {}).get("lyrics", "")
    if note:
        doc = export.lrc_to_json(note, code)
        if not doc["lines"]:
            raise ValueError("เนื้อร้องที่แก้ไขไม่มี timestamp LRC ที่ถูกต้อง")
        return note, doc, hashlib.sha256(note.encode("utf-8")).hexdigest()
    source = Path(row["path"])
    trio = row.get("ncn") or NCN.resolve_companions(source)
    if trio:
        doc = NCN.ncn_document(trio)
        doc["songCode"] = code
        files = [Path(trio[k]) for k in ("midi", "lyrics", "cursor")]
        fingerprint = hashlib.sha256()
        for item in files:
            # Metadata changes are enough to detect an updated NCN trio at
            # scale without rehashing hundreds of megabytes on every run.
            stat = item.stat()
            fingerprint.update((str(item.resolve()).casefold() + ":" +
                                str(stat.st_size) + ":" + str(stat.st_mtime_ns)).encode("utf-8"))
        return doc["rawLrc"], doc, fingerprint.hexdigest()
    lrc = _matching_lrc(source)
    if lrc is not None:
        data = lrc.read_bytes()
        text = NCN._decode_text(data)
        doc = export.lrc_to_json(text, code)
        if not doc["lines"]:
            raise ValueError("ไฟล์ LRC มีข้อความ แต่ไม่มี timestamp ที่ถูกต้อง: " + lrc.name)
        return text, doc, hashlib.sha256(data).hexdigest()
    if source.suffix.lower() in EXT_MIDI:
        try:
            doc = NCN.kar_document(source, code)
            stat = source.stat()
            fingerprint = hashlib.sha256(
                (str(stat.st_size) + ":" + str(stat.st_mtime_ns)).encode()).hexdigest()
            return doc["rawLrc"], doc, fingerprint
        except ValueError:
            if source.suffix.lower() == ".kar":
                raise
    return "", None, ""


def lyrics_text(row):
    """Preview currently available lyrics; no empty fake timestamped LRC."""
    note = NOTES.get(row["path"], {}).get("lyrics", "")
    if note:
        return note
    try:
        return lyrics_package(row)[0]
    except (ValueError, OSError):
        return ""


def preview_song_identity(row):
    """Resolve title/artist for the ONE selected song; never guess from neighbors.

    A bulk scan of 90k+ songs must remain fast, so inspect embedded KAR or
    LRC metadata on demand only. Saved manual edits retain priority.
    """
    source = Path(row["path"])
    code = str(row.get("code") or source.stem)
    title = str(row.get("title") or source.stem).strip()
    artist = str(row.get("artist") or "").strip()
    overrides = NOTES.get(str(source), {})
    discovered = {}
    trio = row.get("ncn") or NCN.resolve_companions(source)
    if trio and trio.get("lyrics"):
        try:
            discovered = NCN.lyric_metadata(Path(trio["lyrics"]))
        except (OSError, ValueError):
            pass
    elif source.suffix.lower() in EXT_MIDI:
        try:
            _, _, events = NCN.midi_events(source)
            titles = [text[2:].strip() for _, _, _, tag, text in events
                      if tag in (1, 5) and text.startswith("@T") and text[2:].strip()]
            if titles:
                discovered = {"title": titles[0],
                              "artist": titles[1] if len(titles) > 1 else ""}
        except (OSError, ValueError):
            pass
    if not discovered and source.suffix.lower() in EXT_AUDIO:
        lrc = _matching_lrc(source)
        if lrc:
            try:
                head = NCN._decode_text(lrc.read_bytes()[:8192])
                for line in head.splitlines()[:40]:
                    line = line.strip()
                    if line.startswith("[") and line.endswith("]") and ":" in line:
                        tag, value = line[1:-1].split(":", 1)
                        if tag.casefold() in ("ti", "title") and value.strip():
                            discovered["title"] = value.strip()
                        if tag.casefold() in ("ar", "artist") and value.strip():
                            discovered["artist"] = value.strip()
            except (OSError, ValueError):
                pass
    if not str(overrides.get("title") or "").strip() and (
            not title or title.casefold() == source.stem.casefold()):
        title = str(discovered.get("title") or title).strip()
    if not str(overrides.get("artist") or "").strip() and not artist:
        artist = str(discovered.get("artist") or "").strip()
    return {"title": title or code, "artist": artist, "code": code}


def ensure_midi_wav(path):
    if not sf_available():
        raise RuntimeError("การสร้าง MIDI/KAR ต้องเลือก SoundFont SF2/SF3 ก่อน")
    fluid = fluidsynth_binary()
    if not fluid:
        raise RuntimeError("ไม่พบ FluidSynth ในโฟลเดอร์โปรแกรม กรุณาใช้ Ready ZIP ที่รวมไลบรารีครบ")
    tmp = PREVIEW_FOLDER / (secrets.token_hex(10) + ".wav")
    # FluidSynth CLI expects flags before positional SoundFont/MIDI arguments.
    params = [fluid, "-ni", "-F", str(tmp), "-r", "48000", PREFS["soundfont"], str(path)]
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
        # Karaoke PC audio export uses 48 kHz / AAC-LC 256 kbps for MIDI.
        # Keep existing 192 kbps for ordinary audio transcodes to avoid
        # surprising changes in non-MIDI workspaces.
        cmd += ["-vn", "-c:a", "aac", "-profile:a", "aac_low"]
        if midi:
            cmd += ["-ar", "48000", "-b:a", "256k"]
        else:
            cmd += ["-b:a", "192k"]
        cmd += ["-movflags", "+faststart", str(target)]
        run_process(cmd)
        if not target.is_file() or target.stat().st_size < 1000:
            raise RuntimeError("ไฟล์เสียงผลลัพธ์ไม่สมบูรณ์")
        if midi:
            ffmpeg = Path(ffmpeg_binary())
            probe = ffmpeg.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
            if not probe.is_file():
                found = shutil.which("ffprobe")
                probe = Path(found) if found else None
            if probe is None and READY_BUNDLE:
                raise RuntimeError("แพ็กเกจไม่มี ffprobe สำหรับยืนยัน AAC ของ MIDI")
            if probe is not None:
                kw = {}
                if os.name == "nt":
                    kw["creationflags"] = subprocess.CREATE_NO_WINDOW
                checked = subprocess.run([
                    str(probe), "-v", "error", "-select_streams", "a:0",
                    "-show_entries", "stream=codec_name,sample_rate",
                    "-of", "json", str(target)],
                    capture_output=True, text=True, timeout=30, **kw)
                if checked.returncode:
                    raise RuntimeError("ตรวจสอบคุณภาพ M4A ไม่ผ่าน: " + checked.stderr[-500:])
                try:
                    streams = json.loads(checked.stdout).get("streams") or []
                    codec_ok = bool(streams and
                                    streams[0].get("codec_name") == "aac" and
                                    int(streams[0].get("sample_rate", 0)) == 48000)
                except (ValueError, TypeError, AttributeError):
                    codec_ok = False
                if not codec_ok:
                    raise RuntimeError("M4A ที่สร้างจาก MIDI ไม่ใช่ AAC 48 kHz ตามสเปก")
    finally:
        if temp_wav:
            temp_wav.unlink(missing_ok=True)

def separate_ai(row, target, preview=False, *, vocals_only=False):
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
    if preview and vocals_only:
        raise ValueError("การแยกเสียงร้องเพื่อบันทึก M4A ต้องไม่ใช้โหมดตัวอย่าง 60 วินาที")
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
        if not vocals_only:
            update("AI ขั้น 3/4 · เข้ารหัส M4A ดนตรี")
            run_process([ffmpeg_binary(), "-hide_banner", "-loglevel", "error", "-nostdin",
                         "-y", "-i", str(instrumental), "-c:a", "aac", "-b:a", "192k",
                         "-movflags", "+faststart", str(target)])
            if not target.is_file() or target.stat().st_size < 1000:
                raise RuntimeError("ไฟล์ AI Instrumental M4A ไม่สมบูรณ์")
            if preview:
                return None
        update("AI ขั้น 4/4 · เข้ารหัส M4A เสียงร้องแยก")
        stem = target if vocals_only else target.with_name(target.stem + " - vocals.m4a")
        if stem.exists():
            if vocals_only:
                raise FileExistsError("ไฟล์เสียงร้องแยกอยู่แล้ว · ไม่เขียนทับ M4A เดิม")
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


def ai_vocals_target(row):
    """Deterministic private StageWeb/audio M4A for an imported source.

    The filename includes a fingerprint of original path/size/mtime so a
    changed source cannot silently reuse its predecessor's AI vocal file.
    AI-only stems are never added to the public song catalog automatically.
    """
    source = Path(row["path"]).expanduser()
    if (source.suffix.lower() not in EXT_AUDIO or
            not source.is_file() or source.is_symlink()):
        raise ValueError("ต้องเลือกไฟล์เสียงต้นฉบับที่ยังอยู่ในเครื่อง")
    export = _song_export_module()
    root = export.songs_root(PREFS["workspace"])
    bucket = export.source_bucket(str(row.get("code") or source.name))
    key = AI_LYRICS._source_key(source)[:16]
    stem = export.safe_filename(source.stem)[:90]
    return root / "audio" / bucket / (stem + " - AI Vocals-" + key + ".m4a")


def saved_ai_vocals(row):
    """Return only completed M4A; never use a partial output as AI input."""
    path = ai_vocals_target(row)
    return path if path.is_file() and not path.is_symlink() and path.stat().st_size >= 1000 else None


def separate_ai_lyrics_vocals(song_id):
    """Save separate vocal and instrumental AAC M4A files, without publishing.

    Stable source fingerprints make retries idempotent. Neither the imported
    audio nor any existing output is overwritten. An interrupted run may leave
    one completed stem; the next run safely creates only the missing stem.
    """
    with LOCK:
        row = dict(AI_IMPORTED.get(song_id) or {}) if type(song_id) is int else {}
    if not row:
        raise ValueError("เลือกเพลงที่นำเข้าในเมนูเนื้อร้อง AI ก่อน")
    if not ai_available():
        raise RuntimeError("AI Separation HTDemucs ไม่พร้อม · กรุณาใช้ PC Ready ที่รวมโมเดลครบ")
    vocal_target = ai_vocals_target(row)
    music_target = vocal_target.with_name(
        vocal_target.name.replace(" - AI Vocals-", " - AI Instrumental-"))
    if music_target == vocal_target:
        raise RuntimeError("ไม่สามารถกำหนดชื่อ M4A ดนตรีแยกได้")

    def finished(path):
        if path.exists() and (not path.is_file() or path.is_symlink() or
                              path.stat().st_size < 1000):
            raise RuntimeError("พบไฟล์ M4A ที่ไม่สมบูรณ์ · ไม่เขียนทับ: " + str(path))
        return path.is_file()

    vocal_ready, music_ready = finished(vocal_target), finished(music_target)
    if vocal_ready and music_ready:
        update("พบ M4A เสียงร้องและดนตรีที่สร้างแล้ว · ใช้ไฟล์เดิม", 1)
        return {"songId": song_id, "path": str(vocal_target),
                "instrumentalPath": str(music_target), "reused": True,
                "message": "มีไฟล์ M4A แยกเสียงร้องและดนตรีแล้ว · " +
                           str(vocal_target) + " · " + str(music_target)}

    music_target.parent.mkdir(parents=True, exist_ok=True)
    export = _song_export_module()
    staged_music = export.temporary_audio(music_target)
    staged_vocal = None
    try:
        update("กำลังแยกเสียงร้องและดนตรีเป็น M4A สองไฟล์ · ประมวลผลออฟไลน์")
        staged_vocal = separate_ai(row, staged_music, vocals_only=False)
        if CANCEL.is_set():
            raise RuntimeError("ผู้ใช้ยกเลิกก่อนบันทึกไฟล์ M4A")
        # Check again to avoid replacing files created by another process.
        if not finished(vocal_target):
            export.commit_audio(staged_vocal, vocal_target)
        if not finished(music_target):
            export.commit_audio(staged_music, music_target)
    finally:
        staged_music.unlink(missing_ok=True)
        if staged_vocal is not None:
            staged_vocal.unlink(missing_ok=True)
    update("บันทึก M4A เสียงร้องและดนตรีแยกเสร็จแล้ว · ใช้เสียงร้องกับ Whisper AI ได้", 1)
    return {"songId": song_id, "path": str(vocal_target),
            "instrumentalPath": str(music_target), "reused": False,
            "message": "บันทึก M4A แยกเสียงร้อง: " + str(vocal_target) +
                       " · ดนตรี: " + str(music_target) +
                       " · ไม่แก้เพลงต้นฉบับและไม่อัปโหลด Google Drive อัตโนมัติ"}



def export_ai_lyrics_files(song_id, *, include_lyrics=False, include_instrumental=False):
    """Export only the selected reviewed LRC and/or separated karaoke M4A.

    Files are copied to the user's remembered download directory, never to
    the original source folder or directly into the published song catalog.
    Exclusive file creation prevents overwrites, including concurrent exports.
    """
    if type(song_id) is not int or not (include_lyrics or include_instrumental):
        raise ValueError("กรุณาเลือกเพลงและชนิดไฟล์อย่างน้อยหนึ่งรายการ")
    with LOCK:
        row = dict(AI_IMPORTED.get(song_id) or {})
    if not row:
        raise ValueError("กรุณาเลือกเพลงจากรายการที่นำเข้าในหน้า AI")
    source = Path(row["path"]).expanduser()
    if not source.is_file() or source.is_symlink() or source.suffix.lower() not in EXT_AUDIO:
        raise ValueError("ไฟล์เสียงต้นฉบับไม่พร้อมใช้งาน")
    reviewed = ""
    if include_lyrics:
        with LOCK:
            reviewed = str(NOTES.get(row["path"], {}).get("lyrics") or "")
        if not reviewed.strip():
            raise ValueError("ยังไม่ได้ตรวจและบันทึกเนื้อร้อง LRC · ต้องบันทึกก่อนส่งออก")
        parsed = _song_export_module().lrc_to_json(reviewed, str(row.get("code") or ""))
        if not parsed.get("lines"):
            raise ValueError("เนื้อร้อง LRC ไม่มีเวลาที่ถูกต้อง")
    destination = Path(PREFS["download"]).expanduser()
    if not destination.is_dir():
        raise ValueError("โฟลเดอร์ส่งออกไม่พร้อมใช้งาน · เลือกตำแหน่งในเมนูดาวน์โหลดก่อน")
    if destination.is_symlink():
        raise ValueError("ไม่อนุญาตโฟลเดอร์ส่งออกที่เป็น Symbolic Link")
    safe = _song_export_module().safe_filename(
        str(row.get("code") or source.stem) + " - " + str(row.get("title") or source.stem))
    safe = safe[:110]
    instrumental = None
    if include_instrumental:
        instrumental = ai_vocals_target(row).with_name(
            ai_vocals_target(row).name.replace(" - AI Vocals-", " - AI Instrumental-"))
        if instrumental.name == ai_vocals_target(row).name:
            raise RuntimeError("หาไฟล์ดนตรีที่แยกไว้ไม่สำเร็จ")
        if not instrumental.is_file() or instrumental.stat().st_size < 1000:
            update("ยังไม่มีไฟล์เพลงตัดเสียงร้อง · กำลังแยกเสียงด้วย AI ก่อนส่งออก")
            separate_ai_lyrics_vocals(song_id)
        if not instrumental.is_file() or instrumental.stat().st_size < 1000:
            raise RuntimeError("ไม่พบไฟล์ M4A ดนตรีที่แยกเสร็จแล้ว")

    exported = []
    tasks = []
    if include_lyrics:
        tasks.append((safe + ".lrc", reviewed.encode("utf-8-sig")))
    if include_instrumental:
        tasks.append((safe + " - Instrumental.m4a", instrumental))
    for i, (name, data) in enumerate(tasks, 1):
        if CANCEL.is_set():
            raise RuntimeError("ยกเลิกการส่งออก")
        update(f"ส่งออกไฟล์ {i}/{len(tasks)} · {name}", i - 1)
        # Reserve an unused name atomically; never replace an existing export.
        target = None
        for n in range(1, 1001):
            stem = Path(name).stem + (f" ({n})" if n > 1 else "")
            candidate = destination / (stem + Path(name).suffix)
            try:
                with candidate.open("xb") as output:
                    target = candidate
                    try:
                        if isinstance(data, bytes):
                            output.write(data)
                        else:
                            with data.open("rb") as stream:
                                while True:
                                    if CANCEL.is_set():
                                        raise RuntimeError("ยกเลิกการส่งออก")
                                    block = stream.read(1024 * 1024)
                                    if not block:
                                        break
                                    output.write(block)
                        output.flush()
                        os.fsync(output.fileno())
                    except BaseException:
                        output.close()
                        candidate.unlink(missing_ok=True)
                        raise
                break
            except FileExistsError:
                continue
        if target is None:
            raise RuntimeError("มีไฟล์ชื่อซ้ำมากเกินไปในโฟลเดอร์ส่งออก")
        exported.append(str(target))
        update(f"บันทึกไฟล์ {i}/{len(tasks)} สำเร็จ", i)
    return {"songId": song_id, "files": exported, "count": len(exported),
            "message": "ส่งออกสำเร็จ " + str(len(exported)) + " ไฟล์ · " +
                       " | ".join(exported) +
                       " · ไม่แก้ไฟล์ต้นฉบับหรืออัปโหลด Google Drive"}


def _song_export_module():
    path = ROOT / "song_export.py"
    if not path.is_file():
        raise RuntimeError("ไม่พบระบบตรวจเพลงซ้ำ song_export.py กรุณาติดตั้งแพ็กเกจ PC รุ่นใหม่ให้ครบ")
    spec = importlib.util.spec_from_file_location("xstage_song_export", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def code_registry_snapshot(root, *, require_drive=False):
    """Read actual local + visible Google catalog before assigning song codes.

    Without a verified Drive snapshot, code assignments are PC-only provisional;
    publishing always runs a fresh, mandatory online reconciliation.
    """
    registry = _module("code_registry.py", "xstage_code_registry")
    online = _module("online_publish.py", "xstage_online_publish")
    root = Path(root)
    status = GOOGLE.status()
    if status.get("connected"):
        try:
            snapshot = online.OnlinePublisher(GOOGLE).read_code_registry()
            return registry, snapshot["songs"], True, snapshot["generation"]
        except Exception as exc:
            if require_drive:
                raise RuntimeError(
                    "ตรวจรหัสจาก Google Drive ไม่สำเร็จ · ไม่เปลี่ยนรหัสหรืออัปโหลด: " +
                    str(exc)) from exc
            log("ยังไม่สามารถยืนยันรหัส Google Drive · ไม่แก้รหัสเพลงเก่า: " + str(exc))
    elif require_drive:
        raise RuntimeError("ต้อง Google Login ใน Song Studio PC ก่อนตรวจรหัสร่วมสองแหล่ง")
    return registry, [], False, ""


def reconcile_local_codes(root, records, registry, remote, export):
    """Re-map code collisions in durable local catalog; never touch audio."""
    allocator = registry.CodeAllocator(records, remote, root)
    changes = allocator.reconcile_existing()
    if changes:
        update("พบรหัสซ้ำระหว่าง PC และ Google Drive · กำลังจัดสรรรหัสว่าง")
        changed = registry.apply_changes(root, changes, export)
        log(f"แก้รหัสในคลัง PC {changed:,} เพลงโดยไม่แปลง M4A ซ้ำ")
        for old, code in changes[-5:]:
            log(f"รหัสซ้ำ {old['code']} → {code} · {old.get('title', '')}")
    return allocator, len(changes)


def code_registry_preview():
    """Read-only two-source preview; UI can verify before new conversion."""
    export = _song_export_module()
    root = export.songs_root(PREFS["workspace"])
    records = export.existing_records(root)
    registry, remote, verified, generation = code_registry_snapshot(root)
    allocator = registry.CodeAllocator(records, remote, root)
    changes = allocator.reconcile_existing()
    return {
        "pcSongs": len(records), "driveSongs": len(remote),
        "onlineVerified": verified, "driveGeneration": generation,
        "localCodeConflicts": len(changes),
        "sampleRemaps": [{"oldCode": x.get("code"), "newCode": code,
                          "title": x.get("title", "")} for x, code in changes[:10]],
        "message": (
            f"ตรวจครบ PC {len(records):,} และ Google Drive {len(remote):,} เพลง "
            f"· ต้องปรับรหัสในคลัง PC {len(changes):,} รายการ"
            if verified else
            f"ตรวจเฉพาะ PC {len(records):,} เพลง · ยังไม่สามารถยืนยันรหัส Google Drive "
            f"· รหัสใหม่ยังเป็นรหัสชั่วคราว")
    }


def _source_digest(row, export):
    """Deduplicate complete NCN *song packages*, not just MIDI bytes.

    Two different NCN songs may share an identical MIDI arrangement but
    have different .LYR/.CUR and must not share their lyrics record.
    """
    source = Path(row["path"])
    trio = row.get("ncn") or NCN.resolve_companions(source)
    if not trio:
        return export.source_sha256(source)
    digest = hashlib.sha256()
    digest.update(b"NCN-FULL-SOURCE-V1\\0")
    for component in ("midi", "lyrics", "cursor"):
        file = trio.get(component)
        if file:
            digest.update(component.encode())
            digest.update(export.source_sha256(file).encode("ascii"))
        else:
            digest.update((component + "=MISSING").encode())
    return digest.hexdigest()


def build_library(rows, mode, options):
    """Idempotent across independent sessions; checkpoint before next song.

    1. Read previously published catalogs AND the recovered journal.
    2. Match canonical original path first; hash full source only if needed.
    3. Never generate new audio/lyrics for a previously completed source.
    4. Stage output in the destination directory; commit without overwrite.
    5. Fsync each finished record, then atomically replace current.json once.
    """
    export = _song_export_module()
    root = export.songs_root(PREFS["workspace"])
    root.mkdir(parents=True, exist_ok=True)
    for name in ("audio", "lyrics"):
        (root / name).mkdir(exist_ok=True)
    records = export.existing_records(root)
    registry, remote, online_verified, online_generation = code_registry_snapshot(root)
    if online_verified:
        allocator, remapped = reconcile_local_codes(root, records, registry, remote, export)
        if remapped:
            records = export.existing_records(root)
        log(f"ตรวจรหัสสองแหล่งแล้ว · PC {len(records):,} · Google Drive {len(remote):,} เพลง")
    else:
        allocator = registry.CodeAllocator(records, [], root)
        log("ยังไม่ได้ยืนยันรหัสกับ Google Drive · รหัสเพลงที่สร้างขณะออฟไลน์เป็นรหัสชั่วคราวจนกว่าจะอัปโหลด")
    # Build these indices ONCE. Looking up an incomplete source by scanning
    # every catalog row for each new song was quadratic for large libraries
    # (e.g. 90,000 tracks). Preserve the same verified duplicate rules.
    by_path, by_sha, by_incomplete = {}, {}, {}
    indexed_audio_paths = set()
    for record in records:
        marker = record.get("sourceIdentity") or {}
        source_key = marker.get("canonicalPath")
        audio_path = (record.get("audio") or {}).get("path")
        if audio_path:
            indexed_audio_paths.add(audio_path)
        if export.record_is_complete(root, record):
            if source_key:
                by_path[source_key] = record
            if marker.get("sha256"):
                by_sha[marker["sha256"]] = record
        elif source_key:
            by_incomplete[source_key] = record

    created = skipped = errors = audio_count = lyrics_count = 0
    details = []
    with LOCK:
        JOB["total"] = len(rows)
    log(f"ตรวจสอบคลังเพลงเดิม: พบ {len(records):,} รายการ (รวมรายการที่กู้จากงานก่อน)")
    try:
        for idx, row in enumerate(rows, 1):
            if CANCEL.is_set():
                raise RuntimeError("ผู้ใช้ยกเลิกงาน; เพลงที่สำเร็จก่อนหน้านี้ถูกเก็บไว้แล้ว")
            source = Path(row["path"])
            staged = staged_vocals = target = vocal_target = None
            committed_audio = committed_vocals = None
            new_lyric = None
            checkpointed = False
            try:
                if not source.is_file() or source.is_symlink():
                    raise FileNotFoundError("ไม่พบไฟล์ต้นฉบับ หรือเป็น symlink")
                update(f"ตรวจเพลงซ้ำ {idx}/{len(rows)}: {row['title']}")
                canonical = export.canonical_source_path(source)
                previous = by_path.get(canonical)
                # If a previous run has a complete record, checking its path
                # takes milliseconds and avoids re-reading a huge audio file.
                digest = None
                if previous is None:
                    update(f"ตรวจลายนิ้วมือ SHA-256 {idx}/{len(rows)}: {source.name}")
                    digest = _source_digest(row, export)
                    previous = by_sha.get(digest)
                if previous is not None:
                    # The original source's filename is NOT the assigned code
                    # after an earlier two-source reconciliation.
                    row["code"] = str(previous["code"])
                    # Repair or add ONLY the lyric companion. Preserve the
                    # exact same M4A, song ID, audio catalog path and code.
                    if not options.get("audio_only", False):
                        try:
                            lrc, document, lyric_fingerprint = lyrics_package(row)
                            if document and (not previous.get("lyrics") or
                                             previous.get("lyricsSourceIdentity") != lyric_fingerprint):
                                saved_audio = export.safe_media_path(
                                    root, previous["audio"]["path"], "audio")
                                repair = bool(previous.get("lyrics"))
                                upgrade = export.save_lyrics(
                                    root, saved_audio, lrc, str(row.get("code") or source.stem),
                                    document=document, repair=repair)
                                revised = dict(previous)
                                revised["lyrics"] = {
                                    "path": upgrade.relative_to(root).as_posix()
                                }
                                revised["lyricsSourceIdentity"] = lyric_fingerprint
                                export.append_journal(root, revised)
                                records.append(revised)
                                by_path[canonical] = revised
                                by_sha[digest or (previous.get("sourceIdentity") or {}).get("sha256")] = revised
                                lyrics_count += 1
                                log(("ซ่อมเนื้อร้องจากต้นฉบับจริง" if repair else "เพิ่ม Lyrics") +
                                    " โดยไม่สร้าง M4A ซ้ำ: " + source.name)
                            elif document is None:
                                errors += 1
                                issue = source.name + ": ไม่มีไฟล์เนื้อร้องพร้อมเวลา (M4A เดิมยังปลอดภัย)"
                                details.append(issue)
                                log("ERR " + issue)
                        except (OSError, ValueError, RuntimeError) as exc:
                            errors += 1
                            issue = source.name + ": " + str(exc)
                            details.append(issue)
                            log("ERR Lyrics " + issue)
                    else:
                        log(f"ข้ามไฟล์ซ้ำ: {source.name} → {previous['audio']['path']} (ไม่สร้างรหัส/M4A/Lyrics ใหม่)")
                    skipped += 1
                    continue

                # Never create a second filename while repairing a known
                # incomplete prior record. Existing media stays untouched.
                partial = by_incomplete.get(canonical)
                if partial:
                    # Older releases sometimes published blank Lyrics JSON.
                    # Repair from the original components; NEVER re-encode or
                    # allocate a second audio filename for that source.
                    saved_audio = export.safe_media_path(
                        root, partial["audio"]["path"], "audio")
                    if not saved_audio.is_file() or saved_audio.stat().st_size < 1000:
                        raise RuntimeError(
                            "พบรายการเดิมแต่ M4A ไม่สมบูรณ์: " + str(saved_audio) +
                            " · ไม่ลบหรือเขียนทับอัตโนมัติ")
                    if options.get("audio_only", False):
                        skipped += 1
                        log("ข้ามไฟล์เสียงเดิมที่อยู่ระหว่างซ่อม Lyrics: " + source.name)
                        continue
                    lrc, document, lyric_fingerprint = lyrics_package(row)
                    if not document:
                        raise ValueError(
                            "ไม่มีไฟล์ Lyrics จริงสำหรับซ่อมเพลงที่เคยสร้าง · " + source.name)
                    repaired = export.save_lyrics(
                        root, saved_audio, lrc, str(row.get("code") or source.stem),
                        document=document, repair=True)
                    revised = dict(partial)
                    revised["lyrics"] = {"path": repaired.relative_to(root).as_posix()}
                    revised["lyricsSourceIdentity"] = lyric_fingerprint
                    export.append_journal(root, revised)
                    records.append(revised)
                    by_path[canonical] = revised
                    by_sha[digest] = revised
                    by_incomplete.pop(canonical, None)
                    lyrics_count += 1
                    skipped += 1
                    log("ซ่อม Lyrics JSON เดิมที่ผิดพลาดสำเร็จโดยไม่สร้าง M4A ซ้ำ: " + source.name)
                    continue

                # A pre-existing legacy unindexed output may come from an older
                # app that did not store a source fingerprint. Do not invent a
                # different number and accidentally duplicate that song.
                preferred = (root / "audio" / export.source_bucket(source.name) /
                             (export.safe_filename(source.stem) + ".m4a"))
                if (preferred.exists() and
                        preferred.relative_to(root).as_posix() not in indexed_audio_paths):
                    raise RuntimeError(
                        "พบ M4A เดิมที่ไม่มีข้อมูลตรวจต้นฉบับ: " +
                        str(preferred.relative_to(root)) +
                        " หยุดเพื่อป้องกันสร้างไฟล์ซ้ำ กรุณาตรวจ/นำเข้ารายการเดิมก่อน"
                    )
                # Pre-fingerprint legacy Source Preview editions used
                # workspace/song/<edited title>.m4a with NO stored source hash.
                # Skip ambiguous legacy matches rather than creating a repeat
                # with a new numbered output; do not touch those old files.
                legacy = (Path(PREFS["workspace"]).expanduser() / "song" /
                          (safe_stem(row.get("title") or source.stem) + ".m4a"))
                if legacy.is_file() and legacy.stat().st_size >= 1000:
                    # An unindexed legacy file is NOT a verified completed
                    # catalog item. Never report it as a successful duplicate.
                    raise RuntimeError(
                        "พบไฟล์ M4A รุ่นเก่าที่ยังไม่มีข้อมูลยืนยันต้นฉบับ: " +
                        str(legacy) +
                        " · ไม่สร้างซ้ำหรือเขียนทับ · กรุณาตรวจสอบ/นำเข้าคลังเดิมก่อน")
                # Reserve the code against BOTH catalogs before media creation.
                # If Drive was offline, keep this local reservation provisional;
                # the upload stage will verify/reassign against live XStageWeb.
                original_code = str(row.get("code") or source.stem)
                assigned_code = allocator.assign_new(original_code)
                row["code"] = assigned_code
                if assigned_code != original_code:
                    log(f"รหัส {original_code} ถูกใช้แล้ว · จัดสรร {assigned_code} ให้เพลง {row.get('title', '')}")
                # Per-song guard, not a misleading 3x entire-library
                # requirement. If storage runs out, previous commits survive.
                free_now = shutil.disk_usage(root).free
                if free_now < 128 * 1024 ** 2:
                    raise RuntimeError(
                        "พื้นที่ดิสก์เหลือน้อยกว่า 128 MB หยุดสร้างเพลงนี้"
                        " · เปลี่ยนโฟลเดอร์บันทึกหรือเพิ่มพื้นที่ว่าง"
                    )
                # Resolve the entire NCN trio before costly MIDI synthesis.
                # A missing .LYR/.CUR must never produce a wrong timed JSON.
                lyric_info = ("", None, "")
                if not options.get("audio_only", False):
                    lyric_info = lyrics_package(row)
                target = export.next_target(root, assigned_code + source.suffix)
                staged = export.temporary_audio(target)
                update(f"กำลังสร้างเพลงใหม่ {idx}/{len(rows)}: {row['title']}")
                if mode == "instrumental":
                    staged_vocals = separate_ai(row, staged, preview=False)
                elif source.suffix.lower() == ".m4a":
                    shutil.copy2(source, staged)  # Preserve source audio; zero transcoding
                else:
                    convert(row, staged)

                export.commit_audio(staged, target)
                committed_audio = target
                if staged_vocals is not None:
                    vocal_target = target.with_name(target.stem + " - vocals.m4a")
                    export.commit_audio(staged_vocals, vocal_target)
                    committed_vocals = vocal_target

                lyric_file = None
                if not options.get("audio_only", False):
                    lrc, timed_doc, lyric_fingerprint = lyric_info
                    if timed_doc:
                        lyric_file = export.save_lyrics(
                            root, target, lrc, str(row.get("code") or source.stem),
                            document=timed_doc)
                        new_lyric = lyric_file
                    else:
                        # Audio was genuinely created, but lyrics could NOT be
                        # extracted. Report ERR instead of claiming fake JSON.
                        errors += 1
                        reason = source.name + ": ไม่พบเนื้อร้องที่มีเวลาจริง (.LRC, NCN, KAR)"
                        details.append(reason)
                        log("ERR Lyrics " + reason)
                record = export.make_record(root, row, target, lyric_file, vocal_target, mode)
                record["originalCode"] = original_code
                record["codeVerifiedFrom"] = ("pc-and-drive" if online_verified
                                             else "pc-only-unverified")
                if lyric_file:
                    record["lyricsSourceIdentity"] = lyric_fingerprint
                if digest is None:
                    # Path matches never reach here; only new songs are hashed.
                    digest = _source_digest(row, export)
                record["sourceIdentity"] = export.source_marker(source, digest)
                export.append_journal(root, record)
                checkpointed = True
                records.append(record)
                by_path[canonical] = record
                by_sha[digest] = record
                indexed_audio_paths.add(record["audio"]["path"])
                created += 1
                audio_count += 1
                if lyric_file:
                    lyrics_count += 1
                log(f"สร้างสำเร็จ: {record['code']} · {record['audio']['path']}")
            except Exception as exc:
                errors += 1
                reason = f"{source.name}: {type(exc).__name__} — {exc}"
                details.append(reason)
                log("ERR " + reason)
                # Roll back ONLY this iteration's unindexed new artifacts.
                # Never touch source audio or a previously published record.
                if not checkpointed:
                    if new_lyric:
                        new_lyric.unlink(missing_ok=True)
                        new_lyric.with_suffix(".lrc").unlink(missing_ok=True)
                    for built in (committed_vocals, committed_audio):
                        if built is not None:
                            built.unlink(missing_ok=True)
                if CANCEL.is_set():
                    raise RuntimeError("ผู้ใช้ยกเลิก; บันทึกเพลงที่สำเร็จแล้วเพื่อเริ่มใหม่ได้") from exc
            finally:
                for temporary in (staged, staged_vocals):
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
                with LOCK:
                    JOB.update(created=created, skipped=skipped, errors=errors,
                               m4aCount=audio_count, lyricsCount=lyrics_count)
                update(f"ดำเนินการ {idx}/{len(rows)} · ใหม่ {created} · ซ้ำ {skipped} · ERR {errors}", idx)
    finally:
        # Called on normal completion, error, OR user cancellation. Each
        # completed record was journaled and fsynced before this point.
        pending = export.journal_records(root)
        if pending:
            pointer = export.publish_batch(root, pending)
            export.clear_published_journal(root)
            log(f"อัปเดต catalogs + current.json แล้ว · รวม {pointer['songCount']} เพลง")

    result = {
        "created": created, "skipped": skipped, "errors": errors,
        "m4aCount": audio_count, "lyricsCount": lyrics_count,
        "output": str(root), "issues": details[-50:],
        "message": (f"สร้างใหม่ {created} เพลง · ข้ามซ้ำ {skipped} เพลง · ERR {errors} "
                    f"· M4A {audio_count} · Lyrics {lyrics_count} · {root}")
    }
    if not created and not skipped:
        raise RuntimeError(
            "ไม่มีเพลงที่สร้างสำเร็จหรือข้ามซ้ำโดยยืนยันจาก Catalog ได้ · " +
            result["message"] + (" · " + "; ".join(details[-3:]) if details else
                                  " · ตรวจสอบไฟล์ต้นฉบับและ Log"))
    if created == 0 and skipped:
        result["message"] = (
            f"ไม่มีไฟล์ใหม่ · ตรวจยืนยันเพลงเดิมใน Catalog แล้ว {skipped:,} เพลง "
            f"· ERR {errors} · {root}")
    return result


def build_preview(rows, mode):
    """Legacy file-based preview retained only for compatibility.

    The main PC step-3 live player uses live_preview.py and writes no files.
    """
    if len(rows) != 1:
        raise ValueError("การทดลองฟังต้องเลือกหนึ่งเพลง")
    row = rows[0]
    output = PREVIEW_FOLDER / (secrets.token_hex(16) + ".m4a")
    with LOCK:
        JOB["total"] = 1
    try:
        if mode == "instrumental":
            separate_ai(row, output, preview=True)
        else:
            convert(row, output, preview=True)
        ticket = secrets.token_urlsafe(24)
        with LOCK:
            PREVIEWS[ticket] = (output, time.time() + 300)
        update("ทดลองฟังเสร็จแล้ว", 1)
        return {"ticket": ticket, "message": "ทดลองฟังพร้อมแล้ว"}
    except Exception:
        output.unlink(missing_ok=True)
        raise


def execute_job(action, options, started):
    try:
        if action == "scan":
            full = options.get("full") is True
            update("กำลังตรวจคลังเพลงใหม่ทั้งหมด" if full else
                   "กำลังสแกนด่วน · ใช้ดัชนีเดิมที่บันทึกไว้")
            amount = scan_source(full=full)
            stats = dict(LAST_SCAN_STATS)
            log(f"ตรวจพบ {amount:,} เพลง · เพิ่ม {stats.get('added', 0):,} "
                f"· เปลี่ยน {stats.get('changed', 0):,} "
                f"· ลบจากดัชนี {stats.get('removed', 0):,} "
                f"· ใช้ข้อมูลเดิม {stats.get('reused', 0):,}")
            result = {
                "message": (f"สแกนเสร็จแล้ว {amount:,} เพลง · "
                            f"เพิ่ม {stats.get('added', 0):,} · "
                            f"เปลี่ยน {stats.get('changed', 0):,} · "
                            f"ลบจากดัชนี {stats.get('removed', 0):,} · "
                            f"ใช้ดัชนีเดิม {stats.get('reused', 0):,} "
                            "· ยังไม่ได้สร้าง M4A/Lyrics"),
                **stats
            }
        elif action in ("build", "preview"):
            mode = PREFS.get("mode", "original")
            if mode not in ("original", "instrumental"):
                raise ValueError("ประเภทเสียงไม่ถูกต้อง")
            if mode == "instrumental" and not ai_available():
                raise RuntimeError("AI Separation ไม่พร้อม: โมเดลหรือไลบรารีไม่ครบ")
            ids = options.get("ids", [])
            if not isinstance(ids, list):
                raise ValueError("รายการเพลงไม่ถูกต้อง")
            with LOCK:
                rows = [dict(FILE_BY_ID[i]) for i in ids if type(i) is int and i in FILE_BY_ID]
            if not rows:
                raise ValueError("กรุณาเลือกเพลงก่อนสร้าง")
            result = build_library(rows, mode, options) if action == "build" else build_preview(rows, mode)
        elif action == "lyric-groups-scan":
            root = _song_export_module().songs_root(PREFS["workspace"])
            update("กำลังอ่านข้อความจากคลังเพลงที่สร้างแล้ว · ไม่อ่านไฟล์เสียง")
            index = LYRIC_TEXT.scan(
                root, _song_export_module(), cancelled=CANCEL,
                on_progress=lambda detail, done: update(detail, done))
            with LOCK:
                global LYRIC_TEXT_INDEX
                LYRIC_TEXT_INDEX = index
            result = {
                "message": (f"วิเคราะห์ข้อความหัว–ท้ายเพลงเสร็จ {index['songs']:,} เพลง "
                            f"· กลุ่มข้อความ {index['groupCount']:,} กลุ่ม "
                            f"· ข้ามโครงสร้างไม่รองรับ {index['skippedInvalid']:,} เพลง"),
                "songs": index["songs"], "groups": index["groupCount"],
                "skippedInvalid": index["skippedInvalid"],
                "withoutLyrics": index["withoutLyrics"]
            }
        elif action == "lyric-groups-replace":
            with LOCK:
                index = LYRIC_TEXT_INDEX
            if index is None:
                raise ValueError("กรุณากดวิเคราะห์ข้อความก่อนเริ่มแทนที่")
            root = _song_export_module().songs_root(PREFS["workspace"])
            groups = options.get("groups")
            if groups is None and options.get("group"):
                groups = [options["group"]]
            new_text = options.get("replacement")
            search = options.get("search", "")
            planned = LYRIC_TEXT.plan(index, groups, search=search,
                                      replacement=new_text)
            with LOCK:
                JOB["total"] = planned["changedSongs"]
            update(f"กำลังสำรองและแทนที่ {planned['groups']:,} กลุ่ม · "
                   f"{planned['changedLines']:,} บรรทัดใน {planned['changedSongs']:,} เพลง")
            result = LYRIC_TEXT.apply_many(
                root, _song_export_module(), index,
                groups, new_text, LYRIC_TEXT_BACKUPS, search=search,
                expected_count=options.get("expectedCount"),
                cancelled=CANCEL,
                on_progress=lambda detail, done: update(detail, done))
            # Keep LYRIC_TEXT_INDEX: apply_many updates only changed members.
            # All unedited groups remain available for the next batch.
        elif action == "lyric-groups-undo":
            root = _song_export_module().songs_root(PREFS["workspace"])
            update("กำลังตรวจไฟล์หลังแก้ไขและย้อนคืนจากชุดสำรอง")
            result = LYRIC_TEXT.undo(LYRIC_TEXT_BACKUPS, root, options.get("backupId"))
            with LOCK:
                LYRIC_TEXT_INDEX = None
        elif action == "ai-recording-save":
            with LOCK:
                JOB["total"] = 1
            result = save_microphone_recording(options.get("recordingId"))
        elif action == "ai-separate-vocals":
            song_id = options.get("id")
            with LOCK:
                JOB["total"] = 1
            result = separate_ai_lyrics_vocals(song_id)
        elif action == "ai-export":
            with LOCK:
                JOB["total"] = 2
            result = export_ai_lyrics_files(
                options.get("id"),
                include_lyrics=options.get("lyrics") is True,
                include_instrumental=options.get("instrumental") is True)
        elif action == "ai-lyrics":
            song_id = options.get("id")
            with LOCK:
                row = dict(FILE_BY_ID.get(song_id) or {}) if type(song_id) is int else {}
                JOB["total"] = 1
            if not row:
                raise ValueError("ไม่พบเพลงที่ต้องการถอดเนื้อร้อง")
            lang = options.get("language", "th")
            if not ffmpeg_binary():
                raise RuntimeError("ไม่พบ FFmpeg สำหรับเตรียมเสียงให้ Whisper")
            original = Path(row["path"])
            use_vocals = options.get("useSeparatedVocals") is True
            vocals = saved_ai_vocals(row) if use_vocals else None
            if use_vocals and not vocals:
                raise ValueError("ยังไม่มี M4A เสียงร้องแยกที่ใช้ได้ · กดแยกเสียงร้องก่อน")
            if vocals:
                update("ใช้ไฟล์ M4A เสียงร้องที่แยกแล้วสำหรับ Whisper AI")
            draft = AI_LYRICS.transcribe(
                vocals or original, str(row.get("code") or original.stem),
                DATA, RUNTIME, ffmpeg_binary(), CANCEL, update, language=lang,
                draft_source=original)
            update("สร้างเนื้อร้องฉบับร่าง AI แล้ว · ต้องตรวจคำและเวลา", 1)
            result = {
                "message": ("ได้ร่างเนื้อร้อง AI " + str(len(draft["lines"])) +
                            " ช่วงเวลา · ต้องตรวจสอบและกดบันทึกก่อนใช้สร้าง Lyrics"),
                "songId": song_id, "requiresReview": True,
                "segments": len(draft["lines"])
            }
        elif action == "ai-align":
            song_id = options.get("id")
            owner_lyrics = options.get("lyrics")
            with LOCK:
                row = dict(FILE_BY_ID.get(song_id) or {}) if type(song_id) is int else {}
                JOB["total"] = 1
            if not row or Path(row["path"]).suffix.lower() not in EXT_AUDIO:
                raise ValueError("กรุณาเลือกเพลงที่มีเสียงร้องสำหรับจัดเวลา")
            update("กำลังจับคู่คำร้องที่วางกับเวลาจากเสียงเพลง")
            original = Path(row["path"])
            use_vocals = options.get("useSeparatedVocals") is True
            vocals = saved_ai_vocals(row) if use_vocals else None
            if use_vocals and not vocals:
                raise ValueError("ยังไม่มี M4A เสียงร้องแยกที่ใช้ได้ · กดแยกเสียงร้องก่อน")
            draft = AI_LYRICS.load_draft(DATA, original)
            # An older draft from the full mix must not be mistaken for a
            # transcription of the new vocal-only source.
            if vocals and (not draft or
                           draft.get("audioFingerprint") != AI_LYRICS._source_key(vocals)):
                draft = None
            if not draft:
                update("ยังไม่มีร่างจากไฟล์เสียงที่เลือก · กำลังถอดเสียงเพื่อใช้เป็นหลักเวลาจริง")
                ffmpeg = ffmpeg_binary()
                if not ffmpeg:
                    raise RuntimeError("ไม่พบ FFmpeg สำหรับสร้างร่างเสียงร้อง")
                draft = AI_LYRICS.transcribe(
                    vocals or original, str(row.get("code") or original.stem),
                    DATA, RUNTIME, ffmpeg, CANCEL, update,
                    language=options.get("language", "th"), draft_source=original)
            if CANCEL.is_set():
                raise RuntimeError("ผู้ใช้ยกเลิกการจัดเวลาเนื้อเพลง")
            aligned = LYRIC_ALIGNMENT.align_lyrics(owner_lyrics, draft)
            update("จัดเวลาเบื้องต้นแล้ว · ต้องฟังตรวจทุกบรรทัดก่อนบันทึก", 1)
            result = {**aligned, "songId": song_id,
                      "message": aligned["message"] +
                      " · ผลลัพธ์อยู่ในช่องแก้ไขเท่านั้น ยังไม่ได้บันทึกหรืออัปโหลด"}
        elif action == "login":
            update("เปิด Google Login บนเบราว์เซอร์ · รออนุญาตจากเจ้าของบัญชี")
            account = GOOGLE.login(cancelled=CANCEL, on_status=update)
            if not account.get("configured") or not account.get("connected"):
                raise RuntimeError("Google คืนผลลัพธ์ แต่ Song Studio ยังไม่ได้บันทึกสิทธิ์ Google Drive")
            log("Google Login สำเร็จ: " + account.get("email", "(ไม่มีชื่ออีเมล)"))
            result = {"message": "Google Drive เชื่อมต่อแล้วใน Song Studio PC · " +
                      account.get("email", "(ไม่พบชื่อบัญชี)"),
                      "google": account}
        elif action == "logout":
            GOOGLE.logout()
            result = {"message": "ออกจาก Google บน PC เครื่องนี้แล้ว (สิทธิ์ใน Google Account ยังถอนได้จากบัญชี Google)"}
        elif action == "upload":
            export = _song_export_module()
            root = export.songs_root(PREFS["workspace"])
            pointer, _ = export._read_current(root)
            if not pointer:
                raise ValueError("ไม่พบ StageWeb/current.json กรุณาสร้างเพลงก่อนอัปโหลด")
            records = [x for x in export.existing_records(root)
                       if export.record_is_complete(root, x)]
            if len(records) != pointer.get("songCount"):
                raise RuntimeError("ฐานเพลงในเครื่องไม่ครบ · ไม่เผยแพร่ฐานที่อาจเสียหาย")
            registry = _module("code_registry.py", "xstage_code_registry")
            online = _module("online_publish.py", "xstage_online_publish")
            if options.get("create_new_library") is True:
                # Explicit first-library creation only. If already visible,
                # the existing library still wins. No invisible old library
                # is treated as empty without the user's explicit consent.
                snapshot = online.OnlinePublisher(GOOGLE).read_code_registry(
                    allow_missing_root=True)
                remote = snapshot["songs"]
            else:
                snapshot = online.OnlinePublisher(GOOGLE).read_code_registry()
                remote = snapshot["songs"]
            allocator, remapped = reconcile_local_codes(root, records, registry, remote, export)
            if remapped:
                records = [x for x in export.existing_records(root)
                           if export.record_is_complete(root, x)]
                pointer, _ = export._read_current(root)
                if len(records) != pointer.get("songCount"):
                    raise RuntimeError("ปรับรหัสคลัง PC แล้วพบจำนวนเพลงไม่ตรง · หยุดก่อนอัปโหลด")
            log(f"ตรวจรหัสก่อนอัปโหลด: PC {len(records):,} · Google Drive {len(remote):,} "
                f"· ปรับรหัส PC {remapped:,}")
            with LOCK:
                JOB["total"] = len(records)
            update("ตรวจเพลงซ้ำจาก XStageWeb เดิมก่อนอัปโหลด · ไม่ลบเพลงเดิม")
            synced = online.OnlinePublisher(GOOGLE).publish(
                root, records,
                create_new_library=(options.get("create_new_library") is True),
                cancelled=CANCEL,
                on_progress=lambda sent, total:
                update(f"อัปโหลดไฟล์ส่วนตัว {sent:,}/{total:,} bytes"),
                on_batch=lambda batch, total, created, revised:
                update(f"เผยแพร่ฐาน StageWeb ชุดที่ {batch} แล้ว · "
                       f"พร้อมเล่น {total:,} เพลง · เพิ่ม {created:,} · แก้ Lyrics {revised:,}"),
                on_row=lambda done, total, skipped:
                update(f"ตรวจและอัปโหลด {done + skipped:,}/{total + skipped:,} เพลง "
                       "· รวมเพลงที่ข้ามซ้ำโดยตรวจ MD5 แล้ว", done + skipped))
            result = {
                "message": (
                    f"ซิงค์ XStageWeb สำเร็จ · เพลงใหม่ {synced['newSongs']} · "
                    f"ปรับปรุงเนื้อร้อง {synced['updatedSongs']} · "
                    f"ข้ามซ้ำ {synced['duplicates']} · "
                    f"รอตรวจรหัสซ้ำ {synced['conflicts']} · "
                    f"ยังไม่มีเนื้อร้อง {synced['notReady']} · "
                    f"รวมพร้อมเล่น {synced['totalSongs']} เพลง" +
                    (" · ฐานใหม่เผยแพร่แล้ว" if synced['published']
                     else " · ฐานเดิมไม่เปลี่ยน")),
                **synced}
        elif action == "download":
            kind = options.get("kind", "songs")
            update("กำลังอ่าน Catalog จาก Google Drive โดยไม่สร้างคลังใหม่")
            def downloaded_item(done, total):
                with LOCK:
                    JOB["total"] = total
                update(f"ดาวน์โหลดและตรวจ MD5 {done:,}/{total:,} ไฟล์", done)
            result = GOOGLE.download_library(
                PREFS["download"], kind=kind, cancelled=CANCEL,
                on_status=update, on_item=downloaded_item)
            result["message"] = f"ดาวน์โหลด {result['files']} ไฟล์เสร็จแล้ว · {result['path']}"
        elif action == "check-update":
            result = {"message": "ยังไม่มีตัวอัปเดตอัตโนมัติ กรุณาตรวจสอบรุ่น PC Ready ที่ GitHub Releases"}
            update("ตรวจเวอร์ชันเสร็จแล้ว", 1)
        else:
            raise RuntimeError("คำสั่งไม่ถูกต้องหรือยังไม่รองรับ: " + str(action))
        with LOCK:
            build_errors = (
                (action == "build" and result.get("errors", 0) > 0)
                or (action == "upload" and
                    (result.get("conflicts", 0) > 0 or result.get("notReady", 0) > 0)))
            skipped_only = (action == "build" and result.get("created", 0) == 0
                            and result.get("skipped", 0) > 0)
            JOB.update(
                state="error" if build_errors else "success", result=result,
                stage=("ซิงค์บางส่วน · มีเพลงที่ต้องตรวจสอบ" if build_errors and action == "upload" else
                       "สร้างเพลงบางรายการไม่สำเร็จ" if build_errors else
                       "ไม่มีเพลงใหม่ · ยืนยันจาก Catalog แล้ว" if skipped_only else
                       "เสร็จสิ้น"),
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

def validate_build_request(data):
    """Reject impossible builds BEFORE saying that the PC Engine started."""
    ids = data.get("ids")
    if not isinstance(ids, list) or not ids or len(ids) > 100_000:
        raise ValueError("กรุณาเลือกเพลงอย่างน้อย 1 เพลงก่อนสั่งสร้าง")
    if not all(type(item) is int for item in ids):
        raise ValueError("รหัสรายการเพลงไม่ถูกต้อง กรุณาสแกนและเลือกรายการใหม่")
    if not isinstance(data.get("audio_only", False), bool):
        raise ValueError("ประเภทคำสั่งสร้างเพลงไม่ถูกต้อง")
    with LOCK:
        rows = [FILE_BY_ID.get(item) for item in ids]
    if any(row is None for row in rows):
        raise ValueError("รายการเพลงบางรายการไม่อยู่ในฐานปัจจุบัน กรุณาสแกนและเลือกเพลงใหม่")
    from collections import Counter
    formats = Counter(Path(row["path"]).suffix.lower() for row in rows)
    unsupported_count = sum(count for ext, count in formats.items() if ext in EXT_UNSUPPORTED)
    supported_count = len(rows) - unsupported_count
    if supported_count == 0:
        raise ValueError(
            f"ไม่สามารถเริ่มสร้าง: เลือก {len(rows):,} เพลง แต่เป็น NCN ทั้งหมด "
            "ซึ่ง Song Studio PC Engine รุ่นนี้ยังแปลง NCN ไม่ได้ · "
            "กรุณาเลือก MP3/M4A/WAV หรือ MIDI/KAR ที่รองรับ")

    mode = PREFS.get("mode", "original")
    if mode not in ("original", "instrumental"):
        raise ValueError("ประเภทเสียงที่เลือกไม่ถูกต้อง")
    if mode == "instrumental" and not ai_available():
        raise ValueError("AI Separation ไม่พร้อม: โมเดลหรือไลบรารีไม่ครบในแพ็กเกจ")
    if any(Path(row["path"]).suffix.lower() != ".m4a" for row in rows) and not ffmpeg_binary():
        raise ValueError("ไม่พบ FFmpeg ในแพ็กเกจ จึงยังสร้างเพลงจากรูปแบบนี้ไม่ได้")
    if any(Path(row["path"]).suffix.lower() in EXT_MIDI for row in rows) and not sf_available():
        raise ValueError("ยังไม่ได้เลือก SoundFont ที่ใช้งานได้สำหรับเพลง MIDI/KAR")
    for row in rows[:5]:
        if not Path(row["path"]).is_file():
            raise ValueError("ไม่พบไฟล์ต้นฉบับ: " + str(row["path"]))
    workspace = PREFS.get("workspace", "").strip()
    if not workspace:
        raise ValueError("กรุณาเลือกโฟลเดอร์เก็บเพลงก่อนสร้าง")
    output = Path(workspace).expanduser()
    try:
        output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=output):
            pass
    except OSError as exc:
        raise ValueError("โฟลเดอร์เก็บเพลงไม่พร้อมหรือไม่มีสิทธิ์เขียน: " + str(exc)) from exc
    return {"total": len(rows), "unsupported": unsupported_count,
            "supported": supported_count, "formats": dict(formats), "mode": mode}


def start_job(data):
    global JOB
    action = str(data.get("action", ""))
    with LOCK:
        if JOB["state"] == "running":
            raise ValueError("มีงานกำลังดำเนินการอยู่")
    validation = validate_build_request(data) if action == "build" else {}
    if action == "lyric-groups-replace":
        # Reject stale/ambiguous confirmation before starting a background
        # thread that could change many files at once.
        with LOCK:
            snapshot = LYRIC_TEXT_INDEX
        if snapshot is None:
            raise ValueError("ยังไม่ได้วิเคราะห์ข้อความหัว–ท้ายเพลง")
        groups = data.get("groups")
        if groups is None and data.get("group"):
            groups = [data["group"]]
        plan = LYRIC_TEXT.plan(
            snapshot, groups, search=data.get("search", ""),
            replacement=data.get("replacement"))
        if type(data.get("expectedCount")) is not int or data["expectedCount"] != plan["changedLines"]:
            raise ValueError("จำนวนบรรทัดที่จะเปลี่ยนไม่ตรง กรุณาตรวจกลุ่มที่เลือกใหม่")
        if plan["changedSongs"] < 1:
            raise ValueError("ไม่มีเพลงที่ต้องแก้ไข กรุณาเลือกกลุ่มอื่น")
        validation = {"total": plan["changedSongs"], "changedLines": plan["changedLines"]}
    if action == "lyric-groups-undo":
        backup = LYRIC_TEXT.latest_backup(
            LYRIC_TEXT_BACKUPS, _song_export_module().songs_root(PREFS["workspace"]))
        if not backup or data.get("backupId") != backup["id"]:
            raise ValueError("ชุดย้อนคืนไม่ตรงกับการแก้ไขล่าสุด กรุณาตรวจรายการสำรอง")
        validation = {"total": backup["songs"]}
    if action == "login":
        # A Core Preview ZIP intentionally ships without an app-wide Desktop
        # OAuth client. Fail synchronously BEFORE claiming that Google Login
        # started; a Google login elsewhere does not authorize the PC app.
        info = GOOGLE.status()
        if not info["configured"]:
            raise ValueError(
                "Song Studio PC ยังไม่พร้อม Google OAuth: " +
                str(info.get("error") or "ไม่พบ Google Desktop OAuth Client JSON") +
                " · เปิดตั้งค่า > ตัวเลือกขั้นสูง > เลือก Google Desktop OAuth Client JSON "
                "แล้วลอง Google Login ใหม่")
    if action == "ai-recording-save":
        recording_id = data.get("recordingId")
        if not isinstance(recording_id, str) or len(recording_id) > 128:
            raise ValueError("รหัสเสียงบันทึกไม่ถูกต้อง")
        with LOCK:
            uploaded = AI_RECORDINGS_PENDING.get(recording_id)
        if not uploaded or not uploaded.is_file():
            raise ValueError("ไม่พบข้อมูลเสียงที่บันทึกในเครื่อง · กรุณาอัดเสียงใหม่")
        if not ffmpeg_binary():
            raise ValueError("FFmpeg ไม่พร้อมสำหรับแปลงเสียงบันทึกเป็น M4A")
        validation = {"total": 1}
    if action in ("ai-lyrics", "ai-align", "ai-separate-vocals"):
        song_id = data.get("id")
        if type(song_id) is not int or song_id not in FILE_BY_ID:
            raise ValueError("กรุณาเลือกเพลงที่จะใช้ AI ถอดคำร้องก่อน")
        suffix = Path(FILE_BY_ID[song_id]["path"]).suffix.lower()
        if suffix not in EXT_AUDIO:
            raise ValueError("AI ถอดคำร้องได้เฉพาะเพลงที่มีไฟล์เสียงร้องจริง ไม่ใช่ MIDI/NCN ดนตรีล้วน")
        if action in ("ai-lyrics", "ai-align"):
            if not isinstance(data.get("useSeparatedVocals", False), bool):
                raise ValueError("ตัวเลือกเสียงร้องแยกต้องเป็น True/False")
        if action == "ai-separate-vocals":
            if song_id not in AI_IMPORTED:
                raise ValueError("แยกเสียงร้องได้เฉพาะเพลงที่นำเข้าในเมนูสร้างเนื้อร้อง AI")
            if not ai_available() or not ffmpeg_binary():
                raise ValueError("โมเดลแยกเสียงร้อง HTDemucs หรือ FFmpeg ไม่พร้อมในแพ็กเกจนี้")
        if action == "ai-align":
            # Check the user's pasted words before accepting a background job.
            LYRIC_ALIGNMENT._read_owner_lines(data.get("lyrics"))
        # Aligning existing verified-timing draft is possible offline even
        # without re-running Whisper; new songs still require bundled tools.
        has_reference = (action == "ai-align" and
                         AI_LYRICS.load_draft(DATA, Path(FILE_BY_ID[song_id]["path"])))
        if action != "ai-separate-vocals" and not has_reference:
            ready, reason = AI_LYRICS.readiness(RUNTIME)
            if not ready:
                raise ValueError("Whisper AI ยังไม่พร้อม: " + reason)
            if not ffmpeg_binary():
                raise ValueError("ไม่พบ FFmpeg ที่ต้องใช้แปลงไฟล์เสียงสำหรับ AI ในแพ็กเกจ PC Ready")
        validation = {"total": 1}
    with LOCK:
        if JOB["state"] == "running":
            raise ValueError("มีงานกำลังดำเนินการอยู่")
        CANCEL.clear()
        now = time.monotonic()
        JOB = {
            "id": secrets.token_hex(8), "kind": action, "state": "running",
            "stage": "PC Engine รับคำสั่งแล้ว",
            "detail": ("รอเริ่มสร้าง " + str(validation["total"]) + " เพลง" if validation
                       else "กำลังเริ่มต้น"),
            "completed": 0, "total": validation.get("total", 0),
            "elapsed": 0, "eta": None,
            "idleFor": 0, "logs": ["รับคำสั่งสำเร็จ · กำลังเตรียมการประมวลผล"], "result": {},
            "created": 0, "skipped": 0, "errors": 0, "m4aCount": 0, "lyricsCount": 0,
            "started": now, "updated": now
        }
        job_id = JOB["id"]
    try:
        thread = threading.Thread(target=execute_job,
                                  args=(action, data, now), daemon=True,
                                  name="xstage-studio-" + action)
        thread.start()
    except Exception as exc:
        with LOCK:
            JOB["state"] = "error"
            JOB["detail"] = "เริ่ม Thread สร้างเพลงไม่ได้: " + str(exc)
        raise RuntimeError("PC Engine เริ่มงานไม่ได้: " + str(exc)) from exc
    return {"id": job_id, **validation}

def open_picker(kind):
    """Show an actual Windows foreground picker; preserve Unicode/Thai paths.

    A hidden PowerShell host alone can leave FolderBrowserDialog behind
    Microsoft Edge. The bundled PS script supplies a top-most dialog owner,
    and base64-encoded UTF-8 stdout avoids Windows console encoding damage.
    """
    if kind not in ("source", "workspace", "download", "soundfont", "oauth", "vocal"):
        raise ValueError("ประเภทหน้าต่างเลือกโฟลเดอร์/ไฟล์ไม่ถูกต้อง")
    if os.name != "nt":
        raise RuntimeError("หน้าต่างเลือกโฟลเดอร์แบบ PC รองรับเฉพาะ Windows")
    picker = ROOT / "pick_path.ps1"
    if not picker.is_file():
        raise RuntimeError("ไม่พบ pick_path.ps1 กรุณาแตกไฟล์ ZIP รุ่นใหม่ให้ครบก่อน")
    initial = str(PREFS.get("source", "") if kind == "vocal" else PREFS.get(kind) or "")
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

def _preview_lyrics_row(row):
    """Show only actually parsed lyrics, never infer words from MIDI notes.

    AI drafts are displayed separately and never count as verified originals.
    Parsing and MIDI tempo mapping are on-demand, not part of the 93k-song
    catalog scan or HTTP streaming loop.
    """
    source = Path(row["path"])
    is_audio = source.suffix.lower() in EXT_AUDIO
    try:
        lrc, doc, fingerprint = lyrics_package(row)
        if doc and doc.get("lines"):
            status = str(doc.get("sourceFormat") or
                         ("NCN" if row.get("ncn") else "LRC")).upper()
            timed = [{
                "startTime": float(item["startTime"]),
                "endTime": float(item.get("endTime", item["startTime"] + 3)),
                "text": str(item["text"]),
                # True NCN cursor and KAR event positions; no fabricated
                # per-letter animation for ordinary line-timed LRC.
                "characters": [
                    {"text": str(ch["text"]), "startTime": float(ch["startTime"])}
                    for ch in (item.get("characters") or [
                        {"text": unit["text"], "startTime": unit["start"]}
                        for unit in item.get("syllables", [])
                        if isinstance(unit, dict) and "start" in unit and "text" in unit])
                    if isinstance(ch, dict) and "startTime" in ch
                ]
            } for item in doc["lines"][:2500] if str(item.get("text", "")).strip()]
            if timed:
                meta = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
                warnings = list(meta.get("timingWarnings") or [])[:5]
                partial = meta.get("timingComplete") is False
                notice = (f"พบเนื้อร้องจากต้นฉบับ {status} {len(timed)} บรรทัด" +
                          (" · ⚠ เวลาเนื้อร้องบางส่วนไม่ครบ กรุณาตรวจต้นฉบับ LYR/CUR" if partial
                           else ""))
                return {
                    "status": "found", "source": status,
                    "message": notice,
                    "lines": timed, "truncated": len(doc["lines"]) > 2500,
                    "timingComplete": not partial, "timingWarnings": warnings,
                    "aiAvailable": False, "requiresReview": False,
                }
        issue = "ไม่พบไฟล์เนื้อร้องที่มีเวลาตรงกับเพลงนี้"
    except (ValueError, OSError, KeyError) as exc:
        issue = str(exc)
    asr = AI_LYRICS
    draft = asr.load_draft(DATA, source)
    if draft:
        return {
            "status": "ai-draft", "source": "AI · Whisper (ยังไม่ยืนยัน)",
            "message": "พบเนื้อร้องร่างจาก AI · โปรดอ่าน ตรวจคำและเวลา แล้วกดนำไปแก้ไข/บันทึก",
            "lines": draft["lines"][:2500],
            "truncated": len(draft["lines"]) > 2500,
            "aiAvailable": bool(is_audio and asr.available(RUNTIME)),
            "requiresReview": True,
            "draftLrc": draft.get("rawLrc", ""),
            "sourceIssue": issue,
        }
    can_asr = is_audio and asr.available(RUNTIME)
    return {
        "status": "missing", "source": "ไม่พบเนื้อร้อง",
        "message": issue + (
            " · มี AI สำหรับถอดคำร้องจริงเป็นร่างให้ตรวจ" if can_asr else
            " · MIDI ล้วนถอดคำร้องด้วย AI ไม่ได้" if not is_audio else
            " · แพ็กเกจยังไม่มีโมเดล AI ถอดเสียงร้อง"),
        "lines": [], "aiAvailable": bool(can_asr),
        "requiresReview": False, "aiEligible": bool(is_audio),
    }



def _related_preview_files(row, catalog):
    """Use only real indexed files with the exact stem and parent directory."""
    selected = Path(row["path"])
    if not selected.is_file() or selected.is_symlink():
        return []
    candidates = []
    for item in catalog:
        path = Path(item["path"])
        if (path.parent == selected.parent
                and path.stem.casefold() == selected.stem.casefold()
                and path.suffix.lower() in (EXT_AUDIO | EXT_MIDI)
                and path.is_file() and not path.is_symlink()):
            candidates.append(item)
    return sorted(candidates, key=lambda item:
                  (Path(item["path"]).suffix.casefold(), int(item["id"])))


def _preview_source_inventory(row, catalog):
    related = _related_preview_files(row, catalog)
    audio = [item for item in related if Path(item["path"]).suffix.lower() in EXT_AUDIO]
    midi = [item for item in related if Path(item["path"]).suffix.lower() in EXT_MIDI]
    options = []
    if related:
        options.append({
            "value": "auto", "kind": "play",
            "label": ("เสียงต้นฉบับ + MIDI/SoundFont (ผสม)" if audio and midi else
                      "เล่นไฟล์เสียงต้นฉบับ" if audio else "เล่น MIDI/KAR ด้วย SoundFont")
        })
    for item in audio + midi:
        path = Path(item["path"])
        kind = "audio" if item in audio else "midi"
        options.append({"value": f"{kind}:{item['id']}", "kind": "play",
                        "label": ("ทดลองฟังเสียง " if kind == "audio" else "ทดลองฟังดนตรี ") +
                                 path.suffix.upper() + " · " + path.name})
    return options, related


def preview_source_report(song_id):
    """Report observed components, selectable source types, and timed readiness."""
    if type(song_id) is not int:
        raise ValueError("รหัสเพลงสำหรับตรวจไฟล์ไม่ถูกต้อง")
    with LOCK:
        row = dict(FILE_BY_ID.get(song_id) or {})
        catalog = list(FILES)
    if not row:
        raise ValueError("ไม่พบเพลงที่เลือก")
    choices, related = _preview_source_inventory(row, catalog)
    source = Path(row["path"])
    components = []
    def component(kind, path, required=False):
        file = Path(path) if path else None
        exists = bool(file and file.is_file() and not file.is_symlink())
        components.append({"type": kind, "name": file.name if file else "—",
                           "found": exists, "required": bool(required),
                           "size": file.stat().st_size if exists else 0})
        return exists
    for item in related:
        path = Path(item["path"])
        component("เพลง " + path.suffix.upper(), path)
    trio = row.get("ncn") or NCN.resolve_companions(source)
    if trio:
        if not related:
            component("Song · MIDI", trio.get("midi"), True)
        lyr_ok = component("Lyrics · LYR", trio.get("lyrics"), True)
        cur_ok = component("Cursor · CUR", trio.get("cursor"), True)
        choices.extend([
            {"value": "inspect:lyr", "kind": "inspect", "label": "ตรวจเนื้อร้อง LYR"}
            for _ in range(1) if lyr_ok])
        choices.extend([
            {"value": "inspect:cur", "kind": "inspect", "label": "ตรวจเวลา CUR"}
            for _ in range(1) if cur_ok])
    else:
        lrc = _matching_lrc(source)
        if lrc:
            if component("Lyrics · LRC", lrc):
                choices.append({"value": "inspect:lrc", "kind": "inspect",
                                "label": "ตรวจเนื้อร้องและเวลา LRC"})
        if source.suffix.lower() in EXT_MIDI:
            embedded_ok = False
            try:
                embedded_ok = bool(NCN.kar_document(source, source.stem)["lines"])
            except (ValueError, OSError):
                pass
            components.append({"type": "เนื้อร้องฝังใน MIDI/KAR",
                               "name": source.name, "found": embedded_ok,
                               "required": False, "size": source.stat().st_size})
            if embedded_ok:
                choices.append({"value": "inspect:embedded", "kind": "inspect",
                                "label": "ตรวจเนื้อร้องฝังใน MIDI/KAR"})
    proof = _preview_lyrics_row(row)
    status = proof.get("status", "missing")
    return {
        "id": song_id, **preview_song_identity(row), "options": choices,
        "components": components, "timedLyricsReady": status == "found",
        "proofSource": proof.get("source", ""), "proofMessage": proof.get("message", ""),
        "complete": bool(related and status == "found" and
                         proof.get("timingComplete", True) and
                         all(item["found"] for item in components if item["required"])),
    }


def preview_inspect(song_id, choice):
    """Allow inspecting a real text/cursor component without claiming it is audio."""
    if type(choice) is not str or choice not in ("inspect:lyr", "inspect:cur",
                                                  "inspect:lrc", "inspect:embedded"):
        raise ValueError("ชนิดไฟล์สำหรับตรวจไม่ถูกต้อง")
    with LOCK:
        row = dict(FILE_BY_ID.get(song_id) or {})
    if not row:
        raise ValueError("ไม่พบเพลงที่เลือก")
    src = Path(row["path"])
    trio = row.get("ncn") or NCN.resolve_companions(src)
    if choice in ("inspect:lyr", "inspect:cur"):
        file = Path((trio or {}).get("lyrics" if choice == "inspect:lyr" else "cursor") or "")
        if not trio or not file.is_file():
            raise ValueError("ไม่พบไฟล์ประกอบ NCN ชนิดนี้")
        if choice == "inspect:lyr":
            lines = NCN._decode_text(file.read_bytes()).splitlines()
            if len(lines) < 5:
                raise ValueError("LYR ไม่มีส่วนหัวหรือเนื้อร้อง")
            return {"kind": choice, "file": file.name, "verified": True,
                    "message": "อ่านเนื้อร้อง LYR ได้ แต่ต้องตรวจ CUR + MIDI จึงยืนยันเวลาได้",
                    "text": "\n".join(lines[4:])[:15000]}
        raw = file.read_bytes()
        if len(raw) % 2:
            if raw[-1:] != b"\xff":
                raise ValueError("CUR ไม่สมบูรณ์: จำนวนไบต์ไม่ถูกต้อง")
            raw = raw[:-1]
        return {"kind": choice, "file": file.name, "verified": True,
                "message": f"อ่าน Cursor ได้ {len(raw)//2:,} ตำแหน่ง · ต้องตรวจคู่กับ MIDI และ LYR",
                "text": ""}
    if choice == "inspect:lrc":
        lrc = _matching_lrc(src)
        if not lrc:
            raise ValueError("ไม่มีไฟล์ LRC ที่ตรงรหัสเพลงนี้")
        text = NCN._decode_text(lrc.read_bytes())
        if not _song_export_module().lrc_to_json(text, src.stem).get("lines"):
            raise ValueError("LRC ไม่มี timestamp สำหรับการแสดงคาราโอเกะ")
        return {"kind": choice, "file": lrc.name, "verified": True,
                "message": "อ่าน LRC พร้อม timestamp ได้", "text": text[:15000]}
    if src.suffix.lower() not in EXT_MIDI:
        raise ValueError("เพลงที่เลือกไม่ได้เป็น MIDI/KAR")
    doc = NCN.kar_document(src, src.stem)
    return {"kind": choice, "file": src.name, "verified": True,
            "message": f"อ่านเนื้อร้องฝังใน MIDI/KAR ได้ {len(doc['lines'])} บรรทัด",
            "text": "\n".join(line["text"] for line in doc["lines"])[:15000]}



def available_vocal_sources(search="", offset=0, limit=40):
    """Only show songs imported to the independent AI Lyrics workspace."""
    with LOCK:
        matches = list(AI_IMPORTED.values())
    query = str(search or "").casefold()
    if query:
        matches = [row for row in matches if query in
                   (str(row["title"]) + " " + str(row["artist"]) + " " +
                    str(row["code"])).casefold()]
    page = [{**row, **preview_song_identity(row)}
            for row in matches[offset:offset + limit]]
    return {"rows": page, "total": len(matches)}


def ai_lyrics_draft(song_id):
    """AI draft stays in private AppData until the owner explicitly approves."""
    with LOCK:
        row = dict(FILE_BY_ID.get(song_id) or {}) if type(song_id) is int else {}
    if not row or Path(row["path"]).suffix.lower() not in EXT_AUDIO:
        raise ValueError("ต้องเลือกเพลงที่เป็นไฟล์เสียงสำหรับถอดคำร้อง")
    draft = AI_LYRICS.load_draft(DATA, Path(row["path"]))
    ready, reason = AI_LYRICS.readiness(RUNTIME)
    if ready and not ffmpeg_binary():
        ready, reason = False, "ไม่พบ FFmpeg ในแพ็กเกจ PC Ready"
    vocals = saved_ai_vocals(row)
    return {
        "id": song_id, **preview_song_identity(row),
        "available": ready, "aiProblem": reason,
        "separationAvailable": ai_available() and bool(ffmpeg_binary()),
        "separatedVocals": str(vocals) if vocals else None,
        "hasDraft": bool(draft), "draft": draft,
        "approvedLrc": AI_LYRICS.replace_music_interlude_label(
            NOTES.get(row["path"], {}).get("lyrics", ""))
    }


def approve_ai_lyrics(song_id, lrc_text):
    """Require explicit user review and strict timestamps before saving."""
    if type(song_id) is not int or not isinstance(lrc_text, str):
        raise ValueError("ข้อมูลเนื้อร้องไม่ถูกต้อง")
    if len(lrc_text) > 100000 or not lrc_text.strip():
        raise ValueError("เนื้อร้องว่างหรือมีขนาดใหญ่เกินกำหนด")
    # Save the AI interlude label consistently when the owner approves a draft.
    lrc_text = AI_LYRICS.replace_music_interlude_label(lrc_text)
    with LOCK:
        row = dict(FILE_BY_ID.get(song_id) or {})
    if not row or Path(row["path"]).suffix.lower() not in EXT_AUDIO:
        raise ValueError("ต้องเลือกเพลงเสียงร้องที่อยู่ในรายการสแกน")
    if not AI_LYRICS.load_draft(DATA, Path(row["path"])):
        raise ValueError("ยังไม่มีฉบับร่าง AI สำหรับเพลงนี้ กรุณาให้ AI ถอดเสียงก่อน")
    # lrc_to_json ignores invalid lines; reject invalid non-metadata content
    # instead of silently publishing a partial transcription.
    import re
    stamp = re.compile(r"^\[(\d{1,3}):(\d{2})(?:\.(\d{1,3}))?\](.+)$")
    starts = []
    count = 0
    for raw in lrc_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.match(r"^\[(ti|ar|al|by|offset):", line, re.I):
            continue
        match = stamp.match(line)
        if not match or int(match.group(2)) >= 60:
            raise ValueError("รูปแบบ LRC ไม่ถูกต้อง: " + line[:70])
        seconds = int(match.group(1))*60 + int(match.group(2))
        seconds += int((match.group(3) or "0").ljust(3, "0"))/1000
        if starts and seconds < starts[-1]:
            raise ValueError("เวลาคำร้องต้องเรียงจากน้อยไปมาก")
        starts.append(seconds)
        count += 1
    if not count:
        raise ValueError("ต้องมีเนื้อร้องพร้อม timestamp อย่างน้อยหนึ่งบรรทัด")
    doc = _song_export_module().lrc_to_json(lrc_text, str(row.get("code") or ""))
    if len(doc["lines"]) != count:
        raise ValueError("ตรวจคำร้องกับเวลา LRC ไม่ผ่าน โปรดแก้ไขก่อนบันทึก")
    with LOCK:
        notes = NOTES.setdefault(row["path"], {})
        notes["lyrics"] = lrc_text
        save_json(NOTES_FILE, NOTES)
    return {"ok": True, "lines": count, "message": "บันทึก LRC ที่ผู้ใช้ตรวจแก้แล้วในข้อมูลเพลงเรียบร้อย"}



def preview_lyrics(song_id):
    if type(song_id) is not int:
        raise ValueError("รหัสเพลงสำหรับแสดงเนื้อร้องไม่ถูกต้อง")
    with LOCK:
        row = dict(FILE_BY_ID.get(song_id) or {})
    if not row:
        raise ValueError("ไม่พบเพลงที่เลือกในฐานข้อมูลที่สแกน")
    return {"id": song_id, **preview_song_identity(row), **_preview_lyrics_row(row)}


def prepare_live_preview(song_id, music_volume=0.8, synth_volume=0.8, source_choice="auto"):
    """Issue one-use ticket for streamed preview; no output audio files."""
    if type(song_id) is not int:
        raise ValueError("กรุณาเลือกเพลงสำหรับทดลองฟัง")
    if JOB.get("state") == "running":
        raise ValueError("มีงานสร้างเพลงกำลังทำงานอยู่ กรุณารอให้เสร็จก่อน")
    with LOCK:
        row = FILE_BY_ID.get(song_id)
        catalog = list(FILES) + list(AI_IMPORTED.values())
    if row is None:
        raise ValueError("ไม่พบเพลงที่เลือกในรายการที่สแกน")
    spec = importlib.util.spec_from_file_location("xstage_live_preview", ROOT / "live_preview.py")
    if not spec or not spec.loader:
        raise RuntimeError("แพ็กเกจไม่มี Live Preview Engine")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    options, related = _preview_source_inventory(row, catalog)
    allowed = {item["value"] for item in options if item["kind"] == "play"}
    if source_choice not in allowed and source_choice != "ai-vocals":
        raise ValueError("ประเภทไฟล์ที่เลือกไม่มีอยู่จริงสำหรับเพลงนี้")
    audio, midi = mod.matching_sources(row, catalog)
    if source_choice == "ai-vocals":
        if song_id not in AI_IMPORTED:
            raise ValueError("เสียงร้องแยกใช้ได้เฉพาะเพลงที่นำเข้าในหน้า AI")
        audio = saved_ai_vocals(row)
        midi = None
        if not audio:
            raise ValueError("ไม่มีไฟล์เสียงร้องที่แยกแล้วสำหรับทดลองฟัง")
    elif source_choice != "auto":
        category, raw_id = source_choice.split(":", 1)
        match = next((item for item in related if item["id"] == int(raw_id)), None)
        if not match:
            raise ValueError("ไม่พบไฟล์ที่เลือกในรายการเพลงที่สแกน")
        chosen = Path(match["path"])
        audio, midi = ((chosen, None) if category == "audio" else (None, chosen))
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
    stream_id = secrets.token_urlsafe(30)
    selected_font = Path(PREFS["soundfont"]) if midi else None
    stream = mod.LiveControls(backing, sound, selected_font, PREFS.get("midi_preset", "balanced"))
    with LOCK:
        # Keep control session separate from the one-use playback ticket.
        # Do not mutate a stream after it is stopped or its ticket expires.
        for key, value in list(LIVE_TICKETS.items()):
            if value["expires"] <= time.monotonic():
                LIVE_TICKETS.pop(key, None)
        for key, value in list(LIVE_SESSIONS.items()):
            if value["expires"] <= time.monotonic() and not value["controls"].active:
                LIVE_SESSIONS.pop(key, None)
        LIVE_SESSIONS[stream_id] = {
            "controls": stream, "expires": time.monotonic() + 3600,
            "midi": bool(midi), "started": False
        }
        LIVE_TICKETS[ticket] = dict(audio=audio, midi=midi,
                                    soundfont=selected_font, session=stream_id,
                                    expires=time.monotonic() + 90)
    return {
        "ticket": ticket, "stream_id": stream_id,
        **preview_song_identity(row),
        "source_choice": source_choice,
        "has_backing": bool(audio), "has_midi": bool(midi),
        "original_is_midi": bool(midi and not audio),
        "mixed": bool(midi),
        "message": ("กำลังเล่นเสียงต้นฉบับพร้อม SoundFont ที่เลือก" if audio and midi
                    else "กำลังเล่น MIDI เดิมด้วย SoundFont มาตรฐาน + SoundFont ที่เลือก" if midi
                    else "เล่นเสียงดนตรีต้นฉบับ (ไม่มี MIDI สำหรับ SoundFont)")
    }


def job_snapshot():
    with LOCK:
        job = dict(JOB)
    if job["state"] == "running":
        elapsed = max(0, time.monotonic() - job["started"])
        job["elapsed"] = elapsed
        job["idleFor"] = round(time.monotonic() - job["updated"])
        if job["total"] > 0 and 0 < job["completed"] <= job["total"]:
            job["eta"] = (elapsed / job["completed"]) * (job["total"] - job["completed"])
        else:
            job["eta"] = None
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
                    session_id = request["session"]
                    with LOCK:
                        live_session = LIVE_SESSIONS.get(session_id)
                        if not live_session:
                            raise RuntimeError("เซสชันเสียงหมดอายุ")
                        live_session["started"] = True
                        controls = live_session["controls"]
                    generator = live.stream_mp3(
                        audio=request["audio"], midi=request["midi"],
                        soundfont=request["soundfont"], ffmpeg=ffmpeg_binary(),
                        runtime=RUNTIME, controls=controls
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
                    with LOCK:
                        if request:
                            LIVE_SESSIONS.pop(request.get("session", ""), None)
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
                    "google": GOOGLE.status(),
                    "update": {"status": "unavailable"}})
            elif path == "/api/history":
                with LOCK:
                    self._json({"events": HISTORY.list_events(HISTORY_FILE)})
            elif path == "/api/code-registry":
                self._json(code_registry_preview())
            elif path == "/api/environment":
                google = GOOGLE.status()
                self._json({"Python Runtime": True, "FFmpeg": bool(ffmpeg_binary()),
                    "SoundFont": sf_available(), "FluidSynth": bool(fluidsynth_binary()),
                    "Local file mode": True,
                    "Google OAuth Client configured": google["configured"],
                    "Google Drive signed in": google["connected"],
                    "AI separation": ai_available(),
                    "AI lyrics transcription": AI_LYRICS.available(RUNTIME)})
            elif path == "/api/songs/ids":
                self._json({"ids": [x["id"] for x in visible_files(query.get("search", [""])[0])]})
            elif path == "/api/songs":
                rows = visible_files(query.get("search", [""])[0])
                if query.get("audio_only", ["0"])[0] == "1":
                    rows = [row for row in rows if
                            Path(row["path"]).suffix.lower() in EXT_AUDIO]
                limit = max(1, min(500, int(query.get("limit", ["100"])[0])))
                offset = max(0, int(query.get("offset", ["0"])[0]))
                page_rows = rows[offset:offset + limit]
                # Enrich only the small preview page, never the full catalog.
                if query.get("preview_identity", ["0"])[0] == "1":
                    page_rows = [{**item, **preview_song_identity(item)}
                                 for item in page_rows]
                self._json({"rows": page_rows, "total": len(rows)})
            elif path == "/api/lyric-groups":
                with LOCK:
                    snapshot = LYRIC_TEXT_INDEX
                if snapshot is None:
                    raise ValueError("ยังไม่มีผลวิเคราะห์ กรุณากดวิเคราะห์ข้อความหัว–ท้ายเพลงก่อน")
                position = query.get("position", ["first"])[0]
                offset = max(0, int(query.get("offset", ["0"])[0]))
                limit = max(1, min(100, int(query.get("limit", ["40"])[0])))
                only_repeats = query.get("repeats", ["1"])[0] != "0"
                self._json(LYRIC_TEXT.list_groups(snapshot, position,
                    search=query.get("search", [""])[0], offset=offset,
                    limit=limit, repeats_only=only_repeats))
            elif path == "/api/lyric-groups-preview":
                with LOCK:
                    snapshot = LYRIC_TEXT_INDEX
                if snapshot is None:
                    raise ValueError("กลุ่มข้อความหมดอายุ กรุณาวิเคราะห์ใหม่")
                self._json(LYRIC_TEXT.preview(
                    snapshot, query.get("group", [""])[0],
                    search=query.get("search", [""])[0]))
            elif path == "/api/lyric-groups-backup":
                root = _song_export_module().songs_root(PREFS["workspace"])
                self._json({"latest": LYRIC_TEXT.latest_backup(LYRIC_TEXT_BACKUPS, root)})
            elif path == "/api/vocal-songs":
                search = query.get("search", [""])[0]
                offset = max(0, int(query.get("offset", ["0"])[0]))
                limit = max(1, min(60, int(query.get("limit", ["30"])[0])))
                self._json(available_vocal_sources(search, offset, limit))
            elif path == "/api/ai-lyrics-draft":
                try:
                    song_id = int(query.get("id", [""])[0])
                except ValueError as exc:
                    raise ValueError("กรุณาเลือกเพลงเสียงร้อง") from exc
                self._json(ai_lyrics_draft(song_id))
            elif path == "/api/preview-sources":
                try:
                    song_id = int(query.get("id", [""])[0])
                except ValueError as exc:
                    raise ValueError("กรุณาเลือกเพลงสำหรับตรวจไฟล์") from exc
                self._json(preview_source_report(song_id))
            elif path == "/api/preview-inspect":
                try:
                    song_id = int(query.get("id", [""])[0])
                except ValueError as exc:
                    raise ValueError("กรุณาเลือกเพลงสำหรับตรวจไฟล์") from exc
                self._json(preview_inspect(song_id, query.get("kind", [""])[0]))
            elif path == "/api/preview-lyrics":
                try:
                    song_id = int(query.get("id", [""])[0])
                except ValueError as exc:
                    raise ValueError("ต้องระบุรหัสเพลงสำหรับตรวจเนื้อร้อง") from exc
                self._json(preview_lyrics(song_id))
            elif path.startswith("/api/song/"):
                row = FILE_BY_ID.get(int(path.rsplit("/", 1)[-1]))
                if row is None:
                    self._deny("ไม่พบเพลง", 404)
                else:
                    self._json({**row, **preview_song_identity(row),
                                "lyrics_edit": lyrics_text(row)})
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
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (ValueError, TypeError):
            self._deny("ขนาดข้อมูลไม่ถูกต้อง", 413)
            return
        path = urllib.parse.urlsplit(self.path).path
        if path == "/api/ai-recording-upload":
            if not 1000 <= length <= MAX_AI_RECORDING_BYTES:
                self._deny("เสียงบันทึกต้องมีขนาดระหว่าง 1 KB และ 64 MB", 413)
                return
            try:
                self.connection.settimeout(90)
                result = stage_microphone_recording(
                    self.rfile, length, self.headers.get("Content-Type", ""))
                self._json(result)
            except (ValueError, OSError, TimeoutError) as exc:
                self._deny(str(exc), 400)
            return
        if length > 1048576 or length <= 0:
            self._deny("ขนาดคำสั่งไม่ถูกต้อง", 413)
            return
        try:
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("คำสั่งไม่ถูกต้อง")
            path = urllib.parse.urlsplit(self.path).path
            if path == "/api/config":
                previous_preferences = HISTORY.safe_preferences(PREFS)
                previous_catalog_key = (PREFS["source"], PREFS["workspace"])
                for key, value in payload.items():
                    if key not in PREFS or not isinstance(value, str):
                        continue
                    if key == "oauth":
                        candidate = value.strip()
                        if candidate:
                            # Retain existing client when UI sends the current
                            # path; import only when a user selected a new file.
                            if Path(candidate) != Path(google_client_path()):
                                GOOGLE.import_client(candidate)
                        # Empty inputs do NOT remove a bundled or saved client.
                        PREFS[key] = google_client_path()
                    else:
                        PREFS[key] = value[:2048]
                save_json(PREFS_FILE, PREFS)
                with LOCK:
                    HISTORY.append(HISTORY_FILE, "settings", "preferences",
                                   previous_preferences, PREFS)
                if previous_catalog_key != (PREFS["source"], PREFS["workspace"]):
                    with LOCK:
                        global LYRIC_TEXT_INDEX
                        LYRIC_TEXT_INDEX = None
                    restore_song_catalog()
                self._json({"preferences": dict(PREFS), "soundfonts": font_list(),
                            "google": GOOGLE.status()})
            elif path == "/api/history/restore":
                if JOB.get("state") == "running":
                    raise ValueError("มีงานกำลังประมวลผล · หยุดก่อนคืนค่าประวัติ")
                with LOCK:
                    event = HISTORY.get_event(HISTORY_FILE, payload.get("id"))
                    if event["kind"] == "settings":
                        old = HISTORY.safe_preferences(PREFS)
                        selected = HISTORY.safe_preferences(event["before"])
                        # Never restore OAuth identity or tokens from history.
                        previous_catalog_key = (PREFS["source"], PREFS["workspace"])
                        PREFS.update(selected)
                        save_json(PREFS_FILE, PREFS)
                        HISTORY.append(HISTORY_FILE, "settings", "restore", old, PREFS)
                        needs_scan = previous_catalog_key != (PREFS["source"], PREFS["workspace"])
                    elif event["kind"] == "song":
                        target = event["target"]
                        row = next((r for r in FILE_BY_ID.values()
                                    if r.get("path") == target), None)
                        if row is None:
                            raise ValueError("ไม่พบเพลงต้นฉบับในรายการที่สแกน · ไม่คืนค่าทับเพลงอื่น")
                        current = dict(NOTES.get(target, {}))
                        restored = HISTORY.safe_song(event["before"])
                        NOTES[target] = {**current, **restored}
                        save_json(NOTES_FILE, NOTES)
                        HISTORY.append(HISTORY_FILE, "song", target, current, NOTES[target])
                        row["title"], row["artist"] = restored["title"], restored["artist"]
                        needs_scan = False
                    else:
                        raise ValueError("ประวัติไม่รองรับการคืนค่า")
                if needs_scan:
                    restore_song_catalog()
                self._json({"ok": True, "preferences": dict(PREFS),
                            "message": "คืนค่าจากประวัติและบันทึกอัตโนมัติแล้ว"})
            elif path == "/api/lyric-groups-plan":
                with LOCK:
                    snapshot = LYRIC_TEXT_INDEX
                if snapshot is None:
                    raise ValueError("กรุณาวิเคราะห์ข้อความหัว–ท้ายเพลงก่อน")
                self._json(LYRIC_TEXT.plan(
                    snapshot, payload.get("groups"), search=payload.get("search", ""),
                    replacement=payload.get("replacement")))
            elif path == "/api/ai-import":
                self._json(import_ai_audio(payload.get("path")))
            elif path == "/api/folder-picker":
                kind = payload.get("kind", "")
                if kind not in ("source", "workspace", "download", "soundfont", "oauth", "vocal"):
                    raise ValueError("ประเภทไฟล์ไม่ถูกต้อง")
                self._json({"path": open_picker(kind)})
            elif path == "/api/live-preview":
                self._json(prepare_live_preview(
                    payload.get("id"), payload.get("music_volume", .8),
                    payload.get("synth_volume", .8), payload.get("source_choice", "auto")))
            elif path == "/api/live-control":
                session_id = payload.get("stream_id", "")
                with LOCK:
                    active = LIVE_SESSIONS.get(session_id)
                if not active or active["expires"] < time.monotonic() or active["controls"].cancelled.is_set():
                    raise ValueError("เสียงทดลองฟังหยุดไปแล้ว กรุณากดเล่นใหม่")
                changes = {key: payload[key] for key in
                           ("music_volume", "synth_volume", "soundfont", "preset")
                           if key in payload}
                if "soundfont" in changes and not active["midi"]:
                    # No MIDI to resynthesize; audio-only source is unchanged.
                    changes.pop("soundfont")
                values = active["controls"].update(**changes)
                self._json({"ok": True, "music_volume": values[0],
                            "synth_volume": values[1], "preset": values[3]})
            elif path == "/api/live-stop":
                session_id = payload.get("stream_id", "")
                with LOCK:
                    active = LIVE_SESSIONS.pop(session_id, None)
                    for key, value in list(LIVE_TICKETS.items()):
                        if value.get("session") == session_id:
                            LIVE_TICKETS.pop(key, None)
                if active:
                    active["controls"].cancelled.set()
                self._json({"ok": True})
            elif path == "/api/estimate":
                ids = payload.get("ids", [])
                if not isinstance(ids, list):
                    raise ValueError("รายการเพลงไม่ถูกต้อง")
                matches = [FILE_BY_ID[i] for i in ids if isinstance(i, int) and i in FILE_BY_ID]
                size = sum(r["size"] for r in matches)
                workspace = Path(PREFS["workspace"]).expanduser()
                workspace.mkdir(parents=True, exist_ok=True)
                free = shutil.disk_usage(workspace).free
                # Previous estimate incorrectly required 3x ALL input bytes.
                # This app processes one source at a time in a separate folder,
                # without first copying 93,000 originals to disk. Reject only
                # genuinely too-small free space, and check per-track capacity
                # during the actual build. A whole-library forecast is advisory.
                minimum = 256 * 1024 ** 2 if matches else 0
                projected = sum(
                    max(1 * 1024 ** 2, min(r["size"] * 2, 256 * 1024 ** 2))
                    for r in matches if Path(r["path"]).suffix.lower() != ".ncn"
                )
                self._json({
                    "songs": len(matches), "bytes": size,
                    "freeBytes": free, "estimatedOutputBytes": projected,
                    "enoughDisk": free >= minimum,
                    "spaceWarning": projected > free,
                    "warning": len(matches) > 200 or projected > free,
                    "unsupported": sum(Path(r["path"]).suffix.lower() == ".ncn"
                                       for r in matches),
                    "formats": dict(__import__("collections").Counter(
                        Path(r["path"]).suffix.lower() for r in matches))
                })
            elif path == "/api/vocal-import":
                self._json(import_vocal_sources())
            elif path == "/api/vocal-remove":
                self._json(remove_vocal_source(payload.get("id")))
            elif path == "/api/ai-lyrics-approve":
                self._json(approve_ai_lyrics(payload.get("id"), payload.get("lrc")))
            elif path == "/api/google-login-focus":
                # Reopen the exact in-progress Google OAuth URL. The browser
                # never receives the OAuth URL or the refresh token via our API.
                self._json(GOOGLE.show_pending_login())
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
                before_edit = {"title": value.get("title", row.get("title", "")),
                               "artist": value.get("artist", row.get("artist", "")),
                               "lyrics": value.get("lyrics", lyrics_text(row))}
                for key in ("title", "artist", "lyrics"):
                    if isinstance(payload.get(key), str):
                        value[key] = payload[key][:100000]
                row["title"] = value.get("title", row["title"])
                row["artist"] = value.get("artist", row["artist"])
                save_json(NOTES_FILE, NOTES)
                with LOCK:
                    HISTORY.append(HISTORY_FILE, "song", row["path"], before_edit, value)
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
    try:
        count = restore_song_catalog()
        if count:
            JOB["detail"] = f"โหลดดัชนีเพลงเดิมแล้ว {count:,} เพลง · กดสแกนด่วนเพื่ออัปเดต"
    except (OSError, ValueError) as exc:
        JOB["detail"] = "ไม่สามารถโหลดดัชนีเดิม: " + str(exc)
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
                # Full-size PC workspace on first launch. Reuse OS screen size
                # rather than a fixed 1280x720 browser window.
                flags = ["--new-window", "--start-maximized"]
                if os.name == "nt":
                    try:
                        import ctypes
                        cx = max(1280, ctypes.windll.user32.GetSystemMetrics(0))
                        cy = max(720, ctypes.windll.user32.GetSystemMetrics(1))
                        flags += [f"--window-size={cx},{cy}", "--window-position=0,0"]
                    except (AttributeError, OSError):
                        pass
                subprocess.Popen([str(edge), *flags, "--app=" + url],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                webbrowser.open(url)
        except Exception:
            webbrowser.open(url)
        server.serve_forever(poll_interval=0.25)

if __name__ == "__main__":
    main()
