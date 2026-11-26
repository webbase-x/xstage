"""Safe PC/Online library preparation; never removes original song files."""
from pathlib import Path
import os
import shutil
import tempfile
import subprocess
from .shared_drive_layout import setup, inspect, DEFAULT_NAME

DRIVE_DOWNLOAD = "https://www.google.com/drive/download/"
PACKAGES = {".xmid", ".xsk"}

def drive_roots():
    """Find mounted streams and conventional mirrored folders without creating anything."""
    volumes = getattr(os, "listdrives", lambda: [])()
    if os.name == "nt" and not volumes:
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        volumes = [chr(65+i) + ":\\" for i in range(26) if mask & (1 << i)]
    candidates = [Path(v) / name for v in volumes
                  for name in ("My Drive", "ไดรฟ์ของฉัน")]
    candidates.extend(Path.home() / name for name in ("Google Drive", "My Drive", "ไดรฟ์ของฉัน"))
    roots = []
    for candidate in candidates:
        try:
            if candidate.is_dir() and candidate not in roots:
                roots.append(candidate)
        except OSError:
            continue
    return roots

def launch_drive():
    """Launch installed Drive from standard installation directories, not arbitrary executables."""
    if os.name != "nt":
        raise ValueError("Google Drive for desktop ต้องใช้ Windows")
    for key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(key)
        if not base:
            continue
        root = Path(base) / "Google" / "Drive File Stream"
        candidates = [root / "GoogleDriveFS.exe", *sorted(root.glob("*/GoogleDriveFS.exe"), reverse=True)]
        for candidate in candidates:
            if candidate.is_file():
                subprocess.Popen([str(candidate)], shell=False)
                return
    for desktop in (Path.home() / "Desktop", Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop"):
        shortcut = desktop / "Google Drive.lnk"
        if shortcut.is_file():
            os.startfile(str(shortcut))
            return
    raise ValueError("ไม่พบโปรแกรม Google Drive · เปิดจาก Start หรือ Desktop แล้วลองใหม่")

def remembered_drive_root(settings):
    """Selection is independent of which SQLite snapshot is active."""
    pending = settings.get("pending_online_master") or {}
    return str(settings.get("catalog_drive_root") or (None if pending.get("local_only") else pending.get("root")) or
               settings.get("shared_drive_root") or "")

def drive_library(value, *, explicit=False, remembered=""):
    """Resolve the selected library, including a selection inside SONGS.
    Never guess another Drive if the remembered mount is unavailable.
    """
    if not value:
        raise ValueError("กรุณาเลือกโฟลเดอร์หลัก Google Drive ครั้งแรก")
    selected = Path(value).expanduser()
    if not selected.is_dir() or selected.is_symlink():
        raise ValueError("ไม่พบคลัง Google Drive ที่เลือก · ตรวจ Drive for desktop")
    selected = selected.resolve(strict=True)
    for volume in drive_roots():
        mount = volume.resolve(strict=True)
        if mount not in selected.parents:
            continue
        for candidate in (selected, *selected.parents):
            if candidate == mount:
                break
            if ((candidate / "SONGS").is_dir() or
                candidate.name.casefold() == DEFAULT_NAME.casefold() or
                (remembered and candidate == Path(remembered).resolve())):
                inspect(candidate)
                return mount, candidate
        if explicit:
            inspect(selected)
            return mount, selected
    raise ValueError("เลือกโฟลเดอร์หลักคลังเพลงใน My Drive ของ Google Drive for desktop")

def remember_drive_library(app, value, *, explicit=True):
    mount, root = drive_library(value, explicit=explicit,
                                remembered=remembered_drive_root(app.settings))
    if str(root) != remembered_drive_root(app.settings) or not app.settings.get("catalog_drive_root"):
        app.settings["catalog_drive_root"] = str(root)
        app.save_settings()
    return mount, root

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

def prepare_online(source, drive, name="XStageKaraoke", *, cancel=None, progress=None, target_root=None):
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
    root = Path(target_root).absolute() if target_root is not None else drive / name
    # Validate the original path before resolving Windows short-name aliases.
    inspect(root)
    if root.is_symlink():
        raise ValueError("คลังปลายทางเป็น symbolic link")
    root = root.resolve()
    if not _inside(root, drive) or root == drive:
        raise ValueError("คลังปลายทางต้องอยู่ภายใน My Drive ที่เลือก")
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
