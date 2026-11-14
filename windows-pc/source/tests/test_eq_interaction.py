import copy
import os
import time
import unittest
from unittest.mock import Mock
from karaoke.eq_interaction import ramp_frame,flow_positions
from karaoke.graphic_eq import flat

class InteractionTests(unittest.TestCase):
    def curve(self):
        value=flat();value['bands'][10]['gain_db']=8;value['preamp_db']=-9
        return value
    def test_bypass_fades_audible_gain_and_preserves_original_curve(self):
        start=self.curve();target=copy.deepcopy(start);target['bypass']=True
        mid=ramp_frame(start,target,.5)
        self.assertFalse(mid['bypass']);self.assertEqual(mid['bands'][10]['gain_db'],4)
        self.assertEqual(mid['preamp_db'],-4.5)
        self.assertEqual(ramp_frame(start,target,1),target)
        self.assertEqual(start,self.curve())
    def test_unbypass_starts_from_unity(self):
        target=self.curve();start=copy.deepcopy(target);start['bypass']=True
        frame=ramp_frame(start,target,.125)
        self.assertEqual(frame['bands'][10]['gain_db'],1)
        self.assertEqual(frame['preamp_db'],-1.125)
        self.assertEqual(ramp_frame(start,target,1),target)
    def test_flat_is_monotonic(self):
        frames=[ramp_frame(self.curve(),flat(),n/8) for n in range(9)]
        self.assertEqual([x['bands'][10]['gain_db'] for x in frames],list(range(8,-1,-1)))
        self.assertEqual(frames[-1],flat())
    def test_bypassed_preset_changes_stay_unity_until_endpoint(self):
        start=self.curve();start['bypass']=True
        target=flat();target['bypass']=True;target['bands'][1]['gain_db']=12
        mid=ramp_frame(start,target,.5)
        self.assertEqual(sum(abs(b['gain_db']) for b in mid['bands']),0)
        self.assertEqual(ramp_frame(start,target,1),target)
    def test_wrapping_does_not_share_grid_column_widths(self):
        positions,height=flow_positions([(250,30),(60,40),(60,30),(250,50)],330)
        self.assertEqual(positions[0][1],positions[1][1])
        self.assertEqual(positions[2][1],positions[3][1])
        for x,y,w,h in positions:
            self.assertLessEqual(x+w,330);self.assertLessEqual(y+h,height)
    def test_one_oversize_control_does_not_push_next_offscreen(self):
        positions,height=flow_positions([(900,40),(80,20)],320)
        self.assertEqual(positions[0][2],314)
        self.assertGreater(positions[1][1],positions[0][1])

@unittest.skipUnless(os.environ.get('DISPLAY'),'Requires an explicit GUI test display')
class RackIntegrationTests(unittest.TestCase):
    def test_debounce_ramps_child_window_and_large_controls(self):
        import tkinter as tk
        from unittest.mock import patch
        from karaoke.graphic_eq_ui import GraphicEQ,SpectrumCapture
        from karaoke.song_eq_ui import open_manager
        root=tk.Tk();root.geometry('1440x800');root.settings={};root.engine=None
        root.current_song=None;root.save_settings=Mock();root.show_error=Mock();errors=[]
        root.report_callback_exception=lambda *args:errors.append(str(args))
        def pump(seconds=.08):
            until=time.monotonic()+seconds
            while time.monotonic()<until:root.update();time.sleep(.005)
        with patch.object(SpectrumCapture,'start',lambda self:None):
            eq=GraphicEQ(root);pump()
            def settle():
                until=time.monotonic()+5
                while eq.transition and time.monotonic()<until:pump(.02)
                self.assertIsNone(eq.transition)
            try:
                for _ in range(10):eq.step(.5)
                self.assertEqual(eq.saved['bands'][0]['gain_db'],5)
                root.save_settings.assert_not_called()
                self.assertEqual(root.settings['graphic_eq'],eq.saved)
                pump(.5);root.save_settings.assert_called_once()
                original=copy.deepcopy(eq.saved)
                eq.bypass();self.assertFalse(eq.saved['bypass'])
                self.assertGreater(eq.saved['bands'][0]['gain_db'],0)
                self.assertLess(eq.saved['bands'][0]['gain_db'],5)
                settle();self.assertTrue(eq.saved['bypass'])
                self.assertEqual(eq.saved['bands'],original['bands'])
                eq.bypass();settle();self.assertEqual(eq.saved,original)
                eq.bypass();eq.bypass();settle();self.assertEqual(eq.saved,original)
                eq.reset();self.assertNotEqual(eq.saved,flat());settle();self.assertEqual(eq.saved,flat())
                eq.step(1);root.save_settings.reset_mock();eq.dock()
                root.save_settings.assert_called_once();eq.show();pump()
                child=open_manager(eq);eq.child_windows.add(child);pump()
                eq.dock();self.assertTrue(eq.winfo_ismapped())
                with patch.object(eq,'winfo_pointerxy',return_value=(4000,4000)):
                    eq.seen=True;eq.outside=time.monotonic()-3
                    eq.after_cancel(eq.timer);eq.timer=None;eq.poll()
                    self.assertTrue(eq.winfo_ismapped());self.assertIsNone(eq.outside)
                child.destroy();pump();self.assertFalse(eq.child_open())
                # Simulate wide translated labels/high-DPI button metrics.
                def descendants(widget):
                    for child in widget.winfo_children():yield child;yield from descendants(child)
                for widget in descendants(eq.bottom):
                    if isinstance(widget,tk.Button):widget.configure(font=('DejaVu Sans',16),text='Wide control label')
                eq.geometry('800x700+0+0');pump(.2)
                # Poll-triggered fitting uses the latest row sizes.
                eq.fit_to_screen();pump(.1)
                for widget in descendants(eq.bottom):
                    if isinstance(widget,(tk.Button,tk.Checkbutton,tk.Spinbox)):
                        self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),eq.winfo_rootx()+eq.winfo_width())
                        self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),eq.winfo_rooty()+eq.winfo_height())
                self.assertGreaterEqual(eq.canvas.winfo_height(),150)
                root.show_error.assert_not_called();self.assertFalse(errors,errors)
            finally:eq.destroy();root.update();root.destroy()
