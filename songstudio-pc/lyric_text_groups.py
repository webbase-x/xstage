"""Group and safely replace common intro/outro lyric lines in local X-Stage songs.

Only published LOCAL lyrics JSON and its synchronized .lrc are updated.
Original source songs, M4A, vocal files and Google Drive are never changed.
Each batch has a durable backup ZIP and a recoverable manifest in AppData.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
import unicodedata
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

POSITIONS = {
    "first": (0, "บรรทัดแรก"),
    "second": (1, "บรรทัดที่ 2"),
    "penultimate": (-2, "บรรทัดรองสุดท้าย"),
    "last": (-1, "บรรทัดสุดท้าย"),
}
TIMED = re.compile(r"^(\s*\[(?:\d{1,3}):(?:[0-5]\d)(?:[.:]\d{1,3})?\])(.*?)(\r?\n?)$")
ENHANCED = re.compile(r"<\d{1,3}:[0-5]\d(?:[.:]\d{1,3})?>")
MAX_TEXT = 400
MAX_ROWS = 400000


def _same(text):
    return unicodedata.normalize("NFC", str(text).strip())


def _group_id(position, text):
    return hashlib.sha256((position + "\0" + _same(text)).encode("utf-8")).hexdigest()[:24]


def _timestamped_rows(raw):
    chunks = raw.splitlines(keepends=True)
    found = []
    for index, part in enumerate(chunks):
        match = TIMED.match(part)
        if match:
            found.append((index, match))
        elif re.match(r"^\s*\[\d{1,3}:\d{2}", part):
            raise ValueError("พบ LRC แบบหลายเวลาในบรรทัดหรือรูปแบบเวลาไม่รองรับ")
    return chunks, found


def _load(root, row, export):
    lyric = row.get("lyrics") or {}
    rel = lyric.get("path")
    if not rel:
        return None
    path = export.safe_media_path(root, rel, "lyrics")
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    lines = doc.get("lines")
    if not isinstance(lines, list) or len(lines) < 4:
        return None
    if not all(isinstance(x, dict) and isinstance(x.get("text"), str) and
               isinstance(x.get("startTime"), (int, float)) and
               not isinstance(x.get("startTime"), bool) for x in lines):
        raise ValueError("Lyrics JSON ไม่มีบรรทัดและเวลาในรูปแบบที่รองรับ")
    # The companion LRC must be independently validated: a malicious
    # symlink inside lyrics/ must never redirect a bulk write outside songs/.
    lrc_rel = PurePosixPath(rel).with_suffix(".lrc").as_posix()
    lrc_path = export.safe_media_path(root, lrc_rel, "lyrics")
    raw = doc.get("rawLrc")
    file_raw = lrc_path.read_text(encoding="utf-8-sig") if lrc_path.is_file() else None
    if raw is None and file_raw is not None:
        raw = file_raw
    if raw is not None:
        if not isinstance(raw, str):
            raise ValueError("rawLrc ต้องเป็นข้อความ")
        if file_raw is not None and raw.replace("\r\n", "\n") != file_raw.replace("\r\n", "\n"):
            raise ValueError("ไฟล์ JSON และ LRC มีเนื้อหาต่างกัน กรุณาตรวจเพลงก่อนแก้ไข")
        chunks, found = _timestamped_rows(raw)
        if len(found) != len(lines):
            raise ValueError("จำนวนบรรทัด JSON และ LRC ไม่ตรงกัน")
        for (_, match), line in zip(found, lines):
            # Word-level cues are allowed for non-edited lines; after replacing
            # one lyric line they are removed from that line only.
            if _same(ENHANCED.sub("", match.group(2))) != _same(line["text"]):
                raise ValueError("ลำดับคำร้องใน JSON และ LRC ไม่ตรงกัน")
    return path, lrc_path if file_raw is not None else None, doc, raw


def _replacement(document, raw, position, new_text):
    lines = document["lines"]
    index = POSITIONS[position][0]
    changed = json.loads(json.dumps(document, ensure_ascii=False))
    changed_line = changed["lines"][index]
    changed_line["text"] = new_text
    # Enhanced LRC syllable timing belongs to the old words; retaining it
    # would display wrongly highlighted syllables. Preserve line timing only.
    had_syllables = bool(changed_line.pop("syllables", None))
    updated_raw = None
    if raw is not None:
        chunks, entries = _timestamped_rows(raw)
        chunk_idx, match = entries[index]
        chunks[chunk_idx] = match.group(1) + new_text + match.group(3)
        updated_raw = "".join(chunks)
        changed["rawLrc"] = updated_raw
    return changed, updated_raw, had_syllables


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _atomic_bytes(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".xstage-bulk-",
                                         suffix=".tmp", delete=False) as out:
            name = Path(out.name)
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        if name:
            name.unlink(missing_ok=True)


def _record_bytes(root, row, export):
    loaded = _load(root, row, export)
    if loaded is None:
        return None
    path, lrc, doc, raw = loaded
    return path, lrc, doc, raw


def scan(root, export, *, cancelled=None, on_progress=None):
    root = Path(root).expanduser().resolve()
    if not (root / "current.json").is_file():
        raise ValueError("ยังไม่มีคลังเพลงที่สร้างแล้ว กรุณาสร้างเพลงให้มี songs/current.json ก่อน")
    pointer, _ = export._read_current(root)
    entries = export.existing_records(root)
    if len(entries) > MAX_ROWS:
        raise ValueError("จำนวนรายการเพลงเกินขนาดที่รุ่นนี้รองรับ")
    grouped = {name: defaultdict(list) for name in POSITIONS}
    included = excluded = missing = 0
    seen = set()
    for number, row in enumerate(entries, 1):
        if cancelled is not None and cancelled.is_set():
            raise RuntimeError("ยกเลิกการวิเคราะห์ข้อความ · ยังไม่ได้แก้ไขเพลง")
        if not isinstance(row, dict) or not row.get("webSongId"):
            excluded += 1
            continue
        song_id = row["webSongId"]
        if song_id in seen:
            continue
        seen.add(song_id)
        try:
            parsed = _record_bytes(root, row, export)
        except (OSError, ValueError, TypeError, KeyError, UnicodeError):
            excluded += 1
            continue
        if parsed is None:
            missing += 1
            continue
        _, _, doc, _ = parsed
        included += 1
        for pos, (index, _) in POSITIONS.items():
            text = _same(doc["lines"][index]["text"])
            if not text:
                continue
            ident = _group_id(pos, text)
            grouped[pos][ident].append({
                "songId": song_id, "code": str(row.get("code") or ""),
                "title": str(row.get("title") or ""),
                "artist": str(row.get("artist") or ""),
                "text": text, "record": row,
            })
        if on_progress and number % 500 == 0:
            on_progress(f"อ่านเนื้อร้องแล้ว {number:,}/{len(entries):,} เพลง · ตรวจใช้ได้ {included:,}", number)
    group_lookup = {}
    for pos, groups in grouped.items():
        for ident, members in groups.items():
            group_lookup[ident] = {
                "id": ident, "position": pos, "label": POSITIONS[pos][1],
                "text": members[0]["text"], "count": len(members),
                "members": members
            }
    return {
        "root": str(root), "generation": pointer.get("generation"),
        "groups": group_lookup, "songs": included,
        "skippedInvalid": excluded, "withoutLyrics": missing,
        "inspected": len(entries), "groupCount": len(group_lookup),
    }


def list_groups(snapshot, position, *, search="", offset=0, limit=40, repeats_only=True):
    if position not in POSITIONS:
        raise ValueError("ตำแหน่งบรรทัดไม่ถูกต้อง")
    query = _same(search).casefold()
    groups = [g for g in snapshot["groups"].values()
              if g["position"] == position
              and (not repeats_only or g["count"] >= 2)
              and (not query or query in g["text"].casefold())]
    groups.sort(key=lambda x: (-x["count"], x["text"].casefold()))
    page = groups[offset:offset+limit]
    return {
        "position": position, "label": POSITIONS[position][1],
        "total": len(groups), "offset": offset,
        "rows": [{"id": g["id"], "position": g["position"], "text": g["text"],
                  "count": g["count"]} for g in page],
        "songs": snapshot["songs"], "inspected": snapshot["inspected"],
        "skippedInvalid": snapshot["skippedInvalid"],
        "withoutLyrics": snapshot["withoutLyrics"],
    }


def preview(snapshot, group_id, limit=12):
    g = snapshot["groups"].get(group_id)
    if not g:
        raise ValueError("ไม่พบกลุ่มข้อความ กรุณาวิเคราะห์คลังเพลงใหม่")
    return {
        "id": g["id"], "text": g["text"], "position": g["position"],
        "label": g["label"], "count": g["count"],
        "examples": [{"code": s["code"], "title": s["title"],
                      "artist": s["artist"]} for s in g["members"][:limit]],
    }


def apply(root, export, snapshot, group_id, new_text, backup_root,
          *, expected_count, cancelled=None, on_progress=None):
    root = Path(root).expanduser().resolve()
    group = snapshot["groups"].get(group_id)
    if not group or snapshot["root"] != str(root):
        raise ValueError("กลุ่มข้อความนี้หมดอายุ กรุณาวิเคราะห์คลังอีกครั้ง")
    if not isinstance(new_text, str):
        raise ValueError("กรุณาระบุข้อความใหม่")
    new_text = unicodedata.normalize("NFC", new_text.strip())
    if (not new_text or len(new_text) > MAX_TEXT or
            "\r" in new_text or "\n" in new_text or "\0" in new_text):
        raise ValueError("ข้อความแทนที่ต้องเป็นบรรทัดเดียว ความยาวไม่เกิน 400 ตัวอักษร")
    if _same(new_text) == group["text"]:
        raise ValueError("ข้อความใหม่เหมือนข้อความเดิม ไม่จำเป็นต้องเปลี่ยน")
    if type(expected_count) is not int or expected_count != group["count"]:
        raise ValueError("จำนวนเพลงเปลี่ยนไป กรุณาตรวจกลุ่มใหม่ก่อนยืนยัน")
    pointer, _ = export._read_current(root)
    if pointer.get("generation") != snapshot["generation"]:
        raise ValueError("ฐานเพลงมีการเปลี่ยนแปลงหลังวิเคราะห์ กรุณากดวิเคราะห์อีกครั้ง")
    # Preflight the entire batch before modifying any local output. Any
    # external edit detected now aborts the batch, not just an individual song.
    changes = []
    for number, item in enumerate(group["members"], 1):
        if cancelled is not None and cancelled.is_set():
            raise RuntimeError("ยกเลิกก่อนแก้ไข · เพลงยังไม่เปลี่ยนแปลง")
        path, lrc, doc, raw = _record_bytes(root, item["record"], export)
        pos = POSITIONS[group["position"]][0]
        if _same(doc["lines"][pos]["text"]) != group["text"]:
            raise ValueError("ข้อความในเพลงมีการแก้ไขหลังวิเคราะห์ กรุณาสแกนใหม่: " + item["code"])
        revised, revised_lrc, lost_tokens = _replacement(
            doc, raw, group["position"], new_text)
        original_json = path.read_bytes()
        new_json = (json.dumps(revised, ensure_ascii=False,
                               separators=(",", ":")) + "\n").encode("utf-8")
        before = [(path, original_json, new_json)]
        if lrc is not None:
            if revised_lrc is None:
                raise ValueError("LRC ไม่พร้อมแก้ไข: " + item["code"])
            before.append((lrc, lrc.read_bytes(), revised_lrc.encode("utf-8")))
        changes.append({"files": before, "songId": item["songId"],
                        "lostTokens": lost_tokens})
        if on_progress and number % 300 == 0:
            on_progress(f"ตรวจเงื่อนไขและเตรียมสำรอง {number:,}/{group['count']:,} เพลง", number)
    # A full backup is written before the first replace and is never removed
    # automatically. The restore action checks post-edit hashes before undo.
    backup_root = Path(backup_root)
    backup_root.mkdir(parents=True, exist_ok=True)
    operation = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + secrets.token_hex(4)
    zip_path = backup_root / (operation + ".zip")
    manifest_path = backup_root / (operation + ".json")
    files = []
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=3) as bundle:
        for item in changes:
            for path, original, revised in item["files"]:
                rel = path.relative_to(root).as_posix()
                bundle.writestr(rel, original)
                files.append({"path": rel, "before": _sha(original),
                              "after": _sha(revised)})
    manifest = {
        "version": 1, "id": operation, "state": "prepared",
        "root": str(root), "position": group["position"],
        "oldText": group["text"], "newText": new_text,
        "songs": len(changes), "files": files, "createdAt": datetime.now(timezone.utc).isoformat()
    }
    _atomic_bytes(manifest_path, (json.dumps(manifest, ensure_ascii=False) + "\n").encode("utf-8"))
    # Update in-place only after the complete backup exists.
    try:
        for number, item in enumerate(changes, 1):
            if cancelled is not None and cancelled.is_set():
                raise RuntimeError("ผู้ใช้ยกเลิกการแทนที่ · กำลังคืนข้อความเดิม")
            for path, before, revised in item["files"]:
                if _sha(path.read_bytes()) != _sha(before):
                    raise ValueError("ไฟล์เพลงเปลี่ยนระหว่างแก้ไข กำลังคืนค่าเดิม: " + str(path.name))
                _atomic_bytes(path, revised)
            if on_progress and number % 100 == 0:
                on_progress(f"แทนที่ข้อความแล้ว {number:,}/{len(changes):,} เพลง", number)
    except BaseException:
        try:
            _restore_files(root, zip_path, files, strict=False)
            manifest["state"] = "rolled-back"
            _atomic_bytes(manifest_path, (json.dumps(manifest, ensure_ascii=False) + "\n").encode("utf-8"))
        except Exception:
            manifest["state"] = "recovery-required"
            _atomic_bytes(manifest_path, (json.dumps(manifest, ensure_ascii=False) + "\n").encode("utf-8"))
        raise
    manifest["state"] = "committed"
    _atomic_bytes(manifest_path, (json.dumps(manifest, ensure_ascii=False) + "\n").encode("utf-8"))
    return {
        "message": f"แก้ข้อความ {group['label']} สำเร็จ {len(changes):,} เพลง · ไฟล์เสียงและเวลาเดิมไม่เปลี่ยน",
        "changedSongs": len(changes), "changedFiles": len(files),
        "removedSyllableCues": sum(bool(x["lostTokens"]) for x in changes),
        "backupId": operation,
    }


def _restore_files(root, archive, file_specs, *, strict=True):
    with zipfile.ZipFile(archive) as bundle:
        # Always validate hashes before ANY writes during user-requested undo.
        if strict:
            for spec in file_specs:
                path = (root / spec["path"]).resolve()
                if not path.is_relative_to(root):
                    raise ValueError("พาธไฟล์สำรองไม่ปลอดภัย")
                if not path.is_file() or _sha(path.read_bytes()) != spec["after"]:
                    raise ValueError("ไฟล์มีการแก้ไขภายหลัง ไม่สามารถย้อนคืนทั้งชุดโดยไม่ทับข้อมูลใหม่")
        for spec in file_specs:
            path = (root / spec["path"]).resolve()
            if not path.is_relative_to(root):
                raise ValueError("พาธไฟล์สำรองไม่ปลอดภัย")
            original = bundle.read(spec["path"])
            if _sha(original) != spec["before"]:
                raise ValueError("ไฟล์สำรองไม่ครบหรือถูกเปลี่ยนแปลง")
            if strict or path.is_file() and _sha(path.read_bytes()) == spec["after"]:
                _atomic_bytes(path, original)


def latest_backup(backup_root, root):
    backup_root = Path(backup_root)
    if not backup_root.is_dir():
        return None
    for path in sorted(backup_root.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("root") == str(Path(root).expanduser().resolve()) and data.get("state") == "committed":
                return {k: data[k] for k in ("id", "position", "oldText", "newText", "songs", "createdAt")}
        except (ValueError, KeyError, OSError):
            continue
    return None


def undo(backup_root, root, operation):
    root = Path(root).expanduser().resolve()
    if not isinstance(operation, str) or not re.fullmatch(r"\d{8}T\d{12}Z-[0-9a-f]{8}", operation):
        raise ValueError("รหัสชุดสำรองไม่ถูกต้อง")
    base = Path(backup_root)
    manifest_path = base / (operation + ".json")
    backup_zip = base / (operation + ".zip")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if data.get("root") != str(root) or data.get("state") != "committed":
        raise ValueError("ชุดสำรองไม่ตรงกับคลังปัจจุบันหรือย้อนคืนไปแล้ว")
    _restore_files(root, backup_zip, data["files"], strict=True)
    data["state"] = "undone"
    _atomic_bytes(manifest_path, (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8"))
    return {"message": f"ย้อนคืนข้อความ {data['songs']:,} เพลงสำเร็จ · ไฟล์เสียงไม่เปลี่ยน",
            "restoredSongs": data["songs"], "backupId": operation}
