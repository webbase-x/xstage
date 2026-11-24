"""Portable user-named Google Drive library layout.

Folder name is presentation only. A Google Drive Folder ID (copied from the
browser URL) is stored in PC settings and never inferred from the local path.
SONGS/DB/SOUNDFONT/... are the fixed relative contract across apps.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_NAME = "XStageKaraoke"
FOLDERS = ("SONGS", "DB", "SOUNDFONT", "FX", "BACKUP", "CACHE", "LOGS")
RESERVED = frozenset(FOLDERS)
RETIRED_IDS = frozenset(("1RYekUHCC3qs661cUrbxkNauUz_SuqZvy",))
ID = re.compile(r"^[A-Za-z0-9_-]{5,256}$")


def drive_folder_id(value):
    """Extract the exact Drive Folder ID or reject retired/malformed links."""
    raw = str(value or "").strip()
    if "/folders/" in raw:
        match = re.search(r"/folders/([A-Za-z0-9_-]{5,256})(?:[/?#]|$)", raw)
        if not match or not urlparse(raw).hostname in (
            "drive.google.com", "www.drive.google.com"):
            raise ValueError("ลิงก์ Google Drive Folder ID ไม่ถูกต้อง")
        raw = match.group(1)
    if not ID.fullmatch(raw) or raw in RETIRED_IDS:
        raise ValueError("Folder ID ไม่ถูกต้องหรือเป็นคลังที่ยกเลิก")
    return raw


def inspect(root):
    path = Path(root).expanduser()
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise ValueError("ปลายทางคลังเพลงต้องเป็นโฟลเดอร์ปกติ ไม่ใช่ symbolic link")
    if path.name in ("", ".", "..") or path.name.upper() in RESERVED:
        raise ValueError("ต้องเลือกโฟลเดอร์หลักของคลังเพลง ไม่ใช่โฟลเดอร์ย่อยระบบ")
    if path.parent.is_symlink():
        raise ValueError("ไม่อนุญาตโฟลเดอร์แม่ที่เป็น symbolic link")
    if path.exists():
        actual = path.resolve(strict=True)
        if actual != path.absolute() and path.is_symlink():
            raise ValueError("ไม่อนุญาต symbolic link ไปนอกคลัง")
    for part in FOLDERS:
        child = path / part
        if child.is_symlink() or (child.exists() and not child.is_dir()):
            raise ValueError("พบรายการชื่อ "+part+" แต่ไม่ใช่โฟลเดอร์ที่ปลอดภัย")
    existing = tuple(name for name in FOLDERS if (path / name).is_dir())
    missing = tuple(name for name in FOLDERS if name not in existing)
    return {"root": str(path.absolute()), "name": path.name,
            "exists": path.is_dir(), "existing": existing, "missing": missing}


def setup(root):
    """Only call after an explicit user confirmation; never deletes or copies."""
    result = inspect(root)
    target = Path(result["root"])
    target.mkdir(parents=True, exist_ok=True)
    for part in result["missing"]:
        child = target / part
        child.mkdir(exist_ok=True)
        if child.is_symlink() or not child.is_dir():
            raise ValueError("ไม่สามารถสร้างโฟลเดอร์ที่ปลอดภัย: "+part)
    return inspect(target)
