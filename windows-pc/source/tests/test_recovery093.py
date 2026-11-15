import sqlite3, tempfile, unittest
from contextlib import closing
from pathlib import Path
from karaoke.path_relocate import preview, apply, remap_path_settings
from karaoke.song_eq import relocate_batch
from karaoke.library import canonical

class Recovery093Tests(unittest.TestCase):
    def test_batch_relocate_updates_only_selected_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); old=root/'old'; new=root/'new'; old.mkdir(); new.mkdir()
            media=old/'MIDI'/'song.mid'; media.parent.mkdir(); media.write_bytes(b'x')
            db=root/'songs.sqlite3'
            with closing(sqlite3.connect(db)) as conn:
                conn.execute('CREATE TABLE songs(id INTEGER PRIMARY KEY,path TEXT,duplicate_state TEXT,source_catalog TEXT)')
                conn.execute('INSERT INTO songs VALUES (1,?,?,?)',(str(media),'',str(old/'SONG.DBF'))); conn.commit()
            cache=root/'songs-index-cache.sqlite3'
            with closing(sqlite3.connect(cache)) as conn:
                conn.execute('CREATE TABLE files(path TEXT PRIMARY KEY,song_id INTEGER,stamp TEXT,size_key TEXT,content_key TEXT,reader TEXT,complete INTEGER)')
                conn.execute('CREATE TABLE catalogs(path TEXT PRIMARY KEY,stamp TEXT)')
                conn.execute('INSERT INTO files VALUES (?,?,?,?,?,?,?)',(str(media),1,'s','z','c','r',1))
                conn.execute('INSERT INTO catalogs VALUES (?,?)',(str(old/'SONG.DBF'),'s'));conn.commit()
            self.assertEqual(len(preview(db,old,new)),1)
            result=apply(db,old,new)
            self.assertEqual(result['updated'],1)
            with closing(sqlite3.connect(db)) as conn:
                self.assertEqual(conn.execute('SELECT path FROM songs').fetchone()[0],canonical(new/'MIDI'/'song.mid'))
                self.assertEqual(conn.execute('SELECT source_catalog FROM songs').fetchone()[0],canonical(new/'SONG.DBF'))
            with closing(sqlite3.connect(cache)) as conn:
                self.assertEqual(conn.execute('SELECT path FROM files').fetchone()[0],canonical(new/'MIDI'/'song.mid'))
                self.assertEqual(conn.execute('SELECT path FROM catalogs').fetchone()[0],canonical(new/'SONG.DBF'))

    def test_path_keyed_settings_are_remapped(self):
        settings={'offsets':{},'lyric_files':{},'song_eq':{}}
        old=canonical(Path('old/song.mid'));new=canonical(Path('new/song.mid'))
        settings['offsets'][old]=12;settings['lyric_files'][old]='old/song.lrc';settings['song_eq'][old]={'bands':[]}
        remap_path_settings(settings,{old:new})
        self.assertEqual(settings['offsets'],{new:12});self.assertIn(new,settings['lyric_files']);self.assertIn(new,settings['song_eq'])

    def test_path_keyed_settings_collision_is_rejected(self):
        old=canonical(Path('old/song.mid'));new=canonical(Path('new/song.mid'))
        settings={'offsets':{old:12,new:3}}
        with self.assertRaises(ValueError):remap_path_settings(settings,{old:new})
        self.assertEqual(settings['offsets'],{old:12,new:3})

    def test_eq_batch_collision_is_atomic(self):
        settings={'song_eq':{'c:\\old.mid':{'bands':[]},'c:\\new.mid':{'bands':[]}}}
        with self.assertRaises(ValueError): relocate_batch(settings, [('c:\\old.mid','c:\\new.mid')])
        self.assertEqual(set(settings['song_eq']), {'c:\\old.mid','c:\\new.mid'})

if __name__=='__main__': unittest.main()
