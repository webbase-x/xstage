"""Direct NCN batch export without opening a song database."""
from contextlib import contextmanager, ExitStack
import csv
import hashlib
import stat
import string
import time
import json
import os
from pathlib import Path
import re
import tempfile
import uuid
from collections import defaultdict

import ncn_reader as reader
import plus_core as core

LABELS = {
    "title":"title","song":"title","song name":"title","ชื่อเพลง":"title",
    "artist":"artist","singer":"artist","ศิลปิน":"artist","นักร้อง":"artist",
    "key":"key","คีย์":"key","tempo":"tempo","bpm":"tempo","จังหวะ":"tempo",
    "song title":"title","track title":"title","ชื่อ":"title","ชื่อศิลปิน":"artist",
    "นักร้องนำ":"artist","composer":"composer","ผู้แต่ง":"composer",
    "arranger":"arranger","ผู้เรียบเรียง":"arranger",
}
KEY = re.compile(r"(?:[A-G](?:#|b|♯|♭)?(?:m|maj|min|major|minor)?(?:[679]|11|13)?|[-+]?\d{1,2})",re.I)

def clean(value, code):
    value=value.strip()
    if (not value or len(value)>255 or "\ufffd" in value or
        any(ord(c)<32 for c in value) or
        value.casefold() in {code.casefold(),"unknown","untitled","n/a","-","ไม่ทราบ"} or
        re.fullmatch(r"[A-Za-z]?\d{3,}(?:\(\d+\))?",value)):
        return ""
    return value

CREDIT_LABEL = re.compile(r"^(?:credit(?:s)?|created by|sequenced by|programmed by|arranged by|copyright|ผู้จัดทำ|จัดทำโดย|สร้างโดย|ผู้เรียบเรียง|เรียบเรียงโดย|เครดิต|ลิขสิทธิ์)\s*[:=：]\s*\S",re.I)
VENDOR_CREDIT = re.compile(r"^(?:nick[\s_-]*karaoke(?:\s+professional)?|extreme[\s_-]*karaoke|นิค[\s_-]*คาราโอเกะ|เต่า[\s_-]*คาราโอเกะ)$",re.I)

def is_credit(line):
    value=line.strip(" \t.…·•*_-~=<>[]()")
    # Explicit vendor names observed in legacy NCN boundary credits.
    vendor=re.fullmatch(r"(?:(?:music[\s_-]+)?by[\s_-]+)?(?:nick[\s_-]*karaoke|นิค[\s_-]*คาราโอเกะ|เต่า[\s_-]*คาราโอเกะ)(?:[\s_-]+\d{2,4}[- ]?\d{3}[- ]?\d{3,4})?",value,re.I)
    return bool(CREDIT_LABEL.match(value) or VENDOR_CREDIT.fullmatch(value) or vendor or re.fullmatch(r"GMM[\s_-]+Grammy",value,re.I))

def label_value(line):
    m=re.fullmatch(r"\s*[@#]?\s*([^:=：]+?)\s*[:=：]\s*(.*?)\s*",line)
    return (LABELS.get(m[1].strip().casefold()),m[2]) if m else (None,"")

def identify_header(lyr,cur,code, *, lyric_data=None,cursor_data=None,midi_tags=None):
    raw=(bounded_read(Path(lyr),1024*1024)[0] if lyric_data is None else lyric_data).split(b"\x1a",1)[0]
    cursor=bounded_read(Path(cur),2*1024*1024)[0] if cursor_data is None else cursor_data
    if len(raw)>1024*1024 or len(cursor)>2*1024*1024:
        raise ValueError("NCN component exceeds size limit")
    if len(cursor)%2 and cursor[-1:]!=b"\xff":
        raise ValueError("CUR odd length")
    for encoding in ("utf-8-sig","cp874","tis-620"):
        try:
            decoded=raw.decode(encoding)
            break
        except UnicodeError:
            continue
    else:
        raise ValueError("Unsupported LYR encoding")
    rows=decoded.replace("\r\n","\n").replace("\r","\n").split("\n")
    count=len(cursor)//2
    # Anchor layouts in structural evidence, not in the ability to discard
    # arbitrary beginning lyrics until the CUR count happens to fit.
    cuts={}
    if len(rows)>4 and (KEY.fullmatch(rows[2].strip()) or
                         (not rows[2].strip() and rows[3].strip() in ("","."))):
        if not any(label_value(x)[0] for x in rows[:4]):
            cuts[4]={"title":rows[0],"artist":rows[1],"key":rows[2]}
    meta={}
    for i,line in enumerate(rows[:64]):
        key,value=label_value(line)
        if key:
            if key in meta and meta[key]!=value:
                break
            meta[key]=value
        elif not line.strip() or is_credit(line):
            pass
        else:
            break
        if "title" in meta or "artist" in meta:
            cuts[i+1]=dict(meta)
    candidates=[]
    for start,fields in cuts.items():
        # A recognised leading credit may have no CUR. Never drop an
        # ordinary lyric, even when the length happens to fit.
        possible=[start]
        while possible[-1]<len(rows) and is_credit(rows[possible[-1]]):
            possible.append(possible[-1]+1)
        for cut in possible:
            body=rows[cut:]
            while body and not body[-1].strip(" \x00\x1a"):
                body.pop()
            try:
                encoded=[line.encode("cp874") for line in body]
            except UnicodeError:
                continue
            metadata=dict(fields)
            conflict=False
            for key in ("title","artist"):
                recorded=clean(metadata.get(key,""),code)
                tagged=(midi_tags or {}).get(key,"")
                if recorded and tagged and recorded!=tagged:
                    conflict=True
                metadata[key]=recorded or tagged
            if conflict:
                continue
            footer=[]
            while body:
                needed=sum(1+len(line) for line in encoded if line.strip())
                blanks=sum(not line.strip() for line in encoded)
                exact=count in (needed,needed+blanks)
                # Surplus is safe only for independently identified headers
                # with no ambiguity about blank-line CUR consumption.
                surplus=count>needed+blanks
                if needed and (exact or surplus):
                    actual=[x for x in body if x.strip()]
                    details={"header_credit":[x for x in rows[:cut] if is_credit(x)],
                             "footer_credit":list(reversed(footer)),
                             "unused_cursor_values":max(0,count-needed-blanks),
                             "warnings":[k+" missing" for k in ("title","artist") if not metadata[k]]}
                    signature=(metadata,actual,body if count==needed+blanks and blanks else None)
                    candidates.append((0 if exact else 1,signature,(cut,metadata,actual,encoding,details,body)))
                    break
                if not is_credit(body[-1]):
                    break
                footer.append(body.pop())
                encoded.pop()
                while body and not body[-1].strip(" \x00\x1a"):
                    body.pop()
                    encoded.pop()
    if not candidates:
        raise ValueError("Unknown or ambiguous metadata/CUR layout; no guessing")
    rank=min(x[0] for x in candidates)
    unique=[]
    for priority,signature,result in candidates:
        if priority==rank and not any(x[0]==signature for x in unique):
            unique.append((signature,result))
    if len(unique)!=1:
        # Classic NCN has a documented four-row metadata header. Retain
        # measured credits at row five rather than silently shifting all
        # subsequent CUR slots. Only a unique exact shorter layout can
        # take precedence over this full-body convention.
        anchored=[x for x in unique if x[1][0]==4 and 4 in cuts and not any(label_value(y)[0] for y in rows[:4])]
        if len(anchored)==1 and rank==1:
            return anchored[0][1]
        raise ValueError("Unknown or ambiguous metadata/CUR layout; no guessing")
    return unique[0][1]

def scan(root,cancel):
    index=defaultdict(list)
    mids=[]
    for folder,dirs,names in os.walk(root,followlinks=False):
        if cancel is not None and cancel.is_set():
            break
        dirs[:]=sorted(d for d in dirs if not (Path(folder)/d).is_symlink())
        for name in sorted(names):
            path=Path(folder)/name
            ext=path.suffix.casefold()
            if path.is_symlink() or ext not in (".mid",".midi",".lyr",".cur"):
                continue
            index[(str(path.parent).casefold(),path.stem.casefold(),ext)].append(path)
            if ext in (".mid",".midi"):
                mids.append(path)
    return sorted(mids,key=lambda x:(str(x).casefold(),str(x))),index

def companions(midi,index):
    def one(folder,ext):
        items=index.get((str(folder).casefold(),midi.stem.casefold(),ext),[])
        if len(items)>1:
            raise ValueError("Ambiguous companion")
        return items[0] if items else None
    lyr,cur=one(midi.parent,".lyr"),one(midi.parent,".cur")
    if lyr is None and cur is None:
        found=reader.describe(midi)
        if found and found[1]=="song":
            root,_,subdir,_=found
            lyr=one(root/"Lyrics"/subdir,".lyr")
            cur=one(root/"Cursor"/subdir,".cur")
    if lyr is None or cur is None:
        missing = "/".join(label for label, part in (("LYR", lyr), ("CUR", cur)) if part is None)
        raise ValueError("Missing exact matching " + missing)
    return {"midi":str(midi),"lyrics":str(lyr),"cursor":str(cur),"code":midi.stem,"missing":[]}

def file_stamp(path):
    info=path.stat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise ValueError("Component must be a regular non-symlink file")
    return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)

def bounded_read(path,limit):
    before=file_stamp(path)
    if before[2]>limit:
        raise ValueError("NCN component exceeds size limit")
    def descriptor_stamp(stream):
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("NCN component changed during read")
        return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
    with path.open("rb") as stream:
        if descriptor_stamp(stream)!=before:
            raise ValueError("NCN component changed during read")
        raw=stream.read(limit+1)
        if descriptor_stamp(stream)!=before:
            raise ValueError("NCN component changed during read")
    if len(raw)>limit or len(raw)!=before[2] or file_stamp(path)!=before:
        raise ValueError("NCN component changed during read")
    return raw,before

def explicit_midi_tags(events,code):
    values=defaultdict(set)
    for tick,track,order,tag,label in events:
        # Only explicit labels at tick zero, not generic track names or lyrics.
        if tick!=0 or tag not in (1,3):
            continue
        match=re.fullmatch(r"\s*[@#]?\s*([^:=：]+?)\s*[:=：]\s*(.*?)\s*",label)
        if match:
            field=LABELS.get(match[1].strip().casefold())
            value=clean(match[2],code)
            if field in ("title","artist") and value:
                values[field].add(value)
    if any(len(v)>1 for v in values.values()):
        raise ValueError("Conflicting explicit MIDI metadata")
    return {k:next(iter(v)) for k,v in values.items()}

def measured_boundaries(doc,duration):
    # CUR stores onsets, not line endings. Use the next measured line start
    # and actual MIDI end, never the legacy guessed four-second final line.
    for i,line in enumerate(doc["lines"]):
        cues=line["syllables"]
        if not cues:
            raise ValueError("Missing measured CUR onsets")
        end=doc["lines"][i+1]["startTime"] if i+1<len(doc["lines"]) else duration
        if end<=line["startTime"] or any(c["start"]>end for c in cues):
            raise ValueError("CUR lies beyond measured line or MIDI end")
        line["endTime"]=end
        line.pop("endTimeEstimated",None)
        for j,cue in enumerate(cues):
            next_at=cues[j+1]["start"] if j+1<len(cues) else end
            cue["duration"]=round(next_at-cue["start"],6)

def normalize_cursor_trailer(raw):
    """Recognise the observed exact vendor suffix; never trim arbitrary bytes."""
    suffix=b"www.patongbusiness.com"
    if raw.endswith(b"\xff"+suffix):
        data=raw[:-len(suffix)]
        if len(data)%2==1:
            return data, ["CUR vendor text trailer excluded from parsing"]
    return raw, []

def normalize_lyric_trailer(raw,cursor):
    """Recover only an unambiguous text prefix before a padded binary appendix."""
    try:
        raw.split(b"\x1a",1)[0].decode("cp874")
        return raw, []
    except UnicodeError:
        pass
    matches=[]
    count=len(cursor)//2
    for m in re.finditer(rb"(?:\r\n){3,}[ \t]{20,}",raw):
        prefix=raw[:m.start()]
        try:
            rows=prefix.decode("cp874").replace("\r\n","\n").replace("\r","\n").split("\n")
        except UnicodeError:
            continue
        if len(rows)<=4 or not (KEY.fullmatch(rows[2].strip()) or
                                  not rows[2].strip()):
            continue
        needed=sum(1+len(line.encode("cp874")) for line in rows[4:] if line.strip())
        if needed>0 and count in (needed,needed+1):
            matches.append(prefix)
    if len(matches)==1:
        return matches[0], ["LYR padded binary appendix excluded from parsing"]
    return raw, []

def convert_one(parts,dest,code,cancel=None):
    midi,lyr,cur=(Path(parts[x]) for x in ("midi","lyrics","cursor"))
    raw,ms=bounded_read(midi,64*1024*1024)
    lyric,ls=bounded_read(lyr,1024*1024)
    cursor,cs=bounded_read(cur,2*1024*1024)
    cursor, cursor_warnings=normalize_cursor_trailer(cursor)
    lyric, lyric_warnings=normalize_lyric_trailer(lyric,cursor)
    midi_info=reader.midi_events(midi,include_duration=True,raw_data=raw)
    midi_normalized=raw[:4]==reader.OBSERVED_SMF_MARKER
    original_media_hash=hashlib.sha256(raw).hexdigest() if midi_normalized else None
    if midi_normalized:
        # These observed files have complete standard tracks and only a
        # non-standard file marker. Export standard SMF in the XMID payload
        # for PC/Web compatibility. Never touch source files or decrypt data.
        raw=b"MThd"+raw[4:]
        if reader.midi_events(midi,include_duration=True,raw_data=raw)!=midi_info:
            raise ValueError("MIDI header normalization changed parsed events")
    tags=explicit_midi_tags(midi_info[2],parts["code"])
    cut,metadata,expected,encoding,details,body=identify_header(lyr,cur,parts["code"],
        lyric_data=lyric,cursor_data=cursor,midi_tags=tags)
    # Retry only by removing a known final credit. Its invalid/absent
    # positions never shift the earlier lyric. The original bytes are intact.
    original_rows=lyric.split(b"\x1a",1)[0].decode(encoding).replace("\r\n","\n").replace("\r","\n").split("\n")
    def parse_body(candidate, reconstruct, blank_override=None):
        parsing_lyric=("\n".join(original_rows[:cut]+candidate)+"\n").encode(encoding) if reconstruct else lyric
        parsed=reader.ncn_document(parts,header_rows=cut,metadata_override=metadata,
            lyric_data=parsing_lyric,cursor_data=cursor,midi_info=midi_info,blank_markers_override=blank_override)
        info=parsed["metadata"]
        if not info.get("timingComplete") or any("ย้อนกลับ" in w or "เกินความยาว" in w for w in info.get("timingWarnings",[])):
            raise ValueError("Incomplete or inconsistent CUR")
        if [line["text"] for line in parsed["lines"]]!=[x for x in candidate if x.strip()]:
            raise ValueError("Decoded lyric differs from original")
        measured_boundaries(parsed,midi_info[3])
        return parsed
    def parse_checked(candidate,reconstruct):
        needed=sum(1+len(x.encode("cp874")) for x in candidate if x.strip())
        blanks=sum(not x.strip() for x in candidate)
        if not blanks or len(cursor)//2<=needed+blanks:
            return parse_body(candidate,reconstruct)
        valid=[]
        for mode in (False,True):
            try:
                valid.append(parse_body(candidate,reconstruct,mode))
            except ValueError:
                pass
        if not valid:
            raise ValueError("Neither blank-line CUR alignment is valid")
        if len(valid)>1 and valid[0]["lines"]!=valid[1]["lines"]:
            raise ValueError("Ambiguous blank-line CUR alignment")
        return valid[0]
    def verify_sources():
        if any(file_stamp(p)!=stamp for p,stamp in ((midi,ms),(lyr,ls),(cur,cs))):
            raise ValueError("NCN component changed during conversion")
    try:
        doc=parse_checked(body,bool(details["footer_credit"]))
    except ValueError:
        candidate=list(body)
        removed=[]
        while candidate and is_credit(candidate[-1]):
            removed.append(candidate.pop())
            while candidate and not candidate[-1].strip():
                candidate.pop()
        if not removed or not any(x.strip() for x in candidate):
            raise
        doc=parse_checked(candidate,True)
        details["footer_credit"]=list(reversed(removed))+details["footer_credit"]
        details["warnings"].append("Untimed or inconsistent final vendor credit excluded from timed lyrics")
    details["warnings"].extend(cursor_warnings+lyric_warnings)
    if midi_normalized:
        details["warnings"].append("Validated legacy SMF marker normalized in XMID only")
        details["original_midi_sha256"]=original_media_hash
        details["midi_header_normalized"]=True
    info=doc["metadata"]
    verify_sources()
    validated=core.valid_lines(doc)
    if not validated:
        raise ValueError("No timed lyrics")
    media_hash=hashlib.sha256(raw).digest()
    identity=hashlib.sha256(media_hash+json.dumps(doc,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    song={"id":uuid.uuid5(uuid.NAMESPACE_URL,"xstage:ncn:"+code+":"+identity).hex,"code":code}
    if not all(x[4]=="original" for x in validated):
        raise ValueError("Unmeasured timing is not permitted")
    status="original"
    version={"id":uuid.uuid5(uuid.NAMESPACE_URL,"xstage:ncn:lyrics:"+identity).hex,
             "title":metadata["title"],"artist":metadata["artist"],"timing_status":status}
    lines=[({"text":text,"start_time":start,"end_time":end,"timing_status":quality},
            [{"text":glyph,"start_time":at,"duration":duration} for glyph,at,duration in cues])
           for text,start,end,cues,quality in validated]
    meta=core.metadata_bytes(song,version,lines,code_text=code)
    header=core.HEADER.pack(core.MAGIC,core.FORMAT_VERSION,len(meta),len(raw),media_hash,hashlib.sha256(meta).digest())
    details["unused_cursor_values"]=info.get("unusedCursorValues",0)
    result={"title":metadata["title"],"artist":metadata["artist"],"metadata":metadata,
            "header_rows":cut,"encoding":encoding,"timing_status":status,**details}
    if dest.is_symlink():
        raise ValueError("Destination symlink is not permitted")
    if dest.exists():
        if not dest.is_file():
            raise ValueError("Destination is not a regular file")
        with dest.open("rb") as existing:
            same=existing.read(len(header))==header
        if not same:
            raise FileExistsError("Destination conflict; no overwrite")
        core.read_xfile(dest,verify_media=True)
        return dict(result,status="skipped")
    fd,name=tempfile.mkstemp(prefix=".ncn-xmid-",suffix=".tmp",dir=dest.parent)
    stage=Path(name)
    try:
        with os.fdopen(fd,"wb") as stream:
            stream.write(header);stream.write(meta);stream.write(raw)
            stream.flush();os.fsync(stream.fileno())
        core.read_xfile(stage,verify_media=True)
        verify_sources()
        if cancel is not None and cancel.is_set():
            return dict(result,status="cancelled")
        if os.name=="nt":
            os.rename(stage,dest)
        else:
            os.link(stage,dest)
        return dict(result,status="converted")
    finally:
        stage.unlink(missing_ok=True)

@contextmanager
def output_lock(out):
    # OS-owned lock is released on process termination, unlike lock sentinels.
    path=out/".ncn-conversion.lock"
    if path.is_symlink():
        raise ValueError("Conversion lock cannot be a symlink")
    with path.open("a+b") as lock:
        lock.seek(0,os.SEEK_END)
        if lock.tell()==0:
            lock.write(b"\0")
            lock.flush()
        lock.seek(0)
        if os.name=="nt":
            import msvcrt
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            yield
        finally:
            lock.seek(0)
            if os.name=="nt":
                msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(lock,fcntl.LOCK_UN)

def plan_codes(root,out,mids):
    # JSON is only a persistent filename reservation ledger, not a song DB.
    ledger=out/".ncn-code-map.json"
    if ledger.is_symlink():
        raise ValueError("Code ledger cannot be a symlink")
    saved={}
    if ledger.exists():
        payload=json.loads(bounded_read(ledger,128*1024*1024)[0].decode("utf-8"))
        if payload.get("version")!=1 or not isinstance(payload.get("codes"),dict):
            raise ValueError("Unknown NCN code ledger")
        saved=payload["codes"]
    if any(not isinstance(k,str) or not isinstance(v,str) or
           core.xmid_song_code(v).lower()!=v for k,v in saved.items()):
        raise ValueError("Invalid code ledger")
    taken=set(saved.values())
    if len(taken)!=len(saved):
        raise ValueError("Duplicate code ledger entries")
    existing={p.stem.casefold() for p in out.iterdir() if p.suffix.casefold()==".xmid"}
    keys={m:json.dumps([os.path.normcase(str(root)),os.path.normcase(m.relative_to(root).as_posix())],ensure_ascii=False) for m in mids}
    plan={m:saved[k] for m,k in keys.items() if k in saved}
    # Valid original codes get priority. Existing untracked files can only
    # be verified by content, never overwritten.
    conflicts=set()
    for m,k in keys.items():
        if m in plan:
            continue
        try:
            code=core.xmid_song_code(m.stem).lower()
        except ValueError:
            continue
        if code in taken:
            conflicts.add(m)
            continue
        plan[m]=saved[k]=code
        taken.add(code)
    available=(prefix+f"{n:05d}" for prefix in ("",*string.ascii_lowercase) for n in range(1,100000))
    for m,k in keys.items():
        if m in plan or m in conflicts:
            continue
        code=next((c for c in available if c not in taken and c not in existing),None)
        if code is None:
            raise ValueError("XMID filename space exhausted")
        plan[m]=saved[k]=code
        taken.add(code)
    # Persist before publishing songs, so cancel/crash cannot reassign IDs.
    fd,name=tempfile.mkstemp(prefix=".ncn-map-",suffix=".tmp",dir=out)
    stage=Path(name)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            json.dump({"version":1,"codes":saved},stream,ensure_ascii=False,separators=(",",":"))
            stream.flush();os.fsync(stream.fileno())
        os.replace(stage,ledger)
    finally:
        stage.unlink(missing_ok=True)
    return plan

# Resume is a local verification cache, never a song database.
# Bump this revision when parsing/output semantics change.
RESUME_REVISION=2
RESUME_LIMIT=128*1024*1024

def resume_key(midi):
    return os.path.normcase(str(midi))

def resume_stamp(parts,dest,code):
    return {"revision":RESUME_REVISION,"code":code,
            "inputs":[[os.path.normcase(str(parts[k])),list(file_stamp(Path(parts[k])))]
                      for k in ("midi","lyrics","cursor")],
            "output":[os.path.normcase(str(dest)),list(file_stamp(dest))]}

def load_resume(out):
    cached={}
    snapshot=out/".ncn-resume.json"
    try:
        if snapshot.exists():
            data=json.loads(bounded_read(snapshot,RESUME_LIMIT)[0].decode("utf-8"))
            if data.get("revision")==RESUME_REVISION and isinstance(data.get("records"),dict):
                cached=data["records"]
    except (OSError,ValueError,TypeError,AttributeError):
        pass
    # The latest report is buffered. After an abrupt stop only flushed rows
    # are recoverable; unreported outputs are verified normally on retry.
    try:
        reports=[p for p in out.glob("ncn-conversion-*.jsonl") if not p.is_symlink() and p.is_file()]
        if reports:
            latest=max(reports,key=lambda p:p.stat().st_mtime_ns)
            if latest.stat().st_size<=RESUME_LIMIT:
                with latest.open("r",encoding="utf-8") as stream:
                    for line in stream:
                        try:
                            row=json.loads(line)
                            if row.get("resume") and row.get("status") in ("converted","skipped"):
                                cached[resume_key(row["source"])]=row["resume"]
                            elif row.get("status")=="failed":
                                cached.pop(resume_key(row["source"]),None)
                        except (ValueError,TypeError,KeyError,AttributeError):
                            continue
    except (OSError,ValueError):
        pass
    return cached

def previous_report_results(out):
    """Explicit failed-only mode can reuse a v0.1.46 report without stamps."""
    try:
        reports=[p for p in out.glob("ncn-conversion-*.jsonl") if not p.is_symlink() and p.is_file()]
        if not reports:
            return {},None,0
        latest=max(reports,key=lambda p:p.stat().st_mtime_ns)
        stamp=file_stamp(latest)
        if stamp[2]>RESUME_LIMIT:
            return {},None,0
        rows={}
        with latest.open("r",encoding="utf-8") as stream:
            for line in stream:
                try:
                    row=json.loads(line)
                    key=resume_key(row["source"])
                    if row.get("status") in ("converted","skipped"):
                        rows[key]={k:row.get(k) for k in ("code","destination","original_midi_sha256")}
                    else:
                        rows.pop(key,None)
                except (ValueError,TypeError,KeyError,AttributeError):
                    continue
        if file_stamp(latest)!=stamp:
            return {},None,0
        return rows,str(latest),stamp[3]
    except (OSError,ValueError):
        return {},None,0

def verify_report_skip(old,before,parts,dest,code,report_time):
    # A previous successful report is not a verified parser cache. Only
    # explicit failed-only mode can use it, and every retained output must
    # independently pass its embedded metadata and media digest checks.
    if not old or not before or old.get("code")!=code or not isinstance(old.get("destination"),str):
        return None
    if os.path.normcase(old["destination"])!=os.path.normcase(str(dest)):
        return None
    if any(max(x[1][3:5])>report_time for x in before["inputs"]+[before["output"]]):
        return None
    try:
        info=core.read_xfile(dest,verify_media=True)
        if info["code"]!=code:
            return None
        with Path(parts["midi"]).open("rb") as stream:
            source_sha=hashlib.file_digest(stream,"sha256").hexdigest()
        original=old.get("original_midi_sha256")
        if source_sha!=(original or info["mediaSha256"]) or resume_stamp(parts,dest,code)!=before:
            return None
        return {"status":"skipped","report_only":True,"original_midi_sha256":original}
    except (OSError,ValueError,KeyError):
        return None

def save_resume(out,cached):
    target=out/".ncn-resume.json"
    if target.is_symlink():
        return False
    stage=None
    try:
        fd,name=tempfile.mkstemp(prefix=".ncn-resume-",suffix=".tmp",dir=out)
        stage=Path(name)
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            json.dump({"revision":RESUME_REVISION,"records":cached},stream,ensure_ascii=False,separators=(",",":"))
            stream.flush();os.fsync(stream.fileno())
        if stage.stat().st_size>RESUME_LIMIT:
            return False
        os.replace(stage,target)
        return True
    except (OSError,ValueError,TypeError):
        return False
    finally:
        if stage is not None:
            stage.unlink(missing_ok=True)

def convert_folder(source,destination,progress=None,cancel=None,mode="retry"):
    if mode not in ("retry","failed_only","verify"):
        raise ValueError("Unknown NCN conversion mode")
    if not isinstance(source,str) or not source.strip() or not isinstance(destination,str) or not destination.strip():
        raise ValueError("Select source and destination folders")
    root=Path(source).expanduser().resolve(strict=True)
    out=Path(destination).expanduser().resolve()
    if not root.is_dir() or root==out or root in out.parents or out in root.parents:
        raise ValueError("Choose separate, non-nested folders")
    if progress:
        progress({"done":0,"total":0},"Scanning NCN")
    mids,index=scan(root,cancel)
    if cancel is not None and cancel.is_set():
        return {"cancelled":True,"done":0}
    out.mkdir(parents=True,exist_ok=True)
    with output_lock(out):
        return _convert_locked(root,out,mids,index,progress,cancel,mode)

def diagnostic_category(exc):
    message = str(exc)
    if isinstance(exc, FileExistsError):
        return "error", "DESTINATION_CONFLICT"
    if message.startswith("Missing exact matching "):
        return "rejected", "MISSING_" + message.rsplit(" ", 1)[-1].replace("/", "_")
    for prefix, code in (
        ("Ambiguous companion", "AMBIGUOUS_COMPANION"),
        ("Duplicate NCN code", "DUPLICATE_CODE"),
        ("Ambiguous case-insensitive output", "AMBIGUOUS_OUTPUT"),
        ("Unknown or ambiguous metadata/CUR layout", "UNSUPPORTED_LAYOUT"),
        ("Incomplete or inconsistent CUR", "INCONSISTENT_CUR"),
        ("CUR odd length", "INVALID_CUR"),
        ("Unsupported LYR encoding", "UNSUPPORTED_ENCODING"),
        ("NCN component changed", "SOURCE_CHANGED"),
        ("Conflicting explicit MIDI metadata", "METADATA_CONFLICT"),
        ("Decoded lyric differs", "LYRIC_MISMATCH"),
    ):
        if message.startswith(prefix):
            return "rejected", code
    return "error", type(exc).__name__.upper()


def csv_cell(value):
    # CSV is for spreadsheet review; JSONL retains exact unmodified values.
    value = str(value or "")
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")) else value


def _convert_locked(root,out,mids,index,progress,cancel,mode="retry"):
    cached=load_resume(out)
    prior,prior_path,prior_time=previous_report_results(out) if mode=="failed_only" else ({},None,0)
    report=out/("ncn-conversion-"+uuid.uuid4().hex+".jsonl")
    logs = out / "LOGS"
    if logs.is_symlink() or getattr(logs,"is_junction",lambda:False)():
        raise ValueError("LOGS cannot be a symlink or junction")
    logs.mkdir(exist_ok=True)
    run = logs / report.stem
    run.mkdir()
    stats={"done":0,"total":len(mids),"converted":0,"skipped":0,"failed":0,"rejected":0,
           "report":str(report),"log_folder":str(run),"with_credits":0,"with_warnings":0,
           "fast_resumed":0,"report_skipped":0,"previous_report":prior_path,"errors":{},"error_codes":{}}
    codes=plan_codes(root,out,mids)
    last_progress=0.0
    outputs=defaultdict(list)
    for path in out.iterdir():
        if path.suffix.casefold()==".xmid":
            outputs[path.stem.casefold()].append(path)
    fields = ("source", "original_code", "code", "destination", "status", "error_code", "error", "title", "artist", "encoding", "warnings")
    with ExitStack() as stack:
        log = stack.enter_context(report.open("x", encoding="utf-8", buffering=65536))
        streams = [log]
        writers = {}
        for category in ("error", "rejected", "existing", "converted"):
            stream = stack.enter_context((run / (category + ".csv")).open("x", encoding="utf-8-sig", newline="", buffering=65536))
            streams.append(stream)
            writer = csv.writer(stream)
            writer.writerow(fields)
            writers[category] = writer
        last_flush = time.monotonic()
        for midi in mids:
            if cancel is not None and cancel.is_set():
                break
            row={"source":str(midi),"original_code":midi.stem}
            try:
                code=codes.get(midi)
                if code is None:
                    raise ValueError("Duplicate NCN code; not overwritten")
                row["code"]=code
                matches=outputs.get(code,[])
                if len(matches)>1:
                    raise ValueError("Ambiguous case-insensitive output")
                dest=matches[0] if matches else out/(code+".xmid")
                row["destination"]=str(dest)
                parts=companions(midi,index)
                key=resume_key(midi)
                before=None
                if dest.exists() and not dest.is_symlink():
                    try:
                        before=resume_stamp(parts,dest,code)
                    except (OSError,ValueError,KeyError):
                        pass
                old=cached.get(key)
                if (mode!="verify" and before is not None and isinstance(old,dict)
                        and old.get("stamp")==before and resume_stamp(parts,dest,code)==before):
                    row.update(status="skipped",fast_resume=True,resume=old,
                               cached_with_credits=bool(old.get("credits")),
                               cached_with_warnings=bool(old.get("warnings")))
                    stats["fast_resumed"]+=1
                elif mode=="failed_only" and (retained:=verify_report_skip(prior.get(key),before,parts,dest,code,prior_time)):
                    # Do not certify this as a current-parser cache entry.
                    cached.pop(key,None)
                    row.update(retained)
                    stats["report_skipped"]+=1
                else:
                    cached.pop(key,None)
                    inputs_before=[[os.path.normcase(str(parts[k])),list(file_stamp(Path(parts[k])))]
                                   for k in ("midi","lyrics","cursor")]
                    row.update(convert_one(parts,dest,code,cancel))
                    if row["status"] in ("converted","skipped"):
                        try:
                            stamp=resume_stamp(parts,dest,code)
                            if stamp["inputs"]==inputs_before:
                                record={"stamp":stamp,
                                        "credits":bool(row.get("header_credit") or row.get("footer_credit")),
                                        "warnings":bool(row.get("warnings") or row.get("unused_cursor_values"))}
                                cached[key]=record
                                row["resume"]=record
                        except (OSError,ValueError,KeyError):
                            pass
                if row["status"]=="cancelled":
                    break
                stats[row["status"]]+=1
                row["category"] = "existing" if row["status"] == "skipped" else "converted"
                if row.get("header_credit") or row.get("footer_credit") or row.get("cached_with_credits"):
                    stats["with_credits"]+=1
                if row.get("warnings") or row.get("unused_cursor_values") or row.get("cached_with_warnings"):
                    stats["with_warnings"]+=1
                if not matches:
                    outputs[code].append(dest)
            except (ValueError,OSError,OverflowError,KeyError) as exc:
                cached.pop(resume_key(midi),None)
                category, error_code = diagnostic_category(exc)
                row.update(status="failed",error=str(exc),category=category,error_code=error_code)
                stats["failed"]+=1
                stats["rejected"] += category == "rejected"
                stats["error_codes"][error_code] = stats["error_codes"].get(error_code, 0) + 1
                reason=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
                # Bound the UI summary; complete errors remain in JSONL.
                if reason not in stats["errors"] and len(stats["errors"])>=20:
                    reason="Other errors"
                stats["errors"][reason]=stats["errors"].get(reason,0)+1
            log.write(json.dumps(row,ensure_ascii=False)+"\n")
            writers[row["category"]].writerow(csv_cell(row.get(field)) for field in fields)
            stats["done"]+=1
            now=time.monotonic()
            if stats["done"] % 256 == 0 or now - last_flush >= 1:
                for stream in streams:
                    stream.flush()
                last_flush = now
            if progress and (now-last_progress>=.2 or stats["done"]==stats["total"]):
                progress(dict(stats, errors=dict(stats["errors"]), error_codes=dict(stats["error_codes"])),midi.name)
                last_progress=now
    stats["resume_saved"]=save_resume(out,cached)
    result = dict(stats,cancelled=bool(cancel and cancel.is_set()))
    summary = run / "summary.json"
    stage = run / ".summary.tmp"
    with stage.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    os.replace(stage, summary)
    if progress:
        progress(result, "Cancelled" if result["cancelled"] else "Completed")
    return result
