import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
from karaoke.system_eq import render,write,linked,target,endpoint_guid
from karaoke.eq_model import flat
from karaoke.system_eq_ui import apply_system
DEVICE='{0.0.0.00000000}.{12345678-1234-1234-1234-123456789abc}'

class SystemEQTests(unittest.TestCase):
    def test_export_all_filters_scope_and_shelf(self):
        s=flat()
        for b,k in zip(s['bands'],['bell','low_cut','high_cut','notch','low_shelf','high_shelf']):b['kind']=k;b['gain_db']=3
        text=render(s,DEVICE).decode()
        self.assertIn('Device: {12345678-1234-1234-1234-123456789abc}',text)
        for k in ('PK','HPQ','LPQ','NO','LSC','HSC'):self.assertIn('ON '+k+' ',text)
        self.assertIn('Stage: post-mix',text);self.assertIn('Q 0.7071067812',text)
    def test_bypass_does_not_emit_any_processing(self):
        s=flat();s['bypass']=True;s['preamp_db']=-12
        text=render(s,DEVICE).decode();self.assertNotIn('Filter:',text);self.assertNotIn('Preamp:',text)
    def test_bad_device_cannot_inject_config(self):
        with self.assertRaises(ValueError):render(flat(),'all\nPreamp: 99 dB')
        s=render(flat(),DEVICE+'\nPreamp: 99 dB').decode();self.assertNotIn('99 dB',s)
    def test_write_preserves_main_and_returns_rollback(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);main=p/'config.txt';original=b'# X-STAGE SYSTEM EQ BEGIN\nInclude: XStage/xstage-eq.txt\nPreamp: -3 dB\n'
            main.write_bytes(original);target(p).parent.mkdir();target(p).write_bytes(b'# old')
            file,old=write(flat(),DEVICE,p)
            self.assertEqual(old,b'# old');self.assertEqual(main.read_bytes(),original);self.assertIn(b'Filter:',file.read_bytes())
    def test_missing_link_refuses_write(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'config.txt').write_text('# original')
            with self.assertRaises(OSError):write(flat(),DEVICE,p)
            self.assertFalse(target(p).exists())
    def test_apply_sets_windows_scope_only_after_write(self):
        app=NS(settings={'parametric_eq':flat()},engine=None,save_settings=Mock())
        editor=NS(commit=lambda:True,app=app,state=flat(),system_page=NS(selected=lambda:DEVICE),status=Mock())
        with patch('karaoke.system_eq.write',return_value=(Path('file'),b'old')):
            apply_system(editor)
        self.assertEqual(app.settings['eq_scope'],'windows');self.assertEqual(app.settings['system_eq_device'],DEVICE)
    def test_save_failure_rolls_back_system_file_and_settings(self):
        app=NS(settings={'original':1},engine=None,save_settings=Mock(side_effect=OSError('disk full')))
        editor=NS(commit=lambda:True,app=app,state=flat(),system_page=NS(selected=lambda:DEVICE),status=Mock())
        with patch('karaoke.system_eq.write',return_value=(Path('file'),b'old')),patch('karaoke.system_eq.atomic_write') as undo:
            with self.assertRaises(OSError):apply_system(editor)
            undo.assert_called_once_with(Path('file'),b'old')
        self.assertEqual(app.settings,{'original':1})
