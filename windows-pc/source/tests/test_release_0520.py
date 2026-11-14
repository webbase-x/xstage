import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from karaoke.classic import ClassicApp, MidiPlayer
from karaoke.ui import KaraokeApp
from karaoke.library import SongQueue, QueueItem

class Var:
    def __init__(self, value=None, **kw): self.value=value
    def get(self): return self.value
    def set(self, value): self.value=value

class ReleaseTests(unittest.TestCase):
    def queue_app(self, root, count, outcomes):
        queue=SongQueue(root/'queue.json')
        for i in range(count): queue.add(QueueItem(i+1))
        app=NS(song_queue=queue, library=Mock(get=lambda i:{'title':str(i)}),
            refresh_queue=Mock(), status_var=Var('playing'), on_song_ended=Mock(),
            start_song=Mock(), cancel_current_song=Mock())
        pending=iter(outcomes)
        def start(item, quiet=False):
            value=next(pending)
            if isinstance(value, Exception): raise value
            app.last_load_error_kind='file'
            return value
        app.start_song.side_effect=start
        return app

    def test_skip_failures_then_play_and_persist_remaining_queue(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);app=self.queue_app(root,4,[False,False,True])
            with self.assertLogs(level='WARNING') as log: KaraokeApp.next_song(app)
            self.assertEqual([i.song_id for i in app.song_queue.items],[4])
            self.assertEqual([i.song_id for i in SongQueue(root/'queue.json').items],[4])
            self.assertEqual(len(app.queue_skip_report),2)
            self.assertEqual(len(log.output),2)
            self.assertTrue(all(c.kwargs=={'quiet':True} for c in app.start_song.call_args_list))
            app.on_song_ended.assert_not_called()

    def test_system_failure_preserves_current_and_remaining_queue(self):
        with tempfile.TemporaryDirectory() as folder:
            app=self.queue_app(Path(folder),3,[False,OSError('audio unavailable'),False])
            with self.assertLogs(): KaraokeApp.next_song(app)
            app.on_song_ended.assert_not_called()
            app.cancel_current_song.assert_called_once()
            self.assertEqual([i.song_id for i in app.song_queue.items],[2,3])
            self.assertEqual(app.start_song.call_count,2)

    def test_selected_tail_failure_wraps_without_index_error(self):
        with tempfile.TemporaryDirectory() as folder:
            app=self.queue_app(Path(folder),2,[False,True])
            with self.assertLogs(): KaraokeApp.next_song(app,1)
            self.assertEqual([c.args[0].song_id for c in app.start_song.call_args_list],[2,1])

    def test_quiet_failure_does_not_display_modal(self):
        app=NS(show_error=Mock())
        KaraokeApp.report_load_error(app,'missing',quiet=True)
        app.show_error.assert_not_called()
        self.assertEqual(app.last_load_error,'missing')
        KaraokeApp.report_load_error(app,'manual')
        app.show_error.assert_called_once_with('manual')

    def lyric_app(self, path):
        return NS(settings={},current_song={'path':path},save_settings=Mock(),
            paint_lyrics=Mock(),status_var=Var(),lyrics=object())

    def test_saved_lrc_applies_now_and_persists_override(self):
        app=self.lyric_app('a.mid')
        ClassicApp.apply_saved_lyrics(app,'a.mid','a.lrc','[00:01.00]hello')
        self.assertEqual(app.lyrics.lines[0].text,'hello')
        self.assertEqual(app.settings['lyric_files']['a.mid'],str(Path('a.lrc').resolve()))
        app.save_settings.assert_called_once();app.paint_lyrics.assert_called_once()

    def test_editor_bound_song_cannot_replace_next_song_lyrics(self):
        app=self.lyric_app('b.mid');old=app.lyrics
        ClassicApp.apply_saved_lyrics(app,'a.mid','a.lrc','[00:01.00]hello')
        self.assertIs(app.lyrics,old)
        self.assertIn('a.mid',app.settings['lyric_files'])
        app.paint_lyrics.assert_not_called()

    def test_invalid_lrc_keeps_settings(self):
        app=self.lyric_app('a.mid')
        with self.assertRaises(ValueError): ClassicApp.apply_saved_lyrics(app,'a.mid','a.lrc','no timestamp')
        self.assertEqual(app.settings,{})
        app.save_settings.assert_not_called()

    def test_remote_values_clamp_and_reject_nonfinite(self):
        app=NS(engine=Mock(spec=MidiPlayer),volume_var=Var(80),key_var=Var(0),speed_var=Var(100),
            apply_volume=Mock(),apply_key=Mock(),apply_speed=Mock(),update_remote_snapshot=Mock())
        for action,value,expected in [('volume',140,100),('key',-20,-12),('speed',10,50)]:
            ClassicApp.apply_remote(app,{'action':action,'value':value})
            self.assertEqual(getattr(app,action+'_var').get(),expected)
        for value in ['NaN','Infinity','bad']:
            with self.assertRaises(ValueError): ClassicApp.apply_remote(app,{'action':'volume','value':value})

    def test_remote_snapshot_carries_actual_control_values(self):
        app=NS(current_song=None,engine=None,volume_var=Var(74),key_var=Var(2),speed_var=Var(95),
            song_queue=NS(items=[]),snapshot_lock=threading.Lock())
        ClassicApp.update_remote_snapshot(app)
        self.assertEqual([app.remote_state[k] for k in ('volume','key','speed')],[74,2,95])

    def test_mixer_follows_new_engine_and_cancels_poll_on_close(self):
        def engine(gain):
            e=Mock(spec=MidiPlayer)
            e.channel_gain=[gain]*16;e.pan=[64]*16;e.program=[None]*16
            e.muted=set();e.solo=set();e.drum_muted=set();e.position=10
            return e
        first,second=engine(.8),engine(.4)
        widgets=[];window=Mock();window.after.return_value='timer1'
        def widget(*args,**kw):
            w=Mock();w.options=kw;widgets.append(w);return w
        app=NS(engine=first,current_song={'title':'first'},settings={},save_settings=Mock(),status_var=Var())
        with ExitStack() as stack:
            stack.enter_context(patch('karaoke.classic.DialogWindow',return_value=window))
            stack.enter_context(patch('karaoke.classic.WinMidi.devices',return_value=[]))
            stack.enter_context(patch('karaoke.classic.ActionBar',side_effect=widget))
            for name in ['Frame','Label','Button','Combobox','Notebook','Scale','Checkbutton','Spinbox']:
                stack.enter_context(patch('karaoke.classic.ttk.'+name,side_effect=widget))
            for name in ['StringVar','DoubleVar','IntVar','BooleanVar']:
                stack.enter_context(patch('karaoke.classic.tk.'+name,Var))
            ClassicApp.open_mixer(app)
            poll=window.after.call_args.args[1]
            scale=next(w for w in widgets if 'from_' in w.options and w.options.get('to')==100)
            app.engine=second;app.current_song={'title':'second'}
            scale.options['command']()  # during 150ms transition: never copy old song's values
            second.set_channel.assert_not_called()
            poll()
            self.assertEqual(scale.options['variable'].get(),40)
            scale.options['variable'].set(65);scale.options['command']()
            second.set_channel.assert_called_with(0,.65,False)
            first.set_channel.assert_not_called()
            drum=next(w for w in widgets if w.options.get('text')=='ปิด Kick 35')
            drum.options['variable'].set(True);drum.options['command']()
            second.set_drum_muted.assert_called_with(35,True)
            panic=next(w for w in widgets if w.options.get('text')=='หยุดเสียงค้าง')
            panic.options['command']();second.seek.assert_called_with(10)
            app.engine=None;poll();second.set_channel.reset_mock();scale.options['command']()
            second.set_channel.assert_not_called()
            cleanup=window.bind.call_args.args[1];cleanup(NS(widget=window))
            window.after_cancel.assert_called_once_with('timer1')
