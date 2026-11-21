"""Optional Tk dialog for MIDI multi-output routing."""
import tkinter as tk
from tkinter import ttk, messagebox

from .audio_bus import performance_plan


def edit_multi_bus(parent, settings, save):
    current = settings.get('multi_bus', {})
    if not isinstance(current, dict):
        current = {}
    dialog = tk.Toplevel(parent)
    dialog.title('Multi-Out · MIDI Routing')
    dialog.transient(parent)
    dialog.resizable(False, False)
    frame = ttk.Frame(dialog, padding=18)
    frame.pack(fill='both', expand=True)
    enabled = tk.BooleanVar(value=current.get('enabled') is True)
    count = tk.StringVar(value=str(current.get('bus_count', 2)))
    ttk.Checkbutton(frame, text='เปิดใช้งาน Multi-Out (เพลงถัดไป)', variable=enabled).grid(
        row=0, column=0, columnspan=3, sticky='w', pady=(0, 8))
    ttk.Label(frame, text='จำนวนบัส').grid(row=1, column=0, sticky='w')
    ttk.Combobox(frame, textvariable=count, values=('2', '4', '8', '16'),
                 state='readonly', width=7).grid(row=1, column=1, sticky='w')
    ttk.Label(frame, text='MIDI Channel → Bus (0 คือบัสแรก)').grid(
        row=2, column=0, columnspan=3, sticky='w', pady=(12, 4))
    channels = current.get('channels', {})
    if not isinstance(channels, dict):
        channels = {}
    selectors = []
    for ch in range(16):
        row, col = 3 + ch % 8, (ch // 8) * 2
        ttk.Label(frame, text=f'CH {ch+1:02}').grid(row=row, column=col, sticky='w', padx=(0, 8))
        variable = tk.StringVar(value=str(channels.get(str(ch), 0)))
        ttk.Combobox(frame, textvariable=variable, values=tuple(str(n) for n in range(16)),
                     state='readonly', width=4).grid(row=row, column=col+1, padx=(0, 18))
        selectors.append(variable)
    ttk.Label(frame, text='บัส → BASS Device ID (ว่าง = ค่าเริ่มต้น)').grid(
        row=11, column=0, columnspan=3, sticky='w', pady=(12, 4))
    devices = current.get('devices', {})
    if not isinstance(devices, dict):
        devices = {}
    device_vars = []
    for bus in range(16):
        variable = tk.StringVar(value=str(devices.get(str(bus), '')))
        device_vars.append(variable)
    # Compact editor for active buses; all 16 values remain available on resize.
    device_frame = ttk.Frame(frame)
    device_frame.grid(row=12, column=0, columnspan=4, sticky='w')
    def redraw(*_):
        for child in device_frame.winfo_children():
            child.destroy()
        for bus in range(int(count.get())):
            ttk.Label(device_frame, text=f'Bus {bus}').grid(row=bus//4, column=(bus%4)*2)
            ttk.Entry(device_frame, textvariable=device_vars[bus], width=5).grid(
                row=bus//4, column=(bus%4)*2+1, padx=(4, 10))
    count.trace_add('write', redraw)
    redraw()

    def apply():
        try:
            n = int(count.get())
            mapping = {ch: int(var.get()) for ch, var in enumerate(selectors)}
            configured = {str(bus): int(var.get()) for bus, var in enumerate(device_vars[:n])
                          if var.get().strip()}
            plan = performance_plan(n, mapping)
            if any(type(device) is not int or device < 0 for device in configured.values()):
                raise ValueError('หมายเลขอุปกรณ์เสียงต้องไม่ติดลบ')
            old = settings.get('multi_bus', {})
            old = old if isinstance(old, dict) else {}
            updated = dict(old, enabled=enabled.get(), bus_count=plan.channels.bus_count,
                           channels={str(ch): bus for ch, bus in mapping.items()},
                           devices=configured)
            settings['multi_bus'] = updated
            try:
                save()
            except Exception:
                settings['multi_bus'] = old
                raise
        except (ValueError, OSError, TypeError) as exc:
            messagebox.showerror('Multi-Out', str(exc), parent=dialog)
            return
        dialog.destroy()

    ttk.Button(frame, text='บันทึก', command=apply).grid(row=13, column=2, sticky='e', pady=(16, 0))
    ttk.Button(frame, text='ยกเลิก', command=dialog.destroy).grid(row=13, column=3, sticky='e', pady=(16, 0))
    dialog.grab_set()
    return dialog
