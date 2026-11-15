"""Safe, catalog-driven list of visible Song Bundles for Google Drive sync."""
from contextlib import closing
from pathlib import Path
import hashlib
import os
import sqlite3
from .duplicates import bundle
from .ingest import Inspector

EXCLUDED = ('deleted','moved','recycled','excluded','missing','invalid','manual_hidden')


def _source_roots(roots):
    roots = roots if isinstance(roots,(list,tuple)) else [roots] if roots else []
    result = []
    for item in roots:
        if not item: continue
        root = Path(item).resolve()
        if root.is_dir() and root not in result and not any(root.is_relative_to(p) for p in result):
            # If child was added before a parent, collapse it now.
            result = [p for p in result if not p.is_relative_to(root)]
            result.append(root)
    return result


def _safe_file(file):
    path = Path(file)
    if not path.is_file() or path.is_symlink() or any(
        parent.is_symlink() or getattr(parent,'is_junction',lambda:False)() for parent in path.parents):
        raise ValueError('ไฟล์ไม่พบหรือมีลิงก์ในเส้นทาง: '+str(path))
    return path.resolve()


def visible_song_plan(database, song_roots=None, *, search_query=None, progress=None):
    """Returns web-manifest song rows, source->relative target and skipped rows.

    SQLite uses the same visibility condition as SearchReader.  For a filtered
    subset, normalized search terms match the indexed search text or song key.
    No media file is modified, copied, opened for hashing, or uploaded here.
    """
    roots = _source_roots(song_roots)
    staged = {}
    songs = []
    skipped = []
    inspector = Inspector()  # directory listing cache is bounded and shared for this job
    with closing(sqlite3.connect(database)) as db:
        db.row_factory = sqlite3.Row
        sql = """SELECT id,code,title,artist,key_signature AS key,format,kind,playable,path,search
                 FROM songs WHERE duplicate_of=0
                   AND duplicate_state NOT IN (?,?,?,?,?,?,?)"""
        params = list(EXCLUDED)
        if search_query:
            from .library import normalize
            for token in normalize(search_query).split():
                sql += " AND (search LIKE ? ESCAPE '\\' OR key_signature LIKE ? ESCAPE '\\')"
                escaped = token.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
                params.extend(('%'+escaped+'%', '%'+escaped+'%'))
        sql += ' ORDER BY id'
        scanned = 0
        for record in db.execute(sql, params):
            scanned += 1
            if progress is not None and (scanned == 1 or scanned % 250 == 0):
                progress(scanned)
            song = dict(record)
            if not song['playable']:
                skipped.append((song['id'],'offline or unplayable'))
                continue
            try:
                _, parts = bundle(song['path'], inspector)
                # When the format is explicitly NCN, both sidecars are required.
                if 'ncn' in str(song.get('format') or song.get('kind') or '').lower() and (
                       'lyrics' not in parts or 'cursor' not in parts):
                    raise ValueError('NCN ไม่มี LYR/CUR ครบชุด')
                entries = {}
                for role, path in parts.items():
                    source = _safe_file(path)
                    dest = None
                    for i, root in enumerate(roots, 1):
                        if source.is_relative_to(root):
                            dest = ((f'Source{i:02d}/' if len(roots)>1 else '')+
                                    source.relative_to(root).as_posix())
                            break
                    if dest is None:
                        # Include visible songs outside configured roots, including
                        # NCN sidecars in sibling Lyrics/Cursor directories.
                        key = hashlib.sha256(str(source.parent).casefold().encode('utf-8')).hexdigest()[:16]
                        dest = 'External/' + key + '/' + source.name
                    # Avoid same destination referring to different bytes/paths.
                    owner = staged.get(dest)
                    if owner is not None and owner != source:
                        raise ValueError('ชื่อไฟล์ปลายทางชนกัน: '+dest)
                    staged[dest] = source
                    entries[role] = dest
            except (OSError, ValueError) as error:
                skipped.append((song['id'],str(error)))
                continue
            song['rel_path'] = entries['media']
            song['files'] = entries
            song['path'] = entries['media']  # no local paths leak to Drive.
            song.pop('search',None)
            song.pop('kind',None)
            songs.append(song)
    if progress is not None:
        progress(scanned)
    # Prevent orphaned upload for a rejected bundle.
    selected = {v for song in songs for v in song['files'].values()}
    staged = {dest: path for dest, path in staged.items() if dest in selected}
    return songs, staged, skipped
