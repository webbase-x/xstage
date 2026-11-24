"""One canonical XStageKaraoke/DB/songs.sqlite3 for Online and Karaoke PC.

Online publishes the complete portable SQLite snapshot from Google Drive.
PC opens that *same* file without schema migrations or a second song catalog.
Only per-device queue/favorites and other device-specific settings stay local.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .drive_online_catalog import shared_root, _local_media, _open_read_only
from .library import SearchReader

SHARED_SCHEMA = "shared-v1"
REQUIRED = {
    "id", "web_song_id", "path", "kind", "search", "favorite",
    "playable", "format", "code", "title", "artist",
    "duplicate_of", "duplicate_state", "key_signature", "payload",
}


def validate_shared(root):
    root = shared_root(root)
    with _open_read_only(root) as db:
        metadata = dict(db.execute("SELECT key,value FROM catalog_meta"))
        if (metadata.get("format") != "xstage-sqlite3-v1" or
            metadata.get("schemaVersion") != "1" or
            metadata.get("pcSchema") != SHARED_SCHEMA or
            metadata.get("pathBase") != "SONGS" or
            metadata.get("kind") != "snapshot"):
            raise ValueError(
                "ฐานเพลงยังไม่ใช่ SQLite สำหรับ PC/Online ร่วมกัน "
                "ให้เปิด Karaoke Online > จัดการคลัง > สร้างฐานใหม่สำหรับ PC/Online")
        cols = {row[1] for row in db.execute("PRAGMA table_info(songs)")}
        if not REQUIRED.issubset(cols):
            raise ValueError("ฐานร่วมมีคอลัมน์ไม่ครบ กรุณาสร้างฐานใหม่จาก Karaoke Online")
        if db.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
            raise ValueError("ฐานร่วม SQLite ไม่สมบูรณ์ หยุดอ่านเพื่อป้องกันเพลงผิดรายการ")
    return root


class SharedReader(SearchReader):
    def __init__(self, library):
        self.library = library
        # The Drive sync client may replace a complete SQLite snapshot.
        # Immutable, read-only handles never create -wal or -shm in Drive.
        self.db = _open_read_only(library.root)
        self.db.create_function("xstage_rank", 4, library._rank, deterministic=True)
        self.fts = False
        self._version = None
        self._count = None
        from collections import OrderedDict
        self._cache = OrderedDict()

    def search(self, text="", favorite=False, limit=1000,
               playable_only=False, cancelled=None):
        # Local favorites are a per-device presentation preference; never
        # modify a shared cloud music catalog just because PC marked a star.
        fetch_limit = 5000 if favorite else limit
        rows = super().search(text, False, fetch_limit, False, cancelled)
        rows = (self.library._visible(row) for row in rows)
        rows = (row for row in rows if (not favorite or row["favorite"]) and
                (not playable_only or row["playable"]))
        return list(row for _, row in zip(range(max(0, min(5000,int(limit)))),rows))


class SharedSongLibrary:
    shared_drive = True

    def __init__(self, drive_root, settings=None, save_settings=None):
        self.root = validate_shared(drive_root)
        self.path = self.root / "DB" / "songs.sqlite3"
        self.fts = False
        self.settings = settings if isinstance(settings, dict) else {}
        self.save_settings = save_settings
        from .library import search_rank
        self._rank = search_rank

    def _visible(self, row):
        row = dict(row)
        raw = str(row.get("path") or "")
        # The database owns a relative path, so changing drive letters is safe.
        if not raw.startswith("SONGS/"):
            row["path"] = ""
            row["playable"] = 0
        else:
            absolute = _local_media(self.root, raw)
            row["path"] = absolute or ""
            row["playable"] = int(bool(row.get("playable")) and bool(absolute))
        favorites = self.settings.get("shared_favorite_song_ids", [])
        row["favorite"] = int(row["id"] in favorites) if isinstance(favorites, list) else 0
        return row

    @contextmanager
    def connect(self):
        with _open_read_only(self.root) as db:
            yield db

    def open_reader(self):
        return SharedReader(self)

    def search(self, text="", favorite=False, limit=1000, playable_only=False):
        with self.open_reader() as reader:
            return reader.search(text, favorite, limit, playable_only)

    def get(self, song_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM songs WHERE id=?", (int(song_id),)).fetchone()
            return self._visible(row) if row else None

    def count(self):
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM songs WHERE duplicate_of=0 "
                "AND duplicate_state NOT IN ('deleted','missing','invalid','excluded')").fetchone()[0]

    def has_songs(self):
        return self.count() > 0

    def favorite(self, song_id):
        song_id = int(song_id)
        if self.get(song_id) is None:
            return
        selected = set(x for x in self.settings.get("shared_favorite_song_ids", [])
                       if type(x) is int and x > 0)
        if song_id in selected:
            selected.remove(song_id)
        else:
            selected.add(song_id)
        self.settings["shared_favorite_song_ids"] = sorted(selected)
        if self.save_settings:
            self.save_settings()

    @staticmethod
    def _cloud_owned(*args, **kwargs):
        raise ValueError(
            "ฐานเพลงร่วมสร้างจาก Karaoke Online เท่านั้น "
            "ให้ส่งไฟล์ผ่าน Google Drive แล้วกดสร้าง/อัปเดตฐานบนเว็บ "
            "ไม่เพิ่มรายการที่ไม่มี Drive File ID ลง SQLite")

    edit = _cloud_owned
    add_files = _cloud_owned
    upsert_catalog = _cloud_owned
    rebuild = _cloud_owned
    restore_reindex_backup = _cloud_owned
    backup_before_rebuild = _cloud_owned

    def close(self):
        # No persistent SQLite handles.
        return None


class UnavailableSharedSongLibrary:
    """Fail closed if the selected Drive is unmounted or its DB is not built."""
    shared_drive = True

    def __init__(self, root, error):
        self.root = Path(root)
        self.path = self.root / "DB" / "songs.sqlite3"
        self.reason = str(error)

    def search(self, *args, **kwargs):
        return []
    def get(self, song_id):
        return None
    def count(self):
        return 0
    def has_songs(self):
        return False
    def open_reader(self):
        raise ValueError(self.reason)
    @contextmanager
    def connect(self):
        raise ValueError(self.reason)
        yield  # pragma: no cover
    def favorite(self, *args):
        raise ValueError(self.reason)
    edit = favorite
    add_files = favorite
    rebuild = favorite
    backup_before_rebuild = favorite
