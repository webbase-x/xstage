"""Safe, non-semantic formatting of already-generated X-Stage Lyrics JSON.

Only JSON referenced by the local immutable published catalog is selectable.
Never renames or modifies audio, never invents timestamps, never edits source LRC.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

TOP_KEYS = ("schemaVersion", "songCode", "audioOffsetMs", "lines", "rawLrc")
LINE_KEYS = ("startTime", "endTime", "text", "syllables")
SYLLABLE_KEYS = ("text", "start", "duration")


def _ordered(data, keys):
    return {**{k: data[k] for k in keys if k in data},
            **{k: v for k, v in data.items() if k not in keys}}


def _canonical(document):
    result = _ordered(document, TOP_KEYS)
    result["lines"] = [
        {**_ordered(line, LINE_KEYS),
         **({"syllables": [_ordered(s, SYLLABLE_KEYS) for s in line["syllables"]]}
            if isinstance(line.get("syllables"), list) else {})}
        for line in document["lines"]]
    return json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def _validate(doc, expected_code=None):
    if not isinstance(doc, dict) or doc.get("schemaVersion") != 1:
        raise ValueError("Lyrics JSON ต้องเป็น schemaVersion 1")
    if not isinstance(doc.get("songCode"), str):
        raise ValueError("ไม่มี songCode ชนิดข้อความ")
    if expected_code and doc["songCode"] != expected_code:
        raise ValueError("รหัสใน Lyrics JSON ไม่ตรงกับ Catalog: " + expected_code)
    if not isinstance(doc.get("audioOffsetMs", 0), int) or isinstance(doc.get("audioOffsetMs", 0), bool):
        raise ValueError("audioOffsetMs ต้องเป็นจำนวนเต็ม")
    lines = doc.get("lines")
    if not isinstance(lines, list) or not lines:
        raise ValueError("ไม่มีรายการเนื้อร้องที่มีเวลา")
    for i, line in enumerate(lines):
        if not isinstance(line, dict) or not isinstance(line.get("text"), str):
            raise ValueError(f"บรรทัด {i+1}: ไม่มีข้อความ")
        start, end = line.get("startTime"), line.get("endTime")
        if (isinstance(start, bool) or isinstance(end, bool)
                or not isinstance(start, (int, float))
                or not isinstance(end, (int, float))
                or not (0 <= start < end < float("inf"))):
            raise ValueError(f"บรรทัด {i+1}: เวลาไม่ถูกต้อง")
        if i and start < lines[i-1]["startTime"]:
            raise ValueError(f"บรรทัด {i+1}: เวลาเริ่มย้อนกลับ")
        if "syllables" in line:
            if not isinstance(line["syllables"], list):
                raise ValueError(f"บรรทัด {i+1}: syllables ไม่ใช่รายการ")
            for syllable in line["syllables"]:
                if (not isinstance(syllable, dict)
                        or not isinstance(syllable.get("text"), str)
                        or isinstance(syllable.get("start"), bool)
                        or not isinstance(syllable.get("start"), (int, float))
                        or isinstance(syllable.get("duration"), bool)
                        or not isinstance(syllable.get("duration"), (int, float))
                        or not (0 <= syllable["start"] < float("inf"))
                        or not (0 <= syllable["duration"] < float("inf"))):
                    raise ValueError(f"บรรทัด {i+1}: syllable ไม่ถูกต้อง")
    if "rawLrc" in doc and not isinstance(doc["rawLrc"], str):
        raise ValueError("rawLrc ต้องเป็นข้อความ")


def _records(root, export):
    result = {}
    for row in export.existing_records(root):
        lyrics = row.get("lyrics") or {}
        if not isinstance(lyrics, dict) or not lyrics.get("path"):
            continue
        try:
            path = export.safe_media_path(root, lyrics["path"], "lyrics")
            if path.suffix.lower() != ".json" or path.is_symlink() or not path.is_file():
                continue
            key = lyrics["path"]
            result[key] = (path, row)
        except (ValueError, OSError, KeyError, TypeError):
            continue
    return result


def list_created(root, export, *, search="", offset=0, limit=100):
    rows = _records(root, export)
    needle = str(search).casefold().strip()
    result = []
    for key, (path, record) in sorted(rows.items()):
        code = str(record.get("code") or "")
        title = str(record.get("title") or "")
        artist = str(record.get("artist") or "")
        if needle and not any(needle in x.casefold() for x in (key, code, title, artist)):
            continue
        status = "valid"
        try:
            if path.stat().st_size > 5_000_000:
                raise ValueError("ไฟล์ JSON ใหญ่ผิดปกติ")
            doc = json.loads(path.read_text(encoding="utf-8-sig"))
            _validate(doc, code or None)
            status = "needs-format" if path.read_bytes() != _canonical(doc).encode("utf-8") else "formatted"
        except (OSError, ValueError, TypeError, UnicodeError) as exc:
            status = "error: " + str(exc)[:160]
        result.append({"path": key, "code": code, "title": title,
                       "artist": artist, "status": status})
    return {"total": len(result), "rows": result[max(0, offset):max(0, offset)+max(1, min(limit, 200))]}


def format_created(root, export, paths, *, dry_run=True):
    if not isinstance(paths, list) or not 1 <= len(paths) <= 100 or not all(isinstance(x, str) for x in paths):
        raise ValueError("เลือกไฟล์ Lyrics JSON ครั้งละ 1–100 รายการ")
    rows = _records(root, export)
    if len(set(paths)) != len(paths):
        raise ValueError("มีรายการซ้ำในคำสั่ง")
    results = []
    for key in paths:
        if key not in rows:
            results.append({"path": key, "status": "skipped", "reason": "ไม่พบใน Catalog"})
            continue
        path, record = rows[key]
        try:
            if path.is_symlink() or path.stat().st_size > 5_000_000:
                raise ValueError("ไฟล์ไม่ปลอดภัยหรือใหญ่ผิดปกติ")
            before = path.read_bytes()
            doc = json.loads(before.decode("utf-8-sig"))
            _validate(doc, str(record.get("code") or "") or None)
            after = _canonical(doc).encode("utf-8")
            if before == after:
                results.append({"path": key, "status": "unchanged"})
                continue
            if not dry_run:
                if path.read_bytes() != before:
                    raise RuntimeError("ไฟล์ถูกเปลี่ยนระหว่างตรวจ กรุณาตรวจอีกครั้ง")
                suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                backup = path.with_name(path.name + ".before-format-" + suffix + "-" + secrets.token_hex(3) + ".bak")
                with backup.open("xb") as stream:
                    stream.write(before)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    temporary = path.with_name("." + path.name + "." + secrets.token_hex(6) + ".tmp")
                    try:
                        with temporary.open("xb") as stream:
                            stream.write(after)
                            stream.flush()
                            os.fsync(stream.fileno())
                        os.replace(temporary, path)
                    finally:
                        temporary.unlink(missing_ok=True)
                except BaseException:
                    shutil.copy2(backup, path)
                    raise
                results.append({"path": key, "status": "formatted", "backup": backup.name,
                                "sha256": hashlib.sha256(after).hexdigest()})
            else:
                results.append({"path": key, "status": "would-format", "bytesBefore": len(before),
                                "bytesAfter": len(after)})
        except (OSError, ValueError, TypeError, UnicodeError, RuntimeError) as exc:
            results.append({"path": key, "status": "skipped", "reason": str(exc)[:200]})
    return {"dryRun": dry_run, "results": results,
            "formatted": sum(row["status"] in ("formatted", "would-format") for row in results),
            "skipped": sum(row["status"] == "skipped" for row in results)}


def restore_created(root, export, key, backup_name, expected_sha256):
    if not all(isinstance(x, str) for x in (key, backup_name, expected_sha256)):
        raise ValueError("ข้อมูลย้อนคืนไม่ถูกต้อง")
    records = _records(root, export)
    if key not in records:
        raise ValueError("ไฟล์ไม่อยู่ในคลังที่เผยแพร่")
    path, record = records[key]
    if not backup_name.startswith(path.name + ".before-format-") or not backup_name.endswith(".bak") or "/" in backup_name or "\\" in backup_name:
        raise ValueError("ชื่อไฟล์สำรองไม่ถูกต้อง")
    backup = path.with_name(backup_name)
    if backup.is_symlink() or not backup.is_file():
        raise ValueError("ไม่พบไฟล์สำรอง")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError("ไฟล์ปัจจุบันเปลี่ยนไปหลังจัดรูปแบบ ไม่ย้อนคืนทับข้อมูลใหม่")
    source = backup.read_bytes()
    _validate(json.loads(source.decode("utf-8-sig")), str(record.get("code") or "") or None)
    temporary = path.with_name("." + path.name + "." + secrets.token_hex(6) + ".tmp")
    try:
        with temporary.open("xb") as out:
            out.write(source)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"ok": True, "message": "ย้อนคืน Lyrics JSON จากไฟล์สำรองแล้ว"}
