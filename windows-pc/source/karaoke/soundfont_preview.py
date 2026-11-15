"""Isolated audition: all native synth ownership stays on one background thread."""
import queue
import logging
import threading
from .soundfont import normalize_audio, bounded


def note_groups(mode, first, last):
    if mode not in ('โน้ตเดียว','ไล่ช่วงโน้ต','คอร์ดเมเจอร์'):raise ValueError('รูปแบบทดลองเสียงไม่ถูกต้อง')
    first=bounded(first,0,127,'โน้ตเริ่ม',True)
    last=bounded(last,0,127,'โน้ตสุดท้าย',True)
    if mode=='โน้ตเดียว':return [(first,)]
    if mode=='คอร์ดเมเจอร์':
        if first>120:raise ValueError('คอร์ดเมเจอร์ต้องเริ่มไม่เกินโน้ต 120')
        return [(first,first+4,first+7)]
    if first>last:raise ValueError('โน้ตเริ่มต้องไม่เกินโน้ตสุดท้าย')
    return [(n,) for n in range(first,last+1)]


class Audition:
    def __init__(self):
        self.events=queue.Queue();self.serial=0;self.cancel=None;self.threads=[]
        self.lock=threading.Lock()

    def busy(self):
        return any(t.is_alive() for t in self.threads)

    def stop(self):
        self.serial+=1
        if self.cancel:self.cancel.set()

    def start(self,native,settings,preset,channel,program,groups,factory=None):
        self.stop();token=self.serial;cancel=self.cancel=threading.Event()
        def run():
            synth=None
            # Serialize native initialization/teardown, including cancelled loads.
            with self.lock:
                if cancel.is_set():return
                try:
                    logging.info('SOUNDFONT_AUDITION preparing token=%s', token)
                    options=normalize_audio(settings,require_files=True)
                    actual=dict(settings,soundfont_audio=options)
                    if preset:
                        from .preset_browser import preview_settings
                        actual=preview_settings(options,*preset[:3])
                    if cancel.is_set():return
                    if factory is None:
                        from .bass import BassSynth
                        create=BassSynth
                    else:create=factory
                    logging.info('SOUNDFONT_AUDITION native load begin token=%s', token)
                    synth=create(native,settings=actual)
                    logging.info('SOUNDFONT_AUDITION native load complete token=%s', token)
                    if cancel.is_set():return
                    synth.send(bytes([0xc0|channel,program]))
                    synth.send(bytes([0xb0|channel,7,80]))
                    self.events.put((token,'playing',None))
                    for group in groups:
                        if cancel.is_set():break
                        for n in group:synth.send(bytes([0x90|channel,n,64]))
                        interrupted=cancel.wait(.30)
                        for n in group:synth.send(bytes([0x80|channel,n,0]))
                        if interrupted or cancel.wait(.10):break
                except Exception as error:
                    logging.exception('SOUNDFONT_AUDITION failed token=%s', token)
                    self.events.put((token,'error',str(error)))
                finally:
                    if synth is not None:
                        try:synth.close()
                        except Exception as error:
                            logging.exception('SOUNDFONT_AUDITION cleanup failed token=%s', token)
                            self.events.put((token,'error',str(error)))
                    logging.info('SOUNDFONT_AUDITION finished token=%s cancelled=%s', token, cancel.is_set())
                    self.events.put((token,'finished',None))
        self.threads=[t for t in self.threads if t.is_alive()]
        thread=threading.Thread(target=run,daemon=True,name='soundfont-audition')
        self.threads.append(thread);thread.start()
        return token
