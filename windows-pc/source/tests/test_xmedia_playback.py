import hashlib
import sqlite3
import struct
import tempfile
import unittest
from pathlib import Path

from karaoke.ingest import Inspector
from karaoke.index_plan import SongPlan
from karaoke.plus_catalog import discover
from karaoke.pc_xstagesong import catalog_rows
from karaoke.smf import load_midi
from karaoke.xmedia_reader import HEADER, MAGIC, inspect_xmedia, materialize_media


def packed_text(value):
    raw=value.encode('utf-8')
    return struct.pack('<I',len(raw))+raw


def midi_fixture():
    track=b'\x00\xff\x2f\x00'
    return b'MThd'+struct.pack('>IHHH',6,0,1,480)+b'MTrk'+struct.pack('>I',len(track))+track


def xmedia(path, media, code='42', title='เพลงทดสอบ', artist='ศิลปินทดสอบ'):
    metadata=b''.join(packed_text(v) for v in ('song-42',code,'version-1',title,artist,'complete'))
    metadata+=struct.pack('<I',1)+struct.pack('<dd',1.0,3.0)+packed_text('สวัสดี')+packed_text('complete')
    metadata+=struct.pack('<I',2)
    metadata+=struct.pack('<dd',1.0,.5)+packed_text('ส')
    metadata+=struct.pack('<dd',1.5,.75)+packed_text('วัสดี')
    head=HEADER.pack(MAGIC,1,len(metadata),len(media),hashlib.sha256(media).digest(),
                     hashlib.sha256(metadata).digest())
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(head+metadata+media)
    return path


class XMediaPlaybackTests(unittest.TestCase):
    def test_xmid_inspect_and_midi_playback(self):
        with tempfile.TemporaryDirectory() as temp:
            path=xmedia(Path(temp)/'00000042.xmid',midi_fixture())
            info=inspect_xmedia(path)
            self.assertEqual((info['code'],info['kind']),('42','MIDI'))
            record,warnings=Inspector().inspect(path)
            self.assertEqual(record['title'],'เพลงทดสอบ')
            self.assertEqual(record['artist'],'ศิลปินทดสอบ')
            self.assertEqual(record['format'],'XMID')
            self.assertFalse([w for w in warnings if 'ไม่รองรับ' in w])
            song=load_midi(path)
            self.assertEqual(song.title,'เพลงทดสอบ')
            self.assertEqual(song.artist,'ศิลปินทดสอบ')
            self.assertEqual(song.lyrics.lines[0].text,'สวัสดี')
            self.assertEqual(song.lyrics.lines[0].words[1][0],1.5)

    def test_xaudio_materializes_verified_original_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);media=b'ID3'+b'payload'*100
            path=xmedia(root/'00000042.xmp3',media)
            target,document=materialize_media(path,root/'cache')
            self.assertEqual(target.suffix,'.mp3')
            self.assertEqual(target.read_bytes(),media)
            self.assertEqual(document['title'],'เพลงทดสอบ')
            damaged=bytearray(path.read_bytes());damaged[-1]^=1;path.write_bytes(damaged)
            with self.assertRaisesRegex(ValueError,'media SHA-256'):
                materialize_media(path,root/'new-cache')

    def test_plus_sqlite_seeds_exported_xmedia_without_replacing_legacy_scan(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);export=xmedia(root/'AUDIO'/'XMP3'/'0'/'00000042.xmp3',b'ID3payload')
            db_path=root/'DB'/'xstage_plus.sqlite3';db_path.parent.mkdir(parents=True)
            db=sqlite3.connect(db_path)
            db.executescript('''
              CREATE TABLE xstage_songs(id TEXT PRIMARY KEY,code INTEGER,title TEXT,artist TEXT,media_id TEXT);
              CREATE TABLE xstage_media(id TEXT PRIMARY KEY);
              CREATE TABLE xstage_lyric_versions(id TEXT PRIMARY KEY,song_id TEXT,is_current INTEGER,timing_status TEXT);
              CREATE TABLE xstage_lyric_lines(version_id TEXT,position INTEGER,text TEXT);
              CREATE TABLE xstage_exports(song_id TEXT PRIMARY KEY,version_id TEXT,output_path TEXT,sha256 TEXT);
            ''')
            db.execute('INSERT INTO xstage_media VALUES (?)',('media-1',))
            db.execute('INSERT INTO xstage_songs VALUES (?,?,?,?,?)',('song-42',42,'เพลงจากฐาน','ศิลปินจากฐาน','media-1'))
            db.execute('INSERT INTO xstage_lyric_versions VALUES (?,?,?,?)',('version-1','song-42',1,'complete'))
            db.execute('INSERT INTO xstage_lyric_lines VALUES (?,?,?)',('version-1',0,'สวัสดี'))
            db.execute('INSERT INTO xstage_exports VALUES (?,?,?,?)',
                       ('song-42','version-1',str(export.relative_to(root)),'abc'))
            db.commit();db.close()
            rows,warnings=discover(root)
            self.assertFalse(warnings)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0][1]['title'],'เพลงจากฐาน')
            imported_root, imported_rows=catalog_rows(root)
            self.assertTrue(imported_root.samefile(root),'Plus import must return the same workspace directory')
            self.assertEqual(len(imported_rows),1)
            self.assertEqual(imported_rows[0]['source_catalog'],'Song Studio Plus SQLite')
            self.assertEqual(imported_rows[0]['title'],'เพลงจากฐาน')
            with SongPlan() as plan:
                plan.folder(root)
                hint=plan.hint(export)
                self.assertEqual(hint['artist'],'ศิลปินจากฐาน')
                self.assertGreaterEqual(plan.count(),1)


if __name__ == '__main__':
    unittest.main()
