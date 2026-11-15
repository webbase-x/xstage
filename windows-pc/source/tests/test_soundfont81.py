import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
from karaoke.soundfont_preview import Audition,note_groups
from karaoke.soundfont_coverage import requirements,check_song
from test_soundfont80 import metadata_font
from soundfont_fixture import make_font

class Soundfont81Tests(unittest.TestCase):
    def test_note_ranges_and_chord_validation(self):
        self.assertEqual(note_groups('คอร์ดเมเจอร์','60','72'),[(60,64,67)])
        self.assertEqual(note_groups('ไล่ช่วงโน้ต',126,127),[(126,),(127,)])
        self.assertEqual(note_groups('โน้ตเดียว',0,127),[(0,)])
        for mode,a,b in [('คอร์ดเมเจอร์',121,127),('ไล่ช่วงโน้ต',70,60),('โน้ตเดียว','x',60)]:
            with self.assertRaises(ValueError):note_groups(mode,a,b)

    def test_cancel_during_load_closes_without_notes_on_worker(self):
        with tempfile.TemporaryDirectory() as d:
            p=make_font(Path(d)/'a.sf2');started=threading.Event();release=threading.Event();closed=threading.Event();threads=[];sent=[]
            class Synth:
                def __init__(self,*a,**kw):threads.append(threading.get_ident());started.set();release.wait(3)
                def send(self,msg):sent.append(msg)
                def close(self):threads.append(threading.get_ident());closed.set()
            worker=Audition();worker.start(Path(d),{'soundfont':str(p)},None,0,0,[(60,)],Synth)
            try:
                self.assertTrue(started.wait(3));worker.stop();release.set()
                self.assertTrue(closed.wait(3));self.assertFalse(sent)
                self.assertEqual(threads[0],threads[-1]);self.assertNotEqual(threads[0],threading.get_ident())
            finally:release.set()

    def test_preview_error_is_reported_and_worker_finishes(self):
        worker=Audition()
        token=worker.start(Path('.'),{'soundfont':'missing.sf2'},None,0,0,[(60,)])
        event=worker.events.get(timeout=3)
        self.assertEqual(event[:2],(token,'error'))
        self.assertEqual(worker.events.get(timeout=3)[:2],(token,'finished'))

    def test_note_off_and_close_after_normal_preview(self):
        with tempfile.TemporaryDirectory() as d:
            p=make_font(Path(d)/'a.sf2');sent=[];closed=threading.Event()
            class Synth:
                def __init__(self,*a,**kw):pass
                def send(self,msg):sent.append(msg)
                def close(self):closed.set()
            worker=Audition();worker.start(Path(d),{'soundfont':str(p)},None,0,0,[(60,64,67)],Synth)
            self.assertTrue(closed.wait(3))
            self.assertEqual([x[1] for x in sent if x[0]==0x90],[60,64,67])
            self.assertEqual([x[1] for x in sent if x[0]==0x80],[60,64,67])

    def test_requirements_only_count_audible_notes_and_latch_bank(self):
        messages=[[0xb0,0,10],[0x90,60,80],[0xc0,5],[0x90,61,80],[0x90,61,0],[0xc9,0],[0x99,36,80]]
        rows,_=requirements([NS(data=bytes(x)) for x in messages])
        self.assertEqual(rows,[(0,0,0,0),(0,10,0,5),(9,128,0,0)])

    def test_coverage_exact_missing_and_lsb_are_distinct(self):
        with tempfile.TemporaryDirectory() as d:
            p=metadata_font(Path(d)/'all.sf2')
            events=[NS(data=bytes(x)) for x in [[0xb0,0,10],[0xc0,5],[0x90,60,80],[0xc0,99],[0x90,60,80],[0xb0,32,1],[0xc0,5],[0x90,60,80]]]
            with patch('karaoke.smf.load_midi',return_value=NS(events=events)):
                rows,warnings=check_song('x.mid',{'soundfont_audio':{'fonts':[{'path':str(p)}]},'soundfont_follow_song':True})
            self.assertEqual([r[4] for r in rows],['พบตรง','ไม่พบตรง','ต้องตรวจเพิ่มเติม'])
            self.assertEqual(rows[0][5],'Khim');self.assertTrue(warnings)

    def test_invalid_mapping_does_not_claim_confirmed_sound(self):
        with tempfile.TemporaryDirectory() as d:
            p=metadata_font(Path(d)/'all.sf2')
            events=[NS(data=bytes([0x90,60,80]))]
            with patch('karaoke.smf.load_midi',return_value=NS(events=events)):
                rows,warnings=check_song('x.mid',{'soundfont_audio':{'fonts':[{'path':str(p)}]},
                    'instrument_fonts':{'piano':'gone.sf2'}})
            self.assertEqual(rows[0][4],'ตรวจไม่ครบ')
            self.assertTrue(any('จับคู่' in x for x in warnings))

@unittest.skipUnless(os.environ.get('DISPLAY'),'requires graphical display')
class SoundfontGui81Tests(unittest.TestCase):
    def test_pending_gain_selection_and_close_prompt_and_restore(self):
        import tkinter as tk
        from karaoke.ui import KaraokeApp
        from karaoke.audio_dialog import AudioSettings
        with tempfile.TemporaryDirectory() as d:
            app=tk.Tk();app.geometry('300x100');KaraokeApp._setup_style(app)
            p=metadata_font(Path(d)/'all.sf2');q=metadata_font(Path(d)/'other.sf2')
            app.settings={'synth_backend':'winmm','soundfont_audio':{'fonts':[{'path':str(p),'gain_db':-8},{'path':str(q),'gain_db':-12}]}}
            app.home=Path(__file__).resolve().parents[1];app.engine=None;app.status_var=tk.StringVar();app.save_settings=Mock()
            errors=[];app.report_callback_exception=lambda *e:errors.append(e)
            win=AudioSettings(app);app.update()
            try:
                self.assertEqual(win.edit_state(),win._initial_state)
                win.tree.selection_set('1');app.update()
                self.assertEqual(win.edit_state(),win._initial_state)
                win.gain.set('-14')
                self.assertEqual(win.collect(False)['fonts'][1]['gain_db'],-14)
                win.browser.query.set('Khim');win.book.select(1);app.update()
                with patch('karaoke.audio_dialog.messagebox.askyesnocancel',return_value=None) as prompt:win.close();prompt.assert_called_once()
                self.assertTrue(win.winfo_exists())
                win.gain.set('bad')
                with patch('karaoke.audio_dialog.messagebox.showerror') as error:
                    win.save();error.assert_called_once()
                self.assertTrue(win.winfo_exists())
                win.gain.set('-15');win.save();app.update()
                self.assertEqual(app.settings['soundfont_audio']['fonts'][1]['gain_db'],-15)
                self.assertFalse(win.winfo_exists())
                win=AudioSettings(app);app.update()
                self.assertEqual(win.browser.query.get(),'Khim')
                self.assertEqual(win.book.index(win.book.select()),1)
                win.close();app.update();self.assertFalse(errors,errors)
            finally:
                if win.winfo_exists():win.destroy()
                app.destroy()
