import json
from pathlib import Path
import random
from tempfile import TemporaryDirectory
import unittest

from karaoke.library import SearchCancelled, SongLibrary, canonical
from karaoke.random_medley import build_preview, read_rhythms


class RandomMedleyPreviewTests(unittest.TestCase):
    def setUp(self):
        work = TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.folder = Path(work.name)
        self.library = SongLibrary(self.folder / 'songs.db')

    def song(self, filename, title='A Song', artist='Singer', key='C#', rhythm='Rock', *, present=True):
        path = self.folder / filename
        if present:
            path.write_bytes(b'media')
        self.library.upsert_catalog([dict(path=path, title=title, artist=artist, key_signature=key,
                                          rhythm=rhythm, kind='midi', playable=1)])
        with self.library.connect() as db:
            return db.execute('SELECT id FROM songs WHERE path=?', (canonical(path),)).fetchone()[0]

    def preview(self, source, count, **kwargs):
        return build_preview(self.library.path, source, count, rng=random.Random(0), **kwargs)

    def test_library_deduplicates_known_key_and_excludes_queue_by_identity(self):
        original = self.song('one.mid')
        same_key = self.song('two.mid', title=' a  song ', artist='SINGER', key='Db')
        different_key = self.song('three.mid', key='D')
        different_artist = self.song('four.mid', artist='Other')
        result = self.preview('library', 10)
        self.assertEqual({row.item.song_id for row in result.rows}, {original, different_key, different_artist})
        self.assertEqual((result.matched, result.duplicates), (4, 1))
        result = self.preview('library', 10, excluded_ids={same_key, 2**64})
        self.assertEqual({row.item.song_id for row in result.rows}, {different_key, different_artist})
        self.assertEqual(result.queued, 2)

    def test_rhythm_and_favorites_use_visible_rows(self):
        keeper = self.song('one.mid', rhythm='Rock  Pop')
        alias = self.song('alias.mid', rhythm='Old style')
        blank = self.song('blank.mid', title='Uncategorized', rhythm='')
        removed = self.song('removed.mid', title='Removed', rhythm='Hidden')
        with self.library.connect() as db:
            db.execute("UPDATE songs SET duplicate_of=?, favorite=1 WHERE id=?", (keeper, alias))
            db.execute("UPDATE songs SET duplicate_state='recycled', favorite=1 WHERE id=?", (removed,))

        self.assertEqual(read_rhythms(self.library.path), (('rock pop', 'Rock Pop'), ('', '')))
        self.assertEqual([row.item.song_id for row in self.preview('rhythm', 2, rhythm='ROCK POP').rows], [keeper])
        self.assertEqual([row.item.song_id for row in self.preview('rhythm', 2).rows], [blank])
        self.assertEqual([row.item.song_id for row in self.preview('favorites', 2).rows], [keeper])

    def test_missing_file_falls_back_to_matching_duplicate(self):
        self.song('missing.mid', present=False)
        keeper = self.song('exists.mid', key='Db')
        empty = self.song('empty.mid', title='Empty')
        (self.folder / 'empty.mid').write_bytes(b'')
        result = self.preview('library', 3)
        self.assertEqual([row.item.song_id for row in result.rows], [keeper])
        self.assertEqual((result.duplicates, result.unavailable), (1, 2))
        self.assertGreater(empty, 0)

    def test_playlist_maps_alias_and_preserves_settings_without_mutating_catalog(self):
        keeper = self.song('keeper.mid')
        alias = self.song('alias.mid')
        external = self.folder / 'external.mid'
        external.write_bytes(b'not indexed')
        with self.library.connect() as db:
            db.execute('UPDATE songs SET duplicate_of=? WHERE id=?', (keeper, alias))
            before = [tuple(row) for row in db.execute('SELECT * FROM songs ORDER BY id')]

        playlist = self.folder / 'playlist.json'
        playlist.write_text(json.dumps(dict(format='xstage.playlist', version=1, tracks=[
            dict(path='alias.mid', song_id=0, singer='Guest', key=-3, speed=125,
                 request_id='old remote request', medley_session='old session'),
            dict(path='keeper.mid', singer='Duplicate'),
            dict(path=str(external), song_id=keeper),
        ])), encoding='utf-8')
        playlist_bytes = playlist.read_bytes()
        result = self.preview('playlist', 3, playlist=playlist)
        self.assertEqual((result.matched, result.duplicates, result.unavailable), (3, 1, 1))
        item, = (row.item for row in result.rows)
        self.assertEqual((item.song_id, item.singer, item.key, item.speed), (keeper, 'Guest', -3, 125))
        self.assertEqual((item.request_id, item.medley_session), ('', ''))
        with self.library.connect() as db:
            self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM songs ORDER BY id')], before)
        self.assertEqual(playlist.read_bytes(), playlist_bytes)
        self.assertFalse((self.folder / 'queue.json').exists())

    def test_playlist_with_directory_alias_matches_canonical_index(self):
        # Path.resolve() used by SongLibrary expands junctions/symlinks, unlike
        # os.path.abspath().  Playlists must compare the same file identity.
        target = self.folder / 'media'
        target.mkdir()
        song_path = target / 'linked-song.mid'
        song_path.write_bytes(b'media')
        alias = self.folder / 'alias'
        try:
            alias.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest('symlink unavailable: ' + str(exc))
        self.library.upsert_catalog([dict(path=song_path, title='Alias song',
            artist='Singer', key_signature='C', rhythm='Rock', kind='midi', playable=1)])
        with self.library.connect() as db:
            song_id = db.execute('SELECT id FROM songs WHERE path=?',
                                 (canonical(song_path),)).fetchone()[0]
        playlist = self.folder / 'playlist.json'
        playlist.write_text(json.dumps(dict(format='xstage.playlist', version=1,
            tracks=[dict(path='alias/linked-song.mid')])), encoding='utf-8')
        result = self.preview('playlist', 1, playlist=playlist)
        self.assertEqual([row.item.song_id for row in result.rows], [song_id])
        self.assertEqual(result.unavailable, 0)

    def test_preview_honors_cancellation(self):
        self.song('one.mid')
        with self.assertRaises(SearchCancelled):
            self.preview('library', 2, cancelled=lambda: True)
