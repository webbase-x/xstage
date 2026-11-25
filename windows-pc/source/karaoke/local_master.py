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

def _prepare_replacement(target):
    """Let SQLite checkpoint its own WAL; never unlink a user's journal."""
    target = Path(target)
    _safe(target.parent)
    _safe(target)
    validate_sqlite_sidecars(target.parent, (target.name,))
    sidecars = [target.with_name(target.name + suffix)
                for suffix in ("-wal", "-shm", "-journal")]
    if any(p.exists() for p in sidecars):
        if not target.is_file() or sidecars[2].exists():
            raise ValueError("ฐานปลายทางมี journal ค้าง · ไม่เขียนทับ")
        try:
            with closing(sqlite3.connect(target.resolve().as_uri() + "?mode=rw",
                                         uri=True, timeout=0.2)) as db:
                # A busy reader or writer must prevent replacement. A clean
                # read-only WAL session on Windows can leave valid sidecars
                # even after all handles have closed.
                busy, frames, copied = db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                if busy or (frames >= 0 and copied != frames):
                    raise ValueError("ฐานปลายทางยังเปิดอยู่ · ไม่เขียนทับ")
                if db.execute("PRAGMA journal_mode=DELETE").fetchone()[0].lower() != "delete":
                    raise ValueError("ไม่สามารถปิด WAL อย่างปลอดภัย")
        except sqlite3.Error as error:
            raise ValueError("ฐานปลายทางยังเปิดอยู่หรือ WAL ไม่พร้อม · ไม่เขียนทับ") from error
    validate_sqlite_sidecars(target.parent, (target.name,))
    if any(p.exists() for p in sidecars):
        raise ValueError("ฐานปลายทางยังเปิดอยู่หรือมี journal ค้าง · ไม่เขียนทับ")


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
        _prepare_replacement(target)
        _safe(target)
        os.replace(stage, target)
    finally:
        stage.unlink(missing_ok=True)

def activate(home, data, settings, *, installed=False):
    """Call before opening any song reader. Legacy database and archives survive."""
    home, data = Path(home), Path(data)
    pending = settings.get("pending_online_master")
    pending_shared = settings.get("pending_shared_drive")
    pc_only = settings.get("pending_pc_only") is True
    local = home / "DB" / "songs.sqlite3"
    # Recover a completed master if the process exited between atomic replace
    # and saving the UI settings. The receipt is local, and must match the DB.
    if not (pending or pending_shared or pc_only):
        receipt = local.parent / ".xstage-pc-master.json"
        if receipt.is_file() and not receipt.is_symlink() and local.is_file() and not local.is_symlink():
            import json
            try:
                if receipt.stat().st_size > 16384:
                    raise ValueError("receipt too large")
                record = json.loads(receipt.read_text(encoding="utf-8"))
                if (record.get("format") == "xstage-pc-master-v1" and
                        record.get("generation") != settings.get("local_master_generation")):
                    from .shared_song_library import validate_shared
                    with closing(sqlite3.connect(local.resolve().as_uri()+"?mode=ro&immutable=1", uri=True)) as db:
                        generation = db.execute("SELECT value FROM catalog_meta WHERE key='generation'").fetchone()
                    if generation and generation[0] == record.get("generation"):
                        validate_shared(record["root"], local)
                        if settings.get("shared_drive_root") != record["root"]:
                            settings.pop("shared_drive_folder_id", None)
                        settings.update(library_mode="google-drive", shared_local_master=True,
                                        shared_drive_root=record["root"], local_master_generation=generation[0])
                        backup = record.get("backup","")
                        if backup and Path(backup).name == backup and (local.parent / backup).is_file():
                            settings["pc_only_backup"] = backup
            except (OSError, ValueError, TypeError, KeyError, AttributeError, sqlite3.Error):
                pass
    if pending_shared and not pc_only:
        from .shared_song_library import validate_shared
        root = validate_shared(pending_shared["root"])
        # Import a verified Drive snapshot to the App/DB local master.
        source = root / "DB/songs.sqlite3"
        current = kind(local)
        if current:
            backup = local.with_name(current + "-" + secrets.token_hex(12) + ".sqlite3.bak")
            snapshot(local, backup)
            if current == "pc":
                settings["pc_only_backup"] = backup.name
        snapshot(source, local)
        validate_shared(root, local)
        with closing(sqlite3.connect(local.resolve().as_uri()+"?mode=ro&immutable=1", uri=True)) as db:
            generation = db.execute("SELECT value FROM catalog_meta WHERE key='generation'").fetchone()[0]
        settings.update(library_mode="google-drive", shared_drive_root=str(root),
                        shared_local_master=True, local_master_generation=generation)
        settings.pop("pending_shared_drive", None)
        settings.pop("pending_online_master", None)
        return local
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
        settings.pop("pending_shared_drive", None)
    elif settings.get("library_mode") != "google-drive" and target != data / "songs.sqlite3":
        if kind(target) == "online":
            raise ValueError("ฐานหลักเป็นชนิด Online · กรุณาเลือกสลับโหมดอย่างปลอดภัย")
        if not target.exists() and kind(data / "songs.sqlite3") == "pc":
            snapshot(data / "songs.sqlite3", target)
    return target
