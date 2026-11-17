#!/usr/bin/env python3
"""Create the distinctive X-Stage Karaoke PC Windows icon (pure Pillow).

Generates windows-pc/source/assets/xstage.ico just before Windows packaging.
Never modifies the Online player's original X/microphone icon.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "windows-pc/source/assets/xstage.ico"
FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
]

def make_icon(size=512):
    im = Image.new("RGBA", (size, size), (18, 29, 54, 255))
    d = ImageDraw.Draw(im)
    def rect(coords, fill, outline=None, width=1, radius=0):
        d.rounded_rectangle(coords, radius=radius, fill=fill, outline=outline, width=width)
    # Gold PC / desktop identity (different from teal Web and green TV).
    rect((8, 8, 504, 504), (28, 34, 70), (250, 186, 100), 8, 105)
    d.ellipse((240, 80, 510, 400), fill=(68, 44, 92))
    d.line(((62, 48), (120, 115)), fill=(109, 219, 255), width=16)
    d.line(((120, 48), (62, 115)), fill=(254, 159, 87), width=16)
    rect((85, 155, 392, 338), (14, 29, 67), (210, 231, 255), 11, 20)
    rect((101, 174, 376, 313), (26, 54, 112), (96, 133, 206), 4, 8)
    d.line(((206, 351), (278, 351)), fill=(218, 231, 253), width=12)
    d.line(((243, 338), (243, 354)), fill=(218, 231, 253), width=10)
    for y, length in [(257, 142), (278, 112)]:
        d.line(((135, y), (135 + length, y)), fill=(255, 208, 137), width=9)
    d.line(((165, 189), (165, 235)), fill=(142, 218, 250), width=8)
    d.line(((165, 189), (205, 180)), fill=(142, 218, 250), width=8)
    d.ellipse((151, 225, 176, 252), fill=(142, 218, 250))
    d.ellipse((192, 214, 219, 241), fill=(142, 218, 250))
    # Front microphone is the unmistakable karaoke cue for Windows PC.
    rect((308, 193, 397, 326), (245, 176, 95), (255, 235, 185), 6, 37)
    for y in (228, 249, 269):
        d.line(((325, y), (382, y)), fill=(124, 78, 43), width=6)
    d.arc((300, 258, 406, 356), 0, 180, fill=(255, 231, 171), width=8)
    d.line(((352, 354), (352, 375)), fill=(245, 187, 116), width=9)
    d.line(((318, 379), (384, 379)), fill=(245, 187, 116), width=9)
    face = next((p for p in FONT_PATHS if Path(p).exists()), None)
    if face:
        font = ImageFont.truetype(face, 28)
    else:
        font = ImageFont.load_default()
    text = "KARAOKE PC"
    box = d.textbbox((0, 0), text, font=font)
    d.text(((512 - (box[2] - box[0])) / 2, 421), text,
           font=font, fill=(243, 248, 255))
    return im

def main():
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    image = make_icon()
    image.save(TARGET, format="ICO", sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
    if TARGET.stat().st_size < 2048:
        raise SystemExit("Generated ICO is unexpectedly small")
    print("X-Stage Karaoke PC Windows ICO:", TARGET, TARGET.stat().st_size, "bytes")

if __name__ == "__main__":
    main()
