"""Offline XStageSong/AUDIO + LYRICS export for Karaoke PC.

Source: Song Studio XStageSong (audio/, lyrics/, current.json).
Destination: user-selected parent/XStageSong, or XStageSong itself.
Neither Drive credentials nor a Windows installer are required.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import tempfile
from datetime import datetime, timezone

SCHEMA = 1
FORMAT = "xstage-pc-local-current"
CATALOG = "xstage-pc-local-catalog"
ALLOWED_MEDIA = {".mp3", ".m4a", ".mp4", ".aac", ".wav", ".wma",
                 ".flac", ".ogg", ".oga", ".mid", ".midi", ".kar",
                 ".sf2", ".sf3"}
ALLOWED_LYRICS = {".json", ".lrc"}


def destination_root(selected):
    if not isinstance(selected, str) or not selected.strip():
        raise ValueError("กรุณาเลือกตำแหน่งเก็บคลัง XStageSong สำหรับ Karaoke PC")
    chosen = Path(selected.strip()).expanduser().resolve()
    if chosen.name.casefold() == "xstagesong":
        return chosen
    if chosen.name.casefold() == "songs":
        return chosen / "XStageSong"
    if ((chosen / "App" / "XStageKaraoke.exe").is_file()
            or (chosen / "XStageKaraoke.exe").is_file()):
        return chosen / "Songs" / "XStageSong"
    return chosen / "XStageSong"


def _sqlite_bridge():
    path = Path(__file__).resolve().with_name("pc_sqlite_bridge.py")
    if not path.is_file():
        raise RuntimeError("ไม่พบโมดูล SQLite ของ Karaoke PC")
    spec = importlib.util.spec_from_file_location("xstage_pc_sqlite_bridge", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("ไม่สามารถอ่านโมดูล SQLite ของ Karaoke PC")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _safe_rel(value, prefix):
    if not isinstance(value, str) or not value.startswith(prefix + "/"):
        raise ValueError("ตำแหน่งไฟล์เพลงไม่อยู่ในคลังที่รองรับ")
    parts = value.split("/")
    if (len(parts) < 3 or any(x in ("", ".", "..") for x in parts)
            or any("\\" in part or ":" in part or "\0" in part for part in parts)):
        raise ValueError("ตำแหน่งไฟล์อาจไม่ปลอดภัย")
    return Path(*parts)


def _hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _files(source):
    for folder, suffixes, upper in (("audio", ALLOWED_MEDIA, "AUDIO"),
                                    ("lyrics", ALLOWED_LYRICS, "LYRICS")):
        base = source / folder
        if not base.is_dir() or base.is_symlink():
            raise ValueError("คลังเพลงต้องมีโฟลเดอร์ audio และ lyrics ที่ใช้งานได้")
        for root, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = sorted(n for n in dirs if not (Path(root) / n).is_symlink()
                             and not n.startswith("."))
            for name in sorted(files):
                file = Path(root) / name
                if (file.is_symlink() or not file.is_file() or
                        name.startswith(".") or file.suffix.casefold() not in suffixes):
                    continue
                # Never recycle generated Karaoke PC/Drive catalogs as lyrics
                # when the authoring and playback XStageSong roots are shared.
                if folder == "lyrics" and (name.casefold() == "current.json"
                        or name.casefold().startswith(("catalog-", "database-"))):
                    continue
                rel = file.relative_to(base)
                if any(part in ("", ".", "..") for part in rel.parts):
                    raise ValueError("พบพาธเพลงไม่ปลอดภัย")
                yield file, Path(upper) / rel


def _source(source, export):
    pointer, buckets = export._read_current(source)
    if not pointer:
        raise ValueError("ไม่พบ XStageSong/current.json กรุณาสร้างเพลงก่อนส่งออกไป Karaoke PC")
    records = []
    for group in buckets.values():
        records.extend(group.get("songs") or [])
    if len(records) != pointer.get("songCount"):
        raise ValueError("Catalog จาก Song Studio มีจำนวนเพลงไม่ตรง หยุดเพื่อป้องกันฐานเสีย")
    for row in records:
        if not export.record_is_complete(source, row):
            raise ValueError("เพลงหรือ Lyrics JSON ไม่ครบ: " + str(row.get("code", ""))[:80])
    return records


def _existing(root):
    folder = root / "LYRICS"
    pointer = folder / "current.json"
    if not pointer.is_file():
        if folder.is_dir() and any(folder.glob("catalog-*")):
            raise ValueError("พบฐานเพลงปลายทางแต่ไม่มี current.json โปรดตรวจคลังก่อน")
        return {}
    data = json.loads(pointer.read_text(encoding="utf-8-sig"))
    if data.get("format") != FORMAT or data.get("schemaVersion") != SCHEMA:
        raise ValueError("พบ current.json รูปแบบอื่น หยุดเพื่อไม่ให้ทับคลังเดิม")
    result = {}
    for info in data.get("catalogFiles") or []:
        filename = str(info.get("path") or "")
        if (not filename.startswith("catalog-pc-") or not filename.endswith(".json")
                or "/" in filename or "\\" in filename):
            raise ValueError("พาธ Catalog ปลายทางผิดปกติ")
        catalog = json.loads((folder / filename).read_text(encoding="utf-8-sig"))
        if catalog.get("format") != CATALOG or catalog.get("schemaVersion") != SCHEMA:
            raise ValueError("Catalog Karaoke PC ไม่ถูกต้อง")
        for row in catalog.get("songs") or []:
            key = row["webSongId"]
            if key in result:
                raise ValueError("Catalog Karaoke PC มีรหัสเพลงซ้ำ")
            result[key] = row
    return result


def _pc_row(row, replacements=None):
    replacements = replacements or {}
    item = dict(row)
    for key, prefix, replacement in (("audio", "audio", "AUDIO"),
                                     ("lyrics", "lyrics", "LYRICS"),
                                     ("vocals", "audio", "AUDIO")):
        obj = row.get(key)
        if obj:
            path = _safe_rel(obj["path"], prefix)
            original = Path(replacement, *path.parts[1:]).as_posix()
            item[key] = {**obj, "path": replacements.get(original, original)}
    return item


def _plan_files(source, destination):
    """Immutable versioned lyrics preserve the previous published catalog.

    Song Studio may correct JSON timestamps after the first export.
    A changed Lyrics JSON/LRC goes to a new content-addressed path, while
    an existing media path with conflicting bytes is rejected for review.
    """
    files = []
    replacements = {}
    copied_bytes = 0
    new_count = versioned = 0
    for src, rel in _files(source):
        original = destination / rel
        target = original
        if original.is_symlink():
            raise ValueError("พบ symbolic link ในคลัง Karaoke PC: " + str(original))
        if original.is_file() and _hash(original) != _hash(src):
            if rel.parts[0] != "LYRICS":
                raise FileExistsError(
                    "ไฟล์เสียงชื่อเดิมแต่เนื้อหาเปลี่ยน กรุณาตรวจเพลงก่อนนำเข้า: " + str(original))
            variant = rel.with_name(rel.stem + "-rev-" + _hash(src)[:16] + rel.suffix)
            target = destination / variant
            replacements[rel.as_posix()] = variant.as_posix()
            versioned += 1
            if target.is_symlink():
                raise ValueError("พบ symbolic link ในไฟล์ Lyrics ฉบับปรับปรุง")
            if target.is_file() and _hash(target) != _hash(src):
                raise FileExistsError("ไฟล์ Lyrics ฉบับแก้ไขมีชื่อชนกัน: " + str(target))
        if not target.is_file():
            new_count += 1
            copied_bytes += src.stat().st_size
        files.append((src, target))
    return files, replacements, new_count, copied_bytes, versioned


def inspect(source_root, selected_destination, export):
    source = Path(source_root).expanduser().resolve()
    target = destination_root(selected_destination)
    if target != source and (target.is_relative_to(source) or source.is_relative_to(target)):
        raise ValueError("โฟลเดอร์ปลายทางทับซ้อนพื้นที่สร้างเพลง · เลือก XStageSong เดียวกันหรือแยกคลัง")
    records = _source(source, export)
    existing = _existing(target)
    files, _replacements, missing, bytes_to_copy, versioned = _plan_files(source, target)
    return {"source": str(source), "destination": str(target),
            "songs": len(records), "existingSongs": len(existing),
            "files": len(files), "newFiles": missing,
            "updatedLyrics": versioned,
            "bytesToCopy": bytes_to_copy,
            "database": str(_sqlite_bridge().database_location(target)[0]),
            "databaseAction": "update" if _sqlite_bridge().database_location(target)[0].is_file() else "create",
            "databaseInstalled": _sqlite_bridge().database_location(target)[1]}


def _atomic_copy(source_file, target_file):
    target_file.parent.mkdir(parents=True, exist_ok=True)
    if target_file.is_symlink():
        raise ValueError("พบลิงก์ปลายทางที่ไม่อนุญาต: " + str(target_file))
    if target_file.is_file():
        if (target_file.stat().st_size == source_file.stat().st_size
                and _hash(target_file) == _hash(source_file)):
            return False
        raise FileExistsError("พบไฟล์ชื่อเดียวกันแต่เนื้อหาต่างกัน: " + str(target_file))
    temp = target_file.with_name("." + target_file.name + "." + secrets.token_hex(8) + ".partial")
    try:
        with source_file.open("rb") as original, temp.open("xb") as output:
            shutil.copyfileobj(original, output, 1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        if (_hash(temp) != _hash(source_file)):
            raise OSError("ตรวจ SHA-256 ของไฟล์ที่คัดลอกไม่ผ่าน: " + source_file.name)
        # Windows FAT/exFAT removable drives do not support hard links.
        # Windows rename is no-replace; POSIX link is no-replace. Both commit
        # only after the temporary file's SHA-256 has been verified.
        if os.name == "nt":
            os.rename(temp, target_file)
        else:
            os.link(temp, target_file)
        return True
    finally:
        temp.unlink(missing_ok=True)


def _atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        with tmp.open("x", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False, separators=(",", ":"))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def publish(source_root, selected_destination, export, *, cancelled=None, progress=None):
    report = inspect(source_root, selected_destination, export)
    source = Path(report["source"])
    dest = Path(report["destination"])
    records = _source(source, export)
    previous = _existing(dest)
    files, replacements, _count, _bytes, _versions = _plan_files(source, dest)
    planned = [_pc_row(row, replacements) for row in records]
    combined = dict(previous)
    for row in planned:
        # Keep the previous immutable catalog and source file unchanged;
        # the new pointer selects edited metadata/timing only after copying.
        combined[row["webSongId"]] = row
    if report["bytesToCopy"] > 0:
        dest.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(dest).free < report["bytesToCopy"] + 32 * 1024 * 1024:
            raise ValueError("พื้นที่ปลายทางไม่เพียงพอสำหรับคัดลอกไฟล์เพลง")
    # Existing files with conflicting content must never be replaced.
    copied = reused = 0
    for i, (src, target_file) in enumerate(files, 1):
        if cancelled and cancelled.is_set():
            raise RuntimeError("ยกเลิกการคัดลอกแล้ว · ฐานข้อมูลชุดเก่ายังใช้งานได้")
        if _atomic_copy(src, target_file):
            copied += 1
        else:
            reused += 1
        if progress and (i % 20 == 0 or i == len(files)):
            progress(i, len(files), src.name)
    if cancelled and cancelled.is_set():
        raise RuntimeError("ยกเลิกก่อนเผยแพร่ฐานข้อมูล · ฐานเดิมไม่เปลี่ยน")
    folder = dest / "LYRICS"
    generation = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + secrets.token_hex(4)
    refs = []
    for bucket in sorted({r.get("bucket", "_") for r in combined.values()}):
        songs = sorted((r for r in combined.values() if r.get("bucket", "_") == bucket),
                       key=lambda r: r["webSongId"])
        filename = f"catalog-pc-{bucket}-{generation}.json"
        _atomic_json(folder / filename, {"schemaVersion": SCHEMA, "format": CATALOG,
                                          "bucket": bucket, "songs": songs})
        refs.append({"bucket": bucket, "path": filename, "songCount": len(songs)})
    _atomic_json(folder / "current.json",
                 {"schemaVersion": SCHEMA, "format": FORMAT, "layoutVersion": 4,
                  "songCount": len(combined), "generation": generation,
                  "catalogFiles": refs,
                  "publishedAt": datetime.now(timezone.utc).isoformat()})
    # Reuse the exact SongLibrary SQLite schema and upsert semantics from
    # Karaoke PC; preserve existing user edits, favorites and other rows.
    db_result = _sqlite_bridge().sync(dest, list(combined.values()))
    return {**report, **db_result, "copied": copied, "reused": reused,
            "songCount": len(combined),
            "message": f"นำเข้า Karaoke PC สำเร็จ {len(combined):,} เพลง · คัดลอกใหม่ {copied:,} ไฟล์ · ใช้เดิม {reused:,} ไฟล์ · ฐาน SQLite {db_result['databaseAction']} · {db_result['database']}"}
