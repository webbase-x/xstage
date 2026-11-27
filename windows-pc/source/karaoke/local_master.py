"""Local master catalog activation and non-destructive migration."""
from contextlib import closing
from pathlib import Path
import os
import hashlib
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
        if not pending.get("local_only"):
            if settings.get("shared_drive_root") != pending["root"]:
                settings.pop("shared_drive_folder_id", None)
            settings["shared_drive_root"] = pending["root"]
        settings.update(library_mode="google-drive", shared_local_master=True)
        settings["shared_source_songs"] = pending.get("source_songs") or str(Path(pending["root"]) / "SONGS")
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

def _catalog_fingerprint(path, cancel=None):
    """Read the completed snapshot in bounded chunks, not a whole-file buffer."""
    path = Path(path)
    _safe(path)
    if not path.is_file():
        return None
    before = path.stat()
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as stream:
        while True:
            if cancel is not None and cancel.is_set():
                raise InterruptedError("ยกเลิกการตรวจฐานข้อมูล")
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError("ฐานข้อมูลเปลี่ยนระหว่างตรวจสอบ · ลองซิงก์ใหม่")
    return before.st_size, digest.hexdigest()


def export_portable(home, drive_root, *, overwrite=False, cancel=None, on_unchanged=None):
    """Publish a completed PC snapshot independently of catalog scanning.

    The destination must be the selected library root. Do not modify songs
    or device settings, and retain an existing destination as a backup.
    """
    from .shared_song_library import validate_shared
    from .shared_drive_layout import inspect
    home = Path(home).resolve(strict=True)
    source = home / "DB" / "songs.sqlite3"
    root = Path(inspect(drive_root)["root"])
    if not root.is_dir() or not (root / "SONGS").is_dir():
        raise ValueError("กรุณาคัดลอกโฟลเดอร์ SONGS ไปยังคลัง Google Drive ก่อน")
    _safe(source.parent)
    _safe(source)
    validate_sqlite_sidecars(source.parent, (source.name,))
    validate_shared(home, source)
    target = root / "DB" / "songs.sqlite3"
    _safe(target.parent)
    _safe(target)
    if source.resolve() == target.resolve():
        raise ValueError("ต้นทางและปลายทางเป็นไฟล์เดียวกัน")
    def stopped():
        if cancel is not None and cancel.is_set():
            raise InterruptedError("ยกเลิกก่อนเผยแพร่ฐานข้อมูล")
    stopped()
    target.parent.mkdir(parents=True, exist_ok=True)
    # Never compare a live base file as if it were a complete SQLite snapshot.
    if target.exists():
        validate_sqlite_sidecars(target.parent, (target.name,))
        if any(target.with_name(target.name + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
            raise ValueError("ฐานปลายทางมี journal ค้าง · ไม่ซิงก์จนกว่าจะปิดฐานอย่างปลอดภัย")
    original = _catalog_fingerprint(target, cancel)
    stage = target.with_name(".export-" + secrets.token_hex(16) + ".sqlite3")
    try:
        snapshot(source, stage)
        validate_shared(root, stage)
        # Drive file IDs belong to a particular cloud folder, not the PC
        # catalog. Resolve them from the selected folder at playback time.
        import json
        with closing(sqlite3.connect(stage)) as db:
            for ident, payload, path, size in db.execute(
                    "SELECT id,payload,path,original_file_size FROM songs"):
                stopped()
                row = json.loads(payload)
                parts = path.split("/")
                if (len(parts) < 2 or parts[0] != "SONGS" or
                    any(x in ("", ".", "..") or ":" in x or chr(92) in x for x in parts)):
                    raise ValueError("พาธเพลงในฐานไม่ปลอดภัย: " + path)
                media = root.joinpath(*parts)
                if (not media.is_file() or media.is_symlink() or
                    (root / "SONGS").resolve() not in media.resolve().parents or
                    (size is not None and media.stat().st_size != size)):
                    raise ValueError("เพลงบน Drive ไม่ตรงกับฐาน PC: " + path)
                for key in ("xmid", "xsk"):
                    if row.get(key):
                        import hashlib
                        expected = str(row[key].get("md5Checksum", "")).lower()
                        if len(expected) != 32 or any(ch not in "0123456789abcdef" for ch in expected):
                            raise ValueError("ฐานเพลงไม่มี MD5 ที่ตรวจสอบได้: " + path)
                        digest = hashlib.md5(usedforsecurity=False)
                        with media.open("rb") as stream:
                            while True:
                                stopped()
                                chunk = stream.read(1024 * 1024)
                                if not chunk:
                                    break
                                digest.update(chunk)
                        if digest.hexdigest() != expected:
                            raise ValueError("MD5 เพลงบน Drive ไม่ตรงกับฐาน PC: " + path)
                        row[key]["fileId"] = ""
                        row["pendingDriveLink"] = True
                db.execute("UPDATE songs SET payload=? WHERE id=?",
                           (json.dumps(row, ensure_ascii=False, separators=(",", ":")), ident))
            db.commit()
        validate_shared(root, stage)
        stopped()
        staged_fingerprint = _catalog_fingerprint(stage, cancel)
        if _catalog_fingerprint(target, cancel) != original:
            raise ValueError("ฐาน Cloud เปลี่ยนระหว่างเตรียมส่ง · ไม่เขียนทับ")
        if original is not None and original == staged_fingerprint:
            # Identical bytes: do not alter mtime, create a backup, or upload.
            if on_unchanged is not None:
                on_unchanged()
            return target
        if target.exists():
            if not overwrite:
                raise FileExistsError("มีฐานปลายทางแล้ว · ต้องยืนยันก่อนเขียนทับ")
            _prepare_replacement(target)
            backup = target.with_name("songs-" + secrets.token_hex(8) + ".sqlite3.bak")
            snapshot(target, backup)
        stopped()
        _prepare_replacement(target)
        if not overwrite and target.exists():
            raise FileExistsError("พบฐานปลายทางใหม่ · ไม่เขียนทับ")
        if _catalog_fingerprint(target, cancel) != original:
            raise ValueError("ฐาน Cloud เปลี่ยนก่อนแทนที่ · ไม่เขียนทับ")
        stopped()
        os.replace(stage, target)
        return target
    finally:
        stage.unlink(missing_ok=True)
