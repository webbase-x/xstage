#!/usr/bin/env python3
"""Build all X-Stage web/app icons from the canonical stage emblem SVG.

The source is assets/xstage-app-icon.svg, which matches the X + microphone
emblem used on the live karaoke stage. No user songs, Drive files, OAuth
tokens, or account content are accessed.
"""
from io import BytesIO
from pathlib import Path

import cairosvg
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SOURCE = ASSETS / "xstage-app-icon.svg"
BG = (7, 21, 37, 255)
RESAMPLE = Image.Resampling.LANCZOS


def render_svg(size: int) -> Image.Image:
    png = cairosvg.svg2png(url=str(SOURCE), output_width=size, output_height=size)
    return Image.open(BytesIO(png)).convert("RGBA")


# Browser favicon plus standard install/app icons.
render_svg(32).save(ASSETS / "xstage-favicon-32.png", format="PNG", optimize=True)
for size in (192, 512):
    render_svg(size).save(ASSETS / f"xstage-app-icon-{size}.png", format="PNG", optimize=True)

# Maskable icon: keep the stage emblem inside the central safe region.
mask_size = 512
maskable = Image.new("RGBA", (mask_size, mask_size), BG)
subject = render_svg(336).resize((336, 336), RESAMPLE)
margin = (mask_size - 336) // 2
maskable.alpha_composite(subject, (margin, margin))
maskable.convert("RGB").save(
    ASSETS / "xstage-app-icon-maskable-512.png", format="PNG", optimize=True
)

# Apple Home Screen icon uses the same emblem at a near-full safe size.
apple_size = 180
apple = Image.new("RGBA", (apple_size, apple_size), BG)
apple_logo = render_svg(168).resize((168, 168), RESAMPLE)
apple.alpha_composite(apple_logo, (6, 6))
apple.convert("RGB").save(
    ASSETS / "xstage-apple-touch-icon.png", format="PNG", optimize=True
)

print("Generated X-Stage stage-emblem icons: favicon 32, app 192/512, maskable 512, Apple 180.")
