import logging
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from karaoke.runtime_diagnostics import Diagnostics, start
from karaoke.instance_lock import DataDirectoryLock

class Diagnostics060Tests(unittest.TestCase):
    def test_every_event_has_session(self):
        with tempfile.TemporaryDirectory() as d:
            diagnostics=Diagnostics(d)
            try:
                logging.info('RECORDING_STARTED fixture')
                text=(Path(d)/'XStageKaraoke.log').read_text(encoding='utf-8')
                self.assertIn('[session='+diagnostics.session+']',text)
                self.assertIn('RECORDING_STARTED fixture',text)
            finally:diagnostics.close()
    def test_separate_data_directories_get_separate_logs(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{'LOCALAPPDATA':d}):
            first=start(Path(d)/'one');first_path=first.directory;first.close()
            second=start(Path(d)/'two')
            try:self.assertNotEqual(first_path,second.directory)
            finally:second.close()
    def test_startup_diagnostics_failure_releases_data_lock(self):
        import main
        with tempfile.TemporaryDirectory() as d, patch.object(sys,'argv',['main.py','--data-dir',d]), patch('karaoke.runtime_diagnostics.start',side_effect=OSError('log device full')):
            with self.assertRaises(OSError):main.main()
            lock=DataDirectoryLock(d).acquire();lock.close()
