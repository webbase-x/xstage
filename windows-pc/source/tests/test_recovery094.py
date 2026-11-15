import tempfile, time, unittest
from pathlib import Path
from karaoke.startup_hygiene import quarantine_stale
from karaoke.path_probe import PathProbe

class Recovery094Tests(unittest.TestCase):
    def test_stale_temp_is_quarantined_not_deleted(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); item=root/'queue.json.restore.tmp'; item.write_text('partial'); old=time.time()-90000; import os; os.utime(item,(old,old))
            moved=quarantine_stale(root,age_seconds=10)
            self.assertEqual(len(moved),1); self.assertFalse(item.exists()); self.assertTrue(Path(moved[0]['quarantine']).is_file())
    def test_path_probe_can_cancel_and_join(self):
        result=[]; probe=PathProbe([Path(__file__)],result.append).start(); self.assertTrue(probe.join(2)); self.assertEqual(result[0][0]['exists'],True)

if __name__=='__main__': unittest.main()