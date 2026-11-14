import struct
import unittest

from karaoke.emk import parse_emk
from karaoke.ingest import Inspector
from karaoke.legacy import parse_ncn_lyrics
from test_studio import archive_fixture, midi_fixture
from karaoke.smf import parse_midi


class LyricEOFTests(unittest.TestCase):
    raw = 'เพลง\r\nศิลปิน\r\nC\r\n\r\nกข\r\n'.encode('cp874')
    trailer = b'\x1aOPT 1.50\x01\x00\x84\r\nBINARY\x00'
    cursor = struct.pack('<40H', *range(40))

    def test_ncn_trailer_does_not_change_text_or_timing(self):
        midi = parse_midi(midi_fixture())
        clean = parse_ncn_lyrics(self.raw, self.cursor, midi)
        actual = parse_ncn_lyrics(self.raw + self.trailer, self.cursor, midi)
        self.assertEqual(actual.lines, clean.lines)
        self.assertEqual(actual.source_character_count, clean.source_character_count)
        self.assertEqual([line.text for line in actual.lines], ['กข'])

    def test_emk_trailer_is_not_displayed(self):
        for masked in (False, True):
            with self.subTest(masked=masked):
                song = parse_emk(archive_fixture(masked, assets={
                    'MIDI_DATA': midi_fixture(), 'LYRIC_DATA': self.raw + self.trailer,
                    'CURSOR_DATA': self.cursor}))
                self.assertEqual([line.text for line in song.lyrics.lines], ['กข'])

    def test_metadata_decodes_thai_without_binary_fallback(self):
        self.assertEqual(Inspector.lyric_metadata(self.raw + self.trailer),
                         Inspector.lyric_metadata(self.raw))
        self.assertEqual(Inspector.lyric_metadata(self.raw + self.trailer)['first_lyric'], 'กข')

    def test_eof_without_newline_and_literal_opt_preserved(self):
        raw = b'a\nb\nC\n\nOPT 1.50'
        midi = parse_midi(midi_fixture())
        actual = parse_ncn_lyrics(raw + b'\x1a\x00junk', self.cursor, midi)
        self.assertEqual([line.text for line in actual.lines], ['OPT 1.50'])
