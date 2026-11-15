import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
from karaoke.dialog_layout import ActionBar,DialogWindow

class Layout65Tests(unittest.TestCase):
    def test_action_bar_reflows_new_buttons_without_window_resize(self):
        first=Mock();first.winfo_reqwidth.return_value=100
        second=Mock();second.winfo_reqwidth.return_value=100
        buttons=[first]
        bar=NS(columns=0,_signature=None,winfo_children=lambda:buttons,
               winfo_width=lambda:240,columnconfigure=Mock())
        ActionBar.reflow(bar)
        buttons.append(second);ActionBar.reflow(bar)
        self.assertEqual(second.grid.call_args.kwargs['row'],1)
        bar.winfo_width=lambda:700;ActionBar.reflow(bar)
        self.assertEqual(second.grid.call_args.kwargs['row'],0)
    def test_wrapped_label_shrinks_then_restores_its_original_limit(self):
        class Label:
            def __init__(self):self.width=600
            def cget(self,key):return self.width
            def winfo_rootx(self):return 20
            def winfo_children(self):return []
            def configure(self,**kw):self.width=kw['wraplength']
        label=Label()
        window=NS(_wrap_pending=None,content=NS(winfo_children=lambda:[label]),
                  footer=NS(winfo_children=lambda:[]),winfo_rootx=lambda:0,
                  winfo_width=lambda:420,winfo_pixels=int)
        with patch('karaoke.dialog_layout.ttk.Label',Label),patch('karaoke.dialog_layout.tk.Label',Label):
            DialogWindow._wrap_text(window);self.assertEqual(label.width,372)
            window.winfo_width=lambda:1000
            DialogWindow._wrap_text(window);self.assertEqual(label.width,600)
