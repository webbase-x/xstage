import copy
import ctypes as C
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
import numpy as np
from karaoke.eq_model import flat,validate,response,peak_gain,headroom
from karaoke.parametric_eq import Processor,Biquad,Volume

class ModelTests(unittest.TestCase):
    def test_flat_and_bypass_are_unity(self):
        s=flat();f=np.geomspace(20,20000,1000)
        np.testing.assert_allclose(response(s,f),0,atol=1e-10)
        s['bands'][0].update(kind='low_cut',frequency=100);s['bypass']=True;s['preamp_db']=-12
        np.testing.assert_array_equal(response(s,f),0)
    def test_bell_center_and_reciprocal(self):
        s=flat();s['bands'][2].update(frequency=900,gain_db=9)
        self.assertAlmostEqual(response(s,[900])[0],9,places=8)
        pos=response(s,np.geomspace(20,20000,1000));s['bands'][2]['gain_db']=-9
        np.testing.assert_allclose(pos+response(s,np.geomspace(20,20000,1000)),0,atol=1e-9)
    def test_composite_peak_not_single_gain(self):
        s=flat()
        for b,f in zip(s['bands'][:2],[800,1000]):b.update(frequency=f,gain_db=6)
        self.assertGreater(peak_gain(s),11)
        dense=response(s,np.geomspace(20,20000,100000),include_levels=False).max()
        self.assertAlmostEqual(peak_gain(s),dense,places=3)
        self.assertLess(headroom(s),-12)
    def test_every_filter_finite_and_disabled_flat(self):
        for kind in ('bell','low_shelf','high_shelf','low_cut','high_cut','notch'):
            s=flat();s['bands'][0].update(kind=kind,gain_db=9)
            self.assertTrue(np.isfinite(response(s,np.geomspace(20,20000,1000))).all())
            s['bands'][0]['enabled']=False
            np.testing.assert_allclose(response(s,[50,1000,16000]),0,atol=1e-9)
    def test_import_validation_does_not_mutate(self):
        s=flat();before=copy.deepcopy(s);self.assertEqual(validate(s),s);self.assertEqual(s,before)
        for key,value in [('frequency',float('nan')),('q',12),('kind','broken')]:
            bad=flat();bad['bands'][0][key]=value
            with self.assertRaises(ValueError):validate(bad)
        s['version']=99
        with self.assertRaises(ValueError):validate(s)

class NativeTests(unittest.TestCase):
    def output(self):
        d=NS()
        for name in ('ChannelSetFX','FXSetParameters','ChannelRemoveFX','ChannelGetAttribute'):setattr(d,'BASS_'+name,Mock(return_value=1))
        d.BASS_ChannelSetFX.side_effect=range(1,11)
        d.BASS_ChannelGetAttribute.side_effect=lambda h,a,p:setattr(p._obj,'value',44100) or 1
        return NS(dll=d,fx=object(),stream=42)
    def test_native_abi_and_channel_bypass_without_removal(self):
        self.assertEqual(C.sizeof(Biquad),28);self.assertEqual(C.sizeof(Volume),8)
        out=self.output();p=Processor(out);captured=[]
        out.dll.BASS_FXSetParameters.side_effect=lambda h,param:captured.append((h,C.string_at(param,C.sizeof(param._obj)))) or 1
        s=flat();s['bands'][0].update(kind='low_shelf',slope=.5);s['bands'][1]['enabled']=False;p.set(s)
        b=Biquad.from_buffer_copy(captured[1][1]);self.assertEqual((b.kind,b.q,b.slope,b.channel),(7,0,.5,-1))
        self.assertEqual(Biquad.from_buffer_copy(captured[2][1]).channel,0)
        out.dll.BASS_ChannelRemoveFX.assert_not_called()
        p.close();self.assertEqual(out.dll.BASS_ChannelRemoveFX.call_count,10)
    def test_failed_write_rolls_back(self):
        out=self.output();p=Processor(out);s=flat();s['bands'][0]['gain_db']=5;p.set(s)
        out.dll.BASS_FXSetParameters.side_effect=[1,0]+[1]*10
        new=flat();new['preamp_db']=-12
        with self.assertRaises(OSError):p.set(new)
        self.assertEqual(p.state,s)
    def test_partial_creation_cleans_handles(self):
        out=self.output();out.dll.BASS_ChannelSetFX.side_effect=[11,12,0]
        with self.assertRaises(OSError):Processor(out)
        self.assertEqual(out.dll.BASS_ChannelRemoveFX.call_count,2)
