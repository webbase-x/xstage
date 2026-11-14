"""Song EQ uses full normalized file paths, never titles or transient catalog IDs."""
import copy
import ntpath
from .graphic_eq import flat,validate

def key(song):
    if not song:return None
    path=dict(song).get('path')
    return ntpath.normcase(ntpath.normpath(str(path))) if path else None

def remembered(settings,song):
    values=settings.get('song_eq',{})
    value=values.get(key(song)) if isinstance(values,dict) else None
    if value is None:return None
    try:return validate(value)
    except (ValueError,KeyError,TypeError):return None

def selected(settings,song):
    value=remembered(settings,song)
    if value is not None:return value
    try:return validate(settings.get('graphic_eq',flat()))
    except (ValueError,KeyError,TypeError):return flat()

def store(settings,song,state):
    identity=key(song)
    if not identity:raise ValueError('กรุณาเล่นเพลงก่อนบันทึก EQ')
    if not isinstance(settings.get('song_eq'),dict):settings['song_eq']={}
    settings['song_eq'][identity]=copy.deepcopy(validate(state))

def forget(settings,song):
    values=settings.get('song_eq',{})
    if isinstance(values,dict):values.pop(key(song),None)

def relocate(settings,old_path,new_path,overwrite=False):
    old=key({'path':old_path});new=key({'path':new_path})
    values=settings.get('song_eq',{})
    if not isinstance(values,dict) or not new or old not in values:raise ValueError('ไม่พบค่าต้นทาง')
    if old==new:return
    if new in values and not overwrite:raise ValueError('เพลงปลายทางมี EQ อยู่แล้ว')
    state=validate(values[old]);values[new]=state;del values[old]

def relocate_batch(settings, mapping, overwrite=False):
    """Move per-song EQ keys atomically for a verified path mapping.

    Returns counts and never mutates settings until all collisions and keys are
    validated. ``mapping`` is an iterable of (old_path, new_path) pairs.
    """
    values=settings.get('song_eq',{})
    if not isinstance(values,dict):
        return {'moved':0,'missing':0,'skipped':0}
    pairs=[];seen_old=set();seen_new=set()
    for old_path,new_path in mapping:
        old,new=key({'path':old_path}),key({'path':new_path})
        if not old or not new: raise ValueError('เส้นทางเพลงไม่ถูกต้อง')
        if old in seen_old or new in seen_new: raise ValueError('รายการเส้นทางซ้ำในชุดย้าย')
        seen_old.add(old);seen_new.add(new);pairs.append((old,new))
    collisions=[new for old,new in pairs if new in values and new not in seen_old and not overwrite]
    if collisions: raise ValueError('มี EQ ปลายทางอยู่แล้ว '+str(len(collisions))+' รายการ')
    moved=0;missing=0;skipped=0;updates={}
    for old,new in pairs:
        if old not in values:
            missing+=1;continue
        updates[new]=copy.deepcopy(validate(values[old]));moved+=1
    for old,new in pairs:
        if old in values and old!=new: del values[old]
    values.update(updates)
    return {'moved':moved,'missing':missing,'skipped':skipped}