"""v0.9.38 regression: remote lifecycle, durable history, backups and sampling."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import json
import random
import sqlite3
from contextlib import closing
import unittest

from karaoke.library import SongLibrary, QueueItem, write_json
from karaoke.remote_requests import RequestBook
from karaoke.remote import RemoteServer
from karaoke.play_stats import sync_recent, history_hits, validate_stats
from karaoke.performance_features import PlayHistory
from karaoke.cloud_sync import create_snapshot, validate_snapshot
from karaoke.restore import stage_restore, apply_pending
from karaoke.random_medley import build_preview

class RemoteLifecycleTests(unittest.TestCase):
    def test_foreground_poll_refreshes_presence_without_permanent_idle_session(self):
        with TemporaryDirectory() as d:
            lib = SimpleNamespace(search=lambda *_a, **_k: [])
            remote = RemoteServer(lib, lambda x: {}, lambda: {}, '127.0.0.1', 0)
            try:
                remote.sessions['token'] = dict(active=100., seen=100., role='guest')
                with patch('karaoke.remote.time.monotonic', return_value=410.):
                    remote.expire_sessions()
                self.assertNotIn('token', remote.sessions)
                remote.sessions['token'] = dict(active=100., seen=399., role='guest')
                with patch('karaoke.remote.time.monotonic', return_value=410.):
                    remote.expire_sessions()
                self.assertIn('token', remote.sessions)
                # Polling stops; it must eventually expire even if initially read-only.
                with patch('karaoke.remote.time.monotonic', return_value=800.):
                    remote.expire_sessions()
                self.assertNotIn('token', remote.sessions)
            finally:
                remote.server.server_close()
                remote.audio.close()

    def test_ended_requests_pruned_active_preserved_and_retry_idempotent(self):
        book = RequestBook()
        for i in range(5000):
            book.records[f'old{i}'] = dict(owner='one', status='ended', position=None)
        book.records['important'] = dict(owner='one', status='queued', position=1)
        app = SimpleNamespace(song_queue=SimpleNamespace(items=[]), current_item=None,
                              refresh_queue=lambda: None, library=SimpleNamespace())
        book.sync(app)
        self.assertIn('important', book.records)
        self.assertLessEqual(len(book.records), 3500)
        self.assertEqual(book.command(app, {'action':'queue','request_id':'old0', '_owner':'one'},
                         {'accepting':True, 'limit':3}),
                         {'ok':True,'duplicate':True,'request_id':'old0'})
        with self.assertRaises(ValueError):
            book.command(app, {'action':'queue','request_id':'old0', '_owner':'attacker'},
                         {'accepting':True, 'limit':3})

class DurablePlayStatsTests(unittest.TestCase):
    def row(self, i, status='completed'):
        return dict(time=(datetime.now(timezone.utc)-timedelta(days=(i%100)+0.5)).isoformat(),
                    title='Song', artist='Singer', path='C:/media/song.mid',
                    item={'song_id':1}, status=status, event_id=f'event-{i}')

    def test_more_than_500_plays_persist_and_migration_is_idempotent(self):
        with TemporaryDirectory() as d:
            p=Path(d)/'history.json'
            write_json(p, [self.row(i) for i in range(500)])
            stats=sync_recent(p)
            self.assertTrue(validate_stats(stats))
            # A following 500-event journal no longer contains the first 10 plays.
            write_json(p, [self.row(i) for i in range(10,510)])
            sync_recent(p);sync_recent(p)
            hits=history_hits(p)
            self.assertEqual(hits[0][2],510)
            self.assertEqual(history_hits(p,period='30')[0][2],sum(i%100 < 30 for i in range(510)))
            self.assertEqual(history_hits(p,period='7')[0][2],sum(i%100 < 7 for i in range(510)))
            with closing(sqlite3.connect(stats)) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM plays').fetchone()[0],510)

    def test_actual_play_completion_updates_stats_but_interrupted_not_counted(self):
        with TemporaryDirectory() as d:
            p=Path(d)/'history.json'
            h=PlayHistory(p)
            h.start(QueueItem(1), {'path':'C:/song.mid','title':'A'})
            h.finish('completed')
            h.start(QueueItem(1), {'path':'C:/song.mid','title':'A'})
            h.finish('interrupted')
            h.start(QueueItem(1), {'path':'C:/song.mid','title':'A'})
            h.finish('medley')
            self.assertEqual(history_hits(p)[0][2],2)

    def test_drive_backup_and_restore_history_stats_as_optional(self):
        with TemporaryDirectory() as d:
            root=Path(d);source=root/'Source';dest=root/'Dest';source.mkdir();dest.mkdir()
            for folder in (source,dest):
                SongLibrary(folder/'songs.sqlite3')
                write_json(folder/'settings.json',{})
                write_json(folder/'queue.json',[])
            write_json(source/'history.json',[self.row(1)])
            sync_recent(source/'history.json')
            snapshot=create_snapshot(source,root/'Drive','user@example.com')
            dbroot=snapshot/'database'
            self.assertTrue((dbroot/'history.json').exists())
            self.assertTrue((dbroot/'play_stats.sqlite3').exists())
            self.assertEqual(validate_snapshot(snapshot)['songs'],0)
            stage_restore(dbroot,dest)
            apply_pending(dest)
            self.assertEqual(history_hits(dest/'history.json')[0][2],1)
            # Legacy backup omitting both optional files still restores.
            (dbroot/'history.json').unlink()
            (dbroot/'play_stats.sqlite3').unlink()
            stage_restore(dbroot,dest)
            apply_pending(dest)

    def test_snapshot_sha256_detects_tampering(self):
        with TemporaryDirectory() as d:
            root=Path(d);source=root/'Source';source.mkdir()
            SongLibrary(source/'songs.sqlite3')
            write_json(source/'settings.json',{})
            write_json(source/'queue.json',[])
            snapshot=create_snapshot(source,root/'Drive','user@example.com')
            self.assertEqual(validate_snapshot(snapshot)['songs'],0)
            with (snapshot/'database'/'queue.json').open('ab') as file:
                file.write(b' ')
            with self.assertRaisesRegex(ValueError,'SHA-256'):
                validate_snapshot(snapshot)

    def test_rollback_after_history_write_restores_previous_files(self):
        with TemporaryDirectory() as d:
            root=Path(d);source=root/'source';dest=root/'dest'
            for folder in (source,dest):
                folder.mkdir();SongLibrary(folder/'songs.sqlite3')
                write_json(folder/'settings.json',{})
                write_json(folder/'queue.json',[])
            write_json(source/'history.json',[self.row(1)])
            write_json(dest/'history.json',[self.row(2)])
            sync_recent(source/'history.json');sync_recent(dest/'history.json')
            stage_restore(source,dest)
            from karaoke import restore
            original=restore.replace_file
            def fail(s,t):
                if t.name=='play_stats.sqlite3':
                    raise OSError('simulated disk error')
                return original(s,t)
            with patch.object(restore,'replace_file',side_effect=fail):
                with self.assertRaises(OSError):
                    apply_pending(dest)
            self.assertEqual(json.loads((dest/'history.json').read_text(encoding='utf-8'))[0]['event_id'],'event-2')
            self.assertEqual(history_hits(dest/'history.json')[0][2],1)

class LargeCatalogSamplingTests(unittest.TestCase):
    def test_large_catalog_is_bounded_and_excludes_current_queue(self):
        with TemporaryDirectory() as d:
            root=Path(d);lib=SongLibrary(root/'catalog.db')
            songfile=root/'playable.mid';songfile.write_bytes(b'MIDI')
            rows=[]
            for i in range(3000):
                rows.append((str(root/f'song{i}.mid'),f'CODE{i}',f'Song {i}',f'Artist {i}','midi', f'Song {i} Artist {i}', 'Rock'))
            # Distinct paths exercise the same unique-path constraint as a real catalog.
            for i in range(3000):
                (root/f'song{i}.mid').write_bytes(b'MIDI')
            with lib.connect() as db:
                db.executemany('INSERT INTO songs(path,code,title,artist,kind,search,rhythm,playable) VALUES (?,?,?,?,?,?,?,1)',rows)
            result=build_preview(lib.path,'library',10,rng=random.Random(8),excluded_ids={1})
            self.assertEqual(result.matched,3000)
            self.assertEqual(len(result.rows),10)
            self.assertNotIn(1,{r.item.song_id for r in result.rows})
            self.assertEqual(len({r.item.song_id for r in result.rows}),10)

if __name__=='__main__':unittest.main()
