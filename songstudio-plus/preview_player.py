"""Pre-export playback for actual source media with timestamped SQLite lyrics.

MIDI output uses the Windows MIDI Mapper (WinMM) without SoundFont downloads
or writing a temporary MIDI file. The browser plays audio/video through
byte-range HTTP responses from the registered source path.

This is a *preview* only: a passed listening test is an explicit user action;
the program never silently marks a song verified. Unsupported formats show a
real error instead of presenting a simulated waveform.
"""
from __future__ import annotations

import ctypes
import os
import threading
import time
from pathlib import Path

import ncn_reader
import plus_core as core

AUDIO_EXT = frozenset({".mp3", ".m4a", ".wav", ".flac", ".mp4", ".webm", ".mkv", ".mov"})
MIDI_EXT = frozenset({".mid", ".midi", ".kar"})
MAX_MIDI_BYTES = 64 * 1024 * 1024


def source_info(workspace, song_id):
    """Resolve exactly the media registered for this Song ID, never by filename."""
    # The app initializes schema once at startup. Range media requests
    # must NOT execute SQLite DDL on each seek/scrub of a large video.
    with core.connect(workspace) as db:
        row=db.execute("""SELECT s.id AS song_id,s.code,xc.export_code,s.title,s.artist,
                m.id AS media_id,m.sha256,m.extension,m.bytes,m.stored_path,
                v.id AS version_id,v.timing_status
             FROM xstage_songs s JOIN xstage_media m ON m.id=s.media_id
             LEFT JOIN xstage_song_export_codes xc ON xc.song_id=s.id
             LEFT JOIN xstage_lyric_versions v ON v.song_id=s.id AND v.is_current=1
             WHERE s.id=?""",(song_id,)).fetchone()
        if not row:
            raise ValueError("ไม่พบเพลงใน SQLite")
        media=db.execute("SELECT * FROM xstage_media WHERE id=?",(row["media_id"],)).fetchone()
        source=core.source_for_build(workspace,db,media)
        if source.suffix.lower() not in AUDIO_EXT | MIDI_EXT:
            raise ValueError("ไม่รองรับการทดสอบสื่อชนิดนี้")
        return dict(row),source


def preview_details(workspace,song_id):
    row,path=source_info(workspace,song_id)
    ext=path.suffix.lower()
    mode="midi" if ext in MIDI_EXT else (
        "video" if ext in {".mp4",".webm",".mkv",".mov"} else "audio")
    with core.connect(workspace) as db:
        if row["version_id"]:
            pairs=core.get_version_lines(db,row["version_id"])
            lines=[]
            for line,cues in pairs:
                cues=core.display_cues(line["text"],cues)
                lines.append({
                    "position":line["position"],"text":line["text"],
                    "start":line["start_time"],"end":line["end_time"],
                    "timing":line["timing_status"],
                    "cues":[{"text":c["text"],"start":c["start_time"],
                             "duration":c["duration"]} for c in cues]
                })
        else:
            lines=[]
        draft=db.execute("SELECT raw_text,reason FROM xstage_lyric_drafts WHERE song_id=?",
                         (song_id,)).fetchone()
    information={
        "song_id":song_id,"code":row["code"],"title":row["title"],
        "artist":row["artist"],"mode":mode,
        "extension":ext,"version_id":row["version_id"],
        "timing_status":row["timing_status"] or "untimed",
        "lines":lines,
        "draft":dict(draft) if draft else None,
        "media_bytes":row["bytes"],
        "warning":(
            "เวลา CUR ไม่ครบ · แสดงเฉพาะช่วงที่มีข้อมูล ไม่ยืนยันว่าปาดสีถูก"
            if row["timing_status"]=="incomplete" else
            "เวลาเป็นค่าประมาณ ต้องฟังตรวจเทียบกับเสียงจริง"
            if row["timing_status"]=="estimated" else
            "เนื้อร้องไม่มีเวลาปาดสี · ทดสอบเสียงได้แต่ยังไม่พร้อมส่งออก"
            if not row["version_id"] else
            "เสียง MIDI ใช้เครื่องสังเคราะห์เสียงที่ Windows มีอยู่ อาจต่างจาก SoundFont ใน Karaoke"),
    }
    if mode=="midi":
        division,tempo,_,duration=ncn_reader.midi_events(path,include_duration=True)
        information["duration"]=round(duration,3)
    else:
        information["duration"]=None  # HTML media element provides actual duration.
    return information


def iter_midi_messages(path):
    """Decode MIDI channel voice messages and exact tempo-based timestamps.

    No random timings, no source mutation and no SysEx device configuration.
    Accept only formats validated by the existing NCN MIDI header parser.
    """
    source=Path(path)
    if source.stat().st_size>MAX_MIDI_BYTES:
        raise ValueError("MIDI ใหญ่เกินขอบเขตการทดลองเปิด (64 MB)")
    original=source.read_bytes()
    division,tempo_map,_,duration=ncn_reader.midi_events(source,include_duration=True,
                                                          raw_data=original)
    if original[:4] != b"MThd":
        # Known legacy header substitutions are validated by midi_events.
        original=b"MThd"+original[4:]
    header_len=int.from_bytes(original[4:8],"big")
    tracks=int.from_bytes(original[10:12],"big")
    offset=8+header_len
    events=[]
    for track in range(tracks):
        if original[offset:offset+4]!=b"MTrk" or offset+8>len(original):
            raise ValueError("MIDI track ไม่สมบูรณ์")
        length=int.from_bytes(original[offset+4:offset+8],"big")
        pos=offset+8
        end=pos+length
        if end>len(original):
            raise ValueError("MIDI track มีข้อมูลไม่ครบ")
        tick=0
        running=None
        order=0
        while pos<end:
            delta,pos=ncn_reader._varlen(original,pos,end)
            tick+=delta
            if pos>=end:
                raise ValueError("MIDI event ถูกตัด")
            code=original[pos]
            if code&0x80:
                pos+=1
                if code<0xF0:
                    running=code
            else:
                if running is None:
                    raise ValueError("MIDI running status ไม่ถูกต้อง")
                code=running
            if code==0xFF:
                if pos>=end:raise ValueError("MIDI meta event ไม่ครบ")
                kind=original[pos]
                pos+=1
                size,pos=ncn_reader._varlen(original,pos,end)
                if pos+size>end:raise ValueError("MIDI meta payload ไม่ครบ")
                pos+=size
                if kind==0x2F:break
            elif code in (0xF0,0xF7):
                size,pos=ncn_reader._varlen(original,pos,end)
                if pos+size>end:raise ValueError("MIDI sysex ไม่ครบ")
                pos+=size
            elif 0x80<=code<=0xEF:
                size=1 if code&0xF0 in (0xC0,0xD0) else 2
                if pos+size>end:raise ValueError("MIDI channel event ไม่ครบ")
                data=original[pos:pos+size]
                pos+=size
                if any(c>127 for c in data):
                    raise ValueError("ข้อมูล MIDI Channel ไม่อยู่ในช่วง 0-127")
                msg=code | (data[0]<<8)
                if size==2:msg|=data[1]<<16
                seconds=ncn_reader.tick_to_seconds(tick,division,tempo_map)
                kind=code&0xF0
                # Note Off precedes Note On when two tracks share a timestamp.
                priority=0 if kind==0x80 or (kind==0x90 and size==2 and data[1]==0) else 1
                events.append((seconds,priority,track,order,msg))
            elif code in (0xF1,0xF3):
                pos+=1
            elif code==0xF2:
                pos+=2
            elif code in (0xF6,0xF8,0xFA,0xFB,0xFC,0xFE):
                pass
            else:
                raise ValueError("ไม่รองรับ MIDI event นี้")
            if pos>end:raise ValueError("MIDI event เกินขนาด track")
            order+=1
        offset=end
    events.sort(key=lambda event:event[:4])
    return [(seconds,msg) for seconds,_,_,_,msg in events],float(duration)


class MidiPreview:
    """One local Windows MIDI output session per Song Studio Plus process."""

    def __init__(self):
        self.lock=threading.RLock()
        self.events=[]
        self.duration=0.0
        self.song_id=None
        self.status="stopped"
        self.position=0.0
        self.offset=0.0
        self.origin=0.0
        self.stop_event=None
        self.worker=None
        self.error=""

    def _stop_locked(self):
        # Capture position before modifying the "playing" state.
        self.position=self._position_locked()
        if self.stop_event is not None:
            self.stop_event.set()
        self.status="paused" if self.song_id is not None else "stopped"

    def _position_locked(self):
        if self.status=="playing":
            return max(0.,min(self.duration,time.monotonic()-self.origin))
        return self.position

    def stop(self):
        with self.lock:
            self._stop_locked()
            self.song_id=None
            self.events=[]
            self.position=0.
            self.status="stopped"

    def state(self):
        with self.lock:
            return {"song_id":self.song_id,"status":self.status,
                    "position":round(self._position_locked(),3),
                    "duration":round(self.duration,3),
                    "error":self.error}

    @staticmethod
    def _open_winmm():
        if os.name!="nt":
            raise ValueError("ทดสอบ MIDI ด้วยเสียงรองรับเฉพาะ Windows")
        from ctypes import wintypes
        lib=ctypes.WinDLL("winmm")
        out=ctypes.c_void_p()
        lib.midiOutOpen.argtypes=[ctypes.POINTER(ctypes.c_void_p),
            wintypes.UINT,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD]
        lib.midiOutOpen.restype=wintypes.UINT
        lib.midiOutShortMsg.argtypes=[ctypes.c_void_p,wintypes.DWORD]
        lib.midiOutShortMsg.restype=wintypes.UINT
        lib.midiOutReset.argtypes=[ctypes.c_void_p]
        lib.midiOutReset.restype=wintypes.UINT
        lib.midiOutClose.argtypes=[ctypes.c_void_p]
        lib.midiOutClose.restype=wintypes.UINT
        code=lib.midiOutOpen(ctypes.byref(out),0xFFFFFFFF,None,None,0)
        if code:
            raise ValueError("Windows ไม่มี MIDI Synthesizer พร้อมใช้งาน (WinMM error "+
                             str(code)+") · ไม่สามารถยืนยันเสียง MIDI ได้")
        return lib,out

    def _play_thread(self,events,duration,offset,stop_event,ready_event):
        handle=None
        lib=None
        try:
            lib,handle=self._open_winmm()
            ready_event.set()  # MIDI Mapper opened successfully.
            # Restore channel program/continuous controllers up to requested
            # seek position. Notes already sounding at a seek point are NOT
            # inferred: only a full play-through proves alignment reliably.
            channel_state={}
            for seconds,msg in events:
                if seconds>=offset:break
                command=msg&0xF0
                if command in (0xC0,0xB0,0xE0):
                    kind=(msg&0xFF,(msg>>8)&0x7F) if command==0xB0 else (msg&0xFF,)
                    channel_state[kind]=msg
            for msg in channel_state.values():
                if stop_event.is_set():break
                lib.midiOutShortMsg(handle,msg)
            for seconds,msg in events:
                if stop_event.is_set():break
                if seconds<offset:continue
                while not stop_event.is_set():
                    with self.lock:
                        time_left=seconds-self._position_locked()
                    if time_left<=0:break
                    stop_event.wait(min(time_left,0.035))
                if stop_event.is_set():break
                lib.midiOutShortMsg(handle,msg)
            with self.lock:
                if self.stop_event is stop_event and not stop_event.is_set():
                    self.position=duration
                    self.status="ended"
        except Exception as error:
            with self.lock:
                if self.stop_event is stop_event:
                    self.status="error"
                    self.error=str(error)
            ready_event.set()
        finally:
            if lib and handle:
                lib.midiOutReset(handle)
                lib.midiOutClose(handle)

    def play(self,workspace,song_id,seek=0.0):
        entry,path=source_info(workspace,song_id)
        if path.suffix.lower() not in MIDI_EXT:
            raise ValueError("เพลงนี้ไม่ใช่ MIDI")
        events,duration=iter_midi_messages(path)
        if duration<=0:
            raise ValueError("MIDI ไม่มีระยะเวลาเล่นที่ตรวจสอบได้")
        # A cursor/tempo-only MIDI fixture is valid but not audible.
        if not any((msg&0xF0)==0x90 and ((msg>>16)&0x7F)>0 for _,msg in events):
            raise ValueError("MIDI นี้ไม่มีโน้ตสำหรับสร้างเสียงทดสอบ")
        seek=float(seek)
        if not 0<=seek<duration:
            raise ValueError("ตำแหน่งเริ่มเล่นอยู่นอกช่วงเพลง")
        if os.name!="nt":
            raise ValueError("Windows MIDI Synthesizer ใช้งานได้เฉพาะบน Windows")
        with self.lock:
            prior=self.worker
            if self.stop_event is not None:self.stop_event.set()
        # MIDI Mapper devices may be exclusive; release the previous output
        # before opening the next one. Never join under the state lock.
        if prior is not None and prior.is_alive():
            prior.join(timeout=2.0)
            if prior.is_alive():
                raise ValueError("MIDI รุ่นก่อนยังหยุดไม่สำเร็จ ลองหยุดเล่นอีกครั้ง")
        with self.lock:
            self.events=events
            self.duration=duration
            self.song_id=song_id
            self.position=seek
            self.origin=time.monotonic()-seek
            self.status="playing"
            self.error=""
            stop_event=threading.Event()
            ready_event=threading.Event()
            self.stop_event=stop_event
            worker=threading.Thread(target=self._play_thread,
                                    args=(events,duration,seek,stop_event,ready_event),
                                    daemon=True,name="Plus-MIDI-Preview")
            self.worker=worker
            worker.start()
        # Do not say "playing" before Windows confirms that the MIDI output
        # exists and accepted a device handle.
        if not ready_event.wait(timeout=2.0):
            self.pause()
            raise ValueError("Windows MIDI Synthesizer ไม่ตอบสนอง ไม่สามารถทดสอบเสียงได้")
        with self.lock:
            if self.status=="error":
                raise ValueError(self.error or "Windows MIDI Synthesizer ไม่พร้อม")
            return self.state()

    def pause(self):
        with self.lock:
            if self.status=="playing":
                self.position=self._position_locked()
                self.status="paused"
                if self.stop_event:self.stop_event.set()
            return self.state()
