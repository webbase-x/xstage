import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from karaoke.performer import PlaybackApp
from karaoke.ui import KaraokeApp
from karaoke.classic import ClassicApp

class MenuDispatchTests(unittest.TestCase):
    def test_callback_runs_after_menu_release(self):
        events = []
        app = SimpleNamespace(context_menu=SimpleNamespace(
            unpost=lambda: events.append('unpost'), grab_release=lambda: events.append('release')),
            closing=False, after_idle=Mock(), show_error=Mock())
        callback = Mock(side_effect=lambda: events.append('callback'))
        PlaybackApp.defer_menu_command(app, callback)
        callback.assert_not_called()
        self.assertEqual(events, ['unpost', 'release'])
        app.after_idle.call_args.args[0]()
        self.assertEqual(events, ['unpost', 'release', 'callback'])

    def test_callback_error_is_visible(self):
        app = SimpleNamespace(context_menu=Mock(), closing=False, after_idle=Mock(), show_error=Mock())
        PlaybackApp.defer_menu_command(app, Mock(side_effect=ValueError('bad folder')))
        with self.assertLogs(level='ERROR'):
            app.after_idle.call_args.args[0]()
        self.assertEqual(str(app.show_error.call_args.args[0]), 'bad folder')

    def test_closed_app_ignores_pending_command(self):
        app = SimpleNamespace(context_menu=Mock(), closing=True, after_idle=Mock())
        callback = Mock()
        PlaybackApp.defer_menu_command(app, callback)
        app.after_idle.call_args.args[0]()
        callback.assert_not_called()

    def test_folder_picker_owned_and_cancel_noop(self):
        app = SimpleNamespace(scanning=True, start_scan=Mock(), settings={}, save_settings=Mock(), status_var=Mock())
        with patch('karaoke.ui.filedialog.askdirectory', return_value='D:/Songs') as picker:
            KaraokeApp.add_folder(app)
            self.assertIs(picker.call_args.kwargs['parent'], app)
        app.start_scan.assert_not_called()
        self.assertEqual(len(app.settings['song_folders']), 1)
        app.save_settings.assert_called_once()
        app.start_scan.reset_mock()
        with patch('karaoke.ui.filedialog.askdirectory', return_value=''):
            KaraokeApp.add_folder(app)
        app.start_scan.assert_not_called()

    def test_files_cancel_and_catalog_ownership(self):
        app = SimpleNamespace(scanning=False, start_index_job=Mock(), start_catalog=Mock())
        with patch('karaoke.ui.filedialog.askopenfilenames', return_value=()) as picker:
            KaraokeApp.add_files(app)
            self.assertIs(picker.call_args.kwargs['parent'], app)
        app.start_index_job.assert_not_called()
        with patch('karaoke.classic.filedialog.askdirectory', return_value='') as picker:
            ClassicApp.connect_catalog(app)
            self.assertIs(picker.call_args.kwargs['parent'], app)
        app.start_catalog.assert_not_called()

    def test_scan_keeps_status_visible(self):
        app = SimpleNamespace(_transport_timer=None, transport_pinned_var=Mock(),
            _pointer_on_transport=False, scanning=True, transport=Mock())
        app.transport_pinned_var.get.return_value = False
        PlaybackApp.hide_transport(app)
        app.transport.place_forget.assert_not_called()

if __name__ == '__main__': unittest.main()

