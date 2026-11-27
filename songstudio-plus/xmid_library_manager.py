"""Read-only Karaoke catalog audit and reversible local XMID relocation."""
from collections import Counter, defaultdict
from contextlib import closing
import json
import os
from pathlib import Path, PureWindowsPath
import sqlite3
import stat
import uuid

MAX_ROWS = 300000
FILTERS = {"all", "duplicate", "no_title", "no_artist", "missing", "unsafe", "shared_path", "unplayable"}


def stamp(path):
    s = path.stat()
    if not stat.S_ISREG(s.st_mode):
        raise ValueError("Not a regular file")
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def local_path(root, value):
    raw = str(value or "").replace(chr(92), "/")
    if not raw or ".." in raw.split("/"):
        raise ValueError("Unsafe path")
    candidate = Path(raw)
    if not candidate.is_absolute():
        if PureWindowsPath(raw).drive or raw.startswith("//"):
            raise ValueError("Unsupported absolute path")
        parts = raw.split("/")
        if parts[0].casefold() == "songs" and root.name.casefold() == "songs":
            parts = parts[1:]
        candidate = root.joinpath(*parts)
    if root not in candidate.parents:
        raise ValueError("Outside selected library")
    if any(p.is_symlink() or getattr(p, "is_junction", lambda: False)()
           for p in (candidate, *candidate.parents) if p != root and root in p.parents):
        raise ValueError("Symlink or junction")
    resolved = candidate.resolve()
    if root not in resolved.parents or resolved.suffix.casefold() != ".xmid":
        raise ValueError("Not a local XMID")
    return resolved


def scan(database, songs):
    if not str(database).strip() or not str(songs).strip():
        raise ValueError("Select songs.sqlite3 and the song folder")
    db = Path(database).expanduser().resolve(strict=True)
    root = Path(songs).expanduser().resolve(strict=True)
    if db.name.casefold() != "songs.sqlite3" or not db.is_file() or not root.is_dir():
        raise ValueError("Select existing songs.sqlite3 and song folder")
    initial = stamp(db)
    wal = Path(str(db) + "-wal")
    wal_stamp = stamp(wal) if wal.exists() else None
    with closing(sqlite3.connect(db.as_uri()+"?mode=ro", uri=True, timeout=3)) as con:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only=ON")
        con.execute("BEGIN")
        cols = {r[1] for r in con.execute("PRAGMA table_info(songs)")}
        if not {"id", "path", "code", "title", "artist"} <= cols:
            raise ValueError("Unsupported Karaoke songs schema")
        shared = "web_song_id" in cols or "payload" in cols
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        schema = "legacy-pc"
        if shared:
            schema = "legacy-shared"
            if "catalog_meta" in tables:
                meta = dict(con.execute("SELECT key,value FROM catalog_meta"))
                if (meta.get("pcSchema") != "shared-v1" or meta.get("format") != "xstage-sqlite3-v1" or
                        meta.get("schemaVersion") != "1" or meta.get("kind") != "snapshot" or
                        meta.get("pathBase") != "SONGS" or "removed_songs" not in tables or
                        not {"web_song_id","payload","original_relative_path"} <= cols):
                    raise ValueError("Unsupported shared-v1 Karaoke catalog")
                schema = "shared-v1"
        optional = [c for c in ("original_relative_path", "source_format", "format",
                    "midi_md5", "midi_size", "duplicate_of", "playable", "web_song_id",
                    "first_lyric", "rhythm", "key_signature", "bpm") if c in cols]
        result = []
        all_paths = Counter()
        for index, record in enumerate(con.execute("SELECT "+",".join(["id","path","code","title","artist"]+optional)+" FROM songs ORDER BY id")):
            if index >= MAX_ROWS:
                raise ValueError("Catalog exceeds safe scan limit")
            row = dict(record)
            # The canonical shared path works when selecting either
            # XStageKaraoke or its SONGS folder.
            source = row["path"] if schema == "shared-v1" else (row.get("original_relative_path") if shared else row["path"])
            if not source:
                source = row["path"]
            if not str(source).lower().endswith(".xmid"):
                continue
            item = {"id": int(row["id"]), "code": str(row["code"] or ""),
                    "title": str(row["title"] or ""), "artist": str(row["artist"] or ""),
                    "path": str(source), "issues": [], "stamp": None,
                    "webSongId": str(row.get("web_song_id") or ""),
                    "firstLyric": str(row.get("first_lyric") or ""),
                    "rhythm": str(row.get("rhythm") or ""),
                    "keySignature": str(row.get("key_signature") or ""),
                    "bpm": str(row.get("bpm") or "")}
            title = item["title"].strip()
            if not title or title.casefold() in {item["code"].casefold(), "unknown", "untitled", "ไม่ทราบ", "-"}:
                item["issues"].append("no_title")
            if not item["artist"].strip():
                item["issues"].append("no_artist")
            if row.get("playable") == 0:
                item["issues"].append("unplayable")
            try:
                path = local_path(root, source)
                item["path"] = str(path)
                all_paths[os.path.normcase(str(path))] += 1
                try:
                    item["stamp"] = stamp(path)
                except FileNotFoundError:
                    item["issues"].append("missing")
                except (OSError, ValueError):
                    item["issues"].append("unsafe")
            except (OSError, ValueError, RuntimeError):
                item["issues"].append("unsafe")
            item["hash"] = (row.get("midi_md5"), row.get("midi_size"))
            item["duplicate_of"] = row.get("duplicate_of")
            result.append(item)
    if stamp(db) != initial or (stamp(wal) if wal.exists() else None) != wal_stamp:
        raise ValueError("Catalog changed while scanning; scan again")
    hashes = defaultdict(list)
    for item in result:
        h, size = item["hash"]
        if isinstance(h, str) and len(h) == 32 and all(c in "0123456789abcdef" for c in h.lower()) and isinstance(size, int) and size > 0:
            hashes[(h.lower(), size)].append(item)
    for group in hashes.values():
        if len(group) > 1:
            # Keep one healthy, existing record. Never treat matching titles as identity.
            group.sort(key=lambda x: (not bool(x["stamp"]), len(x["issues"]), x["id"]))
            for item in group[1:]:
                item["issues"].append("duplicate")
    for item in result:
        if item["duplicate_of"] and "duplicate" not in item["issues"]:
            item["issues"].append("duplicate")
        if all_paths[os.path.normcase(item["path"])] > 1:
            item["issues"].append("shared_path")
        item["actionable"] = bool(item["stamp"] and item["issues"] and
            not shared and not {"unsafe", "shared_path"}.intersection(item["issues"]))
        del item["hash"], item["duplicate_of"]
    counts = Counter(issue for item in result for issue in item["issues"])
    return {"token": uuid.uuid4().hex, "database": str(db), "root": str(root),
            "revision": (initial, wal_stamp), "shared": shared, "schema": schema, "rows": result,
            "counts": dict(counts)}


def filtered(plan, category):
    if category not in FILTERS:
        raise ValueError("Unknown issue filter")
    return [r for r in plan["rows"] if r["issues"] and (category == "all" or category in r["issues"])]


def page(plan, category, offset=0):
    rows = filtered(plan, category)
    offset = max(0, int(offset))
    return {"token": plan["token"], "shared": plan["shared"], "counts": plan["counts"],
            "total": len(plan["rows"]), "matches": len(rows),
            "actionable": sum(r["actionable"] for r in rows),
            "rows": [{k:v for k,v in row.items() if k != "stamp"} for row in rows[offset:offset+100]]}


def relocate(plan, category, ids, all_selected, excluded, destination, action):
    if plan["shared"]:
        raise ValueError("Shared Online catalog: audit only; use the Karaoke publisher to update it")
    if action not in ("move", "delete"):
        raise ValueError("Unknown action")
    if not str(destination).strip():
        raise ValueError("Select an external destination / recovery folder")
    root = Path(plan["root"])
    out = Path(destination).expanduser().resolve(strict=True)
    if not out.is_dir() or out == root or root in out.parents or out in root.parents:
        raise ValueError("Select a separate, non-nested destination")
    current = scan(plan["database"], plan["root"])
    if current["revision"] != plan["revision"] or current["shared"]:
        raise ValueError("Catalog changed; scan again")
    old = {r["id"]: r for r in filtered(plan, category)}
    chosen = ({i for i, row in old.items() if row["actionable"]} - set(excluded)) if all_selected else set(ids)
    if not chosen or not chosen <= old.keys():
        raise ValueError("Invalid or empty selection")
    new = {r["id"]: r for r in filtered(current, category)}
    selected = []
    for ident in sorted(chosen):
        row = old[ident]
        if not row["actionable"] or new.get(ident) != row:
            raise ValueError("Selection is no longer safe; scan again")
        selected.append(row)
    run = out / ("XMID-recovery-" + uuid.uuid4().hex)
    run.mkdir()
    log = run / "operations.jsonl"
    moved = failed = 0
    with log.open("x", encoding="utf-8") as stream:
        for row in selected:
            src = Path(row["path"])
            dest = run / src.relative_to(root)
            entry = {"id": row["id"], "source": str(src), "destination": str(dest), "action": action}
            # Record intention before moving; no permanent deletion or overwrite.
            stream.write(json.dumps(dict(entry, status="planned"), ensure_ascii=False)+"\n")
            stream.flush()
            os.fsync(stream.fileno())
            try:
                db = Path(plan["database"])
                wal = Path(str(db) + "-wal")
                if (stamp(db), stamp(wal) if wal.exists() else None) != plan["revision"]:
                    raise ValueError("Catalog changed; scan again")
                if local_path(root, str(src)) != src or stamp(src) != tuple(row["stamp"]):
                    raise ValueError("File changed since audit")
                dest.parent.mkdir(parents=True, exist_ok=True)
                # Same filesystem only, atomic no-clobber link; if unsupported fail safely.
                os.link(src, dest)
                if local_path(root, str(src)) != src or not os.path.samefile(src, dest) or stamp(src)[:4] != tuple(row["stamp"])[:4]:
                    raise ValueError("Destination identity mismatch")
                src.unlink()
                moved += 1
                entry["status"] = "moved"
            except (OSError, ValueError) as exc:
                failed += 1
                entry.update(status="failed", error=str(exc))
            stream.write(json.dumps(entry, ensure_ascii=False)+"\n")
            stream.flush()
    return {"moved": moved, "failed": failed, "log": str(log), "database_unchanged": True}
