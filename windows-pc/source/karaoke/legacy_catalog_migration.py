"""Migrate a legacy PC SQLite catalog into the shared-v1 snapshot.

No original songs or source database are modified. The old catalog drives the
migration, not a scan/import of every unrelated file in the selected folder.
The shared primary key remains the cross-platform FNV key; the old PC primary
key and visible code are retained as explicit migration identities.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import secrets
import sqlite3
import unicodedata

from . import shared_catalog_builder as b
from .local_master import kind, snapshot, _safe, _catalog_fingerprint
from .shared_song_library import validate_shared
from .restore import validate_sqlite_sidecars


def _relative(raw, root):
    """Resolve the old Windows location without trusting its drive letter.

    Match existing files under the selected SONGS root only. Several possible
    suffixes are allowed for relocation (e.g. XMID/0 -> MIDI/XMID/0), but
    ambiguity is an error, not an arbitrary basename match.
    """
    path = PureWindowsPath(str(raw))
    parts = list(path.parts)
    if path.anchor:
        parts = parts[1:]
    if not parts or any(x in ("", ".", "..") or ":" in x for x in parts):
        raise ValueError("พาธเพลงเดิมไม่ปลอดภัย: " + str(raw))
    if Path(parts[-1]).suffix.lower() not in (".xmid", ".xsk"):
        raise ValueError("ชนิดไฟล์เดิมยังไม่รองรับการย้ายฐาน: " + str(raw))
    matches = {}
    candidates = [tuple(parts[i:]) for i in range(len(parts))]
    # Only a directly selected folder may match the bare filename; never
    # recursively search by basename or silently select a duplicate.
    candidates += [("MIDI", *p) for p in candidates if len(p) >= 2]
    for rel in candidates:
        file = root.joinpath(*rel)
        try:
            # Reject symbolic links/junctions in any component.
            for parent in [file, *file.parents]:
                if parent == root:
                    break
                _safe(parent)
            actual = file.resolve(strict=True)
            if root not in actual.parents or not actual.is_file():
                continue
            matches[os.path.normcase(str(actual))] = (actual.relative_to(root).as_posix(), actual)
        except (FileNotFoundError, NotADirectoryError):
            continue
    if len(matches) != 1:
        raise ValueError(("ไม่พบเพลงในต้นทาง: " if not matches else "พาธเพลงกำกวม: ") + str(raw))
    return next(iter(matches.values()))


def migrate(source_db, source_songs, home, *, progress=None, cancel=None,
            cache_dir=None, full_verify=False, publish=True, cloud_index=None):
    source = Path(source_db).resolve(strict=True)
    songs = Path(source_songs).resolve(strict=True) if cloud_index is None else None
    home = Path(home).resolve(strict=True)
    if (cloud_index is None and not songs.is_dir()) or kind(source) != "pc":
        raise ValueError("กรุณาเลือกฐาน PC เดิมและโฟลเดอร์เพลง XMID/XSK")
    _safe(source)
    validate_sqlite_sidecars(source.parent, (source.name,))
    dest = home / "DB" / ".online-pending.sqlite3"
    _safe(dest.parent)
    _safe(dest)
    if source == dest.resolve():
        raise ValueError("ฐานต้นฉบับและฐานรอเปิดต้องแยกกัน")
    dest.parent.mkdir(parents=True, exist_ok=True)
    stage = dest.with_name(".migration-" + secrets.token_hex(12) + ".sqlite3")
    generation = secrets.token_hex(12)
    old_ids = {**b._old_ids(home / "DB" / "songs.sqlite3"), **b._old_ids(dest)}
    old_owners = {value: key for key,value in old_ids.items()}
    seen_paths, seen_ids, seen_web_ids = set(),set(),set()
    count = reused = 0
    original = _catalog_fingerprint(dest, cancel)
    try:
        # Read a consistent source snapshot even if the local master uses WAL.
        with closing(sqlite3.connect(source.as_uri()+"?mode=ro",uri=True,timeout=10)) as src, \
             closing(sqlite3.connect(stage)) as out:
            src.row_factory = sqlite3.Row
            src.execute("PRAGMA query_only=ON")
            src.execute("PRAGMA trusted_schema=OFF")
            src.execute("BEGIN")
            if src.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                raise ValueError("ฐาน PC เดิมไม่ผ่าน quick_check")
            columns = {r[1] for r in src.execute("PRAGMA table_info(songs)")}
            required = {"id","path","code","title","artist"}
            if not required <= columns or {"web_song_id","payload"} & columns:
                raise ValueError("ฐาน PC เดิมไม่มีคอลัมน์ที่จำเป็น")
            total = src.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
            if not 0 < total <= b.MAX_PACKAGES:
                raise ValueError("จำนวนเพลงต้นฉบับอยู่นอกช่วงที่รองรับ")
            out.executescript(b.SCHEMA)
            out.execute("CREATE TABLE legacy_pc_ids(legacy_id INTEGER PRIMARY KEY, shared_id INTEGER NOT NULL UNIQUE, web_song_id TEXT NOT NULL UNIQUE)")
            out.executemany("INSERT INTO catalog_meta VALUES (?,?)", {
                "format":"xstage-sqlite3-v1","schemaVersion":"1","kind":"snapshot",
                "generation":generation,"pcSchema":"shared-v1","pathBase":"SONGS",
                "legacyMigration":"pc-v1","legacyCount":str(total)}.items())

            def entries():
                for old in src.execute("SELECT * FROM songs ORDER BY id"):
                    b._stop(cancel)
                    relative,file = _relative(old["path"], songs)
                    yield (relative,file)

            # A separate cursor over the same read transaction supplies old
            # metadata. Verified package cache remains reusable after cancel.
            originals = src.execute("SELECT * FROM songs ORDER BY id")
            if cloud_index is None:
                verified = b._verified_rows(entries(), songs, {},
                    cache_dir, cancel, full_verify, False)
            else:
                # Drive reports package MD5 and size, not inner MIDI metadata.
                # Never download packages or fabricate MIDI fingerprints here.
                from .cloud_legacy_migration import resolve_legacy, cloud_record
                def cloud_rows():
                    for old in src.execute("SELECT * FROM songs ORDER BY id"):
                        b._stop(cancel)
                        relative, media = resolve_legacy(old["path"], cloud_index)
                        yield relative, cloud_record(relative, media, dict(old)), False
                verified = cloud_rows()
            for relative, row, cached in verified:
                old = dict(next(originals))
                b._stop(cancel)
                legacy_id = old["id"]
                if type(legacy_id) is not int or legacy_id <= 0:
                    raise ValueError("รหัสภายใน PC เดิมไม่ถูกต้อง")
                key = relative.casefold()
                if key in seen_paths:
                    raise ValueError("หลายรายการเดิมชี้ไปยังไฟล์เดียวกัน: "+relative)
                seen_paths.add(key)
                if not str(old["code"] or "").strip():
                    raise ValueError("เพลงเดิมไม่มีรหัส: "+relative)
                # Never deduplicate or rewrite the user's visible song code.
                # The stable shared key uses the package hash, with a path
                # identity only for otherwise identical packages.
                ident = old_ids.get(key) or row["webSongId"]
                if ident in seen_web_ids or (ident in old_owners and old_owners[ident] != key):
                    if key in old_ids:
                        raise ValueError("รหัสฐานร่วมเดิมชนกัน: "+relative)
                    ident = "browser/"+b.file_kind(row)+"/"+hashlib.sha256(key.encode("utf-8")).hexdigest()
                number = b._pc_id(ident)
                if number in seen_ids or ident in seen_web_ids:
                    raise ValueError("รหัสฐานร่วมชนกัน: "+relative)
                seen_ids.add(number); seen_web_ids.add(ident)
                row["webSongId"] = ident
                row["legacyPcId"] = legacy_id
                row["code"] = str(old["code"])
                row["sourceCode"] = str(old["code"])
                row["title"] = str(old["title"] or "")
                row["artist"] = str(old["artist"] or "")
                row["metadataComplete"] = bool(row["title"].strip() and row["artist"].strip())
                for old_key,new_key in (("first_lyric","firstLyric"),("rhythm","rhythm"),("key_signature","keySignature"),("bpm","bpm")):
                    if old.get(old_key) not in (None,""):
                        row[new_key] = str(old[old_key])
                # Preserve duplicate tracks (including identical MIDI).
                # Shared-v1 permits NULL MIDI fingerprint with package MD5.
                row.pop("midiHash",None)
                if cloud_index is None:
                    row["pendingDriveLink"] = True
                    row[b.file_kind(row)]["fileId"] = ""
                else:
                    row.pop("pendingDriveLink",None)
                out.execute(b.INSERT, (number,count,ident,"SONGS/"+relative,"MIDI",
                    unicodedata.normalize("NFC"," ".join(str(row.get(k,"")) for k in
                        ("code","title","artist","firstLyric","rhythm"))).lower(),
                    row["sourceFormat"],row["code"],row["title"],row["artist"],
                    row["sourceFormat"],row["originalFilename"],relative,row["originalFileSize"],
                    row["sourceCode"],row["midiSize"],None,
                    json.dumps(row,ensure_ascii=False,separators=(",",":")),
                    row["firstLyric"],row["rhythm"],row["keySignature"],row["bpm"]))
                # Preserve local flags, then resolve legacy duplicate pointers
                # after all new identities have been created.
                out.execute("UPDATE songs SET favorite=?,playable=?,source_catalog=?,user_edited=?,duplicate_of=?,duplicate_state=?,duplicate_preferred=? WHERE id=?",
                    (int(bool(old.get("favorite",0))),int(bool(old.get("playable",1))),
                     str(old.get("source_catalog") or ""),int(bool(old.get("user_edited",0))),
                     int(old.get("duplicate_of") or 0),str(old.get("duplicate_state") or ""),
                     int(bool(old.get("duplicate_preferred",0))),number))
                out.execute("INSERT INTO legacy_pc_ids VALUES (?,?,?)",(legacy_id,number,ident))
                count += 1; reused += int(cached)
                if progress and (count % 25 == 0 or count == total):
                    progress(dict(scanned=count,total=total,accepted=count,duplicates=0,reused=reused),"ย้ายฐาน PC เดิม · ตรวจไฟล์จริง")
            if count != total:
                raise ValueError("จำนวนเพลงย้ายไม่ครบ")
            # Reject orphan duplicate pointers rather than silently losing them.
            if out.execute("SELECT 1 FROM songs WHERE duplicate_of<>0 AND duplicate_of NOT IN (SELECT legacy_id FROM legacy_pc_ids) LIMIT 1").fetchone():
                raise ValueError("ฐานเดิมมีรหัสเพลงซ้ำอ้างอิงที่ไม่พบ")
            out.execute("UPDATE songs SET duplicate_of=(SELECT shared_id FROM legacy_pc_ids WHERE legacy_id=songs.duplicate_of) WHERE duplicate_of<>0")
            out.commit()
            if out.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("ฐานร่วมที่สร้างไม่ผ่าน integrity_check")
            if out.execute("SELECT COUNT(*) FROM legacy_pc_ids").fetchone()[0] != total:
                raise ValueError("ตารางจับคู่รหัสไม่ครบ")
        validate_shared(home,stage)
        b._stop(cancel)
        if publish:
            if _catalog_fingerprint(dest,cancel) != original:
                raise ValueError("ฐานรอเปิดเปลี่ยนระหว่างทำงาน · ไม่เขียนทับ")
            if dest.exists():
                backup_dir=home/"BACKUP"
                _safe(backup_dir)
                backup_dir.mkdir(parents=True,exist_ok=True)
                snapshot(dest,backup_dir/("pending-"+secrets.token_hex(8)+".sqlite3.bak"))
            b._stop(cancel)
            os.replace(stage,dest)
        return dict(scanned=count,accepted=count,duplicates=0,reused=reused,
                    pending_drive_ids=count if cloud_index is None else 0,generation=generation,
                    root=str(home),database=str(dest),legacy_migration=True)
    finally:
        stage.unlink(missing_ok=True)


def migrate_queue(data, staged, settings):
    """Retain the PC queue and map its IDs into the separate shared queue.

    Never overwrite a nonempty shared queue. Preserve old queue file; if a
    reference is absent stop activation so the user can resolve it.
    """
    from dataclasses import replace
    from .library import SongQueue
    data=Path(data)
    old=SongQueue(data/"queue.json")
    new=SongQueue(data/"drive-queue.json")
    with closing(sqlite3.connect(Path(staged).resolve().as_uri()+"?mode=ro",uri=True)) as db:
        mapping=dict(db.execute("SELECT legacy_id,shared_id FROM legacy_pc_ids"))
        favorites=[r[0] for r in db.execute("SELECT id FROM songs WHERE favorite=1")]
    if any(item.song_id not in mapping for item in old.items):
        raise ValueError("คิวเดิมมีเพลงที่ไม่พบในฐานที่ย้าย · ไม่เปลี่ยนคิว")
    mapped=[replace(item,song_id=mapping[item.song_id]) for item in old.items]
    if mapped and new.items and new.items!=mapped:
        raise ValueError("มีคิว Online เดิมอยู่ · ไม่เขียนทับคิว")
    if mapped and not new.items:
        new._commit(mapped)
    settings["shared_favorite_song_ids"]=sorted(set(
        settings.get("shared_favorite_song_ids",[]))|set(favorites))
