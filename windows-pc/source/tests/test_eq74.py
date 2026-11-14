import copy
import unittest
from karaoke.graphic_eq import flat
from karaoke.song_eq import store,relocate,remembered,key
from karaoke.eq_ui_state import status,clamp_rack
from karaoke.dependency_ui import check_command

class EQ74Tests(unittest.TestCase):
    def test_relocate_keeps_curve_and_other_songs(self):
        settings={};old={'path':r'D:\old\เพลง.mid'};new={'path':r'E:\new\เพลง.mid'}
        curve=flat();curve['preamp_db']=-5
        store(settings,old,curve);store(settings,{'path':'other.mid'},flat())
        relocate(settings,old['path'],new['path'])
        self.assertEqual(remembered(settings,new),curve)
        self.assertIsNone(remembered(settings,old));self.assertEqual(len(settings['song_eq']),2)
    def test_collision_does_not_modify_either_song(self):
        settings={};store(settings,{'path':'a.mid'},flat());store(settings,{'path':'b.mid'},flat())
        before=copy.deepcopy(settings)
        with self.assertRaises(ValueError):relocate(settings,'a.mid','b.mid')
        self.assertEqual(settings,before)
    def test_relocate_same_path_is_noop(self):
        settings={};store(settings,{'path':r'D:\Music\A.mid'},flat())
        relocate(settings,r'D:\Music\A.mid',r'd:\music\a.mid')
        self.assertEqual(len(settings['song_eq']),1)
    def test_status_requires_application_not_just_saved_settings(self):
        state=flat();song={'path':'a.mid'};settings={};store(settings,song,state)
        self.assertIn('ยังไม่ได้ใช้',status(state,settings,song,True,False))
        self.assertIn('ไม่รองรับ',status(state,settings,song,False,False))
        self.assertIn('บันทึกประจำเพลงแล้ว',status(state,settings,song,True,True))
        changed=copy.deepcopy(state);changed['preamp_db']=-3
        self.assertIn('ยังไม่บันทึก',status(changed,settings,song,True,True))
    def test_clamp_keeps_whole_rack_inside_negative_monitor(self):
        area=(-1920,0,0,1040)
        x,y,w,h=clamp_rack((-400,900,1200,500),area)
        self.assertGreaterEqual(x,area[0]);self.assertLessEqual(x+w,area[2]);self.assertLessEqual(y+h,area[3])
    def test_removed_monitor_and_small_area(self):
        self.assertEqual(clamp_rack((2000,2000,1400,600),(0,0,800,480)),(0,0,800,480))
    def test_check_commands_keep_paths_as_individual_arguments(self):
        home='D:/โฟลเดอร์ เพลง';report='D:/data user/report.json'
        command=check_command(home,report,'python.exe',False)
        self.assertEqual(command[-1],report);self.assertIn(home,command)
        self.assertEqual(check_command(home,report,'app.exe',True),['app.exe','--check-dependencies','--dependency-report',report])
