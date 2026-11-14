"""R14 quota widget integration: read quota in worker, render Tk on main thread."""
import os
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

@unittest.skipUnless(os.environ.get('XSTAGE_TEST_GUI')=='1','Requires Tk display')
class OnlineCapacityWidgetTests(unittest.TestCase):
    def setUp(self):
        from karaoke.ui import KaraokeApp
        from tests.test_studio import midi_fixture
        self.tmp=tempfile.TemporaryDirectory()
        root=Path(self.tmp.name)
        (root/'samples').mkdir()
        file=root/'Songs'/'12345.mid'
        file.parent.mkdir();file.write_bytes(midi_fixture())
        with patch('karaoke.google_session.has_saved_session',return_value=False):
            self.app=KaraokeApp(root,root/'Data')
        self.app.library.add_files([file]);self.app.withdraw()

    def tearDown(self):
        try:
            window=self.app._cloud_progress_window
            if window is not None and window.winfo_exists():window.destroy()
            try:self.app.after_cancel(self.app.tick_after)
            except Exception:pass
            self.app.destroy()
        finally:self.tmp.cleanup()

    def pump(self,condition,timeout=4):
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            self.app.update()
            if condition():return True
            time.sleep(.018)
        return False

    def test_actual_account_usage_and_verified_upload_projection(self):
        self.app.web_online_data()
        wizard=self.app._online_wizard
        account=self.app.google_account
        account.credentials=('access','owner@example.com','refresh',time.monotonic()+3600)
        account.profile={'email':'owner@example.com','name':'Owner'}
        wizard['state']['storage_stats']={'processed':50,'total':100,
              'sample_songs':20,'sample_uploads':5,'sample_bytes':800}
        quota={'usage':5000,'limit':10000,'usageInDrive':2000,'usageInDriveTrash':0}
        with (patch('karaoke.google_drive_sync.load_client',return_value=('client','secret')),
              patch('karaoke.google_drive_sync.Drive',return_value=object()),
              patch('karaoke.online_wizard.read_drive_quota',return_value=quota)):
            wizard['show']('progress')
            actual=wizard['storage_views']['actual']
            forecast=wizard['storage_views']['forecast']
            self.assertTrue(self.pump(lambda:'50.0%' in actual[0].cget('text')))
            self.assertIn('70.0%',forecast[0].cget('text'))
            self.assertEqual(actual[0].winfo_class(),'TLabel')
            self.assertTrue(forecast[0].winfo_ismapped())
            self.assertEqual(wizard['progress_bar'].winfo_class(),'TProgressbar')
        # A severely narrow view remains vertically scrollable, not clipped.
        window=self.app._cloud_progress_window
        window.geometry('320x310+5+5')
        self.assertTrue(self.pump(lambda:window.winfo_width()<=330))
        self.assertLessEqual(wizard['progress'].winfo_width(),window.winfo_width()+3)

if __name__=='__main__':unittest.main()
