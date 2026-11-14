"""Bounded, throttled progress with a complete streaming CSV work log."""
import csv
import time
import uuid
from datetime import datetime
from collections import deque
from pathlib import Path

class JobReporter:
    def __init__(self, messages, directory, title='สร้างรายการเพลง'):
        self.messages=messages
        self.started=time.monotonic()
        self.started_at=datetime.now().astimezone().isoformat(timespec='seconds')
        self.phase_started=self.started
        self.last_emit=0
        self.pending=deque(maxlen=300)
        self.log_path=Path(directory)/('song-job-'+uuid.uuid4().hex[:12]+'.csv')
        self.stream=None
        self.writer=None
        self.logged=0
        self.state=dict(title=title,started_at=self.started_at,ended_at='',phase='เตรียมงาน',total=None,done=0,target=0,
                        processed=0,accepted=0,rejected=0,unsupported=0,duplicates=0,path='',
                        finished=False,cancelled=False,error='',elapsed=0,log=str(self.log_path))

    def event(self, event):
        kind=event.get('type','progress')
        if kind=='phase':
            self.phase_started=time.monotonic()
            self.state.update(phase=event['phase'],total=event.get('total'),done=0,path='',bytes_done=0,bytes_total=0)
            if 'target' in event:
                self.state['target']=event['target']
        elif kind in ('item','notice'):
            row=dict(event)
            if kind=='item':
                self.state['processed']+=1
                self.state['accepted' if event.get('ok') else 'rejected']+=1
                self.state['done']=self.state['processed']
                category={'เดิมไม่เปลี่ยน':'unchanged','เพิ่มใหม่':'added','อัปเดต':'updated','ซ้ำกับรายการเดิม':'duplicates','อ่านไม่ได้':'failed'}.get(event.get('category'))
                if category:self.state[category]=self.state.get(category,0)+1
            else:
                self.state['unsupported']+=1
            self.state['path']=event.get('path','')
            self.pending.append(row)
            if self.writer is None:
                self.log_path.parent.mkdir(parents=True,exist_ok=True)
                self.stream=self.log_path.open('w',newline='',encoding='utf-8-sig')
                self.writer=csv.writer(self.stream)
                self.writer.writerow(['ลำดับ','เวลา (วินาที)','ผลตรวจ','รหัส','ชื่อเพลง','ศิลปิน','ไฟล์','รายละเอียด'])
            def safe(value):
                value=str(value)
                return "'"+value if value.lstrip().startswith(('=','+','-','@')) else value
            self.logged+=1
            self.writer.writerow([self.logged,round(time.monotonic()-self.started,2),
                event.get('result') or ('อ่านได้' if event.get('ok') else 'ข้าม'),safe(event.get('code','')),safe(event.get('title','')),
                safe(event.get('artist','')),safe(event.get('path','')),safe(event.get('note',''))])
        else:
            if event.get('path') and event['path']!=self.state.get('path'):
                self.state.update(bytes_done=0,bytes_total=0)
            for name in ('done','total','target','path','duplicates','phase','accepted','rejected','bytes_done','bytes_total','unchanged','added','updated','failed','incremental'):
                if name in event:
                    self.state[name]=event[name]
        self.emit(force=kind=='phase')

    def emit(self,force=False):
        now=time.monotonic()
        if not force and now-self.last_emit<.1:
            return
        self.state['elapsed']=now-self.started
        self.state['phase_elapsed']=now-self.phase_started
        self.messages.put(('job_progress',dict(state=dict(self.state),rows=list(self.pending))))
        self.pending.clear()
        self.last_emit=now
        if self.stream:
            self.stream.flush()

    def finish(self,cancelled=False,error=''):
        self.state.update(finished=True,cancelled=bool(cancelled),error=str(error),ended_at=datetime.now().astimezone().isoformat(timespec='seconds'))
        if error:
            self.state['phase']='เกิดข้อผิดพลาด'
        elif cancelled:
            self.state['phase']='ยกเลิกแล้ว — เก็บส่วนที่ทำเสร็จ'
        else:
            self.state['phase']='เสร็จเรียบร้อย'
        self.emit(force=True)
        if self.stream:
            self.stream.close()
            self.stream=None


def percent(state):
    total=state.get('total')
    if total is None:
        return None
    if total==0:
        return 100 if state.get('finished') and not state.get('cancelled') and not state.get('error') else 0
    return min(100,max(0,100*state.get('done',0)/total))


def timing(state):
    done=state.get('done',0);total=state.get('total');elapsed=state.get('phase_elapsed',state.get('elapsed',0))
    rate=done/elapsed if elapsed>0 and done else 0
    eta=(total-done)/rate if total is not None and total>=done and rate else None
    return rate,eta
