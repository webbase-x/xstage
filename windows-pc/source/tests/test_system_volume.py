import ctypes as C
import unittest
from contextlib import contextmanager
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from karaoke import system_volume as sv
from karaoke.performer import PlaybackApp

class Var:
    def __init__(self,value=0):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value

class SystemVolumeTests(unittest.TestCase):
    def app(self):
        app=NS(system_volume=Mock(),volume_var=Var(30),status_var=Var(),_syncing_volume=False)
        app.system_volume.read.return_value=(72,True)
        app.read_system_volume=lambda:PlaybackApp.read_system_volume(app)
        return app
    def test_external_windows_changes_update_ui_without_writing_back(self):
        app=self.app();app.read_system_volume()
        self.assertEqual(app.volume_var.get(),72);self.assertTrue(app._windows_muted)
        app.system_volume.write.assert_not_called()
    def test_slider_write_uses_confirmed_windows_value(self):
        app=self.app();app.volume_var.set(45);app.system_volume.write.return_value=(44.8,False)
        PlaybackApp.apply_volume(app)
        app.system_volume.write.assert_called_once_with(45)
        self.assertEqual(app.volume_var.get(),44.8)
        self.assertFalse(app._windows_muted)
    def test_poll_feedback_cannot_write_system_volume(self):
        app=self.app();app._syncing_volume=True
        PlaybackApp.apply_volume(app);app.system_volume.write.assert_not_called()
    def test_failed_write_restores_readback(self):
        app=self.app();app.system_volume.write.side_effect=OSError('disconnected')
        PlaybackApp.apply_volume(app)
        self.assertEqual(app.volume_var.get(),72)
        self.assertIn('disconnected',app.status_var.get())
    def test_missing_device_poll_retries(self):
        app=self.app();app.system_volume.read.side_effect=OSError('no device')
        app.after=Mock(return_value='timer');app.poll_system_volume=Mock()
        PlaybackApp.poll_system_volume(app)
        app.after.assert_called_once_with(400,app.poll_system_volume)
    def test_wheel_reads_latest_windows_value_before_increment(self):
        app=self.app();surface=object()
        app.surface=surface;app.preview=app.video_frame=app.stage=app.stage_canvas=app.stage_video=None
        app.apply_volume=Mock();app.show_volume_overlay=Mock()
        event=NS(widget=surface,delta=120,num=None)
        self.assertEqual(PlaybackApp.volume_wheel(app,event),'break')
        self.assertEqual(app.volume_var.get(),77)
        app.apply_volume.assert_called_once()
    def test_wheel_device_error_does_not_guess_or_write(self):
        app=self.app();surface=object()
        app.surface=surface;app.preview=app.video_frame=app.stage=app.stage_canvas=app.stage_video=None
        app.system_volume.read.side_effect=OSError('missing')
        app.apply_volume=Mock();app.show_volume_overlay=Mock()
        PlaybackApp.volume_wheel(app,NS(widget=surface,delta=120,num=None))
        app.apply_volume.assert_not_called()
        self.assertEqual(app.volume_var.get(),30)
    def test_guid_layout_and_hresult_sign(self):
        self.assertEqual(C.sizeof(sv.GUID),16)
        self.assertEqual(bytes(sv.CLSID_ENUM).hex(),'9503debc2fe57c468e3dc4579291692e')
        sv.checked(0);sv.checked(1)
        with self.assertRaises(OSError):sv.checked(0x80070490)
    def test_native_write_clamps_reads_back_and_mute_state(self):
        controller=object.__new__(sv.WindowsVolume)
        @contextmanager
        def endpoint():yield C.c_void_p(123)
        controller.endpoint=endpoint
        def invoke(pointer,index,argtypes=(),args=(),**kw):
            if index==9:C.cast(args[0],C.POINTER(C.c_float))[0]=.65
            if index==15:C.cast(args[0],C.POINTER(sv.BOOL))[0]=1
            return 0
        with patch.object(sv,'invoke',side_effect=invoke) as calls:
            level,muted=controller.write(150)
            self.assertAlmostEqual(level,65,places=4);self.assertTrue(muted)
            self.assertEqual(calls.call_args_list[0].args[1],7)
            self.assertEqual(calls.call_args_list[0].args[3],(1.,None))
            self.assertEqual(calls.call_args_list[1].args[3],(0,None))
            calls.reset_mock();controller.write(-10)
            self.assertEqual(calls.call_args_list[1].args[3],(1,None))
        with self.assertRaises(ValueError):controller.write(float('nan'))
    def test_endpoint_releases_all_com_references_after_error(self):
        controller=object.__new__(sv.WindowsVolume);controller.closed=False
        def create(*args):C.cast(args[-1],C.POINTER(C.c_void_p))[0]=101;return 0
        controller.ole=NS(CoCreateInstance=create)
        def invoke(pointer,index,argtypes=(),args=(),**kw):
            if index==4:C.cast(args[-1],C.POINTER(C.c_void_p))[0]=102
            if index==3:C.cast(args[-1],C.POINTER(C.c_void_p))[0]=103
            return 0
        with patch.object(sv,'invoke',side_effect=invoke) as calls:
            with self.assertRaises(RuntimeError):
                with controller.endpoint():raise RuntimeError('read failed')
            self.assertEqual([c.args[0].value for c in calls.call_args_list if c.args[1]==2],[103,102,101])
    def test_close_com_once(self):
        controller=object.__new__(sv.WindowsVolume)
        controller.closed=False;controller.owns_com=True;controller.ole=Mock()
        controller.close();controller.close()
        controller.ole.CoUninitialize.assert_called_once()
