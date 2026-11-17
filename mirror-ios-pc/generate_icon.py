#!/usr/bin/env python3
"""Render the existing X-Stage Mirror iOS PC SVG into a multiresolution Windows ICO.

Run: python -m pip install Pillow==11.3.0 CairoSVG==2.7.1
     python mirror-ios-pc/generate_icon.py
The generated ICO is an intermediate build asset, not a separately downloaded app dependency.
"""
from pathlib import Path
from io import BytesIO

import cairosvg
from PIL import Image

repo = Path(__file__).resolve().parent.parent
source = repo / "assets/app-icons/mirror-ios-pc.svg"
target = repo / "mirror-ios-pc/app.ico"
if not source.is_file():
    raise SystemExit("Mirror iOS PC source icon is missing")
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
print(f"Created {target.relative_to(repo)} ({target.stat().st_size} bytes)")
