"""Queue insertion, persistent playback history and operator performance dialogs."""
import copy
import logging
import uuid
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog
from .library import QueueItem,read_json,write_json,validate_queue,json_recovery_error,JsonRecoveryError,read_json_snapshot,JSON_UNSET
from .dialog_layout import DialogWindow,ActionBar,scrollable_tree

def validate_history(raw):
    if not isinstance(raw, list):raise ValueError('ประวัติต้องเป็นรายการ JSON')
    for index, row in enumerate(raw, 1):
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) for k in ('time','title','path','status')):
            raise ValueError(f'ประวัติรายการที่ {index} มีข้อมูลไม่ครบหรือผิดรูปแบบ')
        try:validate_queue([row['item']])
        except (KeyError, ValueError) as error:
            raise ValueError(f'ประวัติรายการที่ {index}: ข้อมูลคิวไม่ถูกต้อง') from error
    return raw


def read_history_snapshot(path):
    raw,revision=read_json_snapshot(Path(path),[])
    try:validate_history(raw)
    except ValueError as error:raise json_recovery_error(path,str(error)) from error
    return raw,revision


def read_history(path):
    return read_history_snapshot(path)[0]


class PlayHistory:
    def __init__(self,path):
        self.path=Path(path)
        raw,self._revision=read_history_snapshot(self.path)
        # Import legacy events before the rolling 500-row history is shortened.
        # Failure does not erase the original journal; a later preview can retry.
        if raw and any(row.get('status') in ('completed','medley') for row in raw):
            try:
                from .play_stats import sync_recent
                sync_recent(self.path)
            except (OSError, sqlite3.Error, ValueError):
                logging.exception('PLAY_STATS_MIGRATION_FAILED')
        self.rows=copy.deepcopy(raw[-500:])
        for row in self.rows:
            if row.get('status')=='playing':row['status']='interrupted'

    def _commit(self,rows):
        old=self.rows
        self.rows=rows
        try:self.save()
        except Exception:
            self.rows=old
            raise

    def start(self,item,song):
        rows=copy.deepcopy(self.rows)
        if rows and rows[-1].get('status')=='playing':rows[-1]['status']='interrupted'
        row={'time':datetime.now().astimezone().isoformat(timespec='seconds'),'title':song.get('title',''),'artist':song.get('artist',''),'path':song['path'],'item':asdict(item),'status':'playing','event_id':uuid.uuid4().hex}
        row['item']['request_id']='';rows.append(row)
        self._commit(rows[-500:])
        return row

    def finish(self,status,item=None):
        if not self.rows or self.rows[-1].get('status')!='playing':return
        rows=copy.deepcopy(self.rows)
        if item is not None:
            rows[-1]['item']=asdict(item);rows[-1]['item']['request_id']=''
        rows[-1]['status']=status
        self._commit(rows)
        if status in ('completed','medley'):
            try:
                from .play_stats import sync_recent
                sync_recent(self.path)
            except (OSError, sqlite3.Error, ValueError):
                # Recent history is already saved, and can be replayed into
                # stats idempotently at the next successful operation.
                logging.exception('PLAY_STATS_SYNC_FAILED')

    def save(self):
        read_history(self.path)
        validate_history(self.rows)
        self._revision=write_json(self.path,self.rows,expected_revision=getattr(self,'_revision',JSON_UNSET))

    def item(self,index,library):
        row=self.rows[index];item=QueueItem.from_dict(row['item']);song=library.get(item.song_id)
        if not song or song['path']!=row['path']:raise ValueError('เพลงในประวัติไม่ตรงกับฐานข้อมูลปัจจุบัน กรุณาค้นหาใหม่')
        if not Path(song['path']).is_file():raise ValueError('ไม่พบไฟล์เพลงเดิม')
        item.request_id=''
        item.medley_session=''
        return item

def history(app):
    if 'data_dir' not in app.__dict__:return None
    if '_play_history' not in app.__dict__:app._play_history=PlayHistory(app.data_dir/'history.json')
    return app._play_history

def report_history_error(app):
    logging.exception('HISTORY_PERSIST_FAILED')
    status=getattr(app,'status_var',None)
    if status is not None:status.set('บันทึกประวัติไม่สำเร็จ • ไฟล์เดิมยังอยู่ กรุณาตรวจ Log')


def history_finish(app,status):
    try:
        h=history(app)
        if h:h.finish(status,getattr(app,'current_item',None))
    except OSError:report_history_error(app)


def history_start(app,item):
    try:
        h=history(app)
        if h:h.start(item,app.current_song)
    except OSError:report_history_error(app)


def history_for_window(app):
    if 'data_dir' not in app.__dict__:return None
    path=Path(app.data_dir)/'history.json'
    try:
        _,revision=read_history_snapshot(path)
        cached=app.__dict__.get('_play_history')
        if cached is not None and getattr(cached,'_revision',revision)!=revision:
            app.__dict__['_play_history']=PlayHistory(path)
        return history(app)
    except JsonRecoveryError as error:
        logging.exception('HISTORY_RECOVERY_REQUIRED')
        from .json_recovery import prompt_recovery
        if not prompt_recovery(error,parent=app):return None
        app.__dict__.pop('_play_history',None)
        return history(app)


def restore_history(app):
    from .json_recovery import prompt_restore
    path=Path(app.data_dir)/'history.json'
    if not prompt_restore(path,'กู้ประวัติการเล่นจากไฟล์สำรอง ไม่เปลี่ยนคิวหรือเพลงที่กำลังเล่น',parent=app):return False
    app.__dict__.pop('_play_history',None)
    # Reload before reporting success to the caller; existing UI gets a fresh snapshot.
    history(app)
    logging.info('HISTORY_RECOVERY_COMPLETE')
    return True


class PerformanceFeatures:
    def insert_queue_window(self):
        win=DialogWindow(self);win.title('แทรกเพลงเข้าคิว');win.geometry('720x480')
        query=tk.StringVar();row=ttk.Frame(win.content,padding=12);row.pack(fill='x')
        entry=ttk.Entry(row,textvariable=query,font=('Tahoma',13));entry.pack(side='left',fill='x',expand=True)
        table,tree=scrollable_tree(win.content,columns=('title','artist'),show='headings',height=10,selectmode='browse')
        tree.heading('title',text='เพลง');tree.heading('artist',text='ศิลปิน');table.pack(fill='both',expand=True,padx=12)
        def search(*unused):
            tree.delete(*tree.get_children())
            for song in self.library.search(query.get(),limit=200,playable_only=True):tree.insert('','end',iid=str(song['id']),values=(song['title'],song['artist']))
        ttk.Button(row,text='ค้นหา',command=search).pack(side='left',padx=8);entry.bind('<Return>',search)
        selected=self.queue_index();position=tk.IntVar(value=(selected+1 if selected is not None else 1))
        footer=ttk.Frame(win.content,padding=12);footer.pack(fill='x')
        ttk.Label(footer,text='แทรกก่อนคิวที่').pack(side='left');ttk.Spinbox(footer,from_=1,to=len(self.song_queue.items)+1,textvariable=position,width=6).pack(side='left',padx=8)
        def insert():
            if not tree.selection():return
            try:
                index=position.get()-1
                if not 0<=index<=len(self.song_queue.items):raise ValueError('ตำแหน่งคิวเปลี่ยนไป กรุณาระบุตำแหน่งใหม่')
                self.song_queue.insert(index,QueueItem(int(tree.selection()[0])));self.refresh_queue(index);win.destroy()
            except (ValueError,tk.TclError,OSError) as error:self.show_error(error)
        ttk.Button(win.footer,text='แทรกคิว',command=insert).pack(side='right');entry.focus_set()
    def history_window(self):
        try:h=history_for_window(self)
        except OSError as error:
            logging.exception('HISTORY_OPEN_FAILED');self.show_error(error);return
        if h is None:return
        rows=copy.deepcopy(h.rows)
        win=DialogWindow(self);win.title('ประวัติการเล่น • 500 รายการล่าสุด');win.geometry('820x500')
        table,tree=scrollable_tree(win.content,columns=('time','title','singer','status'),show='headings',height=14,selectmode='browse')
        for col,label in [('time','เวลา'),('title','เพลง'),('singer','ผู้ร้อง'),('status','สถานะ')]:tree.heading(col,text=label);tree.column(col,width=160)
        table.pack(fill='both',expand=True,padx=12,pady=12)
        labels={'playing':'เพลงปัจจุบัน','completed':'จบเพลง','interrupted':'หยุด/เปลี่ยนเพลง','medley':'ต่อเมดเล่ย์'}
        for i,row in reversed(list(enumerate(rows))):tree.insert('','end',iid=str(i),values=(row['time'],row['title'],row['item'].get('singer',''),labels.get(row['status'],row['status'])))
        def restore(first=False):
            if not tree.selection():return
            try:
                # Snapshot row avoids wrong selection when playback adds new history.
                snapshot=PlayHistory.__new__(PlayHistory);snapshot.rows=rows
                item=snapshot.item(int(tree.selection()[0]),self.library)
                index=0 if first else len(self.song_queue.items);self.song_queue.insert(index,item);self.refresh_queue(index)
                self.status_var.set('นำเพลงจากประวัติเข้าคิวแล้ว')
            except (ValueError,OSError) as error:self.show_error(error)
        bar=ActionBar(win.footer);bar.pack(fill='x')
        for label,cmd in [('เพิ่มท้ายคิว',lambda:restore(False)),('แทรกเป็นคิวถัดไป',lambda:restore(True))]:ttk.Button(bar,text=label,command=cmd).pack(side='left',padx=6,pady=10)
        def recover():
            try:
                if restore_history(self):
                    win.destroy();self.history_window()
            except OSError as error:
                logging.exception('HISTORY_RECOVERY_RELOAD_FAILED');self.show_error(error)
        ttk.Button(bar,text='กู้ประวัติจากไฟล์สำรอง',command=recover).pack(side='right',padx=6,pady=10)

    def media_audio_window(self):
        from .media_routing import audio_window
        return audio_window(self)
    def soundfont_mapping_window(self):
        from .font_mapping import mapping_window
        return mapping_window(self)
    def stage_fx_window(self):
        from .midi_keyboard import open_keyboard
        panel=open_keyboard(self)
        panel._keyboard_pinned=True
        return panel
    def medley_window(self):
        from .medley import settings_window
        return settings_window(self)
