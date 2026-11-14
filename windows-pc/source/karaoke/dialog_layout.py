"""Work-area-aware utility windows; no changes to either singer display."""
import sys
import tkinter as tk
from tkinter import ttk


def viewport_metrics(width, height, needed_w, needed_h, bar_width, bar_height):
    vertical = horizontal = False
    for _ in range(3):
        horizontal = needed_w > width - (bar_width if vertical else 0)
        vertical = needed_h > height - (bar_height if horizontal else 0)
    return (max(1, width-(bar_width if vertical else 0)),
            max(1, height-(bar_height if horizontal else 0)), vertical, horizontal)


def fit_rect(area, desired, minimum=(420, 280)):
    """Return client geometry with space for native borders and taskbar."""
    left, top, right, bottom = area
    available_w = max(1, right - left - 32)
    available_h = max(1, bottom - top - 72)
    width = min(available_w, max(minimum[0], desired[0]))
    height = min(available_h, max(minimum[1], desired[1]))
    return width, height, left + (right-left-width)//2, top + 16


def work_area(window, use_owner=True):
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        class MonitorInfo(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT),
                        ('work', wintypes.RECT), ('flags', wintypes.DWORD)]
        try:
            user = ctypes.WinDLL('user32', use_last_error=True)
            user.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
            user.MonitorFromWindow.restype = wintypes.HANDLE
            user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
            user.GetMonitorInfoW.restype = wintypes.BOOL
            owner = (window.master or window) if use_owner else window
            handle = user.MonitorFromWindow(owner.winfo_id(), 2)
            info = MonitorInfo(); info.size = ctypes.sizeof(info)
            if user.GetMonitorInfoW(handle, ctypes.byref(info)):
                r = info.work
                return r.left, r.top, r.right, r.bottom
        except (OSError, AttributeError, tk.TclError):
            pass
    return (0, 0, window.winfo_screenwidth(), window.winfo_screenheight())


class ScrollBody(ttk.Frame):
    """Two-axis overflow only; retain native size of controls at high DPI."""
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0,
                                background='#10192d', width=1, height=1)
        self.vertical = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.horizontal = ttk.Scrollbar(self, orient='horizontal', command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vertical.set, xscrollcommand=self.horizontal.set)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.rowconfigure(0, weight=1); self.columnconfigure(0, weight=1)
        self.content = ttk.Frame(self.canvas)
        self.item = self.canvas.create_window(0, 0, window=self.content, anchor='nw')
        self.pending = None
        self.content.bind('<Configure>', self.schedule)
        self.canvas.bind('<Configure>', self.schedule)
        # Bind to this toplevel only, never bind_all (which leaks across dialogs).
        parent.winfo_toplevel().bind('<MouseWheel>', self.wheel, add='+')
        parent.winfo_toplevel().bind('<Button-4>', self.wheel, add='+')
        parent.winfo_toplevel().bind('<Button-5>', self.wheel, add='+')
        parent.winfo_toplevel().bind('<FocusIn>', self.reveal, add='+')
        self.bind('<Destroy>', self.cleanup, add='+')

    def cleanup(self, event):
        if event.widget is self and self.pending:
            self.after_cancel(self.pending); self.pending = None

    def schedule(self, event=None):
        if self.pending is None:
            self.pending = self.after_idle(self.layout)

    def layout(self):
        self.pending = None
        needed_w, needed_h = self.content.winfo_reqwidth(), self.content.winfo_reqheight()
        width, height, vertical, horizontal = viewport_metrics(
            self.winfo_width(), self.winfo_height(), needed_w, needed_h,
            self.vertical.winfo_reqwidth(), self.horizontal.winfo_reqheight())
        self.canvas.itemconfigure(self.item, width=max(width, needed_w), height=max(height, needed_h))
        self.canvas.configure(scrollregion=(0, 0, max(width, needed_w), max(height, needed_h)))
        if vertical:
            self.vertical.grid(row=0, column=1, sticky='ns')
        else:
            self.vertical.grid_remove(); self.canvas.yview_moveto(0)
        if horizontal:
            self.horizontal.grid(row=1, column=0, sticky='ew')
        else:
            self.horizontal.grid_remove(); self.canvas.xview_moveto(0)

    def wheel(self, event):
        # Native lists, text editors and comboboxes keep their own scrolling.
        if event.widget.winfo_class() in ('Treeview', 'Text', 'Listbox', 'TCombobox', 'TSpinbox', 'Spinbox'):
            return
        if not str(event.widget).startswith(str(self)):
            return
        delta = getattr(event, 'delta', 0)
        units = (-max(1, abs(delta)//120) if delta > 0 else max(1, abs(delta)//120)) if delta else (-1 if event.num == 4 else 1)
        if event.state & 1:
            self.canvas.xview_scroll(units, 'units')
        else:
            self.canvas.yview_scroll(units, 'units')
        return 'break'

    def reveal(self, event):
        widget = event.widget
        if not str(widget).startswith(str(self.content)+'.'):
            return
        x = widget.winfo_rootx() - self.content.winfo_rootx()
        y = widget.winfo_rooty() - self.content.winfo_rooty()
        for axis, pos, size, view, total in (
                ('x', x, widget.winfo_width(), self.canvas.winfo_width(), self.content.winfo_width()),
                ('y', y, widget.winfo_height(), self.canvas.winfo_height(), self.content.winfo_height())):
            offset = getattr(self.canvas, axis+'view')()[0] * total
            if pos < offset:
                getattr(self.canvas, axis+'view_moveto')(max(0, pos-8)/max(1,total))
            elif pos+size > offset+view:
                getattr(self.canvas, axis+'view_moveto')(max(0,pos+min(size,view)-view+8)/max(1,total))


class ActionBar(ttk.Frame):
    """Equal-width actions wrap into rows instead of clipping on small screens."""
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.columns = 0
        self._signature = None
        self.bind('<Configure>', self.reflow)

    def reflow(self, event=None):
        buttons = self.winfo_children()
        if not buttons:
            return
        widest = max(button.winfo_reqwidth() for button in buttons) + 12
        columns = min(len(buttons), max(1, (self.winfo_width()-32)//widest))
        signature = (columns, tuple(str(b) for b in buttons), widest)
        if signature == self._signature:
            return
        self._signature = signature
        for column in range(self.columns):
            self.columnconfigure(column, weight=0, minsize=0, uniform='')
        self.columns = columns
        for button in buttons:
            button.pack_forget()
        for index, button in enumerate(buttons):
            button.grid(row=index//columns, column=index%columns, sticky='ew', padx=4, pady=4)
        for column in range(columns):
            self.columnconfigure(column, weight=1, uniform='actions')


class DialogWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.configure(bg='#10192d')
        self.footer = ttk.Frame(self)
        self.footer.pack(side='bottom', fill='x')
        self.viewport = ScrollBody(self)
        self.viewport.pack(fill='both', expand=True)
        self.content = self.viewport.content
        self._fit_pending = self.after_idle(self.fit)
        self._wrap_pending = None
        self.bind('<Configure>', self._schedule_wrap, add='+')
        self.bind('<Destroy>', self._cleanup, add='+')

    def _schedule_wrap(self, event=None):
        if event is not None and event.widget is not self:return
        if self._wrap_pending is None:self._wrap_pending=self.after_idle(self._wrap_text)

    def _wrap_text(self):
        self._wrap_pending=None
        def visit(parent):
            for widget in parent.winfo_children():
                if isinstance(widget,(tk.Label,ttk.Label)):
                    try:
                        original=getattr(widget,'_dialog_wrap_limit',None)
                        if original is None:
                            original=self.winfo_pixels(widget.cget('wraplength'))
                            widget._dialog_wrap_limit=original
                        if original:
                            left=max(0,widget.winfo_rootx()-self.winfo_rootx())
                            width=max(100,min(original,self.winfo_width()-left-28))
                            if self.winfo_pixels(widget.cget('wraplength'))!=width:widget.configure(wraplength=width)
                    except tk.TclError:pass
                visit(widget)
        visit(self.content);visit(self.footer)

    def _cleanup(self, event):
        if event.widget is self and self._wrap_pending:
            self.after_cancel(self._wrap_pending);self._wrap_pending=None
        if event.widget is self and self._fit_pending:
            self.after_cancel(self._fit_pending); self._fit_pending = None

    def fit(self):
        self._fit_pending = None
        # Constructors have finished; derive natural size even for grid forms.
        self.update_idletasks()
        area = work_area(self)
        current = self.geometry().split('+')[0].split('-')[0]
        width, height = (int(n) for n in current.split('x'))
        desired = (max(width, self.content.winfo_reqwidth()+24, self.footer.winfo_reqwidth()+24),
                   max(height, self.content.winfo_reqheight()+self.footer.winfo_reqheight()+24))
        w, h, x, y = fit_rect(area, desired)
        self.minsize(min(420, w), min(280, h))
        self.geometry(f'{w}x{h}+{x}+{y}')
        self.resizable(True, True)
        self._schedule_wrap()


def scrollable_tree(parent, **kwargs):
    """Table with visible two-axis navigation and a flexible viewport."""
    frame=ttk.Frame(parent)
    frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
    tree=ttk.Treeview(frame,**kwargs)
    vertical=ttk.Scrollbar(frame,orient='vertical',command=tree.yview)
    horizontal=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview)
    tree.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
    tree.grid(row=0,column=0,sticky='nsew')
    vertical.grid(row=0,column=1,sticky='ns')
    horizontal.grid(row=1,column=0,sticky='ew')
    return frame,tree
