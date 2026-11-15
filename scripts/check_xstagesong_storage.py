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
# Scan source, configuration, documentation and platform packaging scripts.
# The old local authoring folder StageWeb is a distinct historical name; only
# the deprecated shared cloud/PC root is prohibited.
source_suffixes = {
    ".js", ".mjs", ".py", ".html", ".css", ".json", ".webmanifest",
    ".md", ".java", ".xml", ".kt", ".ps1", ".cmd", ".yml", ".yaml",
    ".gradle", ".properties", ".txt", ".svg", ".ts", ".tsx",
}
files = sorted(path for path in ROOT.rglob("*") if path.is_file()
               and path.suffix.lower() in source_suffixes
               and not any(part in {"vendor", ".git", "__pycache__"}
                           for part in path.relative_to(ROOT).parts)
               and path.relative_to(ROOT).as_posix() !=
               "scripts/check_xstagesong_storage.py")
old_root = re.compile("xstage" + "web", re.IGNORECASE)
failures = []
for path in files:
    relative = path.relative_to(ROOT)
    if old_root.search(relative.as_posix()):
        failures.append(f"{relative}: old storage filename")
    try:
        body = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as error:
        failures.append(f"{relative}: unable to inspect: {error}")
        continue
    for index, line in enumerate(body.splitlines(), 1):
        if old_root.search(line):
            failures.append(f"{relative}:{index}: old X-Stage storage root")

publisher = (ROOT / "songstudio-pc/online_publish.py").read_text(encoding="utf-8")
pc_export = (ROOT / "songstudio-pc/pc_library_export.py").read_text(encoding="utf-8")
pc_reader = (ROOT / "windows-pc/source/karaoke/pc_xstagesong.py").read_text(encoding="utf-8")
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
