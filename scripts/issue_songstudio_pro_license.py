"""Owner-only offline issuer for X-Stage Song Studio PC Pro licenses.

Example:
  python scripts/issue_songstudio_pro_license.py --private-key secret.pem \
    --name "Studio Pro" --expires 2027-12-31

Never commit, upload, or bundle the private PEM file.
"""
import argparse
import base64
import json
from datetime import date
from pathlib import Path


def b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def issue(key_path, name, expires):
    from cryptography.hazmat.primitives import serialization
    signing = serialization.load_pem_private_key(Path(key_path).read_bytes(), password=None)
    if expires:
        date.fromisoformat(expires)
    data = {"product": "X-Stage Song Studio PC", "tier": "Pro",
            "licensedTo": name, "expires": expires}
    content = b64(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    signature = signing.sign(content.encode("ascii"))
    return content + "." + b64(signature)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--expires", default="")
    args = parser.parse_args()
    print(issue(args.private_key, args.name, args.expires))
