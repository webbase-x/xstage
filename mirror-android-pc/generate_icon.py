#!/usr/bin/env python3
"""Render the brand SVG into the Windows ICO and the embedded welcome-screen PNG.

Run: python -m pip install Pillow==11.3.0 CairoSVG==2.7.1
     python mirror-android-pc/generate_icon.py
Both generated assets are CI build inputs, not user-downloaded runtime dependencies.
"""
from pathlib import Path
from io import BytesIO

import cairosvg
from PIL import Image

repo = Path(__file__).resolve().parent.parent
source = repo / "assets/app-icons/mirror-android-pc.svg"
target = repo / "mirror-android-pc/app.ico"
logo_target = repo / "mirror-android-pc/logo.png"
if not source.is_file():
    raise SystemExit("Mirror Android PC source icon is missing")
png = cairosvg.svg2png(url=str(source), output_width=256, output_height=256)
with Image.open(BytesIO(png)) as opened:
    image = opened.convert("RGBA")
    image.save(
        target, format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
               (64, 64), (128, 128), (256, 256)],
    )
with Image.open(target) as generated:
    sizes = set(generated.info.get("sizes", []))
    assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= sizes, sizes
assert target.stat().st_size > 1_024, "Icon output is unexpectedly small"
# Render from the SAME original SVG at higher resolution for the welcome display.
logo_data = cairosvg.svg2png(url=str(source), output_width=512, output_height=512)
with Image.open(BytesIO(logo_data)) as source_image:
    source_image.convert("RGBA").save(logo_target, format="PNG", optimize=True)
with Image.open(logo_target) as generated_logo:
    assert generated_logo.size == (512, 512)
    assert generated_logo.mode == "RGBA"
assert logo_target.stat().st_size > 1_024, "Brand PNG output is unexpectedly small"
print(f"Created {target.relative_to(repo)} ({target.stat().st_size} bytes)")
print(f"Created {logo_target.relative_to(repo)} ({logo_target.stat().st_size} bytes)")
