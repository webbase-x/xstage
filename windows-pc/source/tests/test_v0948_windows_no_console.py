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

    def test_ffmpeg_version_probe_is_silent(self):
        from karaoke.web_environment import resolve_ffmpeg
        from unittest.mock import Mock
        with patch('karaoke.web_environment.silent_subprocess_options',return_value={'creationflags':0x08000000}), \
             patch('karaoke.web_environment.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='ffmpeg version test 7.1',stderr='')) as call, \
             patch('karaoke.web_environment.Path.is_file',return_value=True):
            result=resolve_ffmpeg(Path('.'),{'web_ffmpeg':'C:/fake/ffmpeg.exe'})
        self.assertTrue(result)
        self.assertEqual(call.call_args.kwargs['creationflags'],0x08000000)
        self.assertTrue(call.call_args.kwargs['capture_output'])

    def test_ffprobe_codec_probe_is_silent(self):
        from karaoke.offline_generator import _check_aac
        with patch('karaoke.offline_generator.silent_subprocess_options',return_value={'creationflags':0x08000000}), \
             patch('karaoke.offline_generator.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='aac\n',stderr='')) as call:
            _check_aac('test.m4a','ffprobe.exe')
        self.assertEqual(call.call_args.kwargs['creationflags'],0x08000000)
        self.assertTrue(call.call_args.kwargs['capture_output'])

    def test_audio_encoding_process_is_silent_but_errors_still_captured(self):
        from karaoke.web_assets import render_audio
        class Synth:
            def start_offline_song(self): pass
            def render(self, frames): return b'\0'*(frames*8)
            def send(self, data): pass
        class FakeProcess:
            def __init__(self):
                self.stdin=io.BytesIO()
                self.stderr=io.BytesIO(b'')
            def wait(self, timeout=None):return 0
        midi=SimpleNamespace(events=[SimpleNamespace(at=0.,data=b'\x90\x3c\x64')],duration=.02)
        with tempfile.TemporaryDirectory() as work:
            output=Path(work)/'result.m4a'
            def fake_popen(args,**kwargs):
                Path(args[-1]).write_bytes(b'FAKE-AAC'*90)
                return FakeProcess()
            with patch('karaoke.web_assets.load_midi',return_value=midi), \
                 patch('karaoke.web_assets.silent_subprocess_options',return_value={'creationflags':0x08000000}), \
                 patch('karaoke.web_assets.subprocess.Popen',side_effect=fake_popen) as call:
                render_audio(Path(work)/'song.mid',output,Path(work),{},synth=Synth())
            self.assertTrue(output.is_file())
            self.assertEqual(call.call_args.kwargs['creationflags'],0x08000000)
            self.assertIsNotNone(call.call_args.kwargs['stderr'])
            self.assertIsNotNone(call.call_args.kwargs['stdin'])

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
