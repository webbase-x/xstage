"""Tests for v0.9.37's local history-based medley ranking."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from karaoke.library import JsonRecoveryError, QueueItem, SearchCancelled, SongLibrary, canonical
from karaoke.popular_medley import history_hits
from karaoke.random_medley import build_preview

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone(timedelta(hours=7)))


class PopularMedleyTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.lib = SongLibrary(self.folder / 'catalog.sqlite3')
        self.hist = self.folder / 'history.json'
        self.now = datetime.now().astimezone()

    def song(self, name, title, *, present=True, artist='Singer'):
        path = self.folder / name
        if present:
            path.write_bytes(b'midi')
        self.lib.upsert_catalog([dict(path=path, title=title, artist=artist, key_signature='C',
                                      rhythm='Slow', kind='midi', playable=1)])
        with self.lib.connect() as db:
            return db.execute('SELECT id FROM songs WHERE path=?', (canonical(path),)).fetchone()[0]

    def record(self, song_id, path, *, status='completed', days=0, when=None):
        return dict(time=(when or self.now - timedelta(days=days)).isoformat(timespec='seconds'),
                    title='Played', artist='Singer', path=str(self.folder / path),
                    item=asdict(QueueItem(song_id)), status=status)

    def store(self, rows):
        self.hist.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
        return self.hist.read_bytes()

    def preview(self, count=10, **kwargs):
        return build_preview(self.lib.path, 'popular', count, history_path=self.hist, **kwargs)

    def test_counts_only_completed_or_medley_and_orders_by_play_count(self):
        often = self.song('often.mid', 'Often')
        rare = self.song('rare.mid', 'Rare')
        rows = ([self.record(often, 'often.mid', status='completed', days=1),
                 self.record(rare, 'rare.mid', status='completed'),
                 self.record(often, 'often.mid', status='medley'),
                 self.record(rare, 'rare.mid', status='interrupted'),
                 self.record(rare, 'rare.mid', status='playing')])
        source = self.store(rows)
        result = self.preview()
        self.assertEqual([(r.item.song_id, r.plays) for r in result.rows], [(often, 2), (rare, 1)])
        self.assertEqual(self.hist.read_bytes(), source)

    def test_all_and_periods_filter_by_time(self):
        a = self.song('a.mid', 'A')
        b = self.song('b.mid', 'B')
        self.store([self.record(a, 'a.mid', days=40), self.record(a, 'a.mid', days=40),
                    self.record(b, 'b.mid', days=2)])
        self.assertEqual(self.preview(popular_period='30').rows[0].item.song_id, b)
        self.assertEqual(self.preview(popular_period='90').rows[0].item.song_id, a)
        self.assertEqual(len(self.preview(popular_period='all').rows), 2)

    def test_identical_song_versions_combine_scores_and_keep_only_one(self):
        a = self.song('a.mid', 'Same')
        b = self.song('b.mid', 'Same')
        c = self.song('c.mid', 'Other')
        self.store([self.record(a, 'a.mid')] * 2 + [self.record(b, 'b.mid')] * 3 +
                   [self.record(c, 'c.mid')] * 4)
        result = self.preview()
        self.assertEqual(len(result.rows), 2)
        self.assertEqual(result.rows[0].plays, 5)
        self.assertIn(result.rows[0].item.song_id, (a, b))
        self.assertEqual(result.rows[1].item.song_id, c)

    def test_alias_history_contributes_to_keeper_without_queue_duplicates(self):
        keeper = self.song('keeper.mid', 'Same')
        alias = self.song('alias.mid', 'Same')
        other = self.song('other.mid', 'Other')
        with self.lib.connect() as db:
            db.execute('UPDATE songs SET duplicate_of=? WHERE id=?', (keeper, alias))
        self.store([self.record(alias, 'alias.mid')] * 3 + [self.record(other, 'other.mid')])
        self.assertEqual([(row.item.song_id, row.plays) for row in self.preview().rows], [(keeper, 3), (other, 1)])
        self.assertEqual([row.item.song_id for row in self.preview(excluded_ids={alias}).rows], [other])

    def test_history_symlink_alias_matches_canonical_index(self):
        # The history may contain an older junction/symlink spelling.  A
        # matching *physical* path must count, but a different file must not.
        target = self.folder / 'media'
        target.mkdir()
        song_path = target / 'track.mid'
        song_path.write_bytes(b'midi')
        alias = self.folder / 'alias'
        try:
            alias.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest('symlink unavailable: ' + str(exc))
        self.lib.upsert_catalog([dict(path=song_path, title='Alias hit',
            artist='Singer', key_signature='C', rhythm='Slow', kind='midi', playable=1)])
        with self.lib.connect() as db:
            song_id = db.execute('SELECT id FROM songs WHERE path=?',
                                 (canonical(song_path),)).fetchone()[0]
        self.store([self.record(song_id, 'alias/track.mid')])
        result = self.preview()
        self.assertEqual([(row.item.song_id, row.plays) for row in result.rows],
                         [(song_id, 1)])

    def test_path_mismatch_does_not_transfer_hits_to_reused_song_id(self):
        song = self.song('actual.mid', 'Safe')
        self.store([self.record(song, 'different.mid')])
        result = self.preview()
        self.assertEqual((len(result.rows), result.unavailable), (0, 1))

    def test_missing_and_nonplayable_are_excluded(self):
        gone = self.song('gone.mid', 'Gone', present=False)
        blocked = self.song('blocked.mid', 'Blocked')
        valid = self.song('valid.mid', 'Valid')
        with self.lib.connect() as db:
            db.execute("UPDATE songs SET duplicate_state='missing' WHERE id=?", (blocked,))
        self.store([self.record(gone, 'gone.mid')] * 3 +
                   [self.record(blocked, 'blocked.mid')] * 2 + [self.record(valid, 'valid.mid')])
        self.assertEqual([(r.item.song_id, r.plays) for r in self.preview().rows], [(valid, 1)])

    def test_corrupted_history_is_not_silently_reset(self):
        self.song('song.mid', 'Song')
        self.hist.write_text('{broken', encoding='utf-8')
        raw = self.hist.read_bytes()
        with self.assertRaises(JsonRecoveryError):
            self.preview()
        self.assertEqual(self.hist.read_bytes(), raw)

    def test_empty_history_and_missing_history_are_safe(self):
        self.song('song.mid', 'Song')
        self.assertEqual(self.preview().rows, [])
        self.store([])
        self.assertEqual(self.preview().matched, 0)

    def test_cancelled_aborts_before_reading_database(self):
        a = self.song('song.mid', 'Song')
        self.store([self.record(a, 'song.mid')])
        with self.assertRaises(SearchCancelled):
            self.preview(cancelled=lambda: True)

    def test_invalid_period_rejected(self):
        with self.assertRaises(ValueError):
            self.preview(popular_period='century')

    def test_excludes_queued_song_and_its_identity(self):
        one = self.song('one.mid', 'Song A')
        other = self.song('other.mid', 'Song B')
        self.store([self.record(one, 'one.mid')] * 3 + [self.record(other, 'other.mid')])
        self.assertEqual([row.item.song_id for row in self.preview(excluded_ids={one}).rows], [other])

    def test_stale_status_including_interrupted_not_counted(self):
        a = self.song('a.mid', 'Song A')
        self.store([self.record(a, 'a.mid', status=status) for status in
                    ('playing', 'interrupted', 'cancelled')])
        self.assertEqual(self.preview().rows, [])


if __name__ == '__main__':
    unittest.main()

# Optional integration smoke test for the real Tk dialog (run under xvfb-run on Linux).
import os
from types import SimpleNamespace
from unittest.mock import Mock


@unittest.skipUnless(os.name == 'nt' or os.environ.get('XSTAGE_GUI_TESTS') == '1',
                     'requires Windows GUI or explicit XSTAGE_GUI_TESTS=1 under Xvfb')
class PopularMedleyGuiTests(unittest.TestCase):
    """UI entrypoint and worker integration with an actual Tk interpreter."""
    def test_preview_dialog_selects_popular_source_and_enqueues(self):
        import tkinter as tk
        from karaoke.random_medley import RandomMedleyWindow
        fixture = PopularMedleyTests('test_counts_only_completed_or_medley_and_orders_by_play_count')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        song = fixture.song('hit.mid', 'Hit')
        fixture.store([fixture.record(song, 'hit.mid') for _ in range(3)])
        root = tk.Tk()
        root.withdraw()
        try:
            root.data_dir = fixture.folder
            root.library = fixture.lib
            root.song_queue = SimpleNamespace(items=[])
            root.current_item = None
            root.enqueue_random_medley = Mock(return_value=1)
            root._random_medley_window = None
            dialog = RandomMedleyWindow(root, 'popular')
            self.assertIn('เพลงฮิต', dialog.header_title.cget('text'))
            dialog.count.set('1')
            dialog.generate()
            import time
            for _ in range(50):
                root.update()
                if not dialog.busy:
                    break
                time.sleep(.02)
            self.assertFalse(dialog.busy)
            self.assertIsNotNone(dialog.preview)
            self.assertEqual(len(dialog.preview.rows), 1)
            self.assertEqual(dialog.preview.rows[0].plays, 3)
            dialog._enqueue(False)
            root.enqueue_random_medley.assert_called_once()
        finally:
            root.destroy()
