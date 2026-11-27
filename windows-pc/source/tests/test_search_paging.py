"""Search paging regression: real temporary SQLite and UI state, no hardware."""
import tempfile
import unittest
from pathlib import Path

from karaoke.library import SongLibrary
from karaoke.search_paging import SearchPaging
from karaoke.stage_layout import overlay_layout


class SearchPagingTests(unittest.TestCase):
    def test_request_guard_stale_page_and_retry(self):
        state = SearchPaging()
        state.reset(7)
        self.assertIsNone(state.request(7))
        self.assertFalse(state.accept(6, 0, 5, True))
        self.assertTrue(state.accept(7, 0, 5, True))
        self.assertEqual(state.request(7), 5)
        self.assertIsNone(state.request(7))
        state.failed(7, 5)
        self.assertEqual(state.request(7), 5)
        self.assertTrue(state.accept(7, 5, 2, False))
        self.assertIsNone(state.request(7))
        state.reset(8)
        self.assertFalse(state.accept(7, 5, 5, True))
        self.assertTrue(state.accept(8, 0, 0, False))
        self.assertIsNone(state.request(8))

    def test_five_rows_fit_compact_and_desktop(self):
        for width, height in ((800, 500), (1024, 768), (1920, 1080)):
            layout = overlay_layout(width, height)
            self.assertEqual(layout['rows'], 5)
            _, y, _, h = layout['search']
            self.assertLessEqual(y+h, height)

    def test_sqlite_pages_beyond_old_200_limit_without_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = SongLibrary(root/'songs.sqlite3')
            library.upsert_catalog([dict(path=str(root/f'{i}.mid'), code=f'{i:05}',
                title=f'เพลงทดสอบ {i:04}', artist='ศิลปิน', kind='MIDI',
                format='NCN24', playable=int(i % 7 != 0)) for i in range(260)])
            reader = library.open_reader()
            try:
                for query in ('', 'เพลง', 'เพลงทดสอบ'):
                    expected = reader.search(query, limit=500, playable_only=True, offset=0)
                    actual = []
                    while True:
                        page = reader.search(query, limit=6, playable_only=True, offset=len(actual))
                        actual.extend(page[:5])
                        if len(page) <= 5:
                            break
                    self.assertGreater(len(actual), 200)
                    self.assertEqual([r['id'] for r in actual], [r['id'] for r in expected])
                    self.assertEqual(len(actual), len({r['id'] for r in actual}))
            finally:
                reader.close()


if __name__ == '__main__':
    unittest.main()
