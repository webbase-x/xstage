"""Relevance, cancellation and persistent read-cache regression tests."""
import tempfile
import unittest
from pathlib import Path
from karaoke.library import SongLibrary, SearchCancelled


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.library = SongLibrary(Path(self.temporary.name)/'songs.sqlite3')
        fixtures = [
            ('A013677', '02รักน้องพรจดหมายผิดซอง', 'สดใส', 'NCN24', 'รักน้องพร'),
            ('U04944', '02รักน้องพรจดหมายผิดซอง', 'สดใส', 'EMK', 'รักน้องพร'),
            ('20120', 'รักน้องพร', 'บาซู', 'NCN24', ''),
            ('60981', 'รักน้องพร', 'สดใส รุ่งโพธิ์ทอง', 'NCN24', ''),
            ('005492', 'รักน้องพร', 'บาซู', 'EMK', ''),
            ('ABC', 'กอด', 'รักน้องพร', 'NCN24', ''),
            ('999', 'คนละเพลง', '-', 'NCN24', 'รักน้องพร'),
        ]
        self.library.upsert_catalog([dict(path=str(Path(self.temporary.name)/(code+'.mid')),
            code=code, title=title, artist=artist, format=kind, kind='MIDI', playable=1,
            first_lyric=lyric) for code, title, artist, kind, lyric in fixtures])

    def tearDown(self):
        self.temporary.cleanup()

    def test_exact_title_precedes_numbered_prefix_and_lyric(self):
        rows = self.library.search('รักน้องพร')
        self.assertEqual([row['code'] for row in rows[:3]], ['20120', '60981', '005492'])
        self.assertLess(next(i for i, r in enumerate(rows) if r['code']=='A013677'),
                        next(i for i, r in enumerate(rows) if r['code']=='999'))

    def test_ranking_is_applied_before_limit(self):
        self.assertEqual(self.library.search('รักน้องพร', limit=1)[0]['code'], '20120')

    def test_short_title_prefix_skips_unsupported_before_selection(self):
        self.library.upsert_catalog([dict(path=str(Path(self.temporary.name)/f'prefix-{i}.mid'),
            code=f'C{i}', title=f'ร{i:03}', artist='', kind='MIDI', format='NCN24', playable=int(i%3 != 0))
            for i in range(80)])
        self.assertEqual([r['code'] for r in self.library.search('ร',limit=3,playable_only=True)], ['C1','C2','C4'])

    def test_exact_code_and_artist_tokens(self):
        self.assertEqual(self.library.search('20120')[0]['code'], '20120')
        self.assertEqual(self.library.search('รักน้องพร บาซู')[0]['code'], '20120')

    def test_like_fallback_uses_same_relevance(self):
        self.library.fts = False
        self.assertEqual(self.library.search('รักน้องพร', limit=1)[0]['code'], '20120')

    def test_cache_refreshes_after_metadata_or_favorite_write(self):
        reader = self.library.open_reader()
        try:
            self.assertEqual(reader.search('รักน้องพร')[0]['code'], '20120')
            song_id = self.library.search('20120')[0]['id']
            self.library.edit(song_id, '20120', 'แก้ชื่อใหม่', 'บาซู')
            self.assertNotIn('20120', [row['code'] for row in reader.search('รักน้องพร')])
            self.library.favorite(song_id)
            self.assertEqual(reader.search('แก้ชื่อใหม่', favorite=True)[0]['code'], '20120')
        finally:
            reader.close()

    def test_cancellation_does_not_break_next_search(self):
        reader = self.library.open_reader()
        try:
            calls = []
            def cancelled():
                calls.append(1)
                return len(calls) > 1
            with self.assertRaises(SearchCancelled):
                reader.search('รักน้องพร', cancelled=cancelled)
            self.assertEqual(reader.search('20120')[0]['code'], '20120')
        finally:
            reader.close()

    def test_long_obsolete_query_is_interrupted_inside_sqlite(self):
        self.library.upsert_catalog([dict(path=str(Path(self.temporary.name)/f'bulk-{i}.mid'),
            code=str(100000+i), title=f'เพลงทดสอบ {i}', artist='', kind='MIDI', format='NCN24', playable=1)
            for i in range(8000)])
        reader = self.library.open_reader()
        calls = []
        def cancelled():
            calls.append(1)
            return len(calls) > 2
        try:
            with self.assertRaises(SearchCancelled) as caught:
                reader.search('Z', cancelled=cancelled)
            self.assertIsNotNone(caught.exception.__cause__)
            self.assertIn('interrupt', str(caught.exception.__cause__).lower())
            self.assertEqual(reader.search('20120')[0]['code'], '20120')
        finally:
            reader.close()

    def test_existing_schema_reopens_without_ddl_writes(self):
        reader = self.library.open_reader()
        try:
            reader.warm_up()
            version = reader.db.execute('PRAGMA data_version').fetchone()[0]
            other = SongLibrary(self.library.path)
            self.assertTrue(other.has_songs())
            self.assertEqual(version, reader.db.execute('PRAGMA data_version').fetchone()[0])
        finally:
            reader.close()


if __name__ == '__main__':
    unittest.main()
