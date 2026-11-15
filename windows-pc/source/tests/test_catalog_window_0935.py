"""Catalog-browser paging: preserve old semantics, avoid stale unavailable rows."""
import tempfile
import unittest
from pathlib import Path
from karaoke.library import SongLibrary, canonical
from karaoke.catalog_window import read_page


class CatalogWindow0935Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = SongLibrary(Path(self.temp.name) / 'Data' / 'songs.sqlite3')
        self.db.upsert_catalog([
            dict(path=str(Path(self.temp.name)/'one.wav'),code='001',title='สวัสดีฉัน',artist='นักร้องหนึ่ง',
                 kind='audio',format='wav',playable=1,key_signature='C Major'),
            dict(path=str(Path(self.temp.name)/'two.wav'),code='002',title='สวัสดีดาว',artist='นักร้องสอง',
                 kind='audio',format='wav',playable=1,key_signature='Am'),
            dict(path=str(Path(self.temp.name)/'three.wav'),code='003',title='เรืองแสง',artist='แสงดาว',
                 kind='audio',format='wav',playable=1,key_signature='G'),
        ])

    def test_thai_trigram_and_short_keys(self):
        for q, expected in [('สวัสดี',2),('ดาว',2),('C Major',1),('Am',1),('นักร้อง',2),('ไม่มี',0)]:
            with self.subTest(query=q):
                rows,total,found,page = read_page(self.db.path,q,0,lambda:False)
                self.assertEqual(total,3)
                self.assertEqual(found,expected)
                self.assertEqual(len(rows), expected)

    def test_missing_row_is_not_displayed(self):
        with self.db.connect() as db:
            db.execute("UPDATE songs SET duplicate_state='missing',playable=0 WHERE code='002'")
        rows,total,found,page=read_page(self.db.path,'สวัสดี',0,lambda:False)
        self.assertEqual(total,2)
        self.assertEqual(found,1)
        self.assertEqual(rows[0]['code'],'001')

    def test_page_boundaries(self):
        rows,total,found,page=read_page(self.db.path,'',99,lambda:False)
        self.assertEqual(page,0)
        self.assertEqual(len(rows),3)


if __name__=='__main__':
    unittest.main()
