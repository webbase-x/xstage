"""Read-only folder preflight and private, non-catalog media upload.

Raw uploaded files never modify XStageWeb/current.json or pretend to be
playable in Karaoke Online. Verified complete source sets use the requested
AUDIO / VIDEO / MIDI taxonomy and immutable content names on private Drive.
"""
from __future__ import annotations
import hashlib
import re
from pathlib import Path

FOLDER = "application/vnd.google-apps.folder"
BUCKETS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
VIDEO = {".avi": "AVI", ".mpg": "MPG", ".mpeg": "MPG", ".dat": "VCD",
         ".wmv": "WMV", ".vob": "VCD"}
AUDIO = {".mp3": "MP3", ".m4a": "M4A"}
MIDI = {".mid", ".midi", ".kar"}
LYRIC = {".lrc"}
SCAN_LIMIT = 250000


def digest(path):
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def bucket(stem):
    match = re.match(r"^([0-9A-Za-z])", stem)
    return match.group(1).upper() if match else "_"


def _safe_root(folder):
    if not isinstance(folder, str) or not folder.strip():
        raise ValueError("กรุณาเลือกโฟลเดอร์เพลงที่จะอัปโหลด")
    root = Path(folder).expanduser().resolve()
    if not root.is_dir() or Path(folder).is_symlink():
        raise ValueError("ไม่พบโฟลเดอร์เพลงที่เลือก หรือเป็น Symbolic Link")
    return root


def _indexed(root):
    files = []
    for path in root.rglob("*"):
        if path.is_symlink():
            continue
        if not path.is_file():
            continue
        files.append(path)
        if len(files) > SCAN_LIMIT:
            raise ValueError("พบไฟล์เกินขีดจำกัดการสแกน 250,000 ไฟล์")
    return files


def _probe_audio(path):
    # Real media is checked with FFprobe in the PC Engine before upload.
    return path.stat().st_size >= 1024


def _timed_lrc(path):
    try:
        text = path.read_text(encoding="utf-8-sig")
        stamps = []
        for line in text.splitlines():
            m = re.match(r"^\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]\s*(\S.+|\S)$", line.strip())
            if m:
                seconds = int(m.group(1)) * 60 + int(m.group(2))
                if int(m.group(2)) >= 60 or seconds < (stamps[-1] if stamps else -1):
                    return False
                stamps.append(seconds)
        return bool(stamps)
    except (UnicodeError, OSError, ValueError):
        return False


def _route(file, group, fmt):
    if group == "audio":
        sub = "Songs" if file.suffix.lower() in AUDIO else "Lyrics"
        return ("AUDIO", fmt, sub, bucket(file.stem))
    if group == "video":
        return ("VIDEO", fmt, bucket(file.stem))
    return ("MIDI", "NCN", {"mid": "Songs", "lyr": "Lyrics", "cur": "Cursor"}[fmt],
            bucket(file.stem))


def scan(folder):
    root = _safe_root(folder)
    paths = _indexed(root)
    by_dir = {}
    for path in paths:
        by_dir.setdefault((path.parent, path.stem.casefold()), []).append(path)
    complete, incomplete, unsupported = [], [], []
    handled = set()

    def add(reason, members):
        incomplete.append({"name": members[0].stem, "reason": reason})

    for key, members in sorted(by_dir.items(), key=lambda x: str(x[0])):
        if key in handled:
            continue
        handled.add(key)
        candidates = {}
        for p in members:
            candidates.setdefault(p.suffix.lower(), []).append(p)
        # A pair must be in the same directory with the exact same stem.
        audios = [p for p in members if p.suffix.lower() in AUDIO]
        videos = [p for p in members if p.suffix.lower() in VIDEO]
        midis = [p for p in members if p.suffix.lower() in MIDI]
        if audios or videos:
            media = audios + videos
            lyrics = candidates.get(".lrc", [])
            if len(media) != 1 or len(lyrics) != 1:
                add("ต้องมี Song และ .LRC ชื่อเดียวกันอย่างละ 1 ไฟล์", members)
                continue
            primary, lyric = media[0], lyrics[0]
            if not _probe_audio(primary) or not _timed_lrc(lyric):
                add("ไฟล์เพลงสั้นผิดปกติหรือเนื้อร้อง LRC ไม่มีเวลาที่ถูกต้อง", members)
                continue
            fmt = AUDIO.get(primary.suffix.lower()) or VIDEO[primary.suffix.lower()]
            group = "audio" if primary.suffix.lower() in AUDIO else "video"
            layout = [(primary, _route(primary, group, fmt))]
            if group == "audio":
                layout.append((lyric, _route(lyric, "audio", fmt)))
            else:
                # Video Lyrics share the VIDEO category; no false Online DB references.
                layout.append((lyric, ("VIDEO", fmt, "Lyrics", bucket(primary.stem))))
            complete.append({"name": primary.stem, "kind": fmt,
                             "files": layout})
        elif midis:
            cursors = candidates.get(".cur", [])
            lyrs = candidates.get(".lyr", [])
            if len(midis) != 1 or len(cursors) != 1 or len(lyrs) != 1:
                add("NCN ต้องมี MIDI/KAR + .LYR + .CUR ชื่อเดียวกัน", members)
                continue
            trio = (midis[0], lyrs[0], cursors[0])
            if any(p.stat().st_size < 8 for p in trio):
                add("NCN มีไฟล์ว่างหรือไม่สมบูรณ์", members)
                continue
            complete.append({"name": midis[0].stem, "kind": "NCN", "files": [
                (p, _route(p, "midi", ext)) for p, ext in
                zip(trio, ("mid", "lyr", "cur"))]})
        elif members:
            if any(p.suffix.lower() in (".emk", ".lrc", ".lyr", ".cur") for p in members):
                incomplete.append({"name": members[0].stem,
                                   "reason": "ไฟล์ประกอบไม่มีเพลงคู่กันหรือ EMK ยังไม่ได้ตรวจโครงสร้าง"})
            else:
                unsupported.append(members[0].name)
    return {"folder": str(root), "complete": complete,
            "incomplete": incomplete, "unsupported": unsupported,
            "fileCount": len(paths), "total": len(complete)}


def report(folder):
    result = scan(folder)
    return {"folder": result["folder"], "fileCount": result["fileCount"],
            "ready": result["total"], "incomplete": len(result["incomplete"]),
            "unsupported": len(result["unsupported"]),
            "examples": result["incomplete"][:12],
            "kinds": {kind: sum(row["kind"] == kind for row in result["complete"])
                      for kind in ("MP3", "M4A", "AVI", "MPG", "VCD", "WMV", "NCN")}}


def upload(drive, folder, *, create_new_library=False, cancelled=None, progress=None):
    from importlib import import_module
    result = scan(folder)
    if not result["complete"]:
        raise ValueError("ไม่พบชุดเพลงพร้อมอัปโหลด · ตรวจไฟล์เพลงและเนื้อร้องให้ครบก่อน")
    # Never merge uncatalogued media into an unverified Online code registry.
    from pathlib import Path
    roots = [x for x in drive.list_children("root")
             if x.get("name") in ("XStageWeb", "StageWeb")
             and x.get("mimeType") == FOLDER]
    if len(roots) > 1:
        raise ValueError("พบ XStageWeb/StageWeb ซ้ำกัน · กรุณาตรวจคลังเดิมก่อนอัปโหลด")
    if not roots and not create_new_library:
        raise ValueError("ไม่พบคลัง XStageWeb ที่เข้าถึงได้ · กรุณาตรวจสิทธิ์ Google Drive ก่อน")
    root_id = roots[0]["id"] if roots else drive.folder("root", "XStageWeb")
    cache = {}
    uploaded = skipped = 0
    finished = 0
    for row in result["complete"]:
        # Validate all companions again immediately before the group transfer.
        for path, _ in row["files"]:
            if not path.is_file() or path.is_symlink():
                raise ValueError("ไฟล์เปลี่ยนหลังตรวจสอบ: " + str(path))
        for path, parts in row["files"]:
            if cancelled and cancelled.is_set():
                raise ValueError("ยกเลิกการอัปโหลด · ไฟล์ที่ส่งก่อนหน้าจะคงอยู่บน Drive")
            parent = root_id
            prefix = []
            for part in parts:
                prefix.append(part)
                key = tuple(prefix)
                if key not in cache:
                    cache[key] = drive.folder(parent, part)
                parent = cache[key]
            md5 = digest(path)
            name = path.stem + "-" + md5[:16] + path.suffix.lower()
            status, _ = drive.upload_file(parent, path, name, cancelled=cancelled)
            if status == "created":
                uploaded += 1
            else:
                skipped += 1
        finished += 1
        if progress:
            progress(finished, result["total"], row["name"])
    return {"ready": result["total"], "uploadedFiles": uploaded,
            "skippedFiles": skipped, "incomplete": len(result["incomplete"]),
            "unsupported": len(result["unsupported"]), "catalogUnchanged": True,
            "message": f"อัปโหลดชุดไฟล์พร้อมใช้ {finished} ชุด · ส่งใหม่ {uploaded} ไฟล์ "
                       f"· ข้ามซ้ำ {skipped} · ไม่ครบ {len(result['incomplete'])} "
                       "· ไม่แก้ current.json (ไฟล์ต้นฉบับยังไม่ถูกเพิ่มเข้าฐานเล่นออนไลน์)"}
