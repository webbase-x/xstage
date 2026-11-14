"""Local SQLite song index. Imported media remains at its original location."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
import sqlite3
import threading
import unicodedata
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, asdict, replace
from pathlib import Path
from uuid import uuid4

MIDI_EXT = {".mid", ".midi", ".kar", ".emk"}
AUDIO_EXT = {".wav", ".mp3", ".wma"}
VIDEO_EXT = {".mp4", ".avi", ".mpg", ".mpeg", ".wmv", ".mkv", ".mov"}
SUPPORTED = MIDI_EXT | AUDIO_EXT | VIDEO_EXT


def song_supports_key(song):
    if not song:return False
    ext=Path(str(dict(song).get('path',''))).suffix.lower()
    if ext in MIDI_EXT:return True
    if ext in ('.wav','.mp3'):
        from .pcm_player import available
        return available()
    return False



def normalize(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def canonical(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def filename_info(path: Path):
    parts = [part.strip() for part in path.stem.split(" - ")]
    code, artist = "", ""
    if len(parts) >= 3:
        code, title, artist = parts[0], parts[1], " - ".join(parts[2:])
    elif len(parts) == 2:
        title, artist = parts
    else:
        title = parts[0]
    return code, title, artist


def search_rank(code, title, artist, query):
    """Rank title/code matches before artist and lyric-only matches."""
    code, title, artist = (normalize(str(value or '')).strip() for value in (code, title, artist))
    if code == query:
        return 0
    if title == query:
        return 1
    if query.isascii() and any(char.isdigit() for char in query) and code.startswith(query):
        return 2
    if title.startswith(query):
        return 3
    if query in title:
        return 4
    if all(token in title for token in query.split()):
        return 5
    if artist == query:
        return 6
    if query in artist:
        return 7
    return 8


class SearchCancelled(Exception):
    pass


class SearchReader:
    """One worker-owned, read-only SQLite connection with bounded ID caches."""
    def __init__(self, path, fts=None):
        self.db = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True, timeout=3)
        self.db.row_factory = sqlite3.Row
        self.db.create_function('xstage_rank', 4, search_rank, deterministic=True)
        self.db.execute('PRAGMA cache_size=-32768')
        self.db.execute('PRAGMA mmap_size=268435456')
        self.db.execute('PRAGMA temp_store=MEMORY')
        if fts is None:
            fts = self.db.execute("SELECT 1 FROM sqlite_master WHERE name='song_fts'").fetchone() is not None
        self.fts = fts
        self._version = None
        self._count = None
        self._cache = OrderedDict()

    def close(self):
        self.db.close()

    def interrupt(self):
        # sqlite3 explicitly permits interrupt from the UI thread.
        self.db.interrupt()

    def _check_version(self):
        version = self.db.execute('PRAGMA data_version').fetchone()[0]
        if version != self._version:
            self._version, self._count = version, None
            self._cache.clear()
        return version

    def count(self):
        self._check_version()
        if self._count is None:
            self._count = self.db.execute('SELECT count(*) FROM songs WHERE duplicate_of=0 AND duplicate_state NOT IN (\'deleted\',\'moved\',\'recycled\',\'invalid\',\'missing\',\'excluded\',\'manual_hidden\')').fetchone()[0]
        return self._count

    def warm_up(self):
        self.db.execute('SELECT code FROM songs ORDER BY code LIMIT 32').fetchall()
        self.db.execute('SELECT id FROM songs ORDER BY title COLLATE NOCASE,id LIMIT 32').fetchall()
        return self.count()

    def _exact_numeric_code_ids(self, query, limit, favorite, playable_only):
        """Use the existing B-tree index for a complete numeric song code.

        Never load the catalog into RAM.  Partial codes, text and unsupported
        codes retain the usual FTS/LIKE relevance search.
        """
        if len(query) < 4 or not query.isascii() or not query.isdecimal():
            return None
        where = ["code=?", "duplicate_of=0",
                 "duplicate_state NOT IN ('deleted','moved','recycled','invalid','missing','excluded','manual_hidden')"]
        if favorite:
            where.append("(favorite=1 OR EXISTS (SELECT 1 FROM songs d "
                         "WHERE d.duplicate_of=songs.id AND d.favorite=1))")
        if playable_only:
            where.append('playable=1')
        rows = self.db.execute('SELECT id FROM songs INDEXED BY songs_code WHERE '
                               + ' AND '.join(where) + ' ORDER BY id LIMIT ?',
                               (query, limit)).fetchall()
        return tuple(row[0] for row in rows) if rows else None

    def _title_prefix_ids(self, query, limit, favorite, playable_only):
        # The title index covers id/title. Rank its small header records first,
        # then fetch only a bounded candidate page to check playback flags.
        # If that page supplies a full result set, every substring/lyric match
        # has a lower rank and cannot enter the first page.
        if favorite or not query or not all('\u0e00' <= char <= '\u0e7f' for char in query):
            return None
        rows = self.db.execute('SELECT id FROM songs INDEXED BY songs_title '
            "WHERE duplicate_of=0 AND duplicate_state NOT IN (\'deleted\',\'moved\',\'recycled\',\'invalid\',\'missing\',\'excluded\',\'manual_hidden\') AND title LIKE ? ESCAPE '\\' ORDER BY CASE WHEN title=? COLLATE NOCASE THEN 0 ELSE 1 END,"
            'length(title),id LIMIT ?', (query+'%', query, limit*2+16)).fetchall()
        if len(rows) < limit:
            return None
        ids = [row[0] for row in rows]
        ids += [row[0] for row in self.db.execute('SELECT id FROM songs WHERE duplicate_of=0 AND duplicate_state NOT IN (\'deleted\',\'moved\',\'recycled\',\'invalid\',\'missing\',\'excluded\',\'manual_hidden\') AND code=?', (query,))]
        candidates = self.db.execute('SELECT * FROM songs WHERE id IN ('+','.join('?' for _ in ids)+')', ids)
        candidates = [dict(row) for row in candidates if not playable_only or row['playable']]
        if len(candidates) < limit:
            return None
        candidates.sort(key=lambda row: (search_rank(row['code'], row['title'], row['artist'], query),
                                          len(row['title']), row['id']))
        return tuple(row['id'] for row in candidates[:limit])

    def search(self, text='', favorite=False, limit=1000, playable_only=False, cancelled=None):
        cancelled = cancelled or (lambda: False)
        if cancelled():
            raise SearchCancelled()
        query = ' '.join(normalize(text).split())
        limit = max(0, min(5000, int(limit)))
        if not limit:
            return []
        key = query, bool(favorite), bool(playable_only), limit
        self.db.set_progress_handler(lambda: 1 if cancelled() else 0, 1000)
        try:
            self._check_version()
            ids = self._cache.get(key)
            if ids is None:
                ids = self._exact_numeric_code_ids(query, limit, favorite, playable_only)
                if ids is None:
                    ids = self._title_prefix_ids(query, limit, favorite, playable_only)
            if ids is None:
                tokens = query.split()
                where = ['duplicate_of=0 AND duplicate_state NOT IN (\'deleted\',\'moved\',\'recycled\',\'invalid\',\'missing\',\'excluded\',\'manual_hidden\')'] + (['(favorite=1 OR EXISTS (SELECT 1 FROM songs d WHERE d.duplicate_of=songs.id AND d.favorite=1))'] if favorite else [])
                if playable_only:
                    where.append('playable=1')
                values = []
                indexed = [token for token in tokens if len(token) >= 3] if self.fts else []
                if indexed:
                    where.append('id IN (SELECT rowid FROM song_fts WHERE song_fts MATCH ?)')
                    values.append(' AND '.join('"'+token.replace('"', '""')+'"' for token in indexed))
                for token in tokens:
                    if token not in indexed:
                        where.append("search LIKE ? ESCAPE '\\'")
                        escaped = token.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
                        values.append('%'+escaped+'%')
                statement = 'SELECT id FROM songs'+(' WHERE '+' AND '.join(where) if where else '')
                if tokens:
                    statement += ' ORDER BY xstage_rank(code,title,artist,?),length(title),id LIMIT ?'
                    values += [query, limit]
                else:
                    statement += ' ORDER BY title COLLATE NOCASE,id LIMIT ?'
                    values.append(limit)
                ids = tuple(row[0] for row in self.db.execute(statement, values))
            if key not in self._cache:
                if cancelled():
                    raise SearchCancelled()
                self._cache[key] = ids
                self._cache.move_to_end(key)
                while len(self._cache) > 48:
                    self._cache.popitem(last=False)
            else:
                self._cache.move_to_end(key)
            if not ids:
                return []
            rows = self.db.execute('SELECT * FROM songs WHERE id IN ('+','.join('?' for _ in ids)+')', ids)
            by_id = {row['id']: dict(row) for row in rows}
            favorites = self.db.execute('SELECT DISTINCT duplicate_of FROM songs WHERE favorite=1 AND duplicate_of IN ('+','.join('?' for _ in ids)+')', ids)
            for row in favorites:
                if row[0] in by_id:
                    by_id[row[0]]['favorite'] = 1
            if cancelled():
                raise SearchCancelled()
            return [by_id[song_id] for song_id in ids if song_id in by_id]
        except sqlite3.OperationalError as error:
            if cancelled() and 'interrupt' in str(error).lower():
                raise SearchCancelled() from error
            raise
        finally:
            self.db.set_progress_handler(None, 0)


class SongLibrary:
    def __init__(self, path: Path):
        self.path = path
        self.fts = False
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            fields = {row[1] for row in db.execute('PRAGMA table_info(songs)')}
            objects = {row[0] for row in db.execute('SELECT name FROM sqlite_master')}
            complete = {'id','path','code','title','artist','kind','search','favorite','format','playable',
                        'first_lyric','rhythm','key_signature','bpm','source_catalog','user_edited','duplicate_of','duplicate_state','duplicate_preferred'}
            expected = {'songs_code','songs_title','song_fts','songs_fts_insert','songs_fts_delete','songs_fts_update','songs_duplicate'}
            if complete <= fields and expected <= objects and db.execute('PRAGMA journal_mode').fetchone()[0] == 'wal':
                try:
                    db.execute('SELECT rowid FROM song_fts LIMIT 0')
                    self.fts = True
                except sqlite3.OperationalError:
                    pass
                return
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS songs (
                id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL,
                code TEXT NOT NULL, title TEXT NOT NULL, artist TEXT NOT NULL,
                kind TEXT NOT NULL, search TEXT NOT NULL,
                favorite INTEGER NOT NULL DEFAULT 0)""")
            fields = {row[1] for row in db.execute('PRAGMA table_info(songs)')}
            for name, declaration in {'format': "TEXT NOT NULL DEFAULT ''", 'playable': 'INTEGER NOT NULL DEFAULT 1',
                    'first_lyric': "TEXT NOT NULL DEFAULT ''", 'rhythm': "TEXT NOT NULL DEFAULT ''",
                    'key_signature': "TEXT NOT NULL DEFAULT ''", 'bpm': "TEXT NOT NULL DEFAULT ''",
                    'source_catalog': "TEXT NOT NULL DEFAULT ''", 'user_edited': 'INTEGER NOT NULL DEFAULT 0',
                    'duplicate_of': 'INTEGER NOT NULL DEFAULT 0', 'duplicate_state': "TEXT NOT NULL DEFAULT ''",
                    'duplicate_preferred': 'INTEGER NOT NULL DEFAULT 0'}.items():
                if name not in fields:
                    db.execute(f'ALTER TABLE songs ADD COLUMN {name} {declaration}')
            db.execute('CREATE INDEX IF NOT EXISTS songs_duplicate ON songs(duplicate_of)')
            db.execute('CREATE INDEX IF NOT EXISTS songs_code ON songs(code)')
            db.execute('CREATE INDEX IF NOT EXISTS songs_title ON songs(title COLLATE NOCASE, id)')
            try:
                existed = db.execute("SELECT 1 FROM sqlite_master WHERE name='song_fts'").fetchone()
                db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS song_fts USING fts5(search, content='songs', content_rowid='id', tokenize='trigram')")
                db.executescript("""
                    CREATE TRIGGER IF NOT EXISTS songs_fts_insert AFTER INSERT ON songs BEGIN
                      INSERT INTO song_fts(rowid,search) VALUES(new.id,new.search);
                    END;
                    CREATE TRIGGER IF NOT EXISTS songs_fts_delete AFTER DELETE ON songs BEGIN
                      INSERT INTO song_fts(song_fts,rowid,search) VALUES('delete',old.id,old.search);
                    END;
                    CREATE TRIGGER IF NOT EXISTS songs_fts_update AFTER UPDATE OF search ON songs
                    WHEN new.search <> old.search BEGIN
                      INSERT INTO song_fts(song_fts,rowid,search) VALUES('delete',old.id,old.search);
                      INSERT INTO song_fts(rowid,search) VALUES(new.id,new.search);
                    END;
                """)
                if not existed:
                    db.execute("INSERT INTO song_fts(song_fts) VALUES('rebuild')")
                self.fts = True
            except sqlite3.OperationalError:
                # An older system SQLite may omit FTS5/trigram. LIKE remains a
                # correct, asynchronous fallback rather than claiming support.
                self.fts = False

    def upsert_catalog(self, records, preserve_playable=False):
        with self.connect() as db:
            for song in records:
                song = dict(song)
                # Catalog paths must use the same resolved identity as Inspector
                # and SongPlan (notably Windows 8.3 aliases and long paths).
                song['path'] = canonical(Path(song['path']))
                song['search'] = normalize(' '.join(str(song.get(key, '')) for key in
                    ('code', 'title', 'artist', 'first_lyric', 'rhythm')))
                columns = ('path', 'code', 'title', 'artist', 'kind', 'search', 'format', 'playable',
                           'first_lyric', 'rhythm', 'key_signature', 'bpm', 'source_catalog')
                db.execute('INSERT INTO songs(' + ','.join(columns) + ') VALUES (' + ','.join('?' for _ in columns) + ') '
                    'ON CONFLICT(path) DO UPDATE SET ' + ','.join(key + '=' +
                        ('songs.playable' if key=='playable' and preserve_playable else f'CASE WHEN songs.user_edited=1 THEN songs.{key} ELSE excluded.{key} END' if key in ('code','title','artist','search') else 'excluded.'+key)
                        for key in columns if key != 'path'),
                    [song.get(key, '') for key in columns])
        return len(records)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=10000')
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def add_files(self, paths, inspector=None, errors=None, cancelled=None, inspected=None, events=None):
        from .ingest import Inspector
        inspector = inspector or Inspector()
        ids, records, rejected = [], [], []
        outcomes, final_records = [], {}
        # File I/O and MIDI parsing must not hold the SQLite write lock.
        for item in paths:
            if cancelled and cancelled.is_set():
                break
            if events:
                events(dict(type='progress',path=str(item)))
            try:
                record, warnings = inspector.inspect(item)
                records.append(record)
                if inspected:
                    outcomes.append((str(item),True,'; '.join(warnings)))
                if errors is not None:
                    for warning in warnings:
                        errors.append(f"คำเตือน: {item}: {warning}")
            except (OSError, ValueError, EOFError) as error:
                rejected.append(canonical(Path(item)))
                if inspected:
                    outcomes.append((str(item),False,str(error)))
                if errors is not None:
                    errors.append(f"ข้าม: {item}: {error}")
        with self.connect() as db:
            db.executemany('UPDATE songs SET playable=0 WHERE path=?', [(path,) for path in rejected])
            for record in records:
                rich = record.pop('_rich', set())
                old = db.execute('SELECT * FROM songs WHERE path=?', (record['path'],)).fetchone()
                if old and old['duplicate_state'] in ('deleted','recycled','moved','excluded'):
                    continue  # User/previous deletion tombstone needs explicit restoration.
                merged = dict(old) if old else {}
                for key, value in record.items():
                    if key.startswith('_'):continue
                    if old and key in ('title', 'artist', 'code') and old['user_edited']:
                        continue
                    # Re-scanning a plain MIDI must not erase catalog metadata.
                    if old and key in ('title','artist','code','first_lyric','key_signature','bpm'):
                        if old[key] and (key not in rich or (old['source_catalog'] and not record.get('_catalog_refresh'))):
                            continue
                    merged[key] = value
                merged['search'] = normalize(' '.join(str(merged.get(k, '')) for k in
                    ('code','title','artist','first_lyric','rhythm')))
                columns = ('path','code','title','artist','kind','search','format','playable',
                           'first_lyric','key_signature','bpm','rhythm','source_catalog')
                db.execute('INSERT INTO songs('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+') '
                    'ON CONFLICT(path) DO UPDATE SET '+','.join(k+'=excluded.'+k for k in columns if k != 'path'),
                    [merged.get(k, '') for k in columns])
                # Preserve an explicit manual hide on a simple metadata refresh.
                if not old or old['duplicate_state'] != 'manual_hidden':
                    db.execute("UPDATE songs SET duplicate_of=0,duplicate_state='' WHERE path=?", (record['path'],))
                ids.append(db.execute('SELECT id FROM songs WHERE path=?', (record['path'],)).fetchone()[0])
                final_records[record['path']]=merged
        if inspected:
            for path,ok,note in outcomes:
                final=final_records.get(canonical(Path(path)),{})
                inspected(dict(type='item',ok=ok,path=path,code=final.get('code',''),
                    title=final.get('title',Path(path).name),artist=final.get('artist',''),note=note))
        return ids

    def list_reindex_backups(self, include_legacy=False):
        """Newest-first rotating copies, optionally including the old fixed name."""
        prefix = self.path.stem + '-before-reindex-'
        copies = sorted(self.path.parent.glob(prefix + '*.sqlite3'), reverse=True)
        legacy = self.path.with_name(self.path.stem + '-before-reindex.sqlite3')
        if include_legacy and legacy.is_file():
            copies.append(legacy)
        return copies

    def backup_before_rebuild(self, cancelled=None, keep=5):
        """Checked, timestamped rotating SQLite snapshot; never overwrites old copy."""
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = self.path.with_name(
            self.path.stem + '-before-reindex-' + stamp + '-' + uuid4().hex[:8] + '.sqlite3')
        temp = backup.with_suffix('.tmp')
        def step(status, remaining, total):
            if cancelled and cancelled.is_set():
                raise SearchCancelled()
        try:
            with self.connect() as source:
                target = sqlite3.connect(temp)
                try:
                    source.backup(target, pages=256, progress=step)
                    check = target.execute('PRAGMA quick_check').fetchone()
                    if not check or check[0] != 'ok':
                        raise sqlite3.DatabaseError('ตรวจสำเนาฐานเพลงไม่ผ่าน')
                finally:
                    target.close()
            temp.replace(backup)
            # Compatibility with earlier installers/tests: keep the historic
            # fixed-name copy if absent, but NEVER overwrite an existing one.
            legacy = self.path.with_name(self.path.stem + '-before-reindex.sqlite3')
            if not legacy.exists():
                try:
                    os.link(backup, legacy)
                except FileExistsError:
                    pass
                except OSError:
                    # FAT/network shares may not permit hard links. This fallback
                    # is an extra one-time copy, not an overwrite of old backups.
                    from shutil import copyfile
                    legacy_temp = legacy.with_name(legacy.name + '-' + uuid4().hex + '.tmp')
                    try:
                        copyfile(backup, legacy_temp)
                        if not legacy.exists():
                            legacy_temp.replace(legacy)
                    finally:
                        legacy_temp.unlink(missing_ok=True)
            # Never prune old copies until the newest was safely written.
            for older in self.list_reindex_backups()[max(1, keep):]:
                older.unlink(missing_ok=True)
            return backup
        finally:
            temp.unlink(missing_ok=True)

    def restore_reindex_backup(self, backup):
        """Explicit offline restore; call only after the application has closed.

        A fresh safety snapshot is made before the replacement. Check the
        chosen SQLite backup first; never accept an arbitrary external file.
        """
        backup = Path(backup).resolve()
        if backup not in [item.resolve() for item in self.list_reindex_backups(include_legacy=True)]:
            raise ValueError('สำเนาไม่อยู่ในชุดสำรองที่โปรแกรมสร้าง')
        source = sqlite3.connect(backup.resolve().as_uri()+'?mode=ro', uri=True, timeout=10)
        try:
            if source.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise sqlite3.DatabaseError('สำเนาฐานข้อมูลเสียหาย')
            if not source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='songs'").fetchone():
                raise ValueError('ไฟล์สำรองไม่ใช่ฐานเพลง')
            safety = self.backup_before_rebuild(keep=max(5, len(self.list_reindex_backups()) + 1))
            try:
                target = sqlite3.connect(self.path, timeout=10)
                try:
                    source.backup(target, pages=256)
                    if target.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                        raise sqlite3.DatabaseError('กู้คืนฐานเพลงไม่สมบูรณ์')
                finally:
                    target.close()
            except BaseException as error:
                raise RuntimeError(f'กู้คืนไม่สำเร็จ ตรวจสำเนาฉุกเฉิน {safety}: {error}') from error
            # A restored database must never trust metadata/fingerprints
            # calculated against a newer catalog version.
            for cache_name in ('-fast-catalog-cache.sqlite3', '-index-cache.sqlite3'):
                cache = self.path.with_name(self.path.stem + cache_name)
                for stale in (cache, Path(str(cache) + '-wal'), Path(str(cache) + '-shm')):
                    stale.unlink(missing_ok=True)
            return safety
        finally:
            source.close()

    def rebuild(self, progress=None, cancelled=None, events=None, force=True, protected=(), enforce_policy=False):
        """Count a stable snapshot, retain IDs and process bounded batches."""
        from .index_plan import SongPlan
        try:
            if events:events(dict(type='phase',phase='สำรองฐานข้อมูล',total=None))
            self.backup_before_rebuild(cancelled)
        except SearchCancelled:
            return 0, 0, []
        with SongPlan() as plan:
            if events:events(dict(type='phase',phase='นับรายการเดิม',total=None))
            with self.connect() as db:
                for row in db.execute("SELECT path FROM songs WHERE duplicate_state NOT IN ('moved','recycled','deleted','excluded','missing')"):
                    if cancelled and cancelled.is_set():break
                    plan.add(row['path'])
                    if events and plan.count()%1000==0:events(dict(type='progress',done=plan.count(),total=None))
            if enforce_policy:
                from .managed_import import run_plan
                return run_plan(self,plan,cancelled,events,force=force,protected=protected,backup_done=True,songs_root=self.path.parent.parent/'Songs',strict=True)
            return plan.run(self,cancelled,events,progress,force=force,protected=protected)

    def search(self, text="", favorite=False, limit=1000, playable_only=False):
        reader = self.open_reader()
        try:
            return reader.search(text, favorite, limit, playable_only)
        finally:
            reader.close()

    def open_reader(self):
        return SearchReader(self.path, self.fts)

    def has_songs(self):
        with self.connect() as db:
            return db.execute('SELECT 1 FROM songs LIMIT 1').fetchone() is not None

    @staticmethod
    def _active_alias(db, song_id):
        row = db.execute('SELECT duplicate_state FROM songs WHERE id=?', (song_id,)).fetchone()
        if not row or row[0] != 'missing':
            return None
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='catalog_song_alias'").fetchone():
            return None
        alias = db.execute('SELECT new_id FROM catalog_song_alias WHERE old_id=?', (song_id,)).fetchone()
        if not alias:
            return None
        target = db.execute("SELECT id FROM songs WHERE id=? AND duplicate_state NOT IN ('missing','deleted','invalid','recycled','moved','excluded')", (alias[0],)).fetchone()
        return target[0] if target else None

    def get(self, song_id):
        with self.connect() as db:
            alias = self._active_alias(db, song_id)
            row = db.execute('SELECT * FROM songs WHERE id=?', (alias or song_id,)).fetchone()
            return dict(row) if row else None

    def count(self):
        with self.connect() as db:
            return db.execute("SELECT count(*) FROM songs WHERE duplicate_of=0 AND duplicate_state NOT IN (\'deleted\',\'moved\',\'recycled\',\'invalid\',\'missing\',\'excluded\',\'manual_hidden\')").fetchone()[0]

    def favorite(self, song_id):
        with self.connect() as db:
            alias = self._active_alias(db, song_id)
            effective = alias or song_id
            row = db.execute('SELECT duplicate_of FROM songs WHERE id=?', (effective,)).fetchone()
            if row is None:
                return
            keeper = row[0] or effective
            marked = db.execute('SELECT max(favorite) FROM songs WHERE id=? OR duplicate_of=?', (keeper, keeper)).fetchone()[0]
            db.execute('UPDATE songs SET favorite=? WHERE id=? OR duplicate_of=? OR id=?',
                       (0 if marked else 1, keeper, keeper, song_id))

    def edit(self, song_id, code, title, artist, key_signature=None):
        if key_signature is not None:
            if not title.strip() or not artist.strip():raise ValueError('ต้องระบุชื่อเพลงและนักร้อง')
            from .name_duplicates import musical_key
            if musical_key(key_signature) is None:raise ValueError('คีย์เพลงไม่ถูกต้อง เช่น C, Am, F#')
        with self.connect() as db:
            alias = self._active_alias(db, song_id)
            ids = (song_id, alias) if alias else (song_id,)
            for sid in ids:
                db.execute("UPDATE songs SET user_edited=1,code=?,title=?,artist=?,search=? WHERE id=?",
                           (code,title,artist,normalize(f"{code} {title} {artist}"),sid))
                if key_signature is not None:
                    db.execute('UPDATE songs SET key_signature=? WHERE id=?',(key_signature.strip(),sid))


def scan_folder(folder: Path, library: SongLibrary, progress=None, cancelled=None, extensions=None, events=None, force=False, protected=()):
    from .index_plan import SongPlan
    from .legacy import catalog_location, import_catalog
    with SongPlan() as plan:
        if events:events(dict(type='phase',phase='นับจำนวนเพลง',total=None))
        plan.folder(folder,extensions,cancelled,events)
        if cancelled and cancelled.is_set():return 0,plan.omitted,plan.errors
        if extensions is None:
            try:catalog_location(folder)
            except ValueError:pass
            else:
                from .lister import refresh_catalog
                refresh_catalog(library,folder,cancelled,events,plan.errors,force)
        return plan.run(library,cancelled,events,progress,force=force,protected=protected)


_JSON_ERROR_BACKUPS = OrderedDict()
_JSON_ERROR_BACKUPS_LOCK = threading.RLock()


def _json_file_digest(path):
    import hashlib
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


class JsonRecoveryError(OSError):
    """Existing data needs operator recovery, never silent defaults."""
    def __init__(self, path, reason, backup=None):
        self.path = Path(path)
        self.backup = backup
        message = f"อ่านข้อมูลไม่ได้: {self.path}\n{reason}\nไฟล์เดิมยังอยู่"
        if backup is not None:
            message += f"\nสำเนา: {backup}"
        super().__init__(message)


def preserve_json(path):
    import shutil
    import uuid
    path = Path(path)
    backup = path.with_name(path.name + '.corrupt-' + uuid.uuid4().hex + '.bak')
    with path.open('rb') as source, backup.open('xb') as output:
        shutil.copyfileobj(source, output)
        output.flush()
        os.fsync(output.fileno())
    return backup


def json_recovery_error(path, reason):
    path = Path(path)
    try:
        digest = _json_file_digest(path)
        key = (canonical(path), digest)
        with _JSON_ERROR_BACKUPS_LOCK:
            backup = _JSON_ERROR_BACKUPS.get(key)
            if backup is not None:
                try:
                    if _json_file_digest(backup) == digest:
                        _JSON_ERROR_BACKUPS.move_to_end(key)
                        return JsonRecoveryError(path, reason, backup)
                except OSError:
                    pass
            backup = preserve_json(path)
            if _json_file_digest(backup) == digest:
                _JSON_ERROR_BACKUPS[key] = backup
                _JSON_ERROR_BACKUPS.move_to_end(key)
                while len(_JSON_ERROR_BACKUPS) > 128:
                    _JSON_ERROR_BACKUPS.popitem(last=False)
    except OSError as error:
        return JsonRecoveryError(path, f"{reason}; สำรองไม่สำเร็จ: {error}")
    return JsonRecoveryError(path, reason, backup)


def parse_json(text):
    def invalid(value):
        raise ValueError(f"JSON มีตัวเลขที่ไม่ถูกต้อง: {value}")
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('JSON มีคีย์ซ้ำ จึงไม่เลือกทับค่าเดิม')
            value[key] = item
        return value
    def number(text):
        import math
        value=float(text)
        if not math.isfinite(value):raise ValueError('JSON มีตัวเลขเกินช่วงที่รองรับ')
        return value
    return json.loads(text, parse_constant=invalid, parse_float=number, object_pairs_hook=unique)


JSON_UNSET = object()


class JsonConflictError(OSError):
    pass


class PlaylistImportError(OSError):
    def __init__(self,indexed_count,stage,reason):
        self.indexed_count=indexed_count
        self.stage=stage
        self.queue_saved=False
        super().__init__(f'นำเข้าคิวไม่สำเร็จ ({stage}) • ตรวจ/เพิ่มดัชนีสำเร็จก่อนเกิดข้อผิดพลาด {indexed_count} รายการ\n'
                         f'คิวเดิมคงอยู่ ดัชนีที่เพิ่มแล้วอาจยังอยู่ในคลัง\n{reason}')


def file_revision(path):
    try:return _json_file_digest(path)
    except FileNotFoundError:return None


def read_json_snapshot(path: Path, default):
    import hashlib
    path=Path(path)
    try:
        raw=path.read_bytes()
        text=raw.decode('utf-8')
    except FileNotFoundError:
        if path.is_symlink():raise JsonRecoveryError(path,'ลิงก์ไฟล์ไม่สามารถอ่านได้')
        return default,None
    except UnicodeError as error:raise json_recovery_error(path,'รูปแบบข้อความไม่ใช่ UTF-8') from error
    except OSError as error:raise JsonRecoveryError(path,str(error)) from error
    try:
        value=parse_json(text)
        if isinstance(default,(dict,list)) and not isinstance(value,type(default)):
            raise ValueError('ชนิดข้อมูลหลักใน JSON ไม่ถูกต้อง')
        if path.name=='settings.json':
            from .settings_schema import validate_settings
            validate_settings(value)
        return value,hashlib.sha256(raw).hexdigest()
    except ValueError as error:raise json_recovery_error(path,str(error)) from error


def read_json(path: Path, default):
    return read_json_snapshot(path,default)[0]


def write_json(path: Path, value, *, expected_revision=JSON_UNSET):
    import tempfile
    import hashlib
    path=Path(path)
    if path.name=='settings.json':
        from .settings_schema import validate_settings
        validate_settings(value)
    payload=json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8')
    _,revision=read_json_snapshot(path,{} if path.name=='settings.json' else None)
    if expected_revision is not JSON_UNSET and revision!=expected_revision:
        raise JsonConflictError(f'ไฟล์ {path.name} เปลี่ยนจากตอนที่โหลดไว้ จึงไม่เขียนทับ กรุณาเปิดใหม่เพื่อโหลดข้อมูลล่าสุด')
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=None
    try:
        with tempfile.NamedTemporaryFile(mode='wb',dir=path.parent,prefix=path.name+'.',suffix='.tmp',delete=False) as output:
            temp=Path(output.name);output.write(payload);output.flush();os.fsync(output.fileno())
        if file_revision(path)!=revision:
            raise JsonConflictError(f'ไฟล์ {path.name} เปลี่ยนระหว่างบันทึก จึงไม่เขียนทับ กรุณาโหลดข้อมูลล่าสุด')
        temp.replace(path)
        return hashlib.sha256(payload).hexdigest()
    finally:
        if temp is not None:temp.unlink(missing_ok=True)


@dataclass
class QueueItem:
    song_id: int
    singer: str = ""
    key: int = 0
    speed: int = 100
    request_id: str = ""
    medley_session: str = ""

    @classmethod
    def from_dict(cls, value):
        return cls(int(value["song_id"]), str(value.get("singer", ""))[:100],
                   max(-12, min(12, int(value.get("key", 0)))),
                   max(50, min(150, int(value.get("speed", 100)))),
                   str(value.get("request_id", ""))[:100],
                   str(value.get("medley_session", ""))[:100])


def validate_queue(raw):
    if not isinstance(raw, list):
        raise ValueError('คิวต้องเป็นรายการ JSON')
    items = []
    for index, value in enumerate(raw, 1):
        if not isinstance(value, dict):
            raise ValueError(f'คิวรายการที่ {index} ต้องเป็น object')
        song_id = value.get('song_id')
        if type(song_id) is not int or song_id < 1:
            raise ValueError(f'คิวรายการที่ {index}: song_id ต้องเป็นจำนวนเต็มบวก')
        for key, minimum, maximum, default in (('key', -12, 12, 0), ('speed', 50, 150, 100)):
            number = value.get(key, default)
            if type(number) is not int or not minimum <= number <= maximum:
                raise ValueError(f'คิวรายการที่ {index}: {key} ไม่อยู่ในช่วงที่รองรับ')
        for key in ('singer', 'request_id', 'medley_session'):
            text = value.get(key, '')
            if not isinstance(text, str) or len(text) > 100:
                raise ValueError(f'คิวรายการที่ {index}: {key} ไม่ถูกต้อง')
        items.append(QueueItem.from_dict(value))
    return items


class SongQueue:
    def __init__(self, path: Path):
        self.path = Path(path)
        raw, self._revision = read_json_snapshot(self.path, [])
        try:
            self.items = validate_queue(raw)
        except ValueError as error:
            raise json_recovery_error(self.path, str(error)) from error

    def save(self):
        # Detect external damage too, before replacing any existing entries.
        old = read_json(self.path, [])
        try:
            validate_queue(old)
        except ValueError as error:
            raise json_recovery_error(self.path, str(error)) from error
        payload = [asdict(item) for item in self.items]
        validate_queue(payload)
        self._revision = write_json(self.path, payload, expected_revision=getattr(self,'_revision',JSON_UNSET))

    def _commit(self, pending):
        if getattr(self,"_maintenance_locked",False):raise OSError("กำลังลบเพลงตามรายงาน กรุณารอให้งานเสร็จก่อนแก้คิว")
        old = self.items
        self.items = pending
        try:
            self.save()
        except Exception:
            self.items = old
            raise

    def add(self, item):
        self._commit(self.items + [item])

    def add_medley(self, items, play_next=False):
        session = uuid4().hex
        batch = [replace(item, request_id='', medley_session=session) for item in items]
        if batch:
            self._commit(batch + self.items if play_next else self.items + batch)
        return len(batch)

    def cancel_medley(self, session):
        if not session:
            return 0
        pending = [item for item in self.items if item.medley_session != session]
        count = len(self.items) - len(pending)
        if count:
            self._commit(pending)
        return count

    def insert(self, index, item):
        if not 0 <= index <= len(self.items):
            raise ValueError('ตำแหน่งคิวไม่ถูกต้อง')
        pending = list(self.items)
        pending.insert(index, item)
        self._commit(pending)

    def pop(self, index=0):
        pending = list(self.items)
        item = pending.pop(index)
        self._commit(pending)
        return item

    def move(self, index, step):
        target = index + step
        if 0 <= index < len(self.items) and 0 <= target < len(self.items):
            pending = list(self.items)
            pending[index], pending[target] = pending[target], pending[index]
            self._commit(pending)
            return target
        return index

    def export(self, path, library):
        tracks = []
        for item in self.items:
            song = library.get(item.song_id)
            if song:
                track = asdict(item)
                track.pop('medley_session')
                tracks.append({**track, "path": song["path"], "title": song["title"]})
        write_json(Path(path), {"format": "xstage.playlist", "version": 1, "tracks": tracks})

    def import_file(self, path, library, errors=None, enforce_policy=False, prepare_only=False, cancelled=None, events=None):
        if Path(path).stat().st_size>64*1024*1024:raise ValueError('ไฟล์คิวใหญ่เกินขอบเขต 64 MB')
        data = parse_json(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("format") not in ("xstage.playlist", "newKaraoke.playlist") or not isinstance(data.get("tracks"), list):
            raise ValueError("ไม่ใช่ไฟล์คิวเพลง X-Stage Karaoke")
        version = data.get('version', 1)
        if type(version) is not int or version != 1:
            raise ValueError('ไม่รองรับรุ่นไฟล์คิวนี้')
        # Validate the entire document before any library/index mutation.
        validated = []
        for index, value in enumerate(data['tracks'], 1):
            if not isinstance(value, dict) or not isinstance(value.get('path'), str) or not value['path'].strip() or '\x00' in value['path']:
                raise ValueError(f'ข้อมูลตำแหน่งเพลงรายการที่ {index} ไม่ถูกต้อง')
            try:
                item = QueueItem.from_dict({**value, 'song_id': 0, 'medley_session': ''})
            except (KeyError, TypeError, ValueError, OverflowError) as error:
                raise ValueError(f'ข้อมูลคิวรายการที่ {index} ไม่ถูกต้อง') from error
            validated.append((Path(value['path']), item))
        missing = 0
        pending = []
        try:
            if enforce_policy:
                from .managed_import import ImportSession
                library.backup_before_rebuild(cancelled)
                with ImportSession(library,library.path.parent.parent/'Songs',strict=True,cancelled=cancelled,events=events) as session:
                    session.prepare()
                    for song_path,item in validated:
                        if cancelled and cancelled.is_set():break
                        try:
                            row,_=session.import_one(song_path);item.song_id=row['id'];pending.append(item)
                        except SearchCancelled:break
                        except (OSError,ValueError) as error:
                            missing+=1
                            if errors is not None:errors.append(str(song_path)+': '+str(error))
                validated=[]
            for song_path,item in validated:
                ids=library.add_files([song_path],errors=errors)
                if ids:item.song_id=ids[0];pending.append(item)
                else:missing+=1
        except SearchCancelled:return ([],missing) if prepare_only else (0,missing)
        except (OSError,ValueError,sqlite3.Error) as error:
            raise PlaylistImportError(len(pending),'ตรวจ/เพิ่มดัชนี',str(error)) from error
        if prepare_only:return pending,missing
        try:self._commit(self.items+pending)
        except (OSError,ValueError) as error:
            raise PlaylistImportError(len(pending),'บันทึกคิว',str(error)) from error
        return len(pending),missing
