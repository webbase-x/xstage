import unittest
import math
import time
from unittest.mock import patch
import numpy as np
from karaoke.eq_meter import WindowsMix,dbfs
class MeterTests(unittest.TestCase):
    def test_peak_accumulates_and_drain(self):
        m=WindowsMix();m.feed(np.array([[.5,-1.25],[.2,.1]]));m.feed(np.array([[.1,.1]]))
        self.assertEqual(m.read(),(.5,1.25));self.assertEqual(m.read(),(0,0))
        self.assertAlmostEqual(dbfs(.5),-6.0205999);self.assertGreater(dbfs(1.25),0)
        self.assertEqual(dbfs(0),-math.inf)
    def test_stale_read_not_false_live_level(self):
        m=WindowsMix();m.feed(np.ones((2,2)));m.stamp=time.monotonic()-1;self.assertIsNone(m.read())
    def test_reject_bad_samples(self):
        for frames in (np.zeros((1,1)),np.zeros((0,2)),np.array([[np.nan,0]])):
            with self.assertRaises(ValueError):WindowsMix().feed(frames)
    def test_non_windows_visible_error_and_cleanup(self):
        m=WindowsMix()
        with patch('os.name','posix'):m.run()
        self.assertIn('Windows',m.error);self.assertIsNone(m.read());m.stop();self.assertTrue(m.stop_event.is_set())
