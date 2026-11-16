"""Karaoke PC queue memory regression (works without a Windows audio device)."""
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from karaoke.queue_warm import (
    QueueWarmup, MiB, MAX_HEADER, MAX_HELD, MAX_ITEMS, memory_level, physical_memory,
)


class LocalQueueWarmupTests(unittest.TestCase):
    def test_bounded_headers_all_local_media_types(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sources = []
            for i, suffix in enumerate((".xsk", ".mid", ".mp3", ".mp4",
                                        ".m4a", ".mkv", ".flac", ".wav")):
                target = root / (str(i) + suffix)
                target.write_bytes(b"A" * (MAX_HEADER + 300))
                sources.append(target)
            manager = QueueWarmup()
            try:
                with patch("karaoke.queue_warm.physical_memory", return_value={
                    "total": 8 * 1024 * MiB, "available": 4 * 1024 * MiB,
                    "used_percent": 50,
                }):
                    manager.request(sources)
                    deadline = time.monotonic() + 3
                    while manager.snapshot()["count"] < MAX_ITEMS and time.monotonic() < deadline:
                        time.sleep(.01)
                    state = manager.snapshot()
                    self.assertEqual(state["count"], MAX_ITEMS)
                    self.assertEqual(state["bytes"], MAX_ITEMS * MAX_HEADER,
                                     "Only two bounded headers may be retained")
                    self.assertLessEqual(state["bytes"], MAX_HELD)
                    self.assertEqual(state["level"], "low")
                    # A queue reorder releases stale items rather than
                    # pinning every song opened during the session.
                    manager.request(sources[4:6])
                    deadline = time.monotonic() + 3
                    while manager.snapshot()["count"] != 2 and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertEqual(manager.snapshot()["count"], 2)
            finally:
                manager.close()
            self.assertEqual(manager.snapshot()["count"], 0)

    def test_high_pressure_never_warms_large_files(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "video.mp4"
            source.write_bytes(b"v" * (MAX_HEADER + 1))
            manager = QueueWarmup()
            try:
                with patch("karaoke.queue_warm.physical_memory", return_value={
                    "total": 2 * 1024 * MiB, "available": 200 * MiB,
                    "used_percent": 91,
                }):
                    manager.request([source])
                    manager._future.result(timeout=3)
                    self.assertEqual(manager.snapshot()["count"], 0)
            finally:
                manager.close()

    def test_ram_color_thresholds_are_actual_windows_metrics(self):
        self.assertEqual(memory_level(None), "unknown")
        self.assertEqual(memory_level({"total": 8 * 1024 * MiB,
                                       "available": 4 * 1024 * MiB}), "low")
        self.assertEqual(memory_level({"total": 8 * 1024 * MiB,
                                       "available": 2 * 1024 * MiB}), "medium")
        self.assertEqual(memory_level({"total": 8 * 1024 * MiB,
                                       "available": 300 * MiB}), "high")
        if sys.platform != "win32":
            self.assertIsNone(physical_memory())


if __name__ == "__main__":
    unittest.main()
