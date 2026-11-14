"""Whole-line text rasterization, cropped color wipe and monitor enumeration."""
from __future__ import annotations
import os
from pathlib import Path
from .ui import LyricsCanvas
from .typography import ThaiFont, draw_text
from . import __version__
from .branding import asset, background_path, wall_clock
from .stage_layout import lyric_font_size, lyric_top


def monitors():
    if os.name != 'nt':
        return []
    import ctypes
    from ctypes import wintypes as w
    result = []
    callback_type = ctypes.WINFUNCTYPE(w.BOOL, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(w.RECT), ctypes.c_ssize_t)
    def collect(monitor, dc, rect, data):
        r = rect.contents
        result.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
        return True
    callback = callback_type(collect)
    dll = ctypes.WinDLL('user32')
    dll.EnumDisplayMonitors.argtypes = [ctypes.c_void_p, ctypes.c_void_p, callback_type, ctypes.c_ssize_t]
    dll.EnumDisplayMonitors(None, None, callback, 0)
    return result


def lyric_progress(lyrics, position, offset=0):
    current, following, prefix = lyrics.at(position, offset)
    if not current or not current.words:
        return current, following, prefix, '', 0.0
    at = position + (lyrics.offset_ms + offset) / 1000
    active = -1
    for index, (when, text) in enumerate(current.words):
        if when <= at:
            active = index
        else:
            break
    if active < 0:
        return current, following, '', '', 0.0
    before = ''.join(text for _, text in current.words[:active])
    start, word = current.words[active]
    end = current.words[active + 1][0] if active + 1 < len(current.words) else start + .15
    fraction = max(0., min(1., (at - start) / max(.001, end - start)))
    return current, following, before, word, fraction


class StageCanvas(LyricsCanvas):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.progress_word, self.progress_fraction = '', 0.
        self.preferences = {}
        self._cache = None
        self._images = []
        self.telemetry = {}
        self._background_cache = None
        self._paint_key = None
        self._hud_fonts = {}
        self._logo_cache = None
        self._lyric_bounds = (0, 0, 0, 0)
        self._line_boxes = ()

    def show_frame(self, current, upcoming, prefix='', title='', word='', fraction=0., preferences=None):
        self.state = current, upcoming, prefix, title
        self.progress_word, self.progress_fraction = word, fraction
        self.preferences = preferences or {}
        self.redraw()

    def redraw(self):
        try:
            from PIL import ImageTk
        except ImportError:
            return super().redraw()
        width, height = self.winfo_width(), self.winfo_height()
        if width < 10 or height < 10:
            return
        current, upcoming, prefix, title = self.state
        prefs = self.preferences
        bg, normal, active = prefs.get('stage_bg', '#090d1f'), prefs.get('lyric_color', '#ffffff'), prefs.get('active_color', '#ffe079')
        idle = self.telemetry.get('idle', False)
        reserved_top = max(132 if height < 650 else 174, int(self.telemetry.get('reserved_top', 132 if height < 650 else 174)))
        reserved_bottom = max(16, int(self.telemetry.get('reserved_bottom', 96)))
        key = width, height, current, upcoming, title, bg, normal, active, prefs.get('font_size', 84), str(background_path(prefs) or ''), prefs.get('background_dim', .25), idle, reserved_top, reserved_bottom
        paint_key = key, prefix, self.progress_word, round(self.progress_fraction, 3), tuple(sorted(self.telemetry.items())), wall_clock()
        if self._paint_key == paint_key:
            return
        if not self._cache or self._cache[0] != key:
            size = lyric_font_size(prefs.get('font_size', 84), width, height)
            available_height = max(40, height-reserved_top-reserved_bottom)
            while True:
                font = ThaiFont(size)
                small = ThaiFont(max(14, size // 2))
                run = font.shape(current)
                hint = self.fit_text(upcoming, small, width-70)
                next_run = small.shape(hint)
                gap = max(12, round(size*.3))
                band_height = run.height+gap+next_run.height
                if size <= 14 or (font.getlength(current) <= width-60 and band_height <= available_height):
                    break
                size -= 1
            background = self.background(width, height, bg, prefs)
            left = max(24, (width - font.getlength(current)) // 2)
            top = lyric_top(height, band_height, run.height, gap, reserved_top, reserved_bottom, idle)
            normal_image = background.copy()
            stroke = max(1, size//40)
            self._lyric_bounds = draw_text(normal_image, (left, top), current, font, normal,
                stroke_width=stroke)
            next_bounds = draw_text(normal_image, (width//2, top+run.height+gap), hint, small,
                '#c1d9f1', stroke_width=1, anchor='mt')
            self._line_boxes = self._lyric_bounds, next_bounds
            overlay = normal_image.copy()
            draw_text(overlay, (left, top), current, font, active, stroke_width=stroke)
            self._cache = key, normal_image, overlay, left, top, font, size
        _, base, overlay, left, top, font, size = self._cache
        result = base.copy()
        if prefix or self.progress_word:
            run = font.shape(current)
            start = min(len(prefix), len(run.boundaries)-1)
            extent = run.boundaries[start]
            if self.progress_word:
                end = min(len(prefix+self.progress_word), len(run.boundaries)-1)
                extent += (run.boundaries[end]-extent)*self.progress_fraction
            right = int(min(width, left + extent + (3 if prefix and not self.progress_word else 0)))
            if extent >= run.width:
                right = min(width, max(right, self._lyric_bounds[2]))
            box = (max(0, self._lyric_bounds[0]), max(0, self._lyric_bounds[1]), right,
                   min(height, self._lyric_bounds[3]))
            # A wipe may still be in leading whitespace, before any ink.
            if box[2] > box[0] and box[3] > box[1]:
                result.paste(overlay.crop(box), box[:2])
        self.draw_hud(result, title)
        from .remote_ui import draw_invite
        draw_invite(result, self.telemetry.get("remote_invite"))
        photo = ImageTk.PhotoImage(result, master=self)
        self._images = [photo]
        self.delete('all')
        self.create_image(0, 0, image=photo, anchor='nw')
        self._paint_key = paint_key

    @staticmethod
    def fit_text(text, font, width):
        if font.getlength(text) <= width:
            return text
        while text and font.getlength(text+'…') > width:
            text = text[:-1]
        return text+'…'

    def background(self, width, height, color, prefs):
        """Cache the photograph independently of the changing lyric lines."""
        from PIL import Image, ImageDraw, ImageOps, ImageFilter, ImageEnhance
        imagefile = str(background_path(prefs) or '')
        dim = max(0., min(.8, float(prefs.get('background_dim', .25))))
        key = width, height, color, imagefile, dim
        if self._background_cache and self._background_cache[0] == key:
            return self._background_cache[1].copy()
        image = None
        if imagefile:
            try:
                with Image.open(imagefile) as source:
                    image = ImageOps.fit(ImageOps.exif_transpose(source).convert('RGB'), (width, height))
                image = ImageEnhance.Brightness(image).enhance(1-dim)
            except (OSError, ValueError):
                pass
        if image is None:
            from PIL import ImageColor
            rgb = ImageColor.getrgb(color)
            image = Image.new('RGB', (width, height))
            draw = ImageDraw.Draw(image)
            for y in range(height):
                ratio = y/max(1, height-1)
                draw.line((0, y, width, y), fill=tuple(min(255, int(v*(.55+.5*ratio)+n*ratio)) for v, n in zip(rgb, (12, 5, 25))))
            glow = Image.new('RGBA', (max(1, width//4), max(1, height//4)))
            light = ImageDraw.Draw(glow)
            w, h = glow.size
            light.ellipse((-w*.2, -h*.7, w*.55, h*.4), fill=(64, 98, 225, 75))
            light.ellipse((w*.55, h*.2, w*1.3, h*1.5), fill=(134, 63, 214, 65))
            glow = glow.filter(ImageFilter.GaussianBlur(max(8, w//8))).resize((width, height))
            image = Image.alpha_composite(image.convert('RGBA'), glow).convert('RGB')
            draw = ImageDraw.Draw(image)
            for index in range(36):
                x, y = (index*367+71) % width, (index*191+53) % height
                radius = 1 if index % 4 else 2
                draw.ellipse((x, y, x+radius, y+radius), fill='#404964')
        scrim = Image.new('RGBA', (width, height))
        draw = ImageDraw.Draw(scrim)
        for y in range(height):
            strength = int(110*max(0, (y/height-.48)/.52))
            draw.line((0, y, width, y), fill=(3, 8, 20, strength))
        image = Image.alpha_composite(image.convert('RGBA'), scrim).convert('RGB')
        self._background_cache = key, image
        return image.copy()

    def draw_hud(self, image, title):
        from PIL import ImageDraw
        draw = ImageDraw.Draw(image)
        width, height = image.size
        data = self.telemetry
        def cached_font(size, family='Leelawadee UI'):
            key = family, size
            if key not in self._hud_fonts:
                self._hud_fonts[key] = ThaiFont(size, family)
            return self._hud_fonts[key]
        small, label, brand = (cached_font(size) for size in (13, 16, 19))
        from PIL import Image, ImageOps
        logo_size = 70 if width >= 1000 else 58
        if self._logo_cache is None or self._logo_cache[0] != logo_size:
            try:
                with Image.open(asset('xstage-logo.jpg')) as source:
                    logo = ImageOps.contain(source.convert('RGB'), (logo_size, logo_size), Image.Resampling.LANCZOS)
                self._logo_cache = logo_size, logo
            except (OSError, ValueError):
                self._logo_cache = logo_size, None
        if self._logo_cache[1] is not None:
            image.paste(self._logo_cache[1], (24, 16))
        brand_x = 24 + logo_size + 12
        draw_text(image, (brand_x, 23), 'X-STAGE', brand, '#f0f5ff', stroke_width=1)
        draw_text(image, (brand_x, 50), f'KARAOKE  v{__version__}', small, '#9facce')
        song_title_font, song_info_font = cached_font(20), cached_font(16)
        info_width = max(80, width-390)
        draw_text(image, (24, 87), self.fit_text(data.get('song_title') or title, song_title_font, info_width), song_title_font, '#f0f5ff', stroke_width=1)
        if height < 650:
            details = '  ·  '.join(value for value in (data.get('song_artist', ''), data.get('song_details', '')) if value)
            draw_text(image, (24, 119), self.fit_text(details, song_info_font, width-48), song_info_font, '#c5d3eb', stroke_width=1)
        else:
            draw_text(image, (24, 119), self.fit_text(data.get('song_artist', ''), song_info_font, info_width), song_info_font, '#c5d3eb', stroke_width=1)
            draw_text(image, (24, 147), self.fit_text(data.get('song_details', ''), song_info_font, width-48), song_info_font, '#9eacc7', stroke_width=1)
        left = width-342
        draw.rounded_rectangle((left, 20, width-24, 98), radius=14, fill='#10192d', outline='#33445f', width=1)
        clock = data.get('clock') or wall_clock()
        digital = cached_font(26, 'Consolas')
        draw_text(image, (left+16, 29), clock, digital, '#74f0ed')
        draw_text(image, (left+17, 69), data.get('status', 'พร้อมเล่น'), small, '#a1afc9')
        draw.line((left+163, 35, left+163, 82), fill='#33445f')
        bpm = data.get('bpm', '—')
        draw_text(image, (left+180, 25), f'{bpm} BPM', label, '#ffe079')
        beat, beats = int(data.get('beat', 0)), int(data.get('beats', 4))
        draw_text(image, (left+180, 51), f"ห้อง {data.get('bar', '—')}  ·  {beat or '—'}/{beats}", small, '#c5d3eb')
        for index in range(min(beats, 12)):
            x = left+181+index*15
            draw.rounded_rectangle((x, 80, x+9, 84), radius=2, fill='#74f0ed' if index+1 == beat else '#35445f')
        duration = max(.01, float(data.get('duration', 0)))
        progress = min(1, max(0, data.get('seconds', 0)/duration))
        if progress:
            draw.rectangle((0, height-3, int(width*progress), height), fill='#62dce8')
