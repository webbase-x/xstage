"""Configured song locations and explicit, cancellable Lister jobs."""
from pathlib import Path
from .library import scan_folder, canonical, MIDI_EXT, AUDIO_EXT, VIDEO_EXT, SearchCancelled

TYPES = {'ทุกประเภท': None, 'NCN / MIDI / KAR': MIDI_EXT - {'.emk'},
         'EMK': {'.emk'}, 'เพลงเสียง MP3 / WAV / WMA': AUDIO_EXT, 'วิดีโอ': VIDEO_EXT}

def locations(settings):
    result, seen = [], set()
    for entry in settings.get('song_folders', []):
        if not isinstance(entry, dict) or not isinstance(entry.get('path'), str):
            continue
        kind = entry.get('type', 'ทุกประเภท')
        if kind not in TYPES:
            kind = 'ทุกประเภท'
        path = canonical(Path(entry['path']))
        key = (path, kind)
        if key not in seen:
            result.append({'path': path, 'type': kind})
            seen.add(key)
    return result

def register_catalog_location(settings, path):
    """Remember a successful legacy import as an explicit scan location."""
    root={'path':str(path),'type':'ทุกประเภท'}
    roots=locations(settings)
    roots.append(root)
    settings['song_folders']=locations({'song_folders':roots})
    settings['legacy_root']=str(path)


def migrate_locations(settings):
    """Register older remembered catalogs once; later removal stays removed."""
    if settings.get('song_locations_migrated') is True:return False
    legacy=settings.get('legacy_root')
    if not locations(settings) and isinstance(legacy,str) and legacy.strip():
        register_catalog_location(settings,legacy)
    settings['song_locations_migrated']=True
    return True


def refresh_catalog(library,folder,cancelled=None,events=None,errors=None,force=False):
    from .legacy import catalog_location,import_catalog
    from .incremental import IncrementalIndex,READER_REVISION,encode
    dbf,_=catalog_location(folder)
    def stamp():
        stat=dbf.stat()
        return encode((stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns,READER_REVISION))
    before=stamp();source=str(dbf.resolve())
    with IncrementalIndex(library,events,cancelled) as index:
        previous=index.db.execute('SELECT stamp FROM catalogs WHERE path=?',(source,)).fetchone()
        if not force and previous and previous[0]==before:return False
        # The DBF supplies metadata; media inspection is performed by the counted plan.
        import_catalog(folder,library,cancelled=cancelled,errors=errors,events=events,
                       log_items=False,inspect_media=False)
        if not (cancelled and cancelled.is_set()) and stamp()==before:
            index.db.execute('INSERT OR REPLACE INTO catalogs VALUES (?,?)',(source,before))
    return True


def build_list(library, roots, progress=None, cancelled=None, events=None, force=False, protected=(), import_options=None):
    from .index_plan import SongPlan
    from .legacy import catalog_location
    try:
        if events:events(dict(type='phase',phase='สำรองฐานข้อมูล',total=None))
        library.backup_before_rebuild(cancelled)
    except SearchCancelled:
        return 0, 0, []
    with SongPlan() as plan:
        if events:events(dict(type='phase',phase='นับจำนวนเพลง',total=None))
        catalogs=[]
        for root in roots:
            if cancelled and cancelled.is_set():break
            folder=Path(root['path']);scan_root=folder
            if TYPES.get(root.get('type')) is None:
                try:
                    dbf,base=catalog_location(folder)
                    if str(dbf.resolve()) not in [str(item[0].resolve()) for item in catalogs]:catalogs.append((dbf,folder))
                    if (base/'Songs').is_dir():scan_root=base/'Songs'
                except ValueError:pass
            plan.folder(scan_root,TYPES.get(root.get('type')),cancelled,events)
        if force:
            with library.connect() as db:
                for row in db.execute("SELECT path FROM songs WHERE duplicate_state NOT IN ('moved','recycled','deleted','excluded')"):
                    if cancelled and cancelled.is_set():break
                    plan.add(row['path'])
        if cancelled and cancelled.is_set():return 0,plan.omitted,plan.errors
        if events:events(dict(type='progress',target=plan.count()))
        if import_options is not None:
            from .managed_import import catalog_hints,run_plan
            try:
                for _,folder in catalogs:catalog_hints(plan,folder,cancelled)
            except SearchCancelled:return 0,plan.omitted,plan.errors
            return run_plan(library,plan,cancelled,events,force=force,protected=protected,backup_done=True,**import_options)
        for _,folder in catalogs:refresh_catalog(library,folder,cancelled,events,plan.errors,force)
        return plan.run(library,cancelled,events,progress,force=force,protected=protected)
