import unittest
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "android-tv/app/src/main/java/com/webbasex/xstage/NativeCatalogStore.java"

class NativeCatalogDiskContract(unittest.TestCase):
    def test_source_storage_guards(self):
        text = SOURCE.read_text(encoding="utf-8")
        for phrase in ["getFilesDir()", "new byte[BUFFER_SIZE]", "getUsableSpace()", "getFD().sync()", "Os.rename", "OPEN_READONLY", "PRAGMA quick_check(1)", "LIMIT \" + PAGE_SIZE", "verifySource", "Catalog checksum or length mismatch"]:
            self.assertIn(phrase, text)
        self.assertNotIn("192 * 1024", text)
        self.assertLess(text.index("stream(fileId"), text.index("Os.rename"))
        self.assertLess(text.index("Os.rename"), text.index("database = candidate"))

    def test_large_disk_database_and_page_queries(self):
        # Host SQLite simulation, not Android instrumentation.
        # A zeroblob writes a >192 MiB database without a giant Python bytes object.
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "songs.sqlite3"
            db = sqlite3.connect(p)
            try:
                db.execute("CREATE TABLE songs(id INTEGER PRIMARY KEY, ordinal INTEGER, web_song_id TEXT, payload TEXT, code TEXT, title TEXT, artist TEXT, playable INTEGER)")
                db.execute("CREATE TABLE padding(data BLOB)")
                db.execute("INSERT INTO padding VALUES (zeroblob(?))", (193 * 1024 * 1024,))
                db.executemany("INSERT INTO songs VALUES(?,?,?,?,?,?,?,1)", [(i,i,str(i),'{}',str(i),'เพลงทดสอบ','ศิลปิน') for i in range(1,21)])
                db.commit()
                self.assertGreater(p.stat().st_size, 192 * 1024 * 1024)
            finally:
                db.close()
            reader = sqlite3.connect(p.as_uri()+"?mode=ro", uri=True)
            try:
                self.assertEqual(reader.execute("PRAGMA quick_check(1)").fetchone()[0],"ok")
                sql = "SELECT id FROM songs WHERE playable=1 AND instr(lower(code)||' '||lower(title)||' '||lower(artist),?)>0 ORDER BY ordinal,id LIMIT 5 OFFSET ?"
                self.assertEqual([r[0] for r in reader.execute(sql,("เพลง",0))], list(range(1,6)))
                self.assertEqual([r[0] for r in reader.execute(sql,("เพลง",5))], list(range(6,11)))
            finally:
                reader.close()

if __name__ == "__main__":
    unittest.main()
