#!/usr/bin/env python3
"""Safely import the verified Windows PC v0.9.48 R18.1 source archive.

No binary installer is produced here. This only stages source for later Windows CI.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_NAME = "X-Stage-Karaoke-v0.9.48-Windows-Source-TurboSync-R18.1-Thai-ETA.zip"
EXPECTED_SHA256 = "2e7769c70580b61996ff2e351a20c30816dc674dcc8db1ee257fc1ed8c062beb"
ARCHIVE = ROOT / "downloads" / ARCHIVE_NAME
WINDOWS_ROOT = ROOT / "windows-pc"
DESTINATION = WINDOWS_ROOT / "source"


def main() -> None:
    if not ARCHIVE.is_file():
        raise SystemExit(f"Missing ZIP: {ARCHIVE.relative_to(ROOT)}. Upload the actual source archive first.")
    actual = hashlib.file_digest(ARCHIVE.open("rb"), "sha256").hexdigest()
    if actual.lower() != EXPECTED_SHA256:
        raise SystemExit(f"SHA-256 mismatch: expected {EXPECTED_SHA256}, got {actual}")
    WINDOWS_ROOT.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="xstage-windows-source-", dir=WINDOWS_ROOT))
    try:
        with zipfile.ZipFile(ARCHIVE) as z:
            entries = [e for e in z.infolist() if not e.is_dir()]
            if len(entries) != 444:
                raise ValueError(f"Expected 444 files; got {len(entries)}")
            if sum(e.file_size for e in entries) > 40_000_000:
                raise ValueError("Unexpectedly large unpacked source")
            for member in entries:
                name = PurePosixPath(member.filename)
                if (member.filename.startswith("/") or "\\" in member.filename
                    or any(part in ("", ".", "..") for part in name.parts)):
                    raise ValueError(f"Unsafe ZIP path: {member.filename}")
                mode = member.external_attr >> 16
                if stat.S_IFMT(mode) == stat.S_IFLNK:
                    raise ValueError(f"Symlink in source archive: {member.filename}")
                dest = stage.joinpath(*name.parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with z.open(member) as src, dest.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
        version = (stage / "version_info.txt").read_text(encoding="utf-8-sig")
        if "0.9.48" not in version:
            raise ValueError("Windows version_info.txt does not match v0.9.48")
        if not (stage / "Build-Windows.cmd").is_file() or not (stage / "main.py").is_file():
            raise ValueError("Archive is missing Windows build entrypoints")
        # Replace only the dedicated Windows source subtree after full validation.
        if DESTINATION.exists():
            shutil.rmtree(DESTINATION)
        stage.rename(DESTINATION)
        stage = None
        manifest = {
            "platform": "windows",
            "version": "0.9.48",
            "source_revision": "TurboSync-R18.1-Thai-ETA",
            "source_archive": "downloads/" + ARCHIVE_NAME,
            "sha256": EXPECTED_SHA256,
            "source_files": len(entries),
            "source_imported": True,
            "windows_build_verified": False,
            "installer_published": False,
            "status": "SOURCE_IMPORTED_NOT_A_WINDOWS_RELEASE",
        }
        (WINDOWS_ROOT / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Imported {len(entries)} Windows source files into {DESTINATION.relative_to(ROOT)}")
    finally:
        if stage and stage.exists():
            shutil.rmtree(stage)


if __name__ == "__main__":
    main()
