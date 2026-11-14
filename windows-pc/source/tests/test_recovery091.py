import json,sqlite3,tempfile,unittest
from contextlib import closing
from pathlib import Path
from karaoke.pending_cleanup import find_pending
class PendingCleanupRecoveryTests(unittest.TestCase):
    def test_detects_interrupted_journal_without_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'quality-reports'; folder=root/'Cleanup-interrupted'; folder.mkdir(parents=True)
            (folder/'summary.json').write_text(json.dumps({'complete':True}),encoding='utf-8')
            with closing(sqlite3.connect(folder/'execution.sqlite3')) as db:
                db.execute('CREATE TABLE actions(id INTEGER PRIMARY KEY,state TEXT,data TEXT,error TEXT)')
                db.execute("INSERT INTO actions VALUES (1,'files_deleted','{}','')"); db.commit()
            before=(folder/'execution.sqlite3').read_bytes(); found=find_pending(root)
            self.assertEqual(found[0]['unresolved'],{'files_deleted':1})
            self.assertEqual((folder/'execution.sqlite3').read_bytes(),before)
    def test_completed_journal_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'quality-reports'; folder=root/'Cleanup-complete'; folder.mkdir(parents=True)
            (folder/'summary.json').write_text('{}',encoding='utf-8')
            with closing(sqlite3.connect(folder/'execution.sqlite3')) as db:
                db.execute('CREATE TABLE actions(id INTEGER PRIMARY KEY,state TEXT,data TEXT,error TEXT)')
                db.execute("INSERT INTO actions VALUES (1,'applied','{}','')"); db.commit()
            self.assertEqual(find_pending(root),[])
if __name__=='__main__': unittest.main()