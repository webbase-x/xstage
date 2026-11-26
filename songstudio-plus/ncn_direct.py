"""Direct NCN batch export without opening a song database."""
import hashlib
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
}
KEY = re.compile(r"(?:[A-G](?:#|b|♯|♭)?(?:m|maj|min|major|minor)?|[-+]?\d{1,2})",re.I)

def clean(value, code):
    value=value.strip()
    if (not value or len(value)>255 or "\ufffd" in value or
        any(ord(c)<32 for c in value) or
        value.casefold() in {code.casefold(),"unknown","untitled","n/a","-","ไม่ทราบ"} or
        re.fullmatch(r"[A-Za-z]?\d{3,}(?:\(\d+\))?",value)):
        return ""
    return value

def identify_header(lyr,cur,code):
    raw=Path(lyr).read_bytes().split(b"\x1a",1)[0]
    cursor=Path(cur).read_bytes()
    if len(raw)>1024*1024 or len(cursor)>2*1024*1024:
        raise ValueError("NCN component exceeds size limit")
    if len(cursor)%2 and cursor[-1:]!=b"\xff":
        raise ValueError("CUR odd length")
    encoding="utf-8-sig"
    try:
        decoded=raw.decode(encoding)
    except UnicodeError:
        encoding="cp874"
        decoded=raw.decode(encoding)
    rows=decoded.replace("\r\n","\n").replace("\r","\n").split("\n")
    count=len(cursor)//2
    candidates=[]
    for cut in range(1,min(17,len(rows))):
        body=rows[cut:]
        while body and not body[-1].strip(" \x00\x1a"):
            body.pop()
        try:
            encoded=[line.encode("cp874") for line in body]
        except UnicodeError:
            continue
        needed=sum(1+len(line) for line in encoded if line.strip())
        blanks=sum(not line.strip() for line in encoded)
        if not needed or count not in (needed,needed+blanks):
            continue
        header=rows[:cut]
        metadata={}
        conflict=False
        for line in header:
            match=re.fullmatch(r"\s*[@#]?\s*([^:=：]+?)\s*[:=：]\s*(.*?)\s*",line)
            if not match:
                continue
            key=LABELS.get(match[1].strip().casefold())
            if key:
                if key in metadata and metadata[key]!=match[2]:
                    conflict=True
                metadata[key]=match[2]
        if conflict:
            continue
        if not metadata and cut==4 and (KEY.fullmatch(header[2].strip()) or not header[2].strip()):
            metadata={"title":header[0],"artist":header[1],"key":header[2]}
        for key in ("title","artist"):
            metadata[key]=clean(metadata.get(key,""),code)
        if metadata["title"] and metadata["artist"]:
            candidates.append((cut,metadata,[x for x in body if x.strip()],encoding))
    if len(candidates)!=1:
        raise ValueError("Unknown or ambiguous metadata/CUR layout; no guessing")
    return candidates[0]

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
        raise ValueError("Missing exact matching LYR/CUR")
    return {"midi":str(midi),"lyrics":str(lyr),"cursor":str(cur),"code":midi.stem,"missing":[]}

def convert_one(parts,dest,code,cancel=None):
    cut,metadata,expected,encoding=identify_header(parts["lyrics"],parts["cursor"],parts["code"])
    midi=Path(parts["midi"])
    if midi.stat().st_size>64*1024*1024:
        raise ValueError("MIDI exceeds 64 MiB safety limit")
    raw=midi.read_bytes()
    doc=reader.ncn_document(parts,header_rows=cut,metadata_override=metadata)
    info=doc["metadata"]
    if not info.get("timingComplete") or any("ย้อนกลับ" in w or "เกินความยาว" in w for w in info.get("timingWarnings",[])):
        raise ValueError("Incomplete or inconsistent CUR")
    if [line["text"] for line in doc["lines"]]!=expected:
        raise ValueError("Decoded lyric differs from original")
    if midi.read_bytes()!=raw:
        raise ValueError("MIDI changed during conversion")
    validated=core.valid_lines(doc)
    if not validated:
        raise ValueError("No timed lyrics")
    media_hash=hashlib.sha256(raw).digest()
    identity=hashlib.sha256(media_hash+json.dumps(doc,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    song={"id":uuid.uuid5(uuid.NAMESPACE_URL,"xstage:ncn:"+code+":"+identity).hex,"code":code}
    status="original" if all(x[4]=="original" for x in validated) else "estimated"
    version={"id":uuid.uuid5(uuid.NAMESPACE_URL,"xstage:ncn:lyrics:"+identity).hex,
             "title":metadata["title"],"artist":metadata["artist"],"timing_status":status}
    lines=[({"text":text,"start_time":start,"end_time":end,"timing_status":quality},
            [{"text":glyph,"start_time":at,"duration":duration} for glyph,at,duration in cues])
           for text,start,end,cues,quality in validated]
    meta=core.metadata_bytes(song,version,lines,code_text=code)
    header=core.HEADER.pack(core.MAGIC,core.FORMAT_VERSION,len(meta),len(raw),media_hash,hashlib.sha256(meta).digest())
    result={"title":metadata["title"],"artist":metadata["artist"],"metadata":metadata,
            "header_rows":cut,"encoding":encoding,"timing_status":status}
    if dest.exists():
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
        if cancel is not None and cancel.is_set():
            return dict(result,status="cancelled")
        if os.name=="nt":
            os.rename(stage,dest)
        else:
            os.link(stage,dest)
        return dict(result,status="converted")
    finally:
        stage.unlink(missing_ok=True)

def convert_folder(source,destination,progress=None,cancel=None):
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
    report=out/("ncn-conversion-"+uuid.uuid4().hex+".jsonl")
    stats={"done":0,"total":len(mids),"converted":0,"skipped":0,"failed":0,"report":str(report)}
    codes={}
    for midi in mids:
        try:
            codes[midi]=core.xmid_song_code(midi.stem).lower()
        except ValueError:
            pass
    reserved=set(codes.values())
    assigned=set()
    next_code=1
    with report.open("x",encoding="utf-8") as log:
        for midi in mids:
            if cancel is not None and cancel.is_set():
                break
            row={"source":str(midi),"original_code":midi.stem}
            try:
                code=codes.get(midi)
                if code is None:
                    while f"{next_code:05d}" in reserved or f"{next_code:05d}" in assigned:
                        next_code+=1
                    code=core.xmid_song_code(next_code)
                    next_code+=1
                if code in assigned:
                    raise ValueError("Duplicate NCN code; not overwritten")
                assigned.add(code)
                row["code"]=code
                dest=out/(code+".xmid")
                row["destination"]=str(dest)
                row.update(convert_one(companions(midi,index),dest,code,cancel))
                if row["status"]=="cancelled":
                    break
                stats[row["status"]]+=1
            except (ValueError,OSError,OverflowError,KeyError) as exc:
                row.update(status="failed",error=str(exc))
                stats["failed"]+=1
            log.write(json.dumps(row,ensure_ascii=False)+"\n")
            log.flush()
            stats["done"]+=1
            if progress:
                progress(stats,midi.name)
    return dict(stats,cancelled=bool(cancel and cancel.is_set()))
