"""Read portable unencrypted XSK2 and legacy encrypted XSK1.

XSK2 requires no Windows key and shares exactly the same package with
Web and APK. Legacy XSK1 still requires the owner's existing DPAPI key.
Always validate ZIP entries, metadata, and MIDI SHA-256 before indexing.
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

MAGIC = b"XSK2"
LEGACY_MAGIC = b"XSK1"
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
    if size < 26 or size > MAX_ENCRYPTED:
        raise ValueError("ขนาดแพ็กเกจ XSK ไม่ปลอดภัย")
    data = path.read_bytes()
    if data.startswith(MAGIC):
        plain = data[4:]
        expected_version = 2
    elif data.startswith(LEGACY_MAGIC):
        if key is None:
            key = existing_key()
        if not isinstance(key, bytes) or len(key) != 32:
            raise ValueError("XSK1 เดิมต้องใช้กุญแจ Windows ของเจ้าของไฟล์")
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:
            raise RuntimeError("ตัวเล่นต้องมี cryptography สำหรับ XSK1 เดิม") from exc
        plain = AESGCM(key).decrypt(data[4:16], data[16:], LEGACY_MAGIC)
        expected_version = 1
    else:
        raise ValueError("XSK header ไม่ใช่ XSK1/XSK2 ที่รองรับ")
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
        if (doc.get("format") != "XSK" or
                doc.get("formatVersion") != expected_version or
                not isinstance(info, dict) or info.get("file") != midi[0].filename or
                not isinstance(doc.get("lines"), list)):
            raise ValueError("รูปแบบเอกสาร XSK ไม่ถูกต้อง")
        banned = {"x-stage karaoke", "x-stage song studio", "unknown", "ไม่ระบุศิลปิน"}
        title, artist = doc.get("title"), doc.get("artist")
        if (not isinstance(title, str) or not title.strip() or
                title.strip() == str(doc.get("songCode") or "") or
                not isinstance(artist, str) or not artist.strip() or
                artist.strip().casefold() in banned):
            raise ValueError("XSK ไม่มีชื่อเพลงหรือศิลปินจริง · กรุณาสร้างใหม่ด้วย Song Studio")
        raw = archive.read(midi[0])
        if (hashlib.sha256(raw).hexdigest() != info.get("sha256") or
                len(raw) != info.get("size")):
            raise ValueError("ลายเซ็น SHA-256 หรือขนาด MIDI ไม่ตรง")
        previous = -1
        for row in doc["lines"]:
            if not isinstance(row, dict) or not isinstance(row.get("text"), str):
                raise ValueError("เนื้อร้อง XSK ผิดรูปแบบ")
            at = row.get("startTime")
            if isinstance(at, bool) or not isinstance(at, (float, int)) or not 0 <= at < 86400 or at < previous:
                raise ValueError("เวลาเนื้อร้อง XSK ไม่ถูกต้อง")
            previous = at
        return raw, doc
