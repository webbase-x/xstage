from array import array
from pathlib import Path
import unittest
from unittest.mock import Mock

from karaoke.lyrics import LyricLine, Lyrics
from karaoke.medley_trim import midi_bounds, pcm_bounds, protect_lyrics
from karaoke.smf import MidiEvent, MidiSong


def song(*events, lyrics=None):
    return MidiSong([MidiEvent(at, bytes(data)) for at, *data in events], 20., lyrics or Lyrics())


class MidiTrimTests(unittest.TestCase):
    def test_low_velocity_pickup_and_sustain_release(self):
        midi = song((2., 0x90, 60, 1), (3., 0xb0, 64, 127),
                    (8., 0x90, 60, 0), (12., 0xb0, 64, 0))
        bounds = midi_bounds(midi)
        self.assertAlmostEqual(bounds.start, 1.65)
        self.assertEqual((bounds.end, bounds.first_note), (14., 2.))

    def test_unresolved_pedal_or_overlapping_note_keeps_tail(self):
        sustained = song((2., 0x90, 60, 65), (3., 0xb0, 66, 127), (6., 0x80, 60, 0))
        repeated = song((2., 0x90, 60, 65), (3., 0x90, 60, 65), (6., 0x80, 60, 0))
        for midi in (sustained, repeated):
            self.assertEqual(midi_bounds(midi).end, midi.duration)

    def test_lyrics_keep_the_first_cue_and_last_word_with_offset(self):
        midi = song((5., 0x90, 60, 80), (11., 0x80, 60, 0),
                    lyrics=Lyrics([LyricLine(2., 'คำแรก')]))
        bounds = midi_bounds(midi)
        self.assertAlmostEqual(bounds.start, 1.2)
        lyric_track = Lyrics([LyricLine(2., 'คำสุดท้าย', [(17., 'ท้าย')])], offset_ms=100)
        final = protect_lyrics(bounds, lyric_track, offset_ms=100)
        self.assertAlmostEqual(final.start, 1.0)
        self.assertAlmostEqual(final.end, 18.8)
        self.assertEqual(final.first_note, bounds.first_note)

    def test_no_notes_has_no_reliable_cut_point(self):
        bounds = midi_bounds(song((2., 0xb0, 7, 100)))
        self.assertEqual((bounds.start, bounds.end, bounds.first_note), (0., 20., None))


def region(start, end, samples):
    return start, end, array('f', samples).tobytes()


class PcmTrimTests(unittest.TestCase):
    def test_preserves_very_quiet_pickup_and_decay_in_either_channel(self):
        # 10 interleaved samples/s are enough to test the time arithmetic.
        head = region(0., 8., [0.]*21 + [.00002, .3] + [0.]*57)
        tail = region(12., 20., [.3] + [0.]*26 + [-.00002] + [0.]*52)
        decoder = Mock(sample_regions=Mock(return_value=(head, tail)))
        bounds = pcm_bounds(Path('song.wav'), 20., decoder=decoder)
        self.assertAlmostEqual(bounds.start, 1.75)
        self.assertAlmostEqual(bounds.end, 15.45)

    def test_preserves_unverified_edges_and_rejects_length_disagreement(self):
        decoder = Mock(sample_regions=Mock(return_value=(region(0., 8., [0.]*8),
                                                       region(12., 20., [.2] + [0.]*7))))
        bounds = pcm_bounds(Path('song.mp3'), 22., decoder=decoder)
        self.assertEqual((bounds.start, bounds.end), (0., 22.))
        decoder.sample_regions.side_effect = OSError('decode failed')
        bounds = pcm_bounds(Path('song.mp3'), 22., decoder=decoder, scan_tail=False)
        self.assertEqual((bounds.start, bounds.end), (0., 22.))
        decoder.sample_regions.assert_called_with(Path('song.mp3'), 8., scan_tail=False)
