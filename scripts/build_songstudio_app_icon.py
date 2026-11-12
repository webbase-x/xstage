#!/usr/bin/env python3
"""Render native Windows PNG/ICO for X-Stage Song Studio PC.

Build-only dependency: Pillow. The user's PC Ready ZIP receives the final
raster assets and never installs Pillow or executes this graphics build.
Visual identity matches studio/app-icon.svg (X, headset, mic, equalizer, PC).
"""
from __future__ import annotations

import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont


def generate(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    size = 768
    unit = size / 512

    def scale(points):
        return [(int(x * unit), int(y * unit)) for x, y in points]

    base = Image.new("RGBA", (size, size))
    draw = ImageDraw.Draw(base)
    for y in range(size):
        t = y / size
        col = (int(9 + 10*t), int(20 + 3*t), int(46 + 12*t), 255)
        draw.line((0, y, size, y), fill=col)
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((8,8,size-9,size-9), radius=int(109*unit), fill=255)
    base.putalpha(mask)

    bloom = Image.new("RGBA", (size,size))
    d = ImageDraw.Draw(bloom)
    d.ellipse((int(60*unit),int(32*unit),int(450*unit),int(430*unit)),
              fill=(44,110,255,74))
    d.ellipse((int(270*unit),int(30*unit),int(530*unit),int(322*unit)),
              fill=(220,54,250,60))
    bloom = bloom.filter(ImageFilter.GaussianBlur(48*unit))
    base = Image.alpha_composite(base,bloom)

    layer=Image.new("RGBA",(size,size))
    d=ImageDraw.Draw(layer)
    # Headphone bridge and monitor earcups.
    for color,width,offset in [((12,42,111,255),37,0),((73,151,255,255),11,5),
                               ((166,230,255,200),3,13)]:
        box = tuple(int(z*unit) for z in (107+offset,68+offset,414-offset,347-offset))
        d.arc(box,188,352, fill=color,width=max(1,int(width*unit)))
    d.rounded_rectangle(tuple(int(n*unit) for n in (96,202,151,315)),
                        radius=20*unit,fill="#0b2853",outline="#7ae5fb",width=7*unit)
    d.rounded_rectangle(tuple(int(n*unit) for n in (373,202,427,315)),
                        radius=20*unit,fill="#231452",outline="#bc7aff",width=7*unit)

    # Colorful studio equalizer behind the X.
    heights=[18,39,73,100,55,82,48,91,104,72,44,96,60,37,18]
    for i,h in enumerate(heights):
        x=(67+i*26)*unit; y=215*unit
        d.rounded_rectangle((x,y-h/2*unit,x+12*unit,y+h/2*unit),
                  radius=6*unit,fill=(39+int(i*8),138,int(253-i*2),135))
    base = Image.alpha_composite(base,layer)

    # Soft shadow and metallic X, same geometry as SVG.
    xpoints = scale([(131,141),(203,141),(260,211),(314,141),(390,141),
                     (299,251),(390,371),(315,371),(258,295),(196,371),
                     (117,371),(215,251)])
    shadow=Image.new("RGBA",(size,size))
    ImageDraw.Draw(shadow).polygon([(x+8*unit,y+10*unit) for x,y in xpoints],
                                   fill=(3,1,24,255))
    base=Image.alpha_composite(base,shadow.filter(ImageFilter.GaussianBlur(10*unit)))
    xmask=Image.new("L",(size,size),0)
    ImageDraw.Draw(xmask).polygon(xpoints,fill=255)
    alloy=Image.new("RGBA",(size,size))
    ad=ImageDraw.Draw(alloy)
    for y in range(size):
        t=y/size
        r=int(63+(167*t if t<.5 else 149*(1-t)))
        g=int(161+72*(1-abs(2*t-1)))
        b=int(255-40*t)
        ad.line((0,y,size,y),fill=(r,g,b,255))
    alloy.putalpha(xmask)
    base=Image.alpha_composite(base,alloy)
    d=ImageDraw.Draw(base)
    d.line(xpoints+[xpoints[0]],fill=(236,252,255,230),width=4*unit,joint="curve")
    d.line(scale([(151,154),(197,154),(260,235),(316,154),(364,154)]),
           fill=(235,251,255,180),width=6*unit,joint="curve")

    # Chrome studio microphone at top right, partly overlapping headset.
    d.rounded_rectangle(tuple(int(z*unit) for z in (310,183,372,292)),
                        radius=25*unit,fill="#dce7fc",outline="#92ccff",width=6*unit)
    for yy in (212,232,252,272):
        d.line((319*unit,yy*unit,365*unit,yy*unit),fill="#142a62",width=8*unit)
    d.arc(tuple(int(z*unit) for z in (302,233,380,317)),0,180,fill="#ccedff",width=7*unit)
    d.line((341*unit,317*unit,341*unit,334*unit),fill="#cceaff",width=9*unit)
    d.line((320*unit,335*unit,364*unit,335*unit),fill="#cceaff",width=9*unit)

    # Audio waveform below the X.
    for i,h in enumerate((12,23,36,19,44,56,31,20,45,62,36,25,14,39,28,15)):
        xx=(93+i*17)*unit; cy=420*unit
        d.line((xx,cy-h/2*unit,xx,cy+h/2*unit),
               fill="#41e9fd",width=5*unit)

    # PC badge; legible at 64px.
    rect=(355*unit,399*unit,474*unit,473*unit)
    d.rounded_rectangle(rect,radius=22*unit,fill="#1866c3",
                        outline="#b4f4ff",width=5*unit)
    fonts=[r"C:\Windows\Fonts\arialbd.ttf",r"/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
    font=next((ImageFont.truetype(path,int(47*unit)) for path in fonts if Path(path).is_file()),
              ImageFont.load_default())
    d.text((414*unit,436*unit),"PC",fill="white",font=font,anchor="mm",
           stroke_width=1*unit,stroke_fill="#3265cf")
    d.rounded_rectangle((5,5,size-6,size-6),radius=109*unit,
                        outline="#50d7ff",width=8*unit)
    d.rounded_rectangle((14,14,size-15,size-15),radius=103*unit,
                        outline=(212,127,255,180),width=2*unit)
    base.putalpha(mask)

    png=output/"app-icon-512.png"
    base.resize((512,512),Image.Resampling.LANCZOS).save(png,optimize=True)
    icon=output/"app-icon.ico"
    base.save(icon,format="ICO",sizes=[(16,16),(24,24),(32,32),(48,48),
                                      (64,64),(96,96),(128,128),(256,256)])
    assert png.stat().st_size>10000
    assert icon.stat().st_size>10000
    print("App art ready:",png, png.stat().st_size,"bytes", icon,icon.stat().st_size,"bytes")


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("output",type=Path)
    generate(parser.parse_args().output)
