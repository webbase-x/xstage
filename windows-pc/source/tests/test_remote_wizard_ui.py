"""Drive real dialog callbacks with mocked widgets; no native GUI claims."""
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch
from karaoke.remote_ui import remote_window
from karaoke.wifi_network import WifiState


class Variable:
    def __init__(self, value=None): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value


class RemoteWizardUiTests(unittest.TestCase):
    def test_connection_options_failure_retry_finish_and_stop(self):
        widgets = []
        def widget(*args, **kwargs):
            w = Mock(); w.options = dict(kwargs); w.visible=False
            w.parent=args[0] if args else None
            def show(*a,**kw):w.visible=True
            def hide(*a,**kw):w.visible=False
            w.grid.side_effect=show;w.pack.side_effect=show
            w.grid_forget.side_effect=hide;w.grid_remove.side_effect=hide;w.pack_forget.side_effect=hide
            w.configure.side_effect = lambda *args, **values: w.options.update(values)
            w.selection.return_value = (); w.get_children.return_value = ()
            widgets.append(w)
            return w
        def button(text):
            return next(w for w in widgets if w.options.get('text') == text)
        def click(text): button(text).options['command']()
        window = Mock()
        monitor = Mock()
        monitor.snapshot.return_value = WifiState('denied')
        repair = Mock(running=False); repair.completed.return_value = None
        app = SimpleNamespace(remote=None, settings={}, _wifi_monitor=monitor,
            _wifi_repair=repair, library=Mock(), dispatch_remote=Mock(),
            get_remote_snapshot=Mock(), save_settings=Mock(), paint_lyrics=Mock(),
            show_error=Mock(), update_remote_snapshot=Mock())
        server = Mock(port=8080, request_key='123456', operator_key='654321')
        server.connected_count.return_value = 0
        server.capacity_stats.return_value = (1,0)
        server.policy = {'audio':False}
        with ExitStack() as stack:
            stack.enter_context(patch('karaoke.remote_ui.DialogWindow', return_value=window))
            stack.enter_context(patch('karaoke.dialog_layout.ActionBar', side_effect=widget))
            for name in ('Frame','Label','Button','Entry','Spinbox','Checkbutton','Radiobutton','Treeview','Progressbar','Style'):
                stack.enter_context(patch('karaoke.remote_ui.ttk.'+name, side_effect=widget))
            for name in ('StringVar','IntVar','BooleanVar'):
                stack.enter_context(patch('karaoke.remote_ui.tk.'+name, Variable))
            stack.enter_context(patch('PIL.ImageTk.PhotoImage', return_value=Mock()))
            factory = stack.enter_context(patch('karaoke.remote.RemoteServer', side_effect=[OSError('port busy'), server]))
            remote_window(app)
            self.assertEqual(button('ถัดไป →').options['state'], 'disabled')
            self.assertTrue(button('เปิดสิทธิ์อ่าน Wi-Fi').parent.visible)
            self.assertFalse(button('หยุดรีโมท').visible)
            click('ถัดไป →'); factory.assert_not_called()
            monitor.snapshot.return_value = WifiState('connected','Stage Wi-Fi','192.168.1.9')
            refresh = window.after.call_args.args[1]
            refresh()
            self.assertFalse(button('เปิดสิทธิ์อ่าน Wi-Fi').parent.visible)
            self.assertFalse(button('เชื่อมต่อ Wi-Fi').visible)
            click('ถัดไป →')
            click('ตั้งค่าเพิ่มเติม ▾');self.assertIsNotNone(button('ตั้งค่าเพิ่มเติม ▴'))
            click('ตั้งค่าเพิ่มเติม ▴');self.assertIsNotNone(button('ตั้งค่าเพิ่มเติม ▾'))
            self.assertEqual(button('บันทึกและเปิดรีโมท').options['state'], 'normal')
            for label, expected in [('แสดงตลอด',(True,False)),('แสดงเฉพาะช่วงรอเพลง',(True,True)),('ปิดการแสดง',(False,True))]:
                choice=button(label)
                choice.options['variable'].set(choice.options['value'])
                choice.options['command']()
                self.assertEqual((app.settings['remote_show_stage'],app.settings['remote_idle_only']),expected)
            click('บันทึกและเปิดรีโมท')
            self.assertIsNone(app.remote)
            app.show_error.assert_called_once()
            self.assertIsNotNone(button('บันทึกและเปิดรีโมท'))
            click('บันทึกและเปิดรีโมท')
            self.assertIs(app.remote, server); server.start.assert_called_once()
            self.assertIsNotNone(button('เสร็จสิ้น'))
            self.assertTrue(button('หยุดรีโมท').visible)
            self.assertFalse(button('ปิดหน้าต่าง').visible)
            click('เสร็จสิ้น'); window.destroy.assert_called_once()
            server.close.assert_not_called()
            click('หยุดรีโมท'); server.close.assert_called_once()
            self.assertIsNone(app.remote)
            self.assertFalse(button('หยุดรีโมท').visible)
            self.assertIsNotNone(button('ถัดไป →'))


if __name__ == '__main__': unittest.main()
