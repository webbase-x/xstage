"""Windows Thai glyph placement and native resource lifetime regression tests."""
import ctypes as c
import os
import unittest
from karaoke.typography import ThaiFont, shape, measure, draw_text


@unittest.skipUnless(os.name == 'nt', 'Windows Uniscribe text engine')
class ThaiTypographyTests(unittest.TestCase):
    def test_upper_and_lower_marks_have_room(self):
        for size in (24, 64, 110):
            base = shape('ก', size)
            upper = shape('กิ้', size)
            lower = shape('กุ', size)
            self.assertLess(upper.mask.getbbox()[1], base.mask.getbbox()[1])
            self.assertGreater(lower.mask.getbbox()[3], base.mask.getbbox()[3])
            for run in (base, upper, lower, shape('ปี่ กุ้ง น้ำ ผู้หญิงขึ้นเวที', size)):
                left, top, right, bottom = run.mask.getbbox()
                self.assertGreater(min(left, top), 0)
                self.assertLess(right, run.mask.width)
                self.assertLess(bottom, run.mask.height)

    def test_combining_marks_share_the_base_advance(self):
        for text in ('กิ้', 'ปี่', 'ญุ', 'ชั้น'):
            run = shape(text, 64)
            self.assertEqual(len(run.boundaries), len(text)+1)
            self.assertEqual(run.boundaries[-1], run.width)
            self.assertEqual(list(run.boundaries), sorted(run.boundaries))
            self.assertEqual(measure(text, 64).width, run.width)
        self.assertEqual(measure('ก', 64).width, measure('กิ้', 64).width)

    def test_colored_masks_keep_identical_mark_positions(self):
        from PIL import Image, ImageChops
        font = ThaiFont(64)
        first, second = (Image.new('RGB', (750, 180)) for _ in range(2))
        bounds = draw_text(first, (20, 20), 'น้ำ ปี่ กุ้ง', font, '#ffffff', stroke_width=2)
        other = draw_text(second, (20, 20), 'น้ำ ปี่ กุ้ง', font, '#ffff00', stroke_width=2)
        self.assertEqual(bounds, other)
        self.assertIsNone(ImageChops.difference(first.getchannel('R'), second.getchannel('R')).getbbox())
        self.assertIsNotNone(ImageChops.difference(first, second).getbbox())

    def test_shaping_releases_gdi_handles(self):
        user = c.WinDLL('user32')
        user.GetGuiResources.argtypes = [c.c_void_p, c.c_uint]
        user.GetGuiResources.restype = c.c_uint
        process = c.c_void_p(-1)
        shape('อุ่นเครื่อง', 36)
        before = user.GetGuiResources(process, 0)
        for index in range(30):
            shape(f'ปี่ กุ้ง น้ำ ทดสอบ {index}', 36)
        after = user.GetGuiResources(process, 0)
        self.assertLessEqual(after-before, 1, 'Native font or bitmap handles leaked')


if __name__ == '__main__':
    unittest.main()
