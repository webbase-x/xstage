"""Dialog callback tests; no assertion of native Windows layout or sound."""
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
from karaoke import audio_tools_ui as ui

class Variable:
    def __init__(self,value=None):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value
    def trace_add(self,*args):pass
class Widget:
    all=[]
    def __init__(self,parent=None,**kw):
        self.options=kw;self.children=[];self.index=-1;self.callbacks=[]
        if isinstance(parent,Widget):parent.children.append(self)
        Widget.all.append(self)
    def pack(self,**kw):pass
    def pack_forget(self):pass
    def bind(self,*a,**kw):pass
    def configure(self,**kw):self.options.update(kw)
    def winfo_children(self):return self.children
    def current(self,index=None):
        if index is not None:self.index=index
        return self.index
    def set(self,value):self.value=value
    def after(self,ms,fn):self.callbacks.append(fn)
    def winfo_exists(self):return True
    def title(self,*a):pass
    def geometry(self,*a):pass
    def protocol(self,*a):pass
    def destroy(self):pass
    def lift(self):pass

class AudioDialogTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close);Widget.all=[]
        self.window=Widget();self.window.content=Widget();self.window.footer=Widget()
        self.stack.enter_context(patch.object(ui,'DialogWindow',return_value=self.window))
        self.stack.enter_context(patch.object(ui,'ActionBar',Widget))
        for name in ('Label','Frame','Button','Spinbox','Radiobutton','Combobox'):self.stack.enter_context(patch.object(ui.ttk,name,Widget))
        for name in ('StringVar','DoubleVar','IntVar'):self.stack.enter_context(patch.object(ui.tk,name,Variable))
        self.app=NS(home=Path('.'),engine=None,recorder=None,settings={},save_settings=Mock(),show_error=Mock())
    def click(self,text):next(w for w in Widget.all if w.options.get('text')==text).options['command']()
    def test_eq_routes_to_new_editor(self):
        with patch('karaoke.eq_ui.open_window',return_value=self.window) as opened:
            self.assertIs(ui.eq_window(self.app),self.window)
            opened.assert_called_once_with(self.app)
    def test_record_start_and_close_file_callbacks(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'test.wav';rec=NS(start=Mock(),stop=Mock(),error=None,path=file,writer=None,thread=Mock())
            rec.thread.is_alive.return_value=False
            self.stack.enter_context(patch('karaoke.recording.WaveRecorder.devices',return_value=[(0,'mic')]))
            factory=self.stack.enter_context(patch('karaoke.recording.WaveRecorder',return_value=rec));factory.devices.return_value=[(0,'mic')]
            self.stack.enter_context(patch.object(ui.filedialog,'asksaveasfilename',return_value=str(file)))
            ui.record_window(self.app);self.click('● เริ่มบันทึก');rec.start.assert_called_once()
            self.click('■ จบบันทึก');self.window.callbacks[-1]();self.assertIsNone(self.app.recorder)
    def test_diagnostics_refuses_while_song_active(self):
        info=dict(windows=True,soundcard=True,native={})
        self.stack.enter_context(patch('karaoke.audio_diagnostics.readiness',return_value=info))
        probe=self.stack.enter_context(patch('karaoke.audio_diagnostics.probe_output'))
        self.app.engine=object();ui.diagnostics_window(self.app);self.click('ทดสอบลำโพง');probe.assert_not_called()

    def test_probe_failure_is_visible_and_exported_with_traceback(self):
        import json
        info=dict(windows=True,soundcard=True,native={})
        self.stack.enter_context(patch('karaoke.audio_diagnostics.readiness',return_value=info))
        self.stack.enter_context(patch('karaoke.audio_diagnostics.probe_output',side_effect=RuntimeError('device failed')))
        self.stack.enter_context(patch.object(ui.threading,'Thread',side_effect=lambda target,**kw:NS(start=target)))
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'report.json'
            self.stack.enter_context(patch.object(ui.filedialog,'asksaveasfilename',return_value=str(path)))
            ui.diagnostics_window(self.app)
            with self.assertLogs(level='ERROR'):self.click('ทดสอบลำโพง')
            self.assertFalse(self.app._audio_probe_busy)
            self.click('บันทึกรายงาน')
            error=json.loads(path.read_text(encoding='utf-8'))['output_test']['error']
            self.assertEqual(error['message'],'device failed');self.assertEqual(error['type'],'RuntimeError')
            self.assertIn('Traceback',error['traceback'])
