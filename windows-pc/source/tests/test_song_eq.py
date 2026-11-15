import copy,unittest
from karaoke.song_eq import key,remembered,selected,store,forget
from karaoke.graphic_eq import flat
class SongEQTests(unittest.TestCase):
    def test_recall_by_path_survives_catalog_id_changes(self):
        song={'id':1,'title':'ชื่อซ้ำ','path':r'D:\Songs\A.mid'};state=flat();state['bands'][2]['gain_db']=3
        settings={};store(settings,song,state)
        replay={'id':999,'title':'ชื่อใหม่','path':'d:/songs/a.mid'}
        self.assertEqual(remembered(settings,replay),state)
        self.assertIsNone(remembered(settings,{'title':'ชื่อซ้ำ','path':r'D:\Songs\B.mid'}))
    def test_global_and_other_song_not_changed(self):
        base=flat();base['preamp_db']=-6;settings={'graphic_eq':copy.deepcopy(base)}
        own=flat();own['bands'][1]['gain_db']=2;song={'path':'D:/a.mid'}
        store(settings,song,own);own['bands'][1]['gain_db']=10
        self.assertEqual(selected(settings,song)['bands'][1]['gain_db'],2)
        self.assertEqual(selected(settings,{'path':'D:/b.mid'}),base)
        forget(settings,song);self.assertEqual(selected(settings,song),base)
    def test_bad_preset_falls_back_and_no_song_rejected(self):
        settings={'song_eq':{key({'path':'D:/a.mid'}):{'bad':True}}}
        self.assertEqual(selected(settings,{'path':'D:/a.mid'}),flat())
        with self.assertRaises(ValueError):store(settings,None,flat())
