"""Original X-Stage voicings, not copies of third-party player presets."""
import copy
import math
import numpy as np
from .graphic_eq import CENTRES, flat, validate
from .eq_model import peak_gain

# Control points are interpolated in log frequency onto the fixed 31 controls.
ANCHORS=(20,63,125,250,500,1000,2000,4000,8000,16000,20000)
CURVES={
 'Flat':(0,0,0,0,0,0,0,0,0,0,0),
 'นุ่มนวล':(0,.5,1,.5,0,0,-.5,-1,-1.5,-2,-2),
 'เบสกระชับ':(-2,1.5,1,-1,-.5,0,0,0,0,0,0),
 'สดใส':(0,0,0,-.5,0,0,.5,1,1.5,1,.5),
 'เปิดพื้นที่ให้เสียงร้อง':(0,.5,0,-.5,-.5,-1.5,-2,-1,0,0,0),
 'Pop':(0,1,.5,-.5,0,.5,1,.5,.5,0,0),
 'Rock':(0,1.5,1,0,-1,-1,0,1,1.5,1,0),
 'Dance':(-1,2,1.5,0,-1,-.5,0,.5,1,1,0),
}
def builtins():
    result={}
    for name,gains in CURVES.items():
        state=flat()
        for b,g in zip(state['bands'],np.interp(np.log(CENTRES),np.log(ANCHORS),gains)):b['gain_db']=float(g)
        result[name]=state
    return result

def intensity(base,percent):
    value=float(percent)
    if not math.isfinite(value) or not 0<=value<=100:raise ValueError('ความเข้มต้องอยู่ระหว่าง 0–100%')
    state=validate(base);t=value/100
    for b in state['bands']:b['gain_db']*=t
    state['preamp_db']*=t;state['output_db']*=t
    return state

def compensate(state,rates=(44100,48000)):
    """Estimate composite headroom with 1 dB reserve; never raise existing input."""
    state=validate(state)
    if state['bypass']:return state
    boost=max(peak_gain(state,rate) for rate in rates)+state['output_db']
    if boost>1e-6:state['preamp_db']=min(state['preamp_db'],max(-48.,-boost-1.))
    return state

class Compare:
    def __init__(self,state):self.slots=[copy.deepcopy(state),copy.deepcopy(state)];self.index=0
    def store(self,state):self.slots[self.index]=copy.deepcopy(state)
    def other(self):return copy.deepcopy(self.slots[1-self.index])
    def switch(self):self.index=1-self.index

def wheel_steps(delta=0,num=None):
    if num in (4,5):return 1 if num==4 else -1
    return float(delta)/120
