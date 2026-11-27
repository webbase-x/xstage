"""Fail closed before publishing an in-place Karaoke Android test update."""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

PACKAGE = "com.webbasex.xstage.debug"


def identity(badging, certificates):
    match = re.search(r"^package: name='([^']+)' versionCode='([0-9]+)' versionName='([^']+)'", badging, re.M)
    signers = re.findall(r"^Signer #\d+ certificate SHA-256 digest:\s*([0-9a-fA-F]{64})\s*$", certificates, re.M)
    if not match or len(signers) != 1:
        raise ValueError("APK package identity or single verified signer missing")
    return match[1], int(match[2]), match[3], signers[0].lower()


def expected(meta):
    version = meta.get("version")
    build = meta.get("build")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("Invalid APK version")
    if type(build) is not int or not 0 < build <= 2100000000:
        raise ValueError("Invalid Android versionCode")
    return PACKAGE, build, version + "-debug"


def check_upgrade(previous, candidate, old_meta, new_meta):
    if previous[:3] != expected(old_meta) or candidate[:3] != expected(new_meta):
        raise ValueError("APK package/versionCode/versionName differs from metadata")
    if candidate[1] < previous[1]:
        raise ValueError("APK versionCode downgrade")
    if candidate[1] == previous[1] and candidate[2] != previous[2]:
        raise ValueError("Reused versionCode with a different versionName")
    if candidate[3] != previous[3]:
        raise ValueError("APK signing certificate changed; in-place update blocked")
    return candidate[3]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inspect(apk, aapt, apksigner):
    def run(*args):
        return subprocess.run(args, check=True, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=60).stdout
    return identity(run(aapt, "dump", "badging", str(apk)),
                    run(apksigner, "verify", "--verbose", "--print-certs", str(apk)))


def verify(root, aapt, apksigner, candidate):
    old = json.loads((root / "downloads/android-tv-latest.json").read_text(encoding="utf-8"))
    new = json.loads((root / "version.json").read_text(encoding="utf-8"))
    _, build, _ = expected(old)
    filename = f"X-Stage-Karaoke-Android-v{old['version']}-build{build}.apk"
    if old.get("file") != filename:
        raise ValueError("Unexpected previous APK filename")
    previous = root / "downloads" / filename
    legacy = root / "karaoke.htmldownloads"
    if (digest(previous) != old.get("sha256") or
            digest(legacy / filename) != old.get("sha256") or
            json.loads((legacy / "android-tv-latest.json").read_text(encoding="utf-8")) != old):
        raise ValueError("Previous public APK or compatibility feed differs from metadata")
    prior = inspect(previous, aapt, apksigner)
    if old.get("signer_sha256") not in (None, prior[3]):
        raise ValueError("Previous APK signer differs from published fingerprint")
    return check_upgrade(prior, inspect(candidate, aapt, apksigner), old, new)


if __name__ == "__main__":
    try:
        print(verify(Path.cwd(), sys.argv[1], sys.argv[2], Path(sys.argv[3])))
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, IndexError) as exc:
        sys.exit(f"Android test update gate: {exc}")
