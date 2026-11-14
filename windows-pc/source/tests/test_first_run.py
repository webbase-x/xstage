import copy
import ctypes
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
from karaoke import first_run as setup
from karaoke import external_program as external
from karaoke.offline_components import validate_component, sha256


class FirstRunTests(unittest.TestCase):
    def test_new_machine_and_disconnected_device_are_distinct(self):
        self.assertEqual(setup.setup_reason({}, ['new'], 'A'), 'first_run')
        self.assertEqual(setup.setup_reason({'machine':'B','device':'old'}, ['new'], 'A'), 'new_machine')
        self.assertEqual(setup.setup_reason({'machine':'A','device':'old'}, ['new'], 'A'), 'missing_device')
        self.assertIsNone(setup.setup_reason({'machine':'A','device':'new'}, ['new'], 'A'))

    def test_migration_drops_hardware_but_preserves_curves_for_explicit_import(self):
        original = {'font_size':84, 'system_eq_device':'old-id', 'system_eq_profiles':{'old-id':{}},
                    'midi_device':4, 'eq_scope':'windows', 'output_eq':[3,0,-2], 'system_eq':{'curve':1}}
        before = copy.deepcopy(original)
        value = setup.portable_settings(original)
        self.assertEqual(original, before)
        self.assertEqual(value['font_size'],84)
        for key in setup.LOCAL_KEYS + setup.CURVE_KEYS + ('eq_scope',):
            self.assertNotIn(key,value)
        self.assertEqual(value['imported_audio_presets']['output_eq'],[3,0,-2])
        self.assertEqual(setup.portable_settings(value),value)

    def test_same_machine_restore_keeps_settings_but_unknown_machine_is_portable(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(setup,'machine_key',return_value='A'):
            path = Path(folder)
            settings = {'system_eq_device':'old','system_eq':{'curve':1}}
            self.assertNotIn('system_eq_device',setup.settings_for_restore(path,settings))
            (path/'transfer-meta.json').write_text(json.dumps({'machine':'A'}))
            self.assertEqual(setup.settings_for_restore(path,settings),settings)
            (path/'transfer-meta.json').write_text(json.dumps({'machine':'B'}))
            self.assertNotIn('system_eq_device',setup.settings_for_restore(path,settings))

    def test_cannot_finish_without_actual_hearing_confirmation(self):
        with patch.object(setup,'enumerate_devices') as devices:
            with self.assertRaises(ValueError):setup.save_choice(NS(),'id','name',False,False)
            devices.assert_not_called()

    def test_copied_data_directory_cannot_auto_activate_the_previous_machines_eq(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(setup,'machine_key',return_value='new'):
            path=Path(folder)/'audio-setup.json'
            path.write_text(json.dumps({'machine':'old','device':'old-card'}))
            self.assertTrue(setup.hardware_changed(folder))
            path.write_text(json.dumps({'machine':'new','device':'card'}))
            self.assertFalse(setup.hardware_changed(folder))

    def test_non_default_or_removed_device_cannot_be_saved_as_ready(self):
        for rows in ([], [('id','name',False)]):
            with self.subTest(rows=rows),patch.object(setup,'enumerate_devices',return_value=rows):
                with self.assertRaises(ValueError):setup.save_choice(NS(),'id','name',False,True)

    def test_optional_eq_cannot_be_marked_ready_without_link_and_user_test(self):
        from karaoke import system_eq
        with patch.object(setup,'enumerate_devices',return_value=[('id','name',True)]), \
             patch.object(system_eq,'installation',return_value=Path('config')), \
             patch.object(system_eq,'linked',return_value=False):
            with self.assertRaises(ValueError):setup.save_choice(NS(),'id','name',True,True,True)
        with patch.object(setup,'enumerate_devices',return_value=[('id','name',True)]), \
             patch.object(system_eq,'installation',return_value=Path('config')), \
             patch.object(system_eq,'linked',return_value=True):
            with self.assertRaises(ValueError):setup.save_choice(NS(),'id','name',True,True,False)

    def test_save_backs_up_original_and_never_reuses_curve_on_another_device(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            settings={'font_size':84,'system_eq_device':'old','system_eq':{'curve':1}}
            settings_path=path/'settings.json'
            settings_path.write_text(json.dumps(settings))
            original=settings_path.read_bytes()
            app=NS(data_dir=path,settings_path=settings_path,settings=settings)
            app.save_settings=lambda:settings_path.write_text(json.dumps(app.settings))
            with patch.object(setup,'enumerate_devices',return_value=[('new','Speaker',True)]):
                result=setup.save_choice(app,'new','Speaker',False,True)
            self.assertEqual(result['status'],'karaoke_ready')
            self.assertNotIn('system_eq_device',settings)
            self.assertEqual(settings['imported_audio_presets']['system_eq'],{'curve':1})
            backups=list((path/'setup-backups').glob('*/settings.json'))
            self.assertEqual(len(backups),1)
            self.assertEqual(backups[0].read_bytes(),original)

    def test_test_tone_targets_only_selected_device_without_changing_volume(self):
        from contextlib import contextmanager
        from karaoke import windows_audio
        selected=NS(id='wanted',channels=2,play=Mock())
        other=NS(id='other',channels=2,play=Mock())
        @contextmanager
        def audio():yield NS(all_speakers=lambda:[other,selected])
        with patch.object(windows_audio,'audio_context',audio):setup.test_tone('wanted')
        other.play.assert_not_called()
        data=selected.play.call_args.args[0]
        self.assertEqual(data.shape,(33600,2))
        self.assertLessEqual(abs(data).max(),.030001)


class ExternalProgramTests(unittest.TestCase):
    def test_external_qt_gets_its_own_plugins_and_parent_environment_is_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'qt/platforms').mkdir(parents=True)
            (root/'qt/platforms/qwindows.dll').write_bytes(b'fixture')
            inherited={'QT_PLUGIN_PATH':'bad','QT_QPA_PLATFORM':'offscreen','PATH':'normal'}
            env=external.environment(root,inherited)
            self.assertEqual(inherited['QT_PLUGIN_PATH'],'bad')
            self.assertNotIn('QT_QPA_PLATFORM',env)
            self.assertEqual(env['QT_PLUGIN_PATH'],str(root/'qt'))

    def test_bundle_path_is_removed_only_from_child(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(external.sys,'_MEIPASS',folder,create=True):
            original={'PATH':os.pathsep.join([folder,str(Path(folder)/'child'),'C:\\Windows'])}
            child=external.environment(folder,original)
            self.assertEqual(child['PATH'],'C:\\Windows')
            self.assertIn(folder,original['PATH'])

    def test_launch_restores_dll_path_even_if_popen_fails(self):
        kernel=NS(GetDllDirectoryW=Mock(return_value=0),SetDllDirectoryW=Mock(return_value=1))
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(external.sys,'platform','win32'),patch.object(external.sys,'frozen',True,create=True), \
             patch.object(external.ctypes,'WinDLL',return_value=kernel,create=True), \
             patch.object(external.subprocess,'Popen',side_effect=OSError('failed')):
            with self.assertRaises(OSError):external.launch(['tool.exe'],folder)
        self.assertEqual(kernel.SetDllDirectoryW.call_count,2)
        self.assertEqual(kernel.SetDllDirectoryW.call_args.args,(None,))

    def test_selector_uses_apo_working_directory_and_helper(self):
        from karaoke import system_eq
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'DeviceSelector.exe').write_bytes(b'fixture')
            with patch.object(system_eq,'installation',return_value=root/'config'), \
                 patch('karaoke.external_program.launch') as launch:
                system_eq.open_selector()
            self.assertEqual(launch.call_args.args[1],root)
            self.assertIn('Open-APO-Device.ps1',str(launch.call_args.args[0]))


class OfflinePackageTests(unittest.TestCase):
    def test_binary_without_source_and_license_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(OSError):validate_component(folder)

    def test_component_requires_all_matching_hashes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);component=root/'EqualizerAPO';component.mkdir()
            hashes={}
            for name in ('EqualizerAPO-x64-1.4.2.exe','EqualizerAPO-src-1.4.2.zip','COPYING.txt'):
                path=component/name;path.write_bytes(name.encode());hashes[name]=sha256(path)
            (component/'component.json').write_text(json.dumps({'name':'Equalizer APO','version':'1.4.2','architecture':'x64','sha256':hashes}))
            expected = component/'EqualizerAPO-x64-1.4.2.exe'
            actual = validate_component(root)
            # Windows TEMP may use an 8.3 alias while resolve() returns the
            # full Unicode path. Compare canonical paths AND file identity.
            self.assertEqual(actual, expected.resolve())
            self.assertTrue(actual.samefile(expected))
            for name in hashes:
                with self.subTest(tampered=name):
                    file = component/name
                    original = file.read_bytes()
                    file.write_bytes(b'changed')
                    try:
                        with self.assertRaises(ValueError):validate_component(root)
                    finally:
                        file.write_bytes(original)
