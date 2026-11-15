#!/usr/bin/env python3
"""Read-only cross-platform XStageSong storage naming contract.

Legacy local Song Studio StageWeb is mentioned only in the non-destructive,
same-volume authoring-library migration code. No legacy root is accepted by
current Web/Android, Google Drive publishing, or Karaoke PC.
"""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]
patterns = (
    "*.js", "*.html", "studio/*.js", "studio/*.html",
    "songstudio-pc/*.py", "windows-pc/source/karaoke/*.py",
    "android-tv/app/src/main/java/**/*.java",
)
files = sorted({path for pattern in patterns for path in ROOT.glob(pattern)
                if path.is_file()})
old_root = re.compile(r"XStageWeb|StageWeb")
failures = []
for path in files:
    body = path.read_text(encoding="utf-8-sig")
    for index, line in enumerate(body.splitlines(), 1):
        if not old_root.search(line):
            continue
        # Preserve existing *local* authoring work, not old Drive libraries.
        if (path.relative_to(ROOT).as_posix() == "songstudio-pc/song_export.py"
                and ("StageWeb" in line) and "XStageWeb" not in line):
            continue
        if (path.relative_to(ROOT).as_posix() == "songstudio-pc/song_index.py"
                and 'work / "StageWeb"' in line):
            continue  # Exclude old authoring output from the input scanner.
        failures.append(f"{path.relative_to(ROOT)}:{index}: old storage root")

publisher = (ROOT / "songstudio-pc/online_publish.py").read_text(encoding="utf-8")
pc_export = (ROOT / "songstudio-pc/pc_library_export.py").read_text(encoding="utf-8")
pc_reader = (ROOT / "windows-pc/source/karaoke/pc_stageweb.py").read_text(encoding="utf-8")
browser = (ROOT / "app.js").read_text(encoding="utf-8")
importer = (ROOT / "cloud-import.js").read_text(encoding="utf-8")
if 'ONLINE_ROOT = "XStageSong"' not in publisher:
    failures.append("Song Studio cloud publisher does not use XStageSong")
if 'return chosen if chosen.name.casefold() == "xstagesong" else chosen / "XStageSong"' not in pc_export:
    failures.append("Song Studio PC destination is not XStageSong")
if 'path = path / "XStageSong"' not in pc_reader:
    failures.append("Karaoke PC reader is not XStageSong")
if "name='XStageSong'" not in browser or "name='XStageSong'" not in importer:
    failures.append("Browser library discovery/import does not use XStageSong")
if len(re.findall(r"(?<![A-Za-z])XStageSong(?![A-Za-z])", publisher)) < 1:
    failures.append("Publisher has no canonical storage root")

version = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
page = (ROOT / "index.html").read_text(encoding="utf-8")
if version.get("version") != package.get("version"):
    failures.append("Web and package versions differ")
if f"?v={version.get('build')}" not in page:
    failures.append("Web cache-busting build does not match version.json")
print(f"Audited {len(files)} active sources across Web, Android, Studio and Windows.")
if failures:
    for entry in failures:
        print("FAIL:", entry)
    raise SystemExit(1)
print(f"PASS: all active storage paths use XStageSong, Web/Android v{version['version']} build {version['build']}.")
