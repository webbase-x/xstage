"""Repair catalog identity independently from lyric timing; never mutate sources."""
import json
import uuid
from pathlib import Path
import plus_core as core
import ncn_reader

def run(workspace,progress=None,cancel=None):
    core.init(workspace)
    root=core.root_folder(workspace)
    folder=root/"REPORTS"
    folder.mkdir(exist_ok=True)
    report=folder/("metadata-recovery-"+uuid.uuid4().hex+".jsonl")
    totals={"done":0,"total":0,"updated":0,"rebuilt":0,"unresolved":0,"failed":0,"report":str(report)}
    with core.connect(workspace) as db:
        totals["total"]=db.execute("SELECT count(*) FROM xstage_songs").fetchone()[0]
    last=0
    with report.open("x",encoding="utf-8") as out:
        while not (cancel and cancel.is_set()):
            with core.connect(workspace) as db:
                ids=db.execute("SELECT id,code FROM xstage_songs WHERE code>? ORDER BY code LIMIT 128",(last,)).fetchall()
            if not ids: break
            for entry in ids:
                if cancel and cancel.is_set(): break
                sid=entry["id"];last=entry["code"];issues=[];sources=[];rebuild=False
                try:
                    with core.WRITE_LOCK,core.connect(workspace) as db:
                        song=db.execute("SELECT * FROM xstage_songs WHERE id=?",(sid,)).fetchone()
                        candidates={f:set() for f in ("title","artist")}
                        for row in db.execute("SELECT source_path,bytes,mtime_ns FROM xstage_media_sources WHERE media_id=?",(song["media_id"],)):
                            path=Path(row["source_path"])
                            try:
                                stat=path.stat()
                                if (stat.st_size,stat.st_mtime_ns)!=(row["bytes"],row["mtime_ns"]):
                                    issues.append("SOURCE_CHANGED");continue
                                if path.suffix.lower() not in core.MIDI_EXT: continue
                                comps=core.companion_candidates(path)
                                if core.is_ncn_media(path,comps):
                                    missing=core.ncn_missing_companions(comps)
                                    if missing: issues.append("NCN_MISSING:"+",".join(missing))
                                meta=ncn_reader.lyric_metadata(comps[".lyr"]) if comps.get(".lyr") else {}
                                try:
                                    if comps.get(".lyr") and comps.get(".cur"):
                                        doc=ncn_reader.ncn_document({"midi":str(path),"lyrics":str(comps[".lyr"]),"cursor":str(comps[".cur"]),"code":path.stem,"missing":[]})
                                        if not doc["metadata"]["timingComplete"]: issues.append("CUR_INCOMPLETE")
                                        issues.extend(doc["metadata"].get("timingWarnings",[]))
                                        for f in candidates:
                                            if core.identity_missing(meta.get(f),song["original_code"],f): meta[f]=doc["metadata"].get(f,"")
                                    elif any(core.identity_missing(meta.get(f),song["original_code"],f) for f in candidates):
                                        _,_,events=ncn_reader.midi_events(path)
                                        for f,v in ncn_reader.midi_metadata(events).items():
                                            if not meta.get(f): meta[f]=v
                                except (OSError,ValueError,UnicodeError) as exc:
                                    issues.append("TIMING_OR_MIDI:"+str(exc)[:160])
                                for f in candidates:
                                    v=str(meta.get(f) or "").strip()
                                    if not core.identity_missing(v,song["original_code"],f): candidates[f].add(v)
                                sources.append(str(path))
                            except (OSError,ValueError,UnicodeError) as exc:
                                issues.append("SOURCE:"+str(exc)[:160])
                        selected={}
                        for f,values in candidates.items():
                            if len(values)>1: issues.append("CONFLICT_"+f.upper())
                            elif len(values)==1:
                                v=next(iter(values))
                                if not core.identity_missing(song[f],song["original_code"],f) and core.norm(song[f])!=core.norm(v): issues.append("CONFLICT_"+f.upper())
                                else: selected[f]=v
                        before=db.total_changes
                        identity=core.merge_song_identity(db,song,selected)
                        changed=db.total_changes>before
                        for f in candidates:
                            if core.identity_missing(identity[f],song["original_code"],f): issues.append("MISSING_OR_INVALID_"+f.upper())
                        version=db.execute("SELECT * FROM xstage_lyric_versions WHERE song_id=? AND is_current=1",(sid,)).fetchone()
                        export=db.execute("SELECT * FROM xstage_exports WHERE song_id=?",(sid,)).fetchone()
                        if not sources: issues.append("NO_VERIFIED_SOURCE")
                        if not version or version["timing_status"]=="incomplete": issues.append("NO_COMPLETE_TIMING")
                        if version and any(core.norm(version[f])!=core.norm(identity[f]) for f in candidates): issues.append("CURRENT_VERSION_IDENTITY_CONFLICT")
                        elif export and version and version["timing_status"]!="incomplete":
                            path=(root/export["output_path"]).resolve()
                            if not path.is_relative_to(root): raise ValueError("Output outside workspace")
                            if not path.is_file(): issues.append("EXPORTED_FILE_MISSING")
                            else:
                                old=core.read_xfile(path)
                                rebuild=any(old.get(f)!=version[f] for f in candidates)
                    if changed: totals["updated"]+=1
                    if rebuild:
                        result=core.build_song(workspace,sid,repair_metadata=True)
                        if not result["skipped"]: totals["rebuilt"]+=1
                except (OSError,ValueError,UnicodeError) as exc:
                    totals["failed"]+=1;issues.append("REPAIR_FAILED:"+str(exc)[:240])
                if issues:
                    totals["unresolved"]+=1
                    out.write(json.dumps({"song_id":sid,"code":last,"issues":list(dict.fromkeys(issues)),"sources":sources},ensure_ascii=False)+"\n");out.flush()
                totals["done"]+=1
                if progress and (totals["done"]%16==0 or totals["done"]==totals["total"]):
                    progress(dict(totals),f"ตรวจ {totals['done']:,}/{totals['total']:,} · แก้ {totals['updated']:,} · สร้างใหม่ {totals['rebuilt']:,} · ตรวจต่อ {totals['unresolved']:,}")
    return totals
