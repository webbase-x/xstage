"""Synchronize an exported XStageSong catalog with Karaoke PC's real SQLite DB.

The Karaoke PC songs.sqlite3 is separate from XStageSong/LYRICS/current.json.
Import is additive: never replace a live DB, favorites, queue, or manual edits.
"""
from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys


def database_location(destination):
    """Identify an installed Karaoke PC, otherwise create portable native DB."""
    library = Path(destination).expanduser().resolve()
    if library.parent.name.casefold() == "songs":
        install = library.parent.parent
        app = install / "App"
        if (app / "XStageKaraoke.exe").is_file():
            # Start-XStage-Silent.vbs passes --data-dir <install>/Data.
            if (install / "Data").is_dir() or (install / "Start-XStage-Silent.vbs").is_file():
                return install / "Data" / "songs.sqlite3", True
            if (app / "data").is_dir():
                return app / "data" / "songs.sqlite3", True
            return install / "Data" / "songs.sqlite3", True
        if (install / "XStageKaraoke.exe").is_file():
            return install / "data" / "songs.sqlite3", True
    return library / "DB" / "songs.sqlite3", False


def native_song_library():
    """Bundle the exact Karaoke PC SongLibrary rather than reimplement its schema."""
    folder = Path(__file__).resolve().parent
    candidates = (folder / "karaoke_library.py",
                  folder.parent / "windows-pc" / "source" / "karaoke" / "library.py")
    source = next((p for p in candidates if p.is_file()), None)
    if not source:
        raise RuntimeError("ชุด Song Studio ไม่พบโมดูล SQLite ของ Karaoke PC")
    name = "_xstage_native_karaoke_library"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, source)
        if spec is None or spec.loader is None:
            raise RuntimeError("โหลดโครงสร้างฐานข้อมูล Karaoke PC ไม่สำเร็จ")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(name, None)
            raise
    return sys.modules[name].SongLibrary


def _inside(root, rel, prefix):
    if not isinstance(rel, str) or not rel.startswith(prefix + "/"):
        raise ValueError("รายการเพลงอ้างถึงพาธคลังไม่ถูกต้อง")
    parts = rel.split("/")
    if len(parts) < 3 or any(p in ("", ".", "..") or
                             any(c in p for c in ("\\", ":", "\0")) for p in parts):
        raise ValueError("รายการเพลงมีพาธไม่ปลอดภัย")
    raw = Path(root).joinpath(*parts)
    if raw.is_symlink() or not raw.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError("รายการเพลงอ้างพาธนอกคลังหรือ symbolic link")
    return raw


def catalog_rows(destination, records):
    """Match karaoke.pc_xstagesong.catalog_rows' columns and media identities."""
    root = Path(destination)
    seen, rows = set(), []
    allowed = {".mid", ".midi", ".kar", ".m4a", ".mp3", ".wav", ".wma",
               ".mp4", ".avi", ".mpg", ".mpeg", ".wmv", ".mkv", ".mov",
               ".flac", ".ogg", ".oga", ".aac"}
    for rec in records:
        path = _inside(root, (rec.get("audio") or {}).get("path"), "AUDIO")
        if not path.is_file() or path.suffix.casefold() not in allowed:
            raise ValueError("ไม่พบไฟล์เพลงที่ Karaoke PC รองรับ: " + str(path))
        key = os.path.normcase(str(path.resolve())).casefold()
        if key in seen:
            raise ValueError("พบไฟล์เพลงซ้ำในฐาน Karaoke PC: " + str(path))
        seen.add(key)
        first = ""
        lyric = rec.get("lyrics")
        if lyric:
            lp = _inside(root, lyric.get("path"), "LYRICS")
            if not lp.is_file() or lp.suffix.casefold() != ".json":
                raise ValueError("ไม่พบ Lyrics JSON สำหรับ Karaoke PC")
            data = json.loads(lp.read_text(encoding="utf-8-sig"))
            if data.get("schemaVersion") != 1 or not isinstance(data.get("lines"), list):
                raise ValueError("รูปแบบเนื้อร้อง Karaoke PC ไม่ถูกต้อง")
            first = " ".join(str(v.get("text") or "") for v in data["lines"][:8])[:512]
        ext = path.suffix.casefold()
        rows.append({
            "path": str(path), "code": str(rec.get("code") or ""),
            "title": str(rec.get("title") or path.stem),
            "artist": str(rec.get("artist") or ""),
            "kind": "MIDI" if ext in {".mid", ".midi", ".kar"} else
                    "VIDEO" if ext in {".mp4", ".avi", ".mov", ".mkv"} else "AUDIO",
            "format": ext[1:].upper(), "playable": 1,
            "first_lyric": first, "source_catalog": "XStageSong PC"
        })
    return rows


def sync(destination, records):
    """Create or safely upsert the native Karaoke SQLite index.

    SQLite online backup runs before any modification to an existing DB.
    Retry is safe; the native upsert preserves manual artist/title, favorites,
    and the queue file, and changes only catalog-indexed songs.
    """
    dest = Path(destination).resolve()
    db_path, installed = database_location(dest)
    if db_path.is_symlink() or any(p.is_symlink() for p in db_path.parents):
        raise ValueError("พบ symbolic link ในตำแหน่งฐานเพลง")
    # Validate every file BEFORE touching any database.
    rows = catalog_rows(dest, records)
    existed = db_path.is_file()
    if db_path.exists() and not existed:
        raise ValueError("ปลายทางฐานเพลงไม่ใช่ไฟล์ SQLite")
    if existed:
        with sqlite3.connect(db_path, timeout=10) as original:
            if original.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                raise ValueError("ฐาน Karaoke PC เดิมไม่สมบูรณ์")
            has_songs = original.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='songs'"
            ).fetchone()
            if not has_songs:
                raise ValueError("ไฟล์ปลายทางไม่ใช่ฐานเพลง Karaoke PC · ไม่เขียนทับ")
            backup = db_path.with_name(
                db_path.stem + "-before-songstudio-" +
                datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") +
                "-" + secrets.token_hex(4) + ".sqlite3"
            )
            temp = backup.with_suffix(".tmp")
            try:
                with sqlite3.connect(temp) as copy:
                    original.backup(copy, pages=256, sleep=0.1)
                    if copy.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                        raise ValueError("ตรวจฐานสำรอง Karaoke PC ไม่ผ่าน")
                os.replace(temp, backup)
            finally:
                temp.unlink(missing_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    native_song_library()(db_path).upsert_catalog(rows, preserve_playable=True)
    with sqlite3.connect(db_path, timeout=10) as verified:
        if verified.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
            raise ValueError("ฐาน Karaoke PC หลังอัปเดตไม่ผ่านการตรวจสอบ")
    return {"database": str(db_path), "databaseAction": "updated" if existed else "created",
            "databaseInstalled": installed, "indexedSongs": len(rows)}
