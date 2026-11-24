"""Safe, review-first publishing to the user's existing Google Drive for desktop.

Never opens or overwrites DB/songs.sqlite3: the Online catalog publisher owns it.
Google Drive for desktop uploads successfully published files asynchronously.
No OAuth token, destructive duplicate removal, or source-file deletion.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import re
import secrets
import sys
from collections import defaultdict
from pathlib import Path

ROOT_NAME = "XStageKaraoke"
AREAS = ("SONGS", "SOUNDFONT", "FX")
REQUIRED = ("SONGS", "DB", "SOUNDFONT")
CHUNK = 1024 * 1024
MAX_FILES = 300000

FORMATS = {
    "SONGS": {".xmid", ".xsk", ".mid", ".kar", ".lyr", ".cur",
              ".lrc", ".json", ".mp3", ".m4a", ".wav", ".flac",
              ".aac", ".ogg", ".oga", ".wma", ".mp4", ".mkv",
              ".webm", ".avi", ".mov", ".mpg", ".mpeg", ".vob"},
    "SOUNDFONT": {".sf2", ".sf3"},
    "FX": {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".oga",
           ".flac", ".opus"},
}


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError("ยกเลิกโดยเก็บไฟล์ที่ส่งสำเร็จไว้ ไม่ลบงานเดิม")


def _inside(child, parent):
    return child == parent or parent in child.parents


def _safe_path(base, path):
    base = Path(base).resolve(strict=True)
    path = Path(path)
    if not _inside(path.absolute(), base):
        raise ValueError("เส้นทางอยู่นอก XStageKaraoke")
    cursor = path
    while cursor != base:
        if cursor.is_symlink():
            raise ValueError("ไม่อนุญาต symbolic link ในปลายทาง Google Drive")
        cursor = cursor.parent
    return path


def resolve_root(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("ต้องเลือกโฟลเดอร์ XStageKaraoke ที่ซิงก์กับ Google Drive บนเครื่อง")
    root = Path(value.strip().strip('"')).expanduser()
    if root.name in AREAS:
        root = root.parent
    if root.name != ROOT_NAME or root.is_symlink() or not root.is_dir():
        raise ValueError("ปลายทางต้องเป็นโฟลเดอร์หลัก XStageKaraoke ที่มีอยู่แล้ว")
    root = root.resolve(strict=True)
    if root.name != ROOT_NAME or not all((root / x).is_dir() for x in REQUIRED):
        raise ValueError("ต้องพบ SONGS, DB และ SOUNDFONT ใต้ XStageKaraoke")
    if any((root / x).is_symlink() for x in REQUIRED):
        raise ValueError("โฟลเดอร์หลักต้องไม่เป็น symbolic link")
    return root


def _source_folder(source, area):
    if source.name == area:
        return source, True
    inside = source / area
    if inside.is_dir() and not inside.is_symlink():
        return inside, True
    return source, False


def _bucket(stem):
    match = re.search(r"[A-Za-z0-9]", stem)
    return match.group(0).upper() if match else "_"


def _flat_relative(file, area):
    suffix = file.suffix.lower()
    if area == "SOUNDFONT":
        return Path(suffix[1:].upper()) / file.name
    if area == "FX":
        return Path(file.name)
    bucket = _bucket(file.stem)
    if suffix in (".xmid", ".xsk", ".kar"):
        return Path("MIDI") / suffix[1:].upper() / bucket / file.name
    if suffix == ".mid":
        return Path("MIDI/MID/SONG") / bucket / file.name
    if suffix in (".lyr", ".cur"):
        return Path("MIDI/NCN") / suffix[1:].upper() / bucket / file.name
    if suffix in (".lrc", ".json"):
        # Cannot know which song/format this sidecar belongs to from its name.
        return None
    if suffix in (".mp3", ".m4a", ".wav", ".flac", ".aac", ".ogg", ".oga", ".wma"):
        return Path("AUDIO") / suffix[1:].upper() / "SONG" / bucket / file.name
    return Path("VIDEO") / suffix[1:].upper() / "SONG" / bucket / file.name


def _walk(folder, area, structured, cancel=None):
    count = 0
    for base, dirs, names in os.walk(folder, followlinks=False):
        _check_cancel(cancel)
        dirs[:] = sorted(d for d in dirs if not (Path(base) / d).is_symlink()
                         and not d.startswith("."))
        for name in sorted(names):
            _check_cancel(cancel)
            file = Path(base) / name
            if file.is_symlink() or not file.is_file() or name.startswith("."):
                continue
            if file.suffix.lower() not in FORMATS[area]:
                continue
            relative = file.relative_to(folder) if structured else _flat_relative(file, area)
            if relative is None or not relative.parts or any(p in (".", "..") for p in relative.parts):
                continue
            count += 1
            if count > MAX_FILES:
                raise ValueError("จำนวนไฟล์เกิน 300,000 รายการต่อหนึ่งหมวด")
            yield file, relative


def _digest(file, cancel=None):
    h = hashlib.sha256()
    with Path(file).open("rb") as handle:
        while True:
            _check_cancel(cancel)
            chunk = handle.read(CHUNK)
            if not chunk:
                return h.digest()
            h.update(chunk)


def _inventory(target, cancel=None):
    by_size = defaultdict(list)
    for base, dirs, names in os.walk(target, followlinks=False):
        _check_cancel(cancel)
        dirs[:] = [d for d in dirs if not (Path(base) / d).is_symlink()]
        for name in names:
            path = Path(base) / name
            if path.is_file() and not path.is_symlink() and path.suffix.lower() in FORMATS[target.name]:
                by_size[path.stat().st_size].append(path)
    return by_size


def inspect(source, drive_root, area, cancel=None, progress=None):
    """Read-only preflight. No mkdir, upload, delete or SQLite writes."""
    if area not in AREAS:
        raise ValueError("เลือกหมวด SONGS, SOUNDFONT หรือ FX")
    root = resolve_root(str(drive_root))
    source = Path(source).expanduser()
    if not source.is_dir() or source.is_symlink():
        raise ValueError("ไม่พบโฟลเดอร์ต้นทางที่ใช้งานได้")
    source = source.resolve(strict=True)
    if _inside(source, root) or _inside(root, source):
        raise ValueError("ต้นทางต้องอยู่นอกคลัง Google Drive ป้องกันการส่งซ้ำเข้าหาตัวเอง")
    content, structured = _source_folder(source, area)
    dest = root / area
    if dest.is_symlink() or (dest.exists() and not dest.is_dir()):
        raise ValueError("ปลายทางไม่ใช่โฟลเดอร์ที่ปลอดภัย")
    known = _inventory(dest, cancel) if dest.is_dir() else defaultdict(list)
    hashes = {}
    selected = {}
    entries = []
    stats = dict(area=area, scanned=0, new=0, identical=0,
                 duplicate=0, conflict=0, bytes=0, skipped_sidecars=0)
    for src, relative in _walk(content, area, structured, cancel):
        _check_cancel(cancel)
        stats["scanned"] += 1
        dst = dest / relative
        _safe_path(root, dst)
        key = str(relative).casefold()
        if key in selected:
            status = "conflict"
        else:
            selected[key] = src
            size = src.stat().st_size
            source_hash = _digest(src, cancel)
            if dst.exists():
                status = "identical" if dst.is_file() and dst.stat().st_size == size and _digest(dst, cancel) == source_hash else "conflict"
            else:
                status = "new"
                for candidate in known[size]:
                    candidate_hash = hashes.get(candidate)
                    if candidate_hash is None:
                        candidate_hash = _digest(candidate, cancel)
                        hashes[candidate] = candidate_hash
                    if candidate_hash == source_hash:
                        status = "duplicate"
                        break
            if status == "new":
                # A second source file with identical bytes is also a duplicate.
                for other in entries:
                    if other["status"] == "new" and other["bytes"] == size and other["sha256"] == source_hash.hex():
                        status = "duplicate"
                        break
        if key in selected and selected[key] == src:
            size = src.stat().st_size
            source_hash = _digest(src, cancel) if "source_hash" not in locals() else source_hash
        entry = dict(source=str(src), relative=str(relative), status=status,
                     bytes=size, sha256=source_hash.hex())
        entries.append(entry)
        stats[status] += 1
        if status == "new":
            stats["bytes"] += size
        if progress and stats["scanned"] % 20 == 0:
            progress(dict(stats), "ตรวจไฟล์ " + str(stats["scanned"]) + " รายการ")
        # Reset per-entry values (never carry an earlier file hash to a collision).
        del source_hash, size
    return dict(root=str(root), source=str(source), area=area,
                stats=stats, items=entries)


def _publish_exclusive(temp, destination):
    """Never replace an existing Drive file. Atomic no-clobber publication."""
    if sys.platform == "win32":
        method = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
        method.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        method.restype = ctypes.c_int
        if not method(str(temp), str(destination), 0):
            code = ctypes.get_last_error()
            raise FileExistsError("Google Drive ปฏิเสธการเขียนไฟล์ (ไม่เขียนทับ): " + str(code))
    else:
        os.link(temp, destination)
        temp.unlink()


def publish(source, drive_root, area, progress=None, cancel=None, plan=None):
    """Publish already verified, new files only. A cancellation preserves success."""
    snapshot = inspect(source, drive_root, area, cancel, progress)
    if plan is not None:
        expected = [(x["relative"], x["bytes"], x["sha256"], x["status"])
                    for x in plan["items"]]
        actual = [(x["relative"], x["bytes"], x["sha256"], x["status"])
                  for x in snapshot["items"]]
        if plan.get("root") != snapshot["root"] or plan.get("area") != area or expected != actual:
            raise ValueError("แหล่งเพลง/Drive เปลี่ยนหลังตรวจ กรุณาตรวจรายการใหม่ก่อนส่ง")
    root = Path(snapshot["root"])
    outcome = dict(snapshot["stats"], phase="publish", published=0,
                   published_bytes=0, cancelled=False)
    for entry in snapshot["items"]:
        if entry["status"] != "new":
            continue
        try:
            _check_cancel(cancel)
            src = Path(entry["source"])
            dest = root / area / entry["relative"]
            _safe_path(root, dest)
            if dest.exists():
                raise FileExistsError("ปลายทางมีไฟล์ใหม่แล้ว: " + str(dest))
            dest.parent.mkdir(parents=True, exist_ok=True)
            _safe_path(root, dest)
            tmp = dest.with_name(".xstage-staging-" + secrets.token_hex(12) + ".part")
            try:
                h = hashlib.sha256()
                with src.open("rb") as incoming, tmp.open("xb") as outgoing:
                    while True:
                        _check_cancel(cancel)
                        block = incoming.read(CHUNK)
                        if not block:
                            break
                        outgoing.write(block)
                        h.update(block)
                    outgoing.flush()
                    os.fsync(outgoing.fileno())
                if tmp.stat().st_size != entry["bytes"] or h.hexdigest() != entry["sha256"]:
                    raise ValueError("ต้นทางเปลี่ยน/ตรวจ SHA-256 ไม่ผ่าน: " + str(src))
                _check_cancel(cancel)
                _publish_exclusive(tmp, dest)
                outcome["published"] += 1
                outcome["published_bytes"] += entry["bytes"]
                if progress:
                    progress(dict(outcome), "ส่งเข้า Drive บนเครื่อง: " + dest.name)
            finally:
                tmp.unlink(missing_ok=True)
        except InterruptedError:
            outcome["cancelled"] = True
            break
    outcome["phase"] = "cancelled" if outcome["cancelled"] else "completed"
    outcome["next_step"] = ("รอ Google Drive for desktop ซิงก์ไฟล์ขึ้นคลาวด์จนเสร็จ "
                            "แล้วเปิด Karaoke Online > จัดการคลัง > ตรวจไฟล์และอัปเดตฐาน DB/songs.sqlite3")
    return outcome
