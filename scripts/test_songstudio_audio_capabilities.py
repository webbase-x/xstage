"""Song Studio local hardware/SoundFont readiness: offline, no Drive credentials."""
from __future__ import annotations
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("songstudio_audio_engine",
    ROOT/"songstudio-pc"/"engine.py")
engine=importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)

MB=1024**2

class AudioCapabilitiesTests(unittest.TestCase):
    def test_memory_and_disk_risk(self):
        safe=engine.soundfont_pc_assessment(24*MB,4*1024**3,10*1024**3)
        self.assertEqual(safe["level"],"safe")
        self.assertEqual(safe["downloadBytes"],24*MB)
        self.assertGreater(safe["estimatedRamBytes"],safe["downloadBytes"])
        danger=engine.soundfont_pc_assessment(250*MB,300*MB,100*MB)
        self.assertEqual(danger["level"],"blocked")
        self.assertIn("RAM",danger["reason"])
        unknown=engine.soundfont_pc_assessment(24*MB,None,None)
        self.assertEqual(unknown["level"],"caution")
        low_disk=engine.soundfont_pc_assessment(24*MB,4*1024**3,10*MB)
        self.assertEqual(low_disk["level"],"caution")
        self.assertIn("พื้นที่",low_disk["reason"])
        self.assertEqual(engine.soundfont_pc_assessment(-1,None,None)["level"],"caution")

    def test_selected_soundfont_and_scan_counts_are_local_read_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            sf=root/"piano.sf2";sf.write_bytes(b"RIFF"+b"x"*4092)
            previous=dict(engine.PREFS)
            try:
                engine.PREFS["soundfont"]=str(sf)
                engine.PREFS["download"]=str(root)
                with engine.LOCK:
                    original=list(engine.FILES)
                    engine.FILES[:]=[
                        {"path":str(root/"a.mid"),"ncn":{"midi":"a.mid"}},
                        {"path":str(root/"b.kar")},
                        {"path":str(root/"c.m4a")},
                        {"path":str(root/"d.mp3")},
                        {"path":str(root/"e.mp4")}
                    ]
                with patch.object(engine,"_physical_memory",return_value=(8*1024**3,4*1024**3)):
                    result=engine.pc_audio_capabilities()
                self.assertEqual(result["totalSongs"],5)
                self.assertEqual(result["songCounts"]["NCN"],1)
                self.assertEqual(result["songCounts"]["KAR"],1)
                self.assertEqual(result["songCounts"]["M4A"],1)
                self.assertEqual(result["songCounts"]["MP3"],1)
                self.assertEqual(result["songCounts"]["VIDEO"],1)
                self.assertEqual(result["soundfont"]["sizeBytes"],sf.stat().st_size)
                self.assertEqual(result["soundfont"]["level"],"safe")
                self.assertEqual(result["ramAvailableBytes"],4*1024**3)
                self.assertIsInstance(result["downloadDiskFreeBytes"],int)
                self.assertEqual(sf.stat().st_size,4096,'Capability checks must not edit SF2')
                engine.PREFS["soundfont"]=str(root/"missing.sf2")
                self.assertIsNone(engine.pc_audio_capabilities()["soundfont"])
            finally:
                with engine.LOCK:engine.FILES[:]=original
                engine.PREFS.clear();engine.PREFS.update(previous)


if __name__=="__main__":
    unittest.main()
