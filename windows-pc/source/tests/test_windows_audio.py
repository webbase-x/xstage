"""COM ownership simulation reproduces SoundCard's first-import S_FALSE bug."""
import sys
import threading
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
from karaoke.windows_audio import com_context,load_soundcard,audio_context

class AudioComTests(unittest.TestCase):
    def test_success_and_already_initialized_each_balance_one_reference(self):
        for hr in (0,1):
            ole=Mock();ole.CoInitializeEx.return_value=hr
            with self.assertRaises(ValueError):
                with com_context(ole):raise ValueError('capture failed')
            ole.CoUninitialize.assert_called_once()
    def test_existing_sta_is_not_uninitialized(self):
        ole=Mock();ole.CoInitializeEx.return_value=-2147417850
        with com_context(ole):pass
        ole.CoUninitialize.assert_not_called()
    def test_real_error_not_suppressed_or_uninitialized(self):
        ole=Mock();ole.CoInitializeEx.return_value=-2147024891
        with self.assertRaisesRegex(OSError,'80070005'):
            with com_context(ole):self.fail('must not enter')
        ole.CoUninitialize.assert_not_called()
    def test_import_on_clean_thread_then_release_same_thread(self):
        caller=threading.get_ident();threads=[];module=NS();owner=NS(com_loaded=True)
        backend=NS(_com=owner,_ole32=NS(CoUninitialize=lambda:threads.append(threading.get_ident())))
        def import_module(name):
            threads.append(threading.get_ident());sys.modules['soundcard']=module;sys.modules['soundcard.mediafoundation']=backend;return module
        with patch.dict(sys.modules):
            sys.modules.pop('soundcard',None);sys.modules.pop('soundcard.mediafoundation',None)
            with patch('karaoke.windows_audio.importlib.import_module',side_effect=import_module) as importer:
                self.assertIs(load_soundcard(),module);self.assertIs(load_soundcard(),module);importer.assert_called_once()
        self.assertEqual(threads[0],threads[1]);self.assertNotEqual(threads[0],caller);self.assertFalse(owner.com_loaded)
    def test_first_import_precedes_callers_com_initialization(self):
        events=[];ole=Mock();ole.CoInitializeEx.side_effect=lambda *a:events.append('init') or 0
        def load():events.append('import');return 'module'
        from karaoke.windows_audio import com_context as real_context
        with patch('karaoke.windows_audio.sys.platform','win32'),patch('karaoke.windows_audio.load_soundcard',side_effect=load),patch('karaoke.windows_audio.com_context',side_effect=lambda:real_context(ole)):
            with audio_context() as module:self.assertEqual(module,'module')
        self.assertEqual(events,['import','init']);ole.CoUninitialize.assert_called_once()
    def test_import_failure_surfaces_and_can_retry(self):
        with patch.dict(sys.modules):
            sys.modules.pop('soundcard',None)
            with patch('karaoke.windows_audio.importlib.import_module',side_effect=ImportError('missing soundcard')):
                with self.assertRaisesRegex(ImportError,'missing soundcard'):load_soundcard()
    def test_external_preimport_is_not_released_on_wrong_thread(self):
        module=NS();backend=NS(_com=NS(com_loaded=True),_ole32=Mock())
        with patch.dict(sys.modules,{'soundcard':module,'soundcard.mediafoundation':backend}):self.assertIs(load_soundcard(),module)
        backend._ole32.CoUninitialize.assert_not_called()
