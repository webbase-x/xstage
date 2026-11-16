"""Read Song Studio XSK1 packages on the same authorized Windows account.

Never create a key while importing, never write decrypted media to disk, and
never consider an unverified XSK playable. Other accounts/devices require
an explicit future key-transfer flow.
"""
from __future__ import annotations

import ctypes
import hashlib
import io
import json
import os
import zipfile
from ctypes import wintypes
from pathlib import Path

MAGIC = b"XSK1"
MAX_SOURCE = 128 * 1024 * 1024
MAX_DOC = 8 * 1024 * 1024
MAX_ENCRYPTED = MAX_SOURCE + MAX_DOC + 16 * 1024 * 1024


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD),
                ("data", ctypes.POINTER(ctypes.c_ubyte))]


def existing_key():
    """Return Song Studio's existing *current-user* DPAPI key; never mint one."""
    if os.name != "nt":
        raise PermissionError("XSK ต้องใช้บัญชี Windows ที่สร้างไฟล์เพื่อถอดรหัส")
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise PermissionError("ไม่พบ LOCALAPPDATA สำหรับกุญแจ XSK")
    path = Path(base) / "X-Stage" / "SongStudio" / "xsk-key.dpapi"
    if path.is_symlink() or not path.is_file():
        raise PermissionError("ไม่พบกุญแจ XSK ของบัญชีนี้: เปิดผ่าน Song Studio ที่สร้างไฟล์")
    raw = path.read_bytes()
    if not raw or len(raw) > 65536:
        raise ValueError("ไฟล์กุญแจ XSK ไม่ถูกต้อง")
    source_buf = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    source = _Blob(len(raw), ctypes.cast(source_buf, ctypes.POINTER(ctypes.c_ubyte)))
    dest = _Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    crypt.CryptUnprotectData.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0,
                                    ctypes.byref(dest)):
        raise PermissionError("บัญชี Windows นี้ไม่มีสิทธิ์เปิด XSK หรือกุญแจเสียหาย")
    try:
        value = ctypes.string_at(dest.data, dest.size)
    finally:
        kernel.LocalFree(dest.data)
    if len(value) != 32:
        raise ValueError("ขนาดกุญแจ XSK ไม่ถูกต้อง")
    return value


def read_xsk(path, *, key=None):
    """Authenticate first; return (MIDI bytes, timed JSON) without extraction."""
    path = Path(path)
    if path.suffix.casefold() != ".xsk" or path.is_symlink() or not path.is_file():
        raise ValueError("ต้องเลือกไฟล์ XSK ปกติ")
    size = path.stat().st_size
    if size < 33 or size > MAX_ENCRYPTED:
        raise ValueError("ขนาดแพ็กเกจ XSK ไม่ปลอดภัย")
    data = path.read_bytes()
    if not data.startswith(MAGIC):
        raise ValueError("XSK header ไม่ถูกต้อง")
    if key is None:
        key = existing_key()
    if not isinstance(key, bytes) or len(key) != 32:
        raise ValueError("กุญแจ XSK ไม่ถูกต้อง")
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise RuntimeError("ตัวเล่นต้องติดตั้ง cryptography เพื่อเปิด XSK") from exc
    plain = AESGCM(key).decrypt(data[4:16], data[16:], MAGIC)
    with zipfile.ZipFile(io.BytesIO(plain)) as archive:
        infos = archive.infolist()
        if len(infos) != 2 or len(set(x.filename for x in infos)) != 2:
            raise ValueError("XSK ต้องมี MIDI และ Lyrics JSON อย่างละหนึ่งไฟล์")
        for info in infos:
            if (info.filename != Path(info.filename).name or
                    "\\" in info.filename or info.filename.startswith(".") or
                    info.flag_bits & 1 or info.file_size < 0):
                raise ValueError("พบรายการ ZIP ไม่ปลอดภัย")
        documents = [x for x in infos if x.filename.lower().endswith(".json")]
        midi = [x for x in infos if x.filename.lower().endswith((".mid", ".midi", ".kar"))]
        if len(documents) != 1 or len(midi) != 1:
            raise ValueError("XSK ไม่มี MIDI/JSON ครบคู่")
        if documents[0].file_size > MAX_DOC or midi[0].file_size > MAX_SOURCE:
            raise ValueError("ข้อมูลภายใน XSK ใหญ่เกินขอบเขต")
        doc = json.loads(archive.read(documents[0]).decode("utf-8"))
        info = doc.get("audio")
        if (doc.get("format") != "XSK" or doc.get("formatVersion") != 1 or
                not isinstance(info, dict) or info.get("file") != midi[0].filename or
                not isinstance(doc.get("lines"), list)):
            raise ValueError("รูปแบบเอกสาร XSK ไม่ถูกต้อง")
        raw = archive.read(midi[0])
        if hashlib.sha256(raw).hexdigest() != info.get("sha256"):
            raise ValueError("ลายเซ็น SHA-256 ของ MIDI ไม่ตรง")
        previous = -1
        for row in doc["lines"]:
            if not isinstance(row, dict) or not isinstance(row.get("text"), str):
                raise ValueError("เนื้อร้อง XSK ผิดรูปแบบ")
            at = row.get("startTime")
            if isinstance(at, bool) or not isinstance(at, (float, int)) or not 0 <= at < 86400 or at < previous:
                raise ValueError("เวลาเนื้อร้อง XSK ไม่ถูกต้อง")
            previous = at
        return raw, doc
