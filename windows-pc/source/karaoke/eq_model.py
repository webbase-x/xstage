"""Versioned EQ state and RBJ response; no audio or GUI dependencies."""
import copy
import math
import numpy as np

KINDS={'bell':6,'low_shelf':7,'high_shelf':8,'low_cut':1,'high_cut':0,'notch':4}
FREQUENCIES=(40,100,250,630,1600,4000,8000,16000)

def flat():
    return {'version':1,'bypass':False,'preamp_db':0.,'output_db':0.,'bands':[
        dict(enabled=True,kind='bell',frequency=float(f),gain_db=0.,q=.707,slope=1.) for f in FREQUENCIES]}

def validate(state):
    if not isinstance(state,dict) or state.get('version')!=1:raise ValueError('รูปแบบ EQ ไม่รองรับ')
    value=copy.deepcopy(state)
    def number(obj,key,lo,hi):
        x=float(obj[key])
        if not math.isfinite(x) or not lo<=x<=hi:raise ValueError(f'{key}: ต้องอยู่ระหว่าง {lo} ถึง {hi}')
        obj[key]=x
    if type(value.get('bypass')) is not bool:raise ValueError('สถานะ Bypass ไม่ถูกต้อง')
    number(value,'preamp_db',-48,0);number(value,'output_db',-24,6)
    if not isinstance(value.get('bands'),list) or len(value['bands'])!=8:raise ValueError('ต้องมี 8 แบนด์')
    for b in value['bands']:
        if b.get('kind') not in KINDS or type(b.get('enabled')) is not bool:raise ValueError('ชนิดแบนด์ไม่ถูกต้อง')
        number(b,'frequency',20,20000);number(b,'gain_db',-15,15)
        # Official bass_fx 2.4 header documents Q and S in this range.
        number(b,'q',.1,1);number(b,'slope',.1,1)
    return value

def from_settings(settings):
    if 'parametric_eq' in settings:return validate(settings['parametric_eq'])
    return flat()  # legacy EQ is retained until the user explicitly applies this editor

def coefficients(b,rate):
    f=min(b['frequency'],rate*.49);w=2*math.pi*f/rate;c=math.cos(w);s=math.sin(w)
    A=10**(b['gain_db']/40);alpha=s/(2*b['q']);k=b['kind']
    if b.get('bandwidth',0)>0:alpha=s*math.sinh(math.log(2)/2*b['bandwidth']*w/s)
    if k in ('low_shelf','high_shelf'):
        alpha=s/2*math.sqrt((A+1/A)*(1/b['slope']-1)+2);t=2*math.sqrt(A)*alpha
    if k=='bell':num=[1+alpha*A,-2*c,1-alpha*A];den=[1+alpha/A,-2*c,1-alpha/A]
    elif k=='low_cut':num=[(1+c)/2,-(1+c),(1+c)/2];den=[1+alpha,-2*c,1-alpha]
    elif k=='high_cut':num=[(1-c)/2,1-c,(1-c)/2];den=[1+alpha,-2*c,1-alpha]
    elif k=='notch':num=[1,-2*c,1];den=[1+alpha,-2*c,1-alpha]
    elif k=='low_shelf':
        num=[A*((A+1)-(A-1)*c+t),2*A*((A-1)-(A+1)*c),A*((A+1)-(A-1)*c-t)]
        den=[(A+1)+(A-1)*c+t,-2*((A-1)+(A+1)*c),(A+1)+(A-1)*c-t]
    else:
        num=[A*((A+1)+(A-1)*c+t),-2*A*((A-1)+(A+1)*c),A*((A+1)+(A-1)*c-t)]
        den=[(A+1)-(A-1)*c+t,2*((A-1)-(A+1)*c),(A+1)-(A-1)*c-t]
    return np.asarray(num)/den[0],np.asarray(den)/den[0]

def response(state,frequencies,rate=48000,include_levels=True):
    f=np.asarray(frequencies);result=np.zeros_like(f,dtype=float)
    if state['bypass']:return result
    z=np.exp(-2j*np.pi*f/rate)
    for b in state['bands']:
        if not b['enabled'] or (state.get('graphic')==31 and b['frequency']>=rate/2):continue
        n,d=coefficients(b,rate)
        h=(n[0]+n[1]*z+n[2]*z*z)/(d[0]+d[1]*z+d[2]*z*z)
        result+=20*np.log10(np.maximum(abs(h),1e-15))
    if include_levels:result+=state['preamp_db']+state['output_db']
    return result

def peak_gain(state,rate=48000):
    # Dense baseline + adaptive local maxima, not a sample-peak/true-peak limiter.
    upper=min(20000,rate*.49)
    grid=np.unique(np.r_[np.geomspace(20,upper,2048),[min(b['frequency'],upper) for b in state['bands']]])
    y=response(state,grid,rate,False)
    for _ in range(3):
        idx=np.flatnonzero((y[1:-1]>=y[:-2])&(y[1:-1]>=y[2:]))+1
        idx=idx[np.argsort(y[idx])[-16:]]
        if not len(idx):break
        extra=np.concatenate([np.geomspace(grid[i-1],grid[i+1],17) for i in idx])
        grid=np.unique(np.r_[grid,extra]);y=response(state,grid,rate,False)
    return float(max(0,np.max(y)))

def headroom(state):
    return max(-48.,min(0.,-peak_gain(state)-state['output_db']-1.))
