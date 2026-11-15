from array import array
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from karaoke.audio_benchmark import run, metrics, choose, Cancelled, FRAMES
from soundfont_fixture import make_font


class Clock:
    def __init__(self): self.t = 0.
    def __call__(self): return self.t


class FakeSynth:
    def __init__(self, clock, seconds=.001, payload=None):
        self.clock, self.seconds = clock, seconds
        self.payload = payload if payload is not None else array('f', [.01]*(FRAMES*2)).tobytes()
        self.closed = False
        self.sent = []
    def send(self, msg): self.sent.append(msg)
    def reset(self): pass
    def render(self, frames):
        self.clock.t += self.seconds
        return self.payload
    def close(self): self.closed = True


class BenchmarkTests(unittest.TestCase):
    def setup_run(self, folder, factory, clock, cancel=None):
        path = make_font(Path(folder)/'test.sf2')
        return run(Path(folder), {'fonts':[{'path':str(path)}], 'quality_mode':'auto'},
                   cancel or threading.Event(), factory=factory, clock=clock, groups=1, blocks=3)

    def test_actual_render_pipeline_chooses_highest_passing_and_closes(self):
        clock = Clock()
        made = []
        calls = []
        def factory(native, settings, decode):
            calls.append((settings, decode))
            s = FakeSynth(clock, .006 if settings['soundfont_audio']['quality']==2 else .002)
            made.append(s)
            return s
        with tempfile.TemporaryDirectory() as folder:
            result = self.setup_run(folder, factory, clock)
        self.assertEqual(result['recommended']['quality'], 1)
        self.assertEqual(len(result['rows']),3)
        self.assertTrue(all(s.closed for s in made))
        self.assertTrue(all(decode and s['soundfont_audio']['quality_mode']=='manual' for s,decode in calls))
        self.assertFalse(result['output_driver_tested'])
        self.assertTrue(any(msg[0] == 0x99 for msg in made[0].sent))

    def test_thresholds_do_not_accept_spikes_or_silence(self):
        self.assertTrue(metrics([.002]*100,.1)['passed'])
        self.assertFalse(metrics([.002]*99+[.012],.1)['passed'])
        self.assertFalse(metrics([.002]*90+[.006]*10,.1)['passed'])
        self.assertFalse(metrics([.002]*100,0)['passed'])
        self.assertIsNone(choose([dict(passed=False,settings={})]))

    def test_cancel_before_native_load(self):
        event = threading.Event()
        event.set()
        factory = Mock()
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(Cancelled):
            self.setup_run(folder, factory, Clock(), event)
        factory.assert_not_called()

    def test_cancel_during_render_releases_synth(self):
        clock, event = Clock(), threading.Event()
        synth = FakeSynth(clock)
        original = synth.render
        def render(frames):
            event.set()
            return original(frames)
        synth.render = render
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(Cancelled):
            self.setup_run(folder, lambda *a,**kw:synth, clock, event)
        self.assertTrue(synth.closed)

    def test_invalid_pcm_and_native_error_close_without_result(self):
        for payload in (b'', array('f',[float('nan')]*(FRAMES*2)).tobytes()):
            clock = Clock()
            synth = FakeSynth(clock, payload=payload)
            with tempfile.TemporaryDirectory() as folder, self.assertRaises(ValueError):
                self.setup_run(folder, lambda *a,**kw:synth, clock)
            self.assertTrue(synth.closed)
        clock = Clock()
        synth = FakeSynth(clock)
        synth.render = Mock(side_effect=OSError('native failed'))
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(OSError):
            self.setup_run(folder, lambda *a,**kw:synth, clock)
        self.assertTrue(synth.closed)

    def test_initial_load_is_separate_and_report_retains_warning(self):
        clock = Clock()
        def factory(*args, **kwargs):
            synth = FakeSynth(clock)
            original = synth.render
            n = [0]
            def render(frames):
                n[0]+=1
                if n[0]==1: clock.t+=.1
                return original(frames)
            synth.render = render
            return synth
        with tempfile.TemporaryDirectory() as folder:
            result = self.setup_run(folder, factory, clock)
        self.assertGreater(result['rows'][0]['initial_worst_ms'],100)
        self.assertTrue(result['rows'][0]['passed'])
        self.assertIn('ไดรเวอร์',result['warning'])

    def test_uses_full_gm_program_range_and_progress_finishes(self):
        clock, made, updates = Clock(), [], []
        def factory(*args,**kwargs):
            s=FakeSynth(clock)
            made.append(s)
            return s
        with tempfile.TemporaryDirectory() as folder:
            path=make_font(Path(folder)/'test.sf2')
            run(Path(folder),{'fonts':[{'path':str(path)}]},threading.Event(),
                updates.append,factory=factory,clock=clock,groups=9,blocks=1)
        programs={msg[1] for msg in made[0].sent if msg[0]&0xf0==0xc0 and msg[0]!=0xc9}
        self.assertEqual(programs,set(range(128)))
        self.assertEqual(updates[-1]['percent'],100)
        self.assertEqual(sorted(v['percent'] for v in updates),[v['percent'] for v in updates])


    def test_apply_is_manual_and_requires_explicit_save(self):
        from types import SimpleNamespace
        from karaoke.audio_benchmark_dialog import BenchmarkWindow
        owner = SimpleNamespace(quality_mode=Mock(), quality=Mock(), voices=Mock(),
            buffer_ms=Mock(), auto_detail=Mock(), status=Mock(), update_auto=Mock(), save=Mock())
        dialog = SimpleNamespace(running=False, result={'recommended':dict(quality=1,voices=256,buffer_ms=150)},
                                 owner=owner, close=Mock())
        BenchmarkWindow.apply(dialog)
        owner.quality_mode.set.assert_called_once_with('manual')
        owner.quality.set.assert_called_once_with('1')
        owner.save.assert_not_called()
        dialog.close.assert_called_once()
