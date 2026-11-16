"""Export verified media + timed Lyrics JSON to a separate local XStageSong catalog.

Never edit original media. Each completed pair is checkpointed before an atomic
catalog pointer switch; stop/resume skips already published source fingerprints.
Unsupported or malformed pairs are reported, not published as playable songs.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

MEDIA_EXT = {".mid", ".midi", ".kar", ".mp3", ".m4a", ".wav", ".aac",
             ".flac", ".ogg", ".oga", ".wma", ".mp4", ".webm", ".avi",
             ".mkv", ".mov", ".mpg", ".mpeg", ".vob", ".dat", ".wmv", ".flv"}
AUDIO_FORMATS = {"original", "m4a", "mp3", "wav", "flac", "ogg"}


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
        return doc
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
    return doc


def export_folder(source_folder, destination_folder, *, output_format, export, scanner,
                  ncn=None, convert=None, cancelled=None, progress=None):
    """Create a local Karaoke-compatible catalog; never publish to Google Drive.

    output_format is a constrained FFmpeg output extension or 'original'.
    """
    if output_format not in AUDIO_FORMATS:
        raise ValueError("ไม่รองรับรูปแบบเสียงที่เลือก")
    source = Path(source_folder).expanduser()
    destination = Path(destination_folder).expanduser()
    if (not source.is_dir() or source.is_symlink() or not destination_folder
            or destination.is_symlink()):
        raise ValueError("กรุณาเลือกต้นทางและปลายทางที่เป็นโฟลเดอร์ปกติ")
    root = export.songs_root(destination)
    src_real = source.resolve()
    root_real = root.resolve()
    if src_real == root_real or src_real in root_real.parents or root_real in src_real.parents:
        raise ValueError("ต้นทางและปลายทางต้องแยกจากกัน เพื่อไม่ให้อ่านหรือเขียนวนทับคลังเดิม")
    inspection = scanner.scan(str(source), ncn=ncn)
    entries = inspection["complete"]
    root.mkdir(parents=True, exist_ok=True)
    prior = export.existing_records(root)
    seen = set()
    existing = set()
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
    created = skipped = errors = 0
    issues = []
    staged_records = []
    for index, item in enumerate(entries, 1):
        if cancelled is not None and cancelled.is_set():
            raise RuntimeError("ยกเลิกการส่งออกแล้ว · คงไฟล์ที่สำเร็จไว้สำหรับเริ่มต่อ")
        media = next((path for path, _ in item["files"]
                      if path.suffix.lower() in MEDIA_EXT), None)
        if media is None:
            skipped += 1
            continue
        final_audio = final_lyrics = None
        try:
            source_hash = _fingerprint(media)
            code = media.stem.strip()
            if not code or len(code) > 140:
                raise ValueError("ชื่อเพลงต้นทางไม่สามารถใช้เป็นรหัสได้")
            doc = _document(item, code, export, ncn)
            lyric_hash = _lyrics_digest(doc)
            identity = "json-pro/" + source_hash + "/" + output_format + "/" + lyric_hash[:24]
            if (source_hash, output_format, lyric_hash) in seen or identity in existing:
                skipped += 1
                continue
            # Distinct lyric versions produce separate immutable exports,
            # even when the MIDI/audio file bytes remain identical.
            slug = (source_hash[:18] + "-" + lyric_hash[:12] +
                    ("-raw" if output_format == "original" else "-" + output_format))
            bucket = export.source_bucket(media.name)
            relative_audio = "audio/" + bucket + "/" + slug + (
                media.suffix.lower() if output_format == "original"
                else "." + output_format)
            relative_lyrics = "lyrics/" + bucket + "/" + slug + ".json"
            final_audio = export.safe_media_path(root, relative_audio, "audio")
            final_lyrics = export.safe_media_path(root, relative_lyrics, "lyrics")
            if final_audio.exists() or final_lyrics.exists():
                # The only safe automatic resume is an already published pair.
                raise FileExistsError("มีชื่อไฟล์ผลลัพธ์อยู่แล้วแต่ยังไม่อยู่ใน Catalog")
            final_audio.parent.mkdir(parents=True, exist_ok=True)
            final_lyrics.parent.mkdir(parents=True, exist_ok=True)
            temp_audio = final_audio.with_name("." + final_audio.stem + ".partial" + final_audio.suffix)
            temp_lyrics = final_lyrics.with_name(final_lyrics.name + ".partial")
            if temp_audio.is_symlink() or temp_lyrics.is_symlink():
                raise ValueError("พบไฟล์ชั่วคราวแบบ Symbolic Link")
            temp_audio.unlink(missing_ok=True)
            temp_lyrics.unlink(missing_ok=True)
            try:
                if output_format == "original":
                    with media.open("rb") as reader, temp_audio.open("xb") as writer:
                        while True:
                            if cancelled is not None and cancelled.is_set():
                                raise RuntimeError("ยกเลิกการคัดลอกไฟล์ต้นฉบับ")
                            block = reader.read(1024 * 1024)
                            if not block:
                                break
                            writer.write(block)
                        writer.flush()
                        os.fsync(writer.fileno())
                    if _fingerprint(temp_audio) != source_hash:
                        raise ValueError("ตรวจ SHA-256 หลังคัดลอกต้นฉบับไม่ผ่าน")
                else:
                    if convert is None:
                        raise ValueError("ไม่พบตัวแปลงเสียงของ PC Engine")
                    convert(media, temp_audio, output_format)
                    if not temp_audio.is_file() or temp_audio.stat().st_size < 1000:
                        raise ValueError("ไฟล์เสียงหลังแปลงไม่สมบูรณ์")
                with temp_lyrics.open("x", encoding="utf-8") as writer:
                    json.dump(doc, writer, ensure_ascii=False, allow_nan=False)
                    writer.write("\n")
                    writer.flush()
                    os.fsync(writer.fileno())
                os.replace(temp_audio, final_audio)
                os.replace(temp_lyrics, final_lyrics)
            finally:
                temp_audio.unlink(missing_ok=True)
                temp_lyrics.unlink(missing_ok=True)
            title = doc.get("title") if isinstance(doc.get("title"), str) else ""
            artist = doc.get("artist") if isinstance(doc.get("artist"), str) else ""
            record = {"webSongId": identity, "code": code,
                      "title": title.strip() or code,
                      "artist": artist.strip(), "bucket": bucket,
                      "audio": {"path": relative_audio},
                      "lyrics": {"path": relative_lyrics},
                      "sourceFormat": item["kind"],
                      "sourceIdentity": {"sha256": source_hash,
                                         "canonicalPath": export.canonical_source_path(media),
                                         "bytes": media.stat().st_size,
                                         "outputFormat": output_format,
                                         "lyricsSha256": lyric_hash}}
            export.append_journal(root, record)
            staged_records.append(record)
            existing.add(identity)
            seen.add((source_hash, output_format, lyric_hash))
            created += 1
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            errors += 1
            issues.append({"name": item["name"], "reason": str(exc)[:200]})
        if progress is not None:
            progress(index, len(entries), {"created": created, "skipped": skipped,
                                            "errors": errors})
    pending = export.journal_records(root)
    if pending:
        export.publish_batch(root, pending)
        export.clear_published_journal(root)
    if not entries:
        raise ValueError("ไม่พบเพลงที่มีเนื้อร้องพร้อมเวลาในต้นทาง")
    if not created and not skipped and errors:
        raise ValueError("ไม่มีไฟล์ที่ส่งออกสำเร็จ: " +
                         "; ".join(item["reason"] for item in issues[:3]))
    return {"created": created, "skipped": skipped, "errors": errors,
            "incomplete": len(inspection["incomplete"]),
            "unsupported": len(inspection["unsupported"]),
            "total": len(entries), "output": str(root), "issues": issues[:50],
            "message": (f"ส่งออก Lyrics JSON สำเร็จ {created} เพลง · ข้ามซ้ำ {skipped}"
                        f" · ผิดพลาด {errors} · ไม่ครบ {len(inspection['incomplete'])}"
                        f" · ปลายทาง {root}")}
