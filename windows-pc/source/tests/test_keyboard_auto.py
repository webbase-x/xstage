import unittest
from karaoke.midi_keyboard import display_key_count

class AutoKeyboardTests(unittest.TestCase):
    def test_small_and_large_available_space(self):
        self.assertEqual(display_key_count(650),61)
        self.assertEqual(display_key_count(1200),128)
    def test_dpi_keeps_keys_readable(self):
        self.assertEqual(display_key_count(1200,scale=1.5),61)
        self.assertEqual(display_key_count(1800,scale=1.5),128)
    def test_manual_override_and_return_to_auto(self):
        self.assertEqual(display_key_count(650,'128'),128)
        self.assertEqual(display_key_count(1800,'61'),61)
        self.assertEqual(display_key_count(650,'auto'),61)
