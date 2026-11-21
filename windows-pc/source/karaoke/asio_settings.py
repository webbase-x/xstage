"""ASIO driver preferences. Enumerating drivers never starts audio playback."""
import tkinter as tk
from tkinter import messagebox, ttk

from .asio_devices import discover_asio


def edit_asio_output(parent, settings, save, *, discover=discover_asio):
    current = settings.get('asio_output')
    current = current if isinstance(current, dict) else {}
    dialog = tk.Toplevel(parent)
    dialog.title('ASIO Output · ทดลองใช้')
    dialog.transient(parent)
    dialog.resizable(False, False)
    frame = ttk.Frame(dialog, padding=18)
    frame.pack(fill='both', expand=True)
    enabled = tk.BooleanVar(value=current.get('enabled') is True)
    device = tk.StringVar()
    channel = tk.StringVar(value=str(current.get('channel', 0)))
    limiter = tk.BooleanVar(value=current.get('limiter') is True)
    status = tk.StringVar(value='ยังไม่ได้ตรวจสอบไดรเวอร์')
    ttk.Checkbutton(frame, text='เปิด ASIO สำหรับเพลงถัดไป (ทดลองใช้)',
                    variable=enabled).grid(row=0, column=0, columnspan=2, sticky='w')
    ttk.Label(frame, text='ไดรเวอร์ ASIO').grid(row=1, column=0, sticky='w', pady=(12, 4))
    driver_box = ttk.Combobox(frame, textvariable=device, state='readonly', width=45)
    driver_box.grid(row=1, column=1, sticky='ew')
    ttk.Label(frame, text='ช่อง Output (คู่ Stereo)').grid(row=2, column=0, sticky='w', pady=(12, 4))
    ttk.Combobox(frame, textvariable=channel, values=tuple(str(i) for i in range(0, 32, 2)),
                 state='readonly', width=8).grid(row=2, column=1, sticky='w')
    ttk.Checkbutton(frame, text='Peak Limiter สำหรับ ASIO (ทดลองใช้)',
                    variable=limiter).grid(row=3, column=0, columnspan=2, sticky='w', pady=(10, 0))
    ttk.Label(frame, textvariable=status, wraplength=380).grid(
        row=4, column=0, columnspan=2, sticky='w', pady=(10, 0))
    ttk.Label(frame, text='หากเริ่ม ASIO ไม่สำเร็จ จะใช้ BASS แทน\n'
              'Multi-Out มีลำดับความสำคัญเหนือ ASIO ในรุ่นนี้',
              wraplength=380).grid(row=5, column=0, columnspan=2, sticky='w', pady=(8, 0))
    found = []
    def refresh():
        nonlocal found
        try:
            found = discover(parent.home / 'native' / 'x64')
            labels = [f'{entry.index} · {entry.name}' for entry in found]
            driver_box.configure(values=labels)
            preferred = current.get('device')
            selected = next((i for i, entry in enumerate(found) if entry.index == preferred), None)
            if selected is not None:
                driver_box.current(selected)
            elif found:
                driver_box.current(0)
            else:
                device.set('')
            status.set(f'พบไดรเวอร์ {len(found)} รายการ (ยังไม่ได้ทดสอบการเล่นเสียง)' if found
                       else 'ไม่พบไดรเวอร์ ASIO หรือ bassasio.dll')
        except Exception as exc:
            found = []
            device.set('')
            driver_box.configure(values=())
            status.set('ตรวจสอบไดรเวอร์ไม่สำเร็จ: ' + str(exc))
    ttk.Button(frame, text='ค้นหาไดรเวอร์อีกครั้ง', command=refresh).grid(
        row=6, column=0, columnspan=2, sticky='w', pady=(12, 0))
    def apply():
        old = settings.get('asio_output')
        try:
            if enabled.get():
                index = driver_box.current()
                if not 0 <= index < len(found):
                    raise ValueError('โปรดเลือกไดรเวอร์ ASIO ที่ตรวจพบ')
                selected_device = found[index].index
            else:
                selected_device = current.get('device')
            selected_channel = int(channel.get())
            if selected_channel < 0 or selected_channel % 2:
                raise ValueError('ช่อง Output ต้องเป็นเลขคู่')
            settings['asio_output'] = {'enabled': enabled.get(),
                                       'device': selected_device, 'channel': selected_channel,
                                       'limiter': limiter.get()}
            try:
                save()
            except Exception:
                if old is None:
                    settings.pop('asio_output', None)
                else:
                    settings['asio_output'] = old
                raise
        except (ValueError, OSError, TypeError) as exc:
            messagebox.showerror('ASIO Output', str(exc), parent=dialog)
            return
        dialog.destroy()
    ttk.Button(frame, text='บันทึก', command=apply).grid(row=7, column=0, pady=(16, 0))
    ttk.Button(frame, text='ยกเลิก', command=dialog.destroy).grid(row=7, column=1, sticky='e', pady=(16, 0))
    refresh()
    dialog.grab_set()
    return dialog
