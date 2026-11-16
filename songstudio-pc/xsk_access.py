"""User-approved, password-wrapped export of the existing Song Studio XSK key.

No Windows username, computer name, license, raw key, or password is stored.
The export file must be treated as a sensitive credential and shared manually.
The XSK source encryption format itself remains unchanged.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from pathlib import Path

MAGIC = "XSK-ACCESS1"
AAD = MAGIC.encode("ascii")
ROUNDS = 310_000


def export_access(key: bytes, password: str, destination):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if not isinstance(key, bytes) or len(key) != 32:
        raise ValueError("กุญแจ XSK ของบัญชีนี้ไม่ถูกต้อง")
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError("รหัสผ่านสำหรับส่งต่อ XSK ต้องมีอย่างน้อย 12 ตัวอักษร")
    target = Path(destination).expanduser()
    if target.suffix.lower() != ".xskkey" or target.is_symlink() or target.exists():
        raise ValueError("ต้องใช้ไฟล์ใหม่ .xskkey ที่ยังไม่มีอยู่เท่านั้น")
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    wrapping = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ROUNDS, dklen=32)
    wrapped = AESGCM(wrapping).encrypt(nonce, key, AAD)
    b64 = lambda value: base64.b64encode(value).decode("ascii")
    doc = {"format": MAGIC, "kdf": "PBKDF2-SHA256",
           "iterations": ROUNDS, "salt": b64(salt),
           "nonce": b64(nonce), "wrappedKey": b64(wrapped),
           "publisher": "X-Stage Song Studio"}
    # No replacing existing files. A failed save never exposes a raw key.
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as out:
        json.dump(doc, out, ensure_ascii=False, separators=(",", ":"))
        out.flush()
        os.fsync(out.fileno())
    return str(target)


def unwrap_access(document: dict, password: str) -> bytes:
    """Test/diagnostic helper; production Web uses WebCrypto instead."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not isinstance(document, dict) or document.get("format") != MAGIC or (
            document.get("kdf") != "PBKDF2-SHA256" or
            document.get("iterations") != ROUNDS):
        raise ValueError("รูปแบบกุญแจส่งต่อไม่ถูกต้อง")
    decode = lambda name: base64.b64decode(document[name], validate=True)
    salt, nonce, wrapped = (decode(k) for k in ("salt", "nonce", "wrappedKey"))
    if len(salt) != 16 or len(nonce) != 12 or len(wrapped) != 48:
        raise ValueError("ข้อมูลกุญแจส่งต่อไม่ครบ")
    wrapping = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ROUNDS, dklen=32)
    key = AESGCM(wrapping).decrypt(nonce, wrapped, AAD)
    if len(key) != 32:
        raise ValueError("กุญแจ XSK ที่เปิดได้มีขนาดไม่ถูกต้อง")
    return key
