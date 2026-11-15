"""R4 regression tests: truthful preflight progress, narrow Drive discovery and stale work detection."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from karaoke.online_sync_feedback import OnlineSyncFeedback
from karaoke.library import SongLibrary
from karaoke.web_drive import sync_web_assets
from tests.test_studio import midi_fixture
from tests.test_v0944_web_sync import FakeWebDrive, StubRenderer


class RecordingDrive(FakeWebDrive):
    def __init__(self):
        super().__init__()
        self.lookups = []

    def children(self, parent, name=None):
        self.lookups.append((parent, name))
        return super().children(parent, name)


class PreflightFeedbackTests(unittest.TestCase):
    def test_worker_activity_with_unknown_total_resets_stale_timer_only_on_real_signal(self):
        f = OnlineSyncFeedback(now=100.)
        f.begin(4, 'ตรวจและซิงค์ไฟล์เพลง', now=100.)
        self.assertIn('ยังไม่ได้รับความคืบหน้าใหม่', f.indicator(now=131.))
        f.activity(now=135.)
        self.assertNotIn('ยังไม่ได้รับความคืบหน้าใหม่', f.indicator(now=153.))
        self.assertIn('ยังไม่ได้รับความคืบหน้าใหม่', f.indicator(now=167.))

    def test_preflight_reports_actual_steps_before_songs_and_filters_root_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            music = base / 'Songs'
            music.mkdir()
            data = base / 'Data'
            data.mkdir()
            midi = music / '97401.mid'
            midi.write_bytes(midi_fixture())
            lib = SongLibrary(data / 'songs.sqlite3')
            lib.add_files([midi])
            font = base / 'tone.sf2'
            font.write_bytes(b'test')
            drive = RecordingDrive()
            notices = []
            result = sync_web_assets(
                drive, lib.path, [music], base / 'native', {}, font,
                data / 'WebAssets', renderer_factory=StubRenderer,
                progress=lambda message, done=0, total=0: notices.append((message, done, total))
            )
            self.assertEqual(result['total'], 1)
            self.assertIn(('root','XStageWeb'), drive.lookups)
            messages = [m for m,_,_ in notices]
            self.assertTrue(any('กำลังค้นหาโฟลเดอร์ XStageWeb' in m for m in messages))
            self.assertTrue(any('กำลังอ่านดัชนีเพลง' in m for m in messages))
            self.assertTrue(any('กำลังตรวจไฟล์ต้นทาง' in m for m in messages))
            self.assertTrue(any('เพลงที่เข้าข่ายซิงก์ 1 เพลง' in m for m in messages))
            self.assertTrue(any('ตรวจโฟลเดอร์บน Drive ครบ' in m for m in messages))
            self.assertTrue(any('เผยแพร่ฐานเพลงรุ่น' in m for m in messages))

    def test_preflight_error_does_not_publish_or_delete_song(self):
        class FailingDrive(RecordingDrive):
            def children(self, parent, name=None):
                if parent == 'root':
                    raise TimeoutError('simulated Drive timeout')
                return super().children(parent, name)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            music = base / 'Songs'; music.mkdir()
            midi = music / '97402.mid';midi.write_bytes(midi_fixture())
            lib = SongLibrary(base / 'songs.sqlite3')
            lib.add_files([midi])
            font=base / 'tone.sf2';font.write_bytes(b'test')
            d=FailingDrive()
            progress=[]
            with self.assertRaisesRegex(TimeoutError, 'simulated Drive timeout'):
                sync_web_assets(d,lib.path,[music],base/'native',{},font,base/'cache',
                                renderer_factory=StubRenderer,
                                progress=lambda m,*_:progress.append(m))
            self.assertTrue(midi.is_file())
            self.assertIn('กำลังค้นหาโฟลเดอร์ XStageWeb บน Google Drive…',progress)
            self.assertFalse(d.uploads)


if __name__ == '__main__':
    unittest.main()
