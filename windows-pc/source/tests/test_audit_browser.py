import threading
import time
import unittest
from unittest.mock import Mock, MagicMock
from karaoke.font_metadata import MetadataLoader
from karaoke.preset_browser import PresetBrowser

class MetadataTests(unittest.TestCase):
    def wait_result(self, loader):
        end=time.monotonic()+2
        while time.monotonic()<end:
            result=loader.take()
            if result is not None:return result
            time.sleep(.005)
        self.fail('No metadata result')

    def test_hundred_requests_use_one_worker_and_keep_only_latest(self):
        entered=threading.Event();release=threading.Event();calls=[];threads=[]
        def inspect(path):
            calls.append(path);threads.append(threading.get_ident())
            if path=='slow':entered.set();release.wait(2)
            return {'presets':[(0,0,path)]}
        loader=MetadataLoader(inspect)
        try:
            loader.submit('slow');self.assertTrue(entered.wait(1))
            for i in range(100):last=loader.submit(str(i))
            self.assertEqual(loader.pending,(last,'99'))
            release.set();result=self.wait_result(loader)
            self.assertEqual(result[:2],(last,'99'))
            self.assertEqual(calls,['slow','99'])
            self.assertEqual(len(set(threads)),1)
        finally:release.set();loader.close();loader.thread.join(2)
        self.assertFalse(loader.thread.is_alive())

    def test_cancel_drops_inflight_and_pending_results(self):
        entered=threading.Event();release=threading.Event();finished=threading.Event();calls=[]
        def inspect(path):
            calls.append(path);entered.set();release.wait(2);finished.set();return {'presets':[]}
        loader=MetadataLoader(inspect)
        try:
            loader.submit('slow');self.assertTrue(entered.wait(1))
            loader.submit('pending');loader.cancel();release.set()
            self.assertTrue(finished.wait(1))
        finally:release.set();loader.close();loader.thread.join(2)
        self.assertIsNone(loader.take());self.assertEqual(calls,['slow'])

    def test_error_is_returned_and_next_request_succeeds(self):
        def inspect(path):
            if path=='bad':raise OSError('unavailable')
            return {'presets':[(0,0,'ok')]}
        loader=MetadataLoader(inspect)
        try:
            loader.submit('bad');self.assertIsInstance(self.wait_result(loader)[3],OSError)
            loader.submit('good');self.assertIsNone(self.wait_result(loader)[3])
        finally:loader.close();loader.thread.join(2)

class BrowserTests(unittest.TestCase):
    def browser(self):
        b=PresetBrowser.__new__(PresetBrowser)
        b.parent=Mock();b.generation=2;b.poll_id=None;b.pending_view=None
        b.loader=Mock();b.bank=MagicMock();b.cancel_button=Mock()
        b.render=Mock();b.info=Mock();b.apply_selection=Mock()
        return b
    def test_current_result_and_error_are_consumed_on_ui_thread(self):
        b=self.browser();b.loader.take.return_value=(2,'new',{'presets':[(1,3,'new')]},None)
        b.poll_load(2);self.assertEqual(b.rows,[(1,3,'new')]);b.render.assert_called_once()
        b.loader.take.return_value=(2,'new',None,OSError('unavailable'))
        b.poll_load(2);b.info.set.assert_called_with('unavailable')
    def test_old_poll_does_not_consume_new_result(self):
        b=self.browser();b.poll_load(1);b.loader.take.assert_not_called()
    def test_cancel_clears_timer_and_disables_button(self):
        b=self.browser();b.poll_id='timer';b.loader.cancel.return_value=3
        b.cancel_loading();self.assertEqual(b.generation,3)
        b.parent.after_cancel.assert_called_once_with('timer')
        b.cancel_button.configure.assert_called_once_with(state='disabled')
