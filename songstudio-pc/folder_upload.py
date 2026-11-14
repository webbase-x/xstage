"""Preflight private songs, then publish verified playable files and online DB.

Existing StageWeb catalogs retain their original publishing logic. New MP3/M4A
and timed LRC pairs are staged for the same verified online publisher.
Unsupported VIDEO/NCN never appear as falsely playable catalog rows.
"""
from __future__ import annotations
import hashlib
import re
from pathlib import Path

FOLDER = "application/vnd.google-apps.folder"
BUCKETS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
VIDEO = {".avi": "AVI", ".mpg": "MPG", ".mpeg": "MPG", ".dat": "VCD",
         ".wmv": "WMV", ".vob": "VCD", ".mp4": "MP4", ".mkv": "MKV",
         ".mov": "MOV", ".flv": "FLV", ".webm": "WEBM"}
AUDIO = {".mp3": "MP3", ".m4a": "M4A", ".wav": "WAV",
         ".flac": "FLAC", ".aac": "AAC", ".wma": "WMA",
         ".ogg": "OGG", ".oga": "OGG"}
MIDI = {".mid", ".midi", ".kar"}
LYRIC = {".lrc"}
SCAN_LIMIT = 250000


def digest(path):
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def bucket(stem):
    match = re.match(r"^([0-9A-Za-z])", stem)
    return match.group(1).upper() if match else "_"


def _safe_root(folder):
    if not isinstance(folder, str) or not folder.strip():
        raise ValueError("กรุณาเลือกโฟลเดอร์เพลงที่จะอัปโหลด")
    root = Path(folder).expanduser().resolve()
    if not root.is_dir() or Path(folder).is_symlink():
        raise ValueError("ไม่พบโฟลเดอร์เพลงที่เลือก หรือเป็น Symbolic Link")
    return root


def _indexed(root):
    files = []
    for path in root.rglob("*"):
        if path.is_symlink():
            continue
        if not path.is_file():
            continue
        files.append(path)
        if len(files) > SCAN_LIMIT:
            raise ValueError("พบไฟล์เกินขีดจำกัดการสแกน 250,000 ไฟล์")
    return files


def _probe_audio(path):
    # Real media is checked with FFprobe in the PC Engine before upload.
    return path.stat().st_size >= 1024


def _timed_lrc(path):
    try:
        text = path.read_text(encoding="utf-8-sig")
        stamps = []
        for line in text.splitlines():
            m = re.match(r"^\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]\s*(\S.+|\S)$", line.strip())
            if m:
                seconds = int(m.group(1)) * 60 + int(m.group(2))
                if int(m.group(2)) >= 60 or seconds < (stamps[-1] if stamps else -1):
                    return False
                stamps.append(seconds)
        return bool(stamps)
    except (UnicodeError, OSError, ValueError):
        return False


def _route(file, group, fmt):
    if group == "audio":
        sub = "Songs" if file.suffix.lower() in AUDIO else "Lyrics"
        return ("AUDIO", fmt, sub, bucket(file.stem))
    if group == "video":
        return ("VIDEO", fmt, bucket(file.stem))
    return ("MIDI", "NCN", {"mid": "Songs", "lyr": "Lyrics", "cur": "Cursor"}[fmt],
            bucket(file.stem))


def scan(folder, ncn=None):
    root = _safe_root(folder)
    paths = _indexed(root)
    by_dir = {}
    for path in paths:
        # Pair both same-directory originals and already sorted
        # AUDIO/{MP3,M4A}/{Songs,Lyrics}/A and MIDI/NCN/{Songs,Lyrics,Cursor}/A.
        # Keep the source collection prefix and bucket: never pair unrelated
        # tracks merely because their filenames match.
        parent = path.relative_to(root).parts[:-1]
        lowered = [part.casefold() for part in parent]
        role = next((i for i, part in enumerate(lowered)
                     if part in ("songs", "lyrics", "cursor")
                     and i > 0), None)
        if role is None:
            key = (tuple(lowered), path.stem.casefold())
        else:
            key = (tuple(lowered[:role] + lowered[role+1:]), path.stem.casefold())
        by_dir.setdefault(key, []).append(path)
    complete, incomplete, unsupported = [], [], []
    handled = set()

    def add(reason, members):
        incomplete.append({"name": members[0].stem, "reason": reason})

    for key, members in sorted(by_dir.items(), key=lambda x: str(x[0])):
        if key in handled:
            continue
        handled.add(key)
        candidates = {}
        for p in members:
            candidates.setdefault(p.suffix.lower(), []).append(p)
        # A pair must be in the same directory with the exact same stem.
        audios = [p for p in members if p.suffix.lower() in AUDIO]
        videos = [p for p in members if p.suffix.lower() in VIDEO]
        midis = [p for p in members if p.suffix.lower() in MIDI]
        if audios or videos:
            media = audios + videos
            lyrics = candidates.get(".lrc", [])
            if len(media) != 1 or len(lyrics) != 1:
                add("ต้องมี Song และ .LRC ชื่อเดียวกันอย่างละ 1 ไฟล์", members)
                continue
            primary, lyric = media[0], lyrics[0]
            if not _probe_audio(primary) or not _timed_lrc(lyric):
                add("ไฟล์เพลงสั้นผิดปกติหรือเนื้อร้อง LRC ไม่มีเวลาที่ถูกต้อง", members)
                continue
            fmt = AUDIO.get(primary.suffix.lower()) or VIDEO[primary.suffix.lower()]
            group = "audio" if primary.suffix.lower() in AUDIO else "video"
            layout = [(primary, _route(primary, group, fmt))]
            if group == "audio":
                layout.append((lyric, _route(lyric, "audio", fmt)))
            else:
                # Video Lyrics share the VIDEO category; no false Online DB references.
                layout.append((lyric, ("VIDEO", fmt, "Lyrics", bucket(primary.stem))))
            complete.append({"name": primary.stem, "kind": fmt,
                             "files": layout})
        elif midis:
            cursors = candidates.get(".cur", [])
            lyrs = candidates.get(".lyr", [])
            if len(midis) != 1:
                add("พบไฟล์ MIDI ชื่อเดียวกันหลายรายการ", members)
                continue
            if len(cursors) == 1 and len(lyrs) == 1:
                trio = (midis[0], lyrs[0], cursors[0])
                if any(p.stat().st_size < 8 for p in trio):
                    add("NCN มีไฟล์ว่างหรือไม่สมบูรณ์", members)
                    continue
                complete.append({"name": midis[0].stem, "kind": "NCN", "files": [
                    (p, _route(p, "midi", ext)) for p, ext in
                    zip(trio, ("mid", "lyr", "cur"))]})
            elif not cursors and not lyrs and ncn is not None:
                try:
                    doc = ncn.kar_document(midis[0], midis[0].stem)
                    if not doc.get("lines"):
                        raise ValueError("ไม่พบข้อความพร้อมเวลา")
                    complete.append({"name": midis[0].stem, "kind": "KAR",
                                     "files": [(midis[0], _route(midis[0], "midi", "mid"))]})
                except (OSError, ValueError) as exc:
                    add("MIDI ไม่มี .LYR/.CUR หรือเนื้อร้องฝังที่มีเวลาจริง: " + str(exc), members)
            else:
                add("NCN ต้องมี MIDI + .LYR + .CUR ชื่อเดียวกัน", members)
        elif members:
            if any(p.suffix.lower() in (".emk", ".lrc", ".lyr", ".cur") for p in members):
                incomplete.append({"name": members[0].stem,
                                   "reason": "ไฟล์ประกอบไม่มีเพลงคู่กันหรือ EMK ยังไม่ได้ตรวจโครงสร้าง"})
            else:
                unsupported.append(members[0].name)
    return {"folder": str(root), "complete": complete,
            "incomplete": incomplete, "unsupported": unsupported,
            "fileCount": len(paths), "total": len(complete)}


def existing_local_catalog(folder, export):
    """Detect a complete locally generated Song Studio StageWeb library."""
    if export is None:
        return None
    chosen = _safe_root(folder)
    candidates = [chosen]
    if chosen.name.casefold() != "stageweb":
        candidates.append(chosen / "StageWeb")
    for root in candidates:
        if not (root / "current.json").is_file():
            continue
        pointer, _ = export._read_current(root)  # Invalid DB must fail closed.
        rows = export.existing_records(root)
        ready = [row for row in rows if export.record_is_complete(root, row)]
        return {"root": root, "rows": ready, "incomplete": len(rows) - len(ready),
                "pointerCount": pointer.get("songCount", 0)}
    return None


def report(folder, export=None, ncn=None):
    library = existing_local_catalog(folder, export)
    if library is not None:
        return {"folder": str(library["root"]), "fileCount": library["pointerCount"],
                "ready": len(library["rows"]), "incomplete": library["incomplete"],
                "unsupported": 0, "examples": [],
                "kinds": {"M4A": len(library["rows"])}, "source": "StageWeb catalog"}
    result = scan(folder, ncn=ncn)
    return {"folder": result["folder"], "fileCount": result["fileCount"],
            "ready": result["total"], "incomplete": len(result["incomplete"]),
            "unsupported": len(result["unsupported"]),
            "examples": result["incomplete"][:12],
            "kinds": {kind: sum(row["kind"] == kind for row in result["complete"])
                      for kind in ("MP3", "M4A", "AVI", "MPG", "VCD", "WMV", "NCN")}}


def upload(drive, folder, *, create_new_library=False, cancelled=None,
           progress=None, export=None, publisher=None, staging_root=None, validator=None,
           renderer=None, ncn=None, video_renderer=None):
    """Publish supported ready audio+lyrics sets through the SAME online DB.

    The existing Karaoke Online schema supports audio+timed JSON. Do not put
    unsupported VIDEO/NCN into the catalog and falsely claim playability.
    Original source files are never modified.
    """
    import json
    import shutil
    import tempfile
    if export is None or publisher is None or staging_root is None:
        raise ValueError("ต้องใช้ Online Publisher และตัวแปลง LRC ของ X-Stage")
    library = existing_local_catalog(folder, export)
    if library is not None:
        if not library["rows"]:
            raise ValueError("ไม่พบเพลงพร้อมเล่นใน StageWeb Catalog ที่เลือก")
        # Validate each pair before publishing. Corrupt lyrics must be
        # reported as skipped; they must not invalidate all healthy songs.
        if validator is None:
            raise ValueError("ยังไม่ได้ตั้งค่าตัวตรวจเนื้อร้องของ X-Stage Online")
        verified = []
        for row in library["rows"]:
            try:
                if validator(library["root"], row):
                    verified.append(row)
            except (OSError, ValueError, RuntimeError):
                pass
        if not verified:
            raise ValueError("ไม่พบเพลงที่มีไฟล์เสียงและเนื้อร้องพร้อมเวลาใช้งานจริง")
        # Preserve original production publishing: stable song IDs and the
        # incremental remote DB. Only remote media folder paths differ.
        synced = publisher.publish(
            library["root"], verified,
            create_new_library=create_new_library, cancelled=cancelled,
            on_row=(lambda done, total, skipped:
                    progress(done + skipped, total + skipped, "กำลังอัปเดต DB"))
                   if progress else None)
        return {**synced, "ready": len(verified),
                "incomplete": library["incomplete"] + len(library["rows"]) - len(verified), "deferred": 0,
                "message": (
                    f"ซิงค์คลังเดิมพร้อม DB · เพิ่ม {synced['newSongs']} · "
                    f"แก้เนื้อร้อง {synced['updatedSongs']} · "
                    f"ข้ามซ้ำ {synced['duplicates']} · "
                    f"รหัสต้องตรวจ {synced['conflicts']} · "
                    f"ข้ามไฟล์ไม่ครบ {library['incomplete']}")}
    result = scan(folder, ncn=ncn)
    supported = [r for r in result["complete"] if r["kind"] != "EMK"]
    deferred = [r for r in result["complete"] if r["kind"] == "EMK"]
    if not supported:
        raise ValueError("ไม่พบเพลงพร้อมเนื้อร้องสำหรับเผยแพร่ · ชุดที่ไม่รองรับจะไม่ถูกส่ง")
    # Check the live catalogue before creating local files or modifying Drive.
    preview = publisher.read_code_registry(allow_missing_root=create_new_library)
    if not preview.get("visible") and not create_new_library:
        raise ValueError("ไม่พบ XStageWeb ที่มองเห็นได้ · ต้องยืนยันสร้างคลังใหม่")
    staging_root = Path(staging_root).expanduser()
    staging_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="xstage-upload-", dir=staging_root) as scratch:
        stage = Path(scratch)
        (stage / "audio").mkdir()
        (stage / "lyrics").mkdir()
        prepared = []
        seen = set()
        for row in supported:
            if cancelled and cancelled.is_set():
                raise ValueError("ยกเลิกก่อนเผยแพร่")
            media = next((p for p, _ in row["files"]
                          if p.suffix.lower() in AUDIO or p.suffix.lower() in VIDEO
                          or p.suffix.lower() in MIDI), None)
            lyric = next((p for p, _ in row["files"] if p.suffix.lower() == ".lrc"), None)
            if media is None:
                continue
            source_id = digest(media)
            if source_id in seen:
                continue
            seen.add(source_id)
            code = row["name"].strip()
            if not code or len(code) > 140:
                continue
            source_kind = media.suffix.lower()
            is_video = source_kind in VIDEO
            is_midi = source_kind in MIDI
            file = stage / "audio" / (source_id[:16] +
                    (source_kind if source_kind in (".mid", ".midi", ".kar", ".mp3", ".m4a")
                     else ".m4a"))
            lyrics_file = stage / "lyrics" / (source_id[:16] + ".json")
            lrc_file = lyrics_file.with_suffix(".lrc")
            if is_midi:
                if ncn is None:
                    raise ValueError("ไม่มีตัวอ่านเนื้อร้อง NCN/MIDI ในแพ็กเกจ")
                companions = {p.suffix.lower(): p for p, _ in row["files"]}
                if ".lyr" in companions and ".cur" in companions:
                    pair = {"midi": str(media), "lyrics": str(companions[".lyr"]),
                            "cursor": str(companions[".cur"]), "code": code, "missing": []}
                    document = ncn.ncn_document(pair)
                else:
                    document = ncn.kar_document(media, code)
                raw_lrc = ncn.to_lrc(document["lines"]).encode("utf-8")
            else:
                if lyric is None:
                    continue
                raw_lrc = lyric.read_bytes()
                document = export.lrc_to_json(lyric.read_text(encoding="utf-8-sig"), code)
            if not document.get("lines"):
                continue
            if file.suffix.lower() == source_kind:
                shutil.copyfile(media, file)
                if digest(file) != source_id:
                    raise ValueError("SHA-256 ไฟล์ที่คัดลอกไม่ตรงต้นฉบับ: " + media.name)
            elif renderer is not None:
                renderer(media, file)
            else:
                raise ValueError("ต้องใช้ FFmpeg/FluidSynth ที่มากับ PC Ready เพื่อแปลงเพลง " + media.name)
            minimum = 22 if is_midi else 1000
            if not file.is_file() or file.stat().st_size < minimum:
                raise ValueError("ไฟล์เพลงที่เตรียมไว้ไม่สมบูรณ์: " + media.name)
            lrc_file.write_bytes(raw_lrc)
            lyrics_file.write_text(json.dumps(document, ensure_ascii=False),
                                   encoding="utf-8")
            record = {
                "webSongId": "import/" + source_id,
                "code": code, "title": row["name"], "artist": "",
                "sourceFormat": row["kind"],
                "audio": {"path": "audio/" + file.name},
                "lyrics": {"path": "lyrics/" + lyrics_file.name}}
            # NCN sources (LYR/CUR) remain on the local computer only.
            # For Web/TV only the unmodified MIDI and timed Lyrics JSON
            # are published; no extra source-type folders or companion files.
            if is_video and video_renderer is not None:
                (stage / "video").mkdir(exist_ok=True)
                video = stage / "video" / (source_id[:16] + ".mp4")
                video_renderer(media, video)
                if video.is_file() and video.stat().st_size > 1000:
                    record["video"] = {"path": "video/" + video.name}
            prepared.append(record)
        if not prepared:
            raise ValueError("ไม่มีเนื้อร้องที่แปลงเป็น JSON พร้อมเวลาได้")
        (stage / "current.json").write_text('{"staging":true}', encoding="utf-8")
        result_db = publisher.publish(
            stage, prepared, create_new_library=create_new_library,
            cancelled=cancelled,
            on_row=(lambda done, total, skipped:
                    progress(done + skipped, total + skipped, "กำลังสร้าง DB ออนไลน์"))
                   if progress else None)
    return {
        **result_db, "ready": len(prepared), "deferred": len(deferred),
        "incomplete": len(result["incomplete"]), "unsupported": len(result["unsupported"]),
        "message": (
            f"ซิงค์ DB พร้อมเล่น · เพิ่ม {result_db['newSongs']} เพลง · "
            f"ปรับเนื้อร้อง {result_db['updatedSongs']} · "
            f"ข้ามซ้ำ {result_db['duplicates']} · รหัสชนกัน {result_db['conflicts']} · "
            f"ข้ามรายการไม่สมบูรณ์ {len(result['incomplete'])} · "
            f"ข้ามประเภทที่ยังแปลงไม่ได้ {len(deferred)} รายการ")
    }


def inspect_soundfont(path):
    """Check the SoundFont file signature, not merely its extension."""
    if not isinstance(path, str) or not path.strip():
        raise ValueError("กรุณาเลือกไฟล์ SoundFont .sf2 หรือ .sf3")
    source = Path(path).expanduser()
    if not source.is_file() or source.is_symlink():
        raise ValueError("ไม่พบ SoundFont ที่เลือก หรือไฟล์เป็น Symbolic Link")
    suffix = source.suffix.lower()
    if suffix not in (".sf2", ".sf3"):
        raise ValueError("รองรับ SoundFont .sf2/.sf3 เท่านั้น")
    size = source.stat().st_size
    if size < 256 or size > 2 * 1024 * 1024 * 1024:
        raise ValueError("ขนาด SoundFont ไม่ถูกต้องหรือใหญ่เกิน 2 GB")
    with source.open("rb") as stream:
        header = stream.read(12)
    if header[:4] != b"RIFF" or header[8:12] != b"sfbk":
        raise ValueError("ไฟล์ SoundFont ไม่ใช่ RIFF sfbk ที่ถูกต้อง")
    return {"path": str(source), "name": source.name, "format": suffix[1:].upper(),
            "bytes": size}


def upload_soundfont(drive, path, *, create_new_library=False,
                     cancelled=None, progress=None):
    """Upload private SF2/SF3 without altering the playable songs catalog.

    XStageWeb/AUDIO/ contains immutable SF2/SF3 alongside other media. Until the browser
    MIDI engine implements loading these private Drive IDs, it is not a claim
    that a SoundFont can be played in Karaoke Online.
    """
    info = inspect_soundfont(path)
    roots = [item for item in drive.list_children("root")
             if item.get("name") in ("XStageWeb", "StageWeb")
             and item.get("mimeType") == FOLDER]
    if len(roots) > 1:
        raise ValueError("พบ StageWeb/XStageWeb ซ้ำกัน · หยุดก่อนอัปโหลด SoundFont")
    if not roots and not create_new_library:
        raise ValueError("ไม่พบ XStageWeb ที่เข้าถึงได้ · ต้องยืนยันสร้างคลังใหม่")
    if cancelled and cancelled.is_set():
        raise ValueError("ยกเลิกการอัปโหลด SoundFont")
    library_name = roots[0]["name"] if roots else "XStageWeb"
    root = roots[0]["id"] if roots else drive.folder("root", library_name)
    # Flat Drive v3: SoundFonts are playable media, under AUDIO.
    target = drive.folder(root, "AUDIO")
    source = Path(info["path"])
    fingerprint = digest(source)
    # Immutably named artifacts: same name + same bytes is skipped, changed
    # bytes are versioned without overwriting a working SoundFont.
    stem = re.sub(r"[^\w .()-]", "_", source.stem, flags=re.UNICODE).strip(" .")[:100] or "SoundFont"
    filename = stem + "-" + fingerprint[:16] + source.suffix.lower()
    if progress:
        progress("ตรวจ MD5 และอัปโหลด SoundFont ไปยัง XStageWeb/AUDIO")
    status, meta = drive.upload_file(target, source, filename, cancelled=cancelled)
    if str(meta.get("md5Checksum", "")).lower() != fingerprint:
        raise ValueError("Google Drive ไม่ยืนยัน MD5 SoundFont ให้ตรงกับไฟล์ต้นฉบับ")
    return {"uploaded": status == "created", "skipped": status == "skipped",
            "name": filename, "fileId": meta["id"], "md5": fingerprint,
            "bytes": info["bytes"], "path": library_name + "/AUDIO/" + filename,
            "webMidiReady": True,
            "message": ("อัปโหลด SoundFont สำเร็จ" if status == "created"
                        else "พบ SoundFont เดิมที่ตรงกัน · ข้ามซ้ำ") +
                       " · " + info["format"] + " · พร้อมให้เว็บตรวจสอบ SoundFont"}
