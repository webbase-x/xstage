#!/usr/bin/env python3
"""Build brand-matched X-Stage PWA icons from the existing public X-Stage logo.

This script reads only assets/xstage-logo.jpg. It does not access user songs,
Google Drive files, Google OAuth tokens, or private account content.
"""
from pathlib import Path
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SOURCE = ASSETS / "xstage-logo.jpg"
RESAMPLE = Image.Resampling.LANCZOS

with Image.open(SOURCE) as image:
    original = ImageOps.fit(image.convert("RGB"), (1600, 1600), method=RESAMPLE)

for size in (192, 512):
    original.resize((size, size), RESAMPLE).save(
        ASSETS / f"xstage-app-icon-{size}.png", format="PNG", optimize=True
    )

# A dedicated maskable icon keeps the subject within the safe central region.
mask_size = 512
maskable = Image.new("RGB", (mask_size, mask_size), (5, 21, 33))
subject_size = 360
subject = original.resize((subject_size, subject_size), RESAMPLE)
margin = (mask_size - subject_size) // 2
maskable.paste(subject, (margin, margin))
maskable.save(ASSETS / "xstage-app-icon-maskable-512.png", format="PNG", optimize=True)

# Apple Home Screen icons need a dedicated high-resolution square image.
apple_size = 180
apple = Image.new("RGB", (apple_size, apple_size), (5, 21, 33))
apple_logo = original.resize((166, 166), RESAMPLE)
apple.paste(apple_logo, (7, 7))
apple.save(ASSETS / "xstage-apple-touch-icon.png", format="PNG", optimize=True)

print("Generated X-Stage PWA icons: 192, 512, maskable 512, Apple 180.")
