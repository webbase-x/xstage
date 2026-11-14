import unittest
from unittest.mock import patch,Mock
from types import SimpleNamespace
from karaoke import eq_scope,eq_ui,system_eq
from karaoke.eq_model import flat

class ScopeTests(unittest.TestCase):
    def test_xstage_never_touches_apo(self):
        with patch.object(system_eq,'installation') as lookup:
            self.assertIsNone(eq_scope.suspend_windows_eq({'eq_scope':'xstage'}));lookup.assert_not_called()
    def test_existing_windows_curve_is_bypassed_only_in_owned_file(self):
        with patch.object(system_eq,'installation',return_value='config'),patch.object(system_eq,'linked',return_value=True),patch.object(system_eq,'write',return_value=('path',b'old')) as write:
            result=eq_scope.suspend_windows_eq({'eq_scope':'windows','system_eq_device':'device'})
            self.assertEqual(result,('path',b'old'));self.assertTrue(write.call_args.args[0]['bypass']);self.assertEqual(write.call_args.args[1:],('device','config'))
    def test_missing_device_refuses_migration(self):
        with patch.object(system_eq,'installation',return_value='config'),patch.object(system_eq,'linked',return_value=True):
            with self.assertRaises(ValueError):eq_scope.suspend_windows_eq({'eq_scope':'windows'})
    def editor(self):
        app=SimpleNamespace(settings={'eq_scope':'windows'},engine=None,save_settings=Mock(),show_error=Mock())
        return SimpleNamespace(system=False,commit=lambda:True,app=app,state=flat(),mode=SimpleNamespace(get=lambda:'ขั้นสูง'),status=Mock())
    def test_apply_changes_scope_and_persists(self):
        e=self.editor()
        with patch.object(eq_scope,'suspend_windows_eq',return_value=('path',b'old')):
            eq_ui.EQWindow.apply(e)
        self.assertEqual(e.app.settings['eq_scope'],'xstage');self.assertEqual(e.saved,flat());e.app.show_error.assert_not_called()
    def test_save_failure_restores_scope_and_apo(self):
        e=self.editor();e.app.save_settings.side_effect=OSError('disk full')
        with patch.object(eq_scope,'suspend_windows_eq',return_value=('path',b'old')),patch.object(system_eq,'atomic_write') as restore:
            eq_ui.EQWindow.apply(e)
        self.assertEqual(e.app.settings,{'eq_scope':'windows'});restore.assert_called_once_with('path',b'old');e.app.show_error.assert_called_once()
    def test_reopen_hidden_window_restores_same_draft(self):
        old=Mock();old.winfo_exists.return_value=True;app=SimpleNamespace(_eq_window=old)
        self.assertIs(eq_ui.open_window(app),old);old.show.assert_called_once()
    def test_switch_to_karaoke_hides_without_destroying(self):
        e=SimpleNamespace(commit=Mock(),withdraw=Mock(),app=Mock())
        self.assertEqual(eq_ui.EQWindow.show_karaoke(e),'break');e.withdraw.assert_called_once();e.app.lift.assert_called_once()
