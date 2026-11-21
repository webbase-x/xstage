import unittest
from concurrent.futures import Future
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from karaoke.library import QueueItem
from karaoke.lyrics import Lyrics
from karaoke.medley import begin, cancel_random_fill, end_random_medley, tick, toggle_random_fill
from karaoke.medley_decks import Decks
from karaoke.medley_full import can_play_fill, drum_fill
from karaoke.medley_trim import TrimBounds
from karaoke.smf import MidiEvent, MidiSong


class FullSongMedleyTests(unittest.TestCase):
    def test_rhythm_volume_failure_restores_drums_and_preserves_song(self):
        decks = Decks()
        rhythm = Mock()
        rhythm.playing = True
        rhythm.speed = 1.0
        rhythm.song.initial_bpm = 120
        rhythm.set_volume.side_effect = OSError('rhythm volume failed')
        active = Mock()
        active.playing = True
        app = NS(engine=active, system_volume=1.0)
        decks.rhythm = rhythm
        decks.rhythm_target = active
        decks.drum_was_muted = False
        decks.stamp = 10.0
        try:
            with patch('karaoke.medley.bpm_at', return_value=120):
                decks.update(app, 10.1)
            self.assertIsNone(decks.rhythm)
            self.assertIsNone(decks.rhythm_target)
            active.set_channel.assert_called_with(9, muted=False)
            rhythm.close.assert_called_once()
            self.assertTrue(active.playing)
        finally:
            decks.close()

    def test_auxiliary_rhythm_failure_restores_drums_and_keeps_song(self):
        decks = Decks()
        rhythm = Mock()
        rhythm.playing = True
        rhythm.pump.side_effect = OSError('rhythm device error')
        rhythm.close.side_effect = OSError('rhythm cleanup error')
        active = Mock()
        active.playing = True
        app = NS(engine=active, system_volume=1.0)
        decks.rhythm = rhythm
        decks.rhythm_target = active
        decks.drum_was_muted = False
        decks.stamp = 10.
        try:
            with patch('karaoke.transition_report.record'):
                decks.update(app, 10.1)
            self.assertIsNone(decks.rhythm)
            self.assertIsNone(decks.rhythm_target)
            active.set_channel.assert_called_with(9, muted=False)
            rhythm.close.assert_called_once()
            self.assertTrue(active.playing)
        finally:
            decks.close()

    def test_optional_drum_fill_cleanup_failure_keeps_preloaded_song(self):
        from pathlib import Path
        from karaoke.medley_decks import build

        class FakeMidiPlayer:
            instances = []
            def __init__(self, output=None):
                self.load = Mock()
                self.set_channel = Mock()
                self.set_key = Mock()
                self.set_speed = Mock()
                self.set_volume = Mock()
                self.seek = Mock()
                self.close = Mock()
                self.speed = 1.0
                self.__class__.instances.append(self)
                if len(self.instances) == 2:
                    self.seek.side_effect = ValueError('fill seek failed')
                    self.close.side_effect = OSError('fill close failed')

        song = MidiSong([], 1, Lyrics())
        bounds = TrimBounds(0, 5, 6, 1)
        with patch('karaoke.bass.BassSynth'), \
             patch('karaoke.playback.MidiPlayer', FakeMidiPlayer), \
             patch('karaoke.medley_full.source_bounds', return_value=bounds), \
             patch('karaoke.medley_full.drum_fill', return_value=song), \
             patch('karaoke.medley_full.can_play_fill', return_value=True):
            prepared, fill = build(Path('native'), {}, Path('next.mid'), 0, 100,
                                   False, None, full_song=True, fill=True)
        self.assertIs(prepared, FakeMidiPlayer.instances[0])
        self.assertIsNone(fill)
        FakeMidiPlayer.instances[1].close.assert_called_once()
        prepared.close.assert_not_called()

    def test_stop_tail_closes_both_decks_even_if_first_fails(self):
        decks = Decks()
        first, second = Mock(), Mock()
        first.close.side_effect = OSError('tail close failed')
        decks.tail, decks.rhythm = first, second
        try:
            with self.assertRaisesRegex(OSError, 'tail close failed'):
                decks.stop_tail()
            first.close.assert_called_once()
            second.close.assert_called_once()
            self.assertIsNone(decks.tail)
            self.assertIsNone(decks.rhythm)
        finally:
            decks.close()

    def test_close_shuts_down_preload_pool_after_tail_failure(self):
        decks = Decks()
        decks.tail = Mock()
        decks.tail.close.side_effect = OSError('tail failed')
        pool = decks.pool
        with self.assertRaisesRegex(OSError, 'tail failed'):
            decks.close()
        self.assertTrue(pool._shutdown)
        self.assertIsNone(decks.tail)

    def test_discard_closes_both_preloaded_decks_if_first_close_fails(self):
        first = Mock()
        second = Mock()
        first.close.side_effect = OSError('first deck cleanup failed')
        future = Future()
        future.set_result((first, second))
        decks = Decks()
        try:
            decks.future = future
            decks.key = ('queued',)
            decks.item = object()
            decks.discard()
            first.close.assert_called_once()
            second.close.assert_called_once()
            self.assertIsNone(decks.future)
            self.assertIsNone(decks.key)
            self.assertIsNone(decks.item)
        finally:
            decks.close()

    def test_preload_build_closes_both_decks_when_rhythm_setup_fails(self):
        from pathlib import Path
        from karaoke.medley_decks import build

        class FakeMidiPlayer:
            instances = []
            def __init__(self, output=None):
                self.load = Mock()
                self.set_channel = Mock()
                self.set_key = Mock()
                self.set_speed = Mock()
                self.set_volume = Mock()
                self.seek = Mock()
                self.set_loop = Mock()
                self.close = Mock()
                self.__class__.instances.append(self)
                if len(self.instances) == 1:
                    self.close.side_effect = OSError('engine close failed')
                else:
                    self.set_loop.side_effect = ValueError('rhythm setup failed')

        pattern = (MidiSong([], 2, Lyrics()), 2.0)
        with patch('karaoke.bass.BassSynth'), \
             patch('karaoke.playback.MidiPlayer', FakeMidiPlayer):
            with self.assertRaisesRegex(ValueError, 'rhythm setup failed'):
                build(Path('native'), {}, Path('queued.mid'), 0, 100,
                      False, pattern)
        self.assertEqual(len(FakeMidiPlayer.instances), 2)
        FakeMidiPlayer.instances[1].close.assert_called_once()
        FakeMidiPlayer.instances[0].close.assert_called_once()

    def test_fill_needs_explicit_metadata_and_exact_downbeat(self):
        song = MidiSong([], 8, Lyrics(), explicit_tempo=True, explicit_meter=True)
        fill = drum_fill(song, TrimBounds(1.65, 8, 8, 2), speed=1.25)
        self.assertAlmostEqual(fill.duration, 1.32)
        self.assertAlmostEqual(fill.initial_bpm, 150)
        self.assertTrue(all(event.data[0] & 15 == 9 for event in fill.events))
        self.assertIsNone(drum_fill(song, TrimBounds(0, 8, 8, .5), speed=1))
        self.assertIsNone(drum_fill(song, TrimBounds(0, 8, 8, 2), speed=1))
        song.explicit_meter = False
        self.assertIsNone(drum_fill(song, TrimBounds(0, 8, 8, 0), speed=1))

    def test_ordinary_song_does_not_mark_out_into_a_random_set(self):
        engine = NS(song=MidiSong([], 8, Lyrics()), duration=8, playing=True,
                    position=7, speed=1, set_volume=Mock())
        app = NS(engine=engine, current_item=QueueItem(1), volume_var=NS(get=lambda:80),
                 settings={'medley': {'enabled': True, 'bars': 2, 'crossfade': True, 'fade': 2}},
                 song_queue=NS(items=[QueueItem(2, medley_session='set')]),
                 next_song=Mock(), _medley_decks=Mock(rhythm=None))
        begin(app)
        tick(app)
        engine.set_volume.assert_called_once_with(.8)
        app.next_song.assert_not_called()

    def test_fill_requires_audible_entry_and_drum_preset(self):
        engine = NS(song=MidiSong([MidiEvent(0, b'\x93\x3c\x40')], 5, Lyrics()),
                    muted={3}, output=NS(options={'fonts': [{'path': 'instrument.sf2'}]}))
        with patch('karaoke.soundfont.inspect_font', return_value={'presets': [(128, 0, 'Drums')]}) as inspect:
            self.assertFalse(can_play_fill(engine, {}, 0))
            inspect.assert_not_called()
            engine.muted.clear()
            self.assertTrue(can_play_fill(engine, {}, 0))
            inspect.return_value = {'presets': [(0, 0, 'Piano')]}
            self.assertFalse(can_play_fill(engine, {}, 0))

    def test_full_song_tail_trim_respects_a_b_loop_and_then_advances(self):
        engine = NS(duration=8, playing=True, position=7, pause=Mock(),
                    medley_bounds=TrimBounds(0, 6.5, 8), loop_end=7.5)
        app = NS(engine=engine, current_item=QueueItem(1, medley_session='set'),
                 settings={'medley': {'enabled': True, 'bars': 2}}, song_queue=NS(items=[]),
                 on_song_ended=Mock(), lyrics=Lyrics(), offset_var=NS(get=lambda:0))
        begin(app)
        tick(app)
        engine.pause.assert_not_called()
        engine.loop_end = None
        tick(app)
        engine.pause.assert_called_once()
        app.on_song_ended.assert_called_once()

    def test_fill_follows_the_exact_queued_occurrence_and_can_pause(self):
        incoming = QueueItem(2, medley_session='set')
        outgoing = QueueItem(1, medley_session='set')
        song = MidiSong([], 8, Lyrics(), explicit_tempo=True, explicit_meter=True)
        target = NS(song=song, speed=1., medley_bounds=TrimBounds(0, 8, 8, 0))
        player = NS(playing=True, ended=False, scheduler_error=None, pause=Mock(),
                    play=Mock(), enable_scheduler=Mock(), set_volume=Mock(), seek=Mock())
        future = Future()
        future.set_result((target, player))
        decks = NS(future=future, matches=Mock(side_effect=lambda item, _app: item is incoming))
        app = NS(current_item=outgoing, song_queue=NS(items=[incoming]), _medley_decks=decks,
                 library=NS(get=lambda _: {'path':'fixture.mid'}), settings={}, status_var=Mock(),
                 volume_var=NS(get=lambda:80), next_song=Mock())
        self.assertTrue(end_random_medley(app))
        self.assertTrue(toggle_random_fill(app))
        player.pause.assert_called_once()
        app.song_queue.items[0] = QueueItem(2, medley_session='set')
        tick(app)
        self.assertNotIn('_random_medley_fill', app.__dict__)
        app.next_song.assert_called_once()
        self.assertFalse(end_random_medley(app))

    def test_stopping_a_fill_without_advancing_leaves_pending_song(self):
        item = QueueItem(2, medley_session='set')
        player = NS(playing=True, pause=Mock())
        app = NS(song_queue=NS(items=[item]), next_song=Mock(),
                 _random_medley_fill=(item, player))
        cancel_random_fill(app)
        player.pause.assert_called_once()
        self.assertEqual(app.song_queue.items, [item])
        app.next_song.assert_not_called()

    def test_same_song_parameters_do_not_match_another_occurrence(self):
        first = QueueItem(2, medley_session='set')
        second = QueueItem(2, medley_session='set')
        decks = Decks()
        self.addCleanup(decks.close)
        decks.key, decks.item = (2, 0, 100), first
        decks.future = Future()
        decks.future.set_result((Mock(), None))
        self.assertTrue(decks.matches(first))
        self.assertFalse(decks.matches(second))
