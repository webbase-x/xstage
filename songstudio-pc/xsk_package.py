"""X-Stage Karaoke portable XSK2 (plain ZIP) package.

New XSK files are readable by PC, Web and APK without any decryption key.
Old XSK1 AES-GCM files remain read-only compatible when the owner has a key.
Exactly one MIDI/KAR source and one timed JSON are stored; every MIDI is
SHA-256 verified, and original source files are never modified.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import struct
import zipfile
from pathlib import Path

MAGIC = b"XSK2"
LEGACY_MAGIC = b"XSK1"
MAX_SOURCE = 128 * 1024 * 1024
MAX_DOC = 8 * 1024 * 1024
MAX_ENCRYPTED = MAX_SOURCE + MAX_DOC + 16 * 1024 * 1024
CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def destination(workspace, code):
    if not isinstance(code, str) or not CODE_RE.fullmatch(code):
        raise ValueError("รหัสเพลงไม่ปลอดภัยสำหรับตั้งชื่อไฟล์")
    root = Path(workspace).expanduser()
    if root.name.casefold() != "xstagesong":
        root /= "XStageSong"
    return root / "MIDI" / "XSK" / code[0].upper() / (code + ".xsk")


def _validated(source, document, code, title, artist):
    source = Path(source)
    if (source.suffix.lower() not in (".mid", ".midi", ".kar")
            or not source.is_file() or source.is_symlink()):
        raise ValueError("XSK รุ่นนี้รองรับ MIDI/KAR ต้นฉบับที่มีอยู่จริงเท่านั้น")
    size = source.stat().st_size
    if not 32 <= size <= MAX_SOURCE:
        raise ValueError("ขนาด MIDI ไม่ถูกต้องหรือเกินขีดจำกัด")
    if not isinstance(document, dict) or not isinstance(document.get("lines"), list) or not document["lines"]:
        raise ValueError("ไม่มีเนื้อร้องพร้อมเวลาจริง")
    if not CODE_RE.fullmatch(code):
        raise ValueError("รหัสเพลงไม่ถูกต้อง")
    # A missing title or singer must never be replaced with the code or the
    # application's publisher name in a new cross-platform XSK2 catalog.
    title = str(title or "").strip()
    artist = str(artist or "").strip()
    placeholders = {"x-stage karaoke", "x-stage song studio", "unknown",
                    "ไม่ระบุชื่อเพลง", "ไม่ระบุศิลปิน"}
    if (not title or title.casefold() in placeholders or
            title.casefold() == code.casefold() or title.casefold() == source.stem.casefold()):
        raise ValueError("XSK2 ต้องมีชื่อเพลงจริง ไม่ใช้ชื่อไฟล์หรือรหัสเพลง")
    if not artist or artist.casefold() in placeholders:
        raise ValueError("XSK2 ต้องมีชื่อศิลปินจริง ไม่ใช้ชื่อโปรแกรม")
    previous = -1.0
    for row in document["lines"]:
        if not isinstance(row, dict) or not isinstance(row.get("text"), str):
            raise ValueError("โครงสร้างบรรทัดคำร้องผิดปกติ")
        t = row.get("startTime")
        if not isinstance(t, (int, float)) or isinstance(t, bool) or not 0 <= t < 86400:
            raise ValueError("เวลาคำร้องไม่ถูกต้อง")
        if t < previous:
            raise ValueError("เวลาคำร้องย้อนหลัง · ข้ามเพลงเพื่อป้องกันเวลาเสีย")
        previous = t
    return {"schemaVersion": 2, "format": "XSK", "formatVersion": 2,
            "createdBy": "X-Stage Song Studio",
            "publisher": "X-Stage Song Studio",
            "songCode": code, "title": title[:200],
            "artist": artist[:200],
            "audio": {"file": code + source.suffix.lower(),
                      "type": source.suffix[1:].upper(),
                      "size": size, "sha256": _hash_source(source)},
            "audioOffsetMs": document.get("audioOffsetMs", 0),
            "lines": document["lines"],
            "rawLrc": document.get("rawLrc", "")}


def _hash_source(source):
    dig = hashlib.sha256()
    with Path(source).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            dig.update(block)
    return dig.hexdigest()


def _commit_sealed_file(staged, target):
    """Atomic no-overwrite publish on NTFS and removable Windows volumes."""
    try:
        os.link(staged, target)
    except FileExistsError:
        raise
    except OSError:
        if os.name != "nt":
            # Refuse an unsafe rename/copy fallback which could expose a
            # partial encrypted package or overwrite someone else's file.
            raise
        # A Windows same-volume MoveFileEx WITHOUT REPLACE_EXISTING is
        # atomic, supports e.g. exFAT where NTFS hardlinks are unavailable.
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        mover = kernel.MoveFileExW
        mover.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        mover.restype = wintypes.BOOL
        MOVEFILE_WRITE_THROUGH = 0x00000008
        if not mover(str(staged), str(target), MOVEFILE_WRITE_THROUGH):
            error = ctypes.get_last_error()
            if error in (80, 183):
                raise FileExistsError("XSK มีชื่อไฟล์ซ้ำ · ไม่เขียนทับ") from None
            raise OSError(error, "ไม่สามารถเผยแพร่ XSK บนโฟลเดอร์นี้ได้")


def seal(source, document, code, title, artist, key=None, target=None):
    """Produce portable plaintext XSK2; legacy positional key is ignored.

    No key or password is ever created or embedded in newly written XSK2.
    The key parameter is retained temporarily for older internal callers.
    """
    metadata = _validated(source, document, code, title, artist)
    raw = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(raw) > MAX_DOC:
        raise ValueError("เนื้อร้องมีขนาดใหญ่ผิดปกติ")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=False) as z:
        # Avoid path traversal by writing fixed member basenames only.
        z.writestr(metadata["audio"]["file"], Path(source).read_bytes())
        z.writestr(code + ".json", raw)
    portable = MAGIC + archive.getvalue()
    if target is not None:
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            raise FileExistsError("มีไฟล์ XSK รหัสนี้อยู่แล้ว · ไม่เขียนทับอัตโนมัติ")
        temp = target.with_name("." + target.name + "." + secrets.token_hex(8) + ".partial")
        try:
            with temp.open("xb") as writer:
                writer.write(portable)
                writer.flush()
                os.fsync(writer.fileno())
            check = open_package(temp)
            if check["songCode"] != code:
                raise ValueError("ตรวจไฟล์ XSK หลังเข้ารหัสไม่ผ่าน")
            _commit_sealed_file(temp, target)  # Never overwrite existing XSK.
        finally:
            temp.unlink(missing_ok=True)
    return portable


def open_package(data_or_path, key=None):
    """Verify XSK2 without a key; read legacy XSK1 only with existing key."""
    if isinstance(data_or_path, Path):
        if data_or_path.is_symlink() or data_or_path.stat().st_size > MAX_ENCRYPTED:
            raise ValueError("ไฟล์ XSK ไม่ปลอดภัยหรือมีขนาดใหญ่เกินกำหนด")
        data = data_or_path.read_bytes()
    else:
        data = bytes(data_or_path)
    if len(data) > MAX_ENCRYPTED:
        raise ValueError("ไฟล์ XSK ใหญ่เกินขีดจำกัดที่รองรับ")
    if data.startswith(MAGIC):
        if len(data) < 26:
            raise ValueError("XSK2 ไม่สมบูรณ์")
        plain = data[4:]
    elif data.startswith(LEGACY_MAGIC):
        if len(data) < 33 or not isinstance(key, bytes) or len(key) != 32:
            raise ValueError("XSK1 รุ่นเก่าต้องใช้กุญแจ Windows เดิม · สร้างใหม่เป็น XSK2 เพื่อใช้กับ Web/APK")
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        plain = AESGCM(key).decrypt(data[4:16], data[16:], LEGACY_MAGIC)
    else:
        raise ValueError("ไฟล์ XSK ไม่ใช่ XSK1/XSK2 ที่รองรับ")
    with zipfile.ZipFile(io.BytesIO(plain)) as z:
        names = z.namelist()
        if len(names) != 2 or len(set(names)) != 2:
            raise ValueError("แพ็กเกจ XSK ไม่สมบูรณ์")
        documents = [n for n in names if n.endswith(".json")]
        if len(documents) != 1:
            raise ValueError("XSK ต้องมีข้อมูลเพลงหนึ่งรายการ")
        if z.getinfo(documents[0]).file_size > MAX_DOC:
            raise ValueError("ข้อมูล Lyrics JSON ภายใน XSK ใหญ่เกินขีดจำกัด")
        doc = json.loads(z.read(documents[0]))
        media = doc.get("audio") or {}
        expected_version = 2 if data.startswith(MAGIC) else 1
        if (doc.get("format") != "XSK" or doc.get("formatVersion") != expected_version
                or media.get("file") not in names):
            raise ValueError("โครงสร้าง XSK ไม่ถูกต้อง")
        if z.getinfo(media["file"]).file_size > MAX_SOURCE:
            raise ValueError("ไฟล์ MIDI ภายใน XSK ใหญ่เกินขีดจำกัด")
        with z.open(media["file"]) as stream:
            dig = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                dig.update(block)
        if dig.hexdigest() != media.get("sha256") or z.getinfo(media["file"]).file_size != media.get("size"):
            raise ValueError("ค่า SHA-256 ของเพลงไม่ตรง")
        return doc
