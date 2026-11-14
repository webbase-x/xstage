"""Safe batch relocation for catalog roots that moved or changed drive letters."""
from pathlib import Path
import sqlite3
from contextlib import closing
from .library import canonical

def remap_path_settings(settings, mapping):
    """Move path-keyed settings without losing offsets, lyrics, or EQ."""
    for field in ('offsets','lyric_files','song_eq'):
        values=settings.get(field)
        if not isinstance(values,dict):continue
        updates={}
        for path,value in list(values.items()):
            normalized=canonical(Path(path))
            target=mapping.get(normalized)
            if target is not None:updates[target]=value
        collisions=set(updates).intersection(values)
        if collisions:raise ValueError(f'พบข้อมูลปลายทางซ้ำใน {field}: {len(collisions)} รายการ')
        for path in list(values):
            if mapping.get(canonical(Path(path))) is not None:del values[path]
        values.update(updates)
    return settings


def preview(library_path, old_root, new_root):
    old=canonical(Path(old_root)); new=canonical(Path(new_root))
    if not old or not new: raise ValueError('ต้องระบุโฟลเดอร์ต้นทางและปลายทาง')
    rows=[]
    with closing(sqlite3.connect(library_path, timeout=10)) as db:
        db.row_factory=sqlite3.Row
        for row in db.execute("SELECT id,path FROM songs WHERE duplicate_state NOT IN ('moved','recycled','deleted')"):
            path=canonical(Path(row['path']))
            try: relative=Path(path).relative_to(old)
            except ValueError: continue
            target=canonical(new/relative)
            rows.append({'id':row['id'],'old':path,'new':target,'exists':Path(target).is_file()})
    return rows


def apply(library_path, old_root, new_root):
    """Atomically update catalog paths; refuses collisions and leaves files untouched."""
    old=canonical(Path(old_root));new=canonical(Path(new_root))
    rows=preview(library_path,old,new)
    old_paths={item['old'] for item in rows}; new_paths=[item['new'] for item in rows]
    if len(new_paths)!=len(set(new_paths)): raise ValueError('ปลายทางซ้ำกันในคลังเพลง')
    with closing(sqlite3.connect(library_path, timeout=10)) as db:
        db.execute('PRAGMA busy_timeout=10000'); db.execute('PRAGMA foreign_keys=ON')
        has_source_catalog=bool(db.execute('PRAGMA table_info(songs)').fetchall() and any(row[1]=='source_catalog' for row in db.execute('PRAGMA table_info(songs)')))
        for item in rows:
            existing=db.execute('SELECT id FROM songs WHERE path=?',(item['new'],)).fetchone()
            if existing and item['new'] not in old_paths: raise ValueError('ปลายทางมีรายการอยู่แล้ว: '+item['new'])
        db.execute('BEGIN IMMEDIATE')
        for item in rows:
            if has_source_catalog:
                source=db.execute('SELECT source_catalog FROM songs WHERE id=?',(item['id'],)).fetchone()[0]
                updated_source=source
                if source:
                    try:updated_source=canonical(Path(new)/Path(canonical(Path(source))).relative_to(old))
                    except ValueError:pass
                db.execute('UPDATE songs SET path=?, source_catalog=? WHERE id=?',(item['new'],updated_source,item['id']))
            else:
                db.execute('UPDATE songs SET path=? WHERE id=?',(item['new'],item['id']))
        db.commit()
    cache_path=Path(library_path).with_name(Path(library_path).stem+'-index-cache.sqlite3')
    if cache_path.is_file():
        with closing(sqlite3.connect(cache_path, timeout=10)) as cache:
            cache.execute('PRAGMA busy_timeout=10000')
            cache.execute('BEGIN IMMEDIATE')
            for (cache_path_value,) in cache.execute('SELECT path FROM files').fetchall():
                try:cache_new=canonical(Path(new)/Path(canonical(Path(cache_path_value))).relative_to(old))
                except ValueError:continue
                cache.execute('UPDATE files SET path=? WHERE path=?',(cache_new,cache_path_value))
            catalog_paths=cache.execute('SELECT path FROM catalogs').fetchall()
            for (catalog_path,) in catalog_paths:
                try:catalog_new=canonical(Path(new)/Path(canonical(Path(catalog_path))).relative_to(old))
                except ValueError:continue
                cache.execute('UPDATE catalogs SET path=? WHERE path=?',(catalog_new,catalog_path))
            cache.commit()
    return {'updated':len(rows),'missing':sum(not item['exists'] for item in rows),'preview':rows}
