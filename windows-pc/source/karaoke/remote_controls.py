"""Readable remote controls with explicit tick and radio indicators."""
from PIL import Image, ImageDraw, ImageTk


def indicator_image(kind, selected, disabled=False, size=26):
    scale=4
    image=Image.new('RGBA',(size*scale,size*scale),(0,0,0,0))
    draw=ImageDraw.Draw(image)
    def box(values):return tuple(int(v*size*scale/26) for v in values)
    edge='#68809b' if disabled else '#b7c9df'
    fill='#26364b' if disabled else '#122238'
    accent='#698580' if disabled else '#54e3cf'
    bounds=box((2,2,24,24))
    if kind=='check':
        draw.rounded_rectangle(bounds,radius=4*scale,fill=accent if selected else fill,outline=edge,width=2*scale)
        if selected:draw.line([box((7,13)),box((11,17)),box((19,9))],fill='#092420',width=3*scale,joint='curve')
    else:
        draw.ellipse(bounds,fill=fill,outline=accent if selected else edge,width=2*scale)
        if selected:draw.ellipse(box((8,8,18,18)),fill=accent)
    return image.resize((size,size),Image.Resampling.LANCZOS)


def configure_controls(window, style):
    try:size=max(26,min(52,round(26*float(window.tk.call('tk','scaling'))/(96/72))))
    except (TypeError,ValueError,AttributeError):size=26
    window._remote_control_images=[]
    for kind,widget in [('check','Checkbutton'),('radio','Radiobutton')]:
        photos=[ImageTk.PhotoImage(indicator_image(kind,selected,disabled,size),master=window)
                for selected,disabled in [(False,False),(True,False),(False,True),(True,True)]]
        window._remote_control_images.extend(photos)
        element=f'Remote{ id(window) }.{widget}.indicator'
        style.element_create(element,'image',photos[0],
                             ('disabled','selected',photos[3]),('disabled',photos[2]),('selected',photos[1]),width=size,border=0,sticky='')
        name='Remote.T'+widget
        style.layout(name,[(widget+'.padding',{'sticky':'nswe','children':[
            (element,{'side':'left','sticky':''}),
            (widget+'.focus',{'side':'left','sticky':'nswe','children':[
                (widget+'.label',{'sticky':'nswe'})]})]})])
        style.configure(name,background='#10192d',foreground='#f3f7ff',font=('Tahoma',12),padding=(8,7),focuscolor='#54e3cf')
        style.map(name,background=[('active','#1b304b')],foreground=[('disabled','#8395aa'),('active','#ffffff')])
    style.configure('Remote.TButton',font=('Tahoma',12),padding=(14,9))
    style.configure('Remote.Accent.TButton',font=('Tahoma',12,'bold'),padding=(14,9))
    style.configure('Remote.TSpinbox',font=('Tahoma',12),padding=7)
    style.configure('Remote.Treeview',font=('Tahoma',12),rowheight=max(34,size+8))
    style.configure('Remote.Treeview.Heading',font=('Tahoma',12,'bold'))
