import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from types import SimpleNamespace as NS
from karaoke.soundfont import inspect_font
from karaoke.preset_browser import filter_presets,preview_settings
from karaoke.bass import BassSynth
from soundfont_fixture import chunk,make_font
import test_soundfont


def metadata_font(path):
    rows=[(b'Piano',0,0),(b'Ranat',4,10),(b'Khim',5,10),(b'Khaen',6,12),(b'Thai drums',0,128),(b'EOP',0,0)]
    phdr=b''.join(struct.pack('<20sHHHIII',name,p,b,0,0,0,0) for name,p,b in rows)
    path.write_bytes(chunk(b'RIFF',b'sfbk'+chunk(b'LIST',b'pdta'+chunk(b'phdr',phdr))))
    return path

class Soundfont80Tests(unittest.TestCase):
    def test_one_file_lists_all_banks_and_names(self):
        with tempfile.TemporaryDirectory() as d:
            rows=inspect_font(metadata_font(Path(d)/'combined.sf2'))['presets']
            self.assertEqual(len(rows),5)
            self.assertEqual(filter_presets(rows,'khim'),[(10,5,'Khim')])
            self.assertEqual(len(filter_presets(rows,bank=10)),2)
            self.assertEqual(filter_presets(rows,'unknown'),[])

    def test_audition_exact_preset_and_does_not_modify_options(self):
        with tempfile.TemporaryDirectory() as d:
            p=str(metadata_font(Path(d)/'combined.sf2'))
            options={'fonts':[{'path':p,'gain_db':-6}]}
            settings=preview_settings(options,p,10,5)
            self.assertEqual(settings['instrument_fonts']['piano'],{'path':p,'bank':10,'preset':5})
            self.assertNotIn('instrument_fonts',options)
            self.assertIn('drums',preview_settings(options,p,128,0)['instrument_fonts'])
            with self.assertRaises(ValueError):preview_settings(options,p,10,99)

    def test_follow_song_loads_once_all_presets_and_forwards_bank_events(self):
        with tempfile.TemporaryDirectory() as d:
            p=metadata_font(Path(d)/'combined.sf2')
            api=test_soundfont.SoundFontTests();dll,midi=api.fake_api()
            synth=BassSynth(Path(d),settings={'soundfont':str(p),'soundfont_follow_song':True,
                'instrument_fonts':{'piano':{'path':'obsolete.sf2','bank':0,'preset':0}}},bindings=(dll,midi))
            try:
                self.assertEqual(midi.BASS_MIDI_FontInit.call_count,1)
                config=midi.BASS_MIDI_StreamSetFonts.call_args.args[1]
                self.assertEqual([(r.preset,r.bank) for r in config],[(-1,0)])
                for message in [bytes([0xb0,0,10]),bytes([0xb0,32,0]),bytes([0xc0,5]),bytes([0x90,60,80])]:synth.send(message)
                self.assertEqual(api.messages[-4:],[bytes([0xb0,0,10]),bytes([0xb0,32,0]),bytes([0xc0,5]),bytes([0x90,60,80])])
            finally:synth.close()

    def test_utf8_thai_preset_name(self):
        with tempfile.TemporaryDirectory() as d:
            p=metadata_font(Path(d)/'thai.sf2')
            data=p.read_bytes().replace(b'Khim'+b'\0'*16,'ขิม'.encode('utf-8').ljust(20,b'\0'))
            p.write_bytes(data)
            self.assertEqual(filter_presets(inspect_font(p)['presets'],'ขิม')[0][2],'ขิม')

    def test_save_failure_restores_previous_settings(self):
        from karaoke.audio_dialog import AudioSettings
        app=NS(settings={'synth_backend':'old'},save_settings=Mock(side_effect=OSError('disk full')))
        dialog=NS(app=app,benchmark_busy=lambda:False,collect=lambda:{'fonts':[]},mode=NS(get=lambda:'winmm'),stop_preview=Mock())
        with patch('karaoke.audio_dialog.messagebox.showerror'):
            AudioSettings.save(dialog)
        self.assertEqual(app.settings,{'synth_backend':'old'})

@unittest.skipUnless(os.environ.get('DISPLAY'),'requires graphical display')
class SoundfontGui80Tests(unittest.TestCase):
    def test_tabs_browser_and_controls(self):
        import tkinter as tk
        from karaoke.ui import KaraokeApp
        from karaoke.audio_dialog import AudioSettings
        with tempfile.TemporaryDirectory() as d:
            app=tk.Tk();app.geometry('300x100');KaraokeApp._setup_style(app)
            app.settings={'soundfont':str(metadata_font(Path(d)/'combined.sf2'))};app.engine=None
            app.home=Path(__file__).resolve().parents[1];app.status_var=tk.StringVar();app.save_settings=Mock()
            errors=[];app.report_callback_exception=lambda *e:errors.append(e)
            win=AudioSettings(app)
            try:
                app.update()
                win.geometry('880x640+25+30');app.update()
                geometry=win.geometry()
                for tab in win.book.tabs():
                    win.book.select(tab);app.update()
                    self.assertEqual(win.geometry(), geometry, 'Tab switch changed user window geometry')
                win.book.select(1);app.update()
                import time
                deadline=time.monotonic()+3
                while not win.browser.rows and time.monotonic()<deadline:
                    app.update();time.sleep(.01)
                self.assertEqual(len(win.browser.tree.get_children()),5)
                win.browser.query.set('Khim');app.update()
                self.assertEqual(len(win.browser.tree.get_children()),1)
                win.audition=Mock();win.browser.play()
                self.assertEqual(win.audition.call_args.args[0][1:3],(10,5))
                self.assertTrue(win.follow_song.get())
                win.fonts=[];win.refresh();app.update()
                self.assertEqual(len(win.browser.tree.get_children()),0)
                self.assertEqual(str(win.browser.play_button['state']),'disabled')
                self.assertFalse(errors,errors)
            finally:
                with patch('karaoke.audio_dialog.messagebox.askyesnocancel',return_value=False):win.close()
                app.destroy()
