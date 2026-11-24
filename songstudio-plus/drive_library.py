"""Import a user-owned Google Drive for desktop XStageKaraoke library.

This never contacts a retired Drive folder, guesses a cloud folder ID, creates
folders in Drive, or opens the Karaoke Online SQLite database. Drive for desktop
provides authenticated file access and downloads cloud-only placeholders on read.
Only SONGS is copied into a *local* managed mirror before SQLite indexing.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sys
from pathlib import Path

import plus_core as core

ROOT_NAME = "XStageKaraoke"
REQUIRED = ("SONGS", "DB", "SOUNDFONT")
# Preserve the current Karaoke Online directory layout, including packaged X
# files and sidecars. Only source media are subsequently indexed into Studio.
SONG_EXT = core.MEDIA_EXT | {
    ".lyr", ".cur", ".lrc", ".json", ".xmid", ".xsk", ".xmp3",
    ".xm4a", ".xmp4", ".xflac", ".xwav", ".xwebm", ".xml",
}
CHUNK = 1024 * 1024


def _candidates():
    home = Path.home()
    # The actual Drive root may live on a virtual drive or in mirrored
    # folders; detection is bounded to known locations, never a disk crawl.
    for parent in (home / "Google Drive", home / "My Drive",
                   home / "ไดรฟ์ของฉัน", home / "GoogleDrive"):
        yield parent / ROOT_NAME
        yield parent / "My Drive" / ROOT_NAME
        yield parent / "ไดรฟ์ของฉัน" / ROOT_NAME
    if sys.platform == "win32":
        for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
            disk = Path(letter + ":/")
            yield disk / ROOT_NAME
            yield disk / "My Drive" / ROOT_NAME
            yield disk / "ไดรฟ์ของฉัน" / ROOT_NAME


def resolve_root(value=""):
    if not isinstance(value, str):
        raise ValueError("กรุณาเลือกโฟลเดอร์ XStageKaraoke")
    if value.strip():
        candidates = [Path(value.strip().strip('"\u0027')).expanduser()]
    else:
        candidates = list(_candidates())
    root = None
    for candidate in candidates:
        if candidate.name.upper() in REQUIRED:
            candidate = candidate.parent
        try:
            if candidate.is_dir():
                root = candidate.resolve(strict=True)
                break
        except (OSError, RuntimeError):
            continue
    if root is None:
        raise ValueError(
            "ไม่พบ XStageKaraoke ใน Google Drive สำหรับเดสก์ท็อป "
            "กรุณาเลือกโฟลเดอร์ XStageKaraoke ที่ซิงก์อยู่บนเครื่อง")
    if not all((root / part).is_dir() for part in REQUIRED):
        raise ValueError("คลังที่เลือกต้องมี SONGS, DB และ SOUNDFONT")
    return root


def describe(value=""):
    root = resolve_root(value)
    return {"root": str(root), "songs": str(root / "SONGS"),
            "layout": list(REQUIRED), "mode": "google-drive-desktop",
            "sqlite_policy": "ไม่คัดลอกหรือเขียนฐานข้อมูล DB ของ Karaoke Online",
            "download_policy": "ดาวน์โหลดเฉพาะเพลงจาก SONGS ลงในเครื่อง"}


def _hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            digest.update(block)
    return digest.digest()


def iter_song_files(folder):
    for base, dirs, names in os.walk(folder, followlinks=False):
        dirs[:] = sorted(name for name in dirs
                         if not (Path(base) / name).is_symlink())
        for name in sorted(names):
            source = Path(base) / name
            if (source.suffix.lower() in SONG_EXT and
                    source.is_file() and not source.is_symlink()):
                yield source


def download_and_import(workspace, root, progress=None, cancel=None,
                        destination=None):
    root = resolve_root(str(root))
    workspace = Path(workspace).expanduser().resolve()
    target = (Path(destination).expanduser().resolve() if destination else
              (Path.home() / "Downloads" / "XStageSongStudioPro" /
               ROOT_NAME).resolve())
    # Do not recurse into a Drive mirror or expose Studio's own workspace.
    if any(a == b or a in b.parents or b in a.parents for a, b in (
            (target, root), (target, workspace), (root, workspace))):
        raise ValueError("ที่เก็บไฟล์ดาวน์โหลดต้องแยกจาก Drive และคลัง SQLite")
    source_folder = root / "SONGS"
    local_folder = target / "SONGS"
    local_folder.mkdir(parents=True, exist_ok=True)
    counts = {"phase": "download", "files_seen": 0, "downloaded": 0,
              "unchanged": 0, "downloaded_bytes": 0}
    for source in iter_song_files(source_folder):
        if cancel is not None and cancel.is_set():
            return {**counts, "cancelled": True, "download_path": str(target)}
        relative = source.relative_to(source_folder)
        output = local_folder / relative
        if any(part in (".", "..") for part in relative.parts):
            raise ValueError("เส้นทางไฟล์ใน SONGS ไม่ถูกต้อง")
        if output.is_symlink() or any(part.is_symlink()
                                      for part in output.parents if part != target):
            raise ValueError("พบ symbolic link ในโฟลเดอร์ดาวน์โหลด")
        size = source.stat().st_size
        counts["files_seen"] += 1
        if output.is_file() and output.stat().st_size == size:
            if _hash(source) == _hash(output):
                counts["unchanged"] += 1
                if progress and counts["files_seen"] % 25 == 0:
                    progress(dict(counts), "ข้ามไฟล์ที่ตรงกัน " + source.name)
                continue
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(output.name + "." + secrets.token_hex(8) + ".part")
        digest = hashlib.sha256()
        try:
            with source.open("rb") as incoming, temporary.open("xb") as outgoing:
                while True:
                    if cancel is not None and cancel.is_set():
                        return {**counts, "cancelled": True, "download_path": str(target)}
                    chunk = incoming.read(CHUNK)
                    if not chunk:
                        break
                    digest.update(chunk)
                    outgoing.write(chunk)
                    counts["downloaded_bytes"] += len(chunk)
            if temporary.stat().st_size != size or _hash(temporary) != digest.digest():
                raise OSError("ตรวจสอบ SHA-256 หลังดาวน์โหลดไม่ผ่าน: " + source.name)
            os.replace(temporary, output)
            counts["downloaded"] += 1
            if progress:
                progress(dict(counts), "ดาวน์โหลด " + source.name)
        finally:
            temporary.unlink(missing_ok=True)
    if cancel is not None and cancel.is_set():
        return {**counts, "cancelled": True, "download_path": str(target)}
    if progress:
        progress({**counts, "phase": "index"}, "ดาวน์โหลดเสร็จ · กำลังนำเข้า SQLite")
    def report(summary, message):
        if progress:
            progress({**counts, **summary, "phase": "index"}, message)
    result = core.import_folder(workspace, str(local_folder), report, cancel)
    return {**counts, "phase": "completed", "import": result,
            "download_path": str(target)}
