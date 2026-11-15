"""Safely seal existing catalogued MIDI + Lyrics JSON as XSK (Pro only).

No original media or lyric documents are modified. XSK target naming and
encryption are inherited from xsk_package. A corrupt/unreadable existing XSK
blocks the operation rather than silently circumventing duplicate detection.
"""
from __future__ import annotations

import json
from pathlib import Path


def export_selected(root, selected, export, created_json, package, codes, key,
                    *, cancelled=None, progress=None):
    root = Path(root)
    if not isinstance(selected, list) or not 1 <= len(selected) <= 100:
        raise ValueError("เลือก Lyrics JSON ครั้งละ 1–100 รายการ")
    if any(not isinstance(item, str) for item in selected) or len(set(selected)) != len(selected):
        raise ValueError("รายการ Lyrics JSON ไม่ถูกต้องหรือซ้ำ")
    entries = created_json._records(root, export)
    # No file may be published unless all existing XSKs can be authenticated.
    xsk_root = root / "MIDI" / "XSK"
    reserved = set()
    midi_hashes = set()
    if xsk_root.is_dir():
        for file in xsk_root.rglob("*"):
            if file.suffix.casefold() != ".xsk":
                continue
            if file.is_symlink() or not file.is_file():
                raise ValueError("XSK เดิมไม่ใช่ไฟล์ปกติ: " + str(file))
            try:
                existing = package.open_package(file, key)
                code = existing["songCode"]
                digest = existing["audio"]["sha256"]
                if (not isinstance(code, str) or not package.CODE_RE.fullmatch(code)
                        or not isinstance(digest, str) or len(digest) != 64
                        or file.stem.casefold() != code.casefold()):
                    raise ValueError("ข้อมูลภายในและชื่อไฟล์ไม่ตรงกัน")
            except Exception as exc:
                raise ValueError("ตรวจ XSK เดิมไม่ได้ หยุดเพื่อรักษาข้อมูล: " + file.name) from exc
            reserved.add(code)
            midi_hashes.add(digest)
    allocator = codes.CodeAllocator(
        export.existing_records(root), [], root, code_style="source", code_length=6)
    for code in reserved:
        allocator.used.add(code.casefold())
        allocator._track_numeric(code)
    result = {"created": 0, "skipped": 0, "errors": 0, "issues": [],
              "output": str(xsk_root), "total": len(selected)}
    for position, item in enumerate(selected, 1):
        if cancelled is not None and cancelled.is_set():
            raise RuntimeError("ยกเลิกการสร้าง XSK แล้ว · เก็บไฟล์ที่สร้างสำเร็จไว้")
        try:
            if item not in entries:
                raise ValueError("ไม่พบไฟล์ Lyrics JSON ใน Catalog")
            lyric_path, record = entries[item]
            audio_data = record.get("audio") or {}
            midi_rel = audio_data.get("path")
            if not isinstance(midi_rel, str):
                raise ValueError("รายการไม่มีไฟล์เพลง")
            source = export.safe_media_path(root, midi_rel, "audio")
            if (source.suffix.casefold() not in (".mid", ".midi", ".kar")
                    or not source.is_file() or source.is_symlink()):
                raise ValueError("XSK รองรับเฉพาะไฟล์ MIDI/KAR และ Lyrics JSON ที่ครบคู่")
            if lyric_path.is_symlink() or not lyric_path.is_file() or lyric_path.stat().st_size > package.MAX_DOC:
                raise ValueError("Lyrics JSON ไม่ปลอดภัยหรือไฟล์ใหญ่เกินกำหนด")
            document = json.loads(lyric_path.read_text(encoding="utf-8-sig"))
            created_json._validate(document, str(record.get("code") or "") or None)
            sha = package._hash_source(source)
            if sha in midi_hashes:
                result["skipped"] += 1
                continue
            preferred = str(record.get("code") or source.stem)
            code = allocator.assign_new(preferred)
            target = package.destination(root, code)
            if target.exists() or target.is_symlink():
                raise FileExistsError("XSK มีรหัสนี้อยู่แล้ว · ไม่เขียนทับ: " + code)
            title = str(record.get("title") or document.get("title") or code)
            artist = str(record.get("artist") or document.get("artist") or "X-Stage Song Studio")
            package.seal(source, document, code, title, artist, key, target=target)
            midi_hashes.add(sha)
            result["created"] += 1
        except (ValueError, OSError, TypeError, KeyError, RuntimeError) as exc:
            result["errors"] += 1
            result["issues"].append(str(item) + ": " + str(exc))
        finally:
            if progress is not None:
                progress(position, result)
    result["issues"] = result["issues"][-50:]
    result["message"] = (
        f"สร้าง XSK ใหม่ {result['created']} เพลง · ข้าม MIDI ซ้ำ {result['skipped']} "
        f"· ผิดพลาด {result['errors']}"
    )
    return result
