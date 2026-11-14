"""Small native Tk tooltip helper with screen-edge and lifecycle safety."""
import tkinter as tk
import ctypes
import os

def screen_bounds_for_point(x, y, fallback_width, fallback_height):
    if os.name == 'nt':
        try:
            user32=ctypes.windll.user32
            class POINT(ctypes.Structure): _fields_=[('x',ctypes.c_long),('y',ctypes.c_long)]
            class RECT(ctypes.Structure): _fields_=[('left',ctypes.c_long),('top',ctypes.c_long),('right',ctypes.c_long),('bottom',ctypes.c_long)]
            class MONITORINFO(ctypes.Structure): _fields_=[('cbSize',ctypes.c_ulong),('rcMonitor',RECT),('rcWork',RECT),('dwFlags',ctypes.c_ulong)]
            monitor=user32.MonitorFromPoint(POINT(int(x),int(y)),2)
            info=MONITORINFO();info.cbSize=ctypes.sizeof(MONITORINFO)
            if monitor and user32.GetMonitorInfoW(monitor,ctypes.byref(info)):
                r=info.rcWork;return (r.left,r.top,r.right,r.bottom)
        except (AttributeError,OSError,TypeError): pass
    return (0,0,int(fallback_width),int(fallback_height))

class Tooltip:
    def __init__(self, widget, text, delay=550):
        self.widget=widget; self.text=text; self.delay=delay; self.window=None; self.after_id=None
        for event,handler in (('<Enter>',self._schedule),('<FocusIn>',self._schedule),('<Leave>',self.hide),('<FocusOut>',self.hide),('<ButtonPress>',self.hide),('<Destroy>',self._destroy)):
            widget.bind(event,handler,add='+')
    def _schedule(self,_event=None):
        self.hide()
        try:self.after_id=self.widget.after(self.delay,self.show)
        except tk.TclError:self.after_id=None
    def show(self):
        self.after_id=None
        try:
            if self.window or not self.widget.winfo_exists():return
            x=self.widget.winfo_rootx()+8; below=self.widget.winfo_rooty()+self.widget.winfo_height()+6
            self.window=tk.Toplevel(self.widget); self.window.wm_overrideredirect(True); self.window.withdraw()
            label=tk.Label(self.window,text=self.text,bg='#18263d',fg='#f4f7ff',padx=8,pady=4,relief='solid',bd=1); label.pack(); self.window.update_idletasks()
            width=self.window.winfo_width(); height=self.window.winfo_height()
            bounds=screen_bounds_for_point(self.widget.winfo_rootx(),self.widget.winfo_rooty(),self.widget.winfo_screenwidth(),self.widget.winfo_screenheight())
            x,y=tooltip_geometry(self.widget.winfo_rootx(),self.widget.winfo_rooty(),self.widget.winfo_width(),self.widget.winfo_height(),width,height,bounds[2]-bounds[0],bounds[3]-bounds[1],screen_left=bounds[0],screen_top=bounds[1])
            self.window.wm_geometry(f'+{x}+{y}'); self.window.deiconify()
        except tk.TclError:self.window=None
    def hide(self,_event=None):
        if self.after_id is not None:
            try:self.widget.after_cancel(self.after_id)
            except tk.TclError:pass
            self.after_id=None
        if self.window is not None:
            try:self.window.destroy()
            except tk.TclError:pass
            self.window=None
    def _destroy(self,_event=None):
        self.hide()


def tooltip_geometry(widget_x, widget_y, widget_width, widget_height, tip_width, tip_height, screen_width, screen_height, screen_left=0, screen_top=0, screen_right=None, screen_bottom=None, gap=6):
    """Return a tooltip position clamped to the visible screen."""
    if screen_right is None: screen_right=screen_left+screen_width
    if screen_bottom is None: screen_bottom=screen_top+screen_height
    x = min(max(screen_left+8, widget_x + 8), max(screen_left+8, screen_right-8-tip_width))
    below = widget_y + widget_height + gap
    y = below if below + tip_height <= screen_bottom - 8 else max(screen_top+8, widget_y - tip_height - gap)
    return x, y
def attach(widget,text):
    widget._xstage_tooltip=Tooltip(widget,text); return widget
