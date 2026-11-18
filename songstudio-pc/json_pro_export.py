"""Export verified media + timed Lyrics JSON to a separate local XStageSong catalog.

Never edit original media. Each completed pair is checkpointed before an atomic
catalog pointer switch; stop/resume skips already published source fingerprints.
Unsupported or malformed pairs are reported, not published as playable songs.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import time
from pathlib import Path

MEDIA_EXT = {".mid", ".midi", ".kar", ".mp3", ".m4a", ".wav", ".aac",
             ".flac", ".ogg", ".oga", ".wma", ".mp4", ".webm", ".avi",
             ".mkv", ".mov", ".mpg", ".mpeg", ".vob", ".dat", ".wmv", ".flv"}
AUDIO_FORMATS = {"original", "m4a", "mp3", "wav", "flac", "ogg"}
CHECKPOINT_SIZE = 1024
CHECKPOINT_INTERVAL_SECONDS = 60


def _review_module():
    """Use the same local outcome history in source checkouts and Ready ZIPs."""
    path = Path(__file__).with_name("json_pro_review.py")
    spec = importlib.util.spec_from_file_location("xstage_json_pro_review", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module



def _fingerprint(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _lyrics_digest(doc):
    """Hash lyric content independent of filename-derived songCode.

    Same audio with the same timed lyrics remains a duplicate after a rename;
    actual edits to lyric lines/timing or embedded metadata are new versions.
    """
    normalized = dict(doc)
    normalized.pop("songCode", None)
    return hashlib.sha256(json.dumps(
        normalized, sort_keys=True, ensure_ascii=False, allow_nan=False,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def _publish_no_overwrite(staged, target):
    """Commit a complete staged file without an overwrite race.

    Hardlink on local NTFS/POSIX is atomic. Removable drives without links
    get an exclusive-create copy; collisions never overwrite user files.
    """
    if target.exists() or target.is_symlink():
        raise FileExistsError("มีไฟล์ปลายทางแล้ว · จะไม่เขียนทับ: " + str(target))
    try:
        os.link(staged, target)
    except FileExistsError:
        raise
    except OSError:
        with staged.open("rb") as source, target.open("xb") as output:
            try:
                shutil.copyfileobj(source, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
            except BaseException:
                output.close()
                target.unlink(missing_ok=True)
                raise
    staged.unlink(missing_ok=True)


def _can_recover_pair(media, audio, lyrics, source_hash, document, output_format):
    """Recovery is allowed only for intact, matching, unindexed output pairs."""
    if (audio.is_symlink() or lyrics.is_symlink()
            or not audio.is_file() or not lyrics.is_file()):
        return False
    try:
        saved = json.loads(lyrics.read_text(encoding="utf-8-sig"))
        if saved != document:
            return False
        if output_format == "original":
            return _fingerprint(audio) == source_hash
        return audio.stat().st_size >= 1000
    except (ValueError, TypeError, OSError):
        return False


def _with_song_identity(document, code, export):
    """Write real name/performer to top-level Lyrics JSON for every Karaoke app.

    NCN/KAR parsers can store their names under metadata; LRC names can live
    only inside rawLrc. Do not publish guessed filenames or app brand names.
    """
    title, artist = export.lyrics_identity(document, code)
    normalized = dict(document)
    if title:
        normalized["title"] = title
    else:
        normalized.pop("title", None)
    if artist:
        normalized["artist"] = artist
    else:
        normalized.pop("artist", None)
    return normalized


def _document(row, code, export, ncn):
    members = {path.suffix.lower(): path for path, _ in row["files"]}
    lyrics = members.get(".json")
    if lyrics is not None:
        if lyrics.stat().st_size > 5_000_000 or lyrics.is_symlink():
            raise ValueError("Lyrics JSON ใหญ่ผิดปกติหรือไม่ปลอดภัย")
        doc = json.loads(lyrics.read_text(encoding="utf-8-sig"))
        # Same validator used by Online source preflight; no manufactured cue times.
        from math import isfinite
        lines = doc.get("lines") if isinstance(doc, dict) else None
        if (not isinstance(doc, dict) or doc.get("schemaVersion") != 1
                or not isinstance(lines, list) or not lines):
            raise ValueError("Lyrics JSON ไม่มี schemaVersion 1 และบรรทัดพร้อมเวลา")
        last = -1
        for line in lines:
            value = line.get("startTime") if isinstance(line, dict) else None
            if (not isinstance(value, (int, float)) or isinstance(value, bool)
                    or not isfinite(value) or not 0 <= value < 86400
                    or value < last or not isinstance(line.get("text"), str)
                    or not line["text"].strip()):
                raise ValueError("Lyrics JSON มีข้อความ/เวลาไม่ถูกต้อง")
            last = value
        doc = dict(doc)
        doc["songCode"] = code
        return _with_song_identity(doc, code, export)
    lyrics = members.get(".lrc")
    if lyrics is not None:
        doc = export.lrc_to_json(lyrics.read_text(encoding="utf-8-sig"), code)
    elif row["kind"] == "NCN" and ncn is not None:
        source = next(path for path in members.values() if path.suffix.lower() in
                      {".mid", ".midi", ".kar"})
        doc = ncn.ncn_document({"midi": str(source),
                                "lyrics": str(members[".lyr"]),
                                "cursor": str(members[".cur"]),
                                "code": code, "missing": []})
    elif row["kind"] == "KAR" and ncn is not None:
        source = next(path for path in members.values() if path.suffix.lower() in
                      {".mid", ".midi", ".kar"})
        doc = ncn.kar_document(source, code)
    else:
        raise ValueError("ไม่มี Lyrics JSON/LRC หรือข้อมูลคำร้องมีเวลาที่อ่านได้")
    if not isinstance(doc, dict) or not doc.get("lines"):
        raise ValueError("ไม่พบข้อมูลเนื้อร้องพร้อมเวลาจริง")
    doc["songCode"] = code
    return _with_song_identity(doc, code, export)


def _next_code(used, style, width, preferred, counters):
    """Allocate a single safe, globally unique code for the media/JSON pair."""
    preferred = str(preferred or "").strip().upper()
    if (style == "source" and re.fullmatch(r"[A-Za-z0-9]{1,12}", preferred)
            and len(preferred) == width and preferred.casefold() not in used):
        used.add(preferred.casefold())
        return preferred
    alphabet = ("0123456789" if style in ("numeric", "source") else
                "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if style == "letters" else
                "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    radix = len(alphabet)
    number = counters.get((style, width), 1)
    while number < radix ** width:
        n = number
        chars = []
        for _ in range(width):
            chars.append(alphabet[n % radix])
            n //= radix
        code = "".join(reversed(chars))
        if code.casefold() not in used:
            used.add(code.casefold())
            counters[(style, width)] = number + 1
            return code
        number += 1
    raise ValueError("รหัสเพลงเต็มช่วงที่เลือก · กรุณาเพิ่มจำนวนหลัก")


def export_folder(source_folder, destination_folder, *, output_format, export, scanner,
                   ncn=None, convert=None, cancelled=None, progress=None,
                   code_style="numeric", code_length=5, scan_progress=None,
                   source_stream=None, retry_errors_only=False):
    """Create a local Karaoke-compatible catalog; never publish to Google Drive.

    output_format is a constrained FFmpeg output extension or 'original'.
    """
    if output_format not in AUDIO_FORMATS:
        raise ValueError("ไม่รองรับรูปแบบเสียงที่เลือก")
    if code_style not in ("source", "numeric", "letters", "alphanumeric"):
        raise ValueError("รูปแบบรหัสเพลงไม่ถูกต้อง")
    if type(code_length) is not int or not 1 <= code_length <= 12:
        raise ValueError("จำนวนหลักรหัสเพลงต้องอยู่ระหว่าง 1–12")
    source = Path(source_folder).expanduser()
    destination = Path(destination_folder).expanduser()
    if (not source.is_dir() or source.is_symlink() or not destination_folder
            or destination.is_symlink()):
        raise ValueError("กรุณาเลือกต้นทางและปลายทางที่เป็นโฟลเดอร์ปกติ")
    root = export.songs_root(destination)
    review = _review_module()
    spec = importlib.util.spec_from_file_location(
        "xstage_song_registry", Path(__file__).with_name("song_registry.py"))
    registry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(registry)
    src_real = source.resolve()
    root_real = root.resolve()
    if src_real == root_real or src_real in root_real.parents or root_real in src_real.parents:
        raise ValueError("ต้นทางและปลายทางต้องแยกจากกัน เพื่อไม่ให้อ่านหรือเขียนวนทับคลังเดิม")
    # Stream the current song from the source code/filename directly.
    # In retry mode enumerate ONLY the persisted errors; do not revisit
    # tens of thousands of already completed songs.
    if retry_errors_only:
        source_stream = lambda folder, **kw: review.retry_stream(
            folder, root, output_format=output_format, **kw)
    # Legacy callers may still supply the old full scanner for compatibility.
    # No whole-library pairing pass, fabricated Lyrics JSON, or upfront count.
    inspection = (source_stream(str(source), ncn=ncn, progress=scan_progress,
                                cancelled=cancelled)
                  if source_stream is not None
                  else scanner.scan(str(source), ncn=ncn, progress=scan_progress))
    entries = inspection["complete"]
    known_total = None if source_stream is not None else len(entries)
    root.mkdir(parents=True, exist_ok=True)
    prior = export.existing_records(root)
    seen = set()
    existing = set()
    used_codes = {str(row.get("code") or "").casefold() for row in prior if row.get("code")}
    code_counters = {}

    # Unindexed complete pairs may be recovered after a crash; keep their codes
    # available for strict content verification in _can_recover_pair.
    for record in prior:
        if not export.record_is_complete(root, record):
            continue
        existing.add(record.get("webSongId"))
        origin = record.get("sourceIdentity") or {}
        lyric_hash = origin.get("lyricsSha256")
        if not lyric_hash:
            # Legacy Build 348 exported pairs tracked audio SHA only.
            # Read the actual saved lyrics once: unchanged exports must stay
            # idempotent without duplicating previously published songs.
            try:
                lyric_file = export.safe_media_path(
                    root, record["lyrics"]["path"], "lyrics")
                lyric_hash = _lyrics_digest(json.loads(
                    lyric_file.read_text(encoding="utf-8-sig")))
            except (KeyError, TypeError, OSError, ValueError):
                continue
        seen.add((origin.get("sha256"), origin.get("outputFormat"), lyric_hash))
    legacy_by_source = {}
    for record in prior:
        origin = record.get("sourceIdentity") or {}
        if (record.get("webSongId") in existing
                and origin.get("outputFormat") == output_format
                and origin.get("canonicalPath") and origin.get("sha256")):
            legacy_by_source[origin["canonicalPath"]] = (
                origin["sha256"], origin.get("bytes"), record["webSongId"])
    db = review.connect(root)
    source_root = str(src_real)
    created = skipped = errors = deferred = resumed = 0
    issues = []
    examined = 0
    checkpointed = 0
    checkpoint_at = time.monotonic()

    def checkpoint(*, force=False):
        nonlocal checkpointed, checkpoint_at
        if (not force and created - checkpointed < CHECKPOINT_SIZE
                and time.monotonic() - checkpoint_at < CHECKPOINT_INTERVAL_SECONDS):
            return
        # All items are already fsynced to a crash-safe journal. Publish it
        # periodically so completed files become usable before the scan ends.
        # An interrupted/cancelled run must also publish its last good batch.
        pending = export.journal_records(root)
        if pending:
            export.publish_batch(root, pending)
            export.clear_published_journal(root)
        db.commit()
        checkpointed = created
        checkpoint_at = time.monotonic()

    try:
        for index, item in enumerate(entries, 1):
            examined = index
            if cancelled is not None and cancelled.is_set():
                raise RuntimeError("ยกเลิกการส่งออกแล้ว · คงไฟล์ที่สำเร็จไว้สำหรับเริ่มต่อ")
            media = next((path for path, _ in item["files"]
                          if path.suffix.lower() in MEDIA_EXT), None)
            if media is None:
                skipped += 1
                continue
            final_audio = final_lyrics = None
            source_signature = ""
            try:
                source_signature = review.signature(item["files"])
                previous = review.lookup(db, media, output_format)
                if (not retry_errors_only and previous
                        and previous[0] == source_signature):
                    previous_status, previous_identity = previous[1], previous[2]
                    if previous_status in ("completed", "duplicate") and previous_identity in existing:
                        skipped += 1
                        resumed += 1
                        continue
                    if previous_status == "error" and previous_identity != "retryable":
                        # Known source-data errors are queued for user review.
                        # Filesystem/IO failures are automatically retried.
                        deferred += 1
                        continue
                # Fast legacy resume: a verified output in the old Catalog is
                # retained. Compare media SHA to avoid skipping an edited song
                # merely because its filename or size matches.
                legacy = legacy_by_source.get(export.canonical_source_path(media))
                if (not retry_errors_only and previous is None and legacy
                        and media.stat().st_size == legacy[1]
                        and _fingerprint(media) == legacy[0]):
                    skipped += 1
                    resumed += 1
                    review.record(db, media=media, source_root=source_root,
                                  output_format=output_format,
                                  source_signature=source_signature,
                                  status="completed", identity=legacy[2])
                    continue
                source_code = media.stem.strip()
                if not source_code or len(source_code) > 140:
                    raise ValueError("ชื่อเพลงต้นทางไม่สามารถใช้เป็นรหัสได้")
                # Validate actual source cues BEFORE hashing/copying media. Invalid
                # source songs need no costly SHA-256 read of a large audio file.
                doc = _document(item, source_code, export, ncn)
                lyric_hash = _lyrics_digest(doc)
                source_hash = _fingerprint(media)
                identity = "json-pro/" + source_hash + "/" + output_format + "/" + lyric_hash[:24]
                if (source_hash, output_format, lyric_hash) in seen or identity in existing:
                    skipped += 1
                    review.record(db, media=media, source_root=source_root,
                                  output_format=output_format,
                                  source_signature=source_signature,
                                  status="duplicate", reason="เนื้อร้องและไฟล์เพลงซ้ำกับ Catalog ที่ยืนยันแล้ว",
                                  identity=identity)
                    continue
                # Allocate after fingerprint deduplication; existing songs never change.
                code = _next_code(used_codes, code_style, code_length, source_code, code_counters)
                doc["songCode"] = code
                # Store the actual Pro output in the SHARED XStageSong hierarchy.
                # Bucket follows assigned song code, not the source filename.
                bucket = code[0].upper() if code[0].upper() in (
                    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ") else "_"
                extension = (media.suffix.lower() if output_format == "original"
                             else "." + output_format)
                if extension in (".mid", ".midi"):
                    relative_audio = "MIDI/MID/SONG/" + bucket + "/" + code + extension
                    relative_lyrics = "MIDI/MID/LYRICS/" + bucket + "/" + code + ".json"
                elif extension == ".kar":
                    # KAR is self-contained and needs neither SONG nor external JSON.
                    relative_audio = "MIDI/KAR/" + bucket + "/" + code + extension
                    relative_lyrics = None
                elif extension in (".mp4", ".webm", ".avi", ".mkv", ".mov", ".mpg",
                                   ".mpeg", ".vob", ".dat", ".wmv", ".flv"):
                    category = "VIDEO/" + extension[1:].upper()
                    relative_audio = category + "/SONG/" + bucket + "/" + code + extension
                    relative_lyrics = category + "/LYRICS/" + bucket + "/" + code + ".json"
                else:
                    category = "AUDIO/" + extension[1:].upper()
                    relative_audio = category + "/SONG/" + bucket + "/" + code + extension
                    relative_lyrics = category + "/LYRICS/" + bucket + "/" + code + ".json"
                final_audio = export.safe_media_path(root, relative_audio, "audio")
                final_lyrics = (export.safe_media_path(root, relative_lyrics, "lyrics")
                                if relative_lyrics else None)
                # Recover an orphaned but verified pair if the process exited
                # after committing files and before the journal append.
                already_published_files = final_audio.exists() or (final_lyrics is not None and final_lyrics.exists())
                if already_published_files and not (
                        _can_recover_pair(media, final_audio, final_lyrics, source_hash,
                                          doc, output_format) if final_lyrics is not None
                        else (final_audio.is_file() and not final_audio.is_symlink()
                              and _fingerprint(final_audio) == source_hash)):
                    raise FileExistsError(
                        "ผลลัพธ์เก่าไม่ครบหรือไม่ตรงข้อมูล · ไม่เขียนทับไฟล์เดิม")
                if not already_published_files:
                    final_audio.parent.mkdir(parents=True, exist_ok=True)
                    if final_lyrics is not None:
                        final_lyrics.parent.mkdir(parents=True, exist_ok=True)
                    temp_audio = final_audio.with_name("." + final_audio.stem + ".partial" + final_audio.suffix)
                    temp_lyrics = (final_lyrics.with_name(final_lyrics.name + ".partial")
                                   if final_lyrics is not None else None)
                    if temp_audio.is_symlink() or (temp_lyrics is not None and temp_lyrics.is_symlink()):
                        raise ValueError("พบไฟล์ชั่วคราวแบบ Symbolic Link")
                    temp_audio.unlink(missing_ok=True)
                    if temp_lyrics is not None:
                        temp_lyrics.unlink(missing_ok=True)
                    try:
                        if output_format == "original":
                            # Verify the exact bytes during copying instead of
                            # reading the whole destination for a third time.
                            copy_hash = hashlib.sha256()
                            with media.open("rb") as reader, temp_audio.open("xb") as writer:
                                while True:
                                    if cancelled is not None and cancelled.is_set():
                                        raise RuntimeError("ยกเลิกการคัดลอกไฟล์ต้นฉบับ")
                                    block = reader.read(1024 * 1024)
                                    if not block:
                                        break
                                    copy_hash.update(block)
                                    writer.write(block)
                                writer.flush()
                                os.fsync(writer.fileno())
                            if copy_hash.hexdigest() != source_hash:
                                raise ValueError("ตรวจ SHA-256 ระหว่างคัดลอกต้นฉบับไม่ผ่าน")
                        else:
                            if convert is None:
                                raise ValueError("ไม่พบตัวแปลงเสียงของ PC Engine")
                            convert(media, temp_audio, output_format)
                            if not temp_audio.is_file() or temp_audio.stat().st_size < 1000:
                                raise ValueError("ไฟล์เสียงหลังแปลงไม่สมบูรณ์")
                        if temp_lyrics is not None:
                            with temp_lyrics.open("x", encoding="utf-8") as writer:
                                json.dump(doc, writer, ensure_ascii=False, allow_nan=False)
                                writer.write("\n")
                                writer.flush()
                                os.fsync(writer.fileno())
                        _publish_no_overwrite(temp_audio, final_audio)
                        if temp_lyrics is not None:
                            _publish_no_overwrite(temp_lyrics, final_lyrics)
                    finally:
                        temp_audio.unlink(missing_ok=True)
                        if temp_lyrics is not None:
                            temp_lyrics.unlink(missing_ok=True)
                title, artist = export.lyrics_identity(doc, source_code)
                record = {"webSongId": identity, "code": code,
                          "title": title or "ไม่ระบุชื่อเพลง",
                          "artist": artist or "ไม่ระบุศิลปิน", "bucket": bucket,
                          "audio": {"path": relative_audio},
                          "lyrics": {"path": relative_lyrics} if relative_lyrics else None,
                          "sourceFormat": item["kind"],
                          "sourceIdentity": {"sha256": source_hash,
                                             "canonicalPath": export.canonical_source_path(media),
                                             "bytes": media.stat().st_size,
                                             "outputFormat": output_format,
                                             "lyricsSha256": lyric_hash}}
                export.append_journal(root, record)
                registry.register_catalog_row(root, record)
                existing.add(identity)
                seen.add((source_hash, output_format, lyric_hash))
                review.record(db, media=media, source_root=source_root,
                              output_format=output_format,
                              source_signature=source_signature,
                              status="completed", identity=identity)
                created += 1
            except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
                errors += 1
                review.record(db, media=media, source_root=source_root,
                              output_format=output_format,
                              source_signature=source_signature,
                              status="error", reason=str(exc)[:500],
                              identity="retryable" if isinstance(exc, (OSError, RuntimeError)) else "")
                if len(issues) < 50:
                    issues.append({"name": item["name"], "reason": str(exc)[:200]})
            finally:
                if index % 128 == 0:
                    db.commit()
                checkpoint()
                if progress is not None:
                    progress(index, known_total, {"created": created, "skipped": skipped,
                                                    "errors": errors,
                                                    "resumed": resumed, "deferred": deferred})
    finally:
        try:
            checkpoint(force=True)
        finally:
            db.commit()
            db.close()
    if examined == 0:
        raise ValueError("ไม่พบเพลงที่มีเนื้อร้องพร้อมเวลาในต้นทาง")
    if not retry_errors_only and not created and not skipped and errors:
        raise ValueError("ไม่มีไฟล์ที่ส่งออกสำเร็จ: " +
                         "; ".join(item["reason"] for item in issues[:3]))
    return {"created": created, "skipped": skipped, "errors": errors,
            "resumed": resumed, "deferred": deferred,
            "incomplete": inspection.get("incompleteCount", len(inspection["incomplete"])),
            "unsupported": inspection.get("unsupportedCount", len(inspection["unsupported"])),
            "total": examined, "output": str(root), "issues": issues[:50],
            "message": (f"ส่งออก Lyrics JSON สำเร็จ {created} เพลง · ข้ามซ้ำ/มีแล้ว {skipped}"
                        f" · ต่อจากรุ่นเดิม {resumed} · ERR ค้างทบทวน {deferred} · ผิดพลาดใหม่ {errors} · ไม่ครบ {inspection.get('incompleteCount', len(inspection['incomplete']))}"
                        f" · ปลายทาง {root}")}
