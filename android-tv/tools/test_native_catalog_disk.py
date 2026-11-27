import unittest
import sqlite3
import hashlib
import os
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

    def test_cloud_revision_contract(self):
        text = SOURCE.read_text(encoding="utf-8")
        self.assertIn("String revision = contentRevision(md5, size);", text)
        self.assertIn('return md5 + "-" + size;', text)
        self.assertIn("activeFile.length() == size", text)
        self.assertIn("md5.equals(hex(digest.digest()))", text)
        self.assertIn("Cloud catalog changed during download", text)
        self.assertLess(text.index("JSONObject latest = verifySource"), text.index("Os.rename"))
        self.assertNotIn('String revision = fileId +', text)

    def test_revision_and_atomic_swap_simulation(self):
        # Host-side transfer model: content comparison, interrupted download,
        # and successful replacement. Does not emulate Android Java or Drive.
        def identity(path):
            h = hashlib.md5()
            with path.open("rb") as f:
                for block in iter(lambda: f.read(131072), b""):
                    h.update(block)
            return (h.hexdigest(), path.stat().st_size)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local, cloud, part = [root / n for n in ("songs.sqlite3", "cloud.sqlite3", "download.part")]
            for p in (local, cloud):
                p.write_bytes(b"same catalog bytes")
            self.assertEqual(identity(local), identity(cloud))
            cloud.write_bytes(b"new! catalog bytes")
            self.assertEqual(local.stat().st_size, cloud.stat().st_size)
            self.assertNotEqual(identity(local), identity(cloud))
            old = identity(local)
            part.write_bytes(b"new!")
            self.assertNotEqual(identity(part), identity(cloud))
            self.assertEqual(identity(local), old)
            part.write_bytes(cloud.read_bytes())
            self.assertEqual(identity(part), identity(cloud))
            os.replace(part, local)
            self.assertEqual(identity(local), identity(cloud))

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
