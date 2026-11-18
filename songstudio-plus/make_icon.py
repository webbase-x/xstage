"""Create a multi-resolution Windows icon for Studio Plus (build-time only).

Pillow is needed only in GitHub Actions; end users do not install it.
"""
from pathlib import Path
from PIL import Image, ImageDraw

SIZE=512
im=Image.new("RGBA",(SIZE,SIZE),(9,17,36,255))
pixels=im.load()
for y in range(SIZE):
    for x in range(SIZE):
        blend=(x+y)/(2*SIZE)
        glow=max(0,1-((x-355)**2+(y-134)**2)**.5/370)
        pixels[x,y]=(int(13+43*blend+25*glow),
                     int(29+22*blend+40*glow),
                     int(58+54*blend+63*glow),255)
d=ImageDraw.Draw(im)
d.rounded_rectangle((11,11,501,501),radius=116,outline=(121,206,240),width=10)
d.ellipse((86,86,426,426),fill=(11,22,46),outline=(92,154,199),width=6)
for radius in (145,125,104):
    d.ellipse((256-radius,256-radius,256+radius,256+radius),
              outline=(42+radius//6,83+radius//3,126+radius//3),width=3)
# Thick geometric X, deliberately drawn without relying on installed fonts.
d.polygon([(145,138),(203,138),(256,210),(309,138),(368,138),
           (289,256),(372,374),(312,374),(256,300),(200,374),
           (140,374),(222,256)],fill=(128,240,234))
d.line((376,78,376,135),fill=(145,241,225),width=13)
d.line((348,106,404,106),fill=(145,241,225),width=13)
d.ellipse((243,243,269,269),fill=(10,33,62),outline=(233,255,253),width=4)
out=Path(__file__).resolve().parent/"app-plus.ico"
im.save(out,format="ICO",sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
print(out)
