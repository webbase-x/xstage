"""Operator dialogs for output EQ and explicit microphone/music capture."""
import json
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk,filedialog,messagebox
from .dialog_layout import DialogWindow,ActionBar

def add_button(bar,text,command):
    button=ttk.Button(bar,text=text,command=command);button.pack(side='left',padx=4,pady=4);return button

def wrap_labels(frame):
    def resize(event):
        for child in frame.winfo_children():
            if isinstance(child,ttk.Label):child.configure(wraplength=max(240,event.width-12))
    frame.bind('<Configure>',resize,add='+')

def eq_window(app):
    from .eq_ui import open_window
    return open_window(app)

def record_window(app):
    from .recording import WaveRecorder
    from .mixed_recording import MixedRecorder,devices as mixed_devices
    old=getattr(app,'_record_window',None)
    if old is not None and old.winfo_exists():old.lift();return old
    win=DialogWindow(app);app._record_window=win;win.title('บันทึกเสียง');win.geometry('640x540')
    frame=ttk.Frame(win.content,padding=18);frame.pack(fill='both',expand=True);wrap_labels(frame)
    ttk.Label(frame,text='บันทึกการแสดง',font=('Tahoma',18,'bold')).pack(anchor='w',pady=(0,12))
    mode=tk.StringVar(value='input');devices=[];mixed=[];discovery_error=''
    try:devices=WaveRecorder.devices()
    except Exception as error:discovery_error=str(error)
    ttk.Radiobutton(frame,text='อุปกรณ์รับเสียงเดียว',variable=mode,value='input').pack(anchor='w',pady=4)
    ttk.Radiobutton(frame,text='ไมค์ + เสียงลำโพง Windows',variable=mode,value='mix').pack(anchor='w',pady=4)
    ttk.Label(frame,text='อุปกรณ์รับเสียง',font=('Tahoma',12)).pack(anchor='w',pady=(12,4))
    combo=ttk.Combobox(frame,state='readonly',font=('Tahoma',12));combo.pack(fill='x')
    gains=ttk.Frame(frame);gains.pack(fill='x',pady=12)
    mic=tk.IntVar(value=70);music=tk.IntVar(value=70);gain_controls=[]
    for label,var in (('ไมค์',mic),('ดนตรี',music)):
        row=ttk.Frame(gains);row.pack(fill='x',pady=4)
        ttk.Label(row,text=label,width=10).pack(side='left',padx=4)
        control=ttk.Spinbox(row,from_=0,to=200,increment=5,textvariable=var,width=5,font=('Tahoma',12))
        control.pack(side='left');gain_controls.append(control)
        ttk.Label(row,text='%').pack(side='left',padx=4)
    hint=tk.StringVar();hint_label=ttk.Label(frame,textvariable=hint,wraplength=530);hint_label.pack(fill='x')
    status=tk.StringVar(value=discovery_error or 'พร้อมบันทึก');ttk.Label(frame,textvariable=status,wraplength=530,font=('Tahoma',12)).pack(fill='x',pady=16)
    busy={'stop':False,'close':False};controls=[]
    def choose(*unused):
        nonlocal mixed
        if mode.get()=='mix':
            try:mixed=mixed_devices();status.set('พร้อมบันทึก' if mixed else 'ไม่พบไมค์')
            except Exception as error:mixed=[];status.set(str(error))
        options=mixed if mode.get()=='mix' else devices
        combo.configure(values=[name for _,name in options]);combo.set('')
        if options:combo.current(0)
        hint.set('บันทึกเสียงทุกโปรแกรมที่ออกลำโพงเริ่มต้นด้วย • ปิด Listen to this device เพื่อไม่ให้เสียงไมค์ซ้ำ' if mode.get()=='mix' else 'เลือกไมค์ หรือ Stereo Mix ที่ Windows เปิดไว้')
        if mode.get()=='mix':gains.pack(fill='x',pady=12,before=hint_label)
        else:gains.pack_forget()
        for child in gain_controls:child.configure(state='normal' if mode.get()=='mix' else 'disabled')
    mode.trace_add('write',choose);choose()
    def start():
        if app.recorder or busy['stop']:return
        if getattr(app,'_audio_probe_busy',False):status.set('กรุณารอการทดสอบเสียงจบก่อน');return
        options=mixed if mode.get()=='mix' else devices
        index=combo.current()
        if not 0<=index<len(options):status.set('กรุณาเลือกอุปกรณ์รับเสียง');return
        try:
            mg,bg=mic.get()/100,music.get()/100
            if not 0<=mg<=2 or not 0<=bg<=2:raise ValueError('ระดับเสียงต้องเป็น 0–200%')
        except Exception as error:app.show_error(error);return
        file=filedialog.asksaveasfilename(parent=win,defaultextension='.wav',filetypes=[('PCM WAV','*.wav')])
        if not file:return
        current=getattr(app,'current_song',None)
        if current and Path(file).resolve()==Path(current['path']).resolve():app.show_error(ValueError('ห้ามบันทึกทับเพลงที่กำลังเล่น'));return
        try:
            recorder=MixedRecorder(file,options[index][0],mg,bg) if mode.get()=='mix' else WaveRecorder(Path(file),options[index][0])
            app.recorder=recorder;recorder.start();status.set('กำลังบันทึก: '+Path(file).name)
            for widget in controls:widget.configure(state='disabled')
        except Exception as error:
            app.recorder=None;app.show_error(error)
    def stop():
        if not app.recorder or busy['stop']:return
        busy['stop']=True;status.set('กำลังปิดไฟล์เสียง…')
        threading.Thread(target=app.recorder.stop,daemon=True,name='stop-recording').start()
    bar=ActionBar(win.footer,padding=(12,8));bar.pack(fill='x');start_button=add_button(bar,'● เริ่มบันทึก',start);add_button(bar,'■ จบบันทึก',stop)
    controls.extend([start_button,combo]+[w for w in frame.winfo_children() if isinstance(w,ttk.Radiobutton)])
    controls.extend(gain_controls)
    def refresh():
        if not win.winfo_exists():return
        recorder=app.recorder
        if recorder:
            thread=getattr(recorder,'thread',None)
            if not busy['stop'] and recorder.error:stop()
            elif not busy['stop'] and isinstance(recorder,MixedRecorder):
                status.set(f'บันทึก {recorder.frames/recorder.rate:.1f} วินาที  •  ระดับ {recorder.peak*100:.0f}%  •  เสียงเกินระดับ {recorder.clipped} ตัวอย่าง')
            if busy['stop'] and thread and not thread.is_alive():
                workers=getattr(recorder,'workers',[])
                if any(w.is_alive() for w in workers):status.set(str(recorder.error)+' • ยังไม่เริ่มการบันทึกใหม่')
                elif getattr(recorder,'writer',None) is None:
                    status.set(str(recorder.error) if recorder.error else 'บันทึกเสร็จ: '+recorder.path.name)
                    if isinstance(recorder,MixedRecorder):
                        report=dict(seconds=recorder.frames/recorder.rate,peak=recorder.max_peak,clipped_samples=recorder.clipped,error=str(recorder.error or ''),sample_rate=recorder.rate,channels=2)
                        try:recorder.path.with_suffix('.recording.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                        except OSError as error:status.set('ปิดไฟล์เสียงแล้ว แต่บันทึกรายงานไม่ได้: '+str(error))
                    app.recorder=None;busy['stop']=False
                    for widget in controls:widget.configure(state='readonly' if widget is combo else 'normal')
                    for widget in gain_controls:widget.configure(state='normal' if mode.get()=='mix' else 'disabled')
                    if busy['close']:win.destroy();return
        win.after(200,refresh)
    def close():
        if app.recorder:busy['close']=True;stop()
        else:win.destroy()
    win.protocol('WM_DELETE_WINDOW',close);win.after(200,refresh);return win

def diagnostics_window(app):
    import queue
    from .audio_diagnostics import readiness,probe_output
    win=DialogWindow(app);win.title('ตรวจระบบเสียง');win.geometry('650x520')
    frame=ttk.Frame(win.content,padding=18);frame.pack(fill='both',expand=True);wrap_labels(frame)
    ttk.Label(frame,text='ตรวจระบบเสียง',font=('Tahoma',18,'bold')).pack(anchor='w',pady=(0,12))
    info=readiness(app.home);report={'readiness':info};channel=queue.Queue();busy=[False]
    lines=['Windows: '+('พร้อม' if info['windows'] else 'ต้องทดสอบบน Windows'), 'SoundCard: '+('พบ' if info['soundcard'] else 'ยังไม่ติดตั้ง')]
    lines += [name+': '+status for name,status in info['native'].items()]
    text=tk.StringVar(value='\n'.join(lines));ttk.Label(frame,textvariable=text,wraplength=550).pack(fill='x',pady=10)
    status=tk.StringVar(value='การทดสอบจะส่งเสียงสั้น ๆ ที่ลำโพงเริ่มต้น แล้วตรวจสัญญาณที่ Windows ส่งออก')
    ttk.Label(frame,textvariable=status,wraplength=550,font=('Tahoma',12)).pack(fill='x',pady=12)
    ttk.Label(frame,text='ผลนี้ไม่ใช่ค่าหน่วงจากลำโพงถึงหู และไม่ยืนยันคุณภาพไมค์หรือการเล่นต่อเนื่องระยะยาว',wraplength=550).pack(fill='x')
    def run():
        if busy[0] or getattr(app,'_audio_probe_busy',False):return
        if app.engine or app.recorder:status.set('กรุณายกเลิกเพลงและหยุดบันทึกก่อนทดสอบ');return
        if not info['windows']:status.set('ต้องทดสอบบน Windows ที่ต่ออุปกรณ์เสียง');return
        busy[0]=True;app._audio_probe_busy=True;status.set('กำลังทดสอบ • 3 วินาที…');test_button.configure(state='disabled')
        def worker():
            try:channel.put((probe_output(),None))
            except Exception as error:
                import logging,traceback
                logging.exception('Audio output probe failed')
                channel.put((None,dict(message=str(error),type=type(error).__name__,traceback=traceback.format_exc())))
        threading.Thread(target=worker,daemon=True,name='audio-output-probe').start()
        poll()
    def poll():
        try:result,error=channel.get_nowait()
        except queue.Empty:win.after(150,poll);return
        busy[0]=False;app._audio_probe_busy=False;test_button.configure(state='normal')
        report['output_test']=result or {'error':error}
        if error:status.set('ตรวจไม่สำเร็จ: '+error['message']+'\nกดบันทึกรายงานเพื่อดูรายละเอียด')
        else:status.set(('ตรวจพบเสียงทดสอบ' if result['test_tone_detected'] else 'ไม่พบเสียงทดสอบ • ตรวจลำโพง/ระดับเสียง/ปิดเสียง')+f"\nระดับสูงสุด {result['peak']*100:.1f}% • เสียงเกินระดับ {result['clipped_samples']} • ข้อมูลผิดปกติ {result['invalid_samples']}")
    def export():
        file=filedialog.asksaveasfilename(parent=win,defaultextension='.json',initialfile='XStage-audio-check.json',filetypes=[('รายงาน JSON','*.json')])
        if file:
            try:Path(file).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            except OSError as error:app.show_error(error)
    bar=ActionBar(win.footer,padding=(12,8));bar.pack(fill='x');test_button=add_button(bar,'ทดสอบลำโพง',run);add_button(bar,'บันทึกรายงาน',export)
    def close():
        if busy[0]:status.set('กรุณารอให้การทดสอบจบก่อนปิดหน้าต่าง')
        else:win.destroy()
    win.protocol('WM_DELETE_WINDOW',close);return win
