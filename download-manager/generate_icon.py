"""Create an original X-Stage Download Manager ICO for Windows builds."""
from pathlib import Path
from PIL import Image, ImageDraw

out = Path(__file__).resolve().parent / "app.ico"
size = 256
img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
px = img.load()
for y in range(size):
    for x in range(size):
        a = max(0, min(1, (x + y) / (2 * size)))
        px[x, y] = (int(13 + 25 * a), int(50 + 77 * a), int(113 + 123 * a), 255)
d = ImageDraw.Draw(img)
d.rounded_rectangle((7, 7, 249, 249), 48, outline=(135, 221, 255, 245), width=8)
d.rounded_rectangle((48, 173, 208, 211), 13, fill=(194, 235, 252))
d.rounded_rectangle((73, 190, 183, 195), 2, fill=(23, 102, 176))
d.line((128, 54, 128, 148), fill=(255, 255, 255), width=28)
d.polygon([(78, 122), (128, 174), (178, 122)], fill=(255, 255, 255))
d.rounded_rectangle((78, 218, 178, 226), 3, fill=(91, 206, 248))
img.save(out, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                   (64, 64), (128, 128), (256, 256)])
print(out)
