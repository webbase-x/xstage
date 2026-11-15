import io
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from karaoke.lyrics import parse_lrc, decode_text, midi_lyrics
from karaoke.smf import parse_midi
from karaoke.library import SongLibrary, SongQueue, QueueItem, scan_folder, read_json
from tools.make_demo import vlq, meta, build_demo


def smf(tracks, fmt=1, division=480):
    return b"MThd" + struct.pack(">IHHH", 6, fmt, len(tracks), division) + b"".join(
        b"MTrk" + struct.pack(">I", len(track)) + track for track in tracks)


class LyricsTests(unittest.TestCase):
    def test_thai_encodings(self):
        value = "สวัสดีชาวโลก"
        self.assertEqual(decode_text(value.encode("utf-8")), value)
        self.assertEqual(decode_text(value.encode("cp874")), value)

    def test_precision_multi_timestamp_and_offset(self):
        lyrics = parse_lrc("[offset:100]\n[00:01.25][01:02.500]ร้องเพลง\n[00:03.5]ถัดไป")
        self.assertEqual(lyrics.starts, [1.25, 3.5, 62.5])
        self.assertIsNone(lyrics.at(1.0)[0])
        self.assertEqual(lyrics.at(1.15)[0].text, "ร้องเพลง")
        self.assertEqual(lyrics.at(62.4)[0].text, "ร้องเพลง")

    def test_enhanced_words_are_not_faked(self):
        lyrics = parse_lrc("[00:01.00]<00:01.00>สวัสดี <00:02.00>ทุกคน\n[00:04.00]จบ")
        self.assertEqual(lyrics.at(1.1)[2], "สวัสดี ")
        self.assertEqual(lyrics.at(2.1)[2], "สวัสดี ทุกคน")
        self.assertEqual(lyrics.at(4.1)[2], "จบ")

    def test_enhanced_repeat_shift(self):
        lyrics = parse_lrc("[00:01.0][00:11.0]<00:01.0>A<00:02.0>B")
        self.assertEqual(lyrics.at(11.5)[2], "A")

    def test_kar_line_breaks(self):
        lyrics = midi_lyrics([(0, "@KMIDI"), (1, "/สวัสดี "), (2, "ทุกคน"), (3, "\\ท่อนใหม่")])
        self.assertEqual([line.text for line in lyrics.lines], ["สวัสดี ทุกคน", "ท่อนใหม่"])
        self.assertEqual(lyrics.at(1.5)[2], "สวัสดี ")


class MidiTests(unittest.TestCase):
    def test_tempo_change_merged_tracks(self):
        conductor = vlq(0) + meta(0x51, (500000).to_bytes(3, "big")) + vlq(480) + meta(0x51, (1000000).to_bytes(3, "big")) + vlq(480) + meta(0x2F, b"")
        notes = b"\x00\x90\x3c\x50" + vlq(960) + b"\x80\x3c\x00\x00" + meta(0x2F, b"")
        song = parse_midi(smf([conductor, notes]))
        self.assertAlmostEqual(song.events[-1].at, 1.5)
        self.assertAlmostEqual(song.duration, 1.5)

    def test_running_status(self):
        notes = b"\x00\x90\x3c\x50\x01\x40\x50\x01\x3c\x00\x00" + meta(0x2F, b"")
        song = parse_midi(smf([notes], fmt=0))
        self.assertEqual(song.events[1].data, b"\x90\x40\x50")

    def test_smpte_timing(self):
        track = b"\x00\x90\x3c\x50" + vlq(2500) + b"\x80\x3c\x00\x00" + meta(0x2F, b"")
        song = parse_midi(smf([track], fmt=0, division=0xE764))
        self.assertAlmostEqual(song.duration, 1.0)

    def test_thai_midi_lyrics(self):
        track = b"\x00" + meta(5, "/สวัสดี".encode("cp874")) + vlq(480) + meta(0x2F, b"")
        self.assertEqual(parse_midi(smf([track], 0)).lyrics.lines[0].text, "สวัสดี")

    def test_bad_input_rejected(self):
        for data in (b"Not midi", b"MThd\0\0\0\6", smf([b"\x81\x81\x81\x81\x00"], 0),
                     smf([b"\x00\x90\xff\x01"], 0), smf([b"\0" + meta(0x51, b"\0\0\0")], 0)):
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    parse_midi(data)

    def test_async_format_rejected(self):
        with self.assertRaises(ValueError):
            parse_midi(smf([b"\0" + meta(0x2F, b"")], 2))

    def test_demo_has_timed_lyrics_and_music(self):
        with tempfile.TemporaryDirectory() as folder:
            data = build_demo(Path(folder))
            song = parse_midi(data)
            self.assertAlmostEqual(song.duration, 16)
            self.assertEqual(len(song.lyrics.lines), 4)
            self.assertGreater(len(song.events), 80)


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library = SongLibrary(self.root / "index.sqlite3")
        self.song = self.root / "001 - ร้องเพลง - ศิลปิน.wav"
        import wave
        with wave.open(str(self.song), 'wb') as audio:
            audio.setparams((1,2,8000,0,'NONE','not compressed'))
            audio.writeframes(b'\0\0' * 80)
        self.song_id = self.library.add_files([self.song])[0]

    def tearDown(self):
        self.temp.cleanup()

    def test_dedup_search_edit_favorite(self):
        self.library.add_files([self.song])
        self.assertEqual(self.library.count(), 1)
        self.assertEqual(len(self.library.search("ร้อง ศิลปิน")), 1)
        self.library.favorite(self.song_id)
        self.library.edit(self.song_id, "A", "ทดสอบ 100%", "คนร้อง")
        self.assertEqual(self.library.search("100%", True)[0]["code"], "A")
        self.assertEqual(self.library.search("_"), [])
        self.library.add_files([self.song])
        self.assertEqual(self.library.get(self.song_id)["title"], "ทดสอบ 100%")

    def test_scan_ignores_proprietary(self):
        (self.root / "protected.xmk").write_bytes(b"not opened")
        (self.root / "sub").mkdir()
        from test_studio import midi_fixture
        (self.root / "sub" / "other.mid").write_bytes(midi_fixture())
        count, skipped, errors = scan_folder(self.root, self.library)
        self.assertEqual((count, skipped), (2, 1))
        self.assertTrue(all("protected.xmk" in e or e.startswith("คำเตือน:") for e in errors))

    def test_queue_persistence_and_move(self):
        path = self.root / "queue.json"
        queue = SongQueue(path)
        queue.add(QueueItem(self.song_id, "ครูไพรัช", 2, 110))
        queue.add(QueueItem(self.song_id, "คนที่สอง"))
        self.assertEqual(queue.move(1, -1), 0)
        restored = SongQueue(path)
        self.assertEqual(restored.items[1].singer, "ครูไพรัช")
        restored.pop(0)
        self.assertEqual(SongQueue(path).items[0].key, 2)

    def test_portable_playlist_rebuilds_ids_and_keeps_missing_out(self):
        queue = SongQueue(self.root / "q.json")
        queue.add(QueueItem(self.song_id, "ครู", -3, 90))
        exported = self.root / "export.json"
        queue.export(exported, self.library)
        other = SongLibrary(self.root / "other.sqlite3")
        restored = SongQueue(self.root / "q2.json")
        self.assertEqual(restored.import_file(exported, other), (1, 0))
        self.assertEqual(other.get(restored.items[0].song_id)["title"], "ร้องเพลง")
        self.song.unlink()
        self.assertEqual(restored.import_file(exported, other), (0, 1))

    def test_malformed_queue_requires_recovery(self):
        path = self.root / "q.json"
        path.write_text('[null, {}, {"song_id":"broken"}]')
        from karaoke.library import JsonRecoveryError
        with self.assertRaises(JsonRecoveryError):
            SongQueue(path)
        self.assertEqual(path.read_text(), '[null, {}, {"song_id":"broken"}]')
        with self.assertRaises(ValueError):
            SongQueue(self.root / 'fresh-queue.json').import_file(path, self.library)


if __name__ == "__main__":
    unittest.main()
