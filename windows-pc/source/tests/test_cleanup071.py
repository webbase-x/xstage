from concurrent.futures import ThreadPoolExecutor
import faulthandler
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from karaoke.library import JsonRecoveryError, read_json
from karaoke.json_recovery import restore_json
from karaoke.runtime_diagnostics import Diagnostics

class BackupReuseTests(unittest.TestCase):
    def error(self,p):
        try:read_json(p,{})
        except JsonRecoveryError as error:return error
        self.fail('Expected bad JSON')
    def test_repeated_same_damage_creates_one_exact_backup(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'settings.json';p.write_bytes(b'broken')
            errors=[self.error(p) for _ in range(10)]
            self.assertEqual(len({e.backup for e in errors}),1)
            self.assertEqual(len(list(Path(d).glob('*.bak'))),1)
            self.assertEqual(errors[0].backup.read_bytes(),b'broken');self.assertEqual(p.read_bytes(),b'broken')
    def test_changed_damage_gets_new_backup_and_keeps_old(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'settings.json';p.write_bytes(b'broken one');first=self.error(p).backup
            p.write_bytes(b'broken two');second=self.error(p).backup
            self.assertNotEqual(first,second);self.assertEqual(first.read_bytes(),b'broken one');self.assertEqual(second.read_bytes(),b'broken two')
    def test_missing_or_corrupted_cached_backup_is_not_reused(self):
        for missing in (True,False):
            with self.subTest(missing=missing),tempfile.TemporaryDirectory() as d:
                p=Path(d)/'settings.json';p.write_bytes(b'broken');first=self.error(p).backup
                if missing:first.unlink()
                else:first.write_bytes(b'damaged backup')
                second=self.error(p).backup
                self.assertNotEqual(first,second);self.assertEqual(second.read_bytes(),b'broken')
                if not missing:self.assertEqual(first.read_bytes(),b'damaged backup')
    def test_concurrent_failures_share_verified_backup(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'settings.json';p.write_bytes(b'broken')
            with ThreadPoolExecutor(max_workers=4) as pool:errors=list(pool.map(lambda _:self.error(p),range(16)))
            self.assertEqual(len({e.backup for e in errors}),1);self.assertEqual(len(list(Path(d).glob('*.bak'))),1)
    def test_explicit_restore_always_preserves_a_fresh_original(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'settings.json';p.write_bytes(b'broken');cached=self.error(p).backup
            source=Path(d)/'valid.json';source.write_bytes(b'{}');backup=restore_json(p,source)
            self.assertNotEqual(backup,cached);self.assertEqual(backup.read_bytes(),b'broken');self.assertEqual(cached.read_bytes(),b'broken')

class DiagnosticsCleanupTests(unittest.TestCase):
    def snapshot(self):return (list(logging.getLogger().handlers),logging.getLogger().level,sys.excepthook,threading.excepthook)
    def assert_snapshot(self,old):
        self.assertEqual(list(logging.getLogger().handlers),old[0]);self.assertEqual(logging.getLogger().level,old[1])
        self.assertIs(sys.excepthook,old[2]);self.assertIs(threading.excepthook,old[3])
    def test_native_file_open_failure_closes_log_handler(self):
        with tempfile.TemporaryDirectory() as d:
            old=self.snapshot();handlers=[];original=Path.open
            def handler(*args,**kwargs):
                obj=RotatingFileHandler(*args,**kwargs);handlers.append(obj);return obj
            def open_path(path,*args,**kwargs):
                if path.name.startswith('XStageKaraoke-native-'):raise OSError('native open failed')
                return original(path,*args,**kwargs)
            with patch('karaoke.runtime_diagnostics.RotatingFileHandler',side_effect=handler),patch('pathlib.Path.open',open_path):
                with self.assertRaisesRegex(OSError,'native open failed'):Diagnostics(d)
            self.assert_snapshot(old);self.assertIsNone(handlers[0].stream)
    def test_fault_enable_failure_closes_both_files(self):
        with tempfile.TemporaryDirectory() as d:
            old=self.snapshot();handlers=[];natives=[];original=Path.open
            def handler(*args,**kwargs):
                obj=RotatingFileHandler(*args,**kwargs);handlers.append(obj);return obj
            def open_path(path,*args,**kwargs):
                file=original(path,*args,**kwargs)
                if path.name.startswith('XStageKaraoke-native-'):natives.append(file)
                return file
            with patch('karaoke.runtime_diagnostics.RotatingFileHandler',side_effect=handler),patch('pathlib.Path.open',open_path),patch('karaoke.runtime_diagnostics.faulthandler.is_enabled',return_value=False),patch('karaoke.runtime_diagnostics.faulthandler.enable',side_effect=OSError('enable failed')):
                with self.assertRaisesRegex(OSError,'enable failed'):Diagnostics(d)
            self.assert_snapshot(old);self.assertIsNone(handlers[0].stream);self.assertTrue(natives[0].closed)
    def test_session_start_failure_restores_global_state(self):
        with tempfile.TemporaryDirectory() as d:
            old=self.snapshot();fault_before=faulthandler.is_enabled()
            with patch('karaoke.runtime_diagnostics.logging.info',side_effect=RuntimeError('start log failed')):
                with self.assertRaisesRegex(RuntimeError,'start log failed'):Diagnostics(d)
            self.assert_snapshot(old);self.assertEqual(faulthandler.is_enabled(),fault_before)
    def test_close_is_idempotent_and_releases_resources(self):
        with tempfile.TemporaryDirectory() as d:
            old=self.snapshot();diag=Diagnostics(d);diag.close();diag.close()
            self.assert_snapshot(old);self.assertTrue(diag.native.closed);self.assertIsNone(diag.handler.stream)
    def test_session_end_failure_still_releases_resources(self):
        with tempfile.TemporaryDirectory() as d:
            old=self.snapshot();diag=Diagnostics(d)
            with patch('karaoke.runtime_diagnostics.logging.info',side_effect=RuntimeError('end log failed')):
                with self.assertRaisesRegex(RuntimeError,'end log failed'):diag.close()
            self.assert_snapshot(old);self.assertTrue(diag.native.closed);self.assertIsNone(diag.handler.stream);diag.close()
    def test_native_close_failure_does_not_skip_handler_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            old=self.snapshot();diag=Diagnostics(d);native=diag.native
            def close():native.close();raise OSError('native close failed')
            diag.native=Mock(wraps=native);diag.native.close.side_effect=close
            with self.assertRaisesRegex(OSError,'native close failed'):diag.close()
            self.assert_snapshot(old);self.assertTrue(native.closed);self.assertIsNone(diag.handler.stream)
    def test_handler_close_failure_keeps_hooks_restored(self):
        with tempfile.TemporaryDirectory() as d:
            old=self.snapshot();diag=Diagnostics(d);original=diag.handler.close
            def close():original();raise OSError('handler close failed')
            with patch.object(diag.handler,'close',side_effect=close):
                with self.assertRaisesRegex(OSError,'handler close failed'):diag.close()
            self.assert_snapshot(old);self.assertTrue(diag.native.closed);self.assertIsNone(diag.handler.stream)
    def test_later_external_hooks_and_log_level_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            old=self.snapshot();diag=Diagnostics(d);external_sys=lambda *args:None;external_thread=lambda args:None
            try:
                sys.excepthook=external_sys;threading.excepthook=external_thread;logging.getLogger().setLevel(logging.DEBUG)
                diag.close();self.assertIs(sys.excepthook,external_sys);self.assertIs(threading.excepthook,external_thread);self.assertEqual(logging.getLogger().level,logging.DEBUG)
            finally:
                diag.close();sys.excepthook=old[2];threading.excepthook=old[3];logging.getLogger().setLevel(old[1])
    def test_preexisting_native_fault_handler_is_left_owned_by_host(self):
        with tempfile.TemporaryDirectory() as d,patch('karaoke.runtime_diagnostics.faulthandler.is_enabled',return_value=True),patch('karaoke.runtime_diagnostics.faulthandler.enable') as enable,patch('karaoke.runtime_diagnostics.faulthandler.disable') as disable:
            diag=Diagnostics(d);diag.close();enable.assert_not_called();disable.assert_not_called()
