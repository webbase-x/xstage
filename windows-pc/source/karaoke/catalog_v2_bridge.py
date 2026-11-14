"""Offline Windows SQLite ↔ Unified Song Catalog V2 bridge.

The existing songs.sqlite3 remains the authoritative fast local search database.
Export is read-only and atomic. Import is local-path-only, dry-run by default,
preserves the original songs and queue, and creates a SQLite backup before writes.
No Google, network, credentials or web sync imports.
"""
from __future__ import annotations

import json
import os
from contextlib import closing
import sqlite3
import tempfile
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone

from .unified_catalog_v2 import (
    CATALOG_FORMAT, CatalogValidationError, validate_catalog,
    validate_song, export_local_song, MAX_SONGS)


def _ncn_part(song_path: Path, folder: str, suffix: str):
    """Find a verified NCN LYR/CUR sibling in the selected local library."""
    options=[song_path.with_suffix(suffix)]
    parent=song_path.parent
    # Standard NCN/Songs/<bucket>/CODE.mid -> NCN/Lyrics|Cursor/<bucket>/CODE.*
    for ancestor in (parent, *parent.parents):
        if ancestor.name.casefold() == "songs":
            options.insert(0, ancestor.parent/folder/song_path.relative_to(ancestor).with_suffix(suffix))
            break
    matches=[p for p in options if p.is_file() and not p.is_symlink()]
    if not matches:
        raise CatalogValidationError("NCN missing verified "+folder+" for "+song_path.name)
    return str(matches[0].resolve())


def row_to_catalog_song(row):
    row=dict(row)
    if not row.get("format"):
        row["format"]=Path(row["path"]).suffix.lower().lstrip(".")
    fmt=str(row.get("format") or "").lower().lstrip(".")
    path=Path(str(row.get("path") or ""))
    if not path.is_absolute() or not path.is_file():
        raise CatalogValidationError("Local song file missing: "+str(path))
    if fmt=="ncn":
        if path.suffix.lower() not in (".mid",".midi"):
            raise CatalogValidationError("NCN source must be MID or MIDI")
        song={
            "id":str(row["id"]),"webSongId":str(row["id"]),
            "code":str(row.get("code") or row["id"]),
            "title":str(row.get("title") or row.get("code") or row["id"]),
            "artist":str(row.get("artist") or ""),
            "media":{"midi":{"type":"ncn","localPath":str(path.resolve()),
              "lyr":{"localPath":_ncn_part(path,"Lyrics",".lyr")},
              "cur":{"localPath":_ncn_part(path,"Cursor",".cur")}}},
            "lyrics":None
        }
        validate_song(song,cloud=False)
    else:
        song=export_local_song(row)
    if row.get("duplicate_of"):
        song["duplicateOf"]=str(row["duplicate_of"])
    # Preserve a local timed JSON sidecar when present, but do not confuse
    # untimed .LRC/.LYR files with Web's synchronized Lyrics JSON.
    timed=path.with_suffix(".json")
    if timed.is_file() and not timed.is_symlink():
        try:
            data=json.loads(timed.read_text(encoding="utf-8-sig"))
            if data.get("schemaVersion")==1 and isinstance(data.get("lines"),list):
                song["lyrics"]={"localPath":str(timed.resolve())}
        except (ValueError,UnicodeError,OSError,AttributeError):
            pass
    validate_song(song,cloud=False)
    return song


def export_catalog(db_path, destination, *, on_progress=None):
    """Atomic read-only JSON export; unsupported or missing files are reported."""
    db_path=Path(db_path).resolve()
    destination=Path(destination).resolve()
    if not db_path.is_file():
        raise FileNotFoundError("ไม่พบฐานเพลง SQLite")
    if db_path==destination or destination.suffix.lower()!=".json":
        raise CatalogValidationError("Please choose a separate .json destination")
    destination.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(db_path.as_uri()+"?mode=ro",uri=True,timeout=10)
    conn.row_factory=sqlite3.Row
    skipped=[]
    converted=0
    temp=None
    try:
        total=conn.execute("SELECT count(*) FROM songs").fetchone()[0]
        if total>MAX_SONGS:
            raise CatalogValidationError("Library exceeds maximum catalog entries")
        handle=tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",newline="\n",
                 dir=destination.parent,prefix=".xstage-v2-",suffix=".tmp",delete=False)
        temp=Path(handle.name)
        with handle:
            handle.write('{"schemaVersion":2,"format":'+json.dumps(CATALOG_FORMAT)+
                         ',"catalogScope":"local-offline","songs":[')
            cursor=conn.execute("SELECT * FROM songs ORDER BY id")
            for i,row in enumerate(cursor,1):
                try:
                    song=row_to_catalog_song(row)
                except (CatalogValidationError, ValueError, TypeError, OSError) as exc:
                    if len(skipped)<100:skipped.append({"id":row["id"],"reason":str(exc)[:220]})
                    continue
                if converted:handle.write(",")
                handle.write(json.dumps(song,ensure_ascii=False,separators=(",",":"),allow_nan=False))
                converted+=1
                if on_progress and i%250==0:on_progress(i,total)
            handle.write("]}\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp,destination)
        temp=None
        if on_progress:on_progress(total,total)
        return {"exported":converted,"scanned":total,"skipped":total-converted,
                "skippedSamples":skipped,"path":str(destination)}
    finally:
        conn.close()
        if temp is not None:
            temp.unlink(missing_ok=True)


def preview_import(db_path, catalog_path):
    """Local songs only. No Drive file IDs, no remotely scoped records."""
    catalog_path=Path(catalog_path)
    if not catalog_path.is_file() or catalog_path.stat().st_size>512*1024*1024:
        raise CatalogValidationError("Catalog missing or too large")
    doc=json.loads(catalog_path.read_text(encoding="utf-8-sig"))
    if doc.get("catalogScope")!="local-offline":
        raise CatalogValidationError("Only an offline local-path catalog can be imported into Windows PC")
    validate_catalog(doc,cloud=False)
    prepared=[]
    for song in doc["songs"]:
        media=song["media"]
        if len(media)!=1:
            raise CatalogValidationError("Choose one source format per song before PC import")
        kind,ref=next(iter(media.items()))
        if "localPath" not in ref or "fileId" in ref:
            raise CatalogValidationError("Remote file references are not allowed in Windows PC")
        path=Path(ref["localPath"])
        if not path.is_absolute() or not path.is_file():
            raise CatalogValidationError("Missing local song: "+str(path))
        if kind=="midi":
            fmt=ref["type"].upper()
            if fmt=="NCN":
                for part in ("lyr","cur"):
                    component=ref.get(part) or {}
                    if "localPath" not in component or not Path(component["localPath"]).is_file():
                        raise CatalogValidationError("Missing NCN "+part+" for "+song["code"])
        elif kind=="video":
            fmt=ref["type"].upper()
        else:
            fmt=kind.upper()
        prepared.append({
            "path":str(path.resolve()),"code":song["code"],"title":song["title"],
            "artist":song.get("artist",""),"kind":fmt,"format":fmt,
            "playable":1,"first_lyric":"","rhythm":"","key_signature":"",
            "bpm":"","source_catalog":"unified-v2-local"
        })
    return prepared


def import_catalog(db_path, catalog_path, *, confirmation=None):
    """Explicit import only. Creates a durable SQLite snapshot first."""
    prepared=preview_import(db_path,catalog_path)
    if confirmation!="IMPORT_UNIFIED_V2":
        return {"dryRun":True,"ready":len(prepared),"imported":0}
    db_path=Path(db_path).resolve()
    if not db_path.is_file():
        raise FileNotFoundError("ไม่พบฐานเพลงในเครื่อง")
    backup=db_path.with_name(db_path.stem+"-before-unified-v2-"+
          datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-"+uuid4().hex[:8]+".sqlite3")
    # sqlite3's connection context manager commits but does not CLOSE.
    # Close both handles explicitly or Windows cannot reopen/delete backups.
    with closing(sqlite3.connect(db_path,timeout=30)) as src, \
         closing(sqlite3.connect(backup,timeout=30)) as dest:
        src.backup(dest)
        if dest.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
            raise CatalogValidationError("SQLite backup integrity check failed")
    from .library import SongLibrary
    try:
        affected=SongLibrary(db_path).upsert_catalog(prepared,preserve_playable=True)
    except Exception:
        # Existing DB transactions roll back; keep the backup for recovery.
        raise
    return {"dryRun":False,"ready":len(prepared),"imported":affected,
            "backup":str(backup)}
