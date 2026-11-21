"""Manual karaoke lyric repair and build approval without inventing CUR timing.

All edits are versioned in the existing xstage_ SQLite catalog. An edited
song is only build-ready in the UI after an explicit approval of that exact
lyric version. Draft text is kept for edits not yet completely timed.
"""
from __future__ import annotations

import math
import uuid
from pathlib import Path
import plus_core as core

SCHEMA = """
CREATE TABLE IF NOT EXISTS xstage_manual_reviews (
 song_id TEXT PRIMARY KEY REFERENCES xstage_songs(id),
 version_id TEXT, decision TEXT NOT NULL CHECK(decision IN ('skip','approved','pending')),
 updated_at TEXT NOT NULL
);
"""

_INITIALIZED = set()

def init(workspace):
    """Install review schema once; read-only UI actions never need DDL locks."""
    key=str(core.db_path(workspace).resolve())
    if key in _INITIALIZED:
        return
    with core.WRITE_LOCK:
        if key in _INITIALIZED:
            return
        with core.connect(workspace) as db:
            db.executescript(SCHEMA)
        _INITIALIZED.add(key)

BASE = """
 FROM xstage_songs s JOIN xstage_media m ON m.id=s.media_id
 LEFT JOIN xstage_lyric_versions v ON v.song_id=s.id AND v.is_current=1
 LEFT JOIN xstage_lyric_drafts d ON d.song_id=s.id
 LEFT JOIN xstage_manual_reviews r ON r.song_id=s.id
  AND COALESCE(r.version_id,'')=COALESCE(v.id,'')
 LEFT JOIN xstage_exports e ON e.song_id=s.id
"""

def _status_expr():
    return """CASE
      WHEN COALESCE(r.decision,'')='pending' AND
        v.id IS NOT NULL AND v.timing_status!='incomplete' THEN 'review'
      WHEN COALESCE(r.decision,'')='pending' THEN 'incomplete'
      WHEN v.id IS NULL AND d.song_id IS NOT NULL THEN 'untimed'
      WHEN v.id IS NULL THEN 'missing'
      WHEN v.timing_status='incomplete' THEN 'incomplete'
      WHEN v.timing_status='estimated'
        AND COALESCE(r.decision,'')!='approved' THEN 'review'
      ELSE 'ready' END"""

def queue(workspace, query="", filter="pending", offset=0, limit=6):
    init(workspace)
    if filter not in ("pending","all","skipped","missing","incomplete","review"):
        raise ValueError("ตัวกรองรายการไม่ถูกต้อง")
    limit=max(1,min(int(limit),50))
    offset=max(0,int(offset))
    term="%"+str(query).strip()[:100]+"%"
    status=_status_expr()
    select="""SELECT s.id,s.code,s.title,s.artist,s.original_code,
       m.extension,v.id AS version_id,v.timing_status,d.reason AS draft_reason,
       COALESCE(r.decision,'') AS decision,e.output_path,
       """+status+" AS review_status "+BASE
    conditions=""" WHERE (s.title LIKE ? OR s.artist LIKE ? OR s.original_code LIKE ?)
    """
    params=[term,term,term]
    if filter=="pending":
        conditions+=" AND ("+status+")!='ready' AND COALESCE(r.decision,'')!='skip'"
    elif filter=="skipped":
        conditions+=" AND r.decision='skip'"
    elif filter!="all":
        if filter=="missing":
            conditions+=" AND ("+status+") IN ('missing','untimed')"
        else:
            conditions+=" AND ("+status+")=?"
            params.append(filter)
        conditions+=" AND COALESCE(r.decision,'')!='skip'"
    with core.connect(workspace) as db:
        rows=db.execute(select+conditions+" ORDER BY s.code DESC LIMIT ? OFFSET ?",
                        params+[limit,offset]).fetchall()
        count=db.execute("SELECT COUNT(*) "+BASE+conditions,params).fetchone()[0]
    return {"rows":[dict(x) for x in rows], "total":count,"offset":offset,
            "limit":limit}

def approved_build_ids(workspace,exclude=None):
    """Query entire ready catalog, not only the current UI page."""
    init(workspace)
    excluded=set(exclude or ())
    if len(excluded)>300000 or any(not isinstance(v,str) for v in excluded):
        raise ValueError("รายการยกเว้นไม่ถูกต้อง")
    with core.connect(workspace) as db:
        rows=db.execute("""SELECT s.id """+BASE+"""
            WHERE v.id IS NOT NULL AND v.timing_status!='incomplete'
              AND """+_status_expr()+"""='ready'
              AND (e.version_id IS NULL OR e.version_id!=v.id
                   OR COALESCE(e.output_path,'')='') ORDER BY s.code""").fetchall()
    return [x[0] for x in rows if x[0] not in excluded]


def approved_selected_ids(workspace, song_ids):
    """Check only explicit selected IDs; avoid loading the entire song catalog.

    The all-ready workflow uses approved_build_ids() once. Explicit builds
    need a small membership query, even when SQLite stores 100k+ songs.
    """
    requested=list(dict.fromkeys(song_ids))
    if len(requested)>5000 or any(not isinstance(s,str) for s in requested):
        raise ValueError("รายการเพลงที่เลือกไม่ถูกต้อง")
    if not requested:
        return set()
    init(workspace)
    ready=set()
    with core.connect(workspace) as db:
        for start in range(0,len(requested),400):
            part=requested[start:start+400]
            matches=db.execute("""SELECT s.id """+BASE+"""
                WHERE s.id IN ("""+",".join("?" for _ in part)+""")
                  AND v.id IS NOT NULL AND v.timing_status!='incomplete'
                  AND """+_status_expr()+"""='ready'
                  AND (e.version_id IS NULL OR e.version_id!=v.id
                       OR COALESCE(e.output_path,'')='')""",part)
            ready.update(row[0] for row in matches)
    return ready

def skip(workspace,song_id,version_id):
    init(workspace)
    with core.WRITE_LOCK,core.connect(workspace) as db:
        current=db.execute("""SELECT s.id,v.id AS version_id FROM xstage_songs s
          LEFT JOIN xstage_lyric_versions v ON v.song_id=s.id AND v.is_current=1
          WHERE s.id=?""",(song_id,)).fetchone()
        if not current or (current["version_id"] or None)!=(version_id or None):
            raise ValueError("เพลงหรือเวอร์ชันเปลี่ยนไป กรุณาโหลดรายการอีกครั้ง")
        db.execute("""INSERT INTO xstage_manual_reviews
          (song_id,version_id,decision,updated_at) VALUES (?,?,?,?)
          ON CONFLICT(song_id) DO UPDATE SET version_id=excluded.version_id,
          decision=excluded.decision,updated_at=excluded.updated_at""",
          (song_id,version_id,"skip",core.now()))
    return {"skipped":True}

def approve(workspace,song_id,version_id):
    init(workspace)
    with core.WRITE_LOCK,core.connect(workspace) as db:
        row=db.execute("""SELECT id,timing_status FROM xstage_lyric_versions
                 WHERE song_id=? AND is_current=1""",(song_id,)).fetchone()
        if not row or row["id"]!=version_id or row["timing_status"]=="incomplete":
            raise ValueError("เนื้อร้องยังไม่ครบหรือเปลี่ยนเวอร์ชันแล้ว")
        db.execute("""INSERT INTO xstage_manual_reviews
          (song_id,version_id,decision,updated_at) VALUES (?,?,?,?)
          ON CONFLICT(song_id) DO UPDATE SET version_id=excluded.version_id,
          decision=excluded.decision,updated_at=excluded.updated_at""",
          (song_id,version_id,"approved",core.now()))
    return {"approved":True,"version_id":version_id}

def _number(value,label):
    if isinstance(value,bool):
        raise ValueError(label+" ไม่ใช่ตัวเลขเวลา")
    try: num=float(value)
    except (ValueError,TypeError): raise ValueError(label+" ต้องเป็นตัวเลข")
    if not math.isfinite(num) or not 0<=num<=86400:
        raise ValueError(label+" ต้องอยู่ในช่วง 0–86400 วินาที")
    return round(num,5)

def _normalize_lines(lines):
    """Only source/manual onset values may become cues; no interpolation."""
    if not isinstance(lines,list) or not 1<=len(lines)<=400:
        raise ValueError("กรุณาป้อนเนื้อร้อง 1–400 บรรทัด")
    saved=[]
    draft=[]
    total=0
    ready=True
    for i,item in enumerate(lines):
        if not isinstance(item,dict):
            raise ValueError("โครงสร้างเนื้อร้องไม่ถูกต้อง")
        raw=str(item.get("text") or "").rstrip("\r\n")
        if not raw.strip():
            continue
        if len(raw)>400 or "\x00" in raw or "\n" in raw or "\r" in raw:
            raise ValueError(f"บรรทัด {i+1}: ข้อความเกิน 400 อักขระหรือมีอักขระต้องห้าม")
        total+=len(raw)
        if total>50000:
            raise ValueError("เนื้อร้องรวมยาวเกินขอบเขต")
        draft.append(raw)
        start=item.get("start")
        end=item.get("end")
        segments=item.get("segments") or []
        starts=item.get("starts") or []
        if start in (None,"") or end in (None,"") or not starts:
            ready=False
            continue
        start=_number(start,f"เริ่มบรรทัด {i+1}")
        end=_number(end,f"จบบรรทัด {i+1}")
        if end<=start:
            raise ValueError(f"บรรทัด {i+1}: เวลาจบต้องมากกว่าเวลาเริ่ม")
        if not isinstance(segments,list) or not isinstance(starts,list):
            raise ValueError(f"บรรทัด {i+1}: รูปแบบการแบ่งคำและเวลาไม่ถูกต้อง")
        if len(segments)!=len(starts) or not 1<=len(starts)<=400:
            raise ValueError(f"บรรทัด {i+1}: จำนวนคำกับเวลาปาดไม่เท่ากัน")
        if any(not isinstance(s,str) or not s or len(s)>400 for s in segments):
            raise ValueError(f"บรรทัด {i+1}: มีคำว่างหรือคำยาวผิดปกติ")
        if "".join(segments)!=raw:
            raise ValueError(f"บรรทัด {i+1}: ข้อความที่แบ่งคำต้องตรงกับเนื้อร้องทุกตัว")
        times=[_number(t,f"เวลาคำ {k+1} บรรทัด {i+1}") for k,t in enumerate(starts)]
        if times[0]<start-0.001 or times[-1]>=end or any(
                times[k]<times[k-1] for k in range(1,len(times))):
            raise ValueError(f"บรรทัด {i+1}: เวลาปาดไม่อยู่ในช่วงเริ่ม–จบหรือเรียงย้อนหลัง")
        cues=[(segment,at,round(max(0,(times[k+1] if k+1<len(times) else end)-at),5))
              for k,(segment,at) in enumerate(zip(segments,times))]
        saved.append((raw,start,end,cues,"estimated"))
    if not draft:
        raise ValueError("กรุณาพิมพ์เนื้อร้องอย่างน้อยหนึ่งบรรทัด")
    return saved, draft, ready and len(saved)==len(draft)

def save(workspace,song_id,base_version,lines):
    """Optimistic version check, separate complete/manual vs partial draft."""
    init(workspace)
    parsed,draft,complete=_normalize_lines(lines)
    with core.WRITE_LOCK,core.connect(workspace) as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("""SELECT s.*,v.id AS active_version
                    FROM xstage_songs s LEFT JOIN xstage_lyric_versions v
                    ON v.song_id=s.id AND v.is_current=1 WHERE s.id=?""",
                    (song_id,)).fetchone()
        if not row:
            raise ValueError("ไม่พบเพลงในคลัง")
        if (row["active_version"] or None)!=(base_version or None):
            raise ValueError("เพลงนี้ถูกแก้ไขในหน้าต่างอื่น กรุณาโหลดใหม่ก่อนบันทึก")
        if parsed:
            version=uuid.uuid4().hex
            signature=core.content_sha(parsed)
            previous=db.execute("""SELECT id FROM xstage_lyric_versions
                WHERE song_id=? AND content_sha256=?""",(song_id,signature)).fetchone()
            if previous:
                version=previous["id"]
            else:
                db.execute("""INSERT INTO xstage_lyric_versions
                 (id,song_id,content_sha256,source_sha256,origin,timing_status,
                  title,artist,created_at,is_current)
                 VALUES (?,?,?,NULL,'manual',?,?,?,?,0)""",
                 (version,song_id,signature,
                  "estimated" if complete else "incomplete",
                  row["title"],row["artist"],core.now()))
                for i,(txt,start,end,cues,_) in enumerate(parsed):
                    cur=db.execute("""INSERT INTO xstage_lyric_lines
                       (version_id,position,text,normalized_text,start_time,
                        end_time,timing_status) VALUES (?,?,?,?,?,?,?)""",
                        (version,i,txt,core.norm(txt),start,end,"estimated"))
                    for k,(part,at,duration) in enumerate(cues):
                        db.execute("""INSERT INTO xstage_lyric_cues
                         (line_id,position,text,start_time,duration)
                         VALUES (?,?,?,?,?)""",
                         (cur.lastrowid,k,part,at,duration))
            db.execute("UPDATE xstage_lyric_versions SET is_current=0 WHERE song_id=?",(song_id,))
            db.execute("UPDATE xstage_lyric_versions SET is_current=1 WHERE id=?",(version,))
        else:
            version=row["active_version"]
        if complete:
            db.execute("DELETE FROM xstage_lyric_drafts WHERE song_id=?",(song_id,))
        else:
            db.execute("""INSERT INTO xstage_lyric_drafts
             (song_id,source_path,title,artist,raw_text,reason,updated_at)
             VALUES (?,?,?,?,?,?,?)
             ON CONFLICT(song_id) DO UPDATE SET raw_text=excluded.raw_text,
             reason=excluded.reason,updated_at=excluded.updated_at""",
             (song_id,"manual",row["title"],row["artist"],
              "\n".join(draft),"Manual timing incomplete",core.now()))
        db.execute("""INSERT INTO xstage_manual_reviews
          (song_id,version_id,decision,updated_at) VALUES (?,?,?,?)
          ON CONFLICT(song_id) DO UPDATE SET version_id=excluded.version_id,
          decision=excluded.decision,updated_at=excluded.updated_at""",
          (song_id,version,"pending",core.now()))
    return {"version_id":version,"complete":complete,
            "saved_lines":len(parsed),"total_lines":len(draft),
            "message":("บันทึกครบแล้ว · รอฟังยืนยันก่อนสร้าง .X"
                       if complete else "เก็บเนื้อร้องที่มีเวลาบางส่วนและฉบับร่างแล้ว · ยังสร้าง .X ไม่ได้")}

def inspect_cue_issues(lines):
    """Evidence and review advice only. Does not infer correct lyrics or times.

    Checks explicit text/cue alignment and recorded numeric time invariants.
    Unverified estimated timing is a listening prompt, never a confirmed fault.
    """
    items=[]
    def add(kind,rule,index,found,advice):
        items.append({"category":kind,"rule":rule,"line_position":index,
                      "found":found,"suggestion":advice})
    if not lines:
        add("missing","NO_LYRICS",-1,
            "เพลงนี้ยังไม่มีข้อความเนื้อร้องในฐานข้อมูล",
            "เพิ่มเนื้อร้องหรือวางข้อความ แล้วจับเวลาจากเสียงต้นฉบับ")
        return items
    for index,line in enumerate(lines):
        raw=str(line.get("text") or "")
        if not raw.strip():
            continue
        start=line.get("start")
        end=line.get("end")
        segments=line.get("segments") or []
        timestamps=line.get("starts") or []
        if start is None or end is None or start=="" or end=="":
            add("missing","LINE_UNTIMED",index,
                "มีเนื้อร้องแต่ยังไม่มีเวลาเริ่มหรือจบ",
                "ฟังต้นฉบับแล้วกดจับเวลาเริ่มและจบบรรทัดนี้")
            continue
        try:
            start,end=float(start),float(end)
        except (ValueError,TypeError):
            add("structural","LINE_TIME_INVALID",index,
                "เวลาเริ่มหรือเวลาจบไม่ใช่ตัวเลข",
                "แก้เวลาเป็นวินาทีจากเพลงต้นฉบับ")
            continue
        if not all(math.isfinite(v) for v in (start,end)) or start<0 or end<=start:
            add("structural","LINE_RANGE_INVALID",index,
                "เวลาจบบรรทัดไม่มากกว่าเวลาเริ่ม หรือค่าเวลาไม่ถูกต้อง",
                "ตรวจเวลาเริ่มและเวลาจบจากเสียงจริง")
            continue
        if not segments or not timestamps:
            add("missing","CUES_MISSING",index,
                "มีเนื้อร้องและช่วงเวลา แต่ยังไม่มีจุดปาดคำ",
                "แบ่งคำด้วย | แล้วกดจับเวลาต้นแต่ละคำขณะเล่นจริง")
            continue
        if len(segments)!=len(timestamps) or any(v in ("",None) for v in timestamps):
            add("missing","CUES_PARTIAL",index,
                f"มี {len(segments)} ช่วงข้อความ แต่เวลาเริ่มปาดครบเพียง {sum(v not in ('',None) for v in timestamps)} จุด",
                "เลือกคำที่ยังขาดเวลาแล้วกดจับเวลาปาดคำ หรือกรอกเวลาที่ตรวจจากเสียงจริง")
            continue
        if "".join(str(v) for v in segments)!=raw:
            cue_text="".join(str(v) for v in segments)
            at=next((j for j,(a,b) in enumerate(zip(raw,cue_text)) if a!=b),
                    min(len(raw),len(cue_text)))
            add("structural","CUES_TEXT_MISMATCH",index,
                f"ข้อความเริ่มต่างกันบริเวณอักขระที่ {at+1}: "
                f"เนื้อร้อง «{raw[max(0,at-8):at+26]}» · "
                f"จุดปาด «{cue_text[max(0,at-8):at+26]}»",
                "แก้ข้อความหรือแบ่งคำใหม่โดยรักษาช่องว่าง สระ และวรรณยุกต์ให้ครบ")
        try:
            values=[float(v) for v in timestamps]
        except (TypeError,ValueError):
            add("structural","CUE_TIME_INVALID",index,
                "มีเวลาปาดที่ไม่ใช่ตัวเลข",
                "กรอกเวลาเริ่มปาดของแต่ละคำเป็นวินาทีที่ตรวจได้จริง")
            continue
        if (any(not math.isfinite(v) for v in values) or
                values[0]<start-.001 or values[-1]>=end or
                any(values[j]<values[j-1] for j in range(1,len(values)))):
            add("structural","CUES_TIME_OUT_OF_RANGE",index,
                "เวลาปาดอยู่นอกบรรทัดหรือเรียงย้อนหลัง",
                "เลื่อนฟังท่อนนี้แล้วจับเวลาปาดแต่ละคำใหม่")
        if line.get("timing")=="estimated":
            add("unverified","ESTIMATED_TIMING",index,
                "เวลาบรรทัดนี้เป็นค่าประมาณ ยังไม่ใช่หลักฐานว่าปาดผิด",
                "ทดลองฟังและดูการปาดสี หากตรงแล้วจึงกดยืนยัน")
    return items


def detail(workspace,song_id):
    """Return all source lines, including untimed draft tail, for manual repair."""
    init(workspace)
    with core.connect(workspace) as db:
        song=db.execute("""SELECT s.id,s.code,s.title,s.artist,
                  v.id AS version_id,v.timing_status,
                  COALESCE(r.decision,'') AS decision
             FROM xstage_songs s
             LEFT JOIN xstage_lyric_versions v ON v.song_id=s.id AND v.is_current=1
             LEFT JOIN xstage_manual_reviews r ON r.song_id=s.id
              AND COALESCE(r.version_id,'')=COALESCE(v.id,'')
             WHERE s.id=?""",(song_id,)).fetchone()
        if song is None:
            raise ValueError("ไม่พบเพลงในฐานข้อมูล")
        source=[]
        if song["version_id"]:
            for line,cues in core.get_version_lines(db,song["version_id"]):
                cues=core.display_cues(line["text"],cues)
                source.append({
                  "text":line["text"],"start":line["start_time"],
                  "end":line["end_time"],
                  "segments":[c["text"] for c in cues],
                  "starts":[c["start_time"] for c in cues],
                  "timing":line["timing_status"],
                })
        draft=db.execute("""SELECT raw_text,reason FROM xstage_lyric_drafts
                 WHERE song_id=?""",(song_id,)).fetchone()
        if draft:
            draft_lines=[x for x in draft["raw_text"].splitlines() if x.strip()]
            # The partial CUR version normally contains a timed prefix of LYR.
            # Match by order AND content, and use full LYR draft as canonical
            # body only if the prefix alignment is exact.
            prefix=all(i<len(draft_lines) and
                       source[i]["text"]==draft_lines[i]
                       for i in range(min(len(source),len(draft_lines))))
            if prefix and len(draft_lines)>len(source):
                source += [{"text":x,"start":None,"end":None,
                            "segments":[],"starts":[],"timing":"untimed"}
                           for x in draft_lines[len(source):]]
            elif not source:
                source=[{"text":x,"start":None,"end":None,
                         "segments":[],"starts":[],"timing":"untimed"}
                        for x in draft_lines]
        findings=inspect_cue_issues(source)
        # Include structural duration/overlap evidence from the existing
        # risk inspector as well. Unlike timing guesses, this is grounded in
        # the immutable SQLite cue rows for the selected lyric version.
        if song["version_id"]:
            import risk_audit
            version=db.execute(
                "SELECT * FROM xstage_lyric_versions WHERE id=?",
                (song["version_id"],)).fetchone()
            timed_pairs=core.get_version_lines(db,song["version_id"])
            guidance={
                "CUE_OVERLAP":"ตรวจเวลาจุดปาดที่ทับกัน แล้วจับเวลาคำตามเสียงต้นฉบับ",
                "CUE_OUTSIDE_LINE":"แก้ช่วงเวลาเริ่ม–จบหรือจุดปาดให้อยู่ในช่วงบรรทัด",
                "CUE_TIME_REVERSES":"จับเวลาปาดตามลำดับที่ได้ยินใหม่",
                "CUE_TEXT_DIFFERS":"แบ่งคำใหม่ให้ข้อความตรงกับเนื้อร้องทุกอักขระ",
                "NO_SWEEP_CUES":"จับจุดเริ่มปาดของคำที่ยังไม่มี",
                "INVALID_LINE_RANGE":"ตรวจเวลาเริ่ม–จบจากเพลงต้นฉบับ",
                "INCOMPLETE_CUR":"ตรวจบรรทัดและ CUR ที่ขาด ไม่สร้างเวลาแทนต้นฉบับ",
                "EMPTY_TIMED_VERSION":"เพิ่มเนื้อร้องและจับเวลาปาดใหม่",
                "ESTIMATED_SWEEP":"ฟังจริงก่อนยืนยันว่าเวลาปาดถูก",
            }
            seen={(x["line_position"],x["rule"]) for x in findings}
            for recorded in risk_audit.analyze(version,timed_pairs):
                key=(recorded["line_position"],recorded["rule"])
                if key in seen:
                    continue
                findings.append({
                    "category":("missing" if recorded["category"]=="blocked"
                                else recorded["category"]),
                    "rule":recorded["rule"],
                    "line_position":recorded["line_position"],
                    "found":recorded["evidence"],
                    "suggestion":guidance.get(recorded["rule"],
                        "ตรวจเนื้อร้องและจังหวะปาดกับเพลงจริง")
                })
                seen.add(key)
        return {"song":dict(song),"lines":source,
                "findings":findings,
                "draft_reason":draft["reason"] if draft else None,
                "has_lyrics":bool(source)}

def annotate_rows(workspace,rows):
    """Add readiness and review labels to existing paginated catalog rows."""
    if not rows:
        return rows
    init(workspace)
    ids=[r["id"] for r in rows]
    args=",".join("?" for _ in ids)
    with core.connect(workspace) as db:
        records=db.execute("""SELECT song_id,version_id,decision
            FROM xstage_manual_reviews WHERE song_id IN ("""+args+")",ids)
        flags={r["song_id"]:(r["version_id"],r["decision"]) for r in records}
    out=[]
    for row in rows:
        r=dict(row)
        decision=flags.get(r["id"])
        decision=decision[1] if decision and (
            decision[0] or None)==(r.get("version_id") or None) else ""
        if decision=="pending":
            status="review" if r.get("version_id") and r.get("timing_status")!="incomplete" else "incomplete"
        elif not r.get("version_id"):
            status="untimed" if r.get("draft_reason") else "missing"
        elif r.get("timing_status")=="incomplete":
            status="incomplete"
        elif r.get("timing_status")=="estimated" and decision!="approved":
            status="review"
        else:
            status="ready"
        r["manual_status"]=status
        r["manual_decision"]=decision
        out.append(r)
    return out


def build_catalog(workspace, status="ready", offset=0, limit=40, query=""):
    """Bounded, status-filtered XMID/X-Media catalog for infinite scrolling.

    Readiness is computed from the current lyric version and explicit
    approval, never from client-side state or a stale downloaded page.
    """
    if status not in ("ready", "converted", "attention"):
        raise ValueError("สถานะกลุ่มเพลงไม่ถูกต้อง")
    init(workspace)
    offset=max(0,int(offset))
    limit=max(1,min(int(limit),80))
    term="%"+str(query).strip()[:100].replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%"
    expr=_status_expr()
    converted="(e.version_id=v.id AND COALESCE(e.output_path,'')!='')"
    condition=("("+expr+")!='ready'" if status=="attention" else
        "("+expr+")='ready' AND "+(converted if status=="converted" else "NOT "+converted))
    sql="""SELECT s.id,s.code,s.title,s.artist,s.original_code,
       m.extension,v.id AS version_id,v.timing_status,
       d.reason AS draft_reason,e.output_path,
       COALESCE(r.decision,'') AS manual_decision,
       """+expr+""" AS manual_status """+BASE+"""
       WHERE (s.title LIKE ? ESCAPE '\\' OR s.artist LIKE ? ESCAPE '\\'
           OR s.original_code LIKE ? ESCAPE '\\')
       AND """+condition+"""
       ORDER BY s.code DESC LIMIT ? OFFSET ?"""
    with core.connect(workspace) as db:
        rows=[dict(row) for row in db.execute(
            sql,(term,term,term,limit+1,offset))]
    return {"rows":rows[:limit],"has_more":len(rows)>limit,
            "offset":offset+len(rows[:limit])}


def ready_count(workspace):
    """Return a count without transferring a giant catalog to the browser."""
    init(workspace)
    with core.connect(workspace) as db:
        return db.execute("""SELECT COUNT(*) """+BASE+"""
          WHERE v.id IS NOT NULL AND v.timing_status!='incomplete'
            AND """+_status_expr()+"""='ready'
            AND (e.version_id IS NULL OR e.version_id!=v.id
                 OR COALESCE(e.output_path,'')='')""").fetchone()[0]
