"""Whole-line Thai shaping with Windows Uniscribe and GDI raster masks.

No optional shaping DLLs or third-party fonts are required on Windows.
The returned caret positions belong to the full shaped line, including Thai
combining marks; lyric wiping must not measure separately shaped prefixes.
"""
from __future__ import annotations

import ctypes as c
from ctypes import wintypes as w
from dataclasses import dataclass
from functools import lru_cache
import os


@dataclass(frozen=True)
class TextRun:
    width: int
    height: int
    boundaries: tuple[int, ...]
    mask: object = None
    padding: int = 0


class BitmapInfo(c.Structure):
    _fields_ = [('size', w.DWORD), ('width', w.LONG), ('height', w.LONG),
                ('planes', w.WORD), ('bit_count', w.WORD), ('compression', w.DWORD),
                ('image_size', w.DWORD), ('xppm', w.LONG), ('yppm', w.LONG),
                ('colors_used', w.DWORD), ('colors_important', w.DWORD)]


@lru_cache(maxsize=1)
def _api():
    if os.name != 'nt':
        raise OSError('Windows text shaping is required')
    gdi = c.WinDLL('gdi32', use_last_error=True)
    usp = c.WinDLL('usp10', use_last_error=True)
    pointer = c.c_void_p
    signatures = [
        (gdi.CreateCompatibleDC, [pointer], pointer),
        (gdi.DeleteDC, [pointer], w.BOOL),
        (gdi.CreateFontW, [c.c_int]*5+[w.DWORD]*8+[w.LPCWSTR], pointer),
        (gdi.SelectObject, [pointer, pointer], pointer),
        (gdi.DeleteObject, [pointer], w.BOOL),
        (gdi.SetTextColor, [pointer, w.DWORD], w.DWORD),
        (gdi.SetBkColor, [pointer, w.DWORD], w.DWORD),
        (gdi.SetBkMode, [pointer, c.c_int], c.c_int),
        (gdi.CreateDIBSection, [pointer, c.POINTER(BitmapInfo), w.UINT, c.POINTER(pointer), pointer, w.DWORD], pointer),
        (gdi.GdiFlush, [], w.BOOL),
        (usp.ScriptStringAnalyse, [pointer, pointer, c.c_int, c.c_int, c.c_int, w.DWORD, c.c_int,
                                   pointer, pointer, pointer, pointer, pointer, c.POINTER(pointer)], c.c_long),
        (usp.ScriptString_pSize, [pointer], c.POINTER(w.SIZE)),
        (usp.ScriptStringCPtoX, [pointer, c.c_int, w.BOOL, c.POINTER(c.c_int)], c.c_long),
        (usp.ScriptStringOut, [pointer, c.c_int, c.c_int, w.UINT, pointer, c.c_int, c.c_int, w.BOOL], c.c_long),
        (usp.ScriptStringFree, [c.POINTER(pointer)], c.c_long),
    ]
    for function, arguments, result in signatures:
        function.argtypes, function.restype = arguments, result
    return gdi, usp


def _success(result, action):
    if result != 0:
        raise OSError(f'{action}: HRESULT 0x{result & 0xffffffff:08X}')


def _analyse(text, size, family, bold, rasterize):
    from PIL import Image
    if not text:
        return TextRun(0, max(1, size), (0,), Image.new('L', (1, max(1, size))) if rasterize else None)
    gdi, usp = _api()
    dc = font = bitmap = old_font = old_bitmap = None
    analysis = c.c_void_p()
    try:
        dc = gdi.CreateCompatibleDC(None)
        font = gdi.CreateFontW(-size, 0, 0, 0, 700 if bold else 400,
                              0, 0, 0, 1, 4, 0, 4, 0, family)
        if not dc or not font:
            raise c.WinError(c.get_last_error())
        old_font = gdi.SelectObject(dc, font)
        buffer = c.create_unicode_buffer(text)
        units = len(text.encode('utf-16-le'))//2
        # SSA_GLYPHS | SSA_FALLBACK. Analyse the full UTF-16 string once.
        _success(usp.ScriptStringAnalyse(dc, buffer, units, units*3//2+16, -1, 0x80|0x20,
            0, None, None, None, None, None, c.byref(analysis)), 'ScriptStringAnalyse')
        dimensions = usp.ScriptString_pSize(analysis)
        if not dimensions:
            raise OSError('Uniscribe returned no text dimensions')
        width, height = dimensions.contents.cx, dimensions.contents.cy
        positions, offset = [], 0
        for character in text:
            x = c.c_int()
            _success(usp.ScriptStringCPtoX(analysis, offset, False, c.byref(x)), 'ScriptStringCPtoX')
            positions.append(x.value)
            offset += len(character.encode('utf-16-le'))//2
        positions.append(width)
        if not rasterize:
            return TextRun(width, height, tuple(positions))
        padding = max(8, size//3)
        image_width, image_height = max(1, width+padding*2), max(1, height+padding*2)
        info = BitmapInfo(c.sizeof(BitmapInfo), image_width, -image_height, 1, 32, 0,
                          image_width*image_height*4, 0, 0, 0, 0)
        pixels = c.c_void_p()
        bitmap = gdi.CreateDIBSection(dc, c.byref(info), 0, c.byref(pixels), None, 0)
        if not bitmap or not pixels:
            raise c.WinError(c.get_last_error())
        old_bitmap = gdi.SelectObject(dc, bitmap)
        c.memset(pixels, 0, info.image_size)
        gdi.SetTextColor(dc, 0xffffff)
        gdi.SetBkColor(dc, 0)
        gdi.SetBkMode(dc, 1)  # TRANSPARENT; grayscale antialiasing is in CreateFont.
        _success(usp.ScriptStringOut(analysis, padding, padding, 0, None, 0, 0, False), 'ScriptStringOut')
        gdi.GdiFlush()
        mask = Image.frombytes('RGB', (image_width, image_height),
            c.string_at(pixels, info.image_size), 'raw', 'BGRX').convert('L')
        return TextRun(width, height, tuple(positions), mask, padding)
    finally:
        if analysis:
            usp.ScriptStringFree(c.byref(analysis))
        if old_bitmap:
            gdi.SelectObject(dc, old_bitmap)
        if bitmap:
            gdi.DeleteObject(bitmap)
        if old_font:
            gdi.SelectObject(dc, old_font)
        if font:
            gdi.DeleteObject(font)
        if dc:
            gdi.DeleteDC(dc)


@lru_cache(maxsize=2048)
def measure(text, size, family='Leelawadee UI', bold=True):
    return _analyse(text, size, family, bold, False)


@lru_cache(maxsize=128)
def shape(text, size, family='Leelawadee UI', bold=True):
    return _analyse(text, size, family, bold, True)


@dataclass(frozen=True)
class ThaiFont:
    size: int
    family: str = 'Leelawadee UI'
    bold: bool = True

    def getlength(self, text):
        return measure(text, self.size, self.family, self.bold).width

    def shape(self, text):
        return shape(text, self.size, self.family, self.bold)


def draw_text(image, xy, text, font, fill, stroke_width=0, stroke_fill='black', anchor='lt'):
    """Draw the shaped mask and return its full ink bounds, including marks."""
    from PIL import ImageFilter
    run = font.shape(text)
    x, y = xy
    if anchor.startswith('m'):
        x -= run.width/2
    elif anchor.startswith('r'):
        x -= run.width
    origin = int(x)-run.padding, int(y)-run.padding
    if stroke_width:
        border = run.mask.filter(ImageFilter.MaxFilter(stroke_width*2+1))
        image.paste(stroke_fill, origin, border)
    image.paste(fill, origin, run.mask)
    ink = run.mask.getbbox()
    if ink:
        return (origin[0]+ink[0]-stroke_width, origin[1]+ink[1]-stroke_width,
                origin[0]+ink[2]+stroke_width, origin[1]+ink[3]+stroke_width)
    return int(x), int(y), int(x), int(y)+run.height
