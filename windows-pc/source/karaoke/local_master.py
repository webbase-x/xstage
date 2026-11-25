"""Local master catalog activation and non-destructive migration."""
from contextlib import closing
from pathlib import Path
import os
import secrets
import sqlite3
from .restore import copy_database, validate_sqlite_sidecars

def _safe(path):
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise ValueError("พาธฐานเพลงเป็นลิงก์ที่ไม่ปลอดภัย: " + str(path))

def master_path(home, data, *, installed=False):
    home, data = Path(home), Path(data)
    # --data-dir remains an isolated runtime/test/portable profile.
    return home / "DB" / "songs.sqlite3" if installed and data.resolve() == (home / "data").resolve() else data / "songs.sqlite3"

def kind(path):
    path = Path(path)
    _safe(path)
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError("พาธฐานเพลงไม่ใช่ไฟล์")
    validate_sqlite_sidecars(path.parent, (path.name,))
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "catalog_meta" in tables:
            meta = dict(db.execute("SELECT key,value FROM catalog_meta"))
            if meta.get("pcSchema") == "shared-v1":
                return "online"
            raise ValueError("ไม่รู้จักโครงสร้างฐานเพลงร่วม")
        if "songs" in tables:
            return "pc"
        raise ValueError("ไม่รู้จักโครงสร้างฐานเพลง PC")

def snapshot(source, target):
    source, target = Path(source), Path(target)
    _safe(target.parent)
    _safe(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.with_name(".catalog-" + secrets.token_hex(16) + ".sqlite3")
    try:
        copy_database(source, stage)
        with closing(sqlite3.connect(stage)) as db:
            if db.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                raise ValueError("สำเนาฐานเพลงไม่สมบูรณ์")
            db.execute("PRAGMA journal_mode=DELETE")
        validate_sqlite_sidecars(target.parent, (target.name,))
        if any(target.with_name(target.name + suffix).exists()
               for suffix in ("-wal", "-shm", "-journal")):
            raise ValueError("ฐานปลายทางยังเปิดอยู่หรือมี journal ค้าง · ไม่เขียนทับ")
        _safe(target)
        os.replace(stage, target)
    finally:
        stage.unlink(missing_ok=True)

def activate(home, data, settings, *, installed=False):
    """Call before opening any song reader. Legacy database and archives survive."""
    home, data = Path(home), Path(data)
    pending = settings.get("pending_online_master")
    pc_only = settings.get("pending_pc_only") is True
    local = home / "DB" / "songs.sqlite3"
    if pending or pc_only or settings.get("shared_local_master") or settings.get("catalog_local_master"):
        target = local
    else:
        target = master_path(home, data, installed=installed)
    _safe(target.parent)
    if pending:
        from .shared_song_library import validate_shared
        if not isinstance(pending, dict) or not isinstance(pending.get("root"), str):
            raise ValueError("ข้อมูลรอเปิดฐานร่วมไม่ถูกต้อง")
        staged = local.with_name(".online-pending.sqlite3")
        validate_shared(pending["root"], staged)
        with closing(sqlite3.connect(staged.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            generation = db.execute("SELECT value FROM catalog_meta WHERE key='generation'").fetchone()
        if not generation or generation[0] != pending.get("generation"):
            raise ValueError("ฐานรอเปิดไม่ตรงรุ่นที่สร้าง")
        current = kind(local)
        if current:
            backup = local.with_name(current + "-" + secrets.token_hex(8) + ".sqlite3.bak")
            snapshot(local, backup)
            if current == "pc":
                settings["pc_only_backup"] = backup.name
        snapshot(staged, local)
        if settings.get("shared_drive_root") != pending["root"]:
            settings.pop("shared_drive_folder_id", None)
        settings.update(library_mode="google-drive", shared_local_master=True,
                        shared_drive_root=pending["root"])
        settings.pop("pending_online_master", None)
        settings.pop("pending_pc_only", None)
    elif pc_only:
        legacy = data / "songs.sqlite3"
        name = settings.get("pc_only_backup", "")
        prior = local.parent / name if isinstance(name, str) and name and Path(name).name == name else legacy
        if kind(prior) != "pc":
            prior = legacy
        current = kind(local)
        if current == "online":
            snapshot(local, local.with_name("online-" + secrets.token_hex(8) + ".sqlite3.bak"))
        if current != "pc":
            if kind(prior) == "pc":
                snapshot(prior, local)
            else:
                from .library import SongLibrary
                stage = local.with_name(".pc-empty-" + secrets.token_hex(8) + ".sqlite3")
                try:
                    SongLibrary(stage)
                    snapshot(stage, local)
                finally:
                    stage.unlink(missing_ok=True)
        settings["library_mode"] = "pc"
        settings["catalog_local_master"] = True
        settings.pop("shared_local_master", None)
        settings.pop("pending_pc_only", None)
    elif settings.get("library_mode") != "google-drive" and target != data / "songs.sqlite3":
        if kind(target) == "online":
            raise ValueError("ฐานหลักเป็นชนิด Online · กรุณาเลือกสลับโหมดอย่างปลอดภัย")
        if not target.exists() and kind(data / "songs.sqlite3") == "pc":
            snapshot(data / "songs.sqlite3", target)
    return target
