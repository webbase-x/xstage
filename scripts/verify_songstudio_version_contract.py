"""Fail early if the Windows Ready release and bundled PC Engine disagree.

No third-party dependencies or downloads. Intended to run *before* building
the 650+ MB offline bundle; the full integration smoke test remains mandatory.
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def identity():
    builder = (ROOT / "scripts/build_songstudio_ready.ps1").read_text(encoding="utf-8-sig")
    engine = (ROOT / "songstudio-pc/engine.py").read_text(encoding="utf-8-sig")

    package = re.search(
        r"(?m)^\$Version\s*=\s*'v(\d+\.\d+\.\d+)-build(\d+)'\s*$",
        builder,
    )
    runtime_version = re.search(
        r'(?m)^STATUS_VERSION\s*=\s*"([^"]+)"\s+if READY_BUNDLE\s+else',
        engine,
    )
    runtime_build = re.search(
        r'(?m)^STATUS_BUILD\s*=\s*"([^"]+)"\s+if READY_BUNDLE\s+else',
        engine,
    )
    if not (package and runtime_version and runtime_build):
        raise ValueError("Cannot independently identify Ready package and engine versions")
    requested = (package.group(1), package.group(2))
    actual = (runtime_version.group(1), runtime_build.group(1))
    if requested != actual:
        raise ValueError(
            f"PC Ready package v{requested[0]} Build {requested[1]} "
            f"does not match bundled Engine v{actual[0]} Build {actual[1]}"
        )
    return requested


if __name__ == "__main__":
    try:
        version, build = identity()
    except (OSError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"PASS: Song Studio Ready and PC Engine v{version} Build {build} agree")
