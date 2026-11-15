import json
import tempfile
import unittest
from pathlib import Path
from karaoke.library import read_json, write_json, JsonRecoveryError
from karaoke.instance_lock import DataDirectoryLock

class RecoveryTests(unittest.TestCase):
    def test_missing_file_defaults_and_normal_write(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'settings.json'
            self.assertEqual(read_json(p,{}),{})
            write_json(p,{'hello':1})
            self.assertEqual(read_json(p,{}),{'hello':1})
            self.assertFalse(list(Path(d).glob('*.tmp')))
    def test_corruption_never_overwritten_and_backup_exact(self):
        for payload in (b'{broken', b'\xff\xfe'):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as d:
                p=Path(d)/'queue.json';p.write_bytes(payload)
                with self.assertRaises(JsonRecoveryError):read_json(p,[])
                with self.assertRaises(JsonRecoveryError):write_json(p,[])
                self.assertEqual(p.read_bytes(),payload)
                copies=list(Path(d).glob('*.bak'))
                self.assertTrue(copies)
                self.assertTrue(all(x.read_bytes()==payload for x in copies))
    def test_wrong_root_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'settings.json';p.write_text('[]')
            with self.assertRaises(JsonRecoveryError):read_json(p,{})
            self.assertEqual(p.read_text(),'[]')
    def test_lock_exclusion_and_release(self):
        with tempfile.TemporaryDirectory() as d:
            first=DataDirectoryLock(d).acquire()
            try:
                with self.assertRaises(RuntimeError):DataDirectoryLock(d).acquire()
            finally:first.close()
            second=DataDirectoryLock(d).acquire();second.close()
