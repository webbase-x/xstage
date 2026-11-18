"""Portable, incremental Song Studio source registry shared by PC/Drive import.

A source library is an independent XStageSong tree that can be copied from
another computer. Relative paths, content identities and a persistent bundle
UUID survive moves; song numbers do not define musical identity.

This registry records candidate duplicates and import history but NEVER deletes,
moves, overwrites, or changes karaoke favorites/queues.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path, PurePosixPath

SCHEMA = 1
GROUPS = ("new", "variant", "updated", "duplicate", "conflict")
DEFAULT_GROUPS = ("new", "variant", "updated")
MEDIA_TYPES = {".mid", ".midi", ".kar", ".xsk", ".mp3", ".m4a", ".mp4",
               ".wav", ".flac", ".ogg", ".aac", ".wma", ".webm", ".avi", ".mkv"}


def _rel(root, file):
    root = Path(root).expanduser().resolve()
    file = Path(file)
    if file.is_absolute():
        file = file.resolve()
    else:
        file = (root / file).resolve()
    if not file.is_relative_to(root) or file.is_symlink() or not file.is_file():
        raise ValueError("ไฟล์อยู่นอก XStageSong หรือไม่ใช่ไฟล์ปกติ: " + str(file))
    name = file.relative_to(root).as_posix()
    if not name or any(part in ("", ".", "..") for part in PurePosixPath(name).parts):
        raise ValueError("พาธเพลงไม่ปลอดภัย")
    return name, file


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _lyrics_fingerprint(document):
    if not isinstance(document, dict):
        return ""
    lines = document.get("lines")
    if not isinstance(lines, list) or not lines:
        return ""
    clean = [{"startTime": x.get("startTime"), "endTime": x.get("endTime"),
              "text": x.get("text"), "syllables": x.get("syllables")}
             for x in lines if isinstance(x, dict)]
    if len(clean) != len(lines):
        return ""
    data = json.dumps({"lines": clean, "audioOffsetMs": document.get("audioOffsetMs", 0)},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _song_id(media_sha, lyrics_sha):
    if not (isinstance(media_sha, str) and len(media_sha) == 64):
        raise ValueError("ไม่มีลายนิ้วมือเพลง SHA-256")
    return "song-" + hashlib.sha256(("XSTAGE-SONG-V1:" + media_sha + ":" +
                                      (lyrics_sha or "")).encode()).hexdigest()


def connect(root):
    root = Path(root).expanduser().resolve()
    folder = root / "DB"
    if folder.is_symlink():
        raise ValueError("DB เป็น Symbolic Link ที่ไม่อนุญาต")
    folder.mkdir(parents=True, exist_ok=True)
    file = folder / "song-registry.sqlite3"
    if file.is_symlink():
        raise ValueError("ฐานทะเบียนเพลงเป็น Symbolic Link")
    db = sqlite3.connect(file, timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
    db.execute("""CREATE TABLE IF NOT EXISTS entries(
       path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
       content_sha TEXT NOT NULL, media_sha TEXT NOT NULL, lyrics_sha TEXT NOT NULL,
       song_id TEXT NOT NULL, kind TEXT NOT NULL, record_json TEXT NOT NULL,
       updated_at REAL NOT NULL
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS ix_song_registry_song ON entries(song_id)")
    db.execute("CREATE INDEX IF NOT EXISTS ix_song_registry_sha ON entries(content_sha)")
    db.execute("""CREATE TABLE IF NOT EXISTS import_events(
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       target TEXT NOT NULL, bundle_id TEXT NOT NULL, source_path TEXT NOT NULL,
       source_sha TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL,
       recorded_at REAL NOT NULL
    )""")
    db.execute("""CREATE INDEX IF NOT EXISTS ix_song_registry_imports
                  ON import_events(target,bundle_id,source_sha)""")
    db.execute("CREATE TABLE IF NOT EXISTS duplicate_review("
               "source_path TEXT NOT NULL,target TEXT NOT NULL,source_sha TEXT NOT NULL,"
               "status TEXT NOT NULL,detail TEXT NOT NULL,updated_at REAL NOT NULL,"
               "PRIMARY KEY(source_path,target,source_sha))")
    if not db.execute("SELECT value FROM metadata WHERE key='bundle_id'").fetchone():
        db.execute("INSERT INTO metadata(key,value) VALUES('bundle_id',?)",
                   (uuid.uuid4().hex,))
        db.commit()
    return db


def bundle_id(db):
    return db.execute("SELECT value FROM metadata WHERE key='bundle_id'").fetchone()[0]


def _record(db, root, path, row, *, media_sha, lyrics_sha="", kind):
    name, file = _rel(root, path)
    st = file.stat()
    cache = db.execute("SELECT size,mtime_ns,content_sha FROM entries WHERE path=?",
                       (name,)).fetchone()
    file_sha = (cache[2] if cache and cache[:2] == (st.st_size, st.st_mtime_ns)
                else _hash(file))
    song = _song_id(media_sha, lyrics_sha)
    # A song may have XSK, MIDI+JSON, MP3 or MP4 assets. Its Song ID is
    # shared, but each representation requires a unique karaoke catalog ID.
    # Never reuse filename-derived IDs from two unrelated computers.
    asset_id = song + "-format-" + file.suffix.lower().lstrip(".")
    descriptor = {**row, "webSongId": asset_id,
                  "sourceRegistry": {
        "songId": song, "mediaSha256": media_sha, "lyricsSha256": lyrics_sha,
        "contentSha256": file_sha, "bundleId": bundle_id(db),
        "originalWebSongId": str(row.get("webSongId") or "")}}
    db.execute("""INSERT INTO entries(path,size,mtime_ns,content_sha,media_sha,
       lyrics_sha,song_id,kind,record_json,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)
       ON CONFLICT(path) DO UPDATE SET size=excluded.size,mtime_ns=excluded.mtime_ns,
       content_sha=excluded.content_sha,media_sha=excluded.media_sha,
       lyrics_sha=excluded.lyrics_sha,song_id=excluded.song_id,
       kind=excluded.kind,record_json=excluded.record_json,updated_at=excluded.updated_at""",
       (name, st.st_size, st.st_mtime_ns, file_sha, media_sha, lyrics_sha,
        song, kind, json.dumps(descriptor, ensure_ascii=False, separators=(",", ":")),
        time.time()))
    return descriptor


def register_xsk(root, file, document, *, db=None):
    """Record a sealed XSK2 once without reparsing its MIDI payload."""
    if not isinstance(document, dict) or document.get("format") != "XSK":
        raise ValueError("ข้อมูล XSK ยังไม่ผ่านการตรวจสอบ")
    name, file = _rel(root, file)
    if not name.startswith("MIDI/XSK/") or file.suffix.lower() != ".xsk":
        raise ValueError("ตำแหน่ง XSK ไม่ตรงโครงสร้าง XStageSong")
    media = document.get("audio") or {}
    code = str(document.get("songCode") or "")
    digest = str(media.get("sha256") or "")
    lyric = _lyrics_fingerprint(document)
    row = {"webSongId": _song_id(digest, lyric) + "-format-xsk",
           "code": code, "title": str(document.get("title") or ""),
           "artist": str(document.get("artist") or ""),
           "sourceFormat": "XSK", "audio": {"path": name}, "lyrics": None,
           "bucket": (code[:1].upper() if code[:1].isalnum() else "_")}
    own = db is None
    if own:
        db = connect(root)
    try:
        result = _record(db, root, file, row, media_sha=digest,
                         lyrics_sha=lyric, kind="xsk")
        if own:
            db.commit()
        return result
    finally:
        if own:
            db.close()


def register_catalog_row(root, row, *, db=None):
    """Index a verified pair generated by MIDI-to-Lyrics JSON."""
    audio = row.get("audio") or {}
    name, file = _rel(root, audio.get("path", ""))
    media_sha = str((row.get("sourceIdentity") or {}).get("sha256")
                    or (row.get("sourceRegistry") or {}).get("mediaSha256") or "")
    if len(media_sha) != 64:
        media_sha = _hash(file)
    lyrics_sha = ""
    lyric_path = (row.get("lyrics") or {}).get("path")
    if lyric_path:
        _, lyric = _rel(root, lyric_path)
        lyrics_sha = _lyrics_fingerprint(json.loads(lyric.read_text(encoding="utf-8-sig")))
    own = db is None
    if own:
        db = connect(root)
    try:
        result = _record(db, root, name, row, media_sha=media_sha,
                         lyrics_sha=lyrics_sha, kind="catalog")
        if own:
            db.commit()
        return result
    finally:
        if own:
            db.close()


def _xsk_reader():
    file = Path(__file__).with_name("xsk_package.py")
    spec = importlib.util.spec_from_file_location("xstage_registry_xsk", file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_rows(root, export, *, include_xsk=True, discover_legacy=True):
    """Combine verified legacy JSON catalog with indexed XSK2 without a full MIDI scan.

    On first import of a pre-registry XSK library, read its XSK2 files once.
    Subsequent imports reuse size/mtime-validated records. XSK1 is retained and
    never treated as portable until converted with the owner's existing key.
    """
    root = Path(root).expanduser().resolve()
    if root.name.casefold() != "xstagesong":
        root = root / "XStageSong"
    if not root.is_dir() or root.is_symlink():
        raise ValueError("ไม่พบคลัง XStageSong ที่เลือก")
    with closing(connect(root)) as db:
        legacy = []
        pointer = root / "current.json"
        if pointer.is_file():
            legacy = export.existing_records(root)
        elif (root / "DB" / "songs-portable.json").is_file():
            descriptor = json.loads((root / "DB" / "songs-portable.json").read_text(encoding="utf-8-sig"))
            if (descriptor.get("format") != "xstage-portable-song-db"
                    or descriptor.get("schemaVersion") != 1
                    or not isinstance(descriptor.get("songs"), list)):
                raise ValueError("ฐานเพลงพกพาไม่ใช่รูปแบบ XStageSong ที่รองรับ")
            legacy = descriptor["songs"]
        output = []
        for row in legacy:
            if str((row.get("audio") or {}).get("path") or "").lower().endswith(".xsk"):
                # Portable XSK rows are registered from their authenticated
                # XSK2 container below, not hashed as ordinary song audio.
                continue
            if not export.record_is_complete(root, row) and not (
                (root / "DB" / "songs-portable.json").is_file()
                and (row.get("audio") or {}).get("path")):
                raise ValueError("เพลงจากฐานต้นทางมีไฟล์ไม่ครบ: " + str(row.get("code")))
            # Old source libraries have no registry. Index each asset once; the
            # content checksum is cached on subsequent runs.
            output.append(register_catalog_row(root, row, db=db))
        if include_xsk:
            folder = root / "MIDI" / "XSK"
            if folder.is_dir() and not folder.is_symlink():
                reader = None
                for file in folder.rglob("*.xsk"):
                    if not file.is_file() or file.is_symlink():
                        raise ValueError("พบไฟล์ XSK ไม่ปลอดภัย: " + str(file))
                    rel, path = _rel(root, file)
                    st = path.stat()
                    entry = db.execute(
                        "SELECT size,mtime_ns,record_json FROM entries WHERE path=? AND kind='xsk'",
                        (rel,)).fetchone()
                    if entry and entry[:2] == (st.st_size, st.st_mtime_ns):
                        output.append(json.loads(entry[2]))
                        continue
                    if not discover_legacy:
                        continue
                    with path.open("rb") as handle:
                        if handle.read(4) == b"XSK1":
                            continue
                    reader = reader or _xsk_reader()
                    document = reader.open_package(path)
                    output.append(register_xsk(root, path, document, db=db))
        db.commit()
    # Keep exactly one portable asset record by content fingerprint and format;
    # a different format is retained as a separate optional variant.
    seen = set()
    result = []
    for row in output:
        info = row.get("sourceRegistry") or {}
        media = (row.get("audio") or {}).get("path", "")
        key = (info.get("songId"), Path(media).suffix.casefold())
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def classify(rows, existing, selected_groups=None):
    """Conservative plan: never merge songs just because codes/titles match."""
    selected = set(selected_groups if selected_groups is not None else DEFAULT_GROUPS)
    if not selected.issubset(GROUPS):
        raise ValueError("ตัวกรองชนิดเพลงนำเข้าไม่ถูกต้อง")
    by_id = {str(r.get("webSongId")): r for r in existing}
    by_code = {}
    by_song = {}
    for row in existing:
        by_code.setdefault(str(row.get("code") or "").casefold(), []).append(row)
        reg = row.get("sourceRegistry") or {}
        if reg.get("songId"):
            by_song.setdefault(reg["songId"], []).append(row)
    result = {"counts": {g: 0 for g in GROUPS}, "selected": [],
              "conflicts": [], "duplicates": [], "total": 0}
    for row in rows:
        ident = str(row.get("webSongId") or "")
        code = str(row.get("code") or "").casefold()
        reg = row.get("sourceRegistry") or {}
        family = reg.get("songId")
        fmt = Path((row.get("audio") or {}).get("path", "")).suffix.casefold()
        prior = by_id.get(ident)
        siblings = by_song.get(family, []) if family else []
        if prior:
            oldreg = prior.get("sourceRegistry") or {}
            old_fmt = Path((prior.get("audio") or {}).get("path", "")).suffix.casefold()
            if oldreg.get("songId") == family and family:
                # Two XSK builds may contain identical MIDI and timed lyrics
                # but have different ZIP metadata / file hashes. The verified
                # musical identity is equal: do not import those twice.
                category = ("duplicate" if old_fmt == fmt
                            and prior.get("title") == row.get("title")
                            and prior.get("artist") == row.get("artist")
                            else "updated")
            elif oldreg.get("contentSha256") == reg.get("contentSha256") and (
                    oldreg.get("lyricsSha256") == reg.get("lyricsSha256")):
                category = "duplicate"
            elif (oldreg.get("bundleId") and
                  oldreg.get("bundleId") == reg.get("bundleId") and
                  oldreg.get("mediaSha256") and
                  oldreg.get("mediaSha256") == reg.get("mediaSha256") and
                  (prior.get("audio") or {}).get("path") ==
                  (row.get("audio") or {}).get("path")):
                # Same independently created source bundle and same unchanged
                # media file: a revised timed JSON is a NEW VERSION, not a
                # second playable song with the same path.
                category = "updated"
            else:
                category = "conflict"
        elif siblings:
            category = ("duplicate" if any(
                Path((x.get("audio") or {}).get("path", "")).suffix.casefold() == fmt
                for x in siblings) else "variant")
        elif code and any((x.get("sourceRegistry") or {}).get("songId") != family
                          for x in by_code.get(code, [])):
            category = "conflict"
        else:
            category = "new"
        result["counts"][category] += 1
        result["total"] += 1
        if category == "conflict":
            result["conflicts"].append({"code": row.get("code"), "title": row.get("title"),
                                        "reason": "รหัสหรือ Song ID ชนกับเพลงอื่น"})
        elif category == "duplicate":
            result["duplicates"].append({"code": row.get("code"), "title": row.get("title"),
                                         "path": (row.get("audio") or {}).get("path")})
        if category in selected and category not in ("conflict", "duplicate"):
            # An exact duplicate is reviewable, never copied/uploaded twice.
            result["selected"].append(row)
    return result


def assign_target_codes(records, destination_rows):
    """Resolve numeric collisions only in the import projection, never alter source.

    Content identity remains stable across machines; an import from machine B
    with code 00001 must not overwrite unrelated 00001 from machine A.
    """
    used = {}
    destination_by_id = {}
    for row in destination_rows:
        code = str(row.get("code") or "").casefold()
        if code:
            used.setdefault(code, row)
        stable_id = str(row.get("webSongId") or "")
        if stable_id:
            destination_by_id.setdefault(stable_id, row)
    result = []
    # An unchanged audio source may receive a new content-derived Song ID
    # after its timed lyrics are edited. Preserve the karaoke catalog identity
    # only for the same source bundle + identical media checksum + same
    # relative media path. Different machines with 00001.mid remain distinct.
    destination_by_source = {}
    for original in destination_rows:
        reg = original.get("sourceRegistry") or {}
        key = (reg.get("bundleId"), reg.get("mediaSha256"),
               (original.get("audio") or {}).get("path"))
        if all(key):
            destination_by_source.setdefault(key, []).append(original)
    for original in records:
        row = dict(original)
        code = str(row.get("code") or "")
        prior = destination_by_id.get(str(row.get("webSongId") or ""))
        reg = row.get("sourceRegistry") or {}
        source_key = (reg.get("bundleId"), reg.get("mediaSha256"),
                      (row.get("audio") or {}).get("path"))
        source_matches = destination_by_source.get(source_key, []) if all(source_key) else []
        if prior is None and len(source_matches) == 1:
            former = source_matches[0]
            if former.get("webSongId"):
                row["sourceRegistry"] = {
                    **reg, "revisedSongId": reg.get("songId"),
                    "songId": (former.get("sourceRegistry") or {}).get("songId")}
                row["webSongId"] = former["webSongId"]
                prior = former
        if prior and ((prior.get("sourceRegistry") or {}).get("songId") ==
                      (row.get("sourceRegistry") or {}).get("songId")):
            # Previous import may have assigned an alias. Reuse it forever,
            # even when the original machine's code is still 00001.
            previous_code = str(prior.get("code") or "")
            if previous_code and previous_code.casefold() in used:
                if code != previous_code:
                    row["originalCode"] = code
                row["code"] = previous_code
                result.append(row)
                continue
        occupying = used.get(code.casefold())
        if occupying is not None:
            same = ((occupying.get("sourceRegistry") or {}).get("songId")
                    == (row.get("sourceRegistry") or {}).get("songId"))
            if not same:
                width = max(5, min(12, len(code)))
                # Numeric destination codes are local aliases, not Song IDs.
                number = 1
                while str(number).zfill(width).casefold() in used:
                    number += 1
                    if number > 999999999999:
                        raise ValueError("รหัสเพลงปลายทางไม่เพียงพอ")
                next_code = str(number).zfill(width)
                row["originalCode"] = code
                row["code"] = next_code
                code = next_code
        if code:
            used[code.casefold()] = row
        result.append(row)
    return result


def log_import(target_root, target, source_root, rows, status, detail=""):
    if target not in ("pc", "drive") or not isinstance(status, str) or len(status) > 64:
        raise ValueError("ปลายทางหรือสถานะนำเข้าไม่ถูกต้อง")
    with closing(connect(target_root)) as dest:
        with closing(connect(source_root)) as src:
            source_bundle = bundle_id(src)
        for row in rows:
            reg = row.get("sourceRegistry") or {}
            media = str((row.get("audio") or {}).get("path") or "")
            source_sha = str(reg.get("contentSha256") or "")
            if not media or len(source_sha) != 64:
                continue
            dest.execute("""INSERT INTO import_events
                (target,bundle_id,source_path,source_sha,status,detail,recorded_at)
                VALUES(?,?,?,?,?,?,?)""",
                (target, source_bundle, media, source_sha, status, detail[:400], time.time()))
            if status in ("duplicate", "conflict"):
                dest.execute("""INSERT INTO duplicate_review(
                     source_path,target,source_sha,status,detail,updated_at)
                     VALUES(?,?,?,?,?,?)
                     ON CONFLICT(source_path,target,source_sha)
                     DO UPDATE SET status=excluded.status,detail=excluded.detail,
                     updated_at=excluded.updated_at""",
                     (media, target, source_sha, status, detail[:400], time.time()))
        dest.commit()


def duplicate_page(root, target="pc", offset=0, limit=50):
    if target not in ("pc", "drive") or type(offset) is not int or offset < 0:
        raise ValueError("ตัวกรองประวัติไม่ถูกต้อง")
    with closing(connect(root)) as db:
        total = db.execute("SELECT COUNT(*) FROM duplicate_review WHERE target=?",
                           (target,)).fetchone()[0]
        items = db.execute("""SELECT source_path,status,detail,source_sha
            FROM duplicate_review WHERE target=?
            ORDER BY updated_at DESC LIMIT ? OFFSET ?""",
            (target, min(100, max(1, limit)), offset)).fetchall()
    return {"total": total, "offset": offset,
            "items": [{"path": a, "status": b, "reason": c, "sha256": d}
                      for a, b, c, d in items]}
