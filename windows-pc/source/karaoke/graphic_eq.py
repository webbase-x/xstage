"""31 fixed nominal 1/3-octave centres, stereo-linked music EQ."""
import copy
import math
CENTRES=(20,25,31.5,40,50,63,80,100,125,160,200,250,315,400,500,630,800,1000,1250,1600,2000,2500,3150,4000,5000,6300,8000,10000,12500,16000,20000)
def flat():
    return {'graphic':31,'bypass':False,'preamp_db':0.,'output_db':0.,'bands':[{'kind':'bell','frequency':f,'gain_db':0.,'bandwidth':1/3,'q':.707,'slope':1.,'enabled':True} for f in CENTRES]}
def validate(value):
    if not isinstance(value,dict) or value.get('graphic')!=31 or type(value.get('bypass')) is not bool:raise ValueError('รูปแบบ Graphic EQ ไม่ถูกต้อง')
    bands=value.get('bands',[])
    if len(bands)!=31:raise ValueError('ต้องมี 31 แบนด์')
    result=flat();result['bypass']=value['bypass']
    for key,lo,hi in [('preamp_db',-48,0),('output_db',-24,6)]:
        v=float(value[key])
        if not math.isfinite(v) or not lo<=v<=hi:raise ValueError('ระดับเสียงเกินช่วง')
        result[key]=v
    for i,b in enumerate(bands):
        v=float(b['gain_db'])
        if not math.isfinite(v) or not -12<=v<=12:raise ValueError('Gain ต้องอยู่ระหว่าง -12 ถึง +12 dB')
        if float(b['frequency'])!=CENTRES[i]:raise ValueError('ความถี่ Graphic EQ ต้องเป็นค่าคงที่')
        result['bands'][i]['gain_db']=v
    return result

def band_rms(frames,rate=48000):
    """Window-normalized band energy (digital RMS), not SPL or feedback detection."""
    import numpy as np
    x=np.asarray(frames,dtype=float)
    if x.ndim!=2 or len(x)<4 or rate<=0 or x.shape[1]!=2 or not np.isfinite(x).all():raise ValueError('ต้องเป็น PCM stereo')
    n=len(x);w=np.hanning(n);spec=np.abs(np.fft.rfft(x*w[:,None],axis=0))**2
    hz=np.fft.rfftfreq(n,1/rate);scale=2/(n*np.sum(w*w))
    result=[]
    for f in CENTRES:
        bins=(hz>=f/2**(1/6))&(hz<f*2**(1/6))
        result.append(float(np.sqrt(np.max(np.sum(spec[bins],axis=0))*scale)))
    return result
