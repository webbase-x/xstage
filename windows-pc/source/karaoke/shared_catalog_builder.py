"""Rebuild the exact XStage Karaoke Online+PC SQLite snapshot from Drive for desktop.

The Google Drive *folder* is shared; this code never opens the Song Studio DB.
A local PC cannot infer Google Drive file IDs. Unlinked packages are marked
pendingDriveLink in payload; Online verifies the Drive path and MD5 on demand.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time
import unicodedata
import zipfile
from contextlib import closing
from pathlib import Path

from .xmid_reader import read_xmid

MAX_PACKAGES = 300000
MAX_SQLITE_BYTES = 192 * 1048576
MAX_XSK_BYTES = 152 * 1048576
MAX_XSK_MEDIA = 128 * 1048576
SCHEMA = """
CREATE TABLE catalog_meta (key TEXT PRIMARY KEY NOT NULL,value TEXT NOT NULL);
CREATE TABLE songs (
 id INTEGER PRIMARY KEY NOT NULL,ordinal INTEGER NOT NULL,
 web_song_id TEXT UNIQUE NOT NULL,path TEXT NOT NULL,kind TEXT NOT NULL,
 search TEXT NOT NULL,favorite INTEGER NOT NULL DEFAULT 0,
 playable INTEGER NOT NULL DEFAULT 1,format TEXT NOT NULL DEFAULT '',
 first_lyric TEXT NOT NULL DEFAULT '',rhythm TEXT NOT NULL DEFAULT '',
 key_signature TEXT NOT NULL DEFAULT '',bpm TEXT NOT NULL DEFAULT '',
 source_catalog TEXT NOT NULL DEFAULT '',user_edited INTEGER NOT NULL DEFAULT 0,
 duplicate_of INTEGER NOT NULL DEFAULT 0,duplicate_state TEXT NOT NULL DEFAULT '',
 duplicate_preferred INTEGER NOT NULL DEFAULT 0,
 code TEXT NOT NULL,title TEXT NOT NULL,artist TEXT NOT NULL,
 source_format TEXT NOT NULL,original_filename TEXT NOT NULL DEFAULT '',
 original_relative_path TEXT NOT NULL DEFAULT '',original_file_size INTEGER,
 source_code TEXT NOT NULL DEFAULT '',midi_size INTEGER,midi_md5 TEXT,
 payload TEXT NOT NULL
);
CREATE UNIQUE INDEX songs_midi_md5_uq ON songs(midi_md5)
 WHERE midi_md5 IS NOT NULL;
CREATE INDEX songs_midi_size_idx ON songs(midi_size)
 WHERE midi_size IS NOT NULL;
CREATE INDEX songs_source_code_idx ON songs(source_code);
CREATE INDEX songs_code_idx ON songs(code);
CREATE INDEX songs_title_idx ON songs(title);
CREATE INDEX songs_artist_idx ON songs(artist);
CREATE INDEX songs_code ON songs(code);
CREATE INDEX songs_title ON songs(title COLLATE NOCASE,id);
CREATE INDEX songs_duplicate ON songs(duplicate_of);
CREATE UNIQUE INDEX songs_portable_path ON songs(path COLLATE NOCASE);
CREATE TABLE removed_songs (web_song_id TEXT PRIMARY KEY NOT NULL);
"""
INSERT = """INSERT INTO songs (
 id,ordinal,web_song_id,path,kind,search,format,code,title,artist,
 source_format,original_filename,original_relative_path,original_file_size,
 source_code,midi_size,midi_md5,payload
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""


def _stop(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError("ยกเลิกการสร้างฐานใหม่แล้ว ฐานเดิมยังไม่เปลี่ยน")


def _hash(path):
    digest = hashlib.md5()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pc_id(ident):
    h = 14695981039346656037
    for byte in ident.encode("utf-8"):
        h = ((h ^ byte) * 1099511628211) & ((1 << 64) - 1)
    return (h & ((1 << 53) - 1)) or 1


def _root(value):
    root = Path(value).expanduser()
    if root.name != "XStageKaraoke" or root.is_symlink() or not root.is_dir():
        raise ValueError("ต้องเลือกโฟลเดอร์หลัก XStageKaraoke ใน Google Drive for desktop")
    root = root.resolve(strict=True)
    for kind in ("SONGS", "SOUNDFONT"):
        child = root / kind
        if not child.is_dir() or child.is_symlink():
            raise ValueError("ไม่มีโฟลเดอร์ " + kind + " ใน XStageKaraoke")
    for kind in ("DB", "CACHE", "BACKUP"):
        child = root / kind
        if child.is_symlink() or (child.exists() and not child.is_dir()):
            raise ValueError("โฟลเดอร์ " + kind + " ไม่ปลอดภัย")
    return root


def _read_xsk(path):
    if path.stat().st_size > MAX_XSK_BYTES:
        raise ValueError("XSK ใหญ่เกินขอบเขต")
    with path.open("rb") as stream:
        if stream.read(4) != b"XSK2":
            raise ValueError("รองรับเฉพาะ XSK2 ที่ไม่เข้ารหัส")
        packed = stream.read(MAX_XSK_BYTES + 1)
    with zipfile.ZipFile(io.BytesIO(packed)) as z:
        entries = z.infolist()
        if len(entries) != 2 or len({x.filename for x in entries}) != 2:
            raise ValueError("XSK ต้องมี MIDI และ JSON อย่างละ 1 ไฟล์")
        for item in entries:
            if (item.flag_bits & 1 or item.compress_type not in
                (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) or
                item.file_size > MAX_XSK_MEDIA or
                not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,149}", item.filename)):
                raise ValueError("XSK มีไฟล์ภายในที่ไม่ปลอดภัย")
        metadata = [x for x in entries if x.filename.lower().endswith(".json")]
        if len(metadata) != 1 or metadata[0].file_size > 8 * 1048576:
            raise ValueError("XSK ไม่มี Lyrics JSON")
        doc = json.loads(z.read(metadata[0]).decode("utf-8"))
        info = doc.get("audio") or {}
        midi = [x for x in entries if x.filename == info.get("file")]
        if (len(midi) != 1 or not re.search(r"\.(mid|midi|kar)$", midi[0].filename, re.I)
            or doc.get("format") != "XSK" or doc.get("formatVersion") != 2
            or doc.get("schemaVersion") != 2 or
            not isinstance(doc.get("lines"), list) or not doc["lines"]):
            raise ValueError("XSK ไม่มี MIDI/metadata ที่ตรงกัน")
        raw = z.read(midi[0])
        if (len(raw) != info.get("size") or
            hashlib.sha256(raw).hexdigest() != str(info.get("sha256", "")).lower()
            or raw[:4] not in (b"MThd", b"NCN1")):
            raise ValueError("XSK MIDI ไม่ผ่านการตรวจ SHA-256")
        return raw, {"code": doc.get("songCode"), "title": doc.get("title"),
                     "artist": doc.get("artist"), "lines": doc.get("lines")}


def _old_refs(path):
    refs = {}
    if not path.is_file():
        return refs
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            for (payload,) in db.execute("SELECT payload FROM songs"):
                row = json.loads(payload)
                for key in ("xmid", "xsk"):
                    media = row.get(key) or {}
                    if media.get("fileId") and media.get("path") and media.get("md5Checksum"):
                        refs[(str(media["path"]).casefold(),
                              str(media["md5Checksum"]).lower())] = str(media["fileId"])
    except (sqlite3.Error, ValueError, TypeError, UnicodeError):
        # Old schemas may be incompatible; rebuild without reading them.
        return {}
    return refs


def _files(root, cancel):
    songs = root / "SONGS"
    files = []
    for directory, folders, names in os.walk(songs, followlinks=False):
        _stop(cancel)
        folders[:] = sorted(d for d in folders
                            if not (Path(directory) / d).is_symlink()
                            and not d.startswith("."))
        for name in sorted(names):
            file = Path(directory) / name
            if file.is_symlink() or file.suffix.lower() not in (".xmid", ".xsk"):
                continue
            relative = file.relative_to(songs).as_posix()
            if any(c in (".", "..", "") or ":" in c for c in relative.split("/")):
                raise ValueError("พาธเพลงไม่ปลอดภัย: " + relative)
            files.append((relative, file))
            if len(files) > MAX_PACKAGES:
                raise ValueError("มีไฟล์เกิน 300,000 รายการ")
    return sorted(files, key=lambda entry: entry[0].casefold())


def _record(relative, file, old):
    ext = file.suffix.lower()
    if ext == ".xmid":
        midi, doc = read_xmid(file)
    else:
        midi, doc = _read_xsk(file)
    code = str(doc.get("code") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", code):
        raise ValueError("รหัสเพลงในแพ็กเกจไม่รองรับ: " + str(file))
    title = str(doc.get("title") or "").strip()
    artist = str(doc.get("artist") or "").strip()
    if not title or not artist:
        raise ValueError("ไฟล์ไม่มีชื่อเพลงหรือศิลปิน: " + str(file))
    midi_hash = hashlib.md5(midi).hexdigest()
    packed_hash = _hash(file)
    kind = ext[1:]
    ident = "browser/" + kind + "/" + packed_hash
    media_path = "SONGS/" + relative
    file_id = old.get((media_path.casefold(), packed_hash), "")
    media = {"fileId": file_id, "md5Checksum": packed_hash,
             "size": file.stat().st_size, "path": media_path}
    record = {
        "webSongId": ident, "code": code, "sourceCode": code,
        "title": title, "artist": artist, "metadataComplete": True,
        "sourceFormat": kind.upper(), "originalFilename": file.name,
        "originalRelativePath": relative, "originalFileSize": file.stat().st_size,
        "midiHash": midi_hash, "midiSize": len(midi),
        "lyricsMode": "timed" if doc.get("lines") else "unavailable",
        kind: media,
    }
    if not file_id:
        record["pendingDriveLink"] = True
    return record


def build(root_value, progress=None, cancel=None, publish=True):
    """Create fresh verified snapshot; atomically replace after explicit consent."""
    root = _root(root_value)
    songs = _files(root, cancel)
    if not songs:
        raise ValueError("ไม่มี XMID/XSK ที่พร้อมสร้างฐานใน XStageKaraoke/SONGS")
    old_file = root / "DB/songs.sqlite3"
    if old_file.is_symlink() or (old_file.exists() and not old_file.is_file()):
        raise ValueError("DB/songs.sqlite3 ไม่ใช่ไฟล์ SQLite ปกติ หยุดเพื่อไม่เขียนนอกคลัง")
    original_signature = _hash(old_file) if old_file.exists() else None
    references = _old_refs(old_file)
    rows, midi_hashes, paths, codes, ids = [], set(), set(), set(), set()
    duplicates = 0
    for index, (relative, file) in enumerate(songs, 1):
        _stop(cancel)
        key = relative.casefold()
        if key in paths:
            raise ValueError("พบชื่อไฟล์ซ้ำบน Windows: " + relative)
        paths.add(key)
        row = _record(relative, file, references)
        if row["midiHash"] in midi_hashes:
            duplicates += 1
            continue
        midi_hashes.add(row["midiHash"])
        base_code = row["code"]
        if base_code.casefold() in codes:
            row["code"] = base_code + "-" + row["midiHash"][:8]
            if row["code"].casefold() in codes:
                raise ValueError("รหัสเพลงในฐานซ้ำ: " + row["code"])
        codes.add(row["code"].casefold())
        number = _pc_id(row["webSongId"])
        if number in ids:
            raise ValueError("รหัสเพลง PC ชนกัน: " + row["webSongId"])
        ids.add(number)
        rows.append((number, row))
        if progress and (index % 25 == 0 or index == len(songs)):
            progress(dict(scanned=index, total=len(songs), accepted=len(rows),
                          duplicates=duplicates), "ตรวจแพ็กเกจ XMID/XSK")
    _stop(cancel)
    if not rows:
        raise ValueError("ไม่พบ MIDI ที่อ่านได้และไม่ซ้ำกัน")
    if not publish:
        return {"scanned": len(songs), "accepted": len(rows),
                "duplicates": duplicates,
                "pending_drive_ids": sum(bool(row.get("pendingDriveLink")) for _, row in rows)}
    for directory in ("DB", "CACHE", "BACKUP"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    # Share the same advisory lock namespace as the browser importer.
    # Drive Desktop propagation is asynchronous, so also re-check the old
    # snapshot immediately before committing the new database.
    cache_root = root / "CACHE"
    for other in cache_root.glob(".xstage-import-lock-*"):
        if other.is_symlink():
            raise ValueError("CACHE มี symlink ของงานสร้างฐาน ไม่ปลอดภัย")
        if other.is_file() and time.time() - other.stat().st_mtime < 300:
            raise ValueError("อีกอุปกรณ์กำลังสร้างฐานบน Google Drive กรุณารอให้เสร็จ")
    lock = cache_root / (".xstage-import-lock-pc-" + secrets.token_hex(12) + ".json")
    with lock.open("x", encoding="utf-8") as handle:
        json.dump({"format": "xstage-catalog-import-lock-v1",
                   "createdBy": "Karaoke PC", "pid": os.getpid(),
                   "createdAt": time.time()}, handle)
    stage = root / "CACHE" / (".songs-" + secrets.token_hex(10) + ".sqlite3")
    try:
        _stop(cancel)
        generation = secrets.token_hex(12)
        with closing(sqlite3.connect(stage)) as db:
            db.executescript(SCHEMA)
            db.executemany("INSERT INTO catalog_meta(key,value) VALUES (?,?)",
                           [(k, str(v)) for k, v in {
                               "format": "xstage-sqlite3-v1", "schemaVersion": 1,
                               "kind": "snapshot", "generation": generation,
                               "pcSchema": "shared-v1", "pathBase": "SONGS"}.items()])
            for ordinal, (ident, row) in enumerate(rows):
                db.execute(INSERT, (ident, ordinal, row["webSongId"],
                    "SONGS/" + row["originalRelativePath"], "MIDI",
                    unicodedata.normalize("NFC",
                        " ".join(str(row.get(k, "")) for k in ("code","title","artist"))).lower(),
                    row["sourceFormat"], row["code"], row["title"], row["artist"],
                    row["sourceFormat"], row["originalFilename"],
                    row["originalRelativePath"], row["originalFileSize"],
                    row["sourceCode"], row["midiSize"], row["midiHash"],
                    json.dumps(row, ensure_ascii=False, separators=(",",":"))))
            db.commit()
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("SQLite ที่สร้างไม่ผ่าน integrity_check")
            if db.execute("SELECT COUNT(*) FROM songs").fetchone()[0] != len(rows):
                raise ValueError("จำนวนเพลงในฐานไม่ตรงกับที่ตรวจ")
        if stage.stat().st_size > MAX_SQLITE_BYTES:
            raise ValueError("ฐาน SQLite ใหญ่เกิน 192 MiB ที่ Online รองรับ")
        _stop(cancel)
        if (_hash(old_file) if old_file.exists() else None) != original_signature:
            raise ValueError("ฐานบน Google Drive เปลี่ยนระหว่างทำงาน กรุณาสร้างใหม่")
        if old_file.exists():
            backup = root / "BACKUP" / (
                "songs-" + time.strftime("%Y%m%d-%H%M%S") + "-" +
                original_signature[:12] + ".sqlite3.bak")
            shutil.copyfile(old_file, backup)
            if _hash(backup) != original_signature:
                raise ValueError("ไฟล์สำรองฐานเดิมไม่ผ่าน SHA-256")
        _stop(cancel)
        os.replace(stage, old_file)  # same Drive volume, atomic local replacement
        return {"scanned": len(songs), "accepted": len(rows),
                "duplicates": duplicates, "generation": generation,
                "database": str(old_file),
                "pending_drive_ids": sum(bool(row.get("pendingDriveLink")) for _, row in rows)}
    finally:
        stage.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)
