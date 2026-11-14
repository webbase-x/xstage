"""Keep each settings section together within the available dialog height."""
import tkinter as tk


def partition_sections(heights, available):
    pages=[];page=[];used=0
    for index,height in enumerate(heights):
        height=max(1,height)
        if page and used+height>max(1,available):
            pages.append(page);page=[];used=0
        page.append(index);used+=height
    if page:pages.append(page)
    return pages or [[]]


class SettingsPages:
    def __init__(self, window, container, sections, visible, changed):
        self.window,self.container=window,container
        self.sections,self.visible,self.changed=sections,visible,changed
        self.pages=[[]];self.index=0;self.pending=None;self.busy=False
        window.bind('<Configure>',self.schedule,add='+')
        window.viewport.canvas.bind('<Configure>',lambda event:self.schedule(),add='+')
        window.bind('<Destroy>',self.cleanup,add='+')

    @property
    def more(self):return self.index<len(self.pages)-1

    def schedule(self,event=None):
        if event is not None and event.widget is not self.window:return
        if not self.busy and self.pending is None:
            self.pending=self.window.after(80,self.reflow)

    def cleanup(self,event):
        if event.widget is self.window and self.pending is not None:
            self.window.after_cancel(self.pending);self.pending=None

    def reflow(self):
        self.pending=None
        if self.busy or not self.container.winfo_ismapped():return
        self.busy=True
        try:
            previous=self.pages[self.index][0] if self.pages[self.index] else None
            active=self.visible()
            for widget,opts in self.sections:widget.pack_forget()
            for i in active:self.sections[i][0].pack(**self.sections[i][1])
            self.window.update_idletasks()
            canvas=self.window.viewport.canvas
            # Container's top includes the wizard title and progress strip.
            top=self.container.winfo_rooty()-self.window.content.winfo_rooty()
            budget=max(60,canvas.winfo_height()-top-40)
            heights=[self.sections[i][0].winfo_reqheight()+16 for i in active]
            groups=partition_sections(heights,budget)
            self.pages=[[active[i] for i in page] for page in groups]
            self.index=next((i for i,page in enumerate(self.pages) if previous in page),min(self.index,len(self.pages)-1))
            self.show()
        except tk.TclError:
            pass # Window may have been closed during idle layout.
        finally:self.busy=False

    def show(self):
        for widget,opts in self.sections:widget.pack_forget()
        for i in self.pages[self.index]:self.sections[i][0].pack(**self.sections[i][1])
        self.window.viewport.canvas.yview_moveto(0)
        self.changed()

    def next(self):
        if not self.more:return False
        self.index+=1;self.show();return True

    def back(self):
        if not self.index:return False
        self.index-=1;self.show();return True
