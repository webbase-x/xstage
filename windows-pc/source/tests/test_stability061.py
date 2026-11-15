import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
from karaoke.library import QueueItem, JsonRecoveryError
from karaoke.performance_features import PlayHistory, history_start, history_finish, PerformanceFeatures
from karaoke.runtime_diagnostics import log_base
from karaoke.log_viewer import log_directory
from karaoke.instance_lock import DataDirectoryLock
from tools.verify_release import make_manifest, verify_manifest, file_hash

class History061Tests(unittest.TestCase):
    def test_invalid_entry_preserves_original_and_exact_backup(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'history.json';raw=b'[{"time":"now","title":"song","path":"a.mid","status":"completed","item":{"song_id":1}},null]';p.write_bytes(raw)
            with self.assertRaises(JsonRecoveryError):PlayHistory(p)
            self.assertEqual(p.read_bytes(),raw);self.assertEqual(next(Path(d).glob('*.bak')).read_bytes(),raw)
    def test_start_and_finish_failures_roll_back_memory_and_file(self):
        with tempfile.TemporaryDirectory() as d:
            h=PlayHistory(Path(d)/'history.json');h.start(QueueItem(1),{'title':'one','path':'one.mid'})
            before=copy.deepcopy(h.rows);raw=h.path.read_bytes()
            for action in (lambda:h.start(QueueItem(2),{'title':'two','path':'two.mid'}),lambda:h.finish('completed',QueueItem(1,key=5))):
                with patch.object(h,'save',side_effect=OSError('disk full')):
                    with self.assertRaises(OSError):action()
                self.assertEqual(h.rows,before);self.assertEqual(h.path.read_bytes(),raw)
    def test_external_damage_blocks_cached_history_save(self):
        with tempfile.TemporaryDirectory() as d:
            h=PlayHistory(Path(d)/'history.json');h.start(QueueItem(1),{'path':'one.mid'})
            before=copy.deepcopy(h.rows);h.path.write_bytes(b'[null]')
            with self.assertRaises(JsonRecoveryError):h.finish('completed')
            self.assertEqual(h.rows,before);self.assertEqual(h.path.read_bytes(),b'[null]')
    def test_corrupt_history_does_not_escape_playback_hooks(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'history.json';p.write_bytes(b'broken')
            app=NS(data_dir=Path(d),current_song={'path':'one.mid'},current_item=QueueItem(1),status_var=Mock())
            with self.assertLogs(level='ERROR') as logs:
                history_start(app,QueueItem(1));history_finish(app,'completed')
            self.assertTrue(any('HISTORY_PERSIST_FAILED' in x for x in logs.output))
            self.assertEqual(p.read_bytes(),b'broken');self.assertEqual(app.status_var.set.call_count,2)
    def test_history_window_reports_failure_before_creating_dialog(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'history.json';p.write_bytes(b'broken');app=NS(data_dir=Path(d),show_error=Mock())
            with patch('karaoke.performance_features.DialogWindow') as window, patch('karaoke.json_recovery.prompt_recovery',return_value=False) as recovery, self.assertLogs(level='ERROR'):
                PerformanceFeatures.history_window(app)
            recovery.assert_called_once();app.show_error.assert_not_called();window.assert_not_called()

class Manifest061Tests(unittest.TestCase):
    def test_rejects_empty_manifest_wrong_algorithm_and_invalid_hash(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'XStageKaraoke.exe').write_bytes(b'fixture');valid=make_manifest(p,'0.6.1')
            invalid=[{},dict(valid,files={}),dict(valid,algorithm='md5'),dict(valid,version='01.6.1'),dict(valid,files={'XStageKaraoke.exe':'bad'})]
            for manifest in invalid:
                with self.subTest(manifest=manifest):
                    (p/'release-manifest.json').write_text(json.dumps(manifest))
                    with self.assertRaises(ValueError):verify_manifest(p)
    def test_rejects_traversal_absolute_and_windows_stream_paths(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);exe=p/'XStageKaraoke.exe';exe.write_bytes(b'fixture')
            for path in ('../outside','/absolute','C:/outside','dir/../file','dir//file','dir\\file','file:stream'):
                manifest=make_manifest(p,'0.6.1');manifest['files'][path]=file_hash(exe)
                (p/'release-manifest.json').write_text(json.dumps(manifest))
                with self.subTest(path=path),self.assertRaises(ValueError):verify_manifest(p)
    def test_rejects_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'release-manifest.json').write_text('{"version":"0.6.1","version":"0.6.0","algorithm":"sha256","files":{}}')
            with self.assertRaisesRegex(ValueError,'Duplicate manifest key'):verify_manifest(p)
    def test_rejects_case_collisions_on_windows(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'XStageKaraoke.exe').write_bytes(b'fixture');(p/'A.txt').write_bytes(b'same')
            manifest=make_manifest(p,'0.6.1');manifest['files']['a.txt']=file_hash(p/'A.txt')
            (p/'release-manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'Duplicate Windows path'):verify_manifest(p)

class Cleanup061Tests(unittest.TestCase):
    def test_log_viewer_without_attached_diagnostics_uses_data_specific_path(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'LOCALAPPDATA':d}):
            data=Path(d)/'data';self.assertEqual(log_directory(NS(data_dir=data)),log_base(data))
            fallback=data/'Logs';fallback.mkdir(parents=True)
            self.assertEqual(log_directory(NS(data_dir=data)),fallback)
            log_base(data).mkdir(parents=True)
            self.assertEqual(log_directory(NS(data_dir=data)),log_base(data))
    def test_no_localappdata_has_one_consistent_log_directory(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'LOCALAPPDATA':''}):
            data=Path(d);self.assertEqual(log_base(data),data/'Logs');self.assertEqual(log_directory(NS(data_dir=data)),data/'Logs')
    def test_diagnostics_close_failure_still_releases_data_lock(self):
        import main
        with tempfile.TemporaryDirectory() as d,patch.object(sys,'argv',['main.py','--data-dir',d]):
            diagnostics=Mock();diagnostics.close.side_effect=OSError('close failed')
            with patch('karaoke.runtime_diagnostics.start',return_value=diagnostics),patch('karaoke.restore.apply_pending',return_value=None),patch('karaoke.json_recovery.preflight',return_value=False):
                with self.assertRaisesRegex(OSError,'close failed'):main.main()
            lock=DataDirectoryLock(d).acquire();lock.close()
