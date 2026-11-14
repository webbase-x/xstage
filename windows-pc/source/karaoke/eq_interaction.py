"""Pure rack layout and gain-ramp calculations (no audio callbacks)."""
import copy
from .graphic_eq import validate

def ramp_frame(start,target,fraction):
    """Interpolate audible gains; keep stored bypass curve intact at the endpoint."""
    start=validate(start);target=validate(target)
    if fraction>=1:return target
    t=max(0.,fraction);value=copy.deepcopy(target);value['bypass']=False
    for key in ('preamp_db','output_db'):
        a=0. if start['bypass'] else start[key]
        b=0. if target['bypass'] else target[key]
        value[key]=a+(b-a)*t
    for out,a,b in zip(value['bands'],start['bands'],target['bands']):
        left=0. if start['bypass'] else a['gain_db']
        right=0. if target['bypass'] else b['gain_db']
        out['gain_db']=left+(right-left)*t
    return value

def flow_positions(sizes,width,gap=6,padding=3):
    """Independent row widths: a wide control in one row cannot widen other rows."""
    width=max(1,width);x=padding;y=2;row_height=0;positions=[]
    for requested_w,h in sizes:
        w=min(requested_w,max(1,width-2*padding))
        if x>padding and x+w+padding>width:
            x=padding;y+=row_height+gap;row_height=0
        positions.append((x,y,w,h));x+=w+gap;row_height=max(row_height,h)
    return positions,y+row_height+2
