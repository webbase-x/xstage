"""Evidence-based lyric sweep diagnostics and historical listening reviews.

Never mark a song as "confirmed wrong" from metadata alone. Findings are
reproducible structural problems or explicitly unmeasured (estimated) timing.
Only a human listening test may confirm a perceived alignment problem.
No audio/media hashes, file copies or changes to the source folder.
"""
from __future__ import annotations

import os
import sqlite3
import unicodedata
import uuid
from collections import defaultdict
from pathlib import Path

import plus_core as core

DDL = """
CREATE TABLE IF NOT EXISTS xstage_swipe_audit_runs(
 id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
 status TEXT NOT NULL, songs_checked INTEGER NOT NULL DEFAULT 0,
 structural_songs INTEGER NOT NULL DEFAULT 0,
 estimated_songs INTEGER NOT NULL DEFAULT 0,
 blocked_songs INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS xstage_swipe_findings(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 run_id TEXT NOT NULL REFERENCES xstage_swipe_audit_runs(id),
 song_id TEXT NOT NULL REFERENCES xstage_songs(id),
 version_id TEXT NOT NULL REFERENCES xstage_lyric_versions(id),
 category TEXT NOT NULL CHECK(category IN ('structural','unverified','blocked')),
 rule TEXT NOT NULL, line_position INTEGER NOT NULL DEFAULT -1,
 line_start REAL, line_end REAL, excerpt TEXT NOT NULL DEFAULT '',
 evidence TEXT NOT NULL, detected_at TEXT NOT NULL,
 UNIQUE(run_id,song_id,version_id,rule,line_position));
CREATE INDEX IF NOT EXISTS xstage_swipe_findings_lookup
 ON xstage_swipe_findings(run_id,category,song_id);
CREATE TABLE IF NOT EXISTS xstage_swipe_reviews(
 id INTEGER PRIMARY KEY AUTOINCREMENT, song_id TEXT NOT NULL REFERENCES xstage_songs(id),
 version_id TEXT NOT NULL REFERENCES xstage_lyric_versions(id),
 action TEXT NOT NULL CHECK(action IN ('opened','confirmed','passed','needs-review')),
 note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS xstage_swipe_reviews_song
 ON xstage_swipe_reviews(song_id,version_id,id);
"""

CATEGORY_LABELS = {
    "structural": "พบความผิดปกติจากข้อมูล",
    "unverified": "ปาดสีจากเวลาประมาณ ต้องฟังตรวจ",
    "blocked": "เวลาไม่ครบ ยังทดลองปาดสีไม่ได้",
}

RULES = {
    "INVALID_LINE_RANGE": "เวลาเริ่ม–จบบรรทัดไม่ถูกต้อง",
    "NO_SWEEP_CUES": "มีเนื้อร้องแต่ไม่มีจุดปาดสี",
    "CUE_TEXT_DIFFERS": "ข้อความจุดปาดสีไม่ตรงกับเนื้อร้อง",
    "CUE_TIME_REVERSES": "เวลา CUR ปาดย้อนกลับ",
    "CUE_OUTSIDE_LINE": "จุดปาดสีอยู่นอกเวลาบรรทัด",
    "CUE_OVERLAP": "ช่วงปาดสีทับตำแหน่งถัดไป",
    "ESTIMATED_SWEEP": "จุดปาดสีเกิดจากการประมาณเวลา ไม่ใช่จุดวัดจริง",
    "INCOMPLETE_CUR": "ชุดเนื้อร้องยังมี CUR ไม่ครบ",
    "EMPTY_TIMED_VERSION": "เวอร์ชันปัจจุบันไม่มีบรรทัดที่มีเวลา",
}


_INITIALIZED = set()

def init(workspace):
    """Create evidence tables once, not on every risk-page refresh."""
    key=str(core.db_path(workspace).resolve())
    if key in _INITIALIZED:
        return
    core.init(workspace)
    with core.WRITE_LOCK:
        if key in _INITIALIZED:
            return
        with core.connect(workspace) as db:
            db.executescript(DDL)
        _INITIALIZED.add(key)


def _finding(category,rule,line=None,detail=""):
    return {
        "category":category,"rule":rule,
        "line_position":int(line["position"]) if line else -1,
        "line_start":float(line["start_time"]) if line else None,
        "line_end":float(line["end_time"]) if line else None,
        "excerpt":(line["text"][:150] if line else ""),
        "evidence":detail[:400],
    }


def analyze(version,lines):
    """Pure, deterministic inspection of actual SQLite timing/cue records."""
    result=[]
    if version["timing_status"]=="incomplete":
        result.append(_finding("blocked","INCOMPLETE_CUR",
                               detail="SQLite ระบุ timing_status=incomplete · ห้ามสรุปว่าเล่นปาดได้"))
        return result
    if not lines:
        return [_finding("blocked","EMPTY_TIMED_VERSION",
                         detail="มี Lyrics Version ปัจจุบันแต่ไม่พบบรรทัดใน xstage_lyric_lines")]
    for line,cues in lines:
        start=float(line["start_time"])
        end=float(line["end_time"])
        if start<0 or end<=start:
            result.append(_finding("structural","INVALID_LINE_RANGE",line,
                 f"เริ่ม {start:.4f}s · จบ {end:.4f}s"))
            continue
        if not cues and line["text"].strip():
            result.append(_finding("structural","NO_SWEEP_CUES",line,
                 f"บรรทัด {line['position']+1} มีข้อความ {len(line['text'])} อักขระ แต่จุดปาดสี = 0"))
        if cues:
            # Internal trailing > fills unused original CUR slots. Only the
            # visible text is compared; numeric timing still checks all cues.
            shown=core.display_cues(line["text"],cues)
            merged=unicodedata.normalize("NFC","".join(str(c["text"]) for c in shown))
            target=unicodedata.normalize("NFC",line["text"])
            if merged!=target:
                result.append(_finding("structural","CUE_TEXT_DIFFERS",line,
                     f"บรรทัด {line['position']+1}: เนื้อร้อง {len(target)} อักขระ · จากจุดปาด {len(merged)} อักขระ · ข้อความไม่เท่ากัน"))
            last_at=None
            for idx,cue in enumerate(cues):
                at=float(cue["start_time"])
                duration=float(cue["duration"])
                # Tolerate float/rounding variance of up to 25ms. No random thresholds.
                if at<start-.025 or at>end+.025 or duration<0 or at+duration>end+.025:
                    result.append(_finding("structural","CUE_OUTSIDE_LINE",line,
                        f"จุดปาด {idx+1}: {at:.4f}s + {duration:.4f}s · ช่วงบรรทัด {start:.4f}–{end:.4f}s"))
                    break
                if last_at is not None and at<last_at-.025:
                    result.append(_finding("structural","CUE_TIME_REVERSES",line,
                        f"จุดปาด {idx+1}: {at:.4f}s เร็วกว่าจุดก่อน {last_at:.4f}s"))
                    break
                last_at=at
            for idx,(left,right) in enumerate(zip(cues,cues[1:])):
                overflow=(float(left["start_time"])+float(left["duration"])
                          -float(right["start_time"]))
                if overflow>.05:
                    result.append(_finding("structural","CUE_OVERLAP",line,
                        f"จุดปาด {idx+1} ทับจุด {idx+2} {overflow:.3f}s"))
                    break
        if line["timing_status"]=="estimated":
            result.append(_finding("unverified","ESTIMATED_SWEEP",line,
                f"บรรทัด {line['position']+1} ระบุ timing_status=estimated · ต้องฟังเพลงยืนยัน ไม่ถือว่าผิดแน่"))
    return result


def scan(workspace,progress=None,cancel=None):
    """Scan only current lyric versions; preserve every previous audit/review."""
    init(workspace)
    run=uuid.uuid4().hex
    totals={"processed":0,"total":0,"structural_songs":0,
            "estimated_songs":0,"blocked_songs":0,"findings":0}
    with core.WRITE_LOCK,core.connect(workspace) as db:
        rows=db.execute("""SELECT s.id AS song_id,v.id AS version_id,
                                  v.timing_status,v.origin
             FROM xstage_songs s JOIN xstage_lyric_versions v
               ON v.song_id=s.id AND v.is_current=1
             ORDER BY s.code""").fetchall()
        totals["total"]=len(rows)
        db.execute("""INSERT INTO xstage_swipe_audit_runs(id,started_at,status)
                      VALUES (?,?,'running')""",(run,core.now()))
        db.commit()
        for entry in rows:
            if cancel and cancel.is_set(): break
            song_id=entry["song_id"]
            version_id=entry["version_id"]
            db.execute("SAVEPOINT swipe_audit_song")
            try:
                lines=core.get_version_lines(db,version_id)
                results=analyze(entry,lines)
                categories={x["category"] for x in results}
                totals["structural_songs"]+=int("structural" in categories)
                totals["estimated_songs"]+=int("unverified" in categories)
                totals["blocked_songs"]+=int("blocked" in categories)
                for finding in results:
                    db.execute("""INSERT INTO xstage_swipe_findings(
                      run_id,song_id,version_id,category,rule,line_position,
                      line_start,line_end,excerpt,evidence,detected_at
                      ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                      (run,song_id,version_id,finding["category"],finding["rule"],
                       finding["line_position"],finding["line_start"],finding["line_end"],
                       finding["excerpt"],finding["evidence"],core.now()))
                totals["findings"]+=len(results)
                db.execute("RELEASE SAVEPOINT swipe_audit_song")
            except Exception:
                db.execute("ROLLBACK TO SAVEPOINT swipe_audit_song")
                db.execute("RELEASE SAVEPOINT swipe_audit_song")
                raise
            totals["processed"]+=1
            if totals["processed"]%64==0:
                db.execute("""UPDATE xstage_swipe_audit_runs
                     SET songs_checked=?,structural_songs=?,estimated_songs=?,blocked_songs=?
                     WHERE id=?""",(totals["processed"],totals["structural_songs"],
                                    totals["estimated_songs"],totals["blocked_songs"],run))
                db.commit()
            if progress: progress(dict(totals),f"เพลง {totals['processed']:,}/{totals['total']:,}")
        db.execute("""UPDATE xstage_swipe_audit_runs
            SET songs_checked=?,structural_songs=?,estimated_songs=?,blocked_songs=?,
                finished_at=?,status=? WHERE id=?""",
                (totals["processed"],totals["structural_songs"],
                 totals["estimated_songs"],totals["blocked_songs"],core.now(),
                 "cancelled" if cancel and cancel.is_set() else "completed",run))
        db.commit()
    return {"run_id":run,**totals,
            "cancelled":bool(cancel and cancel.is_set())}


def _latest_complete(db):
    row=db.execute("""SELECT * FROM xstage_swipe_audit_runs
                   WHERE status='completed'
                   ORDER BY finished_at DESC,started_at DESC LIMIT 1""").fetchone()
    return dict(row) if row else None


def list_findings(workspace,category="structural",limit=100,offset=0):
    init(workspace)
    if category not in ("structural","unverified","blocked","all"):
        raise ValueError("ประเภทความเสี่ยงไม่ถูกต้อง")
    limit=max(1,min(int(limit),250))
    offset=max(0,int(offset))
    with core.connect(workspace) as db:
        latest=_latest_complete(db)
        if not latest:
            return {"run":None,"total":0,"rows":[]}
        condition="" if category=="all" else "AND f.category=?"
        args=[latest["id"]]+([] if category=="all" else [category])
        totals=db.execute("""SELECT COUNT(DISTINCT f.song_id)
             FROM xstage_swipe_findings f
             JOIN xstage_lyric_versions v ON v.id=f.version_id AND v.is_current=1
             WHERE f.run_id=? """+condition,args).fetchone()[0]
        data=db.execute("""SELECT f.song_id,s.code,xc.export_code,s.title,s.artist,m.extension,
            f.version_id,f.category,f.rule,f.line_position,
            f.line_start,f.line_end,f.excerpt,f.evidence,f.detected_at,
            (SELECT r.action FROM xstage_swipe_reviews r
             WHERE r.song_id=f.song_id AND r.version_id=f.version_id
             ORDER BY r.id DESC LIMIT 1) AS review_status
            FROM xstage_swipe_findings f
            JOIN xstage_songs s ON s.id=f.song_id
             LEFT JOIN xstage_song_export_codes xc ON xc.song_id=s.id
            JOIN xstage_media m ON m.id=s.media_id
            JOIN xstage_lyric_versions v ON v.id=f.version_id AND v.is_current=1
            WHERE f.run_id=? """+condition+"""
            GROUP BY f.song_id
            ORDER BY CASE f.category WHEN 'structural' THEN 0
                    WHEN 'unverified' THEN 1 ELSE 2 END,
                    s.code ASC LIMIT ? OFFSET ?""",args+[limit,offset]).fetchall()
        songs=[]
        for row in data:
            item=dict(row)
            findings=[dict(x) for x in db.execute("""SELECT category,rule,
                line_position,line_start,line_end,excerpt,evidence
                FROM xstage_swipe_findings
                WHERE run_id=? AND song_id=? AND version_id=?
                """+("" if category=="all" else " AND category=?")+"""
                ORDER BY line_position,rule LIMIT 40""",
                [latest["id"],item["song_id"],item["version_id"]]+
                ([] if category=="all" else [category]))]
            item["findings"]=findings
            songs.append(item)
        return {"run":latest,"total":totals,"rows":songs}


def history(workspace,limit=30):
    init(workspace)
    with core.connect(workspace) as db:
        runs=[dict(x) for x in db.execute("""SELECT * FROM xstage_swipe_audit_runs
                  ORDER BY started_at DESC LIMIT ?""",(max(1,min(limit,100)),))]
        reviews=[dict(x) for x in db.execute("""SELECT r.*,s.code,xc.export_code,s.title
           FROM xstage_swipe_reviews r JOIN xstage_songs s ON s.id=r.song_id
           LEFT JOIN xstage_song_export_codes xc ON xc.song_id=s.id
           ORDER BY r.id DESC LIMIT 60""")]
        return {"runs":runs,"reviews":reviews}


def review(workspace,song_id,version_id,action,note=""):
    if action not in ("confirmed","passed","needs-review"):
        raise ValueError("สถานะผลทดลองไม่ถูกต้อง")
    note=str(note).strip()
    if len(note)>800:
        raise ValueError("หมายเหตุยาวเกิน 800 ตัวอักษร")
    init(workspace)
    with core.WRITE_LOCK,core.connect(workspace) as db:
        row=db.execute("""SELECT 1 FROM xstage_lyric_versions
                           WHERE id=? AND song_id=?""",
                           (version_id,song_id)).fetchone()
        if not row: raise ValueError("ไม่พบเวอร์ชันเพลงที่ทดลอง")
        db.execute("""INSERT INTO xstage_swipe_reviews
           (song_id,version_id,action,note,created_at)
           VALUES (?,?,?,?,?)""",(song_id,version_id,action,note,core.now()))
        return {"saved":True}


def open_original(workspace,song_id,version_id):
    """Explicit user action: launch actual original media in Windows default player.

    This is not a karaoke-with-lyrics preview. A normal media/MIDI player may
    play sound only. The user must verify lyric sweep in a compatible player.
    """
    if os.name!="nt":
        raise ValueError("การเปิดไฟล์ต้นฉบับรองรับเฉพาะ Windows")
    init(workspace)
    with core.WRITE_LOCK,core.connect(workspace) as db:
        media=db.execute("""SELECT m.* FROM xstage_songs s
            JOIN xstage_media m ON m.id=s.media_id WHERE s.id=?""",
            (song_id,)).fetchone()
        version=db.execute("""SELECT 1 FROM xstage_lyric_versions
            WHERE id=? AND song_id=?""",(version_id,song_id)).fetchone()
        if media is None or version is None:
            raise ValueError("ไม่พบเพลงและ Lyrics Version")
        source=core.source_for_build(workspace,db,media)
        if source.suffix.lower() not in core.MEDIA_EXT:
            raise ValueError("ชนิดไฟล์ต้นฉบับไม่รองรับ")
        os.startfile(str(source))
        db.execute("""INSERT INTO xstage_swipe_reviews
           (song_id,version_id,action,note,created_at)
           VALUES (?,?,?,?,?)""",
           (song_id,version_id,"opened","เปิดต้นฉบับผ่านโปรแกรม Windows · ไม่ยืนยันการปาดสี",core.now()))
        return {"opened":True,"filename":source.name,
                "note":"โปรแกรมเล่นสื่อทั่วไปอาจไม่แสดงการปาดสี ใช้ X-Stage Karaoke ที่รองรับสำหรับการยืนยันจริง"}
