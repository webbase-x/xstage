import copy
import json
import tempfile
import unittest
from pathlib import Path, PureWindowsPath, PurePosixPath
from unittest.mock import patch
from karaoke.graphic_eq import flat
from karaoke.song_eq_backup import encode,decode,merge,load
from karaoke.support_report import manual_results,collect
from karaoke.support_ui import command

class SupportTests(unittest.TestCase):
    def test_backup_roundtrip_unicode(self):
        songs={r'd:\เพลง\ทดสอบ.mid':flat()}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'eq.json';path.write_text(json.dumps(encode(songs),ensure_ascii=False),encoding='utf-8-sig')
            self.assertEqual(load(path),songs)
    def test_invalid_curve_rejects_whole_import(self):
        value=encode({'a.mid':flat(),'b.mid':flat()});value['songs']['b.mid']['bands'][0]['gain_db']=200
        with self.assertRaises(ValueError):decode(value)
    def test_normalized_collision_rejected(self):
        with self.assertRaises(ValueError):encode({'A.mid':flat(),'a.mid':flat()})
    def test_merge_keeps_existing_by_default_without_aliases(self):
        original={'a.mid':flat()};new=flat();new['preamp_db']=-5
        incoming={'a.mid':new,'b.mid':new};merged=merge(original,incoming)
        self.assertEqual(merged['a.mid'],flat());self.assertEqual(merged['b.mid'],new)
        merged['b.mid']['preamp_db']=-8;self.assertEqual(incoming['b.mid']['preamp_db'],-5)
        self.assertEqual(merge(original,incoming,True)['a.mid'],new)
    def test_oversize_input_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'large.json';path.write_bytes(b' '*40)
            with patch('karaoke.song_eq_backup.MAX_BYTES',32):
                with self.assertRaises(ValueError):load(path)
    def test_unperformed_checks_are_never_passed(self):
        self.assertTrue(all(x['status']=='ยังไม่ทดสอบ' for x in manual_results({}).values()))
        value=manual_results({'continuous':{'status':'ผ่าน','note':'30 นาที'},'display':{'status':'unknown'}})
        self.assertEqual(value['continuous']['source'],'user-reported')
        self.assertEqual(value['display']['status'],'ยังไม่ทดสอบ')
    def test_report_errors_do_not_become_audio_pass(self):
        with tempfile.TemporaryDirectory() as folder,patch('karaoke.dependency_check.inspect',return_value={'ok':False,'checks':[]}),patch('karaoke.windows_audio.audio_context',side_effect=OSError('No audio device')):
            report=collect(folder,folder)
        self.assertFalse(report['dependencies']['ok']);self.assertIn('not performed',report['audio_test'])
        self.assertIn('No audio device',report['output_devices_error']);self.assertNotIn('settings',report)
    def test_child_command_preserves_spaces_and_thai(self):
        cmd=command('D:/เพลง ใหม่','D:/ข้อมูล','D:/รายงาน เสียง.json','python.exe',False)
        self.assertEqual(cmd,['python.exe',str(Path('D:/เพลง ใหม่')/'main.py'),'--system-report','D:/รายงาน เสียง.json','--data-dir','D:/ข้อมูล'])
        self.assertEqual(command('D:/app','data','out','app.exe',True)[1],'--system-report')

    def test_child_command_windows_and_posix_path_flavors(self):
        for path_class,home,expected in (
            (PureWindowsPath,'D:/เพลง ใหม่',r'D:\เพลง ใหม่\main.py'),
            (PureWindowsPath,r'\\server\share\เพลง ใหม่',r'\\server\share\เพลง ใหม่\main.py'),
            (PurePosixPath,'/tmp/เพลง ใหม่','/tmp/เพลง ใหม่/main.py')):
            with self.subTest(path_class=path_class,home=home),patch('karaoke.support_ui.Path',path_class):
                self.assertEqual(command(home,'data space','report space.json','python.exe',False),
                    ['python.exe',expected,'--system-report','report space.json','--data-dir','data space'])
                self.assertEqual(command(home,'data space','report space.json','app.exe',True),
                    ['app.exe','--system-report','report space.json','--data-dir','data space'])
