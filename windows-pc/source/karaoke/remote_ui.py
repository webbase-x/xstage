"""Desktop remote setup, shared stage invite, and UI-thread snapshot helpers."""
import bisect
import time
import tkinter as tk
from tkinter import ttk
from .dialog_layout import DialogWindow


def enrich_snapshot(app, value):
    value.update(position=app.engine.position if app.engine else 0,
                 playback_rate=getattr(app.engine,'speed',1.) if app.engine else 1.,
                 _sampled=time.monotonic(), lyric_lines=[], offset_ms=0, requests=[],
                 countdown=app.__dict__.get('_queue_countdown_seconds',0))
    lyrics = getattr(app, 'lyrics', None)
    if lyrics and getattr(app, 'current_song', None):
        offset = lyrics.offset_ms + app.offset_var.get()
        value['offset_ms'] = offset
        index = max(0,bisect.bisect_right(lyrics.starts,value['position']+offset/1000)-1)
        value['lyric_lines'] = [dict(start=l.start,text=l.text,words=l.words) for l in lyrics.lines[index:index+4]]
    for item in app.song_queue.items:
        song = app.library.get(item.song_id)
        if song:
            value['queue'].append(dict(title=song['title'], singer=item.singer, key=item.key, speed=item.speed))
    book = getattr(app,'remote_requests',None)
    if book:
        book.sync(app)
        value['requests'] = [dict(r) for r in book.records.values()]


def validate_remote_command(app, command):
    if '_generation' not in command: return
    server = getattr(app,'remote',None)
    if not server or command['_generation'] != server.generation:
        raise ValueError('รหัสเชื่อมต่อถูกเปลี่ยน กรุณาเชื่อมต่อใหม่')
    if command.get('_session') not in server.sessions:
        raise ValueError('การเชื่อมต่อหมดสิทธิ์แล้ว')
    if command.get('_role') == 'operator' and not server.policy['operator']:
        raise ValueError('ผู้ดูแลปิดสิทธิ์ควบคุมแล้ว')


def sync_wifi_invite(app):
    monitor=app.__dict__.get('_wifi_monitor')
    if not monitor:return
    state=monitor.snapshot()
    server=getattr(app,'remote',None)
    if server and state.ready and app.settings.get('remote_capacity_auto',True) and time.monotonic()-app.__dict__.get('_capacity_checked',0)>5:
        from .remote_capacity import recommended_clients
        server.configure(max_clients=recommended_clients(state,server.policy.get('audio',False),server.capacity_stats()[1]))
        app.__dict__['_capacity_checked']=time.monotonic()
    if not server or not state.ready:
        app.remote_invite=None
        return
    old=getattr(app,'remote_invite',None)
    url=f'http://{state.address}:{server.port}/'
    if not old or (old['url'],old['code'],old['wifi'])!=(url,server.request_key,state.ssid):
        app.remote_invite=make_invite(state.address,server.port,server.request_key,state.ssid)


def stage_invite(app):
    sync_wifi_invite(app)
    server = getattr(app,'remote',None)
    if not server or not app.settings.get('remote_show_stage',False): return None
    if app.settings.get('remote_idle_only',True) and app.current_song: return None
    invite = getattr(app,'remote_invite',None)
    if not invite or invite['code'] != server.request_key: return None
    return invite


def make_invite(address, port, code, wifi=''):
    import qrcode
    url = f'http://{address}:{port}/'
    qr = qrcode.make(url+'#code='+code).convert('RGB')
    return dict(code=code,url=url,wifi=wifi,qr=qr)


_invite_cache = {}
def draw_invite(image, invite):
    if not invite: return
    from PIL import Image, ImageDraw
    from .typography import ThaiFont, draw_text
    width,height = image.size
    size = min(280, int(height*.27), int(width*.3))
    if size<100: return
    cache_key = (invite['url'],invite['code'],invite['wifi'],size)
    cached = _invite_cache.get(cache_key)
    if cached is None:
        _invite_cache.clear()
        cached = (invite['qr'].resize((size,size),Image.Resampling.NEAREST), ThaiFont(max(24,size//6),'Consolas'), ThaiFont(max(13,size//17),'Leelawadee UI'))
        _invite_cache[cache_key] = cached
    qr, large, small = cached
    x,y = width-size-28, 126
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((x-12,y-10,x+size+12,y+size+105),radius=14,fill='#081326',outline='#5edbd5',width=2)
    image.paste(qr,(x,y))
    code = invite['code'][:3]+' '+invite['code'][3:]
    draw_text(image,(x+8,y+size+4),code,large,'#ffe269')
    draw_text(image,(x+8,y+size+size//6+12),'สแกนเพื่อขอเพลง / ดูเนื้อร้อง',small,'#ffffff')
    if invite['wifi']: draw_text(image,(x+8,y+size+size//6+35),'Wi-Fi: '+invite['wifi'],small,'#b5d7e6')


def initial_policy(settings):
    try: limit=max(1,min(20,int(settings.get('remote_limit',3))))
    except (ValueError,TypeError,OverflowError): limit=3
    return dict(accepting=bool(settings.get('remote_accepting',True)), operator=False,
                approval=bool(settings.get('remote_approval',False)),
                allow_edit=bool(settings.get('remote_allow_edit',True)), audio=False, limit=limit)


def remote_window(app):
    from .remote import RemoteServer
    from .remote_requests import RequestBook
    from PIL import Image, ImageTk
    existing = app.__dict__.get('_remote_window')
    if existing and existing.winfo_exists(): existing.lift(); return
    window = DialogWindow(app)
    app._remote_window = window
    window.title('รีโมทมือถือ • ค้นหา / คิว / จอร้องสด')
    style = ttk.Style(window)
    style.configure('Remote.TFrame',background='#10192d')
    style.configure('Remote.TLabel',background='#10192d',foreground='#edf4ff',font=('Tahoma',12))
    from .remote_controls import configure_controls
    configure_controls(window,style)
    body = window.content
    ttk.Label(body,style='Remote.TLabel',text='X-STAGE  •  MOBILE REMOTE',font=('Tahoma',18,'bold')).pack(anchor='w',padx=16,pady=(16,8))
    from .remote_setup import RemoteSetup, validate_setup
    flow = RemoteSetup(bool(app.remote))
    step_label = ttk.Label(body,style='Remote.TLabel',font=('Tahoma',14,'bold'))
    step_label.pack(anchor='w',padx=16,pady=(0,8))
    progress = ttk.Progressbar(body,maximum=3)
    progress.pack(fill='x',padx=16,pady=(0,8))
    pages = [ttk.Frame(body,style='Remote.TFrame') for _ in range(3)]
    network = ttk.Frame(pages[0],style='Remote.TFrame',padding=16);network.pack(fill='x')
    from .wifi_network import WifiMonitor
    if not app.__dict__.get('_wifi_monitor'):app._wifi_monitor=WifiMonitor()
    monitor=app._wifi_monitor
    from .wifi_permission import PermissionRepair, wifi_heading
    if not app.__dict__.get('_wifi_repair'):app._wifi_repair=PermissionRepair()
    repair=app._wifi_repair
    repair_note=tk.StringVar()
    address=tk.StringVar();port=tk.IntVar(value=app.remote.port if app.remote else 8080)
    wifi=tk.StringVar(value='กำลังตรวจสอบ…')
    ttk.Label(network,style='Remote.TLabel',text='เครือข่าย Wi-Fi').grid(row=0,column=0,sticky='w')
    ttk.Label(network,style='Remote.TLabel',textvariable=wifi,font=('Tahoma',16,'bold'),wraplength=460).grid(row=1,column=0,sticky='ew',padx=(0,8))
    def wifi_settings():
        import os
        if os.name=='nt':os.startfile('ms-settings:network-wifi')
    connect_wifi=ttk.Button(network,style='Remote.TButton',text='เชื่อมต่อ Wi-Fi',command=wifi_settings)
    refresh_wifi=ttk.Button(network,style='Remote.TButton',text='ตรวจสอบอีกครั้ง',command=monitor.refresh)
    permission_bar=ttk.Frame(network,style='Remote.TFrame')
    permission_bar.grid(row=5,column=0,columnspan=2,sticky='ew',pady=(4,8))
    def open_permission(restore=False):
        try:
            if repair.launch(restore):
                repair_note.set('ยืนยันสิทธิ์ในหน้าต่าง Windows')
            else:repair_note.set('กำลังเปิดสิทธิ์…')
        except (OSError,ValueError) as error:app.show_error(error)
    permission_button=ttk.Button(permission_bar,style='Remote.TButton',text='เปิดสิทธิ์อ่าน Wi-Fi',command=open_permission)
    permission_button.pack(side='left',padx=(0,8))
    repair_label=ttk.Label(network,style='Remote.TLabel',textvariable=repair_note,wraplength=460)
    network.columnconfigure(0,weight=1)
    card=ttk.Frame(pages[2],style='Remote.TFrame',padding=16);card.pack(fill='x')
    qr_label=ttk.Label(card);qr_label.pack(side='left',padx=(0,16))
    codes=ttk.Frame(card,style='Remote.TFrame');codes.pack(side='left',fill='both',expand=True)
    ttk.Label(codes,style='Remote.TLabel',textvariable=wifi,font=('Tahoma',13,'bold'),wraplength=320).pack(anchor='w',pady=(0,8))
    ttk.Label(codes,style='Remote.TLabel',text='รหัสผู้ร้อง').pack(anchor='w')
    guest=ttk.Label(codes,style='Remote.TLabel',text='—',font=('Consolas',40,'bold'),foreground='#ffe269');guest.pack(anchor='w')
    url_label=ttk.Label(codes,style='Remote.TLabel',text='',wraplength=420);url_label.pack(anchor='w')
    operator_code=ttk.Label(codes,style='Remote.TLabel',text='',font=('Tahoma',13),foreground='#b5cadf');operator_code.pack(anchor='w',pady=(12,0))
    status=ttk.Label(window.footer,style='Remote.TLabel',text='ยังไม่เปิดรีโมท',wraplength=540);status.pack(anchor='w',padx=16,pady=8)
    options=ttk.Frame(pages[1],style='Remote.TFrame',padding=16);options.pack(fill='x')
    advanced=options
    advanced_open=tk.BooleanVar(value=False)
    port_row=ttk.Frame(advanced,style='Remote.TFrame');port_row.pack(fill='x',pady=(0,12))
    ttk.Label(port_row,style='Remote.TLabel',text='พอร์ตรีโมท').pack(side='left')
    port_entry=ttk.Spinbox(port_row,style='Remote.TSpinbox',font=('Tahoma',12),from_=1024,to=65535,textvariable=port,width=8)
    port_entry.pack(side='left',padx=8)
    policy=app.remote.policy if app.remote else initial_policy(app.settings)
    variables={k:tk.BooleanVar(value=policy[k]) for k in ('accepting','operator','approval','allow_edit','audio')}
    qr_mode=tk.StringVar(value='off' if not app.settings.get('remote_show_stage',False) else ('idle' if app.settings.get('remote_idle_only',True) else 'always'))
    limit=tk.IntVar(value=policy['limit'])
    from .remote_capacity import recommended_clients
    capacity_auto=tk.BooleanVar(value=app.settings.get('remote_capacity_auto',True))
    capacity=tk.IntVar(value=app.settings.get('remote_max_clients',10))
    def capacity_value():
        latency=app.remote.capacity_stats()[1] if app.remote else 0
        return recommended_clients(monitor.snapshot(),variables['audio'].get(),latency) if capacity_auto.get() else capacity.get()

    def update_invite():
        sync_wifi_invite(app)
        if app.remote and app.remote_invite:
            photo=ImageTk.PhotoImage(app.remote_invite['qr'].resize((180,180),Image.Resampling.NEAREST))
            qr_label.configure(image=photo);qr_label.image=photo
            code=app.remote.request_key;guest.configure(text=code[:3]+' '+code[3:])
            operator_code.configure(text='ผู้ดูแล (ไม่ขึ้นจอร้อง): '+app.remote.operator_key[:3]+' '+app.remote.operator_key[3:] if variables['operator'].get() else '')
            url_label.configure(text=app.remote_invite['url'])
        else:
            app.remote_invite=None;qr_label.configure(image='');qr_label.image=None;guest.configure(text='—');url_label.configure(text='');operator_code.configure(text='')
        app.paint_lyrics()
    def apply_options():
        try:
            maximum=capacity_value()
            if not 1<=maximum<=100:raise ValueError('จำนวนผู้เข้าใช้ต้องอยู่ระหว่าง 1–100')
            count=limit.get()
            if not 1<=count<=20: raise ValueError('จำนวนเพลงรอต้องอยู่ระหว่าง 1–20')
            if app.remote: app.remote.configure(**{k:v.get() for k,v in variables.items()},limit=count,max_clients=maximum)
            app.settings.update(remote_show_stage=qr_mode.get()!='off',remote_idle_only=qr_mode.get()!='always')
            app.settings.update({('remote_'+k):variables[k].get() for k in ('accepting','approval','allow_edit')})
            app.settings['remote_limit']=count
            app.settings.update(remote_capacity_auto=capacity_auto.get(),remote_max_clients=maximum)
            app.save_settings();update_invite();update_visibility();settings_pages.schedule()
            return True
        except (ValueError,tk.TclError) as e:
            app.show_error(e)
            return False
    accepting_control=ttk.Checkbutton(options,style='Remote.TCheckbutton',text='รับคำขอเพลง',variable=variables['accepting'],command=apply_options)
    accepting_control.pack(anchor='w',pady=6)
    approval_row=ttk.Frame(options,style='Remote.TFrame');approval_row.pack(fill='x',pady=6)
    ttk.Label(approval_row,style='Remote.TLabel',text='อนุมัติเพลง').pack(anchor='w',pady=(0,4))
    for value,label in [(False,'อัตโนมัติ'),(True,'อนุมัติเอง')]:
        ttk.Radiobutton(approval_row,text=label,variable=variables['approval'],value=value,command=apply_options,style='Remote.TRadiobutton').pack(anchor='w',pady=2)
    limits=ttk.Frame(options,style='Remote.TFrame');limits.pack(fill='x',pady=6)
    ttk.Label(limits,style='Remote.TLabel',text='เพลงรอต่อคน',width=15).pack(side='left')
    limit_input=ttk.Spinbox(limits,style='Remote.TSpinbox',font=('Tahoma',12),from_=1,to=20,textvariable=limit,width=5,command=apply_options)
    limit_input.pack(side='left',padx=6)
    limit_input.bind('<FocusOut>',lambda e:apply_options())
    qr_row=ttk.Frame(options,style='Remote.TFrame');qr_row.pack(fill='x',pady=6)
    ttk.Label(qr_row,style='Remote.TLabel',text='QR บนจอร้อง').pack(anchor='w',pady=(0,4))
    qr_choices=ttk.Frame(qr_row,style='Remote.TFrame');qr_choices.pack(anchor='w')
    for value,label in [('off','ปิดการแสดง'),('always','แสดงตลอด'),('idle','แสดงเฉพาะช่วงรอเพลง')]:
        ttk.Radiobutton(qr_choices,text=label,variable=qr_mode,value=value,command=apply_options,style='Remote.TRadiobutton').pack(anchor='w',pady=2)
    audio_control=ttk.Checkbutton(options,style='Remote.TCheckbutton',text='เสียงมือถือ (รวมเสียงโปรแกรมอื่น)',variable=variables['audio'],command=apply_options)
    audio_control.pack(anchor='w',pady=8)
    def toggle_advanced():
        advanced_open.set(not advanced_open.get())
        advanced_button.configure(text='ตั้งค่าเพิ่มเติม ▴' if advanced_open.get() else 'ตั้งค่าเพิ่มเติม ▾')
        update_visibility();settings_pages.schedule()
    advanced_button=ttk.Button(options,style='Remote.TButton',text='ตั้งค่าเพิ่มเติม ▾',command=toggle_advanced)
    advanced_button.pack(anchor='w',pady=(12,0))
    capacity_control=ttk.Checkbutton(advanced,style='Remote.TCheckbutton',text='จำนวนผู้ใช้: อัตโนมัติ',variable=capacity_auto,command=apply_options)
    capacity_row=ttk.Frame(advanced,style='Remote.TFrame')
    ttk.Label(capacity_row,style='Remote.TLabel',text='จำนวนผู้ใช้สูงสุด').pack(side='left')
    capacity_input=ttk.Spinbox(capacity_row,style='Remote.TSpinbox',font=('Tahoma',12),from_=1,to=100,textvariable=capacity,width=5,command=apply_options)
    capacity_input.pack(side='left',padx=8)
    capacity_input.bind('<FocusOut>',lambda e:apply_options())
    edit_control=ttk.Checkbutton(advanced,style='Remote.TCheckbutton',text='ผู้ร้องแก้คีย์ / ยกเลิกคำขอได้',variable=variables['allow_edit'],command=apply_options)
    operator_control=ttk.Checkbutton(advanced,style='Remote.TCheckbutton',text='รีโมทผู้ดูแล',variable=variables['operator'],command=apply_options)
    review_panel=ttk.Frame(pages[2],style='Remote.TFrame')
    tree=ttk.Treeview(review_panel,style='Remote.Treeview',columns=('song','singer','key'),show='headings',height=4)
    for name,label in [('song','รออนุมัติ'),('singer','ผู้ร้อง'),('key','คีย์')]:
        tree.heading(name,text=label);tree.column(name,width=240 if name=='song' else 90,stretch=True)
    tree.pack(fill='both',expand=True,padx=16,pady=8)
    def moderate(action):
        selected=tree.selection()
        if not selected or not app.remote:return
        try: app.apply_remote(dict(action=action,request_id=selected[0],_owner='local',_role='operator'))
        except Exception as e:app.show_error(e)
    review=ttk.Frame(review_panel,style='Remote.TFrame',padding=(16,0));review.pack(fill='x')
    ttk.Button(review,style='Remote.TButton',text='อนุมัติคำขอที่เลือก',command=lambda:moderate('approve')).pack(side='left')
    ttk.Button(review,style='Remote.TButton',text='ปฏิเสธคำขอที่เลือก',command=lambda:moderate('reject')).pack(side='left',padx=8)
    def show_step():
        for page in pages: page.pack_forget()
        pages[flow.step].pack(fill='both',expand=True)
        titles = ('1 / 3  •  เชื่อมต่อ',
                  '2 / 3  •  ตั้งค่า',
                  '3 / 3  •  รีโมทพร้อมใช้งาน')
        step_label.configure(text=titles[flow.step])
        progress.configure(value=flow.step+1)
        back_button.configure(state='disabled' if flow.step==0 else 'normal')
        next_button.configure(text=('ถัดไป →','บันทึก' if app.remote else 'บันทึกและเปิดรีโมท','เสร็จสิ้น')[flow.step])
        port_entry.configure(state='disabled' if app.remote else 'normal')
        window.viewport.canvas.yview_moveto(0)
        window.viewport.canvas.xview_moveto(0)
        update_buttons()
        window.after_idle(window.fit)
        settings_pages.schedule()
    def update_visibility():
        if variables['operator'].get() and app.remote:operator_code.pack(anchor='w',pady=(12,0))
        else:operator_code.pack_forget()
    def update_buttons():
        blocked = repair.running or (flow.step < 2 and not monitor.snapshot().ready)
        next_button.configure(state='disabled' if blocked else 'normal')
        if flow.step==1:
            step_label.configure(text=f'2 / 3  •  ตั้งค่า  {settings_pages.index+1} / {len(settings_pages.pages)}')
            next_button.configure(text='ถัดไป →' if settings_pages.more else ('บันทึก' if app.remote else 'บันทึกและเปิดรีโมท'))
        stop_button.configure(state='normal' if app.remote else 'disabled')
        rotate_button.configure(state='normal' if app.remote else 'disabled')
        for button in (back_button,next_button,stop_button,close_button):button.grid_forget()
        actions=([back_button] if flow.step else [])+[next_button]+([stop_button] if app.remote else [])+([close_button] if flow.step!=2 else [])
        try:
            widest=max(button.winfo_reqwidth() for button in actions)+8
            columns=max(1,min(len(actions),(bar.winfo_width()-16)//widest))
        except TypeError:columns=len(actions)
        for i in range(4):bar.columnconfigure(i,weight=1 if i<columns else 0)
        for i,button in enumerate(actions):button.grid(row=i//columns,column=i%columns,padx=4,pady=4,sticky='ew')
        update_visibility()
    def start():
        state=monitor.snapshot()
        try:
            selected_port,count=validate_setup(state.ready,repair.running,port.get(),limit.get())
        except (ValueError,tk.TclError) as e:
            if not state.ready:flow.stopped();show_step()
            app.show_error(e)
            return
        if not apply_options():return
        if not app.remote:
            server=None
            try:
                server=RemoteServer(app.library,app.dispatch_remote,app.get_remote_snapshot,port=selected_port)
                server.configure(**{k:v.get() for k,v in variables.items()},limit=count,max_clients=capacity_value())
                app.remote=server
                app.remote_requests=RequestBook()
                app.update_remote_snapshot();server.start()
            except (OSError,ValueError,RuntimeError,tk.TclError) as e:
                if server is not None:server.server.server_close()
                app.remote=None
                app.show_error(e)
                return
        flow.started();update_invite();show_step()
    def advance():
        if flow.step==0:
            if flow.next(monitor.snapshot().ready,repair.running):show_step()
        elif flow.step==1:
            if not settings_pages.next():start()
        else:window.destroy()
    def back():
        if flow.step==1 and settings_pages.back():return
        flow.back();show_step()
    def stop():
        if app.remote:app.remote.close();app.remote=None
        repair_note.set('')
        flow.stopped();update_invite();show_step()
    def rotate():
        if app.remote:app.remote.rotate_codes();update_invite()
    tools=ttk.Frame(pages[2],style='Remote.TFrame',padding=16);tools.pack(fill='x')
    rotate_button=ttk.Button(tools,style='Remote.TButton',text='เปลี่ยนรหัสเชื่อมต่อ',command=rotate)
    rotate_button.pack(side='left')
    bar=ttk.Frame(window.footer,style='Remote.TFrame',padding=8);bar.pack(fill='x')
    back_button=ttk.Button(bar,style='Remote.TButton',text='← ย้อนกลับ',command=back);back_button.pack(side='left')
    next_button=ttk.Button(bar,style='Remote.Accent.TButton',text='ถัดไป →',command=advance);next_button.pack(side='left')
    stop_button=ttk.Button(bar,style='Remote.TButton',text='หยุดรีโมท',command=stop);stop_button.pack(side='left')
    close_button=ttk.Button(bar,style='Remote.TButton',text='ปิดหน้าต่าง',command=window.destroy)
    for button in (back_button,next_button,stop_button):button.pack_forget()
    for i in range(4):bar.columnconfigure(i,weight=1)
    bar.bind('<Configure>',lambda event:update_buttons(),add='+')
    from .remote_paging import SettingsPages
    section_widgets=[accepting_control,approval_row,limits,qr_row,audio_control,advanced_button,
                     port_row,capacity_control,capacity_row,edit_control,operator_control]
    sections=[(widget,dict(fill='x',pady=8)) for widget in section_widgets]
    def visible_sections():
        active=list(range(6))
        if advanced_open.get():
            if not app.remote:active.append(6)
            active.append(7)
            if not capacity_auto.get():active.append(8)
            active.extend([9,10])
        return active
    settings_pages=SettingsPages(window,options,sections,visible_sections,update_buttons)
    for widget in section_widgets[6:]:widget.pack_forget()
    pending=[None];last=[None];last_network=[None]
    def refresh():
        server=app.remote
        result=repair.completed()
        if result is not None:
            monitor.refresh()
            repair_note.set('กำลังตรวจสอบ…' if result==0 else 'เปิดสิทธิ์ไม่สำเร็จ กรุณาลองอีกครั้ง')
        state=monitor.snapshot()
        from .remote_setup import network_actions
        actions=network_actions(state.status,state.ready,repair.running)
        permission_bar.grid_remove();connect_wifi.grid_remove();refresh_wifi.grid_remove();repair_label.grid_remove()
        if actions['permission']:permission_bar.grid(row=5,column=0,columnspan=2,sticky='w',pady=8)
        if actions['connect']:connect_wifi.grid(row=4,column=0,sticky='w',pady=8)
        if actions['refresh']:refresh_wifi.grid(row=4,column=1,pady=8)
        if repair.running:repair_note.set('กำลังจัดการสิทธิ์…')
        if state.ready:repair_note.set('')
        if repair_note.get():repair_label.grid(row=7,column=0,columnspan=2,sticky='w',pady=4)
        occupancy,latency=server.capacity_stats() if server else (0,0)
        recommended=recommended_clients(state,variables['audio'].get(),latency)
        if server and capacity_auto.get():server.configure(max_clients=recommended)
        previous_step=flow.step
        flow.network_changed(state.ready,bool(server))
        if previous_step!=flow.step:show_step()
        update_buttons()
        if state!=last_network[0]:
            wifi.set(wifi_heading(state))
            address.set(state.address)
            update_invite();last_network[0]=state
        if flow.step==2:
            step_label.configure(text='3 / 3  •  รีโมทพร้อมใช้งาน' if state.ready else '3 / 3  •  รอเชื่อมต่อ Wi-Fi อีกครั้ง')
        status.configure(text=(f'เชื่อมต่อ {server.connected_count()} / {server.policy.get("max_clients",10)} เครื่อง' if server else ('พร้อมเชื่อมต่อ' if state.ready else 'กำลังตรวจสอบ' if state.status=='checking' else 'ยังไม่พร้อมเชื่อมต่อ')))
        book=getattr(app,'remote_requests',None)
        rows=[r for r in book.records.values() if r['status']=='pending'] if book else []
        if rows:review_panel.pack(fill='both',expand=True)
        else:review_panel.pack_forget()
        signature=[(r['request_id'],r['title'],r['singer'],r['key']) for r in rows]
        if signature!=last[0]:
            selection=tree.selection();tree.delete(*tree.get_children())
            for rid,title,singer,key in signature:tree.insert('', 'end',iid=rid,values=(title,singer,key))
            if selection and tree.exists(selection[0]):tree.selection_set(selection[0])
            last[0]=signature
        pending[0]=window.after(700,refresh)
    def cleanup(e):
        if e.widget is window:
            if pending[0] is not None:window.after_cancel(pending[0]);pending[0]=None
    window.bind('<Destroy>',cleanup,add='+')
    show_step();update_invite();refresh()
