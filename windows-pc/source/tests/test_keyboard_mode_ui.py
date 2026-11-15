import unittest
from contextlib import ExitStack
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
from karaoke.keyboard_controls import PreviewVoice

class Var:
    def __init__(self,value=None):self.value=value
    def set(self,value):self.value=value
    def get(self):return self.value

class Widget:
    def __init__(self,parent=None,**kw):
        self.options=kw;self.children=[];self.events={};self.grid_data={};self.visible=True
        if hasattr(parent,'children'):parent.children.append(self)
    def __getattr__(self,name):return Mock()
    def grid(self,**kw):self.grid_data=kw
    def grid_info(self):return self.grid_data
    def winfo_children(self):return self.children
    def winfo_reqwidth(self):return 85
    def winfo_reqheight(self):return 28
    def winfo_width(self):return 1000
    def winfo_height(self):return 200
    def winfo_exists(self):return True
    def winfo_ismapped(self):return self.visible
    def winfo_pointerxy(self):return (400,10)
    def winfo_rootx(self):return 350
    def winfo_rooty(self):return 0
    def grab_current(self):return None
    def bind(self,event,callback):self.events[event]=callback
    def place_forget(self):self.visible=False
    def configure(self,*args,**kw):self.options.update(kw)

class KeyboardModeTests(unittest.TestCase):
    def test_explicit_play_search_escape_and_focus_loss(self):
        from karaoke.midi_keyboard import open_keyboard
        output=Mock();voice=PreviewVoice(lambda:output)
        app=NS(settings={},engine=None,children=[],_keyboard_voice=voice,_fx_rack=Mock(),
            winfo_width=lambda:1920,winfo_height=lambda:1080,winfo_fpixels=lambda _:96,
            bind=Mock(),focus_set=Mock(),update_idletasks=Mock(),save_settings=Mock(),show_error=Mock())
        widgets=[]
        def factory(*args,**kw):
            widget=Widget(*args,**kw);widgets.append(widget);return widget
        with ExitStack() as stack:
            for name in ('Frame','Canvas'):stack.enter_context(patch('tkinter.'+name,side_effect=factory))
            for name in ('Button','Label','Radiobutton','Checkbutton','Combobox','Style'):
                stack.enter_context(patch('tkinter.ttk.'+name,side_effect=factory))
            for name in ('StringVar','BooleanVar'):stack.enter_context(patch('tkinter.'+name,Var))
            panel=open_keyboard(app)
            play=next(w for w in widgets if w.options.get('text')=='เล่นคีย์บอร์ด')
            canvas=next(w for w in widgets if '<KeyPress>' in w.events)
            mode=play.options['variable'];down=canvas.events['<KeyPress>'];up=canvas.events['<KeyRelease>']
            self.assertEqual(mode.get(),'search')
            self.assertIsNone(down(NS(keysym='a',char='a')));self.assertFalse(voice.notes)
            mode.set('play');play.options['command']()
            for key in ('a','d','g'):self.assertEqual(down(NS(keysym=key,char=key)),'break')
            self.assertEqual(voice.notes,{60,64,67})
            self.assertEqual(down(NS(keysym='q',char='q')),'break')
            up(NS(keysym='d'));self.assertEqual(voice.notes,{60,67})
            down(NS(keysym='Escape',char=''));self.assertEqual(mode.get(),'search');self.assertFalse(voice.notes)
            mode.set('play');down(NS(keysym='a',char='a'))
            canvas.events['<FocusOut>'](None)
            self.assertFalse(voice.notes);self.assertEqual(mode.get(),'search')
            panel._keyboard_hide();self.assertFalse(panel.visible)
