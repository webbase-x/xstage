import ctypes as C
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
import numpy as np
from karaoke.library import QueueItem,SongQueue,write_json,read_json
from karaoke.performance_features import PlayHistory
from karaoke.font_mapping import font_entries
from karaoke.medley import mark_out,options,begin,tick
from karaoke.smf import MidiSong
from karaoke.lyrics import Lyrics
from karaoke.media_routing import route_samples,StereoRouter
from karaoke.playback import MediaPlayer
from karaoke.stage_fx import FxRack

class QueueHistoryTests(unittest.TestCase):
    def test_insert_preserves_occurrences_and_persistence(self):
        with tempfile.TemporaryDirectory() as folder:
            q=SongQueue(Path(folder)/'queue.json');a=QueueItem(1,key=3);b=QueueItem(1,key=-2);q.add(a);q.insert(0,b)
            self.assertEqual([x.key for x in SongQueue(q.path).items],[-2,3]);self.assertIs(q.items[1],a)
            with patch.object(q,'save',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):q.insert(1,QueueItem(2))
            self.assertEqual(len(q.items),2)
    def test_history_replay_clears_session_and_keeps_song_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);song=root/'เพลง.mid';song.touch();h=PlayHistory(root/'history.json')
            item=QueueItem(1,'ผู้ร้อง',3,110,'private-session');h.start(item,dict(title='เพลง',path=str(song)));item.key=5;h.finish('completed',item)
            item=h.item(0,NS(get=lambda _:dict(path=str(song))))
            self.assertEqual((item.key,item.speed,item.singer,item.request_id),(5,110,'ผู้ร้อง',''))
            self.assertEqual(PlayHistory(h.path).rows[0]['status'],'completed')
            with self.assertRaises(ValueError):h.item(0,NS(get=lambda _:dict(path='wrong.mid')))
    def test_history_limits_and_recovers_interrupted_session(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'history.json';row=dict(time='now',title='song',path='a.mid',status='playing',item=dict(song_id=1))
            write_json(p,[row]*501);h=PlayHistory(p);self.assertEqual(len(h.rows),500);self.assertEqual(h.rows[-1]['status'],'interrupted')
            write_json(p,[{},None,dict(row,item={'song_id':'bad'})])
            from karaoke.library import JsonRecoveryError
            with self.assertRaises(JsonRecoveryError):PlayHistory(p)
            self.assertEqual(len(read_json(p,[])),3)

class MappingRoutingTests(unittest.TestCase):
    def test_specific_guitar_and_drums_precede_default_stack(self):
        options=dict(fonts=[dict(path='a.sf2'),dict(path='b.sf2')]);entries=font_entries(options,[11,22],dict(guitar='b.sf2',drums='a.sf2'))
        self.assertEqual(entries[:8],[(22,p,0) for p in range(24,32)])
        self.assertIn((11,0,128),entries);self.assertEqual(entries[-2:],[(11,-1,0),(22,-1,0)])
        with self.assertRaises(ValueError):font_entries(options,[11,22],dict(bass='missing.sf2'))
    def test_removing_font_clears_only_its_mappings(self):
        from karaoke.font_mapping import retained_mapping
        self.assertEqual(retained_mapping(dict(guitar='a.sf2',bass='b.sf2'),[dict(path='a.sf2')]),dict(guitar='a.sf2'))
    def test_source_selection_and_stereo_bypass(self):
        a=np.array([[.1,.2],[.3,.4]],dtype=np.float32);b=a.copy();route_samples(b,'left');np.testing.assert_allclose(b[:,0],b[:,1])
        b=a.copy();route_samples(b,'right');np.testing.assert_allclose(b[:,0],a[:,1])
        b=a.copy();route_samples(b,'stereo');np.testing.assert_array_equal(a,b)
    def test_native_dsp_callback_changes_float_samples_and_is_removed(self):
        dll=Mock()
        def info(stream,p):p._obj.chans=2;p._obj.flags=0x100;return 1
        dll.BASS_ChannelGetInfo.side_effect=info;dll.BASS_ChannelSetDSP.return_value=77
        router=StereoRouter(dll,2);router.set('right');array=(C.c_float*4)(.1,.2,.3,.4)
        router.callback(77,2,C.addressof(array),16,None)
        self.assertAlmostEqual(array[0],.2,places=5);self.assertAlmostEqual(array[2],.4,places=5)
        router.close();router.close();dll.BASS_ChannelRemoveDSP.assert_called_once_with(2,77)
    def test_mci_channel_failure_restores_previous_selection(self):
        p=MediaPlayer.__new__(MediaPlayer);p.alias='test';p.audio_mode='stereo';p.command=Mock(side_effect=[None,OSError('unsupported'),None,None])
        with self.assertRaises(OSError):p.set_audio_mode('left')
        self.assertEqual(p.audio_mode,'stereo');self.assertEqual(p.command.call_args.args[0],'setaudio test right on')
    def test_track_selection_records_only_success(self):
        p=MediaPlayer.__new__(MediaPlayer);p.alias='test';p.command=Mock();p.set_audio_track(2)
        p.command.assert_called_with('setaudio test stream to 2');self.assertEqual(p.audio_track,2)
        p.command.side_effect=OSError('no track')
        with self.assertRaises(OSError):p.set_audio_track(3)
        self.assertEqual(p.audio_track,2)

class MedleyTests(unittest.TestCase):
    def song(self):return MidiSong([],8,Lyrics(),initial_bpm=120,division=480)
    def app(self):
        engine=NS(song=self.song(),position=0.,duration=8.,speed=1.,playing=True,set_volume=Mock(),set_speed=Mock())
        app=NS(engine=engine,settings={'medley':dict(enabled=True,bars=1,fade=1,keep_bpm=False)},song_queue=NS(items=[QueueItem(2)]),volume_var=NS(get=lambda:80),system_volume=None,next_song=Mock(),current_item=QueueItem(1),speed_var=Mock())
        begin(app);app._medley_state['stamp']=0;return app
    def test_mark_out_uses_musical_bars_and_tempo_changes(self):
        song=self.song();self.assertEqual(mark_out(song,1),6);self.assertEqual(mark_out(song,2),4)
        song.tempo_map=[(0,0.,500000),(1920,2.,1000000)];song.duration=14
        self.assertEqual(mark_out(song,1),10)
        song.signatures=[(0,3,4)];song.tempo_map=[(0,0.,500000)];song.duration=6
        self.assertEqual(mark_out(song,1),4.5)
    def test_transition_once_pause_and_no_queue(self):
        app=self.app();app.engine.position=5.5;tick(app,2);app.engine.set_volume.assert_called_with(.4)
        app.engine.playing=False;app.engine.position=6;tick(app,3);app.next_song.assert_not_called()
        app.engine.playing=True;tick(app,4);tick(app,5);app.next_song.assert_called_once()
        app=self.app();app.song_queue.items=[];app.engine.position=7;tick(app,2);app.next_song.assert_not_called();app.engine.set_volume.assert_called_with(.8)
    def test_keep_bpm_changes_only_started_occurrence_and_clamps(self):
        app=self.app();app.settings['medley']['keep_bpm']=True;app._medley_carry=240;begin(app)
        app.engine.set_speed.assert_called_with(1.5);self.assertEqual(app.current_item.speed,150)
        self.assertEqual(app.song_queue.items[0].speed,100)
    def test_invalid_options_rejected(self):
        with self.assertRaises(ValueError):options({'medley':dict(fade=float('nan'))})
        with self.assertRaises(ValueError):options({'medley':dict(bars=1.5)})

class FxTests(unittest.TestCase):
    def test_polyphony_limit_and_cleanup_on_load_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'a.wav';path.touch();players=[]
            def factory(path):
                p=Mock(duration=1,ended=False);players.append(p);return p
            rack=FxRack(factory)
            for _ in range(5):rack.play(path)
            self.assertEqual(len(rack.players),4);players[0].close.assert_called_once()
            rack.close();self.assertEqual(rack.players,[])
            bad=Mock();bad.load.side_effect=OSError('bad file');rack=FxRack(lambda path:bad)
            with self.assertRaises(OSError):rack.play(path)
            bad.close.assert_called_once();self.assertFalse(rack.players)
    def test_long_effect_rejected_and_original_file_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'a.wav';path.write_bytes(b'original');p=Mock(duration=61,ended=False);rack=FxRack(lambda path:p)
            with self.assertRaises(ValueError):rack.play(path)
            p.close.assert_called_once();self.assertEqual(path.read_bytes(),b'original')

class IconTests(unittest.TestCase):
    def test_icon_contains_small_and_large_windows_sizes(self):
        from PIL import Image
        path=Path(__file__).resolve().parents[1]/'assets/xstage.ico'
        with Image.open(path) as icon:self.assertTrue({(16,16),(32,32),(48,48),(256,256)}<=icon.ico.sizes())
