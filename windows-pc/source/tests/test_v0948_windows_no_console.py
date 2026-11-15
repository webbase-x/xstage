"""Regression: GUI sync may never flash ffmpeg/ffprobe console windows.

No real Google Drive, SoundFont, Windows process, or credentials required.
"""
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from karaoke.windows_process import silent_subprocess_options


class WindowsNoConsoleTests(unittest.TestCase):
    def test_windows_process_flags_hide_console(self):
        with patch('karaoke.windows_process.sys.platform','win32'):
            options=silent_subprocess_options()
        self.assertEqual(options['creationflags'] & 0x08000000,0x08000000)
        if 'startupinfo' in options:
            self.assertEqual(options['startupinfo'].wShowWindow,0)

    def test_other_platform_does_not_apply_windows_flags(self):
        with patch('karaoke.windows_process.sys.platform','linux'):
            self.assertEqual(silent_subprocess_options(),{})

    def test_gui_silent_launcher_exists_and_installer_copies_it(self):
        root=Path(__file__).resolve().parents[1]
        launcher=(root/'Start-XStage-Silent.vbs').read_text(encoding='utf-8')
        installer=(root/'install_to_D.ps1').read_text(encoding='utf-8-sig')
        builder=(root/'build.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('shell.Run command, 1, False',launcher)
        self.assertIn("$target 'Start-XStage-Silent.vbs'",installer)
        self.assertIn("'Start-XStage-Silent.vbs'",builder)
        self.assertIn(' --windowed ',builder)


if __name__=='__main__': unittest.main()
