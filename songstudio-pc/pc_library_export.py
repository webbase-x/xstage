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
# Retain the old AUDIO/<bucket> paths for audio, but publish native MIDI and
# video to distinct folders. A catalog row always carries the actual path.
VIDEO_EXT = {".mp4", ".webm", ".avi", ".mkv", ".mov", ".mpg", ".mpeg",
             ".vob", ".dat", ".wmv", ".flv"}
MIDI_EXT = {".mid", ".midi", ".kar", ".xsk"}

def media_category(name):
    extension = Path(name).suffix.casefold()
    if extension == ".xsk":
        return Path("MIDI") / "XSK"
    if extension == ".kar":
        return Path("MIDI") / "KAR"
    if extension in {".mid", ".midi"}:
        return Path("MIDI") / "MID"
    if extension in VIDEO_EXT:
        return Path("VIDEO")
    if extension in {".sf2", ".sf3"}:
        return Path("SOUNDFONT")
    return Path("AUDIO")

def media_relative(path):
    """Convert a trusted Studio media path into a typed destination path."""
    source = _safe_rel(path, "audio")
    return media_category(source.name).joinpath(*source.parts[1:])



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
    """Enumerate legacy authoring files OR direct categorized Pro exports.

    Do not include catalogs/temporary files, and never recurse into links.
    The media category is already final for uppercase XStageSong folders.
    """
    local = (("audio", ALLOWED_MEDIA | {".xsk"} | VIDEO_EXT),
             ("lyrics", ALLOWED_LYRICS))
    typed = (("AUDIO", ALLOWED_MEDIA | {".json", ".xsk"} | VIDEO_EXT),
             ("VIDEO", VIDEO_EXT | {".json"}),
             ("MIDI", {".mid", ".midi", ".kar", ".xsk", ".json"}),
             ("LYRICS", ALLOWED_LYRICS),
             ("SOUNDFONT", {".sf2", ".sf3"}))
    if not (any((source / name).is_dir() for name in ("audio", "AUDIO", "VIDEO", "MIDI"))
            and any((source / name).is_dir() for name in ("lyrics", "LYRICS", "AUDIO", "VIDEO", "MIDI"))):
        raise ValueError("คลังเพลงต้องมีโฟลเดอร์เพลงและ Lyrics JSON ที่ใช้งานได้")
    # Windows resolves AUDIO as audio on case-insensitive filesystems.
    # Use the actual on-disk directory spelling to avoid visiting each tree
    # twice and copying the same song twice in a single export.
    present = {entry.name for entry in source.iterdir()
               if entry.is_dir() and not entry.is_symlink()}
    for folder, suffixes in (*local, *typed):
        if folder not in present:
            continue
        base = source / folder
        if not base.is_dir() or base.is_symlink():
            continue
        for root, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = sorted(n for n in dirs if not (Path(root) / n).is_symlink()
                             and not n.startswith("."))
            for name in sorted(files):
                file = Path(root) / name
                if (file.is_symlink() or not file.is_file() or
                        name.startswith(".") or file.suffix.casefold() not in suffixes):
                    continue
                rel = file.relative_to(base)
                if (folder.lower() == "lyrics" or
                    (folder in ("AUDIO", "VIDEO", "MIDI") and
                     "LYRICS" in rel.parts)) and (
                        name.casefold() == "current.json" or
                        name.casefold().startswith(("catalog-", "database-")) or
                        "-pc-snapshot-" in name.casefold() or
                        "-rev-" in name.casefold()):
                    continue
                rel = file.relative_to(base)
                if any(part in ("", ".", "..") for part in rel.parts):
                    raise ValueError("พบพาธเพลงไม่ปลอดภัย")
                if folder == "audio":
                    output = media_category(file.name) / rel
                elif folder == "lyrics":
                    output = Path("LYRICS") / rel
                else:
                    output = Path(folder) / rel
                yield file, output


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
    for key in ("audio", "lyrics", "vocals"):
        obj = row.get(key)
        if not obj:
            continue
        incoming = obj.get("path")
        if not isinstance(incoming, str):
            raise ValueError("พาธรายการเพลงไม่ถูกต้อง")
        root_name = incoming.split("/", 1)[0]
        if root_name in ("AUDIO", "VIDEO", "MIDI", "SOUNDFONT", "LYRICS"):
            path = _safe_rel(incoming, root_name)
            if key == "lyrics" and root_name not in ("LYRICS",):
                if "/LYRICS/" not in incoming or "/SONG/" in incoming:
                    raise ValueError("ไฟล์เนื้อร้องต้องอยู่ใน LYRICS ของประเภทเพลง")
            original = path.as_posix()
        elif key == "lyrics":
            path = _safe_rel(incoming, "lyrics")
            original = Path("LYRICS", *path.parts[1:]).as_posix()
        else:
            path = _safe_rel(incoming, "audio")
            original = media_relative(incoming).as_posix()
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
    shared_root = source.resolve() == destination.resolve()
    for src, rel in _files(source):
        original = destination / rel
        target = original
        # On case-insensitive Windows, source/lyrics and Karaoke/LYRICS can
        # be the SAME directory. Always publish a separate immutable snapshot
        # so subsequent text edits never change a previous karaoke catalog.
        if shared_root and "LYRICS" in rel.parts:
            digest = _hash(src)[:16]
            variant = rel.with_name(rel.stem + "-pc-snapshot-" + digest + rel.suffix)
            target = destination / variant
            replacements[rel.as_posix()] = variant.as_posix()
            if not target.is_file():
                versioned += 1
            if target.is_symlink():
                raise ValueError("พบ symbolic link ใน Lyrics snapshot")
            if target.is_file() and _hash(target) != _hash(src):
                raise FileExistsError("Lyrics snapshot มีชื่อชนกันแต่เนื้อหาไม่ตรง")
        if original.is_symlink():
            raise ValueError("พบ symbolic link ในคลัง Karaoke PC: " + str(original))
        if not shared_root and original.is_file() and _hash(original) != _hash(src):
            if "LYRICS" not in rel.parts:
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
    db_path, installed = _sqlite_bridge().database_location(target)
    return {"source": str(source), "destination": str(target),
            "songs": len(records), "existingSongs": len(existing),
            "files": len(files), "newFiles": missing,
            "updatedLyrics": versioned,
            "bytesToCopy": bytes_to_copy,
            "database": str(db_path),
            "portableDatabase": str(target / "DB" / "songs-portable.json"),
            "webApkRequiresDriveUpload": True,
            "databaseAction": "update" if db_path.is_file() else "create",
            "databaseInstalled": installed}


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


PORTABLE_FORMAT = "xstage-portable-song-db"
PORTABLE_SCHEMA = 1


def portable_catalog(destination, rows, generation):
    """Offline interchange database for PC and authenticated Drive publishers.

    Paths are relative to XStageSong; no absolute Windows paths, secrets or
    invented Drive file IDs. Web/APK require Drive publication to resolve IDs.
    """
    root = Path(destination)
    songs = []
    seen = set()
    for row in sorted(rows, key=lambda item: str(item.get("webSongId", ""))):
        ident = str(row.get("webSongId") or "")
        if not ident or ident in seen:
            raise ValueError("รายการฐานเพลงแบบพกพามีรหัสซ้ำหรือว่าง")
        seen.add(ident)
        media = (row.get("audio") or {}).get("path")
        lyrics = (row.get("lyrics") or {}).get("path")
        if not isinstance(media, str) or media.split("/", 1)[0] not in ("AUDIO", "VIDEO", "MIDI", "SOUNDFONT"):
            raise ValueError("พาธสื่อแบบพกพาไม่ได้อยู่ในหมวดที่กำหนด")
        audio_path = _safe_rel(media, media.split("/", 1)[0])
        lyric_path = None
        if lyrics is not None:
            lyric_root = lyrics.split("/", 1)[0] if isinstance(lyrics, str) else ""
            if lyric_root not in ("LYRICS", "AUDIO", "VIDEO", "MIDI"):
                raise ValueError("พาธเนื้อร้องในฐานพกพาไม่ถูกต้อง")
            if lyric_root != "LYRICS" and "/LYRICS/" not in lyrics:
                raise ValueError("Lyrics JSON ต้องอยู่ในหมวดประเภทเพลง")
            lyric_path = _safe_rel(lyrics, lyric_root)
        elif audio_path.suffix.casefold() not in (".kar", ".xsk"):
            raise ValueError("ไฟล์เพลงชนิดนี้ต้องมี Lyrics JSON ที่ครบคู่")
        # Export the same immutable paths validated by the native PC bridge.
        for rel in (audio_path, lyric_path):
            if rel is None:
                continue
            file = root / rel
            if (not file.is_file() or file.is_symlink()
                    or not file.resolve().is_relative_to(root.resolve())):
                raise ValueError("ฐานพกพามีไฟล์ต้นทางไม่ครบ: " + str(rel))
        songs.append({
            "webSongId": ident, "code": str(row.get("code") or ""),
            "title": str(row.get("title") or ""),
            "artist": str(row.get("artist") or ""),
            "sourceFormat": row.get("sourceFormat"),
            "audio": {"path": audio_path.as_posix()},
            "lyrics": {"path": lyric_path.as_posix()} if lyric_path else None,
        })
    return {
        "schemaVersion": PORTABLE_SCHEMA, "format": PORTABLE_FORMAT,
        "layoutVersion": 4, "generation": generation,
        "songCount": len(songs), "songs": songs,
        "mediaRoot": "XStageSong", "lyricsRoot": "LYRICS",
        "mediaFolders": ["AUDIO", "VIDEO", "MIDI", "SOUNDFONT"],
        "platforms": ["pc", "web", "apk"],
        "webApk": {"requiresGoogleDrivePublication": True,
                   "catalogUsesDriveFileIds": True},
    }


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
    # Publish a portable database alongside Karaoke PC's native SQLite. Both
    # are derived from the same already-verified immutable catalog snapshot.
    portable = portable_catalog(dest, combined.values(), generation)
    portable_path = dest / "DB" / "songs-portable.json"
    _atomic_json(portable_path, portable)
    return {**report, **db_result, "copied": copied, "reused": reused,
            "songCount": len(combined),
            "portableDatabase": str(portable_path),
            "portableSchema": PORTABLE_FORMAT,
            "webApkRequiresDriveUpload": True,
            "message": (f"ส่งออก {len(combined):,} เพลงพร้อมฐานข้อมูล · "
                        f"คัดลอกใหม่ {copied:,} ไฟล์ · ใช้เดิม {reused:,} ไฟล์ · "
                        f"SQLite สำหรับ PC: {db_result['database']} · "
                        f"JSON พกพา: {portable_path} · "
                        "Web/APK ต้องนำเข้าคลัง Google Drive เพื่อสร้าง File ID")}
