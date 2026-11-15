import unittest
from pathlib import Path
from unittest.mock import patch
from karaoke.branding import asset, background_path, wall_clock, song_details
from karaoke.stage import StageCanvas


class BrandingTests(unittest.TestCase):
    def test_custom_saved_path_is_ignored(self):
        self.assertEqual(background_path({'background_image': '/arbitrary.jpg'}), asset('xstage-background.jpg'))
        self.assertIsNone(background_path({'background_mode': 'none', 'background_image': '/arbitrary.jpg'}))
        self.assertEqual(background_path({'background_mode': '/arbitrary.jpg'}), asset('xstage-background.jpg'))

    def test_artwork_is_packaged(self):
        from PIL import Image
        for name in ('xstage-logo.jpg', 'xstage-background.jpg'):
            with Image.open(asset(name)) as image:
                image.verify()

    def test_clock_uses_computer_time(self):
        with patch('karaoke.branding.time.strftime', return_value='07:45:12') as fmt:
            self.assertEqual(wall_clock(), '07:45:12')
            fmt.assert_called_once_with('%H:%M:%S')

    def test_song_details_include_available_values(self):
        title, artist, details = song_details(dict(title='เพลงทดสอบ', artist='ศิลปิน', code='T0026', format='EMK', key_signature='C', rhythm='รำวง'), 245, -2)
        self.assertEqual((title, artist), ('เพลงทดสอบ', 'ศิลปิน'))
        for value in ('EMK', 'C', 'รำวง', '-2'):
            self.assertIn(value, details)
        self.assertNotIn('T0026', details)
        self.assertNotIn('ความยาว', details)
        self.assertNotIn('4:05', details)
        self.assertNotIn('None', song_details({'title': 'เพลง'})[2])

    def test_render_background_cannot_open_custom_path(self):
        from types import SimpleNamespace
        canvas = SimpleNamespace(_background_cache=None)
        image = StageCanvas.background(canvas, 320, 180, '#090d1f', {'background_image': '/not-found.jpg'})
        self.assertEqual(image.size, (320, 180))
        self.assertEqual(canvas._background_cache[0][3], str(asset('xstage-background.jpg')))

    def test_menu_has_only_two_background_choices(self):
        from test_context_menu import ContextMenuTests, Menu
        from karaoke.context_menu import populate_context_menu
        app, menu = ContextMenuTests().app(), Menu()
        populate_context_menu(app, menu, Menu, [])
        choices = menu.find('พื้นหลัง')['menu'].entries
        self.assertEqual([entry['label'] for entry in choices], ['ใช้ภาพเวที X-STAGE', 'ไม่มีรูปพื้นหลัง'])
        choices[0]['command'](); app.choose_background.assert_called_once()
        choices[1]['command'](); app.clear_background.assert_called_once()

    def test_lyrics_larger_and_one_line_higher(self):
        from karaoke.stage_layout import lyric_font_size, lyric_top
        self.assertEqual(lyric_font_size(84, 1920, 1080), 84)
        self.assertEqual(lyric_font_size(84, 1280, 720), 56)
        original = 1080 - 150 - 24
        self.assertEqual(lyric_top(1080, 150, 84, 24, 174, 24), original - 108)
        self.assertGreaterEqual(lyric_top(500, 150, 84, 24, 300, 24), 300)

    def test_frozen_assets_fall_back_to_bundle(self):
        import tempfile
        import sys
        with tempfile.TemporaryDirectory() as temp:
            # Windows may return an 8.3 TEMP alias; asset() resolves the EXE path.
            # Normalize the fixture too, so both spellings identify the same file.
            root = Path(temp).resolve()
            bundle = root/'_internal'
            (bundle/'assets').mkdir(parents=True)
            (bundle/'assets/xstage.ico').write_bytes(b'icon')
            with patch.object(sys, 'frozen', True, create=True), patch.object(sys, '_MEIPASS', str(bundle), create=True), patch.object(sys, 'executable', str(root/'app.exe')):
                self.assertEqual(asset('xstage.ico'), bundle/'assets/xstage.ico')
                (root/'assets').mkdir()
                (root/'assets/xstage.ico').write_bytes(b'external')
                self.assertEqual(asset('xstage.ico'), root/'assets/xstage.ico')

    def test_windows_sets_current_and_default_icon(self):
        from unittest.mock import MagicMock
        from karaoke.branding import install_window_icon
        import ctypes
        window = MagicMock()
        path = Path('/logo.ico')
        with patch('os.name', 'nt'), patch.object(ctypes, 'windll', MagicMock(), create=True), patch('karaoke.branding.asset', return_value=path):
            install_window_icon(window)
        window.iconbitmap.assert_called_once_with(bitmap=str(path), default=str(path))
        window.iconphoto.assert_not_called()

    def test_bitmap_failure_uses_retained_photo_fallback(self):
        from unittest.mock import MagicMock
        from tkinter import TclError
        from karaoke.branding import install_window_icon
        import ctypes
        window = MagicMock()
        window.iconbitmap.side_effect = TclError('unsupported bitmap')
        logo = asset('xstage-logo.jpg')
        with patch('os.name', 'nt'), patch.object(ctypes, 'windll', MagicMock(), create=True), patch('karaoke.branding.asset', return_value=logo), patch('PIL.ImageTk.PhotoImage', side_effect=lambda *a, **kw: object()), patch('logging.exception'):
            install_window_icon(window)
        self.assertEqual(len(window._brand_icons), 5)
        window.iconphoto.assert_called_once_with(True, *window._brand_icons)

    def test_ico_frames_are_visible_windows_bitmaps(self):
        import struct
        from PIL import Image, ImageStat
        path = asset('xstage.ico')
        raw = path.read_bytes()
        self.assertEqual(struct.unpack_from('<HHH', raw), (0, 1, 7))
        with Image.open(path) as icon:
            for i in range(7):
                w,h,_,_,_,bits,length,offset = struct.unpack_from('<BBBBHHII', raw, 6+i*16)
                self.assertEqual(bits, 32)
                self.assertLessEqual(offset+length, len(raw))
                self.assertEqual(struct.unpack_from('<I', raw, offset)[0], 40)
                frame = icon.ico.getimage((w or 256, h or 256)).convert('RGBA')
                self.assertEqual(frame.getchannel('A').getextrema(), (255,255))
                self.assertGreater(max(ImageStat.Stat(frame.convert('RGB')).stddev), 20)
