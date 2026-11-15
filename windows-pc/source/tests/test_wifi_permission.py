import unittest
import tempfile
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
from karaoke.wifi_permission import PermissionRepair,PendingRemoteStart,wifi_heading,repair_script
from karaoke.wifi_network import WifiState

class PermissionTests(unittest.TestCase):
    def test_denied_heading_is_not_disconnected(self):
        text=wifi_heading(WifiState('denied'))
        self.assertIn('ปิดสิทธิ์',text);self.assertNotIn('ไม่ได้เชื่อมต่อ',text)
    def test_connected_heading_keeps_exact_ssid(self):
        self.assertEqual(wifi_heading(WifiState('connected','เวที TP-Link','10.0.0.5')),'เวที TP-Link')
    def test_other_states_differ(self):
        self.assertNotEqual(wifi_heading(WifiState('checking')),wifi_heading(WifiState('disconnected')))
        self.assertNotEqual(wifi_heading(WifiState('no_adapter')),wifi_heading(WifiState('error')))
    def test_source_distribution_has_repair_script(self):
        self.assertTrue(repair_script().is_file())
    def test_frozen_distribution_resolves_beside_exe(self):
        with tempfile.TemporaryDirectory() as temporary:
            installation=Path(temporary).resolve()/"ไพรัช  อินควรชุม"/"teacher's folder"
            script=installation/'tools'/'Repair-XStage-WiFi.ps1'
            script.parent.mkdir(parents=True)
            script.write_text('# fixture',encoding='utf-8')
            with patch('karaoke.wifi_permission.sys.frozen',True,create=True),patch('karaoke.wifi_permission.sys.executable',str(installation/'XStageKaraoke.exe')):
                self.assertEqual(repair_script(),script)
                script.unlink()
                with self.assertRaises(FileNotFoundError):repair_script()
    def test_missing_script_is_reported(self):
        with patch.object(Path,'is_file',return_value=False):
            with self.assertRaises(FileNotFoundError):repair_script()
    def test_launch_has_no_shell_interpolation_and_no_pause(self):
        process=Mock();process.poll.return_value=None
        with tempfile.TemporaryDirectory() as temporary:
            script=Path(temporary).resolve()/"ไพรัช  อินควรชุม"/"teacher's folder"/'Repair.ps1'
            with patch('karaoke.wifi_permission.sys.platform','win32'),patch('karaoke.wifi_permission.repair_script',return_value=script),patch('karaoke.wifi_permission.subprocess.Popen',return_value=process) as spawn:
                controller=PermissionRepair();self.assertTrue(controller.launch())
                args=spawn.call_args.args[0]
                self.assertIsInstance(args,list)
                self.assertEqual(args[args.index('-File')+1],str(script))
                self.assertEqual(args.count(str(script)),1)
                self.assertIn('-NoPause',args);self.assertNotIn('shell',spawn.call_args.kwargs)
                self.assertFalse(controller.launch());self.assertEqual(spawn.call_count,1)
    def test_windows_drive_and_unc_script_stay_single_arguments(self):
        paths=[PureWindowsPath("C:/Users/ไพรัช  อินควรชุม/teacher's folder/Repair.ps1"),
               PureWindowsPath('//server/share/Thai folder/Repair.ps1')]
        for script in paths:
            with self.subTest(path=str(script)),patch('karaoke.wifi_permission.sys.platform','win32'),patch('karaoke.wifi_permission.repair_script',return_value=script),patch('karaoke.wifi_permission.subprocess.Popen') as spawn:
                PermissionRepair().launch()
                args=spawn.call_args.args[0]
                self.assertEqual(args[args.index('-File')+1],str(script))
                self.assertNotIn('/',args[args.index('-File')+1])
    def test_restore_flag_is_explicit(self):
        with patch('karaoke.wifi_permission.sys.platform','win32'),patch('karaoke.wifi_permission.subprocess.Popen',return_value=Mock()) as spawn:
            PermissionRepair().launch(restore=True)
            self.assertIn('-RestoreLatest',spawn.call_args.args[0])
    def test_completion_delivered_once(self):
        controller=PermissionRepair();controller.process=NS(poll=lambda:0)
        self.assertEqual(controller.completed(),0);self.assertIsNone(controller.completed())
    def test_cancelled_uac_reported_as_failure(self):
        controller=PermissionRepair();controller.process=NS(poll=lambda:1)
        self.assertEqual(controller.completed(),1);self.assertFalse(controller.running)
    def test_no_start_without_request(self):
        self.assertFalse(PendingRemoteStart().consume(True))
    def test_wait_until_ready_start_once(self):
        pending=PendingRemoteStart();pending.request();self.assertFalse(pending.consume(False))
        self.assertTrue(pending.consume(True));self.assertFalse(pending.consume(True))
    def test_stop_or_window_close_cancels_pending_start(self):
        pending=PendingRemoteStart();pending.request();pending.cancel();self.assertFalse(pending.consume(True))
    def test_non_windows_does_not_launch(self):
        with patch('karaoke.wifi_permission.sys.platform','linux'),patch('karaoke.wifi_permission.subprocess.Popen') as spawn:
            with self.assertRaises(OSError):PermissionRepair().launch()
            spawn.assert_not_called()

if __name__=='__main__':unittest.main()
