"""X-Stage Song Studio Plus: SQLite-first catalog and binary embedded-media output.

No external dependencies. The original song media is immutable; every mutable
lyric revision is an independent SQLite version.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
import re
import shutil
import sqlite3
import struct
import tempfile
import threading
import unicodedata
import uuid
from collections import defaultdict
from contextlib import contextmanager
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path

import ncn_reader

MEDIA_EXT = {".mid", ".midi", ".kar", ".mp3", ".m4a", ".wav", ".flac",
             ".mp4", ".mkv", ".webm", ".mov"}
MIDI_EXT = {".mid", ".midi", ".kar"}
MAGIC = b"XSTGPLS1"
FORMAT_VERSION = 1
HEADER = struct.Struct("<8sIQQ32s32s")
SIZE_LIMIT = 2 * 1024 * 1024 * 1024 * 1024
WRITE_LOCK = threading.RLock()
_INIT_LOCK = threading.RLock()
_INITIALIZED = set()

def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")

def norm(value):
    return unicodedata.normalize("NFC", str(value).strip()).casefold()

def digest(path, chunk=1024*1024):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(chunk), b""):
            h.update(block)
    return h.hexdigest()

def binary_digest(*payloads):
    h = hashlib.sha256()
    for payload in payloads:
        h.update(struct.pack("<Q", len(payload)))
        h.update(payload)
    return h.hexdigest()

def clean_path(path):
    p = Path(path).expanduser().resolve(strict=True)
    if not p.is_dir():
        raise ValueError("กรุณาเลือกโฟลเดอร์เพลงที่มีอยู่จริง")
    return p

def root_folder(workspace):
    p = Path(workspace).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p

def db_path(workspace):
    return root_folder(workspace) / "DB" / "xstage_plus.sqlite3"

@contextmanager
def connect(workspace):
    path = db_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    # WAL is configured once by init(). Do not renegotiate journal mode on
    # every UI read while the importer is writing; that can wait on locks and
    # make unrelated buttons appear frozen.
    c = sqlite3.connect(path, timeout=5)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA busy_timeout=5000")
    try:
        with c:
            yield c
    finally:
        c.close()

SCHEMA = """
CREATE TABLE IF NOT EXISTS xstage_migrations(
 key TEXT PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS xstage_media(
 id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, extension TEXT NOT NULL,
 bytes INTEGER NOT NULL, stored_path TEXT NOT NULL, first_filename TEXT NOT NULL,
 created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS xstage_media_sources(
 source_path TEXT PRIMARY KEY, media_id TEXT NOT NULL REFERENCES xstage_media(id),
 bytes INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
 verified_sha256 TEXT NOT NULL, last_seen TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS xstage_media_source_lookup
 ON xstage_media_sources(media_id,last_seen);
CREATE TABLE IF NOT EXISTS xstage_songs(
 id TEXT PRIMARY KEY, code INTEGER NOT NULL UNIQUE, media_id TEXT NOT NULL UNIQUE
 REFERENCES xstage_media(id), title TEXT NOT NULL, artist TEXT NOT NULL,
 original_code TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS xstage_import_batches(
 id TEXT PRIMARY KEY, source_root TEXT NOT NULL, created_at TEXT NOT NULL,
 completed_at TEXT, files_seen INTEGER NOT NULL DEFAULT 0,
 files_new INTEGER NOT NULL DEFAULT 0,
 media_duplicates INTEGER NOT NULL DEFAULT 0,
 lyrics_new INTEGER NOT NULL DEFAULT 0,
 failures INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS xstage_import_items(
 id INTEGER PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES xstage_import_batches(id),
 source_path TEXT NOT NULL, source_name TEXT NOT NULL, media_sha256 TEXT,
 song_id TEXT REFERENCES xstage_songs(id), outcome TEXT NOT NULL, message TEXT,
 created_at TEXT NOT NULL, UNIQUE(batch_id,source_path));
CREATE TABLE IF NOT EXISTS xstage_import_resume_state(
 batch_id TEXT PRIMARY KEY REFERENCES xstage_import_batches(id),
 source_root TEXT NOT NULL, counters_json TEXT NOT NULL,
 status TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS xstage_import_resume_root
 ON xstage_import_resume_state(source_root,status,updated_at);
CREATE TABLE IF NOT EXISTS xstage_import_file_checkpoints(
 batch_id TEXT NOT NULL REFERENCES xstage_import_batches(id),
 source_path TEXT NOT NULL, bytes INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
 companion_stamp TEXT NOT NULL, outcome TEXT NOT NULL,
 counters_delta TEXT NOT NULL, PRIMARY KEY(batch_id,source_path));
CREATE TABLE IF NOT EXISTS xstage_lyric_scan_cache(
 source_path TEXT PRIMARY KEY, media_sha256 TEXT NOT NULL,
 companion_stamp TEXT NOT NULL, outcome TEXT NOT NULL,
 last_scanned TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS xstage_lyric_drafts(
 song_id TEXT PRIMARY KEY REFERENCES xstage_songs(id),
 source_path TEXT NOT NULL, title TEXT NOT NULL, artist TEXT NOT NULL,
 raw_text TEXT NOT NULL, reason TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS xstage_lyric_versions(
 id TEXT PRIMARY KEY, song_id TEXT NOT NULL REFERENCES xstage_songs(id),
 content_sha256 TEXT NOT NULL, source_sha256 TEXT, origin TEXT NOT NULL,
 timing_status TEXT NOT NULL, title TEXT NOT NULL, artist TEXT NOT NULL,
 created_at TEXT NOT NULL, is_current INTEGER NOT NULL DEFAULT 0,
 UNIQUE(song_id,content_sha256));
CREATE UNIQUE INDEX IF NOT EXISTS xstage_current_lyric
 ON xstage_lyric_versions(song_id) WHERE is_current=1;
CREATE TABLE IF NOT EXISTS xstage_lyric_lines(
 id INTEGER PRIMARY KEY, version_id TEXT NOT NULL REFERENCES xstage_lyric_versions(id),
 position INTEGER NOT NULL, text TEXT NOT NULL, normalized_text TEXT NOT NULL,
 start_time REAL NOT NULL, end_time REAL NOT NULL,
 timing_status TEXT NOT NULL, UNIQUE(version_id,position));
CREATE INDEX IF NOT EXISTS xstage_lyric_search
 ON xstage_lyric_lines(normalized_text,version_id);
CREATE TABLE IF NOT EXISTS xstage_lyric_cues(
 id INTEGER PRIMARY KEY, line_id INTEGER NOT NULL REFERENCES xstage_lyric_lines(id),
 position INTEGER NOT NULL, text TEXT NOT NULL, start_time REAL NOT NULL,
 duration REAL NOT NULL, UNIQUE(line_id,position));
CREATE TABLE IF NOT EXISTS xstage_edit_batches(
 id TEXT PRIMARY KEY, created_at TEXT NOT NULL, search TEXT NOT NULL,
 replacement TEXT NOT NULL, changed_lines INTEGER NOT NULL,
 status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS xstage_edit_changes(
 id INTEGER PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES xstage_edit_batches(id),
 song_id TEXT NOT NULL REFERENCES xstage_songs(id),
 before_version TEXT NOT NULL REFERENCES xstage_lyric_versions(id),
 after_version TEXT NOT NULL REFERENCES xstage_lyric_versions(id));
CREATE TABLE IF NOT EXISTS xstage_exports(
 song_id TEXT PRIMARY KEY REFERENCES xstage_songs(id), version_id TEXT NOT NULL
 REFERENCES xstage_lyric_versions(id), output_path TEXT NOT NULL,
 sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
"""
def _quality(status):
    # Complete, independently timed lyrics outrank incomplete CUR fragments.
    return {"incomplete":0,"estimated":1,"original":2,
            "preserved":3,"verified":4}.get(status,0)

def _line_total(db,version_id):
    return db.execute(
        "SELECT COUNT(*) FROM xstage_lyric_lines WHERE version_id=?",
        (version_id,)).fetchone()[0]

def _prefer_version(db,song_id,version_id):
    """Promote improved evidence, never replace a user's edited lyric version."""
    candidate=db.execute(
        "SELECT id,origin,timing_status FROM xstage_lyric_versions WHERE id=? AND song_id=?",
        (version_id,song_id)).fetchone()
    if candidate is None:
        raise ValueError("ไม่พบ Lyrics Version ที่ต้องประเมิน")
    current=db.execute("""SELECT id,origin,timing_status FROM xstage_lyric_versions
                         WHERE song_id=? AND is_current=1""",(song_id,)).fetchone()
    if current and current["id"]==candidate["id"]:
        return True
    if current and (current["origin"] in ("edit","manual") or
                    current["timing_status"]=="verified"):
        return False
    new_rank=_quality(candidate["timing_status"])
    old_rank=_quality(current["timing_status"]) if current else -1
    if new_rank<old_rank:
        return False
    if new_rank==old_rank and current:
        # Do not reorder equally sound versions on each reimport unless
        # the new one covers *more* lyric lines.
        if _line_total(db,candidate["id"])<=_line_total(db,current["id"]):
            return False
    db.execute("UPDATE xstage_lyric_versions SET is_current=0 WHERE song_id=?",
               (song_id,))
    db.execute("UPDATE xstage_lyric_versions SET is_current=1 WHERE id=?",
               (candidate["id"],))
    return True

def _repair_historical_lyrics(db):
    """One-time non-destructive repair of older incorrect current pointers."""
    if db.execute("SELECT 1 FROM xstage_migrations WHERE key=?",
                  ("plus-lyrics-quality-v1",)).fetchone():
        return
    # Repair only the cases known to be wrong, not manually edited songs.
    affected=db.execute("""
        SELECT DISTINCT v.song_id FROM xstage_lyric_versions v
        WHERE NOT EXISTS (
          SELECT 1 FROM xstage_lyric_versions c
          WHERE c.song_id=v.song_id AND c.is_current=1)
        OR (EXISTS (
          SELECT 1 FROM xstage_lyric_versions c
          WHERE c.song_id=v.song_id AND c.is_current=1
            AND c.timing_status='incomplete' AND c.origin!='edit')
          AND EXISTS (
          SELECT 1 FROM xstage_lyric_versions complete
          WHERE complete.song_id=v.song_id
            AND complete.timing_status!='incomplete'))
    """).fetchall()
    for (song_id,) in affected:
        rows=db.execute("""SELECT id,timing_status FROM xstage_lyric_versions
                           WHERE song_id=?""",(song_id,)).fetchall()
        if not rows:
            continue
        best=max(rows,key=lambda v:(_quality(v["timing_status"]),
                                     _line_total(db,v["id"])))
        _prefer_version(db,song_id,best["id"])
    db.execute("INSERT INTO xstage_migrations(key,applied_at) VALUES (?,?)",
               ("plus-lyrics-quality-v1",now()))

def init(workspace):
    path=db_path(workspace).resolve()
    key=str(path)
    first_time=key not in _INITIALIZED
    if first_time:
        with _INIT_LOCK:
            if key not in _INITIALIZED:
                path.parent.mkdir(parents=True,exist_ok=True)
                # Configure WAL exactly once per process/workspace before normal
                # request traffic starts. Afterwards read connections never issue
                # PRAGMA journal_mode while the import writer is active.
                db=sqlite3.connect(path,timeout=10)
                try:
                    db.row_factory=sqlite3.Row
                    db.execute("PRAGMA foreign_keys=ON")
                    db.execute("PRAGMA busy_timeout=10000")
                    db.execute("PRAGMA journal_mode=WAL")
                    db.execute("PRAGMA synchronous=NORMAL")
                    with db:
                        db.executescript(SCHEMA)
                        _repair_historical_lyrics(db)
                finally:
                    db.close()
                _INITIALIZED.add(key)
                return path
    # Keep migration repair observable after initialization. This is normally
    # a single marker SELECT and does not renegotiate WAL. It also repairs an
    # older incomplete current lyric pointer if the migration marker is absent.
    with connect(workspace) as db:
        _repair_historical_lyrics(db)
    return path

def source_for_build(workspace, db, media):
    """Resolve a verified source without copying it on import.

    Legacy Plus entries retain a SOURCE/... path. New Plus entries reference
    one or more absolute source paths registered under xstage_media_sources.
    If a USB is unplugged, stop safely and ask for the source again.
    """
    entries=db.execute("""SELECT source_path,bytes,mtime_ns FROM xstage_media_sources
          WHERE media_id=? ORDER BY last_seen DESC""",(media["id"],)).fetchall()
    changed=False
    for entry in entries:
        candidate=Path(entry["source_path"])
        try:
            stat=candidate.stat()
            if candidate.is_file():
                if (stat.st_size==media["bytes"] and
                        stat.st_mtime_ns==entry["mtime_ns"]):
                    return candidate
                changed=True
        except OSError:
            pass
    if changed:
        raise ValueError("ไฟล์ต้นฉบับเปลี่ยนหลังลงทะเบียน · กรุณานำเข้าเพลงนั้นอีกครั้งก่อนสร้าง XMID")
    stored=media["stored_path"]
    if stored:
        legacy=Path(workspace)/stored
        if legacy.is_file():
            return legacy
    raise ValueError("ไม่พบไฟล์เพลงต้นฉบับ กรุณาเชื่อมต่อ USB/HDD หรือเพิ่มแหล่งเพลงใหม่ก่อนส่งออก")


@lru_cache(maxsize=4096)
def _sidecar_folders_for_stamp(root_text,mtime_ns):
    """Cache collection directory layout, never the existence of lyric files."""
    root=Path(root_text)
    names={
        ".lyr":("Lyrics","Lyric","Lyr","Texts"),
        ".cur":("Cursor","Cursors","Cur","Timing"),
        ".lrc":("Lyrics","Lyric","LRC","TimedLyrics"),
    }
    result={}
    for ext,aliases in names.items():
        folders=[]
        for alias in aliases:
            for name in (alias,alias.lower(),alias.upper()):
                folder=root/name
                if folder.is_dir() and folder not in folders:
                    folders.append(folder)
        result[ext]=tuple(folders)
    return result

def _sidecar_folders(root):
    try:
        return _sidecar_folders_for_stamp(str(root),root.stat().st_mtime_ns)
    except OSError:
        return {}

def companion_candidates(media):
    """Exact-code sidecar matching: no backup, hashing or recursive per-song scan.

    Directory layouts are cached by root revision so 100k MIDI files do not
    require repeated probes of nonexistent Lyrics/CUR folder aliases.
    Supports flat, bucketed and sibling NCN trees and sidecar LRC for media.
    """
    p=Path(media)
    result={".lyr":None,".cur":None,".lrc":None}
    def probe(folder,ext):
        for suffix in (ext,ext.upper()):
            candidate=folder/(p.stem+suffix)
            if candidate.is_file() and not candidate.is_symlink():
                return candidate
        return None
    eligible=(".lyr",".cur",".lrc") if p.suffix.lower() in MIDI_EXT else (".lrc",)
    for ext in eligible:
        result[ext]=probe(p.parent,ext)
    if all(result[e] for e in eligible):
        return result
    roots=[]
    seen=set()
    def add(root,subdir):
        key=(str(root).casefold(),str(subdir).casefold())
        if key not in seen:
            roots.append((root,subdir))
            seen.add(key)
    if p.suffix.lower() in MIDI_EXT:
        found=ncn_reader.describe(p)
        if found and found[1]=="song":
            add(found[0],found[2])
    for ancestor in p.parents:
        if ancestor.name.casefold() in (
                "song","songs","mid","midi","music","audio","video","vdo"):
            add(ancestor.parent,p.parent.relative_to(ancestor))
            break
    ancestor=p.parent
    for _ in range(4):
        add(ancestor,p.parent.relative_to(ancestor))
        if ancestor.parent==ancestor:
            break
        ancestor=ancestor.parent
    for root,subdir in roots:
        directories=_sidecar_folders(root)
        for ext in eligible:
            if result[ext]:
                continue
            for folder in directories.get(ext,()):
                found=probe(folder/subdir,ext)
                if found:
                    result[ext]=found
                    break
        if all(result[e] for e in eligible):
            break
    return result

def is_ncn_media(path,companions=None):
    """NCN MID requires its matched LYR+CUR triplet; KAR/audio remain independent."""
    p=Path(path)
    if p.suffix.lower() not in (".mid",".midi"):
        return False
    if any(part.casefold()=="ncn" for part in p.parts):
        return True
    found=ncn_reader.describe(p)
    if found and found[1]=="song":
        return True
    if any(ancestor.name.casefold() in ("song","songs") for ancestor in p.parents):
        return True
    comps=companions or {}
    return bool(comps.get(".lyr") or comps.get(".cur"))


def ncn_missing_companions(companions):
    """Missing and empty companions cannot form a complete NCN triplet."""
    result=[]
    for ext in (".lyr",".cur"):
        file=companions.get(ext)
        if file is None:
            result.append(ext[1:].upper())
        else:
            try:
                if Path(file).stat().st_size==0:
                    result.append(ext[1:].upper()+" (ว่าง)")
            except OSError:
                result.append(ext[1:].upper())
    return result


def parse_lrc(path):
    import re
    lines=[]
    raw=Path(path).read_text(encoding="utf-8-sig")
    expr=re.compile(r"^\[(\d{1,3}):([0-5]\d)(?:[.:](\d{1,3}))?\](.*)$")
    for entry in raw.splitlines():
        m=expr.match(entry)
        if not m: continue
        fraction=(m.group(3) or "0").ljust(3,"0")[:3]
        start=int(m.group(1))*60+int(m.group(2))+int(fraction)/1000
        text=m.group(4).strip()
        if text: lines.append({"text":text,"startTime":start,"syllables":[]})
    if not lines:
        raise ValueError("LRC ไม่มีบรรทัดเนื้อร้องพร้อมเวลาที่รองรับ")
    for i,line in enumerate(lines):
        end=lines[i+1]["startTime"] if i+1<len(lines) else line["startTime"]+4
        if end<=line["startTime"]:
            raise ValueError("เวลา LRC ย้อนกลับหรือทับซ้อนกัน")
        line["endTime"]=end
        if i+1==len(lines):
            line["endTimeEstimated"]=True
    return {"lines":lines, "metadata":{"timingComplete":True},
            "sourceFormat":"LRC"}

def document_for(path, companions):
    """Prefer measured NCN CUR, recover via timed LRC or embedded KAR.

    A damaged CUR should not block a valid LRC or embedded MIDI lyric track.
    A partial NCN remains available when no complete timed alternative exists.
    Never infer original CUR timestamps from audio notes.
    """
    p=Path(path)
    is_midi=p.suffix.lower() in MIDI_EXT
    partial=None
    original_error=None
    if is_midi and companions.get(".lyr") and companions.get(".cur"):
        try:
            document=ncn_reader.ncn_document({
                "midi":str(p),"lyrics":str(companions[".lyr"]),
                "cursor":str(companions[".cur"]),
                "missing":[],"code":p.stem})
            if (document.get("metadata") or {}).get("timingComplete",True):
                return document
            partial=document
        except (ValueError,OSError) as exc:
            original_error=exc
    if companions.get(".lrc"):
        try:
            return parse_lrc(companions[".lrc"])
        except (ValueError,OSError,UnicodeError) as exc:
            if original_error is None:
                original_error=exc
    if is_midi:
        try:
            return ncn_reader.kar_document(p,p.stem)
        except (ValueError,OSError):
            pass
    if partial:
        return partial
    if original_error is not None:
        raise ValueError(str(original_error))
    return None

def valid_lines(doc):
    # A short historical CUR may still contain dozens of verified lines.
    # Preserve them as an INCOMPLETE version, never as ready for export.
    if not doc or not doc.get("lines"):
        return None
    result=[]
    for line in doc["lines"]:
        text=str(line["text"])
        start=float(line["startTime"])
        end=float(line["endTime"])
        if not 0<=start<end or not text.strip():
            raise ValueError("พบข้อความหรือช่วงเวลาบรรทัดไม่ถูกต้อง")
        cues=[]
        for cue in line.get("syllables",[]):
            at=float(cue["start"])
            duration=float(cue["duration"])
            if not start-.001<=at<=end+.001 or duration<0:
                raise ValueError("เวลาปาดสีอยู่นอกช่วงของบรรทัด")
            cues.append((str(cue["text"]),at,duration))
        if any(cues[i][1]>cues[i+1][1] for i in range(len(cues)-1)):
            raise ValueError("เวลาปาดสีเรียงย้อนหลัง")
        original_cues=bool(cues)
        if not cues:
            # A plain timed LRC has line boundaries but not measured
            # syllable cues. Interpolate a visible sweep, explicitly marked
            # as ESTIMATED; never pass it off as measured from audio or CUR.
            units=glyphs(text)
            positions=[start+(end-start)*i/len(units) for i in range(len(units))]
            cues=[(glyph,round(at,6),
                   round((positions[i+1] if i+1<len(positions) else end)-at,6))
                  for i,(glyph,at) in enumerate(zip(units,positions))]
        status="original" if original_cues and not line.get("endTimeEstimated") else "estimated"
        result.append((text,start,end,cues,status))
    return result

def content_sha(lines):
    canonical=json.dumps(lines,ensure_ascii=False,separators=(",",":"),sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

def insert_version(db,song,media,doc,source_signature,origin="NCN"):
    lines=valid_lines(doc)
    if not lines:
        return (None,False)
    signature=content_sha(lines)
    meta=doc.get("metadata") or {}
    status=("incomplete" if meta.get("timingComplete",True) is False else
            "original" if all(l[4]=="original" for l in lines) else "estimated")
    prior=db.execute("""SELECT id,timing_status FROM xstage_lyric_versions
                        WHERE song_id=? AND content_sha256=?""",
                     (song["id"],signature)).fetchone()
    if prior:
        # A later, fully verified CUR can close an earlier partial import
        # without unnecessarily creating a second content-identical version.
        if _quality(status)>_quality(prior["timing_status"]):
            db.execute("""UPDATE xstage_lyric_versions SET timing_status=?
                          WHERE id=?""",(status,prior["id"]))
        _prefer_version(db,song["id"],prior["id"])
        return prior["id"],False
    version=uuid.uuid4().hex
    title=str(meta.get("title") or song["title"]).strip()[:255]
    artist=str(meta.get("artist") or song["artist"]).strip()[:255]
    db.execute("""INSERT INTO xstage_lyric_versions
      (id,song_id,content_sha256,source_sha256,origin,timing_status,title,artist,created_at,is_current)
      VALUES (?,?,?,?,?,?,?,?,?,0)""",
      (version,song["id"],signature,source_signature,origin,status,title,artist,now()))
    for index,(text,start,end,cues,line_status) in enumerate(lines):
        cur=db.execute("""INSERT INTO xstage_lyric_lines
            (version_id,position,text,normalized_text,start_time,end_time,timing_status)
            VALUES (?,?,?,?,?,?,?)""",
            (version,index,text,norm(text),start,end,line_status))
        for ci,(glyph,at,duration) in enumerate(cues):
            db.execute("""INSERT INTO xstage_lyric_cues
             (line_id,position,text,start_time,duration) VALUES (?,?,?,?,?)""",
             (cur.lastrowid,ci,glyph,at,duration))
    _prefer_version(db,song["id"],version)
    return version,True

def companion_stamp(companions):
    """Sidecar identity via path/size/mtime, WITHOUT any content SHA-256.

    The real lyric identity is checked after parsing against its version.
    An unchanged source can skip re-parsing on later imports; timestamp and
    size updates cause re-validation.
    """
    parts=[]
    for ext in (".lyr",".cur",".lrc"):
        item=companions.get(ext)
        if item:
            stat=Path(item).stat()
            parts.append((ext,str(Path(item).resolve()),stat.st_size,stat.st_mtime_ns))
    return json.dumps(parts,ensure_ascii=False,separators=(",",":"))

def save_draft(db,song,lyr_path,reason):
    """Preserve human-readable LYR text even when CUR/MIDI timing is absent.

    Drafts are NOT counted as timed karaoke-ready lyrics and cannot be built.
    """
    raw=Path(lyr_path).read_bytes()
    if len(raw)>1024*1024:
        raise ValueError("ไฟล์ .LYR ใหญ่เกิน 1 MB")
    raw=raw.split(b"\x1a",1)[0]
    rows=raw.replace(b"\r\n",b"\n").replace(b"\r",b"\n").split(b"\n")
    if len(rows)<5:
        raise ValueError("ไฟล์ .LYR ไม่มีหัวข้อมูลและเนื้อร้องครบตามโครงสร้าง NCN")
    # Reuse the same CP874/UTF-8 fallback as the NCN timed parser.
    title=ncn_reader._decode_text(rows[0]).strip()[:255]
    artist=ncn_reader._decode_text(rows[1]).strip()[:255]
    body=ncn_reader._decode_text(b"\n".join(rows[4:])).strip()
    if not body:
        raise ValueError("ไฟล์ .LYR ไม่มีเนื้อร้องให้บันทึก")
    db.execute("""INSERT INTO xstage_lyric_drafts
          (song_id,source_path,title,artist,raw_text,reason,updated_at)
          VALUES (?,?,?,?,?,?,?)
          ON CONFLICT(song_id) DO UPDATE SET
          source_path=excluded.source_path,title=excluded.title,
          artist=excluded.artist,raw_text=excluded.raw_text,
          reason=excluded.reason,updated_at=excluded.updated_at""",
          (song["id"],str(Path(lyr_path).resolve()),title,artist,body,reason,now()))
    if song["title"]==song["original_code"] and title:
        db.execute("UPDATE xstage_songs SET title=?,artist=? WHERE id=?",
                   (title,artist,song["id"]))


def iter_source(root):
    for base,dirs,files in os.walk(root):
        dirs[:]=sorted(x for x in dirs if not (Path(base)/x).is_symlink())
        for name in sorted(files):
            p=Path(base)/name
            if p.suffix.lower() in MEDIA_EXT and not p.is_symlink() and p.is_file():
                yield p

def prepare_import_for_restart(workspace,batch_id):
    """Mark an intentionally paused import resumable by the next Pro process.

    Used only after the previous import worker has stopped and its SQLite
    transaction and checkpoint have committed. User-initiated cancel by itself
    stays cancelled, not auto-resumed.
    """
    if not batch_id:
        return False
    with WRITE_LOCK,connect(workspace) as db:
        cur=db.execute("""UPDATE xstage_import_resume_state
            SET status='interrupted',updated_at=?
            WHERE batch_id=? AND status='cancelled'""",(now(),batch_id))
        if cur.rowcount:
            db.execute("""UPDATE xstage_import_batches SET status='interrupted'
                WHERE id=? AND status='cancelled'""",(batch_id,))
        return bool(cur.rowcount)


def interrupted_import(workspace):
    """Latest recoverable import. A previous crash cannot leave 'running' forever."""
    with connect(workspace) as db:
        db.execute("""UPDATE xstage_import_resume_state SET status='interrupted',
          updated_at=? WHERE status='running'""",(now(),))
        db.execute("""UPDATE xstage_import_batches SET status='interrupted'
          WHERE id IN (SELECT batch_id FROM xstage_import_resume_state
          WHERE status='interrupted') AND status='running'""")
        row=db.execute("""SELECT r.batch_id,r.source_root,r.status,r.counters_json,
            r.updated_at FROM xstage_import_resume_state r
            WHERE r.status IN ('interrupted','cancelled')
            ORDER BY r.updated_at DESC LIMIT 1""").fetchone()
        return dict(row) if row else None


def import_folder(workspace,source,progress=None,cancel=None):
    """Incremental import: hash and index original media, NEVER copy it.

    Reuses one SQLite connection and commits in batches, not one full
    journal-mode negotiation and several connections per song. Every file
    has its own SAVEPOINT, so a corrupt LYR/CUR cannot poison the batch.
    """
    root=clean_path(source)
    target=root_folder(workspace)
    if root==target or target in root.parents or root in target.parents:
        raise ValueError("ต้นทางและคลัง Plus ต้องไม่อยู่ภายในกัน เพื่อป้องกันสแกนไฟล์วนซ้ำ")
    init(target)
    totals={"files_seen":0,"files_new":0,"media_duplicates":0,
            "lyrics_new":0,"partial_lyrics":0,"draft_lyrics":0,
            "skipped_ncn":0,"failures":0,"hash_cache_hits":0,"bytes_hashed":0}
    with WRITE_LOCK,connect(target) as db:
        prior=db.execute("""SELECT * FROM xstage_import_resume_state
            WHERE source_root=? AND status IN ('interrupted','cancelled','running')
            ORDER BY updated_at DESC LIMIT 1""",(str(root),)).fetchone()
        resumed=prior is not None
        if resumed:
            batch=prior["batch_id"]
            totals.update(json.loads(prior["counters_json"]))
            db.execute("""UPDATE xstage_import_resume_state
                SET status='running',updated_at=? WHERE batch_id=?""",(now(),batch))
            db.execute("""UPDATE xstage_import_batches SET status='running'
                WHERE id=?""",(batch,))
        else:
            batch=uuid.uuid4().hex
            db.execute("""INSERT INTO xstage_import_batches
                (id,source_root,created_at,status) VALUES (?,?,?,'running')""",
                (batch,str(root),now()))
            db.execute("""INSERT INTO xstage_import_resume_state
                (batch_id,source_root,counters_json,status,updated_at)
                VALUES (?,?,?,'running',?)""",
                (batch,str(root),json.dumps(totals),now()))
        db.commit()
        def store_resume(status):
            db.execute("""UPDATE xstage_import_resume_state SET
                counters_json=?,status=?,updated_at=? WHERE batch_id=?""",
                (json.dumps(totals,separators=(",",":")),status,now(),batch))
            db.execute("""UPDATE xstage_import_batches SET
                files_seen=?,files_new=?,media_duplicates=?,lyrics_new=?,
                failures=?,status=?,completed_at=? WHERE id=?""",
                (totals["files_seen"],totals["files_new"],
                 totals["media_duplicates"],totals["lyrics_new"],
                 totals["failures"],status,now() if status!="running" else None,batch))
            db.commit()
        def checkpoint(path,original_path,stat,stamp,outcome,before_totals):
            if stat is None:
                stat=path.stat() if path.exists() else None
            if stat is None:
                return
            delta={key:totals[key]-before_totals.get(key,0)
                   for key in totals if totals[key]!=before_totals.get(key,0)}
            db.execute("""INSERT INTO xstage_import_file_checkpoints
                (batch_id,source_path,bytes,mtime_ns,companion_stamp,
                 outcome,counters_delta) VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(batch_id,source_path) DO UPDATE SET
                bytes=excluded.bytes,mtime_ns=excluded.mtime_ns,
                companion_stamp=excluded.companion_stamp,outcome=excluded.outcome,
                counters_delta=excluded.counters_delta""",
                (batch,original_path,stat.st_size,stat.st_mtime_ns,
                 stamp,outcome,json.dumps(delta,separators=(",",":"))))
        last_progress=0.0
        resumed_count=0
        for path in iter_source(root):
            if cancel and cancel.is_set():
                break
            original_path=str(path.resolve())
            # Resume is a metadata checkpoint, never a blind skip by filename.
            # Changing the media file or any accompanying LYR/CUR/LRC re-opens it.
            try:
                source_stat=path.stat()
                comps=companion_candidates(path)
                stamp=companion_stamp(comps)
            except OSError:
                source_stat=None
                comps={".lyr":None,".cur":None,".lrc":None}
                stamp=""
            previous=db.execute("""SELECT * FROM xstage_import_file_checkpoints
                WHERE batch_id=? AND source_path=?""",(batch,original_path)).fetchone()
            if previous is not None and source_stat is not None and (
                  previous["bytes"]==source_stat.st_size and
                  previous["mtime_ns"]==source_stat.st_mtime_ns and
                  previous["companion_stamp"]==stamp and
                  previous["outcome"] not in ("error","lyrics-error")):
                resumed_count+=1
                if progress and time.monotonic()-last_progress>.25:
                    progress({**totals,"resumed_files":resumed_count,"resume":resumed},
                             "ทำต่อ · ข้ามไฟล์ที่บันทึกครบแล้ว "+path.name)
                    last_progress=time.monotonic()
                continue
            if previous is not None:
                for field,value in json.loads(previous["counters_delta"]).items():
                    totals[field]=max(0,totals[field]-value)
                db.execute("""DELETE FROM xstage_import_file_checkpoints
                    WHERE batch_id=? AND source_path=?""",(batch,original_path))
            previous_totals=totals.copy()
            totals["files_seen"]+=1
            outcome="error"
            message=""
            song_id=None
            h=None
            savepoint=False
            try:
                # Validate NCN triplet before hashing; skip unpaired tracks
                # and preserve any existing SQLite entries untouched.
                if is_ncn_media(path,comps):
                    missing=ncn_missing_companions(comps)
                    if missing:
                        totals["skipped_ncn"]+=1
                        outcome="skipped-ncn-incomplete"
                        message="ข้าม NCN: "+", ".join(missing)+" ไม่มีหรือว่าง"
                        db.execute("""INSERT OR REPLACE INTO xstage_import_items
                         (batch_id,source_path,source_name,media_sha256,song_id,
                          outcome,message,created_at)
                         VALUES (?,?,?,?,?,?,?,?)""",
                         (batch,original_path,path.name,None,None,outcome,message,now()))
                        checkpoint(path,original_path,source_stat,stamp,
                                   "skipped-ncn-incomplete",previous_totals)
                        if totals["files_seen"]%16==0: store_resume("running")
                        if progress and time.monotonic()-last_progress>.25:
                            progress({**totals,"resumed_files":resumed_count,"resume":resumed},
                                     path.name)
                            last_progress=time.monotonic()
                        continue
                before=source_stat or path.stat()
                if not 0<=before.st_size<SIZE_LIMIT:
                    raise ValueError("ขนาดไฟล์ไม่อยู่ในช่วงที่รองรับ")
                cached=db.execute("""SELECT verified_sha256 FROM xstage_media_sources
                    WHERE source_path=? AND bytes=? AND mtime_ns=?""",
                    (original_path,before.st_size,before.st_mtime_ns)).fetchone()
                if cached:
                    h=cached["verified_sha256"]
                    totals["hash_cache_hits"]+=1
                else:
                    h=digest(path)
                    totals["bytes_hashed"]+=before.st_size
                after=path.stat()
                if (after.st_size,after.st_mtime_ns)!=(before.st_size,before.st_mtime_ns):
                    raise ValueError("ไฟล์เพลงต้นฉบับเปลี่ยนระหว่างตรวจ SHA-256")
                # Companions were checked first so incomplete NCN source sets
                # never trigger an expensive media SHA-256 or registration.
                db.execute("SAVEPOINT plus_media_item")
                savepoint=True
                media=db.execute("SELECT * FROM xstage_media WHERE sha256=?",(h,)).fetchone()
                if media:
                    totals["media_duplicates"]+=1
                    outcome="media-duplicate"
                    song=db.execute("SELECT * FROM xstage_songs WHERE media_id=?",(media["id"],)).fetchone()
                else:
                    media_id=uuid.uuid4().hex
                    # Empty stored_path means zero import-time copying. Prior
                    # previews with SOURCE/... continue to work unchanged.
                    db.execute("""INSERT INTO xstage_media
                      (id,sha256,extension,bytes,stored_path,first_filename,created_at)
                      VALUES (?,?,?,?,?,?,?)""",
                      (media_id,h,path.suffix.lower(),before.st_size,"",path.name,now()))
                    song_id=uuid.uuid4().hex
                    seq=db.execute("SELECT COALESCE(MAX(code),0)+1 FROM xstage_songs").fetchone()[0]
                    db.execute("""INSERT INTO xstage_songs
                     (id,code,media_id,title,artist,original_code,created_at)
                     VALUES (?,?,?,?,?,?,?)""",
                     (song_id,seq,media_id,path.stem,"",path.stem,now()))
                    totals["files_new"]+=1
                    song=db.execute("SELECT * FROM xstage_songs WHERE id=?",(song_id,)).fetchone()
                    media=db.execute("SELECT * FROM xstage_media WHERE id=?",(media_id,)).fetchone()
                    outcome="new-media"
                if not song:
                    raise ValueError("ทะเบียนเพลงที่ตรงกับสื่อนี้ไม่สมบูรณ์")
                song_id=song["id"]
                # The same path may be reused for a different song after
                # replacement: keep the latest verified media relationship.
                # A verified unchanged source must not be rewritten on every
                # rescan. This avoids a full SQLite index/WAL update for each
                # of hundreds of thousands of already-indexed media files.
                if not cached:
                    db.execute("""INSERT INTO xstage_media_sources
                        (source_path,media_id,bytes,mtime_ns,verified_sha256,last_seen)
                        VALUES (?,?,?,?,?,?)
                        ON CONFLICT(source_path) DO UPDATE SET
                        media_id=excluded.media_id,bytes=excluded.bytes,
                        mtime_ns=excluded.mtime_ns,
                        verified_sha256=excluded.verified_sha256,
                        last_seen=excluded.last_seen""",
                        (original_path,media["id"],before.st_size,before.st_mtime_ns,h,now()))
                # Never SHA-256 the .LYR/.CUR/.LRC files. Their small
                # stat-only stamp avoids re-parsing unchanged successful
                # sources; new/changed companions are decoded and compared
                # through the SQLite lyric-version table.
                cached_lyrics=db.execute("""SELECT * FROM xstage_lyric_scan_cache
                    WHERE source_path=?""",(original_path,)).fetchone()
                has_version=db.execute("""SELECT 1 FROM xstage_lyric_versions
                    WHERE song_id=? LIMIT 1""",(song_id,)).fetchone()
                if (cached_lyrics and cached_lyrics["media_sha256"]==h and
                        cached_lyrics["companion_stamp"]==stamp and
                        cached_lyrics["outcome"] in ("new-lyrics","same-lyrics","no-lyrics") and
                        (has_version or cached_lyrics["outcome"]=="no-lyrics")):
                    outcome=("no-lyrics" if cached_lyrics["outcome"]=="no-lyrics" else "same-lyrics")
                else:
                    try:
                        doc=document_for(path,comps)
                        parsed=valid_lines(doc) if doc else None
                        if parsed:
                            _,new=insert_version(db,song,media,doc,None,
                                doc.get("sourceFormat") or "NCN")
                            meta=doc.get("metadata") or {}
                            partial=meta.get("timingComplete",True) is False
                            if new and partial:
                                totals["partial_lyrics"]+=1
                                outcome="partial-lyrics"
                                message="เก็บบรรทัดที่มีเวลา CUR จริงได้บางส่วน · ยังไม่พร้อมสร้าง XMID"
                            elif new:
                                totals["lyrics_new"]+=1
                                outcome="new-lyrics"
                            else:
                                outcome="same-lyrics"
                            if song["title"]==song["original_code"] and meta.get("title"):
                                db.execute("UPDATE xstage_songs SET title=?,artist=? WHERE id=?",
                                    (str(meta["title"])[:255],
                                     str(meta.get("artist") or "")[:255],song_id))
                            if comps.get(".lyr") and partial:
                                # Partial timed lines and untimed remainder
                                # belong to the SAME song; do not double
                                # count them as two separate problem songs.
                                save_draft(db,song,comps[".lyr"],"CUR timing incomplete")
                            elif not partial:
                                db.execute("DELETE FROM xstage_lyric_drafts WHERE song_id=?",(song_id,))
                        elif comps.get(".lyr"):
                            # Preserve LYR text even without CUR, without
                            # inventing timing or reporting it as ready.
                            save_draft(db,song,comps[".lyr"],
                                       "CUR missing or unrecognized")
                            totals["draft_lyrics"]+=1
                            outcome="untimed-lyrics"
                            message="บันทึกเนื้อร้องแล้ว แต่ยังไม่พบเวลาปาดสีที่ตรวจสอบได้"
                        elif comps.get(".cur") and path.suffix.lower() in MIDI_EXT:
                            outcome="missing-lyr"
                            message="พบ CUR แต่ไม่พบไฟล์ LYR ที่ตรงกับเพลง"
                        elif doc:
                            outcome="timing-incomplete"
                            message="ข้อมูลเวลาปาดสีไม่ครบ · ยังไม่พร้อมสร้างคาราโอเกะ"
                        else:
                            outcome="no-lyrics"
                        if outcome in ("new-lyrics","same-lyrics","no-lyrics"):
                            db.execute("""INSERT INTO xstage_lyric_scan_cache
                              (source_path,media_sha256,companion_stamp,outcome,last_scanned)
                              VALUES (?,?,?,?,?)
                              ON CONFLICT(source_path) DO UPDATE SET
                              media_sha256=excluded.media_sha256,
                              companion_stamp=excluded.companion_stamp,
                              outcome=excluded.outcome,
                              last_scanned=excluded.last_scanned""",
                              (original_path,h,stamp,outcome,now()))
                    except (OSError,ValueError,TypeError,KeyError) as lyric_error:
                        outcome="lyrics-error"
                        totals["failures"]+=1
                        message=str(lyric_error)[:350]
                        # A valid LYR should survive even if the associated
                        # CUR or MIDI parser failed; never hide the real error.
                        if comps.get(".lyr"):
                            try:
                                save_draft(db,song,comps[".lyr"],message)
                                totals["draft_lyrics"]+=1
                            except (OSError,ValueError,UnicodeError):
                                pass
                # Successes are already reflected in the batch counters and
                # resumable checkpoints; only issues need a row per source.
                # Remove a resolved earlier issue when rechecking a file in
                # the same batch after its companions have been repaired.
                if outcome in ("lyrics-error","timing-incomplete","partial-lyrics",
                               "untimed-lyrics","missing-lyr"):
                    db.execute("""INSERT OR REPLACE INTO xstage_import_items
                     (batch_id,source_path,source_name,media_sha256,song_id,
                      outcome,message,created_at)
                     VALUES (?,?,?,?,?,?,?,?)""",
                     (batch,original_path,path.name,h,song_id,outcome,message,now()))
                else:
                    db.execute("""DELETE FROM xstage_import_items
                         WHERE batch_id=? AND source_path=?""",
                         (batch,original_path))
                db.execute("RELEASE SAVEPOINT plus_media_item")
                savepoint=False
            except (OSError,ValueError,TypeError,sqlite3.DatabaseError) as exc:
                if savepoint:
                    db.execute("ROLLBACK TO SAVEPOINT plus_media_item")
                    db.execute("RELEASE SAVEPOINT plus_media_item")
                totals["failures"]+=1
                message=str(exc)[:350]
                db.execute("""INSERT OR REPLACE INTO xstage_import_items
                 (batch_id,source_path,source_name,media_sha256,song_id,outcome,message,created_at)
                 VALUES (?,?,?,?,?,?,?,?)""",
                 (batch,original_path,path.name,h,None,"error",message,now()))
            checkpoint(path,original_path,source_stat,stamp,outcome,previous_totals)
            if totals["files_seen"]%16==0:store_resume("running")
            if progress and time.monotonic()-last_progress>.25:
                progress({**totals,"resumed_files":resumed_count,"resume":resumed},
                         path.name)
                last_progress=time.monotonic()
        final_status="cancelled" if cancel and cancel.is_set() else "completed"
        store_resume(final_status)
        if final_status=="completed":
            # Only finished batches may discard resume checkpoints. The batch
            # counters retain successes; issue rows remain inspectable.
            try:
                db.execute("DELETE FROM xstage_import_file_checkpoints WHERE batch_id=?",
                           (batch,))
                db.execute("""DELETE FROM xstage_import_items WHERE batch_id=?
                    AND outcome NOT IN ('error','lyrics-error','timing-incomplete',
                    'partial-lyrics','untimed-lyrics','missing-lyr',
                    'skipped-ncn-incomplete')""",(batch,))
                db.commit()
            except sqlite3.DatabaseError:
                # Never fail an already-committed import because housekeeping
                # could not free its disposable log rows.
                db.rollback()
        if progress:progress({**totals,"resumed_files":resumed_count,
                              "resume":resumed},final_status)
    return {"batch":batch,**totals,"resumed_files":resumed_count,
            "resumed":resumed,"cancelled":bool(cancel and cancel.is_set())}


def recover_existing_lyrics(workspace,progress=None,cancel=None):
    """Re-evaluate pending registered songs without hashing or copying media.

    Only songs that currently lack a complete timed version are queued.
    Inspect their original registered source paths, preferring a source with
    actual companion files. All lyric updates are versioned; complete and
    user-edited versions remain untouched. No source file mutations.
    """
    init(workspace)
    totals={"processed":0,"total":0,"recovered_ready":0,
            "partial_lyrics":0,"draft_lyrics":0,
            "missing_sources":0,"changed_sources":0,"skipped_ncn":0,"failures":0}
    batch=uuid.uuid4().hex
    with WRITE_LOCK,connect(workspace) as db:
        entries=db.execute("""SELECT s.id AS song_id,s.code,m.id AS media_id,
            m.sha256,m.stored_path,x.source_path,
            x.bytes AS source_bytes,x.mtime_ns AS source_mtime_ns
            FROM xstage_songs s
            JOIN xstage_media m ON m.id=s.media_id
            LEFT JOIN xstage_media_sources x ON x.media_id=m.id
            WHERE NOT EXISTS (
                SELECT 1 FROM xstage_lyric_versions v
                WHERE v.song_id=s.id AND v.is_current=1
                  AND v.timing_status!='incomplete')
            ORDER BY s.code,x.last_seen DESC""").fetchall()
        collected=defaultdict(list)
        for entry in entries:
            collected[entry["song_id"]].append(dict(entry))
        totals["total"]=len(collected)
        db.execute("""INSERT INTO xstage_import_batches
            (id,source_root,created_at,status)
            VALUES (?,?,?,'running')""",
            (batch,"Registered media paths — lyrics recovery",now()))
        db.commit()
        for song_id,paths in collected.items():
            if cancel and cancel.is_set():
                break
            event_path=None
            outcome="no-lyrics"
            note=""
            db.execute("SAVEPOINT lyrics_recovery")
            try:
                media_row=db.execute("SELECT * FROM xstage_media WHERE id=?",
                                    (paths[0]["media_id"],)).fetchone()
                candidates={}
                changed=False
                for row in paths:
                    if not row["source_path"]:
                        continue
                    source=Path(row["source_path"])
                    try:
                        current=source.stat()
                        if current.st_size!=row["source_bytes"] or current.st_mtime_ns!=row["source_mtime_ns"]:
                            changed=True
                            continue
                        if source.is_file():
                            candidates[source]=True
                    except OSError:
                        continue
                # Legacy SOURCE copies are read-only fallback, never created.
                if media_row["stored_path"]:
                    legacy=Path(workspace)/media_row["stored_path"]
                    if legacy.is_file():
                        candidates[legacy]=True
                # Prefer sources with complete NCN triplets, not the first
                # duplicate source path that may lack its own sidecars.
                ranked=[]
                for source in candidates:
                    comps=companion_candidates(source)
                    score=(int(bool(comps.get(".lyr") and comps.get(".cur")))*4+
                           int(bool(comps.get(".lrc")))*3+
                           int(bool(comps.get(".lyr")))*2+
                           int(bool(comps.get(".cur"))))
                    ranked.append((score,source,comps))
                ranked.sort(key=lambda x:x[0],reverse=True)
                if not ranked:
                    if changed:
                        totals["changed_sources"]+=1
                        outcome="changed-source"
                        note="เพลงต้นฉบับเปลี่ยนไปตั้งแต่ลงทะเบียน · ต้องนำเข้าไฟล์หลักใหม่"
                    else:
                        totals["missing_sources"]+=1
                        outcome="missing-source"
                        note="ไม่พบไฟล์เพลงต้นฉบับในพาธที่ลงทะเบียนไว้"
                else:
                    for _,source,comps in ranked:
                        event_path=source
                        if is_ncn_media(source,comps):
                            missing=ncn_missing_companions(comps)
                            if missing:
                                outcome="skipped-ncn-incomplete"
                                note="ข้าม NCN: "+", ".join(missing)+" ไม่มีหรือว่าง"
                                continue
                        try:
                            doc=document_for(source,comps)
                            lines=valid_lines(doc) if doc else None
                            song=db.execute("SELECT * FROM xstage_songs WHERE id=?",
                                            (song_id,)).fetchone()
                            if lines:
                                version,created=insert_version(
                                    db,song,media_row,doc,None,
                                    doc.get("sourceFormat") or "NCN")
                                meta=doc.get("metadata") or {}
                                active=db.execute(
                                    """SELECT timing_status FROM xstage_lyric_versions
                                       WHERE song_id=? AND is_current=1""",
                                    (song_id,)).fetchone()
                                if active and active["timing_status"]!="incomplete":
                                    totals["recovered_ready"]+=1
                                    outcome="recovered-lyrics"
                                    db.execute("DELETE FROM xstage_lyric_drafts WHERE song_id=?",
                                               (song_id,))
                                else:
                                    totals["partial_lyrics"]+=1
                                    outcome="partial-lyrics"
                                    note="อ่าน CUR ได้บางส่วน · คงเนื้อร้องไว้ตรวจเวลา"
                                    if comps.get(".lyr"):
                                        save_draft(db,song,comps[".lyr"],note)
                                if song["title"]==song["original_code"] and meta.get("title"):
                                    db.execute("UPDATE xstage_songs SET title=?,artist=? WHERE id=?",
                                      (str(meta["title"])[:255],
                                       str(meta.get("artist") or "")[:255],song_id))
                                break
                            if comps.get(".lyr"):
                                save_draft(db,song,comps[".lyr"],"CUR missing or unrecognized")
                                if outcome!="untimed-lyrics":
                                    totals["draft_lyrics"]+=1
                                outcome="untimed-lyrics"
                                note="บันทึกข้อความ LYR แล้ว แต่ยังไม่มีเวลาปาดสี"
                                # Try other registered sources before deciding
                                # this song cannot be recovered completely.
                                continue
                            if outcome not in ("untimed-lyrics","lyrics-error"):
                                outcome="no-lyrics"
                        except (OSError,ValueError,TypeError,UnicodeError,KeyError) as e:
                            note=str(e)[:350]
                            outcome="lyrics-error"
                            if comps.get(".lyr"):
                                try:
                                    save_draft(db,song,comps[".lyr"],note)
                                    totals["draft_lyrics"]+=1
                                except (OSError,ValueError,UnicodeError):
                                    pass
                            continue
                    if outcome=="skipped-ncn-incomplete":
                        totals["skipped_ncn"]+=1
                    elif outcome=="lyrics-error":
                        totals["failures"]+=1
                db.execute("""INSERT OR REPLACE INTO xstage_import_items
                   (batch_id,source_path,source_name,media_sha256,song_id,
                    outcome,message,created_at) VALUES (?,?,?,?,?,?,?,?)""",
                   (batch,str(event_path or paths[0]["source_path"] or ("unresolved://"+song_id)),
                    Path(event_path).name if event_path else "",
                    paths[0]["sha256"],song_id,outcome,note,now()))
                db.execute("RELEASE SAVEPOINT lyrics_recovery")
            except (OSError,ValueError,TypeError,sqlite3.DatabaseError) as err:
                db.execute("ROLLBACK TO SAVEPOINT lyrics_recovery")
                db.execute("RELEASE SAVEPOINT lyrics_recovery")
                totals["failures"]+=1
                db.execute("""INSERT OR REPLACE INTO xstage_import_items
                   (batch_id,source_path,source_name,media_sha256,song_id,
                    outcome,message,created_at) VALUES (?,?,?,?,?,?,?,?)""",
                   (batch,str(event_path or paths[0]["source_path"] or ("unresolved://"+song_id)),
                    "",paths[0]["sha256"],song_id,"error",str(err)[:350],now()))
            totals["processed"]+=1
            if totals["processed"]%64==0:
                db.execute("""UPDATE xstage_import_batches SET files_seen=?,lyrics_new=?,
                        failures=? WHERE id=?""",
                        (totals["processed"],totals["recovered_ready"],totals["failures"],batch))
                db.commit()
            if progress:
                progress(dict(totals),event_path.name if event_path else str(song_id))
        db.execute("""UPDATE xstage_import_batches SET files_seen=?,lyrics_new=?,
            failures=?,status=?,completed_at=? WHERE id=?""",
            (totals["processed"],totals["recovered_ready"],totals["failures"],
             "cancelled" if cancel and cancel.is_set() else "completed",now(),batch))
        db.commit()
    return {"batch":batch,**totals,"cancelled":bool(cancel and cancel.is_set())}


def stats(workspace):
    init(workspace)
    with connect(workspace) as db:
        counts={}
        for label,table in (("songs","xstage_songs"),("media","xstage_media"),
                            ("lyrics","xstage_lyric_versions"),("exports","xstage_exports")):
            counts[label]=db.execute("SELECT count(*) FROM "+table).fetchone()[0]
        counts["songs_with_lyrics"]=db.execute(
            "SELECT COUNT(*) FROM xstage_lyric_versions WHERE is_current=1 AND timing_status!='incomplete'").fetchone()[0]
        counts["songs_partial_lyrics"]=db.execute(
            "SELECT COUNT(*) FROM xstage_lyric_versions WHERE is_current=1 AND timing_status='incomplete'").fetchone()[0]
        counts["songs_draft_lyrics"]=db.execute(
            """SELECT COUNT(*) FROM xstage_lyric_drafts d
               WHERE NOT EXISTS (SELECT 1 FROM xstage_lyric_versions v
                  WHERE v.song_id=d.song_id AND v.is_current=1)"""
        ).fetchone()[0]
        counts["songs_without_lyrics"]=max(0,counts["songs"]-counts["songs_with_lyrics"])
        counts["songs_estimated_timing"]=db.execute(
            "SELECT COUNT(*) FROM xstage_lyric_versions WHERE is_current=1 AND timing_status='estimated'"
        ).fetchone()[0]
        counts["songs_with_text"]=db.execute("""
            SELECT COUNT(DISTINCT song_id) FROM (
                SELECT song_id FROM xstage_lyric_versions
                UNION SELECT song_id FROM xstage_lyric_drafts)
        """).fetchone()[0]
        counts["lyrics_versions"]=counts["lyrics"]
        counts["latest_batches"]=[dict(x) for x in db.execute(
            "SELECT * FROM xstage_import_batches ORDER BY created_at DESC LIMIT 4")]
        return counts

def import_issues(workspace, limit=80):
    """Recent failed or incomplete lyric imports; a media-only row is not an error."""
    init(workspace)
    with connect(workspace) as db:
        rows=db.execute("""SELECT i.source_name,i.source_path,i.outcome,i.message,
                       i.created_at,b.source_root
                   FROM xstage_import_items i
                   JOIN xstage_import_batches b ON b.id=i.batch_id
                   WHERE i.outcome IN ('error','lyrics-error','timing-incomplete',
                                       'partial-lyrics','untimed-lyrics','missing-lyr','skipped-ncn-incomplete')
                   ORDER BY i.id DESC LIMIT ?""",
                   (max(1,min(int(limit),250)),)).fetchall()
        return [dict(row) for row in rows]

def songs(workspace,query="",limit=80,offset=0):
    init(workspace)
    term="%"+str(query)[:100].strip()+"%"
    with connect(workspace) as db:
        items=db.execute("""SELECT s.id,s.code,s.title,s.artist,s.original_code,m.extension,
            m.sha256,v.id AS version_id,v.timing_status,
            d.reason AS draft_reason,e.output_path
            FROM xstage_songs s JOIN xstage_media m ON m.id=s.media_id
            LEFT JOIN xstage_lyric_versions v ON v.song_id=s.id AND v.is_current=1
            LEFT JOIN xstage_lyric_drafts d ON d.song_id=s.id
            LEFT JOIN xstage_exports e ON e.song_id=s.id
            WHERE s.title LIKE ? OR s.artist LIKE ? OR s.original_code LIKE ?
            ORDER BY s.code DESC LIMIT ? OFFSET ?""",
            (term,term,term,max(1,min(int(limit),200)),max(0,int(offset)))).fetchall()
        return [dict(x) for x in items]

def groups(workspace,query,limit=100,offset=0):
    init(workspace)
    q=norm(query)
    if not q or len(q)>100: return []
    with connect(workspace) as db:
        return [dict(x) for x in db.execute("""SELECT l.normalized_text AS group_key,
            min(l.text) AS text,count(*) AS lines,count(DISTINCT v.song_id) AS songs
            FROM xstage_lyric_lines l
            JOIN xstage_lyric_versions v ON v.id=l.version_id AND v.is_current=1
            WHERE instr(l.normalized_text,?)>0
            GROUP BY l.normalized_text
            ORDER BY lines DESC,l.normalized_text
            LIMIT ? OFFSET ?""",(q,max(1,min(limit,500)),max(0,offset)))]

def chosen_rows(db,query,group_keys):
    q=norm(query)
    keys=[norm(x) for x in group_keys]
    if not q or not keys or len(keys)>1000 or any(q not in k for k in keys):
        raise ValueError("กรุณาค้นคำและเลือกกลุ่มบรรทัดที่ตรงกับคำค้น")
    placeholders=",".join("?" for _ in keys)
    return db.execute("""SELECT l.*,v.song_id,s.code FROM xstage_lyric_lines l
       JOIN xstage_lyric_versions v ON v.id=l.version_id AND v.is_current=1
       JOIN xstage_songs s ON s.id=v.song_id
       WHERE l.normalized_text IN ("""+placeholders+") ORDER BY s.code,l.position",keys).fetchall()

def plan_edit(workspace,query,keys):
    with connect(workspace) as db:
        rows=chosen_rows(db,query,keys)
        return {"lines":len(rows),"songs":len({x["song_id"] for x in rows}),
                "groups":len(set(norm(x) for x in keys)),
                "sample":[{"code":x["code"],"text":x["text"]} for x in rows[:12]]}

def glyphs(text):
    result=[]
    for c in text:
        if result and (unicodedata.category(c).startswith("M") or c=="\u200d"):
            result[-1]+=c
        else: result.append(c)
    return result

def remap_cues(old_text,new_text,start,end,cues):
    """Remap changed lyrics onto measured CUR onsets; never invent timestamps.

    Short new lyrics: fill surplus cursor slots with silent > placeholders.
    Long new lyrics: sweep several graphemes together at one old onset.
    The true lyric text stays clean; all timing remains unverified until heard.
    """
    units=glyphs(new_text)
    if not units:
        raise ValueError("ข้อความแทนที่ว่าง")
    if not cues:
        return [],"incomplete"
    try:
        measured=[float(x["start_time"]) for x in cues]
        original="".join(str(x["text"]) for x in cues)
        source_matches=(original==old_text and len(cues)==len(glyphs(old_text)))
        times_valid=(math.isfinite(start) and math.isfinite(end) and
            start<end and len(measured)<=4000 and
            all(math.isfinite(at) and start-.001<=at<end for at in measured) and
            all(measured[i]<=measured[i+1] for i in range(len(measured)-1)))
    except (TypeError,ValueError,OverflowError):
        return [],"incomplete"
    if not times_valid:
        return [],"incomplete"
    size=len(measured)
    if len(units)<size:
        # > is an internal silent cursor slot, not visible lyric text.
        pieces=units+[">"]*(size-len(units))
    elif len(units)>size:
        # Combined swipe: multiple adjacent characters at an original onset.
        pieces=["".join(units[i*len(units)//size:(i+1)*len(units)//size])
                for i in range(size)]
    else:
        pieces=units
    # Text was replaced. CUR onsets remain real, but matching words to
    # those onsets still requires listening; never auto-approve.
    status="estimated"
    return [(piece,round(at,6),
             round(max(0,(measured[i+1] if i+1<size else end)-at),6))
            for i,(piece,at) in enumerate(zip(pieces,measured))],status


def display_cues(line_text,cues):
    """Hide only internal extra trailing > slots while preserving real >."""
    merged="".join(str(c["text"]) for c in cues)
    text=str(line_text)
    if merged.startswith(text):
        suffix=merged[len(text):]
        if suffix and all(v==">" for v in suffix) and len(suffix)<=len(cues):
            visible=len(cues)-len(suffix)
            if visible>=1 and all(str(c["text"])==">" for c in cues[visible:]):
                return cues[:visible]
    return cues


def get_version_lines(db,version_id):
    """Read one song with two ordered queries, not one query per lyric line.

    This avoids thousands of round trips to SQLite for bulk repairs of a
    large library while preserving the original cue ordering and fields.
    """
    lines=[dict(row) for row in db.execute(
        "SELECT * FROM xstage_lyric_lines WHERE version_id=? ORDER BY position",
        (version_id,))]
    if not lines:
        return []
    cues_by_line=defaultdict(list)
    for row in db.execute("""SELECT c.line_id,c.text,c.start_time,c.duration
          FROM xstage_lyric_cues c JOIN xstage_lyric_lines l ON l.id=c.line_id
          WHERE l.version_id=? ORDER BY l.position,c.position""",(version_id,)):
        cues_by_line[row["line_id"]].append({
            "text":row["text"],"start_time":row["start_time"],
            "duration":row["duration"]})
    return [(line,cues_by_line[line["id"]]) for line in lines]

class _EditCancelled(Exception):
    pass


def replace_groups(workspace,query,keys,replacement,expected_lines,progress=None,cancel=None):
    replacement=unicodedata.normalize("NFC",str(replacement).strip())
    if not replacement or len(replacement)>400 or any(c in replacement for c in "\r\n\0"):
        raise ValueError("ข้อความใหม่ต้องเป็นหนึ่งบรรทัด ไม่เกิน 400 อักขระ")
    init(workspace)
    with WRITE_LOCK,connect(workspace) as db:
        db.execute("BEGIN IMMEDIATE")
        selected=chosen_rows(db,query,keys)
        if len(selected)!=int(expected_lines):
            raise ValueError("จำนวนบรรทัดเปลี่ยนไป กรุณาตรวจรายการก่อนยืนยัน")
        edits=defaultdict(dict)
        for row in selected:
            if norm(row["text"])!=norm(replacement):
                edits[row["song_id"]][row["position"]]=row
        if not edits: return {"changed_lines":0,"changed_songs":0,"batch":None}
        batch=uuid.uuid4().hex
        db.execute("""INSERT INTO xstage_edit_batches
         (id,created_at,search,replacement,changed_lines,status)
         VALUES (?,?,?,?,?,'committed')""",(batch,now(),query,replacement,
            sum(len(e) for e in edits.values())))
        ordered_edits=list(edits.items())
        total=len(ordered_edits)
        needs_review=0
        estimated=0
        padded_lines=0
        combined_lines=0
        silent_slots=0
        done_lines=0
        if progress:
            progress({"done":0,"total":total,"changed_lines":0,
                      "needs_review_lines":0,"estimated_lines":0},
                     "เตรียมแก้ไขเนื้อร้อง "+str(total)+" เพลง")
        for completed,(song_id,positions) in enumerate(ordered_edits,1):
            if cancel is not None and cancel.is_set():
                raise _EditCancelled("ผู้ใช้ยกเลิก · คืนค่าธุรกรรมทั้งหมด")
            prior=db.execute("""SELECT * FROM xstage_lyric_versions
               WHERE song_id=? AND is_current=1""",(song_id,)).fetchone()
            previous=get_version_lines(db,prior["id"])
            revised=[]
            for line,cues in previous:
                text=line["text"]
                status=line["timing_status"]
                if line["position"] in positions:
                    text=replacement
                    remapped,status=remap_cues(line["text"],text,
                        line["start_time"],line["end_time"],cues)
                    if status=="incomplete":
                        needs_review+=1
                    elif status=="estimated":
                        estimated+=1
                        units=len(glyphs(text))
                        if units<len(cues):
                            padded_lines+=1
                            silent_slots+=len(cues)-units
                        elif units>len(cues):
                            combined_lines+=1
                else:
                    remapped=[(x["text"],x["start_time"],x["duration"]) for x in cues]
                revised.append((text,line["start_time"],line["end_time"],remapped,status))
            version=uuid.uuid4().hex
            canonical=content_sha(revised)
            existing=db.execute("SELECT id FROM xstage_lyric_versions WHERE song_id=? AND content_sha256=?",
                                (song_id,canonical)).fetchone()
            if existing:
                version=existing["id"]
            else:
                db.execute("""INSERT INTO xstage_lyric_versions
                (id,song_id,content_sha256,source_sha256,origin,timing_status,
                 title,artist,created_at,is_current)
                VALUES (?,?,?,NULL,'edit',?,?,?,?,0)""",
                (version,song_id,canonical,
                 "incomplete" if prior["timing_status"]=="incomplete" or
                     any(x[4]=="incomplete" for x in revised) else
                 "estimated" if any(x[4]=="estimated" for x in revised) else "preserved",
                 prior["title"],prior["artist"],now()))
                for pos,(text,start,end,remapped,status) in enumerate(revised):
                    cursor=db.execute("""INSERT INTO xstage_lyric_lines
                    (version_id,position,text,normalized_text,start_time,end_time,timing_status)
                    VALUES (?,?,?,?,?,?,?)""",(version,pos,text,norm(text),start,end,status))
                    for i,(glyph,at,duration) in enumerate(remapped):
                        db.execute("""INSERT INTO xstage_lyric_cues
                        (line_id,position,text,start_time,duration) VALUES (?,?,?,?,?)""",
                        (cursor.lastrowid,i,glyph,at,duration))
            db.execute("UPDATE xstage_lyric_versions SET is_current=0 WHERE song_id=?",
                       (song_id,))
            db.execute("UPDATE xstage_lyric_versions SET is_current=1 WHERE id=?",(version,))
            db.execute("""INSERT INTO xstage_edit_changes
              (batch_id,song_id,before_version,after_version) VALUES (?,?,?,?)""",
              (batch,song_id,prior["id"],version))
            done_lines+=len(positions)
            if progress and (completed==total or completed%8==0):
                progress({"done":completed,"total":total,
                          "changed_lines":done_lines,
                          "needs_review_lines":needs_review,
                          "estimated_lines":estimated,
                          "padded_lines":padded_lines,
                          "combined_lines":combined_lines,
                          "silent_slots":silent_slots},
                         "แก้ไขแล้ว "+str(completed)+"/"+str(total)+" เพลง")
        if cancel is not None and cancel.is_set():
            raise _EditCancelled("ผู้ใช้ยกเลิก · คืนค่าธุรกรรมทั้งหมด")
        return {"batch":batch,"changed_songs":len(edits),
                "changed_lines":sum(map(len,edits.values())),
                "needs_review_lines":needs_review,"estimated_lines":estimated,
                "padded_lines":padded_lines,
                "combined_lines":combined_lines,"silent_slots":silent_slots}

def undo_edit(workspace,batch):
    with WRITE_LOCK,connect(workspace) as db:
        db.execute("BEGIN IMMEDIATE")
        b=db.execute("SELECT * FROM xstage_edit_batches WHERE id=?",(batch,)).fetchone()
        if not b or b["status"]!="committed": raise ValueError("ไม่พบชุดแก้ไขที่ย้อนคืนได้")
        edits=list(db.execute("SELECT * FROM xstage_edit_changes WHERE batch_id=?",(batch,)))
        for row in edits:
            current=db.execute("SELECT id FROM xstage_lyric_versions WHERE song_id=? AND is_current=1",
                               (row["song_id"],)).fetchone()
            if not current or current[0]!=row["after_version"]:
                raise ValueError("มีการแก้ไขต่อภายหลัง ย้อนคืนทั้งชุดไม่ได้โดยไม่ทับข้อมูลใหม่")
        for row in edits:
            db.execute("UPDATE xstage_lyric_versions SET is_current=0 WHERE song_id=?",
                       (row["song_id"],))
            db.execute("UPDATE xstage_lyric_versions SET is_current=1 WHERE id=?",
                       (row["before_version"],))
        db.execute("UPDATE xstage_edit_batches SET status='undone' WHERE id=?",(batch,))
        return {"restored_songs":len(edits)}

def packed_text(text):
    raw=str(text).encode("utf-8")
    if len(raw)>2**20: raise ValueError("ข้อความเกินขนาด")
    return struct.pack("<I",len(raw))+raw

def metadata_bytes(song,version,lines):
    stream=bytearray()
    for val in (song["id"],str(song["code"]),version["id"],
                version["title"],version["artist"],version["timing_status"]):
        stream.extend(packed_text(val))
    stream.extend(struct.pack("<I",len(lines)))
    for line,cues in lines:
        stream.extend(struct.pack("<dd",line["start_time"],line["end_time"]))
        stream.extend(packed_text(line["text"]))
        stream.extend(packed_text(line["timing_status"]))
        stream.extend(struct.pack("<I",len(cues)))
        visible_count=len(display_cues(line["text"],cues))
        for i,c in enumerate(cues):
            stream.extend(struct.pack("<dd",c["start_time"],c["duration"]))
            # Preserve every measured cursor slot in the X container, but
            # serialize the internal tail-padding as silent (zero text).
            stream.extend(packed_text(c["text"] if i<visible_count else ""))
    return bytes(stream)

def destination_for(workspace,song,ext):
    kind=ext.lstrip(".").lower()
    name=f'{song["code"]:08d}'
    bucket=name[0]
    if kind in ("mid","midi","kar"):
        return root_folder(workspace)/"MIDI"/"MID"/"XMID"/bucket/(name+".xmid")
    if kind in ("mp4","mkv","webm","mov"):
        return root_folder(workspace)/"VDO"/("X"+kind.upper())/bucket/(name+".x"+kind)
    return root_folder(workspace)/"AUDIO"/("X"+kind.upper())/bucket/(name+".x"+kind)

def build_song(workspace,song_id):
    init(workspace)
    with WRITE_LOCK,connect(workspace) as db:
        pair=db.execute("""SELECT s.*,m.id AS source_media_id,m.sha256,m.extension,m.stored_path,m.bytes
          FROM xstage_songs s JOIN xstage_media m ON m.id=s.media_id WHERE s.id=?""",
          (song_id,)).fetchone()
        if not pair: raise ValueError("ไม่พบเพลง")
        version=db.execute("""SELECT * FROM xstage_lyric_versions
          WHERE song_id=? AND is_current=1""",(song_id,)).fetchone()
        if not version: raise ValueError("เพลงนี้ยังไม่มีเนื้อร้องพร้อมเวลา · ยังสร้าง Karaoke ไม่ได้")
        if version["timing_status"]=="incomplete":
            raise ValueError("เพลงนี้มีเนื้อร้องบางส่วนแต่ CUR ยังไม่ครบ · ตรวจสอบเวลาปาดสีก่อนสร้าง XMID")
        lines=get_version_lines(db,version["id"])
        meta=metadata_bytes(pair,version,lines)
        # Do not require or make a second original-file copy. Resolve the
        # saved source reference, including legacy preview SOURCE archives.
        lookup=db.execute("SELECT * FROM xstage_media WHERE id=?",
                          (pair["source_media_id"],)).fetchone()
        media_file=source_for_build(workspace,db,lookup)
        dest=destination_for(workspace,pair,pair["extension"])
        dest.parent.mkdir(parents=True,exist_ok=True)
        previous=db.execute("SELECT * FROM xstage_exports WHERE song_id=?",(song_id,)).fetchone()
        if previous and previous["version_id"]==version["id"] and dest.is_file():
            if digest(dest)==previous["sha256"]:
                return {"path":str(dest),"skipped":True,"sha256":previous["sha256"]}
        metadata_sha=hashlib.sha256(meta).digest()
        fd,name=tempfile.mkstemp(prefix=".xstage-build-",dir=dest.parent)
        os.close(fd)
        stage=Path(name)
        try:
            # Hash the original bytes in the SAME streaming pass that writes
            # the X-file. No pre-hash + copy + readback triplication.
            output_digest=hashlib.sha256()
            media_digest=hashlib.sha256()
            with stage.open("wb") as out,media_file.open("rb") as src:
                header=HEADER.pack(MAGIC,FORMAT_VERSION,len(meta),
                                   pair["bytes"],bytes.fromhex(pair["sha256"]),metadata_sha)
                out.write(header)
                out.write(meta)
                output_digest.update(header)
                output_digest.update(meta)
                transferred=0
                for block in iter(lambda:src.read(1024*1024),b""):
                    transferred+=len(block)
                    media_digest.update(block)
                    output_digest.update(block)
                    out.write(block)
                out.flush()
                os.fsync(out.fileno())
            if transferred!=pair["bytes"] or media_digest.hexdigest()!=pair["sha256"]:
                raise ValueError("ไฟล์ต้นฉบับเปลี่ยนหลังนำเข้า · ต้องนำเข้าใหม่ก่อนส่งออก")
            info=inspect_xfile(stage,full_verify=False)
            if info["media_sha256"]!=pair["sha256"]:
                raise ValueError("สื่อในไฟล์ X-Stage ไม่ตรงกับทะเบียน")
            if dest.exists() and (not previous or digest(dest)!=previous["sha256"]):
                raise ValueError("ปลายทางมีไฟล์ที่ไม่ตรงกับทะเบียน · ไม่เขียนทับ")
            os.replace(stage,dest)
            output_sha=output_digest.hexdigest()
            db.execute("""INSERT INTO xstage_exports
              (song_id,version_id,output_path,sha256,created_at) VALUES (?,?,?,?,?)
              ON CONFLICT(song_id) DO UPDATE SET version_id=excluded.version_id,
              output_path=excluded.output_path,sha256=excluded.sha256,
              created_at=excluded.created_at""",
              (song_id,version["id"],str(dest.relative_to(root_folder(workspace))),
               output_sha,now()))
            return {"path":str(dest),"skipped":False,"sha256":output_sha,
                    "timing_status":version["timing_status"]}
        finally:
            stage.unlink(missing_ok=True)

def inspect_xfile(path,full_verify=False):
    p=Path(path)
    with p.open("rb") as source:
        header=source.read(HEADER.size)
        if len(header)!=HEADER.size: raise ValueError("ไฟล์ X-Stage มีส่วนหัวไม่ครบ")
        magic,version,metadata_length,media_length,media_hash,meta_hash=HEADER.unpack(header)
        if magic!=MAGIC or version!=FORMAT_VERSION:
            raise ValueError("ไม่ใช่ไฟล์ X-Stage Plus รุ่นที่รองรับ")
        if metadata_length>32*1024*1024 or media_length>SIZE_LIMIT:
            raise ValueError("ขนาดเนื้อร้องหรือสื่อเกินขอบเขต")
        if p.stat().st_size!=HEADER.size+metadata_length+media_length:
            raise ValueError("ขนาดไฟล์ X-Stage ไม่ตรงกับส่วนหัว")
        data=source.read(metadata_length)
        if hashlib.sha256(data).digest()!=meta_hash:
            raise ValueError("ข้อมูลเนื้อร้องในไฟล์เสียหาย")
        if full_verify:
            h=hashlib.sha256()
            for block in iter(lambda:source.read(1024*1024),b""):
                h.update(block)
            if h.digest()!=media_hash: raise ValueError("SHA-256 สื่อใน XMID ไม่ตรง")
        return {"version":version,"media_sha256":media_hash.hex(),
                "metadata_bytes":metadata_length,"media_bytes":media_length,
                "verified_media":bool(full_verify)}


def decode_metadata(payload):
    """Read the documented Plus binary lyric records without a JSON sidecar.

    This method is suitable as the portable reference decoder for future
    Windows/Web/Android players; all offsets and counts are bounds checked.
    """
    from math import isfinite
    raw=memoryview(payload)
    cursor=0
    def take(n):
        nonlocal cursor
        if n<0 or n>len(raw)-cursor:
            raise ValueError("โครงสร้าง metadata ภายใน X-Stage ไม่ครบ")
        block=raw[cursor:cursor+n]
        cursor+=n
        return block
    def scalar(fmt):
        size=struct.calcsize(fmt)
        return struct.unpack(fmt,take(size))[0]
    def read_text():
        length=scalar("<I")
        if length>1024*1024:
            raise ValueError("ข้อมูลข้อความ XMID ยาวเกินกำหนด")
        return bytes(take(length)).decode("utf-8","strict")
    song_id,code,version_id,title,artist,status=(read_text() for _ in range(6))
    line_count=scalar("<I")
    if line_count>100000:
        raise ValueError("จำนวนบรรทัด XMID เกินกำหนด")
    lines=[]
    for _ in range(line_count):
        start,end=struct.unpack("<dd",take(16))
        lyric=read_text()
        timing=read_text()
        if not all(isfinite(v) for v in (start,end)) or not 0<=start<end:
            raise ValueError("เวลาบรรทัด XMID ไม่ถูกต้อง")
        cue_count=scalar("<I")
        if cue_count>100000:
            raise ValueError("จำนวนจุดปาดสีเกินกำหนด")
        cues=[]
        for _ in range(cue_count):
            at,duration=struct.unpack("<dd",take(16))
            glyph=read_text()
            if not all(isfinite(v) for v in (at,duration)) or not start-.001<=at<=end+.001 or duration<0:
                raise ValueError("เวลาปาดสี XMID ไม่ถูกต้อง")
            cues.append({"startTime":at,"duration":duration,"text":glyph})
        if any(a["startTime"]>b["startTime"] for a,b in zip(cues,cues[1:])):
            raise ValueError("ตำแหน่งปาดสี XMID ย้อนกลับ")
        lines.append({"text":lyric,"startTime":start,"endTime":end,
                      "timingStatus":timing,"cues":cues})
    if cursor!=len(raw):
        raise ValueError("พบข้อมูล XMID เกินจากโครงสร้างที่กำหนด")
    return {"songId":song_id,"code":code,"lyricsVersionId":version_id,
            "title":title,"artist":artist,"timingStatus":status,"lines":lines}

def read_xfile(path,verify_media=False):
    """Return metadata and offset without materializing the media payload."""
    p=Path(path)
    with p.open("rb") as source:
        block=source.read(HEADER.size)
        if len(block)!=HEADER.size:
            raise ValueError("ไฟล์ X-Stage ไม่ครบส่วนหัว")
        magic,version,metadata_length,media_length,media_sha,meta_sha=HEADER.unpack(block)
        if magic!=MAGIC or version!=FORMAT_VERSION:
            raise ValueError("รูปแบบ X-Stage ไม่รองรับ")
        if metadata_length>32*1024*1024 or media_length>SIZE_LIMIT:
            raise ValueError("ส่วนข้อมูลใหญ่เกินขอบเขต")
        if p.stat().st_size!=HEADER.size+metadata_length+media_length:
            raise ValueError("ขนาดไฟล์จริงไม่ตรงกับส่วนหัว")
        payload=source.read(metadata_length)
        if hashlib.sha256(payload).digest()!=meta_sha:
            raise ValueError("ข้อมูลเนื้อร้องใน XMID ถูกเปลี่ยนแปลง")
        lyrics=decode_metadata(payload)
        if verify_media:
            h=hashlib.sha256()
            for chunk in iter(lambda:source.read(1024*1024),b""):
                h.update(chunk)
            if h.digest()!=media_sha:
                raise ValueError("สื่อของไฟล์ XMID ไม่ตรงกับ SHA-256")
        return {**lyrics,"mediaOffset":HEADER.size+metadata_length,
                "mediaBytes":media_length,"mediaSha256":media_sha.hex(),
                "verifiedMedia":bool(verify_media)}
