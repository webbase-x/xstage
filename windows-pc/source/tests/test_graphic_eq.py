import copy, unittest
import numpy as np
from unittest.mock import Mock
from types import SimpleNamespace as NS
from karaoke.graphic_eq import flat,validate,band_rms,CENTRES
from karaoke.parametric_eq import Processor,Biquad
from karaoke.graphic_eq_ui import rack_size

class GraphicTests(unittest.TestCase):
    def test_fixed_31_bands_and_range(self):
        s=flat();self.assertEqual(len(s['bands']),31);self.assertEqual(validate(s),s)
        for key,val in [('frequency',999),('gain_db',float('nan')),('gain_db',13)]:
            bad=copy.deepcopy(s);bad['bands'][0][key]=val
            with self.assertRaises(ValueError):validate(bad)
    def test_band_rms_sine_calibration_stereo(self):
        t=np.arange(32768)/48000;x=.25*np.sin(2*np.pi*1000*t)
        bands=band_rms(np.column_stack((x,np.zeros_like(x))))
        self.assertEqual(np.argmax(bands),CENTRES.index(1000));self.assertAlmostEqual(max(bands),.25/np.sqrt(2),places=3)
        np.testing.assert_array_equal(band_rms(np.zeros((32768,2))),np.zeros(31))
    def test_invalid_pcm_rejected(self):
        with self.assertRaises(ValueError):band_rms([[float('nan'),0]])
    def test_real_31_native_filters_bandwidth_and_nyquist(self):
        dll=NS()
        for name in ('ChannelSetFX','FXSetParameters','ChannelRemoveFX','ChannelGetAttribute'):setattr(dll,'BASS_'+name,Mock(return_value=1))
        dll.BASS_ChannelSetFX.side_effect=range(1,34)
        dll.BASS_ChannelGetAttribute.side_effect=lambda h,a,p:setattr(p._obj,'value',32000) or 1
        out=NS(dll=dll,fx=object(),stream=1);p=Processor(out,graphic=True)
        self.assertEqual(len(p.handles),33)
        records=[]
        dll.BASS_FXSetParameters.side_effect=lambda h,arg:records.append(copy.copy(arg._obj)) or 1
        s=flat();s['bands'][17]['gain_db']=6;p.set(s)
        self.assertAlmostEqual(records[18].bandwidth,1/3,places=6);self.assertEqual(records[18].gain,6)
        self.assertEqual(records[-2].channel,0);self.assertEqual(records[-3].channel,0)
        p.close();self.assertEqual(dll.BASS_ChannelRemoveFX.call_count,33)
    def test_rack_fits_work_area(self):
        for area in [(0,0,800,600),(1920,0,3840,1080)]:
            w,h,x,y=rack_size(area);self.assertLessEqual(x+w,area[2]);self.assertLessEqual(y+h,area[3]);self.assertGreaterEqual(x,area[0])
