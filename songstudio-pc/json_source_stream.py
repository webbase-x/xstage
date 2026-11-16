"""Streaming source discovery for MIDI to Lyrics JSON.

Find a media file, pair only its existing source companions by exact basename,
and yield it for conversion immediately. This is not the library-wide
upload/preflight scanner: no output JSON or catalog is required as an input.
"""
from __future__ import annotations

import os
from pathlib import Path

MIDI = {".mid", ".midi", ".kar"}
AUDIO = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".oga", ".wma"}
VIDEO = {".mp4", ".webm", ".avi", ".mkv", ".mov", ".mpg", ".mpeg",
         ".vob", ".dat", ".wmv", ".flv"}
MEDIA = MIDI | AUDIO | VIDEO
MAX_FILES = 1_000_000
# Source NCN catalogs may place MIDI, LYR and CUR under sibling role folders.
SOURCE_ROLES = {"song", "songs", "audio", "lyrics", "lyr", "cursor", "cur"}
ALIASES = {
    ".lyr": ("LYR", "Lyrics", "LYRICS", "lyr", "lyrics"),
    ".cur": ("CUR", "Cursor", "CURSOR", "cur", "cursor"),
    ".json": ("LYRICS", "Lyrics", "lyrics", "JSON", "json"),
    ".lrc": ("LYRICS", "Lyrics", "lyrics", "LRC", "lrc"),
}


def _companion(root: Path, media: Path, extension: str) -> Path | None:
    """Find an exact-code source file, never fabricate a Lyrics JSON."""
    filename = media.stem + extension
    candidate = media.parent / filename
    if candidate.is_file() and not candidate.is_symlink():
        return candidate
    relative = media.relative_to(root)
    folders = relative.parts[:-1]
    # The role is removed (rather than the bucket). E.g.
    # MIDI/NCN/SONG/A/00001.mid -> MIDI/NCN/LYR/A/00001.lyr
    for i in range(len(folders) - 1, -1, -1):
        if folders[i].casefold() not in SOURCE_ROLES:
            continue
        for role in ALIASES[extension]:
            if folders[i].casefold() == role.casefold():
                continue
            candidate = root.joinpath(*folders[:i], role, *folders[i + 1:], filename)
            if candidate.is_file() and not candidate.is_symlink():
                return candidate
        break
    return None


def _source_row(root: Path, media: Path):
    """Only check companions for the CURRENT song; deep validation is at conversion."""
    suffix = media.suffix.lower()
    files = [(media, None)]
    if suffix in MIDI:
        lyr = _companion(root, media, ".lyr")
        cur = _companion(root, media, ".cur")
        if lyr or cur:
            if not (lyr and cur):
                return None, "NCN ขาดไฟล์ LYR หรือ CUR ที่รหัสตรงกับ MIDI"
            files.extend(((lyr, None), (cur, None)))
            kind = "NCN"
        else:
            lrc = _companion(root, media, ".lrc")
            if lrc:
                files.append((lrc, None))
                kind = "MIDI"
            else:
                existing_json = _companion(root, media, ".json")
                if existing_json:
                    # Compatibility with preexisting MIDI + JSON sources.
                    # JSON is optional, not a prerequisite for creating it.
                    files.append((existing_json, None))
                    kind = "MIDI"
                else:
                    # A KAR or SMF may contain text/cues inside its MIDI events.
                    # Read and validate those events while converting this song.
                    kind = "KAR"
    else:
        lyric = _companion(root, media, ".lrc")
        if lyric is None:
            lyric = _companion(root, media, ".json")
        if lyric is None:
            return None, "เสียง/วิดีโอต้นทางไม่มีเนื้อร้องพร้อมเวลา (ใช้เมนู Lyrics AI)"
        files.append((lyric, None))
        kind = suffix.lstrip(".").upper()
    return {"name": media.stem, "kind": kind, "files": files}, None


def stream(source_folder, *, ncn=None, progress=None, cancelled=None):
    """Return a bounded-memory iterator plus truthful mutable scan statistics.

    Yield the first valid source song as soon as it is encountered. Directory
    enumeration and conversion interleave; no pass over every song is required.
    A cancelled or unreadable scan never silently reports full completion.
    """
    root = Path(source_folder).expanduser()
    if not root.is_dir() or root.is_symlink():
        raise ValueError("กรุณาเลือกโฟลเดอร์ต้นทางที่มีอยู่จริง")
    root = root.resolve()
    report = {"complete": None, "incomplete": [], "unsupported": [],
              "fileCount": 0, "folderCount": 0, "total": 0,
              "incompleteCount": 0, "unsupportedCount": 0}

    def cancelled_now():
        return cancelled is not None and cancelled.is_set()

    def iterate():
        folders = [root]
        examined = 0
        while folders:
            if cancelled_now():
                raise RuntimeError("ผู้ใช้ยกเลิกการค้นหาไฟล์ต้นทาง")
            directory = folders.pop()
            children = []
            try:
                listing = os.scandir(directory)
            except OSError as exc:
                raise OSError("ไม่สามารถอ่านโฟลเดอร์ต้นทาง: " + str(directory)) from exc
            with listing:
                report["folderCount"] += 1
                for entry in listing:
                    if cancelled_now():
                        raise RuntimeError("ผู้ใช้ยกเลิกการค้นหาไฟล์ต้นทาง")
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            children.append(Path(entry.path))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                    except OSError as exc:
                        raise OSError("อ่านข้อมูลไฟล์ต้นทางไม่ได้: " + entry.path) from exc
                    examined += 1
                    if examined > MAX_FILES:
                        raise ValueError("จำนวนไฟล์ต้นทางเกินขีดจำกัด 1,000,000 ไฟล์")
                    report["fileCount"] = examined
                    if progress is not None and examined % 256 == 0:
                        progress("discover", examined, None)
                    media = Path(entry.path)
                    if media.suffix.lower() not in MEDIA:
                        continue
                    row, reason = _source_row(root, media)
                    if reason:
                        report["incompleteCount"] += 1
                        if len(report["incomplete"]) < 50:
                            report["incomplete"].append({
                                "name": media.name, "reason": reason})
                        continue
                    report["total"] += 1
                    if progress is not None and report["total"] % 32 == 0:
                        progress("validate", report["total"], None)
                    yield row
            # Only directory paths are queued, never all songs in the library.
            folders.extend(reversed(sorted(children, key=lambda p: p.name.casefold())))
        if progress is not None:
            progress("discover", examined, None)
            progress("validate", report["total"], report["total"])

    report["complete"] = iterate()
    return report
