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
        # Pair both same-directory originals and already sorted
        # AUDIO/{MP3,M4A}/{Songs,Lyrics}/A and MIDI/NCN/{Songs,Lyrics,Cursor}/A.
        # Keep the source collection prefix and bucket: never pair unrelated
        # tracks merely because their filenames match.
        parent = path.relative_to(root).parts[:-1]
        lowered = [part.casefold() for part in parent]
        role = next((i for i, part in enumerate(lowered)
                     if part in ("songs", "lyrics", "cursor")
                     and i > 0), None)
        if role is None:
            key = (tuple(lowered), path.stem.casefold())
        else:
            key = (tuple(lowered[:role] + lowered[role+1:]), path.stem.casefold())
        by_dir.setdefault(key, []).append(path)
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


def upload(drive, folder, *, create_new_library=False, cancelled=None,
           progress=None, export=None, publisher=None, staging_root=None):
    """Publish supported ready audio+lyrics sets through the SAME online DB.

    The existing Karaoke Online schema supports audio+timed JSON. Do not put
    unsupported VIDEO/NCN into the catalog and falsely claim playability.
    Original source files are never modified.
    """
    import json
    import shutil
    import tempfile
    if export is None or publisher is None or staging_root is None:
        raise ValueError("ต้องใช้ Online Publisher และตัวแปลง LRC ของ X-Stage")
    result = scan(folder)
    supported = [r for r in result["complete"] if r["kind"] in ("MP3", "M4A")]
    deferred = [r for r in result["complete"] if r["kind"] not in ("MP3", "M4A")]
    if not supported:
        raise ValueError("ยังไม่มี MP3/M4A พร้อมเนื้อร้องให้เผยแพร่ทันที · "
                         "VIDEO/NCN ยังไม่รองรับ Catalog สำหรับเล่นออนไลน์ จึงไม่อัปโหลดโดยอ้างว่าพร้อมเล่น")
    # Check the live catalogue before creating local files or modifying Drive.
    preview = publisher.read_code_registry(allow_missing_root=create_new_library)
    if not preview.get("visible") and not create_new_library:
        raise ValueError("ไม่พบ XStageWeb ที่มองเห็นได้ · ต้องยืนยันสร้างคลังใหม่")
    staging_root = Path(staging_root).expanduser()
    staging_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="xstage-upload-", dir=staging_root) as scratch:
        stage = Path(scratch)
        (stage / "audio").mkdir()
        (stage / "lyrics").mkdir()
        prepared = []
        seen = set()
        for row in supported:
            if cancelled and cancelled.is_set():
                raise ValueError("ยกเลิกก่อนเผยแพร่")
            media = next((p for p, _ in row["files"] if p.suffix.lower() in AUDIO), None)
            lyric = next((p for p, _ in row["files"] if p.suffix.lower() == ".lrc"), None)
            if media is None or lyric is None:
                continue
            # Content fingerprint allows distinct same-name songs, while the
            # remote publisher will verify MD5 and code collisions again.
            source_id = digest(media)
            if source_id in seen:
                continue
            seen.add(source_id)
            code = row["name"].strip()
            if not code or len(code) > 140:
                continue
            name = export.safe_filename(code)
            suffix = media.suffix.lower()
            file = stage / "audio" / (source_id[:16] + suffix)
            lyrics_file = stage / "lyrics" / (source_id[:16] + ".json")
            lrc_file = lyrics_file.with_suffix(".lrc")
            document = export.lrc_to_json(lyric.read_text(encoding="utf-8-sig"), code)
            if not document.get("lines"):
                continue
            # Use ordinary copies for cross-volume safety. Avoid mutating user
            # originals; ephemeral staging is deleted even after cancellation.
            shutil.copy2(media, file)
            raw_lrc = lyric.read_bytes()
            lrc_file.write_bytes(raw_lrc)
            lyrics_file.write_text(json.dumps(document, ensure_ascii=False),
                                   encoding="utf-8")
            prepared.append({
                "webSongId": "import/" + source_id,
                "code": code, "title": row["name"], "artist": "",
                "sourceFormat": row["kind"],
                "audio": {"path": "audio/" + file.name},
                "lyrics": {"path": "lyrics/" + lyrics_file.name}})
        if not prepared:
            raise ValueError("ไม่มีเนื้อร้องที่แปลงเป็น JSON พร้อมเวลาได้")
        (stage / "current.json").write_text('{"staging":true}', encoding="utf-8")
        result_db = publisher.publish(
            stage, prepared, create_new_library=create_new_library,
            cancelled=cancelled,
            on_row=(lambda done, total, skipped:
                    progress(done + skipped, total + skipped, "กำลังสร้าง DB ออนไลน์"))
                   if progress else None)
    return {
        **result_db, "ready": len(prepared), "deferred": len(deferred),
        "incomplete": len(result["incomplete"]), "unsupported": len(result["unsupported"]),
        "message": (
            f"ซิงค์ DB พร้อมเล่น · เพิ่ม {result_db['newSongs']} เพลง · "
            f"ปรับเนื้อร้อง {result_db['updatedSongs']} · "
            f"ข้ามซ้ำ {result_db['duplicates']} · รหัสชนกัน {result_db['conflicts']} · "
            f"ข้ามรายการไม่สมบูรณ์ {len(result['incomplete'])} · "
            f"ยังไม่เผยแพร่ VIDEO/NCN {len(deferred)} รายการ (ยังไม่มี Online Catalog ที่รองรับ)")
    }
