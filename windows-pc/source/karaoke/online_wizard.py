"""Three-step X-Stage Online window. UI only; never owns credentials/uploads.

The existing X-Stage workers and SQLite recovery journal remain authoritative.
No OAuth secrets, songs or session tokens are written by these Tk widgets.
"""
from __future__ import annotations

import time
import queue
import threading
import tkinter as tk

from .drive_storage import format_bytes, projected_storage, read_drive_quota, storage_pct
from .online_eta import OverallSyncEstimate
from tkinter import ttk


def setup_online_wizard(*, window, app, account, state, recovery, schedule,
                        font_var, font_labels, type_vars, plan_counts,
                        choose_font, start_sync, main_view, confirm_enabled, progress_widgets=None, stop_sync=None):
    """Show login -> verified identity/options -> live sync inside one Toplevel."""
    page = {'name': 'login', 'login_clicked': False, 'started_at': time.monotonic()}
    # Fixed, compact page content. No scrollbars; nonessential text is omitted.
    def compact_page(pad):
        overlay=ttk.Frame(window)
        content=ttk.Frame(overlay, padding=pad)
        content.place(relx=.5, rely=.5, anchor='center')
        overlay.bind('<Configure>', lambda event: content.place_configure(
            width=max(240,min(600,event.width))))
        return overlay, content

    login_overlay, login = compact_page((18, 16))
    settings_overlay, settings = compact_page((14, 12))
    progress_overlay, progress = compact_page((14, 10))
    login.columnconfigure(0, weight=1)
    settings.columnconfigure(0, weight=1)
    progress.columnconfigure(0, weight=1)

    def title(parent, label, index):
        ttk.Label(parent, text=f'ขั้นตอน {index}/3   •   {label}',
                  font=('Tahoma', 14, 'bold'), foreground='#49daca').grid(
                      row=0, column=0, sticky='w', pady=(0, 5))

    title(login, 'เข้าสู่ระบบ Google Drive', 1)
    signin_card = ttk.LabelFrame(login, text='บัญชี Google Drive ส่วนตัว', padding=(12, 9))
    signin_card.grid(row=1, column=0, sticky='ew', pady=(3, 7))
    signin_card.columnconfigure(0, weight=1)
    login_status = ttk.Label(signin_card, text='กำลังตรวจบัญชีที่จดจำไว้…',
                             wraplength=580, justify='left')
    login_status.grid(row=0, column=0, sticky='ew', pady=(0, 7))
    login_button = ttk.Button(signin_card, text='G  เข้าสู่ระบบ Google Drive',
                              style='Accent.TButton')
    login_button.grid(row=1, column=0, sticky='ew', ipady=6)
    ttk.Button(login, text='ปิดหน้าต่าง', command=lambda: window.event_generate('<<OnlineClose>>')).grid(
        row=2, column=0, sticky='e', pady=(4, 0))

    title(settings, 'ยืนยันบัญชีและตั้งค่าซิงค์', 2)
    account_box = ttk.Frame(settings, padding=(6, 3))
    account_box.grid(row=1, column=0, sticky='ew', pady=(0, 5))
    account_box.columnconfigure(1, weight=1)
    avatar = ttk.Label(account_box, text='G', width=3, anchor='center')
    avatar.grid(row=0, column=0, rowspan=2, padx=(0, 6), pady=(0, 0))
    account_name = ttk.Label(account_box, text='ยังไม่มีบัญชี', font=('Tahoma', 10, 'bold'), wraplength=400, justify='left')
    account_name.grid(row=0, column=1, sticky='w')
    account_email = ttk.Label(account_box, text='', style='Muted.TLabel', wraplength=400, justify='left')
    account_email.grid(row=1, column=1, sticky='w')
    settings_box = ttk.Frame(settings, padding=(6, 3))
    settings_box.grid(row=2, column=0, sticky='ew')
    settings_box.columnconfigure(0, weight=1)
    # Stack SoundFont and song types: no three-column row wider than a small
    # laptop or a high-DPI window. Long paths are clipped by the readonly combo.
    ttk.Label(settings_box, text='SoundFont').grid(row=0, column=0,
        sticky='w', pady=(0, 2))
    font_row = ttk.Frame(settings_box)
    font_row.grid(row=1, column=0, sticky='ew', pady=(0, 5))
    font_row.columnconfigure(0, weight=1)
    fonts = ttk.Combobox(font_row, textvariable=font_var, values=list(font_labels),
                         state='readonly', width=12)
    fonts.grid(row=0, column=0, sticky='ew', padx=(0, 6))
    font_button = ttk.Button(font_row, text='เลือก SF2…', command=choose_font)
    font_button.grid(row=0, column=1, sticky='e')
    type_box = ttk.Frame(settings_box)
    type_box.grid(row=2, column=0, sticky='ew', pady=(0, 3))
    ttk.Checkbutton(type_box, text='NCN', variable=type_vars['NCN']).pack(side='left', padx=(0, 17))
    ttk.Checkbutton(type_box, text='MIDI / KAR', variable=type_vars['MIDI']).pack(side='left')
    count_status = ttk.Label(settings_box, text='กำลังตรวจฐานเพลง…',
                             wraplength=555, justify='left')
    count_status.grid(row=3, column=0, sticky='ew', pady=(3, 0))
    recovery_status = ttk.Label(settings, text=recovery.describe() or
        'ข้อมูลเพลงและคิวเดิมจะยังอยู่ในเครื่อง แม้ปิดหน้าต่างหรือไฟดับ',
        style='Muted.TLabel', wraplength=580, justify='left')
    recovery_status.grid(row=3, column=0, sticky='w', pady=(3, 3))
    actions = ttk.Frame(settings)
    actions.grid(row=4, column=0, sticky='ew', pady=(3, 0))
    actions.columnconfigure(0, weight=1)
    actions.columnconfigure(1, weight=1)
    ttk.Button(actions, text='← กลับ', command=lambda: show('login')).grid(row=0, column=0, sticky='w')
    confirm = ttk.Button(actions, text='ซิงค์ต่อ' if recovery.interrupted() else 'เริ่มซิงค์', state='disabled', style='Accent.TButton')
    confirm.grid(row=0, column=1, sticky='e')

    # R19: one visible bar for the entire job; keep the Google Drive quota
    # information as text, without two additional misleading percent bars.
    title(progress, 'สถานะซิงค์', 3)
    progress_user = ttk.Frame(progress)
    progress_user.grid(row=1, column=0, sticky='ew', pady=(0, 5))
    progress_user.columnconfigure(1, weight=1)
    progress_avatar = ttk.Label(progress_user, text='G', width=3, anchor='center')
    progress_avatar.grid(row=0, column=0, rowspan=2, padx=(0, 7))
    progress_name = ttk.Label(progress_user, text='Google', font=('Tahoma', 10, 'bold'))
    progress_name.grid(row=0, column=1, sticky='w')
    progress_email = ttk.Label(progress_user, text='', style='Muted.TLabel')
    progress_email.grid(row=1, column=1, sticky='w')

    styles = ttk.Style(window)
    for key, color in [('Waiting','#64a8e8'),('Low','#fa7a66'),
                       ('Medium','#efb64e'),('High','#56c7f0'),('Done','#46d5a0')]:
        styles.configure('Online'+key+'.Horizontal.TProgressbar', background=color,
                         troughcolor='#17273e', bordercolor='#17273e',
                         lightcolor=color, darkcolor=color)
    sync_board = ttk.Frame(progress, padding=(3, 3))
    sync_board.grid(row=2, column=0, sticky='ew', pady=(2, 5))
    sync_board.columnconfigure(0, weight=1)
    ttk.Label(sync_board, text='ความคืบหน้ารวม').grid(row=0, column=0, sticky='w')
    overall_number = ttk.Label(sync_board, text='0.0%', style='Muted.TLabel')
    overall_number.grid(row=0, column=1, sticky='e')
    overall_bar = ttk.Progressbar(sync_board, maximum=100, mode='determinate',
        value=0, style='OnlineWaiting.Horizontal.TProgressbar')
    overall_bar.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(4, 3))
    eta_label = ttk.Label(sync_board, text='กำลังเตรียมข้อมูลเพื่อประเมินเวลาเสร็จ',
        wraplength=570, style='Muted.TLabel', justify='left')
    eta_label.grid(row=2, column=0, columnspan=2, sticky='w')

    for name, color in [('Safe','#46d5a0'), ('Caution','#56c7f0'),
                        ('Warning','#efb64e'), ('Critical','#fa7a66')]:
        styles.configure('OnlineStorage'+name+'.TLabel', foreground=color)
    storage_board=ttk.Frame(progress, padding=(3, 1))
    storage_board.grid(row=3, column=0, sticky='ew', pady=(0, 2))
    storage_board.columnconfigure(0, weight=1)
    storage_views={}
    for row,(key,label) in enumerate((('actual','Drive ใช้จริง'),
                                       ('forecast','เมื่อซิงค์ครบ'))):
        line=ttk.Label(storage_board, text=label+' : รอข้อมูล',
                       style='Muted.TLabel', anchor='w', wraplength=570)
        line.grid(row=row, column=0, sticky='ew', pady=(0, 1))
        # Notes remain available for diagnostics; only one progress bar is shown.
        note=ttk.Label(storage_board, text='', style='Muted.TLabel')
        storage_views[key]=(line, note)
    estimator=OverallSyncEstimate()

    quota_results=queue.SimpleQueue()
    quota_state={'in_flight':False,'last_request':0.0,'snapshot':None,
                 'checked':0.0,'last_email':'','error':False}

    def fetch_quota(credentials):
        try:
            from .google_drive_sync import Drive, load_client
            client_id, client_secret = load_client(app.home, app.data_dir)
            token, email, refresh, expires = credentials
            drive=Drive(token,None,client_id,client_secret,refresh,expires)
            data=read_drive_quota(drive)
            quota_results.put((email,data,None))
        except Exception as error:
            # Google errors are advisory here; never interrupt a running sync.
            quota_results.put((credentials[1],None,type(error).__name__))

    def capacity_style(pct):
        return ('Critical' if pct>=90 else 'Warning' if pct>=75 else
                'Caution' if pct>=50 else 'Safe')

    def display_capacity(key, amount, limit, note):
        label,info=storage_views[key]
        pct=storage_pct(amount,limit)
        caption='Drive ใช้จริง' if key=='actual' else 'เมื่อซิงค์ครบ'
        if amount is None:
            label.configure(text=caption+' : รอข้อมูล', style='Muted.TLabel')
        elif pct is None:
            label.configure(text=caption+' : '+format_bytes(amount)+' (ไม่ระบุโควตา)',
                            style='Muted.TLabel')
        else:
            label.configure(text=f'{caption} : {pct:.1f}% ({format_bytes(amount)})',
                            style='OnlineStorage'+capacity_style(pct)+'.TLabel')
        info.configure(text=note)

    def update_storage():
        now=time.monotonic()
        credentials=getattr(account,'credentials',None)
        email=str(credentials[1]) if credentials else ''
        if quota_state['last_email'] and email!=quota_state['last_email']:
            quota_state['snapshot']=None
            quota_state['checked']=0
        quota_state['last_email']=email
        while True:
            try: result_email,data,error=quota_results.get_nowait()
            except queue.Empty: break
            quota_state['in_flight']=False
            if result_email!=email: continue
            if data is not None:
                quota_state['snapshot']=data
                quota_state['checked']=now
                quota_state['error']=False
            else:
                quota_state['error']=True
        if (credentials and not quota_state['in_flight'] and
                now-quota_state['last_request']>=30):
            quota_state['last_request']=now
            quota_state['in_flight']=True
            threading.Thread(target=fetch_quota,args=(tuple(credentials),),daemon=True,
                             name='xstage-google-storage').start()
        quota=quota_state['snapshot']
        if quota is None:
            note=('เชื่อมต่อ Google ไม่สำเร็จ • กำลังลองใหม่' if quota_state['error'] else
                  'รอ Google Drive ส่งข้อมูลพื้นที่บัญชี')
            display_capacity('actual',None,None,note)
            display_capacity('forecast',None,None,'รอข้อมูลพื้นที่และตัวอย่างไฟล์ซิงค์')
            return
        stale=' • กำลังอัปเดตใหม่' if quota_state['error'] or now-quota_state['checked']>65 else ''
        drive=quota.get('usageInDrive')
        note='Drive '+format_bytes(drive)+' • อัปเดตทุก ~30 วินาที'+stale
        display_capacity('actual',quota['usage'],quota.get('limit'),note)
        stats=state.get('storage_stats')
        predicted=projected_storage(quota,stats)
        if predicted is None:
            display_capacity('forecast',None,quota.get('limit'),
                'รอตัวอย่างไฟล์อัปโหลดใหม่อย่างน้อย 3 เพลง และตรวจอย่างน้อย 12 เพลง')
        elif predicted['complete']:
            display_capacity('forecast',predicted['bytes'],quota.get('limit'),
                'ประมวลผลครบแล้ว • รอ Google รายงานพื้นที่ล่าสุด (ข้อมูลอาจมีความหน่วง)')
        else:
            display_capacity('forecast',predicted['bytes'],quota.get('limit'),
                'คาดว่าจะเพิ่มอีก '+format_bytes(predicted['extra_bytes'])+
                f' • อิง {predicted["samples"]} เพลงล่าสุด (อัปโหลดใหม่ {predicted["uploads"]})' +
                ' • เป็นค่าประมาณ ไม่รวมการเปลี่ยนแปลงจากแอปอื่น')

    detail=ttk.Label(progress,text='รอเริ่มงาน',style='Muted.TLabel',anchor='w')
    detail.grid(row=4,column=0,sticky='ew',pady=(1,3))
    # Preserve the worker's detailed indicator for diagnostics without UI clutter.
    indicator=ttk.Label(progress,text='',style='Muted.TLabel')
    progress_actions=ttk.Frame(progress)
    progress_actions.grid(row=5,column=0,sticky='ew',pady=(2,0))
    progress_actions.columnconfigure(1,weight=1)
    back_button=ttk.Button(progress_actions,text='← กลับ',
        command=lambda: show('settings'))
    back_button.grid(row=0,column=0,sticky='w')
    def finish_or_stop():
        if state.get('sync_completed') and not state['started']:
            # Browser and close only after the user clicks the completed action.
            app.open_karaoke_online()
            window.event_generate('<<OnlineClose>>')
        elif state['started']:
            # Stop the worker but keep this window open for the final status.
            if stop_sync:
                stop_sync()
            else:
                window.event_generate('<<OnlineClose>>')
        else:
            window.event_generate('<<OnlineClose>>')

    pause_button=ttk.Button(progress_actions, text='หยุด',
        command=finish_or_stop)
    pause_button.grid(row=0,column=1,sticky='e')

    def update_progress():
        source=progress_widgets or {}
        if not source:return
        try:
            message=str(source['status'].cget('text'))
            detail.configure(text=short_status(message, 74))
            indicator.configure(text=str(source['indicator'].cget('text'))[:220])
            feedback=source['feedback']
            pct, eta=estimator.observe(running=bool(state['started']),
                completed=bool(state.get('sync_completed')), step=feedback.step,
                done=feedback.done, total=feedback.total, unit=feedback.unit,
                message=message, now=time.monotonic())
            choice=('Waiting' if not state['started'] and not state.get('sync_completed')
                    else 'Low' if pct<25 else 'Medium' if pct<50 else
                    'High' if pct<75 else 'Done')
            overall_bar.configure(value=pct,
                style='Online'+choice+'.Horizontal.TProgressbar')
            overall_number.configure(text=f'{pct:.1f}%')
            eta_label.configure(text=eta)
            back_button.configure(state='disabled' if state['started'] else 'normal')
            pause_button.configure(text=('หยุด' if state['started'] else
                'สำเร็จ • เปิดเว็บ' if state.get('sync_completed') else 'ปิด'))
        except tk.TclError:
            pass

    def short_status(value, limit=70):
        value=' '.join(str(value).split())
        return value if len(value)<=limit else value[:limit-1]+'…'

    def update_responsive(event=None):
        if state['closed']:return
        width=min(600,window.winfo_width())
        # One-row actions, compact labels, no scrolling and no horizontal growth.
        confirm.configure(text='ซิงค์ต่อ' if recovery.interrupted() else 'เริ่มซิงค์')
        confirm.grid_configure(row=0,column=1,columnspan=1,sticky='e',pady=0)
        text_width=max(100,width-104)
        login_status.configure(wraplength=text_width)
        for label in (account_name,account_email,progress_name,progress_email):
            label.configure(wraplength=max(100,width-110))
        count_status.configure(wraplength=max(100,width-62))
        recovery_status.configure(wraplength=max(100,width-60))
        eta_label.configure(wraplength=max(100,width-66))
        for storage_label,_info in storage_views.values():
            storage_label.configure(wraplength=max(100,width-66))

    def show(which):
        if state['closed'] or not window.winfo_exists():
            return
        page['name'] = which
        for overlay in (login_overlay,settings_overlay,progress_overlay):
            overlay.place_forget()
        chosen={'login':login_overlay,'settings':settings_overlay,'progress':progress_overlay}[which]
        chosen.place(x=0, y=0, relwidth=1, relheight=1)
        chosen.lift()
        if which == 'settings':
            update_review()
        elif which == 'progress':
            update_review()
            update_progress()
            update_storage()

    def update_review():
        credentials = getattr(account, 'credentials', None)
        if not credentials:
            confirm.configure(state='disabled')
            account_name.configure(text='รอบัญชี Google')
            account_email.configure(text='')
            return
        email = credentials[1]
        verified_profile = getattr(account, 'profile', {}) or {}
        # An unverified profile cannot replace the authenticated account email.
        from .google_account_ui import display_identity
        name = display_identity(verified_profile, email)
        width=min(600,window.winfo_width())
        max_chars=max(14,min(56,(width-95)//7))
        account_name.configure(text=short_status(name,max_chars))
        account_email.configure(text=short_status(email,max_chars+4))
        picture = getattr(account, '_photo', None)
        progress_name.configure(text=short_status(name,max_chars))
        progress_email.configure(text=short_status(email,max_chars+4))
        if picture:
            avatar.configure(image=picture, text='')
            avatar.image = picture
            progress_avatar.configure(image=picture,text='')
            progress_avatar.image=picture
        else:
            avatar.configure(image='', text='G')
            avatar.image = None
            progress_avatar.configure(image='',text='G')
            progress_avatar.image=None
        if tuple(fonts.cget('values')) != tuple(font_labels):
            fonts.configure(values=list(font_labels))
        total = sum(plan_counts[k] for k in ('NCN', 'MIDI') if type_vars[k].get())
        if not state['ready']:
            count_status.configure(text='กำลังนับเพลง…')
        else:
            count_status.configure(text=(f'รวม {total:,} เพลง' if window.winfo_width()<400 else
                f'NCN {plan_counts["NCN"]:,}  •  MIDI {plan_counts["MIDI"]:,}  •  เลือก {total:,}'))
        recovery_status.configure(text='พบงานค้าง • ซิงค์ต่อได้' if recovery.interrupted() else '')
        confirm.configure(state='normal' if confirm_enabled() else 'disabled')

    def do_login():
        if not account:
            login_status.configure(text='ไม่พบส่วนเชื่อมต่อ Google กรุณาเปิดโปรแกรมใหม่')
            return
        if getattr(account, 'credentials', None):
            page['login_clicked'] = True
            show('settings')
        elif not account.auth_busy:
            page['login_clicked'] = True
            page['started_at'] = time.monotonic()
            account.login()

    def confirm_sync():
        if not confirm_enabled():
            update_review()
            return
        show('progress')
        start_sync()
        # If preflight rejects the run, don't strand the user on empty progress.
        if not state['started'] and not state['closed']:
            show('settings')

    login_button.configure(command=do_login)
    confirm.configure(command=confirm_sync)
    state['show_wizard_page'] = show
    window.bind('<<OnlineClose>>', lambda _e: window.event_generate('<<OnlineRequestClose>>'), add='+')
    # Delegate all closes to the original window protocol (cancellation is safe).
    window.bind('<<OnlineRequestClose>>', lambda _e: window.tk.call(
        window.protocol('WM_DELETE_WINDOW')), add='+')

    def poll():
        if state['closed'] or not window.winfo_exists():
            return
        credentials = getattr(account, 'credentials', None)
        busy = bool(getattr(account, 'auth_busy', False))
        if page['name'] == 'login':
            if credentials:
                login_status.configure(text='✓ เชื่อมต่อแล้ว: '+str(credentials[1]))
                login_button.configure(text='ถัดไป →', state='normal')
                if page['login_clicked']:
                    page['login_clicked'] = False
                    show('settings')
            elif busy:
                seconds = max(0, int(time.monotonic() - page['started_at']))
                login_status.configure(text=f'กำลังเชื่อมต่อ Google… {seconds} วินาที')
                login_button.configure(state='disabled')
            else:
                login_status.configure(text=short_status(getattr(account, 'home_status', tk.StringVar(
                    value='กรุณาเข้าสู่ระบบ Google')).get(),85))
                login_button.configure(text='G  เข้าสู่ระบบ Google Drive', state='normal')
        elif page['name'] == 'settings':
            update_review()
        elif page['name']=='progress':
            update_progress()
            update_storage()
        schedule(380, poll)

    # The legacy worker widgets are used as a state backend only.
    main_view.pack_forget()
    # First display is always the login step, even when a saved Google session
    # is being restored in the background; nothing is uploaded automatically.
    show('login')
    schedule(200, poll)
    return {'page': page, 'show': show, 'login': login_overlay, 'settings': settings_overlay,
            'progress':progress_overlay, 'progress_bar':overall_bar,
            'progress_percent':overall_number, 'progress_eta':eta_label,
            'progress_pause':pause_button, 'storage_views':storage_views,'state':state,
            'confirm': confirm, 'login_button': login_button,
            'recovery_status': recovery_status}
