import queue
import unittest
from concurrent.futures import Future
from types import SimpleNamespace as NS
from unittest.mock import Mock
from karaoke.audio_device import acquire,release
from karaoke.keyboard_controls import PreviewVoice
from karaoke.midi_input import MidiInput
from karaoke.medley_decks import Decks,drum_pattern
from karaoke.smf import MidiSong,MidiEvent
from karaoke.lyrics import Lyrics

class LiveAudioTests(unittest.TestCase):
    def test_shared_device_freed_only_after_last_user(self):
        dll=Mock();dll.BASS_Init.return_value=1;dll.BASS_GetDevice.return_value=1
        a,_=acquire(dll);b,_=acquire(dll)
        dll.BASS_Init.assert_called_once()
        release(dll,a);dll.BASS_Free.assert_not_called()
        release(dll,b);release(dll,b);dll.BASS_Free.assert_called_once()
    def test_foreign_device_not_adopted_or_freed(self):
        dll=Mock();dll.BASS_Init.return_value=0;dll.BASS_ErrorGetCode.return_value=14
        with self.assertRaises(OSError):acquire(dll)
        dll.BASS_Free.assert_not_called()
    def test_pc_chord_and_shared_note_source_release(self):
        out=Mock();voice=PreviewVoice(lambda:out)
        for n in (60,64,67):voice.press(n,source='pc')
        voice.press(60,source='midi');voice.off(60,'pc')
        self.assertEqual(voice.notes,{60,64,67})
        voice.release_source('pc');self.assertEqual(voice.notes,{60})
        voice.off(60,'midi');self.assertFalse(voice.notes)
        voice.close()
    def test_midi_velocity_note_off_pedal_and_overflow(self):
        out=Mock();voice=PreviewVoice(lambda:out)
        port=MidiInput.__new__(MidiInput);port.events=queue.Queue();port.overflow=False
        for data in (bytes([0x91,60,80]),bytes([0x91,64,90])):port.events.put(int.from_bytes(data,'little'))
        port.drain(voice);self.assertEqual(voice.notes,{60,64})
        out.send.assert_any_call(bytes([0x90,60,80]))
        port.events.put(int.from_bytes(bytes([0x91,60,0]),'little'));port.drain(voice)
        self.assertEqual(voice.notes,{64})
        port.overflow=True;port.drain(voice);self.assertFalse(voice.notes)
    def test_drum_pattern_excludes_other_channels_and_keeps_setup(self):
        song=MidiSong([MidiEvent(0,bytes([0xc9,8])),MidiEvent(2,bytes([0x99,36,90])),MidiEvent(2.1,bytes([0x89,36,0])),MidiEvent(2.2,bytes([0x90,60,90]))],8,Lyrics())
        pattern,duration=drum_pattern(song,4)
        self.assertEqual(duration,2);self.assertTrue(all(e.data[0]&15==9 for e in pattern.events))
        self.assertEqual(pattern.events[0].data,bytes([0xc9,8]))
        self.assertIsNone(drum_pattern(MidiSong([],8,Lyrics()),4))
    def test_discard_inflight_deck_closes_both_outputs_on_completion(self):
        decks=Decks();future=Future();future.set_running_or_notify_cancel();decks.future=future
        decks.discard();a,b=Mock(),Mock();future.set_result((a,b))
        a.close.assert_called_once();b.close.assert_called_once();decks.close()
    def test_prepared_song_must_match_queue_occurrence(self):
        decks=Decks();decks.key=(2,3,100);decks.future=Future();engine=Mock()
        decks.future.set_result((engine,None))
        self.assertIsNone(decks.take(NS(song_id=2,key=0,speed=100)))
        self.assertEqual(decks.take(NS(song_id=2,key=3,speed=100)),(engine,None));decks.close()
    def test_overlap_fades_both_and_closes_only_old_deck(self):
        decks=Decks();old=Mock(playing=True,ended=False);new=Mock(playing=True,ended=False)
        app=NS(engine=new,volume_var=NS(get=lambda:100),system_volume=None)
        decks.attach(old,None,app,2);decks.stamp=0
        decks.update(app,1)
        self.assertAlmostEqual(old.set_volume.call_args.args[0],2**-.5)
        self.assertAlmostEqual(new.set_volume.call_args.args[0],2**-.5)
        decks.update(app,2);old.close.assert_called_once();new.close.assert_not_called();decks.close()

    def test_ui_promotes_preloaded_midi_without_closing_outgoing_audio(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from karaoke.ui import KaraokeApp
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'next.mid';path.touch()
            old=Mock();new=Mock(duration=8,song=NS(lyrics=Lyrics()))
            decks=Mock();decks.take.return_value=(new,None)
            app=NS(engine=old,_medley_overlap=True,_medley_decks=decks,
                library=NS(get=lambda _:dict(path=str(path),title='next')),
                settings={'medley':dict(enabled=True,crossfade=True,fade=2)},home=Path(folder),
                melody_var=Mock(),key_box=Mock(),volume_var=NS(get=lambda:80),
                key_var=Mock(),speed_var=Mock(),offset_var=Mock(),now_var=Mock(),seek=Mock(),
                show_main_media=Mock(),update_stage_mode=Mock(),resize_video=Mock(),status_var=Mock(),report_load_error=Mock())
            item=NS(song_id=2,key=0,speed=100,singer='')
            with patch('karaoke.ui.sidecar_lyrics',return_value=None),patch('karaoke.equalizer.output_for',return_value=None):
                self.assertTrue(KaraokeApp.start_song(app,item))
            self.assertIs(app.engine,new);new.load.assert_not_called();new.play.assert_called_once()
            old.close.assert_not_called();decks.attach.assert_called_once_with(old,None,app,2)

    def test_natural_end_reuses_prepared_decks_for_three_songs(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from karaoke.ui import KaraokeApp
        from karaoke.performer import PlaybackApp
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'next.mid';path.touch()
            engines=[Mock(duration=8,song=NS(lyrics=Lyrics())) for _ in range(3)]
            decks=Decks();items=[NS(song_id=i,key=0,speed=100,singer='') for i in (2,3)]
            app=NS(engine=engines[0],_medley_decks=decks,song_queue=NS(items=items),
                library=NS(get=lambda _:dict(path=str(path),title='next')),
                settings={'medley':dict(enabled=True,crossfade=False,fade=0)},home=Path(folder),
                melody_var=Mock(),key_box=Mock(),volume_var=NS(get=lambda:80),
                key_var=Mock(),speed_var=Mock(),offset_var=Mock(),now_var=Mock(),seek=Mock(),
                show_main_media=Mock(),update_stage_mode=Mock(),resize_video=Mock(),status_var=Mock(),report_load_error=Mock())
            def next_song():
                self.assertTrue(app._medley_prepared)
                self.assertTrue(KaraokeApp.start_song(app,items[0]))
                items.pop(0)
            app.next_song=next_song
            with patch('karaoke.ui.sidecar_lyrics',return_value=None),patch('karaoke.equalizer.output_for',return_value=None):
                for index in (1,2):
                    from karaoke.medley_decks import preparation_key
                    app.melody_var.get.return_value=False
                    decks.key=preparation_key(app,items[0],path);decks.future=Future();decks.future.set_result((engines[index],None))
                    PlaybackApp.on_song_ended(app)
                    self.assertIs(app.engine,engines[index]);self.assertNotIn('_medley_prepared',app.__dict__)
                    engines[index].load.assert_not_called();engines[index].play.assert_called_once()
                    engines[index-1].close.assert_called_once()
            self.assertEqual(items,[]);decks.close()

    def test_prepared_flag_cleared_when_advancing_raises(self):
        from karaoke.medley_decks import advance_prepared
        decks=Mock();decks.matches.return_value=True
        app=NS(_medley_decks=decks,song_queue=NS(items=[object()]),next_song=Mock(side_effect=OSError('device')))
        with self.assertRaises(OSError):advance_prepared(app)
        self.assertNotIn('_medley_prepared',app.__dict__)
