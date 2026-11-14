"""Explicit GM-family soundfont overrides before the normal fallback stack."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from .dialog_layout import DialogWindow, ActionBar, scrollable_tree
GROUPS=[('piano','เปียโน',0,7),('chromatic','เครื่องเคาะมีระดับเสียง',8,15),('organ','ออร์แกน',16,23),('guitar','กีตาร์',24,31),('bass','เบส',32,39),('strings','เครื่องสาย',40,47),('ensemble','เครื่องสายหมู่/ประสานเสียง',48,55),('brass','เครื่องเป่าทองเหลือง',56,63),('reed','เครื่องเป่าลิ้น',64,71),('pipe','ขลุ่ย/เครื่องเป่าลม',72,79),('lead','ซินธ์นำ',80,87),('pad','ซินธ์พื้นหลัง',88,95),('synth_fx','ซินธ์เอฟเฟกต์',96,103),('ethnic','เครื่องดนตรีพื้นเมือง',104,111),('percussion','เพอร์คัสชัน',112,119),('sound_fx','เสียงประกอบ GM',120,127),('drums','ชุดกลอง Bank 128',0,127)]

def mapping_path(value):
    return value.get('path', '') if isinstance(value, dict) else value

def mapping_label(value):
    if not value:return 'ตามลำดับชุดเสียง'
    label=Path(mapping_path(value)).name
    if isinstance(value,dict):label+=f" • Bank {value['bank']} / Preset {value['preset']}"
    return label

def refresh_waiting_audio(app):
    decks = app.__dict__.get('_medley_decks')
    if decks: decks.discard()
    voice = app.__dict__.get('_keyboard_voice')
    if voice: voice.close()

def extended_entries(options, handles, mapping):
    from .soundfont import inspect_font
    # Validate paths using the legacy mapping contract first.
    font_entries(options, handles, mapping)
    names={str(Path(row['path']).resolve()).casefold():h for row,h in zip(options['fonts'],handles)}
    result=[]
    for key,label,first,last in GROUPS:
        value=mapping.get(key)
        if not value: continue
        path=mapping_path(value);handle=names[str(Path(path).resolve()).casefold()]
        bank=128 if key=='drums' else 0
        presets=inspect_font(path)['presets']
        if isinstance(value,dict):
            source=(value.get('bank'),value.get('preset'))
            if not presets or source not in [(b,p) for b,p,_ in presets]:
                raise ValueError('ไม่พบ Bank/Preset ที่เลือกใน '+Path(path).name)
            if any(type(v) is not int for v in source):raise ValueError('Bank/Preset ต้องเป็นจำนวนเต็ม')
            result.extend((handle,source[1],source[0],p,bank,0) for p in range(first,last+1))
        elif presets is not None:
            # Only map existing presets: missing GM instruments use the fallback stack.
            available={(b,p) for b,p,_ in presets}
            result.extend((handle,p,bank,p,bank,0) for p in range(first,last+1) if (bank,p) in available)
        else:
            result.extend((handle,p,bank,p,bank,0) for p in range(first,last+1))
    result.extend((h,-1,-1,-1,0,0) for h in handles)
    return result

def font_entries(options,handles,mapping):
    """Return (handle, program, bank); unknown/removed file mappings are rejected."""
    if not isinstance(mapping,dict):raise ValueError('การจับคู่ SoundFont ไม่ถูกต้อง')
    names={str(Path(row['path']).resolve()).casefold():handle for row,handle in zip(options['fonts'],handles)}
    result=[]
    for key,label,first,last in GROUPS:
        value=mapping.get(key)
        path=mapping_path(value)
        if not path:continue
        handle=names.get(str(Path(path).resolve()).casefold())
        if handle is None:raise ValueError('SoundFont สำหรับ '+label+' ไม่อยู่ในชุดที่โหลด กรุณาตั้งค่าการจับคู่ใหม่')
        result.extend((handle,p,128 if key=='drums' else 0) for p in range(first,last+1))
    result.extend((handle,-1,0) for handle in handles)
    return result

def retained_mapping(mapping,fonts):
    if not isinstance(mapping,dict):return {}
    paths={str(Path(row['path']).resolve()).casefold() for row in fonts}
    return {key:value for key,value in mapping.items() if mapping_path(value) and str(Path(mapping_path(value)).resolve()).casefold() in paths}


def apply_mapping(app, mapping, fonts):
    """Save validated assignments; keep the current song and overlapping tail intact."""
    extended_entries({'fonts': fonts}, range(len(fonts)), mapping)
    previous = app.settings.get('instrument_fonts', {})
    previous_follow = app.settings.get('soundfont_follow_song')
    app.settings['instrument_fonts'] = dict(mapping)
    app.settings['soundfont_follow_song'] = False
    try:
        app.save_settings()
    except Exception:
        app.settings['instrument_fonts'] = previous
        if previous_follow is None:app.settings.pop('soundfont_follow_song',None)
        else:app.settings['soundfont_follow_song']=previous_follow
        raise
    refresh_waiting_audio(app)


def mapping_window(app):
    from .soundfont import normalize_audio
    fonts=normalize_audio(app.settings)['fonts'];mapping=dict(app.settings.get('instrument_fonts',{}))
    win=DialogWindow(app);win.title('SoundFont แยกเครื่องดนตรี');win.geometry('780x660')
    ttk.Label(win.content,text='เลือกกลุ่มเครื่องดนตรี แล้วเลือกไฟล์เสียง',font=('Tahoma',14,'bold')).pack(anchor='w',padx=14,pady=12)
    table,tree=scrollable_tree(win.content,columns=('group','font'),show='headings',height=9,selectmode='browse')
    tree.heading('group',text='กลุ่ม GM');tree.heading('font',text='SoundFont');tree.column('group',width=240,minwidth=160);tree.column('font',width=370,minwidth=180)
    table.pack(fill='both',expand=True,padx=14)
    editor=ttk.LabelFrame(win.content,text='เสียงของกลุ่มที่เลือก',padding=12)
    editor.pack(fill='x',padx=14,pady=12)
    for key,label,first,last in GROUPS:tree.insert('','end',iid=key,values=(label,mapping_label(mapping.get(key))))
    choices=['ตามลำดับชุดเสียง']+[f'{i+1}. {Path(f["path"]).name}' for i,f in enumerate(fonts)]
    combo=ttk.Combobox(editor,values=choices,state='readonly',font=('Tahoma',12));combo.pack(fill='x',padx=14,pady=10);combo.current(0)
    preset_combo=ttk.Combobox(editor,state='readonly',font=('Tahoma',11))
    preset_combo.pack(fill='x',padx=14,pady=4)
    preset_rows=[]
    def load_presets(value=None):
        from .soundfont import inspect_font
        preset_rows.clear()
        try:
            if combo.current()>0:
                preset_rows.extend(inspect_font(fonts[combo.current()-1]['path'])['presets'] or [])
            preset_combo['values']=['ตามหมายเลข GM ที่มีจริง']+[f'Bank {b} / Preset {p} — {n}' for b,p,n in preset_rows]
            preset_combo.current(0)
            if isinstance(value,dict):
                for i,(b,p,n) in enumerate(preset_rows):
                    if (b,p)==(value.get('bank'),value.get('preset')):preset_combo.current(i+1);break
        except (ValueError,OSError) as error:
            preset_combo['values']=['อ่านรายการเสียงไม่ได้'];preset_combo.current(0);app.show_error(error)
    combo.bind('<<ComboboxSelected>>',lambda event:load_presets())
    load_presets()
    def selected(*unused):
        if tree.selection():
            value=mapping.get(tree.selection()[0]);combo.current(next((i+1 for i,f in enumerate(fonts) if f['path']==mapping_path(value)),0));load_presets(value)
    tree.bind('<<TreeviewSelect>>',selected)
    def assign():
        if not tree.selection():return
        key=tree.selection()[0];index=combo.current()
        if index>0:
            path=fonts[index-1]['path'];choice=preset_combo.current()
            mapping[key]=dict(path=path,bank=preset_rows[choice-1][0],preset=preset_rows[choice-1][1]) if choice>0 else path
        else:mapping.pop(key,None)
        tree.set(key,'font',mapping_label(mapping.get(key)))
    def save():
        try:
            assign()
            apply_mapping(app,mapping,fonts)
            app.status_var.set('บันทึกแล้ว • ใช้กับเพลงถัดไปและคีย์บอร์ดครั้งถัดไป');win.destroy()
        except (ValueError,OSError) as error:app.show_error(error)
    bar=ActionBar(win.footer);bar.pack(fill='x',padx=14,pady=8)
    ttk.Button(bar,text='ใช้กับกลุ่มที่เลือก',command=assign).pack(side='left');ttk.Button(bar,text='บันทึก',command=save).pack(side='right')
    ttk.Label(editor,text='เลือก Preset เฉพาะจะใช้เสียงเดียวกันทั้งกลุ่ม • แบบ GM ใช้เฉพาะหมายเลขที่มีจริง ที่ขาดใช้ชุดเสียงสำรอง • SFZ ไม่มีรายการ Preset',wraplength=640).pack(padx=14,pady=8)
    return win
