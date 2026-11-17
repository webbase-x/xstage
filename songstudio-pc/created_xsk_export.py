"""Export existing catalogued MIDI + timed Lyrics JSON as portable XSK2.

XSK2 is an unencrypted ZIP wrapper with verified MIDI SHA-256. Original media
and lyric documents are never modified. XSK1 files are retained untouched;
invalid XSK2 files block unsafe deduplication and are never overwritten.
"""
from __future__ import annotations

import json
from pathlib import Path


def export_selected(root, selected, export, created_json, package, codes, key,
                    *, destination_root=None, cancelled=None, progress=None):
    root = Path(root)
    if not isinstance(selected, list) or not selected:
        raise ValueError("กรุณาเลือก Lyrics JSON อย่างน้อยหนึ่งรายการ")
    if any(not isinstance(item, str) for item in selected) or len(set(selected)) != len(selected):
        raise ValueError("รายการ Lyrics JSON ไม่ถูกต้องหรือซ้ำ")
    entries = created_json._records(root, export)
    # Output selection is independent of the catalog source folder.
    output_root = Path(destination_root).expanduser() if destination_root else root
    if output_root.is_symlink():
        raise ValueError("โฟลเดอร์ปลายทาง XSK ต้องไม่เป็น Symbolic Link")
    # No file may be published unless all existing XSKs can be authenticated.
    xsk_root = package.destination(output_root, "CHECK").parent.parent
    reserved = set()
    midi_hashes = set()
    if xsk_root.is_dir():
        for file in xsk_root.rglob("*"):
            if file.suffix.casefold() != ".xsk":
                continue
            if file.is_symlink() or not file.is_file():
                raise ValueError("XSK เดิมไม่ใช่ไฟล์ปกติ: " + str(file))
            # Preserve old encrypted XSK1 without requiring a key.
            # Reserve its filename but allow a NEW portable XSK2 from
            # the same original MIDI (never replace the old file).
            with file.open("rb") as old:
                legacy = old.read(4) == b"XSK1"
            if legacy:
                reserved.add(file.stem)
                continue
            try:
                existing = package.open_package(file)
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
    # Existing catalog codes are SOURCE identities, not occupied XSK filenames.
    # Reserve only verified XSK outputs so the first export preserves its code.
    allocator = codes.CodeAllocator(
        [], [], root, code_style="source", code_length=6)
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
            target = package.destination(output_root, code)
            if target.exists() or target.is_symlink():
                raise FileExistsError("XSK มีรหัสนี้อยู่แล้ว · ไม่เขียนทับ: " + code)
            # Catalog placeholders from an older Lyrics JSON export must not
            # override the real artist embedded in the JSON's NCN/KAR/LRC tags.
            # Manual catalog edits still take priority when they are genuine.
            doc_title, doc_artist = export.lyrics_identity(document, source.stem)
            record_title, record_artist = export.lyrics_identity(
                {"title": record.get("title"), "artist": record.get("artist")},
                source.stem)
            title = record_title or doc_title
            artist = record_artist or doc_artist
            if not title or not artist:
                raise ValueError("ขาดชื่อเพลงหรือศิลปินจริง · ข้ามเพลงเพื่อไม่บันทึก DB ผิด")
            package.seal(source, document, code, title, artist, target=target)
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
    if not result["created"] and not result["skipped"]:
        raise ValueError("ไม่พบเพลงที่สร้าง XSK สำเร็จ · " + "; ".join(result["issues"][:3]))
    return result
