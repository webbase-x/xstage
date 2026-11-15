"""Offline Pro entitlement verification via Ed25519.

Only the public verification key ships in Song Studio. The administrator's
private signing key MUST remain outside repositories and release archives.
"""
import base64
import json
from datetime import date
from pathlib import Path

PUBLIC_KEY_HEX = "4ca146a6a1cf061a74d0fb35b32aecb5dcc6ba713835856b8db5f8f55d710919"


def _decode(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify(text):
    if not isinstance(text, str) or len(text) > 8192:
        return False
    try:
        payload, signature = text.strip().split(".", 1)
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY_HEX)).verify(
            _decode(signature), payload.encode("ascii"))
        doc = json.loads(_decode(payload))
        return (doc.get("product") == "X-Stage Song Studio PC"
                and doc.get("tier") == "Pro"
                and (not doc.get("expires") or
                     date.fromisoformat(doc["expires"]) >= date.today()))
    except (ValueError, KeyError, TypeError, ImportError, UnicodeError, Exception):
        return False


def enabled(data_dir):
    path = Path(data_dir) / "pro-license.key"
    try:
        return path.is_file() and verify(path.read_text(encoding="utf-8"))
    except OSError:
        return False


def activate(data_dir, key):
    if not verify(key):
        raise ValueError("License Key Pro ไม่ถูกต้องหรือหมดอายุ")
    path = Path(data_dir) / "pro-license.key"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key.strip(), encoding="utf-8")
    return True
