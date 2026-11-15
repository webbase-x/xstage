import ctypes as C
import tempfile
import time
import unittest
import wave
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock,patch
import numpy as np
from karaoke.pcm_player import PcmPlayer
from karaoke.equalizer import Equalizer,Parameters
from karaoke.mixed_recording import MixedRecorder,mix_frames
from karaoke.library import song_supports_key

class FakeBass:
    def __init__(self):
        names=['Init','Free','ErrorGetCode','GetDevice','SetDevice','SetConfig','StreamCreateFile','StreamFree','ChannelPlay','ChannelPause','ChannelStop','ChannelIsActive','ChannelSetAttribute','ChannelGetPosition','ChannelGetLength','ChannelBytes2Seconds','ChannelSeconds2Bytes','ChannelSetPosition','ChannelSetFX','ChannelRemoveFX','FXSetParameters','ChannelGetAttribute']
        for name in names:setattr(self,'BASS_'+name,Mock(return_value=1))
        self.BASS_StreamCreateFile.return_value=11;self.BASS_ChannelGetLength.return_value=480000
        self.BASS_ChannelBytes2Seconds.side_effect=lambda stream,value:value/48000
        self.BASS_ChannelSeconds2Bytes.side_effect=lambda stream,value:int(value*48000)
        self.BASS_ChannelGetAttribute.side_effect=lambda stream,attr,pointer:setattr(pointer._obj,'value',22050) or 1
        self.BASS_ChannelSetFX.side_effect=[101,102,103]

def player():
    dll=FakeBass();fx=Mock();fx.BASS_FX_TempoCreate.return_value=22
    return PcmPlayer('.',bindings=(dll,fx)),dll,fx

class PcmTests(unittest.TestCase):
    def test_independent_controls_and_stream_ownership(self):
        p,d,f=player();p.load('เพลง.mp3');p.set_key(3);p.set_speed(1.2);p.set_volume(.5)
        self.assertEqual((p.key,p.speed,p.duration),(3,1.2,10))
        self.assertEqual([c.args[1] for c in d.BASS_ChannelSetAttribute.call_args_list],[0x10001,0x10000,2])
        p.seek(200);d.BASS_ChannelSetPosition.assert_called_with(22,480000,0)
        p.close();p.close();d.BASS_StreamFree.assert_called_once_with(22);d.BASS_Free.assert_called_once()
    def test_load_failure_frees_owned_source(self):
        p,d,f=player();f.BASS_FX_TempoCreate.return_value=0
        with self.assertRaises(OSError):p.load('a.wav')
        p.close();d.BASS_StreamFree.assert_called_once_with(11)
    def test_failed_key_does_not_change_state(self):
        p,d,f=player();p.load('a.wav');d.BASS_ChannelSetAttribute.return_value=0
        with self.assertRaises(OSError):p.set_key(3)
        self.assertEqual(p.key,0)
        with self.assertRaises(ValueError):p.set_speed(float('nan'))
        p.close()
    def test_stall_is_not_end_and_pause_does_not_advance_queue(self):
        p,d,f=player();p.load('a.wav');p.play();d.BASS_ChannelIsActive.return_value=2;p.pump();self.assertFalse(p.ended)
        p.pause();d.BASS_ChannelIsActive.return_value=0;p.pump();self.assertFalse(p.ended)
        p.play();p.pump();self.assertTrue(p.ended);p.close()
    def test_key_capability_depends_on_backend(self):
        for enabled in (False,True):
            with patch('karaoke.pcm_player.available',return_value=enabled):
                for ext in ('.wav','.mp3'):self.assertEqual(song_supports_key({'path':'song'+ext}),enabled)
                self.assertFalse(song_supports_key({'path':'song.mp4'}))
    def test_eq_rate_limit_and_transaction(self):
        d=FakeBass();eq=Equalizer(d,1);self.assertEqual(eq.frequencies[-1],7350)
        eq.set([2,3,4]);d.BASS_FXSetParameters.side_effect=[1,0,1,1,1]
        with self.assertRaises(OSError):eq.set([5,6,7])
        self.assertEqual(eq.gains,[2,3,4])
        with self.assertRaises(ValueError):eq.set([float('nan'),0,0])
        eq.close();self.assertEqual(d.BASS_ChannelRemoveFX.call_count,3)

class MixedTests(unittest.TestCase):
    def test_mix_clip_and_nonfinite(self):
        mic=np.array([[1.,1.],[np.nan,.2]])
        music=np.array([[1.,-1.],[.5,.2]])
        pcm,peak,clips=mix_frames(mic,music,1,1)
        self.assertEqual(clips,1);self.assertEqual(peak,2)
        self.assertEqual(np.frombuffer(pcm,dtype='<i2').tolist(),[32767,0,16383,13106])
    def test_invalid_shape_and_gain(self):
        with self.assertRaises(ValueError):mix_frames(np.zeros((2,2)),np.zeros((3,2)))
        with self.assertRaises(ValueError):mix_frames(np.zeros((2,2)),np.zeros((2,2)),float('nan'),1)
    def test_record_closes_valid_stereo_file_and_stops_workers(self):
        @contextmanager
        def source(kind,device,rate,block):
            def read(numframes):time.sleep(.015);return np.full((numframes or 0,2),.1 if kind=='mic' else .2)
            yield Mock(record=read)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'เสียง.wav';r=MixedRecorder(path,'mic',1,1,source=source);r.start()
            deadline=time.monotonic()+3
            while r.frames<9600 and time.monotonic()<deadline:time.sleep(.01)
            self.assertTrue(r.stop());self.assertIsNone(r.error);self.assertGreaterEqual(r.frames,9600)
            with wave.open(str(path),'rb') as out:
                self.assertEqual((out.getnchannels(),out.getframerate(),out.getnframes()),(2,48000,r.frames))
                self.assertTrue(np.all(np.frombuffer(out.readframes(1),dtype='<i2')==9830))
    def test_failed_device_closes_file_and_unblocks_other_device(self):
        @contextmanager
        def source(kind,*args):
            if kind=='mic':raise OSError('device unplugged')
            yield Mock()
        with tempfile.TemporaryDirectory() as folder:
            r=MixedRecorder(Path(folder)/'a.wav','mic',source=source);r.start();r.thread.join(3)
            self.assertFalse(r.running);self.assertIn('device unplugged',str(r.error));self.assertTrue(r.stop())
            with wave.open(str(r.path),'rb') as f:self.assertEqual(f.getnframes(),0)

if __name__=='__main__':unittest.main()

class DiagnosticsTests(unittest.TestCase):
    def test_tone_and_silence_are_distinguished(self):
        from karaoke.audio_diagnostics import analyze_output
        rate=48000;tone=.08*np.sin(2*np.pi*880*np.arange(rate)/rate)
        self.assertTrue(analyze_output(np.column_stack((tone,tone)),rate)['test_tone_detected'])
        self.assertFalse(analyze_output(np.zeros((rate,2)),rate)['test_tone_detected'])
        other=.08*np.sin(2*np.pi*440*np.arange(rate)/rate)
        self.assertFalse(analyze_output(np.column_stack((other,other)),rate)['test_tone_detected'])
    def test_invalid_samples_are_reported(self):
        from karaoke.audio_diagnostics import analyze_output
        data=np.zeros((9600,2));data[0,0]=np.nan;data[1,0]=1.2
        result=analyze_output(data,48000)
        self.assertEqual(result['invalid_samples'],1);self.assertEqual(result['clipped_samples'],1)
