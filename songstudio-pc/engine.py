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
STATUS_VERSION = "0.3.68" if READY_BUNDLE else "0.2.8-Source-Preview"
STATUS_BUILD = "368" if READY_BUNDLE else "208-SRC"
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
EXT_AUDIO = {".mp3", ".m4a", ".mp4", ".aac", ".wav", ".wma", ".flac", ".ogg", ".oga",
             ".webm", ".avi", ".mkv", ".mov", ".mpg", ".mpeg", ".dat", ".vob",
             ".wmv", ".flv", ".m4v", ".3gp", ".ts", ".m2ts", ".aiff", ".aif"}
EXT_MIDI = {".mid", ".midi", ".kar"}
EXT_UNSUPPORTED = {".ncn"}
PREFS_FILE = DATA / "preferences.json"
NOTES_FILE = DATA / "song-metadata.json"
LOCK = threading.RLock()
TOKEN = secrets.token_urlsafe(40)
PORT = None
BROWSER_PROCESS = None
JOB = {
    "id": "", "kind": "", "state": "idle", "stage": "พร้อมใช้งาน",
    "detail": "", "completed": 0, "total": 0, "elapsed": 0,
    "eta": None, "idleFor": 0, "logs": [], "result": {},
    "created": 0, "skipped": 0, "errors": 0, "m4aCount": 0, "lyricsCount": 0
}
CANCEL = threading.Event()
JOB_THREAD = None
PROCESS = None
ACTIVE_JOBS = {}
_WORKER_LOCAL = threading.local()
_CPU_SAMPLE = None
MAX_PARALLEL_JOBS = 3

# Each worker sees its own job state, cancellation event and subprocess.
# The legacy JOB/CANCEL names continue to represent the most recently started
# job for old API consumers, while workers never overwrite one another.
def worker_job():
    return getattr(_WORKER_LOCAL, "job", JOB)

def worker_cancel():
    return getattr(_WORKER_LOCAL, "cancel", CANCEL)

def worker_prefs():
    # A worker keeps its source, output and SoundFont preferences from launch.
    # A later UI change cannot silently redirect a running conversion.
    return getattr(_WORKER_LOCAL, "prefs", PREFS)

def set_worker_process(proc):
    global PROCESS
    job_id = getattr(_WORKER_LOCAL, "id", None)
    with LOCK:
        if job_id and job_id in ACTIVE_JOBS:
            ACTIVE_JOBS[job_id]["process"] = proc
        else:
            PROCESS = proc

def any_active_jobs():
    with LOCK:
        return any(item["thread"] and item["thread"].is_alive()
                   for item in ACTIVE_JOBS.values())

def job_group(action):
    if action in ("scan", "duplicates-scan", "duplicates-apply", "build", "xsk-stream", "json-pro-export",
                  "created-xsk", "pc-export", "download", "lyric-groups-scan",
                  "lyric-groups-replace", "lyric-groups-undo"):
        return "library"
    if action in ("ai-lyrics", "ai-align", "ai-separate-vocals",
                  "ai-export", "preview"):
        return "audio-ai"
    if action in ("upload", "upload-folder", "upload-soundfont",
                  "login", "logout", "check-update", "download-update"):
        return "network"
    if action == "install-update":
        return "installer"
    return "exclusive"

def cpu_busy_percent():
    """Best-effort Windows system-wide CPU utilization from two passive samples."""
    global _CPU_SAMPLE
    if os.name != "nt":
        try:
            return min(100, round(os.getloadavg()[0] / max(1, os.cpu_count() or 1) * 100))
        except (AttributeError, OSError):
            return None
    try:
        import ctypes
        class FileTime(ctypes.Structure):
            _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]
        idle, kernel, user = FileTime(), FileTime(), FileTime()
        if not ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        val = lambda t: (int(t.high) << 32) | int(t.low)
        current = (val(idle), val(kernel) + val(user))
        with LOCK:
            previous = _CPU_SAMPLE
            _CPU_SAMPLE = current
        if previous:
            total_delta = current[1] - previous[1]
            idle_delta = current[0] - previous[0]
            if total_delta > 0:
                return max(0, min(100, round((1-idle_delta/total_delta)*100)))
    except (AttributeError, OSError, TypeError):
        pass
    return None

def resource_snapshot():
    """Lightweight physical-memory/capacity snapshot; no extra packages."""
    cores = max(1, os.cpu_count() or 1)
    available = None
    total = None
    if os.name == "nt":
        try:
            import ctypes
            class MemStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("memoryLoad", ctypes.c_ulong),
                            ("totalPhys", ctypes.c_ulonglong),
                            ("availPhys", ctypes.c_ulonglong),
                            ("totalPageFile", ctypes.c_ulonglong),
                            ("availPageFile", ctypes.c_ulonglong),
                            ("totalVirtual", ctypes.c_ulonglong),
                            ("availVirtual", ctypes.c_ulonglong),
                            ("availExtendedVirtual", ctypes.c_ulonglong)]
            mem = MemStatus()
            mem.length = ctypes.sizeof(mem)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
                available, total = mem.availPhys, mem.totalPhys
        except (AttributeError, OSError, ValueError):
            pass
    else:
        try:
            lines = Path("/proc/meminfo").read_text().splitlines()
            values = {x.split(":",1)[0]: int(x.split(":",1)[1].split()[0])*1024
                      for x in lines if ":" in x and x.split(":",1)[1].strip()}
            available = values.get("MemAvailable")
            total = values.get("MemTotal")
        except (OSError, ValueError, IndexError):
            pass
    # Hardware telemetry is informational only. Never refuse a user job just
    # because the CPU is busy, RAM is low, or the machine has few cores.
    # Conflicting writes/installer jobs are still serialized below.
    with LOCK:
        active = sum(1 for entry in ACTIVE_JOBS.values()
                     if entry["thread"] and entry["thread"].is_alive())
    return {"cpuCores": cores, "cpuBusyPercent": cpu_busy_percent(),
            "memoryAvailableBytes": available,
            "memoryTotalBytes": total, "parallelLimit": None,
            "active": active, "freeSlots": None}

def _check_resource_capacity(action):
    state = resource_snapshot()
    group = job_group(action)
    with LOCK:
        active = [item for item in ACTIVE_JOBS.values()
                  if item["thread"] and item["thread"].is_alive()]
        if (group == "installer" and active) or any(
            item["group"] in ("installer", "exclusive") for item in active):
            raise ValueError("มีงานที่ต้องใช้ Engine แบบเฉพาะกำลังทำอยู่")
        if group == "exclusive" and active:
            raise ValueError("งานนี้ต้องรอให้งานอื่นหยุดก่อนเพื่อป้องกันข้อมูลชนกัน")
        if any(item["group"] == group for item in active):
            raise ValueError("มีงานประเภทเดียวกันกำลังทำงานอยู่ · กรุณารอหรือยกเลิกเฉพาะงานนั้น")
    return state

FILES = []
FILE_BY_ID = {}
PREVIEWS = {}
LIVE_TICKETS = {}
LIVE_SESSIONS = {}
LIVE_LIMIT = threading.BoundedSemaphore(2)
IMPORT_PREVIEW = {"kind": "", "folder": "", "items": []}

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

def default_song_workspace():
    """Use an installed X-Stage Karaoke PC Songs folder, otherwise user Music.

    Probe only known installation layouts with a real executable marker. Never
    create folders merely because a drive or similarly named directory exists.
    An explicit saved workspace always wins over this first-run default.
    """
    candidates = []
    if os.name == "nt":
        candidates.append(Path("D:/newKaraoke/Karaoke"))
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.append(Path(local) / "XStageKaraoke")
        for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
            base = os.environ.get(env_name)
            if base:
                candidates.append(Path(base) / "X-Stage Karaoke")
    for root in candidates:
        if ((root / "App" / "XStageKaraoke.exe").is_file()
                or (root / "XStageKaraoke.exe").is_file()):
            return str(root / "Songs" / "XStageSong")
    return str(HOME_MUSIC / "XStageSong")

PREFS = {
    "source": str(HOME_MUSIC),
    "workspace": default_song_workspace(),
    "download": str(Path.home() / "Downloads"),
    "soundfont": "", "midi_preset": "balanced", "mode": "original",
    "export_format": "xsk", "catalog_view": "changes", "code_style": "numeric", "code_length": "5", "oauth": "",
    "upload_folder": "", "lyric_source": "", "pc_export_folder": "", "xsk_folder": "",
    "json_source": "", "json_destination": "",
    "dup_source": "", "dup_destination": ""
}
PREFS.update({k: v for k, v in load_json(PREFS_FILE, {}).items() if k in PREFS and isinstance(v, str)})
NOTES = load_json(NOTES_FILE, {})

# This library belongs ONLY to the independent AI Lyrics menu.
AI_IMPORTS_FILE = DATA / "ai-lyrics-imports.json"
AI_IMPORTED = {}
def _source_audio_details(source):
    """Read metadata and existing lyrics on demand; never modify the audio.

    Embedded title/performer/lyrics come from FFprobe when available. A
    same-stem companion LRC takes precedence for timed lyrics. Plain lyrics
    stay plain: guessing timestamps would corrupt karaoke synchronization.
    """
    source = Path(source)
    result = {"title": "", "artist": "", "timedLrc": "",
              "plainLyrics": "", "lyricsSource": "", "metadataSource": ""}
    ffmpeg = ffmpeg_binary()
    probe = (Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
             if ffmpeg else None)
    if not probe or not probe.is_file():
        found = shutil.which("ffprobe")
        probe = Path(found) if found else None
    if probe:
        try:
            proc = subprocess.run(
                [str(probe), "-v", "error", "-show_entries",
                 "format_tags:stream_tags", "-of", "json", str(source)],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL, timeout=12,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            if proc.returncode == 0 and len(proc.stdout) <= 500000:
                document = json.loads(proc.stdout.decode("utf-8", errors="replace"))
                tags = {}
                groups = [document.get("format") or {}, *(document.get("streams") or [])]
                for group in groups:
                    for key, value in (group.get("tags") or {}).items():
                        normalized = str(key).casefold().replace(" ", "").replace("_", "")
                        if isinstance(value, str) and value.strip():
                            tags.setdefault(normalized, value.strip())
                def tagged(*keys):
                    return next((tags[key] for key in keys if tags.get(key)), "")
                result["title"] = tagged("title", "tit2", "©nam")[:180]
                result["artist"] = tagged("artist", "albumartist", "performer",
                                          "tpe1", "©art")[:180]
                embedded = tagged("lyrics", "unsyncedlyrics", "unsynchronisedlyrics",
                                  "unsynchronizedlyrics", "©lyr", "uslt",
                                  "syncedlyrics", "sylt")[:100000]
                if result["title"] or result["artist"]:
                    result["metadataSource"] = "แท็กภายในไฟล์เสียง"
                if embedded:
                    if _song_export_module().lrc_to_json(
                            embedded, source.stem).get("lines"):
                        result["timedLrc"] = embedded
                    else:
                        result["plainLyrics"] = embedded
                    result["lyricsSource"] = "แท็กเนื้อร้องในไฟล์เสียง"
        except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
            pass  # Metadata is optional; retaining original audio is mandatory.
    companion = _matching_lrc(source)
    if companion and companion.is_file() and not companion.is_symlink():
        try:
            if companion.stat().st_size <= 250000:
                content = NCN._decode_text(companion.read_bytes()).lstrip("\ufeff").strip()
                if content:
                    for header in content.splitlines()[:40]:
                        header = header.strip()
                        if header.startswith("[") and header.endswith("]") and ":" in header:
                            tag, value = header[1:-1].split(":", 1)
                            key = tag.casefold()
                            if key in ("ti", "title") and value.strip() and not result["title"]:
                                result["title"] = value.strip()[:180]
                                result["metadataSource"] = "ส่วนหัวไฟล์ LRC"
                            elif key in ("ar", "artist") and value.strip() and not result["artist"]:
                                result["artist"] = value.strip()[:180]
                                result["metadataSource"] = "ส่วนหัวไฟล์ LRC"
                    if _song_export_module().lrc_to_json(
                            content, source.stem).get("lines"):
                        result["timedLrc"] = content
                        result["plainLyrics"] = ""
                    elif not result["timedLrc"]:
                        result["plainLyrics"] = content
                    result["lyricsSource"] = "ไฟล์ LRC คู่กับเพลง"
        except (OSError, ValueError, TypeError):
            pass
    # Use an explicit paired Lyrics JSON only when there is no usable LRC.
    # Line start times are real; never invent character-level karaoke timing.
    companion_json = source.with_suffix(".json")
    if (not result["timedLrc"] and companion_json.is_file()
            and not companion_json.is_symlink()):
        try:
            if companion_json.stat().st_size <= 5_000_000:
                document = json.loads(companion_json.read_text(encoding="utf-8-sig"))
                lines = document.get("lines") if isinstance(document, dict) else None
                if document.get("schemaVersion") == 1 and isinstance(lines, list) and lines:
                    import math
                    timestamped = []
                    last = -1
                    for row in lines:
                        when = row.get("startTime") if isinstance(row, dict) else None
                        if (not isinstance(when, (int, float)) or isinstance(when, bool)
                                or not math.isfinite(when) or when < last or when < 0
                                or when >= 86400 or not isinstance(row.get("text"), str)
                                or not row["text"].strip()):
                            timestamped = []
                            break
                        last = when
                        minutes = int(when // 60)
                        timestamped.append(f"[{minutes:02d}:{when%60:05.2f}]{row['text']}")
                    if timestamped:
                        original_lrc = document.get("rawLrc")
                        if isinstance(original_lrc, str) and original_lrc.strip():
                            result["timedLrc"] = original_lrc
                        else:
                            result["timedLrc"] = "\n".join(timestamped)
                        metadata = document.get("metadata") or {}
                        if isinstance(metadata, dict):
                            if not result["title"]:
                                result["title"] = str(metadata.get("title") or "")[:180]
                            if not result["artist"]:
                                result["artist"] = str(metadata.get("artist") or "")[:180]
                        result["plainLyrics"] = ""
                        result["lyricsSource"] = "Lyrics JSON คู่กับเพลง (เวลาแต่ละบรรทัด)"
        except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
            pass
    return result


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

def import_ai_audio(source_path, *, inspect_metadata=True):
    """Register a selected local audio file without scanning the song library."""
    if not isinstance(source_path, str) or not source_path.strip():
        raise ValueError("กรุณาเลือกไฟล์เพลงจากเครื่อง")
    path = Path(source_path).expanduser()
    if path.suffix.lower() not in EXT_AUDIO:
        raise ValueError("ไฟล์นี้ไม่ใช่ชนิดเสียง/วิดีโอที่ PC Engine รองรับ · ตรวจชนิดที่ FFmpeg อ่านได้")
    if not path.is_file() or path.is_symlink():
        raise ValueError("ไม่พบไฟล์เพลงหรือไม่อนุญาตให้ใช้ symbolic link")
    if path.stat().st_size < 1000:
        raise ValueError("ไฟล์เสียงมีขนาดเล็กผิดปกติหรือไม่มีข้อมูล")
    resolved = str(path.resolve())
    discovered = (_source_audio_details(path) if inspect_metadata
                  else {"title": "", "artist": ""})
    with LOCK:
        existing = next((row for row in AI_IMPORTED.values()
                         if row["path"].casefold() == resolved.casefold()), None)
        if existing:
            return {"ok": True, "alreadyImported": True, "song": existing,
                    "message": "ไฟล์นี้มีอยู่แล้วในเมนูสร้างเนื้อร้อง AI"}
        song_id = min([0, *AI_IMPORTED.keys()]) - 1
        row = {"id": song_id, "path": resolved, "code": path.stem,
               "title": discovered["title"] or path.stem,
               "artist": discovered["artist"], "kind": path.suffix[1:].upper(),
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
FOLDER_UPLOAD = _module("folder_upload.py", "xstage_folder_upload")
DUPLICATES = _module("song_duplicate.py", "xstage_song_duplicates")
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
SCAN_CHANGE_FILE = DATA / "last-scan-changes.json"
SCAN_CHANGE_IDS = set()


def restore_scan_changes():
    """Restore only the delta belonging to the current source/workspace."""
    stored = load_json(SCAN_CHANGE_FILE, {})
    if not isinstance(stored, dict) or (
        stored.get("source") != PREFS["source"] or
        stored.get("workspace") != PREFS["workspace"]):
        ids = set()
    else:
        ids = {n for n in stored.get("ids", [])
               if type(n) is int and n > 0}
    with LOCK:
        SCAN_CHANGE_IDS.clear()
        SCAN_CHANGE_IDS.update(ids)
    return len(ids)


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
            worker_job()["total"] = 0  # Enumeration count is unknown; never invent a percentage.
            worker_job()["completed"] = completed
        update(message)

    with LOCK:
        running_scan = worker_job().get("state") == "running" and worker_job().get("kind") == "scan"
    rows, stats = SONG_INDEX.scan(
        worker_prefs()["source"], worker_prefs()["workspace"], DATA / "song-index.sqlite3",
        NOTES, NCN, full=bool(full),
        cancelled=worker_cancel() if running_scan else None, on_progress=progress)
    with LOCK:
        FILES[:] = rows
        FILE_BY_ID.clear()
        FILE_BY_ID.update((row["id"], row) for row in rows)
        FILE_BY_ID.update(AI_IMPORTED)
        # Keep potentially large ID lists out of the job/status JSON polled
        # every second; only summary counts belong in the public job snapshot.
        LAST_SCAN_STATS = {key: value for key, value in stats.items()
                           if key not in ("addedIds", "changedIds")}
        SCAN_CHANGE_IDS.clear()
        SCAN_CHANGE_IDS.update(stats.get("addedIds", []))
        SCAN_CHANGE_IDS.update(stats.get("changedIds", []))
        worker_job()["total"] = len(rows)
        worker_job()["completed"] = len(rows)
    # Persist after the successful SQLite snapshot; do not overwrite a known
    # good delta when enumeration was interrupted or failed.
    save_json(SCAN_CHANGE_FILE, {
        "source": worker_prefs()["source"], "workspace": worker_prefs()["workspace"],
        "ids": sorted(SCAN_CHANGE_IDS)})
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
    for index, raw in enumerate(paths):
        try:
            # Resolve the first selected song immediately. Other 199 inputs
            # remain fast, then load their metadata when the user selects one.
            result = import_ai_audio(raw, inspect_metadata=index == 0)
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
        if worker_job().get("state") == "running":
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


def visible_files(search="", view="all"):
    if view not in ("all", "changes"):
        raise ValueError("ตัวกรองรายการเพลงไม่ถูกต้อง")
    with LOCK:
        rows = list(FILES)
        if view == "changes":
            pending = set(SCAN_CHANGE_IDS)
            rows = [row for row in rows if row["id"] in pending]
    query = search.casefold()
    if query:
        rows = [row for row in rows if query in
                (row["title"] + " " + row["artist"] + " " + row["code"]).casefold()]
    return rows

def log(line):
    with LOCK:
        worker_job()["logs"].append(str(line))
        worker_job()["logs"][:] = worker_job()["logs"][-100:]
        worker_job()["detail"] = str(line)
        worker_job()["updated"] = time.monotonic()

def update(stage, done=None):
    with LOCK:
        worker_job()["stage"] = stage
        if done is not None:
            worker_job()["completed"] = done
        worker_job()["updated"] = time.monotonic()

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
            set_worker_process(proc)
        try:
            _, stderr = proc.communicate()
            if worker_cancel().is_set():
                raise RuntimeError("ผู้ใช้ยกเลิกงาน")
            if proc.returncode:
                msg = stderr.decode("utf-8", errors="replace")[-800:]
                raise RuntimeError("FFmpeg ไม่สำเร็จ: " + msg)
        finally:
            with LOCK:
                set_worker_process(None)

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


def _mirrored_lyric_sidecar(source, extension):
    """Match by relative code and subfolders, not a global same-name search."""
    source = Path(source)
    direct = source.with_suffix(extension)
    if direct.is_file():
        return direct
    parts = source.parts
    for index, name in enumerate(parts[:-1]):
        if name.casefold() not in ("audio", "songs", "song", "midi"):
            continue
        for lyric_name in ("LYRICS", "Lyrics", "lyrics"):
            mirrored = Path(*parts[:index], lyric_name, *parts[index + 1:]).with_suffix(extension)
            if mirrored.is_file() and not mirrored.is_symlink():
                return mirrored
    return None


def lyrics_package(row, *, export=None):
    """Return (LRC, accurately timed JSON, source fingerprint) or no lyrics.

    Never invent timings. The metadata editor's saved timed LRC has priority.
    NCN requires .MID + .LYR + .CUR with the SAME code and mirrored folder.
    KAR text events are decoded from the MIDI itself.
    """
    export = export if export is not None else _song_export_module()
    code = str(row.get("code") or Path(row["path"]).stem)
    note = NOTES.get(row["path"], {}).get("lyrics", "")
    if note:
        doc = export.lrc_to_json(note, code)
        if not doc["lines"]:
            raise ValueError("เนื้อร้องที่แก้ไขไม่มี timestamp LRC ที่ถูกต้อง")
        return note, doc, hashlib.sha256(note.encode("utf-8")).hexdigest()
    source = Path(row["path"])
    # A same-stem Lyrics JSON is the direct, lossless companion to MID/MIDI.
    # Do not fall back to embedded KAR text when a supplied JSON is malformed.
    if source.suffix.lower() in EXT_MIDI:
        companion = _mirrored_lyric_sidecar(source, ".json")
        if companion is not None:
            if companion.is_symlink() or companion.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("Lyrics JSON ไม่ปลอดภัยหรือใหญ่เกินกำหนด")
            raw_json = companion.read_bytes()
            try:
                doc = json.loads(raw_json.decode("utf-8-sig"))
            except (UnicodeError, ValueError) as exc:
                raise ValueError("ไฟล์ Lyrics JSON คู่กับ MIDI อ่านไม่ได้: " + companion.name) from exc
            if not isinstance(doc, dict) or not isinstance(doc.get("lines"), list) or not doc["lines"]:
                raise ValueError("Lyrics JSON คู่กับ MIDI ไม่มีบรรทัดเนื้อร้องพร้อมเวลา")
            # The output songCode will be assigned only after checking existing XSKs.
            doc = dict(doc)
            doc["songCode"] = code
            return str(doc.get("rawLrc") or ""), doc, hashlib.sha256(raw_json).hexdigest()
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
    lrc = _matching_lrc(source) or _mirrored_lyric_sidecar(source, ".lrc")
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


def _carry_lyrics_identity(row, document, export):
    """Carry verified source/user metadata into generated JSON and catalog.

    The scanner starts with a filename; it is not a verified song title.
    Saved edits take priority, but must not become a publisher/filename label.
    Only called for the song being converted (never on every scan row).
    """
    if not isinstance(document, dict):
        return
    source = Path(row["path"])
    discovered_title, discovered_artist = export.lyrics_identity(document, source.stem)
    saved = NOTES.get(str(source), {})
    unknown = {"x-stage karaoke", "xstage karaoke", "x-stage song studio",
               "xstage song studio", "unknown", "ไม่ระบุชื่อเพลง",
               "ไม่ระบุศิลปิน", "ไม่ระบุ"}
    def meaningful(value, title=False):
        value = str(value or "").strip()
        if not value or value.casefold() in unknown:
            return ""
        if title and value.casefold() == source.stem.casefold():
            return ""
        return value[:200]
    title = (meaningful(saved.get("title"), True)
             or meaningful(row.get("title"), True) or discovered_title)
    artist = (meaningful(saved.get("artist"))
              or meaningful(row.get("artist")) or discovered_artist)
    if title:
        row["title"] = title
        document["title"] = title
    if artist:
        row["artist"] = artist
        document["artist"] = artist


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
    params = [fluid, "-ni", "-F", str(tmp), "-r", "48000", worker_prefs()["soundfont"], str(path)]
    run_process(params)
    return tmp

def render_browser_video(source, target):
    """Normalize mixed AVI/MPG/VCD/WMV/MOV/MKV sources to HTML5 MP4.

    Never copy a codec-incompatible legacy file and call it playable. All
    media remains private and the conversion runs locally in the bundled PC.
    """
    if not ffmpeg_binary():
        raise RuntimeError("ไม่มี FFmpeg ที่รวมใน Song Studio PC Ready")
    target = Path(target)
    source = Path(source)
    if target.suffix.lower() != ".mp4" or source.resolve() == target.resolve():
        raise ValueError("ปลายทางวิดีโอออนไลน์ต้องเป็น MP4 ใหม่ ไม่ทับต้นฉบับ")
    update("กำลังแปลงวิดีโอ " + source.name + " เป็น H.264/AAC MP4 สำหรับ WEB/APK")
    run_process([
        ffmpeg_binary(), "-hide_banner", "-loglevel", "error", "-nostdin",
        "-y", "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart", str(target)
    ])
    if not target.is_file() or target.stat().st_size < 1000:
        raise RuntimeError("วิดีโอที่แปลงยังไม่พร้อมเล่น: " + source.name)


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

def json_pro_transcode(source, destination, kind):
    """Render MIDI with the selected SoundFont before FFmpeg encoding.

    FFmpeg alone cannot reliably synthesize MIDI. Do not export an empty,
    unplayable MP3/WAV/FLAC/OGG just because the source has a .mid extension.
    """
    source = Path(source)
    destination = Path(destination)
    if not ffmpeg_binary():
        raise ValueError("ไม่พบ FFmpeg สำหรับแปลงรูปแบบไฟล์เสียง")
    if kind == "m4a":
        convert({"path": str(source)}, destination)
        return
    codec = {"mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
             "wav": ["-c:a", "pcm_s16le"],
             "flac": ["-c:a", "flac"],
             "ogg": ["-c:a", "libvorbis", "-q:a", "5"]}.get(kind)
    if codec is None:
        raise ValueError("ไม่รองรับรูปแบบปลายทางที่เลือก")
    temporary_wav = None
    try:
        if source.suffix.lower() in EXT_MIDI:
            temporary_wav = ensure_midi_wav(source)
        audio_input = temporary_wav or source
        run_process([ffmpeg_binary(), "-hide_banner", "-loglevel", "error",
                     "-nostdin", "-y", "-i", str(audio_input), "-vn",
                     *codec, "-f", kind, str(destination)])
        if not destination.is_file() or destination.stat().st_size < 1000:
            raise ValueError("การแปลงไฟล์เสียงไม่สมบูรณ์")
    finally:
        if temporary_wav:
            temporary_wav.unlink(missing_ok=True)


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
        if worker_cancel().is_set():
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
                set_worker_process(proc)
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
                            worker_job()["detail"] = "ประมวลผลบน CPU · " + fraction + " ช่วง"
                            worker_job()["updated"] = time.monotonic()
                    elif item.startswith("AI_STAGE "):
                        update("AI ขั้น 2/4 · " + item.removeprefix("AI_STAGE "))
                    elif item.startswith("AI_ERROR "):
                        log(item)
                returncode = proc.wait()
                if worker_cancel().is_set():
                    raise RuntimeError("ผู้ใช้ยกเลิกงาน")
                if returncode:
                    raise RuntimeError(
                        "AI separation ไม่สำเร็จ (code " + str(returncode) + "): " +
                        " | ".join(output_lines[-5:])
                    )
            finally:
                with LOCK:
                    set_worker_process(None)
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
    """Deterministic private XStageSong/audio M4A for an imported source.

    The filename includes a fingerprint of original path/size/mtime so a
    changed source cannot silently reuse its predecessor's AI vocal file.
    AI-only stems are never added to the public song catalog automatically.
    """
    source = Path(row["path"]).expanduser()
    if (source.suffix.lower() not in EXT_AUDIO or
            not source.is_file() or source.is_symlink()):
        raise ValueError("ต้องเลือกไฟล์เสียงต้นฉบับที่ยังอยู่ในเครื่อง")
    export = _song_export_module()
    root = export.songs_root(worker_prefs()["workspace"])
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
        if worker_cancel().is_set():
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



def export_ai_lyrics_files(song_id, *, include_lyrics=False, include_instrumental=False,
                           include_source=False, source_format="original"):
    """Export only the selected reviewed LRC and/or separated karaoke M4A.

    Files are copied to the user's remembered download directory, never to
    the original source folder or directly into the published song catalog.
    Exclusive file creation prevents overwrites, including concurrent exports.
    """
    if type(song_id) is not int or not (include_lyrics or include_instrumental or include_source):
        raise ValueError("กรุณาเลือกเพลงและชนิดไฟล์อย่างน้อยหนึ่งรายการ")
    with LOCK:
        row = dict(AI_IMPORTED.get(song_id) or {})
    if not row:
        raise ValueError("กรุณาเลือกเพลงจากรายการที่นำเข้าในหน้า AI")
    source = Path(row["path"]).expanduser()
    if source_format not in ("original", "m4a", "mp3", "wav", "flac", "ogg"):
        raise ValueError("รูปแบบไฟล์เสียงที่เลือกไม่รองรับ")
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
    destination = Path(worker_prefs()["download"]).expanduser()
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
    if include_source:
        if source_format == "original":
            tasks.append((safe + source.suffix.lower(), source))
        else:
            tasks.append((safe + "." + source_format, ("convert", source, source_format)))
    for i, (name, data) in enumerate(tasks, 1):
        if worker_cancel().is_set():
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
                        temporary = None
                        if isinstance(data, tuple) and data[0] == "convert":
                            _, original, extension = data
                            temporary = destination / ("." + secrets.token_hex(16) + "." + extension)
                            try:
                                if extension == "m4a":
                                    convert({"path": str(original)}, temporary)
                                else:
                                    codecs = {"mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
                                              "wav": ["-c:a", "pcm_s16le"],
                                              "flac": ["-c:a", "flac"],
                                              "ogg": ["-c:a", "libvorbis", "-q:a", "5"]}
                                    run_process([ffmpeg_binary(), "-hide_banner", "-loglevel",
                                                 "error", "-nostdin", "-y", "-i", str(original),
                                                 "-vn", *codecs[extension], "-f", extension,
                                                 str(temporary)])
                                if temporary.stat().st_size < 1000:
                                    raise ValueError("ไฟล์เสียงหลังแปลงไม่สมบูรณ์")
                                data = temporary
                            except BaseException:
                                temporary.unlink(missing_ok=True)
                                raise
                        if isinstance(data, bytes):
                            output.write(data)
                        else:
                            with data.open("rb") as stream:
                                while True:
                                    if worker_cancel().is_set():
                                        raise RuntimeError("ยกเลิกการส่งออก")
                                    block = stream.read(1024 * 1024)
                                    if not block:
                                        break
                                    output.write(block)
                        output.flush()
                        os.fsync(output.fileno())
                        if temporary is not None:
                            temporary.unlink(missing_ok=True)
                    except BaseException:
                        if temporary is not None:
                            temporary.unlink(missing_ok=True)
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


def lyric_source_root(selected=None):
    """Resolve XStageSong catalogs or an arbitrary folder with timed LRC.

    Original audio/MIDI is never edited. Folder mode updates only validated
    .lrc files after explicit confirmation and a full recoverable backup.
    """
    folder = worker_prefs().get("lyric_source", "") if selected is None else selected
    if not isinstance(folder, str):
        raise ValueError("โฟลเดอร์ต้นทางข้อความหัว–ท้ายเพลงไม่ถูกต้อง")
    if not folder.strip():
        return _song_export_module().songs_root(worker_prefs()["workspace"])
    try:
        selected_path = Path(folder.strip()).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("ไม่พบโฟลเดอร์ต้นทางข้อความหัว–ท้ายเพลง กรุณาเลือกใหม่") from exc
    if not selected_path.is_dir():
        raise ValueError("ต้นทางข้อความหัว–ท้ายเพลงต้องเป็นโฟลเดอร์")
    # Also recognize users choosing XStageSong/lyrics instead of XStageSong.
    if (selected_path.name.casefold() == "lyrics" and
            (selected_path.parent / "current.json").is_file()):
        selected_path = selected_path.parent
    root = (selected_path if (selected_path / "current.json").is_file()
            else selected_path / "XStageSong" if (selected_path / "XStageSong" / "current.json").is_file()
            else selected_path)
    pointer_file = root / "current.json"
    if pointer_file.is_file():
        try:
            pointer = json.loads(pointer_file.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise ValueError("อ่าน current.json ของโฟลเดอร์ที่เลือกไม่สำเร็จ") from exc
        if (not isinstance(pointer, dict) or
                pointer.get("format") != "xstage-local-current" or
                pointer.get("schemaVersion") != 1):
            raise ValueError("โฟลเดอร์ต้นทางไม่ใช่คลัง XStageSong ที่รองรับ")
    # Raw NCN/LRC folders are no longer editable. Only catalogued JSON may be modified.
    if not pointer_file.is_file():
        raise ValueError("กรุณาเลือกคลัง XStageSong ที่มี current.json และ Lyrics JSON")
    return root.resolve()


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
    root = export.songs_root(worker_prefs()["workspace"])
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



def _xsk_format(options):
    return options.get("export_format", worker_prefs().get("export_format", "xsk"))


def _xsk_apply_head_tail(document, options):
    """Only adjust the draft document, never original MIDI, LYR or CUR."""
    if options.get("edit_head_tail") != "yes":
        return document
    import copy
    modified = copy.deepcopy(document)
    lines = modified.get("lines") or []
    for position, prefix in ((0, "head"), (-1, "tail")):
        before = str(options.get(prefix + "_find") or "")
        after = str(options.get(prefix + "_replace") or "")
        if not before:
            continue
        if not lines or not isinstance(lines[position], dict):
            raise ValueError("ไม่สามารถค้นหาบรรทัดหัว–ท้ายเพลง")
        line = lines[position]
        if line.get("text") != before:
            raise ValueError("ข้อความ" + prefix + "ไม่ตรงกับตัวอย่าง · ไม่เปลี่ยนเพลง")
        if line.get("syllables") and after != before:
            raise ValueError("มีเวลาปาดระดับอักษร · การเปลี่ยนข้อความนี้ต้องตรวจด้วยตนเอง")
        line["text"] = after
    return modified


def _xsk_stream_scan_status(data, complete, backlog, *, job_id=None):
    """Discovered MIDI count is dynamic until the source walk finishes."""
    with LOCK:
        # The source discovery producer has its own Python thread, so the
        # caller's thread-local context does not propagate automatically.
        entry = ACTIVE_JOBS.get(job_id) if job_id else None
        target = entry["job"] if entry else worker_job() if job_id is None else None
        if target is None or (job_id and target.get("id") != job_id):
            return
        target["scannedFiles"] = data["files"]
        target["discovered"] = data["found"]
        target["queuedBatches"] = backlog
        target["scanDone"] = bool(complete)
        if complete:
            target["total"] = data["found"]
        target["updated"] = time.monotonic()


def _xsk_identity(source, row, doc):
    """Prioritize verified companion/embedded identity over scanner filenames.

    The MIDI discovery scanner only knows the filename. NCN and KAR return
    title/artist under doc.metadata, not necessarily at the document root.
    Do not mistakenly attribute unknown songs to the application's brand.
    """
    metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
    saved = NOTES.get(str(source), {})
    # Preserve standard [ti:] and [ar:] LRC metadata alongside timed lines.
    lrc_metadata = {}
    raw_lrc = doc.get("rawLrc")
    if isinstance(raw_lrc, str):
        for raw_line in raw_lrc.splitlines()[:40]:
            line = raw_line.strip().lstrip("\ufeff")
            if not (line.startswith("[") and "]" in line):
                continue
            tag = line[1:line.index("]")]
            if ":" not in tag:
                continue
            field, value = tag.split(":", 1)
            key = {"ti": "title", "title": "title",
                   "ar": "artist", "artist": "artist"}.get(field.strip().casefold())
            if key and value.strip() and key not in lrc_metadata:
                lrc_metadata[key] = value.strip()
    placeholders = {"x-stage karaoke", "x-stage song studio", "xstage karaoke",
                    "xstage song studio", "unknown", "ไม่ระบุ", "ไม่ทราบ"}
    def meaningful(value, *, title=False):
        if not isinstance(value, str):
            return ""
        value = value.strip()
        if not value or value.casefold() in placeholders:
            return ""
        if title and value.casefold() == source.stem.casefold():
            return ""
        return value
    title = (meaningful(saved.get("title"), title=True)
             or meaningful(doc.get("title"), title=True)
             or meaningful(metadata.get("title"), title=True)
             or meaningful(lrc_metadata.get("title"), title=True)
             or meaningful(row.get("title"), title=True)
             or source.stem)
    artist = (meaningful(saved.get("artist"))
              or meaningful(doc.get("artist"))
              or meaningful(metadata.get("artist"))
              or meaningful(lrc_metadata.get("artist"))
              or meaningful(row.get("artist"))
              or "ไม่ระบุศิลปิน")
    return title, artist


def build_xsk(rows, mode, options, *, progressive=False):
    """Seal each verified MIDI + timed lyric document without publishing raw assets."""
    if mode != "original" or options.get("audio_only"):
        raise ValueError("XSK ต้องเป็นเพลง MIDI/KAR ต้นฉบับ ไม่ใช่โหมดแยกเสียง")
    package = _module("xsk_package.py", "xstage_xsk_package")
    review = _module("xsk_review.py", "xstage_xsk_review")
    # Do not open/create any encryption key for portable XSK2 exports.
    export = _song_export_module()
    root = export.songs_root(options.get("xsk_folder") or worker_prefs().get("xsk_folder") or worker_prefs()["workspace"])
    review_db = review.connect(root)
    try:
        codes = _module("code_registry.py", "xstage_xsk_codes")
        records = export.existing_records(root)
        allocator = codes.CodeAllocator(
            records, [], root,
            code_style=options.get("code_style", worker_prefs().get("code_style", "numeric")),
            code_length=int(options.get("code_length", worker_prefs().get("code_length", "5"))))
        # Read existing XSK2 (or older XSK1) only to deduplicate and reserve codes.
        # Index its authenticated MIDI digests and occupied codes once before
        # assigning any new ID. Never infer uniqueness from filenames alone.
        existing_midi = set()
        xsk_root = root / "MIDI" / "XSK"
        if xsk_root.is_dir():
            for existing_path in xsk_root.rglob("*.xsk"):
                if not existing_path.is_file() or existing_path.is_symlink():
                    raise ValueError("พบ XSK ที่ตรวจสอบไม่ได้: " + str(existing_path))
                # Preserve encrypted XSK1 untouched. Reserve the filename,
                # but never treat its encrypted MIDI as an existing portable
                # XSK2 song: the user may regenerate it safely with a new code.
                with existing_path.open("rb") as old:
                    legacy = old.read(4) == b"XSK1"
                if legacy:
                    allocator.used.add(existing_path.stem.casefold())
                    allocator._track_numeric(existing_path.stem)
                    log("XSK1 รุ่นเก่าคงไว้ ไม่เขียนทับ · สร้าง XSK2 ใหม่ได้: " + existing_path.name)
                    continue
                try:
                    cached = review.verified(review_db, existing_path)
                    if cached is not None:
                        digest, used_code = cached
                    else:
                        existing_doc = package.open_package(existing_path)
                        digest = existing_doc["audio"]["sha256"]
                        used_code = existing_doc["songCode"]
                        review.store_verified(review_db, existing_path, digest, used_code)
                    if not isinstance(digest, str) or len(digest) != 64:
                        raise ValueError("SHA-256 ของ XSK ไม่ถูกต้อง")
                    if not isinstance(used_code, str) or not package.CODE_RE.fullmatch(used_code):
                        raise ValueError("รหัสเพลง XSK ไม่ถูกต้อง")
                except Exception as exc:
                    raise ValueError(
                        "ไม่สามารถตรวจความซ้ำของ XSK เดิมได้ จึงไม่สร้างเพลงใหม่: "
                        + str(existing_path) + " (" + str(exc) + ")") from exc
                existing_midi.add(digest)
                allocator.used.add(used_code.casefold())
                allocator._track_numeric(used_code)
                # Reserve the filename as well, even if old metadata differs.
                allocator.used.add(existing_path.stem.casefold())
                allocator._track_numeric(existing_path.stem)
        created = skipped = errors = not_ready = resumed = deferred = 0
        source_root = str(options.get("source") or worker_prefs().get("source") or "")
        retry_only = options.get("retry_issues_only") is True
        issues = []
        with LOCK:
            worker_job()["total"] = 0 if progressive else len(rows)
        for index, original in enumerate(rows, 1):
            if worker_cancel().is_set():
                raise RuntimeError("ยกเลิกงานสร้าง XSK · เก็บเพลงที่สำเร็จแล้ว")
            row = dict(original)
            source = Path(row["path"])
            stamp = ""
            source_digest = ""
            try:
                stamp = review.signature(source)
                previous = review.lookup(review_db, source)
                if previous is not None and previous[0] == stamp and not retry_only:
                    old_status, old_digest = previous[1], previous[2]
                    if old_status in ("completed", "duplicate") and old_digest in existing_midi:
                        skipped += 1
                        resumed += 1
                        continue
                    if old_status in ("not_ready", "error"):
                        deferred += 1
                        continue
                if source.suffix.lower() not in EXT_MIDI:
                    raise ValueError("XSK รองรับเฉพาะ MIDI/KAR ที่มีเวลาคำร้องถูกต้อง")
                if not source.is_file() or source.is_symlink():
                    raise ValueError("ไฟล์ MIDI ต้นฉบับไม่พร้อมใช้งาน")
                # Hash first: skip already sealed MIDI before costly NCN/LRC/JSON
                # lyric decoding. Re-reading unchanged lyric sidecars is wasteful
                # on a 100k-track second run.
                source_digest = package._hash_source(source)
                if source_digest in existing_midi:
                    skipped += 1
                    review.record(review_db, source, source_root, signature_value=stamp,
                                  status="duplicate", digest=source_digest,
                                  reason="MIDI เหมือนกับ XSK2 ที่ตรวจสอบ SHA-256 แล้ว")
                    log("XSK ข้าม MIDI ซ้ำ (SHA-256): " + source.name)
                    continue
                preferred = str(row.get("code") or source.stem)
                # Thai titles and names containing spaces are valid source files,
                # but not valid protected XSK song-code filenames. Allocate a
                # safe numeric code instead of rejecting an otherwise valid song.
                if not package.CODE_RE.fullmatch(preferred):
                    preferred = "1".zfill(int(options.get(
                        "code_length", worker_prefs().get("code_length", "5"))))
                row["code"] = source.stem
                _lrc, doc, _fingerprint = lyrics_package(row, export=export)
                if not doc or not doc.get("lines"):
                    raise ValueError("ไม่มีเนื้อร้องที่มีเวลาจริงสำหรับสร้าง XSK")
                doc = _xsk_apply_head_tail(doc, options)
                title, artist = _xsk_identity(source, row, doc)
                if title == source.stem or artist == "ไม่ระบุศิลปิน":
                    raise ValueError("ไม่มีชื่อเพลง/ศิลปินจริงใน metadata · ข้ามเพื่อไม่สร้าง DB ผิด: " + source.name)
                # CodeAllocator fills numeric gaps before appending after the
                # highest occupied code. The target file is still checked by seal.
                code = allocator.assign_new(preferred)
                output = package.destination(root, code)
                if output.exists() or output.is_symlink():
                    raise FileExistsError("รหัส XSK ปลายทางมีอยู่แล้ว · ไม่เขียนทับ: " + code)
                row["code"] = code
                doc["songCode"] = code
                update(f"บรรจุ XSK2 ไม่เข้ารหัส รายการ {index:,}" +
                       (f"/{len(rows):,}" if not progressive else "") + f": {title}")
                package.seal(source, doc, code, title, artist, target=output)
                review.store_verified(review_db, output, source_digest, code)
                review.record(review_db, source, source_root, signature_value=stamp,
                              status="completed", digest=source_digest,
                              output_path=str(output))
                existing_midi.add(source_digest)
                created += 1
                log("XSK2 ไม่เข้ารหัส · ตรวจ ZIP / SHA-256 ผ่าน: " + code)
            except Exception as exc:
                reason = source.name + ": " + str(exc)
                if progressive and isinstance(exc, ValueError):
                    not_ready += 1
                    issue_status = "not_ready"
                    log("XSK ข้ามไม่ผ่านเงื่อนไข: " + reason)
                else:
                    errors += 1
                    issue_status = "error"
                    log("ERR " + reason)
                review.record(review_db, source, source_root, signature_value=stamp,
                              status=issue_status, reason=str(exc)[:500])
                if len(issues) < 50:
                    issues.append(reason)
            finally:
                if index % 32 == 0:
                    review_db.commit()
                with LOCK:
                    worker_job().update(created=created, skipped=skipped, errors=errors,
                               notReady=not_ready, resumed=resumed, deferred=deferred,
                               m4aCount=0, lyricsCount=created)
                update((f"XSK {index:,}" + (f"/{len(rows):,}" if not progressive else "") +
                        f" · ใหม่ {created:,} · ซ้ำ {skipped:,} · ใช้ผลเดิม {resumed:,}"
                        f" · ค้างทบทวน {deferred:,} · ไม่พร้อม {not_ready:,} · ERR {errors:,}"), index)
        result = {"created": created, "skipped": skipped, "errors": errors,
                  "notReady": not_ready, "resumed": resumed, "deferred": deferred,
                  "m4aCount": 0, "lyricsCount": created,
                  "output": str(root / "MIDI" / "XSK"),
                  "issues": issues[-50:],
                  "message": (f"สร้าง XSK {created} เพลง · ซ้ำ/มีแล้ว {skipped} · ใช้ผลเดิม {resumed}"
                              f" · ค้างทบทวน {deferred} · ไม่พร้อมใหม่ {not_ready} · ERR ใหม่ {errors}")}
        if not progressive and not created and not skipped:
            raise ValueError("ไม่มีเพลงที่สร้างสำเร็จ · " + "; ".join(issues[:3]))
        return result
    finally:
        review_db.commit()
        review_db.close()

def build_library(rows, mode, options):
    """Idempotent across independent sessions; checkpoint before next song.

    1. Read previously published catalogs AND the recovered journal.
    2. Match canonical original path first; hash full source only if needed.
    3. Never generate new audio/lyrics for a previously completed source.
    4. Stage output in the destination directory; commit without overwrite.
    5. Fsync each finished record, then atomically replace current.json once.
    """
    export = _song_export_module()
    export_format = options.get("export_format", "xstage")
    if export_format not in ("xstage", "m4a"):
        raise ValueError("ประเภทส่งออกต้องเป็น MIDI/Audio + Lyrics JSON หรือ M4A + Lyrics JSON")
    root = export.songs_root(worker_prefs()["workspace"])
    root.mkdir(parents=True, exist_ok=True)
    for name in ("audio", "lyrics"):
        (root / name).mkdir(exist_ok=True)
    records = export.existing_records(root)
    registry, remote, online_verified, online_generation = code_registry_snapshot(root)
    if online_verified:
        allocator, remapped = reconcile_local_codes(root, records, registry, remote, export)
        allocator.code_style = worker_prefs().get("code_style", "numeric")
        allocator.code_length = int(worker_prefs().get("code_length", "5"))
        if remapped:
            records = export.existing_records(root)
        log(f"ตรวจรหัสสองแหล่งแล้ว · PC {len(records):,} · Google Drive {len(remote):,} เพลง")
    else:
        allocator = registry.CodeAllocator(
            records, [], root,
            code_style=worker_prefs().get("code_style", "numeric"),
            code_length=int(worker_prefs().get("code_length", "5")))
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
        worker_job()["total"] = len(rows)
    log(f"ตรวจสอบคลังเพลงเดิม: พบ {len(records):,} รายการ (รวมรายการที่กู้จากงานก่อน)")
    try:
        for idx, row in enumerate(rows, 1):
            if worker_cancel().is_set():
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
                    is_midi_source = source.suffix.lower() in (".mid", ".midi", ".kar")
                    desired_ext = (source.suffix.lower() if
                                   is_midi_source and export_format == "xstage" and
                                   mode == "original" and not options.get("audio_only", False)
                                   else ".m4a")
                    prior_ext = Path((previous.get("audio") or {}).get("path") or "").suffix.lower()
                    if is_midi_source and prior_ext != desired_ext:
                        raise ValueError(
                            "เพลงนี้เคยสร้างในรูปแบบ " + prior_ext +
                            " แล้ว · ไม่สร้างเพลงซ้ำหรือเปลี่ยนรหัสโดยอัตโนมัติ "
                            "กรุณาเลือกไฟล์ต้นฉบับ/ชุดส่งออกแยกต่างหาก")
                    # The original source's filename is NOT the assigned code
                    # after an earlier two-source reconciliation.
                    row["code"] = str(previous["code"])
                    # Repair or add ONLY the lyric companion. Preserve the
                    # exact same M4A, song ID, audio catalog path and code.
                    if not options.get("audio_only", False):
                        try:
                            lrc, document, lyric_fingerprint = lyrics_package(row)
                            if document:
                                _carry_lyrics_identity(row, document, export)
                            if document and (not previous.get("lyrics") or
                                             previous.get("lyricsSourceIdentity") != lyric_fingerprint):
                                saved_audio = export.safe_media_path(
                                    root, previous["audio"]["path"], "audio")
                                repair = bool(previous.get("lyrics"))
                                upgrade = export.save_lyrics(
                                    root, saved_audio, lrc, str(row.get("code") or source.stem),
                                    document=document, repair=repair)
                                revised = dict(previous)
                                revised["title"] = str(row.get("title") or previous.get("title") or "")
                                revised["artist"] = str(row.get("artist") or previous.get("artist") or "")
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
                    if document:
                        _carry_lyrics_identity(row, document, export)
                    if not document:
                        raise ValueError(
                            "ไม่มีไฟล์ Lyrics จริงสำหรับซ่อมเพลงที่เคยสร้าง · " + source.name)
                    repaired = export.save_lyrics(
                        root, saved_audio, lrc, str(row.get("code") or source.stem),
                        document=document, repair=True)
                    revised = dict(partial)
                    revised["title"] = str(row.get("title") or partial.get("title") or "")
                    revised["artist"] = str(row.get("artist") or partial.get("artist") or "")
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
                legacy = (Path(worker_prefs()["workspace"]).expanduser() / "song" /
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
                # the upload stage will verify/reassign against live XStageSong.
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
                    if lyric_info[1]:
                        _carry_lyrics_identity(row, lyric_info[1], export)
                copy_midi = (source.suffix.lower() in (".mid", ".midi", ".kar") and
                             export_format == "xstage" and mode == "original"
                             and not options.get("audio_only", False))
                target = export.next_target(
                    root, assigned_code + source.suffix,
                    media_ext=source.suffix.lower() if copy_midi else ".m4a")
                staged = export.temporary_audio(target)
                update(f"กำลังสร้างเพลงใหม่ {idx}/{len(rows)}: {row['title']}")
                if copy_midi:
                    # Byte-for-byte copy. MIDI source is never opened for write
                    # and neither its track data nor its tempo events change.
                    shutil.copyfile(source, staged)
                    if export.source_sha256(source) != export.source_sha256(staged):
                        raise RuntimeError("SHA-256 หลังคัดลอก MIDI ไม่ตรงต้นฉบับ")
                elif mode == "instrumental":
                    staged_vocals = separate_ai(row, staged, preview=False)
                elif source.suffix.lower() == ".m4a":
                    shutil.copyfile(source, staged)  # Preserve source bytes
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
                log(f"สร้างสำเร็จ: {record['code']} · {record['audio']['path']}"
                    + (" · MIDI คัดลอกโดย SHA-256 ตรงต้นฉบับ" if copy_midi else ""))
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
                if worker_cancel().is_set():
                    raise RuntimeError("ผู้ใช้ยกเลิก; บันทึกเพลงที่สำเร็จแล้วเพื่อเริ่มใหม่ได้") from exc
            finally:
                for temporary in (staged, staged_vocals):
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
                with LOCK:
                    worker_job().update(created=created, skipped=skipped, errors=errors,
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
                    f"· ไฟล์เพลง {audio_count} · Lyrics JSON {lyrics_count} · {root}")
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
        worker_job()["total"] = 1
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
        if action == "duplicates-scan":
            def dup_progress(stage, discovered, hashed, groups):
                with LOCK:
                    worker_job()["scannedFiles"] = discovered
                    worker_job()["hashedFiles"] = hashed
                    worker_job()["duplicateGroups"] = groups
                update(
                    (f"ค้นหาไฟล์เพลง {discovered:,} ไฟล์" if stage == "scan"
                     else f"ตรวจ SHA-256 {hashed:,} ไฟล์ · กลุ่มซ้ำ {groups:,}"
                          if stage == "hash"
                     else f"ตรวจเพลงซ้ำครบแล้ว {discovered:,} ไฟล์"))
            result = DUPLICATES.REGISTRY.scan(
                str(options.get("source") or worker_prefs().get("dup_source") or ""),
                mode=options.get("matchMode", "exact"),
                cancelled=worker_cancel(), progress=dup_progress)
            update(result["message"], result["fileCount"])
        elif action == "duplicates-apply":
            selected = options.get("selected")
            result = DUPLICATES.REGISTRY.apply(
                scan_id=options.get("scanId"), selected=selected,
                operation=options.get("operation"),
                destination=(options.get("destination")
                             or worker_prefs().get("dup_destination")),
                keeper_by_group=options.get("keeperByGroup") or {},
                preferred_extension=options.get("preferredExtension") or "",
                include_companions=options.get("includeCompanions", True),
                same_song_confirmed=options.get("sameSongConfirmed", False),
                preview_id=options.get("previewId"),
                confirmed=options.get("confirmed") is True,
                cancelled=worker_cancel(),
                progress=lambda done, total, name: update(
                    f"จัดการไฟล์ซ้ำ {done:,}/{total:,} · {name}", done))
            update(result["message"], result["processed"])
        elif action == "scan":
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
        elif action == "json-pro-export":
            module = _module("json_pro_export.py", "xstage_json_pro_export")
            source_stream = _module("json_source_stream.py", "xstage_json_source_stream")
            output_format = options.get("format", "original")
            retry_errors_only = options.get("retry_errors_only") is True
            code_style = options.get("code_style", worker_prefs().get("code_style", "numeric"))
            code_length = int(options.get("code_length", worker_prefs().get("code_length", "5")))
            def _json_progress(done, total, state):
                with LOCK:
                    worker_job().update(completed=done, created=state["created"],
                                        skipped=state["skipped"], errors=state["errors"],
                                        resumed=state.get("resumed", 0),
                                        deferred=state.get("deferred", 0))
                    if total is not None:
                        worker_job()["total"] = total
                # Total is deliberately unknown until the final source is found.
                # The first song starts immediately; no fabricated percentage.
                amount = f"{done:,}/{total:,}" if total is not None else f"{done:,}"
                update(f"Lyrics JSON {amount} เพลง · สร้าง {state['created']:,}"
                       f" · ข้ามซ้ำ {state['skipped']:,} · ERR {state['errors']:,}", done)
            def _json_scan_progress(phase, count, total):
                if worker_cancel().is_set():
                    raise RuntimeError("ยกเลิกการตรวจไฟล์แล้ว")
                with LOCK:
                    worker_job()["scanPhase"] = phase
                    worker_job()["scannedFiles" if phase == "discover" else "validatedGroups"] = count
                    if total is not None:
                        worker_job()["totalGroups"] = total
                if phase == "discover":
                    update(f"ค้นหาไฟล์ต้นฉบับแล้ว {count:,} ไฟล์ · แปลงไปพร้อมค้นหา")
                elif total is not None:
                    update(f"ค้นหาเสร็จ · พบเพลงเข้าคิวแปลง {count:,} เพลง")
                else:
                    update(f"พบไฟล์ต้นฉบับพร้อมแปลง {count:,} เพลง · ไม่รอสแกนครบ")
            def _json_convert(src, dest, kind):
                json_pro_transcode(src, dest, kind)
            update("กำลังทบทวนเฉพาะ ERR ที่บันทึกไว้" if retry_errors_only
                   else "กำลังสร้างต่อจาก Catalog รุ่นก่อน · ไม่สร้างเพลงเดิมซ้ำ")
            result = module.export_folder(
                worker_prefs()["json_source"], worker_prefs()["json_destination"],
                output_format=output_format, export=_song_export_module(),
                code_style=code_style, code_length=code_length,
                scanner=FOLDER_UPLOAD, ncn=NCN, convert=_json_convert,
                cancelled=worker_cancel(), progress=_json_progress,
                scan_progress=_json_scan_progress,
                source_stream=source_stream.stream,
                retry_errors_only=retry_errors_only)
            # Source count is only known after the last directory has been read.
            # Make finished counts truthful even if interim progress was unknown.
            with LOCK:
                worker_job().update(total=result["total"], completed=result["total"],
                                    created=result["created"], skipped=result["skipped"],
                                    errors=result["errors"], lyricsCount=result["created"],
                                    resumed=result.get("resumed", 0),
                                    deferred=result.get("deferred", 0))
        elif action == "created-xsk":
            module = _module("created_xsk_export.py", "xstage_created_xsk_export")
            output_root = worker_prefs().get("xsk_folder") or worker_prefs()["workspace"]
            def _created_progress(done, outcome):
                with LOCK:
                    worker_job().update(created=outcome["created"], skipped=outcome["skipped"],
                               errors=outcome["errors"], lyricsCount=outcome["created"])
                update(f"XSK {done}/{outcome['total']} · สร้าง {outcome['created']} "
                       f"· ข้าม MIDI ซ้ำ {outcome['skipped']} · ERR {outcome['errors']}", done)
            result = module.export_selected(
                _song_export_module().songs_root(worker_prefs()["workspace"]),
                options["paths"], _song_export_module(),
                _module("created_json_manager.py", "xstage_created_json_manager"),
                _module("xsk_package.py", "xstage_xsk_package"),
                _module("code_registry.py", "xstage_xsk_codes"),
                None,
                destination_root=output_root, cancelled=worker_cancel(), progress=_created_progress)
        elif action == "xsk-stream":
            options = dict(options)
            options["source"] = str(options.get("source") or worker_prefs()["source"])
            options["xsk_folder"] = str(options.get("xsk_folder") or worker_prefs().get("xsk_folder") or worker_prefs()["workspace"])
            options["code_style"] = str(options.get("code_style") or worker_prefs()["code_style"])
            options["code_length"] = str(options.get("code_length") or worker_prefs()["code_length"])
            root = _song_export_module().songs_root(options["xsk_folder"])
            if options.get("retry_issues_only") is True:
                review = _module("xsk_review.py", "xstage_xsk_review")
                incoming, count = review.pending_rows(
                    root, options["source"], cancelled=worker_cancel())
                with LOCK:
                    worker_job().update(total=count, discovered=count,
                                        scannedFiles=0, scanDone=True)
                update(f"ทบทวนเฉพาะ XSK ที่ไม่พร้อม/ERR {count:,} รายการ · ไม่สแกนเพลงสำเร็จ")
                result = build_xsk(incoming, "original", {
                    **options, "audio_only": False}, progressive=True)
            else:
                scanner = _module("xsk_stream.py", "xstage_xsk_stream")
                with LOCK:
                    scan_job_id = worker_job()["id"]
                with scanner.source_batches(
                        options["source"], root, cancelled=worker_cancel(),
                        batch_size=32, max_batches=4,
                        on_scan=lambda data, done, backlog: _xsk_stream_scan_status(
                            data, done, backlog, job_id=scan_job_id)) as incoming:
                    result = build_xsk(incoming, "original", {
                        **options, "audio_only": False}, progressive=True)
        elif action in ("build", "preview"):
            mode = worker_prefs().get("mode", "original")
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
            result = (build_xsk(rows, mode, options) if _xsk_format(options) == "xsk"
                      else build_library(rows, mode, options)) if action == "build" else build_preview(rows, mode)
        elif action == "lyric-groups-scan":
            root = lyric_source_root()
            if not (root / "current.json").is_file():
                raise ValueError("รองรับเฉพาะคลัง Lyrics JSON ที่สร้างแล้ว · ไม่แก้ LYR/CUR/NCN ต้นฉบับ")
            update("กำลังวิเคราะห์ข้อความใน Lyrics JSON · ไม่อ่าน MID/LYR/CUR")
            index = LYRIC_TEXT.scan(
                root, _song_export_module(), cancelled=worker_cancel(),
                on_progress=lambda detail, done: update(detail, done))
            with LOCK:
                global LYRIC_TEXT_INDEX
                LYRIC_TEXT_INDEX = index
            result = {
                "message": (f"วิเคราะห์ Lyrics JSON เสร็จ {index['songs']:,} เพลง "
                            f"· กลุ่มข้อความ {index['groupCount']:,} กลุ่ม "
                            f"· ข้ามไม่สมบูรณ์ {index['skippedInvalid']:,} รายการ"),
                "songs": index["songs"], "groups": index["groupCount"],
                "skippedInvalid": index["skippedInvalid"],
                "withoutLyrics": index["withoutLyrics"], "sourceMode": "stageweb"
            }
        elif action == "lyric-groups-replace":
            with LOCK:
                index = LYRIC_TEXT_INDEX
            if index is None:
                raise ValueError("กรุณากดวิเคราะห์ข้อความก่อนเริ่มแทนที่")
            root = lyric_source_root()
            groups = options.get("groups")
            if groups is None and options.get("group"):
                groups = [options["group"]]
            new_text = options.get("replacement")
            search = options.get("search", "")
            planned = LYRIC_TEXT.plan(index, groups, search=search,
                                      replacement=new_text)
            with LOCK:
                worker_job()["total"] = planned["changedSongs"]
            update(f"Smart Batch: ตรวจทุกเพลงและเตรียมสำรอง {planned['groups']:,} กลุ่ม · "
                   f"{planned['changedLines']:,} บรรทัดใน {planned['changedSongs']:,} เพลง")
            result = LYRIC_TEXT.apply_many_smart(
                root, _song_export_module(), index,
                groups, new_text, LYRIC_TEXT_BACKUPS, search=search,
                expected_count=options.get("expectedCount"),
                cancelled=worker_cancel(),
                on_progress=lambda detail, done: update(detail, done))
            # Keep LYRIC_TEXT_INDEX: apply_many updates only changed members.
            # All unedited groups remain available for the next batch.
        elif action == "lyric-groups-undo":
            root = lyric_source_root()
            update("กำลังตรวจไฟล์หลังแก้ไขและย้อนคืนจากชุดสำรอง")
            result = LYRIC_TEXT.undo(LYRIC_TEXT_BACKUPS, root, options.get("backupId"))
            with LOCK:
                LYRIC_TEXT_INDEX = None
        elif action == "ai-separate-vocals":
            song_id = options.get("id")
            with LOCK:
                worker_job()["total"] = 1
            result = separate_ai_lyrics_vocals(song_id)
        elif action == "ai-export":
            with LOCK:
                worker_job()["total"] = 2
            result = export_ai_lyrics_files(
                options.get("id"),
                include_lyrics=options.get("lyrics") is True,
                include_instrumental=options.get("instrumental") is True,
                include_source=options.get("source") is True,
                source_format=options.get("source_format", "original"))
        elif action == "ai-lyrics":
            song_id = options.get("id")
            with LOCK:
                row = dict(FILE_BY_ID.get(song_id) or {}) if type(song_id) is int else {}
                worker_job()["total"] = 1
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
                DATA, RUNTIME, ffmpeg_binary(), worker_cancel(), update, language=lang,
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
                worker_job()["total"] = 1
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
                    DATA, RUNTIME, ffmpeg, worker_cancel(), update,
                    language=options.get("language", "th"), draft_source=original)
            if worker_cancel().is_set():
                raise RuntimeError("ผู้ใช้ยกเลิกการจัดเวลาเนื้อเพลง")
            aligned = LYRIC_ALIGNMENT.align_lyrics(owner_lyrics, draft)
            update("จัดเวลาเบื้องต้นแล้ว · ต้องฟังตรวจทุกบรรทัดก่อนบันทึก", 1)
            result = {**aligned, "songId": song_id,
                      "message": aligned["message"] +
                      " · ผลลัพธ์อยู่ในช่องแก้ไขเท่านั้น ยังไม่ได้บันทึกหรืออัปโหลด"}
        elif action == "login":
            update("เปิด Google Login บนเบราว์เซอร์ · รออนุญาตจากเจ้าของบัญชี")
            account = GOOGLE.login(cancelled=worker_cancel(), on_status=update)
            if not account.get("configured") or not account.get("connected"):
                raise RuntimeError("Google คืนผลลัพธ์ แต่ Song Studio ยังไม่ได้บันทึกสิทธิ์ Google Drive")
            log("Google Login สำเร็จ: " + account.get("email", "(ไม่มีชื่ออีเมล)"))
            result = {"message": "Google Drive เชื่อมต่อแล้วใน Song Studio PC · " +
                      account.get("email", "(ไม่พบชื่อบัญชี)"),
                      "google": account}
        elif action == "logout":
            GOOGLE.logout()
            result = {"message": "ออกจาก Google บน PC เครื่องนี้แล้ว (สิทธิ์ใน Google Account ยังถอนได้จากบัญชี Google)"}
        elif action == "upload-soundfont":
            with LOCK:
                worker_job()["total"] = 1
            update("กำลังตรวจ SoundFont SF2/SF3 ก่อนอัปโหลด")
            result = FOLDER_UPLOAD.upload_soundfont(
                GOOGLE, worker_prefs().get("soundfont", ""),
                create_new_library=(options.get("create_new_library") is True),
                cancelled=worker_cancel(), progress=lambda stage: update(stage))
            update(result["message"], 1)
        elif action == "pc-export":
            module = _module("pc_library_export.py", "xstage_pc_export")
            local_source = _song_export_module().songs_root(worker_prefs()["workspace"])
            update("กำลังตรวจ XStageSong ต้นทางและพื้นที่เก็บปลายทาง")
            result = module.publish(
                local_source, worker_prefs().get("pc_export_folder", ""),
                _song_export_module(), cancelled=worker_cancel(),
                progress=lambda done, total, name: update(
                    f"คัดลอกไฟล์เข้า XStageSong {done:,}/{total:,} · {name}", done))
            update(result["message"], result["files"])
        elif action == "upload-folder":
            root = worker_prefs().get("upload_folder", "").strip()
            with LOCK:
                worker_job()["total"] = 1
            update("กำลังตรวจเพลงและไฟล์ประกอบในโฟลเดอร์ที่เลือก")
            online_module = _module("online_publish.py", "xstage_online_publish")
            result = FOLDER_UPLOAD.upload(
                GOOGLE, root,
                create_new_library=(options.get("create_new_library") is True),
                cancelled=worker_cancel(), export=_song_export_module(),
                publisher=online_module.OnlinePublisher(GOOGLE),
                staging_root=DATA, validator=online_module._valid_row,
                renderer=lambda src, dest: convert({"path": str(src)}, dest),
                video_renderer=render_browser_video, ncn=NCN,
                progress=lambda done, total, name: update(
                    f"ตรวจและเผยแพร่ {done:,}/{total:,} · {name}", done))
        elif action == "upload":
            export = _song_export_module()
            root = export.songs_root(worker_prefs()["workspace"])
            pointer, _ = export._read_current(root)
            if not pointer:
                raise ValueError("ไม่พบ XStageSong/current.json กรุณาสร้างเพลงก่อนอัปโหลด")
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
                worker_job()["total"] = len(records)
            update("ตรวจเพลงซ้ำจาก XStageSong เดิมก่อนอัปโหลด · ไม่ลบเพลงเดิม")
            synced = online.OnlinePublisher(GOOGLE).publish(
                root, records,
                create_new_library=(options.get("create_new_library") is True),
                cancelled=worker_cancel(),
                on_progress=lambda sent, total:
                update(f"อัปโหลดไฟล์ส่วนตัว {sent:,}/{total:,} bytes"),
                on_batch=lambda batch, total, created, revised:
                update(f"เผยแพร่ฐาน XStageSong ชุดที่ {batch} แล้ว · "
                       f"พร้อมเล่น {total:,} เพลง · เพิ่ม {created:,} · แก้ Lyrics {revised:,}"),
                on_row=lambda done, total, skipped:
                update(f"ตรวจและอัปโหลด {done + skipped:,}/{total + skipped:,} เพลง "
                       "· รวมเพลงที่ข้ามซ้ำโดยตรวจ MD5 แล้ว", done + skipped))
            result = {
                "message": (
                    f"ซิงค์ XStageSong สำเร็จ · เพลงใหม่ {synced['newSongs']} · "
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
                    worker_job()["total"] = total
                update(f"ดาวน์โหลดและตรวจ MD5 {done:,}/{total:,} ไฟล์", done)
            result = GOOGLE.download_library(
                worker_prefs()["download"], kind=kind, cancelled=worker_cancel(),
                on_status=update, on_item=downloaded_item)
            result["message"] = f"ดาวน์โหลด {result['files']} ไฟล์เสร็จแล้ว · {result['path']}"
        elif action == "check-update":
            result = _module("pc_ready_updates.py", "xstage_pc_ready_updates").check(
                STATUS_VERSION, STATUS_BUILD)
            update("ตรวจรุ่นล่าสุดจาก GitHub Releases เสร็จแล้ว", 1)
        elif action == "download-update":
            updater = _module("pc_ready_updates.py", "xstage_pc_ready_updates")
            result = updater.download(
                DATA / "verified-updates", STATUS_VERSION, STATUS_BUILD,
                cancelled=worker_cancel(), on_progress=lambda done, total: (
                    update(f"ดาวน์โหลด ZIP รุ่นใหม่ {done:,}/{total:,} ไบต์", done)))
            update("ดาวน์โหลด ZIP และตรวจ SHA-256 สำเร็จ", 1)
        elif action == "install-update":
            if not READY_BUNDLE or os.name != "nt":
                raise ValueError("ติดตั้งอัปเดตอัตโนมัติรองรับเฉพาะ PC Ready บน Windows")
            updater = _module("pc_ready_updates.py", "xstage_pc_ready_updates")
            update("กำลังดาวน์โหลดและตรวจ SHA-256 รุ่นใหม่", 0)
            package = updater.download(
                DATA / "verified-updates", STATUS_VERSION, STATUS_BUILD,
                cancelled=worker_cancel(), on_progress=lambda done, total: (
                    update(f"กำลังดาวน์โหลด {done:,}/{total:,} ไบต์", done)))
            if not package.get("update"):
                result = {"message": "โปรแกรมเป็นรุ่นล่าสุดที่เผยแพร่แล้ว"}
            else:
                update("กำลังตรวจ ZIP และติดตั้งในโฟลเดอร์รุ่นใหม่", 0)
                result = updater.install(
                    package["path"], ROOT, cancelled=worker_cancel(),
                    on_progress=lambda done, total: update(
                        f"กำลังติดตั้ง {done:,}/{total:,} ไฟล์", done),
                    launch=True)
                update("ติดตั้งและเปิดรุ่นใหม่แล้ว · หน้าต่างรุ่นเดิมจะปิดเอง", 1)
        else:
            raise RuntimeError("คำสั่งไม่ถูกต้องหรือยังไม่รองรับ: " + str(action))
        with LOCK:
            build_errors = (
                (action in ("build", "json-pro-export", "xsk-stream")
                 and result.get("errors", 0) > 0)
                or (action == "upload" and
                    (result.get("conflicts", 0) > 0 or result.get("notReady", 0) > 0)))
            skipped_only = (action == "build" and result.get("created", 0) == 0
                            and result.get("skipped", 0) > 0)
            worker_job().update(
                state="cancelled" if worker_cancel().is_set() else "error" if build_errors else "success", result=result,
                stage=("ยกเลิกงานแล้ว" if worker_cancel().is_set() else
                       "ซิงค์บางส่วน · มีเพลงที่ต้องตรวจสอบ" if build_errors and action == "upload" else
                       "สร้างเพลงบางรายการไม่สำเร็จ" if build_errors else
                       "ไม่มีเพลงใหม่ · ยืนยันจาก Catalog แล้ว" if skipped_only else
                       "เสร็จสิ้น"),
                detail=result.get("message", "เสร็จแล้ว"))
        if worker_job()["state"] == "success":
            try:
                output_folder = completed_job_folder(action, result, worker_prefs())
                if output_folder:
                    with LOCK:
                        worker_job()["outputFolder"] = output_folder
            except (OSError, ValueError, KeyError):
                pass
        if (action == "install-update" and result.get("launched")
                and os.name == "nt" and READY_BUNDLE):
            # Leave enough time for the browser to receive the success result.
            # New Ready engine runs from its own verified version folder.
            timer = threading.Timer(3.0, close_old_version_after_handoff)
            timer.daemon = True
            timer.start()
    except Exception as exc:
        with LOCK:
            worker_job()["state"] = "cancelled" if worker_cancel().is_set() else "error"
            worker_job()["stage"] = "ยกเลิกงาน" if worker_cancel().is_set() else "เกิดข้อผิดพลาด"
        log(str(exc))
    finally:
        with LOCK:
            worker_job()["elapsed"] = time.monotonic() - started
            worker_job()["updated"] = time.monotonic()

def validate_build_request(data):
    """Reject impossible builds BEFORE saying that the PC Engine started."""
    ids = data.get("ids")
    if not isinstance(ids, list) or not ids or len(ids) > 100_000:
        raise ValueError("กรุณาเลือกเพลงอย่างน้อย 1 เพลงก่อนสั่งสร้าง")
    if not all(type(item) is int for item in ids):
        raise ValueError("รหัสรายการเพลงไม่ถูกต้อง กรุณาสแกนและเลือกรายการใหม่")
    if not isinstance(data.get("audio_only", False), bool):
        raise ValueError("ประเภทคำสั่งสร้างเพลงไม่ถูกต้อง")
    export_format = data.get("export_format", worker_prefs().get("export_format", "xsk"))
    if export_format not in ("xsk", "xstage", "m4a"):
        raise ValueError("รูปแบบส่งออกไม่รองรับ")
    if (export_format != "xsk" or data.get("audio_only")) and not _module("pro_license.py", "xstage_pro_license").enabled(DATA):
        raise ValueError("รูปแบบส่งออกนี้ต้องใช้สิทธิ์ X-Stage Song Studio PC Pro")
    if data.get("edit_head_tail", "no") not in ("no", "yes"):
        raise ValueError("ตัวเลือกแก้หัว–ท้ายไม่ถูกต้อง")
    if data.get("edit_head_tail") == "yes":
        if not any(data.get(k) for k in ("head_find", "tail_find")):
            raise ValueError("เลือกแก้หัว–ท้ายแล้ว กรุณาระบุข้อความต้นทาง")
        for k in ("head_find", "tail_find", "head_replace", "tail_replace"):
            if not isinstance(data.get(k, ""), str) or len(data.get(k, "")) > 500:
                raise ValueError("ข้อความหัว–ท้ายไม่ถูกต้อง")
    with LOCK:
        rows = [FILE_BY_ID.get(item) for item in ids]
    if any(row is None for row in rows):
        raise ValueError("รายการเพลงบางรายการไม่อยู่ในฐานปัจจุบัน กรุณาสแกนและเลือกเพลงใหม่")
    from collections import Counter
    formats = Counter(Path(row["path"]).suffix.lower() for row in rows)
    unsupported_count = sum(count for ext, count in formats.items() if ext in EXT_UNSUPPORTED)
    supported_count = len(rows) - unsupported_count
    if export_format == "xsk":
        supported_count = sum(1 for row in rows if Path(row["path"]).suffix.lower() in EXT_MIDI)
        unsupported_count = len(rows) - supported_count
    if supported_count == 0:
        raise ValueError(
            f"ไม่สามารถเริ่มสร้าง: เลือก {len(rows):,} เพลง แต่เป็น NCN ทั้งหมด "
            "ซึ่ง Song Studio PC Engine รุ่นนี้ยังแปลง NCN ไม่ได้ · "
            "กรุณาเลือก MP3/M4A/WAV หรือ MIDI/KAR ที่รองรับ")

    mode = worker_prefs().get("mode", "original")
    if mode not in ("original", "instrumental"):
        raise ValueError("ประเภทเสียงที่เลือกไม่ถูกต้อง")
    if mode == "instrumental" and not ai_available():
        raise ValueError("AI Separation ไม่พร้อม: โมเดลหรือไลบรารีไม่ครบในแพ็กเกจ")
    if export_format != "xsk" and any(Path(row["path"]).suffix.lower() != ".m4a" for row in rows) and not ffmpeg_binary():
        raise ValueError("ไม่พบ FFmpeg ในแพ็กเกจ จึงยังสร้างเพลงจากรูปแบบนี้ไม่ได้")
    if export_format != "xsk" and any(Path(row["path"]).suffix.lower() in EXT_MIDI for row in rows) and not sf_available():
        raise ValueError("ยังไม่ได้เลือก SoundFont ที่ใช้งานได้สำหรับเพลง MIDI/KAR")
    for row in rows[:5]:
        if not Path(row["path"]).is_file():
            raise ValueError("ไม่พบไฟล์ต้นฉบับ: " + str(row["path"]))
    workspace = worker_prefs().get("workspace", "").strip()
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
    global JOB, JOB_THREAD, CANCEL
    action = str(data.get("action", ""))
    if action == "ai-recording-save":
        raise ValueError("ยกเลิกฟังก์ชันบันทึกเสียงผ่านไมโครโฟนแล้ว")
    _check_resource_capacity(action)
    validation = validate_build_request(data) if action == "build" else {}
    if action == "duplicates-scan":
        location = str(data.get("source") or PREFS.get("dup_source") or "")
        if not location or not Path(location).expanduser().is_dir():
            raise ValueError("กรุณาเลือกโฟลเดอร์ต้นทางสำหรับตรวจเพลงซ้ำ")
        if data.get("matchMode", "exact") not in ("exact", "code"):
            raise ValueError("โหมดตรวจเพลงซ้ำไม่ถูกต้อง")
        validation = {"total": 0}
    if action == "duplicates-apply":
        chosen = data.get("selected")
        if (not isinstance(chosen, list) or not 1 <= len(chosen) <= 300
                or any(not isinstance(item, str) for item in chosen)):
            raise ValueError("เลือกไฟล์ซ้ำได้ครั้งละ 1–300 ไฟล์")
        if (data.get("confirmed") is not True or
                data.get("operation") not in ("move", "recycle") or
                not isinstance(data.get("previewId"), str) or
                not data.get("previewId")):
            raise ValueError("ต้องตรวจแผนไฟล์เพลงและไฟล์ประกอบก่อนยืนยันการย้าย/ลบ")
        if data.get("operation") == "move" and not (
                data.get("destination") or PREFS.get("dup_destination")):
            raise ValueError("กรุณาเลือกโฟลเดอร์ปลายทางสำหรับย้ายไฟล์ซ้ำ")
        validation = {"total": len(chosen)}
    if action == "xsk-stream":
        source = str(data.get("source") or PREFS.get("source") or "")
        target = str(data.get("xsk_folder") or PREFS.get("xsk_folder")
                     or PREFS.get("workspace") or "")
        if not source or not Path(source).expanduser().is_dir():
            raise ValueError("กรุณาเลือกโฟลเดอร์ MIDI ต้นทางที่เข้าถึงได้")
        if not target:
            raise ValueError("กรุณาเลือกปลายทางสำหรับสร้าง .XSK")
        if data.get("code_style", PREFS.get("code_style")) not in (
                "source", "numeric", "letters", "alphanumeric"):
            raise ValueError("ชนิดรหัสเพลงไม่ถูกต้อง")
        try:
            digits = int(data.get("code_length", PREFS.get("code_length", "5")))
        except (ValueError, TypeError) as exc:
            raise ValueError("จำนวนหลักรหัสไฟล์ต้องเป็นตัวเลข") from exc
        if not 1 <= digits <= 12:
            raise ValueError("จำนวนหลักรหัสไฟล์ต้องอยู่ระหว่าง 1–12")
        if not isinstance(data.get("retry_issues_only", False), bool):
            raise ValueError("ตัวเลือกทบทวน XSK ไม่ถูกต้อง")
        validation = {"total": 0}
    if action == "json-pro-export":
        if not _module("pro_license.py", "xstage_pro_license").enabled(DATA):
            raise ValueError("ส่งออก Lyrics JSON ต้องเปิดใช้ License Pro")
        if data.get("format") not in ("original", "m4a", "mp3", "wav", "flac", "ogg"):
            raise ValueError("รูปแบบการแปลงไฟล์ไม่ถูกต้อง")
        if data.get("code_style", PREFS.get("code_style", "numeric")) not in ("source", "numeric", "letters", "alphanumeric"):
            raise ValueError("ชนิดรหัสเพลงไม่ถูกต้อง")
        try:
            code_length = int(data.get("code_length", PREFS.get("code_length", "5")))
        except (ValueError, TypeError) as exc:
            raise ValueError("จำนวนหลักรหัสเพลงไม่ถูกต้อง") from exc
        if not 1 <= code_length <= 12:
            raise ValueError("จำนวนหลักรหัสเพลงต้องอยู่ระหว่าง 1–12")
        if not PREFS.get("json_source") or not PREFS.get("json_destination"):
            raise ValueError("กรุณาเลือกโฟลเดอร์ต้นทางและปลายทาง")
        if not isinstance(data.get("retry_errors_only", False), bool):
            raise ValueError("ตัวเลือกทบทวน ERR ไม่ถูกต้อง")
        validation = {"total": 0}
    if action == "created-xsk":
        if not _module("pro_license.py", "xstage_pro_license").enabled(DATA):
            raise ValueError("เมนูสร้าง .XSK จากเพลงที่สร้างแล้วต้องเปิดใช้ License Pro ในตั้งค่าก่อน")
        paths = data.get("paths")
        if (not isinstance(paths, list) or not paths
                or any(not isinstance(value, str) or not value for value in paths)
                or len(set(paths)) != len(paths)):
            raise ValueError("กรุณาเลือก Lyrics JSON อย่างน้อยหนึ่งเพลง")
        validation = {"total": len(paths)}
    if action == "lyric-skipped-recheck":
        raise ValueError("ยกเลิกเครื่องมือตรวจแก้ LYR/NCN · ให้แก้เฉพาะ Lyrics JSON")
    if action == "lyric-groups-replace":
        # Reject stale/ambiguous confirmation before starting a background
        # thread that could change many files at once.
        with LOCK:
            snapshot = LYRIC_TEXT_INDEX
        if snapshot is None:
            raise ValueError("ยังไม่ได้วิเคราะห์ข้อความหัว–ท้ายเพลง")
        if snapshot["root"] != str(lyric_source_root()):
            raise ValueError("โฟลเดอร์ต้นทางเปลี่ยนแล้ว กรุณาวิเคราะห์ใหม่")
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
            LYRIC_TEXT_BACKUPS, lyric_source_root())
        if not backup or data.get("backupId") != backup["id"]:
            raise ValueError("ชุดย้อนคืนไม่ตรงกับการแก้ไขล่าสุด กรุณาตรวจรายการสำรอง")
        validation = {"total": backup["songs"]}
    if action == "pc-export":
        module = _module("pc_library_export.py", "xstage_pc_export")
        source = _song_export_module().songs_root(PREFS["workspace"])
        inspection = module.inspect(
            source, PREFS.get("pc_export_folder", ""), _song_export_module())
        validation = {"total": inspection["files"], "destination": inspection["destination"]}
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
    if action == "download-update" and not READY_BUNDLE:
        raise ValueError("อัปเดตได้เฉพาะ Song Studio PC Ready ไม่ใช่ Source Preview")
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
        # Recheck under the lock; two HTTP requests may arrive simultaneously.
        _check_resource_capacity(action)
        CANCEL = threading.Event()
        now = time.monotonic()
        JOB = {
            "id": secrets.token_hex(8), "kind": action, "state": "running",
            "stage": "PC Engine รับคำสั่งแล้ว",
            "detail": ("กำลังเริ่มสแกน MIDI และสร้าง XSK คู่ขนานกัน" if action == "xsk-stream"
                       else ""),
            "completed": 0, "total": validation.get("total", 0),
            "elapsed": 0, "eta": None,
            "idleFor": 0, "logs": ["รับคำสั่งสำเร็จ · กำลังเตรียมการประมวลผล"], "result": {},
            "created": 0, "skipped": 0, "errors": 0, "m4aCount": 0, "lyricsCount": 0,
            "started": now, "updated": now
        }
        job_id = JOB["id"]
    def bound_worker():
        _WORKER_LOCAL.id = job_id
        _WORKER_LOCAL.job = job_data
        _WORKER_LOCAL.cancel = cancel_event
        _WORKER_LOCAL.prefs = preferences
        try:
            execute_job(action, data, now)
        finally:
            _WORKER_LOCAL.__dict__.clear()
    try:
        job_data = JOB
        cancel_event = CANCEL
        preferences = dict(PREFS)
        thread = threading.Thread(target=bound_worker, daemon=True,
                                  name="xstage-studio-" + action + "-" + job_id[:6])
        with LOCK:
            # Keep a bounded recent history; never remove a live worker.
            if len(ACTIVE_JOBS) > 30:
                for old_id, old_entry in list(ACTIVE_JOBS.items()):
                    if (len(ACTIVE_JOBS) <= 25):
                        break
                    if not old_entry["thread"].is_alive():
                        ACTIVE_JOBS.pop(old_id, None)
            ACTIVE_JOBS[job_id] = {"job": job_data, "cancel": cancel_event,
                                   "thread": thread, "group": job_group(action),
                                   "process": None}
            JOB_THREAD = thread
            thread.start()
    except Exception as exc:
        with LOCK:
            ACTIVE_JOBS.pop(job_id, None)
            JOB_THREAD = None
            JOB["state"] = "error"
            JOB["detail"] = "เริ่ม Thread สร้างเพลงไม่ได้: " + str(exc)
        raise RuntimeError("PC Engine เริ่มงานไม่ได้: " + str(exc)) from exc
    return {"id": job_id, "parallel": resource_snapshot(), **validation}

def open_picker(kind):
    """Show an actual Windows foreground picker; preserve Unicode/Thai paths.

    A hidden PowerShell host alone can leave FolderBrowserDialog behind
    Microsoft Edge. The bundled PS script supplies a top-most dialog owner,
    and base64-encoded UTF-8 stdout avoids Windows console encoding damage.
    """
    if kind not in ("source", "workspace", "download", "upload_folder", "pc_export_folder", "lyric_source", "xsk_folder", "json_source", "json_destination", "dup_source", "dup_destination", "soundfont", "oauth", "vocal"):
        raise ValueError("ประเภทหน้าต่างเลือกโฟลเดอร์/ไฟล์ไม่ถูกต้อง")
    if os.name != "nt":
        raise RuntimeError("หน้าต่างเลือกโฟลเดอร์แบบ PC รองรับเฉพาะ Windows")
    picker = ROOT / "pick_path.ps1"
    if not picker.is_file():
        raise RuntimeError("ไม่พบ pick_path.ps1 กรุณาแตกไฟล์ ZIP รุ่นใหม่ให้ครบก่อน")
    initial = str(PREFS.get("source", "") if kind == "vocal" else (PREFS.get("lyric_source") or PREFS["workspace"]) if kind == "lyric_source" else PREFS.get(kind) or "")
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
    """Return saved edits and original metadata before any AI transcription."""
    with LOCK:
        row = dict(FILE_BY_ID.get(song_id) or {}) if type(song_id) is int else {}
        note = dict(NOTES.get(row.get("path", ""), {}))
    if not row or Path(row["path"]).suffix.lower() not in EXT_AUDIO:
        raise ValueError("ต้องเลือกเพลงที่เป็นไฟล์เสียงสำหรับถอดคำร้อง")
    source = Path(row["path"])
    discovered = _source_audio_details(source)
    title = (str(note.get("title") or "").strip() or
             (discovered["title"] if str(row.get("title") or "") == source.stem else
              str(row.get("title") or "")) or source.stem)
    artist = (str(note.get("artist") or "").strip() or
              str(row.get("artist") or "").strip() or
              str(discovered["artist"] or "").strip() or "X-Stage Song Studio")
    draft = AI_LYRICS.load_draft(DATA, source)
    ready, reason = AI_LYRICS.readiness(RUNTIME)
    if ready and not ffmpeg_binary():
        ready, reason = False, "ไม่พบ FFmpeg ในแพ็กเกจ PC Ready"
    vocals = saved_ai_vocals(row)
    return {
        "id": song_id, "title": title, "artist": artist, "code": row["code"],
        "metadataSource": discovered["metadataSource"],
        "lyricsSource": discovered["lyricsSource"],
        "sourceLrc": discovered["timedLrc"],
        "sourcePlainLyrics": discovered["plainLyrics"],
        "savedPlainLyrics": str(note.get("plain_lyrics") or ""),
        "hasSavedPlainLyrics": "plain_lyrics" in note,
        "available": ready, "aiProblem": reason,
        "separationAvailable": ai_available() and bool(ffmpeg_binary()),
        "separatedVocals": str(vocals) if vocals else None,
        "hasDraft": bool(draft), "draft": draft,
        "approvedLrc": AI_LYRICS.replace_music_interlude_label(
            str(note.get("lyrics") or ""))
    }


def save_ai_source_details(song_id, title, artist, plain_lyrics):
    """Save user corrections separately from the immutable source audio."""
    if (type(song_id) is not int or not isinstance(title, str) or
            not isinstance(artist, str) or not isinstance(plain_lyrics, str)):
        raise ValueError("ข้อมูลชื่อเพลง ศิลปิน หรือเนื้อร้องไม่ถูกต้อง")
    title, artist = title.strip(), artist.strip()
    if not title or len(title) > 180 or len(artist) > 180 or len(plain_lyrics) > 100000:
        raise ValueError("กรุณาระบุชื่อเพลง และจำกัดความยาวข้อมูลให้อยู่ในเกณฑ์")
    with LOCK:
        row = AI_IMPORTED.get(song_id)
        if not row:
            raise ValueError("ไม่พบเพลงที่นำเข้าในหน้า AI")
        path = row["path"]
        old_note = dict(NOTES.get(path, {}))
        old_row = dict(row)
        NOTES[path] = {**old_note, "title": title, "artist": artist,
                       "plain_lyrics": plain_lyrics}
        row.update(title=title, artist=artist)
        try:
            save_json(NOTES_FILE, NOTES)
            save_json(AI_IMPORTS_FILE,
                      [{"id": item["id"], "path": item["path"],
                        "title": item["title"], "artist": item["artist"]}
                       for item in AI_IMPORTED.values()])
        except Exception:
            NOTES[path] = old_note
            row.update(old_row)
            raise
    return {"ok": True, "title": title, "artist": artist,
            "message": "บันทึกชื่อเพลง ศิลปิน และเนื้อร้องที่ไม่มีเวลาในข้อมูลส่วนตัวแล้ว"}



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
    # Source LRC and manually timed lyrics can be reviewed without running AI.
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
        if re.match(r"^\[[a-z][a-z0-9_-]{1,30}:[^\]]*\]$", line, re.I):
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


def job_snapshot(job_id=None):
    with LOCK:
        entry = ACTIVE_JOBS.get(job_id) if job_id else ACTIVE_JOBS.get(JOB.get("id"))
        job = dict(entry["job"] if entry else JOB)
        thread = entry["thread"] if entry else JOB_THREAD
        worker_alive = bool(thread and thread.is_alive())
    if worker_alive and job["state"] != "running":
        job["finalState"] = job["state"]
        job["state"] = "running"
        job["stage"] = "กำลังคืนทรัพยากรของงานเดิม"
    if job["state"] == "running":
        elapsed = max(0, time.monotonic() - job.get("started", time.monotonic()))
        job["elapsed"] = elapsed
        job["idleFor"] = round(time.monotonic() - job.get("updated", time.monotonic()))
        if job["total"] > 0 and 0 < job["completed"] <= job["total"]:
            job["eta"] = (elapsed / job["completed"]) * (job["total"] - job["completed"])
        else:
            job["eta"] = None
    job.pop("updated", None)
    job.pop("started", None)
    return job

def completed_job_folder(action, result, prefs):
    """Return only a known, generated local output directory (not user input)."""
    export = _song_export_module()
    if action in ("xsk-stream", "created-xsk"):
        value = result.get("output")
        if value:
            folder = Path(value)
        else:
            folder = export.songs_root(prefs.get("xsk_folder") or prefs["workspace"]) / "MIDI" / "XSK"
    elif action == "json-pro-export":
        folder = export.songs_root(prefs["json_destination"])
    elif action == "build":
        folder = export.songs_root(prefs["workspace"])
    elif action == "pc-export":
        value = result.get("destination") or prefs.get("pc_export_folder")
        if not isinstance(value, str) or not value.strip():
            return None
        folder = Path(value)
    elif action in ("download", "download-update"):
        value = result.get("path")
        if not isinstance(value, str) or not value.strip():
            return None
        output = Path(value)
        folder = output if output.is_dir() else output.parent if output.is_file() else output
    else:
        return None
    # Resolve only existing directories, and do not treat the current
    # directory as an output for missing/empty result paths.
    if not str(folder).strip() or not folder.is_dir() or folder.is_symlink():
        return None
    return str(folder.resolve())


def job_snapshots():
    with LOCK:
        ids = list(ACTIVE_JOBS)[-20:]
    return [job_snapshot(job_id) for job_id in reversed(ids)]


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
                    "job": job_snapshot(), "jobs": job_snapshots(),
                    "resources": resource_snapshot(), "preferences": dict(PREFS),
                    "soundfonts": font_list(), "presets": formats(),
                    "google": GOOGLE.status(),
                    "update": {"status": "unavailable"}})
            elif path == "/api/xsk/review":
                if not PREFS.get("source"):
                    self._deny("กรุณาเลือกโฟลเดอร์ MIDI ต้นทาง", 400)
                    return
                try:
                    review = _module("xsk_review.py", "xstage_xsk_review")
                    folder = _song_export_module().songs_root(
                        PREFS.get("xsk_folder") or PREFS["workspace"])
                    self._json(review.page(
                        folder, PREFS["source"], status=query.get("status", ["all"])[0],
                        offset=int(query.get("offset", ["0"])[0]), limit=50))
                except (OSError, ValueError, TypeError) as exc:
                    self._deny(str(exc), 400)
            elif path == "/api/json-pro/review":
                if not PREFS.get("json_destination") or not PREFS.get("json_source"):
                    self._deny("กรุณาเลือกต้นทางและปลายทางของ Lyrics JSON", 400)
                    return
                try:
                    review_module = _module("json_pro_review.py", "xstage_json_pro_review")
                    output_format = query.get("format", ["original"])[0]
                    status = query.get("status", ["all"])[0]
                    offset = int(query.get("offset", ["0"])[0])
                    self._json(review_module.review(
                        _song_export_module().songs_root(PREFS["json_destination"]),
                        PREFS["json_source"], output_format,
                        status=status, offset=offset, limit=50))
                except (OSError, ValueError, TypeError) as exc:
                    self._deny(str(exc), 400)
            elif path == "/api/duplicates":
                try:
                    offset = int(query.get("offset", ["0"])[0])
                    limit = int(query.get("limit", ["20"])[0])
                    self._json(DUPLICATES.REGISTRY.page(
                        offset=offset, limit=limit,
                        preferred_extension=query.get("prefer", [""])[0]))
                except (ValueError, TypeError) as exc:
                    self._deny(str(exc), 400)
            elif path == "/api/history":
                with LOCK:
                    self._json({"events": HISTORY.list_events(HISTORY_FILE)})
            elif path == "/api/pc-export/inspect":
                module = _module("pc_library_export.py", "xstage_pc_export")
                self._json(module.inspect(
                    _song_export_module().songs_root(PREFS["workspace"]),
                    PREFS.get("pc_export_folder", ""), _song_export_module()))
            elif path == "/api/upload-folder/inspect":
                self._json(FOLDER_UPLOAD.report(PREFS.get("upload_folder", ""), _song_export_module(), ncn=NCN))
            elif path == "/api/license/status":
                self._json({"pro": _module("pro_license.py", "xstage_pro_license").enabled(DATA)})
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
            elif path == "/api/import-preview/list":
                kind = query.get("kind", [""])[0]
                with LOCK:
                    snapshot = dict(IMPORT_PREVIEW)
                selected_folder = PREFS.get("upload_folder", "") if kind == "online" else PREFS.get("workspace", "")
                if kind != snapshot["kind"] or selected_folder != snapshot["folder"]:
                    self._json({"total": 0, "rows": [], "needsScan": True})
                else:
                    module = _module("import_preview.py", "xstage_import_preview")
                    self._json(module.page(
                        snapshot["items"], search=query.get("search", [""])[0],
                        offset=max(0, int(query.get("offset", ["0"])[0])),
                        limit=max(1, min(100, int(query.get("limit", ["50"])[0])))))
            elif path == "/api/songs/ids":
                found = visible_files(query.get("search", [""])[0],
                                      query.get("view", ["all"])[0])
                if query.get("midi_only", ["0"])[0] == "1":
                    found = [row for row in found
                             if Path(row["path"]).suffix.lower() in EXT_MIDI]
                self._json({"ids": [row["id"] for row in found]})
            elif path == "/api/created-json/paths":
                module = _module("created_json_manager.py", "xstage_created_json_manager")
                self._json(module.list_created_paths(
                    _song_export_module().songs_root(PREFS["workspace"]),
                    _song_export_module(), search=query.get("search", [""])[0],
                    midi_only=True))
            elif path == "/api/created-json":
                module = _module("created_json_manager.py", "xstage_created_json_manager")
                self._json(module.list_created(
                    _song_export_module().songs_root(PREFS["workspace"]),
                    _song_export_module(),
                    search=query.get("search", [""])[0],
                    offset=max(0, int(query.get("offset", ["0"])[0])),
                    limit=max(1, min(200, int(query.get("limit", ["50"])[0]))),
                    midi_only=True))
            elif path == "/api/songs":
                rows = visible_files(query.get("search", [""])[0],
                                     query.get("view", ["all"])[0])
                if query.get("audio_only", ["0"])[0] == "1":
                    rows = [row for row in rows if
                            Path(row["path"]).suffix.lower() in EXT_AUDIO]
                if query.get("midi_only", ["0"])[0] == "1":
                    rows = [row for row in rows if
                            Path(row["path"]).suffix.lower() in EXT_MIDI]
                limit = max(1, min(500, int(query.get("limit", ["100"])[0])))
                offset = max(0, int(query.get("offset", ["0"])[0]))
                page_rows = rows[offset:offset + limit]
                # Enrich only the small preview page, never the full catalog.
                if query.get("preview_identity", ["0"])[0] == "1":
                    page_rows = [{**item, **preview_song_identity(item)}
                                 for item in page_rows]
                self._json({"rows": page_rows, "total": len(rows)})
            elif path in ("/api/lyric-groups-skipped", "/api/lyric-groups-skipped.csv"):
                raise ValueError("ยกเลิกเมนูจัดการ NCN ต้นฉบับแล้ว · ใช้ Lyrics JSON")
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
            elif path == "/api/lyric-groups/ids":
                with LOCK:
                    snapshot = LYRIC_TEXT_INDEX
                if snapshot is None:
                    raise ValueError("ยังไม่มีผลวิเคราะห์กลุ่มข้อความ")
                position = query.get("position", ["first"])[0]
                only_repeats = query.get("repeats", ["1"])[0] != "0"
                matches = LYRIC_TEXT.list_groups(
                    snapshot, position,
                    search=query.get("search", [""])[0],
                    offset=0, limit=1000, repeats_only=only_repeats)
                self._json({"ids": [row["id"] for row in matches["rows"]],
                            "total": matches["total"], "limit": 1000})
            elif path == "/api/lyric-groups-preview":
                with LOCK:
                    snapshot = LYRIC_TEXT_INDEX
                if snapshot is None:
                    raise ValueError("กลุ่มข้อความหมดอายุ กรุณาวิเคราะห์ใหม่")
                self._json(LYRIC_TEXT.preview(
                    snapshot, query.get("group", [""])[0],
                    search=query.get("search", [""])[0]))
            elif path == "/api/lyric-groups-backup":
                root = lyric_source_root()
                self._json({"latest": LYRIC_TEXT.latest_backup(LYRIC_TEXT_BACKUPS, root)})
            elif path == "/api/vocal-songs":
                search = query.get("search", [""])[0]
                offset = max(0, int(query.get("offset", ["0"])[0]))
                limit = max(1, min(60, int(query.get("limit", ["30"])[0])))
                self._json(available_vocal_sources(search, offset, limit))
            elif path == "/api/ai-lyrics-source":
                try:
                    song_id = int(query.get("id", [""])[0])
                except ValueError as exc:
                    raise ValueError("กรุณาเลือกเพลงเสียงร้อง") from exc
                with LOCK:
                    selected = dict(AI_IMPORTED.get(song_id) or {})
                if not selected:
                    raise ValueError("ไม่พบไฟล์ที่นำเข้าในเมนู Lyrics AI")
                source = Path(selected["path"])
                if not source.is_file() or source.is_symlink() or source.suffix.lower() not in EXT_AUDIO:
                    raise ValueError("ไฟล์ต้นฉบับถูกย้าย หรือไม่รองรับการอ่าน")
                self._json(_source_audio_details(source))
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
        if path not in ("/index.html", "/app.js", "/style.css", "/pro-design.css", "/entry.js", "/app-icon.svg", "/app-icon-512.png", "/app-icon.ico", "/site.webmanifest"):
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
        if length > 1048576 or length <= 0:
            self._deny("ขนาดคำสั่งไม่ถูกต้อง", 413)
            return
        try:
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("คำสั่งไม่ถูกต้อง")
            path = urllib.parse.urlsplit(self.path).path
            if path == "/api/license/activate":
                license_module = _module("pro_license.py", "xstage_pro_license")
                license_module.activate(DATA, payload.get("key", ""))
                self._json({"pro": True})
            elif path == "/api/config":
                previous_preferences = HISTORY.safe_preferences(PREFS)
                previous_catalog_key = (PREFS["source"], PREFS["workspace"])
                previous_lyric_source = PREFS["lyric_source"]
                if "lyric_source" in payload:
                    requested = payload["lyric_source"]
                    if not isinstance(requested, str) or len(requested) > 2048:
                        raise ValueError("ตำแหน่งคลังเนื้อร้องไม่ถูกต้อง")
                    if requested.strip() != previous_lyric_source and JOB["state"] == "running":
                        raise ValueError("มีงานกำลังดำเนินการอยู่ · เปลี่ยนโฟลเดอร์ต้นทางไม่ได้")
                    if requested.strip():
                        lyric_source_root(requested.strip())
                if ("export_format" in payload and payload["export_format"] != "xsk"
                        and not _module("pro_license.py", "xstage_pro_license").enabled(DATA)):
                    raise ValueError("ต้องเปิดใช้ License Key Pro ก่อนเลือกส่งออกแบบเดิม")
                if "catalog_view" in payload and payload["catalog_view"] not in ("changes", "all"):
                    raise ValueError("ตัวกรองรายการเพลงไม่ถูกต้อง")
                if "code_style" in payload and payload["code_style"] not in ("source", "numeric", "letters", "alphanumeric"):
                    raise ValueError("รูปแบบรหัสเพลงไม่ถูกต้อง")
                if "code_length" in payload:
                    try:
                        count = int(payload["code_length"])
                    except (ValueError, TypeError):
                        raise ValueError("จำนวนหลักรหัสเพลงไม่ถูกต้อง")
                    if not 1 <= count <= 12:
                        raise ValueError("จำนวนหลักต้องอยู่ระหว่าง 1 ถึง 12")
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
                if (previous_catalog_key != (PREFS["source"], PREFS["workspace"])
                        or previous_lyric_source != PREFS["lyric_source"]):
                    with LOCK:
                        global LYRIC_TEXT_INDEX
                        LYRIC_TEXT_INDEX = None
                if previous_catalog_key != (PREFS["source"], PREFS["workspace"]):
                    restore_song_catalog()
                    restore_scan_changes()
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
                    restore_scan_changes()
                self._json({"ok": True, "preferences": dict(PREFS),
                            "message": "คืนค่าจากประวัติและบันทึกอัตโนมัติแล้ว"})
            elif path == "/api/created-json/format":
                with LOCK:
                    if JOB["state"] == "running":
                        raise ValueError("มีงานอื่นกำลังดำเนินการ · ไม่จัดรูปแบบ JSON ระหว่างสร้างเพลง")
                module = _module("created_json_manager.py", "xstage_created_json_manager")
                self._json(module.format_created(
                    _song_export_module().songs_root(PREFS["workspace"]),
                    _song_export_module(), payload.get("paths"),
                    dry_run=payload.get("dryRun") is not False))
            elif path == "/api/created-json/restore":
                with LOCK:
                    if JOB["state"] == "running":
                        raise ValueError("ไม่ย้อนคืนระหว่างมีงานกำลังสร้างเพลง")
                module = _module("created_json_manager.py", "xstage_created_json_manager")
                self._json(module.restore_created(
                    _song_export_module().songs_root(PREFS["workspace"]),
                    _song_export_module(), payload.get("path"),
                    payload.get("backup"), payload.get("sha256")))
            elif path == "/api/import-preview/scan":
                if JOB["state"] == "running":
                    raise ValueError("ไม่สามารถสแกนพรีวิวขณะกำลังนำเข้าหรือสร้างเพลง")
                kind = payload.get("kind")
                if kind not in ("online", "pc"):
                    raise ValueError("เมนูพรีวิวไม่ถูกต้อง")
                folder = PREFS.get("upload_folder", "") if kind == "online" else PREFS.get("workspace", "")
                module = _module("import_preview.py", "xstage_import_preview")
                items = module.scan(kind, folder, PREFS["workspace"],
                                    _song_export_module(), FOLDER_UPLOAD, NCN)
                with LOCK:
                    IMPORT_PREVIEW.update(kind=kind, folder=folder, items=items)
                self._json(module.page(items))
            elif path == "/api/import-preview/lyrics":
                kind, selected = payload.get("kind"), payload.get("id")
                with LOCK:
                    snapshot = dict(IMPORT_PREVIEW)
                folder = PREFS.get("upload_folder", "") if kind == "online" else PREFS.get("workspace", "")
                if (kind != snapshot["kind"] or folder != snapshot["folder"]
                        or type(selected) is not int or not 0 <= selected < len(snapshot["items"])):
                    raise ValueError("รายการพรีวิวหมดอายุ กรุณาสแกนใหม่")
                module = _module("import_preview.py", "xstage_import_preview")
                self._json(module.lyrics(snapshot["items"][selected], _song_export_module(), NCN))
            elif path == "/api/import-preview/play":
                kind, selected = payload.get("kind"), payload.get("id")
                with LOCK:
                    snapshot = dict(IMPORT_PREVIEW)
                folder = PREFS.get("upload_folder", "") if kind == "online" else PREFS.get("workspace", "")
                if (kind != snapshot["kind"] or folder != snapshot["folder"]
                        or type(selected) is not int or not 0 <= selected < len(snapshot["items"])):
                    raise ValueError("รายการพรีวิวหมดอายุ กรุณาสแกนใหม่")
                if JOB["state"] == "running":
                    raise ValueError("มีงานกำลังประมวลผล กรุณาทดลองฟังเมื่อเสร็จ")
                item = snapshot["items"][selected]
                source = item["audio"]
                if not source.is_file() or source.is_symlink():
                    raise ValueError("ไฟล์เสียงต้นฉบับไม่พร้อมใช้งาน")
                midi = source.suffix.lower() in EXT_MIDI
                if not midi and not ffmpeg_binary():
                    raise ValueError("FFmpeg ไม่พร้อมสำหรับทดลองฟังไฟล์เสียง")
                soundfont = PREFS.get("soundfont") or str(DEFAULT_SOUNDFONT)
                if midi and (not Path(soundfont).is_file() or not ffmpeg_binary()):
                    raise ValueError("ทดลองฟัง MIDI ต้องมี SoundFont และ FFmpeg")
                live = _module("live_preview.py", "xstage_import_live")
                session = secrets.token_urlsafe(20)
                ticket = secrets.token_urlsafe(32)
                now = time.monotonic()
                controls = live.LiveControls(.85, .8, soundfont if midi else None)
                with LOCK:
                    LIVE_SESSIONS[session] = {"started": False, "controls": controls,
                                              "expires": now + 120}
                    LIVE_TICKETS[ticket] = {
                        "expires": now + 90, "session": session,
                        "audio": None if midi else source,
                        "midi": source if midi else None,
                        "soundfont": soundfont if midi else None}
                self._json({"ticket": ticket, "session": session,
                            "format": source.suffix.lstrip(".").upper()})
            elif path == "/api/lyric-groups-plan":
                with LOCK:
                    snapshot = LYRIC_TEXT_INDEX
                if snapshot is None:
                    raise ValueError("กรุณาวิเคราะห์ข้อความหัว–ท้ายเพลงก่อน")
                planned = LYRIC_TEXT.plan(
                    snapshot, payload.get("groups"), search=payload.get("search", ""),
                    replacement=payload.get("replacement"))
                planned["sourceMode"] = snapshot.get("mode", "stageweb")
                self._json(planned)
            elif path == "/api/ai-import":
                self._json(import_ai_audio(payload.get("path")))
            elif path == "/api/folder-picker":
                kind = payload.get("kind", "")
                if kind not in ("source", "workspace", "download", "upload_folder", "pc_export_folder", "lyric_source", "xsk_folder", "json_source", "json_destination", "dup_source", "dup_destination", "soundfont", "oauth", "vocal"):
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
                active_output = (PREFS.get("xsk_folder") or PREFS["workspace"]) if PREFS.get("export_format") == "xsk" else PREFS["workspace"]
                workspace = Path(active_output).expanduser()
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
            elif path == "/api/ai-lyrics-details":
                self._json(save_ai_source_details(
                    payload.get("id"), payload.get("title"),
                    payload.get("artist"), payload.get("plainLyrics")))
            elif path == "/api/google-login-focus":
                # Reopen the exact in-progress Google OAuth URL. The browser
                # never receives the OAuth URL or the refresh token via our API.
                self._json(GOOGLE.show_pending_login())
            elif path == "/api/duplicates/plan":
                self._json(DUPLICATES.REGISTRY.plan(
                    scan_id=payload.get("scanId"),
                    selected=payload.get("selected"),
                    operation=payload.get("operation"),
                    destination=payload.get("destination"),
                    keeper_by_group=payload.get("keeperByGroup") or {},
                    preferred_extension=payload.get("preferredExtension") or "",
                    include_companions=payload.get("includeCompanions", True),
                    same_song_confirmed=payload.get("sameSongConfirmed", False)))
            elif path == "/api/jobs":
                self._json(start_job(payload))
            elif path == "/api/jobs/open-output":
                job_id = payload.get("id")
                if not isinstance(job_id, str) or not job_id:
                    raise ValueError("กรุณาระบุเลขงานที่เสร็จแล้ว")
                with LOCK:
                    entry = ACTIVE_JOBS.get(job_id)
                    if not entry:
                        raise ValueError("ไม่พบงานนี้ หรือประวัติงานหมดอายุ")
                    job = entry["job"]
                    if job.get("state") != "success" or entry["thread"].is_alive():
                        raise ValueError("ต้องรอให้งานเสร็จก่อนเปิดปลายทาง")
                    folder = job.get("outputFolder")
                if not isinstance(folder, str) or not folder or not Path(folder).is_dir():
                    raise ValueError("งานนี้ไม่มีโฟลเดอร์ผลลัพธ์ในเครื่อง")
                if os.name != "nt":
                    raise ValueError("เปิดโฟลเดอร์อัตโนมัติรองรับ Windows เท่านั้น")
                subprocess.Popen(["explorer.exe", folder],
                                 stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
                self._json({"ok": True, "path": folder})
            elif path == "/api/jobs/cancel":
                requested = payload.get("id")
                if requested is not None and not isinstance(requested, str):
                    raise ValueError("รหัสงานไม่ถูกต้อง")
                with LOCK:
                    job_id = requested if requested is not None else JOB.get("id")
                    entry = ACTIVE_JOBS.get(job_id)
                    if requested is not None and entry is None:
                        raise ValueError("ไม่พบเลขงานที่ต้องการยกเลิก")
                    active = bool(entry and entry["thread"] and entry["thread"].is_alive()
                                  and not entry["cancel"].is_set())
                    if active:
                        entry["cancel"].set()
                        entry["job"]["stage"] = "กำลังยกเลิกงาน · รอหยุดให้เรียบร้อย"
                        entry["job"]["updated"] = time.monotonic()
                    p = entry.get("process") if active else None
                if p and p.poll() is None:
                    try:
                        p.terminate()
                    except OSError:
                        pass
                self._json({"ok": True, "id": job_id, "stopping": active})
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

def close_old_version_after_handoff():
    """Close only our isolated Edge app window, then retire this Engine.

    The updater calls this only after the new offline Engine confirms startup.
    Never terminate a shared browser profile or unrelated user processes.
    """
    browser = BROWSER_PROCESS
    if browser and browser.poll() is None:
        try:
            browser.terminate()
            browser.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            pass
    os._exit(0)


def main():
    global PORT, BROWSER_PROCESS
    count = 0
    try:
        count = restore_song_catalog()
        restore_scan_changes()
        if count:
            JOB["detail"] = f"โหลดดัชนีเพลงเดิมแล้ว {count:,} เพลง · กดสแกนด่วนเพื่ออัปเดต"
    except (OSError, ValueError) as exc:
        JOB["detail"] = "ไม่สามารถโหลดดัชนีเดิม: " + str(exc)
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        PORT = server.server_port
        # Do not scan the selected song folder or start conversion on launch.
        # The user explicitly starts work by pressing "ตกลง".
        url = f"http://127.0.0.1:{PORT}/#auth={TOKEN}"
        if READY_BUNDLE:
            # PC Ready uses its bundled Qt WebEngine. No external browser,
            # extension onboarding page or normal Edge profile is opened.
            from desktop_window import run_desktop
            run_desktop(server, url, DATA, UI_ROOT / "app-icon.ico")
            return
        # Source-preview remains usable without a bundled Qt runtime.
        webbrowser.open(url)
        server.serve_forever(poll_interval=0.25)

if __name__ == "__main__":
    main()
