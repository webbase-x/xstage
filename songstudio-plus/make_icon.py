"""Create the branded, multi-resolution X-Stage Song Studio Pro Windows icon.

Keep the Windows EXE/Setup icon consistent with web/icon.svg: X and a PRO
badge, not the legacy plus (+) badge. Pillow is only a build dependency.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

SIZE = 512
BADGE_FILL = (21, 62, 89)
BADGE_TEXT = (176, 255, 240)


def _pro_font():
    # Use a bold UI font when available, with a bundled Pillow fallback.
    for name in ("arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, 39)
        except OSError:
            pass
    return ImageFont.load_default(size=39)


def render_icon():
    im = Image.new("RGBA", (SIZE, SIZE), (9, 17, 36, 255))
    pixels = im.load()
    for y in range(SIZE):
        for x in range(SIZE):
            blend = (x + y) / (2 * SIZE)
            glow = max(0, 1 - ((x - 355) ** 2 + (y - 134) ** 2) ** .5 / 370)
            pixels[x, y] = (int(13 + 43 * blend + 25 * glow),
                            int(29 + 22 * blend + 40 * glow),
                            int(58 + 54 * blend + 63 * glow), 255)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((11, 11, 501, 501), radius=116,
                        outline=(121, 206, 240), width=10)
    d.ellipse((86, 86, 426, 426), fill=(11, 22, 46),
              outline=(92, 154, 199), width=6)
    for radius in (145, 125, 104):
        d.ellipse((256-radius, 256-radius, 256+radius, 256+radius),
                  outline=(42+radius//6, 83+radius//3, 126+radius//3),
                  width=3)
    # Main X symbol, independent of fonts.
    d.polygon([(145, 138), (203, 138), (256, 210), (309, 138),
               (368, 138), (289, 256), (372, 374), (312, 374),
               (256, 300), (200, 374), (140, 374), (222, 256)],
              fill=(128, 240, 234))
    # The website badge is explicitly PRO. Do not draw the old '+' mark.
    d.rounded_rectangle((344, 76, 469, 146), radius=25,
                        fill=BADGE_FILL, outline=(131, 232, 220), width=4)
    d.text((406, 110), "PRO", font=_pro_font(), anchor="mm", fill=BADGE_TEXT)
    d.ellipse((243, 243, 269, 269), fill=(10, 33, 62),
              outline=(233, 255, 253), width=4)
    return im


def save_icon(out=None):
    out = Path(out) if out is not None else Path(__file__).resolve().parent / "app-plus.ico"
    render_icon().save(out, format="ICO", sizes=[
        (16, 16), (24, 24), (32, 32), (48, 48),
        (64, 64), (128, 128), (256, 256)])
    return out


if __name__ == "__main__":
    print(save_icon())
