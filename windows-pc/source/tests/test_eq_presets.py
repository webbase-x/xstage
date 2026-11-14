import copy
import unittest
import numpy as np
from karaoke.eq_presets import builtins,intensity,compensate,Compare,wheel_steps
from karaoke.graphic_eq import flat,validate
from karaoke.eq_model import response

class PresetTests(unittest.TestCase):
    def test_factory_presets_are_independent_and_moderate(self):
        presets=builtins();self.assertEqual(len(presets),8)
        for state in presets.values():
            self.assertEqual(validate(state),state)
            self.assertLessEqual(max(abs(b['gain_db']) for b in state['bands']),3)
        presets['Rock']['bands'][0]['gain_db']=12
        self.assertEqual(builtins()['Rock']['bands'][0]['gain_db'],0)
    def test_intensity_endpoints_and_not_cumulative(self):
        state=builtins()['Dance'];old=copy.deepcopy(state)
        self.assertEqual(intensity(state,0),flat())
        self.assertEqual(intensity(state,100),state)
        self.assertAlmostEqual(intensity(state,50)['bands'][5]['gain_db'],state['bands'][5]['gain_db']/2)
        self.assertEqual(state,old)
        for bad in (-1,101,float('nan')):
            with self.assertRaises(ValueError):intensity(state,bad)
    def test_composite_headroom_against_dense_response(self):
        state=flat()
        for b in state['bands']:b['gain_db']=3
        adjusted=compensate(state)
        self.assertLess(adjusted['preamp_db'],-4)
        for rate in (44100,48000):
            freq=np.geomspace(20,rate*.49,32768)
            self.assertLess(np.max(response(adjusted,freq,rate)), -.95)
        self.assertEqual(compensate(flat()),flat())
        state['preamp_db']=-30
        self.assertEqual(compensate(state)['preamp_db'],-30)
    def test_bandwidth_response_matches_center_gain(self):
        state=flat();state['bands'][17]['gain_db']=6
        self.assertAlmostEqual(response(state,[1000])[0],6,places=6)
        self.assertLess(response(state,[2000])[0],.5)
    def test_ab_does_not_alias_and_preserves_each_slot(self):
        original=flat();compare=Compare(original)
        edited=builtins()['Rock'];compare.store(edited)
        self.assertEqual(compare.other(),original)
        compare.switch();self.assertEqual(compare.other(),edited)
        edited['bands'][0]['gain_db']=9
        self.assertNotEqual(compare.other(),edited)
    def test_wheel_windows_and_linux(self):
        self.assertEqual(wheel_steps(120),1);self.assertEqual(wheel_steps(-240),-2)
        self.assertEqual(wheel_steps(30),.25)
        self.assertEqual(wheel_steps(num=4),1);self.assertEqual(wheel_steps(num=5),-1)
