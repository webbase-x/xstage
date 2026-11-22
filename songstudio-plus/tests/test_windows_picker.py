from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import windows_picker


class WindowsPickerTests(unittest.TestCase):
    def test_folder_picker_uses_powershell_sta_and_preserves_unicode_path(self):
        with tempfile.TemporaryDirectory() as base:
            folder=Path(base)/"เพลงไทย ป.๒"
            folder.mkdir()
            seen={}
            def fake_run(args,**kwargs):
                seen["args"]=args
                seen["env"]=kwargs["env"]
                return SimpleNamespace(returncode=0,stdout=str(folder),stderr="")
            with patch.object(windows_picker.sys,"platform","win32"),\
                 patch.object(windows_picker.subprocess,"run",side_effect=fake_run):
                result=windows_picker.pick("folder",str(folder))
            self.assertEqual(result,{"path":str(folder),"cancelled":False})
            self.assertIn("-STA",seen["args"])
            self.assertEqual(seen["env"]["XSTAGE_PICKER_KIND"],"folder")
            self.assertEqual(seen["env"]["XSTAGE_PICKER_CURRENT"],str(folder))
            self.assertEqual(seen["env"]["XSTAGE_PICKER_PARENT_PID"],str(windows_picker.os.getpid()))

    def test_cancel_and_error_are_explicit(self):
        with patch.object(windows_picker.sys,"platform","win32"),\
             patch.object(windows_picker.subprocess,"run",
                          return_value=SimpleNamespace(returncode=0,stdout="",stderr="")):
            self.assertEqual(windows_picker.pick("folder"),{"path":"","cancelled":True})
        with patch.object(windows_picker.sys,"platform","win32"),\
             patch.object(windows_picker.subprocess,"run",
                          return_value=SimpleNamespace(returncode=9,stdout="",stderr="boom")):
            with self.assertRaisesRegex(RuntimeError,"boom"):
                windows_picker.pick("folder")

    def test_picker_has_a_stable_parent_and_never_flashes_transparent_window(self):
        script=windows_picker._SCRIPT
        self.assertIn('XSTAGE_PICKER_PARENT_PID',script)
        self.assertIn('GetForegroundWindow()',script)
        self.assertEqual(script.count('$dlg.ShowDialog($owner)'),3)
        self.assertNotIn('$null=$owner.Show()',script)
        self.assertNotIn('$owner.Activate()',script)
        self.assertIn('$fallback.Dispose()',script)

    def test_concurrent_picker_cannot_open_competing_windows(self):
        self.assertTrue(windows_picker._PICKER_LOCK.acquire(blocking=False))
        try:
            with patch.object(windows_picker.sys,"platform","win32"):
                with self.assertRaisesRegex(RuntimeError,"ยังเปิดอยู่"):
                    windows_picker.pick("lrc")
        finally:
            windows_picker._PICKER_LOCK.release()

    def test_single_media_picker_is_supported_without_changing_folder_dialog(self):
        self.assertIn("elseif ($kind -eq 'media')",windows_picker._SCRIPT)
        self.assertIn("*.mid;*.midi;*.kar;*.mp3",windows_picker._SCRIPT)
        with tempfile.TemporaryDirectory() as folder:
            candidate=Path(folder)/"เพลงไทย ๐๐๑.mid"
            candidate.write_bytes(b"MThd")
            with patch.object(windows_picker.sys,"platform","win32"),\
                 patch.object(windows_picker.subprocess,"run",
                              return_value=SimpleNamespace(
                                  returncode=0,stdout=str(candidate),stderr="")):
                self.assertEqual(windows_picker.pick("media")["path"],str(candidate))

    def test_non_windows_is_rejected(self):
        with patch.object(windows_picker.sys,"platform","linux"):
            with self.assertRaisesRegex(RuntimeError,"Windows"):
                windows_picker.pick("folder")


if __name__=="__main__":
    unittest.main()
