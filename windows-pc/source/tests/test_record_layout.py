import unittest
from types import SimpleNamespace as NS
from contextlib import ExitStack
from unittest.mock import Mock,patch
from karaoke.audio_tools_ui import record_window

class Var:
    def __init__(self,value=None):self.value=value;self.callback=None
    def get(self):return self.value
    def set(self,value):
        self.value=value
        if self.callback:self.callback()
    def trace_add(self,_,callback):self.callback=callback

class Widget:
    all=[]
    def __init__(self,parent=None,**kw):
        self.parent=parent;self.options=kw;self.children=[];self.visible=False;self.index=-1
        if hasattr(parent,'children'):parent.children.append(self)
        self.all.append(self)
    def __getattr__(self,name):return Mock()
    def pack(self,**kw):self.visible=True
    def pack_forget(self):self.visible=False
    def bind(self,*args,**kw):pass
    def winfo_children(self):return self.children
    def configure(self,**kw):self.options.update(kw)
    def set(self,value):self.index=-1
    def current(self,index=None):
        if index is not None:self.index=index
        return self.index

class Window(Widget):
    def __init__(self,parent):
        super().__init__(parent);self.content=Widget(self);self.footer=Widget(self)

class RecordLayoutTests(unittest.TestCase):
    def test_actions_stay_in_footer_and_mixer_is_only_shown_in_mix_mode(self):
        Widget.all=[]
        app=NS(_record_window=None,recorder=None,show_error=Mock())
        with ExitStack() as stack:
            stack.enter_context(patch('karaoke.audio_tools_ui.DialogWindow',Window))
            stack.enter_context(patch('karaoke.audio_tools_ui.ActionBar',Widget))
            for name in ('Frame','Label','Radiobutton','Combobox','Spinbox','Button'):
                stack.enter_context(patch('karaoke.audio_tools_ui.ttk.'+name,type(name,(Widget,),{})))
            for name in ('StringVar','IntVar'):stack.enter_context(patch('karaoke.audio_tools_ui.tk.'+name,Var))
            stack.enter_context(patch('karaoke.recording.WaveRecorder.devices',return_value=[(0,'Mic')]))
            stack.enter_context(patch('karaoke.mixed_recording.devices',return_value=[('mic','Mic')]))
            win=record_window(app)
            start=next(w for w in Widget.all if w.options.get('text')=='● เริ่มบันทึก')
            stop=next(w for w in Widget.all if w.options.get('text')=='■ จบบันทึก')
            self.assertIs(start.parent.parent,win.footer)
            self.assertIs(stop.parent,start.parent)
            mode=next(w.options['variable'] for w in Widget.all if w.options.get('value')=='mix')
            gains=[w for w in Widget.all if w.__class__.__name__=='Spinbox']
            self.assertEqual(len(gains),2)
            frame=gains[0].parent.parent
            self.assertFalse(frame.visible)
            self.assertTrue(all(w.options['state']=='disabled' for w in gains))
            mode.set('mix')
            self.assertTrue(frame.visible)
            self.assertTrue(all(w.options['state']=='normal' for w in gains))
            mode.set('input');self.assertFalse(frame.visible)
