"""X-Stage Karaoke .xsk v1 sealed package.

Contains exactly one MIDI/KAR source and one timed song document. Encrypted
with authenticated AES-256-GCM. The format itself is portable; authorized
players still need a secure key-provisioning mechanism to open it.
No extracted media is written to a general-user project directory.
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

MAGIC = b"XSK1"
MAX_SOURCE = 128 * 1024 * 1024
MAX_DOC = 8 * 1024 * 1024
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
    return {"schemaVersion": 2, "format": "XSK", "formatVersion": 1,
            "songCode": code, "title": str(title or code)[:200],
            "artist": str(artist or "X-Stage Song Studio")[:200],
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


def seal(source, document, code, title, artist, key, target=None):
    """Return encrypted bytes; optionally publish atomically without overwrite."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise RuntimeError("โมดูลเข้ารหัส AES-256-GCM ไม่พร้อมในแพ็กเกจ") from exc
    if not isinstance(key, bytes) or len(key) != 32:
        raise ValueError("ต้องใช้กุญแจ AES-256 ที่มีสิทธิ์เท่านั้น")
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
    nonce = secrets.token_bytes(12)
    # Header is authenticated additional data; no ZIP or JSON plaintext leak.
    encrypted = MAGIC + nonce + AESGCM(key).encrypt(nonce, archive.getvalue(), MAGIC)
    if target is not None:
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            raise FileExistsError("มีไฟล์ XSK รหัสนี้อยู่แล้ว · ไม่เขียนทับอัตโนมัติ")
        temp = target.with_name("." + target.name + "." + secrets.token_hex(8) + ".partial")
        try:
            with temp.open("xb") as writer:
                writer.write(encrypted)
                writer.flush()
                os.fsync(writer.fileno())
            check = open_package(temp, key)
            if check["songCode"] != code:
                raise ValueError("ตรวจไฟล์ XSK หลังเข้ารหัสไม่ผ่าน")
            os.link(temp, target)  # Atomic no-clobber; never overwrite existing file.
        finally:
            temp.unlink(missing_ok=True)
    return encrypted


def open_package(data_or_path, key):
    """Authenticate and check the MIDI digest; no media extraction to disk."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    data = (Path(data_or_path).read_bytes() if isinstance(data_or_path, Path)
            else bytes(data_or_path))
    if len(data) < 33 or not data.startswith(MAGIC):
        raise ValueError("ไฟล์ XSK ไม่ใช่รุ่นที่รองรับ")
    plain = AESGCM(key).decrypt(data[4:16], data[16:], MAGIC)
    with zipfile.ZipFile(io.BytesIO(plain)) as z:
        names = z.namelist()
        if len(names) != 2 or len(set(names)) != 2:
            raise ValueError("แพ็กเกจ XSK ไม่สมบูรณ์")
        documents = [n for n in names if n.endswith(".json")]
        if len(documents) != 1:
            raise ValueError("XSK ต้องมีข้อมูลเพลงหนึ่งรายการ")
        doc = json.loads(z.read(documents[0]))
        media = doc.get("audio") or {}
        if (doc.get("format") != "XSK" or doc.get("formatVersion") != 1
                or media.get("file") not in names):
            raise ValueError("โครงสร้าง XSK ไม่ถูกต้อง")
        with z.open(media["file"]) as stream:
            dig = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                dig.update(block)
        if dig.hexdigest() != media.get("sha256"):
            raise ValueError("ค่า SHA-256 ของเพลงไม่ตรง")
        return doc
