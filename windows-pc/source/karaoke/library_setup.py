"""Safe PC/Online library preparation; never removes original song files."""
from pathlib import Path
import os
import shutil
import tempfile
from .shared_drive_layout import setup

DRIVE_DOWNLOAD = "https://www.google.com/drive/download/"
PACKAGES = {".xmid", ".xsk"}

def drive_roots():
    # Drive Desktop stream volumes normally expose a My Drive directory.
    roots = []
    for volume in getattr(os, "listdrives", lambda: [])():
        for name in ("My Drive", "ไดรฟ์ของฉัน"):
            candidate = Path(volume) / name
            if candidate.is_dir():
                roots.append(candidate)
    return roots

def _inside(child, parent):
    return child == parent or parent in child.parents

def _stop(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError("ยกเลิกแล้ว · เก็บไฟล์ที่คัดลอกสำเร็จและต้นฉบับไว้")

def _equal(left, right, cancel):
    if left.stat().st_size != right.stat().st_size:
        return False
    with left.open("rb") as a, right.open("rb") as b:
        while True:
            _stop(cancel)
            chunk = a.read(1024 * 1024)
            if chunk != b.read(1024 * 1024):
                return False
            if not chunk:
                return True

def prepare_online(source, drive, name="XStageKaraoke", *, cancel=None, progress=None):
    """Copy supported Online packages, preserve relative paths and fail on collisions.

    The selected Drive mount must be one of the detected My Drive folders.
    No content-wide duplicate scan; comparison is only for an occupied destination.
    """
    drive = Path(drive).resolve(strict=True)
    if drive not in [p.resolve() for p in drive_roots()]:
        raise ValueError("ไม่พบ Google Drive for desktop ที่เลือก · ตรวจการเข้าสู่ระบบ")
    if not name or Path(name).name != name or name in (".", "..") or any(c in name for c in '\\/:'):
        raise ValueError("ชื่อโฟลเดอร์หลักไม่ถูกต้อง")
    source = Path(source).resolve(strict=True)
    if not source.is_dir():
        raise ValueError("เลือกโฟลเดอร์คลังเพลงก่อน")
    root = drive / name
    if root.is_symlink():
        raise ValueError("คลังปลายทางเป็น symbolic link")
    songs = root / "SONGS"
    if source == root and songs.is_dir():
        source = songs.resolve()
    if _inside(source, songs.resolve()):
        setup(root)
        return root
    if _inside(root.resolve(), source) or _inside(source, root.resolve()):
        raise ValueError("ต้นทางซ้อนกับคลังปลายทาง กรุณาเลือก SONGS โดยตรง")
    if (source / "SONGS").is_dir() and not (source / "SONGS").is_symlink():
        source = source / "SONGS"
    files = []
    for directory, folders, names in os.walk(source, followlinks=False):
        _stop(cancel)
        folders[:] = [d for d in folders if not (Path(directory) / d).is_symlink()]
        for filename in names:
            file = Path(directory) / filename
            if file.suffix.lower() in PACKAGES and not file.is_symlink():
                relative = file.relative_to(source)
                if len(relative.parts) < 2 or relative.parts[0].casefold() != "midi":
                    relative = Path("MIDI") / relative
                files.append((file, relative))
    if not files:
        raise ValueError("ไม่พบ XMID/XSK สำหรับ Online · ใช้โหมด PC สำหรับรูปแบบอื่น")
    setup(root)
    for index, (file, relative) in enumerate(files, 1):
        _stop(cancel)
        dest = songs / relative
        for parent in (dest, *dest.parents):
            if parent == root:
                break
            if parent.is_symlink():
                raise ValueError("พบ symbolic link ในปลายทาง: " + str(parent))
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            if not dest.is_file() or not _equal(file, dest, cancel):
                raise ValueError("ปลายทางชื่อเดียวกันแต่เนื้อหาแตกต่าง · ไม่เขียนทับ: " + str(dest))
        else:
            fd, temp = tempfile.mkstemp(prefix=".xstage-copy-", dir=dest.parent)
            os.close(fd)
            temp = Path(temp)
            try:
                with file.open("rb") as src, temp.open("wb") as out:
                    while True:
                        _stop(cancel)
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                shutil.copystat(file, temp)
                if not _equal(file, temp, cancel):
                    raise ValueError("ไฟล์ที่คัดลอกไม่ตรงกับต้นฉบับ")
                _stop(cancel)
                # Windows rename refuses to replace an existing destination.
                if os.name == "nt":
                    temp.rename(dest)
                else:
                    os.link(temp, dest)
            finally:
                temp.unlink(missing_ok=True)
        if progress:
            progress({"scanned": index, "total": len(files), "accepted": index}, "เตรียมคลัง Google Drive")
    return root
