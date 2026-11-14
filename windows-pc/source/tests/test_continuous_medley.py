import random
import unittest
from karaoke.continuous_medley import ContinuousMedley, next_category

class WindowsUpdateParityTests(unittest.TestCase):
    def test_version_comparison_ignores_missing_trailing_zeros(self):
        from karaoke.program_updates import version_tuple
        self.assertEqual(version_tuple('1.0.76'), version_tuple('1.0.76.0'))

    def test_build_only_updates_require_newer_build(self):
        from karaoke.program_updates import validate_manifest
        sample={'available':True,'version':'1.0.76','build':1077,
                'installer_file':'X-Stage-Karaoke-Windows-v1.0.76-build1077.exe',
                'sha256':'a'*64}
        self.assertIsNotNone(validate_manifest(sample,'1.0.76',1076))
        self.assertIsNone(validate_manifest(sample,'1.0.76',1077))

class CategoryRotationTests(unittest.TestCase):
    def test_cycles_all_types_including_uncategorized(self):
        types=[('rock','Rock'),('luk thung','ลูกทุ่ง'),('','')]
        rng=random.Random(3)
        seen=[]
        position=0
        for _ in range(3):
            category,position=next_category(types,position,rng)
            seen.append(category[0])
        self.assertEqual(set(seen),{'rock','luk thung',''})
        self.assertIsNotNone(next_category(types,position,rng)[0])

    def test_empty_catalog_does_not_loop(self):
        self.assertEqual(next_category([],0), (None,0))

    def test_stop_cancels_owned_sessions_only(self):
        class Queue:
            def __init__(self):self.cleared=[]
            def cancel_medley(self,session):self.cleared.append(session)
        class App:
            def __init__(self):self.song_queue=Queue();self.refreshes=0
            def refresh_queue(self):self.refreshes+=1
        app=App()
        controller=ContinuousMedley(enabled=True,session_ids={'auto1','auto2'})
        self.assertEqual(controller.stop(app),2)
        self.assertEqual(set(app.song_queue.cleared),{'auto1','auto2'})
        self.assertFalse(controller.enabled)
        self.assertEqual(app.refreshes,1)

if __name__=='__main__':unittest.main()
