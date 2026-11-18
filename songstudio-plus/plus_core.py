"""X-Stage Song Studio Plus: SQLite-first catalog and binary embedded-media output.

No external dependencies. The original song media is immutable; every mutable
lyric revision is an independent SQLite version.
"""
from __future__ import annotations

import hashlib
import json
import os
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
    c = sqlite3.connect(path, timeout=25)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA busy_timeout=25000")
    c.execute("PRAGMA journal_mode=WAL")
    try:
        with c:
            yield c
    finally:
        c.close()

SCHEMA = """
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
CREATE TABLE IF NOT EXISTS xstage_lyric_versions(
 id TEXT PRIMARY KEY, song_id TEXT NOT NULL REFERENCES xstage_songs(id),
 content_sha256 TEXT NOT NULL, source_sha256 TEXT, origin TEXT NOT NULL,
 timing_status TEXT NOT NULL, title TEXT NOT NULL, artist TEXT NOT NULL,
 created_at TEXT NOT NULL, is_current INTEGER NOT NULL DEFAULT 0,
 UNIQUE(song_id,content_sha256));
CREATE UNIQUE INDEX IF NOT EXISTS xstage_current_lyric
 ON xstage_lyric_versions(song_id) WHERE is_current=1;
CREATE INDEX IF NOT EXISTS xstage_lyric_source
 ON xstage_lyric_versions(song_id,source_sha256);
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
def init(workspace):
    with WRITE_LOCK:
        with connect(workspace) as db:
            db.executescript(SCHEMA)
    return db_path(workspace)

def source_for_build(workspace, db, media):
    """Resolve a verified source without copying it on import.

    Legacy Plus entries retain a SOURCE/... path. New Plus entries reference
    one or more absolute source paths registered under xstage_media_sources.
    If a USB is unplugged, stop safely and ask for the source again.
    """
    stored=media["stored_path"]
    if stored:
        legacy=root_folder(workspace) / stored
        if legacy.is_file():
            return legacy
    entries=db.execute("""SELECT source_path,bytes FROM xstage_media_sources
          WHERE media_id=? ORDER BY last_seen DESC""",(media["id"],)).fetchall()
    for entry in entries:
        candidate=Path(entry["source_path"])
        try:
            if candidate.is_file() and candidate.stat().st_size==media["bytes"]:
                return candidate
        except OSError:
            pass
    raise ValueError("ไม่พบไฟล์เพลงต้นฉบับ กรุณาเชื่อมต่อ USB/HDD หรือเพิ่มแหล่งเพลงใหม่ก่อนส่งออก")


def companion_candidates(media):
    # Match direct companions for all formats; the classic split NCN tree
    # is handled by the validated ncn_reader path resolver.
    p = Path(media)
    files = {}
    try:
        names = {x.name.casefold(): x for x in p.parent.iterdir()
                 if x.is_file() and not x.is_symlink()}
    except OSError:
        names = {}
    for extension in (".lyr",".cur",".lrc"):
        files[extension] = names.get((p.stem+extension).casefold())
    if p.suffix.lower() in MIDI_EXT:
        resolved = ncn_reader.resolve_companions(p)
        if resolved:
            files[".lyr"] = files[".lyr"] or (Path(resolved["lyrics"]) if resolved.get("lyrics") else None)
            files[".cur"] = files[".cur"] or (Path(resolved["cursor"]) if resolved.get("cursor") else None)
    return files

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
    p=Path(path)
    if (companions.get(".lyr") and companions.get(".cur")
            and p.suffix.lower() in MIDI_EXT):
        return ncn_reader.ncn_document({
            "midi":str(p),"lyrics":str(companions[".lyr"]),
            "cursor":str(companions[".cur"]),
            "missing":[],"code":p.stem})
    if companions.get(".lrc"):
        return parse_lrc(companions[".lrc"])
    if p.suffix.lower() in MIDI_EXT:
        try:
            return ncn_reader.kar_document(p,p.stem)
        except ValueError:
            return None
    return None

def valid_lines(doc):
    if not doc or not doc.get("lines") or not doc.get("metadata",{}).get("timingComplete",True):
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
    if not lines: return (None,False)
    signature=content_sha(lines)
    prior=db.execute(
        "SELECT id FROM xstage_lyric_versions WHERE song_id=? AND content_sha256=?",
        (song["id"],signature)).fetchone()
    if prior: return (prior["id"],False)
    version=uuid.uuid4().hex
    meta=doc.get("metadata",{})
    title=(meta.get("title") or song["title"]).strip()[:255]
    artist=(meta.get("artist") or song["artist"]).strip()[:255]
    status="original" if all(l[4]=="original" for l in lines) else "estimated"
    db.execute("UPDATE xstage_lyric_versions SET is_current=0 WHERE song_id=?",(song["id"],))
    db.execute("""INSERT INTO xstage_lyric_versions
      (id,song_id,content_sha256,source_sha256,origin,timing_status,title,artist,created_at,is_current)
      VALUES (?,?,?,?,?,?,?,?,?,1)""",
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
    return version,True

def iter_source(root):
    for base,dirs,files in os.walk(root):
        dirs[:]=sorted(x for x in dirs if not (Path(base)/x).is_symlink())
        for name in sorted(files):
            p=Path(base)/name
            if p.suffix.lower() in MEDIA_EXT and not p.is_symlink() and p.is_file():
                yield p

def import_folder(workspace,source,progress=None,cancel=None):
    root=clean_path(source)
    target=root_folder(workspace)
    if root==target or target in root.parents or root in target.parents:
        raise ValueError("ต้นทางและคลัง Plus ต้องไม่อยู่ภายในกัน เพื่อป้องกันสแกนไฟล์วนซ้ำ")
    init(target)
    batch=uuid.uuid4().hex
    totals={"files_seen":0,"files_new":0,"media_duplicates":0,
            "lyrics_new":0,"failures":0}
    with WRITE_LOCK, connect(target) as db:
        db.execute("""INSERT INTO xstage_import_batches
            (id,source_root,created_at,status) VALUES (?,?,?,'running')""",
            (batch,str(root),now()))
    for path in iter_source(root):
        if cancel and cancel.is_set(): break
        totals["files_seen"]+=1
        outcome="error"; message=""; song_id=None; h=None
        try:
            before=path.stat()
            if not 0<=before.st_size<SIZE_LIMIT:
                raise ValueError("ขนาดไฟล์ไม่อยู่ในช่วงที่รองรับ")
            h=digest(path)
            after=path.stat()
            if (after.st_size,after.st_mtime_ns)!=(before.st_size,before.st_mtime_ns):
                raise ValueError("ไฟล์ต้นทางเปลี่ยนระหว่างคำนวณ SHA-256")
            comps=companion_candidates(path)
            with WRITE_LOCK, connect(target) as db:
                media=db.execute("SELECT * FROM xstage_media WHERE sha256=?",(h,)).fetchone()
                if media:
                    totals["media_duplicates"]+=1
                    outcome="media-duplicate"
                    song=db.execute("SELECT * FROM xstage_songs WHERE media_id=?",(media["id"],)).fetchone()
                else:
                    stored=media_location(target,h,path.suffix.lower())
                    safe_store(path,stored,h)
                    media_id=uuid.uuid4().hex
                    db.execute("""INSERT INTO xstage_media
                      (id,sha256,extension,bytes,stored_path,first_filename,created_at)
                      VALUES (?,?,?,?,?,?,?)""",
                      (media_id,h,path.suffix.lower(),before.st_size,
                       str(stored.relative_to(target)),path.name,now()))
                    title=path.stem
                    artist=""
                    song_id=uuid.uuid4().hex
                    seq=db.execute("SELECT COALESCE(MAX(code),0)+1 FROM xstage_songs").fetchone()[0]
                    db.execute("""INSERT INTO xstage_songs
                     (id,code,media_id,title,artist,original_code,created_at)
                     VALUES (?,?,?,?,?,?,?)""",
                     (song_id,seq,media_id,title,artist,path.stem,now()))
                    totals["files_new"]+=1
                    song=db.execute("SELECT * FROM xstage_songs WHERE id=?",(song_id,)).fetchone()
                    media=db.execute("SELECT * FROM xstage_media WHERE id=?",(media_id,)).fetchone()
                    outcome="new-media"
                song_id=song["id"]
                parts=[]
                for ext in (".lyr",".cur",".lrc"):
                    companion=comps.get(ext)
                    if companion:
                        parts.append(ext.encode()+b"\x00"+digest(companion).encode())
                source_sig=binary_digest(*parts) if parts else None
                if source_sig and db.execute("""SELECT 1 FROM xstage_lyric_versions
                     WHERE song_id=? AND source_sha256=?""",(song_id,source_sig)).fetchone():
                    outcome="same-lyrics"
                else:
                    # A bad or partial lyric companion MUST NOT roll back a
                    # verified media record. Keep the source once, log the
                    # lyric problem and permit fixing LYR/CUR on the next scan.
                    try:
                        doc=document_for(path,comps)
                        parsed=valid_lines(doc) if doc else None
                        if parsed:
                            _,new=insert_version(db,song,media,doc,source_sig,
                                "NCN" if comps.get(".lyr") and comps.get(".cur") else
                                "LRC" if comps.get(".lrc") else "KAR")
                            if new:
                                totals["lyrics_new"]+=1
                                outcome="new-lyrics"
                                meta=doc.get("metadata") or {}
                                if song["title"]==song["original_code"] and meta.get("title"):
                                    db.execute("UPDATE xstage_songs SET title=?,artist=? WHERE id=?",
                                               (str(meta["title"])[:255],
                                                str(meta.get("artist") or "")[:255],song_id))
                        elif doc:
                            message="เนื้อร้องหรือ CUR ยังจับเวลาไม่ครบ · เก็บสื่อไว้รอตรวจ"
                            outcome="timing-incomplete"
                    except (OSError,ValueError,TypeError,KeyError) as lyric_error:
                        outcome="lyrics-error"
                        totals["failures"]+=1
                        message=str(lyric_error)[:350]
                db.execute("""INSERT OR REPLACE INTO xstage_import_items
                (batch_id,source_path,source_name,media_sha256,song_id,outcome,message,created_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (batch,str(path),path.name,h,song_id,outcome,message,now()))
        except (OSError,ValueError,TypeError,sqlite3.DatabaseError) as exc:
            totals["failures"]+=1
            message=str(exc)[:350]
            with WRITE_LOCK,connect(target) as db:
                db.execute("""INSERT OR REPLACE INTO xstage_import_items
                (batch_id,source_path,source_name,media_sha256,song_id,outcome,message,created_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (batch,str(path),path.name,h,None,"error",message,now()))
        with WRITE_LOCK,connect(target) as db:
            db.execute("""UPDATE xstage_import_batches SET
             files_seen=?,files_new=?,media_duplicates=?,lyrics_new=?,failures=?
             WHERE id=?""",(*totals.values(),batch))
        if progress: progress(dict(totals),path.name)
    with WRITE_LOCK,connect(target) as db:
        db.execute("UPDATE xstage_import_batches SET status=?,completed_at=? WHERE id=?",
                   ("cancelled" if cancel and cancel.is_set() else "completed",now(),batch))
    return {"batch":batch,**totals,"cancelled":bool(cancel and cancel.is_set())}

def stats(workspace):
    init(workspace)
    with connect(workspace) as db:
        counts={}
        for label,table in (("songs","xstage_songs"),("media","xstage_media"),
                            ("lyrics","xstage_lyric_versions"),("exports","xstage_exports")):
            counts[label]=db.execute("SELECT count(*) FROM "+table).fetchone()[0]
        counts["latest_batches"]=[dict(x) for x in db.execute(
            "SELECT * FROM xstage_import_batches ORDER BY created_at DESC LIMIT 4")]
        return counts

def songs(workspace,query="",limit=80,offset=0):
    init(workspace)
    term="%"+str(query)[:100].strip()+"%"
    with connect(workspace) as db:
        items=db.execute("""SELECT s.id,s.code,s.title,s.artist,s.original_code,m.extension,
            m.sha256,v.id AS version_id,v.timing_status,e.output_path
            FROM xstage_songs s JOIN xstage_media m ON m.id=s.media_id
            LEFT JOIN xstage_lyric_versions v ON v.song_id=s.id AND v.is_current=1
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
    units=glyphs(new_text)
    if not units: raise ValueError("ข้อความแทนที่ว่าง")
    measured=[float(x["start_time"]) for x in cues]
    if cues and ("".join(x["text"] for x in cues)!=old_text or
                 len(cues)!=len(glyphs(old_text))):
        raise ValueError("รูปแบบเวลาปาดสีต้นฉบับไม่สอดคล้องกับข้อความ · ข้ามเพลง")
    if measured and any(measured[i]>measured[i+1] for i in range(len(measured)-1)):
        raise ValueError("เวลา CUR ไม่เรียงลำดับ")
    if measured and len(units)==len(measured):
        times=measured
        status="preserved"
    elif measured:
        track=measured+[end]
        length=len(measured)
        times=[]
        for i in range(len(units)):
            x=i*length/len(units)
            at=min(int(x),length-1)
            times.append(track[at]+(track[at+1]-track[at])*(x-at))
        status="estimated"
    else:
        times=[start+(end-start)*i/len(units) for i in range(len(units))]
        status="estimated"
    if any(not start-.001<=v<=end+.001 for v in times):
        raise ValueError("เวลาปาดสีใหม่อยู่นอกบรรทัด")
    return [(unit,round(at,6),round(max(0,(times[i+1] if i+1<len(times) else end)-at),6))
            for i,(unit,at) in enumerate(zip(units,times))],status

def get_version_lines(db,version_id):
    result=[]
    for line in db.execute("SELECT * FROM xstage_lyric_lines WHERE version_id=? ORDER BY position",
                           (version_id,)):
        cues=[dict(x) for x in db.execute("""SELECT text,start_time,duration
                  FROM xstage_lyric_cues WHERE line_id=? ORDER BY position""",(line["id"],))]
        result.append((dict(line),cues))
    return result

def replace_groups(workspace,query,keys,replacement,expected_lines):
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
        for song_id,positions in edits.items():
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
        return {"batch":batch,"changed_songs":len(edits),
                "changed_lines":sum(map(len,edits.values()))}

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
        for c in cues:
            stream.extend(struct.pack("<dd",c["start_time"],c["duration"]))
            stream.extend(packed_text(c["text"]))
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
        pair=db.execute("""SELECT s.*,m.sha256,m.extension,m.stored_path,m.bytes
          FROM xstage_songs s JOIN xstage_media m ON m.id=s.media_id WHERE s.id=?""",
          (song_id,)).fetchone()
        if not pair: raise ValueError("ไม่พบเพลง")
        version=db.execute("""SELECT * FROM xstage_lyric_versions
          WHERE song_id=? AND is_current=1""",(song_id,)).fetchone()
        if not version: raise ValueError("เพลงนี้ยังไม่มีเนื้อร้องพร้อมเวลา · ยังสร้าง Karaoke ไม่ได้")
        lines=get_version_lines(db,version["id"])
        meta=metadata_bytes(pair,version,lines)
        media_file=root_folder(workspace)/pair["stored_path"]
        if not media_file.is_file() or digest(media_file)!=pair["sha256"]:
            raise ValueError("ไฟล์สื่อต้นฉบับในคลังไม่ถูกต้องหรือถูกแก้ไข")
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
            with stage.open("wb") as out,media_file.open("rb") as src:
                out.write(HEADER.pack(MAGIC,FORMAT_VERSION,len(meta),
                                      pair["bytes"],bytes.fromhex(pair["sha256"]),metadata_sha))
                out.write(meta)
                shutil.copyfileobj(src,out,1024*1024)
                out.flush();os.fsync(out.fileno())
            info=inspect_xfile(stage,full_verify=True)
            if info["media_sha256"]!=pair["sha256"]:
                raise ValueError("สื่อในไฟล์ X-Stage ไม่ตรงกับต้นฉบับ")
            if dest.exists() and (not previous or digest(dest)!=previous["sha256"]):
                raise ValueError("ปลายทางมีไฟล์ที่ไม่ตรงกับทะเบียน · ไม่เขียนทับ")
            os.replace(stage,dest)
            output_sha=digest(dest)
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
