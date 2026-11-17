"""Exact duplicate *media-file* scanner for Song Studio PC.

Only raw media bytes are compared (same size, sampled digest and full SHA-256);
lyrics, catalogs, SoundFonts and sidecars are NEVER candidate media. Scanning is
read-only. Every move/delete is a separately confirmed operation on verified,
unmodified duplicates while one original is retained. No auto-cleanup.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import secrets
import shutil
import threading
from collections import defaultdict
from pathlib import Path

MEDIA_EXTENSIONS = frozenset({
    ".mid", ".midi", ".kar", ".xsk", ".emk",
    ".mp3", ".mp2", ".m4a", ".m4b", ".aac", ".wav", ".wma", ".flac",
    ".ogg", ".oga", ".opus", ".aif", ".aiff", ".aifc", ".alac",
    ".ape", ".wv", ".mpc", ".caf", ".ac3", ".dts",
    ".mp4", ".m4v", ".webm", ".avi", ".mkv", ".mov", ".mpg",
    ".mpeg", ".dat", ".vob", ".wmv", ".flv", ".3gp", ".ts", ".m2ts",
})
MAX_SONGS = 1_000_000
MAX_ACTION_FILES = 300
READ_SIZE = 1024 * 1024
SAMPLE_SIZE = 65536
# These are companions only; they are not used to decide if media are duplicates.
LYRIC_EXTENSIONS = frozenset({".json", ".lrc", ".lyr", ".cur"})
LYRIC_ROLE_FOLDERS = {"lyrics", "lyr", "cur", "cursor", "lrc"}
MEDIA_ROLE_FOLDERS = {"song", "songs", "audio", "midi"}
MAX_PREVIEW_FILES = 1500


def _protected_library(path):
    return "xstagesong" in {part.casefold() for part in path.parts}


def _companions(root, media):
    """Find same-code sidecars, including mirrored NCN SONG/LYR/CUR folders.

    Only already-existing files underneath the selected tree qualify; do not
    inspect catalog/DB files or invent companion filenames. Exact stem matters.
    """
    roots = [media.parent]
    relative = media.relative_to(root)
    parts = relative.parts[:-1]
    for i, part in enumerate(parts):
        if part.casefold() in MEDIA_ROLE_FOLDERS:
            for role in ("LYR", "CUR", "LYRICS", "LRC", "lyrics", "lyr", "cur"):
                folder = root.joinpath(*parts[:i], role, *parts[i + 1:])
                if folder.is_dir() and not folder.is_symlink():
                    roots.append(folder)
    found = set()
    result = []
    for folder in roots:
        try:
            entries = folder.iterdir()
            for candidate in entries:
                if (candidate.stem.casefold() != media.stem.casefold() or
                        candidate.suffix.casefold() not in LYRIC_EXTENSIONS):
                    continue
                if (candidate.is_symlink() or not candidate.is_file() or
                        not candidate.resolve().is_relative_to(root)):
                    continue
                if candidate in found:
                    continue
                found.add(candidate)
                result.append(candidate)
        except OSError as exc:
            raise OSError("อ่านไฟล์ประกอบไม่สำเร็จ: " + str(folder)) from exc
    return sorted(result, key=lambda path: str(path).casefold())


def _shared_sidecar(media):
    """Skip companions with another media file of the same code in this folder."""
    try:
        for item in media.parent.iterdir():
            if (item == media or item.is_symlink() or
                    item.suffix.casefold() not in MEDIA_EXTENSIONS or
                    item.stem.casefold() != media.stem.casefold()):
                continue
            if item.is_file():
                return True
    except OSError as exc:
        raise OSError("ตรวจไฟล์เพลงที่ใช้เนื้อร้องร่วมกันไม่ได้") from exc
    return False


def _preferred_keeper(alive, preference):
    # No fabricated cross-code "same song" matches: choose only among
    # SHA-256 verified exact byte duplicates, including differently named files.
    if preference:
        preferred = [item for item in alive
                     if item["path"].suffix.casefold() == preference]
        if preferred:
            return preferred[0]
    # Preserve existing XStageSong library files if present; never mutate them.
    protected = [item for item in alive if _protected_library(item["path"])]
    return protected[0] if protected else alive[0]



def _stability(path: Path, stat=None):
    if path.is_symlink() or not path.is_file():
        raise ValueError("ไฟล์เปลี่ยนเป็นลิงก์หรือหายไป: " + str(path))
    value = stat or path.stat()
    return (value.st_size, value.st_mtime_ns, value.st_dev, value.st_ino)


def _digest(path: Path, *, sampled=False, cancelled=None):
    before = _stability(path)
    h = hashlib.sha256()
    h.update(str(before[0]).encode("ascii") + b":") if sampled else None
    with path.open("rb") as stream:
        if sampled:
            h.update(stream.read(SAMPLE_SIZE))
            if before[0] > SAMPLE_SIZE:
                stream.seek(max(0, before[0] - SAMPLE_SIZE))
                h.update(stream.read(SAMPLE_SIZE))
        else:
            while True:
                if cancelled is not None and cancelled.is_set():
                    raise RuntimeError("ผู้ใช้ยกเลิกการตรวจเพลงซ้ำ")
                block = stream.read(READ_SIZE)
                if not block:
                    break
                h.update(block)
    if _stability(path) != before:
        raise ValueError("ไฟล์เปลี่ยนแปลงระหว่างตรวจ: " + str(path))
    return h.hexdigest()


def _safe_root(folder):
    if not isinstance(folder, str) or not folder.strip():
        raise ValueError("กรุณาเลือกโฟลเดอร์ไฟล์เพลง")
    root = Path(folder).expanduser()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("โฟลเดอร์ต้นทางไม่ถูกต้องหรือเป็น Symbolic Link")
    root = root.resolve()
    if len(root.parts) < 2:
        raise ValueError("ไม่อนุญาตสแกนทั้งไดรฟ์ระบบโดยตรง")
    return root


def _recycle_windows(path):
    """Move to the user's Windows Recycle Bin, never permanently unlink."""
    if os.name != "nt":
        raise RuntimeError("ลบลงถังรีไซเคิลรองรับเฉพาะ Windows PC")
    from ctypes import wintypes
    # Windows can permanently remove files on network/removable devices even
    # when FOF_ALLOWUNDO is requested. Refuse those volumes; use Move instead.
    volume_root = Path(path).anchor
    if not volume_root or ctypes.windll.kernel32.GetDriveTypeW(volume_root) != 3:
        raise ValueError("ถังรีไซเคิลไม่รับรองสำหรับไดรฟ์นี้ · กรุณาใช้คำสั่งย้ายแทน")

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", wintypes.WORD),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    # FO_DELETE (3), FOF_ALLOWUNDO (0x40), FOF_WANTNUKEWARNING (0x4000):
    # Windows must warn if a file cannot be recycled. Never silently authorize
    # permanent removal. A double-NUL terminated source is required.
    request = SHFILEOPSTRUCTW()
    request.wFunc = 3
    source = str(path) + "\0\0"
    request.pFrom = source
    request.fFlags = 0x40 | 0x4000
    error = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(request))
    if error or request.fAnyOperationsAborted or path.exists():
        raise OSError("Windows ไม่ยืนยันการย้ายเข้าถังรีไซเคิล: " + str(path))


def _move_verified(source, destination, root, expected_digest, cancelled):
    """No-overwrite copy to new folder; verify before removing the old copy."""
    rel = source.relative_to(root)
    if shutil.disk_usage(destination).free < source.stat().st_size + 16 * 1024 * 1024:
        raise ValueError("พื้นที่ปลายทางไม่เพียงพอสำหรับย้ายไฟล์ซ้ำ")
    target = destination / rel
    parent = destination
    for name in rel.parts[:-1]:
        parent = parent / name
        if parent.is_symlink():
            raise ValueError("ปลายทางมี Symbolic Link ในโฟลเดอร์ย่อย")
        parent.mkdir(exist_ok=True)
    if not parent.is_dir():
        raise ValueError("โฟลเดอร์ปลายทางไม่พร้อม")
    attempt = 0
    while target.exists() or target.is_symlink():
        attempt += 1
        if attempt > 10000:
            raise FileExistsError("ไฟล์ปลายทางชนกันจำนวนมาก")
        target = parent / (source.stem + " (duplicate " + str(attempt) + ")" + source.suffix)
    stage = parent / ("." + secrets.token_hex(12) + ".partial")
    try:
        with source.open("rb") as inp, stage.open("xb") as out:
            while True:
                if cancelled is not None and cancelled.is_set():
                    raise RuntimeError("ยกเลิกการย้ายไฟล์ซ้ำ")
                block = inp.read(READ_SIZE)
                if not block:
                    break
                out.write(block)
            out.flush()
            os.fsync(out.fileno())
        if _digest(stage, cancelled=cancelled) != expected_digest:
            raise ValueError("ตรวจ SHA-256 ของไฟล์ที่คัดลอกไม่ผ่าน")
        # Hardlink allows a no-overwrite commit on local NTFS and POSIX.
        # FAT/exFAT fallback uses exclusive creation; never overwrite.
        try:
            os.link(stage, target)
        except (OSError, NotImplementedError):
            with stage.open("rb") as inp, target.open("xb") as out:
                try:
                    shutil.copyfileobj(inp, out, READ_SIZE)
                    out.flush()
                    os.fsync(out.fileno())
                except BaseException:
                    target.unlink(missing_ok=True)
                    raise
        if _digest(target, cancelled=cancelled) != expected_digest:
            target.unlink(missing_ok=True)
            raise ValueError("ตรวจไฟล์ปลายทางหลังบันทึกไม่ผ่าน")
        # The source is re-verified immediately before removal. If a user
        # modifies it during the copy we keep both rather than lose their edit.
        if _digest(source, cancelled=cancelled) != expected_digest:
            raise ValueError("ต้นฉบับมีการแก้ไขระหว่างย้าย · คงทั้งสองไฟล์ไว้")
        source.unlink()
        return str(target)
    finally:
        stage.unlink(missing_ok=True)


def _move_bundle(paths, destination, root, cancelled):
    """Stage and verify the whole media+sidecar bundle before removing sources.

    Preserves the source-relative SONG/LYR/CUR structure and every basename.
    A destination collision blocks the bundle instead of silently renaming a
    companion and breaking its link with the song.
    """
    staged, published, outputs = [], [], []
    try:
        total = sum(path.stat().st_size for path in paths)
        if shutil.disk_usage(destination).free < total + 16 * 1024 * 1024:
            raise ValueError("พื้นที่ปลายทางไม่เพียงพอสำหรับย้ายเพลงและไฟล์ประกอบ")
        for path in paths:
            if cancelled is not None and cancelled.is_set():
                raise RuntimeError("ยกเลิกงานย้ายไฟล์เพลงซ้ำ")
            relative = path.relative_to(root)
            parent = destination
            for segment in relative.parts[:-1]:
                parent = parent / segment
                if parent.is_symlink():
                    raise ValueError("โฟลเดอร์ปลายทางมี Symbolic Link")
                parent.mkdir(exist_ok=True)
            target = destination / relative
            if target.exists() or target.is_symlink():
                raise FileExistsError("พบไฟล์ปลายทางอยู่แล้ว · ไม่เขียนทับไฟล์เพลง/เนื้อร้อง: " + str(target))
            outputs.append((path, target))
        for path, target in outputs:
            expected = _digest(path, cancelled=cancelled)
            stage = target.parent / ("." + secrets.token_hex(12) + ".partial")
            with path.open("rb") as incoming, stage.open("xb") as outgoing:
                while True:
                    if cancelled is not None and cancelled.is_set():
                        raise RuntimeError("ยกเลิกงานย้ายไฟล์เพลงซ้ำ")
                    chunk = incoming.read(READ_SIZE)
                    if not chunk:
                        break
                    outgoing.write(chunk)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            staged.append(stage)
            if _digest(stage, cancelled=cancelled) != expected:
                raise ValueError("SHA-256 ไม่ตรงหลังคัดลอกไฟล์: " + path.name)
            # Race protection: never remove a source that changed mid-copy.
            if _digest(path, cancelled=cancelled) != expected:
                raise ValueError("ไฟล์เพลงหรือเนื้อร้องเปลี่ยนระหว่างย้าย")
        for (source, target), stage in zip(outputs, staged):
            # Hard link provides atomic no-overwrite creation on NTFS.
            try:
                os.link(stage, target)
            except OSError:
                with stage.open("rb") as incoming, target.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing, READ_SIZE)
                    outgoing.flush()
                    os.fsync(outgoing.fileno())
            published.append(target)
            if _digest(target, cancelled=cancelled) != _digest(source, cancelled=cancelled):
                raise ValueError("ตรวจไฟล์ที่ย้ายไม่ผ่าน · คงต้นฉบับไว้")
        # All outputs now exist and were verified. If any remove fails, leave
        # the already copied target files available for manual recovery.
        for source, target in outputs:
            source.unlink()
        return [str(target) for _, target in outputs]
    except BaseException:
        # Do not erase published files after the source removal phase begins:
        # that would lose material when a later source unlink raises.
        if all(source.exists() for source, _ in outputs):
            for target in published:
                target.unlink(missing_ok=True)
        raise
    finally:
        for stage in staged:
            stage.unlink(missing_ok=True)


class DuplicateMediaRegistry:
    def __init__(self):
        self.lock = threading.RLock()
        self.state = None
        self.preview_state = None

    def scan(self, folder, *, cancelled=None, progress=None):
        root = _safe_root(folder)
        by_size = defaultdict(list)
        files = 0
        ignored = 0
        errors = 0
        folders = [root]
        while folders:
            if cancelled is not None and cancelled.is_set():
                raise RuntimeError("ผู้ใช้ยกเลิกการตรวจเพลงซ้ำ")
            directory = folders.pop()
            children = []
            try:
                with os.scandir(directory) as listing:
                    for entry in listing:
                        if cancelled is not None and cancelled.is_set():
                            raise RuntimeError("ผู้ใช้ยกเลิกการตรวจเพลงซ้ำ")
                        try:
                            if entry.is_symlink():
                                ignored += 1
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                children.append(Path(entry.path))
                                continue
                            if not entry.is_file(follow_symlinks=False):
                                continue
                            path = Path(entry.path)
                            if path.suffix.casefold() not in MEDIA_EXTENSIONS:
                                ignored += 1
                                continue
                            # DirEntry.stat and pathlib.Path.stat can expose
                            # different Windows file IDs (st_ino) on some
                            # runners. Use one normalized stat API for the
                            # snapshot and all later stale-file checks.
                            meta = path.stat()
                            if meta.st_size == 0:
                                ignored += 1
                                continue
                            by_size[meta.st_size].append((path, _stability(path, meta)))
                            files += 1
                            if files > MAX_SONGS:
                                raise ValueError("จำนวนไฟล์เพลงเกินขีดจำกัด 1,000,000")
                            if progress and files % 512 == 0:
                                progress("scan", files, 0, 0)
                        except (PermissionError, FileNotFoundError) as exc:
                            errors += 1
            except OSError as exc:
                raise OSError("อ่านโฟลเดอร์ย่อยไม่ได้: " + str(directory)) from exc
            folders.extend(reversed(sorted(children, key=lambda p: p.name.casefold())))
        if progress:
            progress("scan", files, 0, 0)
        # Only files of equal size can be exact byte duplicates. Sample their
        # heads/tails before the expensive whole-file SHA-256 comparison.
        groups = []
        entries = {}
        hashed = 0
        for size, records in by_size.items():
            if len(records) < 2:
                continue
            sampled = defaultdict(list)
            for path, stamp in records:
                if cancelled is not None and cancelled.is_set():
                    raise RuntimeError("ผู้ใช้ยกเลิกการตรวจเพลงซ้ำ")
                try:
                    if _stability(path) == stamp:
                        sampled[_digest(path, sampled=True, cancelled=cancelled)].append((path, stamp))
                    else:
                        errors += 1
                except (OSError, ValueError):
                    errors += 1
            for candidates in sampled.values():
                if len(candidates) < 2:
                    continue
                verified = defaultdict(list)
                for path, stamp in candidates:
                    try:
                        if _stability(path) == stamp:
                            verified[_digest(path, cancelled=cancelled)].append((path, stamp))
                            hashed += 1
                            if progress and hashed % 16 == 0:
                                progress("hash", files, hashed, len(groups))
                        else:
                            errors += 1
                    except (OSError, ValueError):
                        errors += 1
                for digest, copies in verified.items():
                    if len(copies) < 2:
                        continue
                    copies.sort(key=lambda item: str(item[0]).casefold())
                    group_id = "g" + str(len(groups) + 1)
                    file_ids = []
                    for path, stamp in copies:
                        file_id = "f" + str(len(entries) + 1)
                        entries[file_id] = {"id": file_id, "group": group_id,
                                            "path": path, "stamp": stamp,
                                            "sha256": digest, "size": size,
                                            "status": "active"}
                        file_ids.append(file_id)
                    groups.append({"id": group_id, "sha256": digest,
                                   "size": size, "files": file_ids})
        groups.sort(key=lambda g: (-g["size"] * (len(g["files"]) - 1), g["sha256"]))
        result = {
            "scanId": secrets.token_hex(16), "root": root, "groups": groups,
            "groupById": {g["id"]: g for g in groups},
            "files": entries, "scanned": files, "ignored": ignored,
            "errors": errors, "hashed": hashed,
        }
        with self.lock:
            self.state = result
            self.preview_state = None
        if progress:
            progress("done", files, hashed, len(groups))
        return {"scanId": result["scanId"], "fileCount": files,
                "groupCount": len(groups),
                "duplicateFiles": sum(len(g["files"]) - 1 for g in groups),
                "potentialBytes": sum(g["size"] * (len(g["files"]) - 1) for g in groups),
                "ignored": ignored, "errors": errors,
                "message": (f"ตรวจเพลงซ้ำ {files:,} ไฟล์ · พบกลุ่มซ้ำ {len(groups):,}"
                            f" · ไฟล์สำเนา {sum(len(g['files']) - 1 for g in groups):,}")}

    def page(self, *, offset=0, limit=20, preferred_extension=""):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("ขอบเขตหน้ารายการไม่ถูกต้อง")
        with self.lock:
            state = self.state
            if state is None:
                return {"ready": False, "groups": [], "groupCount": 0}
            live_groups = []
            for group in state["groups"]:
                alive = [state["files"][fid] for fid in group["files"]
                         if state["files"][fid]["status"] == "active"]
                if len(alive) > 1:
                    live_groups.append((group, alive))
            rows = []
            preference = str(preferred_extension or "").casefold()
            if preference and preference not in MEDIA_EXTENSIONS:
                raise ValueError("ชนิดไฟล์ที่ต้องการเก็บไม่รองรับ")
            for group, alive in live_groups[offset:offset + limit]:
                keeper = _preferred_keeper(alive, preference)
                # A single dummy/placeholder MIDI may be repeated thousands
                # of times. Send a bounded response; after a cleanup, refreshing
                # the page reveals the next copies without re-scanning the disk.
                shown = alive[:301]
                if keeper not in shown:
                    shown[-1] = keeper
                rows.append({"id": group["id"], "size": group["size"],
                             "sha256": group["sha256"],
                             "fileCount": len(alive),
                             "hiddenFiles": len(alive) - len(shown),
                             "files": [
                                 {"id": item["id"], "path": str(item["path"]),
                                  "keep": item["id"] == keeper["id"],
                                  "extension": item["path"].suffix.lower(),
                                  "protected": _protected_library(item["path"])}
                                 for i, item in enumerate(shown)]})
            return {
                "ready": True, "scanId": state["scanId"],
                "folder": str(state["root"]),
                "fileCount": state["scanned"], "ignored": state["ignored"],
                "errors": state["errors"], "hashed": state["hashed"],
                "groupCount": len(live_groups),
                "duplicateFiles": sum(len(alive) - 1 for _, alive in live_groups),
                "potentialBytes": sum(g["size"] * (len(alive) - 1)
                                      for g, alive in live_groups),
                "groups": rows, "offset": offset, "limit": limit,
            }

    def apply(self, *, scan_id, selected, operation, destination=None,
              confirmed=False, cancelled=None, progress=None):
        if operation not in ("move", "recycle") or confirmed is not True:
            raise ValueError("ต้องเลือกการย้ายหรือส่งเข้าถังรีไซเคิลและยืนยันคำสั่ง")
        if (not isinstance(selected, list) or not 1 <= len(selected) <= MAX_ACTION_FILES
                or any(not isinstance(s, str) for s in selected)
                or len(set(selected)) != len(selected)):
            raise ValueError("กรุณาเลือกไฟล์ซ้ำ 1–300 ไฟล์โดยไม่ซ้ำกัน")
        with self.lock:
            state = self.state
            if state is None or scan_id != state["scanId"]:
                raise ValueError("ผลตรวจเพลงซ้ำหมดอายุ · กรุณาตรวจใหม่")
            root = state["root"]
            chosen = []
            for fid in selected:
                item = state["files"].get(fid)
                if not item or item["status"] != "active":
                    raise ValueError("รายการไฟล์ซ้ำเปลี่ยนแล้ว · กรุณาโหลดผลตรวจใหม่")
                if "xstagesong" in {p.casefold() for p in item["path"].parts}:
                    raise ValueError("ไม่อนุญาตลบ/ย้ายเพลงใน XStageSong ที่ฐานข้อมูลอาจอ้างถึง")
                group = state["groupById"][item["group"]]
                alive = [state["files"][x] for x in group["files"]
                         if state["files"][x]["status"] == "active"]
                keeper = alive[0]
                if keeper["id"] == fid or keeper["id"] in selected:
                    raise ValueError("ต้องเก็บไฟล์หลักอย่างน้อยหนึ่งไฟล์ในแต่ละกลุ่ม")
                chosen.append((item, keeper))
            if operation == "move":
                target_root = _safe_root(destination)
                if (target_root == root or target_root.is_relative_to(root)
                        or root.is_relative_to(target_root)):
                    raise ValueError("โฟลเดอร์ย้ายต้องแยกจากโฟลเดอร์ต้นทาง")
            else:
                if os.name != "nt":
                    raise ValueError("ลบลงถังรีไซเคิลรองรับเฉพาะ Windows")
                target_root = None
            completed = []
            verified_keepers = set()
            for idx, (item, keeper) in enumerate(chosen, 1):
                if cancelled is not None and cancelled.is_set():
                    raise RuntimeError("ยกเลิกการจัดการเพลงซ้ำ")
                # A single 4GB keeper may have hundreds of identical copies.
                # Rehash it ONCE per confirmed action, not 300 times.
                proofs = [item]
                if keeper["id"] not in verified_keepers:
                    proofs.insert(0, keeper)
                for proof in proofs:
                    if (_stability(proof["path"]) != proof["stamp"]
                            or _digest(proof["path"], cancelled=cancelled) != proof["sha256"]):
                        raise ValueError("ไฟล์ต้นฉบับหรือสำเนาเปลี่ยนระหว่างตรวจ · ต้องสแกนใหม่")
                verified_keepers.add(keeper["id"])
                if operation == "move":
                    moved = _move_verified(item["path"], target_root, root,
                                           item["sha256"], cancelled)
                else:
                    _recycle_windows(item["path"])
                    moved = ""
                item["status"] = operation
                completed.append({"id": item["id"], "from": str(item["path"]),
                                  "to": moved})
                if progress:
                    progress(idx, len(chosen), item["path"].name)
            return {
                "processed": len(completed), "operation": operation,
                "files": completed[:50],
                "message": (f"{'ย้าย' if operation == 'move' else 'ส่งเข้าถังรีไซเคิล'}"
                            f"ไฟล์ซ้ำสำเร็จ {len(completed):,} ไฟล์ · เก็บไฟล์หลักไว้ทุกกลุ่ม"),
            }


REGISTRY = DuplicateMediaRegistry()
