#!/usr/bin/env python3
"""Build a source-only Windows ZIP including the existing same-UI control frontend."""
from pathlib import Path
from hashlib import sha256
import re
from zipfile import ZipFile, ZIP_DEFLATED, ZipInfo

REPO = Path(__file__).resolve().parents[1]
DEST = REPO / "downloads" / "X-Stage-Song-Studio-PC-Source-Launcher-v0.2.6-Build206-Preview.zip"
ROOT = "X-Stage-Song-Studio-PC-Source-Preview"
FILES = {
    "songstudio-pc/Start-Song-Studio.cmd": "Start-Song-Studio.cmd",
    "songstudio-pc/Start-Song-Studio.ps1": "Start-Song-Studio.ps1",
    "songstudio-pc/engine.py": "engine.py",
    "songstudio-pc/history_store.py": "history_store.py",
    "songstudio-pc/folder_upload.py": "folder_upload.py",
    "songstudio-pc/ncn_lyrics.py": "ncn_lyrics.py",
    "songstudio-pc/song_index.py": "song_index.py",
    "songstudio-pc/ai_lyrics.py": "ai_lyrics.py",
    "songstudio-pc/lyric_alignment.py": "lyric_alignment.py",
    "songstudio-pc/lyric_text_groups.py": "lyric_text_groups.py",
    "songstudio-pc/google_drive.py": "google_drive.py",
    "songstudio-pc/online_publish.py": "online_publish.py",
    "songstudio-pc/code_registry.py": "code_registry.py",
    "songstudio-pc/created_json_manager.py": "created_json_manager.py",
    "songstudio-pc/created_xsk_export.py": "created_xsk_export.py",
    "songstudio-pc/json_pro_export.py": "json_pro_export.py",
    "songstudio-pc/import_preview.py": "import_preview.py",
"songstudio-pc/xsk_package.py": "xsk_package.py",
    "songstudio-pc/xsk_stream.py": "xsk_stream.py",
    "songstudio-pc/xsk_keys.py": "xsk_keys.py",
    "songstudio-pc/pro_license.py": "pro_license.py",
    "songstudio-pc/pc_ready_updates.py": "pc_ready_updates.py",
    "songstudio-pc/song_export.py": "song_export.py",
    "songstudio-pc/pc_library_export.py": "pc_library_export.py",
    "songstudio-pc/live_preview.py": "live_preview.py",
    "songstudio-pc/ai_separate.py": "ai_separate.py",
    "songstudio-pc/ai-model.lock.json": "ai-model.lock.json",
    "songstudio-pc/pick_path.ps1": "pick_path.ps1",
    "songstudio-pc/README.md": "README.md",
    "studio/app-icon.svg": "studio/app-icon.svg",
    "studio/site.webmanifest": "studio/site.webmanifest",
    "studio/index.html": "studio/index.html",
    "studio/app.js": "studio/app.js",
    "studio/style.css": "studio/style.css",
    "studio/pro-design.css": "studio/pro-design.css",
    "studio/entry.js": "studio/entry.js",
}

def package():
    # The source Engine loads optional feature modules dynamically. Every
    # literal module requested from _module must be included before shipping.
    engine_text = (REPO / "songstudio-pc" / "engine.py").read_text(encoding="utf-8-sig")
    module_names = set(re.findall(r'_module\\(\\s*["\\\']([^"\\\']+\\.py)["\\\']', engine_text))
    package_names = {Path(source).name for source in FILES}
    missing = sorted(module_names - package_names)
    if missing:
        raise RuntimeError("Source ZIP missing Engine modules: " + ", ".join(missing))
    DEST.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(DEST, "w", ZIP_DEFLATED, compresslevel=9) as archive:
        for source, output in sorted(FILES.items()):
            data = (REPO / source).read_bytes()
            info = ZipInfo(f"{ROOT}/{output}", date_time=(2026, 11, 12, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data, compress_type=ZIP_DEFLATED, compresslevel=9)
    digest = sha256(DEST.read_bytes()).hexdigest()
    companion = DEST.with_name(DEST.name + ".sha256")
    companion.write_text(f"{digest}  {DEST.name}\n", encoding="utf-8")
    print(f"Built {DEST} ({DEST.stat().st_size:,} bytes, SHA256 {digest})")
    return DEST

if __name__ == "__main__":
    package()
