import copy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
from karaoke.library import QueueItem
from karaoke.json_recovery import inspect_candidate, restore_json, target_revision, prompt_restore
from karaoke.performance_features import PlayHistory, history_for_window, restore_history, PerformanceFeatures


def rows(song_id=2):
    return [{'time':'now','title':'song','path':'test.mid','status':'completed','item':{'song_id':song_id}}]


class HistoryRecoveryTests(unittest.TestCase):
    def test_history_candidate_is_validated_and_original_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'history.json';p.write_bytes(b'broken');source=Path(d)/'backup.json'
            for raw in (b'{}',b'[null]',b'[{"item":{"song_id":1}}]'):
                source.write_bytes(raw)
                with self.assertRaises(ValueError):restore_json(p,source)
                self.assertEqual(p.read_bytes(),b'broken')
            payload=json.dumps(rows()).encode();source.write_bytes(payload)
            backup=restore_json(p,source)
            self.assertEqual(backup.read_bytes(),b'broken');self.assertEqual(p.read_bytes(),payload);self.assertEqual(source.read_bytes(),payload)
    def test_changed_target_after_preview_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'history.json';p.write_bytes(b'broken');revision=target_revision(p)
            source=Path(d)/'backup.json';source.write_text(json.dumps(rows()))
            p.write_bytes(b'externally repaired')
            with self.assertRaises(ValueError):restore_json(p,source,expected_target=revision)
            self.assertEqual(p.read_bytes(),b'externally repaired');self.assertFalse(list(Path(d).glob('*.bak')))
    def test_change_during_backup_is_preserved(self):
        from karaoke.json_recovery import preserve_json
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'history.json';p.write_bytes(b'broken');source=Path(d)/'backup.json';source.write_text(json.dumps(rows()))
            def save(path):
                backup=preserve_json(path);p.write_bytes(b'new external data');return backup
            with patch('karaoke.json_recovery.preserve_json',side_effect=save):
                with self.assertRaises(ValueError):restore_json(p,source)
            self.assertEqual(p.read_bytes(),b'new external data');self.assertEqual(next(Path(d).glob('*.bak')).read_bytes(),b'broken')
            self.assertFalse(list(Path(d).glob('*.tmp')))
    def test_bad_disk_is_detected_even_with_cached_history(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'history.json';p.write_text(json.dumps(rows(1)));cached=PlayHistory(p)
            app=NS(data_dir=Path(d),_play_history=cached);p.write_bytes(b'broken')
            with patch('karaoke.json_recovery.prompt_recovery',return_value=False) as prompt,self.assertLogs(level='ERROR'):
                self.assertIsNone(history_for_window(app))
            prompt.assert_called_once();self.assertIs(app._play_history,cached);self.assertEqual(p.read_bytes(),b'broken')
    def test_recovery_reloads_cache_without_changing_player_or_queue(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'history.json';p.write_text(json.dumps(rows(1)));cached=PlayHistory(p)
            source=Path(d)/'backup.json';source.write_text(json.dumps(rows(2)))
            queue=[QueueItem(10)];engine=NS(position=42.5,playing=True);song={'path':'playing.mid'}
            app=NS(data_dir=Path(d),_play_history=cached,song_queue=NS(items=queue),engine=engine,current_song=song)
            def prompt(target,description,parent):restore_json(target,source);return True
            with patch('karaoke.json_recovery.prompt_restore',side_effect=prompt):self.assertTrue(restore_history(app))
            self.assertIsNot(app._play_history,cached);self.assertEqual(app._play_history.rows[0]['item']['song_id'],2)
            self.assertIs(app.song_queue.items,queue);self.assertEqual(queue,[QueueItem(10)])
            self.assertIs(app.engine,engine);self.assertEqual(engine.position,42.5);self.assertTrue(engine.playing);self.assertIs(app.current_song,song)
    def test_restore_cancel_keeps_cached_history(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'history.json';p.write_text(json.dumps(rows(1)));cached=PlayHistory(p);raw=p.read_bytes()
            app=NS(data_dir=Path(d),_play_history=cached)
            with patch('karaoke.json_recovery.prompt_restore',return_value=False):self.assertFalse(restore_history(app))
            self.assertIs(app._play_history,cached);self.assertEqual(p.read_bytes(),raw)


@unittest.skipUnless(os.environ.get('DISPLAY'),'requires explicit GUI test display')
class HistoryRecoveryGuiTests(unittest.TestCase):
    def test_parent_is_kept_alive_on_restore_and_cancel(self):
        import tkinter as tk
        root=tk.Tk()
        try:
            with tempfile.TemporaryDirectory() as d:
                p=Path(d)/'history.json';p.write_bytes(b'broken');source=Path(d)/'backup.json';source.write_text(json.dumps(rows()))
                with patch('tkinter.Tk',side_effect=AssertionError('must reuse parent')),patch('tkinter.messagebox.askyesno',return_value=True),patch('tkinter.filedialog.askopenfilename',return_value=str(source)),patch('tkinter.messagebox.showinfo'):
                    self.assertTrue(prompt_restore(p,'history test',parent=root))
                self.assertTrue(root.winfo_exists())
                raw=p.read_bytes()
                with patch('tkinter.messagebox.askyesno',return_value=False):self.assertFalse(prompt_restore(p,'cancel',parent=root))
                self.assertTrue(root.winfo_exists());self.assertEqual(p.read_bytes(),raw)
        finally:root.destroy()
    def test_target_change_during_confirmation_is_rejected(self):
        import tkinter as tk
        root=tk.Tk()
        try:
            with tempfile.TemporaryDirectory() as d:
                p=Path(d)/'history.json';p.write_bytes(b'broken');source=Path(d)/'backup.json';source.write_text(json.dumps(rows()))
                calls=[]
                def ask(*args,**kwargs):
                    calls.append(1)
                    if len(calls)==2:p.write_bytes(b'external change')
                    return True
                with patch('tkinter.messagebox.askyesno',side_effect=ask),patch('tkinter.filedialog.askopenfilename',side_effect=[str(source),'']),patch('tkinter.messagebox.showerror') as error:
                    self.assertFalse(prompt_restore(p,'race test',parent=root));error.assert_called_once()
                self.assertEqual(p.read_bytes(),b'external change')
        finally:root.destroy()
    def test_history_button_restores_and_reopens_without_changing_queue(self):
        import tkinter as tk
        from tkinter import ttk
        from karaoke.dialog_layout import DialogWindow
        root=tk.Tk();errors=[];root.report_callback_exception=lambda *args:errors.append(args)
        try:
            with tempfile.TemporaryDirectory() as d:
                root.data_dir=Path(d);p=Path(d)/'history.json';p.write_text(json.dumps(rows(1)));source=Path(d)/'backup.json';source.write_text(json.dumps(rows(2)))
                root.engine=NS(position=12.5,playing=True);root.song_queue=NS(items=[QueueItem(10)]);root.show_error=Mock();root.status_var=tk.StringVar(root)
                root.history_window=lambda:PerformanceFeatures.history_window(root)
                root.history_window();root.update()
                windows=[w for w in root.winfo_children() if isinstance(w,DialogWindow)];self.assertEqual(len(windows),1);old=windows[0]
                def descendants(w):
                    for c in w.winfo_children():yield c;yield from descendants(c)
                button=next(w for w in descendants(old) if isinstance(w,ttk.Button) and w.cget('text')=='กู้ประวัติจากไฟล์สำรอง')
                with patch('tkinter.messagebox.askyesno',return_value=True),patch('tkinter.filedialog.askopenfilename',return_value=str(source)),patch('tkinter.messagebox.showinfo'):
                    button.invoke();root.update()
                self.assertFalse(old.winfo_exists());self.assertEqual(root._play_history.rows[0]['item']['song_id'],2)
                self.assertEqual(root.song_queue.items,[QueueItem(10)]);self.assertEqual(root.engine.position,12.5);self.assertTrue(root.engine.playing)
                self.assertFalse(errors,errors);root.show_error.assert_not_called()
        finally:root.destroy()
