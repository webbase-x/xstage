import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from karaoke.library import SongQueue, QueueItem, JsonRecoveryError, read_json, write_json
from karaoke.json_recovery import restore_json, inspect_candidate, preflight

class Recovery060Tests(unittest.TestCase):
    def test_valid_recovery_preserves_old_bytes_and_source(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'queue.json';target.write_bytes(b'{broken')
            source=Path(d)/'saved.json';payload=b'[{"song_id":7,"singer":"Test"}]';source.write_bytes(payload)
            backup=restore_json(target,source,expected=payload)
            self.assertEqual(backup.read_bytes(),b'{broken')
            self.assertEqual(source.read_bytes(),payload);self.assertEqual(target.read_bytes(),payload)
            self.assertEqual(SongQueue(target).items[0].song_id,7)
    def test_invalid_candidate_or_changed_preview_never_changes_target(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'queue.json';target.write_bytes(b'old')
            source=Path(d)/'saved.json'
            for payload in (b'{}',b'[null]',b'[{"song_id":false}]',b'[{"song_id":1,"speed":0}]',b'NaN'):
                source.write_bytes(payload)
                with self.assertRaises(ValueError):restore_json(target,source)
                self.assertEqual(target.read_bytes(),b'old')
            source.write_bytes(b'[]')
            with self.assertRaises(ValueError):restore_json(target,source,expected=b'[1]')
            self.assertEqual(target.read_bytes(),b'old')
    def test_replace_failure_keeps_original_and_backup(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'settings.json';target.write_bytes(b'{broken')
            source=Path(d)/'saved.json';source.write_bytes(b'{}')
            with patch('pathlib.Path.replace',side_effect=OSError('locked')):
                with self.assertRaises(OSError):restore_json(target,source)
            self.assertEqual(target.read_bytes(),b'{broken')
            self.assertEqual(len(list(Path(d).glob('*.bak'))),1)
            self.assertFalse(list(Path(d).glob('*.tmp')))
    def test_preflight_cancel_leaves_bad_queue_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'queue.json';target.write_bytes(b'[null]');prompt=Mock(return_value=False)
            self.assertFalse(preflight(d,prompt));prompt.assert_called_once()
            self.assertEqual(target.read_bytes(),b'[null]')
    def test_preflight_retries_after_selected_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'settings.json';target.write_bytes(b'broken')
            source=Path(d)/'saved.json';source.write_bytes(b'{"volume":25}')
            def prompt(error):restore_json(error.path,source);return True
            self.assertTrue(preflight(d,prompt));self.assertEqual(read_json(target,{})['volume'],25)
    def test_corrupt_queue_entry_is_not_silently_removed(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'queue.json';payload=b'[{"song_id":1},null]';target.write_bytes(payload)
            with self.assertRaises(JsonRecoveryError):SongQueue(target)
            self.assertEqual(target.read_bytes(),payload)
            self.assertEqual(next(Path(d).glob('*.bak')).read_bytes(),payload)
    def test_all_queue_mutations_roll_back_if_save_fails(self):
        with tempfile.TemporaryDirectory() as d:
            q=SongQueue(Path(d)/'queue.json');q.add(QueueItem(1));q.add(QueueItem(2))
            original=list(q.items)
            for action in (lambda:q.add(QueueItem(3)),lambda:q.insert(1,QueueItem(3)),lambda:q.pop(),lambda:q.move(0,1)):
                with patch.object(q,'save',side_effect=OSError('disk full')):
                    with self.assertRaises(OSError):action()
                self.assertEqual(q.items,original)
    def test_external_queue_damage_blocks_save_and_rolls_back_memory(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'queue.json';q=SongQueue(p);q.add(QueueItem(1));p.write_bytes(b'[null]')
            with self.assertRaises(JsonRecoveryError):q.add(QueueItem(2))
            self.assertEqual([x.song_id for x in q.items],[1]);self.assertEqual(p.read_bytes(),b'[null]')
    def test_nan_write_does_not_replace_valid_file(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'settings.json';p.write_bytes(b'{}')
            with self.assertRaises(ValueError):write_json(p,{'volume':float('nan')})
            self.assertEqual(p.read_bytes(),b'{}')
