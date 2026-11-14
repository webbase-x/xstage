"""Independent short effect players. User files are never copied or modified."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog
from .dialog_layout import DialogWindow,ActionBar

class FxRack:
    def __init__(self,factory=None):self.players=[];self.factory=factory
    def play(self,path,volume=.6):
        path=Path(path)
        if not path.is_file() or path.suffix.lower() not in ('.wav','.mp3'):raise ValueError('เลือกเอฟเฟกต์ WAV หรือ MP3 ที่มีอยู่จริง')
        self.pump()
        if len(self.players)>=4:self.players.pop(0).close()
        if self.factory:player=self.factory(path)
        else:
            from .playback import WavePlayer,MediaPlayer
            player=WavePlayer() if path.suffix.lower()=='.wav' else MediaPlayer()
        try:
            player.load(path)
            if player.duration>60:raise ValueError('เอฟเฟกต์ต้องยาวไม่เกิน 60 วินาที')
            player.set_volume(max(0,min(1,float(volume))));player.play();self.players.append(player)
        except Exception:player.close();raise
    def pump(self):
        for player in list(self.players):
            try:
                player.pump()
                if player.ended:player.close();self.players.remove(player)
            except Exception:
                player.close();self.players.remove(player)
                raise
    def close(self):
        for player in self.players:player.close()
        self.players.clear()

def fx_window(app):
    old=app.__dict__.get('_fx_window')
    if old is not None and old.winfo_exists():old.lift();return old
    from .branding import asset
    rack=app.__dict__.setdefault('_fx_rack',FxRack());win=DialogWindow(app);app._fx_window=win;win.title('เสียงเอฟเฟกต์หน้าเวที');win.geometry('650x540')
    defaults=[dict(name=name,path=str(asset(file))) for name,file in [('ตบมือสังเคราะห์','fx-clap.wav'),('แตรสั้น','fx-horn.wav'),('เสียงระฆัง','fx-bell.wav'),('กลองส่ง','fx-fill.wav')]]
    slots=app.settings.get('fx_slots',defaults)
    if not isinstance(slots,list) or len(slots)!=4:slots=defaults
    slots=[dict(row) for row in slots];volume=tk.IntVar(value=60)
    ttk.Label(win.content,text='ยิงเอฟเฟกต์ • เปิดพร้อมกันได้ 4 เสียง',font=('Tahoma',15,'bold')).pack(anchor='w',padx=14,pady=12)
    def fire(index):
        try:rack.play(slots[index]['path'],volume.get()/100)
        except (OSError,ValueError,tk.TclError) as error:app.show_error(error)
    for i in range(4):
        row=ttk.Frame(win.content,padding=8);row.pack(fill='x')
        button=ttk.Button(row,text=f'{i+1}  {slots[i]["name"]}',command=lambda i=i:fire(i));button.pack(side='left',fill='x',expand=True)
        def choose(i=i,button=button):
            path=filedialog.askopenfilename(parent=win,filetypes=[('เสียงเอฟเฟกต์','*.wav *.mp3')])
            if path:
                slots[i]=dict(name=Path(path).stem,path=path);app.settings['fx_slots']=slots;app.save_settings();button.configure(text=f'{i+1}  {slots[i]["name"]}')
        ttk.Button(row,text='เลือกไฟล์…',command=choose).pack(side='right',padx=8)
        win.bind('<Control-Key-'+str(i+1)+'>',lambda event,i=i:(fire(i),'break')[1])
    ttk.Label(win.content,text='ความดังเอฟเฟกต์').pack(anchor='w',padx=14,pady=8)
    ttk.Scale(win.content,from_=0,to=100,variable=volume).pack(fill='x',padx=14)
    ttk.Label(win.content,text='Ctrl+1–4 ใช้เมื่อหน้าต่างนี้อยู่ด้านหน้า • เลือกเสียงของคุณเองได้',wraplength=540).pack(padx=14,pady=12)
    ttk.Button(win.footer,text='หยุดเอฟเฟกต์ทั้งหมด',command=rack.close).pack(pady=12)
    def poll():
        if not win.winfo_exists():return
        try:rack.pump()
        except OSError as error:app.show_error(error)
        win.after(100,poll)
    def close():rack.close();win.destroy()
    win.protocol('WM_DELETE_WINDOW',close);win.after(100,poll);return win
